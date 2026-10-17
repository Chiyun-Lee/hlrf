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
# New-style (2410.01234) and old-style (hep-th/0101001) arXiv identifiers, without the version. Old-style ids need a
# real archive name, so that other links' paths (inspirehep.net/authors/1960608) aren't read as ids.
OLD_ARCHIVES = (
    "acc-phys|adap-org|alg-geom|ao-sci|astro-ph|atom-ph|bayes-an|chao-dyn|chem-ph|cmp-lg|comp-gas|cond-mat|cs|dg-ga|"
    "funct-an|gr-qc|hep-ex|hep-lat|hep-ph|hep-th|math|math-ph|mtrl-th|nlin|nucl-ex|nucl-th|patt-sol|physics|plasm-ph|"
    "q-alg|q-bio|quant-ph|solv-int|supr-con"
)
ID = rf"\d{{4}}\.\d{{4,5}}|(?:{OLD_ARCHIVES})(?:\.[A-Z]{{2}})?/\d{{7}}"
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
    """The latest version of each paper, 100 per request; ids arXiv doesn't know are left out."""
    papers: list[ArxivPaper] = []
    for start in range(0, len(ids), 100):
        if start:
            time.sleep(3)  # arXiv asks API clients to wait three seconds between requests
        batch = ids[start : start + 100]
        resp = http.get(API, params={"id_list": ",".join(batch), "max_results": len(batch)})
        resp.raise_for_status()
        papers += parse(resp.content)
    return papers
