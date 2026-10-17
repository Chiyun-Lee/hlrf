from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import arxiv, db, extract, feed, llm
from app.main import app
from app.schemas import Paper, Pitch, Pitches
from helpers import COSMOLOGY, FRIDAY, QUBITS, THURSDAY, arxiv_paper

client = TestClient(app)

# Friday's listing: one cosmology paper and one off-topic one among the qubit papers; Thursday's: five more.
LISTING = [
    arxiv_paper("2610.30001", "Galaxy clustering bispectrum analysis with the effective field theory"),
    arxiv_paper("2610.30002", "Transmon qubit error correction with superconducting couplers"),
    *[arxiv_paper(f"2610.4000{i}", t, day=THURSDAY) for i, t in enumerate(QUBITS + ["Dark sirens"])],
    arxiv_paper("2610.50001", "Off-category paper", category="cond-mat.str-el"),
]
MINE = [arxiv_paper(f"2207.0150{i}", t, day=THURSDAY - timedelta(days=900)) for i, t in enumerate(COSMOLOGY)]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """An empty For you, with arXiv replaced by LISTING (recent) and MINE (by id)."""
    with db.lock, db.conn:
        for table in ("papers", "pitches", "arxiv_papers", "feed_signals", "feed_meta"):
            db.conn.execute(f"DELETE FROM {table}")
    monkeypatch.setattr(feed, "corpus", None)
    calls = {"recent": 0, "by_ids": []}

    def recent(categories, days):
        calls["recent"] += 1
        return LISTING

    def by_ids(ids):
        calls["by_ids"].append(ids)
        return [p for p in MINE if p.id in ids]

    monkeypatch.setattr(arxiv, "recent", recent)
    monkeypatch.setattr(arxiv, "by_ids", by_ids)
    return calls


@pytest.mark.parametrize(
    "url, claimed, expected",
    [
        ("https://arxiv.org/abs/2410.01234v2", None, "2410.01234"),
        ("https://arxiv.org/pdf/2410.01234", None, "2410.01234"),
        ("http://arxiv.org/abs/hep-th/0101001v1", None, "hep-th/0101001"),
        ("https://doi.org/10.1000/x", "arXiv:2410.01234v3", "2410.01234"),
        ("https://doi.org/10.1000/x", "not an id", None),
    ],
)
def test_arxiv_id(url, claimed, expected):
    assert feed.arxiv_id(url, claimed) == expected


def test_ids_in_pasted_text():
    text = "2207.01501, https://arxiv.org/abs/2502.01722v2\nhep-th/0101001 and 2207.01501 again; not 12207.015011"
    assert feed.ids_in(text) == ["2207.01501", "2502.01722", "hep-th/0101001"]
    assert feed.ids_in("https://inspirehep.net/authors/1960608 and astro-ph.CO/0601001") == ["astro-ph.CO/0601001"]


def test_latest_listing_newest_first_until_you_add_your_papers(fresh):
    data = client.get("/feed").json()
    assert (data["day"], data["older"], data["newer"]) == ("2026-10-16", "2026-10-15", None)
    assert data["method"] == "newest" and data["learning"] == {"positives": 0, "needed": 3}
    assert {p["id"] for p in data["papers"]} == {"2610.30001", "2610.30002"}  # not the off-category paper
    assert data["progress"] == {"goal": 2, "sorted": 0, "streak": 0}  # only two papers that day
    client.get("/feed?day=2026-10-15")
    assert fresh["recent"] == 1  # fetched once, then at most hourly


def test_your_papers_rank_the_list(fresh):
    response = client.post("/feed/mine", json={"text": "2207.01500 2207.01501, arxiv.org/abs/2207.01502v1 9999.99999"})
    assert response.json()["added"] == ["2207.01500", "2207.01501", "2207.01502"]
    assert (response.json()["unknown"], response.json()["profile"]) == (["9999.99999"], None)
    data = client.get("/feed").json()
    assert data["method"] == "model"
    assert [p["id"] for p in data["papers"]] == ["2610.30001", "2610.30002"]
    assert data["papers"][0]["score"] > data["papers"][1]["score"] and data["papers"][0]["reasons"]["topics"]
    assert [p["id"] for p in data["mine"]] == ["2207.01502", "2207.01501", "2207.01500"]
    assert data["older"] == "2026-10-15"  # your old papers don't add listing days

    client.delete("/feed/mine/2207.01502")
    assert client.get("/feed").json()["method"] == "newest"
    client.post("/feed/mine", json={"text": "9999.99999"})
    assert sum("9999.99999" in ids for ids in fresh["by_ids"]) == 1  # remembered as unknown, not asked again


