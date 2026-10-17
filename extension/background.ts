// Runs the save in the service worker so it survives the popup closing.
// Progress is kept in chrome.storage under `job:<url>` as a Status; the popup just renders it.
const API = "http://localhost:8000";

type Status = { state: "working" | "done" | "error"; text: string; id?: number };

// The popup sends the save request (the JSON body for POST /papers) in pieces: a captured PDF can be bigger than the
// 64 MiB Chrome allows in one message. Pieces wait here until all of a URL's have come.
const pieces = new Map<string, string[]>();

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.type !== "save-part") return;
  if (msg.i === 0) pieces.set(msg.url, []);
  const got = pieces.get(msg.url);
  if (!got) return reply(false); // a piece without its start (the worker restarted mid-send): the popup's save fails
  got[msg.i] = msg.part;
  if (got.filter((p) => p !== undefined).length === msg.n) {
    pieces.delete(msg.url);
    save(msg.url, got.join(""));
  }
  reply(true);
});

async function save(url: string, body: string) {
  const key = `job:${url}`;
  const set = (status: Status) => chrome.storage.local.set({ [key]: status });
  await set({ state: "working", text: "Reading the paper… (you can close this popup)" });
  // Calling an extension API resets the service worker's 30s idle timer during the long request.
  const keepAlive = setInterval(chrome.runtime.getPlatformInfo, 20_000);
  try {
    const res = await fetch(`${API}/papers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `${res.status} ${res.statusText}`);
    const { id, title } = await res.json();
    await set({ state: "done", text: `Saved “${title}”`, id });
  } catch (e) {
    await set({ state: "error", text: (e as Error).message });
  } finally {
    clearInterval(keepAlive);
  }
}
