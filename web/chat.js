// Highlight-to-ask: select text in a note or in the paper itself, click "Ask", and chat with the tutor about it.
// When the reader is satisfied and the chat surfaced something important, the tutor adds it to the note
// (backend/app/tutor.py decides); the reader can undo that.

let askButton;
let chat;

function enableAsk(container, paperId) {
  if (!askButton) {
    askButton = Object.assign(document.createElement("button"), { className: "ask-button", textContent: "Ask ✦", hidden: true });
    document.body.append(askButton);
    document.addEventListener("selectionchange", () => {
      if (document.getSelection().isCollapsed) askButton.hidden = true;
    });
  }
  container.addEventListener("mouseup", () => setTimeout(() => offerAsk(container, paperId)));
}

function offerAsk(container, paperId) {
  const sel = document.getSelection();
  const selection = sel.toString().trim();
  if (!selection || !container.contains(sel.anchorNode)) return;
  const range = sel.getRangeAt(0);
  const start = range.startContainer.nodeType === Node.ELEMENT_NODE ? range.startContainer : range.startContainer.parentElement;
  const pageEl = start.closest(".page");
  if (!pageEl) return;
  const rect = range.getBoundingClientRect();
  const note = noteAt(pageEl, start, rect);
  Object.assign(askButton.style, { left: `${rect.right + scrollX - 30}px`, top: `${rect.bottom + scrollY + 6}px` });
  askButton.hidden = false;
  askButton.onclick = () => {
    askButton.hidden = true;
    openChat({ paperId, page: +pageEl.dataset.page, note, selection });
  };
}

// The note a selection belongs to: the note it was made in, the text it covers on a text page, or the note box under
// it on a PDF page (selected original text sits underneath a switched-off note).
function noteAt(pageEl, start, rect) {
  const inside = start.closest(".note") ?? start.closest(".block-group")?.querySelector(":scope > .note");
  if (inside) return inside.main ?? inside;
  const [x, y] = [rect.left + rect.width / 2, rect.top + rect.height / 2];
  const hit = [...pageEl.querySelectorAll(".note")].find((n) => {
    const r = n.getBoundingClientRect();
    return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
  });
  return hit ? (hit.main ?? hit) : null;
}

function openChat({ paperId, page, note, selection }) {
  closeChat();
  chat = document.createElement("aside");
  chat.className = "chat";
  chat.innerHTML = `
    <header><b>Ask about this</b><button class="close" title="Close">×</button></header>
    <blockquote>${esc(selection)}</blockquote>
    ${note?.data.heading ? `<div class="chat-about">from the note “${esc(note.data.heading)}”</div>` : ""}
    <div class="messages"></div>
    <form><textarea rows="2" placeholder="What's confusing? (Say thanks when you've got it.)"></textarea><button>Send</button></form>`;
  document.body.append(chat);
  document.body.classList.add("chat-open");
  note?.classList.add("asking");
  chat.note = note;

  const messages = [];
  const list = chat.querySelector(".messages");
  const input = chat.querySelector("textarea");
  const say = (cls, html) => {
    list.insertAdjacentHTML("beforeend", `<div class="msg ${cls}">${html}</div>`);
    list.scrollTop = list.scrollHeight;
    return list.lastElementChild;
  };

  chat.querySelector(".close").onclick = closeChat;
  input.addEventListener("keydown", (e) => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), chat.querySelector("form").requestSubmit()));
  chat.querySelector("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    messages.push({ role: "user", content: text });
    say("user", esc(text));
    const pending = say("ai", "thinking…");
    try {
      const res = await api(atLevel(`/papers/${paperId}/pages/${page}/ask`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note: note?.index ?? null, selection, messages }),
      });
      messages.push({ role: "assistant", content: res.reply });
      pending.innerHTML = esc(res.reply);
      if (res.updated_note && note) noteUpdated(paperId, page, note, res.updated_note, say);
    } catch (err) {
      messages.pop();
      pending.className = "msg error";
      pending.textContent = `Couldn't answer: ${err.message}`;
    }
  });
  input.focus();
}

function noteUpdated(paperId, page, note, updated, say) {
  const before = note.data;
  fillNote(note, updated);
  setNote(note, true);
  const line = say("system", `✎ Added this to the note. <button>Undo</button>`);
  line.querySelector("button").onclick = async () => {
    await api(atLevel(`/papers/${paperId}/pages/${page}/notes/${note.index}`), {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(before),
    });
    fillNote(note, before);
    line.textContent = "Note change undone.";
  };
}

function closeChat() {
  chat?.note?.classList.remove("asking");
  chat?.remove();
  chat = null;
  document.body.classList.remove("chat-open");
}
