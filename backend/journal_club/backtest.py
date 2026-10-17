"""Backtest (DESIGN.md §10.1): split at T, club vs one-call baseline, judged on held-out papers."""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from journal_club import prompts
from journal_club.archive import Archive, Event, Step
from journal_club.cards import PaperCard
from journal_club.llm import LLM, get_llm, resolve_model
from journal_club.rounds.directions import Direction, directions_from_events, run_directions
from journal_club.rounds.map_round import card_content_sha, card_ids_sha, run_parallel, workers

log = logging.getLogger(__name__)

HitVerdict = Literal["hit", "partial", "miss"]
Label = Literal["club", "baseline"]

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LEAK_TYPES = frozenset(
    {"pair_verdict", "quote_rejected", "turn_unverified", "dispute", "direction", "direction_rejected"}
)
UNKNOWN_ID_NOTE = " [paper id not in after-T set]"
REPORT_NOTE = "The judge is an LLM; verdicts were not calibrated against a control. Read the tables."
ClubFn = Callable[[list[PaperCard]], list[Direction]]


class Hit(BaseModel):
    """The judge's verdict on one direction against the after-T set."""

    model_config = ConfigDict(extra="forbid")

    direction_text: str
    verdict: HitVerdict
    after_paper_id: str | None
    reason: str
    label: Label


class BacktestReport(BaseModel):
    """Both arms of one backtest with their verdicts and rates."""

    model_config = ConfigDict(extra="forbid")

    T: str
    before_ids: list[str]
    after_ids: list[str]
    judge_model: str
    club_directions: list[Direction]
    baseline_directions: list[Direction]
    club_hits: list[Hit]
    baseline_hits: list[Hit]
    club_rate: float
    baseline_rate: float
    club_weighted_rate: float
    baseline_weighted_rate: float


# ---------------------------------------------------------------- helpers


def _cards_by_id(cards: list[PaperCard]) -> dict[str, PaperCard]:
    """Index cards by id."""
    return {c.id: c for c in cards}


def _event(step: Step, type: str, papers: list[str], payload: dict, round: int) -> Event:
    """Build an Event with seq 0 (assigned by the archive)."""
    return Event(round=round, step=step, type=type, papers=papers, payload=payload, seq=0)


def _validate_date(value: str) -> str:
    """ISO YYYY-MM-DD and a real calendar date (same rule as PaperCard.date)."""
    if not DATE_RE.match(value):
        raise ValueError(f"T must be YYYY-MM-DD, got {value!r}")
    dt.date.fromisoformat(value)
    return value


def _resume_mismatch() -> type[RuntimeError]:
    """ResumeMismatch, imported lazily (night imports backtest's neighbours)."""
    from journal_club.night import ResumeMismatch

    return ResumeMismatch


def _check_card_contents(started: dict, before: list[PaperCard]) -> None:
    """night.check_card_contents, imported lazily."""
    from journal_club.night import check_card_contents

    check_card_contents(started, before)


# ------------------------------------------------------------------ split


def split_by_date(cards: list[PaperCard], T: str) -> tuple[list[PaperCard], list[PaperCard]]:
    """Cards dated before T and the rest; both sides must be non-empty."""
    T = _validate_date(T)
    before = [c for c in cards if c.date < T]
    after = [c for c in cards if c.date >= T]
    if not before or not after:
        raise ValueError(f"split at {T} leaves {len(before)} before and {len(after)} after; need both")
    log.info("split T=%s before=%d after=%d", T, len(before), len(after))
    return before, after


# --------------------------------------------------------------- baseline


def run_baseline(
    before: list[PaperCard],
    llm: LLM,
    archive: Archive,
    n: int = 10,
    agenda: str = "",
    round: int = 1,
) -> list[Direction]:
    """One `baseline` call over the before-T cards with no discussion; resumed via step_done."""
    if archive.has_step("baseline"):
        found = directions_from_events(archive, "baseline")
        payload = {"reason": "resumed from archive", "count": len(found), "label": None}
        archive.append(_event("baseline", "step_skipped", [], payload, round))
        log.info("baseline: resumed %d direction(s) from archive", len(found))
        return found
    from journal_club.rounds.map_round import MapResult

    return run_directions(
        MapResult(pairs=[]), [], before, llm, archive, n=n, agenda=agenda, round=round, step="baseline", kind="baseline"
    )


