"""The journal club API (app/club.py) on the shipped examples and on the mock LLM backend (JC_LLM=mock)."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import club, db
from app.main import app
from app.schemas import Paper

client = TestClient(app)
FIXTURE_CARDS = Path(__file__).parent / "jc" / "fixtures" / "cards"  # eight synthetic single-cell papers, 2019-2024
LINES = [
    "Spike-in lines as ground truth 2021",
    "We sequence three spike-in cell lines in every batch of the experiment.",
    "Any difference between spike-in cells after integration is residual batch effect.",
    "The design applies only to newly generated data and not to public datasets.",
    "We release the dataset and code.",
]


@pytest.fixture(autouse=True)
def club_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty club folder and the offline backend."""
    monkeypatch.setattr(club, "CLUB_DIR", tmp_path)
    monkeypatch.setenv("JC_LLM", "mock")
    monkeypatch.setenv("JC_CACHE", "0")
    monkeypatch.setenv("JC_CONCURRENCY", "2")
    club.RUNNERS.clear()
    club.INGESTS.clear()
    return tmp_path


def finished(name: str, timeout: float = 90) -> None:
    runner = club.RUNNERS[name]
    runner.thread.join(timeout)
    assert not runner.thread.is_alive(), f"{name} still running after {timeout}s"


def test_examples_listed() -> None:
    runs = {r["name"]: r for r in client.get("/club/runs").json()}
    assert runs["desi-bt-1"]["kind"] == "backtest" and runs["desi-bt-1"]["example"] and runs["desi-bt-1"]["state"] == "done"
    assert runs["desi-bt-1"]["T"] == "2025-01-01" and runs["desi-bt-1"]["n_cards"] == 8
    assert runs["desi-night-1"]["kind"] == "night" and runs["desi-night-1"]["n_directions"] == 6
    sets = {s["name"]: s for s in client.get("/club/cards").json()}
    assert sets["desi"]["example"] and len(sets["desi"]["papers"]) == 9 and len(sets["desi_before"]["papers"]) == 8
    assert {"id", "citekey", "title", "year", "date"} <= set(sets["desi"]["papers"][0])


def test_example_run_folds() -> None:
    view = client.get("/club/runs/desi-bt-1").json()
    st = view["state"]
    assert view["summary"]["state"] == "done"
    assert len(st["pairs"]) == 28 and len(st["disputes"]) == 5 and len(st["directions"]) == 6 and len(st["baseline_directions"]) == 9
    assert st["report"]["T"] == "2025-01-01" and st["report"]["after_ids"] == ["desidr2ii"]
    assert {s["name"]: s["status"] for s in st["steps"]}["judge"] == "done"
    assert st["cards"][0]["citekey"] and "claims" not in st["cards"][0]  # headers only
    minutes = client.get("/club/runs/desi-bt-1/minutes")  # rendered from the archive: the example has no minutes.md
    assert minutes.status_code == 200 and minutes.text.startswith("# Minutes") and "## Backtest" in minutes.text
    assert client.get("/club/runs/desi-bt-1/report").text.startswith("#")
    tail = client.get("/club/runs/desi-bt-1/events?after=70").json()
    assert tail and all(e["seq"] > 70 for e in tail) and tail[-1]["seq"] == st["last_seq"]
    assert client.get("/club/runs/desi-night-1/report").status_code == 404
    assert client.delete("/club/runs/desi-bt-1").status_code == 403
    assert client.get("/club/runs/nope").status_code == 404


def test_night_with_mock(club_dir: Path) -> None:
    shutil.copytree(FIXTURE_CARDS, club_dir / "cards" / "fx")
    req = {"name": "n1", "cards": "fx", "agenda": "batch correction"}
    r = client.post("/club/runs", json=req)
    assert r.status_code == 202, r.text
    assert client.post("/club/runs", json=req).status_code == 409  # already running
    finished("n1")
    view = client.get("/club/runs/n1").json()
    assert view["summary"]["state"] == "done", view["summary"]
    st = view["state"]
    assert st["kind"] == "night" and st["agenda"] == "batch correction" and st["model"] == "mock"
    assert [s["status"] for s in st["steps"]] == ["done"] * 4 and not any(s["reused"] for s in st["steps"])
    assert len(st["pairs"]) == 28 and st["directions"] and st["synthesis"]
    assert client.get("/club/runs/n1/minutes").status_code == 200
    prog = view["summary"]["progress"]
    assert prog["step"] is None and prog["remaining_s"] is None and prog["elapsed_s"] >= 0
    # The same POST again resumes: every step is rebuilt from the archive, no LLM work.
    assert client.post("/club/runs", json=req).status_code == 202
    finished("n1")
    st = client.get("/club/runs/n1").json()["state"]
    assert all(s["reused"] for s in st["steps"]) and len(st["directions"]) > 0
    assert client.delete("/club/runs/n1").status_code == 204
    assert client.get("/club/runs/n1").status_code == 404


