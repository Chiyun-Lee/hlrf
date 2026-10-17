"""Your papers from a profile link, for For you's "Your papers".

INSPIRE-HEP has a public API that lists an author's papers with their arXiv ids. Google Scholar has no API: we read
the profile's first page (up to 100 papers; its robots.txt allows profile pages but not paging through them) and find
each title on arXiv. Scholar sometimes refuses automated requests; then we say so.
"""

import re

import httpx
from bs4 import BeautifulSoup

from . import arxiv

INSPIRE = re.compile(r"inspirehep\.net/authors/(\d+)", re.I)
SCHOLAR = re.compile(r"scholar\.google\.[a-z.]+/citations\?\S*?\buser=([\w-]+)", re.I)
MAX_PAPERS = 100  # most recent; collaboration members can have thousands
http = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "human-pretraining/0.1 (imports your own publication list)"})


class ProfileError(Exception):
    pass


def find(text: str) -> dict | None:
    """The profile a pasted link points to: {"kind": "inspire" | "scholar", "id": ..., "url": ...}, or None."""
    if m := INSPIRE.search(text):
        return {"kind": "inspire", "id": m.group(1), "url": f"https://inspirehep.net/authors/{m.group(1)}"}
    if m := SCHOLAR.search(text):
        return {"kind": "scholar", "id": m.group(1), "url": f"https://scholar.google.com/citations?user={m.group(1)}"}
    return None


def label(profile: dict) -> str:
    return {"inspire": "INSPIRE", "scholar": "Google Scholar"}[profile["kind"]]


def papers(profile: dict) -> tuple[list[str], int]:
    """(arXiv ids, number of the profile's papers that aren't on arXiv)."""
    try:
        return inspire(profile["id"]) if profile["kind"] == "inspire" else scholar(profile["id"])
    except httpx.HTTPError as e:
        raise ProfileError(f"Couldn't read your {label(profile)} profile ({type(e).__name__}). Try again in a moment.") from e


def inspire(recid: str) -> tuple[list[str], int]:
    resp = http.get(
        "https://inspirehep.net/api/literature",
        params={"q": f"authors.recid:{recid}", "size": MAX_PAPERS, "sort": "mostrecent", "fields": "arxiv_eprints"},
    )
    resp.raise_for_status()
    hits = resp.json()["hits"]["hits"]
    ids = [h["metadata"]["arxiv_eprints"][0]["value"] for h in hits if h["metadata"].get("arxiv_eprints")]
    return ids, len(hits) - len(ids)


def scholar(user: str) -> tuple[list[str], int]:
    resp = http.get("https://scholar.google.com/citations", params={"user": user, "hl": "en", "pagesize": MAX_PAPERS})
    if resp.status_code in (403, 429) or "captcha" in resp.text.lower():
        raise ProfileError(
            "Google Scholar didn't let the app read your profile; it sometimes blocks automated requests. "
            "Use your INSPIRE profile, or paste arXiv ids."
        )
    resp.raise_for_status()
    titles = [a.get_text(" ", strip=True) for a in BeautifulSoup(resp.text, "html.parser").select("a.gsc_a_at")]
    if not titles:
        raise ProfileError("That Google Scholar profile lists no papers, or isn't public.")
    found = arxiv.by_titles(titles)
    return [p.id for _, p in found], len(titles) - len(found)
