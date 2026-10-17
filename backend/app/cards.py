"""Summary cards for the whole paper: a TL;DR with headline numbers, a logic flow, a mind map, key findings, an
evidence map, caveats, simple charts redrawn from numbers the paper states and the key figures cropped from the PDF.
web/cards.js draws them under the graphical abstract. A deck keeps a hash of the notes it was made from, so the
reader can be told when their notes (a tutor's edit, their own) have changed since."""

import hashlib
import logging
import math
import os
import re

from . import levels, llm
from .abstract import crop_figure, running_bands
from .schemas import PageSummary, Paper, SummaryCards
from .summarize import parse_note_id

MODEL = os.environ.get("CARDS_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("CARDS_EFFORT", "medium")
MAX_TEXT = 200_000  # characters of the paper's own text sent along with the notes (numbers live there)
MAX_FIGURES = 6

log = logging.getLogger(__name__)

SYSTEM = """You turn a research paper into a deck of summary cards for someone who wants to understand it in five
minutes. You get the paper's reading notes (plain-language, in reading order) and its full text. Keep real numbers,
names and key terms; never add claims the paper doesn't make. Warm language pitched at the reader described at the
end; short lines (they sit in cards).

- tldr: the one-paragraph takeaway (2-3 sentences, under ~60 words).
- stats: 2-4 headline numbers, each a value as printed ("0.45%", "14M+", "3.1σ") and a few-word label.
- flow: 4-6 steps telling the paper's logic in order: the question/gap, what they did, the key evidence, the
  conclusion. Each a short title (under ~8 words) and one line of specifics (under ~20 words).
- topic: a 1-3 word name for the paper's subject (the centre of a mind map).
- mindmap: exactly 4 branches (e.g. method, results, implications, open questions), each a title and 3-4 points under
  ~8 words.
- findings: 4-6 key findings, each one sentence with its number where there is one.
- evidence: 4-7 rows pairing a claim with the evidence behind it (the experiment, dataset, figure or table).
- caveats: 3-5 limitations to keep in mind, including ones the authors state.
- charts: 0-2 simple comparisons worth redrawing, only from numbers stated in the text (tables are best): 2-12 items
  of the same quantity, e.g. one measurement per method or dataset. `printed` is the number exactly as it appears in
  the text (with its uncertainty if any); `value` is that number; `low`/`high` the interval when the paper gives one
  (value ± error gives low = value - error). `source` says where (e.g. "Table 4"). No chart beats a made-up one.
- figures: up to 6 of the paper's figures worth looking at, best first, by id from the figure notes (e.g. "p3n1"),
  each with a callout (under ~20 words) saying what to notice. Prefer main figures. Only ids given; none if none."""


def make(paper: Paper, summaries: list[PageSummary], pdf: bytes | None, level: str) -> SummaryCards:
    prompt = (
        f"Paper: {paper.title}\n\nNotes, in reading order:\n\n{notes_text(summaries)}"
        + f"\n\nFull text:\n\n{paper_text(paper)[:MAX_TEXT]}"
    )
    cards = clean(llm.ask(SummaryCards, f"{SYSTEM}\n\n{levels.for_prompt(level)}", prompt, MODEL, EFFORT), paper, summaries)
    cards.figures = crop_figures(cards, paper, summaries, pdf)
    cards.notes_hash, cards.notes_changed = notes_hash(summaries), False
    return cards


def notes_text(summaries: list[PageSummary]) -> str:
    """The notes the cards are made from: every section and figure note (not asides), in reading order."""
    notes = []
    for p, summary in enumerate(summaries):
        for k, n in enumerate(summary.notes):
            if n.kind == "aside":
                continue
            label = f"[figure p{p}n{k}]" if n.kind == "figure" else "[section]"
            notes.append(f"{label} {n.heading or ''}\n" + "\n".join(f"- {b}" for b in n.bullets))
    return "\n\n".join(notes)


def notes_hash(summaries: list[PageSummary]) -> str:
    return hashlib.sha256(notes_text(summaries).encode()).hexdigest()[:16]


def paper_text(paper: Paper) -> str:
    return "\n\n".join(f"[page {i + 1}]\n" + "\n".join(b.text for b in page.blocks) for i, page in enumerate(paper.pages))


def clean(cards: SummaryCards, paper: Paper, summaries: list[PageSummary]) -> SummaryCards:
    """Guardrails on what came back: sensible lengths, charts only from numbers in the text, figures only from real
    figure notes."""
    if not cards.tldr.strip() or not cards.flow:
        raise RuntimeError("The cards came back without a TL;DR or a flow")
    cards.stats, cards.flow, cards.mindmap = cards.stats[:4], cards.flow[:6], cards.mindmap[:4]
    cards.findings, cards.evidence, cards.caveats = cards.findings[:6], cards.evidence[:7], cards.caveats[:5]

    text = normalise(paper_text(paper))
    charts = []
    for chart in cards.charts[:2]:
        chart.items = [i for i in chart.items if stated(i, text)][:12]
        for i in chart.items:
            if i.low is not None and i.high is not None and not i.low <= i.value <= i.high:
                i.low = i.high = None  # an interval that doesn't contain the value is a misread; drop it
        if len(chart.items) >= 2:
            charts.append(chart)
        else:
            log.info("chart %r dropped: fewer than two numbers found in the paper", chart.title)
    cards.charts = charts

    figures, seen = [], set()
    for f in cards.figures:
        try:
            p, k = parse_note_id(f.figure)
            if summaries[p].notes[k].kind == "figure" and (p, k) not in seen:
                seen.add((p, k))
                figures.append(f)
        except (ValueError, IndexError):
            continue
    cards.figures = figures[:MAX_FIGURES]
    return cards


NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def normalise(s: str) -> str:
    """Text with the spacing and minus signs that vary between PDFs taken out, so numbers can be looked up."""
    return re.sub(r"\s+", "", s.replace("−", "-").replace("–", "-").replace(",", ""))


def stated(item, text: str) -> bool:
    """True when the item's number is printed in the paper and matches its value."""
    printed = normalise(item.printed)
    m = NUMBER.search(printed)
    if not m or not math.isfinite(item.value):
        return False
    number = float(m.group())
    if not math.isclose(number, item.value, rel_tol=1e-3, abs_tol=1e-9):
        return False
    return m.group().lstrip("-") in text


def crop_figures(cards: SummaryCards, paper: Paper, summaries: list[PageSummary], pdf: bytes | None) -> list:
    """Attach a crop of each chosen figure from the PDF; figures that don't crop cleanly are left out."""
    if not pdf:
        return []
    bands = running_bands(paper)
    kept = []
    for f in cards.figures:
        p, k = parse_note_id(f.figure)
        note = summaries[p].notes[k]
        try:
            crop = crop_figure(pdf, paper, p, note.blocks[0], bands[p]) if paper.pages[p].width else None
        except Exception:  # an odd page shouldn't sink the cards
            log.exception("figure %s skipped", f.figure)
            continue
        if crop:
            f.image, f.width, f.height, _clip = crop
            kept.append(f)
    return kept
