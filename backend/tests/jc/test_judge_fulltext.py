"""The backtest's judge reads the after-T papers' full text (kept beside their cards as <id>.txt), not just the cards."""

from __future__ import annotations

from pathlib import Path

from journal_club import prompts
from journal_club.archive import Archive
from journal_club.backtest import run_backtest
from journal_club.cards import FULLTEXT_MAX, PaperCard, load_cards, load_fulltexts, save_card
from journal_club.llm import MockLLM
from journal_club.rounds.directions import Direction
from .conftest import CountingLLM

T = "2023-01-01"  # sc07 and sc08 are after T
SECRET = "The spike-in panel was later extended to eleven cell lines in every batch."


def _direction() -> Direction:
    return Direction(text="from labels to spike-ins", from_a="labels", to_b="spike-ins", because="b", papers=["sc05"],
                     quotes=[], confidence=0.5)


def test_save_card_keeps_the_text_beside_it(cards: list[PaperCard], tmp_path: Path) -> None:
    save_card(cards[0], tmp_path, fulltext="x\x07y" + "z" * (FULLTEXT_MAX + 10))
    save_card(cards[1], tmp_path)  # no text: no .txt
    (tmp_path / "stray.txt").write_text("not a card's")
    texts = load_fulltexts(tmp_path)
    assert list(texts) == [cards[0].id] and texts[cards[0].id].startswith("xyz") and len(texts[cards[0].id]) == FULLTEXT_MAX
    assert [c.id for c in load_cards(tmp_path)] == [cards[0].id, cards[1].id]  # .txt files aren't cards


def test_judge_prompt_carries_full_text_within_budget(cards: list[PaperCard]) -> None:
    after = cards[6:]
    plain = prompts.build_judge(_direction(), after)
    assert prompts.build_judge(_direction(), after, {}) == plain and "FULL_TEXT" not in plain
    long = "w" * prompts.JUDGE_TEXT_MAX
    user = prompts.build_judge(_direction(), after, {after[0].id: SECRET, after[1].id: long, "sc01": "before-T text"})
    assert user.startswith(plain.split("\n\nAFTER_PAPER")[0])  # headers unchanged
    assert SECRET in user and "before-T text" not in user
    assert user.count("w") <= prompts.JUDGE_TEXT_MAX // 2 + 50  # shared evenly by the two papers with text
    assert user.index(SECRET) > user.index(f"AFTER_PAPER: {after[0].id}")


def test_backtest_judge_reads_full_text_and_nothing_else_does(cards: list[PaperCard], tmp_archive: Archive) -> None:
    llm, judge = MockLLM(), MockLLM()
    report = run_backtest(cards, T, CountingLLM(llm), tmp_archive, "agenda", judge_llm=judge,
                          fulltexts={"sc07": SECRET, "sc01": "before-T full text"})
    assert report.judge_read_fulltext == ["sc07"]
    assert judge.calls and all(SECRET in user for kind, user in judge.calls)
    assert not any(SECRET in user for _, user in llm.calls)  # the club and baseline never see after-T text
    assert SECRET not in Path(tmp_archive.path).read_text()  # nor does the archive
    assert "- judge read in full: sc07" in (Path(tmp_archive.path).parent / "report.md").read_text()
