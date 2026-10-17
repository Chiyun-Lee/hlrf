"""Night: three steps run in order, zero-call resume, card-set mismatch, agenda change, crash resume."""

from __future__ import annotations

import pytest

from journal_club import prompts
from journal_club.archive import Archive, Event
from journal_club.cards import PaperCard
from journal_club.llm import LLMError, MockLLM
from journal_club.night import NightResult, ResumeMismatch, check_card_contents, model_label, run_night
from journal_club.rounds.map_round import card_content_sha, card_ids_sha
from .conftest import CountingLLM

AGENDA = "batch correction"


def _types(archive: Archive) -> list[str]:
    """(step, type) of every event in order."""
    return [f"{e.step}:{e.type}" for e in archive.read()]


def test_three_steps_run_in_order(cards: list[PaperCard], tmp_archive: Archive) -> None:
    llm = CountingLLM(MockLLM())
    result = run_night(cards, llm, tmp_archive, AGENDA)
    assert isinstance(result, NightResult)
    assert llm.calls["map"] == 28 and llm.calls["directions"] == 1
    assert llm.calls["debate_turn"] == 4 * len(result.disputes)
    assert llm.calls["debate_verdict"] <= len(result.disputes)
    types = _types(tmp_archive)
    assert types[0] == "map:run_started"
    order = [types.index(f"{s}:step_done") for s in ("map", "debate", "directions")]
    assert order == sorted(order)
    started = tmp_archive.read()[0].payload
    assert started["card_ids_sha"] == card_ids_sha(cards) and started["T"] is None
    assert started["agenda"] == AGENDA and started["model"] == "mock"
    assert [c["id"] for c in started["cards"]] == [c.id for c in cards]


def test_second_run_zero_calls_three_skipped(cards: list[PaperCard], tmp_archive: Archive) -> None:
    first = run_night(cards, MockLLM(), tmp_archive, AGENDA)
    llm = CountingLLM(MockLLM())
    again = run_night(cards, llm, tmp_archive, AGENDA)
    assert llm.total == 0 and again == first
    skipped = [e for e in tmp_archive.read() if e.type == "step_skipped"]
    assert [e.step for e in skipped] == ["map", "debate", "directions", "synthesis"]
    assert skipped[0].payload == {"reason": "resumed from archive", "count": 28, "label": None}
    assert skipped[1].payload["count"] == len(first.disputes)
    assert skipped[2].payload["count"] == len(first.directions)


def test_changed_card_set_raises(cards: list[PaperCard], tmp_archive: Archive) -> None:
    run_night(cards, MockLLM(), tmp_archive, AGENDA)
    with pytest.raises(ResumeMismatch, match="card set"):
        run_night(cards[:7], MockLLM(), tmp_archive, AGENDA)


def test_step_done_sha_mismatch_raises(cards: list[PaperCard], tmp_archive: Archive) -> None:
    run_night(cards, MockLLM(), tmp_archive, AGENDA)
    bad = {"count": 28, "card_ids_sha": "0" * 64, "label": None}
    tmp_archive.append(Event(round=1, step="map", type="step_done", papers=[], payload=bad, seq=0))
    with pytest.raises(ResumeMismatch, match="map"):
        run_night(cards, MockLLM(), tmp_archive, AGENDA)


def test_agenda_change_logs_event(cards: list[PaperCard], tmp_archive: Archive, caplog: pytest.LogCaptureFixture) -> None:
    run_night(cards, MockLLM(), tmp_archive, AGENDA)
    with caplog.at_level("WARNING", logger="journal_club.night"):
        run_night(cards, MockLLM(), tmp_archive, "something else")
    changed = [e for e in tmp_archive.read() if e.type == "agenda_changed"]
    assert len(changed) == 1 and changed[0].step == "map"
    assert changed[0].payload == {"old": AGENDA, "new": "something else"}
    assert any("agenda changed" in r.message for r in caplog.records)


def test_crash_in_map_then_resume(cards: list[PaperCard], tmp_archive: Archive, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JC_CONCURRENCY", "1")
    inner = MockLLM()
    n = {"calls": 0}

    def crash_on_tenth(user: str) -> dict:
        n["calls"] += 1
        if n["calls"] == 10:
            raise LLMError("boom")
        return inner.default("map", user, prompts.SCHEMAS["map"])

    with pytest.raises(LLMError):
        run_night(cards, MockLLM(scripted={"map": crash_on_tenth}), tmp_archive, AGENDA)
    assert not tmp_archive.has_step("map")
    llm = CountingLLM(MockLLM())
    result = run_night(cards, llm, tmp_archive, AGENDA)
    assert llm.calls["map"] == 28 - 9
    assert len(result.map.pairs) == 28
    starts = [e for e in tmp_archive.by_step("map") if e.type == "step_started"]
    assert starts[-1].payload == {"label": None, "reused": 9}
    assert _types(tmp_archive).count("map:run_started") == 1


def test_model_label(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JC_LLM", raising=False)
    monkeypatch.setenv("JC_MODEL", "claude-test-1")
    assert model_label(MockLLM()) == "mock"
    assert model_label(CountingLLM(MockLLM())) == "mock"

    class Fake:
        def complete_json(self, kind: str, system: str, user: str, schema: dict) -> dict:
            return {}

    assert model_label(Fake()) == "claude-test-1"
    from journal_club.llm import AnthropicLLM, CachedLLM

    injected = AnthropicLLM(model="injected-model", client=object())
    assert model_label(injected) == "injected-model", "the backend's own model wins over JC_MODEL"
    assert model_label(CachedLLM(injected)) == "injected-model"
    monkeypatch.setenv("JC_LLM", "mock")
    assert model_label(Fake()) == "mock"


def test_reingested_card_raises_even_with_same_ids(cards: list[PaperCard], tmp_archive: Archive) -> None:
    """Same ids, new quote text: stored verdicts quote the old text, so the archive must not be reused."""
    run_night(cards, MockLLM(), tmp_archive, AGENDA)
    changed = cards[0].model_copy(deep=True)
    changed.claims[0].quote.text = changed.claims[0].quote.text + " (re-ingested with a new sentence)"
    assert card_ids_sha([changed, *cards[1:]]) == card_ids_sha(cards)
    llm = CountingLLM(MockLLM())
    with pytest.raises(ResumeMismatch, match="card contents"):
        run_night([changed, *cards[1:]], llm, tmp_archive, AGENDA)
    assert llm.total == 0


def test_run_started_carries_content_sha(cards: list[PaperCard], tmp_archive: Archive) -> None:
    run_night(cards, MockLLM(), tmp_archive, AGENDA)
    started = tmp_archive.read()[0].payload
    assert started["cards_sha"] == card_content_sha(cards)
    assert card_content_sha(cards) == card_content_sha(list(reversed(cards)))


def test_check_card_contents_tolerates_older_archives(cards: list[PaperCard]) -> None:
    check_card_contents({"card_ids_sha": card_ids_sha(cards)}, cards)
    with pytest.raises(ResumeMismatch, match="card contents"):
        check_card_contents({"cards_sha": "0" * 64}, cards)
