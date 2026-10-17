import httpx
import pytest
from fastapi.testclient import TestClient

from app import db, extract, feed
from app.main import app
from app.schemas import Paper

client = TestClient(app)

FEED = {
    "day": "2026-10-16",
    "method": "model",
    "papers": [
        {"id": "2610.00001", "title": "Saved already", "abs_url": "https://arxiv.org/abs/2610.00001"},
        {"id": "2610.00002", "title": "Not yet", "abs_url": "https://arxiv.org/abs/2610.00002"},
    ],
}


@pytest.fixture
def arxiv_feed(monkeypatch):
    """A stand-in arxiv-feed server; returns the requests it received."""
    monkeypatch.setenv("ARXIV_FEED_URL", "http://feed.test/")
    monkeypatch.setenv("ARXIV_FEED_TOKEN", "secret")
    seen = []

    def fake(method, url, headers=None, **kwargs):
        seen.append((method, url, headers, kwargs))
        if url.endswith("/api/feed"):
            return httpx.Response(200, json=FEED)
        return httpx.Response(200, json={"feedback": kwargs["json"]["kind"], "learning": {}})

    monkeypatch.setattr(feed.httpx, "request", fake)
    return seen


@pytest.mark.parametrize(
    "url, claimed, expected",
    [
        ("https://arxiv.org/abs/2410.01234v2", None, "2410.01234"),
        ("https://arxiv.org/pdf/2410.01234", None, "2410.01234"),
        ("http://arxiv.org/abs/hep-th/0101001v1", None, "hep-th/0101001"),
        ("https://doi.org/10.1000/x", "arXiv:2410.01234v3", "2410.01234"),
        ("https://doi.org/10.1000/x", "not an id", None),
        ("https://example.com/paper.pdf", None, None),
    ],
)
def test_arxiv_id(url, claimed, expected):
    assert feed.arxiv_id(url, claimed) == expected


def test_feed_marks_papers_already_in_the_library(arxiv_feed):
    saved = db.save(Paper(url="https://arxiv.org/abs/2610.00001v1", title="Saved already", authors=[]))
    data = client.get("/feed?date=2026-10-16").json()
    assert [p["library_id"] for p in data["papers"]] == [saved, None]
    method, url, headers, kwargs = arxiv_feed[0]
    assert (method, url, kwargs["params"]) == ("GET", "http://feed.test/api/feed", {"date": "2026-10-16"})
    assert headers == {"Authorization": "Bearer secret"}


def test_feed_explains_what_is_missing(monkeypatch):
    monkeypatch.delenv("ARXIV_FEED_URL", raising=False)
    response = client.get("/feed")
    assert response.status_code == 503 and response.json()["detail"]["reason"] == "not_configured"

    monkeypatch.setenv("ARXIV_FEED_URL", "http://feed.test")
    monkeypatch.setenv("ARXIV_FEED_TOKEN", "wrong")
    monkeypatch.setattr(feed.httpx, "request", lambda *a, **k: httpx.Response(401, json={"error": "no"}))
    assert client.get("/feed").json()["detail"]["reason"] == "rejected"

    def down(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(feed.httpx, "request", down)
    detail = client.get("/feed").json()["detail"]
    assert detail["reason"] == "unreachable" and "http://feed.test" in detail["message"]


def test_feedback_is_passed_on(arxiv_feed):
    assert client.post("/feed/2610.00002/feedback", json={"kind": "up"}).json()["feedback"] == "up"
    assert arxiv_feed[-1][1] == "http://feed.test/api/papers/2610.00002/feedback"
    assert client.post("/feed/2610.00002/feedback", json={"kind": "maybe"}).status_code == 422


def test_saving_an_arxiv_paper_marks_it_relevant(arxiv_feed, monkeypatch):
    paper = Paper(url="https://arxiv.org/abs/2610.00002", title="Not yet", authors=[])
    monkeypatch.setattr(extract, "extract", lambda *a, **k: (paper, None))
    assert client.post("/papers", json={"url": paper.url}).status_code == 200
    assert arxiv_feed[-1][1].endswith("/api/papers/2610.00002/feedback") and arxiv_feed[-1][3]["json"] == {"kind": "up"}


def test_saving_still_works_when_arxiv_feed_is_down(monkeypatch):
    monkeypatch.setenv("ARXIV_FEED_URL", "http://feed.test")
    monkeypatch.setenv("ARXIV_FEED_TOKEN", "secret")

    def down(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(feed.httpx, "request", down)
    paper = Paper(url="https://arxiv.org/abs/2610.00003", title="T", authors=[])
    monkeypatch.setattr(extract, "extract", lambda *a, **k: (paper, None))
    response = client.post("/papers", json={"url": paper.url})
    assert response.status_code == 200 and response.json()["title"] == "T"


def test_library_papers_saved_before_connecting_are_backfilled_once(arxiv_feed):
    db.save(Paper(url="https://journal.example/x", title="Old save", authors=[], arxiv_id="arXiv:2207.01501v2"))
    client.get("/feed")
    liked = [call[1] for call in arxiv_feed if call[0] == "POST"]
    assert "http://feed.test/api/papers/2207.01501/feedback" in liked
    client.get("/feed")
    assert [call[1] for call in arxiv_feed if call[0] == "POST"] == liked  # not sent again


def test_summaries_are_written_once_with_the_readers_work(arxiv_feed, monkeypatch):
    from app import llm, pitch
    from app.schemas import Pitch, Pitches

    monkeypatch.setattr(llm.client, "api_key", "test-key")
    asked = []

    def fake_ask(schema, system, prompt, model, effort):
        asked.append(prompt)
        return Pitches(pitches=[Pitch(id="2610.10001", what="Measures X.", why="You fit X."), Pitch(id="other", what="", why="")])

    monkeypatch.setattr(llm, "ask", fake_ask)
    profile = {"name": "Ada", "categories": ["astro-ph.CO"], "mine": [{"id": "1", "title": "My bispectrum paper", "abstract": "A"}], "liked": []}
    monkeypatch.setattr(feed, "profile", lambda: profile)
    paper = {"id": "2610.10001", "title": "New paper", "abstract": "We measure X.", "reasons": {"topics": ["bispectrum"], "authors": []}}

    first = client.post("/feed/summaries", json={"papers": [paper]}).json()
    assert first == {"2610.10001": {"id": "2610.10001", "what": "Measures X.", "why": "You fit X."}}
    assert "My bispectrum paper" in asked[0] and "matched on: bispectrum" in asked[0] and "[2610.10001]" in asked[0]
    assert client.post("/feed/summaries", json={"papers": [paper]}).json() == first
    assert len(asked) == 1  # cached


def test_summaries_explain_a_missing_api_key(arxiv_feed, monkeypatch):
    from app import llm

    monkeypatch.setattr(llm.client, "api_key", None)
    monkeypatch.setattr(llm.client, "auth_token", None)
    paper = {"id": "2610.10002", "title": "T", "abstract": "A"}
    response = client.post("/feed/summaries", json={"papers": [paper]})
    assert response.status_code == 503 and response.json()["detail"]["reason"] == "no_key"
