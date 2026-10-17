"""Backtest: split, baseline, judge, rates, leakage guards, resume and report.md."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from journal_club import prompts
from journal_club.archive import Archive, Event
from journal_club.backtest import (
    UNKNOWN_ID_NOTE,
    BacktestReport,
    Hit,
    assert_no_leakage,
    hit_rate,
    hits_from_events,
    judge,
    run_backtest,
    run_baseline,
    split_by_date,
    weighted_rate,
)
from journal_club.cards import PaperCard, Quote
from journal_club.llm import LLMError, MockLLM
from journal_club.quotes import verify_quotes
from journal_club.rounds.directions import Direction
from journal_club.rounds.map_round import card_content_sha
from .conftest import FIXTURE_CARDS, CountingLLM

T = "2023-01-01"
BEFORE = ["sc01", "sc02", "sc03", "sc04", "sc05", "sc06"]
AFTER = ["sc07", "sc08"]


# ---------------------------------------------------------------- helpers


def _direction(a: PaperCard, b: PaperCard, text: str, confidence: float = 0.8) -> Direction:
    """A direction resting on the first quote of two cards."""
    return Direction(
        text=text,
        from_a="labels",
        to_b="spike-ins",
        because=f"{a.id} and {b.id} both hit it",
        papers=[a.id, b.id],
        quotes=[a.quotes()[0], b.quotes()[0]],
        confidence=confidence,
    )


def _club_directions(cards: list[PaperCard]) -> list[Direction]:
    """Three scripted club directions over the first fixture cards."""
    return [
        _direction(cards[4], cards[5], "From curated labels to an experimental ground truth", 0.9),
        _direction(cards[2], cards[0], "From blood-only evaluation to solid tissue", 0.7),
        _direction(cards[1], cards[5], "From deep latent models to regularised linear models", 0.4),
    ]


def _hit(text: str, verdict: str, pid: str | None, label: str = "club") -> Hit:
    """A Hit with a fixed reason."""
    return Hit(direction_text=text, verdict=verdict, after_paper_id=pid, reason="r", label=label)


def _fixture_cards() -> list[PaperCard]:
    """The eight fixture cards, loaded fresh."""
    from journal_club.cards import load_cards

    return load_cards(FIXTURE_CARDS)


def _types(archive: Archive, step: str) -> list[str]:
    """Event types of one step in order."""
    return [e.type for e in archive.by_step(step)]


def _judge_scripted(verdict: str, pid: str | None):
    """A scripted judge returning a fixed verdict and id."""
    return lambda user: {"verdict": verdict, "after_paper_id": pid, "reason": f"scripted {verdict}"}


# ------------------------------------------------------------------ split


def test_split_by_date_sides(cards: list[PaperCard]) -> None:
    before, after = split_by_date(cards, T)
    assert [c.id for c in before] == BEFORE
    assert [c.id for c in after] == AFTER


def test_split_by_date_boundary_is_after(cards: list[PaperCard]) -> None:
    before, after = split_by_date(cards, "2023-04-18")
    assert [c.id for c in after] == AFTER  # a paper dated exactly T is after


@pytest.mark.parametrize("t", ["2019-01-01", "2025-01-01"])
def test_split_by_date_empty_side_raises(cards: list[PaperCard], t: str) -> None:
    with pytest.raises(ValueError, match="need both"):
        split_by_date(cards, t)


@pytest.mark.parametrize("t", ["2023", "2023-1-1", "2023-13-01", "01/01/2023"])
def test_split_by_date_bad_t_raises(cards: list[PaperCard], t: str) -> None:
    with pytest.raises(ValueError):
        split_by_date(cards, t)


# ------------------------------------------------------------------ rates


def test_rates_empty() -> None:
    assert hit_rate([]) == 0.0 and weighted_rate([]) == 0.0


def test_rates_values() -> None:
    hits = [_hit("a", "hit", "sc07"), _hit("b", "partial", "sc08"), _hit("c", "miss", None), _hit("d", "hit", "sc07")]
    assert hit_rate(hits) == pytest.approx(0.5)
    assert weighted_rate(hits) == pytest.approx(0.625)


def test_hit_model_rejects_illegal_verdict() -> None:
    with pytest.raises(ValueError):
        _hit("a", "maybe", None)
    with pytest.raises(ValueError):
        _hit("a", "hit", "sc07", label="other")


# ------------------------------------------------------------------ judge


def test_judge_one_call_per_direction_and_events(cards: list[PaperCard], tmp_archive: Archive) -> None:
    before, after = split_by_date(cards, T)
    directions = _club_directions(before)
    llm = CountingLLM(MockLLM())
    hits = judge(directions, after, llm, tmp_archive, "club")
    assert llm.calls == {"judge": 3}
    assert [h.direction_text for h in hits] == [d.text for d in directions]
    assert all(h.label == "club" for h in hits)
    for h in hits:
        assert h.verdict in {"hit", "partial", "miss"}
        assert (h.after_paper_id is None) == (h.verdict == "miss")
        assert h.after_paper_id in {None, "sc07", "sc08"}
    events = tmp_archive.by_step("judge")
    assert [e.type for e in events] == ["step_started", "hit", "hit", "hit", "step_done"]
    assert events[0].payload == {"label": "club", "reused": 0}
    for e, h in zip(events[1:4], hits, strict=True):
        assert e.papers == ([h.after_paper_id] if h.after_paper_id else [])
        assert Hit.model_validate(e.payload) == h
    assert events[-1].payload["label"] == "club" and events[-1].payload["count"] == 3
    assert tmp_archive.has_step("judge", "club") and not tmp_archive.has_step("judge", "baseline")


def test_judge_prompt_sees_after_cards_only(cards: list[PaperCard], tmp_archive: Archive) -> None:
    before, after = split_by_date(cards, T)
    mock = MockLLM()
    judge(_club_directions(before), after, mock, tmp_archive, "club")
    for kind, user in mock.calls:
        assert kind == "judge"
        assert "AFTER_IDS: sc07,sc08" in user
        for c in before:
            assert f"PAPER {c.id} |" not in user
            for q in c.quotes():
                assert q.text not in user


def test_judge_downgrades_unknown_id_to_miss(cards: list[PaperCard], tmp_archive: Archive) -> None:
    before, after = split_by_date(cards, T)
    mock = MockLLM(scripted={"judge": _judge_scripted("hit", "sc99")})
    hits = judge(_club_directions(before)[:1], after, mock, tmp_archive, "club")
    assert hits[0].verdict == "miss" and hits[0].after_paper_id is None
    assert hits[0].reason.endswith(UNKNOWN_ID_NOTE)
    hit_events = [e for e in tmp_archive.by_step("judge") if e.type == "hit"]
    assert hit_events[0].papers == []


def test_judge_before_t_id_counts_as_unknown(cards: list[PaperCard], tmp_archive: Archive) -> None:
    before, after = split_by_date(cards, T)
    mock = MockLLM(scripted={"judge": _judge_scripted("partial", "sc05")})
    hits = judge(_club_directions(before)[:1], after, mock, tmp_archive, "club")
    assert hits[0].verdict == "miss" and hits[0].after_paper_id is None


def test_judge_miss_with_id_is_normalised(cards: list[PaperCard], tmp_archive: Archive) -> None:
    before, after = split_by_date(cards, T)
    mock = MockLLM(scripted={"judge": _judge_scripted("miss", "sc07")})
    hits = judge(_club_directions(before)[:1], after, mock, tmp_archive, "club")
    assert hits[0].verdict == "miss" and hits[0].after_paper_id is None
    assert UNKNOWN_ID_NOTE not in hits[0].reason


def test_judge_resume_zero_calls(cards: list[PaperCard], tmp_archive: Archive) -> None:
    before, after = split_by_date(cards, T)
    directions = _club_directions(before)
    first = judge(directions, after, MockLLM(), tmp_archive, "club")
    llm = CountingLLM(MockLLM())
    again = judge(directions, after, llm, tmp_archive, "club")
    assert llm.total == 0 and again == first
    assert _types(tmp_archive, "judge")[-1] == "step_skipped"
    skipped = tmp_archive.by_step("judge")[-1].payload
    assert skipped == {"reason": "resumed from archive", "count": 3, "label": "club"}


def test_judge_labels_are_independent(cards: list[PaperCard], tmp_archive: Archive) -> None:
    before, after = split_by_date(cards, T)
    directions = _club_directions(before)
    judge(directions, after, MockLLM(), tmp_archive, "club")
    llm = CountingLLM(MockLLM())
    hits = judge(directions, after, llm, tmp_archive, "baseline")
    assert llm.calls == {"judge": 3}
    assert all(h.label == "baseline" for h in hits)
    assert len(hits_from_events(tmp_archive, "club")) == 3
    assert len(hits_from_events(tmp_archive, "baseline")) == 3


def test_judge_partial_resume(cards: list[PaperCard], tmp_archive: Archive, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JC_CONCURRENCY", "1")
    before, after = split_by_date(cards, T)
    directions = _club_directions(before)
    inner = MockLLM()
    n = {"calls": 0}

    def crash_on_second(user: str) -> dict:
        n["calls"] += 1
        if n["calls"] == 2:
            raise LLMError("boom")
        return inner.default("judge", user, prompts.SCHEMAS["judge"])

    with pytest.raises(LLMError):
        judge(directions, after, MockLLM(scripted={"judge": crash_on_second}), tmp_archive, "club")
    assert _types(tmp_archive, "judge") == ["step_started", "hit"]
    assert not tmp_archive.has_step("judge", "club")
    llm = CountingLLM(MockLLM())
    hits = judge(directions, after, llm, tmp_archive, "club")
    assert llm.calls == {"judge": 2}
    assert [h.direction_text for h in hits] == [d.text for d in directions]
    starts = [e for e in tmp_archive.by_step("judge") if e.type == "step_started"]
    assert starts[-1].payload == {"label": "club", "reused": 1}
    assert len(hits_from_events(tmp_archive, "club")) == 3
    assert tmp_archive.has_step("judge", "club")


def test_judge_parallel_batches_keep_order(cards: list[PaperCard], tmp_archive: Archive, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JC_CONCURRENCY", "2")
    before, after = split_by_date(cards, T)
    directions = _club_directions(before)
    hits = judge(directions, after, MockLLM(), tmp_archive, "club")
    hit_events = [e for e in tmp_archive.by_step("judge") if e.type == "hit"]
    assert [e.payload["direction_text"] for e in hit_events] == [d.text for d in directions]
    assert [h.direction_text for h in hits] == [d.text for d in directions]


def test_judge_empty_directions(cards: list[PaperCard], tmp_archive: Archive) -> None:
    _, after = split_by_date(cards, T)
    llm = CountingLLM(MockLLM())
    assert judge([], after, llm, tmp_archive, "club") == []
    assert llm.total == 0
    assert _types(tmp_archive, "judge") == ["step_started", "step_done"]


# --------------------------------------------------------------- baseline


def test_run_baseline_one_call_and_verified_quotes(cards: list[PaperCard], tmp_archive: Archive) -> None:
    before, _ = split_by_date(cards, T)
    llm = CountingLLM(MockLLM())
    directions = run_baseline(before, llm, tmp_archive, n=10, agenda="batch correction")
    assert llm.calls == {"baseline": 1}
    assert 0 < len(directions) <= 10
    by_id = {c.id: c for c in before}
    for d in directions:
        ok, failed = verify_quotes(by_id, d.quotes)
        assert ok and not failed
        assert d.papers == sorted(set(d.papers)) and set(d.papers) <= set(by_id)
    assert [d.confidence for d in directions] == sorted((d.confidence for d in directions), reverse=True)
    types = _types(tmp_archive, "baseline")
    assert types[0] == "step_started" and types[-1] == "step_done"
    assert types.count("direction") == len(directions)
    assert tmp_archive.has_step("baseline") and not tmp_archive.has_step("directions")


def test_run_baseline_prompt_has_no_discussion(cards: list[PaperCard], tmp_archive: Archive) -> None:
    before, after = split_by_date(cards, T)
    mock = MockLLM()
    run_baseline(before, mock, tmp_archive, n=10, agenda="ag")
    (kind, user), = mock.calls
    assert kind == "baseline"
    assert user.startswith("AGENDA: ag\nN: 10\n")
    assert "DISPUTES:" not in user and "SHARED_LIMITATIONS:" not in user
    assert len(re.findall(r"^PAPER sc", user, re.M)) == 6
    for c in after:
        assert f"PAPER {c.id} |" not in user


def test_run_baseline_resume_zero_calls(cards: list[PaperCard], tmp_archive: Archive) -> None:
    before, _ = split_by_date(cards, T)
    first = run_baseline(before, MockLLM(), tmp_archive, n=10)
    llm = CountingLLM(MockLLM())
    again = run_baseline(before, llm, tmp_archive, n=10)
    assert llm.total == 0 and again == first
    last = tmp_archive.by_step("baseline")[-1]
    assert last.type == "step_skipped"
    assert last.payload == {"reason": "resumed from archive", "count": len(first), "label": None}


# ---------------------------------------------------------------- leakage


def test_assert_no_leakage_catches_quote_and_papers(cards: list[PaperCard], tmp_archive: Archive) -> None:
    assert_no_leakage(tmp_archive, {"sc07", "sc08"})
    q = cards[7].quotes()[0].model_dump()
    tmp_archive.append(Event(round=1, step="map", type="pair_verdict", papers=["sc01", "sc02"], payload={"quote_a": q}, seq=0))
    with pytest.raises(RuntimeError, match="leakage.*sc08"):
        assert_no_leakage(tmp_archive, {"sc07", "sc08"})


def test_assert_no_leakage_ignores_judge_and_report(cards: list[PaperCard], tmp_archive: Archive) -> None:
    hit = _hit("d", "hit", "sc07")
    tmp_archive.append(Event(round=1, step="judge", type="hit", papers=["sc07"], payload=hit.model_dump(), seq=0))
    tmp_archive.append(Event(round=1, step="backtest", type="split", papers=[], payload={"after": ["sc07"]}, seq=0))
    assert_no_leakage(tmp_archive, {"sc07", "sc08"})


def test_run_backtest_raises_on_leaked_direction(cards: list[PaperCard], tmp_archive: Archive) -> None:
    def leaky(before: list[PaperCard]) -> list[Direction]:
        d = _direction(cards[7], cards[0], "leaked")
        tmp_archive.append(Event(round=1, step="directions", type="direction", papers=d.papers, payload=d.model_dump(), seq=0))
        return [d]

    with pytest.raises(RuntimeError, match="leakage"):
        run_backtest(cards, T, MockLLM(), tmp_archive, "ag", judge_llm=MockLLM(), club_directions=leaky)
    assert not tmp_archive.by_step("judge")


# --------------------------------------------------------------- backtest


@pytest.fixture
def backtest(cards: list[PaperCard], tmp_archive: Archive, monkeypatch: pytest.MonkeyPatch) -> tuple[BacktestReport, MockLLM, MockLLM]:
    """One mock backtest with scripted club directions."""
    monkeypatch.setenv("JC_LLM", "mock")
    main, judge_llm = MockLLM(), MockLLM()
    report = run_backtest(cards, T, main, tmp_archive, "batch correction", judge_llm=judge_llm, club_directions=_club_directions)
    return report, main, judge_llm


def test_run_backtest_report_fields(backtest: tuple[BacktestReport, MockLLM, MockLLM], cards: list[PaperCard]) -> None:
    report, main, judge_llm = backtest
    assert report.T == T and report.before_ids == BEFORE and report.after_ids == AFTER
    assert report.judge_model == "mock"
    assert [d.text for d in report.club_directions] == [d.text for d in _club_directions(cards[:6])]
    assert len(report.baseline_directions) > 0
    assert len(report.club_hits) == 3 and len(report.baseline_hits) == len(report.baseline_directions)
    assert all(h.label == "club" for h in report.club_hits)
    assert all(h.label == "baseline" for h in report.baseline_hits)
    assert report.club_rate == pytest.approx(hit_rate(report.club_hits))
    assert report.baseline_rate == pytest.approx(hit_rate(report.baseline_hits))
    assert report.club_weighted_rate == pytest.approx(weighted_rate(report.club_hits))
    assert report.baseline_weighted_rate == pytest.approx(weighted_rate(report.baseline_hits))
    assert [k for k, _ in main.calls] == ["baseline"]
    assert all(k == "judge" for k, _ in judge_llm.calls)
    assert len(judge_llm.calls) == 3 + len(report.baseline_directions)


def test_run_backtest_events(backtest: tuple[BacktestReport, MockLLM, MockLLM], tmp_archive: Archive) -> None:
    report, _, _ = backtest
    events = tmp_archive.read()
    assert events[0].step == "map" and events[0].type == "run_started"
    started = events[0].payload
    assert started["T"] == T and started["judge_model"] == "mock" and started["agenda"] == "batch correction"
    assert [c["id"] for c in started["cards"]] == BEFORE, "the archive snapshots before-T cards only"
    assert not any(c["id"] in AFTER for c in started["cards"])
    assert started["cards_sha"] == card_content_sha([c for c in _fixture_cards() if c.id in BEFORE])
    assert events[1].step == "backtest" and events[1].type == "split"
    assert events[1].payload == {"T": T, "before": BEFORE, "after": AFTER}
    assert tmp_archive.has_step("baseline")
    assert tmp_archive.has_step("judge", "club") and tmp_archive.has_step("judge", "baseline")
    last = events[-1]
    assert last.step == "backtest" and last.type == "report"
    assert BacktestReport.model_validate(last.payload) == report
    assert [e.seq for e in events] == list(range(1, len(events) + 1))


def test_run_backtest_no_after_t_in_prompts(backtest: tuple[BacktestReport, MockLLM, MockLLM], cards: list[PaperCard]) -> None:
    _, main, judge_llm = backtest
    before, after = cards[:6], cards[6:]
    for kind, user in main.calls:
        assert kind != "judge"
        for c in after:
            assert c.id not in user
            for q in c.quotes():
                assert q.text not in user
    for kind, user in judge_llm.calls:
        assert kind == "judge"
        for c in before:
            assert f"PAPER {c.id} |" not in user
            for q in c.quotes():
                assert q.text not in user


def test_run_backtest_report_md(backtest: tuple[BacktestReport, MockLLM, MockLLM], tmp_archive: Archive) -> None:
    report, _, _ = backtest
    path = Path(tmp_archive.path).parent / "report.md"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Backtest report\n")
    assert f"- T: {T}" in text and "- judge model: mock" in text
    assert "| arm | directions proposed | kept after quote gate | hits | partial | miss | strict rate | weighted rate |" in text
    club_row = next(line for line in text.splitlines() if line.startswith("| club |"))
    cells = [c.strip() for c in club_row.strip("|").split("|")]
    assert cells[1:3] == ["3", "3"]
    assert cells[6] == f"{report.club_rate:.2f}" and cells[7] == f"{report.club_weighted_rate:.2f}"
    assert text.index("## Club") < text.index("## Baseline")
    assert "| # | direction | verdict | after paper (citekey, year) | reason |" in text
    for d in report.club_directions + report.baseline_directions:
        assert d.text in text
    for h in report.club_hits:
        if h.after_paper_id == "sc08":
            assert "oyelaran2024spikein, 2024" in text
    assert text.rstrip().endswith("The judge is an LLM; verdicts were not calibrated against a control. Read the tables.")


def test_run_backtest_resume_zero_calls(backtest: tuple[BacktestReport, MockLLM, MockLLM], cards: list[PaperCard], tmp_archive: Archive) -> None:
    report, _, _ = backtest
    main, judge_llm = CountingLLM(MockLLM()), CountingLLM(MockLLM())
    again = run_backtest(cards, T, main, tmp_archive, "batch correction", judge_llm=judge_llm, club_directions=_club_directions)
    assert main.total == 0 and judge_llm.total == 0
    assert again == report
    types = [e.type for e in tmp_archive.read()]
    assert types.count("run_started") == 1 and types.count("split") == 1
    assert types.count("step_skipped") == 3 and types.count("report") == 2


def test_run_backtest_resume_mismatch(cards: list[PaperCard], tmp_archive: Archive) -> None:
    run_backtest(cards, T, MockLLM(), tmp_archive, "ag", judge_llm=MockLLM(), club_directions=_club_directions)
    with pytest.raises(RuntimeError, match="card set"):
        run_backtest(cards, "2022-01-01", MockLLM(), tmp_archive, "ag", judge_llm=MockLLM(), club_directions=_club_directions)


def test_run_backtest_rejected_directions_counted(cards: list[PaperCard], tmp_archive: Archive) -> None:
    def bad_then_good(user: str) -> dict:
        out = MockLLM().default("baseline", user, prompts.SCHEMAS["baseline"])
        out["directions"][0]["quotes"] = [{"paper_id": "sc01", "text": "this sentence is not in any paper", "loc": "p1"}]
        return out

    main = MockLLM(scripted={"baseline": bad_then_good})
    report = run_backtest(cards, T, main, tmp_archive, "ag", judge_llm=MockLLM(), club_directions=_club_directions)
    assert len(report.baseline_directions) == 9
    text = (Path(tmp_archive.path).parent / "report.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| baseline |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[1:3] == ["10", "9"]


def test_run_backtest_default_club_uses_night(cards: list[PaperCard], tmp_archive: Archive, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("journal_club.night")
    pytest.importorskip("journal_club.rounds.map_round")
    monkeypatch.setenv("JC_LLM", "mock")
    main = CountingLLM(MockLLM())
    report = run_backtest(cards, T, main, tmp_archive, "ag", judge_llm=MockLLM())
    assert main.calls["map"] == 15
    assert tmp_archive.has_step("map") and tmp_archive.has_step("directions")
    assert len(report.club_hits) == len(report.club_directions)
    assert json.loads(tmp_archive.read()[0].model_dump_json())["payload"]["T"] == T


# ------------------------------------------------- judge crash mid-batch


def test_judge_crash_mid_batch_keeps_finished_prefix(cards: list[PaperCard], tmp_archive: Archive, monkeypatch: pytest.MonkeyPatch) -> None:
    """One failing call in a batch of three does not throw away the verdicts that finished before it."""
    monkeypatch.setenv("JC_CONCURRENCY", "4")
    before, after = split_by_date(cards, T)
    directions = _club_directions(before)
    inner = MockLLM()

    def crash_on_third(user: str) -> dict:
        if user.splitlines()[0] == f"DIRECTION: {directions[2].text}":
            raise LLMError("boom")
        return inner.default("judge", user, prompts.SCHEMAS["judge"])

    with pytest.raises(LLMError):
        judge(directions, after, MockLLM(scripted={"judge": crash_on_third}), tmp_archive, "club")
    hit_events = [e for e in tmp_archive.by_step("judge") if e.type == "hit"]
    assert [e.payload["direction_text"] for e in hit_events] == [d.text for d in directions[:2]]
    assert not tmp_archive.has_step("judge", "club")
    llm = CountingLLM(MockLLM())
    hits = judge(directions, after, llm, tmp_archive, "club")
    assert llm.calls == {"judge": 1}, "only the crashed direction is re-paid"
    assert [h.direction_text for h in hits] == [d.text for d in directions]


# ------------------------------------------------- card contents on resume


def test_run_backtest_reingested_before_card_raises(cards: list[PaperCard], tmp_archive: Archive) -> None:
    run_backtest(cards, T, MockLLM(), tmp_archive, "ag", judge_llm=MockLLM(), club_directions=_club_directions)
    changed = cards[0].model_copy(deep=True)
    changed.limits[0].quote.text += " with an extra clause from re-ingest"
    with pytest.raises(RuntimeError, match="card contents"):
        run_backtest([changed, *cards[1:]], T, MockLLM(), tmp_archive, "ag", judge_llm=MockLLM(), club_directions=_club_directions)


def test_run_backtest_archive_is_a_before_t_artefact(cards: list[PaperCard], tmp_archive: Archive) -> None:
    """run_started snapshots before-T cards only, so `jc minutes` on a backtest run sees the club's cards."""
    from journal_club.minutes import cards_from_archive

    run_backtest(cards, T, MockLLM(), tmp_archive, "ag", judge_llm=MockLLM(), club_directions=_club_directions)
    assert [c.id for c in cards_from_archive(tmp_archive)] == BEFORE
    after_quotes = [q.text for c in cards if c.id in AFTER for q in c.quotes()]
    for e in tmp_archive.read():
        if e.type in ("run_started", "split"):
            blob = json.dumps(e.payload)
            assert not any(q in blob for q in after_quotes), (e.type, "after-T text in the archive header")
