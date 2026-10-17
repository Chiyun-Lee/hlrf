// Write or draw on the paper and Ask about it, as in the PDF Notebook. ✎ Write (bottom-left) turns the pages into
// paper you can write on with a pen, a mouse or a finger: pens in three colours, a highlighter, an eraser, undo. Ask ✦
// sends the part of the paper on screen, with your ink on it, to Claude (backend/app/ink.py), which reads the
// handwriting and answers in one card pinned next to it (Markdown with maths, typeset by MathJax). Cards can be
// dragged by their header, folded or removed; a follow-up Ask builds on the earlier cards.
//
// Ink lives on PDF pages only, in PDF points, so it stays put at any width. Strokes and cards are saved per paper
// (GET/PUT /papers/:id/ink) shortly after each change. While ✎ Write is off the ink layer lets every click through,
// so the notes, pins and highlight-to-ask work as before.

const FREEHAND = "https://cdn.jsdelivr.net/npm/perfect-freehand@1.2.2/dist/esm/index.mjs";
const MARKED = "https://cdn.jsdelivr.net/npm/marked@15.0.12/lib/marked.esm.js";
const PENS = ["#1f2f7a", "#b0181c", "#1d7a3a"]; // navy ink, red, green
const HIGHLIGHTER = "#f2d50f";
const WIDTH = { pen: 1.6, highlighter: 11 }; // PDF points
const ERASER = 5; // PDF points around the pointer
const CARD_WIDTH = 240; // PDF points, at most 45% of the page
const CARD_HEIGHT = 150; // estimated, for placement; the card grows downwards from there
const GAP = 8;
const SAVE_AFTER = 600; // ms after the last change
const CAPTURE_EDGE = 1568; // longest side of the image sent to Claude, in pixels

let getStroke; // perfect-freehand, once loaded; plain lines until then (or if it can't load)
let markedLib;
let ink; // the open paper's ink: {paperId, pages, strokes, cards, ...}

// Sets up writing on the reader's PDF pages. Called by renderReader once the pages are in `container`.
async function setupInk(container, paperId, p) {
  const pageEls = [...container.querySelectorAll(".pdf-page")];
  if (!pageEls.length) return; // papers we only have as HTML
  import(FREEHAND).then((m) => ((getStroke = m.getStroke), ink?.pages.forEach(redrawPage))).catch(() => {});
  const pages = new Map();
  for (const el of pageEls) {
    const i = +el.dataset.page;
    const { width, height } = p.pages[i];
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ink");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("preserveAspectRatio", "none");
    el.append(svg);
    const page = { el, svg, i, width, height, blocks: p.pages[i].blocks.map((b) => b.bbox).filter(Boolean) };
    pages.set(i, page);
    wirePointer(page);
  }
  ink = { paperId, container, pages, strokes: [], cards: [], undo: [], redo: [], tool: "pen", color: PENS[0], askedUpTo: 0 };
  const state = ink;
  container.after(toolbar(state));
  try {
    const saved = await api(`/papers/${paperId}/ink`);
    if (ink !== state) return; // left the paper meanwhile
    state.strokes = [...saved.strokes, ...state.strokes]; // keep anything drawn while it loaded
    state.cards = [...saved.cards, ...state.cards];
    state.askedUpTo = saved.strokes.length;
    pages.forEach(redrawPage);
    saved.cards.forEach((c) => showCard(state, c));
  } catch (e) {
    console.warn("couldn't load ink", e);
  }
}

// --- Toolbar -------------------------------------------------------------------------------------------------------

