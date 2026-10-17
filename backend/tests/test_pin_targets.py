"""Finding a PDF's figures and tables (pins.targets), checking pins (pins.problems) and storing an agent review's pins,
on PDFs drawn here with PyMuPDF."""

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db, pins
from app.extract import pdf_pages
from app.main import app
from app.schemas import Paper, PaperPins, Pin

from test_pins import cosmography

client = TestClient(app)
WORDS = "The fitted curve follows the measured points closely across the whole range of scales that we consider here. "


def text(page, rect, words, size=10):
    """A paragraph filling `rect` from its top; a single line when `rect` is only a line high."""
    if rect[3] - rect[1] < 2 * size:
        page.insert_text((rect[0], rect[1] + size), words, fontsize=size)
    else:
        assert page.insert_textbox(pymupdf.Rect(rect), words, fontsize=size) >= 0, "text doesn't fit"


def plot(page, rect):
    """A vector plot: a white background (paper, not ink), axes, a curve and tick labels below the axes."""
    x0, y0, x1, y1 = rect
    page.draw_rect((x0 - 30, y0 - 10, x1 + 30, y1 + 30), color=None, fill=(1, 1, 1))
    page.draw_rect(rect, color=(0, 0, 0), width=0.8)
    page.draw_polyline([(x0 + 10 * k, y1 - (k * k) % (y1 - y0)) for k in range(int((x1 - x0) / 10))], color=(0, 0, 1))
    text(page, (x0, y1 + 3, x1, y1 + 16), "0     1     2     3     4", size=8)


def ruled_table(page, x0, x1, y0, rows=4):
    """A booktabs table: top, mid and bottom rules around rows of short cells. Returns its bottom."""
    page.draw_line((x0, y0), (x1, y0))
    text(page, (x0 + 4, y0 + 3, x1, y0 + 16), "Sample    z    Value    Error")
    page.draw_line((x0, y0 + 18), (x1, y0 + 18))
    for k in range(rows):
        text(page, (x0 + 4, y0 + 21 + 13 * k, x1, y0 + 34 + 13 * k), f"S{k}    0.{k}5    {k}.27    0.0{k}")
    bottom = y0 + 24 + 13 * rows
    page.draw_line((x0, bottom), (x1, bottom))
    return bottom


def make_pdf() -> bytes:
    doc = pymupdf.open()
    # Page 0, one column: a vector plot with its caption below, then text that mentions a figure but isn't a caption.
    page = doc.new_page(width=612, height=792)
    text(page, (72, 60, 540, 140), WORDS * 3)
    plot(page, (150, 150, 460, 330))
    text(page, (72, 360, 540, 390), "Figure 1. A vector plot of the fit, with tick labels below its axes.")
    text(page, (72, 420, 540, 470), "Figure 2 shows the same data as an image. " + WORDS * 2)
    text(page, (72, 480, 540, 540), WORDS + "As shown in Figure 2, the points scatter. " + WORDS)
    # Page 1: an image figure (caption "Fig. 2:") and a table with its caption above.
    page = doc.new_page(width=612, height=792)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 30), False)
    pix.clear_with(90)
    page.insert_image(pymupdf.Rect(120, 70, 490, 300), pixmap=pix)
    text(page, (72, 312, 540, 340), "Fig. 2: The same data, as an image.")
    text(page, (72, 370, 540, 420), WORDS * 2)
    text(page, (72, 440, 540, 455), "Table 1: Numbers in a table, caption above.")
    ruled_table(page, 150, 460, 462)
    text(page, (72, 600, 540, 680), WORDS * 3)
    # Page 2, two columns: a figure in the left column, a table in the right one, text around both.
    page = doc.new_page(width=612, height=792)
    text(page, (54, 60, 296, 200), WORDS * 3)
    plot(page, (90, 220, 270, 360))
    text(page, (54, 390, 296, 420), "FIG. 3. A plot in the left column.")
    text(page, (54, 440, 296, 700), WORDS * 6)
    text(page, (316, 60, 558, 200), WORDS * 3)
    text(page, (316, 220, 558, 245), "TABLE II. A table in the right column.")
    bottom = ruled_table(page, 330, 545, 252)
    text(page, (316, bottom + 20, 558, 700), WORDS * 6)
    return doc.tobytes()


@pytest.fixture(scope="module")
def drawn():
    pdf = make_pdf()
    return Paper(url="https://example.org/drawn.pdf", title="Drawn", authors=[], pages=pdf_pages(pdf)), pdf


def near(bbox, expected, tol=8):
    return all(abs(a - b) <= tol for a, b in zip(bbox, expected))


def test_targets_finds_figures_and_tables(drawn):
    paper, pdf = drawn
    found = {t.label: t for t in pins.targets(paper, pdf)}
    assert list(found) == ["Figure 1", "Figure 2", "Table 1", "Figure 3", "Table II"]  # in-text "Figure 2 shows" doesn't count
    assert [found[k].caption for k in found] == ["Figure 1.", "Fig. 2:", "Table 1:", "FIG. 3.", "TABLE II."]
    assert [found[k].page for k in found] == [0, 1, 1, 2, 2]
    assert near(found["Figure 1"].bbox, (150, 150, 460, 346))  # the axes and their tick labels, not the white backdrop
    assert near(found["Figure 2"].bbox, (151, 70, 459, 300))  # the picture keeps its 4:3 shape
    assert near(found["Table 1"].bbox, (150, 462, 460, 538))
    assert near(found["Figure 3"].bbox, (90, 220, 270, 376))
    assert near(found["Table II"].bbox, (330, 252, 545, 328))
    assert all(pins.fits(t, paper) and not t.pins for t in found.values())


