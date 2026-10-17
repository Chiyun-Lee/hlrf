import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import db, llm, pins, review
from app.main import app
from app.schemas import Paper, PinTarget

client = TestClient(app)
FIGURE = PinTarget(label="Figure 1", page=0, caption="Figure 1.", bbox=[50, 50, 300, 200], pins=[])
PIN = {"kind": "data", "title": "Data source", "basic": "Where the numbers come from.", "researcher": "Table 3 of the survey.",
       "evidence": "From the paper"}
posix_only = pytest.mark.skipif(os.name == "nt", reason="checks processes with ps and process groups")


def paper(url="https://arxiv.org/abs/2401.00001") -> int:
    """A saved paper with a PDF and one figure."""
    pages = [{"blocks": [{"text": "Figure 1. A plot.", "bbox": [50, 210, 300, 230]}], "width": 612, "height": 792}]
    return db.save(Paper(url=url, title="A paper", authors=[{"raw": "Ada Lovelace"}], pages=pages), b"%PDF-1.4 stand-in")


def stand_in_problems(found, paper, targets=None) -> list[str]:
    """The pin rules that matter here (app/pins.py has the real ones): every target pinned, one data pin first."""
    labels = {t.label for t in found.targets}
    missing = [f"{t.label} has no pins" for t in targets or [] if t.label not in labels]
    return missing + [f"{t.label}: its data pin must come first" for t in found.targets if not t.pins or t.pins[0].kind != "data"]


def skill(tmp_path: Path) -> Path:
    """A stand-in paper-pins skill."""
    path = tmp_path / "skills" / "paper-pins"
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text("---\nname: paper-pins\ndescription: Write pins.json for a paper's figures and tables.\n---\nA stand-in.\n")
    return path


class Runners:
    """Reviews in threads instead of detached processes; kill() cancels one, as the runner's SIGTERM handler does."""

    def __init__(self):
        self.threads, self.tasks = {}, {}

    def spawn(self, paper_id, depth):
        started = threading.Event()

        async def main():
            self.tasks[paper_id] = (asyncio.get_running_loop(), asyncio.current_task())
            started.set()
            await review.run_review(paper_id, depth)

        self.threads[paper_id] = threading.Thread(target=asyncio.run, args=(main(),))
        self.threads[paper_id].start()
        started.wait()
        return SimpleNamespace(pid=paper_id)

    def alive(self, pid, paper_id):
        return self.threads[pid].is_alive()

    def kill(self, pid, hard=False):
        loop, task = self.tasks[pid]
        loop.call_soon_threadsafe(task.cancel)


@pytest.fixture
def reviews(monkeypatch, tmp_path):
    """Reviews in tmp_path, run in threads, the demo at full speed, and stand-ins for the pins core."""
    monkeypatch.setattr(review, "REVIEWS_DIR", tmp_path / "reviews")
    monkeypatch.setattr(review, "DEMO", True)
    monkeypatch.setattr(review, "DEMO_SECONDS", 0.2)
    saved = {}
    monkeypatch.setattr(pins, "targets", lambda paper, pdf: [FIGURE], raising=False)
    monkeypatch.setattr(pins, "problems", stand_in_problems, raising=False)
    monkeypatch.setattr(pins, "save", saved.__setitem__, raising=False)
    runners = Runners()
    for name in ("spawn", "alive", "kill"):
        monkeypatch.setattr(review, name, getattr(runners, name))
    yield SimpleNamespace(saved=saved, dir=tmp_path / "reviews")
    for thread in runners.threads.values():
        thread.join(10)


def wait(paper_id: int) -> dict:
    """The review, once it has stopped running."""
    for _ in range(200):
        if (st := client.get(f"/papers/{paper_id}/review").json())["state"] != "running":
            return st
        time.sleep(0.05)
    raise AssertionError("still running")


