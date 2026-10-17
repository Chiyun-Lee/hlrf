"""Exploration: the PI proposes hypotheses that go beyond the papers, then a second round tests them.

Directions forecast where the field moves (and the backtest scores them); hypotheses are the club's own ideas: a
claim with a mechanism, a test that would refute it and what that test should show. Their premises are verified
quotes, like everything else in a night, but the hypothesis itself is allowed to say what no paper says.

Round 2 (step "critique", events tagged round + 1): each paper a hypothesis rests on has its PhD student support or
object to it from that paper's own quotes; the PI then keeps, revises or drops it; the survivors meet in a round-robin
of pairwise comparisons and are ranked by wins.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Iterable
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from journal_club import prompts
from journal_club.archive import Archive, Event, Step
from journal_club.cards import PaperCard, Quote
from journal_club.llm import LLM
from journal_club.quotes import verify_quotes
from journal_club.rounds.map_round import card_ids_sha, run_parallel, workers

if TYPE_CHECKING:
    from journal_club.rounds.debate import Dispute
    from journal_club.rounds.directions import Direction
    from journal_club.rounds.map_round import MapResult

log = logging.getLogger(__name__)

Source = Literal["combine", "resolve", "gap", "extend"]
Decision = Literal["keep", "revise", "drop"]
N_HYPOTHESES = 6  # proposed per night; a round-robin of 6 is 15 comparisons
CRITICS = 3  # papers heard per hypothesis, in the order it cites them
REJECT_REASON = "no verified quote"


class Hypothesis(BaseModel):
    """One idea of the club's own, resting on verified quotes (its premises)."""

    model_config = ConfigDict(extra="forbid")

    id: str  # h1, h2, ... in the order proposed
    text: str  # the hypothesis, in one sentence
    mechanism: str  # why it would be true
    test: str  # the experiment or analysis that would refute it
    prediction: str  # what that test shows if the hypothesis holds
    source: Source  # combine: agreeing papers joined; resolve: an open dispute; gap: a shared limitation; extend: one result pushed on
    papers: list[str]  # the papers a verified premise comes from
    quotes: list[Quote]  # the premises


class Critique(BaseModel):
    """What one paper's student says about a hypothesis; `quotes` holds the verified ones only."""

    model_config = ConfigDict(extra="forbid")

    speaker: str
    stance: Literal["supports", "objects"]
    text: str
    quotes: list[Quote]
    verified: bool


class Review(BaseModel):
    """A hypothesis after round 2: what its papers said, the PI's call and the tournament's tally."""

    model_config = ConfigDict(extra="forbid")

    hypothesis: Hypothesis  # as revised (the premises never change); as proposed when kept or dropped
    original: str | None = None  # the proposed text, when the PI revised it
    critiques: list[Critique]
    decision: Decision
    reason: str
    wins: int = 0
    played: int = 0  # comparisons it was in; 0 for a dropped hypothesis


# ---------------------------------------------------------------- helpers


def _event(step: Step, type: str, papers: list[str], payload: dict, round: int) -> Event:
    """An Event with seq 0 (assigned by the archive)."""
    return Event(round=round, step=step, type=type, papers=papers, payload=payload, seq=0)


def _quotes(raw: dict) -> list[Quote]:
    """Quote models from a raw item, skipping malformed ones."""
    out: list[Quote] = []
    for q in raw.get("quotes", []):
        try:
            out.append(Quote.model_validate(q))
        except ValueError:
            log.warning("explore: malformed quote dropped: %r", q)
    return out


def _window(events: list[Event]) -> list[Event]:
    """Events after the last step_started that a step_done follows; else all (partial resume)."""
    starts = [i for i, e in enumerate(events) if e.type == "step_started"]
    if starts and any(e.type == "step_done" for e in events[starts[-1] :]):
        return events[starts[-1] :]
    return events


def ranked(reviews: list[Review]) -> list[Review]:
    """Survivors by wins (ties keep the proposed order), then the dropped ones."""
    order = {r.hypothesis.id: i for i, r in enumerate(reviews)}
    return sorted(reviews, key=lambda r: (r.decision == "drop", -r.wins, order[r.hypothesis.id]))


