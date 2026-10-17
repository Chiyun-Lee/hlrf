"""Revision: Duolingo-style practice across papers. Every quiz question written (app/quiz.py) goes into a question
bank with a spaced-repetition box: a right answer moves it up a box and it comes back later (INTERVALS), a wrong one
sends it back to box 0 so it comes back today. Answers earn XP towards a daily goal; practising on consecutive days
builds a streak."""

import random
from datetime import date, timedelta

from . import db

INTERVALS = [0, 1, 3, 7, 16, 35]  # days until a question in each box comes back
TOP_BOX = len(INTERVALS) - 1
DAILY_GOAL = 50  # XP
XP_RIGHT, XP_RIGHT_LATER = 10, 5  # right first time; right after missing it earlier in the session
SESSION = 10  # questions per review


def today() -> date:
    return date.today()  # the server's local day: one reader per install, on their own machine


def answer(question_id: int, correct: bool, first_try: bool) -> dict:
    """Move the question between boxes, award XP and return the day's stats (with the XP just earned)."""
    q = db.get_question(question_id)
    if q is None:
        raise KeyError(question_id)
    box = min(q["box"] + 1, TOP_BOX) if correct else 0
    db.set_question_progress(question_id, box, (today() + timedelta(days=INTERVALS[box])).isoformat())
    xp = (XP_RIGHT if first_try else XP_RIGHT_LATER) if correct else 0
    if xp:
        db.add_xp(today().isoformat(), xp)
    return {**stats(), "xp": xp, "box": box}


def stats() -> dict:
    """Today's XP against the goal, the streak (consecutive days with any XP, counting from today, or from yesterday
    while today has none yet) and the last 7 days."""
    days = db.xp_days()
    t = today()
    day = t if days.get(t.isoformat()) else t - timedelta(days=1)
    streak = 0
    while days.get(day.isoformat()):
        streak, day = streak + 1, day - timedelta(days=1)
    week = [{"day": (d := t - timedelta(days=i)).isoformat(), "xp": days.get(d.isoformat(), 0)} for i in range(6, -1, -1)]
    return {"today": days.get(t.isoformat(), 0), "goal": DAILY_GOAL, "streak": streak, "week": week}


def overview() -> dict:
    """The Revision page: stats, and per paper how many questions it has, how many are due and how strong it is."""
    by_paper: dict[int, list[dict]] = {}
    for q in db.questions():
        by_paper.setdefault(q["paper_id"], []).append(q)
    now = today().isoformat()
    papers = []
    for pid, p in db.list_all():
        qs = by_paper.get(pid, [])
        papers.append({
            "id": pid,
            "title": p.title,
            "questions": len(qs),
            "due": sum(q["due"] <= now for q in qs),
            "strength": sum(q["box"] for q in qs) / (TOP_BOX * len(qs)) if qs else 0,  # 0-1
            "abstract_levels": db.abstract_levels(pid),  # a quiz (and so questions) needs a graphical abstract
        })
    return {**stats(), "due": sum(p["due"] for p in papers), "papers": papers}


def session(paper_ids: list[int] | None, n: int = SESSION) -> list[dict]:
    """Up to `n` questions: due ones first (most overdue, then weakest), topped up with the weakest of the rest, in a
    shuffled order so papers mix."""
    now = today().isoformat()
    qs = [q for q in db.questions() if paper_ids is None or q["paper_id"] in paper_ids]
    random.shuffle(qs)  # ties broken at random, so a top-up isn't always the same questions
    qs.sort(key=lambda q: (q["due"] > now, q["box"] if q["due"] > now else q["due"], q["box"]))
    picked = qs[:n]
    random.shuffle(picked)
    titles = {pid: p.title for pid, p in db.list_all()}
    return [{**q["question"].model_dump(), "id": q["id"], "paper_id": q["paper_id"], "paper": titles.get(q["paper_id"]), "level": q["level"]} for q in picked]
