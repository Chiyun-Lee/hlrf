// For you: each day's new papers from the arXiv categories and bioRxiv subjects you pick under Sources, ranked for you
// (backend/app/feed.py, ranker.py), as a quick daily triage.
// Every paper gets a short summary, top picks first: what it does and why you'd care, given your own papers
// (backend/app/pitch.py). Sorting a paper (Add to library, More like this, Not for me) trains the ranking and counts
// toward a daily goal; meeting it on consecutive listing days builds a streak. Keys: j/k move, a/m/n sort, o opens.
//   #/for-you              the latest listing day
//   #/for-you/2026-10-15   a given day

const PICKS = 5; // shown large at the top; the rest of the day follows in a tighter list
const SUMMARY_BATCH = 8; // papers per summary request after the picks; batches run in parallel
const JSON_HEADERS = { "Content-Type": "application/json" };
const ORDER = {
  model: "ranked by your papers and what you’ve liked, opened and saved",
  newest: "newest first",
};
let mineFlash = null; // set before re-rendering after an add or remove: keeps Your papers open, with this message
let zoteroFlash = null; // the same for the Zotero library panel
let sourcesFlash = null; // and for Sources
const pitches = new Map(); // paper id → summary already written, so re-ranking the page doesn't blank them

// Re-rank in place after Sources, Your papers or Zotero change: no "Loading…" page or jump to the top, as route() does.
function rerank() {
  return forYou(location.hash.match(/^#\/for-you\/(\d{4}-\d{2}-\d{2})$/)?.[1]);
}

async function forYou(day) {
  let feed;
  typeset(); // start loading MathJax while the feed loads
  try {
    feed = await api(day ? `/feed?day=${day}` : "/feed");
  } catch (e) {
    if (e.status !== 503) throw e;
    app.innerHTML = `<section class="fy-setup"><h1>Papers are unavailable</h1><p>${esc(e.message)}</p>
      <button type="button" class="fy-btn fy-primary" id="fy-retry">Try again</button></section>`;
    app.querySelector("#fy-retry").onclick = route;
    return;
  }
  if (!feed.day) {
    app.innerHTML = `<div class="fy"><section class="fy-setup"><h1>No papers yet</h1>
      <p>There are no recent papers in ${esc(sourceLabel(feed.sources))}. Pick other sources below.</p></section>
      ${sourcesPanel(feed.sources, true)}</div>`;
    wireSources(app.querySelector(".fy"));
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
        <p class="fy-sub">${feed.papers.length} papers in <button type="button" class="fy-sources-link" data-sources title="Change which arXiv and bioRxiv categories you follow">${esc(sourceLabel(feed.sources))}</button>, ${ORDER[feed.method]}.</p>
      </header>
      <section class="fy-goal" aria-live="polite"></section>
      ${sourcesPanel(feed.sources)}
      ${minePanel(feed.mine, feed.profiles)}
      ${zoteroPanel(feed.zotero)}
      <p class="fy-notice"${feed.notice ? "" : " hidden"}>${esc(feed.notice ?? "")}</p>
      ${picks.length ? `<ol class="fy-picks">${picks.map((p) => paperEntry(p, true)).join("")}</ol>` : ""}
      ${rest.length && picks.length ? `<h2 class="fy-rest">The rest of ${state.weekday}’s listing</h2>` : ""}
      ${rest.length ? `<${list} class="fy-list">${rest.map((p) => paperEntry(p, false)).join("")}</${list}>` : ""}
    </div>`;

  const root = app.querySelector(".fy");
  root.state = state;
  renderGoal(root);
  root.addEventListener("click", (e) => onClick(root, e));
  wireSources(root);
  wireMine(root);
  wireZotero(root);
  // The keys act on the selected paper: start on the first one still to sort.
  setCurrent(root, root.querySelector(".fy-paper:not(.sorted)") ?? root.querySelector(".fy-paper"), false);
  typeset(root);
  loadAllSummaries(root, picks, rest);
}

// --- rendering ---

function paperEntry(p, full) {
  const site = p.source === "biorxiv" ? "bioRxiv" : "arXiv";
  const meta = [p.source === "biorxiv" && site, p.categories.join(", "), p.comment].filter(Boolean).map(esc).join('<span class="sep"></span>');
  return `
    <li class="fy-paper ${full ? "pick" : "brief"}${sortedClass(p)}" data-id="${esc(p.id)}">
      ${p.score != null ? `<span class="fy-rank" aria-hidden="true">${p.rank}</span>` : ""}
      <div class="fy-body">
        <p class="fy-status">${statusText(p)}</p>
        <h3 class="fy-title"><a href="${esc(p.abs_url)}" target="_blank" rel="noopener" data-click>${esc(p.title)}</a></h3>
        <p class="fy-authors">${esc(authorLine(p.authors))}</p>
        <p class="fy-meta">${meta}</p>
        <div class="fy-summary"></div>
        <div class="fy-actions">
          ${libraryControl(p)}
          <button type="button" class="fy-btn fy-thumb" data-kind="up" aria-pressed="${p.feedback === "up"}">${thumbLabel(p, "up")}<kbd>M</kbd></button>
          <button type="button" class="fy-btn fy-thumb" data-kind="down" aria-pressed="${p.feedback === "down"}">${thumbLabel(p, "down")}<kbd>N</kbd></button>
          <span class="fy-links">
            <button type="button" class="fy-toggle" aria-expanded="false">Abstract</button>
            <a href="${esc(p.abs_url)}" target="_blank" rel="noopener" data-click>${site}</a>
            <a href="${esc(p.pdf_url)}" target="_blank" rel="noopener" data-click>PDF</a>
          </span>
          ${full && p.score != null ? `<span class="fy-score" title="Your model's ranking score for this paper, 0 to 1">${p.score.toFixed(2)}</span>` : ""}
        </div>
        <div class="fy-abstract" hidden>${esc(p.abstract)}</div>
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
  if (!ranked) {
    unlock =
      learning.positives >= learning.needed
        ? `<p class="fy-unlock">Your ranking is ready. <button type="button" class="fy-btn fy-primary" data-rerank>Rank this list for me</button></p>`
        : `<p class="fy-unlock">Add your papers below, or mark ${learning.needed - learning.positives} more as <b>More like this</b>, to rank this list by your interests.</p>`;
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
  goalEl.querySelector("[data-rerank]")?.addEventListener("click", rerank);
}

const FLAME = `<svg class="fy-flame" viewBox="0 0 16 20" aria-hidden="true"><path d="M8.6 1c.7 3.4 4.9 5.5 4.9 10.6A5.5 5.5 0 0 1 2.5 12.3c0-2.6 1.4-4.3 2.6-5.5.2 1.5.8 2.6 1.8 3.2C7.3 7 7.4 3.8 8.6 1Z"/></svg>`;

function updateProgress(root, res) {
  const before = root.state.progress;
  root.state.progress = res.progress;
  root.state.learning = res.learning;
  renderGoal(root, before.sorted < before.goal && res.progress.sorted >= res.progress.goal);
}

// --- summaries ---

// The picks first, since they're read first; then the rest of the day in parallel batches. Ones already written show at once.
async function loadAllSummaries(root, picks, rest) {
  [...picks, ...rest].filter((p) => pitches.has(p.id)).forEach((p) => showSummary(root, p, pitches.get(p.id)));
  picks = picks.filter((p) => !pitches.has(p.id));
  rest = rest.filter((p) => !pitches.has(p.id));
  rest.forEach((p) => showSummary(root, p, "loading"));
  await loadSummaries(root, picks);
  const batches = [];
  for (let i = 0; i < rest.length; i += SUMMARY_BATCH) batches.push(rest.slice(i, i + SUMMARY_BATCH));
  await Promise.all(batches.map((batch) => loadSummaries(root, batch)));
}

async function loadSummaries(root, papers) {
  if (!papers.length) return;
  if (!root.state.summaries) return papers.forEach((p) => showSummary(root, p, null)); // known to fail; don't ask again
  papers.forEach((p) => showSummary(root, p, "loading"));
  try {
    const body = JSON.stringify({ papers: papers.map(({ id, title, abstract, reasons }) => ({ id, title, abstract, reasons })) });
    const found = await api("/feed/summaries", { method: "POST", headers: JSON_HEADERS, body });
    Object.entries(found).forEach(([id, pitch]) => pitches.set(id, pitch));
    papers.forEach((p) => showSummary(root, p, found[p.id] ?? null));
  } catch (e) {
    root.state.summaries = false;
    const notice = root.querySelector(".fy-notice");
    notice.textContent =
      e.detail?.reason === "no_key"
        ? `${e.message} Showing abstracts until then.`
        : `Couldn't write summaries (${e.message}). Showing abstracts instead.`;
    notice.hidden = false;
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
  typeset(box);
}

// --- actions ---

async function onClick(root, e) {
  const li = e.target.closest(".fy-paper");
  const p = li && root.state.papers.get(li.dataset.id);
  if (!p) return;
  if (e.isTrusted) setCurrent(root, li, false); // the keys act on the paper you last clicked
  const fromKeys = !e.isTrusted; // forYouKeys sorts by calling .click(); then move on to the next paper
  if (e.target.closest("a[data-click]")) {
    // Opening a paper counts as (mild) interest. keepalive lets it finish while the new tab opens.
    fetch(`/feed/${p.id}/feedback`, { method: "POST", keepalive: true, headers: JSON_HEADERS, body: '{"kind":"click"}' });
  } else if (e.target.closest(".fy-thumb")) {
    const kind = e.target.closest(".fy-thumb").dataset.kind;
    await sendFeedback(root, li, p, p.feedback === kind ? "none" : kind, fromKeys);
  } else if (e.target.closest(".fy-add")) {
    await addToLibrary(root, li, p, fromKeys);
  } else if (e.target.closest(".fy-toggle")) {
    const box = li.querySelector(".fy-abstract");
    box.hidden = !box.hidden;
    e.target.closest(".fy-toggle").setAttribute("aria-expanded", !box.hidden);
    typeset(box);
  }
}

async function sendFeedback(root, li, p, kind, moveOn = false) {
  const before = p.feedback;
  p.feedback = kind === "none" ? null : kind; // optimistic; reverted if the backend refuses
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
      ...(p.source === "biorxiv" ? {} : { citation_arxiv_id: [p.id] }),
      citation_pdf_url: [p.pdf_url],
      citation_date: [p.published.slice(0, 10)],
      ...(p.doi ? { citation_doi: [p.doi] } : {}),
    };
    const saved = await api("/papers", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ url: p.abs_url, meta }) });
    p.library_id = saved.id;
    button.outerHTML = libraryControl(p);
    // Library papers already count as liked; this also gets the new goal progress back.
    await sendFeedback(root, li, p, "up", moveOn);
  } catch (e) {
    button.disabled = false;
    button.classList.remove("busy");
    button.firstChild.textContent = "Add to library";
    flashError(li, `Couldn't add this paper: ${e.message}`);
  }
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
  setCurrent(root, cards[Math.max(0, Math.min(j, cards.length - 1))], true);
}

