"""Minutes and zotero notes rendered from archive events only."""

from __future__ import annotations

from pathlib import Path

import pytest

from journal_club import prompts
from journal_club.archive import Archive, Event
from journal_club.cards import PaperCard, Quote
from journal_club.llm import MockLLM
from journal_club.minutes import cards_from_archive, write_minutes, zotero_notes
from journal_club.quotes import verify_quotes


def _ev(step: str, type_: str, papers: list[str] | None = None, **payload: object) -> Event:
    """Event with seq 0; `payload` holds the event payload fields."""
    return Event(round=1, step=step, type=type_, papers=papers or [], payload=dict(payload), seq=0)


def _pev(step: str, type_: str, papers: list[str], payload: dict) -> Event:
    """Event with seq 0 from a dumped-model payload (which may itself contain `papers`)."""
    return Event(round=1, step=step, type=type_, papers=papers, payload=payload, seq=0)


def _q(card: PaperCard, i: int = 0) -> dict:
    """The i-th stored quote of a card, dumped."""
    return card.quotes()[i].model_dump()


def _direction(text: str, papers: list[str], quotes: list[dict], confidence: float) -> dict:
    """A Direction.model_dump()-shaped payload."""
    return {
        "text": text,
        "from_a": "label-scored benchmarks",
        "to_b": "experimental ground truth",
        "because": "both papers hit the same limitation",
        "papers": sorted(papers),
        "quotes": quotes,
        "confidence": confidence,
    }


def scripted_directions(cards: list[PaperCard]) -> list[dict]:
    """Four directions over the fixture cards: confidences 0.9, 0.7, 0.7, 0.2; one with 3 papers."""
    by_id = {c.id: c for c in cards}
    return [
        _direction("D-low: tissue priors (#4)", ["sc03"], [_q(by_id["sc03"], 3)], 0.2),
        _direction("D-top: spike-in ground truth (#1)", ["sc05", "sc06"], [_q(by_id["sc05"], 3), _q(by_id["sc06"], 3)], 0.9),
        _direction("D-mid-a: linear beats deep (#2)", ["sc02", "sc06"], [_q(by_id["sc02"]), _q(by_id["sc06"])], 0.7),
        _direction(
            "D-mid-b: rare types and anchors (#3)",
            ["sc01", "sc04", "sc03"],
            [_q(by_id["sc01"], 1), _q(by_id["sc04"]), _q(by_id["sc03"], 1)],
            0.7,
        ),
    ]


def _turn(speaker: str, text: str, quotes: list[dict]) -> dict:
    """A Turn.model_dump()-shaped payload."""
    return {"speaker": speaker, "text": text, "quotes": quotes, "verified": bool(quotes)}


def _dispute(a: str, b: str, verdict: str, turns: list[dict], reason: str = "PI reason") -> dict:
    """A Dispute.model_dump()-shaped payload."""
    return {"a": a, "b": b, "claim": f"{a} contradicts {b}", "turns": turns, "verdict": verdict, "judge_reason": reason}


def _sha(cards: list[PaperCard]) -> str:
    """Card-set sha as the rounds define it."""
    import hashlib

    return hashlib.sha256(",".join(sorted(c.id for c in cards)).encode()).hexdigest()


