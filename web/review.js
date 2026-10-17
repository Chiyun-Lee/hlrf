// Agent review: paper2agent reviews the paper on the backend (POST /papers/:id/review). It turns the paper and its code
// into tools, re-runs the authors' code, tests the claims and writes a review, then pins Data provenance and
// Agent-reviewed concerns on the figures and tables. A full review takes 30 min to 2 h, so it runs in the background:
// the paper's "Agent review" button starts one, and a panel in the corner follows it live (progress, the stages and
// each step the agent takes). The run lives on the server: leaving the paper only stops the checking, and coming back
// picks it up again.

const REVIEW_DEPTHS = {
  full: {
    name: "Full paper2agent review",
    time: "30 min–2 h",
    about: "paper2agent builds tools from the paper and its code, re-runs the authors' code and tests the claims.",
  },
  quick: { name: "Quick review", time: "5–15 min", about: "Reads the paper and its code without running anything." },
};
const REVIEW_POLL = 1500; // ms between status checks while a review runs
const REVIEW_SAY = 20000; // ms: screen readers hear the agent's words at most this often (a new stage at once)
const TOOL_ICON = `<svg class="ev-icon" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 3.5 4.5 6 2 8.5M6.5 9H10"/></svg>`;

let review = null; // the open paper's review: its status, feed and panel; null when no paper is open
let reviewFolded = false; // the panel folded down to a pill, remembered from paper to paper

// Called by the paper view (app.js) with its header button, the reader and the paper.
async function setupReview(button, doc, id, p) {
  closeReview();
  const feed = Object.assign(document.createElement("ol"), { className: "review-feed" });
  feed.setAttribute("aria-label", "The agent's steps");
  const r = (review = { id, doc, p, button, feed, status: null, seen: new Set(), known: 0, stick: true });
  // Follow the newest step unless you've scrolled up to read; then offer a way back down.
  feed.addEventListener("scroll", () => {
    r.stick = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 24;
    r.dock?.querySelector(".review-latest").toggleAttribute("hidden", r.stick);
  });
  button.addEventListener("click", () => {
    if (["new", "done"].includes(buttonState(r))) return r.chooser ? closeChooser(r) : openChooser(r);
    openPanel(r);
    r.dock.querySelector(".review-panel").focus();
  });
  r.ticker = setInterval(() => renderClock(r), 1000);
  await poll(r);
}

// Leaving the paper (app.js route()): stop checking and take the panel down. The review carries on on the server.
function closeReview() {
  if (!review) return;
  clearTimeout(review.timer);
  clearInterval(review.ticker);
  review.dock?.remove();
  review.chooser?.remove();
  review = null;
}

// Asks for the steps we haven't seen yet, and asks again shortly while the review runs and its paper is open.
async function poll(r) {
  clearTimeout(r.timer);
  if (r.busy) return; // one check at a time: the one under way schedules the next
  r.busy = true;
  const s = await api(`/papers/${r.id}/review?after=${r.known}`).catch(() => undefined); // a blip: the next check will tell
  r.busy = false;
  if (r !== review) return; // the paper was closed meanwhile
  if (s !== undefined) update(r, s);
  if (r.status?.state === "running") r.timer = setTimeout(() => poll(r), REVIEW_POLL);
}

// A new status (from GET or POST /papers/:id/review): its new steps go on the feed and the rest is redrawn.
function update(r, s) {
  const was = r.status;
  if (s && was && s.started_at !== was.started_at) resetFeed(r); // a new run, perhaps started in another tab
  r.status = s;
  r.at = Date.now(); // when `elapsed` was measured, for the ticking clock
  if (s) addSteps(r, s, !!was);
  renderButton(r);
  if (s?.state === "running" && !r.dock) openPanel(r, false); // e.g. back on a paper that's being reviewed
  renderPanel(r);
  if (was?.state === "running" && s && s.state !== "running") {
    if (s.state === "done") window.showPins?.(r.doc, r.id, r.p); // the new pins, without a reload
    say(r, headline(s), true);
  }
}

