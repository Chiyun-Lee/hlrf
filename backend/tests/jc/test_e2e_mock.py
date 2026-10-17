"""End to end with the mock: a full night, a zero-call rerun, and a backtest on the eight fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from journal_club import prompts
from journal_club.archive import Archive
from journal_club.backtest import run_backtest
from journal_club.cards import PaperCard
from journal_club.llm import MockLLM, parse_headers, parse_quotes
from journal_club.minutes import write_minutes
from journal_club.night import STEPS, NightResult, run_night
from journal_club.quotes import verify_quotes
from journal_club.rounds.directions import Direction
from .conftest import CountingLLM

AGENDA = "where is batch correction going"
T = "2023-01-01"
N_PAIRS = 28
LEGAL_VERDICTS = {"stands", "contested", "unresolved"}

# The four designed pairs of DESIGN.md §11: (relation, loc of a's quote, loc of b's quote).
DESIGNED: dict[tuple[str, str], tuple[str, str, str]] = {
    ("sc01", "sc04"): ("disagree", "p5 §3.2", "p4 §3.1"),
    ("sc02", "sc06"): ("disagree", "p5 §4.1", "p4 §3.1"),
    ("sc05", "sc06"): ("shared_limitation", "p9 §5", "p8 §5.2"),
    ("sc03", "sc07"): ("shared_limitation", "p9 §5", "p9 §5"),
}


# ---------------------------------------------------------------- helpers


def _quote(user: str, pid: str, loc: str) -> dict[str, str]:
    """The QUOTE line of one paper at one loc, from the prompt."""
    return next(q for q in parse_quotes(user) if q["paper_id"] == pid and q["loc"] == loc)


def designed_mock() -> MockLLM:
    """A mock whose `map` forces the four designed pairs and delegates to the default otherwise."""
    mock = MockLLM()

    def map_fn(user: str) -> dict:
        a, b = (s.strip() for s in parse_headers(user)["PAIR"].split("|"))
        design = DESIGNED.get((a, b))
        if design is None:
            return mock.default("map", user, prompts.SCHEMAS["map"])
        relation, loc_a, loc_b = design
        return {
            "relation": relation,
            "quote_a": _quote(user, a, loc_a),
            "quote_b": _quote(user, b, loc_b),
            "note": f"designed: {a} vs {b} ({relation})",
        }

    mock.scripted["map"] = map_fn
    return mock


def _types(archive: Archive, step: str) -> list[str]:
    """Event types of one step, in order."""
    return [e.type for e in archive.by_step(step)]


def _direction_events(archive: Archive, step: str = "directions") -> list[Direction]:
    """Every surviving direction event of a step as a model."""
    return [Direction.model_validate(e.payload) for e in archive.by_step(step) if e.type == "direction"]


# ------------------------------------------------------------------ night


@pytest.fixture
def night(cards: list[PaperCard], tmp_archive: Archive) -> tuple[NightResult, MockLLM]:
    """One full night with the designed mock."""
    mock = designed_mock()
    return run_night(cards, mock, tmp_archive, AGENDA), mock


def test_map_has_28_pair_verdicts(night: tuple[NightResult, MockLLM], tmp_archive: Archive) -> None:
    result, mock = night
    assert _types(tmp_archive, "map").count("pair_verdict") == N_PAIRS
    assert len(result.map.pairs) == N_PAIRS
    assert sum(1 for k, _ in mock.calls if k == "map") == N_PAIRS
    assert result.map.get("sc01", "sc04").relation == "disagree"
    assert result.map.get("sc02", "sc06").relation == "disagree"
    assert result.map.get("sc05", "sc06").relation == "shared_limitation"
    assert result.map.get("sc03", "sc07").relation == "shared_limitation"


def test_disputes_capped_with_legal_verdicts(night: tuple[NightResult, MockLLM], tmp_archive: Archive) -> None:
    result, _ = night
    assert 2 <= len(result.disputes) <= 5
    assert {d.verdict for d in result.disputes} <= LEGAL_VERDICTS
    keys = {(d.a, d.b) for d in result.disputes}
    assert {("sc01", "sc04"), ("sc02", "sc06")} <= keys
    assert _types(tmp_archive, "debate").count("dispute") == len(result.disputes)
    for d in result.disputes:
        assert len(d.turns) == 4
        assert all(t.speaker in (d.a, d.b) for t in d.turns)


def test_every_surviving_direction_has_a_verified_quote(
    night: tuple[NightResult, MockLLM], cards: list[PaperCard], tmp_archive: Archive
) -> None:
    result, _ = night
    by_id = {c.id: c for c in cards}
    stored = _direction_events(tmp_archive)
    assert stored and len(stored) == len(result.directions)
    for d in stored:
        ok, failed = verify_quotes(by_id, d.quotes)
        assert len(ok) >= 1 and not failed
        assert set(d.papers) <= set(by_id)
    assert [d.confidence for d in result.directions] == sorted((d.confidence for d in result.directions), reverse=True)


def test_rerun_makes_zero_llm_calls(night: tuple[NightResult, MockLLM], cards: list[PaperCard], tmp_archive: Archive) -> None:
    first, mock = night
    n_calls = len(mock.calls)
    counting = CountingLLM(mock)
    second = run_night(cards, counting, tmp_archive, AGENDA)
    assert counting.total == 0
    assert len(mock.calls) == n_calls
    assert second == first
    types = [e.type for e in tmp_archive.read()]
    assert types.count("step_skipped") == len(STEPS)
    assert types.count("run_started") == 1 and "agenda_changed" not in types
    for step in ("map", "debate", "directions"):
        assert _types(tmp_archive, step)[-1] == "step_skipped"


def test_fabricated_loc_never_reaches_minutes(cards: list[PaperCard], tmp_archive: Archive, tmp_path: Path) -> None:
    """A verbatim sentence under an invented location is dropped at every gate and never printed as evidence."""
    mock = designed_mock()
    fake_loc = "p42 Table 9 (fabricated)"

    def directions_fn(user: str) -> dict:
        real = _quote(user, "sc01", "p4 §3.1")
        return {
            "directions": [
                {
                    "text": "Fake-loc direction",
                    "from_a": "a",
                    "to_b": "b",
                    "because": "c",
                    "papers": ["sc01"],
                    "quotes": [dict(real, loc=fake_loc)],
                    "confidence": 0.9,
                },
                {
                    "text": "Real-loc direction",
                    "from_a": "a",
                    "to_b": "b",
                    "because": "c",
                    "papers": ["sc01", "sc02"],
                    "quotes": [real, dict(real, loc=fake_loc)],
                    "confidence": 0.8,
                },
            ]
        }

    mock.scripted["directions"] = directions_fn
    result = run_night(cards, mock, tmp_archive, AGENDA)
    assert [d.text for d in result.directions] == ["Real-loc direction"]
    assert result.directions[0].papers == ["sc01"] and [q.loc for q in result.directions[0].quotes] == ["p4 §3.1"]
    assert _types(tmp_archive, "directions").count("direction_rejected") == 1
    md = write_minutes(tmp_archive, cards, tmp_path / "minutes.md")
    assert "Fake-loc direction" not in md and "(fabricated)" not in md
    assert "(kim2019batchalign, p4 §3.1)" in md
    for v in result.map.pairs:
        assert "fabricated" not in v.quote_a.loc + v.quote_b.loc


def test_minutes_mention_every_direction(night: tuple[NightResult, MockLLM], cards: list[PaperCard], tmp_archive: Archive) -> None:
    result, _ = night
    path = Path(tmp_archive.path).parent / "minutes.md"
    md = write_minutes(tmp_archive, cards, path)
    assert path.exists() and path.read_text(encoding="utf-8") == md
    assert f"- agenda: {AGENDA}" in md
    for d in result.directions:
        assert d.text in md
    for d in result.disputes:
        assert f"- verdict: **{d.verdict}**" in md
    assert "## Backtest" not in md


# --------------------------------------------------------------- backtest


def test_backtest_on_a_second_archive(cards: list[PaperCard], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JC_LLM", "mock")
    mock, judge_llm = designed_mock(), MockLLM()
    with Archive(tmp_path / "bt" / "events.jsonl") as archive:
        report = run_backtest(cards, T, mock, archive, AGENDA, judge_llm=judge_llm)
        md = write_minutes(archive, cards, tmp_path / "bt" / "minutes.md")
        club_stored = _direction_events(archive, "directions")
        baseline_stored = _direction_events(archive, "baseline")
        assert _types(archive, "map").count("pair_verdict") == 15
    assert report.before_ids == ["sc01", "sc02", "sc03", "sc04", "sc05", "sc06"]
    assert report.after_ids == ["sc07", "sc08"]
    assert [d.text for d in report.club_directions] == [d.text for d in sorted(club_stored, key=lambda d: -d.confidence)]
    assert len(report.baseline_directions) == len(baseline_stored) > 0
    assert len(report.club_hits) == len(report.club_directions)
    assert len(report.baseline_hits) == len(report.baseline_directions)
    assert all(k == "judge" for k, _ in judge_llm.calls)
    for kind, user in mock.calls:
        assert kind in {"map", "debate_turn", "debate_verdict", "directions", "baseline", "synthesis"}
        assert "sc07" not in user and "sc08" not in user
    report_md = (tmp_path / "bt" / "report.md").read_text(encoding="utf-8")
    assert (tmp_path / "bt" / "minutes.md").exists()
    for d in report.club_directions + report.baseline_directions:
        assert d.text in report_md
    for d in report.club_directions:
        assert d.text in md
    assert "## Backtest" in md and "Judge model: mock" in md
