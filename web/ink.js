// Write or draw on the paper and Ask about it, as in the PDF Notebook. ✎ Write (bottom-left) turns the pages into
// paper you can write on with a pen, a mouse or a finger: pens in three colours, a highlighter, text boxes, an eraser,
// a lasso to select, move or delete, and undo. Ask ✦ sends the part of the paper on screen, with your ink and text on
// it, to Claude (backend/app/ink.py), which reads it and answers in one card pinned next to it (Markdown with maths,
// typeset by MathJax). Cards can be dragged by their header, folded or removed; a follow-up Ask builds on the earlier
// cards.
//
// Ink lives on PDF pages only, in PDF points, so it stays put at any width. Strokes, text boxes and cards are saved per
// paper (GET/PUT /papers/:id/ink) shortly after each change. While ✎ Write is off the ink layer lets every click
// through, so the notes, pins and highlight-to-ask work as before.

const FREEHAND = "https://cdn.jsdelivr.net/npm/perfect-freehand@1.2.2/dist/esm/index.mjs";
const MARKED = "https://cdn.jsdelivr.net/npm/marked@15.0.12/lib/marked.esm.js";
const PENS = ["#1f2f7a", "#b0181c", "#1d7a3a"]; // navy ink, red, green
const HIGHLIGHTER = "#f2d50f";
const WIDTH = { pen: 1.6, highlighter: 11 }; // PDF points
const ERASER = 5; // PDF points around the pointer
const TEXT_SIZE = 13; // PDF points (css: .ink-text)
const TEXT_WIDTH = 220; // PDF points: the widest a text box grows before it wraps
const CARD_WIDTH = 240; // PDF points, at most 45% of the page
const CARD_HEIGHT = 150; // estimated, for placement; the card grows downwards from there
const GAP = 8;
const SAVE_AFTER = 600; // ms after the last change
const CAPTURE_EDGE = 1568; // longest side of the image sent to Claude, in pixels
const KINDS = ["strokes", "texts", "cards"]; // what an undoable action can add or remove
const SVG = "http://www.w3.org/2000/svg";

let getStroke; // perfect-freehand, once loaded; plain lines until then (or if it can't load)
let markedLib;
let ink; // the open paper's ink: {paperId, pages, strokes, texts, cards, ...}

// Sets up writing on the reader's PDF pages. Called by renderReader once the pages are in `container`.
async function setupInk(container, paperId, p) {
  const pageEls = [...container.querySelectorAll(".pdf-page")];
  if (!pageEls.length) return; // papers we only have as HTML
  import(FREEHAND).then((m) => ((getStroke = m.getStroke), ink?.pages.forEach(redrawPage))).catch(() => {});
  const pages = new Map();
  for (const el of pageEls) {
    const i = +el.dataset.page;
    const { width, height } = p.pages[i];
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("class", "ink");
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("preserveAspectRatio", "none");
    el.append(svg);
    const page = { el, svg, i, width, height, blocks: p.pages[i].blocks.map((b) => b.bbox).filter(Boolean) };
    pages.set(i, page);
    wirePointer(page);
  }
  ink = { paperId, container, pages, strokes: [], texts: [], cards: [], undo: [], redo: [], tool: "pen", color: PENS[0], asked: new Set() };
  const state = ink;
  container.classList.add("tool-pen");
  container.after(toolbar(state));
  try {
    const saved = await api(`/papers/${paperId}/ink`);
    if (ink !== state) return; // left the paper meanwhile
    for (const kind of KINDS) state[kind] = [...saved[kind], ...state[kind]]; // keep anything made while it loaded
    [...saved.strokes, ...saved.texts].forEach((m) => state.asked.add(m.id));
    pages.forEach(redrawPage);
    saved.texts.forEach((t) => showText(state, t));
    saved.cards.forEach((c) => showCard(state, c));
  } catch (e) {
    console.warn("couldn't load ink", e);
  }
}