function setCurrent(root, card, scroll) {
  if (!card) return;
  root.querySelectorAll(".fy-paper.current").forEach((c) => c !== card && c.classList.remove("current"));
  card.classList.add("current");
  if (scroll) card.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
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

// --- sources: the arXiv categories and bioRxiv subjects each day's papers come from ---

function sourceLabel(sources) {
  const parts = [];
  if (sources.arxiv.length) parts.push(`${joinAnd(sources.arxiv)} on arXiv`);
  if (sources.biorxiv.length) parts.push(`${joinAnd(sources.biorxiv)} on bioRxiv`);
  return joinAnd(parts);
}

// The checkboxes load when the panel first opens.
function sourcesPanel(sources, open = false) {
  return `
    <details class="fy-mine fy-sources"${open || sourcesFlash !== null ? " open" : ""}>
      <summary>arXiv and bioRxiv categories <span class="fy-mine-count">${sources.arxiv.length + sources.biorxiv.length}</span></summary>
      <p class="fy-mine-help">Pick where each day’s papers come from. A new category brings in its last month of papers, which can take a minute.</p>
      <form class="fy-sources-form">
        <div class="fy-sources-pick"></div>
        <button type="submit" class="fy-btn fy-primary" disabled>Save sources</button>
      </form>
      <p class="fy-mine-msg" role="status">${esc(sourcesFlash ?? "")}</p>
    </details>`;
}

function sourcePicker({ arxiv, biorxiv, selected }) {
  const on = new Set([...selected.arxiv, ...selected.biorxiv]);
  const box = (name, value, label) => `<label><input type="checkbox" name="${name}" value="${esc(value)}"${on.has(value) ? " checked" : ""} /> <span>${label}</span></label>`;
  // arXiv's groups start folded, except those you already follow something in.
  const groups = arxiv.map(
    ({ group, categories }) => `
      <details class="fy-group"${categories.some((c) => on.has(c.code)) ? " open" : ""}>
        <summary>${esc(group)} <span class="fy-group-count"></span></summary>
        <div class="fy-checks">${categories.map((c) => box("arxiv", c.code, `<code>${esc(c.code)}</code> ${esc(c.name)}`)).join("")}</div>
      </details>`,
  );
  return `
    <fieldset><legend>arXiv</legend>${groups.join("")}</fieldset>
    <fieldset><legend>bioRxiv <span class="fy-group-count"></span></legend>
      <div class="fy-checks">${biorxiv.map((s) => box("biorxiv", s, esc(s))).join("")}</div>
    </fieldset>`;
}

// How many are picked in each arXiv group and on bioRxiv, so folded groups still show it.
function countPicked(form) {
  form.querySelectorAll(".fy-group, fieldset").forEach((el) => {
    const count = el.querySelector(":scope > summary .fy-group-count, :scope > legend .fy-group-count");
    const n = el.querySelectorAll("input:checked").length;
    if (count) count.textContent = n ? `${n} picked` : "";
  });
}

function wireSources(root) {
  sourcesFlash = null;
  const panel = root.querySelector(".fy-sources");
  const form = panel.querySelector("form");
  const button = form.querySelector("button");
  const message = panel.querySelector(".fy-mine-msg");
  let loading = null;
  const load = () => {
    if (!panel.open || loading) return;
    loading = api("/feed/sources")
      .then((options) => {
        form.querySelector(".fy-sources-pick").innerHTML = sourcePicker(options);
        countPicked(form);
        button.disabled = false;
      })
      .catch((e) => {
        loading = null; // try again on the next open
        message.textContent = `Couldn’t load the categories: ${e.message}`;
      });
  };
  panel.addEventListener("toggle", load);
  load();
  // The categories named in the header open this panel too.
  root.querySelector("[data-sources]")?.addEventListener("click", () => {
    panel.open = true;
    panel.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  });
  form.addEventListener("change", () => countPicked(form));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const picked = (name) => [...form.querySelectorAll(`input[name="${name}"]:checked`)].map((i) => i.value);
    button.disabled = true;
    message.textContent = "Saving, and fetching papers from anything new…";
    try {
      const body = JSON.stringify({ arxiv: picked("arxiv"), biorxiv: picked("biorxiv") });
      const chosen = await api("/feed/sources", { method: "PUT", headers: JSON_HEADERS, body });
      sourcesFlash = `Saved. Papers now come from ${sourceLabel(chosen)}.`;
      await rerank();
    } catch (err) {
      message.textContent = err.message;
      button.disabled = false;
    }
  });
}

