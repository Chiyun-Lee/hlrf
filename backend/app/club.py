"""Journal club (journal_club/): the papers of a card set become PhD-student agents that, in one night, map every pair
(agree / disagree / shared limitation), debate the clashes under a PI and write ranked research directions, each backed
by verbatim quotes. A backtest holds out the papers dated on or after T and scores the club's directions against them,
next to a one-call baseline, with a judge on a different model. The contract is journal_club/DESIGN.md.

Everything lives under JOURNAL_CLUB_DIR (default ~/.human-pretraining/journal-club): cards/<set>/*.json (one PaperCard
per paper) and runs/<name>/events.jsonl (the append-only archive, plus minutes.md and, for a backtest, report.md). Two
real runs on DESI papers and their card sets ship with the package (journal_club/examples/), so the tab shows something
before any Claude call. A run is a thread in this process; the archive is the truth, so a restart loses nothing: POST
the same run again and every finished step is rebuilt from the archive with no LLM calls. JC_LLM=mock in backend/.env
runs the deterministic offline backend in seconds (UI work, tests)."""

import inspect
import logging
import math
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError

from . import llm  # first: with LLM_BACKEND=claude-code it takes the API key out of the environment, so Claude Code uses your login
from . import db
from .schemas import Paper

import journal_club
from journal_club.archive import Event
from journal_club.cards import PaperCard, ingest_text, load_cards, load_fulltexts, sanitise_id, save_card
from journal_club.llm import default_backend
from journal_club.night import run_night
from journal_club.rounds.explore import CRITICS
from journal_club.rounds.map_round import workers
from journal_club.state import RunState, fold, read_events

log = logging.getLogger(__name__)
router = APIRouter(prefix="/club")

CLUB_DIR = Path(os.environ.get("JOURNAL_CLUB_DIR", "~/.human-pretraining/journal-club")).expanduser()
EXAMPLES = Path(journal_club.__file__).parent / "examples"
os.environ.setdefault("JC_CACHE_DIR", str(CLUB_DIR / "cache"))  # the club's LLM response cache, next to its runs
NAME = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"  # a run or card set name: also its folder
MAX_RUNNING = 2
MAX_PAPERS = 16  # a night maps every pair: 16 papers is 120 pairs

# How long a night takes, for the estimate before Start and the time left while it runs. Seconds, measured on a
# 9-paper night with the Claude Code login (claude-opus-5-5, JC_CONCURRENCY=4, 6.5 minutes in all): map calls finish
# in batches of JC_CONCURRENCY, a debate is one call at a time (each side speaks `turns` times, then the PI rules),
# directions and the overview (synthesis) are one long call each. The mock backend answers instantly. The exploration
# steps are estimates, not yet measured: hypotheses is one long call; round 2 reviews JC_CONCURRENCY hypotheses at a
# time (each: up to CRITICS critiques, then the PI's call, one after another), then plays its comparisons in batches.
TIMING = {"map_batch": 11.0, "debate_call": 9.0, "directions": 50.0, "hypotheses": 50.0, "critique_call": 9.0,
          "compare_batch": 8.0, "synthesis": 30.0}
_NIGHT = inspect.signature(run_night).parameters
DEBATE_CAP = _NIGHT["cap"].default  # disagreeing pairs debated per night
CALLS_PER_DEBATE = 2 * _NIGHT["turns"].default + 1
N_HYPOTHESES = _NIGHT["n_hypotheses"].default
BACKENDS = {"agent": "your Claude Code login", "anthropic": "the Anthropic API key", "mock": "the offline mock"}


class CardSet(BaseModel):
    """A folder of PaperCards, as GET /club/cards lists it."""

    name: str
    example: bool  # shipped with the package; can't be changed
    papers: list[dict]  # id, citekey, title, year, date of each card
    night_s: int  # about how long a night on this set takes with the current backend (estimate_night_s)
    ingesting: dict | None = None  # {done, total, failed, running} while being made from the library