// Turns ✎ Write on for the open paper (the library's ✎ Whiteboard opens papers this way).
function startWriting() {
  ink?.setWriting(true);
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
      <button data-tool="pen" title="Pen" aria-pressed="true">
        <svg viewBox="0 0 16 16" width="15" height="15"><path d="M11.5 1.8 14.2 4.5 5.4 13.3 2 14 2.7 10.6Z M9.8 3.5 12.5 6.2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
      </button>
      <button data-tool="highlighter" title="Highlighter" aria-pressed="false"><i class="hl" style="background:${HIGHLIGHTER}"></i></button>
      <button data-tool="text" title="Text box: click the page to type" aria-pressed="false">T</button>
      <button data-tool="lasso" title="Lasso: circle ink, text or cards to move or delete them" aria-pressed="false">
        <svg viewBox="0 0 16 16" width="15" height="15"><ellipse cx="8" cy="7" rx="6.5" ry="4.8" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="2.5 2"/><path d="M5 11.5 q-1 2.5 1.5 3.5" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
      </button>
      <button data-tool="eraser" title="Eraser" aria-pressed="false">⌫</button>
      <span class="ink-colors" role="group" aria-label="Colour for the pen and text">
        ${PENS.map((c, k) => `<button class="ink-color" data-color="${c}" title="Colour" aria-pressed="${k === 0}"><i style="background:${c}"></i></button>`).join("")}
      </span>
      <button class="ink-undo" title="Undo (⌘Z)">↶</button>
      <button class="ink-redo" title="Redo (⇧⌘Z)">↷</button>
    </span>
    <button class="ink-ask" title="Ask about what you wrote on screen">Ask ✦</button>`;
  const write = bar.querySelector(".ink-write");
  state.setWriting = (on) => {
    write.setAttribute("aria-pressed", on);
    bar.querySelector(".ink-tools").hidden = !on;
    state.container.classList.toggle("writing", on);
    if (!on) (document.activeElement?.blur(), select(state, null));
  };
  write.onclick = () => state.setWriting(write.getAttribute("aria-pressed") !== "true");
  const useTool = (tool) => {
    state.container.classList.remove(`tool-${state.tool}`);
    state.tool = tool;
    state.container.classList.add(`tool-${tool}`);
    bar.querySelectorAll("[data-tool]").forEach((o) => o.setAttribute("aria-pressed", o.dataset.tool === tool));
    if (tool !== "lasso") select(state, null);
  };
  bar.querySelectorAll("[data-tool]").forEach((b) => b.addEventListener("click", () => useTool(b.dataset.tool)));
  // A colour is for the pen and for text: picking one keeps the pen or text tool (and recolours a text box being
  // typed in), and switches any other tool to the pen.
  bar.querySelectorAll(".ink-color").forEach((b) =>
    b.addEventListener("click", () => {
      state.color = b.dataset.color;
      bar.querySelectorAll(".ink-color").forEach((o) => o.setAttribute("aria-pressed", o === b));
      const typing = document.activeElement?.closest?.(".ink-text");
      if (typing) typing.style.color = state.color;
      else if (state.tool !== "text") useTool("pen");
    }),
  );
  bar.addEventListener("mousedown", (e) => e.preventDefault()); // clicking the toolbar leaves a text box being typed in focused
  bar.querySelector(".ink-undo").onclick = () => undo(state);
  bar.querySelector(".ink-redo").onclick = () => redo(state);
  bar.querySelector(".ink-ask").onclick = () => ask(state);
  return bar;
}

document.addEventListener("keydown", (e) => {
  if (!ink?.container.isConnected || e.target.closest?.("input, textarea, [contenteditable=true]")) return;
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "z") {
    e.preventDefault();
    e.shiftKey ? redo(ink) : undo(ink);
  } else if (ink.selection && (e.key === "Delete" || e.key === "Backspace")) {
    e.preventDefault();
    record(ink, { remove: ink.selection.items });
  } else if (ink.selection && e.key === "Escape") {
    select(ink, null);
  }
});

// --- Drawing, erasing, lasso and text ------------------------------------------------------------------------------

// Pen, mouse or finger draw while ✎ Write is on. Once a pen has touched the page, fingers scroll instead (palm
// rejection, for a tablet with a stylus).
function wirePointer(page) {
  const { svg } = page;
  let live = null; // {stroke, path} being drawn, {erased} while erasing, {lasso, path} while lassoing
  let scrolling = null;
  let penSeen = false;
  let typeAt = null; // where a text box is to open

  const toPage = (e) => {
    const r = svg.getBoundingClientRect();
    return [round(((e.clientX - r.left) / r.width) * page.width), round(((e.clientY - r.top) / r.height) * page.height)];
  };

  svg.addEventListener("pointerdown", (e) => {
    if (e.button > 0) return;
    if (e.pointerType === "pen") penSeen = true;
    if (penSeen && e.pointerType === "touch") return (scrolling = { id: e.pointerId, y: e.clientY });
    e.preventDefault();
    const state = ink;
    const editing = document.activeElement?.closest?.(".ink-text");
    if (editing) return editing.blur(); // a click off a text box being typed in just finishes it
    if (state.tool === "text") return (typeAt = toPage(e)); // the box opens on click (below)
    capturePointer(svg, e);
    if (state.tool === "eraser") {
      live = { id: e.pointerId, erased: { strokes: [], texts: [] } };
      return erase(state, page, toPage(e), live.erased);
    }
    if (state.tool === "lasso") {
      select(state, null);
      const path = document.createElementNS(SVG, "path");
      path.setAttribute("class", "lasso");
      svg.append(path);
      live = { id: e.pointerId, lasso: [toPage(e)], path };
      return;
    }
    const color = state.tool === "highlighter" ? HIGHLIGHTER : state.color;
    const stroke = { id: newId(), page: page.i, tool: state.tool, color, width: WIDTH[state.tool], points: [] };
    const path = document.createElementNS(SVG, "path");
    svg.append(path);
    live = { id: e.pointerId, stroke, path };
    addPoint(live, e, toPage);
  });

  svg.addEventListener("pointermove", (e) => {
    if (scrolling?.id === e.pointerId) return (scrollBy(0, scrolling.y - e.clientY), (scrolling.y = e.clientY));
    if (live?.id !== e.pointerId) return;
    if (live.erased) return erase(ink, page, toPage(e), live.erased);
    if (live.lasso) {
      live.lasso.push(toPage(e));
      return live.path.setAttribute("d", `M${live.lasso.map(([x, y]) => `${x} ${y}`).join(" L")} Z`);
    }
    const coalesced = e.getCoalescedEvents?.() ?? [];
    for (const ev of coalesced.length ? coalesced : [e]) addPoint(live, ev, toPage);
  });

  const end = (e) => {
    if (scrolling?.id === e.pointerId) scrolling = null;
    if (live?.id !== e.pointerId) return;
    const done = live;
    live = null;
    if (done.erased) {
      if (done.erased.strokes.length || done.erased.texts.length) record(ink, { remove: done.erased }, true);
      return;
    }
    done.path.remove();
    if (done.lasso) return select(ink, lassoed(ink, page, done.lasso));
    if (done.stroke.points.length) record(ink, { add: { strokes: [done.stroke] } });
  };
  svg.addEventListener("pointerup", end);
  svg.addEventListener("pointercancel", end);

  // A text box opens and takes the keyboard on click rather than on pointerdown: some browsers (Safari, Firefox) move
  // the focus as the button goes down, which would close a box opened then, and iPad Safari only shows the keyboard
  // for focus given in a click.
  svg.addEventListener("click", () => {
    const at = typeAt;
    typeAt = null;
    if (at && ink.tool === "text") editText(ink, page, null, at);
  });
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
  path.dataset.id = s.id;
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
    const path = document.createElementNS(SVG, "path");
    drawStroke(path, s);
    page.svg.append(path);
  }
}

// Removes (into `erased`) every stroke passing within ERASER of `at`, and any text box under it.
function erase(state, page, at, erased) {
  const strokes = state.strokes.filter((s) => s.page === page.i && nearStroke(s, at, ERASER + s.width / 2));
  const texts = state.texts.filter((t) => t.page === page.i && inside(textRect(t), at));
  if (!strokes.length && !texts.length) return;
  state.strokes = state.strokes.filter((s) => !strokes.includes(s));
  state.texts = state.texts.filter((t) => !texts.includes(t));
  texts.forEach(hideEl);
  erased.strokes.push(...strokes);
  erased.texts.push(...texts);
  if (strokes.length) redrawPage(page);
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

// What a lasso loop takes in: strokes with most of their points inside it, and text boxes and cards whose middle is.
function lassoed(state, page, loop) {
  if (loop.length < 3) return null;
  const middle = ([x0, y0, x1, y1]) => [(x0 + x1) / 2, (y0 + y1) / 2];
  const items = {
    strokes: state.strokes.filter((s) => s.page === page.i && s.points.filter((p) => inPolygon(p, loop)).length > s.points.length / 2),
    texts: state.texts.filter((t) => t.page === page.i && inPolygon(middle(textRect(t)), loop)),
    cards: state.cards.filter((c) => c.page === page.i && !c.pending && inPolygon(middle(cardRect(c)), loop)),
  };
  return KINDS.some((k) => items[k].length) ? { page, items } : null;
}

// --- Text boxes ----------------------------------------------------------------------------------------------------

function showText(state, t) {
  const page = state.pages.get(t.page);
  if (!page) return;
  const el = document.createElement("div");
  el.className = "ink-text";
  el.textContent = t.text;
  t.el = el;
  page.el.append(el);
  placeText(t, page);
  el.addEventListener("click", () => state.tool === "text" && !el.isContentEditable && editText(state, page, t));
}

function placeText(t, page) {
  Object.assign(t.el.style, { left: pct(t.x, page.width), top: pct(t.y, page.height), maxWidth: pct(t.w, page.width), color: t.color });
}

// Types into text box `t`, or into a new one at `at`. Finishing (a click elsewhere, or Escape) makes it one undoable
// change: adding the box, changing its text, or removing it if it was emptied.
function editText(state, page, t, at) {
  let el = t?.el;
  if (!t) {
    const [x, y] = at;
    const draft = { x, y: y - TEXT_SIZE * 0.7, w: Math.max(60, Math.min(TEXT_WIDTH, page.width - x - GAP)), color: state.color };
    el = document.createElement("div");
    el.className = "ink-text";
    page.el.append(el);
    placeText({ ...draft, el }, page);
    t = null;
    el.draft = draft;
  }
  el.contentEditable = "true";
  el.focus();
  getSelection().selectAllChildren(el);
  getSelection().collapseToEnd();
  // (Not el.onkeydown = (e) => e.key === "Escape" && …: a handler property returning false cancels every other key.)
  const onKey = (e) => {
    if (e.key === "Escape" && !e.isComposing) (e.preventDefault(), el.blur());
  };
  el.addEventListener("keydown", onKey);
  el.addEventListener(
    "blur",
    () => {
      el.contentEditable = "false";
      el.removeEventListener("keydown", onKey);
      const text = el.innerText.replace(/\n+$/, "").trim();
      const color = el.style.color ? rgbToHex(el.style.color) : state.color; // the palette may have recoloured it
      if (!t) {
        el.remove();
        if (text) record(state, { add: { texts: [{ id: newId(), page: page.i, ...el.draft, color, text }] } });
      } else if (!text) {
        record(state, { remove: { texts: [t] } });
      } else if (text !== t.text || color !== t.color) {
        record(state, { remove: { texts: [t] }, add: { texts: [{ ...plain(t), text, color }] } });
      } else {
        el.textContent = t.text;
      }
    },
    { once: true },
  );
}

// --- Selection (lasso) ---------------------------------------------------------------------------------------------

// Shows `sel` ({page, items}, or null for none) as a dashed box: drag it to move what's in it, × to delete it.
function select(state, sel) {
  state.selection?.box.remove();
  state.selection = sel;
  if (!sel) return;
  const { page, items } = sel;
  const [x0, y0, x1, y1] = union([...items.strokes.map(bounds), ...items.texts.map(textRect), ...items.cards.map(cardRect)]);
  const box = document.createElement("div");
  box.className = "ink-selection";
  Object.assign(box.style, { left: pct(x0 - 4, page.width), top: pct(y0 - 4, page.height), width: pct(x1 - x0 + 8, page.width), height: pct(y1 - y0 + 8, page.height) });
  box.innerHTML = `<button title="Delete (⌫)">×</button>`;
  box.querySelector("button").onclick = () => record(state, { remove: items });
  page.el.append(box);
  sel.box = box;
  box.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button")) return;
    e.preventDefault();
    capturePointer(box, e);
    const k = page.width / page.el.getBoundingClientRect().width; // points per pixel
    const start = [e.clientX, e.clientY];
    let d = [0, 0];
    const paths = items.strokes.map((s) => page.svg.querySelector(`[data-id="${s.id}"]`)).filter(Boolean);
    const els = [box, ...items.texts.map((t) => t.el), ...items.cards.map((c) => c.el)].filter(Boolean);
    const move = (ev) => {
      d = [round((ev.clientX - start[0]) * k), round((ev.clientY - start[1]) * k)];
      paths.forEach((p) => p.setAttribute("transform", `translate(${d[0]} ${d[1]})`));
      els.forEach((el) => (el.style.transform = `translate(${d[0] / k}px, ${d[1] / k}px)`));
    };
    const up = () => {
      box.removeEventListener("pointermove", move);
      els.forEach((el) => (el.style.transform = ""));
      if (!d[0] && !d[1]) return;
      const moved = moveItems(items, d);
      record(state, { remove: items, add: moved });
      select(state, { page, items: moved });
    };
    box.addEventListener("pointermove", move);
    box.addEventListener("pointerup", up, { once: true });
  });
}

function moveItems(items, [dx, dy]) {
  return {
    strokes: items.strokes.map((s) => ({ ...s, points: s.points.map(([x, y, p]) => [round(x + dx), round(y + dy), p]) })),
    texts: items.texts.map((t) => ({ ...plain(t), x: round(t.x + dx), y: round(t.y + dy) })),
    cards: items.cards.map((c) => ({ ...plain(c), x: round(c.x + dx), y: round(c.y + dy) })),
  };
}

// --- Undo and saving -----------------------------------------------------------------------------------------------

// An action adds and/or removes strokes, text boxes and cards ({add: {strokes, texts, cards}, remove: {...}}); a move
// or an edit removes the old version and adds the new one. `record` applies a new one; `done` when it already happened
// (the eraser removes as it goes).
function record(state, action, done = false) {
  if (!done) apply(state, action);
  else save(state);
  state.undo.push(action);
  state.redo = [];
}

function apply(state, { add = {}, remove = {} }) {
  select(state, null);
  const ids = (list) => new Set((list ?? []).map((x) => x.id));
  for (const kind of KINDS) {
    const gone = ids(remove[kind]);
    if (!gone.size) continue;
    state[kind].filter((x) => gone.has(x.id)).forEach(hideEl);
    state[kind] = state[kind].filter((x) => !gone.has(x.id));
  }
  for (const kind of KINDS) {
    const have = ids(state[kind]);
    for (const x of add[kind] ?? []) {
      if (have.has(x.id)) continue;
      state[kind].push(x);
      if (kind === "texts") showText(state, x);
      if (kind === "cards") showCard(state, x);
    }
  }
  const touched = new Set([...(add.strokes ?? []), ...(remove.strokes ?? [])].map((s) => s.page));
  touched.forEach((i) => state.pages.has(i) && redrawPage(state.pages.get(i)));
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

// What's saved of a stroke, text box or card: everything but its element and the state of an Ask in flight.
const plain = ({ el, pending, error, controller, ...x }) => x;

function save(state) {
  clearTimeout(state.saving);
  state.saving = setTimeout(async () => {
    const body = { strokes: state.strokes, texts: state.texts.map(plain), cards: state.cards.filter((c) => c.answer).map(plain) };
    try {
      await api(`/papers/${state.paperId}/ink`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
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
  document.activeElement?.closest?.(".ink-text")?.blur(); // a text box being typed in is part of the question
  const shown = visiblePages(state);
  if (!shown.length) return;
  let card = retry;
  if (!card) {
    const { page, anchor, view } = focus(state, shown);
    const w = Math.min(CARD_WIDTH, 0.45 * page.width);
    const obstacles = {
      marks: marksOn(state, page.i).map(markRect),
      text: page.blocks,
      cards: state.cards.filter((c) => c.page === page.i).map(cardRect),
    };
    const { x, y } = placeAnswer({ width: page.width, height: page.height, anchor, view, w, h: CARD_HEIGHT, ...obstacles });
    card = { id: newId(), page: page.i, x, y, w, read: [], answer: "", collapsed: false, created: new Date().toISOString() };
    [...state.strokes, ...state.texts].forEach((m) => state.asked.add(m.id));
    record(state, { add: { cards: [card] } });
  }
  card.pending = true;
  card.error = null;
  card.controller = new AbortController();
  renderCard(card);
  try {
    const image = await capture(state, shown);
    const notes = shown.flatMap(({ page }) =>
      [...page.el.querySelectorAll(".note:not(.part):not(.off):not(.aside)")].map((n) => [n.data.heading, ...n.data.bullets].filter(Boolean).join(" · ")),
    );
    const typed = shown.flatMap((v) => state.texts.filter((t) => onScreen(t, v)).map((t) => `[p. ${t.page + 1}] ${t.text}`));
    const res = await api(atLevel(`/papers/${state.paperId}/ink/ask`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image, media_type: "image/jpeg", pages: shown.map((v) => v.page.i), notes, typed, card: card.id }),
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

const marksOn = (state, i) => [...state.strokes, ...state.texts].filter((m) => m.page === i);
const markRect = (m) => (m.points ? bounds(m) : textRect(m));
const onScreen = (m, v) => m.page === v.page.i && markRect(m)[3] >= v.top && markRect(m)[1] <= v.bottom;

// The page to answer on (the one with the most ink and text on screen, else the one taking up most of the screen) and
// what to put the card next to: what was written since the last Ask, else everything on screen. A tall patch (more
// than half the screen) would push the card far away, so then it's just the last thing written.
function focus(state, shown) {
  const all = [...state.strokes, ...state.texts];
  const fresh = all.filter((m) => !state.asked.has(m.id));
  const pool = shown.some((v) => fresh.some((m) => onScreen(m, v))) ? fresh : all;
  const inkArea = (v) => pool.filter((m) => onScreen(m, v)).reduce((n, m) => n + area(markRect(m)) + 1, 0);
  const best = shown.reduce((a, b) => (inkArea(b) > inkArea(a) || (inkArea(b) === inkArea(a) && b.bottom - b.top > a.bottom - a.top) ? b : a));
  const marks = pool.filter((m) => onScreen(m, best));
  let anchor = marks.length ? union(marks.map(markRect)) : null;
  if (anchor && anchor[3] - anchor[1] > (best.bottom - best.top) / 2) anchor = markRect(marks.at(-1));
  return { page: best.page, anchor, view: [best.top, best.bottom] };
}

// Where a card of size w×h goes on a page: beside the anchor (right, below, left, above, then the margins), never on
// top of ink or text boxes if it can help it, preferring free space over the paper's text, near the anchor and on
// screen. Pure, so testable.
function placeAnswer({ width, height, anchor, view, w, h, marks = [], text = [], cards = [] }) {
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
    const score = 1000 * covers(marks) + 3 * covers(cards) + covers(text) + 20 * Math.hypot(cx, cy) + order;
    if (!best || score < best.score) best = { x: round(x), y: round(y), score };
  });
  return best;
}

// The part of the paper on screen with the ink and text boxes on it, as one JPEG (base64): the visible part of each
// page, stacked.
async function capture(state, shown) {
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
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, y, dw, dh);
    ctx.clip();
    for (const t of state.texts.filter((t) => t.page === p.page.i)) drawText(ctx, t, scale, y - p.top * scale);
    ctx.restore();
    y += dh;
    if (p !== parts.at(-1)) (ctx.fillStyle = "#999"), ctx.fillRect(0, y + scale, out.width, 2 * scale), (y += 4 * scale);
  }
  return out.toDataURL("image/jpeg", 0.88).split(",")[1];
}

// A text box, wrapped as on the page, onto the capture (`dy`: where the page's top is on the canvas).
function drawText(ctx, t, scale, dy) {
  const size = TEXT_SIZE * scale;
  ctx.font = `${size}px ${getComputedStyle(document.documentElement).getPropertyValue("--hand")}`;
  ctx.fillStyle = t.color;
  ctx.textBaseline = "top";
  const maxW = t.w * scale;
  let line = 0;
  for (const para of t.text.split("\n")) {
    let cur = "";
    for (const word of para.split(" ")) {
      const next = cur ? `${cur} ${word}` : word;
      if (cur && ctx.measureText(next).width > maxW) ctx.fillText(cur, t.x * scale, dy + t.y * scale + line++ * size * 1.25), (cur = word);
      else cur = next;
    }
    ctx.fillText(cur, t.x * scale, dy + t.y * scale + line++ * size * 1.25);
  }
}

function svgImage(svg, width, height) {
  const copy = svg.cloneNode(true);
  copy.setAttribute("xmlns", SVG);
  copy.setAttribute("width", width * 2);
  copy.setAttribute("height", height * 2);
  copy.querySelectorAll(".highlighter").forEach((p) => p.setAttribute("fill-opacity", "0.4"));
  copy.querySelectorAll(".lasso").forEach((p) => p.remove());
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

function hideEl(x) {
  x.el?.remove();
  x.el = null;
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

// A text box's rect in PDF points, measured on the page (its height depends on how its text wraps).
function textRect(t) {
  const page = ink.pages.get(t.page);
  if (!t.el || !page?.el.clientWidth) return [t.x, t.y, t.x + t.w, t.y + TEXT_SIZE * 1.25];
  const k = page.width / page.el.clientWidth;
  return [t.x, t.y, t.x + t.el.offsetWidth * k, t.y + t.el.offsetHeight * k];
}

function cardRect(c) {
  const page = ink.pages.get(c.page);
  const h = c.el && page?.el.clientWidth ? c.el.offsetHeight * (page.width / page.el.clientWidth) : CARD_HEIGHT;
  return [c.x, c.y, c.x + c.w, c.y + h];
}

function inPolygon([x, y], poly) {
  let isIn = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) isIn = !isIn;
  }
  return isIn;
}

// "rgb(31, 47, 122)" (how the browser reports a colour set as "#1f2f7a") → "#1f2f7a".
function rgbToHex(c) {
  const m = c.match(/\d+/g);
  return c.startsWith("#") || !m ? c : `#${m.slice(0, 3).map((v) => (+v).toString(16).padStart(2, "0")).join("")}`;
}

const inside = ([x0, y0, x1, y1], [x, y]) => x >= x0 && x <= x1 && y >= y0 && y <= y1;
const union = (rects) => [Math.min(...rects.map((r) => r[0])), Math.min(...rects.map((r) => r[1])), Math.max(...rects.map((r) => r[2])), Math.max(...rects.map((r) => r[3]))];
const overlap = (a, b) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
const pct = (v, total) => `${(v / total) * 100}%`;
const round = (v, digits = 1) => Math.round(v * 10 ** digits) / 10 ** digits;
const newId = () => Math.random().toString(36).slice(2, 10);
