"""Turn a paper URL into a Paper: code extracts the text, one Claude call reads the title and authors."""

import io
import json
import logging
import os
import re
import time
from urllib.parse import urljoin

import httpx
import pymupdf
from bs4 import BeautifulSoup

from . import llm
from .schemas import Block, Page, Paper, PaperHeader

# Override in .env to compare speed/quality, e.g. EXTRACT_MODEL=claude-sonnet-5-5 EXTRACT_EFFORT=medium
MODEL = os.environ.get("EXTRACT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("EXTRACT_EFFORT", "low")
HEADER_PAGES = 3  # title, authors and affiliations live up front...
# ...plus later pages with these footnotes/sections
HEADER_HINTS = re.compile(r"author contributions|contributed equally|equal contribution|corresponding author|correspondence:|lead contact", re.I)
HTML_BLOCKS_PER_PAGE = 12  # HTML has no pages; chunk it so the viewer can load summaries page by page

log = logging.getLogger(__name__)
http = httpx.Client(follow_redirects=True, timeout=30, headers={"User-Agent": "hlrf/0.1"})

SYSTEM = """You read the opening pages (and any author-contribution sections) of a research paper and return its
bibliographic header.

Parse the paper's own authors carefully: keep each name as printed in `raw`, split given/family/particle/suffix
(handle "Last, F.", particles like "van der", CJK names, and consortium authors with is_group).
Only set equal_contribution_group when the paper explicitly says so: a marker (*, †, ‡, ...) on the author whose
footnote/legend states equal contribution, or a statement in the author list or text (e.g. "A and B contributed
equally"). Never infer it from author order or shared affiliations; otherwise leave it null. Same for corresponding.
Quote the relevant footnotes/statements in contribution_notes.
The page's meta tags are hints; trust the document when they disagree."""


def load(url: str, html: str | None = None, pdf: bytes | None = None) -> tuple[bytes | None, list[Page]]:
    """Return the paper's PDF (if one could be had) and its pages.

    Uses what the extension captured in the user's browser when given, otherwise downloads the URL. Prefers the PDF
    (the URL itself, or the page's citation_pdf_url). Some hosts (PMC, Cloudflare-protected publishers) block
    downloads, so when no PDF comes back we fall back to the article page's HTML.
    """
    if pdf and is_pdf(pdf):
        return pdf, pdf_pages(pdf)
    if html is None:
        resp = http.get(url)
        resp.raise_for_status()
        if is_pdf(resp.content):
            return resp.content, pdf_pages(resp.content)
        html = resp.text
    soup = BeautifulSoup(html, "html.parser")
    pdf_meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
    if pdf_meta:
        try:
            resp = http.get(urljoin(url, pdf_meta["content"]))
            if resp.is_success and is_pdf(resp.content):
                return resp.content, pdf_pages(resp.content)
            log.info("PDF unavailable at %s (%s, %s); using the HTML text", resp.url, resp.status_code, resp.headers.get("content-type"))
        except httpx.HTTPError as e:
            log.info("PDF download failed (%r); using the HTML text", e)
    return None, html_pages(soup)


def is_pdf(data: bytes) -> bool:
    return data.startswith(b"%PDF")


def pdf_pages(data: bytes) -> list[Page]:
    with pymupdf.open(stream=io.BytesIO(data), filetype="pdf") as doc:
        return [
            Page(
                width=page.rect.width,
                height=page.rect.height,
                # A block is (x0, y0, x1, y1, text, block_no, block_type); type 0 is text, 1 is an image.
                blocks=[Block(text=" ".join(b[4].split()), bbox=list(b[:4])) for b in page.get_text("blocks") if b[6] == 0 and b[4].strip()],
            )
            for page in doc
        ]


def html_pages(soup: BeautifulSoup) -> list[Page]:
    main = soup.find("article") or soup.find("main") or soup.body or soup
    texts = [t for el in main.find_all(["h1", "h2", "h3", "h4", "p"]) if (t := " ".join(el.get_text(" ").split()))]
    # Some sites lay text out in <div>s rather than <p>s; then keep all the text, one line per element.
    if sum(map(len, texts)) < 2000:
        texts = main.get_text("\n", strip=True).split("\n")
    n = HTML_BLOCKS_PER_PAGE
    return [Page(blocks=[Block(text=t) for t in texts[i : i + n]]) for i in range(0, len(texts), n)]


def page_text(page: Page) -> str:
    return "\n\n".join(b.text for b in page.blocks)


def extract(url: str, meta: dict, html: str | None = None, pdf: bytes | None = None) -> tuple[Paper, bytes | None]:
    """html/pdf: the page and PDF as the user's browser saw them, if the extension could capture them."""
    t0 = time.monotonic()
    pdf, pages = load(url, html, pdf)
    t1 = time.monotonic()

    # Only the pages that carry the header, so Claude has less to read (faster, and fewer safety-classifier trips).
    texts = [page_text(p) for p in pages]
    picked = [i for i, t in enumerate(texts) if i < HEADER_PAGES or HEADER_HINTS.search(t)]
    doc = "\n\n".join(f"--- page {i + 1} ---\n{texts[i]}" for i in picked)
    prompt = f"Paper URL: {url}\nMeta tags from the page:\n{json.dumps(meta, indent=1)}\n\n{doc}"
    header = llm.ask(PaperHeader, SYSTEM, prompt, MODEL, EFFORT)

    log.info(
        "extracted %s: fetch %.1fs, claude %.1fs on %d of %d pages (%s, effort %s)",
        url, t1 - t0, time.monotonic() - t1, len(picked), len(pages), MODEL, EFFORT,
    )
    return Paper(url=url, pages=pages, **header.model_dump()), pdf
