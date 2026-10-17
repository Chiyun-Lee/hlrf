import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import cards, db
from app.cards import clean, crop_figures, notes_hash, stated
from app.main import app
from app.schemas import ChartItem, PageSummary, Paper, SummaryCards

PAPER = Paper(
    url="u",
    title="T",
    authors=[],
    pages=[{"blocks": [{"text": "We find Ωm = 0.2975 ± 0.0086 and H0 = 68.50 ± 0.58, with a 2.3 σ tension."}]}],
)
NOTES = [PageSummary(notes=[{"kind": "summary", "blocks": [0], "bullets": ["x"]}, {"kind": "figure", "blocks": [0], "bullets": ["y"]}])]


def deck(**overrides) -> SummaryCards:
    base = dict(
        tldr="A takeaway.",
        stats=[{"value": "2.3σ", "label": "tension"}] * 6,
        flow=[{"title": "Q", "detail": "d"}],
        topic="BAO",
        mindmap=[{"title": "b", "points": ["p"]}] * 5,
        findings=["f"],
        evidence=[{"claim": "c", "evidence": "e"}],
        caveats=["c"],
    )
    return SummaryCards.model_validate(base | overrides)


def item(printed, value, low=None, high=None):
    return ChartItem(label="x", value=value, low=low, high=high, printed=printed)


def test_numbers_must_be_printed_in_the_paper():
    text = "Ωm=0.2975±0.0086andH0=68.50±0.58"
    assert stated(item("0.2975 ± 0.0086", 0.2975), text)
    assert stated(item("68.50", 68.5), text)
    assert not stated(item("0.3169 ± 0.0065", 0.3169), text)  # not in the text
    assert not stated(item("0.2975", 0.31), text)  # value doesn't match what's printed
    assert not stated(item("about a third", 0.33), text)


def test_clean_trims_and_drops_bad_content():
    cards = deck(
        charts=[
            {"title": "real", "axis": "Ωm", "source": "text", "caption": "c",
             "items": [item("0.2975 ± 0.0086", 0.2975, 0.2889, 0.3061), item("68.50", 68.5, 70, 71)]},
            {"title": "made up", "axis": "x", "source": "?", "caption": "c", "items": [item("1.234", 1.234), item("5.678", 5.678)]},
        ],
        figures=[{"figure": "p0n1", "callout": "fig"}, {"figure": "p0n0", "callout": "not a figure"},
                 {"figure": "p9n9", "callout": "missing"}, {"figure": "p0n1", "callout": "duplicate"}],
    )
    cards = clean(cards, PAPER, NOTES)
    assert len(cards.stats) == 4 and len(cards.mindmap) == 4
    assert [c.title for c in cards.charts] == ["real"]
    assert cards.charts[0].items[1].low is None  # interval not containing the value is dropped
    assert [f.figure for f in cards.figures] == ["p0n1"]


def test_clean_rejects_empty_deck():
    with pytest.raises(RuntimeError):
        clean(deck(tldr=" "), PAPER, NOTES)


def test_figures_are_cropped_from_the_pdf():
    """Runs the real crop (app/abstract.py) on a one-page PDF with a drawn figure above its caption."""
    with pymupdf.open() as doc:
        page = doc.new_page(width=600, height=800)
        page.draw_rect(pymupdf.Rect(100, 100, 500, 400), color=(0, 0, 0), fill=(0.2, 0.4, 0.8))
        page.insert_text((100, 430), "Figure 1. A blue box.")
        pdf = doc.tobytes()
    paper = Paper(url="u", title="T", authors=[], pages=[{"width": 600, "height": 800, "blocks": [
        {"text": "Figure 1. A blue box.", "bbox": [100, 418, 300, 434]}]}])
    notes = [PageSummary(notes=[{"kind": "figure", "blocks": [0], "bullets": ["y"]}])]
    cards = deck(figures=[{"figure": "p0n0", "callout": "look"}])
    [figure] = crop_figures(cards, paper, notes, pdf)
    assert figure.image.startswith("data:image/png;base64,") and figure.width > 300 and figure.height > 250


def test_cards_say_when_the_notes_have_changed(monkeypatch):
    """A deck remembers the notes it was made from: editing a note (a tutor's edit, the reader's own) flags it, and
    undoing the edit clears the flag."""
    client = TestClient(app)
    monkeypatch.setattr(cards.llm, "ask", lambda *a, **k: deck())
    pid = db.save(PAPER)
    for level in ("outreach", "researcher"):
        db.save_summary(pid, 0, level, NOTES[0])
    assert client.post(f"/papers/{pid}/cards").json()["notes_changed"] is False
    assert client.get(f"/papers/{pid}/cards").json()["notes_changed"] is False

    note = NOTES[0].notes[0].model_dump()
    client.put(f"/papers/{pid}/pages/0/notes/0", json=note | {"bullets": ["x, said better"]})
    assert client.get(f"/papers/{pid}/cards").json()["notes_changed"] is True
    client.put(f"/papers/{pid}/pages/0/notes/0", json=note)  # undo
    assert client.get(f"/papers/{pid}/cards").json()["notes_changed"] is False

    client.put(f"/papers/{pid}/pages/0/notes/0?level=researcher", json=note | {"bullets": ["other level"]})
    assert client.get(f"/papers/{pid}/cards").json()["notes_changed"] is False  # each level's deck has its own notes
    assert client.post(f"/papers/{pid}/cards").json()["notes_changed"] is False  # a remake is up to date again


def test_notes_hash_ignores_asides():
    aside = PageSummary(notes=[*NOTES[0].notes, {"kind": "aside", "blocks": [0], "bullets": ["a margin note"]}])
    assert notes_hash([aside]) == notes_hash(NOTES) != notes_hash([PageSummary(notes=NOTES[0].notes[:1])])
