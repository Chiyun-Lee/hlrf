import os
from types import SimpleNamespace as Block

import pytest

from app.llm import answer_text
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