def test_pasting_no_ids_explains(fresh):
    response = client.post("/feed/mine", json={"text": "my thesis"})
    assert response.status_code == 400 and "arXiv ids" in response.json()["detail"]["message"]


def test_library_papers_count_as_liked(fresh):
    db.save(Paper(url="https://journal.example/x", title="Saved", authors=[], arxiv_id="arXiv:2207.01501v2"))
    data = client.get("/feed").json()
    assert data["learning"]["positives"] == 1
    assert ["2207.01501"] in fresh["by_ids"]  # fetched so the ranking can read it
    db.save(Paper(url="https://arxiv.org/abs/2610.30001", title="From For you", authors=[]))
    assert {p["id"]: p["library_id"] for p in client.get("/feed").json()["papers"]}["2610.30001"]


def test_feedback_goal_and_streak(fresh):
    client.get("/feed")

    def sort(paper_id, kind="up"):
        return client.post(f"/feed/{paper_id}/feedback", json={"kind": kind}).json()

    for i in range(4):
        sort(f"2610.4000{i}", "down" if i % 2 else "up")
    assert sort("2610.40004")["progress"] == {"goal": 5, "sorted": 5, "streak": 1}  # Thursday done, Friday open
    assert sort("2610.30001")["feedback"] == "up"
    assert sort("2610.30001")["feedback"] == "up"  # setting, not toggling: repeats change nothing
    assert sort("2610.30002", "down")["progress"] == {"goal": 2, "sorted": 2, "streak": 2}
    assert sort("2610.30002", "click")["feedback"] == "down"
    assert sort("2610.40000", "none")["progress"]["streak"] == 1  # Thursday undone breaks the chain behind Friday
    assert client.post("/feed/2610.30001/feedback", json={"kind": "maybe"}).status_code == 422


