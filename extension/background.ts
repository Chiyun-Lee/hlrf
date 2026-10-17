// Runs the save in the service worker so it survives the popup closing.
// Progress is kept in chrome.storage under `job:<url>`; the popup just renders it.
const API = "http://localhost:8000";

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "save") save(msg.url, msg.page);
});

async function save(url: string, page: object) {
  const key = `job:${url}`;
  await chrome.storage.local.set({ [key]: "Extracting… (you can close this popup)" });
  // Calling an extension API resets the service worker's 30s idle timer during the long request.
  const keepAlive = setInterval(chrome.runtime.getPlatformInfo, 20_000);
  try {
    const res = await fetch(`${API}/papers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, ...page }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `${res.status} ${res.statusText}`);
    const { title } = await res.json();
    await chrome.storage.local.set({ [key]: `Saved "${title}". Open the library to read it.` });
  } catch (e) {
    await chrome.storage.local.set({ [key]: `Error: ${(e as Error).message}` });
  } finally {
    clearInterval(keepAlive);
  }
}