function toolbar(state) {
  const bar = document.createElement("div");
  bar.className = "ink-bar";
  bar.setAttribute("role", "toolbar");
  bar.setAttribute("aria-label", "Write on the paper");
  bar.innerHTML = `
    <button class="ink-write" aria-pressed="false" title="Write or draw on the paper">✎ Write</button>
    <span class="ink-tools" hidden>
      ${PENS.map((c, k) => `<button data-tool="pen" data-color="${c}" title="Pen" aria-pressed="${k === 0}"><i style="background:${c}"></i></button>`).join("")}
      <button data-tool="highlighter" data-color="${HIGHLIGHTER}" title="Highlighter" aria-pressed="false"><i class="hl" style="background:${HIGHLIGHTER}"></i></button>
      <button data-tool="eraser" title="Eraser" aria-pressed="false">⌫</button>
      <button class="ink-undo" title="Undo (⌘Z)">↶</button>
      <button class="ink-redo" title="Redo (⇧⌘Z)">↷</button>
    </span>
    <button class="ink-ask" title="Ask about what you wrote on screen">Ask ✦</button>`;
  const write = bar.querySelector(".ink-write");
  write.onclick = () => {
    const on = write.getAttribute("aria-pressed") !== "true";
    write.setAttribute("aria-pressed", on);
    bar.querySelector(".ink-tools").hidden = !on;
    state.container.classList.toggle("writing", on);
  };
  bar.querySelectorAll("[data-tool]").forEach((b) =>
    b.addEventListener("click", () => {
      state.tool = b.dataset.tool;
      if (b.dataset.color) state.color = b.dataset.color;
      bar.querySelectorAll("[data-tool]").forEach((o) => o.setAttribute("aria-pressed", o === b));
    }),
  );
  bar.querySelector(".ink-undo").onclick = () => undo(state);
  bar.querySelector(".ink-redo").onclick = () => redo(state);
  bar.querySelector(".ink-ask").onclick = () => ask(state);
  return bar;
}

document.addEventListener("keydown", (e) => {
  if (!ink?.container.isConnected || !(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== "z") return;
  if (e.target.closest?.("input, textarea, [contenteditable=true]")) return;
  e.preventDefault();
  e.shiftKey ? redo(ink) : undo(ink);
});

// --- Drawing -------------------------------------------------------------------------------------------------------

// Pen, mouse or finger draw while ✎ Write is on. Once a pen has touched the page, fingers scroll instead (palm
// rejection, for a tablet with a stylus).
function wirePointer(page) {
  const { svg } = page;
  let live = null; // {stroke, path} being drawn, or {erased} while erasing
  let scrolling = null;
  let penSeen = false;

  const toPage = (e) => {
    const r = svg.getBoundingClientRect();
    return [round(((e.clientX - r.left) / r.width) * page.width), round(((e.clientY - r.top) / r.height) * page.height)];
  };

  svg.addEventListener("pointerdown", (e) => {
    if (e.button > 0) return;
    if (e.pointerType === "pen") penSeen = true;
    if (penSeen && e.pointerType === "touch") return (scrolling = { id: e.pointerId, y: e.clientY });
    e.preventDefault();
    capturePointer(svg, e);
    const state = ink;
    if (state.tool === "eraser") {
      live = { id: e.pointerId, erased: [] };
      erase(state, page, toPage(e), live.erased);
      return;
    }
    const stroke = { id: newId(), page: page.i, tool: state.tool, color: state.color, width: WIDTH[state.tool], points: [] };
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    svg.append(path);
    live = { id: e.pointerId, stroke, path };
    addPoint(live, e, toPage);
  });

  svg.addEventListener("pointermove", (e) => {
    if (scrolling?.id === e.pointerId) return (scrollBy(0, scrolling.y - e.clientY), (scrolling.y = e.clientY));
    if (live?.id !== e.pointerId) return;
    if (live.erased) return erase(ink, page, toPage(e), live.erased);
    const coalesced = e.getCoalescedEvents?.() ?? [];
    for (const ev of coalesced.length ? coalesced : [e]) addPoint(live, ev, toPage);
  });

  const end = (e) => {
    if (scrolling?.id === e.pointerId) scrolling = null;
    if (live?.id !== e.pointerId) return;
    const done = live;
    live = null;
    if (done.erased) {
      if (done.erased.length) record(ink, { remove: { strokes: done.erased } });
      return;
    }
    done.path.remove();
    if (done.stroke.points.length) record(ink, { add: { strokes: [done.stroke] } });
  };
  svg.addEventListener("pointerup", end);
  svg.addEventListener("pointercancel", end);
}

function addPoint(live, e, toPage) {
  const [x, y] = toPage(e);
  const p = e.pointerType === "pen" ? round(e.pressure, 2) : 0.5;
  const last = live.stroke.points.at(-1);
  if (last && last[0] === x && last[1] === y) return;
  live.stroke.points.push([x, y, p]);
  drawStroke(live.path, live.stroke, false);
}

function drawStroke(path, s, finished = true) {
  path.setAttribute("class", s.tool);
  if (getStroke) {
    const pressure = s.points.some(([, , p]) => p !== 0.5);
    const outline =
      s.tool === "highlighter"
        ? getStroke(s.points, { size: s.width, thinning: 0, smoothing: 0.6, streamline: 0.4, simulatePressure: false, last: finished })
        : getStroke(s.points, { size: s.width * 1.6, thinning: pressure ? 0.6 : 0, smoothing: 0.5, streamline: 0.45, simulatePressure: !pressure, last: finished });
    path.setAttribute("d", outlinePath(outline));
    path.setAttribute("fill", s.color);
    path.removeAttribute("stroke");
  } else {
    path.setAttribute("d", s.points.map(([x, y], k) => `${k ? "L" : "M"}${x} ${y}`).join(" "));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", s.color);
    path.setAttribute("stroke-width", s.width);
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
  }
}

function outlinePath(outline) {
  if (outline.length < 2) return "";
  let d = `M${outline[0][0].toFixed(1)} ${outline[0][1].toFixed(1)}`;
  for (let k = 1; k < outline.length; k++) {
    const [x0, y0] = outline[k - 1];
    const [x1, y1] = outline[k];
    d += ` Q${x0.toFixed(1)} ${y0.toFixed(1)} ${((x0 + x1) / 2).toFixed(1)} ${((y0 + y1) / 2).toFixed(1)}`;
  }
  return `${d} Z`;
}

// Highlights under pen strokes, both in drawing order.
function redrawPage(page) {
  page.svg.replaceChildren();
  const strokes = ink.strokes.filter((s) => s.page === page.i);
  for (const s of [...strokes.filter((s) => s.tool === "highlighter"), ...strokes.filter((s) => s.tool !== "highlighter")]) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    drawStroke(path, s);
    page.svg.append(path);
  }
}

