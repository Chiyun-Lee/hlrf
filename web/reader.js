// The reader: the paper's pages with a "doodle note" laid over each paragraph, in the spirit of Claire Lamman's
// annotated papers. Each note blurs the original underneath and carries a switch (top-right) to flip back to it.
//
// PDF papers render with pdf.js and notes sit on each paragraph's box from the PDF. Papers we only have as HTML
// show their paragraphs as text, with the same notes on top. Notes are fetched page by page as you scroll.

const PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38";
const NOTE_PAD = 4; // PDF points of breathing room around a paragraph's box
const MAX_FONT = 0.024; // largest note font, as a fraction of the page width
const MIN_FONT = { summary: 12, figure: 14, aside: 12 }; // px; below this a note grows past its box instead
const MAX_GAP = 0.03; // vertical gap (fraction of page height) that splits a note's text into separate boxes
const NOTES_AHEAD = "300% 0px"; // ask for a page's notes three screens before it scrolls into view (Claude is slow)...
const DRAW_AHEAD = "100% 0px"; // ...and draw it one screen before
const NOTES_AT_ONCE = 3; // pages whose notes are asked for at a time, so a fast scroll can't start a Claude call per page

let pdfjsLib;
let pdfjs; // pdf.js and its worker, loading or loaded
let prefetched; // {url, doc}: the PDF preloadReader started, for the reader to pick up

// pdf.js and its worker (1.5 MB together, mostly the worker) load side by side, once: one worker serves every PDF. A
// cross-origin script can't be a worker itself, so a one-line module imports it (as pdf.js does). Waiting for its
// first message ("ready") means a worker that fails to load fails the reader instead of leaving it waiting.
function loadPdfjs() {
  pdfjs ??= Promise.all([
    import(`${PDFJS}/pdf.min.mjs`),
    new Promise((resolve, reject) => {
      const src = URL.createObjectURL(new Blob([`import "${PDFJS}/pdf.worker.min.mjs";`], { type: "text/javascript" }));
      const worker = new Worker(src, { type: "module" });
      worker.addEventListener("message", () => resolve(worker), { once: true });
      worker.addEventListener("error", reject, { once: true });
    }),
  ]).then(([lib, worker]) => {
    lib.GlobalWorkerOptions.workerPort = worker;
    return (pdfjsLib = lib);
  });
  return pdfjs;
}

// Opens a PDF, or picks up the one preloadReader started.
function loadPdf(url) {
  const doc = prefetched?.url === url ? prefetched.doc : loadPdfjs().then((lib) => lib.getDocument(url).promise);
  prefetched = null;
  return doc;
}

// Starts loading what the reader needs: pdf.js, its worker, the handwriting font and, given a paper, its PDF. A paper
// calls this as it opens, so they load alongside its details; the library calls it when the browser is idle.
function preloadReader(paperId) {
  document.fonts.load('1em "xkcd"').catch(() => {});
  loadPdfjs().catch(() => {}); // the reader reports it if this fails
  if (paperId == null) return;
  const url = `/papers/${paperId}/pdf`;
  prefetched = { url, doc: loadPdfjs().then((lib) => lib.getDocument(url).promise) };
  prefetched.doc.catch(() => {}); // papers we only have as HTML have no PDF
}

