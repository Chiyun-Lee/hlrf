"""Learning memory: what the reader asks and how they do in quizzes is kept as events, and Claude distils them into a
short learner profile that the tutor, the quiz and the page notes use to meet the reader where they are."""

import logging
import os
import threading

from . import db, llm
from .schemas import LearnerProfile

MODEL = os.environ.get("MEMORY_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("MEMORY_EFFORT", "low")
MAX_FACTS = 15

log = logging.getLogger(__name__)
updating = threading.Lock()  # one profile update at a time, so none is lost

SYSTEM = f"""You keep a short profile of someone who reads research papers with an AI tutor, so future explanations,
notes and quizzes can meet them where they are. You get the current profile and something new they just did (a
question they asked the tutor, or a quiz result). Return the updated profile: at most {MAX_FACTS} short facts
(under ~15 words each), concrete about topics and concepts, each of one kind:
- background: what they seem to know already or their field ("comfortable with ML, new to structural biology")
- struggle: concepts that tripped them up ("shaky on what a protein backbone is")
- strength: things they've shown they understand well
- interest: what they keep wanting to know more about
- preference: how they like things explained ("likes analogies", "wants the numbers")
Merge and update rather than pile up: replace a struggle with a strength once they get it, drop what's stale or
duplicated. Only record what the evidence supports, and nothing personal beyond how they learn. If nothing new is
worth keeping, return the profile unchanged."""


def record(paper_id: int | None, kind: str, data: dict, evidence: str) -> None:
    """Store an event and update the profile from it in the background (it doesn't hold up the reply)."""
    db.add_event(paper_id, kind, data)
    threading.Thread(target=update_profile, args=(evidence,), daemon=True).start()


def update_profile(evidence: str) -> None:
    with updating:
        try:
            current = db.get_profile()
            prompt = f"Current profile:\n{current.model_dump_json(indent=1)}\n\nNew evidence:\n{evidence}"
            profile = llm.ask(LearnerProfile, SYSTEM, prompt, MODEL, EFFORT)
            profile.facts = profile.facts[:MAX_FACTS]
            db.save_profile(profile)
        except Exception:
            log.exception("learner profile update failed")


def for_prompt() -> str:
    """The profile as a few lines for other prompts ("" when there's nothing yet)."""
    facts = db.get_profile().facts
    if not facts:
        return ""
    return "What we know about this reader (adapt to it; don't mention it):\n" + "\n".join(f"- ({f.kind}) {f.text}" for f in facts)
