"""Claude agent that reads a paper and resolves its metadata and references via tool calls.

To add a resolver (OpenAlex, PubMed, ...): write a function and add it to TOOLS.
"""

import io
import json
import os

import anthropic
import httpx
import pymupdf
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pydantic import ValidationError

from .schemas import Paper

MODEL = "claude-opus-5-5"
MAX_TURNS = 40
PAGES_PER_READ = 10

load_dotenv()
client = anthropic.Anthropic()
http = httpx.Client(follow_redirects=True, timeout=30, headers={"User-Agent": "human-pretraining/0.1"})

SYSTEM = """You build an accurate bibliographic record for a research paper.

1. Call fetch_document on the URL, then read_pages until you have seen the whole paper, including the reference list.
2. Parse the paper's own authors carefully: keep each name as printed in `raw`, split given/family/particle/suffix
   (handle "Last, F.", particles like "van der", CJK names, and consortium authors with is_group).
   Only set equal_contribution_group when the paper explicitly says so: a marker (*, †, ‡, ...) on the author whose
   footnote/legend states equal contribution, or a statement in the author list or text (e.g. "A and B contributed
   equally"). Never infer it from author order or shared affiliations; otherwise leave it null. Same for
   corresponding. Quote the relevant footnotes/statements in contribution_notes.
3. For every reference: parse the entry, then confirm it with search_crossref / search_semantic_scholar / get_by_id.
   Only take metadata from a lookup if title, authors and year clearly match; otherwise keep what the document says
   and lower confidence. If a preprint has a published version, prefer the published DOI and keep the arxiv_id.
   Make independent lookups in parallel.
4. For every reference, record the sentence(s) in the body that cite it, the section, page and why it is cited.
5. Finish by calling save_paper exactly once with the full record. If it returns a validation error, fix and retry."""


class Run:
    """Per-request state shared by the tools."""

    def __init__(self, url: str):
        self.url = url
        self.pages: list[str] = []
        self.paper: Paper | None = None

    # --- tools ---

    def fetch_document(self, url: str) -> str:
        resp = http.get(url)
        resp.raise_for_status()
        if "pdf" not in resp.headers.get("content-type", ""):
            soup = BeautifulSoup(resp.text, "html.parser")
            pdf_meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
            if not pdf_meta:
                self.pages = [soup.get_text("\n", strip=True)]
                return self.read_pages(1, 1)
            resp = http.get(pdf_meta["content"])
            resp.raise_for_status()
        with pymupdf.open(stream=io.BytesIO(resp.content), filetype="pdf") as doc:
            self.pages = [page.get_text() for page in doc]
        return self.read_pages(1, PAGES_PER_READ)

    def read_pages(self, start: int, end: int) -> str:
        end = min(end, len(self.pages))
        text = "\n".join(f"--- page {i} ---\n{self.pages[i - 1]}" for i in range(start, end + 1))
        return f"[pages {start}-{end} of {len(self.pages)}]\n{text}"

    def search_crossref(self, query: str, year: int | None = None) -> str:
        params = {"query.bibliographic": query, "rows": 3}
        if year:
            params["filter"] = f"from-pub-date:{year - 1},until-pub-date:{year + 1}"
        items = http.get("https://api.crossref.org/works", params=params).json()["message"]["items"]
        return json.dumps([
            {
                "doi": it.get("DOI"),
                "title": (it.get("title") or [None])[0],
                "authors": [f"{a.get('given', '')} {a.get('family', a.get('name', ''))}".strip() for a in it.get("author", [])],
                "year": (it.get("issued", {}).get("date-parts") or [[None]])[0][0],
                "venue": (it.get("container-title") or [None])[0],
            }
            for it in items
        ])

    def search_semantic_scholar(self, query: str) -> str:
        return self._s2("paper/search", {"query": query, "limit": 3})

    def get_by_id(self, paper_id: str) -> str:
        return self._s2(f"paper/{paper_id}", {})

    def save_paper(self, **paper) -> str:
        self.paper = Paper.model_validate(paper)
        return "ok"

    def _s2(self, path: str, params: dict) -> str:
        params["fields"] = "title,authors,year,venue,externalIds"
        headers = {"x-api-key": os.environ["S2_API_KEY"]} if "S2_API_KEY" in os.environ else {}
        resp = http.get(f"https://api.semanticscholar.org/graph/v1/{path}", params=params, headers=headers)
        if resp.status_code == 429:
            return "Semantic Scholar rate limit hit; use search_crossref instead."
        return resp.text


TOOLS = [
    {
        "name": "fetch_document",
        "description": "Download a paper (HTML page or PDF; follows citation_pdf_url when present) and return the first pages of text.",
        "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    },
    {
        "name": "read_pages",
        "description": "Return pages start..end (1-indexed, inclusive) of the fetched document.",
        "input_schema": {
            "type": "object",
            "properties": {"start": {"type": "integer"}, "end": {"type": "integer"}},
            "required": ["start", "end"],
        },
    },
    {
        "name": "search_crossref",
        "description": "Search Crossref with a free-text citation string (title, authors, venue). Returns the top 3 works with DOIs.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "year": {"type": "integer", "description": "Optional; filters to year ±1."}},
            "required": ["query"],
        },
    },
    {
        "name": "search_semantic_scholar",
        "description": "Search Semantic Scholar by title. Returns top 3 papers with externalIds (DOI, ArXiv), useful for preprint/published matching.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "get_by_id",
        "description": "Look up one paper on Semantic Scholar by id, e.g. 'DOI:10.1145/...' or 'ARXIV:1706.03762'.",
        "input_schema": {"type": "object", "properties": {"paper_id": {"type": "string"}}, "required": ["paper_id"]},
    },
    {
        "name": "save_paper",
        "description": "Save the final, complete paper record. Call once at the end.",
        "input_schema": Paper.model_json_schema(),
    },
]


def extract(url: str, meta: dict) -> Paper:
    run = Run(url)
    prompt = f"Paper URL: {url}\nMeta tags from the page (hints, verify against the document):\n{json.dumps(meta, indent=1)}"
    messages = [{"role": "user", "content": prompt}]

    for _ in range(MAX_TURNS):
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=64000,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            cache_control={"type": "ephemeral"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()

        if response.stop_reason == "refusal":
            raise RuntimeError(f"Claude refused: {response.stop_details}")
        messages.append({"role": "assistant", "content": response.content})
        tool_calls = [b for b in response.content if b.type == "tool_use"]
        if not tool_calls:
            break

        results = []
        for call in tool_calls:
            try:
                output, is_error = getattr(run, call.name)(**call.input), False
            except (httpx.HTTPError, ValidationError, KeyError, ValueError) as e:
                output, is_error = f"{type(e).__name__}: {e}", True
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": output, "is_error": is_error})
        messages.append({"role": "user", "content": results})

        if run.paper:
            return run.paper

    raise RuntimeError("Agent finished without calling save_paper")