// Removes (into `erased`) every stroke on the page passing within ERASER of `at`.
function erase(state, page, at, erased) {
  const hit = state.strokes.filter((s) => s.page === page.i && nearStroke(s, at, ERASER + s.width / 2));
  if (!hit.length) return;
  state.strokes = state.strokes.filter((s) => !hit.includes(s));
  erased.push(...hit);
  redrawPage(page);
}

function nearStroke(s, [x, y], r) {
  const pts = s.points;
  if (pts.length === 1) return Math.hypot(pts[0][0] - x, pts[0][1] - y) <= r;
  for (let k = 1; k < pts.length; k++) if (segmentDistance(pts[k - 1], pts[k], x, y) <= r) return true;
  return false;
}

function segmentDistance([ax, ay], [bx, by], x, y) {
  const dx = bx - ax;
  const dy = by - ay;
  const t = dx || dy ? Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy))) : 0;
  return Math.hypot(ax + t * dx - x, ay + t * dy - y);
}

// --- Undo and saving -----------------------------------------------------------------------------------------------

// An action adds and/or removes strokes and cards. `record` applies a new one (erased strokes are already gone).
function record(state, action) {
  apply(state, action);
  state.undo.push(action);
  state.redo = [];
}

function apply(state, { add, remove }) {
  const has = (list, x) => list.some((y) => y.id === x.id);
  if (remove?.strokes) state.strokes = state.strokes.filter((s) => !has(remove.strokes, s));
  if (remove?.cards) (state.cards = state.cards.filter((c) => !has(remove.cards, c))), remove.cards.forEach(hideCard);
  if (add?.strokes) state.strokes.push(...add.strokes.filter((s) => !has(state.strokes, s)));
  if (add?.cards) add.cards.filter((c) => !has(state.cards, c)).forEach((c) => (state.cards.push(c), showCard(state, c)));
  const touched = [...(add?.strokes ?? []), ...(remove?.strokes ?? [])].map((s) => s.page);
  new Set(touched).forEach((i) => state.pages.has(i) && redrawPage(state.pages.get(i)));
  save(state);
}

const invert = ({ add, remove }) => ({ add: remove, remove: add });

function undo(state) {
  const action = state.undo.pop();
  if (!action) return;
  apply(state, invert(action));
  state.redo.push(action);
}