def test_review_lifecycle(reviews):
    pid = paper()
    assert client.get(f"/papers/{pid}/review").json() is None
    r = client.post(f"/papers/{pid}/review", json={"depth": "quick"})
    assert r.status_code == 202 and r.json()["state"] == "running" and r.json()["stage"] == 1
    st = wait(pid)
    assert st["state"] == "done" and st["stage"] == len(st["stages"]) == 4 and st["progress"] == 1
    assert st["pins"] == 1 and st["report"] and st["error"] is None and st["finished_at"]
    assert st["verdict"] == getattr(reviews.saved[pid], "verdict", None)
    assert [t.label for t in reviews.saved[pid].targets] == ["Figure 1"]
    events = st["events"]
    assert [e["n"] for e in events] == list(range(st["n_events"]))
    assert {e["kind"] for e in events} == {"stage", "tool", "text", "error", "done"}
    assert [e["text"] for e in events if e["kind"] == "stage"] == [f"Stage {k}/4 · {t}" for k, t in enumerate(st["stages"], 1)]
    later = client.get(f"/papers/{pid}/review", params={"after": st["n_events"] - 2}).json()["events"]
    assert [e["n"] for e in later] == [st["n_events"] - 2, st["n_events"] - 1]
    assert client.get("/reviews").json() == {
        str(pid): {"state": "done", "depth": "quick", "progress": 1.0, "stage_title": "Pinning provenance and concerns"}
    }
    report = client.get(f"/papers/{pid}/review/report")
    assert report.status_code == 200 and report.headers["content-type"].startswith("text/plain")
    assert report.text.startswith("# Demo review: A paper")
    assert client.get(f"/papers/{paper()}/review/report").status_code == 404

    full = paper()
    assert client.post(f"/papers/{full}/review").json()["depth"] == "full"  # no body: a full review
    st = wait(full)
    assert st["state"] == "done" and len(st["stages"]) == 7 and any(e["sub"] for e in st["events"])


def test_starts_refused_and_stop(reviews, monkeypatch):
    html_only = db.save(Paper(url="https://example.org/a.html", title="HTML only", authors=[]))
    r = client.post(f"/papers/{html_only}/review")
    assert r.status_code == 400 and "save the PDF version first" in r.json()["detail"]
    assert client.post("/papers/999999/review").status_code == 404
    monkeypatch.setattr(review, "DEMO_SECONDS", 60)  # still running while we look
    a, b, c = paper(), paper(), paper()
    assert client.post(f"/papers/{a}/review").status_code == 202
    assert client.post(f"/papers/{a}/review").status_code == 409
    assert client.post(f"/papers/{b}/review", json={"depth": "quick"}).status_code == 202
    r = client.post(f"/papers/{c}/review")
    assert r.status_code == 409 and r.json()["detail"].startswith("2 reviews are already running")
    running = client.get("/reviews").json()[str(a)]
    assert running == {**running, "state": "running", "depth": "full", "stage_title": "Reading the paper"}
    assert 0 < running["progress"] < 1 / 7
    assert client.delete(f"/papers/{a}/review").status_code == 204
    st = client.get(f"/papers/{a}/review").json()
    assert st["state"] == "stopped" and st["finished_at"] and st["events"][-1] == {**st["events"][-1], "kind": "error", "text": "Stopped"}
    assert client.post(f"/papers/{c}/review").status_code == 202  # a slot is free again
    for p in (b, c):
        assert client.delete(f"/papers/{p}/review").status_code == 204
    assert client.delete(f"/papers/{a}/review").status_code == 204  # not running: nothing to do


def test_deleting_a_paper_removes_its_review(reviews):
    pid = paper()
    client.post(f"/papers/{pid}/review", json={"depth": "quick"})
    wait(pid)
    assert (reviews.dir / str(pid) / "work" / "review.md").exists()
    assert client.delete(f"/papers/{pid}").status_code == 204
    assert not (reviews.dir / str(pid)).exists() and str(pid) not in client.get("/reviews").json()


def test_progress(monkeypatch):
    monkeypatch.setattr(review, "DEMO", False)
    t0 = "2026-10-17T12:00:00+00:00"
    start = review.ts(t0)
    st = {"state": "running", "depth": "full", "stage": 1, "stage_started_at": t0}
    assert sum(m for _, m in review.STAGES["full"]) == 120 and sum(m for _, m in review.STAGES["quick"]) == 15
    assert review.progress(st, start) == 0
    assert review.progress(st, start + 7.5 * 60) == pytest.approx(0.5 / 7)  # halfway through its usual 15 min
    assert review.progress(st, start + 5 * 3600) == pytest.approx(0.9 / 7)  # a long stage creeps up to 0.9 of its share
    assert review.progress({**st, "stage": 4}, start) == pytest.approx(3 / 7)
    assert review.progress({**st, "depth": "quick", "stage": 2}, start + 150) == pytest.approx(1.5 / 4)  # 2.5 of 5 min
    assert review.progress({**st, "state": "failed", "stage": 3}, start + 60) == pytest.approx((2 + 0.1) / 7)
    assert review.progress({**st, "state": "done", "stage": 7}, start) == 1


