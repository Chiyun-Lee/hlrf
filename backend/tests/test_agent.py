import os

import pytest

from app.agent import Run
from app.schemas import Paper


def test_save_paper_validates():
    run = Run("u")
    assert run.save_paper(url="u", title="T", authors=[{"raw": "Ada Lovelace"}]) == "ok"
    assert run.paper.authors[0].raw == "Ada Lovelace"
    with pytest.raises(Exception):
        run.save_paper(url="u")  # missing title/authors


def test_read_pages_clamps():
    run = Run("u")
    run.pages = ["a", "b"]
    assert run.read_pages(1, 10).startswith("[pages 1-2 of 2]")


# Live end-to-end checks against hand-labelled papers. Slow and costs API credit.
@pytest.mark.skipif(not os.environ.get("RUN_LIVE"), reason="set RUN_LIVE=1 to call Claude")
def test_attention_is_all_you_need():
    from app.agent import extract

    paper: Paper = extract("https://arxiv.org/abs/1706.03762", {})
    assert len(paper.authors) == 8
    assert all(a.equal_contribution_group is not None for a in paper.authors)
    assert paper.authors[6].family == "Kaiser"  # Łukasz Kaiser
    layer_norm = next(r for r in paper.references if "Layer normalization" in (r.title or ""))
    assert layer_norm.arxiv_id == "1607.06450"
    assert layer_norm.contexts