function redo(state) {
  const action = state.redo.pop();
  if (!action) return;
  apply(state, action);
  state.undo.push(action);
}

function save(state) {
  clearTimeout(state.saving);
  state.saving = setTimeout(async () => {
    const cards = state.cards.filter((c) => c.answer).map(({ el, pending, error, controller, ...c }) => c);
    try {
      await api(`/papers/${state.paperId}/ink`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ strokes: state.strokes, cards }),
      });
    } catch (e) {
      console.warn("couldn't save ink", e);
    }
  }, SAVE_AFTER);
}

// --- Ask -----------------------------------------------------------------------------------------------------------

// The pages on screen, top to bottom, each with the part of it that shows ([top, bottom] in PDF points).
function visiblePages(state) {
  const out = [];
  for (const page of state.pages.values()) {
    const r = page.el.getBoundingClientRect();
    const top = Math.max(r.top, 0);
    const bottom = Math.min(r.bottom, innerHeight);
    if (bottom - top < 24) continue;
    const toPt = (v) => ((v - r.top) / r.height) * page.height;
    out.push({ page, top: toPt(top), bottom: toPt(bottom) });
  }
  return out;
}

async function ask(state, retry) {
  const shown = visiblePages(state);
  if (!shown.length) return;
  let card = retry;
  if (!card) {
    const { page, anchor, view } = focus(state, shown);
    const w = Math.min(CARD_WIDTH, 0.45 * page.width);
    const obstacles = {
      strokes: state.strokes.filter((s) => s.page === page.i).map(bounds),
      text: page.blocks,
      cards: state.cards.filter((c) => c.page === page.i).map((c) => [c.x, c.y, c.x + c.w, c.y + CARD_HEIGHT]),
    };
    const { x, y } = placeAnswer({ width: page.width, height: page.height, anchor, view, w, h: CARD_HEIGHT, ...obstacles });
    card = { id: newId(), page: page.i, x, y, w, read: [], answer: "", collapsed: false, created: new Date().toISOString() };
    state.askedUpTo = state.strokes.length;
    record(state, { add: { cards: [card] } });
  }
  card.pending = true;
  card.error = null;
  card.controller = new AbortController();
  renderCard(card);
  try {
    const image = await capture(shown);
    const notes = shown.flatMap(({ page }) =>
      [...page.el.querySelectorAll(".note:not(.part):not(.off):not(.aside)")].map((n) => [n.data.heading, ...n.data.bullets].filter(Boolean).join(" · ")),
    );
    const res = await api(atLevel(`/papers/${state.paperId}/ink/ask`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image, media_type: "image/jpeg", pages: shown.map((v) => v.page.i), notes, card: card.id }),
      signal: card.controller.signal,
    });
    Object.assign(card, { read: res.read, answer: res.answer, pending: false });
    save(state);
  } catch (e) {
    if (e.name === "AbortError") return;
    Object.assign(card, { pending: false, error: e.message });
  }
  renderCard(card);
}

// The page to answer on (the one with the most ink on screen, else the one taking up most of the screen) and the
// writing to put the card next to: what was written since the last Ask, else all the ink on screen. A tall patch
// (more than half the screen) would push the card far away, so then it's just the last stroke.
function focus(state, shown) {
  const onScreen = (s, v) => s.page === v.page.i && bounds(s)[3] >= v.top && bounds(s)[1] <= v.bottom;
  const fresh = state.strokes.slice(state.askedUpTo);
  const pool = shown.some((v) => fresh.some((s) => onScreen(s, v))) ? fresh : state.strokes;
  const inkArea = (v) => pool.filter((s) => onScreen(s, v)).reduce((n, s) => n + area(bounds(s)) + 1, 0);
  const best = shown.reduce((a, b) => (inkArea(b) > inkArea(a) || (inkArea(b) === inkArea(a) && b.bottom - b.top > a.bottom - a.top) ? b : a));
  const strokes = pool.filter((s) => onScreen(s, best));
  let anchor = strokes.length ? union(strokes.map(bounds)) : null;
  if (anchor && anchor[3] - anchor[1] > (best.bottom - best.top) / 2) anchor = bounds(strokes.at(-1));
  return { page: best.page, anchor, view: [best.top, best.bottom] };
}