def test_backtest_with_mock(club_dir: Path) -> None:
    shutil.copytree(FIXTURE_CARDS, club_dir / "cards" / "fx")
    r = client.post("/club/runs", json={"name": "bt", "cards": "fx", "agenda": "batch correction", "kind": "backtest", "t": "2023-01-01"})
    assert r.status_code == 202, r.text
    finished("bt")
    view = client.get("/club/runs/bt").json()
    assert view["summary"]["state"] == "done", view["summary"]
    st = view["state"]
    assert st["kind"] == "backtest" and st["T"] == "2023-01-01" and len(st["cards"]) == 6  # the 2023-2024 papers are held out
    assert st["report"]["after_ids"] == ["sc07", "sc08"] and st["baseline_directions"]
    assert client.get("/club/runs/bt/report").status_code == 200


def test_bad_requests() -> None:
    post = lambda **body: client.post("/club/runs", json=body).status_code
    assert post(name="bad name", cards="desi", agenda="x") == 422
    assert post(name="desi-bt-1", cards="desi", agenda="x") == 409  # a shipped example
    assert post(name="n2", cards="missing", agenda="x") == 404
    assert post(name="n2", cards="desi", agenda="x", kind="backtest") == 400  # no T
    assert post(name="n2", cards="desi", agenda="x", kind="backtest", t="2025") == 422
    assert not club.RUNNERS


def test_card_set_from_library() -> None:
    pid = db.save(Paper(url="u", title="Spike-in lines", authors=[], year=2021, arxiv_id="2101.00001", pages=[{"blocks": [{"text": t} for t in LINES]}]))
    r = client.post("/club/cards", json={"name": "mine", "paper_ids": [pid]})
    assert r.status_code == 202, r.text
    club.INGESTS["mine"].thread.join(30)
    sets = {s["name"]: s for s in client.get("/club/cards").json()}
    assert sets["mine"]["ingesting"] == {"done": 1, "total": 1, "failed": [], "running": False}
    assert [p["id"] for p in sets["mine"]["papers"]] == ["2101_00001"] and sets["mine"]["papers"][0]["year"] == 2021
    assert client.post("/club/cards", json={"name": "mine", "paper_ids": [pid]}).status_code == 409
    assert client.post("/club/cards", json={"name": "m2", "paper_ids": [999999]}).status_code == 404
    assert client.post("/club/cards", json={"name": "m3", "paper_ids": []}).status_code == 422


def test_config() -> None:
    cfg = client.get("/club/config").json()
    assert cfg == {"ready": None, "backend": "the offline mock", "debate_cap": club.DEBATE_CAP, "concurrency": 2}


def test_estimates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JC_LLM")
    monkeypatch.setenv("JC_CONCURRENCY", "4")
    assert club.step_totals(9, [], False) == {"map": 36, "debate": club.DEBATE_CAP, "directions": 1, "synthesis": 1}
    some = [{"relation": "disagree"}] * 2 + [{"relation": "agree"}] * 16
    assert club.step_totals(9, some, False)["debate"] == club.DEBATE_CAP  # the cap until the map is done
    assert club.step_totals(9, some, True)["debate"] == 2
    assert club.step_totals(2, [], False)["debate"] == 1  # one pair, at most one debate
    assert 5 * 60 <= club.estimate_night_s(9) <= 8 * 60  # the measured 9-paper night took 6.5 minutes
    assert club.estimate_night_s(2) < club.estimate_night_s(9) < club.estimate_night_s(16)
    sets = {s["name"]: s for s in client.get("/club/cards").json()}
    assert sets["desi"]["night_s"] == club.estimate_night_s(9)


def test_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JC_LLM")
    events = club.read_events(club.EXAMPLES / "runs" / "desi-night-1" / "events.jsonl")
    first_map = next(i for i, e in enumerate(events) if e.type == "pair_verdict")
    early, later = club.fold(events[: first_map + 4]), club.fold(events[: first_map + 20])
    p = club.progress(early, True, started=1000.0, last_write=1060.0, now=1063.0)
    assert (p.step, p.done, p.total, p.elapsed_s) == ("map", 4, 28, 63) and p.remaining_s > 0
    q = club.progress(later, True, started=1000.0, last_write=1060.0, now=1063.0)
    assert q.done == 20 and q.remaining_s < p.remaining_s
    stale = club.progress(later, True, started=1000.0, last_write=1060.0, now=99999.0)
    assert stale.remaining_s == 5  # overdue: a floor, never zero or negative while running
    done = club.progress(club.fold(events), False, started=1000.0, last_write=1390.0, now=5000.0)
    assert (done.step, done.elapsed_s, done.remaining_s) == (None, 390, None)
    example = {r["name"]: r for r in client.get("/club/runs").json()}["desi-night-1"]
    assert example["progress"]["elapsed_s"] is None  # shipped examples have no request.json
