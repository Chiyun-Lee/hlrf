// Runs the save in the service worker so it survives the popup closing.
// Progress is kept in chrome.storage under `job:<url>` as a Status; the popup just renders it.
const API = "http://localhost:8000";

type Status = { state: "working" | "done" | "error"; text: string; id?: number };

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "save") save(msg.url, msg.page);
});

async function save(url: string, page: object) {
  const key = `job:${url}`;
  const set = (status: Status) => chrome.storage.local.set({ [key]: status });
  await set({ state: "working", text: "Reading the paper… (you can close this popup)" });
  // Calling an extension API resets the service worker's 30s idle timer during the long request.
  const keepAlive = setInterval(chrome.runtime.getPlatformInfo, 20_000);
  try {
    const res = await fetch(`${API}/papers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, ...page }),
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
