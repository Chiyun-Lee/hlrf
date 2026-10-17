"""Methods pins: buttons on a paper's figures and tables saying where its data come from, what its methods do and what
a reviewer would worry about, each in a plain line and a researcher's line. An agent review writes them for one
library paper (stored in the database, see skills/paper-pins); a few are shipped as one JSON file per arXiv id in
app/pins/.

`targets` finds a PDF's figures and tables, `problems` checks pins against the rules and `for_paper` serves them.
Run `python -m app.pins` from backend/ for the command line (targets, check, render, save)."""

import json
import logging
import re
import sys
from collections import defaultdict
from pathlib import Path

import pymupdf
from pydantic import ValidationError

from . import db, feed
from .abstract import running_bands
from .extract import pdf_pages
from .schemas import Paper, PaperPins, PinTarget

PINS_DIR = Path(__file__).parent / "pins"
CAPTION_GAP = 40  # PDF points: how far below a figure its caption may start, or above a table its caption may end
FIGURE_GAP = 15  # the most whitespace between the plots, panels and labels of one figure
TABLE_GAP = 8  # ...and between a table's rows and rules (body text sits further off)
WORDS = {"title": 4, "basic": 22, "researcher": 45}  # most words per pin line: the title sits on the button
MAX_PINS = 4
VERDICT_WORDS = 60
# A caption starts with its label and then punctuation, which a sentence that mentions it doesn't have: "Figure 3.",
# "FIG. 3:", "Table II.", "Fig. A1 |", but not "Figure 3 shows". A label without punctuation ("Fig. 3 The fit",
# Springer's style) only counts when no caption of that label has punctuation and a figure sits right against it.
CAPTION = re.compile(
    r"(?i:(extended data |supplementary )?(fig(?:ure)?|tab(?:le)?)\.?)\s*((?:[A-Z]\.?)?\d+(?:\.\d+)?[a-z]?|[IVXL]+)\b"
    r"\s*([.:|–—])?"
)

log = logging.getLogger(__name__)


def load(arxiv_id: str) -> PaperPins | None:
    path = shipped_path(arxiv_id)
    return PaperPins.model_validate_json(path.read_text()) if path.exists() else None


def shipped_path(arxiv_id: str) -> Path:
    return PINS_DIR / f"{arxiv_id.replace('/', '_')}.json"  # old-style ids (hep-th/0101001) have a slash


def has_pins(paper_id: int, url: str, arxiv_id: str | None) -> bool:
    """Whether the paper has pins, cheaply (no PDF or page parsing): for the library's "AI reviewed" filter."""
    arxiv_id = feed.arxiv_id(url, arxiv_id)
    return db.has_paper_pins(paper_id) or bool(arxiv_id and shipped_path(arxiv_id).exists())


def save(paper_id: int, pins: PaperPins) -> None:
    """Store an agent review's pins for a library paper; for_paper serves them before any shipped ones."""
    db.save_paper_pins(paper_id, pins)


def for_paper(paper_id: int, paper: Paper) -> PaperPins | None:
    """The paper's pins: an agent review's for this library paper, else the shipped ones for its arXiv id, keeping
    the figures and tables they fit. Boxes are measured on one version of the PDF, so a figure only gets its pins when
    this PDF has its caption right against the box; on another version they are dropped, never misplaced."""
    pins = db.get_paper_pins(paper_id)
    if not pins and (arxiv_id := feed.arxiv_id(paper.url, paper.arxiv_id)):
        pins = load(arxiv_id)
    if not pins:
        return None
    found = [t for t in pins.targets if fits(t, paper)]
    if len(found) < len(pins.targets):
        log.warning("pins for paper %s: %d of %d targets don't match this PDF", paper_id, len(pins.targets) - len(found), len(pins.targets))
    return pins.model_copy(update={"targets": found}) if found else None