class Progress(BaseModel):
    """Where a run is, for the progress line. Times come from the run folder: request.json is written when the run is
    started (or resumed), events.jsonl on every event."""

    step: str | None  # the step under way, None when the run isn't running
    done: int  # items of that step finished (pairs, disputes)
    total: int  # items that step will make (for debates, the cap until the map is done)
    elapsed_s: int | None  # since the run was last started, up to now or to its last event; None for shipped examples
    remaining_s: int | None  # estimate while running, None otherwise


class RunSummary(BaseModel):
    """One run, as the list shows it."""

    name: str
    example: bool
    kind: Literal["night", "backtest"]
    state: Literal["running", "done", "stopped", "failed"]  # stopped: not finished and not running (resume with POST)
    agenda: str
    model: str
    T: str | None
    n_cards: int
    n_directions: int
    n_disputes: int
    updated: str | None  # ISO 8601, the archive's last write
    error: str | None
    progress: Progress | None = None


class RunView(BaseModel):
    summary: RunSummary
    state: RunState


# --- estimates ---


def timing() -> dict[str, float]:
    return dict.fromkeys(TIMING, 0.0) if os.environ.get("JC_LLM") == "mock" else TIMING


def step_totals(n_cards: int, pairs: list[dict], map_done: bool, n_hypotheses: int | None = None) -> dict[str, int]:
    """Items each night step will make. Debates are the first DEBATE_CAP disagreeing pairs: counted once the map is
    done, and assumed to be the cap until then (both measured nights reached it; projecting from the first few pairs
    swung the estimate by minutes). Round 2 reviews every hypothesis kept, N_HYPOTHESES until they're known."""
    n_pairs = n_cards * (n_cards - 1) // 2
    disagree = sum(p.get("relation") == "disagree" for p in pairs) if map_done else DEBATE_CAP
    return {"map": n_pairs, "debate": min(DEBATE_CAP, disagree, n_pairs), "directions": 1, "hypotheses": 1,
            "critique": N_HYPOTHESES if n_hypotheses is None else n_hypotheses, "synthesis": 1}


def step_seconds(step: str, todo: int, t: dict[str, float], concurrency: int, total: int = 0) -> float:
    """Wall time for `todo` more items of a step (of `total`, for round 2's comparisons, which come after them all)."""
    if step == "map":
        return math.ceil(todo / concurrency) * t["map_batch"]
    if step == "debate":
        return todo * CALLS_PER_DEBATE * t["debate_call"]
    if step == "critique":
        matches = total * (total - 1) // 2
        return math.ceil(todo / concurrency) * (CRITICS + 1) * t["critique_call"] + math.ceil(matches / concurrency) * t["compare_batch"]
    return todo * t.get(step, 0.0)  # backtest-only steps (baseline, judge) aren't estimated


def estimate_night_s(n_cards: int) -> int:
    """About how long a fresh night on n_cards papers takes."""
    t, conc = timing(), workers()
    return round(sum(step_seconds(s, n, t, conc, n) for s, n in step_totals(n_cards, [], False).items()))


def progress(st: RunState, running: bool, started: float | None, last_write: float | None, now: float) -> Progress:
    """The run's step, its counts and the time left. The time spent since the last event counts against the time
    left, since an event lands only when a batch of pairs, a debate or a one-call step finishes."""
    elapsed = round((now if running else last_write) - started) if started and last_write else None
    if not running:
        return Progress(step=None, done=0, total=0, elapsed_s=elapsed, remaining_s=None)
    status = {s.name: s for s in st.steps}
    proposed = len(st.hypotheses) if "hypotheses" in status and status["hypotheses"].status == "done" else None
    totals = step_totals(len(st.cards), st.pairs, "map" in status and status["map"].status == "done", proposed)
    t, conc = timing(), workers()
    left = 0.0
    for s in st.steps:
        if s.status != "done":
            todo = max(0, totals.get(s.name, 0) - (s.count if s.status == "running" else 0))
            left += step_seconds(s.name, todo, t, conc, totals.get(s.name, 0))
    if left:
        left = max(left - (now - last_write if last_write else 0), 5.0)
    current = next((s for s in st.steps if s.status != "done"), None)
    return Progress(
        step=current.name if current else None,
        done=current.count if current and current.status == "running" else 0,
        total=totals.get(current.name, 0) if current else 0,
        elapsed_s=elapsed,
        remaining_s=round(left),
    )


