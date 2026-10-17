// For you: the latest arXiv listing ranked for you by arxiv-feed (backend/app/feed.py), as a quick daily triage.
// Each top pick gets a short summary: what the paper does and why you'd care, given your own papers
// (backend/app/pitch.py). Sorting a paper (Add to library, More like this, Not for me) trains the ranking and counts
// toward a daily goal; meeting it on consecutive listing days builds a streak. Keys: j/k move, a/m/n sort, o opens.
//   #/for-you              the latest listing day
//   #/for-you/2026-10-15   a given day

const PICKS = 5; // shown in full with a summary; the rest of the day is a compact list
const JSON_HEADERS = { "Content-Type": "application/json" };
const ORDER = {
  model: "ranked by what you’ve liked, opened and saved",
  popular: "ordered by what other readers liked",
  newest: "newest first",
};

async function forYou(day) {
  let feed;
  try {
    feed = await api(day ? `/feed?date=${day}` : "/feed");
  } catch (e) {
    if (e.status !== 503) throw e;
    return feedSetup(e.detail ?? {});
  }
  if (!feed.day) {
    app.innerHTML = `<section class="fy-setup"><h1>No papers yet</h1>
      <p>arxiv-feed hasn't fetched any papers in ${esc(feed.categories.join(", "))}. Run <code>uv run arxiv-feed ingest</code> in the arxiv-feed folder, then reload.</p></section>`;
    return;
  }

  const ranked = feed.method === "model";
  const picks = ranked ? feed.papers.slice(0, PICKS) : [];
  const rest = ranked ? feed.papers.slice(PICKS) : feed.papers;
  const list = ranked ? "ol" : "ul";
  const state = {
    weekday: dateLabel(feed.day, { weekday: "long" }),
    ranked,
    progress: feed.progress,
    learning: feed.learning,
    papers: new Map(feed.papers.map((p) => [p.id, p])),
    summaries: true, // false once we know they can't be written (no API key, or an error)
  };

  app.innerHTML = `
    <div class="fy${ranked ? " ranked" : ""}">
      <header class="fy-head">
        <h1>${dateLabel(feed.day, { weekday: "long", day: "numeric", month: "long" })}</h1>
        <nav class="fy-days" aria-label="Listing day">
          ${feed.older ? `<a href="#/for-you/${feed.older}" rel="prev"><span aria-hidden="true">‹</span> ${dateLabel(feed.older)}</a>` : ""}
          ${feed.newer ? `<a href="#/for-you/${feed.newer}" rel="next">${dateLabel(feed.newer)} <span aria-hidden="true">›</span></a>` : ""}
        </nav>
        <p class="fy-sub">${feed.papers.length} papers in ${esc(feed.categories.join(", "))}, ${ORDER[feed.method]}.</p>
      </header>
      <section class="fy-goal" aria-live="polite"></section>
      <p class="fy-notice" hidden></p>
      ${picks.length ? `<ol class="fy-picks">${picks.map((p) => paperEntry(p, true)).join("")}</ol>` : ""}
      ${rest.length && picks.length ? `<h2 class="fy-rest">The rest of ${state.weekday}’s listing</h2>` : ""}
      ${rest.length ? `<${list} class="fy-list">${rest.map((p) => paperEntry(p, false)).join("")}</${list}>` : ""}
    </div>`;

  const root = app.querySelector(".fy");
  root.state = state;
  renderGoal(root);
  root.addEventListener("click", (e) => onClick(root, e));
  window.MathJax?.typesetPromise?.([root]);
  loadSummaries(root, picks);
}

// --- rendering ---

function paperEntry(p, full) {
  const meta = [p.categories.join(", "), p.comment].filter(Boolean).map(esc).join('<span class="sep"></span>');
  return `
    <li class="fy-paper ${full ? "pick" : "brief"}${sortedClass(p)}" data-id="${esc(p.id)}">
      ${p.score != null ? `<span class="fy-rank" aria-hidden="true">${p.rank}</span>` : ""}
      <div class="fy-body">
        <p class="fy-status">${statusText(p)}</p>
        <h3 class="fy-title"><a href="${esc(p.abs_url)}" target="_blank" rel="noopener" data-click>${esc(p.title)}</a></h3>
        <p class="fy-authors">${esc(authorLine(p.authors))}</p>
        <p class="fy-meta">${meta}</p>
        <div class="fy-summary"${full ? "" : " hidden"}></div>
        <div class="fy-abstract" hidden>${esc(p.abstract)}</div>
        <div class="fy-actions">
          ${full ? "" : `<button type="button" class="fy-btn fy-toggle" data-show="summary" aria-expanded="false">Summary</button>`}
          ${libraryControl(p)}
          <button type="button" class="fy-btn fy-thumb" data-kind="up" aria-pressed="${p.feedback === "up"}">${thumbLabel(p, "up")}<kbd>M</kbd></button>
          <button type="button" class="fy-btn fy-thumb" data-kind="down" aria-pressed="${p.feedback === "down"}">${thumbLabel(p, "down")}<kbd>N</kbd></button>
          <span class="fy-links">
            ${full ? `<button type="button" class="fy-toggle" data-show="abstract" aria-expanded="false">Abstract</button>` : ""}
            <a href="${esc(p.abs_url)}" target="_blank" rel="noopener" data-click>arXiv</a>
            <a href="${esc(p.pdf_url)}" target="_blank" rel="noopener" data-click>PDF</a>
          </span>
          ${full && p.score != null ? `<span class="fy-score" title="Your model's ranking score for this paper, 0 to 1">${p.score.toFixed(2)}</span>` : ""}
        </div>
        <p class="fy-error" role="alert" hidden></p>
      </div>
    </li>`;
}

