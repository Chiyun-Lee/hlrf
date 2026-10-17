"""The library list and how the browser caches PDFs."""

import pytest
from fastapi.testclient import TestClient

from app import db, pins
from app.main import app
from app.schemas import Author, Page, PaperPins, Paper

client = TestClient(app)


@pytest.fixture(autouse=True)
def empty_library():
    with db.lock, db.conn:
        db.conn.execute("DELETE FROM papers")


def paper(title: str, pages: int = 2) -> Paper:
    authors = [Author(raw="A. Author", affiliations=["Somewhere"]), Author(raw="B. Author")]
    return Paper(url=f"https://arxiv.org/abs/{title}", title=title, authors=authors, year=2026, venue="JCAP", pages=[Page(blocks=[])] * pages)


def test_library_lists_papers_newest_first():
    first = db.save(paper("First", pages=3))
    second = db.save(Paper(url="https://example.org/x", title="Second", authors=[]))
    assert client.get("/papers").json() == [
        {"id": second, "title": "Second", "authors": [], "year": None, "venue": None, "url": "https://example.org/x", "n_pages": 0, "reviewed": False},
        {"id": first, "title": "First", "authors": ["A. Author", "B. Author"], "year": 2026, "venue": "JCAP", "url": "https://arxiv.org/abs/First", "n_pages": 3, "reviewed": False},
    ]


def test_pdf_comes_from_the_browser_cache_until_it_changes():
    pid = db.save(paper("P"), b"%PDF one")
    first = client.get(f"/papers/{pid}/pdf")
    etag = first.headers["etag"]
    assert first.content == b"%PDF one" and first.headers["cache-control"] == "no-cache"
    again = client.get(f"/papers/{pid}/pdf", headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""

    # A deleted paper's id goes to the next paper saved, whose PDF mustn't come from the cache.
    db.delete(pid)
    assert db.save(paper("Q"), b"%PDF two") == pid
    other = client.get(f"/papers/{pid}/pdf", headers={"If-None-Match": etag})
    assert other.status_code == 200 and other.content == b"%PDF two" and other.headers["etag"] != etag
    assert client.get(f"/papers/{db.save(paper('R'))}/pdf").status_code == 404  # saved without a PDF


def test_reviewed_papers_are_flagged_for_the_ai_reviewed_filter():
    shipped = db.save(paper("2506.22373v2"))  # pins ship with the app for this arXiv paper
    reviewed = db.save(paper("2401.00001"))
    plain = db.save(paper("2401.00002"))
    pins.save(reviewed, PaperPins(reviewed="Agent review, 17 Oct 2026", targets=[]))
    flags = {p["id"]: p["reviewed"] for p in client.get("/papers").json()}
    assert flags == {shipped: True, reviewed: True, plain: False}
    assert client.get(f"/papers/{reviewed}").json()["reviewed"] and not client.get(f"/papers/{plain}").json()["reviewed"]
