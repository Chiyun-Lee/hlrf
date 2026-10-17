import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import arxiv, biorxiv, db, extract, feed, llm
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
# Friday on bioRxiv: a neuroscience preprint and a genomics one.
PREPRINTS = [
    arxiv_paper("10.64898/2026.10.15.000001", "Hippocampal replay during sleep", category="Neuroscience").model_copy(update={"source": "biorxiv"}),
    arxiv_paper("10.64898/2026.10.15.000002", "Long-read assembly of the axolotl genome", category="Genomics").model_copy(update={"source": "biorxiv"}),
]


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    """An empty For you, with arXiv replaced by LISTING (recent) and MINE (by id), and bioRxiv by PREPRINTS."""
    with db.lock, db.conn:
        for table in ("papers", "pitches", "arxiv_papers", "feed_signals", "feed_meta"):
            db.conn.execute(f"DELETE FROM {table}")
    monkeypatch.setattr(feed, "corpus", None)
    calls = {"recent": 0, "fetched": [], "by_ids": []}

    def recent(categories, days):
        calls["recent"] += 1
        calls["fetched"].append(("arxiv", categories, days))
        return LISTING

    def recent_preprints(subjects, days):
        calls["fetched"].append(("biorxiv", subjects, days))
        return [p for p in PREPRINTS if p.categories[0] in subjects]

    def by_ids(ids):
        calls["by_ids"].append(ids)
        return [p for p in MINE if p.id in ids]

    monkeypatch.setattr(arxiv, "recent", recent)
    monkeypatch.setattr(arxiv, "by_ids", by_ids)
    monkeypatch.setattr(biorxiv, "recent", recent_preprints)
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
    an_hour_late()
    monkeypatch.setattr(arxiv, "recent", down)
    data = client.get("/feed").json()
    assert "fetched earlier" in data["notice"] and len(data["papers"]) == 2