def populate(archive: Archive, cards: list[PaperCard]) -> None:
    """A full night's worth of events, hand-built in DESIGN §6 shapes."""
    by_id = {c.id: c for c in cards}
    archive.append(
        _ev(
            "map", "run_started", agenda="batch correction", model="mock-model", judge_model="mock-judge",
            card_ids_sha=_sha(cards), T=None, cards=[c.model_dump() for c in cards],
        )
    )
    archive.append(_ev("map", "step_started", label=None, reused=0))
    archive.append(_ev("map", "quote_rejected", ["sc01", "sc02"], relation_claimed="agree", failed=[], raw={}))
    archive.append(_ev("map", "step_done", count=28, card_ids_sha=_sha(cards), label=None))
    archive.append(_ev("debate", "step_started", label=None, reused=0))
    archive.append(_ev("debate", "turn_unverified", ["sc01", "sc04"], speaker="sc04", turn=0, dropped=[]))
    archive.append(_ev("debate", "turn_unverified", ["sc02", "sc06"], speaker="sc02", turn=1, dropped=[]))
    d1 = _dispute(
        "sc01", "sc04", "contested",
        [_turn("sc01", "sc01 maintains its claim", [_q(by_id["sc01"], 1)]), _turn("sc04", "sc04 objects", [])],
    )
    d2 = _dispute("sc02", "sc06", "unresolved", [_turn("sc02", "no quote", []), _turn("sc06", "no quote either", [])], "no verified quotes")
    archive.append(_pev("debate", "dispute", ["sc01", "sc04"], d1))
    archive.append(_pev("debate", "dispute", ["sc02", "sc06"], d2))
    archive.append(_ev("debate", "step_done", count=2, card_ids_sha=_sha(cards), label=None))
    archive.append(_ev("directions", "step_started", label=None, reused=0))
    archive.append(_ev("directions", "direction_rejected", ["sc05"], raw={}, failed=[], reason="no verified quote"))
    for d in scripted_directions(cards):
        archive.append(_pev("directions", "direction", d["papers"], d))
    archive.append(_ev("directions", "step_done", count=4, card_ids_sha=_sha(cards), label=None))


def test_directions_ranked_by_confidence_with_quotes(tmp_archive: Archive, cards: list[PaperCard], tmp_path: Path) -> None:
    populate(tmp_archive, cards)
    md = write_minutes(tmp_archive, cards, tmp_path / "minutes.md")
    assert (tmp_path / "minutes.md").read_text(encoding="utf-8") == md
    order = [md.index(t) for t in ("D-top", "D-mid-a", "D-mid-b", "D-low")]
    assert order == sorted(order), "directions must be ranked by confidence, stable for ties"
    assert "1. **D-top: spike-in ground truth (#1)** (confidence 0.90)" in md
    assert "4. **D-low: tissue priors (#4)** (confidence 0.20)" in md
    assert "papers: tan2022groundtruth, brandt2022compute" in md
    assert "> Without an experimental ground truth that separates batch effect from biological signal" in md
    assert "(tan2022groundtruth, p9 §5)" in md
    assert "from label-scored benchmarks to experimental ground truth, because both papers hit the same limitation" in md


def test_disputes_unresolved_and_rejected_sections(tmp_archive: Archive, cards: list[PaperCard], tmp_path: Path) -> None:
    populate(tmp_archive, cards)
    md = write_minutes(tmp_archive, cards, tmp_path / "minutes.md")
    assert "## Disputes" in md and "### kim2019batchalign vs moreno2021overcorrection" in md
    assert "- verdict: **contested**" in md and "- reason: PI reason" in md
    assert "- [sc01] (verified) sc01 maintains its claim" in md
    assert "- [sc04] (unverified) sc04 objects" in md
    unresolved = md.split("## Unresolved")[1].split("## Rejected")[0]
    assert "osei2020deepmerge vs brandt2022compute: sc02 contradicts sc06" in unresolved
    assert "kim2019batchalign" not in unresolved
    rejected = md.split("## Rejected")[1]
    assert "- quote_rejected: 1" in rejected
    assert "- turn_unverified: 2" in rejected
    assert "- direction_rejected: 1" in rejected
    assert "## Backtest" not in md


def test_header_and_written_event(tmp_archive: Archive, cards: list[PaperCard], tmp_path: Path) -> None:
    populate(tmp_archive, cards)
    tmp_archive.append(_ev("map", "agenda_changed", old="batch correction", new="rare cell types"))
    before = tmp_archive.last_seq
    md = write_minutes(tmp_archive, cards, tmp_path / "out" / "minutes.md")
    assert md.startswith("# Minutes")
    assert "- agenda: rare cell types" in md and "- model: mock-model" in md and "- cards: 8" in md
    events = tmp_archive.read()
    assert events[-1].step == "minutes" and events[-1].type == "written" and events[-1].seq == before + 1
    assert events[-1].payload == {"path": str(tmp_path / "out" / "minutes.md"), "n_directions": 4, "n_disputes": 2}
    assert tmp_archive.has_step("minutes") is False, "written is not a step_done marker"


