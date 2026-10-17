"""Per-page "doodle summaries": short, plain-language notes laid over each paragraph, in the spirit of Claire Lamman's
annotated papers (https://clairelamman.com/paper_summaries.html)."""

import base64
import os
import re

import pymupdf

from . import llm
from .schemas import PageSummary, Paper

MODEL = os.environ.get("SUMMARY_MODEL", "claude-opus-5-5")
CAPTION = re.compile(r"(fig(ure)?|table|extended data|supplementary)\b", re.I)
FIGURE = re.compile(r"(fig(ure)?\.?|table|extended data fig(ure)?\.?)\s*S?\d", re.I)  # a caption: "Figure 2", "Fig. 3", "Table 1"
IMAGE_DPI = 100  # enough to read a plot; about 1-1.5k tokens per page
EFFORT = os.environ.get("SUMMARY_EFFORT", "low")

SYSTEM = """You annotate one page of a research paper so a curious non-expert can follow it, in the style of Claire
Lamman's doodle summaries: warm, plain, everyday language, a little playful, with concrete analogies ("The Universe is
like old milk: it started out smooth and got clumpier over time"), but without glossing over the methods. Keep the
real numbers, names and key terms; never add claims the text doesn't make.

You get the page's text blocks, numbered, with the column each sits in when the page has two. Group them into a
few big notes (usually 1-4 per page) by meaning, not position: a note covers everything under one section or
subsection heading on this page, heading included, even when that text is split across columns or around a figure.
Every block belongs to at most one note. Notes come in three kinds:
- summary: the science. `heading`: a short playful title (at most 6 words, e.g. "DARN GRAVITY WARPS LIGHT").
  `bullets`: about one per paragraph covered (at most 6), each under ~15 words. They are written over the original in
  a large handwritten font, so they must be much shorter than it.
- figure: one per figure or table, covering only its caption block(s): the figure itself must stay visible, so never
  cover text from inside it (axis labels, panel letters, words in a diagram). `heading`: "FIG 2: " plus a playful
  title. `bullets`: 1-3 plain-words callouts, the way Lamman scribbles next to a plot ("This is a fancy way of showing
  that the measurements are not mixed up with each other"). When you get an image of the page, read the figure
  itself, not just its caption: what is plotted against what (axes in plain words), what to look at (the trend, the
  gap between curves, the outlier, the highlighted panel) and what it tells us.
- aside: anything that isn't the science, which the reader blurs out so people can focus: funding, acknowledgements,
  author contributions, declaration/competing interests, data and code availability, ethics statements, author lists,
  affiliations, correspondence, licence/copyright lines, reference lists, key-resources tables. `heading`: a short
  plain label (e.g. "Funding & thanks", "References"); no bullets.
Leave uncovered: running headers, page numbers, display equations and tiny fragments.
Text continuing from the previous page belongs with whatever it is part of: summarise the part on this page."""


def summarize_page(paper: Paper, index: int, pdf: bytes | None = None) -> PageSummary:
    """`pdf`: the paper's PDF, if we have it; pages with figures are then also sent as an image so Claude can read them."""
    page = paper.pages[index]
    if not page.blocks:  # e.g. a full-page figure
        return PageSummary(notes=[])
    cols = two_columns(page)
    blocks = "\n\n".join(f"[{i}]{f' ({column(b, page)})' if cols else ''} {b.text}" for i, b in enumerate(page.blocks))
    prompt = f"Paper: {paper.title}\nPage {index + 1} of {len(paper.pages)}.\n\n{blocks}"
    if pdf and any(FIGURE.match(b.text) for b in page.blocks):
        image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": page_image(pdf, index)}}
        prompt = [image, {"type": "text", "text": prompt}]
    summary = llm.ask(PageSummary, SYSTEM, prompt, MODEL, EFFORT)
    # Keep valid block indices, each block in at most one note.
    used = set()
    for n in summary.notes:
        n.blocks = [i for i in dict.fromkeys(n.blocks) if 0 <= i < len(page.blocks) and i not in used]
        if n.kind == "figure":  # caption text only; short blocks are labels inside the figure, which must stay visible
            n.blocks = [i for i in n.blocks if CAPTION.match(page.blocks[i].text) or len(page.blocks[i].text) > 80]
        used.update(n.blocks)
    summary.notes = [n for n in summary.notes if n.blocks and (n.heading or n.bullets)]
    return summary


# Column hints help Claude read two-column pages in order. Keep in sync with web/reader.js.


def two_columns(page) -> bool:
    """True when most of a PDF page's text sits in blocks narrower than half the page."""
    if not page.width:
        return False
    narrow = sum(len(b.text) for b in page.blocks if b.bbox[2] - b.bbox[0] < 0.5 * page.width)
    return narrow > 0.5 * sum(len(b.text) for b in page.blocks)


def column(block, page) -> str:
    x0, _, x1, _ = block.bbox
    if x1 - x0 > 0.6 * page.width:
        return "full width"
    return "left column" if (x0 + x1) / 2 < page.width / 2 else "right column"


def page_image(pdf: bytes, index: int) -> str:
    """One page of the PDF as a base64 PNG."""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return base64.b64encode(doc[index].get_pixmap(dpi=IMAGE_DPI).tobytes("png")).decode()


def parse_note_id(note_id: str) -> tuple[int, int]:
    """Notes are referred to as "p<page>n<note>" (0-indexed) in prompts and the API: "p3n1" -> (3, 1)."""
    page, _, note = note_id.strip().lstrip("p").partition("n")
    return int(page), int(note)
