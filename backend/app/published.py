"""Your published papers for For you's "Your papers": DOIs, doi.org links, journal article links and INSPIRE
literature links.

A paper that's also on arXiv resolves to its arXiv id, and For you then uses the arXiv record like any pasted id:
INSPIRE (physics and astronomy) and OpenAlex (every field) both know which journal papers have an arXiv version.
Otherwise For you keeps the journal's record (title, authors, date and abstract) from OpenAlex or INSPIRE, with
Crossref as a last place to find an abstract. A link without a DOI in it is fetched for the DOI the page declares
(citation_doi and similar meta tags); some publishers block that, and then you paste the DOI instead.
"""

import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from urllib.parse import unquote, urlsplit

import httpx
from bs4 import BeautifulSoup

from .arxiv import ID as ARXIV_ID
from .schemas import ArxivPaper

UA = "hlrf/0.1 (looks up your own papers)"
http = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA})
WORKERS = 4  # papers looked up at once

URL = re.compile(r"https?://[^\s<>\"']+", re.I)
DOI = re.compile(r"10\.\d{4,9}/[^\s<>\"']+")
ARXIV_DOI = re.compile(rf"^10\.48550/arxiv\.({ARXIV_ID})(?:v\d+)?$", re.I)
ARXIV_URL = re.compile(rf"arxiv\.org/(?:abs|pdf|html)/({ARXIV_ID})", re.I)
INSPIRE_RECORD = re.compile(r"inspirehep\.net/(?:api/)?literature/(\d+)", re.I)
NATURE = re.compile(r"nature\.com/articles/([a-z0-9.\-]+)", re.I)  # nature.com/articles/s41550-024-02225-0 is 10.1038/s41550-...
# What publishers put after the DOI in their URLs: .../10.3847/1538-4357/ad1234/pdf, .../s10714-024-03270-6.pdf,
# and bioRxiv's version, 10.1101/2024.01.01.123456v2.full
PAGE_SUFFIX = re.compile(
    r"(?:/(?:abstract|full|fulltext|full-text|pdf|epdf|pdfdirect|meta|html|references|citedby|figures|suppl|supplemental|summary|info|metrics)"
    r"|\.(?:pdf|full|html|abstract))$",
    re.I,
)
PREPRINT_VERSION = re.compile(r"^(10\.(?:1101|64898)/[\d.]+)v\d+$")
SKIP_HOSTS = ("arxiv.org", "inspirehep.net/authors")  # handled as arXiv ids and as a profile
META_DOI = ("citation_doi", "dc.identifier", "prism.doi", "bepress_citation_doi")


class PageError(Exception):
    """A pasted link that can't be read for its DOI (blocked, not a public website, not found)."""


@dataclass
class Found:
    """What a pasted text holds besides plain arXiv ids and profile links."""

    arxiv: list[str] = field(default_factory=list)  # arXiv ids from arXiv DOIs
    dois: list[str] = field(default_factory=list)  # lowercase, without trailing punctuation or URL path
    records: list[str] = field(default_factory=list)  # INSPIRE literature record ids
    links: list[str] = field(default_factory=list)  # other links, to be read for their DOI

    def __bool__(self) -> bool:
        return bool(self.arxiv or self.dois or self.records or self.links)


@dataclass
class Resolved:
    """One pasted DOI or link: on arXiv (`arxiv`), only in a journal (`paper`), or neither, with why."""

    given: str
    arxiv: str | None = None
    paper: ArxivPaper | None = None
    problem: str | None = None  # not_found, unreadable or unreachable


def clean_doi(raw: str) -> str:
    """A DOI as found in prose or a URL, without what follows it: punctuation, a query, a publisher's /pdf."""
    doi = unquote(raw).split("?")[0].split("#")[0]
    while True:
        before = doi
        doi = PREPRINT_VERSION.sub(r"\1", PAGE_SUFFIX.sub("", doi.rstrip(".,;:'\"/")))
        for close, open_ in ((")", "("), ("]", "["), ("}", "{")):
            if doi.endswith(close) and doi.count(close) > doi.count(open_):
                doi = doi[:-1]
        if doi == before:
            return doi.lower()