function libraryControl(p) {
  return p.library_id
    ? `<a class="fy-read" href="#/papers/${p.library_id}">Read in library</a>`
    : `<button type="button" class="fy-btn fy-primary fy-add">Add to library<kbd>A</kbd></button>`;
}

// A paper is sorted once you've said something about it: more like this, not for me, or saved to the library.
function sortedClass(p) {
  return (p.feedback || p.library_id ? " sorted" : "") + (p.feedback === "down" ? " dismissed" : "");
}

function statusText(p) {
  if (p.feedback === "down") return "Not for me";
  if (p.library_id) return "In your library";
  return p.feedback === "up" ? "More like this" : "";
}

// On a sorted paper, the pressed button undoes it.
function thumbLabel(p, kind) {
  return p.feedback === kind ? "Undo" : kind === "up" ? "More like this" : "Not for me";
}

function refresh(li, p) {
  li.classList.toggle("sorted", Boolean(p.feedback || p.library_id));
  li.classList.toggle("dismissed", p.feedback === "down");
  li.querySelector(".fy-status").textContent = statusText(p);
  li.querySelectorAll(".fy-thumb").forEach((b) => {
    b.setAttribute("aria-pressed", p.feedback === b.dataset.kind);
    b.firstChild.textContent = thumbLabel(p, b.dataset.kind);
  });
}

// The daily goal: sort a few of the day's papers. Meeting it on consecutive listing days builds a streak.
function renderGoal(root, celebrate = false) {
  const { progress, learning, ranked, weekday } = root.state;
  const { goal, streak } = progress;
  const sorted = Math.min(progress.sorted, goal);
  const done = goal > 0 && sorted >= goal;
  const segments = Array.from({ length: goal }, (_, i) => `<span class="fy-seg${i < sorted ? " on" : ""}" style="--i: ${i}"></span>`).join("");
  let hint;
  if (done) hint = `${weekday} is sorted. New papers arrive with the next arXiv listing.`;
  else if (streak) hint = `Sort ${goal - sorted} more of ${weekday}’s papers to keep your ${streak}-day streak going.`;
  else hint = `Sort ${goal - sorted} of ${weekday}’s papers to start a streak.`;
  let unlock = "";
  if (!ranked && learning.use_ml) {
    unlock =
      learning.positives >= learning.needed
        ? `<p class="fy-unlock">Your ranking is ready. <button type="button" class="fy-btn fy-primary" data-rerank>Rank this list for me</button></p>`
        : `<p class="fy-unlock">Mark ${learning.needed - learning.positives} more as <b>More like this</b> to rank this list by your interests.</p>`;
  }
  const goalEl = root.querySelector(".fy-goal");
  goalEl.className = `fy-goal${done ? " done" : ""}${celebrate ? " celebrate" : ""}`;
  goalEl.innerHTML = `
    <div class="fy-goal-row">
      <span class="fy-segs" role="img" aria-label="${sorted} of ${goal} sorted">${segments}</span>
      <span class="fy-count">${done ? `${weekday} done` : `${sorted} of ${goal} sorted`}</span>
      <span class="fy-streak${streak ? "" : " none"}">${FLAME}${streak ? `${streak}-day streak` : "No streak yet"}</span>
    </div>
    <p class="fy-hint">${hint}</p>
    <p class="fy-keys">Keys: <kbd>J</kbd> <kbd>K</kbd> move, <kbd>A</kbd> add to library, <kbd>M</kbd> more like this, <kbd>N</kbd> not for me, <kbd>O</kbd> open</p>
    ${unlock}`;
  goalEl.querySelector("[data-rerank]")?.addEventListener("click", route);
}

