"""One night of the club: map -> debate -> directions, resumable from the archive (DESIGN.md §8.1)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ConfigDict

from journal_club.archive import Archive, Event, Step
from journal_club.cards import PaperCard
from journal_club.llm import LLM, MockLLM, resolve_model
from journal_club.rounds.debate import Dispute, disputes_from_events, run_debate
from journal_club.rounds.directions import Direction, directions_from_events, run_directions
from journal_club.rounds.map_round import MapResult, card_content_sha, card_ids_sha, run_map
from journal_club.rounds.synthesis import Synthesis, run_synthesis, synthesis_from_events

log = logging.getLogger(__name__)

STEPS: tuple[Step, ...] = ("map", "debate", "directions", "synthesis")
SKIP_REASON = "resumed from archive"
T = TypeVar("T")


class ResumeMismatch(RuntimeError):
    """The archive belongs to a different card set than the one handed in."""


class NightResult(BaseModel):
    """What one night produced: the pair map, the disputes and the ranked directions."""

    model_config = ConfigDict(extra="forbid")

    map: MapResult
    disputes: list[Dispute]
    directions: list[Direction]
    synthesis: Synthesis | None = None


# ---------------------------------------------------------------- helpers


def model_label(llm: LLM) -> str:
    """Model id recorded in run_started: "mock" for the mock backend, else the backend's own model (JC_MODEL as fallback)."""
    inner = getattr(llm, "inner", llm)
    if isinstance(llm, MockLLM) or isinstance(inner, MockLLM) or os.environ.get("JC_LLM") == "mock":
        return "mock"
    model = getattr(llm, "model", None) or getattr(inner, "model", None)
    return str(model) if model else resolve_model("main")


def _event(step: Step, type: str, payload: dict, round: int) -> Event:
    """An event with no papers and seq 0 (assigned by the archive)."""
    return Event(round=round, step=step, type=type, papers=[], payload=payload, seq=0)


def _run_started(archive: Archive) -> Event | None:
    """The run_started event of the archive, if any."""
    return next((e for e in archive.by_step("map") if e.type == "run_started"), None)


def _last_step_done(archive: Archive, step: Step) -> Event | None:
    """The last step_done event of a step without a label, if any."""
    dones = [e for e in archive.by_step(step) if e.type == "step_done" and e.payload.get("label") is None]
    return dones[-1] if dones else None


def check_card_contents(started: dict, cards: list[PaperCard]) -> None:
    """Raise ResumeMismatch if the cards' contents differ from the run_started snapshot (same ids, re-ingested text)."""
    stored = started.get("cards_sha")
    if stored is None:
        log.debug("night: run_started has no cards_sha (older archive); card contents not checked")
        return
    current = card_content_sha(cards)
    if stored != current:
        raise ResumeMismatch(
            f"archive card contents {stored[:12]} != current card contents {current[:12]}: "
            "a card was re-ingested; stored verdicts quote the old text, so start a new run directory"
        )


def check_run(
    archive: Archive, cards: list[PaperCard], agenda: str, llm: LLM, judge_model: str, round: int
) -> str:
    """Bind the archive to this card set: append run_started, or check both shas and the agenda on resume."""
    sha = card_ids_sha(cards)
    started = _run_started(archive)
    if started is None:
        payload = {
            "agenda": agenda,
            "model": model_label(llm),
            "judge_model": judge_model,
            "card_ids_sha": sha,
            "cards_sha": card_content_sha(cards),
            "T": None,
            "cards": [c.model_dump() for c in cards],
        }
        archive.append(_event("map", "run_started", payload, round))
        return sha
    stored = started.payload.get("card_ids_sha")
    if stored != sha:
        raise ResumeMismatch(f"archive card set {stored} != current card set {sha}")
    check_card_contents(started.payload, cards)
    old = str(started.payload.get("agenda", ""))
    if old != agenda:
        log.warning("night: agenda changed from %r to %r; resuming anyway", old, agenda)
        archive.append(_event("map", "agenda_changed", {"old": old, "new": agenda}, round))
    log.info("night: resuming archive %s", archive.path)
    return sha


def _skip(archive: Archive, step: Step, sha: str, count: int, round: int) -> None:
    """Verify the step_done sha and log step_skipped."""
    done = _last_step_done(archive, step)
    stored = done.payload.get("card_ids_sha") if done is not None else None
    if stored != sha:
        raise ResumeMismatch(f"{step}: step_done card set {stored} != current card set {sha}")
    archive.append(_event(step, "step_skipped", {"reason": SKIP_REASON, "count": count, "label": None}, round))
    log.info("night: %s resumed from archive (%d item(s)), no LLM calls", step, count)


def _resume_or_run(
    archive: Archive, step: Step, sha: str, round: int, rebuild: Callable[[], T], run: Callable[[], T], count: Callable[[T], int]
) -> T:
    """Rebuild a finished step from events, else run it (partial resume lives inside the round)."""
    if archive.has_step(step):
        result = rebuild()
        _skip(archive, step, sha, count(result), round)
        return result
    return run()


def _disputes_in_order(archive: Archive, map_result: MapResult, cap: int) -> list[Dispute]:
    """Stored disputes in candidate order, then any others by pair key."""
    done = disputes_from_events(archive)
    ordered = [done[p.key] for p in map_result.by_relation("disagree")[:cap] if p.key in done]
    rest = [done[k] for k in sorted(done) if done[k] not in ordered]
    return ordered + rest


# ------------------------------------------------------------------ night


def run_night(
    cards: list[PaperCard],
    llm: LLM,
    archive: Archive,
    agenda: str,
    round: int = 1,
    judge_model: str = "",
    cap: int = 5,
    turns: int = 2,
    n: int = 8,
) -> NightResult:
    """Run map -> debate -> directions on the cards; steps already in the archive are not re-run."""
    sha = check_run(archive, cards, agenda, llm, judge_model, round)
    map_result = _resume_or_run(
        archive, "map", sha, round,
        lambda: MapResult.from_events(archive),
        lambda: run_map(cards, llm, archive, agenda=agenda, round=round),
        lambda m: len(m.pairs),
    )
    disputes = _resume_or_run(
        archive, "debate", sha, round,
        lambda: _disputes_in_order(archive, map_result, cap),
        lambda: run_debate(map_result, cards, llm, archive, cap=cap, turns=turns, agenda=agenda, round=round),
        len,
    )
    directions = _resume_or_run(
        archive, "directions", sha, round,
        lambda: directions_from_events(archive, "directions"),
        lambda: run_directions(map_result, disputes, cards, llm, archive, n=n, agenda=agenda, round=round),
        len,
    )
    synthesis = _resume_or_run(
        archive, "synthesis", sha, round,
        lambda: synthesis_from_events(archive),
        lambda: run_synthesis(map_result, disputes, directions, cards, llm, archive, agenda=agenda, round=round),
        lambda s: len(s.key_points) if s is not None else 0,
    )
    log.info(
        "night: %d pairs, %d dispute(s), %d direction(s), %d key point(s)",
        len(map_result.pairs), len(disputes), len(directions), len(synthesis.key_points) if synthesis else 0,
    )
    return NightResult(map=map_result, disputes=disputes, directions=directions, synthesis=synthesis)
