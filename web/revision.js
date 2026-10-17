// Revision (#/revision, backend/app/revision.py): Duolingo-style practice across all your papers. Every quiz question
// you've been given is in a deck with spaced repetition; a review mixes the ones due today across papers. Answers earn
// XP towards a daily goal, and practising on consecutive days builds a streak. Lessons run in quiz.js.

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const STRENGTH_BARS = 5;

async function revisionPage() {
  const r = await api("/revision");
  const total = r.papers.reduce((n, p) => n + p.questions, 0);
  const today = r.week.at(-1).day;
  app.innerHTML = `
    <h1 class="title">Revision</h1>
    <section class="rv-today">
      <div class="rv-streak ${r.streak ? "" : "none"}">${FLAME}<b>${r.streak}</b> day streak</div>
      <div class="rv-goal">
        <div class="rv-goal-label">${r.today >= r.goal ? "Daily goal reached!" : "Today's goal"}<span>${Math.min(r.today, r.goal)} / ${r.goal} XP</span></div>
        <div class="quiz-progress"><div style="width:${Math.min(100, (100 * r.today) / r.goal)}%"></div></div>
      </div>
      <div class="rv-week">${r.week
        .map((d) => `<div class="rv-day${d.xp ? " on" : ""}${d.day === today ? " today" : ""}" title="${d.xp} XP">
          <i></i><span>${WEEKDAYS[new Date(`${d.day}T12:00`).getDay()]}</span></div>`)
        .join("")}</div>
    </section>
    <section class="rv-start">
      ${
        total
          ? `<button class="quiz-go" id="start-review">${r.due ? `Start review · ${r.due} due` : "Practise anyway"}</button>
             <p class="muted">${r.due ? "Ten questions, mixed across your papers, the ones you're about to forget first." : "Nothing's due: you're all caught up! Practise your weakest questions anyway."}</p>`
          : `<p class="rv-empty">Your revision deck is empty. Take a <b>Quiz me</b> on a paper, or add questions below, and they'll come back here to keep them fresh.</p>`
      }
    </section>
    <h2 class="title">Your papers</h2>
    <div class="rv-papers">${r.papers.map(paperRow).join("") || `<p class="muted">Save a paper with the extension to get started.</p>`}</div>`;

  app.querySelector("#start-review")?.addEventListener("click", () => revise(null));
  app.querySelector(".rv-papers").addEventListener("click", async (e) => {
    const button = e.target.closest("button");
    if (!button) return;
    const id = +button.closest(".rv-paper").dataset.id;
    if (button.dataset.act === "practise") return revise([id]);
    // Add questions: a quiz at the current reading level if the paper has an abstract there, else any it has.
    const p = r.papers.find((p) => p.id === id);
    const lv = p.abstract_levels.includes(level) ? level : p.abstract_levels[0];
    button.disabled = true;
    button.textContent = "Writing questions…";
    try {
      await api(`/papers/${id}/quiz?level=${lv}`, { method: "POST" });
      route();
    } catch (err) {
      button.textContent = `Failed: ${err.message}`;
    }
  });
}

function paperRow(p) {
  const lit = Math.round(p.strength * STRENGTH_BARS);
  const meter = p.questions
    ? `<div class="rv-strength" title="Strength: how far along its questions are">${Array.from({ length: STRENGTH_BARS }, (_, i) => `<i class="${i < lit ? "on" : ""}"></i>`).join("")}</div>`
    : "";
  const action = p.questions
    ? `<button class="btn" data-act="practise">Practise</button>`
    : p.abstract_levels.length
      ? `<button class="btn" data-act="add">Add questions</button>`
      : `<a class="small" href="#/papers/${p.id}">Make its graphical abstract first →</a>`;
  return `<div class="rv-paper" data-id="${p.id}">
      <div class="rv-paper-main">
        <a href="#/papers/${p.id}">${esc(p.title)}</a>
        <div class="muted small">${p.questions ? `${p.questions} questions${p.due ? ` · <b class="rv-due">${p.due} due</b>` : " · all fresh"}` : "No questions yet"}</div>
      </div>
      ${meter}${action}
    </div>`;
}

// A review in a lesson overlay: due questions first, across `paperIds` (null: every paper). Back on the page, the
// stats refresh when the lesson closes.
async function revise(paperIds) {
  const overlay = openOverlay(`<p class="overlay-status">Shuffling your deck…</p>`);
  overlay.classList.add("quiz-overlay");
  new MutationObserver((_, obs) => !overlay.isConnected && (obs.disconnect(), location.hash === "#/revision" && route())).observe(document.body, { childList: true });
  try {
    const { questions } = await api("/revision/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paper_ids: paperIds }),
    });
    if (!questions.length) throw new Error("no questions yet");
    runQuiz(overlay, questions, { resultUrl: "/revision/result", showPaper: true, again: () => (overlay.remove(), revise(paperIds)) });
  } catch (e) {
    overlay.querySelector(".overlay-status").textContent = `Couldn't start a review: ${e.message}`;
  }
}