def fits(target: PinTarget, paper: Paper) -> bool:
    """Whether the page has a block starting with the target's caption just below its box (figures) or ending just
    above it (tables), overlapping it sideways."""
    if not 0 <= target.page < len(paper.pages):
        return False
    x0, y0, x1, y1 = target.bbox
    blocks = paper.pages[target.page].blocks
    for i, b in enumerate(blocks):
        if not (b.bbox and b.text.startswith(target.caption)) or b.text[len(target.caption) :][:1].isalnum():
            continue  # (a caption "Fig. 1" isn't "Fig. 10")
        cx0, cy0, cx1, cy1 = caption_box(blocks, i)
        if cx0 < x1 and x0 < cx1 and (0 <= cy0 - y1 <= CAPTION_GAP or 0 <= y0 - cy1 <= CAPTION_GAP):
            return True
    return False


def problems(pins: PaperPins, paper: Paper, found: list[PinTarget] | None = None) -> list[str]:
    """Every rule the pins break, as a message saying what to fix; [] when they're fine. `found`, the paper's figures
    and tables from `targets`, lets the messages point at the right box."""
    out = []
    if not pins.reviewed.strip():
        out.append('`reviewed` is empty: say what the pins rest on, e.g. "Agent review of arXiv:2506.22373v2: the '
                   "authors' notebooks re-run and the claims tested, 17 Oct 2026\"")
    if pins.verdict and len(pins.verdict.split()) > VERDICT_WORDS:
        out.append(f"`verdict` has {len(pins.verdict.split())} words: give the review's bottom line in 1-2 sentences (at most {VERDICT_WORDS} words)")
    if pins.arxiv_id and (own := feed.arxiv_id(paper.url, paper.arxiv_id)) and pins.arxiv_id != own:
        out.append(f"`arxiv_id` is {pins.arxiv_id} but this paper is {own}: use {own} (no version)")
    if not pins.targets:
        out.append("no targets: give every figure and table in targets.json a Data provenance pin")
    known = {t.label: t for t in found or []}
    seen = set()
    for t in pins.targets:
        if t.label in seen:
            out.append(f"{t.label} appears twice: merge its pins into one target")
        seen.add(t.label)
        if not fits(t, paper):
            f = known.get(t.label)
            fix = (f'copy its page ({f.page}), caption ("{f.caption}") and bbox ({f.bbox}) from targets.json' if f else
                   "check page (0-indexed), caption (how the caption starts, as printed) and bbox (PDF points from the top-left)")
            out.append(f'{t.label}: no caption starting "{t.caption}" is right against its box on page {t.page}, so it '
                       f"would not show; {fix}")
        kinds = [p.kind for p in t.pins]
        if kinds.count("data") != 1:
            out.append(f"{t.label} has {kinds.count('data')} Data provenance pins (kind \"data\"): give it exactly one, first")
        elif kinds[0] != "data":
            out.append(f"{t.label}: put its Data provenance pin (kind \"data\") first")
        if len(t.pins) > MAX_PINS:
            out.append(f"{t.label} has {len(t.pins)} pins: keep the {MAX_PINS} most important")
        for pin in t.pins:
            for field, limit in WORDS.items():
                if (n := len(getattr(pin, field).split())) > limit:
                    out.append(f'{t.label}, pin "{pin.title}": `{field}` has {n} words; cut it to {limit}')
    return out


# --- finding figures and tables ---


