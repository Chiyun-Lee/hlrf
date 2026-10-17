// Journal club (#/club, backend/app/club.py, backend/journal_club/): the papers of a card set become PhD-student agents
// that, in one night, map every pair (agree / disagree / shared limitation), debate the clashes under a PI and write
// ranked research directions, each backed by verbatim quotes from the papers. A backtest holds out the papers dated on
// or after T and scores the directions against them, next to a one-call baseline.
//   #/club              the nights so far, a form to start one, the card sets
//   #/club/runs/:name   one night: steps, overview, directions, disputes, the pair map, the backtest
// Everything drawn here is a projection of the run's events.jsonl, folded by journal_club/state.py (GET /club/runs/:name).

const RELATIONS = { agree: "Agree", disagree: "Disagree", shared_limitation: "Shared limitation", unrelated: "Unrelated" };
const STEPS = { map: "Map", debate: "Debate", directions: "Directions", synthesis: "Synthesis", baseline: "Baseline", judge: "Judge" };
const POINT_KINDS = { consensus: "Agreed", dissent: "Disputed", gap: "Open", direction: "Next" };
const POLL_MS = 2500;
let clubTimer = null; // the next poll while something is running; cleared when the view is left

// --- #/club ---

async function clubPage() {
  clearTimeout(clubTimer);
  const [runs, sets, papers] = await Promise.all([api("/club/runs"), api("/club/cards"), api("/papers").catch(() => [])]);
  app.innerHTML = `
    <h1 class="hand">Journal club</h1>
    <p class="muted">Each paper in a card set becomes a PhD-student agent. In one night they map every pair of papers (agree,
      disagree, shared limitation), debate the clashes under a PI and write ranked research directions, each backed by
      verbatim quotes. A backtest holds out the papers dated on or after T and scores the directions against them.</p>
    <h2 class="hand">Nights</h2>
    <div id="club-runs"></div>
    <section class="club-new">
      <h3 class="hand">Start a night</h3>
      <form class="club-form">
        <div class="club-row">
          <input name="name" placeholder="Name, e.g. desi-night-2" pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}" required />
          <select name="cards" required>${sets.filter((s) => s.papers.length).map((s) => `<option value="${esc(s.name)}">${esc(s.name)} · ${s.papers.length} papers</option>`).join("")}</select>
        </div>
        <textarea name="agenda" rows="2" placeholder="Agenda: what should the club look for tonight?" required></textarea>
        <div class="club-row">
          <label class="club-kind-pick"><input type="radio" name="kind" value="night" checked /> Night</label>
          <label class="club-kind-pick"><input type="radio" name="kind" value="backtest" /> Backtest, holding out papers from</label>
          <input name="t" type="date" aria-label="Split date T" disabled />
          <button class="btn primary" type="submit">Start</button>
        </div>
        <div class="club-status small" role="status"></div>
      </form>
    </section>
    <h2 class="hand">Card sets</h2>
    <div id="club-sets"></div>
    ${papers.length ? `<form class="club-make-set">
      <h3 class="hand">Make a card set from your library</h3>
      <p class="muted small">One Claude call per paper reads its claims, methods, data and limits, each with a quote checked against the text. Up to 16 papers (a night maps every pair).</p>
      <div class="club-row"><input name="name" placeholder="Set name" pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}" required /><button class="btn" type="submit">Make cards</button></div>
      <div class="club-pick">${papers.map((p) => `<label><input type="checkbox" value="${p.id}" /> ${esc(p.title)}${p.year ? ` <span class="muted small">${p.year}</span>` : ""}</label>`).join("")}</div>
      <div class="club-status small" role="status"></div>
    </form>` : ""}`;

  const runsBox = app.querySelector("#club-runs");
  const setsBox = app.querySelector("#club-sets");
  const draw = (runs, sets) => {
    runsBox.innerHTML = runs.map(runCard).join("") || `<p class="muted">No nights yet. Start one below on a shipped card set.</p>`;
    setsBox.innerHTML = sets.map(setCard).join("");
    const busy = runs.some((r) => r.state === "running") || sets.some((s) => s.ingesting?.running);
    clearTimeout(clubTimer);
    if (busy) clubTimer = setTimeout(async () => location.hash === "#/club" && draw(...(await Promise.all([api("/club/runs"), api("/club/cards")]))), POLL_MS);
  };
  draw(runs, sets);

  const form = app.querySelector(".club-form");
  const t = form.querySelector("[name=t]");
  form.addEventListener("change", () => ((t.disabled = form.kind.value !== "backtest"), (t.required = !t.disabled)));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const status = form.querySelector(".club-status");
    const body = { name: form.name.value.trim(), cards: form.cards.value, agenda: form.agenda.value.trim(), kind: form.kind.value, t: t.disabled ? null : t.value || null };
    status.textContent = "Starting…";
    try {
      const run = await api("/club/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      location.hash = `#/club/runs/${run.name}`;
    } catch (err) {
      status.textContent = err.message;
    }
  });
  app.querySelector(".club-make-set")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const status = f.querySelector(".club-status");
    const ids = [...f.querySelectorAll("input:checked")].map((i) => +i.value);
    if (!ids.length) return (status.textContent = "Tick at least one paper.");
    if (ids.length > 16) return (status.textContent = "At most 16 papers.");
    status.textContent = "Reading the papers…";
    try {
      await api("/club/cards", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: f.name.value.trim(), paper_ids: ids }) });
      f.reset();
      status.textContent = "";
      draw(...(await Promise.all([api("/club/runs"), api("/club/cards")])));
    } catch (err) {
      status.textContent = err.message;
    }
  });
}