@posix_only
def test_dead_runner_is_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(review, "REVIEWS_DIR", tmp_path)
    pid = paper()
    sleep = [sys.executable, "-c", "import time; time.sleep(60)"]
    runner = subprocess.Popen([*sleep, "app.review", "run", str(pid), "quick"])  # has a runner's command line
    other = subprocess.Popen(sleep)  # e.g. the runner's pid, reused after a reboot
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    try:
        for proc, state in ((runner, "running"), (other, "failed"), (gone, "failed")):
            review.begin(pid, "quick")
            (tmp_path / str(pid) / "pid").write_text(str(proc.pid))
            st = review.status(pid)
            assert st.state == state, proc.args
            if state == "failed":
                assert "stopped unexpectedly" in st.error and review.read(pid)["state"] == "failed"
    finally:
        runner.kill(), other.kill()


@posix_only
def test_stop_signals_the_runners_process_group(monkeypatch, tmp_path):
    monkeypatch.setattr(review, "REVIEWS_DIR", tmp_path)
    pid = paper()
    review.begin(pid, "full")
    child = "import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)"
    runner = subprocess.Popen([sys.executable, "-c", child, "app.review", "run", str(pid), "full"], start_new_session=True)
    (tmp_path / str(pid) / "pid").write_text(str(runner.pid))
    time.sleep(0.5)  # let it start its child
    assert client.delete(f"/papers/{pid}/review").status_code == 204
    assert runner.wait(5) == -signal.SIGTERM
    st = review.status(pid)
    assert st.state == "stopped" and st.finished_at
    for _ in range(20):  # the child it started went too
        try:
            os.killpg(runner.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("the runner's process group is still alive")


def test_live_view_lines(tmp_path, monkeypatch):
    sdk = pytest.importorskip("claude_agent_sdk")
    work = tmp_path / "work"

    def call(name, **args):
        return sdk.ToolUseBlock(id="t", name=name, input=args)

    message = sdk.AssistantMessage(model="m", content=[
        sdk.TextBlock("I'll start with the paper.\n\nThen the code."),
        sdk.ThinkingBlock("hmm", "sig"),
        call("Bash", command="uv venv .venv\nuv pip install numpy", description="Create a venv"),
        call("Bash", command="git clone https://github.com/a/b\ncd b"),
        call("Read", file_path=str(work / "paper.txt")),
        call("Write", file_path=str(work / "checks" / "mock.py"), content="..."),
        call("Edit", file_path="/elsewhere/x.py", old_string="a", new_string="b"),
        call("Grep", pattern="H0_max"),
        call("WebFetch", url="https://arxiv.org/abs/2506.22373?context=astro-ph", prompt="links"),
        call("WebSearch", query="cosmography_mcmc github"),
        call("Agent", description="re-run desidr2.ipynb", prompt="..."),
        call("Skill", skill="paper2agent"),
        call("TodoWrite", todos=[{"content": "Read", "status": "completed", "activeForm": "Reading"},
                                 {"content": "Run the notebooks", "status": "in_progress", "activeForm": "Running the notebooks"}]),
        call("mcp__review__stage", stage=2, note="code"),
        call("mcp__review__check_pins"),
        call("ToolSearch", query="select:mcp__review__stage"),
        call("NotebookRead", notebook_path="a.ipynb"),
    ])
    assert review.describe(message, work) == [
        ("text", "I'll start with the paper. Then the code."),
        ("tool", "Create a venv"),
        ("tool", "git clone https://github.com/a/b"),
        ("tool", "Reading paper.txt"),
        ("tool", "Writing checks/mock.py"),
        ("tool", "Editing /elsewhere/x.py"),
        ("tool", "Searching for H0_max"),
        ("tool", "Fetching arxiv.org/abs/2506.22373"),
        ("tool", "Searching the web: cosmography_mcmc github"),
        ("tool", "Helper: re-run desidr2.ipynb"),
        ("tool", "Using the paper2agent skill"),
        ("tool", "Running the notebooks"),
        ("tool", "Checking the pins"),
        ("tool", "Using NotebookRead"),
    ]
    assert review.describe(sdk.AssistantMessage(model="m", content=[sdk.TextBlock("x " * 400)]), work)[0][1].endswith("…")
    results = sdk.UserMessage(content=[
        sdk.ToolResultBlock("t", "fine"),
        sdk.ToolResultBlock("t", [{"type": "text", "text": "<tool_use_error>File does not exist.</tool_use_error>"}], is_error=True),
    ])
    assert review.describe(results, work) == [("error", "File does not exist.")]
    done = sdk.ResultMessage(subtype="success", duration_ms=6_720_000, duration_api_ms=1, is_error=False, num_turns=143,
                             session_id="s", total_cost_usd=41.5)
    assert review.describe(done, work) == [("done", "Agent finished after 1 h 52 min, 143 turns, $41.50")]
    monkeypatch.setattr(llm, "BACKEND", "claude-code")  # on the subscription: no cost
    assert review.describe(done, work) == [("done", "Agent finished after 1 h 52 min, 143 turns")]
    helper = sdk.TaskNotificationMessage(subtype="task_notification", data={}, task_id="a", status="completed",
                                         output_file="o", summary="Re-ran desidr2.ipynb: matches Table II", uuid="u", session_id="s")
    assert review.describe(helper, work) == [("text", "Helper completed: Re-ran desidr2.ipynb: matches Table II")]
    resets = int(review.ts("2026-10-17T18:00:00+00:00"))

    def limit(status):
        return sdk.RateLimitEvent(sdk.RateLimitInfo(status=status, resets_at=resets), uuid="u", session_id="s")

    at = f"(resets at {review.datetime.fromtimestamp(resets):%H:%M})"
    assert review.describe(limit("rejected"), work) == [("error", f"Claude usage limit reached {at}")]
    assert review.describe(limit("allowed_warning"), work) == [("text", f"Close to the Claude usage limit {at}")]
    assert review.describe(limit("allowed"), work) == []


def test_stage_and_check_pins_tools(reviews):
    pytest.importorskip("claude_agent_sdk")
    pid = paper()
    review.begin(pid, "quick")
    run = review.Run(pid, "quick")
    review.prepare(run)
    stage, check_pins = review.review_tools(run)
    assert not asyncio.run(stage.handler({"stage": 2, "note": "Reading the code"}))["is_error"]
    asyncio.run(stage.handler({"stage": 1, "note": ""}))  # never back
    assert asyncio.run(stage.handler({"stage": 5, "note": ""}))["is_error"]
    assert review.read(pid)["stage"] == 2
    assert [(e["kind"], e["text"]) for e in review.read_events(pid)[0][-3:]] == [
        ("stage", "Stage 2/4 · Checking the code and data"), ("text", "Reading the code"), ("stage", "Stage 1/4 · Reading the paper")]
    assert "pins.json is missing" in asyncio.run(check_pins.handler({}))["content"][0]["text"]
    pins_json = {"arxiv_id": "2401.00001", "reviewed": "r", "verdict": "v", "targets": [{**FIGURE.model_dump(), "pins": [PIN]}]}
    (run.work / "pins.json").write_text(json.dumps(pins_json))
    assert asyncio.run(check_pins.handler({}))["content"][0]["text"] == "ok"
    assert json.loads((run.work / "targets.json").read_text()) == [FIGURE.model_dump()]
    assert (run.work / "paper.txt").read_text().startswith("=== Page 1 ===\n\nFigure 1. A plot.")


def agent_run(reviews, monkeypatch, tmp_path, write_pins, init_skills=("paper-pins",), init_tools=("mcp__review__stage",)):
    """A quick review with Claude Code faked: each session writes pins.json with write_pins(call number)."""
    sdk = pytest.importorskip("claude_agent_sdk")
    monkeypatch.setattr(review, "DEMO", False)
    monkeypatch.setitem(review.SKILLS, "paper-pins", skill(tmp_path))
    calls = []

    async def fake_query(prompt, options):
        calls.append((prompt, options))
        yield sdk.SystemMessage(subtype="init", data={"skills": list(init_skills), "tools": list(init_tools)})
        yield sdk.AssistantMessage(model="m", content=[sdk.ToolUseBlock("t", "Bash", {"description": "Read the repository"})],
                                   parent_tool_use_id="helper")
        if (data := write_pins(len(calls))) is not None:
            (options.cwd / "pins.json").write_text(json.dumps(data))
        yield sdk.ResultMessage(subtype="success", duration_ms=1000, duration_api_ms=1, is_error=False, num_turns=3,
                                session_id=f"s{len(calls)}")

    monkeypatch.setattr(sdk, "query", fake_query)
    pid = paper()
    assert client.post(f"/papers/{pid}/review", json={"depth": "quick"}).status_code == 202
    return pid, wait(pid), calls


GOOD = {"arxiv_id": "2401.00001", "reviewed": "Read only", "verdict": "Holds up.", "targets": [{**FIGURE.model_dump(), "pins": [PIN]}]}


def test_agent_is_sent_back_to_fix_the_pins(reviews, monkeypatch, tmp_path):
    pid, st, calls = agent_run(reviews, monkeypatch, tmp_path, lambda call: {**GOOD, "targets": []} if call == 1 else GOOD)
    assert st["state"] == "done" and st["pins"] == 1
    (first, o1), (second, o2) = calls
    assert 'quick review of "A paper" by Ada Lovelace, arXiv:2401.00001' in first and o1.resume is None
    assert o2.resume == "s1" and "Figure 1 has no pins" in second
    work = review.folder(pid) / "work"
    assert (o1.cwd, o1.permission_mode, o1.skills, o1.setting_sources) == (work, "bypassPermissions", ["paper-pins"], ["project"])
    assert (o1.model, o1.effort, o1.tools) == (review.MODEL, review.EFFORT, {"type": "preset", "preset": "claude_code"})
    assert "review" in o1.mcp_servers and o1.strict_mcp_config and "Checking the code and data" in o1.system_prompt["append"]
    assert all(o1.env[v].startswith(str(work)) for v in ("UV_CACHE_DIR", "PIP_CACHE_DIR", "XDG_CACHE_HOME", "MPLCONFIGDIR"))
    assert (work / ".claude" / "skills" / "paper-pins").resolve() == review.SKILLS["paper-pins"].resolve()
    assert [e["sub"] for e in st["events"] if e["text"] == "Read the repository"] == [True, True]  # from a helper
    assert any(e["kind"] == "error" and "sending the agent back" in e["text"] for e in st["events"])


def test_pins_that_stay_broken_fail_the_review(reviews, monkeypatch, tmp_path):
    pid, st, calls = agent_run(reviews, monkeypatch, tmp_path, lambda call: None)
    assert len(calls) == 1 + review.FIXES
    assert st["state"] == "failed" and st["error"].startswith(f"pins.json still has problems after {review.FIXES} fixes")
    assert st["events"][-1]["kind"] == "error" and st["pins"] is None


def test_missing_skill_fails_at_once(reviews, monkeypatch, tmp_path):
    pid, st, calls = agent_run(reviews, monkeypatch, tmp_path, lambda call: GOOD, init_skills=())
    assert len(calls) == 1 and st["state"] == "failed" and "didn't find the paper-pins skill" in st["error"]
    pid, st, calls = agent_run(reviews, monkeypatch, tmp_path / "2", lambda call: GOOD, init_tools=())
    assert len(calls) == 1 and st["state"] == "failed" and "stage and check_pins tools" in st["error"]


def test_full_review_needs_paper2agent(reviews, monkeypatch, tmp_path):
    pytest.importorskip("claude_agent_sdk")
    monkeypatch.setattr(review, "DEMO", False)
    monkeypatch.setitem(review.SKILLS, "paper-pins", skill(tmp_path))
    monkeypatch.setitem(review.SKILLS, "paper2agent", tmp_path / "nowhere")
    r = client.post(f"/papers/{paper()}/review", json={"depth": "full"})
    assert r.status_code == 400 and "paper2agent" in r.json()["detail"] and "quick review" in r.json()["detail"]


# A tiny real run on your Claude subscription (as with LLM_BACKEND=claude-code): proves the SDK wiring.
@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 to call Claude")
def test_live_sdk_wiring(monkeypatch, tmp_path):
    """Claude Code finds the linked project skill, calls the stage tool, and its messages become events."""
    pytest.importorskip("claude_agent_sdk")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # your login, not an API key
    monkeypatch.setattr(review, "REVIEWS_DIR", tmp_path / "reviews")
    monkeypatch.setattr(review, "DEMO", False)
    monkeypatch.setattr(review, "EFFORT", "low")
    monkeypatch.setitem(review.SKILLS, "paper-pins", skill(tmp_path))
    monkeypatch.setattr(pins, "targets", lambda paper, pdf: [FIGURE], raising=False)
    pid = paper()
    review.begin(pid, "quick")
    run = review.Run(pid, "quick")
    review.prepare(run)
    prompt = ("This is a wiring test, not a review. Only do this: call the stage tool with stage 2 and the note "
              "'smoke test', then write the word ok to smoke.txt, then stop.")
    result = asyncio.run(review.converse(run, prompt, max_turns=4))
    events = review.read_events(pid)[0]
    assert result and not result.is_error, result
    assert (run.work / "smoke.txt").read_text().strip() == "ok" and review.read(pid)["stage"] == 2
    assert ("stage", "Stage 2/4 · Checking the code and data") in [(e["kind"], e["text"]) for e in events]
    assert any(e["kind"] == "tool" and "smoke.txt" in e["text"] for e in events) and events[-1]["kind"] == "done"
