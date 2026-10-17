from fastapi.testclient import TestClient

from app import db, pins
from app.main import app
from app.schemas import CheckedClaim, Paper, PaperPins

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
        assert pins.claim_problems(paper_pins) == []


def test_claim_rules():
    """The Reproduction card's claims say only what was run, briefly."""
    claim = {"claim": "j₀ is above 1.", "paper": "5.4σ", "rerun": "5.42σ", "status": "holds", "check": "Re-ran the notebooks."}
    fine = PaperPins(reviewed="r", targets=[], claims=[claim], main_problems=["One problem."])
    assert pins.claim_problems(fine) == []
    bad = fine.model_copy(update={"claims": [
        CheckedClaim(**claim | {"status": "untested"}),  # untested, yet a re-run number
        CheckedClaim(**claim | {"rerun": None}),  # holds, with nothing run
        CheckedClaim(**claim | {"check": "word " * 36}),
    ] + [CheckedClaim(**claim)] * 6, "main_problems": ["word " * 46]})
    found = pins.claim_problems(bad)
    assert len(found) == 5 and "9 claims" in found[0] and "claim 1 is \"untested\"" in found[1]
    assert 'claim 2 is "holds" without a `rerun`' in found[2] and "claim 3: `check` has 36 words" in found[3]
    assert "main problem 1 has 46 words" in found[4]
    assert pins.claim_problems(bad) == pins.problems(bad, cosmography())[1 : 1 + 5]  # after "no targets"


def shipped(paper: Paper):
    return pins.for_paper(db.save(paper), paper)  # a library paper without generated pins


def test_pins_only_where_the_caption_matches():
    found = shipped(cosmography())
    assert found and found.reviewed and [t.label for t in found.targets] == ["Figure 1"]
    assert shipped(cosmography(url="https://arxiv.org/pdf/2506.22373"))  # any version or link form finds the file
    # Another layout (caption far below the stored box, or the figure on another page): no pins on the figures, but the
    # claims and the verdict are about the paper, so they stay
    for other in (cosmography(caption_y=600), cosmography(page=3)):
        assert shipped(other).targets == [] and shipped(other).claims == found.claims
    assert shipped(cosmography(url="https://arxiv.org/abs/2401.00001")) is None  # no pins written
    assert shipped(cosmography(url="https://example.org/paper.pdf")) is None  # not an arXiv paper


def test_pins_route():
    paper_id = db.save(cosmography())
    found = client.get(f"/papers/{paper_id}/pins").json()
    assert [t["label"] for t in found["targets"]] == ["Figure 1"]
    figure_1 = next(t for t in pins.load("2506.22373").targets if t.label == "Figure 1")
    assert found["targets"][0]["pins"] == [p.model_dump() for p in figure_1.pins]
    assert [p["kind"] for p in found["targets"][0]["pins"]] == ["data", "concern", "method"]
    other_pdf = client.get(f"/papers/{db.save(cosmography(page=3))}/pins").json()  # no figure matches this PDF...
    assert other_pdf["targets"] == [] and other_pdf["claims"] == found["claims"] != []  # ...but the claims still hold
    assert client.get("/papers/999999/pins").status_code == 404