function runCard(r) {
  return `<a class="club-run ${r.state}" href="#/club/runs/${esc(r.name)}">
    <div class="club-run-head"><b>${esc(r.name)}</b>${stateBadge(r)}${r.example ? `<span class="club-tag">example</span>` : ""}<span class="club-tag kind">${r.kind}${r.T ? ` · T = ${esc(r.T)}` : ""}</span></div>
    <div class="club-agenda">${esc(r.agenda) || "<i>no agenda yet</i>"}</div>
    <div class="muted small">${r.n_cards} papers · ${r.n_directions} directions · ${r.n_disputes} disputes${r.model ? ` · ${esc(r.model)}` : ""}${r.updated ? ` · ${esc(r.updated.slice(0, 16).replace("T", " "))}` : ""}</div>
    ${r.error ? `<div class="club-error small">${esc(r.error)}</div>` : ""}
  </a>`;
}

function stateBadge(r) {
  const words = { running: "running", done: "done", stopped: "stopped · start again to resume", failed: "failed · start again to resume" };
  return `<span class="club-state ${r.state}">${words[r.state]}</span>`;
}

function setCard(s) {
  const ing = s.ingesting;
  const progress = ing && (ing.running ? `<span class="club-state running">reading ${ing.done}/${ing.total}</span>` : ing.failed.length ? `<span class="club-state failed" title="${esc(ing.failed.join("\n"))}">${ing.failed.length} failed</span>` : "");
  return `<div class="club-set">
    <div class="club-run-head"><b>${esc(s.name)}</b>${s.example ? `<span class="club-tag">example</span>` : ""}${progress || ""}<span class="muted small">${s.papers.length} papers</span></div>
    <div class="club-chips">${s.papers.map((p) => `<span class="club-chip" title="${esc(p.title)}">${esc(p.citekey)}<i>${p.year}</i></span>`).join("")}</div>
  </div>`;
}

// --- #/club/runs/:name ---

