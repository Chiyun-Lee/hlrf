"""Per-page "doodle summaries": short, plain-language notes laid over each paragraph, in the spirit of Claire Lamman's
annotated papers (https://clairelamman.com/paper_summaries.html)."""

import base64
import os
import re

import pymupdf

from . import llm, memory
from .schemas import Mark, PageSummary, Paper

MODEL = os.environ.get("SUMMARY_MODEL", "claude-opus-5-5")
CAPTION = re.compile(r"(fig(ure)?|table|extended data|supplementary)\b", re.I)
FIGURE = re.compile(r"(fig(ure)?\.?|table|extended data fig(ure)?\.?)\s*S?\d", re.I)  # a caption: "Figure 2", "Fig. 3", "Table 1"
IMAGE_DPI = 110  # enough to read a plot and point at things in it; about 1.5k tokens per page
GRID = 100  # spacing in pixels of the faint coordinate grid on page images
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
  `marks`: with the page image, also doodle on the figure itself like Lamman does: 2-4 marks pointing at the
  features that matter. shape "circle" rings a feature (a peak, a cluster, the key panel, a band on a gel); shape
  "arrow" points at one from the note. `box`: [x0, y0, x1, y1] tightly around the feature, `text_at`: [x, y], the
  centre of the note, in nearby empty space (margins, white gaps; never over data or other text), all in pixels of
  the page image (its size is given below; the faint blue grid lines are every 100 px). `text`: at most 6 plain,
  playful words ("the big jump!", "only works in pairs").
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
    prompt = f"{memory.for_prompt()}\n\nPaper: {paper.title}\nPage {index + 1} of {len(paper.pages)}.\n\n{blocks}"
    figures = pdf and any(FIGURE.match(b.text) for b in page.blocks)
    w = h = 0  # page image size, when there is one
    if figures:
        png, (w, h) = page_image(pdf, index, grid=True)
        image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png}}
        prompt = [image, {"type": "text", "text": f"The page image is {w} x {h} px.\n\n{prompt}"}]
    summary = llm.ask(PageSummary, SYSTEM, prompt, MODEL, EFFORT)
    # Keep valid block indices, each block in at most one note.
    used = set()
    for n in summary.notes:
        n.blocks = [i for i in dict.fromkeys(n.blocks) if 0 <= i < len(page.blocks) and i not in used]
        if n.kind == "figure":  # caption text only; short blocks are labels inside the figure, which must stay visible
            n.blocks = [i for i in n.blocks if CAPTION.match(page.blocks[i].text) or len(page.blocks[i].text) > 80]
        used.update(n.blocks)
        n.marks = [to_page_scale(m, w, h) for m in n.marks if n.kind == "figure" and figures and valid_mark(m, w, h)][:4]
    summary.notes = [n for n in summary.notes if n.blocks and (n.heading or n.bullets)]
    return summary


def valid_mark(m: Mark, w: int, h: int) -> bool:
    if len(m.box) != 4 or len(m.text_at) != 2 or not m.text.strip():
        return False
    x0, y0, x1, y1 = m.box
    return 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h and 0 <= m.text_at[0] <= w and 0 <= m.text_at[1] <= h


def to_page_scale(m: Mark, w: int, h: int) -> Mark:
    """Claude places marks in image pixels; the rest of the app uses 0-1000 across the page."""
    x0, y0, x1, y1 = m.box
    tx, ty = m.text_at
    sx, sy = 1000 / w, 1000 / h
    return m.model_copy(update={"box": [x0 * sx, y0 * sy, x1 * sx, y1 * sy], "text_at": [tx * sx, ty * sy]})


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


def page_image(pdf: bytes, index: int, grid: bool = False) -> tuple[str, tuple[int, int]]:
    """One page of the PDF as (base64 PNG, (width, height) in px); with `grid`, faint lines labelled every 100 px so
    Claude can say where things are."""
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:  # an in-memory copy: drawing on it changes nothing saved
        page = doc[index]
        zoom = IMAGE_DPI / 72
        if grid:
            W, H = page.rect.width, page.rect.height
            blue = (0.55, 0.7, 1)
            for px in range(GRID, int(max(W, H) * zoom), GRID):
                v = px / zoom  # in PDF points
                if v < W:
                    page.draw_line((v, 0), (v, H), color=blue, width=0.3, stroke_opacity=0.6)
                    page.insert_text((v + 1, 7), str(px), fontsize=5, color=blue)
                if v < H:
                    page.draw_line((0, v), (W, v), color=blue, width=0.3, stroke_opacity=0.6)
                    page.insert_text((1, v - 1), str(px), fontsize=5, color=blue)
        pix = page.get_pixmap(dpi=IMAGE_DPI)
        return base64.b64encode(pix.tobytes("png")).decode(), (pix.width, pix.height)


def parse_note_id(note_id: str) -> tuple[int, int]:
    """Notes are referred to as "p<page>n<note>" (0-indexed) in prompts and the API: "p3n1" -> (3, 1)."""
    page, _, note = note_id.strip().lstrip("p").partition("n")
    return int(page), int(note)