// Renders paper `p` (from GET /papers/:id) into `container`.
async function renderReader(container, paperId, p) {
  const pins = api(`/papers/${paperId}/pins`).catch(() => null); // extras: the paper reads fine without them
  const pdf = p.has_pdf ? await loadPdf(`/papers/${paperId}/pdf`) : null;
  const pages = p.pages.map((page, i) => pageView(paperId, page, i, pdf));
  container.replaceChildren(...pages);

  // Methods pins on figures and tables (pins.js). Their boxes are in PDF points, so they need the PDF page.
  pins.then((found) =>
    found?.targets.forEach((t) => pages[t.page]?.classList.contains("pdf-page") && addPins(pages[t.page], p.pages[t.page], t, found.reviewed)),
  );

  // Draw pages shortly before they scroll into view; their notes are asked for earlier (nearbyNotes).
  const seen = new IntersectionObserver(
    (entries) => entries.filter((e) => e.isIntersecting).forEach((e) => (seen.unobserve(e.target), e.target.draw())),
    { rootMargin: DRAW_AHEAD },
  );
  pages.forEach((el) => (seen.observe(el), nearbyNotes.observe(el)));

  // Highlight text (in a note or the original) to ask about it; see chat.js.
  enableAsk(container, paperId);

  // Re-fit note text once the handwriting font arrives and whenever the page width changes.
  const refit = () => {
    container.querySelectorAll(".pdf-page").forEach((el) => el.style.setProperty("--scale-factor", el.clientWidth / el.pageWidth));
    container.querySelectorAll(".note:not(.part)").forEach(fit);
  };
  document.fonts.load('1em "xkcd"').then(refit);
  let pending;
  new ResizeObserver(() => {
    cancelAnimationFrame(pending);
    pending = requestAnimationFrame(refit);
  }).observe(container);
}

function pageView(paperId, page, i, pdf) {
  const el = document.createElement("section");
  const onPdf = pdf && page.width;
  el.className = onPdf ? "page pdf-page" : "page text-page";
  el.dataset.page = i;
  el.paperId = paperId;
  if (onPdf) {
    el.pageWidth = page.width;
    el.style.aspectRatio = `${page.width} / ${page.height}`;
    // The canvas shows the page; the invisible text layer on top makes its text selectable.
    el.innerHTML = `<canvas></canvas><div class="textLayer"></div>`;
  } else {
    el.innerHTML = page.blocks.map((b) => `<div class="block"><p>${esc(b.text)}</p></div>`).join("");
  }
  el.insertAdjacentHTML("beforeend", `<div class="page-status"></div>`);

  el.draw = () => onPdf && drawPdfPage(el, pdf, i);
  el.loadNotes = async () => {
    const status = el.querySelector(".page-status");
    status.textContent = "writing notes…";
    try {
      const summary = await api(`/papers/${paperId}/pages/${i}/summary`);
      summary.notes.forEach((n, k) => addNote(el, page, n, k, onPdf));
      status.textContent = "";
    } catch (e) {
      status.innerHTML = `notes failed <button>retry</button>`;
      status.querySelector("button").onclick = () => el.loadNotes();
    }
  };
  return el;
}

// Claude takes seconds to write a page's notes, so they're asked for a few screens ahead: at most NOTES_AT_ONCE pages
// at a time, nearest the screen first, and only pages still near it by then (a fast scroll passes most by).
const waiting = new Set(); // pages near the screen whose notes haven't been asked for
let asking = 0;
const nearbyNotes = new IntersectionObserver(
  (entries) => {
    entries.forEach((e) => (e.isIntersecting ? waiting.add(e.target) : waiting.delete(e.target)));
    askForNotes();
  },
  { rootMargin: NOTES_AHEAD },
);

function askForNotes() {
  const away = (el) => {
    const r = el.getBoundingClientRect();
    return Math.max(0, r.top - innerHeight, -r.bottom); // 0 while on screen
  };
  waiting.forEach((el) => el.isConnected || waiting.delete(el)); // pages of a paper since closed
  while (asking < NOTES_AT_ONCE && waiting.size) {
    const el = [...waiting].reduce((a, b) => (away(b) < away(a) ? b : a));
    waiting.delete(el);
    nearbyNotes.unobserve(el);
    asking++;
    el.loadNotes().finally(() => (asking--, askForNotes()));
  }
}

