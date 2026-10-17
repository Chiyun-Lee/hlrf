// Paper browser: a tiny hash router over the backend API.
//   #/            library of saved papers
//   #/papers/:id  one paper's header and the reader (reader.js)
//   #/for-you     the latest arXiv listing ranked for you (foryou.js)
//   #/revision    Revision: Duolingo-style reviews across papers (revision.js)
//   #/me          My learning: what the app has learned about you, your questions and quizzes
//   #/club        Journal club: paper agents map, debate and propose directions overnight (club.js)
// To add a view: write a function that renders into `app` and add a route below.

const app = document.getElementById("app");
const MARKS = ["*", "†", "‡", "§", "¶"]; // equal-contribution groups, in order of appearance

// Reading levels (backend/app/levels.py): who the notes, graphical abstract and quiz are written for. The choice is
// remembered in this browser.
const LEVELS = {
  outreach: ["Outreach", "For anyone: everyday words and analogies"],
  adjacent: ["Technical", "For technical people from a neighbouring field: its jargon explained, methods kept"],
  expert: ["Expert", "For people in the field: dense, jargon and all"],
};
let level = "outreach";
try {
  if (localStorage.getItem("level") in LEVELS) level = localStorage.getItem("level");
} catch {}
function setLevel(l) {
  level = l;
  try {
    localStorage.setItem("level", l);
  } catch {}
}
// `path` for the API calls that depend on the reading level.
const atLevel = (path) => `${path}?level=${level}`;

