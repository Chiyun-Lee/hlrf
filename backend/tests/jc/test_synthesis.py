"""Synthesis round: overview + quote-gated key points, resume, and the minutes sections it feeds."""

from __future__ import annotations

from pathlib import Path

from journal_club.archive import Archive
from journal_club.cards import load_cards
from journal_club.llm import MockLLM
from journal_club.minutes import render_minutes
from journal_club.night import run_night
from journal_club.quotes import verify_quote
from journal_club.rounds.synthesis import synthesis_from_events

FIXTURES = Path(__file__).parent / "fixtures" / "cards"
AGENDA = "where is batch correction going"


def _night(tmp_path: Path, llm: MockLLM):
    cards = load_cards(FIXTURES)
    archive = Archive(tmp_path / "events.jsonl")
    return cards, archive, run_night(cards, llm, archive, AGENDA)


def test_synthesis_is_quote_gated_and_ordered(tmp_path: Path) -> None:
    cards, archive, result = _night(tmp_path, MockLLM())
    by_id = {c.id: c for c in cards}
    syn = result.synthesis
    assert syn is not None and syn.overview
    assert 1 <= len(syn.key_points) <= 8
    kinds = [k.kind for k in syn.key_points]
    assert kinds == sorted(kinds, key=["consensus", "dissent", "gap", "direction"].index)
    for k in syn.key_points:
        assert k.quotes and all(verify_quote(by_id[q.paper_id], q.text) for q in k.quotes)
    types = [e.type for e in archive.by_step("synthesis")]
    assert types[0] == "step_started" and types[-1] == "step_done" and "synthesis" in types


def test_unverified_key_points_are_rejected(tmp_path: Path) -> None:
    def scripted(user: str) -> dict:
        return {
            "overview": "An overview.",
            "key_points": [
                {"kind": "gap", "text": "Fabricated.", "quotes": [{"paper_id": "sc01", "text": "This sentence does not appear anywhere in the paper at all.", "loc": "p9"}]},
            ],
        }

    cards, archive, result = _night(tmp_path, MockLLM(scripted={"synthesis": scripted}))
    assert result.synthesis is not None and result.synthesis.key_points == []
    assert any(e.type == "keypoint_rejected" for e in archive.by_step("synthesis"))


def test_rerun_resumes_synthesis_without_calls(tmp_path: Path) -> None:
    cards, archive, first = _night(tmp_path, MockLLM())
    second_llm = MockLLM()
    second = run_night(cards, second_llm, archive, AGENDA)
    assert second_llm.calls == []
    assert second.synthesis == first.synthesis == synthesis_from_events(archive)


def test_minutes_have_overview_consensus_and_shared_sections(tmp_path: Path) -> None:
    cards, archive, result = _night(tmp_path, MockLLM())
    md = render_minutes(archive.read(), cards)
    head = md.index("## Overview")
    assert head < md.index("## Consensus") < md.index("## Shared limitations") < md.index("## Directions")
    assert result.synthesis is not None and result.synthesis.overview[:40] in md
    assert "- **Agreed:**" in md or "- **Disputed:**" in md
    n_agree = sum(1 for p in result.map.pairs if p.relation == "agree")
    consensus = md[md.index("## Consensus") : md.index("## Shared limitations")]
    assert consensus.count("\n- ") == n_agree