// New steps onto the feed. The server only sends the newest 200, so say so if some went by unseen.
function addSteps(r, s, live) {
  const fresh = (s.events ?? []).filter((e) => !r.seen.has(e.n));
  const missed = s.n_events - r.known - fresh.length;
  r.known = Math.max(r.known, s.n_events);
  if (!fresh.length && !(missed > 0)) return;
  fresh.forEach((e) => r.seen.add(e.n));
  const gap = missed > 0 ? `<li class="ev gap"><span class="ev-t"></span><span class="ev-x">… ${missed} step${missed === 1 ? "" : "s"} not shown</span></li>` : "";
  r.feed.insertAdjacentHTML("beforeend", gap + fresh.map(stepLine).join(""));
  if (r.stick) r.feed.scrollTop = r.feed.scrollHeight;
  if (!live) return; // not the backlog when you open the paper
  const stage = fresh.findLast((e) => e.kind === "stage");
  const words = fresh.findLast((e) => e.kind === "text");
  if (stage) say(r, `Now: ${stage.text}`, true);
  else if (words) say(r, words.text);
}

// One step: a stage starting (a bold divider), a tool call (a quiet one-liner), the agent's words or an error; steps
// from a helper agent are indented under ↳.
function stepLine(e) {
  const text = esc(e.text);
  return `<li class="ev ${esc(e.kind)}${e.sub ? " sub" : ""}"${e.kind === "tool" ? ` title="${text}"` : ""}>
    <span class="ev-t">${clock(e.t)}</span><span class="ev-x">${e.sub ? "↳ " : ""}${e.kind === "tool" ? TOOL_ICON : ""}${text}</span></li>`;
}

function resetFeed(r) {
  r.feed.replaceChildren();
  r.seen.clear();
  r.known = 0;
  r.stick = true;
  r.dock?.querySelector(".review-latest").setAttribute("hidden", "");
}

// The header button mirrors the run: "Reviewing · 42%" with a thin fill along its bottom edge (style.css).
function renderButton(r) {
  const [s, state] = [r.status, buttonState(r)];
  r.button.className = `toggle-notes review-button ${state}`;
  r.button.textContent =
    state === "new" ? "Run paper2agent review" : state === "done" ? "Agent-reviewed ✓" : label(s);
  r.button.style.setProperty("--progress", state === "running" ? s.progress : 0);
}

// What the header button is for: a run to follow (running, failed), or a review to start (new) or run again (done).
// A paper can have pins from a review made elsewhere (p.reviewed), with no run here to show.
function buttonState(r) {
  const s = r.status?.state;
  return s === "running" || s === "failed" ? s : s === "done" || r.p.reviewed ? "done" : "new";
}

// What the header button and the folded panel say.
function label(s) {
  if (s.state === "running") return s.stage ? `Reviewing · ${Math.round(s.progress * 100)}%` : "Starting review…";
  return { done: "Agent-reviewed ✓", failed: "Review failed", stopped: "Review stopped" }[s.state];
}

// The panel's line under the progress bar.
function headline(s) {
  const n = s.stages.length;
  if (s.state === "running") return s.stage ? `Stage ${s.stage} of ${n} · ${s.stages[s.stage - 1]}` : "Starting…";
  if (s.state !== "done") return `${s.state === "failed" ? "Failed" : "Stopped"} after ${took(s.elapsed)}`;
  const pins = s.pins == null ? "" : ` · ${s.pins || "no"} pin${s.pins === 1 ? "" : "s"} on figures and tables`;
  return `Done in ${took(s.elapsed)}${pins}`;
}

// --- the chooser: full or quick ---

