"""A short Duolingo-style quiz on the paper, written from its notes and graphical abstract."""

import os

from . import llm
from .schemas import GraphicalAbstract, Note, PageSummary, Paper, Quiz
from .summarize import parse_note_id

MODEL = os.environ.get("QUIZ_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("QUIZ_EFFORT", "low")

SYSTEM = """You write a short quiz that checks whether someone understood a research paper they just read with
plain-language notes. Write 8 questions, in roughly the order of the paper, mixing two kinds:
- choice: a question with 3-4 options, exactly one right.
- blank: a sentence from the paper's story with one key word or short phrase replaced by "___"; `options` is a word
  bank of 3-4 tiles, exactly one right.
Test understanding of the question, the approach, the findings and why they matter, not trivia (no author names,
page numbers or exact decimals unless they are the point). Wrong options must be plausible. Keep it light and in the
voice of the notes; prompts under ~25 words, options under ~8 words. `answer` is the index of the right option.
`explanation`: one friendly line saying why the answer is right. `proof`: the id of the note (e.g. "p3n1") whose
content backs up the answer, so the reader can check it against the paper."""


def make(paper: Paper, summaries: list[PageSummary], abstract: GraphicalAbstract) -> Quiz:
    notes = [
        f"[p{p}n{k}] {n.heading or ''}\n" + "\n".join(f"- {b}" for b in n.bullets)
        for p, s in enumerate(summaries)
        for k, n in enumerate(s.notes)
        if n.kind != "aside"
    ]
    prompt = (
        f"Paper: {paper.title}\n\nGraphical abstract:\n{abstract.model_dump_json(exclude={'figures': {'__all__': {'image'}}})}"
        f"\n\nNotes:\n\n" + "\n\n".join(notes)
    )
    quiz = llm.ask(Quiz, SYSTEM, prompt, MODEL, EFFORT)
    quiz.questions = [q for q in quiz.questions if 0 <= q.answer < len(q.options)]
    for q in quiz.questions:  # drop proofs pointing at notes that don't exist
        if q.proof and not note_by_id(summaries, q.proof):
            q.proof = None
    return quiz


def note_by_id(summaries: list[PageSummary], note_id: str) -> tuple[int, Note] | None:
    """("p3n1") -> (3, that note), or None."""
    try:
        p, k = parse_note_id(note_id)
        return p, summaries[p].notes[k]
    except (ValueError, IndexError):
        return None
