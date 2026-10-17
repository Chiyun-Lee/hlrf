"""Reading levels: who the notes are written for. The reader picks one in the reader's toolbar; notes, graphical
abstracts and quizzes are written (and cached) per level, and the tutor pitches its answers to it."""

from typing import Literal

Level = Literal["outreach", "adjacent", "expert"]
DEFAULT: Level = "outreach"

AUDIENCE: dict[str, str] = {
    "outreach": """OUTREACH: someone with no science background (a curious teenager, a friend at the pub). Everyday
words only: replace jargon, or explain it in a few words the first time it comes up. Lean on concrete analogies
("The Universe is like old milk: it started out smooth and got clumpier over time"). Focus on what they asked, what
they found and why anyone should care; keep a number only when it tells the story, and skip the fine print of
methods.""",
    "adjacent": """TECHNICAL: a scientist or engineer from a neighbouring field (a physicist reading
biology, a software engineer reading an ML paper). They're at home with general science, maths and statistics but
not this field's jargon or methods: define field-specific terms in a few words the first time, say how the methods
work and why they were chosen, and keep the key numbers (with uncertainties). Use an analogy only when it bridges
from a field they'd know.""",
    "expert": """EXPERT: a researcher in this field. Use its terminology freely and never explain the basics. Be
dense: what's new compared with prior work, the specific methods, data and assumptions, the key quantitative
results (effect sizes, error bars, baselines) and the caveats and limitations. No analogies; the headings can still
be playful.""",
}


def for_prompt(level: str) -> str:
    return f"Your reader (pitch everything to them):\n{AUDIENCE[level]}"
