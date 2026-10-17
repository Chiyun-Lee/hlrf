from fastapi.testclient import TestClient

from app import db, pins
from app.main import app
from app.schemas import Paper

client = TestClient(app)


def cosmography(url="https://arxiv.org/abs/2506.22373v2", caption_y=431, page=2) -> Paper:
    """A stand-in for arXiv:2506.22373: Figure 1's caption sits just below its box on page 3, as in the real PDF."""
    pages = [{"blocks": [], "width": 612, "height": 792} for _ in range(7)]
    pages[page]["blocks"] = [{"text": "Figure 1. Relative differences between the cosmographic expansion", "bbox": [54, caption_y, 562, 461]}]
    return Paper(url=url, title="Cosmography with DESI DR2 and SN data", authors=[], pages=pages)


def test_shipped_pins_are_short_and_readable():
    for path in pins.PINS_DIR.glob("*.json"):
        paper_pins = pins.load(path.stem)
        assert paper_pins and paper_pins.arxiv_id == path.stem.replace("_", "/")
        for target in paper_pins.targets:
            x0, y0, x1, y1 = target.bbox
            assert 0 <= x0 < x1 and 0 <= y0 < y1 and target.pins
            kinds = [pin.kind for pin in target.pins]
            assert kinds[0] == "data" and kinds.count("data") == 1, (target.label, kinds)  # data provenance leads
            for pin in target.pins:
                assert len(pin.title.split()) <= 4, pin.title
                assert len(pin.basic.split()) <= 22, pin.basic
                assert len(pin.researcher.split()) <= 45, pin.researcher


def test_pins_only_where_the_caption_matches():
    found = pins.for_paper(cosmography())
    assert found and found.reviewed and [t.label for t in found.targets] == ["Figure 1"]
    assert pins.for_paper(cosmography(url="https://arxiv.org/pdf/2506.22373"))  # any version or link form finds the file
    assert pins.for_paper(cosmography(caption_y=600)) is None  # caption far below the stored box: another layout
    assert pins.for_paper(cosmography(page=3)) is None  # figure moved to another page
    assert pins.for_paper(cosmography(url="https://arxiv.org/abs/2401.00001")) is None  # no pins written
    assert pins.for_paper(cosmography(url="https://example.org/paper.pdf")) is None  # not an arXiv paper


def test_pins_route():
    paper_id = db.save(cosmography())
    found = client.get(f"/papers/{paper_id}/pins").json()
    assert [t["label"] for t in found["targets"]] == ["Figure 1"]
    assert [p["kind"] for p in found["targets"][0]["pins"]] == ["data", "concern", "method"]
    assert client.get(f"/papers/{db.save(cosmography(page=3))}/pins").json() is None
    assert client.get("/papers/999999/pins").status_code == 404
