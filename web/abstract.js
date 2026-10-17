// Graphical abstract: one slide built from the notes (backend/app/abstract.py), drawn as SVG so it can be exported
// as a standalone .svg (images and the handwriting font are embedded).

const SLIDE = { w: 1600, h: 900, pad: 60 };
const INK = "#1f2f7a";
const FLOW = {
  question: { label: "THE QUESTION", fill: "#fdeccd" },
  approach: { label: "WHAT THEY DID", fill: "#dfe8fb" },
  finding: { label: "WHAT THEY FOUND", fill: "#dcf2e4" },
  meaning: { label: "SO WHAT?", fill: "#f1e1f8" },
};
const FONT_URL = "https://cdn.jsdelivr.net/gh/ipython/xkcd-font@master/xkcd-script/font/xkcd-script.woff";

// Opens the abstract in an overlay, with the summary cards (cards.js) below it. `make`: (re)generate the abstract
// instead of loading the saved one. `hasCards`: false makes the cards too, alongside the abstract.
async function showAbstract(paperId, paperTitle, { make = false, hasCards = true, onReady } = {}) {
  const deck = api(atLevel(`/papers/${paperId}/cards`), hasCards ? undefined : { method: "POST" });
  deck.catch(() => {}); // shown in the cards section
  const overlay = openOverlay(`<p class="overlay-status">${make ? "Reading every page and drawing your graphical abstract… (about a minute)" : "Loading…"}</p>`);
  let a;
  try {
    a = await api(atLevel(`/papers/${paperId}/abstract`), make ? { method: "POST" } : undefined);
    await document.fonts.load('20px "xkcd"');
  } catch (e) {
    overlay.querySelector(".overlay-status").textContent = `Couldn't make the abstract: ${e.message}`;
    return;
  }
  onReady?.();
  overlay.querySelector(".overlay-box").innerHTML = `
    <div class="overlay-tools">
      <button data-act="export">Export SVG</button>
      <button data-act="remake">Remake</button>
      <button data-act="quiz">Quiz me ✦</button>
      <button data-act="close" class="close" title="Close">×</button>
    </div>
    <div class="abstract-slide">${abstractSvg(a, paperTitle)}</div>
    <div class="cards-slot"></div>`;
  showCards(overlay.querySelector(".cards-slot"), paperId, deck);
  overlay.querySelector(".overlay-tools").onclick = async (e) => {
    const act = e.target.dataset.act;
    if (act === "export") exportSvg(abstractSvg(a, paperTitle, await embeddedFont()), paperTitle);
    if (act === "remake") (overlay.remove(), showAbstract(paperId, paperTitle, { make: true, onReady }));
    if (act === "quiz") (overlay.remove(), startQuiz(paperId));
    if (act === "close") overlay.remove();
  };
}

