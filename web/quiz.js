// Duolingo-style quiz (backend/app/quiz.py): one question at a time, pick an option or fill the blank from a word
// bank, Check, get feedback, Continue. Missed questions come back at the end until they're right. After answering,
// "Show me the proof" shows the original paragraph with the key words highlighted, next to the note's summary.

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
  const box = overlay.querySelector(".overlay-box");
  const queue = questions.map(shuffleOptions);
  const total = queue.length;
  const missed = new Set();
  let right = 0;

  const show = () => {
    if (!queue.length) return finish();
    const q = queue[0];
    let picked = null;
    const [before, after] = q.kind === "blank" ? q.prompt.split("___") : [q.prompt, null];
    box.innerHTML = `
      <div class="quiz-top"><div class="quiz-progress"><div style="width:${(100 * right) / total}%"></div></div>
        <button class="close" title="Close">×</button></div>
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
      box.querySelectorAll(".quiz-options button").forEach((b) => {
        b.disabled = true;
        if (+b.dataset.i === q.answer) b.classList.add("right");
        else if (+b.dataset.i === picked) b.classList.add("wrong");
      });
      box.querySelector(".quiz-footer").classList.add(ok ? "ok" : "no");
      box.querySelector(".quiz-feedback").innerHTML = ok
        ? `<b>Nice!</b> ${esc(q.explanation)}`
        : `<b>Not quite: it's “${esc(q.options[q.answer])}”.</b> ${esc(q.explanation)}`;
      if (q.proof) {
        q.proofText ??= api(atLevel(`/papers/${paperId}/proof`), {
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

  const finish = () => {
    const firstTry = total - missed.size;
    // Remember how it went (feeds the learner profile; see the My learning page).
    api(`/papers/${paperId}/quiz/result`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        right_first_time: firstTry,
        total,
        missed: [...missed].map((q) => ({ prompt: q.prompt, answer: q.options[q.answer] })),
      }),
    }).catch(() => {});
    box.innerHTML = `
      <div class="quiz-done">
        <div class="quiz-big">${firstTry === total ? "Flawless!" : firstTry >= total * 0.7 ? "Nicely done!" : "You got there!"}</div>
        <p>${firstTry} of ${total} right first time.</p>
        ${missed.size ? `<p class="muted">Worth another look:</p><ul>${[...missed].map((q) => `<li>${esc(q.prompt)}</li>`).join("")}</ul>` : ""}
        <div class="quiz-actions"><button data-act="again">New quiz</button><button data-act="close">Done</button></div>
      </div>`;
    box.querySelector(".quiz-actions").onclick = (e) => {
      if (e.target.dataset.act === "again") (overlay.remove(), startQuiz(paperId));
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
  const order = q.options.map((_, i) => i).sort(() => Math.random() - 0.5);
  return { ...q, options: order.map((i) => q.options[i]), answer: order.indexOf(q.answer) };
}