# ------------------------------------------------------------------ judge


def _judge_window(events: list[Event], label: str) -> list[Event]:
    """Judge events of one label since its previous completed run (partial attempts included)."""
    mine = [e for e in events if e.payload.get("label") == label]
    dones = [i for i, e in enumerate(mine) if e.type == "step_done"]
    if len(dones) < 2:
        return mine
    return mine[dones[-2] + 1 :]


def hits_from_events(archive: Archive, label: str) -> dict[str, Hit]:
    """Rebuild hits of one label keyed by direction text, last wins."""
    out: dict[str, Hit] = {}
    for e in _judge_window(archive.by_step("judge"), label):
        if e.type == "hit":
            hit = Hit.model_validate(e.payload)
            out[hit.direction_text] = hit
    return out


def _to_hit(raw: dict, direction: Direction, after_ids: set[str], label: Label) -> Hit:
    """Hit from raw judge output; an unknown after id downgrades the verdict to miss."""
    verdict: str = raw["verdict"]
    pid: str | None = raw["after_paper_id"]
    reason: str = raw["reason"]
    if verdict != "miss" and pid not in after_ids:
        log.warning("judge: %s named unknown after paper %r; downgraded to miss", label, pid)
        verdict, reason = "miss", reason + UNKNOWN_ID_NOTE
    if verdict == "miss":
        pid = None
    return Hit(direction_text=direction.text, verdict=verdict, after_paper_id=pid, reason=reason, label=label)


def judge(
    directions: list[Direction],
    after: list[PaperCard],
    llm: LLM,
    archive: Archive,
    label: Label,
    round: int = 1,
) -> list[Hit]:
    """One `judge` call per direction on the judge model, in parallel batches; resumable per label."""
    after_ids = {c.id for c in after}
    done = hits_from_events(archive, label)
    if archive.has_step("judge", label):
        payload = {"reason": "resumed from archive", "count": len(done), "label": label}
        archive.append(_event("judge", "step_skipped", [], payload, round))
        log.info("judge[%s]: resumed %d hit(s) from archive", label, len(done))
        return [done[d.text] for d in directions if d.text in done]
    todo = list({d.text: d for d in directions if d.text not in done}.values())
    archive.append(_event("judge", "step_started", [], {"label": label, "reused": len(done)}, round))
    system, schema = prompts.load_prompt("judge"), prompts.SCHEMAS["judge"]

    def call(d: Direction) -> Hit:
        """Judge one direction on a worker thread."""
        raw = llm.complete_json("judge", system, prompts.build_judge(d, after), schema)
        return _to_hit(raw, d, after_ids, label)

    def record(hits: list[Hit]) -> None:
        """Archive a batch's hits on the main thread; a crash mid-batch still keeps the finished prefix."""
        for hit in hits:
            papers = [hit.after_paper_id] if hit.after_paper_id else []
            archive.append(_event("judge", "hit", papers, hit.model_dump(), round))
            done[hit.direction_text] = hit

    run_parallel(call, todo, workers(), record)
    payload = {"count": len(done), "card_ids_sha": card_ids_sha(after), "label": label}
    archive.append(_event("judge", "step_done", [], payload, round))
    log.info("judge[%s]: %d hit(s), %d reused", label, len(done), len(done) - len(todo))
    return [done[d.text] for d in directions]


# ------------------------------------------------------------------ rates


def hit_rate(hits: list[Hit]) -> float:
    """Strict rate: n_hit / n, 0.0 when empty."""
    if not hits:
        return 0.0
    return sum(h.verdict == "hit" for h in hits) / len(hits)


