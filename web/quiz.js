// Duolingo-style quiz (backend/app/quiz.py): one question at a time, pick an option or fill the blank from a word
// bank, Check, get feedback, Continue. Missed questions come back at the end until they're right. After answering,
// "Show me the proof" shows the original paragraph with the key words highlighted, next to the note's summary.
// Answers count towards Revision (revision.js): XP, the daily goal and spaced repetition.

async function startQuiz(paperId) {
  const overlay = openOverlay(`<p class="overlay-status">Writing your quiz…</p>`);
  overlay.classList.add("quiz-overlay");
  let questions;
  try {
    ({ questions } = await api(atLevel(`/papers/${paperId}/quiz`), { method: "POST" }));
  } catch (e) {
    overlay.querySelector(".overlay-status").textContent = `Couldn't make a quiz: ${e.message}`;
    return;
  }
  runQuiz(overlay, questions, { resultUrl: `/papers/${paperId}/quiz/result`, again: () => (overlay.remove(), startQuiz(paperId)) });
}

// One lesson in `overlay`. Each question carries its revision-bank id, paper_id, paper and level (backend
// revision.py), so every answer moves it between spaced-repetition boxes and earns XP. `resultUrl` gets the summary at
// the end (it feeds the learner profile); `again` offers another round; `showPaper` labels questions with their paper
// (reviews mix papers).
function runQuiz(overlay, questions, { resultUrl, again, showPaper = false }) {
  const box = overlay.querySelector(".overlay-box");
  const queue = questions.map(shuffleOptions);
  const total = queue.length;
  const missed = new Set();
  let right = 0;
  let xp = 0;
  let combo = 0;
  let bestCombo = 0;
  let stats = null; // the day's XP, goal and streak, from the latest answer
  const goalBefore = api("/revision").then((r) => r.today >= r.goal, () => true);

  const show = () => {
    if (!queue.length) return finish();
    const q = queue[0];
    let picked = null;
    const [before, after] = q.kind === "blank" ? q.prompt.split("___") : [q.prompt, null];
    box.innerHTML = `
      <div class="quiz-top"><div class="quiz-progress"><div style="width:${(100 * right) / total}%"></div></div>
        <span class="quiz-xp" title="XP this lesson">${xp} XP</span><button class="close" title="Close">×</button></div>
      ${showPaper && q.paper ? `<div class="quiz-paper">${esc(q.paper)}</div>` : ""}
      <div class="quiz-kind">${q.kind === "blank" ? "Fill in the blank" : "Pick the right answer"}</div>
      <div class="quiz-prompt">${esc(before)}${after != null ? `<span class="quiz-slot">&nbsp;</span>${esc(after)}` : ""}</div>
      <div class="quiz-options ${q.kind}">${q.options.map((o, i) => `<button data-i="${i}"><kbd>${i + 1}</kbd>${esc(o)}</button>`).join("")}</div>
      <div class="proof" hidden></div>
      <div class="quiz-footer"><div class="quiz-feedback"></div><button class="quiz-proof" hidden>Show me the proof</button><button class="quiz-go" disabled>Check</button></div>`;
    const go = box.querySelector(".quiz-go");
    const pick = (i) => {
      if (go.textContent !== "Check") return;
      picked = i;
      box.querySelectorAll(".quiz-options button").forEach((b) => b.classList.toggle("picked", +b.dataset.i === i));
      const slot = box.querySelector(".quiz-slot");
      if (slot) slot.textContent = q.options[i];
      go.disabled = false;
    };
    const check = () => {
      const ok = picked === q.answer;
      const firstTry = !missed.has(q);
      box.querySelectorAll(".quiz-options button").forEach((b) => {
        b.disabled = true;
        if (+b.dataset.i === q.answer) b.classList.add("right");
        else if (+b.dataset.i === picked) b.classList.add("wrong");
      });
      combo = ok ? combo + 1 : 0;
      bestCombo = Math.max(bestCombo, combo);
      const feedback = box.querySelector(".quiz-feedback");
      box.querySelector(".quiz-footer").classList.add(ok ? "ok" : "no");
      feedback.innerHTML = ok
        ? `<b>${combo >= 3 ? `${combo} in a row!` : "Nice!"}</b> <span class="quiz-gain"></span> ${esc(q.explanation)}`
        : `<b>Not quite: it's “${esc(q.options[q.answer])}”.</b> ${esc(q.explanation)}`;
      if (q.id != null) {
        api(`/revision/questions/${q.id}/answer`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ correct: ok, first_try: firstTry }),
        }).then((res) => {
          stats = res;
          xp += res.xp;
          box.querySelector(".quiz-xp").textContent = `${xp} XP`;
          const gain = feedback.querySelector(".quiz-gain");
          if (gain && res.xp) gain.textContent = `+${res.xp} XP`;
        }, () => {});
      }
      if (q.proof) {
        q.proofText ??= api(`/papers/${q.paper_id}/proof?level=${q.level}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ proof: q.proof, question: q.prompt, answer: q.options[q.answer], explanation: q.explanation }),
        });
        q.proofText.catch(() => {}); // shown if they ask for it
        const button = box.querySelector(".quiz-proof");
        button.hidden = false;
        button.onclick = () => showProof(box.querySelector(".proof"), button, q.proofText);
      }
      queue.shift();
      if (ok) right++;
      else (missed.add(q), queue.push(q)); // comes back at the end
      go.textContent = "Continue";
    };
    box.querySelector(".quiz-options").onclick = (e) => e.target.closest("button") && pick(+e.target.closest("button").dataset.i);
    go.onclick = () => (go.textContent === "Check" ? check() : show());
    box.querySelector(".close").onclick = () => overlay.remove();
    overlay.tabIndex = -1;
    overlay.focus();
    overlay.onkeydown = (e) => {
      if (/^[1-9]$/.test(e.key) && +e.key <= q.options.length) pick(+e.key - 1);
      if (e.key === "Enter" && !go.disabled) go.click();
    };
  };

  const finish = async () => {
    const firstTry = total - missed.size;
    // Remember how it went (feeds the learner profile; see the My learning page).
    api(resultUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        right_first_time: firstTry,
        total,
        missed: [...missed].map((q) => ({ prompt: q.prompt, answer: q.options[q.answer], paper: q.paper })),
      }),
    }).catch(() => {});
    const goalJustMet = stats && stats.today >= stats.goal && !(await goalBefore);
    box.innerHTML = `
      <div class="quiz-done">
        <div class="quiz-big">${firstTry === total ? "Flawless!" : firstTry >= total * 0.7 ? "Nicely done!" : "You got there!"}</div>
        <div class="quiz-tiles">
          <div class="quiz-tile xp"><span>XP</span><b>+${xp}</b></div>
          <div class="quiz-tile acc"><span>First time</span><b>${Math.round((100 * firstTry) / total)}%</b></div>
          <div class="quiz-tile combo"><span>Best run</span><b>${bestCombo}</b></div>
        </div>
        ${stats ? `
          <div class="quiz-goal">
            <div class="quiz-goal-label">${goalJustMet ? "Daily goal reached!" : "Today's goal"} · ${Math.min(stats.today, stats.goal)}/${stats.goal} XP
              <span class="quiz-streak">${stats.streak} day streak</span></div>
            <div class="quiz-progress"><div style="width:${Math.min(100, (100 * stats.today) / stats.goal)}%"></div></div>
          </div>` : ""}
        ${missed.size ? `<p class="muted">Worth another look:</p><ul>${[...missed].map((q) => `<li>${esc(q.prompt)}</li>`).join("")}</ul>` : ""}
        <div class="quiz-actions">${again ? `<button data-act="again">Another round</button>` : ""}<button data-act="close">Done</button></div>
      </div>`;
    box.querySelector(".quiz-actions").onclick = (e) => {
      if (e.target.dataset.act === "again") again();
      if (e.target.dataset.act === "close") overlay.remove();
    };
  };

  show();
}

async function showProof(el, button, proof) {
  if (!el.hidden) return ((el.hidden = true), (button.textContent = "Show me the proof"));
  el.hidden = false;
  button.textContent = "Hide the proof";
  el.innerHTML = `<div class="proof-label">Finding it in the paper…</div>`;
  try {
    const p = await proof;
    const bullets = p.note.bullets.map((b) => `<li>${esc(b)}</li>`).join("");
    el.innerHTML = `
      <div class="proof-label">From the paper · page ${p.page + 1}</div>
      <p class="proof-text">${highlight(p.paragraph, p.quote)}</p>
      <div class="proof-label">In your notes</div>
      <div class="proof-note">${p.note.heading ? `<div class="note-heading">${esc(p.note.heading)}</div>` : ""}<ul>${bullets}</ul></div>`;
  } catch (e) {
    el.innerHTML = `<div class="proof-label">Couldn't find the proof: ${esc(e.message)}</div>`;
  }
}

// The paragraph with `quote` marked, trimmed to a window around it so the bubble stays small.
function highlight(paragraph, quote, around = 260) {
  const i = quote ? paragraph.indexOf(quote) : -1;
  if (i < 0) return esc(paragraph.length > 2 * around ? `${paragraph.slice(0, 2 * around)}…` : paragraph);
  // Cut at word boundaries.
  let start = Math.max(0, i - around);
  if (start) start = paragraph.indexOf(" ", start) + 1 || start;
  let end = Math.min(paragraph.length, i + quote.length + around);
  if (end < paragraph.length) end = paragraph.lastIndexOf(" ", end) > i + quote.length ? paragraph.lastIndexOf(" ", end) : end;
  return `${start ? "…" : ""}${esc(paragraph.slice(start, i))}<mark>${esc(quote)}</mark>${esc(paragraph.slice(i + quote.length, end))}${end < paragraph.length ? "…" : ""}`;
}

function shuffleOptions(q) {
  const order = q.options.map((_, i) => i);
  for (let i = order.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1)); // Fisher-Yates: every order equally likely
    [order[i], order[j]] = [order[j], order[i]];
  }
  return { ...q, options: order.map((i) => q.options[i]), answer: order.indexOf(q.answer) };
}
