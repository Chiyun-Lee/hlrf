import os
from types import SimpleNamespace as Block

import pytest

from app.llm import answer_text
from app.proof import locate
from app.schemas import Mark
from app.summarize import parse_note_id, to_page_scale, valid_mark
from app.schemas import Paper


def test_paper_requires_header():
    paper = Paper(url="u", title="T", authors=[{"raw": "Ada Lovelace"}])
    assert paper.authors[0].raw == "Ada Lovelace"
    with pytest.raises(Exception):
        Paper(url="u")  # missing title/authors


def test_old_text_pages_become_blocks():
    paper = Paper(url="u", title="T", authors=[], pages=["Intro\n\nFirst paragraph.", "Second page."])
    assert [b.text for b in paper.pages[0].blocks] == ["Intro", "First paragraph."]
    assert paper.pages[1].blocks[0].bbox is None


def test_answer_after_safety_fallback():
    fallback = Block(type="fallback", from_=Block(model="a"), to=Block(model="b"))
    content = [Block(type="text", text='{"title": "cut off'), fallback, Block(type="text", text='{"title": "full"}')]
    assert answer_text(content) == '{"title": "full"}'
    assert answer_text([Block(type="thinking"), Block(type="text", text="{}")]) == "{}"


def test_note_ids_and_quote_lookup():
    assert parse_note_id("p12n3") == (12, 3)
    with pytest.raises(ValueError):
        parse_note_id("figure 2")
    text = "The Transformer allows for significantly more\nparallelization and can reach a new state"
    start, end = locate(text, "allows for significantly more parallelization")
    assert text[start:end].startswith("allows") and text[start:end].endswith("parallelization")
    assert locate(text, "not in there") is None


def test_marks_move_from_pixels_to_page_scale():
    m = Mark(shape="circle", box=[100, 200, 300, 400], text="here", text_at=[50, 60])
    assert valid_mark(m, 1000, 2000) and not valid_mark(m, 250, 2000)
    assert to_page_scale(m, 1000, 2000).box == [100, 100, 300, 200]


# Live end-to-end check against a hand-labelled paper. Costs API credit.
@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 to call Claude")
def test_attention_is_all_you_need():
    from app.extract import extract

    paper, pdf = extract("https://arxiv.org/abs/1706.03762", {})
    assert pdf and len(paper.pages) >= 10
    assert len(paper.authors) == 8
    assert all(a.equal_contribution_group is not None for a in paper.authors)
    assert paper.authors[6].family == "Kaiser"  # Łukasz Kaiser
    assert any("Scaled Dot-Product Attention" in b.text for p in paper.pages for b in p.blocks)
    assert all(b.bbox for b in paper.pages[0].blocks)
