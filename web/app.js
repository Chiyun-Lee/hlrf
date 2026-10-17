// Paper browser: a tiny hash router over the backend API.
//   #/            library of saved papers
//   #/papers/:id  one paper's header and the reader (reader.js)
//   #/me          My learning: what the app has learned about you, your questions and quizzes
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
  [/^#\/me$/, me],
];

async function route() {
  const [re, view] = routes.find(([re]) => re.test(location.hash)) ?? [/$/, notFound];
  closeChat();
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
    app.innerHTML = `<p class="empty">No papers yet!<br>Open one in Chrome and hit <b>Save this paper</b> in the extension.</p>`;
    return;
  }
  app.innerHTML = `<h1 class="hand">Your papers</h1><input type="search" placeholder="Filter by title or author" id="q" /><div id="list"></div>`;
  const list = app.querySelector("#list");
  const render = (q = "") => {
    q = q.toLowerCase();
    list.innerHTML = papers
      .filter((p) => (p.title + p.authors.join(" ")).toLowerCase().includes(q))
      .map(
        (p) => `<div class="paper-card">
          <a href="#/papers/${p.id}"><h2>${esc(p.title)}</h2></a>
          <div class="muted small">${esc(shortAuthors(p.authors))}${p.year ? ` · ${p.year}` : ""}${p.venue ? ` · ${esc(p.venue)}` : ""} · ${p.n_pages} pages</div>
          <button class="btn quiet delete" data-id="${p.id}">Delete</button>
        </div>`,
      )
      .join("");
  };
  app.querySelector("#q").addEventListener("input", (e) => render(e.target.value));
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
        <div class="levels" role="group" aria-label="Notes written for">
          ${Object.entries(LEVELS).map(([key, [name, about]]) => `<button data-level="${key}" title="${esc(about)}" aria-pressed="${key === level}">${name}</button>`).join("")}
        </div>
        <button class="btn" id="toggle-notes">Show originals</button>
        <button class="btn" id="abstract"></button>
        <button class="btn primary" id="quiz">Quiz me ✦</button>
        <button class="btn quiet" id="delete">Delete</button>
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
  const hasAbstract = () => p.abstract_levels.includes(level); // abstracts are made per reading level
  const showButtons = () => {
    abstractButton.textContent = hasAbstract() ? "Graphical abstract" : "Done? Make graphical abstract";
    quizButton.hidden = !hasAbstract();
  };
  showButtons();
  abstractButton.addEventListener("click", () =>
    showAbstract(id, p.title, {
      make: !hasAbstract(),
      onReady: () => (hasAbstract() || p.abstract_levels.push(level), showButtons()),
    }),
  );
  app.querySelector(".levels").addEventListener("click", (e) => {
    const key = e.target.dataset.level;
    if (!key || key === level) return;
    setLevel(key);
    app.querySelectorAll(".levels button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.level === key));
    closeChat();
    toggle.textContent = "Show originals";
    showButtons();
    reloadNotes(doc);
  });
  quizButton.addEventListener("click", () => startQuiz(id));
  app.querySelector("#delete").addEventListener("click", async () => {
    await deletePaper(id);
    location.hash = "#/";
  });
  await renderReader(doc, id, p);
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
  const quizzes = events.filter((e) => e.kind === "quiz");
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
    ${quizzes.map((e) => `<div class="history-quiz"><b>${e.data.right_first_time}/${e.data.total}</b> first time · ${esc(e.paper ?? "(deleted paper)")} <span class="muted small">${esc(e.created.slice(0, 16))}</span>${e.data.missed.length ? `<div class="muted small">Missed: ${e.data.missed.map((m) => esc(m.prompt)).join(" · ")}</div>` : ""}</div>`).join("") || `<p class="muted">No quizzes yet: make a graphical abstract, then Quiz me.</p>`}

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

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `${res.status} ${res.statusText}`);
  return res.status === 204 ? null : res.json();
}

function shortAuthors(names) {
  return names.length > 3 ? `${names[0]} et al.` : names.join(", ");
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
