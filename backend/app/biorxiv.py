"""Fetch new preprints from the bioRxiv API (https://api.biorxiv.org) for the For you tab."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import httpx

from .arxiv import clean
from .schemas import ArxivPaper

API = "https://api.biorxiv.org/details/biorxiv"
# bioRxiv's subject collections. Clinical Trials and Epidemiology moved to medRxiv; the API answers those with every
# subject, so they're left out.
SUBJECTS = [
    "Animal Behavior and Cognition", "Biochemistry", "Bioengineering", "Bioinformatics", "Biophysics", "Cancer Biology",
    "Cell Biology", "Developmental Biology", "Ecology", "Evolutionary Biology", "Genetics", "Genomics", "Immunology",
    "Microbiology", "Molecular Biology", "Neuroscience", "Paleontology", "Pathology", "Pharmacology and Toxicology",
    "Physiology", "Plant Biology", "Scientific Communication and Education", "Synthetic Biology", "Systems Biology",
    "Zoology",
]  # fmt: skip
WORKERS = 4  # pages fetched at once: the API serves 30 records a page, about a second each
http = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "human-pretraining/0.1 (For you tab)"})


def listing_date(posted: date) -> date:
    """bioRxiv posts every day; weekend preprints join Monday's papers, so For you's days stay weekdays."""
    while posted.weekday() >= 5:
        posted += timedelta(days=1)
    return posted


def parse(record: dict) -> ArxivPaper:
    """One record of the API's `collection`."""
    subject = clean(record["category"]).lower()
    posted = date.fromisoformat(record["date"])
    return ArxivPaper(
        id=record["doi"],
        version=int(record["version"]),
        title=clean(record["title"]),
        abstract=clean(record["abstract"]),
        # "Doe, J.; Smith, A. B." -> ["J. Doe", "A. B. Smith"]
        authors=[" ".join(reversed([part.strip() for part in a.split(",", 1)])) for a in record["authors"].split(";") if a.strip()],
        categories=[next((s for s in SUBJECTS if s.lower() == subject), subject.title())],
        published=datetime(posted.year, posted.month, posted.day),
        listing_date=listing_date(posted),
        doi=record["doi"],
        source="biorxiv",
    )


def page(subject: str, start: date, end: date, cursor: int) -> dict:
    resp = http.get(f"{API}/{start}/{end}/{cursor}", params={"category": subject.lower().replace(" ", "_")})
    resp.raise_for_status()
    data = resp.json()
    answered = data["messages"][0].get("category")
    if answered != subject.lower():  # an unknown subject comes back as every subject
        raise ValueError(f"bioRxiv doesn't know the subject {subject!r} (it answered for {answered!r})")
    return data


def recent(subjects: list[str], days: int, max_results: int = 2000) -> list[ArxivPaper]:
    """New preprints (first versions) posted in the last `days` days in any of `subjects`, at most `max_results` of
    the newest per subject."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    records = []
    for subject in subjects:
        first = page(subject, start, end, 0)
        total, size = int(first["messages"][0].get("total") or 0), len(first.get("collection", []))
        if not size:
            continue
        skip = max(0, total - max_results)  # the API serves the oldest first: skip ahead to keep the newest
        if not skip:
            records += first["collection"]
        cursors = range(skip or size, total, size)
        with ThreadPoolExecutor(WORKERS) as pool:
            for data in pool.map(lambda c: page(subject, start, end, c), cursors):
                records += data.get("collection", [])
    papers = {r["doi"]: parse(r) for r in records if r.get("version") == "1"}  # later versions aren't new papers
    return list(papers.values())