// The menu under the header button: the choice of review, and for a reviewed paper what came of it.
function openChooser(r) {
  const s = r.status;
  const again = buttonState(r) === "done";
  const box = (r.chooser = document.createElement("div"));
  box.className = "review-chooser";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-label", again ? "Agent review" : "Start an agent review");
  if (again && s?.state === "done") {
    box.innerHTML = `<div class="review-summary">
      <p class="review-headline">${esc(headline(s))}</p>
      ${s.verdict ? `<p class="review-verdict">${esc(s.verdict)}</p>` : ""}
      <p class="review-links">
        ${s.report ? `<a href="/papers/${r.id}/review/report" target="_blank" rel="noopener">Read the full review</a>` : ""}
        <button type="button" class="review-show">Show what it did</button>
      </p>
    </div>`;
    box.querySelector(".review-show").onclick = () => (closeChooser(r), openPanel(r), r.dock.querySelector(".review-panel").focus());
  } else if (again) {
    box.innerHTML = `<p class="review-summary">This paper's figures and tables already have pins from an agent review.</p>`;
  }
  box.append(depthForm(r, s?.depth ?? "full", () => (closeChooser(r), r.button.focus()), again ? "Run again" : "Start review"));
  document.body.append(box);
  const b = r.button.getBoundingClientRect();
  const left = Math.min(b.right - box.offsetWidth, document.documentElement.clientWidth - box.offsetWidth - 8);
  Object.assign(box.style, { left: `${Math.max(8, left) + scrollX}px`, top: `${b.bottom + scrollY + 6}px` });
  r.button.setAttribute("aria-expanded", "true");
  box.querySelector("input:checked").focus();
}

function closeChooser(r) {
  r.chooser?.remove();
  r.chooser = null;
  r.button.setAttribute("aria-expanded", "false");
}

// Click outside the chooser or press Escape to close it.
document.addEventListener("click", (e) => review?.chooser && !e.target.closest(".review-chooser, .review-button") && closeChooser(review));
document.addEventListener("keydown", (e) => e.key === "Escape" && review?.chooser && (closeChooser(review), review.button.focus()));

// Full or quick, then Start: under the header button, or in the panel to run one again.
function depthForm(r, depth, onCancel, submit = "Start review") {
  const form = document.createElement("form");
  form.className = "review-form";
  form.innerHTML = `
    <fieldset>
      <legend class="review-sr">Kind of review</legend>
      ${Object.entries(REVIEW_DEPTHS)
        .map(
          ([k, d]) => `<label class="review-option">
            <input type="radio" name="depth" value="${k}"${k === depth ? " checked" : ""} />
            <b>${d.name}</b><span class="review-time">${d.time}</span><span class="review-about">${d.about}</span>
          </label>`,
        )
        .join("")}
    </fieldset>
    <p class="review-pins">Both end by pinning Data provenance and Agent-reviewed concerns on every figure and table.</p>
    <p class="review-note">Runs on the backend's Claude. A full review runs the authors' code on this machine.</p>
    <p class="review-error" role="alert" hidden></p>
    <div class="review-actions">
      <button type="button" class="review-btn review-cancel">Cancel</button>
      <button class="review-btn primary">${submit}</button>
    </div>`;
  form.querySelector(".review-cancel").onclick = onCancel;
  form.onsubmit = (e) => (e.preventDefault(), startReview(r, form));
  return form;
}

