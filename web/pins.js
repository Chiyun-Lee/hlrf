// Methods pins: labelled buttons on a paper's figures and tables, written by an agent review (GET /papers/:id/pins,
// backend/app/pins.py). Each figure or table gets one group: where its data come from (Data provenance) first, then
// what the review worries about (Agent-reviewed concern), then what was done (Method). A click opens a card in two
// levels: a plain line in the doodle hand, then a precise line for researchers. One card is open at a time.
//
// Where the groups go: in a rail in the margin beside the page, each level with its figure's top and pushed down so
// none overlap (in the left margin when the chat covers the right one; with short kind names when the margin is
// narrow). Without room for a rail, as a compact group in the figure's top-right corner. Hovering or focusing a
// button outlines its figure on the page.

const PIN_KINDS = { // in the order they're listed
  data: { glyph: "■", name: "Data provenance", short: "Data" },
  concern: { glyph: "▲", name: "Agent-reviewed concern", short: "Concern" },
  method: { glyph: "●", name: "Method", short: "Method" },
};
const RAIL = { full: 176, short: 88, max: 216, card: 248, gap: 16, edge: 8, stack: 12 }; // px; card: narrowest card kept in the margin
const TIGHT = 560; // px: pages narrower than this show short kind names in the corner groups
let openPin = null; // {group, button, card}
let pinsDoc = null; // the reader the pins are drawn in, for re-layout

// Fetches the paper's pins and (re)draws them in reader `doc` (the .doc holding the .page sections), with a summary
// line in the paper's header. `paper` is GET /papers/:id. Called by reader.js once the pages exist, and again by
// review.js when an agent review finishes.
async function showPins(doc, paperId, paper) {
  const token = (doc.pinsToken = {}); // a newer call wins
  const found = await api(`/papers/${paperId}/pins`).catch(() => null); // extras: the paper reads fine without them
  if (doc.pinsToken !== token) return;
  closePin();
  doc.querySelectorAll(".pins, .pin-target").forEach((el) => el.remove());
  doc.parentElement?.querySelector(".pins-summary")?.remove();
  const pageOf = (t) => doc.querySelector(`.pdf-page[data-page="${t.page}"]`); // boxes are in PDF points: PDF pages only
  const targets = (found?.targets ?? []).filter((t) => pageOf(t) && paper.pages[t.page]?.width);
  targets.forEach((t) => addPins(pageOf(t), paper.pages[t.page], t, found.reviewed));
  if (!targets.length) return;
  summarise(doc, targets, found.verdict);
  pinsDoc = doc;
  layoutPins(doc);
}

function addPins(el, page, target, reviewed) {
  const pct = (v, total) => `${(v / total) * 100}%`;
  const [x0, y0, x1, y1] = target.bbox;
  const box = document.createElement("div"); // outlines the figure while one of its pins is in use
  box.className = "pin-target";
  Object.assign(box.style, { left: pct(x0, page.width), top: pct(y0, page.height), width: pct(x1 - x0, page.width), height: pct(y1 - y0, page.height) });

  const group = document.createElement("div");
  group.className = "pins";
  group.setAttribute("role", "group");
  group.setAttribute("aria-label", `Agent review of ${target.label}`);
  group.innerHTML = `<div class="pins-label" aria-hidden="true">${esc(target.label)}</div>`;
  Object.assign(group, { target, page, box });

  const order = Object.keys(PIN_KINDS);
  for (const pin of [...target.pins].sort((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind))) {
    const kind = PIN_KINDS[pin.kind];
    const button = document.createElement("button");
    button.className = `pin ${pin.kind}`;
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", `${kind.name}: ${pin.title}, ${target.label}`);
    button.innerHTML = `
      <span class="pin-kind"><span class="pin-glyph">${kind.glyph}</span><span class="pin-name">${kind.name}</span><span class="pin-short">${kind.short}</span></span>
      <span class="pin-title">${esc(pin.title)}</span>`;
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      const wasOpen = openPin?.button === button;
      closePin();
      if (!wasOpen) openPinCard(group, button, pin, reviewed);
    });
    group.append(button);
  }
  for (const type of ["pointerenter", "pointerleave", "focusin", "focusout"]) group.addEventListener(type, () => setTimeout(() => light(group)));
  el.append(box, group);
}

// Outline the group's figure while the group is hovered or focused, or one of its cards is open.
function light(group) {
  group.box.classList.toggle("lit", group.matches(":hover, :focus-within") || openPin?.group === group);
}

