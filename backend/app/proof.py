""""Show me the proof": find the exact words in the original text that back up a quiz answer."""

import os
import re

from . import llm
from .schemas import Note, Paper, Proof, Quote

MODEL = os.environ.get("PROOF_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("PROOF_EFFORT", "low")

SYSTEM = """A reader answered a quiz question about a research paper and wants to see the proof in the original text.
You get the question, its right answer and the passage of the paper it comes from. Return in `quote` the shortest
exact span of the passage (copied character for character, usually a clause or one sentence, under ~40 words) that
shows the answer is right."""


def find(paper: Paper, page: int, note: Note, question: str, answer: str, explanation: str) -> Proof:
    blocks = [paper.pages[page].blocks[i].text for i in note.blocks]
    passage = "\n\n".join(blocks)
    prompt = f"Question: {question}\nRight answer: {answer}\nWhy: {explanation}\n\nPassage:\n{passage}"
    quote = llm.ask(Quote, SYSTEM, prompt, MODEL, EFFORT).quote
    # The quote must really be in the text; find its paragraph, else fall back to the best-matching paragraph.
    for text in blocks:
        if (span := locate(text, quote)) is not None:
            return Proof(page=page, paragraph=text, quote=text[span[0] : span[1]], note=note)
    words = set(re.findall(r"\w+", (quote + " " + answer).lower()))
    best = max(blocks, key=lambda t: len(words & set(re.findall(r"\w+", t.lower()))), default="")
    return Proof(page=page, paragraph=best, quote=None, note=note)


def locate(text: str, quote: str) -> tuple[int, int] | None:
    """Where `quote` occurs in `text`, ignoring differences in whitespace and case."""
    words = quote.split()
    if not words:
        return None
    m = re.search(r"\s+".join(map(re.escape, words)), text, re.I)
    return (m.start(), m.end()) if m else None
