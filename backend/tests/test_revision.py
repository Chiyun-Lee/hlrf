"""Revision: spaced-repetition boxes, XP, streaks and which questions a review picks (on the in-memory test DB)."""

from datetime import date, timedelta

import pytest

from app import db, revision
from app.schemas import Paper, QuizQuestion

DAY = date(2026, 10, 17)


def question(prompt):
    return QuizQuestion(kind="choice", prompt=prompt, options=["a", "b"], answer=0, explanation="because")


@pytest.fixture
def bank(monkeypatch):
    """Two papers with two questions each, all new, and the clock at DAY; cleaned up afterwards."""
    clock = {"today": DAY}
    monkeypatch.setattr(revision, "today", lambda: clock["today"])
    ids = [db.save(Paper(url=f"u{i}", title=f"Paper {i}", authors=[])) for i in range(2)]
    qs = {pid: db.add_questions(pid, "outreach", [question(f"{pid} one"), question(f"{pid} two")], DAY.isoformat()) for pid in ids}
    yield clock, ids, qs
    for pid in ids:
        db.delete(pid)
    with db.lock, db.conn:
        db.conn.execute("DELETE FROM xp")


def test_boxes_and_xp(bank):
    clock, ids, qs = bank
    q = qs[ids[0]][0]
    res = revision.answer(q, correct=True, first_try=True)
    assert (res["box"], res["xp"], res["today"]) == (1, 10, 10)
    assert db.get_question(q)["due"] == (DAY + timedelta(days=1)).isoformat()
    res = revision.answer(q, correct=False, first_try=True)  # wrong: back to box 0, due today, no XP
    assert (res["box"], res["xp"]) == (0, 0) and db.get_question(q)["due"] == DAY.isoformat()
    assert revision.answer(q, correct=True, first_try=False)["xp"] == revision.XP_RIGHT_LATER


def test_banking_a_question_twice_keeps_its_progress(bank):
    clock, ids, qs = bank
    q = qs[ids[0]][0]
    revision.answer(q, correct=True, first_try=True)
    again = db.add_questions(ids[0], "expert", [question(f"{ids[0]} one")], DAY.isoformat())
    assert again == [q] and db.get_question(q)["box"] == 1


def test_streak_counts_consecutive_days(bank):
    clock, ids, qs = bank
    for days_ago in (3, 1):  # a gap two days ago breaks the run
        clock["today"] = DAY - timedelta(days=days_ago)
        revision.answer(qs[ids[0]][0], correct=True, first_try=True)
    clock["today"] = DAY
    assert revision.stats()["streak"] == 1  # yesterday counts while today has no XP yet
    revision.answer(qs[ids[0]][1], correct=True, first_try=True)
    s = revision.stats()
    assert s["streak"] == 2 and s["today"] == 10 and [d["xp"] for d in s["week"]][-4:] == [10, 0, 10, 10]


def test_review_puts_due_questions_first(bank):
    clock, ids, qs = bank
    for q in qs[ids[0]]:  # paper 0's questions answered: not due until tomorrow
        revision.answer(q, correct=True, first_try=True)
    picked = revision.session(None, n=2)
    assert {q["id"] for q in picked} == set(qs[ids[1]]) and picked[0]["paper"] == "Paper 1"
    assert len(revision.session([ids[0]], n=10)) == 2  # topped up from the not-yet-due when asked for one paper
    overview = {p["id"]: p for p in revision.overview()["papers"]}
    assert overview[ids[0]]["due"] == 0 and overview[ids[1]]["due"] == 2 and overview[ids[0]]["strength"] == 1 / revision.TOP_BOX