# --- folders ---


def _named_dirs(kind: str) -> dict[str, tuple[Path, bool]]:
    """name -> (folder, example) for cards or runs: yours in CLUB_DIR first, then the shipped ones not shadowed by them."""
    found: dict[str, tuple[Path, bool]] = {}
    for base, example in ((CLUB_DIR / kind, False), (EXAMPLES / kind, True)):
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if d.is_dir() and d.name not in found and re.match(NAME, d.name):
                    found[d.name] = (d, example)
    return found


def card_dir(name: str) -> Path:
    if not (found := _named_dirs("cards").get(name)):
        raise HTTPException(404, f"No card set called {name}.")
    return found[0]


def run_dir(name: str) -> tuple[Path, bool]:
    if not (found := _named_dirs("runs").get(name)):
        raise HTTPException(404, f"No run called {name}.")
    return found


# --- card sets ---


def card_set(name: str, d: Path, example: bool) -> CardSet:
    papers = []
    for p in sorted(d.glob("*.json")):
        try:
            c = PaperCard.model_validate_json(p.read_text(encoding="utf-8"))
        except ValidationError:
            log.warning("card set %s: %s isn't a PaperCard; skipped", name, p.name)
            continue
        papers.append({"id": c.id, "citekey": c.citekey, "title": c.title, "year": c.year, "date": c.date})
    ingest = INGESTS.get(name)
    return CardSet(name=name, example=example, papers=papers, night_s=estimate_night_s(len(papers)), ingesting=ingest.progress if ingest else None)


@router.get("/cards")
def list_card_sets() -> list[CardSet]:
    """Every card set: yours, and the shipped DESI ones."""
    return [card_set(name, d, example) for name, (d, example) in _named_dirs("cards").items()]


class CardSetRequest(BaseModel):
    name: str = Field(pattern=NAME)
    paper_ids: list[int] = Field(min_length=1, max_length=MAX_PAPERS)  # library papers


def paper_text(paper: Paper) -> str:
    """A library paper's text, page by page; kept beside its card (<id>.txt) for the backtest's judge."""
    return "\n\n".join(b.text for page in paper.pages for b in page.blocks)


def card_from_paper(paper_id: int, paper: Paper, model) -> PaperCard:
    """A library paper's text through the club's ingest (one Claude call, quote-gated). Its id is its arXiv id when it
    has one, as a card id (2503.14738 -> 2503_14738)."""
    text = paper_text(paper)
    if not text.strip():
        raise ValueError("the paper has no text")
    return ingest_text(text, sanitise_id(paper.arxiv_id or f"paper{paper_id}"), str(paper.year or ""), model, source=paper.title)


class Ingest:
    """Makes one card set from library papers in a thread; progress for GET /club/cards."""

    def __init__(self, name: str, papers: list[tuple[int, Paper]]):
        self.name, self.papers, self.done, self.failed = name, papers, 0, []
        self.lock = threading.Lock()
        self.dir = CLUB_DIR / "cards" / name
        self.thread = threading.Thread(target=self.run, name=f"club-ingest-{name}", daemon=True)

    @property
    def progress(self) -> dict:
        return {"done": self.done, "total": len(self.papers), "failed": self.failed, "running": self.thread.is_alive()}

    def run(self) -> None:
        from journal_club.llm import get_llm

        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            model = get_llm()
        except Exception as e:  # no backend: every paper fails the same way
            log.exception("card set %s: no LLM", self.name)
            self.failed = [f"{title}: {type(e).__name__}: {e}" for _, p in self.papers for title in [p.title]]
            self.done = len(self.papers)
            return
        # One Claude call per paper, JC_CONCURRENCY of them at a time (as in the map round).
        with ThreadPoolExecutor(max_workers=workers(), thread_name_prefix=f"club-ingest-{self.name}") as pool:
            for _ in pool.map(lambda item: self.ingest_one(*item, model), self.papers):
                pass

    def ingest_one(self, pid: int, paper: Paper, model) -> None:
        try:
            save_card(card_from_paper(pid, paper, model), self.dir, fulltext=paper_text(paper))
        except Exception as e:
            log.exception("card set %s: paper %s failed", self.name, pid)
            with self.lock:
                self.failed.append(f"{paper.title}: {type(e).__name__}: {e}")
        with self.lock:
            self.done += 1


