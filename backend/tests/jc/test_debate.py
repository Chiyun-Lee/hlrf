"""Debate round: cap, call budget, quote gate, verdicts, claim text, resume."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from journal_club.archive import Archive
from journal_club.cards import PaperCard, Quote
from journal_club.llm import MockLLM, parse_headers, parse_quotes
from journal_club.rounds.debate import (
    DOWNGRADE_NOTE,
    NO_QUOTES_REASON,
    Dispute,
    Turn,
    build_claim,
    disputes_from_events,
    run_debate,
)
from .conftest import CountingLLM

LEGAL = {"stands", "contested", "unresolved"}


@dataclass
class FakePairVerdict:
    """Stand-in for rounds.map_round.PairVerdict (same fields)."""

    a: str
    b: str
    relation: str
    quote_a: Quote
    quote_b: Quote
    note: str


@dataclass
class FakeMapResult:
    """Stand-in for rounds.map_round.MapResult."""

    pairs: list[FakePairVerdict] = field(default_factory=list)

    def by_relation(self, r: str) -> list[FakePairVerdict]:
        """Pairs with the given relation, in pair order."""
        return [p for p in self.pairs if p.relation == r]


def _pv(a: PaperCard, b: PaperCard, relation: str = "disagree", note: str | None = None) -> FakePairVerdict:
    """A verdict using each card's first stored quote."""
    return FakePairVerdict(
        a=a.id,
        b=b.id,
        relation=relation,
        quote_a=a.quotes()[0],
        quote_b=b.quotes()[0],
        note=note if note is not None else f"{a.id} and {b.id} differ on rare cell types",
    )


def _map(cards: list[PaperCard], pairs: list[tuple[int, int]], relation: str = "disagree") -> FakeMapResult:
    """MapResult stand-in with the given index pairs."""
    return FakeMapResult(pairs=[_pv(cards[i], cards[j], relation) for i, j in pairs])


SEVEN = [(0, 3), (1, 5), (0, 1), (2, 4), (3, 6), (4, 7), (5, 6)]


def _events(archive: Archive, type: str) -> list:
    """Debate events of one type."""
    return [e for e in archive.by_step("debate") if e.type == type]


# ------------------------------------------------------------------- budget


def test_cap_limits_disputes_and_calls(cards: list[PaperCard], tmp_archive: Archive) -> None:
    llm = CountingLLM(MockLLM())
    disputes = run_debate(_map(cards, SEVEN), cards, llm, tmp_archive, cap=5, turns=2)
    assert len(disputes) == 5
    assert [(d.a, d.b) for d in disputes] == [(cards[i].id, cards[j].id) for i, j in SEVEN[:5]]
    assert llm.calls["debate_turn"] == 5 * 4
    assert llm.calls["debate_verdict"] == 5
    assert llm.total == 25
    assert len(_events(tmp_archive, "dispute")) == 5
    assert tmp_archive.has_step("debate")


@pytest.mark.parametrize("turns", [1, 2, 3])
def test_calls_per_dispute_is_two_turns_plus_one(cards: list[PaperCard], tmp_archive: Archive, turns: int) -> None:
    llm = CountingLLM(MockLLM())
    disputes = run_debate(_map(cards, [(0, 3), (1, 5)]), cards, llm, tmp_archive, turns=turns)
    assert llm.total == 2 * (2 * turns + 1)
    for d in disputes:
        assert len(d.turns) == 2 * turns
        assert [t.speaker for t in d.turns] == [d.a, d.b] * turns
        assert d.verdict in LEGAL
        assert all(t.verified == bool(t.quotes) for t in d.turns)
        assert all(q.paper_id == t.speaker for t in d.turns for q in t.quotes)


def test_no_disagree_pairs_makes_no_calls(cards: list[PaperCard], tmp_archive: Archive) -> None:
    llm = CountingLLM(MockLLM())
    disputes = run_debate(_map(cards, [(0, 3)], relation="agree"), cards, llm, tmp_archive)
    assert disputes == []
    assert llm.total == 0
    assert tmp_archive.has_step("debate")
    done = _events(tmp_archive, "step_done")[0]
    assert done.payload["count"] == 0


# --------------------------------------------------------------- quote gate


def test_unverified_turn_logs_event_and_verdict_still_called(cards: list[PaperCard], tmp_archive: Archive) -> None:
    def wrong_paper(user: str) -> dict:
        h = parse_headers(user)
        other = [q for q in parse_quotes(user) if q["paper_id"] != h["SPEAKER"]]
        own = [q for q in parse_quotes(user) if q["paper_id"] == h["SPEAKER"]]
        # sc01 cites the other paper's quote (fails); sc04 cites its own (verifies).
        picked = other[:1] if h["SPEAKER"] == "sc01" else own[:1]
        return {"text": f"{h['SPEAKER']} speaks", "quotes": picked}

    llm = CountingLLM(MockLLM(scripted={"debate_turn": wrong_paper}))
    [d] = run_debate(_map(cards, [(0, 3)]), cards, llm, tmp_archive, turns=2)
    a_turns = [t for t in d.turns if t.speaker == "sc01"]
    b_turns = [t for t in d.turns if t.speaker == "sc04"]
    assert all(not t.verified and t.quotes == [] for t in a_turns)
    assert all(t.verified and t.quotes[0].paper_id == "sc04" for t in b_turns)
    rejected = _events(tmp_archive, "turn_unverified")
    assert len(rejected) == 2
    assert all(e.papers == ["sc01", "sc04"] for e in rejected)
    assert [e.payload["turn"] for e in rejected] == [0, 1]
    assert all(e.payload["speaker"] == "sc01" for e in rejected)
    assert all(e.payload["dropped"][0]["paper_id"] == "sc04" for e in rejected)
    assert llm.calls["debate_verdict"] == 1
    assert d.verdict in LEGAL