// --- your papers: what the ranking and each "why you'd care" start from ---

function minePanel(mine, profiles) {
  const linked = profiles.length
    ? `<p class="fy-linked">${profiles
        .map((p) => `Linked: <a href="${esc(p.url)}" target="_blank" rel="noopener">your ${esc(p.label)} profile</a>, checked daily for new papers. <button type="button" class="fy-remove" data-unlink="${esc(p.url)}">Unlink</button>`)
        .join("<br>")}</p>`
    : "";
  const list = mine.length
    ? `<ul class="fy-mine-list">${mine
        .map((p) => `<li><span>${esc(p.title)}</span><button type="button" class="fy-remove" data-id="${esc(p.id)}">Remove</button></li>`)
        .join("")}</ul>`
    : "";
  return `
    <details class="fy-mine fy-yours"${mine.length && mineFlash === null ? "" : " open"}>
      <summary>Your papers <span class="fy-mine-count">${mine.length}</span></summary>
      <p class="fy-mine-help">${
        mine.length
          ? "For you ranks each day’s papers and writes “Why you’d care” from these, plus what you like and save."
          : "Paste your INSPIRE profile link and For you loads your papers, then ranks each day’s papers by your work and says why each one matters to you. arXiv ids or links work too."
      }</p>
      ${linked}
      ${list}
      <form class="fy-mine-add">
        <input name="text" placeholder="inspirehep.net/authors/…, or arXiv ids like 2207.01501" aria-label="Your INSPIRE profile link, or arXiv ids" autocomplete="off" />
        <button type="submit" class="fy-btn fy-primary">Add papers</button>
      </form>
      <p class="fy-mine-msg" role="status">${esc(mineFlash ?? "")}</p>
    </details>`;
}

