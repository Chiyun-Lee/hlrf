"""Answer questions about a highlighted passage, and fold what was learned back into its note when it matters."""

import os

from . import llm, memory
from .extract import page_text
from .schemas import Note, Paper, TutorReply

MODEL = os.environ.get("TUTOR_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("TUTOR_EFFORT", "medium")

SYSTEM = """You help someone read a research paper that has been annotated with short, plain-language "doodle notes"
in the style of Claire Lamman. They highlighted a passage (from a note or from the paper itself) and asked about it.

Answer in warm, everyday language: at most about 4 short sentences (they can ask for more), an analogy if it helps, no jargon you don't explain. Write plain
text (no markdown); it's shown as-is in a small chat panel. Ground the
answer in the paper; say so when the paper doesn't cover something rather than guessing.

You can also change the note over this passage: reword bullets, rewrite its title, add to it, or trim it. Do so when:
- the reader asks for it ("reword this", "simplify that bullet", "add that to the note"): do it straight away; or
- the reader signals they're satisfied (e.g. "thanks", "got it", "that makes sense") and the chat showed that a bullet
  was confusingly worded (reword it so the next reader isn't tripped up) or that something important for
  understanding the science is missing (add it).
Then set update_note and return the note's complete new bullets (and `heading` if the title should change): keep the
rest as it is, bullets under ~15 words in the same voice, 7 at most, and say in your reply what you changed. The
reader may have edited the note themselves; keep their wording unless they ask otherwise. Otherwise leave update_note
false; never change the note for trivia or for what it already says clearly. If there is no note, never update."""


def answer(paper: Paper, page: int, note: Note | None, selection: str, messages: list[dict]) -> TutorReply:
    """`messages`: the chat so far, alternating user/assistant, ending with the reader's latest message."""
    context = f"{memory.for_prompt()}\n\nPaper: {paper.title}\nPage {page + 1} of {len(paper.pages)}. Its text:\n\n{page_text(paper.pages[page])}\n\n"
    if note:
        context += f"The note over the passage ({note.kind}):\n{note.heading or ''}\n" + "\n".join(f"- {b}" for b in note.bullets)
    else:
        context += "There is no note over this passage."
    context += f"\n\nThe reader highlighted: \"{selection}\"\n\nTheir question: "
    first, *rest = messages
    convo = [{"role": "user", "content": context + first["content"]}, *({"role": m["role"], "content": m["content"]} for m in rest)]
    return llm.ask(TutorReply, SYSTEM, convo, MODEL, EFFORT)
