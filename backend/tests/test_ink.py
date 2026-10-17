"""Writing on a paper and asking about it (app/ink.py): saving the ink, and what an Ask sends Claude."""

import pytest
from fastapi.testclient import TestClient

from app import db, ink, llm, memory
from app.main import app
from app.schemas import Block, InkAnswer, Page, Paper

client = TestClient(app)

STROKE = {"id": "s1", "page": 0, "tool": "pen", "color": "#1f2f7a", "width": 1.6, "points": [[10, 20, 0.5], [30, 40, 0.6]]}
TEXT = {"id": "t1", "page": 1, "x": 420, "y": 100, "w": 180, "text": "check Table 2\nvs RNNs", "color": "#b0181c"}
CARD = {"id": "c1", "page": 0, "x": 300, "y": 20, "w": 240, "read": ["why √d_k?"], "answer": "Because **scale** (p. 4).", "collapsed": False, "created": "2026-10-17T12:00:00Z"}


@pytest.fixture
def paper_id():
    with db.lock, db.conn:
        db.conn.execute("DELETE FROM papers")
        db.conn.execute("DELETE FROM ink")
    pages = [Page(blocks=[Block(text=f"Text of page {i + 1}.", bbox=[0, 0, 100, 10])], width=612, height=792) for i in range(3)]
    return db.save(Paper(url="https://arxiv.org/abs/x", title="Attention", authors=[], pages=pages))


def test_ink_is_saved_and_deleted_with_its_paper(paper_id):
    assert client.get(f"/papers/{paper_id}/ink").json() == {"strokes": [], "texts": [], "cards": []}
    saved = {"strokes": [STROKE], "texts": [TEXT], "cards": [CARD]}
    assert client.put(f"/papers/{paper_id}/ink", json=saved).status_code == 200
    assert client.get(f"/papers/{paper_id}/ink").json() == saved
    db.delete(paper_id)
    assert client.get(f"/papers/{paper_id}/ink").status_code == 404
    assert db.get_ink(paper_id).strokes == []


def test_ask_sends_the_screen_the_paper_and_earlier_answers(paper_id, monkeypatch):
    calls = []

    def fake_ask(schema, system, prompt, model, effort):
        calls.append((schema, system, prompt))
        return InkAnswer(read=["why √d_k? (next to Eq. 1)"], answer="To keep the softmax from saturating (p. 4).")

    monkeypatch.setattr(llm, "ask", fake_ask)
    monkeypatch.setattr(memory, "record", lambda *a: calls.append(("memory", a)))
    client.put(f"/papers/{paper_id}/ink", json={"strokes": [STROKE], "cards": [CARD, {**CARD, "id": "c2", "answer": "older"}]})

    res = client.post(
        f"/papers/{paper_id}/ink/ask?level=expert",
        json={"image": "aGVsbG8=", "pages": [1, 2], "notes": ["Scaled attention · divide by √d_k"], "typed": ["[p. 2] check Table 2"], "card": "c2"},
    )
    assert res.status_code == 200
    assert res.json() == {"read": ["why √d_k? (next to Eq. 1)"], "answer": "To keep the softmax from saturating (p. 4)."}
    schema, system, (image, text) = calls[0]
    assert schema is InkAnswer and "EXPERT" in system
    assert image["source"] == {"type": "base64", "media_type": "image/jpeg", "data": "aGVsbG8="}
    assert "[p. 3]\nText of page 3." in text["text"]  # the whole paper, page by page
    assert "page(s) 2, 3 of 3" in text["text"]
    assert "divide by √d_k" in text["text"]
    assert "- [p. 2] check Table 2" in text["text"]  # the reader's typed notes, exactly
    assert "Because **scale**" in text["text"] and "older" not in text["text"]  # the card being re-asked isn't history
    assert calls[1][0] == "memory"


def test_ask_needs_pages_of_the_paper(paper_id):
    assert client.post(f"/papers/{paper_id}/ink/ask", json={"image": "x", "pages": []}).status_code == 422
    assert client.post(f"/papers/{paper_id}/ink/ask", json={"image": "x", "pages": [3]}).status_code == 422
    assert client.post("/papers/999/ink/ask", json={"image": "x", "pages": [0]}).status_code == 404


def test_long_papers_are_cut(monkeypatch):
    monkeypatch.setattr(ink, "MAX_PAPER_CHARS", 50)
    text = ink.paper_text(Paper(url="u", title="t", authors=[], pages=[Page(blocks=[Block(text="x" * 40)])] * 3))
    assert text.startswith("[p. 1]") and text.endswith("[… the rest of the paper is cut]") and len(text) < 100
