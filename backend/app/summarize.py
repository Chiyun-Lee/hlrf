"""Per-page "doodle summaries": short, plain-language notes laid over each paragraph, in the spirit of Claire Lamman's
annotated papers (https://clairelamman.com/paper_summaries.html)."""

import os

from . import llm
from .schemas import PageSummary, Paper

MODEL = os.environ.get("SUMMARY_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("SUMMARY_EFFORT", "low")

SYSTEM = """You annotate one page of a research paper so a curious non-expert can follow it, in the style of Claire
Lamman's doodle summaries: warm, plain, everyday language, a little playful, with concrete analogies ("The Universe is
like old milk: it started out smooth and got clumpier over time"), but without glossing over the methods. Keep the
real numbers, names and key terms; never add claims the text doesn't make.

You get the page's text blocks, numbered, with the column each sits in when known. Write a few big notes, not
one per block: typically 2-4 per page. Each note covers a run of consecutive blocks (`first` to `last`) in the same
column, e.g. a section heading plus the paragraphs under it, or several paragraphs making one point.
- `heading`: a short playful title (at most 6 words, e.g. "DARN GRAVITY WARPS LIGHT"); always use one when the run
  starts with a section heading, otherwise only if it helps.
- `bullets`: about one per paragraph covered (at most 5), each under ~15 words. They are written over the original in
  a large handwritten font, so they must be much shorter than it.
- Leave out what isn't prose: author lists, affiliations, figures, tables and their captions, display equations,
  reference-list entries, running headers, page numbers, footnotes. A run stops at such a block; don't cover it.
A paragraph continuing from the previous page is still prose: cover the part on this page."""


def summarize_page(paper: Paper, index: int) -> PageSummary:
    page = paper.pages[index]
    if not page.blocks:  # e.g. a full-page figure
        return PageSummary(notes=[])
    cols = two_columns(page)
    blocks = "\n\n".join(f"[{i}]{f' ({column(b, page)})' if cols else ''} {b.text}" for i, b in enumerate(page.blocks))
    prompt = f"Paper: {paper.title}\nPage {index + 1} of {len(paper.pages)}.\n\n{blocks}"
    summary = llm.ask(PageSummary, SYSTEM, prompt, MODEL, EFFORT)
    summary.notes = [n for n in summary.notes if 0 <= n.first <= n.last < len(page.blocks) and (n.heading or n.bullets)]
    return summary


# Column hints keep notes from straddling a two-column layout. Keep in sync with web/reader.js.


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