const FLAME = `<svg class="fy-flame" viewBox="0 0 16 20" aria-hidden="true"><path d="M8.6 1c.7 3.4 4.9 5.5 4.9 10.6A5.5 5.5 0 0 1 2.5 12.3c0-2.6 1.4-4.3 2.6-5.5.2 1.5.8 2.6 1.8 3.2C7.3 7 7.4 3.8 8.6 1Z"/></svg>`;

function updateProgress(root, res) {
  const before = root.state.progress;
  root.state.progress = res.progress;
  root.state.learning = res.learning;
  renderGoal(root, before.sorted < before.goal && res.progress.sorted >= res.progress.goal);
}

// --- summaries ---

async function loadSummaries(root, papers) {
  if (!papers.length) return;
  papers.forEach((p) => showSummary(root, p, "loading"));
  try {
    const body = JSON.stringify({ papers: papers.map(({ id, title, abstract, reasons }) => ({ id, title, abstract, reasons })) });
    const found = await api("/feed/summaries", { method: "POST", headers: JSON_HEADERS, body });
    papers.forEach((p) => showSummary(root, p, found[p.id] ?? null));
  } catch (e) {
    root.state.summaries = false;
    const notice = root.querySelector(".fy-notice");
    notice.textContent =
      e.detail?.reason === "no_key"
        ? "Summaries need ANTHROPIC_API_KEY in backend/.env. Showing abstracts until then."
        : `Couldn't write summaries (${e.message}). Showing abstracts instead.`;
    notice.hidden = false;
    root.querySelectorAll('.fy-toggle[data-show="summary"]').forEach((b) => (b.textContent = "Abstract"));
    papers.forEach((p) => showSummary(root, p, null));
  }
}

function showSummary(root, p, pitch) {
  const box = root.querySelector(`.fy-paper[data-id="${CSS.escape(p.id)}"] .fy-summary`);
  if (!box) return;
  box.classList.toggle("loading", pitch === "loading");
  box.classList.toggle("fallback", pitch === null);
  if (pitch === "loading") box.innerHTML = `<p>Summarising for you</p>`;
  else if (pitch) box.innerHTML = `<p class="fy-what"><b>What it does</b> ${esc(pitch.what)}</p><p class="fy-why"><b>Why you’d care</b> ${esc(pitch.why)}</p>`;
  else box.innerHTML = `<p>${esc(p.abstract)}</p>`;
  if (pitch !== "loading") box.dataset.ready = "";
  window.MathJax?.typesetPromise?.([box]);
}

// --- actions ---

async function onClick(root, e) {
  const li = e.target.closest(".fy-paper");
  const p = li && root.state.papers.get(li.dataset.id);
  if (!p) return;
  const fromKeys = !e.isTrusted; // forYouKeys sorts by calling .click(); then move on to the next paper
  if (e.target.closest("a[data-click]")) {
    // Opening a paper counts as interest, as on arxiv-feed. keepalive lets it finish while the tab opens.
    fetch(`/feed/${p.id}/feedback`, { method: "POST", keepalive: true, headers: JSON_HEADERS, body: '{"kind":"click"}' });
  } else if (e.target.closest(".fy-thumb")) {
    const kind = e.target.closest(".fy-thumb").dataset.kind;
    await sendFeedback(root, li, p, p.feedback === kind ? "none" : kind, fromKeys);
  } else if (e.target.closest(".fy-add")) {
    await addToLibrary(root, li, p, fromKeys);
  } else if (e.target.closest(".fy-toggle")) {
    toggle(root, li, p, e.target.closest(".fy-toggle"));
  }
}

async function sendFeedback(root, li, p, kind, moveOn = false) {
  const before = p.feedback;
  p.feedback = kind === "none" ? null : kind; // optimistic; reverted if arxiv-feed refuses
  refresh(li, p);
  try {
    const res = await api(`/feed/${p.id}/feedback`, { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ kind }) });
    p.feedback = res.feedback;
    refresh(li, p);
    updateProgress(root, res);
    if (moveOn && kind !== "none") moveCurrent(root, 1);
  } catch (err) {
    p.feedback = before;
    refresh(li, p);
    flashError(li, `Couldn't save that: ${err.message}`);
  }
}

