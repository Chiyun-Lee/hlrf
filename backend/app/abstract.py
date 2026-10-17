"""A graphical abstract built from the paper's notes: title, takeaway, a flow of what was done and found, key bullets
and one or two key figures cropped from the PDF. web/abstract.js draws it as an SVG slide."""

import base64
import logging
import os
import re
from collections import Counter

import pymupdf

from . import llm
from .schemas import GraphicalAbstract, Mark, PageSummary, Paper
from .summarize import FIGURE, parse_note_id

MODEL = os.environ.get("ABSTRACT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("ABSTRACT_EFFORT", "medium")
CROP_DPI = 150
MARGIN = 0.04  # assumed header/footer depth when no running header is found
HEADER_ZONE = 0.15  # running headers and footers sit within this fraction of the page's top or bottom
MIN_FIGURE = 0.04  # a figure covers at least this fraction of its page...
MIN_INK = 0.03  # ...and isn't blank

log = logging.getLogger(__name__)

SYSTEM = """You turn a research paper's reading notes into a graphical abstract: one slide that jogs the memory of
someone who has just read the paper. Keep the voice of the notes (plain, warm, a little playful, in the style of
Claire Lamman's doodle summaries) and keep real numbers and names.

- title: a short playful title for the whole paper (at most 8 words).
- takeaway: the one thing to remember, in one sentence (under ~20 words).
- flow: 4-6 steps in order, telling the story of the paper: the question, what they did (approach), what they found,
  and what it means. Each step at most ~10 words; they sit in small boxes joined by arrows.
- bullets: 3-5 key points worth remembering that the flow doesn't already say, each under ~15 words.
- figures: up to 4 candidate figures that best capture the paper, best first, by id (e.g. "p3n1"), each with a short
  handwritten callout (under ~12 words) saying what to notice. The slide shows the first two that render. Prefer main
  figures over supplementary ones (S1, Extended Data...). Only use ids from the figure notes given; none if there are
  none."""


def make(paper: Paper, summaries: list[PageSummary], pdf: bytes | None) -> GraphicalAbstract:
    notes = []
    for p, summary in enumerate(summaries):
        for k, n in enumerate(summary.notes):
            if n.kind == "aside":
                continue
            label = f"[figure p{p}n{k}]" if n.kind == "figure" else "[section]"
            notes.append(f"{label} {n.heading or ''}\n" + "\n".join(f"- {b}" for b in n.bullets))
    prompt = f"Paper: {paper.title}\n\nNotes, in reading order:\n\n" + "\n\n".join(notes)
    abstract = llm.ask(GraphicalAbstract, SYSTEM, prompt, MODEL, EFFORT)

    abstract.flow, abstract.bullets = abstract.flow[:6], abstract.bullets[:5]
    if not abstract.flow:
        raise RuntimeError("The abstract came back without a flow")

    # Claude ranks a few candidate figures; keep the first two whose crop looks like a real figure.
    figures = []
    bands = running_bands(paper)
    for f in abstract.figures:
        if len(figures) == 2:
            break
        try:
            p, k = parse_note_id(f.figure)
            note = summaries[p].notes[k]
            if note.kind != "figure" or not pdf or not paper.pages[p].width:
                continue
            crop = crop_figure(pdf, paper, p, note.blocks[0], bands[p])
        except Exception:  # a bad id or an odd page shouldn't sink the whole abstract
            log.exception("figure %s skipped", f.figure)
            continue
        if crop:
            f.image, f.width, f.height, clip = crop
            f.marks = marks_in_crop(note.marks, clip, paper.pages[p])
            figures.append(f)
        else:
            log.info("figure %s skipped: crop didn't look like a figure", f.figure)
    abstract.figures = figures
    return abstract


def running_bands(paper: Paper) -> list[tuple[float, float]]:
    """Per page, where the running header ends and the footer starts: text near the top or bottom that repeats on
    many pages (journal names, logos' captions, page numbers) marks them."""
    def key(b):
        return re.sub(r"\d+", "#", b.text.lower())[:60]

    def zone(b, page):
        return "top" if b.bbox[3] < HEADER_ZONE * page.height else "bottom" if b.bbox[1] > (1 - HEADER_ZONE) * page.height else None

    pages = [p for p in paper.pages if p.height]
    counts = Counter(key(b) for p in pages for b in p.blocks if zone(b, p))
    # (at least a few characters, so panel letters like "a" that recur near the top of figure pages don't count)
    running = {k for k, c in counts.items() if c >= max(3, 0.25 * len(pages)) and len(k.strip("# ")) >= 4}
    bands = []
    for page in paper.pages:
        H = page.height or 0
        top = [b.bbox[3] for b in page.blocks if zone(b, page) == "top" and key(b) in running]
        bottom = [b.bbox[1] for b in page.blocks if zone(b, page) == "bottom" and key(b) in running]
        bands.append((max(top, default=MARGIN * H), min(bottom, default=(1 - MARGIN) * H)))
    return bands


def marks_in_crop(marks: list[Mark], clip: pymupdf.Rect, page) -> list[Mark]:
    """A figure's doodles moved from page coordinates (0-1000 of the page) to crop coordinates (0-1000 of the crop),
    keeping those whose feature lies in the crop and pulling their text inside it."""
    def to_crop(x, y):
        px, py = x * page.width / 1000, y * page.height / 1000
        return (px - clip.x0) / clip.width * 1000, (py - clip.y0) / clip.height * 1000

    out = []
    for m in marks:
        x0, y0 = to_crop(*m.box[:2])
        x1, y1 = to_crop(*m.box[2:])
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if not (0 <= cx <= 1000 and 0 <= cy <= 1000):
            continue
        tx, ty = to_crop(*m.text_at)
        out.append(m.model_copy(update={"box": [x0, y0, x1, y1], "text_at": [min(max(tx, 60), 940), min(max(ty, 30), 970)]}))
    return out


def crop_figure(pdf: bytes, paper: Paper, p: int, caption: int, band: tuple[float, float]):
    """The figure belonging to caption block `caption` on page `p` as (PNG data URI, width, height, clip rect), or
    None if nothing on the page looks like it.

    The figure is the pictures and vector drawings near the caption, inside the page's header/footer `band` and
    between the neighbouring captions: above the caption if there are any (the usual layout), else below it (tables),
    else anywhere in between (captions set beside the figure). Short labels inside it (panel titles, axis text) come
    along."""
    page = paper.pages[p]
    cap = pymupdf.Rect(page.blocks[caption].bbox)
    head, foot = band
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pg = doc[p]
        W, H = pg.rect.width, pg.rect.height
        graphics = [pymupdf.Rect(i["bbox"]) for i in pg.get_image_info()] + list(pg.cluster_drawings())
        # Trim graphics to the space between header and footer: logos vanish, full-page scans keep their middle.
        body = pymupdf.Rect(0, head, W, foot)
        graphics = [r & body for r in graphics]
        graphics = [r for r in graphics if r.width * r.height > 0.002 * W * H]
        captions = [pymupdf.Rect(b.bbox) for i, b in enumerate(page.blocks) if i != caption and FIGURE.match(b.text)]
        prev = max([c.y1 for c in captions if c.y1 <= cap.y0], default=head)
        nxt = min([c.y0 for c in captions if c.y0 >= cap.y1], default=foot)
        for lo, hi in ((prev, cap.y0), (cap.y1, nxt), (prev, nxt)):
            picked = [r for r in graphics if r.y0 >= lo - 4 and r.y1 <= hi + 4 and not r.intersects(cap)]
            if sum(r.width * r.height for r in picked) > MIN_FIGURE * W * H:
                break
        else:
            return None
        clip = pymupdf.Rect(picked[0])
        for r in picked[1:]:
            clip |= r
        near = clip + (-15, -15, 15, 15)
        for b in page.blocks:
            r = pymupdf.Rect(b.bbox)
            if len(b.text) < 60 and r.intersects(near) and r.y0 >= head and r.y1 <= foot and not r.intersects(cap):
                clip |= r
        clip = (clip + (-6, -6, 6, 6)) & pg.rect
        if clip.width * clip.height < MIN_FIGURE * W * H or ink(pg.get_pixmap(clip=clip, dpi=30)) < MIN_INK:
            return None
        png = pg.get_pixmap(clip=clip, dpi=CROP_DPI).tobytes("png")
    return f"data:image/png;base64,{base64.b64encode(png).decode()}", clip.width, clip.height, clip


def ink(pix) -> float:
    """Fraction of pixels that aren't (near) white: a blank crop has almost none."""
    n = pix.n
    samples = pix.samples
    pixels = len(samples) // n
    dark = sum(1 for i in range(0, len(samples), n) if min(samples[i : i + min(n, 3)]) < 230)
    return dark / max(1, pixels)