def test_arxiv_down(fresh, monkeypatch):
    def down(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(arxiv, "recent", down)
    response = client.get("/feed")
    assert response.status_code == 503 and response.json()["detail"]["reason"] == "unreachable"

    monkeypatch.setattr(arxiv, "recent", lambda c, d: LISTING)
    client.get("/feed")
    db.set_meta("fetched_at", (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())
    monkeypatch.setattr(arxiv, "recent", down)
    data = client.get("/feed").json()
    assert "fetched earlier" in data["notice"] and len(data["papers"]) == 2


def test_summaries_are_written_once_from_your_papers(fresh, monkeypatch):
    client.post("/feed/mine", json={"text": "2207.01501"})
    monkeypatch.setattr(llm.client, "api_key", "test-key")
    asked = []

    def fake_ask(schema, system, prompt, model, effort):
        asked.append(prompt)
        return Pitches(pitches=[Pitch(id="2610.30001", what="Measures X.", why="You fit X."), Pitch(id="other", what="", why="")])

    monkeypatch.setattr(llm, "ask", fake_ask)
    paper = {"id": "2610.30001", "title": "New", "abstract": "We measure X.", "reasons": {"topics": ["bispectrum"], "authors": []}}
    first = client.post("/feed/summaries", json={"papers": [paper]}).json()
    assert first == {"2610.30001": {"id": "2610.30001", "what": "Measures X.", "why": "You fit X."}}
    assert COSMOLOGY[1] in asked[0] and "matched on: bispectrum" in asked[0] and "[2610.30001]" in asked[0]
    assert client.post("/feed/summaries", json={"papers": [paper]}).json() == first
    assert len(asked) == 1  # cached


def test_summaries_explain_a_missing_api_key(monkeypatch):
    monkeypatch.setattr(llm.client, "api_key", None)
    monkeypatch.setattr(llm.client, "auth_token", None)
    response = client.post("/feed/summaries", json={"papers": [{"id": "2610.10002", "title": "T", "abstract": "A"}]})
    assert response.status_code == 503 and response.json()["detail"]["reason"] == "no_key"


def test_saving_a_paper_still_works(monkeypatch):
    paper = Paper(url="https://arxiv.org/abs/2610.00003", title="T", authors=[])
    monkeypatch.setattr(extract, "extract", lambda *a, **k: (paper, None))
    response = client.post("/papers", json={"url": paper.url})
    assert response.status_code == 200 and response.json()["title"] == "T"


# --- Your papers from a profile ---

from app import profiles  # noqa: E402

INSPIRE_URL = "https://inspirehep.net/authors/1960608"


def fake_get(responses):
    """profiles.http.get serving {url prefix: (status, body)}; returns the URLs asked for."""
    asked = []

    def get(url, params=None):
        asked.append((url, params))
        status, body = next(v for k, v in responses.items() if url.startswith(k))
        kwargs = {"json": body} if isinstance(body, dict) else {"text": body}
        return httpx.Response(status, request=httpx.Request("GET", url), **kwargs)

    return get, asked


def inspire_hits(*ids):
    return {"hits": {"hits": [{"metadata": {"arxiv_eprints": [{"value": i}]}} for i in ids] + [{"metadata": {}}]}}


def test_profile_links_are_recognised():
    assert profiles.find(f"my profile: {INSPIRE_URL}?ui-citation-summary=true") == {"kind": "inspire", "id": "1960608", "url": INSPIRE_URL}
    assert profiles.find("2207.01501") is None


def test_inspire_profile_loads_your_papers(fresh, monkeypatch):
    get, asked = fake_get({"https://inspirehep.net/api/literature": (200, inspire_hits("2207.01500", "2207.01501", "2207.01502"))})
    monkeypatch.setattr(profiles.http, "get", get)
    res = client.post("/feed/mine", json={"text": INSPIRE_URL}).json()
    assert res["added"] == ["2207.01500", "2207.01501", "2207.01502"]
    assert (res["profile"], res["from_profile"], res["off_arxiv"]) == ("INSPIRE", 3, 1)
    assert asked[0][1]["q"] == "authors.recid:1960608"
    data = client.get("/feed").json()
    assert data["method"] == "model" and data["profiles"] == [{"url": INSPIRE_URL, "label": "INSPIRE"}]




def test_daily_sync_adds_new_papers_but_not_removed_ones(fresh, monkeypatch):
    get, _ = fake_get({"https://inspirehep.net/api/literature": (200, inspire_hits("2207.01500", "2207.01501"))})
    monkeypatch.setattr(profiles.http, "get", get)
    client.post("/feed/mine", json={"text": INSPIRE_URL})
    client.delete("/feed/mine/2207.01501")

    get, _ = fake_get({"https://inspirehep.net/api/literature": (200, inspire_hits("2207.01500", "2207.01501", "2207.01503"))})
    monkeypatch.setattr(profiles.http, "get", get)
    assert feed.due_profiles() == []  # just synced
    monkeypatch.setattr(feed, "PROFILE_SYNC_EVERY", timedelta(0))
    feed.sync_profiles()
    mine = [p["id"] for p in client.get("/feed").json()["mine"]]
    assert set(mine) == {"2207.01500", "2207.01503"}  # the new paper, not the one you removed

    client.delete(f"/feed/profiles?url={INSPIRE_URL}")
    assert feed.linked() == [] and len(client.get("/feed").json()["mine"]) == 2  # papers stay


def test_the_day_being_ranked_is_never_a_training_example(fresh, monkeypatch):
    client.post("/feed/mine", json={"text": "2207.01500 2207.01501 2207.01502"})
    seen = {}
    real_train = feed.ranker.train

    def train(corpus, pool, positives, negatives):
        seen["pool_days"] = {p.listing_date for p in pool}
        return real_train(corpus, pool, positives, negatives)

    monkeypatch.setattr(feed.ranker, "train", train)
    client.get("/feed?day=2026-10-16")
    assert FRIDAY not in seen["pool_days"] and THURSDAY in seen["pool_days"]
