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
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf
from pydantic import ValidationError

from . import db, feed
from .abstract import running_bands
from .extract import pdf_pages
from .schemas import Paper, PaperPins, PinTarget

PINS_DIR = Path(__file__).parent / "pins"
CAPTION_GAP = 40  # PDF points: how far below a figure its caption may start, or above a table its caption may end
FIGURE_REACH = 80  # ...though a figure drawn with blank space around it can end this far from its caption
FIGURE_GAP = 15  # the most whitespace between the plots and labels of one figure...
PANEL_GAP = 36  # ...or before another row of its panels
TABLE_GAP = 8  # ...and between a table's rows and rules (body text sits further off)...
RULE_GAP = 24  # ...or before another of its rules
WORDS = {"title": 4, "basic": 22, "researcher": 45}  # most words per pin line: the title sits on the button
MAX_PINS = 4
VERDICT_WORDS = 60
CLAIM_WORDS = {"claim": 20, "paper": 12, "rerun": 12, "check": 35}  # most words per field of a checked claim
MAX_CLAIMS = 8
MAX_MAIN_PROBLEMS = 5
PROBLEM_WORDS = 45
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
    if not (found or pins.claims or pins.main_problems):
        return None
    return pins.model_copy(update={"targets": found})  # the claims are about the paper, whichever PDF it is


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
    out += claim_problems(pins)
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


def claim_problems(pins: PaperPins) -> list[str]:
    """The rules for `claims` and `main_problems`, which the summary cards' Reproduction card shows."""
    out = []
    if len(pins.claims) > MAX_CLAIMS:
        out.append(f"{len(pins.claims)} claims: keep the {MAX_CLAIMS} that matter most")
    for k, c in enumerate(pins.claims, 1):
        for field, limit in CLAIM_WORDS.items():
            if (n := len((getattr(c, field) or "").split())) > limit:
                out.append(f"claim {k}: `{field}` has {n} words; cut it to {limit}")
        if c.status == "untested" and c.rerun:
            out.append(f'claim {k} is "untested" but has a `rerun`: give the status the re-run supports, or set `rerun` to null')
        if c.status != "untested" and not (c.rerun or "").strip():
            out.append(f'claim {k} is "{c.status}" without a `rerun`: say what the re-run or test gave, or mark it "untested"')
    if len(pins.main_problems) > MAX_MAIN_PROBLEMS:
        out.append(f"{len(pins.main_problems)} main problems: keep the {MAX_MAIN_PROBLEMS} most important")
    for k, text in enumerate(pins.main_problems, 1):
        if (n := len(text.split())) > PROBLEM_WORDS:
            out.append(f"main problem {k} has {n} words; cut it to {PROBLEM_WORDS}")
    return out


# --- finding figures and tables ---


def targets(paper: Paper, pdf: bytes) -> list[PinTarget]:
    """Every figure and table in the PDF, in reading order, without pins: each caption that starts with its label,
    and the pictures, vector graphics, rules and text stacked against it. Which side of their captions figures (and
    tables) sit on is voted by those with something on one side only, so a table caught between two captions goes
    with the right one. One per label."""
    left, right, columns = text_columns(paper)
    bands = running_bands(paper)
    candidates = defaultdict(list)  # label -> [(page, block, caption as printed, has punctuation)]
    for p, page in enumerate(paper.pages):
        for i, b in enumerate(page.blocks):
            if b.bbox and (m := CAPTION.match(b.text)):
                kind = "Figure" if m[2][0] in "fF" else "Table"
                label = " ".join(filter(None, [(m[1] or "").strip().title(), kind, m[3]]))
                candidates[label].append((p, i, b.text[: m.end()].strip(), bool(m[4])))
    tries = defaultdict(list)  # page -> [(block, label, caption, punctuated)]: a label's first punctuated caption, else all
    for label, cs in candidates.items():
        for p, i, caption, punctuated in [c for c in cs if c[3]][:1] or cs:
            tries[p].append((i, label, caption, punctuated))

    found, votes = {}, Counter()
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        pages = {p: layout(paper, doc, p, bands[p], left, right, columns[p]) for p in sorted(tries) if p < len(doc) and paper.pages[p].width}
        for p, lay in pages.items():
            for i, label, _, punctuated in tries[p]:
                kind = label.split()[-2]
                above, below = (drawn(s, kind) for s in sides(lay, i, kind, set()))
                if punctuated and above != below:
                    votes[kind, -1 if above else 1] += 1
        prefer = {k: 1 if votes[k, 1] > votes[k, -1] else -1 if votes[k, -1] > votes[k, 1] else default for k, default in (("Figure", -1), ("Table", 1))}
        for p, lay in pages.items():
            claimed = set()
            for i, label, caption, _ in sorted(tries[p], key=lambda t: lay["blocks"][t[0]].bbox[1]):
                kind = label.split()[-2]
                if label in found or not (picked := choose(sides(lay, i, kind, claimed), kind, prefer[kind])):
                    continue
                claimed.update(key for _, key in picked)
                region = union([r for r, (t, _) in picked if t != "c"])
                found[label] = PinTarget(label=label, page=p, caption=caption, bbox=snap(region, lay["boxes"][i]), pins=[])
    mid = (left + right) / 2  # reading order: page by page, down the left column (or the page), then the right
    return sorted(found.values(), key=lambda t: (t.page, columns[t.page] and t.bbox[0] >= mid - 10, t.bbox[1]))


