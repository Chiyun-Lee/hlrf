// The reader: the paper's pages with a "doodle note" laid over each paragraph, in the spirit of Claire Lamman's
// annotated papers. Each note blurs the original underneath and carries a switch (top-right) to flip back to it.
//
// PDF papers render with pdf.js and notes sit on each paragraph's box from the PDF. Papers we only have as HTML
// show their paragraphs as text, with the same notes on top. Notes are fetched page by page as you scroll.

const PDFJS = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.10.38";
const NOTE_PAD = 4; // PDF points of breathing room around a paragraph's box
const MAX_FONT = 0.024; // largest note font, as a fraction of the page width

let pdfjsLib;
async function loadPdf(url) {
  if (!pdfjsLib) {
    pdfjsLib = await import(`${PDFJS}/pdf.min.mjs`);
    pdfjsLib.GlobalWorkerOptions.workerSrc = `${PDFJS}/pdf.worker.min.mjs`;
  }
  return pdfjsLib.getDocument(url).promise;
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

  // Draw pages (and fetch their notes) shortly before they scroll into view.
  const seen = new IntersectionObserver(
    (entries) => entries.filter((e) => e.isIntersecting).forEach((e) => (seen.unobserve(e.target), e.target.load())),
    { rootMargin: "100% 0px" },
  );
  pages.forEach((el) => seen.observe(el));

  // Re-fit note text once the handwriting font arrives and whenever the page width changes.
  const refit = () => container.querySelectorAll(".note:not(.part)").forEach(fit);
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
  if (onPdf) {
    el.style.aspectRatio = `${page.width} / ${page.height}`;
    el.innerHTML = `<canvas></canvas>`;
  } else {
    el.innerHTML = page.blocks.map((b) => `<div class="block"><p>${esc(b.text)}</p></div>`).join("");
  }
  el.insertAdjacentHTML("beforeend", `<div class="page-status"></div>`);

  el.load = async () => {
    if (onPdf) drawPdfPage(el.querySelector("canvas"), pdf, i);
    const status = el.querySelector(".page-status");
    status.textContent = "writing notes…";
    try {
      const summary = await api(`/papers/${paperId}/pages/${i}/summary`);
      summary.notes.forEach((n) => addNote(el, page, n, onPdf));
      status.textContent = "";
    } catch (e) {
      status.innerHTML = `notes failed <button>retry</button>`;
      status.querySelector("button").onclick = () => el.load();
    }
  };
  return el;
}

async function drawPdfPage(canvas, pdf, i) {
  const page = await pdf.getPage(i + 1);
  const scale = (canvas.parentElement.clientWidth / page.getViewport({ scale: 1 }).width) * (window.devicePixelRatio || 1);
  const viewport = page.getViewport({ scale });
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
}

function addNote(el, page, n, onPdf) {
  const note = document.createElement("div");
  note.className = "note";
  note.innerHTML = `
    <button class="switch" title="Show original" aria-pressed="true"></button>
    <div class="note-body">
      ${n.heading ? `<div class="note-heading">${esc(n.heading)}</div>` : ""}
      ${n.bullets.length ? `<ul>${n.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}
    </div>`;
  note.parts = [];
  note.querySelector(".switch").onclick = () => setNote(note, note.classList.contains("off"));

  if (onPdf) {
    // One box per column the run touches: the largest carries the note, the others are plain washes that switch with it.
    const [main, ...rest] = columnBoxes(page, n.first, n.last).sort((a, b) => area(b) - area(a));
    place(note, main, page);
    el.append(note);
    for (const box of rest) {
      const part = document.createElement("div");
      part.className = "note part";
      place(part, box, page);
      el.append(part);
      note.parts.push(part);
    }
  } else {
    // Wrap the covered blocks so the note can lie over all of them.
    const blocks = [...el.querySelectorAll(".block")].slice(n.first, n.last + 1);
    const group = document.createElement("div");
    group.className = "block-group";
    blocks[0].before(group);
    group.append(...blocks, note);
  }
  fit(note);
}

// Bounding box of blocks first..last in each column, so a note never straddles a two-column layout.
// Column logic mirrors two_columns()/column() in backend/app/summarize.py.
function columnBoxes(page, first, last) {
  const cols = twoColumns(page);
  const boxes = new Map();
  for (const b of page.blocks.slice(first, last + 1)) {
    const col = cols ? columnOf(b, page) : "all";
    const [x0, y0, x1, y1] = b.bbox;
    const r = boxes.get(col);
    boxes.set(col, r ? [Math.min(r[0], x0), Math.min(r[1], y0), Math.max(r[2], x1), Math.max(r[3], y1)] : [x0, y0, x1, y1]);
  }
  return [...boxes.values()];
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

// Largest font (up to MAX_FONT of the page width) at which the note fits in the space of the text it covers.
function fit(note) {
  const body = note.querySelector(".note-body");
  const pageWidth = note.closest(".page").clientWidth;
  let size = Math.max(12, pageWidth * MAX_FONT);
  body.style.fontSize = `${size}px`;
  while (size > 8 && (body.scrollHeight > note.clientHeight || body.scrollWidth > note.clientWidth)) {
    body.style.fontSize = `${--size}px`;
  }
}