async function startReview(r, form) {
  const start = form.querySelector(".primary");
  const error = form.querySelector(".review-error");
  start.disabled = true;
  try {
    const s = await api(`/papers/${r.id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ depth: form.elements.depth.value }),
    });
    if (r !== review) return;
    closeChooser(r);
    resetFeed(r);
    reviewFolded = false;
    update(r, s);
    openPanel(r);
    r.dock.querySelector(".review-panel").focus();
    if (s.state === "running") r.timer = setTimeout(() => poll(r), REVIEW_POLL);
  } catch (e) {
    Object.assign(error, { textContent: e.message, hidden: false }); // e.g. no PDF, or a review already running
    start.disabled = false;
    if (e.status === 409) poll(r); // one is under way already: show it
  }
}

// --- the panel in the corner, and the pill it folds into ---

function openPanel(r, unfold = true) {
  if (unfold) reviewFolded = false;
  if (!r.dock) {
    r.dock = document.createElement("div");
    r.dock.innerHTML = `
      <section class="review-panel" aria-labelledby="review-title" tabindex="-1">
        <div class="review-head"><h2 id="review-title"></h2><button class="review-fold"></button></div>
        <div class="review-bar" role="progressbar" aria-label="Review progress" aria-valuemin="0" aria-valuemax="100"><div></div></div>
        <div class="review-now"><span class="review-headline"></span><span class="review-clock"></span></div>
        <div class="review-result"></div>
        <ol class="review-stages" aria-label="Stages"></ol>
        <div class="review-log"><button class="review-latest" hidden>Jump to latest ↓</button></div>
        <div class="review-foot"></div>
      </section>
      <button class="review-pill"><span class="review-pill-label"></span><span class="review-clock"></span></button>
      <div class="review-sr" aria-live="polite"></div>`;
    r.dock.querySelector(".review-log").prepend(r.feed);
    r.dock.querySelector(".review-fold").onclick = () => (r.status?.state === "running" ? fold(r, true) : closePanel(r));
    // On a phone the chat covers the panel (style.css), so the pill makes way for it.
    r.dock.querySelector(".review-pill").onclick = () => (matchMedia("(max-width: 600px)").matches && closeChat(), fold(r, false));
    r.dock.querySelector(".review-latest").onclick = () => (r.feed.scrollTop = r.feed.scrollHeight);
    r.dock.querySelector(".review-foot").onclick = (e) => {
      const stop = e.target.closest(".review-stop");
      if (stop) stopReview(r, stop);
      if (e.target.closest(".review-again")) runAgain(r);
    };
    document.body.append(r.dock);
  }
  renderPanel(r);
  if (r.stick) r.feed.scrollTop = r.feed.scrollHeight;
}

function fold(r, folded) {
  reviewFolded = folded;
  renderPanel(r);
  if (!folded && r.stick) r.feed.scrollTop = r.feed.scrollHeight;
  r.dock.querySelector(folded ? ".review-pill" : ".review-fold").focus();
}

function closePanel(r) {
  r.dock?.remove();
  r.dock = null;
}

function renderPanel(r) {
  const [s, d] = [r.status, r.dock];
  if (!d) return;
  if (!s) return closePanel(r);
  const running = s.state === "running";
  const waiting = running && !s.stage; // until the first stage starts, the bar shimmers instead
  d.className = `review-dock ${s.state}${reviewFolded ? " folded" : ""}`;
  d.style.setProperty("--progress", s.state === "done" ? 1 : s.progress);
  d.querySelector("#review-title").textContent = `Agent review · ${s.depth === "quick" ? "Quick" : "Full"}`;
  const foldButton = d.querySelector(".review-fold");
  foldButton.textContent = running ? "–" : "×";
  foldButton.setAttribute("aria-label", running ? "Fold the review away" : "Close the review");
  foldButton.title = running ? "Fold away (it keeps running)" : "Close";
  const bar = d.querySelector(".review-bar");
  bar.classList.toggle("waiting", waiting);
  if (waiting) bar.removeAttribute("aria-valuenow");
  else bar.setAttribute("aria-valuenow", Math.round((s.state === "done" ? 1 : s.progress) * 100));
  d.querySelector(".review-headline").textContent = headline(s);
  const result = s.state === "done" ? s.verdict && `<p class="review-verdict">${esc(s.verdict)}</p>` : s.error && `<p class="review-error">${esc(s.error)}</p>`;
  setHTML(d.querySelector(".review-result"), result || "");
  setHTML(d.querySelector(".review-stages"), s.stages.map((title, i) => stageLine(s, title, i)).join(""));
  d.querySelector(".review-pill-label").textContent = label(s);
  d.querySelector(".review-pill").setAttribute("aria-label", `Agent review: ${label(s)}. Show the review.`);
  if (d.querySelector(".review-foot").key !== `${s.state} ${s.report}`) renderFoot(r);
  renderClock(r);
}

// Only touch what changed, so the current stage's spinner and any selected text survive each check.
function setHTML(el, html) {
  if (el.html !== html) el.innerHTML = el.html = html;
}

// One stage in the checklist: done ✓, the current one, or still to come.
function stageLine(s, title, i) {
  const at = s.state === "done" || i + 1 < s.stage ? "past" : i + 1 > s.stage ? "next" : s.state === "running" ? "now" : "halt";
  const mark = { past: "✓", halt: s.state === "failed" ? "✕" : "–" }[at] ?? "";
  return `<li class="${at}"${at === "now" ? ` aria-current="step"` : ""}><span class="mark" aria-hidden="true">${mark}</span>${esc(title)}</li>`;
}

function renderFoot(r) {
  const s = r.status;
  const foot = r.dock.querySelector(".review-foot");
  foot.key = `${s.state} ${s.report}`;
  const report = s.report ? `<a href="/papers/${r.id}/review/report" target="_blank" rel="noopener">Read the full review</a>` : "";
  foot.innerHTML =
    s.state === "running"
      ? `<span class="review-keeps">Keeps going if you leave this page.</span><button class="review-btn review-stop">Stop review</button>`
      : s.state === "done"
        ? `${report}<button class="review-btn review-again">Run again</button>`
        : `<button class="review-btn primary review-again">Try again</button>`;
}

// Run again (or try again) from the panel: the same choice as the first time, in place of the buttons.
function runAgain(r) {
  const foot = r.dock.querySelector(".review-foot");
  foot.key = null; // Cancel puts the buttons back
  const cancel = () => (renderFoot(r), foot.querySelector(".review-again").focus());
  foot.replaceChildren(depthForm(r, r.status.depth, cancel, r.status.state === "done" ? "Run again" : "Try again"));
  foot.querySelector("input:checked").focus();
}

async function stopReview(r, button) {
  if (!confirm("Stop the agent review of this paper?")) return;
  Object.assign(button, { disabled: true, textContent: "Stopping…" });
  try {
    await api(`/papers/${r.id}/review`, { method: "DELETE" });
  } catch (e) {
    Object.assign(button, { disabled: false, textContent: "Stop review" });
    return alert(`Couldn't stop the review: ${e.message}`);
  }
  poll(r); // show it stopped without waiting for the next check
}

// Screen readers hear a new stage and the end at once, and the agent's words now and then, not every step.
function say(r, text, now = false) {
  if (!r.dock || (!now && Date.now() - (r.said ?? 0) < REVIEW_SAY)) return;
  r.dock.querySelector(".review-sr").textContent = text;
  r.said = Date.now();
}

// The elapsed time, ticking every second while the review runs.
function renderClock(r) {
  const s = r.status;
  const text = s?.state === "running" ? clock(s.elapsed + (Date.now() - r.at) / 1000) : "";
  r.dock?.querySelectorAll(".review-clock").forEach((el) => (el.textContent = text));
}

// Seconds as m:ss (h:mm:ss past the hour).
function clock(t) {
  const s = Math.max(0, Math.floor(t));
  const [h, m, ss] = [Math.floor(s / 3600), Math.floor(s / 60) % 60, String(s % 60).padStart(2, "0")];
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

// How long a finished run took, in words: "48 min", "1 h 12 min".
function took(t) {
  const m = Math.round(t / 60);
  return m < 1 ? "under a minute" : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h${m % 60 ? ` ${m % 60} min` : ""}`;
}

// --- the library ---

// A quiet badge on a library card (app.js): a review under way (from GET /reviews), or one done.
function reviewBadge(r, reviewed) {
  if (r?.state === "running") {
    const title = r.stage_title ? ` title="${esc(r.stage_title)}"` : "";
    return `<span class="review-badge running" style="--progress: ${+r.progress || 0}"${title}>Reviewing · ${Math.round(r.progress * 100)}%</span>`;
  }
  return reviewed ? `<span class="review-badge">AI reviewed</span>` : "";
}
