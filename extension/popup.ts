const out = document.getElementById("out")!;

// Runs inside the page: collect citation_* / dc.* / og:* meta tags and JSON-LD as hints for the backend.
function readMeta(): Record<string, string[]> {
  const meta: Record<string, string[]> = {};
  document.querySelectorAll<HTMLMetaElement>("meta[name], meta[property]").forEach((m) => {
    const key = m.getAttribute("name") ?? m.getAttribute("property")!;
    if (/^(citation_|dc\.|og:)/i.test(key)) (meta[key] ??= []).push(m.content);
  });
  meta["json_ld"] = [...document.querySelectorAll('script[type="application/ld+json"]')].map((s) => s.textContent ?? "");
  return meta;
}

async function main() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const key = `job:${tab.url}`;

  // Show this tab's saved status/result, and keep it live while the popup is open.
  const render = async () => (out.textContent = (await chrome.storage.local.get(key))[key] ?? "");
  chrome.storage.onChanged.addListener((changes) => key in changes && render());
  render();

  document.getElementById("save")!.addEventListener("click", async () => {
    // Meta tags are unavailable on PDF tabs and chrome:// pages; the backend works from the URL alone.
    const meta = await chrome.scripting
      .executeScript({ target: { tabId: tab.id! }, func: readMeta })
      .then(([r]) => r.result)
      .catch(() => ({}));
    chrome.runtime.sendMessage({ type: "save", url: tab.url, meta });
  });
}

main();