INGESTS: dict[str, Ingest] = {}
RUNNERS: dict[str, "Runner"] = {}


def not_ready() -> str | None:
    """Why a night or a card set can't start now, None when it can (JC_LLM set, e.g. mock, picks its own backend)."""
    return None if os.environ.get("JC_LLM") else llm.ready()


def check_llm() -> None:
    """503 when Claude can't be called with the current settings."""
    if reason := not_ready():
        raise HTTPException(503, reason)


class ClubConfig(BaseModel):
    """What the start form needs to know before anything runs."""

    ready: str | None  # not_ready()
    backend: str  # who answers the club's calls, in words
    debate_cap: int
    concurrency: int


@router.get("/config")
def config() -> ClubConfig:
    backend = os.environ.get("JC_LLM") or default_backend()
    return ClubConfig(ready=not_ready(), backend=BACKENDS.get(backend, backend), debate_cap=DEBATE_CAP, concurrency=workers())


@router.post("/cards", status_code=202)
def make_card_set(req: CardSetRequest) -> CardSet:
    """A card set from library papers: one Claude call per paper, in the background. GET /club/cards shows progress."""
    if req.name in _named_dirs("cards"):
        raise HTTPException(409, f"There's already a card set called {req.name}.")
    papers = []
    for pid in dict.fromkeys(req.paper_ids):
        if not (paper := db.get(pid)):
            raise HTTPException(404, f"No paper {pid} in the library.")
        papers.append((pid, paper))
    check_llm()
    INGESTS[req.name] = ingest = Ingest(req.name, papers)
    ingest.thread.start()
    return card_set(req.name, ingest.dir, False)


# --- runs ---


class RunRequest(BaseModel):
    name: str = Field(pattern=NAME)
    cards: str = Field(pattern=NAME)  # card set name
    agenda: str = Field(min_length=1, max_length=2000)  # what the club should look for tonight
    kind: Literal["night", "backtest"] = "night"
    t: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")  # backtest split: cards dated >= T are held out


class Runner:
    """One run in a thread. The archive is the truth: an exception is written to error.txt and the run is resumable."""

    def __init__(self, req: RunRequest, d: Path, cards_dir: Path):
        self.req, self.dir, self.cards_dir = req, d, cards_dir
        self.thread = threading.Thread(target=self.run, name=f"club-run-{req.name}", daemon=True)

    def run(self) -> None:
        from journal_club.archive import Archive
        from journal_club.backtest import run_backtest
        from journal_club.llm import get_llm
        from journal_club.minutes import write_minutes
        from journal_club.night import run_night

        try:
            cards = load_cards(self.cards_dir)
            with Archive(self.dir / "events.jsonl") as archive:
                model = get_llm()
                if self.req.kind == "night":
                    run_night(cards, model, archive, self.req.agenda)
                else:
                    run_backtest(cards, self.req.t, model, archive, self.req.agenda, fulltexts=load_fulltexts(self.cards_dir))
                write_minutes(archive, cards, self.dir / "minutes.md")
        except Exception as e:
            log.exception("run %s failed", self.req.name)
            (self.dir / "error.txt").write_text(f"{type(e).__name__}: {e}")


def running() -> list[str]:
    return [name for name, r in RUNNERS.items() if r.thread.is_alive()]


def summary(name: str, d: Path, example: bool, events: list[Event] | None = None) -> RunSummary:
    path = d / "events.jsonl"
    events = read_events(path) if events is None else events
    st = fold(events)
    error = (d / "error.txt").read_text() if (d / "error.txt").exists() else None
    is_running = name in running()
    state = "running" if is_running else "failed" if error else "done" if st.minutes_written else "stopped"
    last_write = path.stat().st_mtime if path.exists() else None
    started = (d / "request.json").stat().st_mtime if (d / "request.json").exists() else None
    updated = datetime.fromtimestamp(last_write, timezone.utc).isoformat(timespec="seconds") if last_write else None
    return RunSummary(
        name=name, example=example, kind=st.kind, state=state, agenda=st.agenda, model=st.model, T=st.T,
        n_cards=len(st.cards), n_directions=len(st.directions), n_disputes=len(st.disputes), updated=updated, error=error,
        progress=progress(st, is_running, started, last_write or started, time.time()),
    )