async function clubRun(name) {
  clearTimeout(clubTimer);
  const { summary, state } = await api(`/club/runs/${name}`);
  const byId = Object.fromEntries(state.cards.map((c) => [c.id, c]));
  const key = (id) => byId[id]?.citekey ?? id;
  app.innerHTML = `
    <div class="club-head">
      <a class="small" href="#/club">← Journal club</a>
      <h1 class="hand">${esc(name)}</h1>
      <div class="club-run-head">${stateBadge(summary)}${summary.example ? `<span class="club-tag">example</span>` : ""}<span class="club-tag kind">${state.kind}${state.T ? ` · T = ${esc(state.T)}` : ""}</span>
        <span class="muted small">${esc(state.model)}${state.judge_model ? ` · judge ${esc(state.judge_model)}` : ""} · ${state.n_events} events</span></div>
      <blockquote class="club-agenda-big">${esc(state.agenda)}</blockquote>
      ${summary.error ? `<div class="club-error">${esc(summary.error)}</div>` : ""}
      <ol class="club-steps">${state.steps.map((s) => `<li class="${s.status}" title="${s.reused ? "rebuilt from the archive, no LLM calls" : s.status}"><span>${STEPS[s.name]}</span><b>${s.count || ""}</b></li>`).join("")}</ol>
      <div class="club-chips">${state.cards.map((c) => `<span class="club-chip" title="${esc(c.title)}">${esc(c.citekey)}<i>${c.year}</i></span>`).join("")}</div>
      <div class="links">
        <a href="/club/runs/${esc(name)}/minutes" target="_blank">Minutes</a>
        ${state.report ? `<a href="/club/runs/${esc(name)}/report" target="_blank">Backtest report</a>` : ""}
        ${summary.example || summary.state === "running" ? "" : `<button class="btn quiet" id="club-delete">Delete</button>`}
      </div>
    </div>
    ${overviewSection(state.synthesis, byId)}
    ${directionsSection("Directions", state.directions, byId, "Ranked by the PI's confidence.")}
    ${disputesSection(state.disputes, key)}
    ${pairMap(state.pairs, state.cards, key)}
    ${state.kind === "backtest" ? backtestSection(state, key) : ""}
    <p class="muted small club-rejected">Quote gate: ${Object.entries(state.rejected).map(([k, n]) => `${k.replace(/_/g, " ")} ${n}`).join(" · ")}</p>`;

  app.querySelector("#club-delete")?.addEventListener("click", async (e) => {
    if (e.target.textContent !== "Really delete?") return (e.target.textContent = "Really delete?");
    await api(`/club/runs/${name}`, { method: "DELETE" });
    location.hash = "#/club";
  });
  const detail = app.querySelector("#club-pair-detail");
  app.querySelector(".club-grid")?.addEventListener("click", (e) => {
    const cell = e.target.closest("td[data-i]");
    if (!cell) return;
    const p = state.pairs[+cell.dataset.i];
    app.querySelectorAll(".club-grid td.picked").forEach((td) => td.classList.remove("picked"));
    cell.classList.add("picked");
    detail.innerHTML = `<b>${esc(key(p.a))}</b> and <b>${esc(key(p.b))}</b>: <span class="club-rel ${p.relation}">${RELATIONS[p.relation] ?? esc(p.relation)}</span>
      <p>${esc(p.note)}</p>${quote(p.quote_a, byId)}${quote(p.quote_b, byId)}`;
  });
  if (summary.state === "running") clubTimer = setTimeout(() => location.hash === `#/club/runs/${name}` && clubRun(name), POLL_MS);
}

function quote(q, byId) {
  if (!q) return "";
  return `<blockquote class="club-quote">“${esc(q.text)}” <span class="muted small">(${esc(byId[q.paper_id]?.citekey ?? q.paper_id)}, ${esc(q.loc)})</span></blockquote>`;
}

function overviewSection(s, byId) {
  if (!s) return "";
  const groups = Object.entries(POINT_KINDS).map(([kind, label]) => [label, s.key_points.filter((k) => k.kind === kind)]).filter(([, ks]) => ks.length);
  return `<section class="club-section">
    <h2 class="hand">Overview</h2>
    <p class="club-overview">${esc(s.overview)}</p>
    ${groups.map(([label, ks]) => `<div class="club-points"><h4 class="hand">${label}</h4>${ks.map((k) => `<div class="club-point">${esc(k.text)}${(k.quotes ?? []).map((q) => quote(q, byId)).join("")}</div>`).join("")}</div>`).join("")}
  </section>`;
}

function directionsSection(title, ds, byId, note) {
  if (!ds.length) return "";
  return `<section class="club-section">
    <h2 class="hand">${title}</h2><p class="muted small">${note}</p>
    <ol class="club-directions">${ds
      .map(
        (d) => `<li>
        <div class="club-dir-text">${esc(d.text)}${d.confidence != null ? `<span class="club-conf" title="PI's confidence">${Number(d.confidence).toFixed(2)}</span>` : ""}</div>
        <div class="club-dir-arc"><span>${esc(d.from_a)}</span> → <span>${esc(d.to_b)}</span></div>
        <div class="muted">because ${esc(d.because)}</div>
        <div class="club-chips">${(d.papers ?? []).map((p) => `<span class="club-chip" title="${esc(byId[p]?.title ?? "")}">${esc(byId[p]?.citekey ?? p)}</span>`).join("")}</div>
        ${(d.quotes ?? []).length ? `<details><summary class="small">${d.quotes.length} quote${d.quotes.length > 1 ? "s" : ""}</summary>${d.quotes.map((q) => quote(q, byId)).join("")}</details>` : ""}
      </li>`,
      )
      .join("")}</ol>
  </section>`;
}

