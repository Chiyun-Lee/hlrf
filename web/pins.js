// Methods pins: small round buttons beside a paper's figures and tables (GET /papers/:id/pins, backend/app/pins.py).
// Each says where the data come from (■ Data), what was done (● Method) or what a reviewer would worry about
// (▲ Concern); hovering shows its title, clicking opens a card in two levels: a plain line in the doodle hand, then a
// precise line for researchers. One card is open at a time.

const PIN_KINDS = {
  data: { glyph: "■", name: "Data" },
  method: { glyph: "●", name: "Method" },
  concern: { glyph: "▲", name: "Concern" },
};
const PIN_SIZE = 22; // px: one button at rest; keep in sync with .pin and .pins in style.css
const pinLine = (k) => k * (PIN_SIZE + 4) - 2; // px: k buttons in a line, with 4px gaps and the stack's 1px padding
let openPin = null; // {button, card}

// Lays the pins of `target` (a figure or table, its bbox in PDF points) on page element `el`.
function addPins(el, page, target, reviewed) {
  const n = target.pins.length;
  const spot = pinSpot(el, page, target.bbox, n);
  const restWidth = pinLine(spot.dir === "column" ? 1 : n);
  const growLeft = spot.x + spot.w / 2 > page.width / 2; // titles slide out towards the middle of the page
  const pct = (v, total) => `${(v / total) * 100}%`;

  const stack = document.createElement("div");
  stack.className = `pins ${spot.dir}${growLeft ? " grow-left" : ""}`;
  stack.setAttribute("role", "group");
  stack.setAttribute("aria-label", `Methods notes on ${target.label}`);
  stack.style.top = pct(target.bbox[1], page.height);
  // Anchor the edge the titles don't grow from, so the buttons stay put while a title slides out.
  if (growLeft) stack.style.right = `calc(${pct(page.width - spot.x, page.width)} - ${restWidth}px)`;
  else stack.style.left = pct(spot.x, page.width);

  for (const pin of target.pins) {
    const kind = PIN_KINDS[pin.kind];
    const button = document.createElement("button");
    button.className = `pin ${pin.kind}`;
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-label", `${kind.name}: ${pin.title}`);
    button.innerHTML = `<span class="pin-glyph" aria-hidden="true">${kind.glyph}</span><span class="pin-label" aria-hidden="true">${esc(pin.title)}</span>`;
    button.addEventListener("click", (e) => {
      e.stopPropagation();
      const wasOpen = openPin?.button === button;
      closePin();
      if (!wasOpen) openPinCard(el, stack, button, target, pin, reviewed);
    });
    stack.append(button);
  }
  el.append(stack);
}

// Where the buttons go so they hide neither data nor text: beside the figure (right, then left; as a column, else as
// a row) in space with no text that stays on the page; failing that, inside its top-right corner.
// Returns the stack's resting box: left edge `x`, width `w` (PDF points) and direction.
function pinSpot(el, page, [x0, y0, x1], n) {
  const pt = page.width / (el.clientWidth || page.width); // PDF points per CSS pixel at the current size
  const column = { dir: "column", w: pinLine(1) * pt, h: pinLine(n) * pt };
  const row = { dir: "row", w: pinLine(n) * pt, h: pinLine(1) * pt };
  const free = ({ x, w, h }) =>
    x >= 0 && x + w <= page.width && !page.blocks.some(({ bbox: [a, b, c, d] }) => a < x + w && x < c && b < y0 + h && y0 < d);
  const spots = [{ ...column, x: x1 }, { ...row, x: x1 }, { ...column, x: x0 - column.w }, { ...row, x: x0 - row.w }];
  return spots.find(free) ?? { ...row, x: x1 - row.w };
}

function openPinCard(el, stack, button, target, pin, reviewed) {
  const kind = PIN_KINDS[pin.kind];
  button.setAttribute("aria-expanded", "true"); // first, so the title folds away and the stack is at rest size
  const card = document.createElement("div");
  card.className = `pin-card ${pin.kind}`;
  card.setAttribute("role", "dialog");
  card.setAttribute("aria-label", `${kind.name}: ${pin.title}`);
  card.innerHTML = `
    <div class="pin-card-head">
      <span class="pin-kind">${kind.glyph} ${kind.name} · ${esc(target.label)}</span>
      <span class="pin-evidence">${esc(pin.evidence)}</span>
    </div>
    <h3>${esc(pin.title)}</h3>
    <p class="pin-basic">${esc(pin.basic)}</p>
    <div class="pin-level">For researchers</div>
    <p class="pin-researcher">${esc(pin.researcher)}</p>
    <p class="pin-foot">${esc(reviewed)}</p>`;
  card.addEventListener("click", (e) => e.stopPropagation());
  el.append(card);

  // Level with the button, opening towards the middle of the page and kept inside it.
  const gap = 6;
  const towardsLeft = stack.classList.contains("grow-left");
  let left = towardsLeft ? stack.offsetLeft - card.offsetWidth - gap : stack.offsetLeft + stack.offsetWidth + gap;
  left = Math.max(4, Math.min(left, el.clientWidth - card.offsetWidth - 4));
  Object.assign(card.style, { left: `${left}px`, top: `${stack.offsetTop + button.offsetTop}px` });
  openPin = { button, card };
}

function closePin() {
  if (!openPin) return;
  openPin.card.remove();
  openPin.button.setAttribute("aria-expanded", "false");
  openPin = null;
}

document.addEventListener("click", closePin);
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || !openPin) return;
  const { button } = openPin;
  closePin();
  button.focus();
});