async function addToLibrary(root, li, p, moveOn) {
  const button = li.querySelector(".fy-add");
  button.disabled = true;
  button.classList.add("busy");
  button.firstChild.textContent = "Adding to library…";
  li.querySelector(".fy-error").hidden = true;
  try {
    // The same route the extension uses; arXiv's metadata goes along as the page's meta tags would.
    const meta = {
      citation_title: [p.title],
      citation_author: p.authors,
      citation_arxiv_id: [p.id],
      citation_pdf_url: [p.pdf_url],
      citation_date: [p.published.slice(0, 10)],
      ...(p.doi ? { citation_doi: [p.doi] } : {}),
    };
    const saved = await api("/papers", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ url: p.abs_url, meta }) });
    p.library_id = saved.id;
    button.outerHTML = libraryControl(p);
    // The backend tells arxiv-feed too; asking here as well gets the new goal progress back.
    await sendFeedback(root, li, p, "up", moveOn);
  } catch (e) {
    button.disabled = false;
    button.classList.remove("busy");
    button.firstChild.textContent = "Add to library";
    flashError(li, `Couldn't add this paper: ${e.message}`);
  }
}

// Summary / Abstract buttons: show or hide that part, writing a compact row's summary on first open.
function toggle(root, li, p, button) {
  const wantsSummary = button.dataset.show === "summary" && root.state.summaries;
  const box = li.querySelector(wantsSummary ? ".fy-summary" : ".fy-abstract");
  box.hidden = !box.hidden;
  button.setAttribute("aria-expanded", !box.hidden);
  if (wantsSummary && !box.hidden && !("ready" in box.dataset)) loadSummaries(root, [p]);
  if (!wantsSummary) window.MathJax?.typesetPromise?.([box]);
}

function flashError(li, message) {
  const el = li.querySelector(".fy-error");
  el.textContent = message;
  el.hidden = false;
}

// --- keyboard triage: j/k move, a add to library, m more like this, n not for me, o open on arXiv ---

function moveCurrent(root, step) {
  const cards = [...root.querySelectorAll(".fy-paper")];
  const i = cards.findIndex((c) => c.classList.contains("current"));
  // Moving on after sorting skips papers that are already sorted.
  let j = i + step;
  if (step > 0 && i >= 0) while (j < cards.length - 1 && cards[j].classList.contains("sorted")) j++;
  const next = cards[Math.max(0, Math.min(j, cards.length - 1))];
  cards.forEach((c) => c.classList.toggle("current", c === next));
  next.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

document.addEventListener("keydown", (e) => {
  const root = document.querySelector(".fy");
  if (!root || e.metaKey || e.ctrlKey || e.altKey || e.target.closest("input, textarea, select, [contenteditable]")) return;
  const key = e.key.toLowerCase();
  if (key === "j" || key === "k") {
    e.preventDefault();
    return moveCurrent(root, key === "j" ? 1 : -1);
  }
  const card = root.querySelector(".fy-paper.current");
  const target = card && { a: ".fy-add", m: '.fy-thumb[data-kind="up"]', n: '.fy-thumb[data-kind="down"]', o: ".fy-title a" }[key];
  if (target) card.querySelector(target)?.click();
});

// --- setup and error states ---

// Shown when the backend can't get recommendations (503 from /feed): what's wrong and how to fix it.
function feedSetup({ reason, message }) {
  const steps = `
    <ol class="fy-steps">
      <li>Start arxiv-feed: in its folder, run <code>uv run arxiv-feed run --port 5055</code></li>
      <li>Create a token for your account: <code>uv run arxiv-feed token --email you@example.com</code></li>
      <li>Add both to <code>backend/.env</code> and restart the backend:
        <pre>ARXIV_FEED_URL=http://127.0.0.1:5055\nARXIV_FEED_TOKEN=…</pre></li>
    </ol>`;
  const body = {
    not_configured: `<p>For you shows each day’s arXiv papers ranked by your arxiv-feed model. Connect it in three steps:</p>${steps}`,
    unreachable: `<p>${esc(message)} Start it with <code>uv run arxiv-feed run --port 5055</code> in the arxiv-feed folder.</p>`,
    rejected: `<p>${esc(message)} Create a new one with <code>uv run arxiv-feed token --email you@example.com</code>, put it in <code>backend/.env</code> and restart the backend.</p>`,
  }[reason] ?? `<p>${esc(message ?? "arxiv-feed returned an error.")}</p>`;
  app.innerHTML = `<section class="fy-setup">
      <h1>${reason === "not_configured" ? "Connect arxiv-feed" : "Recommendations are unavailable"}</h1>
      ${body}
      <button type="button" class="fy-btn fy-primary" id="fy-retry">Check again</button>
    </section>`;
  app.querySelector("#fy-retry").onclick = route;
}

// --- text helpers ---

function authorLine(names) {
  return names.length > 6 ? `${names.slice(0, 5).join(", ")} and ${names.length - 5} more` : joinAnd(names);
}

function joinAnd(items) {
  return items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)}`;
}

function dateLabel(iso, options = { weekday: "short", day: "numeric", month: "short" }) {
  return new Date(`${iso}T12:00:00`).toLocaleDateString("en-GB", options);
}