def targets(paper: Paper, pdf: bytes) -> list[PinTarget]:
    """Every figure and table in the PDF, in reading order, without pins: each caption that starts with its label,
    and the pictures, vector graphics, rules and text that sit against it (figures above their captions, tables
    usually below; whichever side has them). One per label."""
    left, right, columns = text_columns(paper)
    bands = running_bands(paper)
    candidates = defaultdict(list)  # label -> [(page, block, caption as printed, has punctuation)]
    for p, page in enumerate(paper.pages):
        for i, b in enumerate(page.blocks):
            if b.bbox and (m := CAPTION.match(b.text)):
                kind = "Figure" if m[2][0] in "fF" else "Table"
                label = " ".join(filter(None, [(m[1] or "").strip().title(), kind, m[3]]))
                candidates[label].append((p, i, b.text[: m.end()].strip(), bool(m[4])))
    tries = defaultdict(list)  # page -> [(block, label, caption)]: the first punctuated caption of each label, else all
    for label, cs in candidates.items():
        for p, i, caption, _ in [c for c in cs if c[3]][:1] or cs:
            tries[p].append((i, label, caption))

    found = {}
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        for p in sorted(tries):
            page = paper.pages[p]
            if p >= len(doc) or not page.width:
                continue
            head, foot = bands[p]
            boxes = {i: caption_box(page.blocks, i) for i, b in enumerate(page.blocks) if b.bbox and (m := CAPTION.match(b.text)) and m[4]}
            in_captions = {j for i in boxes for j in caption_blocks(page.blocks, i)}
            graphics = page_graphics(doc[p], head, foot)
            texts = [(box(b.bbox), j) for j, b in enumerate(page.blocks) if b.bbox and j not in in_captions and head - 2 < b.bbox[1] and b.bbox[3] < foot + 2]
            claimed = set()
            for i, label, caption in sorted(tries[p], key=lambda t: page.blocks[t[0]].bbox[1]):
                if label in found:
                    continue
                cap = boxes.get(i) or caption_box(page.blocks, i)
                others = [r for k, r in boxes.items() if k != i]
                span = column_span(cap, others, page.width, left, right, columns[p])
                colw = (right - left) / (2 if columns[p] else 1)
                if region := place(cap, label.split()[-2], span, graphics, texts, others, claimed, colw, page.blocks):
                    found[label] = PinTarget(label=label, page=p, caption=caption, bbox=snap(region, cap), pins=[])
    mid = (left + right) / 2  # reading order: page by page, down the left column (or the page), then the right
    return sorted(found.values(), key=lambda t: (t.page, columns[t.page] and t.bbox[0] >= mid - 10, t.bbox[1]))


def place(cap, kind, span, graphics, texts, others, claimed, colw, blocks):
    """The box of the figure or table whose caption is `cap`, or None. Claims what it takes, so the next caption on
    the page can't take it too."""
    within = lambda r: span[0] <= (r[0] + r[2]) / 2 <= span[1]
    beside = lambda r: r[0] < span[1] and span[0] < r[2]
    items = [(r, ("g", k)) for k, r in enumerate(graphics) if within(r) and not overlaps(r, cap)]
    stops = [r for r in others if beside(r)]
    if kind == "Figure":  # body text stops a figure; the labels in it don't
        items += [(r, ("t", j)) for r, j in texts if within(r) and not is_body(blocks[j], r, colw)]
        stops += [r for r, j in texts if beside(r) and is_body(blocks[j], r, colw)]
    else:  # a table's rows can be as long and wide as any paragraph, so only the gap ends it
        items += [(r, ("t", j)) for r, j in texts if within(r)]
    items = [(r, key) for r, key in items if key not in claimed]
    stops += [r for r, key in items if key in claimed]
    gap = FIGURE_GAP if kind == "Figure" else TABLE_GAP
    sides = [stack(cap, side, items, stops, gap) for side in (-1, 1)]  # above, below

    def drawn(picked):  # some graphics, and for a figure enough of them to be a picture
        g = [r for r, (t, _) in picked if t == "g"]
        return g and (kind != "Figure" or (union(g)[2] - union(g)[0] >= 20 and union(g)[3] - union(g)[1] >= 20))

    if kind == "Figure":
        picked = next((s for s in sides if drawn(s)), None)  # above first: figure captions go below
    else:  # tables: the side with rules; if both or neither, the nearer one
        ruled = [s for s in sides if drawn(s)]
        options = ruled if len(ruled) == 1 else [s for s in sides if s]
        picked = min(options, key=lambda s: distance(cap, s[0][0]), default=None)
    if not picked:
        return None
    claimed.update(key for _, key in picked)
    return union([r for r, _ in picked])