def test_paraphrased_quote_is_rejected(cards: list[PaperCard], tmp_archive: Archive) -> None:
    def paraphrase(user: str) -> dict:
        s = parse_headers(user)["SPEAKER"]
        return {"text": "x", "quotes": [{"paper_id": s, "text": "This paper shows batch effects vanish entirely.", "loc": "p1"}]}

    llm = CountingLLM(MockLLM(scripted={"debate_turn": paraphrase}))
    [d] = run_debate(_map(cards, [(0, 3)]), cards, llm, tmp_archive)
    assert d.verdict == "unresolved"
    assert d.judge_reason == NO_QUOTES_REASON
    assert len(_events(tmp_archive, "turn_unverified")) == 4
    assert llm.calls["debate_verdict"] == 0


def test_verbatim_quote_with_fabricated_loc_is_unverified(cards: list[PaperCard], tmp_archive: Archive) -> None:
    def fake_loc(user: str) -> dict:
        s = parse_headers(user)["SPEAKER"]
        own = next(q for q in parse_quotes(user) if q["paper_id"] == s)
        return {"text": "x", "quotes": [dict(own, loc="p42 Table 9 (fabricated)")]}

    llm = CountingLLM(MockLLM(scripted={"debate_turn": fake_loc}))
    [d] = run_debate(_map(cards, [(0, 3)]), cards, llm, tmp_archive)
    assert d.verdict == "unresolved" and d.judge_reason == NO_QUOTES_REASON
    assert all(not t.verified and t.quotes == [] for t in d.turns)
    rejected = _events(tmp_archive, "turn_unverified")
    assert len(rejected) == 4
    assert all(e.payload["dropped"][0]["loc"] == "p42 Table 9 (fabricated)" for e in rejected)
    assert llm.calls["debate_verdict"] == 0


def test_malformed_quote_is_dropped_not_crashing(cards: list[PaperCard], tmp_archive: Archive) -> None:
    def bad_loc(user: str) -> dict:
        s = parse_headers(user)["SPEAKER"]
        own = [q for q in parse_quotes(user) if q["paper_id"] == s][0]
        return {"text": "x", "quotes": [{**own, "loc": "p1]|bad"}, own]}

    llm = CountingLLM(MockLLM(scripted={"debate_turn": bad_loc}))
    [d] = run_debate(_map(cards, [(0, 3)]), cards, llm, tmp_archive, turns=1)
    assert all(t.verified and len(t.quotes) == 1 for t in d.turns)
    rejected = _events(tmp_archive, "turn_unverified")
    assert len(rejected) == 2
    assert all(e.payload["dropped"][0]["loc"] == "p1]|bad" for e in rejected)


def test_no_verified_turns_gives_unresolved_without_verdict_call(cards: list[PaperCard], tmp_archive: Archive) -> None:
    llm = CountingLLM(MockLLM(scripted={"debate_turn": lambda user: {"text": "no evidence", "quotes": []}}))
    [d] = run_debate(_map(cards, [(1, 5)]), cards, llm, tmp_archive, turns=2)
    assert d.verdict == "unresolved"
    assert d.judge_reason == NO_QUOTES_REASON
    assert llm.calls["debate_turn"] == 4
    assert llm.calls["debate_verdict"] == 0
    assert all(not t.verified for t in d.turns)
    # Empty quotes is not a rejection: nothing was dropped.
    assert _events(tmp_archive, "turn_unverified") == []


def test_one_verified_side_is_enough_for_a_verdict(cards: list[PaperCard], tmp_archive: Archive) -> None:
    mock = MockLLM()

    def only_b(user: str) -> dict:
        h = parse_headers(user)
        if h["SPEAKER"] == h["PAIR"].split("|")[0].strip():
            return {"text": "a has nothing", "quotes": []}
        return mock.default("debate_turn", user, {})

    mock.scripted["debate_turn"] = only_b
    mock.scripted["debate_verdict"] = lambda user: {"verdict": "contested", "reason": "b made a verified point"}
    llm = CountingLLM(mock)
    [d] = run_debate(_map(cards, [(1, 5)]), cards, llm, tmp_archive)
    assert llm.calls["debate_verdict"] == 1
    assert d.verdict == "contested"
    assert d.judge_reason == "b made a verified point"


# ------------------------------------------------------------------- claims