@router.get("/runs")
def list_runs() -> list[RunSummary]:
    """Every run, running ones first, then newest first."""
    found = [summary(name, d, example) for name, (d, example) in _named_dirs("runs").items()]
    return sorted(found, key=lambda r: (r.state == "running", r.updated or ""), reverse=True)


@router.post("/runs", status_code=202)
def start_run(req: RunRequest) -> RunSummary:
    """Start a night or a backtest in the background. POSTing an existing run again resumes it: finished steps are
    rebuilt from its archive with no LLM calls (a different card set is refused by the run itself)."""
    dirs = _named_dirs("runs")
    if req.name in dirs and dirs[req.name][1]:
        raise HTTPException(409, f"{req.name} is a shipped example; pick another name.")
    if req.name in running():
        raise HTTPException(409, f"{req.name} is already running.")
    if len(running()) >= MAX_RUNNING:
        raise HTTPException(409, f"{MAX_RUNNING} runs are already going; wait for one to finish.")
    if req.kind == "backtest" and not req.t:
        raise HTTPException(400, "A backtest needs the split date T (YYYY-MM-DD).")
    cards_dir = card_dir(req.cards)
    if not any(cards_dir.glob("*.json")):
        raise HTTPException(400, f"Card set {req.cards} is empty.")
    check_llm()
    d = CLUB_DIR / "runs" / req.name
    d.mkdir(parents=True, exist_ok=True)
    (d / "error.txt").unlink(missing_ok=True)
    (d / "request.json").write_text(req.model_dump_json(indent=2))
    RUNNERS[req.name] = runner = Runner(req, d, cards_dir)
    runner.thread.start()
    return summary(req.name, d, False)


@router.get("/runs/{name}")
def get_run(name: str) -> RunView:
    """The run and its folded state: cards, steps, pairs, disputes, directions, synthesis, backtest report."""
    d, example = run_dir(name)
    events = read_events(d / "events.jsonl")
    return RunView(summary=summary(name, d, example, events), state=fold(events))


@router.get("/runs/{name}/events")
def get_events(name: str, after: int = 0) -> list[Event]:
    """The archive itself, from seq `after` on (the live view polls with the last seq it has)."""
    d, _ = run_dir(name)
    return [e for e in read_events(d / "events.jsonl") if e.seq > after]


@router.get("/runs/{name}/minutes")
def get_minutes(name: str) -> Response:
    """minutes.md; rendered from the archive when the file isn't there (a run still going, or a shipped example)."""
    from journal_club.minutes import render_minutes

    d, _ = run_dir(name)
    if (d / "minutes.md").exists():
        text = (d / "minutes.md").read_text(encoding="utf-8")
    else:
        events = read_events(d / "events.jsonl")
        snapshot = next((e.payload.get("cards") for e in events if e.type == "run_started"), None)
        if snapshot is None:
            raise HTTPException(404, "The run hasn't started yet.")
        text = render_minutes(events, [PaperCard.model_validate(c) for c in snapshot])
    return Response(text, media_type="text/markdown; charset=utf-8")


@router.get("/runs/{name}/report")
def get_report(name: str) -> Response:
    """A backtest's report.md."""
    d, _ = run_dir(name)
    if not (d / "report.md").exists():
        raise HTTPException(404, "No report: not a backtest, or the judge hasn't finished.")
    return Response((d / "report.md").read_text(encoding="utf-8"), media_type="text/markdown; charset=utf-8")


@router.delete("/runs/{name}", status_code=204)
def delete_run(name: str) -> None:
    d, example = run_dir(name)
    if example:
        raise HTTPException(403, "Shipped examples can't be deleted.")
    if name in running():
        raise HTTPException(409, f"{name} is running; a run can't be stopped, wait for it to finish.")
    RUNNERS.pop(name, None)
    shutil.rmtree(d)