def weighted_rate(hits: list[Hit]) -> float:
    """(n_hit + 0.5 * n_partial) / n, 0.0 when empty."""
    if not hits:
        return 0.0
    score = sum(1.0 if h.verdict == "hit" else 0.5 if h.verdict == "partial" else 0.0 for h in hits)
    return score / len(hits)


# ---------------------------------------------------------------- leakage


def _paper_ids_in(payload: Any) -> set[str]:
    """Every `paper_id` value nested anywhere in a payload."""
    found: set[str] = set()
    if isinstance(payload, dict):
        pid = payload.get("paper_id")
        if isinstance(pid, str):
            found.add(pid)
        for v in payload.values():
            found |= _paper_ids_in(v)
    elif isinstance(payload, list):
        for v in payload:
            found |= _paper_ids_in(v)
    return found


def assert_no_leakage(archive: Archive, after_ids: set[str]) -> None:
    """Raise if any club or baseline event names or quotes an after-T paper."""
    for e in archive.read():
        if e.type not in LEAK_TYPES:
            continue
        leaked = (set(e.papers) | _paper_ids_in(e.payload)) & after_ids
        if leaked:
            raise RuntimeError(f"leakage: event seq={e.seq} step={e.step} type={e.type} names after-T {sorted(leaked)}")


# ------------------------------------------------------------------ report


def _judge_model_name() -> str:
    """Judge model id for the report ("mock" under JC_LLM=mock)."""
    if os.environ.get("JC_LLM", "anthropic") == "mock":
        return "mock"
    return resolve_model("judge")


def _main_model_name() -> str:
    """Main model id for run_started ("mock" under JC_LLM=mock)."""
    if os.environ.get("JC_LLM", "anthropic") == "mock":
        return "mock"
    return resolve_model("main")


def _count(hits: list[Hit], verdict: str) -> int:
    """Hits with one verdict."""
    return sum(h.verdict == verdict for h in hits)


def _rejected(archive: Archive, step: Step) -> int:
    """direction_rejected events of a step."""
    return sum(e.type == "direction_rejected" for e in archive.by_step(step))


def _cell(s: str) -> str:
    """One-line, pipe-safe markdown table cell."""
    return " ".join(s.split()).replace("|", "\\|")


def _summary_row(arm: str, directions: list[Direction], hits: list[Hit], rejected: int) -> str:
    """One row of the summary table."""
    kept = len(directions)
    cells = [
        arm,
        str(kept + rejected),
        str(kept),
        str(_count(hits, "hit")),
        str(_count(hits, "partial")),
        str(_count(hits, "miss")),
        f"{hit_rate(hits):.2f}",
        f"{weighted_rate(hits):.2f}",
    ]
    return "| " + " | ".join(cells) + " |"


def _arm_table(title: str, hits: list[Hit], by_id: dict[str, PaperCard]) -> list[str]:
    """Audit table of one arm: every direction with its verdict and matched paper."""
    lines = [f"## {title}", "", "| # | direction | verdict | after paper (citekey, year) | reason |", "|---|---|---|---|---|"]
    if not hits:
        lines.append("| - | (none) | - | - | - |")
    for i, h in enumerate(hits, start=1):
        card = by_id.get(h.after_paper_id or "")
        paper = f"{card.citekey}, {card.year}" if card else "-"
        lines.append(f"| {i} | {_cell(h.direction_text)} | {h.verdict} | {_cell(paper)} | {_cell(h.reason)} |")
    return lines + [""]


def render_report(report: BacktestReport, after: list[PaperCard], club_rejected: int, baseline_rejected: int) -> str:
    """Markdown report.md: header, summary table, per-arm audit tables, closing note."""
    by_id = _cards_by_id(after)
    lines = [
        "# Backtest report",
        "",
        f"- T: {report.T}",
        f"- before-T papers: {', '.join(report.before_ids)}",
        f"- after-T papers: {', '.join(report.after_ids)}",
        f"- main model: {_main_model_name()}",
        f"- judge model: {report.judge_model}",
        "",
        "| arm | directions proposed | kept after quote gate | hits | partial | miss | strict rate | weighted rate |",
        "|---|---|---|---|---|---|---|---|",
        _summary_row("club", report.club_directions, report.club_hits, club_rejected),
        _summary_row("baseline", report.baseline_directions, report.baseline_hits, baseline_rejected),
        "",
    ]
    lines += _arm_table("Club", report.club_hits, by_id)
    lines += _arm_table("Baseline", report.baseline_hits, by_id)
    lines.append(REPORT_NOTE)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- backtest


