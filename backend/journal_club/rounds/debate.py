"""Debate round: disagreeing pairs defend their claims and the PI rules (DESIGN.md §7.2)."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from journal_club import prompts
from journal_club.archive import Archive, Event
from journal_club.cards import PaperCard, Quote
from journal_club.llm import LLM
from journal_club.quotes import verify_quotes

if TYPE_CHECKING:
    from journal_club.rounds.map_round import MapResult, PairVerdict

log = logging.getLogger(__name__)

STEP: Literal["debate"] = "debate"
DOWNGRADE_NOTE = "quote failed verification"
NO_QUOTES_REASON = "no verified quotes"

Verdict = Literal["stands", "contested", "unresolved"]


class Turn(BaseModel):
    """One speaker's turn; `quotes` holds the verified quotes only."""

    model_config = ConfigDict(extra="forbid")

    speaker: str
    text: str
    quotes: list[Quote]
    verified: bool


class Dispute(BaseModel):
    """A disagreement between papers a and b, its transcript and the PI's ruling."""

    model_config = ConfigDict(extra="forbid")

    a: str
    b: str
    claim: str
    turns: list[Turn]
    verdict: Verdict
    judge_reason: str


# ------------------------------------------------------------------ helpers


def _by_id(cards: list[PaperCard]) -> dict[str, PaperCard]:
    """Cards keyed by id."""
    return {c.id: c for c in cards}


def _card_ids_sha(cards: list[PaperCard]) -> str:
    """sha256 of the sorted, comma-joined card ids."""
    return hashlib.sha256(",".join(sorted(c.id for c in cards)).encode()).hexdigest()


def build_claim(pv: PairVerdict) -> str:
    """The disputed claim, derived from both quoted passages plus the map note as context."""
    claim = f'{pv.a} says "{pv.quote_a.text}" but {pv.b} says "{pv.quote_b.text}"'
    note = pv.note.strip()
    if note and note != DOWNGRADE_NOTE:
        claim += f" [context: {note}]"
    return claim


def _parse_quotes(raw_quotes: list[dict]) -> tuple[list[Quote], list[dict]]:
    """Build Quote models; dicts that fail validation are returned separately."""
    ok: list[Quote] = []
    bad: list[dict] = []
    for raw in raw_quotes:
        try:
            ok.append(Quote.model_validate(raw))
        except ValidationError as exc:
            log.warning("debate: malformed quote dropped: %s", exc.errors()[0].get("msg", exc))
            bad.append(dict(raw))
    return ok, bad


def _event(round: int, type: str, papers: list[str], payload: dict) -> Event:
    """A debate-step event with seq 0 (assigned by the archive)."""
    return Event(round=round, step=STEP, type=type, papers=papers, payload=payload, seq=0)


# ------------------------------------------------------------------ rebuild


def _resumable_events(archive: Archive) -> list[Event]:
    """Debate events of the last completed run (walking back through partial resumes), else all of them."""
    events = archive.by_step(STEP)
    starts = [i for i, e in enumerate(events) if e.type == "step_started"]
    if not starts or not any(e.type == "step_done" for e in events[starts[-1] :]):
        return events
    pos = len(starts) - 1
    while pos > 0 and events[starts[pos]].payload.get("reused", 0) > 0:
        pos -= 1
    return events[starts[pos] :]


def disputes_from_events(archive: Archive) -> dict[tuple[str, str], Dispute]:
    """Disputes stored in the archive keyed by (a, b), last one wins."""
    out: dict[tuple[str, str], Dispute] = {}
    for e in _resumable_events(archive):
        if e.type == "dispute":
            d = Dispute.model_validate(e.payload)
            out[(d.a, d.b)] = d
    return out


# --------------------------------------------------------------------- round