function abstractSvg(a, paperTitle, fontCss = "") {
  const { w, h, pad } = SLIDE;
  const out = [];
  let y = pad + 20;
  out.push(svgText(pad, y, a.title.toUpperCase(), 46, w - 2 * pad, { underline: true }));
  y += 52;
  const takeaway = wrap(a.takeaway, w - 2 * pad, 26);
  out.push(svgText(pad, y, takeaway, 26, w - 2 * pad, { opacity: 0.85 }));
  y += takeaway.length * 32 + 20;

  // Flow: boxes left to right joined by arrows.
  const gap = 46;
  const n = a.flow.length;
  const boxW = (w - 2 * pad - gap * (n - 1)) / n;
  const boxH = 168;
  a.flow.forEach((step, i) => {
    const x = pad + i * (boxW + gap);
    const kind = FLOW[step.kind] ?? FLOW.approach;
    out.push(`<rect x="${x}" y="${y}" width="${boxW}" height="${boxH}" rx="16" fill="${kind.fill}" stroke="${INK}" stroke-width="2"/>`);
    out.push(svgText(x + 16, y + 30, kind.label, 15, boxW - 32, { opacity: 0.7 }));
    out.push(svgText(x + 16, y + 62, wrap(step.text, boxW - 32, 21).slice(0, 4), 21, boxW - 32));
    if (i < n - 1) {
      const ax = x + boxW + 6;
      out.push(`<path d="M${ax} ${y + boxH / 2} h${gap - 14}" stroke="${INK}" stroke-width="3" fill="none" marker-end="url(#arrow)"/>`);
    }
  });
  y += boxH + 36;

  // Figures on the left, key points on the right (full width when there are no figures).
  const figs = a.figures.filter((f) => f.image);
  const bottom = h - pad;
  const figW = figs.length ? 840 : 0;
  // Two figures go side by side or stacked, whichever shows them bigger.
  const areaH = bottom - y;
  const shown = (slotW, slotH) => figs.reduce((s, f) => s + Math.min(slotW / f.width, (slotH - 70) / f.height) ** 2 * f.width * f.height, 0);
  const sideBySide = figs.length === 2 && shown((figW - 20) / 2, areaH) > shown(figW, (areaH - 20) / 2);
  figs.forEach((f, i) => {
    const [slotW, slotH] = sideBySide ? [(figW - 20) / 2, areaH] : [figW, (areaH - 20 * (figs.length - 1)) / figs.length];
    const [left, top] = sideBySide ? [pad + i * (slotW + 20), y] : [pad, y + i * (slotH + 20)];
    const label = wrap(f.label, slotW - 24, 20).slice(0, 3);
    const imgH = slotH - 14 - label.length * 26;
    out.push(`<rect x="${left}" y="${top}" width="${slotW}" height="${slotH}" rx="12" fill="#fff" stroke="${INK}" stroke-width="1.5" stroke-dasharray="6 5"/>`);
    const [bx, by, bw, bh] = [left + 8, top + 8, slotW - 16, imgH - 8];
    out.push(`<image href="${f.image}" x="${bx}" y="${by}" width="${bw}" height="${bh}" preserveAspectRatio="xMidYMid meet"/>`);
    if (f.marks?.length) {
      // Doodles sit on the image as drawn (scaled to fit, centred).
      const s = Math.min(bw / f.width, bh / f.height);
      const [dw, dh] = [f.width * s, f.height * s];
      const [ox, oy] = [bx + (bw - dw) / 2, by + (bh - dh) / 2];
      const g = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      drawMarks(g, f.marks, (x, y) => [ox + (x / 1000) * dw, oy + (y / 1000) * dh], 17);
      out.push(g.innerHTML);
    }
    out.push(svgText(left + 12, top + imgH + 22, label, 20, slotW - 24));
  });
  const bx = figs.length ? pad + figW + 50 : pad;
  const bw = w - pad - bx;
  out.push(svgText(bx, y + 24, "KEY POINTS", 26, bw, { underline: true }));
  let by = y + 68;
  for (const b of a.bullets) {
    const lines = wrap(b, bw - 30, 22);
    if (by + lines.length * 30 > bottom) break;
    out.push(`<circle cx="${bx + 8}" cy="${by - 7}" r="4" fill="${INK}"/>`);
    out.push(svgText(bx + 26, by, lines, 22, bw - 30));
    by += lines.length * 30 + 14;
  }
  out.push(svgText(pad, h - 18, paperTitle, 14, w - 2 * pad, { opacity: 0.5 }));

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">
  <defs>
    <style>${fontCss} text { font-family: xkcd, "Comic Sans MS", cursive; fill: ${INK}; }
      .mark-text { stroke: #fff; paint-order: stroke; stroke-linejoin: round; }</style>
    <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0 L10 5 L0 10 z" fill="${INK}"/></marker>
  </defs>
  <rect width="${w}" height="${h}" fill="#fff"/>
  ${out.join("\n  ")}
</svg>`;
}

// SVG <text> with one <tspan> per line; `lines` is a string (wrapped here) or already-wrapped lines.
function svgText(x, y, lines, size, width, { underline = false, opacity = 1 } = {}) {
  if (typeof lines === "string") lines = wrap(lines, width, size);
  const spans = lines.map((l, i) => `<tspan x="${x}" dy="${i ? size * 1.3 : 0}">${esc(l)}</tspan>`).join("");
  const deco = underline ? ` text-decoration="underline"` : "";
  return `<text x="${x}" y="${y}" font-size="${size}" opacity="${opacity}"${deco}>${spans}</text>`;
}

// Greedy word wrap, measured with the handwriting font.
const measure = document.createElement("canvas").getContext("2d");
function wrap(s, width, size) {
  measure.font = `${size}px xkcd, "Comic Sans MS", cursive`;
  const lines = [];
  let line = "";
  for (const word of String(s).split(/\s+/)) {
    const next = line ? `${line} ${word}` : word;
    if (line && measure.measureText(next).width > width) (lines.push(line), (line = word));
    else line = next;
  }
  return line ? [...lines, line] : lines;
}

let fontCss;
async function embeddedFont() {
  if (fontCss === undefined) {
    try {
      const bytes = new Uint8Array(await (await fetch(FONT_URL)).arrayBuffer());
      let binary = "";
      for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      fontCss = `@font-face { font-family: xkcd; src: url(data:font/woff;base64,${btoa(binary)}) format("woff"); }`;
    } catch {
      fontCss = ""; // the export falls back to a system handwriting font
    }
  }
  return fontCss;
}

function exportSvg(svg, title) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  a.download = `${title.replace(/[^\w]+/g, "-").slice(0, 60)}-graphical-abstract.svg`;
  a.click();
  URL.revokeObjectURL(a.href);
}

// A full-screen overlay (shared with quiz.js); click outside the box or press Escape to close.
function openOverlay(html) {
  const overlay = document.createElement("div");
  overlay.className = "overlay";
  overlay.innerHTML = `<div class="overlay-box">${html}</div>`;
  overlay.addEventListener("click", (e) => e.target === overlay && overlay.remove());
  const onKey = (e) => e.key === "Escape" && (overlay.remove(), document.removeEventListener("keydown", onKey));
  document.addEventListener("keydown", onKey);
  document.body.append(overlay);
  return overlay;
}
