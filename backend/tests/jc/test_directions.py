"""Directions round: quote gate, rejection events, ranking, baseline mode, rebuild."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from journal_club import prompts
from journal_club.archive import Archive, Event
from journal_club.cards import PaperCard, Quote
from journal_club.llm import MockLLM
from journal_club.quotes import verify_quotes
from journal_club.rounds.directions import Direction, directions_from_events, run_directions
from .conftest import CountingLLM

# ------------------------------------------------------------- stand-ins


def _map(pairs: list[SimpleNamespace]) -> SimpleNamespace:
    """Stand-in for rounds.map_round.MapResult."""
    return SimpleNamespace(
        pairs=pairs,
        by_relation=lambda r: [p for p in pairs if p.relation == r],
    )


def _shared(a: PaperCard, b: PaperCard, note: str = "same limit") -> SimpleNamespace:
    """Stand-in for a shared_limitation PairVerdict."""
    return SimpleNamespace(
        a=a.id, b=b.id, relation="shared_limitation",
        quote_a=a.limits[0].quote, quote_b=b.limits[0].quote, note=note,
    )


def _agree(a: PaperCard, b: PaperCard) -> SimpleNamespace:
    """Stand-in for an agree PairVerdict (must not reach the prompt)."""
    return SimpleNamespace(
        a=a.id, b=b.id, relation="agree",
        quote_a=a.quotes()[0], quote_b=b.quotes()[0], note="AGREE-NOTE-MARKER",
    )


def _turn(speaker: str, quotes: list[Quote]) -> SimpleNamespace:
    """Stand-in for rounds.debate.Turn."""
    return SimpleNamespace(speaker=speaker, text=f"{speaker} speaks", quotes=quotes, verified=bool(quotes))


def _dispute(a: PaperCard, b: PaperCard, verdict: str, claim: str = "a vs b") -> SimpleNamespace:
    """Stand-in for rounds.debate.Dispute."""
    turns = [_turn(a.id, [a.quotes()[0]]), _turn(b.id, [b.quotes()[0]])]
    return SimpleNamespace(a=a.id, b=b.id, claim=claim, turns=turns, verdict=verdict, judge_reason="r")


def _raw(
    text: str,
    quotes: list[dict[str, str]],
    papers: list[str] | None = None,
    confidence: float = 0.5,
) -> dict[str, Any]:
    """A raw direction dict as the LLM would return it."""
    return {
        "text": text,
        "from_a": "A",
        "to_b": "B",
        "because": "because",
        "papers": papers if papers is not None else sorted({q["paper_id"] for q in quotes}),
        "quotes": quotes,
        "confidence": confidence,
    }


def _q(card: PaperCard, i: int = 0) -> dict[str, str]:
    """A stored quote of a card as a dict."""
    return card.quotes()[i].model_dump()


def _scripted(directions: list[dict], kind: str = "directions") -> MockLLM:
    """A mock that returns fixed directions for `kind`."""
    return MockLLM(scripted={kind: lambda user: {"directions": directions}})


def _events(archive: Archive, step: str, type: str) -> list[Event]:
    """Events of one step and type."""
    return [e for e in archive.by_step(step) if e.type == type]


# ------------------------------------------------------------------ tests


def test_default_mock_all_directions_verify(cards: list[PaperCard], tmp_archive: Archive) -> None:
    before = cards[:6]
    counting = CountingLLM(MockLLM())
    mr = _map([_shared(cards[4], cards[5]), _agree(cards[0], cards[1])])
    disputes = [_dispute(cards[0], cards[3], "contested"), _dispute(cards[1], cards[5], "stands")]
    out = run_directions(mr, disputes, before, counting, tmp_archive, n=8, agenda="agenda")
    assert counting.calls == {"directions": 1}
    assert len(out) == 8
    by_id = {c.id: c for c in before}
    for d in out:
        assert d.quotes
        ok, failed = verify_quotes(by_id, d.quotes)
        assert failed == [] and ok == d.quotes
        assert d.papers == sorted(set(d.papers)) and set(d.papers) <= set(by_id)
        assert 0.0 <= d.confidence <= 1.0
    types = [e.type for e in tmp_archive.by_step("directions")]
    assert types[0] == "step_started" and types[-1] == "step_done"
    assert types.count("direction") == 8 and "direction_rejected" not in types
    done = tmp_archive.by_step("directions")[-1].payload
    assert done["count"] == 8 and len(done["card_ids_sha"]) == 64 and done["label"] is None
    started = tmp_archive.by_step("directions")[0].payload
    assert started == {"label": None, "reused": 0}


def test_prompt_contains_only_live_disputes_and_shared_pairs(cards: list[PaperCard], tmp_archive: Archive) -> None:
    mock = MockLLM()
    mr = _map([_shared(cards[4], cards[5], note="SHARED-NOTE-MARKER"), _agree(cards[0], cards[1])])
    disputes = [
        _dispute(cards[0], cards[3], "contested", claim="CONTESTED-CLAIM"),
        _dispute(cards[1], cards[5], "unresolved", claim="UNRESOLVED-CLAIM"),
        _dispute(cards[2], cards[4], "stands", claim="STANDS-CLAIM"),
    ]
    run_directions(mr, disputes, cards[:6], mock, tmp_archive, n=3, agenda="the agenda")
    kind, user = mock.calls[0]
    assert kind == "directions"
    assert user.startswith("AGENDA: the agenda\nN: 3\n")
    assert "CONTESTED-CLAIM" in user and "UNRESOLVED-CLAIM" in user
    assert "STANDS-CLAIM" not in user
    assert "SHARED-NOTE-MARKER" in user and "AGREE-NOTE-MARKER" not in user
    assert "DISPUTES:" in user and "SHARED_LIMITATIONS:" in user


def test_rejection_path_logs_direction_rejected(cards: list[PaperCard], tmp_archive: Archive) -> None:
    bad = {"paper_id": "sc01", "text": "this sentence appears in no paper at all", "loc": "p1"}
    good = _q(cards[1])
    mock = _scripted([_raw("rejected one", [bad], papers=["sc01"]), _raw("kept one", [good])])
    out = run_directions(_map([]), [], cards[:6], mock, tmp_archive)
    assert [d.text for d in out] == ["kept one"]
    rejected = _events(tmp_archive, "directions", "direction_rejected")
    assert len(rejected) == 1
    ev = rejected[0]
    assert ev.papers == ["sc01"]
    assert ev.payload["reason"] == "no verified quote"
    assert ev.payload["failed"] == [bad]
    assert ev.payload["raw"]["text"] == "rejected one"
    kept = _events(tmp_archive, "directions", "direction")
    assert len(kept) == 1 and kept[0].payload["text"] == "kept one"
    assert _events(tmp_archive, "directions", "step_done")[0].payload["count"] == 1


def test_quote_from_wrong_paper_fails(cards: list[PaperCard], tmp_archive: Archive) -> None:
    wrong = dict(_q(cards[0]), paper_id="sc02")  # sc01's words attributed to sc02
    mock = _scripted([_raw("mislabelled", [wrong])])
    out = run_directions(_map([]), [], cards[:6], mock, tmp_archive)
    assert out == []
    assert len(_events(tmp_archive, "directions", "direction_rejected")) == 1


def test_mixed_quotes_keep_only_verified(cards: list[PaperCard], tmp_archive: Archive) -> None:
    good = _q(cards[2])
    bad = {"paper_id": "sc04", "text": "a paraphrase that was never written down anywhere", "loc": "p9"}
    mock = _scripted([_raw("half good", [good, bad], papers=["sc04", "sc03"])])
    out = run_directions(_map([]), [], cards[:6], mock, tmp_archive)
    assert len(out) == 1
    assert [q.model_dump() for q in out[0].quotes] == [good]
    assert out[0].papers == ["sc03"], "sc04 has no verified quote, so the direction is not attributed to it"
    ev = _events(tmp_archive, "directions", "direction")[0]
    assert ev.payload["quotes"] == [good] and ev.papers == ["sc03"]


def test_papers_sorted_deduped_and_only_from_verified_quotes(cards: list[PaperCard], tmp_archive: Archive) -> None:
    quotes = [_q(cards[5]), _q(cards[1]), _q(cards[5], 1)]
    mock = _scripted([_raw("p", quotes, papers=["sc06", "sc99", "sc02", "sc02", "sc04"])])
    out = run_directions(_map([]), [], cards[:6], mock, tmp_archive)
    assert out[0].papers == ["sc02", "sc06"]


def test_rejected_direction_event_keeps_the_named_papers(cards: list[PaperCard], tmp_archive: Archive) -> None:
    bad = {"paper_id": "sc01", "text": "this sentence appears in no paper at all, whatever the loc", "loc": "p1"}
    mock = _scripted([_raw("nothing verifies", [bad], papers=["sc01", "sc02", "sc99"])])
    assert run_directions(_map([]), [], cards[:6], mock, tmp_archive) == []
    ev = _events(tmp_archive, "directions", "direction_rejected")[0]
    assert ev.papers == ["sc01", "sc02"]


def test_verbatim_text_with_fabricated_loc_is_rejected(cards: list[PaperCard], tmp_archive: Archive) -> None:
    faked = dict(_q(cards[0]), loc="p42 Table 9 (fabricated)")
    mock = _scripted([_raw("Fake-loc direction", [faked])])
    out = run_directions(_map([]), [], cards[:6], mock, tmp_archive)
    assert out == []
    [ev] = _events(tmp_archive, "directions", "direction_rejected")
    assert ev.payload["failed"] == [faked]
    assert _events(tmp_archive, "directions", "direction") == []


def test_verbatim_text_with_true_loc_survives(cards: list[PaperCard], tmp_archive: Archive) -> None:
    real = _q(cards[0])
    mock = _scripted([_raw("Real-loc direction", [real, dict(real, loc="p42 (fabricated)")])])
    [d] = run_directions(_map([]), [], cards[:6], mock, tmp_archive)
    assert [q.model_dump() for q in d.quotes] == [real]
    assert d.quotes[0].loc == cards[0].quotes()[0].loc


def test_confidence_clamped_never_rejected(cards: list[PaperCard], tmp_archive: Archive) -> None:
    mock = _scripted(
        [
            _raw("too high", [_q(cards[0])], confidence=1.7),
            _raw("too low", [_q(cards[1])], confidence=-0.4),
            _raw("int", [_q(cards[2])], confidence=1),
        ]
    )
    out = run_directions(_map([]), [], cards[:6], mock, tmp_archive)
    by_text = {d.text: d.confidence for d in out}
    assert by_text == {"too high": 1.0, "too low": 0.0, "int": 1.0}
    assert Direction.model_validate(dict(_raw("x", [_q(cards[0])]), confidence="0.25")).confidence == 0.25


def test_sorted_by_confidence_desc_stable(cards: list[PaperCard], tmp_archive: Archive) -> None:
    mock = _scripted(
        [
            _raw("low", [_q(cards[0])], confidence=0.2),
            _raw("high", [_q(cards[1])], confidence=0.9),
            _raw("mid-a", [_q(cards[2])], confidence=0.7),
            _raw("mid-b", [_q(cards[3])], confidence=0.7),
        ]
    )
    out = run_directions(_map([]), [], cards[:6], mock, tmp_archive)
    assert [d.text for d in out] == ["high", "mid-a", "mid-b", "low"]
    # archive order is LLM order; ranking happens on the returned list and in the rebuild
    assert [e.payload["text"] for e in _events(tmp_archive, "directions", "direction")] == ["low", "high", "mid-a", "mid-b"]
    assert [d.text for d in directions_from_events(tmp_archive)] == ["high", "mid-a", "mid-b", "low"]


def test_baseline_mode_uses_baseline_step_kind_and_prompt(cards: list[PaperCard], tmp_archive: Archive) -> None:
    mock = MockLLM()
    mr = _map([_shared(cards[4], cards[5], note="SHARED-NOTE-MARKER")])
    disputes = [_dispute(cards[0], cards[3], "contested", claim="CONTESTED-CLAIM")]
    out = run_directions(mr, disputes, cards[:6], mock, tmp_archive, n=10, agenda="ag", step="baseline", kind="baseline")
    assert len(out) == 10
    kind, user = mock.calls[0]
    assert kind == "baseline"
    assert user == prompts.build_baseline("ag", 10, cards[:6])
    assert "DISPUTES:" not in user and "CONTESTED-CLAIM" not in user and "SHARED-NOTE-MARKER" not in user
    assert tmp_archive.by_step("directions") == []
    types = [e.type for e in tmp_archive.by_step("baseline")]
    assert types[0] == "step_started" and types.count("direction") == 10 and types[-1] == "step_done"
    assert tmp_archive.has_step("baseline") and not tmp_archive.has_step("directions")
    assert [d.text for d in directions_from_events(tmp_archive, "baseline")] == [d.text for d in out]
    assert directions_from_events(tmp_archive, "directions") == []


def test_returns_fewer_when_llm_returns_fewer(cards: list[PaperCard], tmp_archive: Archive) -> None:
    mock = _scripted([])
    out = run_directions(_map([]), [], cards[:6], mock, tmp_archive, n=8)
    assert out == []
    assert _events(tmp_archive, "directions", "step_done")[0].payload["count"] == 0
    assert tmp_archive.has_step("directions")


def test_rebuild_matches_run_and_reads_latest_window(cards: list[PaperCard], tmp_archive: Archive) -> None:
    first = run_directions(_map([]), [], cards[:6], _scripted([_raw("one", [_q(cards[0])], confidence=0.4)]), tmp_archive)
    assert directions_from_events(tmp_archive) == first
    # a second complete run on the same archive: only its window is read back
    second = run_directions(_map([]), [], cards[:6], _scripted([_raw("two", [_q(cards[1])], confidence=0.6)]), tmp_archive)
    assert [d.text for d in directions_from_events(tmp_archive)] == ["two"] and second[0].text == "two"
    assert first[0].model_dump() == tmp_archive.by_step("directions")[1].payload


def test_rebuild_partial_step_reads_everything(cards: list[PaperCard], tmp_archive: Archive) -> None:
    run_directions(_map([]), [], cards[:6], _scripted([_raw("done-run", [_q(cards[0])], confidence=0.3)]), tmp_archive)
    # simulate a crash after step_started and one direction, before step_done
    tmp_archive.append(Event(round=1, step="directions", type="step_started", papers=[], payload={"label": None, "reused": 0}, seq=0))
    partial = Direction(text="partial", from_a="a", to_b="b", because="c", papers=["sc02"], quotes=[cards[1].quotes()[0]], confidence=0.8)
    tmp_archive.append(Event(round=1, step="directions", type="direction", papers=partial.papers, payload=partial.model_dump(), seq=0))
    assert [d.text for d in directions_from_events(tmp_archive)] == ["partial", "done-run"]
