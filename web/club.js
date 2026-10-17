// Journal club (#/club, backend/app/club.py, backend/journal_club/): the papers of a card set become PhD-student agents
// that, in one night, map every pair (agree / disagree / shared limitation), debate the clashes under a PI and write
// ranked research directions, each backed by verbatim quotes from the papers. The PI then proposes hypotheses that go
// beyond the papers, and a second round tests them: each paper's student objects or supports, the PI keeps, revises
// or drops each one, and the survivors are ranked by a round-robin. Backtests run from the command line
// (`uv run jc backtest`) and aren't shown here.
//   #/club                     the nights so far, a form to start one, the card sets
//   #/club/runs/:name          one night: overview, pair map, directions, hypotheses, disputes, papers; live progress
//   #/club/runs/:name/minutes  the night's minutes, rendered
// Everything drawn here is a projection of the run's events.jsonl, folded by journal_club/state.py (GET /club/runs/:name).

const RELATIONS = { agree: "Agree", disagree: "Disagree", shared_limitation: "Shared limitation", unrelated: "Unrelated" };
const STEPS = { map: "Map pairs", debate: "Debate", directions: "Directions", hypotheses: "Hypotheses", critique: "Round 2", synthesis: "Overview" };
const COUNTED = new Set(["map", "debate", "directions", "hypotheses", "critique"]); // steps whose count means something to a reader
const DECISIONS = { keep: "kept", revise: "revised", drop: "dropped" }; // the PI's call on a hypothesis after round 2
const SOURCES = { combine: "joins agreeing papers", resolve: "settles a dispute", gap: "behind a shared limitation", extend: "pushes a result further" };
const POINT_KINDS = { consensus: "Agreed", dissent: "Disputed", gap: "Open", direction: "Next" };
const VERDICTS = { stands: "claim stands", contested: "contested", unresolved: "unresolved" };
const AGENDAS = [
  ["Biggest disagreement", "Where do these papers disagree, and which disagreement would change the field most if it were settled?"],
  ["Shared limitation", "Which limitation do these papers share, and what would a study that fixes it look like?"],
  ["Next paper", "What should the next paper in this area do, given what these papers agree on and what they leave open?"],
];
const POLL_MS = 2500;
let clubTimer = null; // the next poll while something is running; cleared when the view is left
const club = { run: null, focus: null, pair: null }; // the open night's view state, kept across live redraws

// --- small words ---

