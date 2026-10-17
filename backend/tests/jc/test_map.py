"""Map round: 28 calls, quote gate, wrong-paper quotes, partial and full resume, rebuild."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from journal_club import prompts
from journal_club.archive import Archive, Event
from journal_club.cards import PaperCard
from journal_club.llm import LLMError, MockLLM, parse_headers, parse_quotes
from journal_club.quotes import verify_quotes
from journal_club.rounds.map_round import (
    DOWNGRADE_NOTE,
    RELATIONS,
    MapResult,
    PairVerdict,
    all_pairs,
    card_ids_sha,
    cards_by_id,
    map_from_events,
    pair_key,
    run_map,
    run_parallel,
    verdict_from_raw,
)

N_PAIRS = 28


def _pair(user: str) -> tuple[str, str]:
    """The PAIR header of a map prompt."""
    a, b = (s.strip() for s in parse_headers(user)["PAIR"].split("|"))
    return a, b


def _first_quote(user: str, pid: str) -> dict[str, str]:
    """First QUOTE line of one paper in the prompt."""
    return next(q for q in parse_quotes(user) if q["paper_id"] == pid)


def _scripted(override: Callable[[str, tuple[str, str]], dict | None]) -> MockLLM:
    """A mock whose `map` output comes from `override`, else the default rule."""
    mock = MockLLM()

    def fn(user: str) -> dict:
        out = override(user, _pair(user))
        return out if out is not None else mock.default("map", user, prompts.SCHEMAS["map"])

    mock.scripted["map"] = fn
    return mock


def _events(archive: Archive, type: str) -> list[Event]:
    """Map-step events of one type."""
    return [e for e in archive.by_step("map") if e.type == type]


# ------------------------------------------------------------------- helpers


def test_helpers(cards: list[PaperCard]) -> None:
    assert pair_key("b", "a") == ("a", "b") and pair_key("a", "b") == ("a", "b")
    assert set(cards_by_id(cards)) == {c.id for c in cards}
    pairs = all_pairs(cards)
    assert len(pairs) == N_PAIRS and pairs == sorted(pairs) and all(a < b for a, b in pairs)
    assert card_ids_sha(cards) == card_ids_sha(list(reversed(cards)))
    assert card_ids_sha(cards[:7]) != card_ids_sha(cards)


def test_pair_verdict_requires_order(cards: list[PaperCard]) -> None:
    qa, qb = cards[0].quotes()[0], cards[1].quotes()[0]
    PairVerdict(a="sc01", b="sc02", relation="agree", quote_a=qa, quote_b=qb, note="n")
    with pytest.raises(ValueError):
        PairVerdict(a="sc02", b="sc01", relation="agree", quote_a=qb, quote_b=qa, note="n")


def test_run_parallel_order_and_prefix_on_crash() -> None:
    seen: list[list[int]] = []

    def fn(i: int) -> int:
        if i == 9:
            raise RuntimeError("boom")
        return i * 10

    out = run_parallel(fn, list(range(8)), 3, seen.append)
    assert out == [i * 10 for i in range(8)]
    assert seen == [[0, 10, 20], [30, 40, 50], [60, 70]]
    seen.clear()
    with pytest.raises(RuntimeError, match="boom"):
        run_parallel(fn, list(range(12)), 4, seen.append)
    assert seen == [[0, 10, 20, 30], [40, 50, 60, 70], [80]]


# ----------------------------------------------------------------- full run


def test_run_map_28_calls_and_events(cards: list[PaperCard], tmp_archive: Archive) -> None:
    mock = MockLLM()
    result = run_map(cards, mock, tmp_archive, agenda="batch correction")
    assert [k for k, _ in mock.calls] == ["map"] * N_PAIRS
    assert all("AGENDA: batch correction" in u for _, u in mock.calls)
    assert [p.key for p in result.pairs] == all_pairs(cards)
    assert all(p.relation in RELATIONS for p in result.pairs)
    assert len(_events(tmp_archive, "pair_verdict")) == N_PAIRS
    assert _events(tmp_archive, "quote_rejected") == []
    started = _events(tmp_archive, "step_started")
    assert len(started) == 1 and started[0].payload == {"label": None, "reused": 0}
    done = _events(tmp_archive, "step_done")
    assert len(done) == 1 and done[0].payload == {"count": N_PAIRS, "card_ids_sha": card_ids_sha(cards), "label": None}
    assert tmp_archive.has_step("map")
    by_id = cards_by_id(cards)
    for p in result.pairs:
        assert verify_quotes(by_id, [p.quote_a], require_paper=p.a)[1] == []
        assert verify_quotes(by_id, [p.quote_b], require_paper=p.b)[1] == []
    for e in _events(tmp_archive, "pair_verdict"):
        v = PairVerdict.model_validate(e.payload)
        assert e.papers == [v.a, v.b]


def test_relation_helpers(cards: list[PaperCard], tmp_archive: Archive) -> None:
    forced = {("sc01", "sc04"): "disagree", ("sc02", "sc06"): "disagree", ("sc05", "sc06"): "shared_limitation", ("sc03", "sc07"): "shared_limitation"}

    def override(user: str, pair: tuple[str, str]) -> dict | None:
        rel = forced.get(pair, "agree")
        return {"relation": rel, "quote_a": _first_quote(user, pair[0]), "quote_b": _first_quote(user, pair[1]), "note": f"forced {rel}"}

    result = run_map(cards, _scripted(override), tmp_archive)
    assert [p.key for p in result.disagreements()] == [("sc01", "sc04"), ("sc02", "sc06")]
    assert [p.key for p in result.shared_limitations()] == [("sc03", "sc07"), ("sc05", "sc06")]
    assert result.disagreements() == result.by_relation("disagree")
    assert len(result.by_relation("agree")) == N_PAIRS - 4
    assert result.get("sc04", "sc01") is not None and result.get("sc04", "sc01").relation == "disagree"
    assert result.get("sc01", "sc99") is None


# ---------------------------------------------------------------- quote gate


def test_bad_quote_downgrades_and_logs(cards: list[PaperCard], tmp_archive: Archive) -> None:
    def override(user: str, pair: tuple[str, str]) -> dict | None:
        if pair != ("sc01", "sc04"):
            return None
        return {
            "relation": "disagree",
            "quote_a": {"paper_id": "sc01", "text": "This sentence was never written by paper sc01.", "loc": "p1"},
            "quote_b": _first_quote(user, "sc04"),
            "note": "fabricated",
        }

    result = run_map(cards, _scripted(override), tmp_archive)
    v = result.get("sc01", "sc04")
    assert v is not None and v.relation == "unrelated" and v.note == DOWNGRADE_NOTE
    assert v.quote_a.text.startswith("This sentence was never") and v.quote_b.paper_id == "sc04"
    assert v not in result.disagreements()
    rejected = _events(tmp_archive, "quote_rejected")
    assert len(rejected) == 1
    e = rejected[0]
    assert e.papers == ["sc01", "sc04"]
    assert e.payload["relation_claimed"] == "disagree"
    assert [q["text"] for q in e.payload["failed"]] == ["This sentence was never written by paper sc01."]
    assert e.payload["raw"]["note"] == "fabricated"
    stored = next(x for x in _events(tmp_archive, "pair_verdict") if x.papers == ["sc01", "sc04"])
    assert stored.payload == v.model_dump() and stored.seq > e.seq
    assert len(_events(tmp_archive, "pair_verdict")) == N_PAIRS


def test_verbatim_quote_with_fabricated_loc_downgrades(cards: list[PaperCard], tmp_archive: Archive) -> None:
    def override(user: str, pair: tuple[str, str]) -> dict | None:
        if pair != ("sc01", "sc04"):
            return None
        return {
            "relation": "disagree",
            "quote_a": dict(_first_quote(user, "sc01"), loc="p99 §FAKE"),
            "quote_b": _first_quote(user, "sc04"),
            "note": "verbatim text, invented location",
        }

    result = run_map(cards, _scripted(override), tmp_archive)
    v = result.get("sc01", "sc04")
    assert v is not None and v.relation == "unrelated" and v.note == DOWNGRADE_NOTE
    assert v not in result.disagreements()
    [e] = _events(tmp_archive, "quote_rejected")
    assert e.papers == ["sc01", "sc04"] and e.payload["relation_claimed"] == "disagree"
    assert [q["loc"] for q in e.payload["failed"]] == ["p99 §FAKE"]
    assert len(_events(tmp_archive, "pair_verdict")) == N_PAIRS


def test_quote_from_wrong_paper_fails(cards: list[PaperCard], tmp_archive: Archive) -> None:
    def override(user: str, pair: tuple[str, str]) -> dict | None:
        if pair != ("sc02", "sc06"):
            return None
        qb = _first_quote(user, "sc06")
        return {"relation": "disagree", "quote_a": qb, "quote_b": dict(qb), "note": "both from b"}

    result = run_map(cards, _scripted(override), tmp_archive)
    v = result.get("sc02", "sc06")
    assert v is not None and v.relation == "unrelated" and v.note == DOWNGRADE_NOTE
    rejected = _events(tmp_archive, "quote_rejected")
    assert len(rejected) == 1 and rejected[0].papers == ["sc02", "sc06"]
    assert [q["paper_id"] for q in rejected[0].payload["failed"]] == ["sc06"]


def test_quote_text_from_wrong_paper_with_right_id_fails(cards: list[PaperCard], tmp_archive: Archive) -> None:
    def override(user: str, pair: tuple[str, str]) -> dict | None:
        if pair != ("sc02", "sc06"):
            return None
        stolen = dict(_first_quote(user, "sc06"))
        stolen["paper_id"] = "sc02"
        return {"relation": "disagree", "quote_a": stolen, "quote_b": _first_quote(user, "sc06"), "note": "relabelled"}

    result = run_map(cards, _scripted(override), tmp_archive)
    assert result.get("sc02", "sc06").relation == "unrelated"
    assert len(_events(tmp_archive, "quote_rejected")) == 1


def test_malformed_quote_and_illegal_relation_do_not_crash(cards: list[PaperCard]) -> None:
    by_id = cards_by_id(cards)
    good_b = cards[3].quotes()[0].model_dump()
    raw = {"relation": "disagree", "quote_a": {"paper_id": "sc01", "text": "x", "loc": "bad]loc"}, "quote_b": good_b, "note": "n"}
    verdict, failed = verdict_from_raw("sc01", "sc04", raw, by_id)
    assert verdict.relation == "unrelated" and verdict.note == DOWNGRADE_NOTE
    assert verdict.quote_a.text == "no quote available" and failed == [verdict.quote_a]
    raw = {"relation": "sideways", "quote_a": cards[0].quotes()[0].model_dump(), "quote_b": good_b, "note": "n"}
    verdict, failed = verdict_from_raw("sc01", "sc04", raw, by_id)
    assert failed == [] and verdict.relation == "unrelated" and verdict.note == "n"


# -------------------------------------------------------------------- resume


def test_partial_resume_after_crash(cards: list[PaperCard], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JC_CONCURRENCY", "1")
    mock = MockLLM()
    n = {"calls": 0}

    def crash_on_10(user: str) -> dict:
        n["calls"] += 1
        if n["calls"] == 10:
            raise LLMError("map: simulated crash")
        return mock.default("map", user, prompts.SCHEMAS["map"])

    mock.scripted["map"] = crash_on_10
    with Archive(tmp_path / "events.jsonl") as archive:
        with pytest.raises(LLMError, match="simulated crash"):
            run_map(cards, mock, archive)
        assert len(_events(archive, "pair_verdict")) == 9
        assert not archive.has_step("map")
        assert len(mock.calls) == 10
    mock.scripted.pop("map")
    with Archive(tmp_path / "events.jsonl") as archive:
        result = run_map(cards, mock, archive)
        assert len(mock.calls) == 10 + 19
        assert len(result.pairs) == N_PAIRS and [p.key for p in result.pairs] == all_pairs(cards)
        assert len(_events(archive, "pair_verdict")) == N_PAIRS
        assert len(map_from_events(archive)) == N_PAIRS
        started = _events(archive, "step_started")
        assert [e.payload["reused"] for e in started] == [0, 9]
        assert archive.has_step("map")
        rerun_pairs = {_pair(u) for _, u in mock.calls[10:]}
        assert rerun_pairs == set(all_pairs(cards)[9:])


def test_full_resume_makes_zero_calls(cards: list[PaperCard], tmp_archive: Archive) -> None:
    mock = MockLLM()
    first = run_map(cards, mock, tmp_archive)
    assert len(mock.calls) == N_PAIRS
    second = run_map(cards, mock, tmp_archive)
    assert len(mock.calls) == N_PAIRS
    assert second == first
    assert [e.payload["reused"] for e in _events(tmp_archive, "step_started")] == [0, N_PAIRS]
    assert len(_events(tmp_archive, "pair_verdict")) == N_PAIRS


def test_from_events_rebuild_and_last_wins(cards: list[PaperCard], tmp_archive: Archive) -> None:
    result = run_map(cards, MockLLM(), tmp_archive)
    assert MapResult.from_events(tmp_archive) == result
    v = result.get("sc01", "sc02")
    assert v is not None
    changed = v.model_copy(update={"relation": "shared_limitation", "note": "later"})
    tmp_archive.append(Event(round=1, step="map", type="pair_verdict", papers=["sc01", "sc02"], payload=changed.model_dump(), seq=0))
    rebuilt = map_from_events(tmp_archive)
    assert len(rebuilt) == N_PAIRS and rebuilt[("sc01", "sc02")] == changed
    assert MapResult.from_events(tmp_archive).get("sc01", "sc02") == changed
    assert map_from_events(Archive(tmp_archive.path.with_name("empty.jsonl"))) == {}


def test_from_events_skips_malformed_payload(tmp_archive: Archive) -> None:
    tmp_archive.append(Event(round=1, step="map", type="pair_verdict", papers=["x", "y"], payload={"junk": True}, seq=0))
    tmp_archive.append(Event(round=1, step="map", type="quote_rejected", papers=["x", "y"], payload={}, seq=0))
    assert map_from_events(tmp_archive) == {}
