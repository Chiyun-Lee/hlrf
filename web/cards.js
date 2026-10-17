// Summary cards (backend/app/cards.py), shown under the graphical abstract: TL;DR with headline numbers, logic flow,
// mind map, key findings, evidence map, caveats, charts redrawn from the paper's own numbers, key figures cropped
// from the PDF. The quiz lives in quiz.js ("Quiz me ✦").
//
// The deck is a snapshot of the notes it was made from: when they have changed since (a tutor's edit, your own), a
// line offers to remake it. The last card, Reproduction, is live instead: it is read from the paper's agent review
// (its pins' verdict, claims and main problems, backend/app/pins.py) each time the cards open, and redrawn when a
// review finishes while they are open.

const STATUS = { // a checked claim's status, as the Reproduction card shows it
  holds: ["✓", "Holds"],
  partly: ["◐", "Partly"],
  fails: ["✗", "Doesn't hold"],
  untested: ["–", "Not tested"],
};

// `deck`: a promise of the cards (GET or POST /papers/:id/cards), started by the caller so it can run alongside
// the abstract.
async function showCards(el, paperId, deck) {
  el.innerHTML = `<p class="overlay-status">Writing your summary cards…</p>`;
  const remake = () => showCards(el, paperId, api(atLevel(`/papers/${paperId}/cards`), { method: "POST" }));
  const checked = reviewed(paperId);
  let c;
  try {
    c = await deck;
  } catch (e) {
    el.innerHTML = `<p class="overlay-status">Couldn't make the summary cards: ${esc(e.message)}</p>
      <div class="cards-retry"><button>Try again</button></div>`;
    el.querySelector("button").onclick = remake;
    return;
  }
  el.innerHTML = cardsHtml(c, paperId, await checked);
  el.querySelectorAll("[data-act=remake-cards]").forEach((b) => (b.onclick = remake));
}

// What the paper's agent review found, for the Reproduction card: its pins (verdict, claims, main problems) and the
// review's state. Either can be null: the cards read fine without them.
async function reviewed(paperId) {
  const [pins, review] = await Promise.all([
    api(`/papers/${paperId}/pins`).catch(() => null),
    api(`/papers/${paperId}/review?after=${Number.MAX_SAFE_INTEGER}`).catch(() => null), // the state, not the steps
  ]);
  return { pins, review };
}

// Redraws the Reproduction card of paper `paperId` if its cards are open. Called by review.js when a review ends.
async function refreshReproduction(paperId) {
  const card = document.querySelector(`.summary-cards[data-paper="${paperId}"] .sc-repro`);
  if (!card) return;
  const html = reproductionCard(+card.dataset.n, paperId, await reviewed(paperId));
  if (card.isConnected) card.outerHTML = html;
}

