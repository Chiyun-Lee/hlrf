"""For you's summaries: what a new arXiv paper does and why this reader should care, given their own work.

One Claude call per batch of papers; the reader's own and recently liked papers (feed.profile()) are the context for
"why". Uses SUMMARY_MODEL / SUMMARY_EFFORT, like the page notes.
"""

from . import llm, summarize
from .schemas import Pitch, Pitches

ABSTRACT_CHARS = 700  # of each profile paper's abstract; enough to tell what the reader works on

SYSTEM = """You help a researcher triage today's new arXiv papers in a few seconds each. For every paper, write:
- `what`: what the paper does and finds, in one or two sentences, at most 40 words. Plain words a busy expert reads at
  a glance; keep the key result or number; no hype.
- `why`: why this researcher in particular should care, at most 30 words, addressed to them as "you". Name the concrete
  link to their own work: a method, dataset, parameter, code or open question they work on. If the link is weak, say
  so plainly (start with "Only loosely related:"). Never invent a connection or claim anything the abstract doesn't.
Use $...$ LaTeX only where words won't do. Return one entry per paper, with its id exactly as given."""


def write(papers: list[dict], profile: dict) -> list[Pitch]:
    """papers: [{id, title, abstract, reasons?}] as GET /feed returns them; profile: as feed.profile() returns it."""

    def listing(items: list[dict]) -> str:
        return "\n".join(f"- {p['title']}\n  {p['abstract'][:ABSTRACT_CHARS]}" for p in items) or "(none yet)"

    today = []
    for p in papers:
        matched = [*(p.get("reasons") or {}).get("topics", []), *(p.get("reasons") or {}).get("authors", [])]
        hint = f"\nTheir ranking model matched on: {', '.join(matched)}" if matched else ""
        today.append(f"[{p['id']}] {p['title']}\n{p['abstract']}{hint}")
    prompt = (
        f"The researcher follows {', '.join(profile.get('categories', []))} on arXiv.\n\n"
        f"Their own papers:\n{listing(profile.get('mine', []))}\n\n"
        f"Papers they recently marked relevant:\n{listing(profile.get('liked', []))}\n\n"
        f"Recent papers in their Zotero library:\n{listing(profile.get('zotero', []))}\n\n"
        "Today's papers to summarise:\n\n" + "\n\n".join(today)
    )
    wanted = {p["id"] for p in papers}
    return [p for p in llm.ask(Pitches, SYSTEM, prompt, summarize.MODEL, summarize.EFFORT).pitches if p.id in wanted]
