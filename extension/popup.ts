const out = document.getElementById("out")!;
const LIBRARY = "http://localhost:8000/";
// Chrome refuses an extension message over 64 MiB, which a big PDF in base64 can pass, so the save request goes to the
// background in pieces of at most this many characters (JSON escaping can grow one, but not past the limit).
const PIECE = 8_000_000;

// Runs inside the page, with the user's cookies, so it works on sites that block the backend (Cloudflare,
// PMC's download check, institutional access). Must be self-contained: Chrome serialises it into the tab.
async function readPage() {
  // citation_* / dc.* / og:* meta tags and JSON-LD, as hints for the backend.
  const meta: Record<string, string[]> = {};
  document.querySelectorAll<HTMLMetaElement>("meta[name], meta[property]").forEach((m) => {
    const key = m.getAttribute("name") ?? m.getAttribute("property")!;
    if (/^(citation_|dc\.|og:)/i.test(key)) (meta[key] ??= []).push(m.content);
  });
  meta["json_ld"] = [...document.querySelectorAll('script[type="application/ld+json"]')].map((s) => s.textContent ?? "");

  // Try to download the PDF here; cross-origin links or download checks fail quietly and the backend falls back to the HTML.
  let pdf: string | null = null;
  const pdfUrl = document.querySelector<HTMLMetaElement>('meta[name="citation_pdf_url"]')?.content;
  if (pdfUrl) {
    try {
      const bytes = new Uint8Array(await (await fetch(pdfUrl)).arrayBuffer());
      if (String.fromCharCode(...bytes.subarray(0, 4)) === "%PDF") {
        let binary = "";
        for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
        pdf = btoa(binary);
      }
    } catch {}
  }
  // With the PDF the backend doesn't need the page itself, and leaving it out keeps the request small.
  return { meta, html: pdf ? null : document.documentElement.outerHTML, pdf };
}

async function main() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const key = `job:${tab.url}`;

  // Show this tab's save status (see background.ts), and keep it live while the popup is open.
  const render = async () => {
    let status = (await chrome.storage.local.get(key))[key];
    if (typeof status === "string") status = { state: "done", text: status }; // saved by an older version
    out.className = `status ${status?.state ?? ""}`;
    out.hidden = !status;
    if (!status) return;
    out.textContent = status.state === "error" ? `Hmm, that didn't work: ${status.text}` : status.text;
    if (status.id) {
      const read = Object.assign(document.createElement("a"), { href: `${LIBRARY}#/papers/${status.id}`, target: "_blank", className: "btn primary", textContent: "Read it →" });
      out.append(read);
    }
  };
  chrome.storage.onChanged.addListener((changes) => key in changes && render());
  render();

  document.getElementById("save")!.addEventListener("click", async () => {
    Object.assign(out, { hidden: false, className: "status working", textContent: "Reading the page…" });
    // Scripts can't run on PDF tabs or chrome:// pages; the backend then downloads the URL itself.
    const page = await chrome.scripting
      .executeScript({ target: { tabId: tab.id! }, func: readPage })
      .then(([r]) => r.result)
      .catch(() => ({}));
    const body = JSON.stringify({ url: tab.url, ...page });
    const n = Math.max(1, Math.ceil(body.length / PIECE));
    for (let i = 0; i < n; i++) {
      const ok = await chrome.runtime.sendMessage({ type: "save-part", url: tab.url, i, n, part: body.slice(i * PIECE, (i + 1) * PIECE) });
      if (!ok) return Object.assign(out, { className: "status error", textContent: "Hmm, that didn't work: the paper didn't reach the extension. Try again." });
    }
  });
}

main();
