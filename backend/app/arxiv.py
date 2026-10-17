"""Fetch papers from the arXiv API (https://info.arxiv.org/help/api/) for the For you tab."""

import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock
from zoneinfo import ZoneInfo

import httpx

from .schemas import ArxivPaper

API = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
EASTERN = ZoneInfo("America/New_York")
DEADLINE = clock(14, 0)  # arXiv's daily submission deadline, US Eastern, Monday to Friday
PAGE = 500
http = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "human-pretraining/0.1 (For you tab)"})


def listing_date(submitted_utc: datetime) -> date:
    """The daily listing a new submission appears in: the first weekday deadline at or after it, listed the next
    weekday (Friday's batch is Monday's papers). Holidays are ignored."""
    local = submitted_utc.replace(tzinfo=timezone.utc).astimezone(EASTERN)
    day = local.date()
    if local.weekday() >= 5 or local.time() >= DEADLINE:
        day = next_weekday(day)
    return next_weekday(day)


def next_weekday(day: date) -> date:
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def parse(xml: str | bytes) -> list[ArxivPaper]:
    papers = []
    for entry in ET.fromstring(xml).findall(f"{ATOM}entry"):
        raw_id = entry.findtext(f"{ATOM}id", "")
        if "/abs/" not in raw_id:
            continue  # the API reports query errors as an entry with an /api/errors id
        m = re.fullmatch(r"(.+?)v(\d+)", raw_id.rsplit("/abs/", 1)[-1])
        primary = entry.find(f"{ARXIV}primary_category")
        categories = [c.get("term") for c in entry.findall(f"{ATOM}category") if c.get("term")]
        if primary is not None and primary.get("term") in categories:
            categories.remove(primary.get("term"))
            categories.insert(0, primary.get("term"))
        published = datetime.strptime(entry.findtext(f"{ATOM}published", "").strip(), "%Y-%m-%dT%H:%M:%SZ")
        papers.append(
            ArxivPaper(
                id=m.group(1) if m else raw_id.rsplit("/abs/", 1)[-1],
                version=int(m.group(2)) if m else 1,
                title=clean(entry.findtext(f"{ATOM}title")),
                abstract=clean(entry.findtext(f"{ATOM}summary")),
                authors=[clean(a.findtext(f"{ATOM}name")) for a in entry.findall(f"{ATOM}author")],
                categories=categories,
                published=published,
                listing_date=listing_date(published),
                comment=clean(entry.findtext(f"{ARXIV}comment")) or None,
                journal_ref=clean(entry.findtext(f"{ARXIV}journal_ref")) or None,
                doi=clean(entry.findtext(f"{ARXIV}doi")) or None,
            )
        )
    return papers


def clean(text: str | None) -> str:
    return " ".join(text.split()) if text else ""


def query(categories: Iterable[str], start: date, end: date) -> str:
    cats = " OR ".join(f"cat:{c}" for c in categories)
    return f"({cats}) AND submittedDate:[{start:%Y%m%d}0000 TO {end:%Y%m%d}2359]"


def recent(categories: list[str], days: int, max_results: int = 2000) -> list[ArxivPaper]:
    """Papers submitted in the last `days` days in any of `categories`, cross-lists included."""
    end = datetime.now(timezone.utc).date()
    papers: list[ArxivPaper] = []
    while len(papers) < max_results:
        if papers:
            time.sleep(3)  # arXiv asks API clients to wait three seconds between requests
        params = {
            "search_query": query(categories, end - timedelta(days=days), end),
            "start": len(papers),
            "max_results": PAGE,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        resp = http.get(API, params=params)
        resp.raise_for_status()
        page = parse(resp.content)
        papers += page
        if len(page) < PAGE:
            break
    return papers


def by_ids(ids: list[str]) -> list[ArxivPaper]:
    """The latest version of each paper; ids arXiv doesn't know are left out."""
    if not ids:
        return []
    resp = http.get(API, params={"id_list": ",".join(ids), "max_results": len(ids)})
    resp.raise_for_status()
    return parse(resp.content)


def by_titles(titles: list[str]) -> list[tuple[str, ArxivPaper]]:
    """(title, paper) for each title that matches a paper on arXiv. Searches each title's most distinctive words,
    ten titles per request, then compares whole titles, ignoring case, punctuation and LaTeX."""
    found = []
    for start in range(0, len(titles), 10):
        if start:
            time.sleep(3)  # arXiv asks API clients to wait three seconds between requests
        batch = titles[start : start + 10]
        clauses = [" AND ".join(f"ti:{w}" for w in sorted(words(t), key=len, reverse=True)[:6]) for t in batch]
        q = " OR ".join(f"({c})" for c in clauses if c)
        if not q:
            continue
        resp = http.get(API, params={"search_query": q, "max_results": 100})
        resp.raise_for_status()
        candidates = parse(resp.content)
        for title in batch:
            if match := next((p for p in candidates if same_title(title, p.title)), None):
                found.append((title, match))
    return found


def words(title: str) -> list[str]:
    """Plain words of a title, without LaTeX: "$\\texttt{SwiftC}_\\ell$: fast ..." -> ["fast", ...]."""
    return re.findall(r"[a-z0-9]+", re.sub(r"\$[^$]*\$", " ", title).lower())


def same_title(a: str, b: str) -> bool:
    x, y = " ".join(words(a)), " ".join(words(b))
    shorter, longer = sorted((x, y), key=len)
    return bool(shorter) and (x == y or (len(shorter) >= 30 and shorter in longer))