const routes = [
  [/^#?\/?$/, library],
  [/^#\/papers\/(\d+)$/, paper],
  [/^#\/for-you(?:\/(\d{4}-\d{2}-\d{2}))?$/, forYou],
  [/^#\/revision$/, revisionPage],
  [/^#\/me$/, me],
  [/^#\/club$/, clubPage],
  [/^#\/club\/runs\/([A-Za-z0-9_-]+)$/, clubRun],
];

async function route() {
  const [re, view] = routes.find(([re]) => re.test(location.hash)) ?? [/$/, notFound];
  closeChat();
  closeReview();
  const tab = location.hash.startsWith("#/for-you") ? "for-you" : location.hash.startsWith("#/club") ? "club" : location.hash === "#/me" ? "me" : location.hash === "#/revision" ? "revision" : "library";
  document.querySelectorAll(".tabs a").forEach((a) => a.toggleAttribute("aria-current", a.dataset.tab === tab));
  app.innerHTML = `<p class="muted">Loading…</p>`;
  try {
    await view(...location.hash.match(re).slice(1));
  } catch (e) {
    app.innerHTML = `<p>Couldn't load: ${esc(e.message)}. Is the backend running?</p>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
route();

// --- views ---

async function library() {
  const papers = await api("/papers");
  app.innerHTML = `<h1 class="hand">Your papers</h1>${addPaperForm()}
    ${papers.length ? `<div class="library-tools">
      <input type="search" placeholder="Filter by title or author" id="q" />
      <button class="btn reviewed-filter" id="reviewed" aria-pressed="false"></button>
    </div>
    <div id="list"></div>` : `<p class="empty">No papers yet! Add one above, or hit <b>Save this paper</b> in the Chrome extension.</p>`}`;
  wireAddPaper(app.querySelector(".add-paper"));
  if (!papers.length) return;
  const list = app.querySelector("#list");
  const search = app.querySelector("#q");
  const reviewedToggle = app.querySelector("#reviewed"); // show only the papers an agent has reviewed (they have pins)
  const reviews = {}; // agent reviews by paper id (GET /reviews, review.js): the list shows without them
  const reviewed = (p) => p.reviewed || reviews[p.id]?.state === "done";
  try {
    reviewedToggle.setAttribute("aria-pressed", localStorage.getItem("onlyReviewed") === "1");
  } catch {} // storage blocked: start with every paper
  const render = () => {
    const q = search.value.toLowerCase();
    const onlyReviewed = reviewedToggle.getAttribute("aria-pressed") === "true";
    reviewedToggle.textContent = `AI reviewed · ${papers.filter(reviewed).length}`;
    const shown = papers.filter((p) => (p.title + p.authors.join(" ")).toLowerCase().includes(q) && (!onlyReviewed || reviewed(p)));
    list.innerHTML = shown
      .map(
        (p) => `<div class="paper-card">
          <a href="#/papers/${p.id}"><h2>${esc(p.title)}</h2></a>
          <div class="muted small">${esc(shortAuthors(p.authors))}${p.year ? ` · ${p.year}` : ""}${p.venue ? ` · ${esc(p.venue)}` : ""} · ${p.n_pages} pages${reviewBadge(reviews[p.id], reviewed(p))}</div>
          <button class="btn quiet delete" data-id="${p.id}">Delete</button>
        </div>`,
      )
      .join("");
    if (!shown.length && onlyReviewed && !q) list.innerHTML = `<p class="muted">No papers reviewed yet. Open one and click <b>Run paper2agent review</b>.</p>`;
  };
  search.addEventListener("input", render);
  reviewedToggle.addEventListener("click", () => {
    const on = reviewedToggle.getAttribute("aria-pressed") !== "true";
    reviewedToggle.setAttribute("aria-pressed", on);
    try {
      localStorage.setItem("onlyReviewed", on ? "1" : "");
    } catch {}
    render();
  });
  api("/reviews").then((found) => (Object.assign(reviews, found), render())).catch(() => {}); // just badges if it fails
  list.addEventListener("click", async (e) => {
    if (!e.target.matches(".delete")) return;
    await deletePaper(e.target.dataset.id);
    route();
  });
  render();
  (window.requestIdleCallback ?? setTimeout)(() => preloadReader()); // so a paper opens without waiting for pdf.js
}

// "Add a paper" on the library page: paste a link, or upload a PDF (pick it or drop it on the box), or both: a link
// with a PDF you downloaded keeps the paper's real address while reading your copy (for sites that block downloads).
const MAX_PDF_MB = 60;

function addPaperForm() {
  return `<form class="add-paper">
    <div class="add-row">
      <input name="url" type="text" placeholder="Paste a link: arXiv, DOI, journal or PMC page, or a PDF" aria-label="Paper link" autocomplete="off" />
      <label class="btn add-file">Upload PDF<input name="pdf" type="file" accept="application/pdf,.pdf" hidden /></label>
      <button class="btn primary" type="submit">Add paper</button>
    </div>
    <div class="add-hint muted small">…or drop a PDF here. Site blocking downloads? Download the PDF yourself, then paste its link and upload it together.</div>
    <div class="add-status small" role="status"></div>
  </form>`;
}

function wireAddPaper(form) {
  const status = form.querySelector(".add-status");
  const fileInput = form.querySelector('input[type="file"]');
  let file = null;
  const pick = (f) => {
    if (!f) return;
    if (!/\.pdf$/i.test(f.name) && f.type !== "application/pdf") return (status.textContent = `${f.name} isn't a PDF.`);
    if (f.size > MAX_PDF_MB * 1e6) return (status.textContent = `${f.name} is over ${MAX_PDF_MB} MB.`);
    file = f;
    status.textContent = `Ready: ${f.name} (${(f.size / 1e6).toFixed(1)} MB). Add a link too if you have one, then Add paper.`;
  };
  fileInput.addEventListener("change", () => pick(fileInput.files[0]));
  form.addEventListener("dragover", (e) => (e.preventDefault(), form.classList.add("dragging")));
  form.addEventListener("dragleave", () => form.classList.remove("dragging"));
  form.addEventListener("drop", (e) => (e.preventDefault(), form.classList.remove("dragging"), pick(e.dataTransfer.files[0])));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = form.url.value.trim();
    if (!url && !file) return (status.textContent = "Paste a link or choose a PDF first.");
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true;
    status.textContent = "Reading the paper… (this can take a minute)";
    try {
      const body = { url, meta: {} };
      if (file) body.pdf = await toBase64(file);
      const saved = await api("/papers", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      location.hash = `#/papers/${saved.id}`;
    } catch (err) {
      status.textContent = `Couldn't add it: ${err.message}`;
      button.disabled = false;
    }
  });
}

function toBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result.split(",")[1]); // drop the "data:application/pdf;base64," prefix
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

async function paper(id) {
  preloadReader(id); // pdf.js, the PDF and the handwriting font load while the paper's details do
  const p = await api(`/papers/${id}`);
  const groups = [...new Set(p.authors.map((a) => a.equal_contribution_group).filter((g) => g != null))];
  const authors = p.authors
    .map((a) => {
      const g = groups.indexOf(a.equal_contribution_group);
      const sup = (g >= 0 ? MARKS[g % MARKS.length] : "") + (a.corresponding ? "✉" : "");
      const title = a.affiliations.join("; ");
      return `<span title="${esc(title)}">${esc(a.raw)}${sup ? `<sup>${sup}</sup>` : ""}</span>`;
    })
    .join(", ");

  app.innerHTML = `
    <section class="paper-head">
      <h1>${esc(p.title)}</h1>
      <div class="authors">${authors}</div>
      <div class="muted small">${[p.year, p.venue].filter(Boolean).map(esc).join(" · ")}</div>
      ${p.contribution_notes ? `<div class="notes small muted">${esc(p.contribution_notes)}</div>` : ""}
      <div class="links small">
        ${/^https?:/i.test(p.url) ? `<a href="${esc(p.url)}" target="_blank">Original</a>` : ""}
        ${p.doi ? `<a href="https://doi.org/${esc(p.doi)}" target="_blank">DOI ${esc(p.doi)}</a>` : ""}
        ${p.arxiv_id ? `<a href="https://arxiv.org/abs/${esc(p.arxiv_id)}" target="_blank">arXiv ${esc(p.arxiv_id)}</a>` : ""}
        <div class="levels" role="group" aria-label="Notes written for">
          ${Object.entries(LEVELS).map(([key, [name, about]]) => `<button data-level="${key}" title="${esc(about)}" aria-pressed="${key === level}">${name}</button>`).join("")}
        </div>
        <button class="btn" id="toggle-notes">Show originals</button>
        <button class="btn" id="abstract"></button>
        <button class="btn primary" id="quiz">Quiz me ✦</button>
        ${p.feed_id ? `<button class="btn" id="mine" title="Add to the papers For you ranks each day's arXiv listing by (For you → Your papers)"></button>` : ""}
        <button class="btn review-button" id="review">Run paper2agent review</button>
        <button class="btn quiet" id="delete">Delete</button>
      </div>
    </section>
    <article class="doc" id="doc"></article>`;
  const doc = app.querySelector("#doc");
  // Show originals switches every note off (and keeps notes written later off), leaving the paper as printed with any
  // agent-review pins on it; the choice holds from paper to paper.
  const toggle = app.querySelector("#toggle-notes");
  const showNotes = (on) => {
    setAllNotes(doc, on);
    toggle.textContent = on ? "Show originals" : "Show notes";
    toggle.setAttribute("aria-pressed", String(!on));
  };
  toggle.addEventListener("click", () => {
    const on = doc.classList.contains("originals");
    showNotes(on);
    remember("originals", !on);
  });
  if (recall("originals")) showNotes(false);
  const abstractButton = app.querySelector("#abstract");
  const quizButton = app.querySelector("#quiz");
  const hasAbstract = () => p.abstract_levels.includes(level); // abstracts are made per reading level
  const showButtons = () => {
    abstractButton.textContent = hasAbstract() ? "Graphical abstract & cards" : "Done? Make graphical abstract & cards";
    quizButton.hidden = !hasAbstract();
  };
  showButtons();
  abstractButton.addEventListener("click", () =>
    showAbstract(id, p.title, {
      make: !hasAbstract(),
      hasCards: p.card_levels.includes(level),
      onReady: () => (
        hasAbstract() || p.abstract_levels.push(level), p.card_levels.includes(level) || p.card_levels.push(level), showButtons()
      ),
    }),
  );
  app.querySelector(".levels").addEventListener("click", (e) => {
    const key = e.target.dataset.level;
    if (!key || key === level) return;
    setLevel(key);
    app.querySelectorAll(".levels button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.level === key));
    closeChat();
    showButtons();
    reloadNotes(doc);
  });
  quizButton.addEventListener("click", () => startQuiz(id));
  const mineButton = app.querySelector("#mine");
  if (mineButton) wireYourPapers(mineButton, p);
  app.querySelector("#delete").addEventListener("click", async () => {
    await deletePaper(id);
    location.hash = "#/";
  });
  setupReview(app.querySelector("#review"), doc, id, p); // paper2agent review in the background (review.js)
  await renderReader(doc, id, p);
}

// "+ Rank For you by this" on a paper's page: adds it to (or removes it from) For you's "Your papers", the papers
// the daily arXiv ranking learns from (POST/DELETE /feed/mine).
function wireYourPapers(button, p) {
  const show = () => {
    button.textContent = p.in_your_papers ? "✓ For you ranks by this" : "＋ Rank For you by this";
    button.setAttribute("aria-pressed", p.in_your_papers);
  };
  show();
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      if (p.in_your_papers) await api(`/feed/mine/${p.feed_id}`, { method: "DELETE" });
      else await api("/feed/mine", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: p.feed_id }) });
      p.in_your_papers = !p.in_your_papers;
      show();
    } catch (e) {
      button.textContent = `Couldn't update: ${e.message}`;
    } finally {
      button.disabled = false;
    }
  });
}

