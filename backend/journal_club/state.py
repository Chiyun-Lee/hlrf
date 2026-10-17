"""What a run looks like to the app: a pure fold of its events.jsonl (DESIGN.md: every view is a projection of the
archive). app/club.py serves it; web/club.js draws it. Reads the file directly, so it works while a run holds the
archive lock, and skips a half-written last line."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from journal_club.archive import Event, Step
from journal_club.minutes import (
    _agenda,
    _directions,
    _disputes,
    _hypotheses,
    _rejected_counts,
    _report,
    _run_started,
    _synthesis,
    _window,
)

NIGHT_STEPS: tuple[Step, ...] = ("map", "debate", "directions", "hypotheses", "critique", "synthesis")
EXPLORE_STEPS: tuple[Step, ...] = ("hypotheses", "critique")  # not in a backtest, nor in runs from before they existed
BACKTEST_STEPS: tuple[Step, ...] = (*NIGHT_STEPS, "baseline", "judge")
CARD_HEAD = ("id", "citekey", "title", "year", "date", "authors", "abstract")


class StepState(BaseModel):
    """One round's progress."""

    name: Step
    status: Literal["pending", "running", "done"]
    count: int  # items it produced (pairs, disputes, directions, key points, hits)
    reused: bool = False  # rebuilt from the archive on a resume, no LLM calls


class RunState(BaseModel):
    """Everything the run page shows."""

    kind: Literal["night", "backtest"]
    agenda: str
    model: str
    judge_model: str
    T: str | None
    cards: list[dict]  # CARD_HEAD fields of each card, from the run_started snapshot
    steps: list[StepState]
    pairs: list[dict]  # every pair verdict of the last map window
    disputes: list[dict]
    directions: list[dict]  # ranked by confidence
    hypotheses: list[dict]  # reviews ranked by the round-2 tournament, then hypotheses not reviewed yet (decision None)
    baseline_directions: list[dict]
    synthesis: dict | None
    report: dict | None
    rejected: dict[str, int]
    minutes_written: bool
    n_events: int
    last_seq: int


def read_events(path: str | Path) -> list[Event]:
    """Every parsable line of an events.jsonl; a half-written last line (a run mid-append) is skipped."""
    events: list[Event] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return events
    for line in lines:
        if not line.strip():
            continue
        try:
            events.append(Event.model_validate_json(line))
        except (ValidationError, json.JSONDecodeError):
            if line is lines[-1]:
                break
            raise
    return events


def _step_state(events: list[Event], step: Step) -> StepState:
    """pending until a step_started; running until a step_done (or step_skipped) closes the last window."""
    evs = [e for e in events if e.step == step]
    if not evs:
        return StepState(name=step, status="pending", count=0)
    last = _window(events, step)
    done = [e for e in last if e.type in ("step_done", "step_skipped")]
    if done:  # a resume appends a step_skipped after the original step_done: the last word says how the step ended
        return StepState(name=step, status="done", count=int(done[-1].payload.get("count", 0)), reused=done[-1].type == "step_skipped")
    produced = sum(1 for e in last if e.type in ("pair_verdict", "dispute", "direction", "hypothesis", "review", "synthesis", "hit"))
    return StepState(name=step, status="running", count=produced)


def fold(events: list[Event]) -> RunState:
    """The state after these events; pure."""
    started = _run_started(events)
    is_backtest = started.get("T") is not None or any(e.step == "backtest" for e in events)
    split = next((e.payload for e in events if e.step == "backtest" and e.type == "split"), {})
    explored = started.get("explore", False) or any(e.step in EXPLORE_STEPS for e in events)
    steps = [s for s in (BACKTEST_STEPS if is_backtest else NIGHT_STEPS) if explored or s not in EXPLORE_STEPS]
    if started.get("baseline") is False:  # a backtest of the club arm alone
        steps.remove("baseline")
    return RunState(
        kind="backtest" if is_backtest else "night",
        agenda=_agenda(events),
        model=str(started.get("model", "")),
        judge_model=str(started.get("judge_model", "")),
        T=started.get("T") or split.get("T"),
        cards=[{k: c.get(k) for k in CARD_HEAD} for c in started.get("cards", [])],
        steps=[_step_state(events, s) for s in steps],
        pairs=[e.payload for e in _window(events, "map") if e.type == "pair_verdict"],
        disputes=_disputes(events),
        directions=_directions(events),
        hypotheses=_hypotheses(events),
        baseline_directions=_directions(events, "baseline") if is_backtest else [],
        synthesis=_synthesis(events),
        report=_report(events),
        rejected=_rejected_counts(events),
        minutes_written=any(e.step == "minutes" and e.type == "written" for e in events),
        n_events=len(events),
        last_seq=events[-1].seq if events else 0,
    )
