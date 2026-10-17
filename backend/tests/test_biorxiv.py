from datetime import date, datetime

import httpx
import pytest

from app import biorxiv

RECORD = {
    "title": "Dopamine  and\nmaternal separation",
    "authors": "Reis, A. L.; Souza, B. R.; The Brain Consortium",
    "doi": "10.64898/2026.10.07.757433",
    "date": "2026-10-17",  # a Saturday
    "version": "1",
    "type": "new results",
    "category": "neuroscience",
    "abstract": "We find X.",
}


def test_parse_reads_every_field():
    p = biorxiv.parse(RECORD)
    assert (p.id, p.doi, p.version, p.source) == ("10.64898/2026.10.07.757433", "10.64898/2026.10.07.757433", 1, "biorxiv")
    assert p.title == "Dopamine and maternal separation"
    assert p.authors == ["A. L. Reis", "B. R. Souza", "The Brain Consortium"]
    assert p.categories == ["Neuroscience"]  # as the Sources panel names it
    assert p.published == datetime(2026, 10, 17) and p.listing_date == date(2026, 10, 19)  # weekend -> Monday
    assert p.abs_url == "https://www.biorxiv.org/content/10.64898/2026.10.07.757433v1"
    assert p.pdf_url == "https://www.biorxiv.org/content/10.64898/2026.10.07.757433v1.full.pdf"


def fake_api(monkeypatch, total, answered=None):
    """biorxiv.http.get serving `total` neuroscience records, 30 a page, oldest first; returns the cursors asked for."""
    asked = []

    def get(url, params=None):
        cursor = int(url.rsplit("/", 1)[1])
        asked.append(cursor)
        records = [
            {**RECORD, "doi": f"10.64898/2026.10.07.{i:06d}", "version": "2" if i % 10 == 9 else "1"}
            for i in range(cursor, min(cursor + 30, total))
        ]
        body = {"messages": [{"status": "ok", "category": answered or params["category"], "total": str(total)}], "collection": records}
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(biorxiv.http, "get", get)
    return asked


def test_recent_reads_every_page_and_keeps_first_versions(monkeypatch):
    asked = fake_api(monkeypatch, total=70)
    papers = biorxiv.recent(["Neuroscience"], days=3)
    assert sorted(asked) == [0, 30, 60]
    assert len(papers) == 63  # every tenth record is a revision of an older preprint


def test_recent_keeps_the_newest_when_there_are_too_many(monkeypatch):
    asked = fake_api(monkeypatch, total=200)
    papers = biorxiv.recent(["Neuroscience"], days=30, max_results=50)
    assert sorted(asked) == [0, 150, 180]  # the first page tells how many; then only the newest 50
    assert min(p.id for p in papers) == "10.64898/2026.10.07.000150"


def test_an_unknown_subject_is_an_error_not_every_paper(monkeypatch):
    fake_api(monkeypatch, total=70, answered="all")
    with pytest.raises(ValueError, match="doesn't know"):
        biorxiv.recent(["Epidemiology"], days=3)
