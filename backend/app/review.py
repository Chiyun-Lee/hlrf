"""Agent review: Claude Code reviews a saved paper in the background, then writes a review for the reader (review.md)
and the paper's methods pins (pins.json, with the paper-pins skill). A full review also re-runs the authors' code and
tests the claims with the paper2agent skill (about 2 h); a quick one only reads the paper, the code and the data
(about 15 min).

Each review runs in its own detached process, `python -m app.review run <paper_id> <full|quick>` from backend/, so a
server restart doesn't stop it. Everything about it is a file in REVIEWS_DIR/<paper_id>/, outside the repo so the
agent picks up neither the repo's CLAUDE.md nor its git:
- status.json: the runner's, except the server's first write and its corrections once the runner is gone, so two
  processes never write it at once
- pid: the runner's process id, written by the server
- events.jsonl: one short line per thing the agent does, for the live view
- runner.log: everything, for debugging
- work/: the agent's working directory: paper.pdf, paper.txt, pages/ (each page as an image), targets.json, then the
  agent's review.md and pins.json
"""

import asyncio
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse

import pymupdf
from pydantic import BaseModel, ValidationError

from . import llm  # first: with LLM_BACKEND=claude-code it takes the API key out of the environment, so Claude Code uses your login
from . import db, feed, pins
from .schemas import Paper, PaperPins, Pin

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).parent.parent
REVIEWS_DIR = Path(os.environ.get("REVIEWS_DIR", "~/.human-pretraining/reviews")).expanduser()
MODEL = os.environ.get("REVIEW_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("REVIEW_EFFORT", "high")
SKILLS = {  # given to the agent as project skills, linked into work/.claude/skills
    "paper2agent": Path(os.environ.get("PAPER2AGENT_SKILL", "~/.claude/skills/paper2agent")).expanduser(),
    "paper-pins": BACKEND_DIR / "skills" / "paper-pins",
}
DEMO = os.environ.get("REVIEW_DEMO") == "1"  # replay a scripted review instead of calling Claude (UI work, tests)
DEMO_SECONDS = float(os.environ.get("REVIEW_DEMO_SECONDS", 45))
MAX_RUNNING = 2
TIME_LIMIT = {"full": 6 * 3600, "quick": 3600}  # seconds; a review still going after this is stopped
FIXES = 2  # times the agent is sent back to fix pins.json
HOUR_MS = str(3600 * 1000)
# Default tools an unattended review mustn't use: they outlive it (cron, wake-ups), reach past this machine (remote
# triggers, push notifications) or work on git outside the work dir (worktrees).
OFF_LIMITS = ["CronCreate", "CronDelete", "CronList", "ScheduleWakeup", "RemoteTrigger", "PushNotification",
              "EnterWorktree", "ExitWorktree", "DesignSync"]

# Each kind of review's stages, with the minutes each usually takes (for the progress bar).
STAGES = {
    "full": [
        ("Reading the paper", 15),
        ("Finding the code and data", 5),
        ("Setting up the code", 10),
        ("Re-running the authors' code", 45),
        ("Testing the claims", 30),
        ("Writing the review", 10),
        ("Pinning provenance and concerns", 5),
    ],
    "quick": [
        ("Reading the paper", 4),
        ("Checking the code and data", 5),
        ("Writing the review", 4),
        ("Pinning provenance and concerns", 2),
    ],
}


class Event(BaseModel):
    """One line of the live view."""

    n: int  # 0-based sequence number
    t: float  # seconds since the review started
    kind: Literal["stage", "tool", "text", "error", "done"]
    text: str  # one short line
    sub: bool = False  # came from a helper agent


class Status(BaseModel):
    """A review as GET /papers/{id}/review shows it."""

    state: Literal["running", "done", "failed", "stopped"]
    depth: Literal["full", "quick"]
    started_at: str  # ISO 8601
    finished_at: str | None
    elapsed: float  # seconds
    stages: list[str]
    stage: int  # 1-based; len(stages) when done
    progress: float  # 0..1
    events: list[Event]  # those with n >= after, at most the newest 200
    n_events: int
    pins: int | None  # pins written, when done
    verdict: str | None
    report: bool  # review.md exists
    error: str | None


class CantStart(Exception):
    """Why a review can't start; `status` is its HTTP status (400 or 409)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Failed(Exception):
    """A review that can't go on, with a message for the reader."""


# --- files ---


def folder(paper_id: int) -> Path:
    return REVIEWS_DIR / str(paper_id)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ts(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def read(paper_id: int) -> dict | None:
    with suppress(FileNotFoundError):
        return json.loads((folder(paper_id) / "status.json").read_text())
    return None


def update(paper_id: int, **changes) -> dict:
    """Change status.json, atomically (a temp file renamed over it), so a reader never sees half of it."""
    st = {**(read(paper_id) or {}), **changes}
    path = folder(paper_id) / "status.json"
    tmp = path.with_name(f"status.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(st))
    os.replace(tmp, path)
    return st


def read_events(paper_id: int, after: int = 0) -> tuple[list[dict], int]:
    """Events numbered `after` on (the newest 200 at most), and how many there are. Event n is line n."""
    try:
        lines = (folder(paper_id) / "events.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)
    except FileNotFoundError:
        return [], 0
    if lines and not lines[-1].endswith("\n"):  # being written right now
        lines.pop()
    return [json.loads(line) for line in lines[max(after, len(lines) - 200, 0) :]], len(lines)


def report(paper_id: int) -> str | None:
    """The review (review.md), once the agent has written it."""
    path = folder(paper_id) / "work" / "review.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


# --- status, as the server reports it ---


def expected(depth: str) -> list[float]:
    """Seconds each stage usually takes; a demo squeezes them into DEMO_SECONDS."""
    minutes = [m for _, m in STAGES[depth]]
    scale = DEMO_SECONDS / (60 * sum(minutes)) if DEMO else 1
    return [60 * m * scale for m in minutes]


def ended(st: dict) -> float:
    return ts(st["finished_at"]) if st.get("finished_at") else time.time()


def progress(st: dict, end: float) -> float:
    """(stage - 1 + creep) / stages, where creep grows with the time spent in the stage up to 0.9 of it: the bar keeps
    moving while a stage runs long, but only fills a stage's share when the next one starts."""
    if st["state"] == "done":
        return 1.0
    seconds = expected(st["depth"])
    k = st["stage"]
    creep = min(0.9, max(0.0, end - ts(st["stage_started_at"])) / seconds[k - 1])
    return (k - 1 + creep) / len(seconds)


def current(paper_id: int) -> dict | None:
    """status.json, with a review whose runner died (crashed, killed, the machine restarted) marked failed."""
    st = read(paper_id)
    if st and st["state"] == "running" and not runner_alive(paper_id):
        st = read(paper_id)  # it may have finished just now
        if st["state"] == "running":
            log_path = folder(paper_id) / "runner.log"
            st = update(paper_id, state="failed", finished_at=now(), error=f"The review stopped unexpectedly; see {log_path}.")
    return st


def status(paper_id: int, after: int = 0) -> Status | None:
    """The paper's review, with its live view from event `after` on; None if it was never reviewed."""
    if not (st := current(paper_id)):
        return None
    end = ended(st)
    events, n = read_events(paper_id, after)
    return Status(
        **st,
        elapsed=round(end - ts(st["started_at"]), 1),
        stages=[title for title, _ in STAGES[st["depth"]]],
        progress=round(progress(st, end), 4),
        events=events,
        n_events=n,
        report=(folder(paper_id) / "work" / "review.md").exists(),
    )


def all_reviews() -> dict[str, dict]:
    """{paper_id: {state, depth, progress, stage_title}} for every paper with a review, running or finished."""
    reviews = {}
    for path in sorted(REVIEWS_DIR.glob("*/status.json"), key=lambda p: p.parent.name):
        if path.parent.name.isdigit() and (st := current(int(path.parent.name))):
            reviews[path.parent.name] = {
                "state": st["state"],
                "depth": st["depth"],
                "progress": round(progress(st, ended(st)), 4),
                "stage_title": STAGES[st["depth"]][st["stage"] - 1][0],
            }
    return reviews


# --- the runner process, from the server's side ---


def pid_of(paper_id: int) -> int | None:
    with suppress(FileNotFoundError, ValueError):
        return int((folder(paper_id) / "pid").read_text())
    return None


def alive(pid: int, paper_id: int) -> bool:
    """Whether this pid is still this paper's runner. The command line is checked too: after a reboot the pid may
    belong to another process, which Stop must never signal."""
    if os.name == "nt":
        return str(pid) in subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    command = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
    return f"app.review run {paper_id} " in command


def runner_alive(paper_id: int) -> bool:
    pid = pid_of(paper_id)
    return pid is None or alive(pid, paper_id)  # no pid yet: the server is starting it this instant


def kill(pid: int, hard: bool = False) -> None:
    """Signal the runner and everything it started (Claude Code, the agent's commands): it leads its own process group."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        return
    with suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGKILL if hard else signal.SIGTERM)


def spawn(paper_id: int, depth: str) -> subprocess.Popen:
    """Start the runner detached from the server (its own session and process group), so a `uvicorn --reload`
    restart doesn't take it down."""
    detach = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    with open(folder(paper_id) / "runner.log", "ab") as out:
        return subprocess.Popen(
            [sys.executable, "-m", "app.review", "run", str(paper_id), depth],
            cwd=BACKEND_DIR, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, **detach,
        )


def skills_for(depth: str) -> list[str]:
    return ["paper2agent", "paper-pins"] if depth == "full" else ["paper-pins"]


def cant_start(paper_id: int, depth: str) -> str | None:
    """Why this review can't start (a 400), or None."""
    if not db.has_pdf(paper_id):
        return "This paper has no PDF: save the PDF version first."
    if DEMO:
        return None
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return "The review runs Claude Code through the Claude Agent SDK: run `uv sync --extra claude-code` in backend/."
    for name in skills_for(depth):
        if not (SKILLS[name] / "SKILL.md").exists():
            if name == "paper2agent":
                return f"A full review needs the paper2agent skill: install it at {SKILLS[name]} (or set PAPER2AGENT_SKILL in backend/.env), or run a quick review."
            return f"The {name} skill is missing: expected {SKILLS[name] / 'SKILL.md'}."
    return None


def begin(paper_id: int, depth: str) -> None:
    """A fresh status.json and live view (an earlier review's work/ stays, for the agent to reuse)."""
    path = folder(paper_id)
    path.mkdir(parents=True, exist_ok=True)
    for name in ("status.json", "events.jsonl", "runner.log", "pid"):
        (path / name).unlink(missing_ok=True)
    stamp = now()
    update(paper_id, state="running", depth=depth, started_at=stamp, finished_at=None, stage=1, stage_started_at=stamp,
           pins=None, verdict=None, error=None)


starting = threading.Lock()  # one start or stop at a time: two quick clicks mustn't start two runners


def start(paper_id: int, depth: str) -> Status:
    with starting:
        if (st := current(paper_id)) and st["state"] == "running":
            raise CantStart(409, "This paper's review is already running.")
        if sum(r["state"] == "running" for r in all_reviews().values()) >= MAX_RUNNING:
            raise CantStart(409, f"{MAX_RUNNING} reviews are already running: wait for one to finish, or stop one.")
        if reason := cant_start(paper_id, depth):
            raise CantStart(400, reason)
        begin(paper_id, depth)
        (folder(paper_id) / "pid").write_text(str(spawn(paper_id, depth).pid))
    return status(paper_id)


def stop(paper_id: int) -> None:
    """Stop the paper's review if it's running: SIGTERM, and the runner records itself stopped; SIGKILL if it's still
    there 10 s later."""
    with starting:
        if not (st := current(paper_id)) or st["state"] != "running":
            return
        if pid := pid_of(paper_id):
            for hard, wait in ((False, 10), (True, 5)):
                kill(pid, hard)
                deadline = time.time() + wait
                while alive(pid, paper_id) and time.time() < deadline:
                    time.sleep(0.25)
                if not alive(pid, paper_id):
                    break
        if read(paper_id)["state"] == "running":  # killed before it could say so (and always on Windows)
            update(paper_id, state="stopped", finished_at=now())


def discard(paper_id: int) -> None:
    """Stop the paper's review and delete its files, as the paper is deleted (SQLite may give its id to the next one)."""
    stop(paper_id)
    shutil.rmtree(folder(paper_id), ignore_errors=True)


# --- the runner process itself ---


class Run:
    """One review, from inside its runner."""

    def __init__(self, paper_id: int, depth: str):
        self.paper_id, self.depth = paper_id, depth
        self.stages = [title for title, _ in STAGES[depth]]
        self.work = folder(paper_id) / "work"
        self.started = ts(read(paper_id)["started_at"])
        self.n = read_events(paper_id)[1]  # events so far
        self.paper: Paper | None = None
        self.found = []  # the PinTargets found in the PDF

    def event(self, kind: str, text: str, sub: bool = False) -> None:
        line = json.dumps({"n": self.n, "t": round(time.time() - self.started, 1), "kind": kind, "text": text, "sub": sub})
        with open(folder(self.paper_id) / "events.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self.n += 1

    def stage(self, k: int, note: str = "") -> None:
        """Start stage k: the bar moves on (never back) and the live view says so."""
        if k > read(self.paper_id)["stage"]:
            update(self.paper_id, stage=k, stage_started_at=now())
        self.event("stage", f"Stage {k}/{len(self.stages)} · {self.stages[k - 1]}")
        if note.strip():
            self.event("text", one_line(note))

    def check(self) -> tuple[PaperPins | None, list[str]]:
        """pins.json, and what's wrong with it ([] when nothing)."""
        path = self.work / "pins.json"
        if not path.exists():
            return None, ["pins.json is missing: write it with the paper-pins skill."]
        try:
            found = PaperPins.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as e:
            return None, [f"pins.json doesn't fit the PaperPins schema: {e}"]
        missing = ["no `claims`: give the paper's main claims as the re-run and the tests left them (the paper-pins "
                   "skill, Reproduction card)"] if self.depth == "full" and not found.claims else []
        return found, missing + pins.problems(found, self.paper, self.found)


def pages_text(paper: Paper) -> str:
    return "\n\n".join(f"=== Page {i} ===\n\n" + "\n\n".join(b.text for b in p.blocks) for i, p in enumerate(paper.pages, 1))


def render_pages(pdf: bytes, out: Path) -> None:
    """Each page as a PNG, so the agent can look at figures and equations (Claude Code's Read renders PDF pages only
    where poppler is installed)."""
    out.mkdir(exist_ok=True)
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        for i, page in enumerate(doc, 1):
            page.get_pixmap(dpi=120).save(out / f"page-{i:03}.png")


def prepare(run: Run) -> None:
    """Fill the work dir: the paper, its text and its pages as images, the figures and tables to pin, and the skills.
    Files an earlier review left (a cloned repository, environments) stay for the agent to reuse; its review and pins
    don't."""
    paper, pdf = db.get(run.paper_id), db.get_pdf(run.paper_id)
    if not paper or not pdf:
        raise Failed("This paper or its PDF is no longer in the library.")
    run.paper, run.found = paper, pins.targets(paper, pdf)
    run.work.mkdir(parents=True, exist_ok=True)
    for name in ("review.md", "pins.json"):
        (run.work / name).unlink(missing_ok=True)
    (run.work / "paper.pdf").write_bytes(pdf)
    (run.work / "paper.txt").write_text(pages_text(paper), encoding="utf-8")
    try:
        render_pages(pdf, run.work / "pages")
    except Exception as e:  # the text is enough to go on
        log.exception("couldn't render the pages of paper %s", run.paper_id)
        run.event("error", one_line(f"Couldn't render the pages as images: {e}"))
    (run.work / "targets.json").write_text(json.dumps([t.model_dump() for t in run.found], indent=1))
    skills = run.work / ".claude" / "skills"
    shutil.rmtree(skills, ignore_errors=True)  # removes the old links, not what they point to
    skills.mkdir(parents=True)
    if not DEMO:
        for name in skills_for(run.depth):
            try:
                (skills / name).symlink_to(SKILLS[name], target_is_directory=True)
            except OSError:  # Windows without the right to make symlinks
                shutil.copytree(SKILLS[name], skills / name)
    run.event("text", f"Ready: the paper's text, its {len(paper.pages)} pages as images, {len(run.found)} figures and tables to pin")


async def run_review(paper_id: int, depth: str) -> None:
    """The whole review; it ends done, failed or stopped (a cancel: Stop's SIGTERM)."""
    run = Run(paper_id, depth)
    limit = asyncio.timeout(TIME_LIMIT[depth])
    try:
        async with limit:
            prepare(run)
            found = await (demo(run) if DEMO else agent(run))
        pins.save(paper_id, found)
    except asyncio.CancelledError:
        run.event("error", "Stopped")
        update(paper_id, state="stopped", finished_at=now())
        return
    except Exception as e:
        if isinstance(e, TimeoutError) and limit.expired():
            error = f"The review ran past its {TIME_LIMIT[depth] // 3600} h limit, so it was stopped."
        elif isinstance(e, Failed):
            error = str(e)
        else:
            log.exception("review of paper %s failed", paper_id)
            error = f"{type(e).__name__}: {e}"
        run.event("error", one_line(error))
        update(paper_id, state="failed", finished_at=now(), error=error)
        return
    n = sum(len(t.pins) for t in found.targets)
    run.event("done", f"Saved {n} pins on {len(found.targets)} figures and tables")
    update(paper_id, state="done", finished_at=now(), stage=len(run.stages), pins=n, verdict=getattr(found, "verdict", None))


async def detached(paper_id: int, depth: str) -> None:
    with suppress(NotImplementedError):  # no loop signal handlers on Windows; stop() marks the review stopped itself
        asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, asyncio.current_task().cancel)
    await run_review(paper_id, depth)


def main(argv: list[str]) -> None:
    """`python -m app.review run <paper_id> <full|quick>`: started by start(), or by hand to debug (logs to stderr)."""
    if len(argv) != 3 or argv[0] != "run" or not argv[1].isdigit() or argv[2] not in STAGES:
        sys.exit("usage: python -m app.review run <paper_id> <full|quick>")
    paper_id, depth = int(argv[1]), argv[2]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if (read(paper_id) or {}).get("state") != "running":  # started by hand: make it visible in the app too
        begin(paper_id, depth)
        (folder(paper_id) / "pid").write_text(str(os.getpid()))
    asyncio.run(detached(paper_id, depth))


# --- the agent ---

RULES = """\
You are reviewing a research paper, unattended, for the readers of a paper-reading app. Nobody can answer questions:
make reasonable calls yourself and say in the review what you decided.

Rules (pass them on to every helper agent you start):
- Work only inside your working directory (the work dir). Never create, change or delete anything outside it, never
  git push, and install nothing system-wide: make environments in the work dir (`uv venv`, `python -m venv`); package
  caches already point into it.
- Keep every command under about 60 minutes. Where the paper's settings would take longer (long chains, big grids),
  shorten them, and say in the review what you shortened and how.
- Be honest about what you did and didn't check: never present a claim as tested when you only read it.

The work dir holds paper.pdf; paper.txt, its text page by page; pages/page-001.png and on, each page as an image
(Read them to see figures and equations); and targets.json, the paper's figures and tables as found in this PDF
(label, page, caption start, box in PDF points). An earlier, unfinished review of this paper may have left files here
(a cloned repository, environments, paper2agent output): reuse what is sound rather than redoing it.

Call the `stage` tool at the start of each stage below, in order, with its number and a one-line note of what you are
about to do.
"""

STEPS = {
    "full": """\
1. Reading the paper: build the paper skill from paper.pdf with the paper2agent skill (its Paper2Skill part), and note
   the claims, data and methods that matter.
2. Finding the code and data: find the authors' code (links in the paper, its arXiv page, GitHub) and pin the commit;
   find where each dataset comes from and which version was used. If there is no code, say so and test what you can.
3. Setting up the code: Paper2MCP's first stage on the repository (environment and tool selection).
4. Re-running the authors' code: re-run it at the paper's settings and compare its numbers and figures with the
   paper's; build and verify the MCP tools (the rest of Paper2MCP).
5. Testing the claims: test the main claims with the MCP tools paper2agent built (call them from scripts, e.g. with
   fastmcp's Client over stdio) and short scripts of your own: a mock with a known answer, other reasonable priors and
   cuts, the significance measure, where the data come from. Keep every script and its output in checks/.
6. Writing the review: write review.md (below).
7. Pinning provenance and concerns: write pins.json (below).
""",
    "quick": """\
This is a quick review: never run the authors' code, or analysis code of your own. Read the paper, the repository and
the data sources; fetching and searching them (git clone, grep) is fine.
1. Reading the paper: read paper.txt, and the page images for the figures and equations; note the claims, data and
   methods that matter.
2. Checking the code and data: find the authors' code (links in the paper, its arXiv page, GitHub) and the data
   sources, and read them. Do the settings, priors, cuts and data versions match the paper? Is anything missing?
3. Writing the review: write review.md (below), saying plainly that nothing was re-run.
4. Pinning provenance and concerns: write pins.json (below).
""",
}

OUTPUTS = """
review.md is for a reader of the paper. Start with a title and one line giving the authors, the arXiv id and the code
(repository @ commit), then say how the paper was checked. Then these sections: ## What the paper claims; ## What the
code does; ## Reproducibility (the paper's numbers against the re-run's, in a table where useful, or what reading could
establish); ## Main problems (numbered, most important first, each with its evidence and how far it was checked);
## Bottom line (what holds, what doesn't, what would settle it); ## Evidence (paths in the work dir, or links, behind
each point).

pins.json: write it with the paper-pins skill, giving every target in targets.json its pins. Set `reviewed` to what
the pins rest on (what was done, then the date) and `verdict` to the review's bottom line in 1-2 sentences. Give
`main_problems` from ## Main problems, and in a full review `claims`: the paper's main claims, each with the paper's
number, the re-run's or the test's, and whether it holds. They fill the paper's Reproduction summary card. The
skill's `python -m app.pins` commands are for interactive use: here targets.json lists the targets, and the
`check_pins` tool checks pins.json. Fix pins.json until check_pins returns ok, then end with the verdict.
"""


def brief(depth: str) -> str:
    """What the agent is told, after Claude Code's own system prompt."""
    return RULES + STEPS[depth] + OUTPUTS


def task(run: Run) -> str:
    p = run.paper
    authors = ", ".join(a.raw for a in p.authors[:8]) + (" et al." if len(p.authors) > 8 else "")
    arxiv = feed.arxiv_id(p.url, p.arxiv_id)
    return (
        f'Do a {run.depth} review of "{p.title}"' + (f" by {authors}" if authors else "")
        + (f", arXiv:{arxiv}" if arxiv else "") + f" ({p.url}). It is paper.pdf in the work dir."
    )


def fix_prompt(problems: list[str]) -> str:
    return (
        "pins.json isn't finished. check_pins reports:\n- " + "\n- ".join(problems)
        + "\nFix pins.json with the paper-pins skill and call check_pins until it returns ok, then end with the verdict."
    )


def reply(text: str, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "is_error": error}


def review_tools(run: Run) -> list:
    """The agent's tools for the app: `stage`, which moves the progress bar, and `check_pins`."""
    from claude_agent_sdk import tool

    @tool(
        "stage",
        "Call at the start of each review stage, in order: it moves the reader's progress bar.",
        {"stage": Annotated[int, "the stage's number, from 1"], "note": Annotated[str, "one line: what you are about to do"]},
    )
    async def stage(args: dict) -> dict:
        k = args["stage"]
        if not 1 <= k <= len(run.stages):
            return reply(f"stage must be 1 to {len(run.stages)}", error=True)
        run.stage(k, args["note"])
        return reply(f"Stage {k}/{len(run.stages)}: {run.stages[k - 1]}")

    @tool("check_pins", "Check pins.json against targets.json and the pin rules: returns ok, or the problems to fix.", {})
    async def check_pins(args: dict) -> dict:
        return reply("\n".join(run.check()[1]) or "ok")

    return [stage, check_pins]


def options(run: Run, resume: str | None = None, **extra):
    """Claude Code on the work dir with its default tools, our two skills and our two tools, unattended."""
    from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server

    cache = run.work / ".cache"
    return ClaudeAgentOptions(
        system_prompt={"type": "preset", "preset": "claude_code", "append": brief(run.depth)},
        tools={"type": "preset", "preset": "claude_code"},
        disallowed_tools=OFF_LIMITS,
        skills=skills_for(run.depth),
        setting_sources=["project"],  # only the work dir's .claude/ (our skills): none of your own settings or skills
        mcp_servers={"review": create_sdk_mcp_server("review", tools=review_tools(run))},
        strict_mcp_config=True,
        permission_mode="bypassPermissions",  # nobody is there to approve tool calls
        cwd=run.work,
        model=MODEL,
        effort=EFFORT,
        forward_subagent_text=True,  # helpers' text in the live view too
        resume=resume,
        stderr=lambda line: log.info("claude: %s", line),
        max_buffer_size=llm.MAX_MESSAGE,  # big tool results (PDF pages, images, logs)
        env={
            # As in llm.ask_claude_code: no memory writes, none of your claude.ai connectors.
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
            "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
            # Package caches and downloaded Pythons go in the work dir, not your home.
            "UV_CACHE_DIR": str(cache / "uv"),
            "UV_PYTHON_INSTALL_DIR": str(cache / "python"),
            "PIP_CACHE_DIR": str(cache / "pip"),
            "XDG_CACHE_HOME": str(cache),
            "MPLCONFIGDIR": str(cache / "matplotlib"),
            # Let a command run up to an hour (default 10 min), and wait as long for background work after a turn.
            "BASH_MAX_TIMEOUT_MS": HOUR_MS,
            "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS": HOUR_MS,
        },
        **extra,
    )


def check_init(run: Run, init: dict) -> None:
    """Stop at once, not hours later, if Claude Code didn't find our skills (a broken link, say) or tools."""
    if missing := [s for s in skills_for(run.depth) if s not in init.get("skills", [])]:
        raise Failed(f"Claude Code didn't find the {' and '.join(missing)} skill in {run.work / '.claude' / 'skills'}.")
    if "mcp__review__stage" not in init.get("tools", []):
        raise Failed("Claude Code didn't load the review's stage and check_pins tools.")


async def converse(run: Run, prompt: str, resume: str | None = None, **extra):
    """One Claude Code session (or a resumed one), streamed into the live view. Returns its last ResultMessage."""
    from claude_agent_sdk import ResultMessage, SystemMessage, query

    result = None
    try:
        async for message in query(prompt=prompt, options=options(run, resume, **extra)):
            if isinstance(message, SystemMessage) and message.subtype == "init":
                check_init(run, message.data)
            if not (isinstance(message, SystemMessage) and message.subtype == "thinking_tokens"):  # one a second
                log.info("%r", message)
            sub = getattr(message, "parent_tool_use_id", None) is not None
            for kind, text in describe(message, run.work):
                run.event(kind, text, sub)
            if isinstance(message, ResultMessage):
                result = message
    except Exception as e:
        # query() yields an error result and then raises (as in llm.py); the result says what went wrong.
        if result is None or not result.is_error:
            raise
        log.info("Claude Code raised after its error result: %r", e)
    return result


def outcome(result) -> str:
    """What went wrong, from Claude Code's last result."""
    return "no result" if result is None else "; ".join(result.errors or []) or result.result or result.subtype


async def agent(run: Run) -> PaperPins:
    """Run the review, then send the agent back to fix pins.json while check_pins finds problems (FIXES times)."""
    prompt, session = task(run), None
    for fix in range(FIXES + 1):
        result = await converse(run, prompt, resume=session)
        found, problems = run.check()
        if not problems:
            return found
        if result is None or result.is_error:
            raise Failed(f"Claude Code stopped: {outcome(result)}")
        if fix < FIXES:
            run.event("error", f"pins.json has {len(problems)} problem(s): sending the agent back to fix them")
            prompt, session = fix_prompt(problems), result.session_id
    raise Failed(f"pins.json still has problems after {FIXES} fixes: " + "; ".join(problems[:3]))


# --- the live view: one short line per message ---


def one_line(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def shown_path(path: str, work: Path) -> str:
    for base in (work, work.resolve()):
        with suppress(ValueError):
            return str(Path(path).relative_to(base))
    return path.replace(str(Path.home()), "~", 1)


def tool_line(name: str, args: dict, work: Path) -> str | None:
    """What a tool call does, in a few words, or None to leave it out."""
    path = shown_path(args.get("file_path") or args.get("notebook_path") or args.get("path") or "", work)
    match name:
        case "Bash":
            return one_line(args.get("description") or (args.get("command") or "").strip().split("\n")[0], 200)
        case "Read":
            return f"Reading {path}"
        case "Write":
            return f"Writing {path}"
        case "Edit" | "MultiEdit" | "NotebookEdit":
            return f"Editing {path}"
        case "Glob" | "Grep":
            return one_line(f"Searching for {args.get('pattern', '')}", 200)
        case "WebFetch":
            url = urlparse(args.get("url", ""))
            return one_line(f"Fetching {url.netloc}{url.path}", 200)
        case "WebSearch":
            return one_line(f"Searching the web: {args.get('query', '')}", 200)
        case "Agent" | "Task":
            return one_line(f"Helper: {args.get('description', '')}", 200)
        case "Skill":
            return f"Using the {args.get('skill') or args.get('name')} skill"
        case "TodoWrite":
            doing = [t for t in args.get("todos", []) if t.get("status") == "in_progress"]
            return one_line(doing[0].get("activeForm") or doing[0].get("content", ""), 200) if doing else None
        case "mcp__review__stage" | "ToolSearch":  # the stage tool adds its own event; ToolSearch only loads tools
            return None
        case "mcp__review__check_pins":
            return "Checking the pins"
        case _:
            return f"Using {name}"


def tool_error(content) -> str:
    text = content if isinstance(content, str) else " ".join(c.get("text", "") for c in content or [] if isinstance(c, dict))
    return one_line(re.sub(r"</?tool_use_error>", "", text) or "Tool error", 200)


def duration(seconds: float) -> str:
    h, m, s = int(seconds // 3600), int(seconds % 3600 // 60), int(seconds % 60)
    return f"{h} h {m} min" if h else f"{m} min {s} s" if m else f"{s} s"


def describe(message, work: Path) -> list[tuple[str, str]]:
    """The live view's lines for one message from Claude Code, as (kind, text). Tool results only when they failed."""
    from claude_agent_sdk import (AssistantMessage, RateLimitEvent, ResultMessage, TaskNotificationMessage, TextBlock,
                                  ToolResultBlock, ToolUseBlock, UserMessage)

    lines = []
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock) and block.text.strip():
                lines.append(("text", one_line(block.text)))
            elif isinstance(block, ToolUseBlock) and (line := tool_line(block.name, block.input or {}, work)):
                lines.append(("tool", line))
    elif isinstance(message, UserMessage) and isinstance(message.content, list):
        lines += [("error", tool_error(b.content)) for b in message.content if isinstance(b, ToolResultBlock) and b.is_error]
    elif isinstance(message, ResultMessage):
        text = f"Agent {'stopped with an error' if message.is_error else 'finished'} after {duration(message.duration_ms / 1000)}, {message.num_turns} turns"
        if llm.BACKEND != "claude-code" and message.total_cost_usd:  # on the subscription the cost isn't billed
            text += f", ${message.total_cost_usd:.2f}"
        lines.append(("done", text))
    elif isinstance(message, TaskNotificationMessage):  # a helper working in the background is done
        lines.append(("text", one_line(f"Helper {message.status}: {message.summary}")))
    elif isinstance(message, RateLimitEvent) and (limit := message.rate_limit_info).status != "allowed":
        resets = f" (resets at {datetime.fromtimestamp(limit.resets_at):%H:%M})" if limit.resets_at else ""
        lines.append(("error", f"Claude usage limit reached{resets}") if limit.status == "rejected"
                     else ("text", f"Close to the Claude usage limit{resets}"))
    return lines


# --- demo: REVIEW_DEMO=1 replays a scripted review, without Claude ---

DEMO_LINES = {  # per stage: (kind, text, from a helper)
    "full": [
        [("tool", "Reading paper.txt", False), ("tool", "Using the paper2agent skill", False),
         ("tool", "Helper: review pages 1-4 of the paper", False), ("tool", "Reading paper-review/pages/p001.json", True),
         ("text", "Pages 1-4 reviewed: one equation needs checking against the source.", True),
         ("text", "The headline claim rests on one table and two figures.", False)],
        [("tool", "Fetching arxiv.org/abs/0000.00000", False), ("tool", "Searching the web: authors' code repository", False),
         ("tool", "Clone the authors' repository", False),
         ("text", "Found the code and pinned its commit; one data file isn't in the repository.", False)],
        [("tool", "Helper: set up the environment", False), ("tool", "Create a virtual environment in the work dir", True),
         ("error", "pip install failed: no matching distribution for an old pinned version", True),
         ("tool", "Install the nearest available version instead", True)],
        [("tool", "Helper: re-run the main notebook", False),
         ("tool", "Run the notebook at the paper's settings (chains shortened to 1 h)", True),
         ("text", "The re-run matches the paper's table to the quoted precision.", True),
         ("tool", "Helper: build and verify the MCP tools", False), ("tool", "Writing src/tools/analysis.py", True)],
        [("tool", "Writing checks/mock_known_answer.py", False),
         ("tool", "Fit a mock with a known answer through the MCP tools", False),
         ("text", "The mock recovers its input only when the priors are wider than the paper's.", False),
         ("tool", "Writing checks/wider_priors.py", False)],
        [("tool", "Writing review.md", False), ("text", "Review written: three main problems, one serious.", False)],
        [("tool", "Using the paper-pins skill", False), ("tool", "Writing pins.json", False), ("tool", "Checking the pins", False)],
    ],
    "quick": [
        [("tool", "Reading paper.txt", False), ("tool", "Reading paper.pdf", False),
         ("text", "The headline claim rests on one table and two figures.", False)],
        [("tool", "Fetching arxiv.org/abs/0000.00000", False), ("tool", "Searching the web: authors' code repository", False),
         ("error", "Fetching zenodo.org/records/0000000: 404 Not Found", False),
         ("text", "The repository's priors differ from those stated in the paper.", False)],
        [("tool", "Writing review.md", False)],
        [("tool", "Using the paper-pins skill", False), ("tool", "Writing pins.json", False), ("tool", "Checking the pins", False)],
    ],
}

DEMO_REVIEW = """# Demo review: {title}

REVIEW_DEMO=1 replayed a scripted review: no agent read this paper, so nothing here is about it.

## What the paper claims
A real review starts with the paper's claims and the data and methods behind them.

## What the code does
Then what the authors' code actually does, and where it differs from the paper.

## Reproducibility
The paper's numbers against the re-run's.

## Main problems
1. Each problem with its evidence, and how far it was checked.

## Bottom line
What holds, what doesn't, and what would settle it.
"""


DEMO_CLAIM = {"claim": "Demo claim: a real review lists the paper's main claims here.", "paper": "As printed",
              "rerun": "The re-run's number", "status": "holds", "check": "Written by REVIEW_DEMO=1, without calling Claude."}


def demo_pins(run: Run) -> dict:
    """Pins for every target: the shipped ones for its label when the paper has some (arXiv:2506.22373), with a
    placeholder data pin first wherever they lack one."""
    arxiv = feed.arxiv_id(run.paper.url, run.paper.arxiv_id)
    shipped_path = BACKEND_DIR / "app" / "pins" / f"{(arxiv or '').replace('/', '_')}.json"
    shipped = PaperPins.model_validate_json(shipped_path.read_text()) if arxiv and shipped_path.exists() else None
    by_label = {t.label: t.pins for t in shipped.targets} if shipped else {}
    placeholder = Pin(kind="data", title="Data source", basic="Demo pin: a real review says where these numbers come from.",
                      researcher="Written by REVIEW_DEMO=1, without calling Claude.", evidence="From the paper")
    targets = []
    for target in run.found:
        given = by_label.get(target.label, [])
        ordered = ([p for p in given if p.kind == "data"][:1] or [placeholder]) + [p for p in given if p.kind != "data"]
        targets.append({**target.model_dump(), "pins": [p.model_dump() for p in ordered]})
    claims = [c.model_dump() for c in shipped.claims] if shipped else [DEMO_CLAIM]
    return {
        "arxiv_id": arxiv,
        "reviewed": shipped.reviewed if shipped else "Demo review (REVIEW_DEMO=1): nothing was checked",
        "verdict": "Demo verdict: a real review ends with its bottom line here.",
        "claims": claims if run.depth == "full" else [],
        "main_problems": shipped.main_problems if shipped else ["Demo problem: a real review lists its main problems here."],
        "targets": targets,
    }


async def demo(run: Run) -> PaperPins:
    """Replay a scripted review over DEMO_SECONDS, then write review.md and pins.json and check them as for a real one."""
    run.event("text", "Demo review (REVIEW_DEMO=1): replaying a script, not calling Claude")
    for k, (lines, seconds) in enumerate(zip(DEMO_LINES[run.depth], expected(run.depth)), 1):
        run.stage(k, f"Demo: {run.stages[k - 1].lower()}")
        for kind, text, sub in lines:
            await asyncio.sleep(seconds / (len(lines) + 1))
            run.event(kind, text, sub)
        await asyncio.sleep(seconds / (len(lines) + 1))
    (run.work / "review.md").write_text(DEMO_REVIEW.format(title=run.paper.title), encoding="utf-8")
    (run.work / "pins.json").write_text(json.dumps(demo_pins(run), indent=1), encoding="utf-8")
    found, problems = run.check()
    if problems:
        raise Failed("The demo's pins didn't pass the check: " + "; ".join(problems[:3]))
    return found


if __name__ == "__main__":
    main(sys.argv[1:])