function wireMine(root) {
  mineFlash = null;
  const panel = root.querySelector(".fy-yours");
  const message = panel.querySelector(".fy-mine-msg");
  panel.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const button = e.target.querySelector("button");
    button.disabled = true;
    const text = e.target.text.value;
    message.textContent = /inspirehep/i.test(text) ? "Reading your INSPIRE profile…" : "Looking them up on arXiv…";
    try {
      const res = await api("/feed/mine", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ text }) });
      const notes = [];
      if (res.profile) {
        const off = res.off_arxiv ? `, plus ${res.off_arxiv} that aren’t on arXiv` : "";
        notes.push(`Found ${res.from_profile} of your papers on your ${res.profile} profile${off}. New ones are added each day.`);
      }
      if (res.unknown.length) notes.push(`arXiv doesn’t know ${res.unknown.join(", ")}.`);
      mineFlash = notes.join(" ");
      await rerank(); // with your papers
    } catch (err) {
      message.textContent = err.message;
      button.disabled = false;
    }
  });
  panel.addEventListener("click", async (e) => {
    const button = e.target.closest(".fy-remove");
    if (!button) return;
    if (button.dataset.unlink) {
      await api(`/feed/profiles?url=${encodeURIComponent(button.dataset.unlink)}`, { method: "DELETE" });
      mineFlash = "Unlinked. The papers it added stay; remove any you don’t want.";
    } else {
      await api(`/feed/mine/${button.dataset.id}`, { method: "DELETE" });
      mineFlash = "";
    }
    rerank();
  });
}