def _start_run(
    archive: Archive,
    before: list[PaperCard],
    after: list[PaperCard],
    T: str,
    agenda: str,
    judge_model: str,
    round: int,
) -> None:
    """Append run_started (before-T snapshot only) and split on a fresh archive; check both shas when resuming."""
    sha = card_ids_sha(before)
    started = [e for e in archive.by_step("map") if e.type == "run_started"]
    if started:
        stored = started[-1].payload.get("card_ids_sha")
        if stored != sha:
            raise _resume_mismatch()(f"archive card set {stored} != current before-T card set {sha}")
        _check_card_contents(started[-1].payload, before)
        log.info("backtest: resuming archive %s", archive.path)
        return
    # Only the before-T cards are snapshotted: the archive stays a clean before-T artefact; after-T ids live in `split`.
    payload = {
        "agenda": agenda,
        "model": _main_model_name(),
        "judge_model": judge_model,
        "card_ids_sha": sha,
        "cards_sha": card_content_sha(before),
        "T": T,
        "cards": [c.model_dump() for c in before],
    }
    archive.append(_event("map", "run_started", [], payload, round))
    split = {"T": T, "before": [c.id for c in before], "after": [c.id for c in after]}
    archive.append(_event("backtest", "split", [], split, round))


def _club(before: list[PaperCard], llm: LLM, archive: Archive, agenda: str, judge_model: str, round: int) -> list[Direction]:
    """Default club arm: the full night (map -> debate -> directions) on the before-T cards."""
    from journal_club.night import run_night

    return run_night(before, llm, archive, agenda, round=round, judge_model=judge_model).directions


def run_backtest(
    cards: list[PaperCard],
    T: str,
    llm: LLM,
    archive: Archive,
    agenda: str,
    judge_llm: LLM | None = None,
    n_club: int = 8,
    n_baseline: int = 10,
    club_directions: ClubFn | None = None,
    round: int = 1,
) -> BacktestReport:
    """Split at T, run club and baseline on before-T, judge both on after-T, write report.md."""
    before, after = split_by_date(cards, T)
    judge_llm = judge_llm or get_llm("judge")
    judge_model = _judge_model_name()
    _start_run(archive, before, after, T, agenda, judge_model, round)
    if club_directions is None:
        club = _club(before, llm, archive, agenda, judge_model, round)
    else:
        club = club_directions(before)
    baseline = run_baseline(before, llm, archive, n=n_baseline, agenda=agenda, round=round)
    after_ids = {c.id for c in after}
    assert_no_leakage(archive, after_ids)
    club_hits = judge(club, after, judge_llm, archive, "club", round=round)
    baseline_hits = judge(baseline, after, judge_llm, archive, "baseline", round=round)
    report = BacktestReport(
        T=T,
        before_ids=[c.id for c in before],
        after_ids=sorted(after_ids),
        judge_model=judge_model,
        club_directions=club,
        baseline_directions=baseline,
        club_hits=club_hits,
        baseline_hits=baseline_hits,
        club_rate=hit_rate(club_hits),
        baseline_rate=hit_rate(baseline_hits),
        club_weighted_rate=weighted_rate(club_hits),
        baseline_weighted_rate=weighted_rate(baseline_hits),
    )
    archive.append(_event("backtest", "report", [], report.model_dump(), round))
    path = Path(archive.path).parent / "report.md"
    path.write_text(render_report(report, after, _rejected(archive, "directions"), _rejected(archive, "baseline")), encoding="utf-8")
    log.info("backtest: club %.2f vs baseline %.2f strict; report at %s", report.club_rate, report.baseline_rate, path)
    return report
