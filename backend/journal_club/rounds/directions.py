"""Directions round: the PI turns live disputes and shared limitations into ranked directions."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, field_validator

from journal_club import prompts
from journal_club.archive import Archive, Event, Step
from journal_club.cards import PaperCard, Quote
from journal_club.llm import LLM
from journal_club.quotes import verify_quotes

if TYPE_CHECKING:
    from journal_club.rounds.debate import Dispute
    from journal_club.rounds.map_round import MapResult

log = logging.getLogger(__name__)

LIVE_VERDICTS = ("contested", "unresolved")
REJECT_REASON = "no verified quote"


class Direction(BaseModel):
    """One predicted move of the field, backed by verified quotes."""

    model_config = ConfigDict(extra="forbid")

    text: str
    from_a: str
    to_b: str
    because: str
    papers: list[str]
    quotes: list[Quote]
    confidence: float

    @field_validator("papers")
    @classmethod
    def _papers(cls, v: list[str]) -> list[str]:
        """Sorted, de-duplicated."""
        return sorted(set(v))

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> float:
        """Clamp into [0, 1]; never reject."""
        try:
            x = float(v)
        except (TypeError, ValueError):
            return 0.0
        if x != x:  # NaN
            return 0.0
        return min(1.0, max(0.0, x))


# ---------------------------------------------------------------- helpers


def _cards_by_id(cards: list[PaperCard]) -> dict[str, PaperCard]:
    """Index cards by id."""
    return {c.id: c for c in cards}


def _card_ids_sha(cards: list[PaperCard]) -> str:
    """sha256 of the sorted, comma-joined card ids."""
    return hashlib.sha256(",".join(sorted(c.id for c in cards)).encode()).hexdigest()


def _event(step: Step, type: str, papers: list[str], payload: dict, round: int) -> Event:
    """Build an Event with seq 0 (assigned by the archive)."""
    return Event(round=round, step=step, type=type, papers=papers, payload=payload, seq=0)


def _raw_quotes(raw: dict) -> list[Quote]:
    """Quote models from a raw direction, skipping malformed ones."""
    out: list[Quote] = []
    for q in raw.get("quotes", []):
        try:
            out.append(Quote.model_validate(q))
        except ValueError:
            log.warning("directions: malformed quote dropped: %r", q)
    return out


def _named_papers(raw: dict, ids: set[str]) -> list[str]:
    """The raw `papers` list restricted to known ids (what the model claimed, unverified)."""
    named = {p for p in raw.get("papers", []) if isinstance(p, str)}
    return sorted(named & ids)


def _papers_for(raw: dict, ok: list[Quote], ids: set[str]) -> list[str]:
    """Only the papers a verified quote comes from; names without a quote are dropped and logged."""
    papers = sorted({q.paper_id for q in ok})
    unbacked = sorted(set(_named_papers(raw, ids)) - set(papers))
    if unbacked:
        log.info("directions: %s named without a verified quote, not attributed", unbacked)
    return papers


def _gate(raw: dict, by_id: dict[str, PaperCard]) -> tuple[Direction | None, list[Quote], list[str]]:
    """Verify one raw direction: (direction or None, failed quotes, papers)."""
    ok, failed = verify_quotes(by_id, _raw_quotes(raw))
    if not ok:
        return None, failed, _named_papers(raw, set(by_id))
    papers = _papers_for(raw, ok, set(by_id))
    direction = Direction(
        text=raw["text"],
        from_a=raw["from_a"],
        to_b=raw["to_b"],
        because=raw["because"],
        papers=papers,
        quotes=ok,
        confidence=raw["confidence"],
    )
    return direction, failed, papers


def _build_user(
    kind: str,
    agenda: str,
    n: int,
    cards: list[PaperCard],
    live: list[Dispute],
    shared: list[Any],
) -> str:
    """User prompt: baseline sees only the cards, directions sees disputes and limitations too."""
    if kind == "baseline":
        return prompts.build_baseline(agenda, n, cards)
    return prompts.build_directions(agenda, n, cards, live, shared)


def _sorted(directions: list[Direction]) -> list[Direction]:
    """Confidence descending, stable."""
    return sorted(directions, key=lambda d: -d.confidence)


# ------------------------------------------------------------------- round


def run_directions(
    map_result: MapResult,
    disputes: list[Dispute],
    cards: list[PaperCard],
    llm: LLM,
    archive: Archive,
    n: int = 8,
    agenda: str = "",
    round: int = 1,
    step: Step = "directions",
    kind: str = "directions",
) -> list[Direction]:
    """One LLM call; every direction passes the quote gate or is rejected and logged."""
    live = [d for d in disputes if d.verdict in LIVE_VERDICTS]
    shared = list(map_result.by_relation("shared_limitation"))
    by_id = _cards_by_id(cards)
    archive.append(_event(step, "step_started", [], {"label": None, "reused": 0}, round))
    user = _build_user(kind, agenda, n, cards, live, shared)
    raw = llm.complete_json(kind, prompts.load_prompt(kind), user, prompts.SCHEMAS[kind])
    survivors: list[Direction] = []
    for item in raw["directions"]:
        direction, failed, papers = _gate(item, by_id)
        if direction is None:
            log.warning("%s: rejected direction without verified quote: %r", kind, item.get("text", "")[:80])
            payload = {"raw": item, "failed": [q.model_dump() for q in failed], "reason": REJECT_REASON}
            archive.append(_event(step, "direction_rejected", papers, payload, round))
            continue
        if failed:
            log.info("%s: dropped %d unverified quote(s) from a direction", kind, len(failed))
        archive.append(_event(step, "direction", direction.papers, direction.model_dump(), round))
        survivors.append(direction)
    survivors = _sorted(survivors)
    done = {"count": len(survivors), "card_ids_sha": _card_ids_sha(cards), "label": None}
    archive.append(_event(step, "step_done", [], done, round))
    log.info("%s: %d direction(s) kept of %d proposed", kind, len(survivors), len(raw["directions"]))
    return survivors


# ----------------------------------------------------------------- rebuild


def _window(events: list[Event]) -> list[Event]:
    """Events after the last step_started that a step_done follows; else all."""
    starts = [i for i, e in enumerate(events) if e.type == "step_started"]
    if not starts:
        return events
    last = starts[-1]
    if any(e.type == "step_done" for e in events[last:]):
        return events[last:]
    return events


def directions_from_events(archive: Archive, step: Step = "directions") -> list[Direction]:
    """Rebuild the surviving directions of a step from its `direction` events, ranked."""
    events = _window(archive.by_step(step))
    found = [Direction.model_validate(e.payload) for e in events if e.type == "direction"]
    return _sorted(found)