# --------------------------------------------------------------- hypotheses


def run_hypotheses(
    map_result: MapResult,
    disputes: list[Dispute],
    directions: list[Direction],
    cards: list[PaperCard],
    llm: LLM,
    archive: Archive,
    n: int = N_HYPOTHESES,
    agenda: str = "",
    round: int = 1,
) -> list[Hypothesis]:
    """One PI call; a hypothesis with no verified premise is rejected and logged."""
    by_id = {c.id: c for c in cards}
    archive.append(_event("hypotheses", "step_started", [], {"label": None, "reused": 0}, round))
    user = prompts.build_hypotheses(
        agenda, n, cards, list(map_result.by_relation("agree")), list(map_result.by_relation("shared_limitation")), disputes, directions
    )
    raw = llm.complete_json("hypotheses", prompts.load_prompt("hypotheses"), user, prompts.SCHEMAS["hypotheses"])
    kept: list[Hypothesis] = []
    for item in raw["hypotheses"][:n]:
        ok, failed = verify_quotes(by_id, _quotes(item))
        if not ok:
            log.warning("hypotheses: rejected without a verified premise: %r", item.get("text", "")[:80])
            payload = {"raw": item, "failed": [q.model_dump() for q in failed], "reason": REJECT_REASON}
            archive.append(_event("hypotheses", "hypothesis_rejected", [], payload, round))
            continue
        fields = {k: item[k] for k in ("text", "mechanism", "test", "prediction", "source")}
        h = Hypothesis(id=f"h{len(kept) + 1}", papers=sorted({q.paper_id for q in ok}), quotes=ok, **fields)
        archive.append(_event("hypotheses", "hypothesis", h.papers, h.model_dump(), round))
        kept.append(h)
    done = {"count": len(kept), "card_ids_sha": card_ids_sha(cards), "label": None}
    archive.append(_event("hypotheses", "step_done", [], done, round))
    log.info("hypotheses: %d kept of %d proposed", len(kept), len(raw["hypotheses"]))
    return kept


def hypotheses_from_events(archive: Archive) -> list[Hypothesis]:
    """The kept hypotheses of the last finished hypotheses step, in proposed order."""
    return hypotheses_from(archive.by_step("hypotheses"))


def hypotheses_from(hypotheses_events: list[Event]) -> list[Hypothesis]:
    """hypotheses_from_events over a list of the hypotheses step's events; pure."""
    return [Hypothesis.model_validate(e.payload) for e in _window(hypotheses_events) if e.type == "hypothesis"]


# ------------------------------------------------------------------ round 2


def _critique(h: Hypothesis, speaker: str, by_id: dict[str, PaperCard], llm: LLM, agenda: str) -> tuple[Critique, list[Quote]]:
    """One paper's student on one hypothesis: (critique, its quotes that failed the gate)."""
    others = [by_id[p] for p in h.papers if p != speaker]
    user = prompts.build_critique(agenda, h, by_id[speaker], others)
    raw = llm.complete_json("critique", prompts.load_prompt("critique"), user, prompts.SCHEMAS["critique"])
    ok, failed = verify_quotes(by_id, _quotes(raw), require_paper=speaker)
    return Critique(speaker=speaker, stance=raw["stance"], text=raw["text"], quotes=ok, verified=bool(ok)), failed


def _review(h: Hypothesis, by_id: dict[str, PaperCard], llm: LLM, agenda: str) -> tuple[Review, list[dict]]:
    """Hear the hypothesis's papers, then the PI's call: (review, unverified critiques to log)."""
    critiques, unverified = [], []
    for speaker in h.papers[:CRITICS]:
        c, failed = _critique(h, speaker, by_id, llm, agenda)
        critiques.append(c)
        if failed:
            unverified.append({"hypothesis": h.id, "speaker": speaker, "dropped": [q.model_dump() for q in failed]})
    user = prompts.build_revise(agenda, h, critiques)
    raw = llm.complete_json("revise", prompts.load_prompt("revise"), user, prompts.SCHEMAS["revise"])
    decision: Decision = raw["decision"]
    final, original = h, None
    if decision == "revise":
        final = h.model_copy(update={k: raw[k] for k in ("text", "mechanism", "test", "prediction") if raw[k].strip()})
        original = h.text
    return Review(hypothesis=final, original=original, critiques=critiques, decision=decision, reason=raw["reason"]), unverified


