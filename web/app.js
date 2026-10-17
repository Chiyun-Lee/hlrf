// Paper browser: a tiny hash router over the backend API.
//   #/            library of saved papers
//   #/papers/:id  one paper's header and the reader (reader.js)
//   #/for-you     the latest arXiv listing ranked for you (foryou.js)
// To add a view: write a function that renders into `app` and add a route below.

const app = document.getElementById("app");
const MARKS = ["*", "†", "‡", "§", "¶"]; // equal-contribution groups, in order of appearance

const routes = [
  [/^#?\/?$/, library],
  [/^#\/papers\/(\d+)$/, paper],
  [/^#\/for-you(?:\/(\d{4}-\d{2}-\d{2}))?$/, forYou],
];

async function route() {
  const [re, view] = routes.find(([re]) => re.test(location.hash)) ?? [/$/, notFound];
  closeChat();
  closeReview();
  const tab = location.hash.startsWith("#/for-you") ? "for-you" : "library";
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
  if (!papers.length) {
    app.innerHTML = `<p class="muted">No papers yet. Open a paper in Chrome and click <b>Save this paper</b> in the extension.</p>`;
    return;
  }
  app.innerHTML = `
    <div class="library-tools">
      <input type="search" placeholder="Filter by title or author" id="q" />
      <button class="reviewed-filter" id="reviewed" aria-pressed="false"></button>
    </div>
    <div id="list"></div>`;
  const list = app.querySelector("#list");
  const search = app.querySelector("#q");
  const only = app.querySelector("#reviewed"); // show only the papers an agent has reviewed (they have pins)
  const reviews = {}; // agent reviews by paper id (GET /reviews, review.js): the list shows without them
  const reviewed = (p) => p.reviewed || reviews[p.id]?.state === "done";
  try {
    only.setAttribute("aria-pressed", localStorage.getItem("onlyReviewed") === "1");
  } catch {} // storage blocked: start with every paper
  const render = () => {
    const q = search.value.toLowerCase();
    const onlyReviewed = only.getAttribute("aria-pressed") === "true";
    only.textContent = `AI reviewed · ${papers.filter(reviewed).length}`;
    const shown = papers.filter((p) => (p.title + p.authors.join(" ")).toLowerCase().includes(q) && (!onlyReviewed || reviewed(p)));
    list.innerHTML = shown
      .map(
        (p) => `<div class="paper-card">
          <a href="#/papers/${p.id}"><h2>${esc(p.title)}</h2></a>
          <div class="muted small">${esc(shortAuthors(p.authors))}${p.year ? ` · ${p.year}` : ""}${p.venue ? ` · ${esc(p.venue)}` : ""} · ${p.n_pages} pages${reviewBadge(reviews[p.id], reviewed(p))}</div>
          <button class="delete" data-id="${p.id}">Delete</button>
        </div>`,
      )
      .join("");
    if (!shown.length && onlyReviewed && !q) list.innerHTML = `<p class="muted">No papers reviewed yet. Open one and click <b>Run paper2agent review</b>.</p>`;
  };
  search.addEventListener("input", render);
  only.addEventListener("click", () => {
    const on = only.getAttribute("aria-pressed") !== "true";
    only.setAttribute("aria-pressed", on);
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
}

async function paper(id) {
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
        <a href="${esc(p.url)}" target="_blank">Original</a>
        ${p.doi ? `<a href="https://doi.org/${esc(p.doi)}" target="_blank">DOI ${esc(p.doi)}</a>` : ""}
        ${p.arxiv_id ? `<a href="https://arxiv.org/abs/${esc(p.arxiv_id)}" target="_blank">arXiv ${esc(p.arxiv_id)}</a>` : ""}
        <button class="toggle-notes" id="toggle-notes">Show originals</button>
        <button class="toggle-notes" id="abstract">${p.has_abstract ? "Graphical abstract" : "Done? Make graphical abstract"}</button>
        <button class="toggle-notes quiz-button" id="quiz" ${p.has_abstract ? "" : "hidden"}>Quiz me ✦</button>
        <button class="toggle-notes review-button" id="review">Run paper2agent review</button>
        <button class="delete" id="delete">Delete</button>
      </div>
    </section>
    <article class="doc" id="doc"></article>`;
  const doc = app.querySelector("#doc");
  const toggle = app.querySelector("#toggle-notes");
  toggle.addEventListener("click", () => {
    const on = toggle.textContent === "Show notes";
    setAllNotes(doc, on);
    toggle.textContent = on ? "Show originals" : "Show notes";
  });
  const abstractButton = app.querySelector("#abstract");
  const quizButton = app.querySelector("#quiz");
  abstractButton.addEventListener("click", () =>
    showAbstract(id, p.title, {
      make: !p.has_abstract,
      onReady: () => ((p.has_abstract = true), (abstractButton.textContent = "Graphical abstract"), (quizButton.hidden = false)),
    }),
  );
  quizButton.addEventListener("click", () => startQuiz(id));
  app.querySelector("#delete").addEventListener("click", async () => {
    await deletePaper(id);
    location.hash = "#/";
  });
  setupReview(app.querySelector("#review"), doc, id, p); // paper2agent review in the background (review.js)
  await renderReader(doc, id, p);
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

function shortAuthors(names) {
  return names.length > 3 ? `${names[0]} et al.` : names.join(", ");
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