def layout(paper: Paper, doc, p: int, band, left, right, two_columns) -> dict:
    """What `sides` needs of a page: its blocks, captions (punctuated ones block other figures), graphics and text."""
    blocks, (head, foot) = paper.pages[p].blocks, band
    captions = {i for i, b in enumerate(blocks) if b.bbox and (m := CAPTION.match(b.text))}
    boxes = {i: caption_box(blocks, i) for i in captions}
    in_captions = {j for i in boxes if CAPTION.match(blocks[i].text)[4] for j in caption_blocks(blocks, i)}
    texts = [(box(b.bbox), j) for j, b in enumerate(blocks) if b.bbox and j not in in_captions and head - 2 < b.bbox[1] and b.bbox[3] < foot + 2]
    return dict(blocks=blocks, boxes=boxes, stops={i for i in boxes if CAPTION.match(blocks[i].text)[4]}, texts=texts,
                graphics=page_graphics(doc[p], head, foot), width=paper.pages[p].width, left=left, right=right,
                two_columns=two_columns, colw=(right - left) / (2 if two_columns else 1))


def sides(lay: dict, i: int, kind: str, claimed: set) -> list[list]:
    """What stacks above and below caption block i: lists of (box, key), key ("g" graphic, "c" canvas or "t" text,
    index). Other captions, body text (for figures) and what other captions claimed stop a stack."""
    cap, blocks = lay["boxes"][i], lay["blocks"]
    others = [r for k, r in lay["boxes"].items() if k != i and k in lay["stops"]]
    span = column_span(cap, others, lay["width"], lay["left"], lay["right"], lay["two_columns"])
    within = lambda r: span[0] <= (r[0] + r[2]) / 2 <= span[1]
    beside = lambda r: r[0] < span[1] and span[0] < r[2]
    items = [(r, ("g" if ink else "c", k)) for k, (r, ink) in enumerate(lay["graphics"]) if within(r) and not overlaps(r, cap)]
    stops = [(r, None) for r in others if beside(r)]
    if kind == "Figure":  # body text stops a figure; the labels in it don't
        items += [(r, ("t", j)) for r, j in lay["texts"] if within(r) and j != i and not is_body(blocks[j], r, lay["colw"])]
        stops += [(r, ("t", j)) for r, j in lay["texts"] if beside(r) and j != i and is_body(blocks[j], r, lay["colw"])]
    else:  # a table's rows can be as long and wide as any paragraph, so only the gap ends it
        items += [(r, ("t", j)) for r, j in lay["texts"] if within(r) and j != i]
    stops = [(r, None if key in claimed else key) for r, key in stops] + [(r, None) for r, key in items if key in claimed]
    items = [(r, key) for r, key in items if key not in claimed]
    if kind == "Figure":  # another row of panels starts with something tall: an axis, a frame, a picture
        first, gap, jump, anchor = FIGURE_REACH, FIGURE_GAP, PANEL_GAP, lambda r, extent: r[3] - r[1] >= 20
    else:  # more of a table starts with a rule at least half its width
        first, gap, jump, anchor = CAPTION_GAP, TABLE_GAP, RULE_GAP, lambda r, extent: r[3] - r[1] <= 2 and r[2] - r[0] >= (extent[2] - extent[0]) / 2
    return [stack(cap, side, items, stops, first, gap, jump, anchor) for side in (-1, 1)]


def drawn(picked, kind: str) -> bool:
    """Whether a stack has graphics (a table's rules), and for a figure enough of them to be a picture."""
    g = [r for r, (t, _) in picked if t == "g"]
    return bool(g) and (kind != "Figure" or (union(g)[2] - union(g)[0] >= 20 and union(g)[3] - union(g)[1] >= 20))