def _compare(pair: tuple[Review, Review], llm: LLM, agenda: str) -> dict:
    """One comparison of the tournament: {a, b, winner, reason} by hypothesis id."""
    a, b = pair
    user = prompts.build_compare(agenda, a, b)
    raw = llm.complete_json("compare", prompts.load_prompt("compare"), user, prompts.SCHEMAS["compare"])
    winner = a if raw["winner"] == "A" else b
    return {"a": a.hypothesis.id, "b": b.hypothesis.id, "winner": winner.hypothesis.id, "reason": raw["reason"]}


def _matches(alive: list[Review]) -> list[tuple[Review, Review]]:
    """Every pair once, the shown order alternating so neither side is always first."""
    return [(x, y) if (i + j) % 2 else (y, x) for (i, x), (j, y) in itertools.combinations(enumerate(alive), 2)]


def run_critique(
    hypotheses: list[Hypothesis],
    cards: list[PaperCard],
    llm: LLM,
    archive: Archive,
    agenda: str = "",
    round: int = 2,
) -> list[Review]:
    """Critique and revise every hypothesis (resumable one by one), then rank the survivors by a round-robin."""
    by_id = {c.id: c for c in cards}
    done = reviews_from_events(archive)
    archive.append(_event("critique", "step_started", [], {"label": None, "reused": len(done)}, round))
    todo = [h for h in hypotheses if h.id not in done]

    def store(batch: list[tuple[Review, list[dict]]]) -> None:
        for review, unverified in batch:
            for u in unverified:
                archive.append(_event("critique", "critique_unverified", [u["speaker"]], u, round))
            archive.append(_event("critique", "review", review.hypothesis.papers, review.model_dump(), round))
            done[review.hypothesis.id] = review

    run_parallel(lambda h: _review(h, by_id, llm, agenda), todo, workers(), after_batch=store)
    reviews = [done[h.id] for h in hypotheses if h.id in done]
    alive = [r for r in reviews if r.decision != "drop"]
    matches = run_parallel(lambda p: _compare(p, llm, agenda), _matches(alive), workers())
    tally(alive, matches)
    archive.append(_event("critique", "ranking", [], {"matches": matches}, round))
    reviews = ranked(reviews)
    done_payload = {"count": len(reviews), "card_ids_sha": card_ids_sha(cards), "label": None}
    archive.append(_event("critique", "step_done", [], done_payload, round))
    log.info("critique: %d reviewed, %d dropped, %d comparisons", len(reviews), len(reviews) - len(alive), len(matches))
    return reviews


def reviews_from_events(archive: Archive) -> dict[str, Review]:
    """Stored reviews by hypothesis id (last wins), with the tournament's tally when it ran."""
    return reviews_from(archive.by_step("critique"))


def reviews_from(critique_events: list[Event]) -> dict[str, Review]:
    """reviews_from_events over a list of the critique step's events; pure (the run page and the minutes use it)."""
    events = _window(critique_events)
    reviews = {r.hypothesis.id: r for r in (Review.model_validate(e.payload) for e in events if e.type == "review")}
    rankings = [e.payload for e in events if e.type == "ranking"]
    if rankings:
        tally(reviews.values(), rankings[-1]["matches"])
    return reviews


def tally(reviews: Iterable[Review], matches: list[dict]) -> None:
    """Set wins and played on each review from the tournament's matches."""
    for r in reviews:
        mine = [m for m in matches if r.hypothesis.id in (m["a"], m["b"])]
        r.played, r.wins = len(mine), sum(m["winner"] == r.hypothesis.id for m in mine)


def critique_from_events(archive: Archive, hypotheses: list[Hypothesis]) -> list[Review]:
    """The finished critique step rebuilt from the archive, ranked."""
    done = reviews_from_events(archive)
    return ranked([done[h.id] for h in hypotheses if h.id in done])
