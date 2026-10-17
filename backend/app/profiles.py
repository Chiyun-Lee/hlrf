"""Your papers from an INSPIRE-HEP profile link, for For you's "Your papers". INSPIRE's public API lists an
author's papers with their arXiv ids."""

import re

import httpx

INSPIRE = re.compile(r"inspirehep\.net/authors/(\d+)", re.I)
MAX_PAPERS = 100  # most recent; collaboration members can have thousands
http = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "human-pretraining/0.1 (imports your own publication list)"})


class ProfileError(Exception):
    pass


def find(text: str) -> dict | None:
    """The profile a pasted link points to: {"kind": "inspire", "id": ..., "url": ...}, or None."""
    if m := INSPIRE.search(text):
        return {"kind": "inspire", "id": m.group(1), "url": f"https://inspirehep.net/authors/{m.group(1)}"}
    return None


def label(profile: dict) -> str:
    return "INSPIRE"


def papers(profile: dict) -> tuple[list[str], int]:
    """(arXiv ids, number of the profile's papers that aren't on arXiv), most recent first."""
    try:
        resp = http.get(
            "https://inspirehep.net/api/literature",
            params={"q": f"authors.recid:{profile['id']}", "size": MAX_PAPERS, "sort": "mostrecent", "fields": "arxiv_eprints"},
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise ProfileError(f"Couldn't read your INSPIRE profile ({type(e).__name__}). Try again in a moment.") from e
    hits = resp.json()["hits"]["hits"]
    ids = [h["metadata"]["arxiv_eprints"][0]["value"] for h in hits if h["metadata"].get("arxiv_eprints")]
    return ids, len(hits) - len(ids)