const FACT_KINDS = {
  background: "What you know",
  struggle: "Tripped you up",
  strength: "You've got this",
  interest: "You're curious about",
  preference: "How you like it explained",
};

async function me() {
  const { profile, events } = await api("/me");
  const questions = events.filter((e) => e.kind === "question");
  const quizzes = events.filter((e) => e.kind === "quiz" || e.kind === "revision");
  const byPaper = Object.groupBy(questions, (e) => e.paper ?? "(deleted paper)");
  app.innerHTML = `
    <h1 class="hand">My learning</h1>
    <p class="muted">What the tutor has picked up from your questions and quizzes. It uses this to pitch notes, answers and
      quizzes at you. Remove anything that's wrong, or add your own.</p>
    <section class="facts">${Object.entries(FACT_KINDS)
      .map(([kind, label]) => {
        const facts = profile.facts.map((f, i) => ({ ...f, i })).filter((f) => f.kind === kind);
        return `<div class="fact-group"><h3 class="hand">${label}</h3>${
          facts.map((f) => `<div class="fact">${esc(f.text)}<button class="x" data-i="${f.i}" title="Forget this">×</button></div>`).join("") ||
          `<div class="muted small">Nothing yet.</div>`
        }</div>`;
      })
      .join("")}</section>
    <form class="add-fact">
      <select>${Object.entries(FACT_KINDS).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select>
      <input placeholder="Tell the tutor something about you (e.g. I'm a chemist)" />
      <button class="btn primary">Add</button>
    </form>

    <h2 class="hand">Your questions</h2>
    ${Object.entries(byPaper)
      .map(([title, qs]) => `<div class="history-paper"><h3>${qs[0].paper_id && qs[0].paper ? `<a href="#/papers/${qs[0].paper_id}">${esc(title)}</a>` : esc(title)}</h3>${qs
        .map((e) => `<details class="history-q"><summary><q>${esc(e.data.selection.slice(0, 120))}</q> ${esc(e.data.question)}</summary><p>${esc(e.data.answer)}</p></details>`)
        .join("")}</div>`)
      .join("") || `<p class="muted">Highlight anything in a paper and click Ask to start.</p>`}

    <h2 class="hand">Quizzes</h2>
    ${quizzes.map((e) => `<div class="history-quiz"><b>${e.data.right_first_time}/${e.data.total}</b> first time · ${esc(e.kind === "revision" ? "Revision, across papers" : e.paper ?? "(deleted paper)")} <span class="muted small">${esc(e.created.slice(0, 16))}</span>${e.data.missed.length ? `<div class="muted small">Missed: ${e.data.missed.map((m) => esc(m.prompt)).join(" · ")}</div>` : ""}</div>`).join("") || `<p class="muted">No quizzes yet: make a graphical abstract, then Quiz me.</p>`}

    <p class="forget"><button class="btn" id="forget">Forget everything</button></p>`;

  const save = async (facts) => (await api("/me/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ facts }) }), route());
  app.querySelector(".facts").onclick = (e) => e.target.matches(".x") && save(profile.facts.filter((_, i) => i !== +e.target.dataset.i));
  app.querySelector(".add-fact").onsubmit = (e) => {
    e.preventDefault();
    const text = e.target.querySelector("input").value.trim();
    if (text) save([...profile.facts, { kind: e.target.querySelector("select").value, text }]);
  };
  const forget = app.querySelector("#forget");
  forget.onclick = async () => {
    if (forget.textContent !== "Really forget everything?") return (forget.textContent = "Really forget everything?");
    await api("/me", { method: "DELETE" });
    route();
  };
}

function notFound() {
  app.innerHTML = `<p>Page not found. <a href="#/">Back to library</a></p>`;
}

// --- helpers ---

async function deletePaper(id) {
  await api(`/papers/${id}`, { method: "DELETE" });
}

// Errors carry the backend's `detail` (a message, or {reason, message} from the feed routes) and the status.
async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const detail = (await res.json().catch(() => null))?.detail;
    const message = typeof detail === "string" ? detail : detail?.message;
    throw Object.assign(new Error(message ?? `${res.status} ${res.statusText}`), { status: res.status, detail });
  }
  return res.status === 204 ? null : res.json();
}

// A choice kept in this browser (localStorage can be blocked: then it lasts until the page is left).
function remember(key, on) {
  try {
    localStorage.setItem(key, on ? "1" : "");
  } catch {}
}

function recall(key) {
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function shortAuthors(names) {
  return names.length > 3 ? `${names[0]} et al.` : names.join(", ");
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
