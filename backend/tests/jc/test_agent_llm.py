"""Claude Agent SDK backend: selection, isolation options, and an opt-in live call."""

from __future__ import annotations

import os

import pytest

from journal_club.llm import AGENT_MAX_TURNS, CachedLLM, ClaudeAgentLLM, LLMError, default_backend, get_llm


def test_default_backend_prefers_agent_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert default_backend() == "agent"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert default_backend() == "anthropic"


def test_get_llm_agent_is_cached_and_isolated(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("JC_LLM", "agent")
    monkeypatch.setenv("JC_MODEL", "claude-opus-5-5")
    llm = get_llm("main")
    assert isinstance(llm, CachedLLM) and isinstance(llm.inner, ClaudeAgentLLM)
    assert llm.model == "claude-opus-5-5"
    opts = llm.inner._options("SYS", {"type": "object", "properties": {}, "additionalProperties": False})
    assert opts.tools == [] and opts.allowed_tools == [] and opts.setting_sources == []
    assert opts.permission_mode == "dontAsk" and opts.max_turns == AGENT_MAX_TURNS
    assert opts.output_format["type"] == "json_schema"
    assert opts.cwd and os.path.isdir(opts.cwd)


def test_agent_refuses_with_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    with pytest.raises(LLMError):
        ClaudeAgentLLM()


@pytest.mark.skipif(os.environ.get("JC_LIVE") != "1", reason="set JC_LIVE=1 to make one real call on the Claude Code login")
def test_live_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm = ClaudeAgentLLM(os.environ.get("JC_MODEL", "claude-sonnet-5-5"))
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "integer"}, "quote": {"type": "string"}},
        "required": ["answer", "quote"],
        "additionalProperties": False,
    }
    out = llm.complete_json(
        "smoke",
        "You answer with JSON only. Copy quotes character for character from QUOTE lines.",
        "QUOTE[p1|Sec. 1]: The quick brown fox jumps over the lazy dog near the riverbank at dawn.\n"
        "What is 6 times 7? Put the number in `answer` and the QUOTE text in `quote`.",
        schema,
    )
    assert out["answer"] == 42
    assert "quick brown fox" in out["quote"]