function disputesSection(ds, key) {
  if (!ds.length) return "";
  return `<section class="club-section">
    <h2 class="hand">Disputes</h2><p class="muted small">Each clash from the map, argued by its two students, called by the PI.</p>
    ${ds
      .map(
        (d) => `<details class="club-dispute" open>
        <summary><b>${esc(key(d.a))}</b> vs <b>${esc(key(d.b))}</b> <span class="club-verdict ${esc(d.verdict)}">${esc(d.verdict)}</span></summary>
        <p class="club-claim">${esc(d.claim)}</p>
        <ul class="club-turns">${(d.turns ?? []).map((t) => `<li class="${t.verified ? "" : "unverified"}"><b>${esc(key(t.speaker))}</b> ${esc(t.text)}${t.verified ? "" : ` <span class="club-tag warn">quote not verified</span>`}</li>`).join("")}</ul>
        ${d.judge_reason ? `<p class="club-judge"><b>PI:</b> ${esc(d.judge_reason)}</p>` : ""}
      </details>`,
      )
      .join("")}
  </section>`;
}

function pairMap(pairs, cards, key) {
  if (!pairs.length) return "";
  const ids = cards.map((c) => c.id);
  const at = {};
  pairs.forEach((p, i) => ((at[`${p.a}|${p.b}`] = i), (at[`${p.b}|${p.a}`] = i)));
  const counts = Object.fromEntries(Object.keys(RELATIONS).map((r) => [r, pairs.filter((p) => p.relation === r).length]));
  return `<section class="club-section">
    <h2 class="hand">Pair map</h2>
    <p class="muted small">${pairs.length} pairs · ${Object.entries(counts).map(([r, n]) => `<span class="club-rel ${r}">${RELATIONS[r]} ${n}</span>`).join(" ")} · click a cell for the note and quotes</p>
    <div class="club-grid-wrap"><table class="club-grid">
      <tr><th></th>${ids.map((id) => `<th><span>${esc(key(id))}</span></th>`).join("")}</tr>
      ${ids.map((a) => `<tr><th>${esc(key(a))}</th>${ids.map((b) => (a === b ? `<td class="self"></td>` : at[`${a}|${b}`] == null ? `<td class="pending"></td>` : `<td class="${pairs[at[`${a}|${b}`]].relation}" data-i="${at[`${a}|${b}`]}" title="${esc(key(a))} · ${esc(key(b))}: ${RELATIONS[pairs[at[`${a}|${b}`]].relation]}"></td>`)).join("")}</tr>`).join("")}
    </table></div>
    <div id="club-pair-detail" class="club-pair-detail muted small">Pick a cell.</div>
  </section>`;
}

function backtestSection(state, key) {
  const r = state.report;
  if (!r) return `<section class="club-section"><h2 class="hand">Backtest</h2><p class="muted">The judge hasn't finished.</p></section>`;
  const arm = (label, hits, rate, weighted) => `<tr><th>${label}</th><td>${hits.length}</td><td>${hits.filter((h) => h.verdict === "hit").length}</td><td>${hits.filter((h) => h.verdict === "partial").length}</td><td>${hits.filter((h) => h.verdict === "miss").length}</td><td>${Number(rate).toFixed(2)}</td><td>${Number(weighted).toFixed(2)}</td></tr>`;
  const hitList = (hits) => `<ul class="club-hits">${hits.map((h) => `<li><span class="club-verdict ${esc(h.verdict)}">${esc(h.verdict)}</span> ${esc(h.direction_text)}<div class="muted small">${h.after_paper_id ? `${esc(key(h.after_paper_id))}: ` : ""}${esc(h.reason)}</div></li>`).join("")}</ul>`;
  return `<section class="club-section">
    <h2 class="hand">Backtest</h2>
    <p class="muted small">Papers dated on or after ${esc(r.T)} were held out as the answer key: ${r.after_ids.map((id) => `<b>${esc(key(id))}</b>`).join(", ")}. Judge: ${esc(r.judge_model)}.</p>
    <table class="club-table"><tr><th></th><th>judged</th><th>hits</th><th>partial</th><th>miss</th><th>rate</th><th>weighted</th></tr>
      ${arm("Club", r.club_hits, r.club_rate, r.club_weighted_rate)}${arm("Baseline (one call)", r.baseline_hits, r.baseline_rate, r.baseline_weighted_rate)}</table>
    <details open><summary>Club directions, judged</summary>${hitList(r.club_hits)}</details>
    <details><summary>Baseline directions, judged</summary>${hitList(r.baseline_hits)}</details>
  </section>`;
}