def pin(kind="data", title="Where data come from", basic="Plain words.", researcher="Precise words.", evidence="From the paper"):
    return Pin(kind=kind, title=title, basic=basic, researcher=researcher, evidence=evidence)


def reviewed(found, **changes) -> PaperPins:
    targets = [t.model_copy(update={"pins": [pin(), pin("concern", "A worry")]}) for t in found]
    return PaperPins(reviewed="Agent review: the code re-run, 17 Oct 2026", verdict="Solid.", targets=targets).model_copy(update=changes)


def test_problems_name_the_target_and_the_fix(drawn):
    paper, pdf = drawn
    found = pins.targets(paper, pdf)
    assert pins.problems(reviewed(found), paper, found) == []
    assert [i[:22] for i in pins.problems(reviewed(found, reviewed=" "), paper, found)] == ["`reviewed` is empty: s"]

    good = reviewed(found)
    t = good.targets[0]
    t.bbox = [150, 30, 460, 120]  # nowhere near its caption
    t.pins = [pin("method", "Step"), pin(), pin(), pin("concern", "One"), pin("concern", "Two")]
    t.pins[3].title = "Far too many title words"
    t.pins[4].basic = "word " * 23
    good.targets.append(good.targets[1].model_copy())
    issues = pins.problems(good, paper, found)
    assert any(i.startswith("Figure 1: no caption") and "copy its page (0)" in i for i in issues)
    assert "Figure 1 has 2 Data provenance pins" in " ".join(issues)
    assert any(i.startswith("Figure 1 has 5 pins") for i in issues)
    assert any(i.startswith('Figure 1, pin "Far too many title words": `title` has 5 words') for i in issues)
    assert any("`basic` has 23 words" in i for i in issues)
    assert "Figure 2 appears twice: merge its pins into one target" in issues

    t = reviewed(found).targets[2]
    t.pins.reverse()
    assert pins.problems(PaperPins(reviewed="x", targets=[t]), paper) == ['Table 1: put its Data provenance pin (kind "data") first']
    assert pins.problems(PaperPins(reviewed="x", targets=[]), paper)[0].startswith("no targets")


def test_generated_pins_are_stored_and_served_first(drawn):
    paper, pdf = drawn
    paper_id = db.save(paper, pdf)
    assert db.get_paper_pins(paper_id) is None and not pins.has_pins(paper_id, paper.url, None)
    generated = reviewed(pins.targets(paper, pdf))
    pins.save(paper_id, generated)
    assert db.get_paper_pins(paper_id) == generated and pins.has_pins(paper_id, paper.url, None)
    assert pins.for_paper(paper_id, paper) == generated
    assert client.get(f"/papers/{paper_id}/pins").json()["verdict"] == "Solid."
    assert db.delete(paper_id) and db.get_paper_pins(paper_id) is None


def test_route_prefers_generated_over_shipped():
    paper = cosmography()
    paper_id = db.save(paper)
    assert pins.has_pins(paper_id, paper.url, None)  # shipped for its arXiv id
    shipped = client.get(f"/papers/{paper_id}/pins").json()
    assert shipped["arxiv_id"] == "2506.22373" and shipped["verdict"] is None
    figure = PaperPins.model_validate(shipped).targets[0]
    mine = PaperPins(reviewed="Agent review, 17 Oct 2026", verdict="Fine.", targets=[figure.model_copy(update={"pins": [pin()]})])
    pins.save(paper_id, mine)
    assert client.get(f"/papers/{paper_id}/pins").json() == mine.model_dump()


def test_fits_takes_a_caption_above_or_below():
    paper = cosmography(caption_y=431)
    below = pins.load("2506.22373").targets[0].model_copy(update={"label": "Figure 1", "caption": "Figure 1.", "page": 2, "bbox": [105, 52, 511, 418]})
    assert pins.fits(below, paper)
    above = below.model_copy(update={"bbox": [105, 470, 511, 600]})  # caption block ends at 461, 9 points above
    assert pins.fits(above, paper)
    assert not pins.fits(above.model_copy(update={"bbox": [105, 520, 511, 600]}), paper)  # 59 points: too far
    assert not pins.fits(below.model_copy(update={"caption": "Figure 1:"}), paper)  # caption printed otherwise
    assert not pins.fits(below.model_copy(update={"caption": "Figure 1", "label": "Figure 10"}), cosmography(caption_y=431).model_copy(
        update={"pages": [p.model_copy(update={"blocks": [b.model_copy(update={"text": "Figure 10. Other"}) for b in p.blocks]}) for p in paper.pages]}
    ))  # "Figure 1" isn't "Figure 10"