// Rail or corner, by the room beside the page; rail groups stack down the margin without overlapping.
function layoutPins(doc) {
  const groups = [...doc.querySelectorAll(".pins")].sort((a, b) => a.target.page - b.target.page || a.target.bbox[1] - b.target.bbox[1]);
  if (!groups.length) return;
  const column = groups[0].parentElement.getBoundingClientRect(); // every page shares the column
  const chat = document.querySelector(".chat")?.getBoundingClientRect();
  const right = chat && chat.left > column.left ? chat.left : document.documentElement.clientWidth; // a side chat covers the right
  const room = { right: right - column.right - RAIL.gap - RAIL.edge, left: column.left - RAIL.gap - RAIL.edge };
  const sides = ["right", "left"];
  const side = sides.find((s) => room[s] >= RAIL.full) ?? sides.find((s) => room[s] >= RAIL.short);
  const width = side && Math.min(RAIL.max, room[side]);

  let below = -Infinity; // bottom of the last rail group, from the top of the document
  for (const g of groups) {
    const el = g.parentElement;
    const s = el.clientWidth / g.page.width; // px per PDF point
    const [, y0, x1] = g.target.bbox;
    g.classList.toggle("rail", !!side);
    g.classList.toggle("corner", !side);
    g.classList.toggle("short", side ? width < RAIL.full : el.clientWidth < TIGHT);
    if (side) {
      const pageTop = el.offsetTop + el.clientTop;
      const top = Math.max(pageTop + y0 * s, below + RAIL.stack);
      const left = side === "right" ? el.clientWidth + el.clientLeft + RAIL.gap : -(el.clientLeft + RAIL.gap + width);
      Object.assign(g.style, { top: `${top - pageTop}px`, left: `${left}px`, right: "", width: `${width}px` });
      below = top + g.offsetHeight;
    } else {
      Object.assign(g.style, { top: `${y0 * s + 6}px`, left: "", right: `${el.clientWidth - x1 * s + 6}px`, width: "" });
    }
  }
  if (openPin) placeCard(openPin.card, openPin.button);
}

function openPinCard(group, button, pin, reviewed) {
  const kind = PIN_KINDS[pin.kind];
  const { label } = group.target;
  button.setAttribute("aria-expanded", "true");
  const card = document.createElement("div");
  card.className = `pin-card ${pin.kind}`;
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-label", `${kind.name}: ${pin.title}, ${label}`);
  card.innerHTML = `
    <div class="pin-card-head">
      <span class="pin-card-kind">${kind.glyph} ${kind.name}</span>
      <span class="pin-evidence">${esc(pin.evidence)}</span>
    </div>
    <h3>${esc(pin.title)} <span class="pin-card-label">· ${esc(label)}</span></h3>
    <p class="pin-basic">${esc(pin.basic)}</p>
    <div class="pin-level">For researchers</div>
    <p class="pin-researcher">${esc(pin.researcher)}</p>
    <p class="pin-foot">${esc(reviewed)}</p>`;
  card.addEventListener("click", (e) => e.stopPropagation());
  group.parentElement.append(card);
  openPin = { group, button, card };
  placeCard(card, button);
  light(group);
}

// Below the button (above it if there's no room), lined up with its group and kept inside the viewport, clear of a
// side chat. In a wide right-hand margin it narrows to stay off the page.
function placeCard(card, button) {
  const el = card.parentElement;
  const page = el.getBoundingClientRect();
  const b = button.getBoundingClientRect();
  const g = button.parentElement.getBoundingClientRect();
  const chat = document.querySelector(".chat")?.getBoundingClientRect();
  const right = (chat && chat.left > page.left ? chat.left : document.documentElement.clientWidth) - RAIL.edge;
  card.style.width = g.left > page.right && right - g.left >= RAIL.card ? `${Math.min(right - g.left, RAIL.card + 40)}px` : "";
  const [w, h] = [card.offsetWidth, card.offsetHeight];
  const left = Math.max(RAIL.edge, Math.min(g.left, right - w));
  let top = b.bottom + 6;
  if (top + h > innerHeight - RAIL.edge) top = b.top - 6 - h;
  if (top < RAIL.edge) top = Math.max(RAIL.edge, innerHeight - RAIL.edge - h);
  Object.assign(card.style, { left: `${left - page.left - el.clientLeft}px`, top: `${top - page.top - el.clientTop}px` });
}

function closePin() {
  if (!openPin) return;
  const { group, button, card } = openPin;
  card.remove();
  button.setAttribute("aria-expanded", "false");
  openPin = null;
  light(group);
}

// "Agent-reviewed · 5 figures and tables · 4 concerns" and the review's verdict, at the end of the paper's header.
function summarise(doc, targets, verdict) {
  const head = doc.parentElement?.querySelector(".paper-head");
  if (!head) return;
  const nouns = [...new Set(targets.map((t) => (/^tab/i.test(t.label) ? "tables" : "figures")))].sort();
  const what = targets.length === 1 ? nouns[0].slice(0, -1) : nouns.join(" and ");
  const concerns = targets.flatMap((t) => t.pins).filter((p) => p.kind === "concern").length;
  head.insertAdjacentHTML("beforeend", `
    <div class="pins-summary">
      <p class="pins-counts"><b>Agent-reviewed</b> · ${targets.length} ${what} · ${concerns} ${concerns === 1 ? "concern" : "concerns"}</p>
      ${verdict ? `<p class="pins-verdict">${esc(verdict)}</p>` : ""}
    </div>`);
}

document.addEventListener("click", closePin);
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || !openPin) return;
  const { button } = openPin;
  closePin();
  button.focus();
});
// The rail moves with the window and with the chat panel (chat.js toggles body.chat-open).
const relayoutPins = () => pinsDoc?.isConnected && layoutPins(pinsDoc);
addEventListener("resize", relayoutPins);
new MutationObserver(relayoutPins).observe(document.body, { attributes: true, attributeFilter: ["class"] });
