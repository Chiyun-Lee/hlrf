"""CLI: run, backtest, minutes and ingest under JC_LLM=mock; refusal without --resume."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from journal_club.archive import Archive
from journal_club.cli import app
from journal_club.night import STEPS
from .conftest import FIXTURE_CARDS, make_pdf

runner = CliRunner()


@pytest.fixture(autouse=True)
def _mock_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every CLI test runs offline."""
    monkeypatch.setenv("JC_LLM", "mock")


def _events(run_dir: Path) -> list[str]:
    """Event types of a run directory's archive."""
    with Archive(run_dir / "events.jsonl") as archive:
        return [e.type for e in archive.read()]


def test_run_writes_events_and_minutes(tmp_path: Path) -> None:
    out = tmp_path / "night"
    res = runner.invoke(app, ["run", str(FIXTURE_CARDS), "--out", str(out), "--agenda", "batch correction"])
    assert res.exit_code == 0, res.output
    assert (out / "events.jsonl").exists() and (out / "minutes.md").exists()
    assert "28 pairs" in res.output
    types = _events(out)
    assert types[0] == "run_started" and types.count("pair_verdict") == 28 and types[-1] == "written"
    assert "## Directions" in (out / "minutes.md").read_text(encoding="utf-8")


def test_run_twice_into_same_out_resumes_without_flag(tmp_path: Path) -> None:
    out = tmp_path / "night"
    args = ["run", str(FIXTURE_CARDS), "--out", str(out), "--agenda", "a"]
    assert runner.invoke(app, args).exit_code == 0
    before = (out / "events.jsonl").read_bytes()
    minutes_before = (out / "minutes.md").read_text(encoding="utf-8")
    res = runner.invoke(app, args)
    assert res.exit_code == 0, res.output
    after = (out / "events.jsonl").read_bytes()
    assert after.startswith(before), "the archive is append-only: the first run's lines are untouched"
    types = _events(out)
    assert types.count("step_skipped") == len(STEPS) and types.count("written") == 2
    assert types.count("pair_verdict") == 28 and types.count("run_started") == 1
    assert (out / "minutes.md").read_text(encoding="utf-8") == minutes_before


def test_run_resume_skips_every_step(tmp_path: Path) -> None:
    out = tmp_path / "night"
    args = ["run", str(FIXTURE_CARDS), "--out", str(out), "--agenda", "a"]
    assert runner.invoke(app, args).exit_code == 0
    res = runner.invoke(app, [*args, "--resume"])
    assert res.exit_code == 0, res.output
    types = _events(out)
    assert types.count("step_skipped") == len(STEPS) and types.count("written") == 2


def test_backtest_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "bt"
    res = runner.invoke(app, ["backtest", str(FIXTURE_CARDS), "--t", "2023-01-01", "--out", str(out), "--agenda", "a"])
    assert res.exit_code == 0, res.output
    for name in ("events.jsonl", "minutes.md", "report.md"):
        assert (out / name).exists()
    assert "club" in res.output and "baseline" in res.output
    assert (out / "report.md").read_text(encoding="utf-8").startswith("# Backtest report")
    assert "## Backtest" in (out / "minutes.md").read_text(encoding="utf-8")


def test_backtest_bad_t_exits_one(tmp_path: Path) -> None:
    res = runner.invoke(app, ["backtest", str(FIXTURE_CARDS), "--t", "2030-01-01", "--out", str(tmp_path / "x"), "--agenda", "a"])
    assert res.exit_code == 1


def test_minutes_rewrites_from_archive(tmp_path: Path) -> None:
    out = tmp_path / "night"
    assert runner.invoke(app, ["run", str(FIXTURE_CARDS), "--out", str(out), "--agenda", "a"]).exit_code == 0
    before = (out / "minutes.md").read_text(encoding="utf-8")
    (out / "minutes.md").unlink()
    res = runner.invoke(app, ["minutes", str(out)])
    assert res.exit_code == 0, res.output
    assert (out / "minutes.md").read_text(encoding="utf-8") == before


