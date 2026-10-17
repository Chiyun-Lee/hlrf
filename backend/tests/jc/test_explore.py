"""Exploration: hypotheses from the night's results, then round 2 (critique, revise, round-robin ranking)."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from journal_club import prompts
from journal_club.archive import Archive
from journal_club.cards import PaperCard
from journal_club.llm import MockLLM, parse_headers, parse_quotes
from journal_club.minutes import render_minutes
from journal_club.night import run_night
from journal_club.quotes import verify_quote
from journal_club.rounds.explore import _matches, ranked
from journal_club.state import fold
from .conftest import CountingLLM

AGENDA = "where is batch correction going"
FAKE = {"paper_id": "sc01", "text": "This sentence does not appear anywhere in the paper at all.", "loc": "p9"}


def _first(user: str, pid: str) -> dict:
    """The first QUOTE line of paper `pid` in a user prompt."""
    return next(q for q in parse_quotes(user) if q["paper_id"] == pid)


def test_night_explores_and_tags_round_two(cards: list[PaperCard], tmp_archive: Archive) -> None:
    llm = CountingLLM(MockLLM())
    result = run_night(cards, llm, tmp_archive, AGENDA)
    by_id = {c.id: c for c in cards}
    assert result.hypotheses and llm.calls["hypotheses"] == 1
    for r in result.hypotheses:
        h = r.hypothesis
        assert h.quotes and all(verify_quote(by_id[q.paper_id], q.text, q.loc) for q in h.quotes)  # premises verified
        assert h.papers == sorted({q.paper_id for q in h.quotes})
        assert [c.speaker for c in r.critiques] == h.papers[:3]
    alive = [r for r in result.hypotheses if r.decision != "drop"]
    assert llm.calls["compare"] == len(alive) * (len(alive) - 1) // 2
    assert sum(r.wins for r in alive) == llm.calls["compare"] and all(r.played == len(alive) - 1 for r in alive)
    assert result.hypotheses == ranked(result.hypotheses)  # survivors by wins, dropped last
    assert {e.round for e in tmp_archive.by_step("critique")} == {2}
    assert {e.round for e in tmp_archive.by_step("hypotheses")} == {1}


def test_hypotheses_need_a_verified_premise(cards: list[PaperCard], tmp_archive: Archive) -> None:
    def scripted(user: str) -> dict:
        real = {"text": "real", "mechanism": "m", "test": "t", "prediction": "p", "source": "gap", "papers": ["sc02"],
                "quotes": [_first(user, "sc02")]}
        return {"hypotheses": [real | {"text": "invented", "papers": ["sc01"], "quotes": [FAKE]}, real]}

    run_night(cards, MockLLM(scripted={"hypotheses": scripted}), tmp_archive, AGENDA)
    kept = [e.payload for e in tmp_archive.by_step("hypotheses") if e.type == "hypothesis"]
    assert [(h["id"], h["text"]) for h in kept] == [("h1", "real")]  # ids count the kept ones
    assert [e.type for e in tmp_archive.by_step("hypotheses")].count("hypothesis_rejected") == 1


def test_a_critique_quoting_another_paper_carries_no_weight(cards: list[PaperCard], tmp_archive: Archive) -> None:
    def critique(user: str) -> dict:  # every student quotes another paper's card, never its own
        speaker = parse_headers(user)["SPEAKER"]
        other = next(q for q in parse_quotes(user) if q["paper_id"] != speaker)
        return {"stance": "objects", "text": "borrowed", "quotes": [other]}

    seen: list[str] = []

    def revise(user: str) -> dict:
        seen.append(user)
        return MockLLM().default("revise", user, prompts.SCHEMAS["revise"])

    result = run_night(cards, MockLLM(scripted={"critique": critique, "revise": revise}), tmp_archive, AGENDA)
    assert result.hypotheses and all(not c.verified and c.quotes == [] for r in result.hypotheses for c in r.critiques)
    assert all("(unverified, objects)" in u for u in seen)  # the PI is told
    assert any(e.type == "critique_unverified" for e in tmp_archive.by_step("critique"))


def test_revision_keeps_premises_and_dropped_ones_sit_out(cards: list[PaperCard], tmp_archive: Archive) -> None:
    calls = itertools.count()

    def revise(user: str) -> dict:
        h = parse_headers(user)
        decision = ("revise", "drop", "keep")[next(calls) % 3]
        text = "narrower" if decision == "revise" else h["HYPOTHESIS"]
        return {"decision": decision, "text": text, "mechanism": h["MECHANISM"], "test": "a sharper test",
                "prediction": h["PREDICTION"], "reason": decision}

    result = run_night(cards, MockLLM(scripted={"revise": revise}), tmp_archive, AGENDA)
    proposed = {e.payload["id"]: e.payload for e in tmp_archive.by_step("hypotheses") if e.type == "hypothesis"}
    revised = [r for r in result.hypotheses if r.decision == "revise"]
    dropped = [r for r in result.hypotheses if r.decision == "drop"]
    assert revised and dropped
    for r in revised:
        assert r.hypothesis.text == "narrower" and r.original == proposed[r.hypothesis.id]["text"]
        assert [q.model_dump() for q in r.hypothesis.quotes] == proposed[r.hypothesis.id]["quotes"]
    assert all(r.wins == r.played == 0 for r in dropped) and result.hypotheses[-len(dropped):] == dropped
    matches = next(e.payload["matches"] for e in tmp_archive.by_step("critique") if e.type == "ranking")
    dropped_ids = {r.hypothesis.id for r in dropped}
    assert not any({m["a"], m["b"]} & dropped_ids for m in matches)


def test_critique_resumes_hypothesis_by_hypothesis(cards: list[PaperCard], tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("JC_CONCURRENCY", "1")
    seen = itertools.count()

    def flaky(user: str) -> dict:
        if next(seen) == 2:
            raise RuntimeError("network")
        return MockLLM().default("revise", user, prompts.SCHEMAS["revise"])

    path = tmp_path / "events.jsonl"
    with Archive(path) as archive, pytest.raises(RuntimeError):
        run_night(cards, MockLLM(scripted={"revise": flaky}), archive, AGENDA)
    with Archive(path) as archive:
        llm = CountingLLM(MockLLM())
        result = run_night(cards, llm, archive, AGENDA)
    assert llm.calls["revise"] == len(result.hypotheses) - 2  # the two reviewed before the crash are reused
    assert llm.calls["map"] == llm.calls["hypotheses"] == 0


def test_backtest_nights_do_not_explore(cards: list[PaperCard], tmp_archive: Archive) -> None:
    llm = CountingLLM(MockLLM())
    result = run_night(cards, llm, tmp_archive, AGENDA, explore=False)
    assert result.hypotheses == [] and not {"hypotheses", "critique", "revise", "compare"} & set(llm.calls)
    assert [s.name for s in fold(tmp_archive.read()).steps] == ["map", "debate", "directions", "synthesis"]


def test_run_page_and_minutes_show_the_hypotheses(cards: list[PaperCard], tmp_archive: Archive) -> None:
    result = run_night(cards, MockLLM(), tmp_archive, AGENDA)
    events = tmp_archive.read()
    state = fold(events)
    assert [s.name for s in state.steps] == ["map", "debate", "directions", "hypotheses", "critique", "synthesis"]
    assert all(s.status == "done" for s in state.steps)
    assert state.hypotheses == [r.model_dump() for r in result.hypotheses]
    minutes = render_minutes(events, cards)
    assert "## Hypotheses" in minutes and result.hypotheses[0].hypothesis.text in minutes
    # mid-way through round 2, unreviewed hypotheses are listed last, undecided
    cut = next(i for i, e in enumerate(events) if e.type == "review")
    partial = fold(events[: cut + 1])
    assert [h["decision"] is None for h in partial.hypotheses] == [False] + [True] * (len(partial.hypotheses) - 1)
    assert next(s for s in partial.steps if s.name == "critique").status == "running"


def test_old_runs_keep_their_steps(cards: list[PaperCard], tmp_archive: Archive) -> None:
    """A run from before exploration (no flag, no events) shows no hypotheses steps waiting forever."""
    run_night(cards, MockLLM(), tmp_archive, AGENDA, explore=False)
    events = tmp_archive.read()
    for e in events:
        e.payload.pop("explore", None)
    assert "hypotheses" not in [s.name for s in fold(events).steps] and fold(events).hypotheses == []


def test_matches_play_every_pair_once_alternating_sides() -> None:
    items = list("abcd")
    pairs = _matches(items)
    assert sorted(tuple(sorted(p)) for p in pairs) == sorted(itertools.combinations(items, 2))
    firsts = [p[0] for p in pairs]
    assert len(set(firsts)) > 1 and firsts.count("a") < 3  # "a" isn't shown first in all its matches
