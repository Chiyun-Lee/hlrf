"""Synthesis round: the PI writes the overview and quote-backed key points that open the minutes."""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from journal_club import prompts
from journal_club.archive import Archive, Event, Step
from journal_club.cards import PaperCard, Quote
from journal_club.llm import LLM
from journal_club.quotes import verify_quotes

if TYPE_CHECKING:
    from journal_club.rounds.debate import Dispute
    from journal_club.rounds.directions import Direction
    from journal_club.rounds.explore import Review
    from journal_club.rounds.map_round import MapResult

log = logging.getLogger(__name__)

Kind = Literal["consensus", "dissent", "gap", "direction"]
KIND_ORDER: tuple[Kind, ...] = ("consensus", "dissent", "gap", "direction")
REJECT_REASON = "no verified quote"


class KeyPoint(BaseModel):
    """One sentence of the overview, backed by verified quotes."""

    model_config = ConfigDict(extra="forbid")

    kind: Kind
    text: str
    quotes: list[Quote]


class Synthesis(BaseModel):
    """The overview prose and its key points."""

    model_config = ConfigDict(extra="forbid")

    overview: str
    key_points: list[KeyPoint]

    def by_kind(self, kind: Kind) -> list[KeyPoint]:
        """Key points of one kind, in order."""
        return [k for k in self.key_points if k.kind == kind]


# ---------------------------------------------------------------- helpers


def _card_ids_sha(cards: list[PaperCard]) -> str:
    """sha256 of the sorted, comma-joined card ids."""
    return hashlib.sha256(",".join(sorted(c.id for c in cards)).encode()).hexdigest()


def _event(step: Step, type: str, papers: list[str], payload: dict, round: int) -> Event:
    """Build an Event with seq 0 (assigned by the archive)."""
    return Event(round=round, step=step, type=type, papers=papers, payload=payload, seq=0)


def _raw_quotes(raw: dict) -> list[Quote]:
    """Quote models from a raw key point, skipping malformed ones."""
    out: list[Quote] = []
    for q in raw.get("quotes", []):
        try:
            out.append(Quote.model_validate(q))
        except ValueError:
            log.warning("synthesis: malformed quote dropped: %r", q)
    return out


def _sorted(points: list[KeyPoint]) -> list[KeyPoint]:
    """Consensus, dissent, gap, direction; stable within a kind."""
    return sorted(points, key=lambda k: KIND_ORDER.index(k.kind))


# ------------------------------------------------------------------- round


def run_synthesis(
    map_result: MapResult,
    disputes: list[Dispute],
    directions: list[Direction],
    cards: list[PaperCard],
    llm: LLM,
    archive: Archive,
    agenda: str = "",
    round: int = 1,
    step: Step = "synthesis",
    hypotheses: list[Review] | None = None,
) -> Synthesis:
    """One LLM call; every key point passes the quote gate or is rejected and logged."""
    by_id = {c.id: c for c in cards}
    archive.append(_event(step, "step_started", [], {"label": None, "reused": 0}, round))
    user = prompts.build_synthesis(
        agenda,
        cards,
        list(map_result.by_relation("agree")),
        list(map_result.by_relation("shared_limitation")),
        disputes,
        directions,
        hypotheses or [],
    )
    raw = llm.complete_json("synthesis", prompts.load_prompt("synthesis"), user, prompts.SCHEMAS["synthesis"])
    kept: list[KeyPoint] = []
    for item in raw["key_points"]:
        ok, failed = verify_quotes(by_id, _raw_quotes(item))
        if not ok:
            log.warning("synthesis: rejected key point without verified quote: %r", item.get("text", "")[:80])
            payload = {"raw": item, "failed": [q.model_dump() for q in failed], "reason": REJECT_REASON}
            archive.append(_event(step, "keypoint_rejected", [], payload, round))
            continue
        kept.append(KeyPoint(kind=item["kind"], text=item["text"], quotes=ok))
    synthesis = Synthesis(overview=" ".join(str(raw["overview"]).split()), key_points=_sorted(kept))
    papers = sorted({q.paper_id for k in synthesis.key_points for q in k.quotes})
    archive.append(_event(step, "synthesis", papers, synthesis.model_dump(), round))
    done = {"count": len(synthesis.key_points), "card_ids_sha": _card_ids_sha(cards), "label": None}
    archive.append(_event(step, "step_done", [], done, round))
    log.info("synthesis: %d key point(s) kept of %d proposed", len(kept), len(raw["key_points"]))
    return synthesis


# ----------------------------------------------------------------- rebuild


def synthesis_from_events(archive: Archive, step: Step = "synthesis") -> Synthesis | None:
    """The last stored synthesis of a step, or None."""
    found = [e.payload for e in archive.by_step(step) if e.type == "synthesis"]
    return Synthesis.model_validate(found[-1]) if found else None