def test_empty_archive_renders_none_sections(tmp_archive: Archive, cards: list[PaperCard], tmp_path: Path) -> None:
    md = write_minutes(tmp_archive, cards, tmp_path / "minutes.md")
    for section in ("## Directions", "## Disputes", "## Unresolved"):
        assert "(none)" in md.split(section)[1].split("## ")[0]
    assert "- quote_rejected: 0" in md


def test_backtest_section_from_report_event(tmp_archive: Archive, cards: list[PaperCard], tmp_path: Path) -> None:
    populate(tmp_archive, cards)
    hit = {"direction_text": "x", "verdict": "hit", "after_paper_id": "sc08", "reason": "r", "label": "club"}
    partial = {**hit, "verdict": "partial", "after_paper_id": "sc07"}
    miss = {**hit, "verdict": "miss", "after_paper_id": None, "label": "baseline"}
    tmp_archive.append(
        _ev(
            "backtest", "report", T="2023-01-01", before_ids=["sc01"], after_ids=["sc07", "sc08"], judge_model="mock-judge",
            club_directions=[], baseline_directions=[], club_hits=[hit, partial, miss], baseline_hits=[miss, miss],
            club_rate=1 / 3, baseline_rate=0.0, club_weighted_rate=0.5, baseline_weighted_rate=0.0,
        )
    )
    tmp_archive.append(_ev("backtest", "step_done", count=1, card_ids_sha=_sha(cards), label=None))
    md = write_minutes(tmp_archive, cards, tmp_path / "minutes.md")
    assert "## Backtest" in md
    assert "Club: 1/3 hits, 1 partial (weighted 0.50). Baseline: 0/2 hits, 0 partial (weighted 0.00). Judge model: mock-judge." in md


def test_zotero_notes_group_three_paper_direction(tmp_archive: Archive, cards: list[PaperCard]) -> None:
    populate(tmp_archive, cards)
    notes = zotero_notes(tmp_archive, cards)
    assert set(notes) == {c.id for c in cards}
    for pid in ("sc01", "sc03", "sc04"):
        assert "D-mid-b: rare types and anchors (#3) (confidence 0.70)" in notes[pid]
    assert "D-mid-b" not in notes["sc02"]
    assert "D-top" in notes["sc05"] and "D-top" in notes["sc06"]
    assert "- vs sc04: contested" in notes["sc01"] and "- vs sc01: contested" in notes["sc04"]
    assert "- vs sc06: unresolved" in notes["sc02"]
    unnamed = notes["sc07"]
    assert unnamed.startswith("# nakamura2023tissue")
    assert unnamed.count("(none)") == 2


def test_zotero_notes_carry_quotes_and_locs(tmp_archive: Archive, cards: list[PaperCard]) -> None:
    populate(tmp_archive, cards)
    notes = zotero_notes(tmp_archive, cards)
    by_id = {c.id: c for c in cards}
    # Directions: every quote of each direction naming the card, as `> text (citekey, loc)`.
    top = by_id["sc05"].quotes()[3]
    assert f"> {top.text} (tan2022groundtruth, {top.loc})" in notes["sc05"]
    assert f"> {top.text} (tan2022groundtruth, {top.loc})" in notes["sc06"], "co-cited quote appears on the partner's note"
    own = by_id["sc01"].quotes()[1]
    assert f"({by_id['sc01'].citekey}, {own.loc})" in notes["sc01"]
    # Disputes: claim, ruling and the verified turn quotes with their locs.
    sc01 = notes["sc01"].split("## Disputes")[1]
    assert "- vs sc04: contested" in sc01
    assert "  - claim: sc01 contradicts sc04" in sc01 and "  - reason: PI reason" in sc01
    assert f"> {own.text} ({by_id['sc01'].citekey}, {own.loc})" in sc01
    sc04 = notes["sc04"].split("## Disputes")[1]
    assert f"({by_id['sc01'].citekey}, {own.loc})" in sc04, "the other side's evidence is on the note too"
    assert "## Disputes" in notes["sc02"] and "- reason: no verified quotes" in notes["sc02"]
    # Unnamed cards still get empty sections and no stray evidence.
    assert notes["sc07"].count("(none)") == 2 and ">" not in notes["sc07"].split("## Directions")[1]