function duration(s) {
  if (s < 10) return "a few seconds";
  if (s < 60) return `${Math.round(s)} s`;
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

const timeLeft = (s) => (s < 60 ? "under a minute left" : `about ${duration(s)} left`);
const localTime = (iso) => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

function liveLine(r) {
  const p = r.progress;
  const step = p.step ? `${STEPS[p.step] ?? p.step}${p.total > 1 ? ` ${p.done}/${p.total}` : ""}` : "Writing the minutes";
  return [step, p.elapsed_s != null ? `running ${duration(p.elapsed_s)}` : "", p.remaining_s != null ? timeLeft(p.remaining_s) : ""].filter(Boolean).join(" · ");
}

function whenLine(r) {
  if (r.example) return "";
  if (r.state === "done" && r.progress?.elapsed_s != null) return `${r.updated ? `${localTime(r.updated)} · ` : ""}took ${duration(r.progress.elapsed_s)}`;
  return r.updated ? localTime(r.updated) : "";
}

// --- #/club ---

async function clubPage() {
  clearTimeout(clubTimer);
  const [runs, sets, papers, cfg] = await Promise.all([api("/club/runs"), api("/club/cards"), api("/papers").catch(() => []), api("/club/config")]);
  const usable = sets.filter((s) => s.papers.length > 1 && !s.ingesting?.running); // a night needs at least one pair
  app.innerHTML = `
    <h1 class="hand">Journal club</h1>
    <p class="muted">Each paper in a card set becomes a PhD-student agent. In one night they compare every pair of papers
      (agree, disagree, shared limitation), debate the clashes under a PI and write ranked research directions. Then the PI
      proposes hypotheses that go beyond the papers, and a second round tests them: the papers they rest on object or
      support, the PI revises or drops them, and the survivors are ranked head to head. Every premise is a quote checked
      word for word against its paper.</p>
    <h2 class="hand">Nights</h2>
    <div id="club-runs"></div>
    <section class="club-new">
      <h3 class="hand">Start a night</h3>
      ${usable.length ? `<form class="club-form">
        <label class="club-field"><span>Papers</span><select name="cards">${usable.map((s) => `<option value="${esc(s.name)}">${esc(s.name)} · ${s.papers.length} papers</option>`).join("")}</select></label>
        <label class="club-field"><span>Question for tonight</span><textarea name="agenda" rows="3" placeholder="What should the club look for? Pick a starting point below or write your own." required></textarea></label>
        <div class="club-presets">${AGENDAS.map(([label], i) => `<button type="button" class="club-preset" data-i="${i}">${esc(label)}</button>`).join("")}</div>
        <label class="club-field"><span>Name</span><input name="name" pattern="[A-Za-z0-9][A-Za-z0-9_\\-]{0,63}" title="Letters, digits, - and _" required /></label>
        <div class="club-row"><button class="btn primary" type="submit">Start the night</button><span class="club-estimate small muted"></span></div>
        <div class="club-status small" role="status"></div>
      </form>` : `<p class="muted">A night needs a card set of at least two papers. Make one from your library below.</p>`}
    </section>
    <h2 class="hand">Card sets</h2>
    <div id="club-sets"></div>
    ${papers.length ? `<form class="club-make-set">
      <h3 class="hand">Make a card set from your library</h3>
      <p class="muted small">One Claude call per paper reads its claims, methods, data and limits, each with a quote checked against the text. Two to 16 papers (a night compares every pair).</p>
      <div class="club-row"><input name="name" placeholder="Set name" pattern="[A-Za-z0-9][A-Za-z0-9_\\-]{0,63}" required /><button class="btn" type="submit">Make cards</button></div>
      <div class="club-pick">${papers.map((p) => `<label><input type="checkbox" value="${p.id}" /> ${esc(p.title)}${p.year ? ` <span class="muted small">${p.year}</span>` : ""}</label>`).join("")}</div>
      <div class="club-status small" role="status"></div>
    </form>` : ""}`;

  const runsBox = app.querySelector("#club-runs");
  const setsBox = app.querySelector("#club-sets");
  const draw = (runs, sets) => {
    const nights = runs.filter((r) => r.kind === "night");
    runsBox.innerHTML = nights.map(runCard).join("") || `<p class="muted">No nights yet. Start one below.</p>`;
    setsBox.innerHTML = sets.map(setCard).join("");
    const busy = nights.some((r) => r.state === "running") || sets.some((s) => s.ingesting?.running);
    clearTimeout(clubTimer);
    if (busy) clubTimer = setTimeout(async () => location.hash === "#/club" && draw(...(await Promise.all([api("/club/runs"), api("/club/cards")]))), POLL_MS);
  };
  draw(runs, sets);

  const form = app.querySelector(".club-form");
  if (form) startForm(form, usable, runs, cfg);
  app.querySelector(".club-make-set")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const status = f.querySelector(".club-status");
    const ids = [...f.querySelectorAll("input:checked")].map((i) => +i.value);
    if (ids.length < 2) return (status.textContent = "Tick at least two papers.");
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

// The start form fills itself in: a free name for the chosen set, starting questions, and what the night will take.
function startForm(form, sets, runs, cfg) {
  const taken = new Set(runs.map((r) => r.name));
  const suggest = (set) => {
    let k = 1;
    while (taken.has(`${set.slice(0, 50)}-night-${k}`)) k++;
    return `${set.slice(0, 50)}-night-${k}`;
  };
  const estimate = form.querySelector(".club-estimate");
  const status = form.querySelector(".club-status");
  const start = form.querySelector("[type=submit]");
  let named = false; // once the name is typed, changing the set leaves it alone
  const update = () => {
    const set = sets.find((s) => s.name === form.cards.value);
    const n = set.papers.length;
    if (!named) form.name.value = suggest(set.name);
    estimate.textContent = `${n} papers · ${(n * (n - 1)) / 2} pairs · up to ${Math.min(cfg.debate_cap, (n * (n - 1)) / 2)} debates · about ${duration(set.night_s)} with ${cfg.backend}. You can leave the page; the night keeps going.`;
  };
  form.name.addEventListener("input", () => (named = true));
  form.cards.addEventListener("change", update);
  form.querySelector(".club-presets").addEventListener("click", (e) => {
    const b = e.target.closest(".club-preset");
    if (!b) return;
    form.agenda.value = AGENDAS[+b.dataset.i][1];
    form.agenda.focus();
  });
  update();
  if (cfg.ready) {
    start.disabled = true;
    status.textContent = `Can't start yet: ${cfg.ready}`;
  }
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = { name: form.name.value.trim(), cards: form.cards.value, agenda: form.agenda.value.trim(), kind: "night" };
    status.textContent = "Starting…";
    start.disabled = true;
    try {
      const run = await api("/club/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      location.hash = `#/club/runs/${run.name}`;
    } catch (err) {
      status.textContent = err.message;
      start.disabled = false;
    }
  });
}

function runCard(r) {
  const facts = r.state === "running" && r.progress ? liveLine(r) : [`${r.n_cards} papers · ${r.n_directions} directions · ${r.n_disputes} disputes`, whenLine(r)].filter(Boolean).join(" · ");
  return `<a class="club-run ${r.state}" href="#/club/runs/${esc(r.name)}">
    <div class="club-run-head"><b>${esc(r.name)}</b>${stateBadge(r)}${r.example ? `<span class="club-tag">example</span>` : ""}</div>
    <div class="club-agenda">${esc(r.agenda) || "<i>starting…</i>"}</div>
    <div class="muted small">${esc(facts)}</div>
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
  const same = club.run === name;
  if (!same) Object.assign(club, { run: name, focus: null, pair: null });
  const open = same ? new Set([...app.querySelectorAll("details[data-key][open]")].map((d) => d.dataset.key)) : new Set();
  const { summary, state } = await api(`/club/runs/${name}`);
  const byId = Object.fromEntries(state.cards.map((c) => [c.id, c]));
  const key = (id) => byId[id]?.citekey ?? id;
  const sections = [
    ["overview", "Overview", overviewSection(state.synthesis, byId)],
    ["pairs", "Pair map", pairMap(state.pairs, state.cards, key)],
    ["directions", "Directions", directionsSection(state.directions, byId)],
    ["hypotheses", "Hypotheses", hypothesesSection(state.hypotheses, byId, key)],
    ["disputes", "Disputes", disputesSection(state.disputes, key)],
    ["papers", "Papers", papersSection(state.cards)],
  ].filter(([, , html]) => html);
  const running = summary.state === "running";
  app.innerHTML = `<div class="club-page">
    <div class="club-head">
      <a class="small" href="#/club">← Journal club</a>
      <h1 class="hand">${esc(name)}</h1>
      <div class="club-run-head">${stateBadge(summary)}${summary.example ? `<span class="club-tag">example</span>` : ""}
        <span class="muted small">${[esc(state.model), `${state.cards.length} papers`, running ? "" : esc(whenLine(summary))].filter(Boolean).join(" · ")}</span></div>
      <blockquote class="club-agenda-big">${esc(state.agenda)}</blockquote>
      ${summary.error ? `<div class="club-error">${esc(summary.error)}</div>` : ""}
      ${stepsStrip(state.steps, summary.progress)}
      ${running && summary.progress ? `<p class="club-live small">${esc(liveLine(summary))}. You can leave this page; the night keeps going.</p>` : ""}
      <div class="club-chips">${state.cards.map((c) => chip(c.id, byId)).join("")}</div>
      <div class="links">
        <a href="#/club/runs/${esc(name)}/minutes">Minutes</a>
        ${summary.example || running ? "" : `<button class="btn quiet" id="club-delete">Delete</button>`}
      </div>
    </div>
    ${sections.length ? `<div class="club-sticky">
      <nav class="club-toc">${sections.map(([id, label]) => `<button type="button" data-goto="club-${id}">${label}</button>`).join("")}</nav>
      <div class="club-focus-bar small" hidden></div>
    </div>` : ""}
    ${sections.map(([id, , html]) => `<section class="club-section" id="club-${id}">${html}</section>`).join("")}
    <p class="muted small club-rejected">${quoteCheck(state.rejected)}</p>
  </div>`;

  const root = app.querySelector(".club-page");
  root.querySelectorAll("details[data-key]").forEach((d) => open.has(d.dataset.key) && (d.open = true));
  const showPair = () => {
    root.querySelectorAll(".club-grid td.picked").forEach((td) => td.classList.remove("picked"));
    const p = state.pairs[club.pair];
    if (!p) return;
    root.querySelectorAll(`.club-grid td[data-i="${club.pair}"]`).forEach((td) => td.classList.add("picked"));
    root.querySelector("#club-pair-detail").innerHTML = `<b>${esc(key(p.a))}</b> and <b>${esc(key(p.b))}</b>: <span class="club-rel ${p.relation}">${RELATIONS[p.relation] ?? esc(p.relation)}</span>
      <p>${esc(p.note)}</p>${quote(p.quote_a, byId)}${quote(p.quote_b, byId)}`;
  };
  showPair();
  applyFocus(root, byId);
  root.addEventListener("click", async (e) => {
    const goto = e.target.closest("[data-goto]");
    if (goto) return document.getElementById(goto.dataset.goto)?.scrollIntoView({ behavior: "smooth", block: "start" });
    const paper = e.target.closest("[data-paper]");
    if (paper) {
      club.focus = club.focus === paper.dataset.paper ? null : paper.dataset.paper;
      return applyFocus(root, byId);
    }
    const cell = e.target.closest("td[data-i]");
    if (cell) return ((club.pair = +cell.dataset.i), showPair());
    if (e.target.matches(".club-more")) {
      const clamped = root.querySelector(".club-overview").classList.toggle("clamped");
      return (e.target.textContent = clamped ? "Read the whole overview" : "Show less");
    }
    if (e.target.id === "club-delete") {
      if (e.target.textContent !== "Really delete?") return (e.target.textContent = "Really delete?");
      await api(`/club/runs/${name}`, { method: "DELETE" });
      location.hash = "#/club";
    }
  });
  if (running) clubTimer = setTimeout(() => location.hash === `#/club/runs/${name}` && clubRun(name), POLL_MS);
}

// Clicking a paper anywhere dims everything that doesn't involve it; clicking it again (or "Show everything") undoes it.
function applyFocus(root, byId) {
  const f = club.focus;
  root.classList.toggle("club-focusing", !!f);
  root.querySelectorAll("[data-papers]").forEach((el) => el.classList.toggle("club-hit", !!f && el.dataset.papers.split(" ").includes(f)));
  root.querySelectorAll("[data-paper]").forEach((el) => el.classList.toggle("on", el.dataset.paper === f));
  const bar = root.querySelector(".club-focus-bar");
  if (!bar) return;
  bar.hidden = !f;
  bar.innerHTML = f ? `<span>Showing what involves <b>${esc(byId[f]?.citekey ?? f)}</b>: ${esc(byId[f]?.title ?? "")}</span><button type="button" class="btn quiet" data-paper="${esc(f)}">Show everything</button>` : "";
}

function stepsStrip(steps, p) {
  const items = steps
    .filter((s) => STEPS[s.name]) // a backtest's baseline and judge steps aren't shown
    .map((s) => {
      const count = s.status === "running" && p?.step === s.name && p.total > 1 ? `${p.done}/${p.total}` : s.status === "done" && COUNTED.has(s.name) ? s.count : "";
      return `<li class="${s.status}" title="${s.reused ? "rebuilt from the archive, no new calls" : s.status}"><span>${STEPS[s.name]}</span>${count !== "" ? `<b>${count}</b>` : ""}${s.status === "done" ? "<i>✓</i>" : ""}</li>`;
    });
  return `<ol class="club-steps">${items.join("")}</ol>`;
}

function chip(id, byId) {
  const c = byId[id];
  return `<button type="button" class="club-chip" data-paper="${esc(id)}" title="${esc(c?.title ?? "")}">${esc(c?.citekey ?? id)}${c?.year ? `<i>${esc(c.year)}</i>` : ""}</button>`;
}

const paperIds = (qs) => esc([...new Set((qs ?? []).map((q) => q.paper_id))].join(" "));

function quote(q, byId) {
  if (!q) return "";
  return `<blockquote class="club-quote">“${esc(q.text)}” <span class="muted small">(${esc(byId[q.paper_id]?.citekey ?? q.paper_id)}, ${esc(q.loc)})</span></blockquote>`;
}

// Quotes fold away under a count, so the claims read as a list first.
function quotes(qs, byId, k) {
  if (!qs?.length) return "";
  return `<details class="club-quotes" data-key="${esc(k)}"><summary class="small">${qs.length} quote${qs.length > 1 ? "s" : ""}</summary>${qs.map((q) => quote(q, byId)).join("")}</details>`;
}

function overviewSection(s, byId) {
  if (!s) return "";
  const groups = Object.entries(POINT_KINDS).map(([kind, label]) => [label, s.key_points.filter((k) => k.kind === kind)]).filter(([, ks]) => ks.length);
  return `<h2 class="hand">Overview</h2>
    <p class="club-overview clamped">${esc(s.overview)}</p>
    <button type="button" class="club-more small">Read the whole overview</button>
    ${groups.map(([label, ks]) => `<div class="club-points"><h4 class="hand">${label}</h4>${ks.map((k, i) => `<div class="club-point" data-papers="${paperIds(k.quotes)}">${esc(k.text)}${quotes(k.quotes, byId, `point-${label}-${i}`)}</div>`).join("")}</div>`).join("")}`;
}

function pairMap(pairs, cards, key) {
  if (!pairs.length) return "";
  const ids = cards.map((c) => c.id);
  const at = {};
  pairs.forEach((p, i) => ((at[`${p.a}|${p.b}`] = i), (at[`${p.b}|${p.a}`] = i)));
  const counts = Object.fromEntries(Object.keys(RELATIONS).map((r) => [r, pairs.filter((p) => p.relation === r).length]));
  const cell = (a, b) => {
    if (a === b) return `<td class="self"></td>`;
    const i = at[`${a}|${b}`];
    if (i == null) return `<td class="pending"></td>`;
    const rel = pairs[i].relation;
    return `<td class="${rel}" data-i="${i}" data-papers="${esc(a)} ${esc(b)}" title="${esc(key(a))} · ${esc(key(b))}: ${RELATIONS[rel]}"></td>`;
  };
  return `<h2 class="hand">Pair map</h2>
    <p class="muted small">${pairs.length} of ${(ids.length * (ids.length - 1)) / 2} pairs · ${Object.entries(counts).map(([r, n]) => `<span class="club-rel ${r}">${RELATIONS[r]} ${n}</span>`).join(" ")} · click a cell for the note and quotes, a name to follow one paper</p>
    <div class="club-grid-wrap"><table class="club-grid">
      <tr><th></th>${ids.map((id) => `<th data-paper="${esc(id)}"><span>${esc(key(id))}</span></th>`).join("")}</tr>
      ${ids.map((a) => `<tr><th data-paper="${esc(a)}">${esc(key(a))}</th>${ids.map((b) => cell(a, b)).join("")}</tr>`).join("")}
    </table></div>
    <div id="club-pair-detail" class="club-pair-detail muted small">Pick a cell.</div>`;
}

function directionsSection(ds, byId) {
  if (!ds.length) return "";
  return `<h2 class="hand">Directions</h2><p class="muted small">Where the club expects the field to go, ranked by the PI's confidence (0 to 1).</p>
    <ol class="club-directions">${ds
      .map(
        (d, i) => `<li data-papers="${esc((d.papers ?? []).join(" "))}">
        <div class="club-dir-text">${esc(d.text)}${d.confidence != null ? `<span class="club-conf" title="PI's confidence">${Number(d.confidence).toFixed(2)}</span>` : ""}</div>
        <div class="club-dir-arc"><span>${esc(d.from_a)}</span> → <span>${esc(d.to_b)}</span></div>
        <div class="muted">because ${esc(d.because)}</div>
        <div class="club-chips">${(d.papers ?? []).map((p) => chip(p, byId)).join("")}</div>
        ${quotes(d.quotes, byId, `direction-${i}`)}
      </li>`,
      )
      .join("")}</ol>`;
}

// Ranked by round 2's round-robin, dropped ones last. Each shows its test and prediction; what its papers said and why
// the PI kept, revised or dropped it fold away under it.
function hypothesesSection(hs, byId, key) {
  if (!hs?.length) return "";
  const alive = hs.filter((r) => r.decision && r.decision !== "drop").length;
  return `<h2 class="hand">Hypotheses</h2><p class="muted small">The club's own ideas, beyond what any one paper says: each rests on quoted premises
    and names the test that would refute it. ${alive > 1 ? `Ranked by ${(alive * (alive - 1)) / 2} head-to-head comparisons by the PI.` : ""}</p>
    <ol class="club-hypotheses">${hs
      .map((r, i) => {
        const h = r.hypothesis;
        const call = r.decision ? `<span class="club-decision ${r.decision}">${DECISIONS[r.decision]}</span>` : `<span class="club-tag">in round 2</span>`;
        const record = r.played ? `<span class="club-conf" title="comparisons won in round 2">won ${r.wins} of ${r.played}</span>` : "";
        const said = (r.critiques ?? [])
          .map((c) => `<li class="${c.verified ? "" : "unverified"}"><b>${esc(key(c.speaker))}</b> <span class="club-stance ${c.stance}">${c.stance}</span> ${esc(c.text)}${c.verified ? "" : ` <span class="club-tag warn">quote not verified</span>`}</li>`)
          .join("");
        return `<li class="${r.decision === "drop" ? "dropped" : ""}" data-papers="${esc((h.papers ?? []).join(" "))}">
          <div class="club-dir-text">${esc(h.text)}${record}</div>
          <div class="club-hyp-meta">${call}<span class="club-tag">${esc(SOURCES[h.source] ?? h.source)}</span></div>
          <dl class="club-hyp">
            <dt>Why</dt><dd>${esc(h.mechanism)}</dd>
            <dt>Test</dt><dd>${esc(h.test)}</dd>
            <dt>Expect</dt><dd>${esc(h.prediction)}</dd>
          </dl>
          <div class="club-chips">${(h.papers ?? []).map((p) => chip(p, byId)).join("")}</div>
          ${quotes(h.quotes, byId, `hypothesis-${h.id}`)}
          ${said || r.reason ? `<details class="club-quotes" data-key="round2-${esc(h.id)}"><summary class="small">Round 2: what the papers said</summary>
            ${r.original ? `<p class="small"><b>Proposed as:</b> ${esc(r.original)}</p>` : ""}
            ${said ? `<ul class="club-turns">${said}</ul>` : ""}
            ${r.reason ? `<p class="small"><b>PI:</b> ${esc(r.reason)}</p>` : ""}</details>` : ""}
        </li>`;
      })
      .join("")}</ol>`;
}

// Closed by default: the summary line says who clashed and how the PI ruled; opening one shows the exchange.
function disputesSection(ds, key) {
  if (!ds.length) return "";
  return `<h2 class="hand">Disputes</h2><p class="muted small">Each clash from the pair map, argued by the two papers' students and called by the PI. Open one for the full exchange.</p>
    ${ds
      .map(
        (d) => `<details class="club-dispute" data-key="dispute-${esc(d.a)}-${esc(d.b)}" data-papers="${esc(d.a)} ${esc(d.b)}">
        <summary><span class="club-dispute-who"><b>${esc(key(d.a))}</b> vs <b>${esc(key(d.b))}</b><span class="club-verdict ${esc(d.verdict)}">${esc(VERDICTS[d.verdict] ?? d.verdict)}</span></span>
          ${d.judge_reason ? `<span class="club-dispute-pi"><b>PI:</b> ${esc(d.judge_reason)}</span>` : ""}</summary>
        <p class="club-claim"><b>The clash.</b> ${esc(d.claim)}</p>
        <ul class="club-turns">${(d.turns ?? []).map((t) => `<li class="${t.verified ? "" : "unverified"}"><b>${esc(key(t.speaker))}</b> ${esc(t.text)}${t.verified ? "" : ` <span class="club-tag warn">quote not verified</span>`}</li>`).join("")}</ul>
      </details>`,
      )
      .join("")}`;
}

function papersSection(cards) {
  if (!cards.length) return "";
  return `<h2 class="hand">Papers</h2><p class="muted small">Click a paper to show only what involves it.</p>
    <ul class="club-papers">${cards
      .map((c) => `<li><button type="button" class="club-paper" data-paper="${esc(c.id)}"><b>${esc(c.citekey)}</b> ${esc(c.title)} <i>${esc(c.year)}</i></button>${c.authors?.length ? `<div class="muted small">${esc(shortAuthors(c.authors))}</div>` : ""}</li>`)
      .join("")}</ul>`;
}

function quoteCheck(r) {
  const failed = [
    [r.quote_rejected, "map quotes rejected"],
    [r.turn_unverified, "debate turns without a verified quote"],
    [r.direction_rejected, "directions dropped for lack of one"],
    [r.hypothesis_rejected, "hypotheses dropped for lack of a verified premise"],
    [r.critique_unverified, "round-2 critiques without a verified quote"],
  ].filter(([n]) => n);
  return `Quote check: every quote on this page was matched word for word against its paper. ${failed.length ? `Failed it: ${failed.map(([n, w]) => `${n} ${w}`).join(", ")}.` : "Nothing failed it."}`;
}

// --- #/club/runs/:name/minutes ---

async function clubMinutes(name) {
  clearTimeout(clubTimer);
  const res = await fetch(`/club/runs/${name}/minutes`);
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `${res.status} ${res.statusText}`);
  app.innerHTML = `<div class="club-head links"><a class="small" href="#/club/runs/${esc(name)}">← ${esc(name)}</a>
      <a class="small" href="/club/runs/${esc(name)}/minutes" download="${esc(name)}-minutes.md">Download as markdown</a></div>
    <article class="club-minutes">${renderMinutes(await res.text())}</article>`;
}