def test_minutes_missing_archive_exits_one(tmp_path: Path) -> None:
    assert runner.invoke(app, ["minutes", str(tmp_path / "nope")]).exit_code == 1


def test_ingest_writes_cards(tmp_path: Path) -> None:
    pdfs, cards = tmp_path / "pdfs", tmp_path / "cards"
    pdfs.mkdir()
    make_pdf(
        pdfs / "demo-2021.pdf",
        [
            "A demo paper on batch correction",
            "Anchor-based alignment removes batch effects while preserving cluster structure in every dataset.",
            "Deep models require a GPU and roughly ninety minutes per million cells to train.",
            "Our evaluation assumes that batches share most cell types and does not cover disjoint composition.",
        ],
    )
    res = runner.invoke(app, ["ingest", str(pdfs), str(cards)])
    assert res.exit_code == 0, res.output
    assert (cards / "demo-2021.json").exists()


def test_ingest_continues_past_bad_pdfs(tmp_path: Path) -> None:
    pdfs, cards = tmp_path / "pdfs", tmp_path / "cards"
    pdfs.mkdir()
    make_pdf(
        pdfs / "a-good-2021.pdf",
        [
            "A good paper on batch correction",
            "Anchor-based alignment removes batch effects while preserving cluster structure in every dataset.",
            "Deep models require a GPU and roughly ninety minutes per million cells to train.",
            "Our evaluation assumes that batches share most cell types and does not cover disjoint composition.",
        ],
    )
    (pdfs / "b-garbage.pdf").write_bytes(b"this is not a pdf at all")
    make_pdf(pdfs / "c-no-claims-2020.pdf", ["Short title", "Too short.", "Also short."])
    make_pdf(
        pdfs / "d-also-good-2022.pdf",
        [
            "Another good paper",
            "Spike-in cell lines give an experimental ground truth for residual batch effect after integration.",
            "Linear methods preserve rare populations better than deep models in our hands on every dataset.",
            "The design applies only to newly generated data and never to the public datasets we did not sequence.",
        ],
    )
    res = runner.invoke(app, ["ingest", str(pdfs), str(cards)])
    assert res.exit_code == 1, res.output
    assert (cards / "a-good-2021.json").exists() and (cards / "d-also-good-2022.json").exists()
    assert not (cards / "b-garbage.json").exists() and not (cards / "c-no-claims-2020.json").exists()
    assert "2 of 4 PDF(s) ingested" in res.output
    assert "b-garbage.pdf" in res.output and "c-no-claims-2020.pdf" in res.output


def test_ingest_no_pdfs_exits_one(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    assert runner.invoke(app, ["ingest", str(tmp_path / "empty"), str(tmp_path / "cards")]).exit_code == 1


def test_sdk_error_is_logged_not_raised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """A 429 escaping the backend exits 1 with one logged line, like every other known failure."""
    import anthropic

    from journal_club import llm as llm_mod
    from .test_llm import _httpx

    httpx = _httpx()
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.RateLimitError("429 too many requests", response=httpx.Response(429, request=req), body=None)

    class _Raising:
        def complete_json(self, kind: str, system: str, user: str, schema: dict) -> dict:
            raise err

    monkeypatch.setattr(llm_mod, "get_llm", lambda role="main": _Raising())
    out = tmp_path / "night"
    with caplog.at_level("ERROR", logger="journal_club.cli"):
        res = runner.invoke(app, ["run", str(FIXTURE_CARDS), "--out", str(out), "--agenda", "x"])
    assert res.exit_code == 1
    assert res.exception is None or isinstance(res.exception, SystemExit), "no traceback escapes"
    assert any("RateLimitError" in r.message for r in caplog.records)
    assert (out / "events.jsonl").exists(), "the run directory stays resumable"