def an_hour_late(source="arxiv"):
    """Make the last hourly fetch from `source` two hours old."""
    last = json.loads(db.get_meta(f"fetched:{source}"))
    db.set_meta(f"fetched:{source}", json.dumps({**last, "at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}))


# --- Sources: what to follow on arXiv and bioRxiv ---


def test_sources_start_from_feed_categories_and_are_checked(fresh):
    options = client.get("/feed/sources").json()
    assert options["selected"] == {"arxiv": ["astro-ph.CO"], "biorxiv": []}
    assert options["arxiv"][0]["group"] == "Astrophysics"
    assert {"code": "astro-ph.CO", "name": "Cosmology and Nongalactic Astrophysics"} in options["arxiv"][0]["categories"]
    assert "Neuroscience" in options["biorxiv"] and "Epidemiology" not in options["biorxiv"]  # medRxiv's now

    bad = client.put("/feed/sources", json={"arxiv": ["astro-ph.XX"], "biorxiv": ["Astrology"]})
    assert bad.status_code == 400 and "astro-ph.XX, Astrology" in bad.json()["detail"]["message"]
    empty = client.put("/feed/sources", json={"arxiv": [], "biorxiv": []})
    assert empty.status_code == 400 and "at least one" in empty.json()["detail"]["message"]
    assert client.get("/feed/sources").json()["selected"]["arxiv"] == ["astro-ph.CO"]  # unchanged


def test_following_biorxiv_adds_its_papers_without_refetching_arxiv(fresh):
    client.get("/feed")
    chosen = client.put("/feed/sources", json={"arxiv": ["astro-ph.CO"], "biorxiv": ["Neuroscience"]}).json()
    assert chosen == {"arxiv": ["astro-ph.CO"], "biorxiv": ["Neuroscience"]}
    data = client.get("/feed").json()
    assert data["sources"] == chosen
    papers = {p["id"]: p for p in data["papers"]}
    assert set(papers) == {"2610.30001", "2610.30002", "10.64898/2026.10.15.000001"}  # not the genomics preprint
    preprint = papers["10.64898/2026.10.15.000001"]
    assert (preprint["source"], preprint["abs_url"]) == ("biorxiv", "https://www.biorxiv.org/content/10.64898/2026.10.15.000001v1")
    assert fresh["fetched"] == [("arxiv", ["astro-ph.CO"], feed.FIRST_DAYS), ("biorxiv", ["Neuroscience"], feed.FIRST_DAYS)]

    client.put("/feed/sources", json={"biorxiv": ["Neuroscience"]})
    assert [p["id"] for p in client.get("/feed").json()["papers"]] == ["10.64898/2026.10.15.000001"]
    assert len(fresh["fetched"]) == 2  # nothing new to fetch


def test_a_new_category_fetches_its_month_and_the_rest_stay_hourly(fresh):
    client.get("/feed")
    client.put("/feed/sources", json={"arxiv": ["astro-ph.CO", "cond-mat.str-el"]})
    assert "2610.50001" in {p["id"] for p in client.get("/feed").json()["papers"]}  # the off-category paper, now followed
    assert fresh["fetched"][1:] == [("arxiv", ["cond-mat.str-el"], feed.FIRST_DAYS)]
    an_hour_late()
    client.get("/feed")
    assert fresh["fetched"][2:] == [("arxiv", ["astro-ph.CO", "cond-mat.str-el"], feed.DAYS)]


def test_biorxiv_papers_in_the_library_are_matched_by_doi(fresh):
    client.put("/feed/sources", json={"biorxiv": ["Neuroscience"]})
    db.save(Paper(url="https://www.biorxiv.org/content/10.64898/2026.10.15.000001v1", title="Replay", authors=[]))
    data = client.get("/feed").json()
    assert data["papers"][0]["library_id"] and data["learning"]["positives"] == 1
    assert not any("10.64898/2026.10.15.000001" in ids for ids in fresh["by_ids"])  # never looked up on arXiv
    assert feed.biorxiv_doi("https://www.biorxiv.org/content/10.1101/123456v2.full.pdf") == "10.1101/123456"


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


def test_uploading_a_pdf(monkeypatch):
    """The library's "Add a paper" box: a PDF with or without a link; nothing, or a non-PDF, is refused up front."""
    seen = {}

    def fake_extract(url, meta, html, pdf):
        seen.update(url=url, pdf=pdf)
        return Paper(url=url, title="Uploaded", authors=[]), pdf

    monkeypatch.setattr(extract, "extract", fake_extract)
    pdf = base64.b64encode(b"%PDF-1.5 fake").decode()
    assert client.post("/papers", json={"pdf": pdf}).status_code == 200
    assert seen == {"url": "", "pdf": b"%PDF-1.5 fake"}
    assert client.post("/papers", json={"url": " https://x.org/p ", "pdf": pdf}).status_code == 200
    assert seen["url"] == "https://x.org/p"
    not_pdf = client.post("/papers", json={"pdf": base64.b64encode(b"<html>").decode()})
    assert not_pdf.status_code == 400 and "isn't a PDF" in not_pdf.json()["detail"]
    assert client.post("/papers", json={"url": "  "}).status_code == 400


def test_reader_knows_if_a_paper_is_one_of_yours():
    paper_id = db.save(Paper(url=f"https://arxiv.org/abs/{MINE[0].id}v2", title="T", authors=[]))
    assert client.get(f"/papers/{paper_id}").json()["feed_id"] == MINE[0].id
    assert not client.get(f"/papers/{paper_id}").json()["in_your_papers"]
    assert client.post("/feed/mine", json={"text": MINE[0].id}).status_code == 200
    assert client.get(f"/papers/{paper_id}").json()["in_your_papers"]
    client.delete(f"/feed/mine/{MINE[0].id}")
    assert not client.get(f"/papers/{paper_id}").json()["in_your_papers"]
    other = db.save(Paper(url="https://doi.org/10.1/x", title="Not on arXiv", authors=[]))
    record = client.get(f"/papers/{other}").json()
    assert record["feed_id"] is None and record["in_your_papers"] is False


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


# --- Your published papers: DOIs and journal links ---

from app import published  # noqa: E402

JOURNAL = "10.1093/mnras/stad1234"
WORK = {
    "display_name": "Galaxy bispectrum constraints from a journal",
    "publication_date": "2024-03-05",
    "authorships": [{"author": {"display_name": "A. Author"}}, {"author": {"display_name": "Jane Doe"}}],
    "abstract_inverted_index": {"We": [0], "measure": [1], "the": [2], "bispectrum.": [3]},
    "locations": [{"landing_page_url": f"https://doi.org/{JOURNAL}", "pdf_url": None}],
    "primary_location": {"source": {"display_name": "Monthly Notices of the Royal Astronomical Society"}},
}
OUP = "https://academic.oup.com/mnras/article/527/1/123/7330000"
ELSEVIER = "https://www.sciencedirect.com/science/article/pii/S0370269324001234"


def fake_lookups(monkeypatch, on_arxiv=(), works=(), pages=()):
    """published's lookups: INSPIRE knows {doi: arXiv id}, OpenAlex {doi: work}, and pages {url: (status, html)}.
    Returns every URL asked for."""
    on_arxiv, works, pages = dict(on_arxiv), dict(works), dict(pages)
    asked = []

    def respond(url, status, body):
        kwargs = {"json": body} if isinstance(body, dict) else {"text": body, "headers": {"content-type": "text/html"}}
        return httpx.Response(status, request=httpx.Request("GET", url), **kwargs)

    def get(url, params=None):
        asked.append(url)
        if url.startswith("https://inspirehep.net/api/literature"):
            doi = params["q"].split('"')[1]
            return respond(url, 200, {"hits": {"hits": [{"metadata": {"arxiv_eprints": [{"value": on_arxiv[doi]}]}}] if doi in on_arxiv else []}})
        if url.startswith("https://api.openalex.org/works/https://doi.org/"):
            doi = url.removeprefix("https://api.openalex.org/works/https://doi.org/")
            return respond(url, 200, works[doi]) if doi in works else respond(url, 404, {"error": "not found"})
        if url.startswith("https://api.crossref.org/works/"):
            return respond(url, 404, {})
        raise AssertionError(f"unexpected lookup {url}")

    def get_page(url):
        asked.append(url)
        return respond(url, *pages[url])

    monkeypatch.setattr(published.http, "get", get)
    monkeypatch.setattr(published.pages, "get", get_page)
    return asked


def stored_paper(paper_id):
    return next(p for p, _ in db.all_arxiv() if p.id == paper_id)


def test_dois_and_links_are_found_in_pasted_text():
    text = (
        "see 10.1103/PhysRevD.110.023501. and (doi:10.1007/JHEP01(2024)123), "
        "https://iopscience.iop.org/article/10.3847/1538-4357/ad1234/pdf https://doi.org/10.48550/arXiv.2207.01501 "
        "https://www.nature.com/articles/s41550-024-02225-0 https://www.biorxiv.org/content/10.1101/2024.01.01.123456v2.full "
        "https://onlinelibrary.wiley.com/doi/10.1002%2Fanie.202400001?af=R https://inspirehep.net/literature/2612345 "
        f"{OUP} https://arxiv.org/abs/2207.01502 https://inspirehep.net/authors/1960608"
    )
    found = published.find(text)
    assert found.dois == [
        "10.3847/1538-4357/ad1234",  # without the /pdf after it
        "10.1038/s41550-024-02225-0",  # from the nature.com address
        "10.1101/2024.01.01.123456",  # without bioRxiv's version and .full
        "10.1002/anie.202400001",  # decoded, without the query
        "10.1103/physrevd.110.023501",  # without the full stop; DOIs are case-insensitive
        "10.1007/jhep01(2024)123",  # its own brackets kept, the sentence's dropped
    ]
    assert (found.arxiv, found.records, found.links) == (["2207.01501"], ["2612345"], [OUP])
    assert feed.ids_in(text) == ["2207.01502"]  # no arXiv ids read out of the DOIs


def test_published_papers_join_your_papers(fresh, monkeypatch):
    fake_lookups(
        monkeypatch,
        on_arxiv={"10.1103/physrevd.110.023501": "2207.01500"},
        works={JOURNAL: WORK, "10.1093/mnras/stad9999": {**WORK, "display_name": "Found from its page"}},
        pages={OUP: (200, '<meta name="citation_doi" content="10.1093/mnras/stad9999">'), ELSEVIER: (403, "Just a moment...")},
    )
    text = f"10.1103/PhysRevD.110.023501 https://doi.org/10.1093/MNRAS/stad1234 10.9999/nothing {OUP} {ELSEVIER}"
    res = client.post("/feed/mine", json={"text": text}).json()
    assert res["published"] == {"added": 3, "on_arxiv": 1, "not_found": ["10.9999/nothing"], "unreadable": [ELSEVIER], "unreachable": []}

    data = client.get("/feed").json()
    assert {p["id"] for p in data["mine"]} == {"2207.01500", JOURNAL, "10.1093/mnras/stad9999"}  # the arXiv version for the first
    assert data["method"] == "model"  # three of your papers: the list is ranked by them
    paper = stored_paper(JOURNAL)
    assert (paper.source, paper.abstract, paper.authors) == ("doi", "We measure the bispectrum.", ["A. Author", "Jane Doe"])
    assert (paper.journal_ref, paper.abs_url) == ("Monthly Notices of the Royal Astronomical Society", f"https://doi.org/{JOURNAL}")
    assert JOURNAL in json.dumps(feed.profile()["mine"])  # and the summaries' "why you'd care" read it

    assert client.delete("/feed/mine/10.1093%2Fmnras%2Fstad1234").status_code == 204
    assert JOURNAL not in {p["id"] for p in client.get("/feed").json()["mine"]}


def test_a_doi_for_you_already_has_keeps_its_record(fresh, monkeypatch):
    client.put("/feed/sources", json={"biorxiv": ["Neuroscience"]})
    client.get("/feed")
    asked = fake_lookups(monkeypatch)
    res = client.post("/feed/mine", json={"text": "https://www.biorxiv.org/content/10.64898/2026.10.15.000001v1"}).json()
    assert res["published"]["added"] == 1 and asked == []  # no lookups
    assert stored_paper("10.64898/2026.10.15.000001").source == "biorxiv"  # still in the day's papers


def test_links_to_this_machine_or_a_private_network_are_refused():
    for url in ("http://127.0.0.1:8000/papers", "http://localhost/admin", "http://192.168.1.1/", "file:///etc/passwd"):
        with pytest.raises(published.PageError):
            published.check_public(url)
    published.check_public("https://8.8.8.8/")  # a public address is fine
    assert published.resolve_link("http://127.0.0.1:8000/papers").problem == "unreadable"  # refused before connecting