async function drawPdfPage(el, pdf, i) {
  const page = await pdf.getPage(i + 1);
  const cssScale = el.clientWidth / page.getViewport({ scale: 1 }).width;
  const viewport = page.getViewport({ scale: cssScale * (window.devicePixelRatio || 1) });
  const canvas = el.querySelector("canvas");
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  el.style.setProperty("--scale-factor", cssScale);
  const textLayer = new pdfjsLib.TextLayer({
    textContentSource: page.streamTextContent(),
    container: el.querySelector(".textLayer"),
    viewport: page.getViewport({ scale: cssScale }),
  });
  await Promise.all([page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise, textLayer.render()]);
}

function addNote(el, page, n, index, onPdf) {
  const note = document.createElement("div");
  note.className = `note ${n.kind}`;
  note.innerHTML = `
    <button class="switch" title="Show original" aria-pressed="true"></button>
    ${n.kind === "aside" ? "" : `<button class="edit" title="Edit note">✎</button>`}
    <div class="note-body"></div>`;
  note.data = n;
  note.index = index;
  note.parts = [];
  fillNote(note, n);
  note.querySelector(".switch").onclick = () => setNote(note, note.classList.contains("off"));
  note.querySelector(".edit")?.addEventListener("click", () => editNote(note));

  // A note's text can sit in several places (both columns, either side of a figure). The largest place carries the
  // note; the others get a matching blurred patch that switches with it.
  const [main, ...rest] = onPdf ? pdfBoxes(page, n.blocks).sort((a, b) => area(b) - area(a)) : textGroups(el, n.blocks);
  for (const box of rest) {
    const part = document.createElement("div");
    part.className = `note ${n.kind} part`;
    part.main = note;
    onPdf ? (place(part, box, page), el.append(part)) : box.append(part);
    note.parts.push(part);
  }
  onPdf ? (place(note, main, page), el.append(note)) : main.append(note);
  fit(note);
}

// (Re)write a note's text, e.g. after the tutor in chat.js adds to it.
function fillNote(note, n) {
  const bullets = n.bullets.length ? `<ul>${n.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : "";
  note.querySelector(".note-body").innerHTML = `${n.heading ? `<div class="note-heading">${esc(n.heading)}</div>` : ""}${bullets}`;
  note.data = n;
  if (note.isConnected) fit(note);
}

// Edit a note in place: the first click makes its title and bullets editable (Enter adds a bullet, Escape cancels),
// the second saves.
async function editNote(note) {
  const body = note.querySelector(".note-body");
  const button = note.querySelector(".edit");
  if (!note.classList.contains("editing")) {
    setNote(note, true);
    if (!body.querySelector(".note-heading")) body.insertAdjacentHTML("afterbegin", `<div class="note-heading"></div>`);
    if (!body.querySelector("li")) body.insertAdjacentHTML("beforeend", `<ul><li></li></ul>`);
    note.classList.add("editing");
    body.contentEditable = "true";
    body.onkeydown = (e) => e.key === "Escape" && (stopEditing(note), fillNote(note, note.data));
    body.focus();
    Object.assign(button, { textContent: "✓", title: "Save note" });
    return;
  }
  const heading = body.querySelector(".note-heading")?.textContent.trim() || null;
  const bullets = [...body.querySelectorAll("li")].map((li) => li.textContent.trim()).filter(Boolean);
  const updated = { ...note.data, heading, bullets };
  stopEditing(note);
  const page = note.closest(".page");
  try {
    fillNote(note, await api(`/papers/${page.paperId}/pages/${page.dataset.page}/notes/${note.index}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updated),
    }));
  } catch (e) {
    fillNote(note, note.data);
    alert(`Couldn't save the note: ${e.message}`);
  }
}

function stopEditing(note) {
  const body = note.querySelector(".note-body");
  body.contentEditable = "false";
  note.classList.remove("editing");
  Object.assign(note.querySelector(".edit"), { textContent: "✎", title: "Edit note" });
}