function cardsHtml(c, paperId, checked) {
  let n = 0;
  const card = (label, title, body, wide = false) =>
    `<div class="sc${wide ? " wide" : ""}"><div class="sc-tag">Card ${++n} · ${label}</div><h3>${esc(title)}</h3>${body}</div>`;
  const list = (items) => `<ul>${items.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>`;

  const out = [];
  out.push(
    card(
      "TL;DR",
      "The takeaway",
      `<p class="sc-tldr">${esc(c.tldr)}</p>
       <div class="sc-stats">${c.stats.map((s) => `<div><b>${esc(s.value)}</b><span>${esc(s.label)}</span></div>`).join("")}</div>`,
      true,
    ),
  );
  out.push(
    card(
      "Logic flow",
      "Question → evidence → conclusion",
      `<ol class="sc-flow">${c.flow.map((s) => `<li><b>${esc(s.title)}</b><span>${esc(s.detail)}</span></li>`).join("")}</ol>`,
    ),
  );
  out.push(card("Mind map", "Concept map", mindMap(c.topic, c.mindmap)));
  out.push(card("Key findings", "What they found", list(c.findings)));
  out.push(
    card(
      "Evidence map",
      "What supports each claim",
      `<table class="sc-table"><tr><th>Claim</th><th>Evidence</th></tr>${c.evidence
        .map((r) => `<tr><td>${esc(r.claim)}</td><td>${esc(r.evidence)}</td></tr>`)
        .join("")}</table>`,
    ),
  );
  if (c.charts.length)
    out.push(
      card(
        "Data, redrawn",
        "Numbers from the paper",
        `<div class="sc-charts">${c.charts.map(chartHtml).join("")}</div>`,
        true,
      ),
    );
  if (c.figures.length)
    out.push(
      card(
        "Key figures",
        "Figures worth a look",
        `<div class="sc-figures">${c.figures
          .map(
            (f) => `<figure><img src="${f.image}" alt="${esc(f.callout)}" />
              <figcaption><span class="muted">Page ${+f.figure.slice(1, f.figure.indexOf("n")) + 1}</span> ${esc(f.callout)}</figcaption></figure>`,
          )
          .join("")}</div>`,
        true,
      ),
    );
  out.push(card("Caveats", "Keep in mind", list(c.caveats), true));
  out.push(reproductionCard(++n, paperId, checked));

  const stale = c.notes_changed
    ? `<p class="sc-stale" role="status">Your notes changed since these cards were made.
        <button data-act="remake-cards">Remake cards</button></p>`
    : "";
  return `<section class="summary-cards" data-paper="${paperId}">
    <div class="sc-head"><h2>Summary cards</h2><button data-act="remake-cards">Remake cards</button></div>
    ${stale}
    <div class="sc-grid">${out.join("")}</div>
  </section>`;
}

// Card n: whether the paper held up when an agent review re-ran its code and tested its claims, from `reviewed`.
function reproductionCard(n, paperId, { pins, review }) {
  const wrap = (body) =>
    `<div class="sc wide sc-repro" data-n="${n}"><div class="sc-tag">Card ${n} · Reproduction</div><h3>Did it hold up?</h3>${body}</div>`;
  const running = review?.state === "running" ? `<p class="sc-repro-note">A review is running now; this card updates when it finishes.</p>` : "";
  const claims = pins?.claims ?? [];
  const problems = pins?.main_problems ?? [];
  if (!pins?.verdict && !claims.length && !problems.length)
    return wrap(running || `<p class="sc-repro-note">Not reproduced yet. <b>Run paper2agent review</b> (in the paper's header) re-runs
      the authors' code and tests these claims; what it finds shows here.</p>`);
  const table = claims.length
    ? `<table class="sc-table sc-claims"><tr><th>Claim</th><th>Paper</th><th>Re-run</th><th>Result</th></tr>${claims
        .map((k) => {
          const [glyph, name] = STATUS[k.status] ?? STATUS.untested;
          return `<tr><td>${esc(k.claim)}<span class="sc-check">${esc(k.check)}</span></td><td>${esc(k.paper)}</td>
            <td>${esc(k.rerun ?? "—")}</td><td><span class="sc-status ${k.status}">${glyph} ${name}</span></td></tr>`;
        })
        .join("")}</table>`
    : "";
  const report = review?.report ? ` · <a href="/papers/${paperId}/review/report" target="_blank" rel="noopener">Read the full review</a>` : "";
  return wrap(`${running}
    ${pins.verdict ? `<p class="sc-verdict">${esc(pins.verdict)}</p>` : ""}
    ${table}
    ${problems.length ? `<h4 class="sc-sub">Main problems</h4><ol class="sc-problems">${problems.map((p) => `<li>${esc(p)}</li>`).join("")}</ol>` : ""}
    <p class="sc-repro-note">${esc(pins.reviewed)}${report}</p>`);
}