// Just the markdown the minutes use (journal_club/minutes.py): headings, - and 1. lists with indented lines and
// > quotes under an item, paragraphs, **bold**.
function renderMinutes(md) {
  const out = [];
  let list = null;
  const close = () => list && (out.push(`</li></${list}>`), (list = null));
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  for (const line of md.split("\n")) {
    let m;
    if (!line.trim()) continue;
    if ((m = line.match(/^(#{1,3}) (.*)$/))) {
      close();
      out.push(`<h${m[1].length} class="hand">${inline(m[2])}</h${m[1].length}>`);
    } else if ((m = line.match(/^(-|\d+\.) (.*)$/))) {
      const kind = m[1] === "-" ? "ul" : "ol";
      if (list === kind) {
        out.push("</li>");
      } else {
        close();
        out.push(`<${kind}>`);
        list = kind;
      }
      out.push(kind === "ol" ? `<li value="${parseInt(m[1], 10)}">` : "<li>", inline(m[2]));
    } else if ((m = line.match(/^\s*> ?(.*)$/))) {
      out.push(`<blockquote class="club-quote">${inline(m[1])}</blockquote>`);
    } else if (list && /^\s/.test(line)) {
      out.push(`<div>${inline(line.trim())}</div>`);
    } else {
      close();
      out.push(`<p>${inline(line)}</p>`);
    }
  }
  close();
  return out.join("");
}
