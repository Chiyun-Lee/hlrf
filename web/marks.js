// Doodles on figures (Mark in backend/app/schemas.py): hand-drawn circles and arrows with short handwritten notes,
// like Claire Lamman draws on her plots. Drawn with rough.js into an SVG, so they work in the reader and in the
// exported graphical abstract alike.

const MARK_INK = "#1f2f7a";

// Draws `marks` into the <svg> element `svg`. `place(x, y)` maps 0-1000 mark coordinates to the svg's units and
// `size` is the text size in those units.
function drawMarks(svg, marks, place, size) {
  const rc = rough.svg(svg);
  const placed = []; // note boxes drawn so far, so notes don't land on each other
  marks.forEach((m, i) => {
    const opts = { stroke: MARK_INK, strokeWidth: size / 8, roughness: 1.3, bowing: 1.2, seed: i + 1 };
    const [x0, y0] = place(m.box[0], m.box[1]);
    const [x1, y1] = place(m.box[2], m.box[3]);
    let [tx, ty] = place(m.text_at[0], m.text_at[1]);
    const lines = splitWords(m.text, 16);
    const half = [(Math.max(...lines.map((l) => l.length)) * size * 0.27), (lines.length * size * 1.15) / 2];
    const hits = () => placed.some(([x, y, w, h]) => Math.abs(tx - x) < half[0] + w && Math.abs(ty - y) < half[1] + h);
    for (let n = 0; n < 6 && hits(); n++) ty += size * 1.2; // nudge down until clear
    placed.push([tx, ty, ...half]);
    const [cx, cy] = [(x0 + x1) / 2, (y0 + y1) / 2];

    if (m.shape === "circle") {
      const [rx, ry] = [((x1 - x0) / 2) * 1.1 + size * 0.25, ((y1 - y0) / 2) * 1.1 + size * 0.25];
      svg.append(rc.ellipse(cx, cy, rx * 2, ry * 2, opts));
      // Join the note to the circle when it sits away from it.
      const angle = Math.atan2(ty - cy, tx - cx);
      const edge = [cx + rx * Math.cos(angle), cy + ry * Math.sin(angle)];
      const start = leaveBox([tx, ty], half, edge, size * 0.3);
      if (Math.hypot(start[0] - edge[0], start[1] - edge[1]) > size * 1.2) svg.append(rc.line(...start, ...edge, opts));
    } else {
      // An arrow from the note to the nearest point of the feature's box.
      const tip = [Math.min(Math.max(tx, x0), x1), Math.min(Math.max(ty, y0), y1)];
      if (tip[0] === tx && tip[1] === ty) tip.splice(0, 2, cx, cy); // note inside the box: point at its centre
      const start = leaveBox([tx, ty], half, tip, size * 0.3);
      svg.append(rc.line(...start, ...tip, opts));
      const a = Math.atan2(tip[1] - start[1], tip[0] - start[0]);
      for (const turn of [2.6, -2.6]) {
        svg.append(rc.line(...tip, tip[0] + size * 0.7 * Math.cos(a + turn), tip[1] + size * 0.7 * Math.sin(a + turn), opts));
      }
    }

    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("class", "mark-text");
    text.setAttribute("font-size", size);
    text.setAttribute("text-anchor", "middle");
    text.setAttribute("stroke-width", size / 4);
    text.innerHTML = lines.map((l, k) => `<tspan x="${tx}" y="${ty - half[1] + size * (0.85 + 1.15 * k)}">${esc(l)}</tspan>`).join("");
    svg.append(text);
  });
}

// Where a line from the centre of a text box (half-sizes `half`) towards `target` leaves the box, plus a small gap.
function leaveBox([x, y], [hw, hh], [px, py], gap) {
  const [dx, dy] = [px - x, py - y];
  const t = Math.min(dx ? (hw + gap) / Math.abs(dx) : Infinity, dy ? (hh + gap) / Math.abs(dy) : Infinity, 1);
  return [x + dx * t, y + dy * t];
}

// Split a short note into lines of about `width` characters.
function splitWords(s, width) {
  const lines = [];
  for (const word of s.split(/\s+/)) {
    const last = lines.at(-1);
    if (last && (last + " " + word).length <= width) lines[lines.length - 1] = `${last} ${word}`;
    else lines.push(word);
  }
  return lines;
}