// Where a card of size w×h goes on a page: beside the anchor (right, below, left, above, then the margins), never on
// top of ink if it can help it, preferring free space over text, near the anchor and on screen. Pure, so testable.
function placeAnswer({ width, height, anchor, view, w, h, strokes = [], text = [], cards = [] }) {
  const [vt, vb] = view;
  const mid = (vt + vb) / 2;
  const [ax0, ay0, ax1, ay1] = anchor ?? [width, mid - h / 2, width, mid - h / 2];
  const candidates = anchor
    ? [[ax1 + GAP, ay0], [ax0, ay1 + GAP], [ax1 - w, ay1 + GAP], [ax0 - GAP - w, ay0], [ax0, ay0 - GAP - h], [width - w - GAP, ay0], [GAP, ay0]]
    : [[width - w - GAP, ay0], [GAP, ay0]];
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  let best;
  candidates.forEach(([x, y], order) => {
    x = clamp(x, 0, width - w);
    y = clamp(y, Math.max(0, vt), Math.max(0, Math.min(height, vb) - Math.min(h, vb - vt)));
    const r = [x, y, x + w, y + h];
    const covers = (rects) => rects.reduce((n, o) => n + overlap(r, o), 0);
    const cx = (x + w / 2) - (ax0 + ax1) / 2;
    const cy = (y + h / 2) - (ay0 + ay1) / 2;
    const score = 1000 * covers(strokes) + 3 * covers(cards) + covers(text) + 20 * Math.hypot(cx, cy) + order;
    if (!best || score < best.score) best = { x: round(x), y: round(y), score };
  });
  return best;
}

// The part of the paper on screen with the ink on it, as one JPEG (base64): the visible part of each page, stacked.
async function capture(shown) {
  const parts = shown.map(({ page, top, bottom }) => ({ page, top, bottom, height: bottom - top }));
  const totalW = Math.max(...parts.map((p) => p.page.width));
  const totalH = parts.reduce((n, p) => n + p.height, 0) + 4 * (parts.length - 1);
  const scale = Math.min(3, CAPTURE_EDGE / Math.max(totalW, totalH));
  const out = document.createElement("canvas");
  out.width = Math.round(totalW * scale);
  out.height = Math.round(totalH * scale);
  const ctx = out.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, out.width, out.height);
  let y = 0;
  for (const p of parts) {
    const src = p.page.el.querySelector("canvas");
    const k = src.height / p.page.height; // canvas pixels per point
    const dw = p.page.width * scale;
    const dh = p.height * scale;
    if (src.width) ctx.drawImage(src, 0, p.top * k, src.width, p.height * k, 0, y, dw, dh);
    const inkImage = await svgImage(p.page.svg, p.page.width, p.page.height);
    ctx.globalCompositeOperation = "multiply";
    ctx.drawImage(inkImage, 0, p.top * (inkImage.height / p.page.height), inkImage.width, p.height * (inkImage.height / p.page.height), 0, y, dw, dh);
    ctx.globalCompositeOperation = "source-over";
    y += dh;
    if (p !== parts.at(-1)) (ctx.fillStyle = "#999"), ctx.fillRect(0, y + scale, out.width, 2 * scale), (y += 4 * scale);
  }
  return out.toDataURL("image/jpeg", 0.88).split(",")[1];
}

function svgImage(svg, width, height) {
  const copy = svg.cloneNode(true);
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  copy.setAttribute("width", width * 2);
  copy.setAttribute("height", height * 2);
  copy.querySelectorAll(".highlighter").forEach((p) => p.setAttribute("fill-opacity", "0.4"));
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(copy)], { type: "image/svg+xml" }));
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => (URL.revokeObjectURL(url), resolve(img));
    img.onerror = reject;
    img.src = url;
  });
}

// --- Answer cards --------------------------------------------------------------------------------------------------

