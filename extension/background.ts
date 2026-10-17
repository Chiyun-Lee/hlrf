// Runs the save in the service worker so it survives the popup closing.
// Progress is kept in chrome.storage under `job:<url>`; the popup just renders it.
const API = "http://localhost:8000";

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "save") save(msg.url, msg.meta);
});

async function save(url: string, meta: object) {
  const key = `job:${url}`;
  await chrome.storage.local.set({ [key]: "Extracting… (this can take a few minutes; you can close this popup)" });
  // Calling an extension API resets the service worker's 30s idle timer during the long request.
  const keepAlive = setInterval(chrome.runtime.getPlatformInfo, 20_000);
  try {
    const res = await fetch(`${API}/papers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, meta }),
    });
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    await chrome.storage.local.set({ [key]: JSON.stringify(await res.json(), null, 2) });
  } catch (e) {
    await chrome.storage.local.set({ [key]: `Error: ${e}` });
  } finally {
    clearInterval(keepAlive);
  }
}