def test_claim_built_from_both_quotes_with_note_as_context(cards: list[PaperCard]) -> None:
    pv = _pv(cards[0], cards[3], note="do anchors erase rare types?")
    claim = build_claim(pv)
    assert claim.startswith(f'sc01 says "{cards[0].quotes()[0].text}" but sc04 says "{cards[3].quotes()[0].text}"')
    assert claim.endswith(" [context: do anchors erase rare types?]")


def test_downgrade_note_is_not_passed_as_context(cards: list[PaperCard]) -> None:
    assert "[context:" not in build_claim(_pv(cards[0], cards[3], note=DOWNGRADE_NOTE))
    assert "[context:" not in build_claim(_pv(cards[0], cards[3], note="   "))


def test_claim_and_transcript_reach_the_prompts(cards: list[PaperCard], tmp_archive: Archive) -> None:
    mock = MockLLM()
    llm = CountingLLM(mock)
    [d] = run_debate(_map(cards, [(0, 3)]), cards, llm, tmp_archive, agenda="rare cells", turns=2)
    turn_prompts = [u for k, u in mock.calls if k == "debate_turn"]
    verdict_prompts = [u for k, u in mock.calls if k == "debate_verdict"]
    assert len(turn_prompts) == 4 and len(verdict_prompts) == 1
    for u in turn_prompts + verdict_prompts:
        h = parse_headers(u)
        assert h["AGENDA"] == "rare cells"
        assert h["PAIR"] == "sc01 | sc04"
        assert h["CLAIM"] == " ".join(d.claim.split())
    assert [parse_headers(u)["SPEAKER"] for u in turn_prompts] == ["sc01", "sc04", "sc01", "sc04"]
    assert [parse_headers(u)["TURN"] for u in turn_prompts] == ["0", "0", "1", "1"]
    assert "TRANSCRIPT: (none)" in turn_prompts[0]
    assert f"[sc01] {d.turns[0].text}" in turn_prompts[1]
    assert f"[sc04] (verified) {d.turns[1].text}" in verdict_prompts[0]


# ------------------------------------------------------------------- resume


def test_from_events_rebuilds_disputes(cards: list[PaperCard], tmp_archive: Archive) -> None:
    disputes = run_debate(_map(cards, SEVEN), cards, MockLLM(), tmp_archive)
    rebuilt = disputes_from_events(tmp_archive)
    assert list(rebuilt) == [(d.a, d.b) for d in disputes]
    assert list(rebuilt.values()) == disputes
    assert all(isinstance(d, Dispute) and all(isinstance(t, Turn) for t in d.turns) for d in rebuilt.values())


def test_second_run_reuses_everything_with_zero_calls(cards: list[PaperCard], tmp_archive: Archive) -> None:
    first = run_debate(_map(cards, SEVEN), cards, MockLLM(), tmp_archive)
    size = tmp_archive.path.stat().st_size
    llm = CountingLLM(MockLLM())
    second = run_debate(_map(cards, SEVEN), cards, llm, tmp_archive)
    assert llm.total == 0
    assert second == first
    assert tmp_archive.path.stat().st_size > size  # step_started + step_done appended, nothing rewritten
    starts = _events(tmp_archive, "step_started")
    assert [e.payload["reused"] for e in starts] == [0, 5]
    assert len(_events(tmp_archive, "dispute")) == 5


def test_partial_resume_after_crash(cards: list[PaperCard], tmp_archive: Archive) -> None:
    mock = MockLLM()
    counter = {"n": 0}

    def crash_on_8th(user: str) -> dict:
        counter["n"] += 1
        if counter["n"] == 8:
            raise RuntimeError("boom")
        return mock.default("debate_turn", user, {})

    mock.scripted["debate_turn"] = crash_on_8th
    with pytest.raises(RuntimeError, match="boom"):
        run_debate(_map(cards, SEVEN), cards, mock, tmp_archive)
    assert len(_events(tmp_archive, "dispute")) == 1
    assert not tmp_archive.has_step("debate")

    llm = CountingLLM(MockLLM())
    disputes = run_debate(_map(cards, SEVEN), cards, llm, tmp_archive)
    assert len(disputes) == 5
    assert llm.total == 4 * 5
    assert _events(tmp_archive, "step_started")[-1].payload["reused"] == 1
    assert tmp_archive.has_step("debate")
    keys = [(d.a, d.b) for d in disputes]
    assert len(set(keys)) == 5
    assert list(disputes_from_events(tmp_archive)) == keys


def test_events_are_valid_json_lines(cards: list[PaperCard], tmp_archive: Archive) -> None:
    run_debate(_map(cards, [(0, 3)]), cards, MockLLM(), tmp_archive)
    lines = tmp_archive.path.read_text().splitlines()
    types = [json.loads(ln)["type"] for ln in lines]
    assert types[0] == "step_started" and types[-1] == "step_done" and "dispute" in types
    done = json.loads(lines[-1])["payload"]
    assert set(done) == {"count", "card_ids_sha", "label"}
    assert len(done["card_ids_sha"]) == 64