def choose(stacks, kind: str, prefer: int):
    """The stack that is the figure or table: the preferred side's if it has graphics, else the other's; a table of
    text alone (no rules) takes whichever side has anything, preferred first."""
    ordered = stacks if prefer < 0 else stacks[::-1]
    return next((s for s in ordered if drawn(s, kind)), None) or (next((s for s in ordered if s), None) if kind == "Table" else None)


def stack(cap, side, items, stops, first, gap, jump, anchor):
    """Items stacked away from the caption on one side (-1 above, 1 below): the first within `first` of it, each next
    within `gap` of those taken, or within `jump` when it starts more of the same figure or table (an `anchor`, or a
    label right against one). A stop ends the stack, unless it's text inside what's taken already (a figure's row of
    panel titles can look like a paragraph); stops without a key always do."""
    near = (lambda r: r[3]) if side < 0 else (lambda r: r[1])
    on_side = lambda r: r[3] <= cap[1] + 1 if side < 0 else r[1] >= cap[3] - 1
    queue = [(r, key, False) for r, key in items if on_side(r)] + [(r, key, True) for r, key in stops if on_side(r)]
    graphics = [r for r, key in items if key[0] == "g" and on_side(r)]

    def more(r, key, extent):  # r is an anchor, or a label (or tick) with one just beyond it
        lo, hi = (r[1] - gap, r[3]) if side < 0 else (r[1], r[3] + gap)
        return key[0] != "t" and anchor(r, extent) or any(lo <= near(a) <= hi and a[0] < r[2] and r[0] < a[2] and anchor(a, extent) for a in graphics)

    edge, picked, extent = cap[1] if side < 0 else cap[3], [], None
    for r, key, stop in sorted(queue, key=lambda t: side * near(t[0])):
        far = side * (near(r) - edge)
        if far > (max(gap, jump) if picked else first) or stop and not (key and extent and inside(r, extent)):
            break
        if picked and far > gap and not more(r, key, extent):
            continue  # too far for a stray label or line, but more of the figure or table further on may still join
        picked.append((r, key))
        extent = union([extent, r]) if extent else r
        edge = min(edge, r[1]) if side < 0 else max(edge, r[3])
    return picked


def page_graphics(pg, head: float, foot: float) -> list[tuple[tuple, bool]]:
    """The page's pictures and vector paths between its running header and footer, each with whether it shows: a
    white fill (a plot's canvas) is just paper, so it can join a figure's panels but doesn't count towards its box.
    Paths are cut to their clip (a contour plot's fills run far outside its axes)."""
    W, H = pg.rect.width, pg.rect.height
    rects, clips = [(i["bbox"], True) for i in pg.get_image_info()], []  # clips: (level, box) of the enclosing clips
    for d in pg.get_cdrawings(extended=True):
        level = d.get("level", 0)
        while clips and clips[-1][0] >= level:
            clips.pop()
        if d["type"] in ("clip", "group"):
            scissor = d.get("scissor") or (clips[-1][1] if clips else (0, 0, W, H))
            clips.append((level, cut(scissor, clips[-1][1]) or (0, 0, 0, 0) if clips else scissor))
        elif r := cut(d["rect"], clips[-1][1]) if clips else d["rect"]:
            rects.append((r, visible(d)))
    out = []
    for (x0, y0, x1, y1), ink in rects:
        if y1 < head + 2 or y0 > foot - 2 or (x1 - x0) * (y1 - y0) > 0.9 * W * H:  # header rules, page backgrounds
            continue
        out.append(((max(x0, 0), max(y0, head + 2), min(x1, W), min(y1, foot - 2)), ink))
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
    """Whole points, clear of the caption and within CAPTION_GAP of it (taking in any blank space between), so that
    `fits` holds."""
    x0, y0, x1, y1 = int(r[0]), int(r[1]), -int(-r[2]), -int(-r[3])
    if r[3] <= cap[1]:
        y1 = min(max(y1, int(cap[1]) - CAPTION_GAP + 2), int(cap[1]))
    if r[1] >= cap[3]:
        y0 = max(min(y0, -int(-cap[3]) + CAPTION_GAP - 2), -int(-cap[3]))
    return [x0, y0, x1, y1]


def box(b) -> tuple:
    return tuple(b[:4])


def union(rects) -> tuple:
    return min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)


def cut(a, b) -> tuple | None:
    """The part of box a inside box b, or None (a line has no height, so empty boxes are kept)."""
    r = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    return r if r[0] <= r[2] and r[1] <= r[3] else None


def inside(a, b, tol=2) -> bool:
    return a[0] >= b[0] - tol and a[1] >= b[1] - tol and a[2] <= b[2] + tol and a[3] <= b[3] + tol


def overlaps(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


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