function showCard(state, card) {
  const page = state.pages.get(card.page);
  if (!page) return;
  const el = document.createElement("div");
  el.className = "ink-card";
  el.innerHTML = `
    <header><span class="ink-read"></span><button class="ink-fold" title="Fold"></button><button class="ink-close" title="Remove">×</button></header>
    <div class="ink-body"></div>`;
  card.el = el;
  page.el.append(el);
  el.querySelector(".ink-close").onclick = () => (card.controller?.abort(), record(state, { remove: { cards: [card] } }));
  el.querySelector(".ink-fold").onclick = () => ((card.collapsed = !card.collapsed), renderCard(card), save(state));
  dragCard(state, page, card);
  renderCard(card);
}

function hideCard(card) {
  card.el?.remove();
  card.el = null;
}

function renderCard(card) {
  const el = card.el;
  if (!el) return;
  const page = ink.pages.get(card.page);
  Object.assign(el.style, { left: pct(card.x, page.width), top: pct(card.y, page.height), width: pct(card.w, page.width) });
  el.classList.toggle("collapsed", card.collapsed);
  el.querySelector(".ink-fold").textContent = card.collapsed ? "▸" : "▾";
  const read = card.read.length ? `Read: ${card.read.map((r) => `“${r}”`).join(", ")}` : card.pending ? "Reading your writing…" : "";
  el.querySelector(".ink-read").textContent = read;
  el.querySelector(".ink-read").title = card.read.join("\n");
  const body = el.querySelector(".ink-body");
  if (card.pending) body.innerHTML = `<p class="muted">Thinking…</p>`;
  else if (card.error) {
    body.innerHTML = `<p class="error">Couldn't answer: ${esc(card.error)}</p><button class="btn">Retry</button>`;
    body.querySelector("button").onclick = () => ask(ink, card);
  } else renderAnswer(body, card.answer);
}

// Markdown with $…$ / $$…$$ maths: the maths is set aside so Markdown leaves it alone, then MathJax typesets it
// (typeset in foryou.js). Raw HTML in the answer is shown as text.
async function renderAnswer(el, md) {
  markedLib ??= import(MARKED).then((m) => (m.marked.use({ renderer: { html: ({ text }) => esc(text) } }), m.marked));
  const maths = [];
  const held = md.replace(/\$\$[\s\S]+?\$\$|\$[^$\n]+?\$/g, (m) => (maths.push(m), `@@MATH${maths.length - 1}@@`));
  let html;
  try {
    html = (await markedLib).parse(held);
  } catch {
    html = `<p>${esc(held).replace(/\n/g, "<br>")}</p>`;
  }
  el.innerHTML = html.replace(/@@MATH(\d+)@@/g, (_, k) => esc(maths[k]));
  typeset(el);
}

function dragCard(state, page, card) {
  const header = card.el.querySelector("header");
  header.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button")) return;
    e.preventDefault();
    capturePointer(header, e);
    const r = page.el.getBoundingClientRect();
    const k = page.width / r.width; // points per pixel
    const start = { x: e.clientX, y: e.clientY, cx: card.x, cy: card.y };
    const move = (ev) => {
      card.x = round(Math.max(0, Math.min(page.width - card.w, start.cx + (ev.clientX - start.x) * k)));
      card.y = round(Math.max(0, Math.min(page.height - 20, start.cy + (ev.clientY - start.y) * k)));
      renderCard(card);
    };
    const up = () => (header.removeEventListener("pointermove", move), save(state));
    header.addEventListener("pointermove", move);
    header.addEventListener("pointerup", up, { once: true });
  });
}

// Keeps a drag's events coming to `el` when the pointer leaves it (not possible for synthetic events).
function capturePointer(el, e) {
  try {
    el.setPointerCapture(e.pointerId);
  } catch {}
}

// --- Geometry ------------------------------------------------------------------------------------------------------

function bounds(s) {
  const pad = s.width / 2;
  const xs = s.points.map((p) => p[0]);
  const ys = s.points.map((p) => p[1]);
  return [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) + pad, Math.max(...ys) + pad];
}

const union = (rects) => [Math.min(...rects.map((r) => r[0])), Math.min(...rects.map((r) => r[1])), Math.max(...rects.map((r) => r[2])), Math.max(...rects.map((r) => r[3]))];
const overlap = (a, b) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
const pct = (v, total) => `${(v / total) * 100}%`;
const round = (v, digits = 1) => Math.round(v * 10 ** digits) / 10 ** digits;
const newId = () => Math.random().toString(36).slice(2, 10);