def test_zotero_dispute_note_dedupes_repeated_turn_quotes(tmp_archive: Archive, cards: list[PaperCard]) -> None:
    by_id = {c.id: c for c in cards}
    q = _q(by_id["sc01"])
    turns = [_turn("sc01", "t0", [q]), _turn("sc04", "t0", []), _turn("sc01", "t1", [q]), _turn("sc04", "t1", [])]
    tmp_archive.append(_ev("map", "run_started", agenda="a", model="mock", judge_model="", card_ids_sha=_sha(cards), T=None, cards=[c.model_dump() for c in cards]))
    tmp_archive.append(_ev("debate", "step_started", label=None, reused=0))
    tmp_archive.append(_pev("debate", "dispute", ["sc01", "sc04"], _dispute("sc01", "sc04", "stands", turns)))
    tmp_archive.append(_ev("debate", "step_done", count=1, card_ids_sha=_sha(cards), label=None))
    note = zotero_notes(tmp_archive, cards)["sc01"]
    assert note.count(f"> {q['text']} (kim2019batchalign, {q['loc']})") == 1


def test_cards_from_archive_round_trip(tmp_archive: Archive, cards: list[PaperCard]) -> None:
    with pytest.raises(ValueError):
        cards_from_archive(tmp_archive)
    populate(tmp_archive, cards)
    rebuilt = cards_from_archive(tmp_archive)
    assert rebuilt == cards
    assert [c.id for c in rebuilt] == sorted(c.id for c in cards)


def test_resume_window_uses_latest_completed_step(tmp_archive: Archive, cards: list[PaperCard], tmp_path: Path) -> None:
    populate(tmp_archive, cards)
    by_id = {c.id: c for c in cards}
    tmp_archive.append(_ev("directions", "step_started", label=None, reused=0))
    tmp_archive.append(_pev("directions", "direction", ["sc05"], _direction("D-rerun only", ["sc05"], [_q(by_id["sc05"])], 0.5)))
    tmp_archive.append(_ev("directions", "step_done", count=1, card_ids_sha=_sha(cards), label=None))
    md = write_minutes(tmp_archive, cards, tmp_path / "minutes.md")
    assert "D-rerun only" in md and "D-top" not in md
    assert tmp_archive.read()[-1].payload["n_directions"] == 1


def test_mock_directions_flow_into_minutes(tmp_archive: Archive, cards: list[PaperCard], tmp_path: Path) -> None:
    before = [c for c in cards if c.date < "2023-01-01"]
    by_id = {c.id: c for c in before}
    llm = MockLLM()
    raw = llm.complete_json("baseline", prompts.load_prompt("baseline"), prompts.build_baseline("agenda", 3, before), prompts.SCHEMAS["baseline"])
    tmp_archive.append(_ev("map", "run_started", agenda="agenda", model="mock", judge_model="mock", card_ids_sha=_sha(before), T=None, cards=[c.model_dump() for c in before]))
    tmp_archive.append(_ev("directions", "step_started", label=None, reused=0))
    kept = []
    for d in raw["directions"]:
        ok, failed = verify_quotes(by_id, [Quote.model_validate(q) for q in d["quotes"]])
        assert ok and not failed, "mock quotes are copied from QUOTE lines and must verify"
        payload = {**d, "quotes": [q.model_dump() for q in ok], "papers": sorted({q.paper_id for q in ok})}
        kept.append(payload)
        tmp_archive.append(_pev("directions", "direction", payload["papers"], payload))
    tmp_archive.append(_ev("directions", "step_done", count=len(kept), card_ids_sha=_sha(before), label=None))
    md = write_minutes(tmp_archive, cards_from_archive(tmp_archive), tmp_path / "minutes.md")
    assert len(kept) == 3
    for d in kept:
        assert d["text"] in md
        for q in d["quotes"]:
            assert f"({by_id[q['paper_id']].citekey}, {q['loc']})" in md
    assert "- cards: 6" in md