// --- your Zotero library: papers you keep count as ones you're interested in ---

function zoteroPanel(z) {
  let status = "";
  if (z?.missing) status = `Can’t read <code>${esc(z.path)}</code> any more (${esc(z.missing)}). Link the export again, or unlink.`;
  else if (z) status = `Linked: <code>${esc(z.path)}</code>, ${z.on_arxiv} of ${z.entries} entries on arXiv, re-read whenever the file changes.`;
  return `
    <details class="fy-mine fy-zotero"${zoteroFlash === null ? "" : " open"}>
      <summary>Zotero library ${z?.on_arxiv != null ? `<span class="fy-mine-count">${z.on_arxiv}</span>` : ""}</summary>
      <p class="fy-mine-help">For you also learns from the papers you keep in Zotero. Export your library as BibTeX (File › Export Library…, or Better BibTeX’s export with “Keep updated” on, so new papers arrive by themselves) and paste the file’s path.</p>
      ${status ? `<p class="fy-linked">${status} <button type="button" class="fy-remove" data-unlink-zotero>Unlink</button></p>` : ""}
      <form class="fy-mine-add">
        <input name="path" placeholder="~/Zotero/My Library.bib" aria-label="Path to your Zotero BibTeX export" autocomplete="off" />
        <button type="submit" class="fy-btn fy-primary">${z ? "Link another" : "Link"}</button>
      </form>
      <p class="fy-mine-msg" role="status">${esc(zoteroFlash ?? "")}</p>
    </details>`;
}

function wireZotero(root) {
  zoteroFlash = null;
  const panel = root.querySelector(".fy-zotero");
  const message = panel.querySelector(".fy-mine-msg");
  panel.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const button = e.target.querySelector("button");
    button.disabled = true;
    message.textContent = "Reading the export and fetching its papers from arXiv…";
    try {
      const res = await api("/feed/zotero", { method: "POST", headers: JSON_HEADERS, body: JSON.stringify({ path: e.target.path.value }) });
      zoteroFlash = `Linked. ${res.on_arxiv} of its ${res.entries} entries are on arXiv and now shape your ranking.`;
      await rerank();
    } catch (err) {
      message.textContent = err.message;
      button.disabled = false;
    }
  });
  panel.querySelector("[data-unlink-zotero]")?.addEventListener("click", async () => {
    await api("/feed/zotero", { method: "DELETE" });
    zoteroFlash = "Unlinked. Your Zotero papers no longer shape the ranking.";
    rerank();
  });
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

// --- maths: arXiv titles and abstracts carry inline LaTeX ($\Lambda$CDM) ---

// MathJax (over 1 MB) loads the first time it's needed rather than with every view; its config is window.MathJax in
// index.html. Typesetting runs one call at a time, as MathJax asks. Without MathJax the LaTeX stays as typed.
const MATHJAX = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-chtml.js";
let maths;

function typeset(...els) {
  maths ??= new Promise((resolve, reject) =>
    document.head.append(Object.assign(document.createElement("script"), { src: MATHJAX, onload: resolve, onerror: reject })),
  ).then(() => MathJax.startup.promise);
  maths = maths.then(() => els.length && MathJax.typesetPromise(els)).catch(() => {});
  return maths;
}
