import os

from app import zotero

BIB = r"""
@preamble{ "\newcommand{\noopsort}[1]{}" }
@comment{ Zotero export }
@article{doe2022,
  title = {Galaxy power spectrum},
  archivePrefix = {arXiv},
  eprint = {2207.01500},
}
@article{roe2017, title={Old style}, eprint = "hep-th/0101001v2"}
@misc{arxivdoi, doi = {10.48550/arXiv.2207.01501}, publisher = {arXiv}}
@article{journalonly, journal = {arXiv preprint arXiv:2207.01502}}
@online{link, url = {https://arxiv.org/abs/2207.01503v1}}
@article{nonarxiv, title = {A journal-only paper}, doi = {10.1093/mnras/stab123}, eprint = {hal-01234567}}
@article{dupe, eprint = {2207.01500}}
"""


def test_reads_arxiv_ids_from_every_field_zotero_uses(tmp_path):
    path = tmp_path / "library.bib"
    path.write_text(BIB)
    ids, entries = zotero.read(path)
    assert entries == 7  # not the @preamble or @comment
    assert ids == ["2207.01500", "hep-th/0101001", "2207.01501", "2207.01502", "2207.01503"]


def test_link_rereads_when_the_file_changes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import arxiv, db, feed
    from app.main import app
    from helpers import arxiv_paper

    with db.lock, db.conn:
        for table in ("papers", "arxiv_papers", "feed_signals", "feed_meta"):
            db.conn.execute(f"DELETE FROM {table}")
    monkeypatch.setattr(feed, "corpus", None)
    monkeypatch.setattr(arxiv, "recent", lambda c, d: [arxiv_paper("2610.30001", "Galaxy power spectrum today")])
    monkeypatch.setattr(arxiv, "by_ids", lambda ids: [arxiv_paper(i, f"Galaxy paper {i}") for i in ids if i.startswith("2207")])
    client = TestClient(app)

    path = tmp_path / "My Library.bib"
    path.write_text(BIB)
    assert client.post("/feed/zotero", json={"path": str(tmp_path / "nope.bib")}).status_code == 400
    res = client.post("/feed/zotero", json={"path": f'"{path}"'}).json()  # quoted, as copied from Finder
    assert (res["entries"], res["on_arxiv"]) == (7, 5)
    data = client.get("/feed").json()
    assert data["learning"]["positives"] == 5 and data["zotero"]["path"] == str(path)
    assert [p["id"] for p in feed.profile()["zotero"]][:1] and "2207.01500" in {p["id"] for p in feed.profile()["zotero"]}

    path.write_text("@article{one, eprint = {2207.01504}}")
    os.utime(path, (1, 1))  # a different mtime, as when Zotero rewrites the export
    assert client.get("/feed").json()["zotero"]["on_arxiv"] == 1

    path.unlink()
    assert "missing" in client.get("/feed").json()["zotero"]
    client.delete("/feed/zotero")
    data = client.get("/feed").json()
    assert data["zotero"] is None and data["learning"]["positives"] == 0