// Boxes around a note's blocks on a PDF page: blocks stack into one box while they're in the same column, overlap
// horizontally and follow without a big vertical gap (a figure, usually, which should stay visible).
function pdfBoxes(page, blocks) {
  const cols = twoColumns(page);
  const boxes = [];
  let cur;
  for (const i of [...blocks].sort((a, b) => a - b)) {
    const b = page.blocks[i];
    const [x0, y0, x1, y1] = b.bbox;
    const col = cols ? columnOf(b, page) : "all";
    const stacks = cur && cur.col === col && x0 < cur.r[2] && x1 > cur.r[0] && y0 - cur.r[3] < MAX_GAP * page.height;
    if (stacks) {
      cur.r = [Math.min(cur.r[0], x0), Math.min(cur.r[1], y0), Math.max(cur.r[2], x1), Math.max(cur.r[3], y1)];
    } else {
      boxes.push((cur = { col, r: [x0, y0, x1, y1] }));
    }
  }
  return boxes.map((b) => b.r);
}

// On text pages, wrap each run of consecutive blocks in a group the note (or a patch) can lie over; largest first.
function textGroups(el, blocks) {
  const all = [...el.querySelectorAll(".block")];
  const runs = [];
  for (const i of [...blocks].sort((a, b) => a - b)) {
    const run = runs.at(-1);
    run && run.at(-1) === i - 1 ? run.push(i) : runs.push([i]);
  }
  const size = (run) => run.reduce((n, i) => n + all[i].textContent.length, 0);
  return runs
    .sort((a, b) => size(b) - size(a))
    .map((run) => {
      const group = document.createElement("div");
      group.className = "block-group";
      all[run[0]].before(group);
      group.append(...run.map((i) => all[i]));
      return group;
    });
}

function twoColumns(page) {
  const chars = (blocks) => blocks.reduce((n, b) => n + b.text.length, 0);
  return chars(page.blocks.filter((b) => b.bbox[2] - b.bbox[0] < 0.5 * page.width)) > 0.5 * chars(page.blocks);
}

function columnOf(b, page) {
  const [x0, , x1] = b.bbox;
  if (x1 - x0 > 0.6 * page.width) return "full";
  return (x0 + x1) / 2 < page.width / 2 ? "left" : "right";
}

const area = ([x0, y0, x1, y1]) => (x1 - x0) * (y1 - y0);

function place(el, [x0, y0, x1, y1], page) {
  const pct = (v, total) => `${(v / total) * 100}%`;
  Object.assign(el.style, {
    left: pct(x0 - NOTE_PAD, page.width),
    top: pct(y0 - NOTE_PAD, page.height),
    width: pct(x1 - x0 + 2 * NOTE_PAD, page.width),
    height: pct(y1 - y0 + 2 * NOTE_PAD, page.height),
  });
}

function setNote(note, on) {
  for (const n of [note, ...note.parts]) n.classList.toggle("off", !on);
  const sw = note.querySelector(".switch");
  sw.setAttribute("aria-pressed", on);
  sw.title = on ? "Show original" : "Show note";
}

function setAllNotes(container, on) {
  container.querySelectorAll(".note:not(.part)").forEach((n) => setNote(n, on));
}

// Largest font (up to MAX_FONT of the page width) at which the note fits in the space of the text it covers. If it
// doesn't fit even at its kind's MIN_FONT (a figure note on a short caption, say), let the note grow downwards.
function fit(note) {
  const body = note.querySelector(".note-body");
  if (note.classList.contains("aside")) return (body.hidden = note.clientWidth < 120); // too narrow for a label: just blur
  const overflows = () => note.scrollHeight > note.clientHeight || note.scrollWidth > note.clientWidth;
  const min = MIN_FONT[[...note.classList].find((c) => c in MIN_FONT)] ?? 12;
  note.classList.remove("grow");
  let size = Math.max(min, note.closest(".page").clientWidth * MAX_FONT);
  body.style.fontSize = `${size}px`;
  while (size > min && overflows()) body.style.fontSize = `${--size}px`;
  note.classList.toggle("grow", overflows());
}