def find(text: str) -> Found:
    found = Found()

    def add_doi(doi: str) -> None:
        if m := ARXIV_DOI.match(doi):
            found.arxiv.append(m.group(1))
        else:
            found.dois.append(doi)

    for url in URL.findall(text):
        url = url.rstrip(".,;:)]}")
        if any(h in url.lower() for h in SKIP_HOSTS):
            continue
        if m := DOI.search(unquote(url)):
            add_doi(clean_doi(m.group(0)))
        elif m := NATURE.search(url):
            found.dois.append(f"10.1038/{m.group(1).lower()}")
        elif m := INSPIRE_RECORD.search(url):
            found.records.append(m.group(1))
        else:
            found.links.append(url)
    for m in DOI.finditer(URL.sub(" ", text)):  # bare DOIs, with or without "doi:"
        add_doi(clean_doi(m.group(0)))
    found.arxiv, found.dois, found.records, found.links = (list(dict.fromkeys(x)) for x in (found.arxiv, found.dois, found.records, found.links))
    return found


def resolve_all(found: Found) -> list[Resolved]:
    """Look up every DOI, record and link, a few at a time."""
    jobs = [(resolve_doi, d) for d in found.dois] + [(resolve_record, r) for r in found.records] + [(resolve_link, u) for u in found.links]
    with ThreadPoolExecutor(WORKERS) as pool:
        return list(pool.map(lambda job: job[0](job[1]), jobs))


# --- by DOI ---


def resolve_doi(doi: str, given: str | None = None) -> Resolved:
    given = given or doi
    inspire = openalex = None
    errors = 0
    try:
        inspire = inspire_hit(f'doi:"{doi}"')
    except httpx.HTTPError:
        errors += 1
    if inspire and (aid := inspire_arxiv(inspire)):
        return Resolved(given, arxiv=aid)
    try:
        openalex = openalex_work(doi)
    except httpx.HTTPError:
        errors += 1
    if openalex and (aid := openalex_arxiv(openalex)):
        return Resolved(given, arxiv=aid)
    paper = (from_openalex(doi, openalex) if openalex else None) or (from_inspire(doi, inspire) if inspire else None)
    if paper is None:
        return Resolved(given, problem="unreachable" if errors == 2 else "not_found")
    if not paper.abstract:
        abstract = (inspire_abstract(inspire) if inspire else "") or crossref_abstract(doi)
        paper = paper.model_copy(update={"abstract": abstract})
    return Resolved(given, paper=paper)


def inspire_hit(query: str) -> dict | None:
    resp = http.get(
        "https://inspirehep.net/api/literature",
        params={"q": query, "size": 1, "fields": "arxiv_eprints,titles,abstracts,authors.full_name,dois,imprints,preprint_date,publication_info"},
    )
    resp.raise_for_status()
    hits = resp.json()["hits"]["hits"]
    return hits[0]["metadata"] if hits else None


def inspire_arxiv(meta: dict) -> str | None:
    eprints = meta.get("arxiv_eprints") or []
    return eprints[0]["value"] if eprints else None


def inspire_abstract(meta: dict) -> str:
    return clean((meta.get("abstracts") or [{}])[0].get("value"))


def from_inspire(doi: str, meta: dict) -> ArxivPaper:
    imprint = (meta.get("imprints") or [{}])[0].get("date") or meta.get("preprint_date")
    pub = (meta.get("publication_info") or [{}])[0]
    return journal_paper(
        doi,
        title=(meta.get("titles") or [{}])[0].get("title"),
        abstract=inspire_abstract(meta),
        authors=[" ".join(reversed([p.strip() for p in a["full_name"].split(",", 1)])) for a in meta.get("authors", [])],
        day=imprint or str(pub.get("year") or ""),
        venue=pub.get("journal_title"),
    )


def openalex_work(doi: str) -> dict | None:
    resp = http.get(f"https://api.openalex.org/works/https://doi.org/{doi}")
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def openalex_arxiv(work: dict) -> str | None:
    for loc in work.get("locations") or []:
        for url in (loc.get("landing_page_url"), loc.get("pdf_url")):
            if url and (m := ARXIV_URL.search(url)):
                return m.group(1)
    return None


def from_openalex(doi: str, work: dict) -> ArxivPaper | None:
    if not work.get("display_name"):
        return None
    return journal_paper(
        doi,
        title=work["display_name"],
        abstract=from_inverted_index(work.get("abstract_inverted_index")),
        authors=[a["author"]["display_name"] for a in work.get("authorships") or [] if a.get("author", {}).get("display_name")],
        day=work.get("publication_date") or str(work.get("publication_year") or ""),
        venue=((work.get("primary_location") or {}).get("source") or {}).get("display_name"),
    )