def stack(cap, side, items, stops, gap):
    """Items stacked away from the caption on one side (-1 above, 1 below): the first within CAPTION_GAP of it, each
    next within `gap` of those taken; a stop ends the stack."""
    near = (lambda r: r[3]) if side < 0 else (lambda r: r[1])
    on_side = lambda r: r[3] <= cap[1] + 1 if side < 0 else r[1] >= cap[3] - 1
    queue = sorted([(r, key) for r, key in items if on_side(r)] + [(r, None) for r in stops if on_side(r)], key=lambda t: side * near(t[0]))
    edge, allowed, picked = cap[1] if side < 0 else cap[3], CAPTION_GAP, []
    for r, key in queue:
        if side * (near(r) - edge) > allowed or key is None:
            break
        picked.append((r, key))
        edge, allowed = (min(edge, r[1]) if side < 0 else max(edge, r[3])), gap
    return picked


def page_graphics(pg, head: float, foot: float) -> list[tuple]:
    """The page's pictures and visible vector paths between its running header and footer (white fills, such as a
    plot's background, are just paper)."""
    W, H = pg.rect.width, pg.rect.height
    rects = [i["bbox"] for i in pg.get_image_info()] + [d["rect"] for d in pg.get_cdrawings() if visible(d)]
    out = []
    for x0, y0, x1, y1 in rects:
        if y1 < head + 2 or y0 > foot - 2 or (x1 - x0) * (y1 - y0) > 0.9 * W * H:  # header rules, page backgrounds
            continue
        out.append((max(x0, 0), max(y0, head + 2), min(x1, W), min(y1, foot - 2)))
    return out


def visible(d: dict) -> bool:
    fill = d.get("fill") if "f" in d["type"] and d.get("fill_opacity", 1) else None
    stroke = d.get("color") if "s" in d["type"] and d.get("stroke_opacity", 1) else None
    return any(c is not None and min(c) < 0.95 for c in (fill, stroke))


def caption_blocks(blocks, i) -> list[int]:
    """Block i, a caption, and the blocks right after it that continue it (a subscript or a font change can split
    one)."""
    out, (x0, y0, x1, y1) = [i], blocks[i].bbox
    for j in range(i + 1, len(blocks)):
        b = blocks[j].bbox
        if not b or not (y0 - 2 <= b[1] <= y1 + 2 and b[0] < x1 and x0 < b[2]) or CAPTION.match(blocks[j].text):
            break
        out.append(j)
        y1 = max(y1, b[3])
    return out


def caption_box(blocks, i) -> tuple:
    return union([box(blocks[j].bbox) for j in caption_blocks(blocks, i)])


def text_columns(paper: Paper) -> tuple[float, float, list[bool]]:
    """The text's left and right edges, and per page whether it's set in two columns: most of its paragraphs are
    under 60% as wide as the text (a page without paragraphs, all figures say, goes with the paper)."""
    paras = [[b.bbox for b in page.blocks if b.bbox and len(b.text) >= 100] for page in paper.pages]
    every = [b for page in paras for b in page]
    if not every:
        return 0, next((page.width for page in paper.pages if page.width), 612), [False] * len(paper.pages)
    left, right = min(b[0] for b in every), max(b[2] for b in every)
    two = lambda bs: sum(b[2] - b[0] < 0.6 * (right - left) for b in bs) > len(bs) / 2
    return left, right, [two(bs) if bs else two(every) for bs in paras]


def column_span(cap, others, width, left, right, two_columns) -> tuple[float, float]:
    """Where the caption's figure can be sideways: its column (or the page), shared with any caption beside it."""
    mid = (left + right) / 2
    x0, x1 = (0, mid) if two_columns and cap[2] <= mid + 10 else (mid, width) if two_columns and cap[0] >= mid - 10 else (0, width)
    for o in others:  # side-by-side figures: split the width between their captions
        if o[1] < cap[3] and cap[1] < o[3]:
            if o[0] >= cap[2] - 5:
                x1 = min(x1, (cap[2] + o[0]) / 2)
            elif o[2] <= cap[0] + 5:
                x0 = max(x0, (o[2] + cap[0]) / 2)
    return x0, x1


