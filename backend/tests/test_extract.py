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


def test_claude_code_backend(monkeypatch, tmp_path):
    """LLM_BACKEND=claude-code: the same call through the Agent SDK, with Claude Code's own context switched off."""
    claude_agent_sdk = pytest.importorskip("claude_agent_sdk")
    import asyncio

    from app import llm
    from app.schemas import PaperHeader

    seen = {}

    async def fake_query(prompt, options):
        seen["prompt"], seen["options"] = prompt, options
        yield claude_agent_sdk.ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="s",
            structured_output={"title": "T", "authors": [{"raw": "Ada Lovelace"}]},
        )

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    monkeypatch.setattr(llm, "CLAUDE_CODE_CWD", tmp_path / "cwd")
    header = asyncio.run(llm.ask_claude_code(PaperHeader, "system", "the paper", "claude-opus-5-5", "low"))
    assert header.title == "T" and header.authors[0].raw == "Ada Lovelace"
    o = seen["options"]
    assert (o.system_prompt, o.model, o.effort, o.tools, o.setting_sources) == ("system", "claude-opus-5-5", "low", [], [])
    assert o.output_format["type"] == "json_schema" and "title" in o.output_format["schema"]["properties"]

    async def failing_query(prompt, options):
        yield claude_agent_sdk.ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=True, num_turns=1, session_id="s",
            errors=["Not logged in"],
        )
        raise RuntimeError("process exited")

    monkeypatch.setattr(claude_agent_sdk, "query", failing_query)
    with pytest.raises(RuntimeError, match="Not logged in"):
        asyncio.run(llm.ask_claude_code(PaperHeader, "system", "the paper", "claude-opus-5-5", "low"))

    monkeypatch.setattr(llm, "BACKEND", "claude-code")
    assert llm.ready() is None
    monkeypatch.setattr(llm, "BACKEND", "carrier-pigeon")
    assert "Unknown LLM_BACKEND" in llm.ready()