def from_inverted_index(index: dict | None) -> str:
    """OpenAlex keeps abstracts as {word: [positions]}."""
    if not index:
        return ""
    return " ".join(word for _, word in sorted((pos, word) for word, positions in index.items() for pos in positions))


def crossref_abstract(doi: str) -> str:
    try:
        resp = http.get(f"https://api.crossref.org/works/{doi}")
        if not resp.is_success:
            return ""
        jats = resp.json()["message"].get("abstract") or ""
    except (httpx.HTTPError, ValueError):
        return ""
    return re.sub(r"^abstract\s+", "", clean(re.sub(r"<[^>]+>", " ", jats)), flags=re.I)


def journal_paper(doi: str, *, title: str | None, abstract: str, authors: list[str], day: str, venue: str | None) -> ArxivPaper:
    when = partial_date(day)
    return ArxivPaper(
        id=doi,
        title=clean(title) or doi,
        abstract=abstract,
        authors=authors,
        categories=[],
        published=datetime(when.year, when.month, when.day),
        listing_date=when,
        journal_ref=clean(venue) or None,
        doi=doi,
        source="doi",
    )


def partial_date(text: str) -> date:
    """"2024-07-03", "2024-07" or "2024"; today if there's none."""
    parts = [int(p) for p in re.findall(r"\d+", text or "")[:3]]
    if not parts or not 1000 < parts[0] < 3000:
        return date.today()
    return date(parts[0], parts[1] if len(parts) > 1 and 1 <= parts[1] <= 12 else 1, parts[2] if len(parts) > 2 and 1 <= parts[2] <= 28 else 1)


def clean(text: str | None) -> str:
    return " ".join(text.split()) if text else ""


# --- by INSPIRE record or by page ---


def resolve_record(recid: str) -> Resolved:
    given = f"inspirehep.net/literature/{recid}"
    try:
        resp = http.get(f"https://inspirehep.net/api/literature/{recid}", params={"fields": "arxiv_eprints,dois"})
        if resp.status_code == 404:
            return Resolved(given, problem="not_found")
        resp.raise_for_status()
    except httpx.HTTPError:
        return Resolved(given, problem="unreachable")
    meta = resp.json()["metadata"]
    if aid := inspire_arxiv(meta):
        return Resolved(given, arxiv=aid)
    if dois := meta.get("dois"):
        return resolve_doi(clean_doi(dois[0]["value"]), given)
    return Resolved(given, problem="not_found")


def check_public(url: httpx.URL | str) -> None:
    """Refuse links to this machine or a private network: anyone using the app can paste a link for it to fetch."""
    url = httpx.URL(str(url))
    if url.scheme not in ("http", "https") or not url.host:
        raise PageError("only http and https links can be read")
    try:
        infos = socket.getaddrinfo(url.host, url.port or (443 if url.scheme == "https" else 80), proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise PageError(f"there's no website at {url.host}") from e
    if not all(ipaddress.ip_address(info[4][0].split("%")[0]).is_global for info in infos):
        raise PageError(f"{url.host} isn't a public website")


# Every request and redirect is checked first.
pages = httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": f"Mozilla/5.0 (compatible; {UA})"},
                     event_hooks={"request": [lambda request: check_public(request.url)]})


def resolve_link(url: str) -> Resolved:
    try:
        kind, value = doi_on_page(url)
    except PageError:
        return Resolved(url, problem="unreadable")
    if kind == "arxiv":
        return Resolved(url, arxiv=value)
    return resolve_doi(value, url)


def doi_on_page(url: str) -> tuple[str, str]:
    """("doi", doi) or ("arxiv", id) from the page's meta tags."""
    try:
        resp = pages.get(url)
    except httpx.HTTPError as e:
        raise PageError(f"couldn't load {urlsplit(url).hostname}") from e
    if not resp.is_success or "html" not in resp.headers.get("content-type", ""):
        raise PageError(f"{urlsplit(url).hostname} answered {resp.status_code}")
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup.find_all("meta"):
        name, content = (tag.get("name") or tag.get("property") or "").lower(), tag.get("content") or ""
        if name == "citation_arxiv_id" and (m := re.search(ARXIV_ID, content)):
            return "arxiv", m.group(0)
        if name in META_DOI and (m := DOI.search(unquote(content))):
            return "doi", clean_doi(m.group(0))
    raise PageError(f"no DOI on {urlsplit(url).hostname}")