def is_body(block, r, colw) -> bool:
    """A paragraph of running text (not a label in a figure): long and about as wide as a column."""
    return len(block.text) >= 80 and r[2] - r[0] >= 0.7 * colw


def snap(r, cap) -> list[float]:
    """Whole points, clear of the caption (so `fits` holds)."""
    x0, y0, x1, y1 = int(r[0]), int(r[1]), -int(-r[2]), -int(-r[3])
    if r[3] <= cap[1]:
        y1 = min(y1, int(cap[1]))
    if r[1] >= cap[3]:
        y0 = max(y0, -int(-cap[3]))
    return [x0, y0, x1, y1]


def box(b) -> tuple:
    return tuple(b[:4])


def union(rects) -> tuple:
    return min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)


def overlaps(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def distance(cap, r) -> float:
    return max(cap[1] - r[3], r[1] - cap[3])


def iou(a, b) -> float:
    w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    inter = max(w, 0) * max(h, 0)
    area = lambda r: (r[2] - r[0]) * (r[3] - r[1])
    return inter / (area(a) + area(b) - inter) if inter else 0.0


# --- command line ---

USAGE = """python -m app.pins COMMAND (from backend/; PAPERS_DB picks the library)
  targets PAPER                 the paper's figures and tables as JSON (what targets.json holds)
  check PAPER PINS.json         the problems with the pins, or "ok"
  render PAPER PAGE OUT.png     draw the found boxes (or PINS.json's, given as a 4th argument) on page PAGE (0-indexed)
  save PAPER_ID PINS.json       check, then store the pins for the library paper
PAPER is a library paper id or the path of a PDF."""


def open_paper(arg: str) -> tuple[Paper, bytes]:
    if arg.isdigit():
        paper, pdf = db.get(int(arg)), db.get_pdf(int(arg))
        if not paper or not pdf:
            sys.exit(f"paper {arg}: not in the library ({db.DB_PATH}), or saved without its PDF")
        return paper, pdf
    pdf = Path(arg).read_bytes()
    return Paper(url=Path(arg).resolve().as_uri(), title="", authors=[], pages=pdf_pages(pdf)), pdf


def read_pins(path: str) -> PaperPins:
    try:
        return PaperPins.model_validate_json(Path(path).read_text())
    except ValidationError as e:
        sys.exit("\n".join(f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()))


def main(args: list[str]) -> None:
    cmd, rest = (args[0], args[1:]) if args else ("", [])
    if cmd == "targets" and len(rest) == 1:
        print(json.dumps([t.model_dump() for t in targets(*open_paper(rest[0]))], indent=1, ensure_ascii=False))
    elif cmd in ("check", "save") and len(rest) == 2 and (cmd == "check" or rest[0].isdigit()):
        paper, pdf = open_paper(rest[0])
        pins = read_pins(rest[1])
        found = targets(paper, pdf)
        if issues := problems(pins, paper, found):
            sys.exit("\n".join(issues))
        if missing := [t.label for t in found if t.label not in {p.label for p in pins.targets}]:
            print(f"note: no pins on {', '.join(missing)}", file=sys.stderr)
        if cmd == "save":
            save(int(rest[0]), pins)
        print("ok" if cmd == "check" else f"ok: saved {len(pins.targets)} targets for paper {rest[0]}")
    elif cmd == "render" and len(rest) in (3, 4) and rest[1].isdigit():
        paper, pdf = open_paper(rest[0])
        page = int(rest[1])
        shown = read_pins(rest[3]).targets if len(rest) == 4 else targets(paper, pdf)
        with pymupdf.open(stream=pdf, filetype="pdf") as doc:
            pg = doc[page]
            for t in shown:
                if t.page == page:
                    pg.draw_rect(t.bbox, color=(0.9, 0.1, 0.1), width=1.5)
                    pg.insert_text((t.bbox[0] + 2, max(t.bbox[1] - 3, 8)), f"{t.label} ({t.caption})", fontsize=9, color=(0.9, 0.1, 0.1))
            pg.get_pixmap(dpi=110).save(rest[2])
        print(rest[2])
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    main(sys.argv[1:])