// Four branches around the topic, joined by lines drawn behind them.
function mindMap(topic, branches) {
  const spots = ["tl", "tr", "bl", "br"];
  return `<div class="sc-mind">
    <svg class="sc-mind-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      ${spots.slice(0, branches.length).map((s) => `<line x1="50" y1="50" x2="${s[1] === "l" ? 18 : 82}" y2="${s[0] === "t" ? 18 : 82}"/>`).join("")}
    </svg>
    <div class="sc-mind-topic">${esc(topic)}</div>
    ${branches
      .map(
        (b, i) => `<div class="sc-branch ${spots[i]}"><b>${esc(b.title)}</b><ul>${b.points.map((p) => `<li>${esc(p)}</li>`).join("")}</ul></div>`,
      )
      .join("")}
  </div>`;
}

// A dot plot with optional error bars; the number as printed in the paper sits in its own column on the right.
function chartHtml(chart) {
  const W = 560, L = 160, R = 410, top = 14, row = 30;
  const H = top + chart.items.length * row + 40;
  const lo = Math.min(...chart.items.map((i) => i.low ?? i.value));
  const hi = Math.max(...chart.items.map((i) => i.high ?? i.value));
  const ticks = niceTicks(lo, hi);
  const [d0, d1] = [ticks[0], ticks.at(-1)];
  const x = (v) => L + ((v - d0) / (d1 - d0 || 1)) * (R - L);
  const base = top + chart.items.length * row;
  const rows = chart.items
    .map((it, k) => {
      const y = top + k * row + row / 2;
      const bar =
        it.low != null && it.high != null
          ? `<path d="M${x(it.low)},${y}H${x(it.high)}M${x(it.low)},${y - 4}v8M${x(it.high)},${y - 4}v8" class="sc-err"/>`
          : "";
      const label = it.label.length > 24 ? `${it.label.slice(0, 23)}…` : it.label;
      return `<g><title>${esc(it.label)}: ${esc(it.printed)}</title>
        <text x="${L - 10}" y="${y + 4}" text-anchor="end">${esc(label)}</text>
        <line x1="${L}" x2="${R}" y1="${y}" y2="${y}" class="sc-row"/>${bar}
        <circle cx="${x(it.value)}" cy="${y}" r="5" class="sc-dot"/>
        <text x="${R + 12}" y="${y + 4}" class="sc-printed">${esc(it.printed)}</text></g>`;
    })
    .join("");
  const axis = ticks
    .map((t) => `<line x1="${x(t)}" x2="${x(t)}" y1="${top}" y2="${base}" class="sc-grid"/><text x="${x(t)}" y="${base + 16}" text-anchor="middle" class="sc-tick">${fmt(t)}</text>`)
    .join("");
  return `<figure class="sc-chart">
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(chart.title)}">${axis}${rows}
      <line x1="${L}" x2="${R}" y1="${base}" y2="${base}" class="sc-axis"/>
      <text x="${(L + R) / 2}" y="${base + 34}" text-anchor="middle" class="sc-tick">${esc(chart.axis)}</text></svg>
    <figcaption><b>${esc(chart.title)}</b> ${esc(chart.caption)} <span class="muted">Source: ${esc(chart.source)}.</span></figcaption>
  </figure>`;
}

function niceTicks(lo, hi, count = 5) {
  if (lo === hi) [lo, hi] = [lo - Math.abs(lo || 1) * 0.1, hi + Math.abs(hi || 1) * 0.1];
  const raw = (hi - lo) / count;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw);
  const ticks = [];
  for (let t = Math.floor(lo / step) * step; t <= hi + step * 1e-9 || ticks.length < 2; t += step) ticks.push(+t.toPrecision(12));
  if (ticks.at(-1) < hi) ticks.push(+(ticks.at(-1) + step).toPrecision(12));
  return ticks;
}

function fmt(v) {
  return Math.abs(v) >= 1e4 || (Math.abs(v) < 1e-3 && v !== 0) ? v.toExponential(1) : String(+v.toPrecision(6));
}