def _take_turn(
    speaker: str,
    k: int,
    claim: str,
    prior: list[Turn],
    ca: PaperCard,
    cb: PaperCard,
    by_id: dict[str, PaperCard],
    llm: LLM,
    archive: Archive,
    agenda: str,
    round: int,
) -> Turn:
    """One debate_turn call for `speaker`, with the quote gate."""
    user = prompts.build_debate_turn(agenda, ca, cb, speaker, claim, k, prior)
    raw = llm.complete_json("debate_turn", prompts.load_prompt("debate_turn"), user, prompts.SCHEMAS["debate_turn"])
    quotes, malformed = _parse_quotes(raw["quotes"])
    ok, failed = verify_quotes(by_id, quotes, require_paper=speaker)
    dropped = [q.model_dump() for q in failed] + malformed
    if dropped:
        log.info("debate: %s turn %d of %s/%s had %d unverified quote(s)", speaker, k, ca.id, cb.id, len(dropped))
        archive.append(_event(round, "turn_unverified", [ca.id, cb.id], {"speaker": speaker, "turn": k, "dropped": dropped}))
    return Turn(speaker=speaker, text=raw["text"], quotes=ok, verified=bool(ok))


def _rule(claim: str, turns: list[Turn], ca: PaperCard, cb: PaperCard, llm: LLM, agenda: str) -> tuple[Verdict, str]:
    """The PI's verdict; `unresolved` without a call when no side has a verified turn."""
    verified_a = any(t.verified for t in turns if t.speaker == ca.id)
    verified_b = any(t.verified for t in turns if t.speaker == cb.id)
    if not verified_a and not verified_b:
        return "unresolved", NO_QUOTES_REASON
    user = prompts.build_debate_verdict(agenda, ca, cb, claim, turns)
    raw = llm.complete_json("debate_verdict", prompts.load_prompt("debate_verdict"), user, prompts.SCHEMAS["debate_verdict"])
    return raw["verdict"], raw["reason"]


def _run_dispute(
    pv: PairVerdict,
    by_id: dict[str, PaperCard],
    llm: LLM,
    archive: Archive,
    turns: int,
    agenda: str,
    round: int,
) -> Dispute:
    """Full transcript and verdict for one disagreeing pair; appends the dispute event."""
    ca, cb = by_id[pv.a], by_id[pv.b]
    claim = build_claim(pv)
    transcript: list[Turn] = []
    for k in range(turns):
        for speaker in (ca.id, cb.id):
            transcript.append(_take_turn(speaker, k, claim, transcript, ca, cb, by_id, llm, archive, agenda, round))
    verdict, reason = _rule(claim, transcript, ca, cb, llm, agenda)
    dispute = Dispute(a=ca.id, b=cb.id, claim=claim, turns=transcript, verdict=verdict, judge_reason=reason)
    archive.append(_event(round, "dispute", [ca.id, cb.id], dispute.model_dump()))
    log.info("debate: %s vs %s -> %s", ca.id, cb.id, verdict)
    return dispute


def run_debate(
    map_result: MapResult,
    cards: list[PaperCard],
    llm: LLM,
    archive: Archive,
    cap: int = 5,
    turns: int = 2,
    agenda: str = "",
    round: int = 1,
) -> list[Dispute]:
    """Debate the first `cap` disagree pairs, `turns` turns per side, then the PI rules."""
    candidates = list(map_result.by_relation("disagree"))[:cap]
    by_id = _by_id(cards)
    done = disputes_from_events(archive)
    archive.append(_event(round, "step_started", [], {"label": None, "reused": len(done)}))
    log.info("debate: %d candidate(s), %d reused from archive", len(candidates), len(done))
    disputes: list[Dispute] = []
    for pv in candidates:
        key = (pv.a, pv.b)
        if key in done:
            disputes.append(done[key])
            continue
        disputes.append(_run_dispute(pv, by_id, llm, archive, turns, agenda, round))
    archive.append(
        _event(round, "step_done", [], {"count": len(disputes), "card_ids_sha": _card_ids_sha(cards), "label": None})
    )
    return disputes
