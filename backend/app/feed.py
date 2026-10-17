"""The For you tab's recommendations, from arxiv-feed (a separate app that ranks each day's arXiv papers per user).

Set ARXIV_FEED_URL and ARXIV_FEED_TOKEN to connect; the tab explains what's missing until then. Papers in the library
count as "relevant" there (including ones saved before connecting), so the library teaches the ranking.
"""

import logging
import os
import re

import httpx

log = logging.getLogger(__name__)

# New-style (2410.01234) and old-style (hep-th/0101001) arXiv identifiers, without the version.
ARXIV_ID = r"\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}"
ARXIV_URL = re.compile(rf"arxiv\.org/(?:abs|pdf|html)/({ARXIV_ID})(?:v\d+)?", re.I)
ARXIV_CLAIM = re.compile(rf"^(?:arxiv:)?\s*({ARXIV_ID})(?:v\d+)?$", re.I)


class FeedError(Exception):
    """Why recommendations are unavailable: `reason` is not_configured, unreachable, rejected or failed."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def arxiv_id(url: str, claimed: str | None = None) -> str | None:
    """The paper's arXiv id, from its URL or else the id read from the paper (e.g. "arXiv:2410.01234v2")."""
    if m := ARXIV_URL.search(url):
        return m.group(1)
    if claimed and (m := ARXIV_CLAIM.match(claimed.strip())):
        return m.group(1)
    return None


def daily(day: str | None = None) -> dict:
    """One listing day's papers ranked for the user (default: the latest day), as arxiv-feed's /api/feed returns it."""
    return _request("GET", "/api/feed", params={"date": day} if day else None)


def feedback(paper_id: str, kind: str) -> dict:
    """kind: up, down, none (clears up/down) or click."""
    return _request("POST", f"/api/papers/{paper_id}/feedback", json={"kind": kind})


def profile() -> dict:
    """The reader's own papers ("mine") and recently liked ones ("liked"), each {id, title, abstract}."""
    return _request("GET", "/api/profile")


def like(paper_id: str) -> bool:
    """Tell arxiv-feed a library paper is relevant. Best effort: never raises; returns whether it worked."""
    try:
        feedback(paper_id, "up")
        return True
    except FeedError as e:
        if e.reason != "not_configured":
            log.warning("couldn't mark %s relevant in arxiv-feed: %s", paper_id, e)
        return False


def _request(method: str, path: str, **kwargs) -> dict:
    url, token = os.environ.get("ARXIV_FEED_URL", "").rstrip("/"), os.environ.get("ARXIV_FEED_TOKEN", "")
    if not url or not token:
        raise FeedError("not_configured", "Set ARXIV_FEED_URL and ARXIV_FEED_TOKEN in backend/.env.")
    try:
        resp = httpx.request(method, url + path, headers={"Authorization": f"Bearer {token}"}, timeout=60, **kwargs)
    except httpx.HTTPError as e:
        raise FeedError("unreachable", f"arxiv-feed isn't answering at {url} ({type(e).__name__}).") from e
    if resp.status_code == 401:
        raise FeedError("rejected", "arxiv-feed rejected ARXIV_FEED_TOKEN.")
    if not resp.is_success:
        try:
            detail = resp.json()["error"]
        except (ValueError, KeyError, TypeError):
            detail = resp.reason_phrase
        raise FeedError("failed", f"arxiv-feed: {resp.status_code} {detail}")
    return resp.json()
