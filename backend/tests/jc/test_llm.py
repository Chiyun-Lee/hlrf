"""LLM layer: mock determinism, schema check, cache, Anthropic call shape, routing."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from journal_club import prompts
from journal_club.cards import PaperCard, Quote, render_card_for_prompt
from journal_club.rounds.explore import Critique, Hypothesis, Review
from journal_club.llm import (
    QUOTE_RE,
    AnthropicLLM,
    CachedLLM,
    LLMError,
    MockLLM,
    cache_key,
    check_schema,
    get_llm,
)
from journal_club.quotes import verify_quotes

# ----------------------------------------------------------- prompt helpers


def _turn(speaker: str, text: str, quotes: list[Quote]) -> SimpleNamespace:
    """Stand-in for rounds.debate.Turn (attribute-compatible)."""
    return SimpleNamespace(speaker=speaker, text=text, quotes=quotes, verified=bool(quotes))


def _dispute(a: PaperCard, b: PaperCard) -> SimpleNamespace:
    """Stand-in for rounds.debate.Dispute."""
    turns = [_turn(a.id, "a speaks", [a.quotes()[0]]), _turn(b.id, "b speaks", [b.quotes()[0]])]
    return SimpleNamespace(a=a.id, b=b.id, claim="a vs b", turns=turns, verdict="contested", judge_reason="r")


def _shared(a: PaperCard, b: PaperCard) -> SimpleNamespace:
    """Stand-in for rounds.map_round.PairVerdict."""
    return SimpleNamespace(a=a.id, b=b.id, relation="shared_limitation", quote_a=a.limits[0].quote, quote_b=b.limits[0].quote, note="same limit")


def _direction() -> SimpleNamespace:
    """Stand-in for rounds.directions.Direction."""
    return SimpleNamespace(text="from labels to spike-ins", from_a="labels", to_b="spike-ins", because="sc05 and sc06", papers=["sc05", "sc06"], quotes=[], confidence=0.8)


def all_user_prompts(cards: list[PaperCard]) -> dict[str, str]:
    """One user prompt per kind on the fixtures."""
    a, b = cards[0], cards[3]
    before, after = cards[:6], cards[6:]
    return {
        "ingest": prompts.build_ingest("sc09", "2021", "A Title\n\n" + cards[0].fulltext_excerpt),
        "map": prompts.build_map("agenda", a, b),
        "debate_turn": prompts.build_debate_turn("agenda", a, b, a.id, "claim", 0, []),
        "debate_verdict": prompts.build_debate_verdict("agenda", a, b, "claim", _dispute(a, b).turns),
        "directions": prompts.build_directions("agenda", 8, before, [_dispute(a, b)], [_shared(cards[4], cards[5])]),
        "baseline": prompts.build_baseline("agenda", 10, before),
        "judge": prompts.build_judge(_direction(), after),
        "synthesis": prompts.build_synthesis(
            "agenda", before, [_agree(cards[1], cards[2])], [_shared(cards[4], cards[5])], [_dispute(a, b)], []
        ),
        "hypotheses": prompts.build_hypotheses(
            "agenda", 6, before, [_agree(cards[1], cards[2])], [_shared(cards[4], cards[5])], [_dispute(a, b)], [_direction()]
        ),
        "critique": prompts.build_critique("agenda", _hypothesis(a, b), a, [b]),
        "revise": prompts.build_revise("agenda", _hypothesis(a, b), [_critique(a)]),
        "compare": prompts.build_compare("agenda", _review(a, b), _review(b, a)),
    }


def _hypothesis(a: PaperCard, b: PaperCard) -> Hypothesis:
    """A hypothesis resting on the first quote of each paper."""
    return Hypothesis(id="h1", text="a and b predict x", mechanism="m", test="t", prediction="p", source="combine",
                      papers=[a.id, b.id], quotes=[a.quotes()[0], b.quotes()[0]])


def _critique(a: PaperCard) -> Critique:
    return Critique(speaker=a.id, stance="objects", text="not in my data", quotes=[a.quotes()[0]], verified=True)


def _review(a: PaperCard, b: PaperCard) -> Review:
    return Review(hypothesis=_hypothesis(a, b), critiques=[_critique(a)], decision="keep", reason="r", wins=1, played=1)


def _agree(a: PaperCard, b: PaperCard) -> SimpleNamespace:
    """Stand-in for an agreeing PairVerdict."""
    return SimpleNamespace(a=a.id, b=b.id, relation="agree", quote_a=a.claims[0].quote, quote_b=b.claims[0].quote, note="same finding")


# ------------------------------------------------------------------- mock


def test_mock_deterministic_across_instances(cards: list[PaperCard]) -> None:
    user = prompts.build_map("x", cards[0], cards[1])
    r1 = MockLLM().complete_json("map", "s", user, prompts.SCHEMAS["map"])
    r2 = MockLLM().complete_json("map", "s", user, prompts.SCHEMAS["map"])
    assert r1 == r2
    assert r1["quote_a"]["paper_id"] == "sc01" and r1["quote_b"]["paper_id"] == "sc02"


def test_mock_scripted_wins_and_is_recorded() -> None:
    mock = MockLLM(scripted={"debate_verdict": lambda user: {"verdict": "stands", "reason": "scripted"}})
    out = mock.complete_json("debate_verdict", "s", "CLAIM: x", prompts.SCHEMAS["debate_verdict"])
    assert out == {"verdict": "stands", "reason": "scripted"}
    assert mock.calls == [("debate_verdict", "CLAIM: x")]


def test_mock_scripted_violating_schema_raises() -> None:
    mock = MockLLM(scripted={"debate_verdict": lambda user: {"verdict": "maybe", "reason": "x"}})
    with pytest.raises(LLMError, match="violates schema"):
        mock.complete_json("debate_verdict", "s", "u", prompts.SCHEMAS["debate_verdict"])


def test_quote_re_on_rendered_card(cards: list[PaperCard]) -> None:
    for c in cards:
        found = QUOTE_RE.findall(render_card_for_prompt(c))
        assert [(p, l, t) for p, l, t in found] == [(q.paper_id, q.loc, q.text) for q in c.quotes()]


def _quotes_in(result: Any) -> list[Quote]:
    """Collect every Quote-shaped dict in a result."""
    out: list[Quote] = []
    if isinstance(result, dict):
        if set(result) == {"paper_id", "text", "loc"}:
            return [Quote.model_validate(result)]
        for v in result.values():
            out += _quotes_in(v)
    elif isinstance(result, list):
        for v in result:
            out += _quotes_in(v)
    return out


@pytest.mark.parametrize("kind", prompts.KINDS)
def test_mock_every_kind_passes_schema_and_verifies(cards: list[PaperCard], kind: str) -> None:
    user = all_user_prompts(cards)[kind]
    out = MockLLM().complete_json(kind, prompts.load_prompt(kind), user, prompts.SCHEMAS[kind])
    assert check_schema(out, prompts.SCHEMAS[kind]) == []
    if kind in ("ingest", "debate_verdict", "judge", "revise", "compare"):
        return  # no quotes in these outputs by schema
    by_id = {c.id: c for c in cards}
    quotes = _quotes_in(out)
    assert quotes, kind
    ok, failed = verify_quotes(by_id, quotes)
    assert failed == [] and ok == quotes


def test_mock_directions_shape(cards: list[PaperCard]) -> None:
    user = prompts.build_baseline("a", 10, cards[:6])
    out = MockLLM().complete_json("baseline", "s", user, prompts.SCHEMAS["baseline"])
    assert len(out["directions"]) == 10
    for d in out["directions"]:
        assert d["papers"] == sorted(d["papers"]) and len(d["quotes"]) == 2
        assert 0.3 <= d["confidence"] < 0.9
        assert d["text"].startswith("The field moves from ")


def test_mock_judge_respects_after_ids(cards: list[PaperCard]) -> None:
    user = prompts.build_judge(_direction(), cards[6:])
    for i in range(6):
        out = MockLLM().complete_json("judge", "s", user + f"\n#{i}", prompts.SCHEMAS["judge"])
        if out["verdict"] == "miss":
            assert out["after_paper_id"] is None
        else:
            assert out["after_paper_id"] in {"sc07", "sc08"}


def test_mock_map_without_quote_fabricates() -> None:
    out = MockLLM().complete_json("map", "s", "PAIR: x1 | x2\n", prompts.SCHEMAS["map"])
    assert out["quote_a"] == {"paper_id": "x1", "text": "no quote available", "loc": "none"}


def test_mock_generic_unknown_kind() -> None:
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "n": {"type": "integer"},
            "x": {"type": "number"},
            "ok": {"type": "boolean"},
            "kind": {"type": "string", "enum": ["p", "q"]},
            "maybe": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "items": {"type": "array", "items": {"type": "string"}},
            "quote": prompts.Q,
        },
        "required": ["name", "n", "x", "ok", "kind", "maybe", "items", "quote"],
        "additionalProperties": False,
    }
    out = MockLLM().complete_json("other", "s", "QUOTE[p1|p2]: a real quote line\n", schema)
    assert check_schema(out, schema) == []
    assert out["n"] == 1 and out["x"] == 0.5 and out["ok"] is True and out["maybe"] is None
    assert out["quote"] == {"paper_id": "p1", "loc": "p2", "text": "a real quote line"}


# ---------------------------------------------------------- check_schema


def test_check_schema_reports() -> None:
    s = prompts.SCHEMAS["judge"]
    assert check_schema({"verdict": "hit", "after_paper_id": None, "reason": "r"}, s) == []
    assert check_schema({"verdict": "hit", "after_paper_id": "x", "reason": "r"}, s) == []
    probs = check_schema({"verdict": "huge", "after_paper_id": 3, "extra": 1}, s)
    assert any("enum" in p for p in probs)
    assert any("anyOf" in p for p in probs)
    assert any("unexpected" in p for p in probs)
    assert any("missing" in p for p in probs)
    assert check_schema({"verdict": "hit", "after_paper_id": None, "reason": 5}, s)
    assert check_schema({"year": True}, {"type": "object", "properties": {"year": {"type": "integer"}}, "required": ["year"], "additionalProperties": False})


# ---------------------------------------------------------------- cache


class _Spy:
    """Inner LLM returning a fixed result and counting calls."""

    def __init__(self, result: dict) -> None:
        self.result = result
        self.n = 0

    def complete_json(self, kind: str, system: str, user: str, schema: dict) -> dict:
        self.n += 1
        return self.result


def test_cache_hit_miss_and_drop(tmp_path: Path) -> None:
    schema = prompts.SCHEMAS["debate_verdict"]
    spy = _Spy({"verdict": "stands", "reason": "r"})
    cached = CachedLLM(spy, tmp_path / "c")
    assert cached.inner is spy
    assert cached.complete_json("debate_verdict", "s", "u", schema) == spy.result
    assert cached.complete_json("debate_verdict", "s", "u", schema) == spy.result
    assert spy.n == 1
    files = list((tmp_path / "c").glob("*.json"))
    assert len(files) == 1 and files[0].stem == cache_key("debate_verdict", "s", "u", schema)
    assert json.loads(files[0].read_text()) == spy.result
    assert cached.complete_json("debate_verdict", "s", "u2", schema) == spy.result
    assert spy.n == 2
    assert cached.drop("debate_verdict", "s", "u", schema) is True
    assert cached.drop("debate_verdict", "s", "u", schema) is False
    cached.complete_json("debate_verdict", "s", "u", schema)
    assert spy.n == 3


def test_cache_key_stable() -> None:
    s = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False}
    s2 = {"additionalProperties": False, "required": ["a"], "properties": {"a": {"type": "string"}}, "type": "object"}
    assert cache_key("k", "s", "u", s) == cache_key("k", "s", "u", s2)
    assert cache_key("k", "s", "u", s) != cache_key("k2", "s", "u", s)
    assert len(cache_key("k", "s", "u", s)) == 64


def test_cache_key_includes_inner_model(tmp_path: Path) -> None:
    schema = prompts.SCHEMAS["debate_verdict"]
    a, b = _Spy({"verdict": "stands", "reason": "a"}), _Spy({"verdict": "contested", "reason": "b"})
    a.model, b.model = "model-a", "model-b"  # type: ignore[attr-defined]
    ca, cb = CachedLLM(a, tmp_path / "c"), CachedLLM(b, tmp_path / "c")
    assert ca.model == "model-a" and cb.model == "model-b"
    assert ca.complete_json("debate_verdict", "s", "u", schema) == a.result
    assert cb.complete_json("debate_verdict", "s", "u", schema) == b.result, "a model change never serves the other model's cached answer"
    assert a.n == 1 and b.n == 1
    assert len(list((tmp_path / "c").glob("*.json"))) == 2
    assert cache_key("k", "s", "u", schema, "model-a") != cache_key("k", "s", "u", schema, "model-b")
    assert cache_key("k", "s", "u", schema, None) == cache_key("k", "s", "u", schema)
    assert CachedLLM(_Spy({}), tmp_path / "c").model is None


def test_cache_no_write_on_invalid(tmp_path: Path) -> None:
    cached = CachedLLM(_Spy({"verdict": "nope", "reason": "r"}), tmp_path / "c")
    with pytest.raises(LLMError):
        cached.complete_json("debate_verdict", "s", "u", prompts.SCHEMAS["debate_verdict"])
    assert not list((tmp_path / "c").glob("*")) if (tmp_path / "c").exists() else True


# ------------------------------------------------------------ anthropic


class _StubMessages:
    """Records create kwargs and returns a canned response."""

    def __init__(self, text: str, stop_reason: str = "end_turn") -> None:
        self.text = text
        self.stop_reason = stop_reason
        self.kwargs: dict | None = None

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.kwargs = kwargs
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=self.text)],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def test_anthropic_call_shape() -> None:
    schema = prompts.SCHEMAS["debate_verdict"]
    stub = _StubMessages(json.dumps({"verdict": "stands", "reason": "r"}))
    llm = AnthropicLLM("claude-opus-5-5", client=SimpleNamespace(messages=stub))
    out = llm.complete_json("debate_verdict", "SYS", "USER", schema)
    assert out == {"verdict": "stands", "reason": "r"}
    kw = stub.kwargs
    assert kw is not None
    assert kw["model"] == "claude-opus-5-5"
    assert kw["max_tokens"] == 16000
    assert kw["system"] == "SYS"
    assert kw["messages"] == [{"role": "user", "content": "USER"}]
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["format"]["schema"] is schema
    for forbidden in ("temperature", "thinking", "tool_choice", "tools", "top_p"):
        assert forbidden not in kw


@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_anthropic_bad_stop_reason(stop: str) -> None:
    stub = _StubMessages('{"verdict": "stands", "reason": "r"}', stop_reason=stop)
    llm = AnthropicLLM("m", client=SimpleNamespace(messages=stub))
    with pytest.raises(LLMError, match=stop):
        llm.complete_json("debate_verdict", "s", "u", prompts.SCHEMAS["debate_verdict"])


def test_anthropic_bad_json_and_schema() -> None:
    llm = AnthropicLLM("m", client=SimpleNamespace(messages=_StubMessages("not json")))
    with pytest.raises(LLMError, match="invalid JSON"):
        llm.complete_json("debate_verdict", "s", "u", prompts.SCHEMAS["debate_verdict"])
    llm = AnthropicLLM("m", client=SimpleNamespace(messages=_StubMessages('{"verdict": "x", "reason": "r"}')))
    with pytest.raises(LLMError, match="schema"):
        llm.complete_json("debate_verdict", "s", "u", prompts.SCHEMAS["debate_verdict"])


# -------------------------------------------------------------- routing


def test_get_llm_routing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("JC_CACHE_DIR", raising=False)  # app/club.py points the cache at JOURNAL_CLUB_DIR; this tests the default
    monkeypatch.setenv("JC_LLM", "mock")
    assert isinstance(get_llm(), MockLLM)
    monkeypatch.setenv("JC_LLM", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("JC_MODEL", "main-model")
    monkeypatch.setenv("JC_JUDGE_MODEL", "judge-model")
    monkeypatch.chdir(tmp_path)
    llm = get_llm()
    assert isinstance(llm, CachedLLM) and isinstance(llm.inner, AnthropicLLM)
    assert llm.inner.model == "main-model"
    assert llm.dir == Path(".jc_cache")
    judge = get_llm("judge")
    assert isinstance(judge, CachedLLM) and judge.inner.model == "judge-model"
    monkeypatch.setenv("JC_CACHE", "0")
    assert isinstance(get_llm(), AnthropicLLM)
    monkeypatch.delenv("JC_MODEL")
    monkeypatch.delenv("JC_JUDGE_MODEL")
    assert get_llm().model == "claude-opus-5-5"
    assert get_llm("judge").model == "claude-sonnet-5-5"
    monkeypatch.setenv("JC_LLM", "openai")
    with pytest.raises(ValueError):
        get_llm()


@pytest.mark.live
def test_live_judge_smoke(cards: list[PaperCard]) -> None:
    os.environ.pop("JC_LLM", None)
    llm = get_llm("judge")
    out = llm.complete_json("judge", prompts.load_prompt("judge"), prompts.build_judge(_direction(), cards[6:]), prompts.SCHEMAS["judge"])
    assert out["verdict"] in {"hit", "partial", "miss"}
    assert out["after_paper_id"] in {None, "sc07", "sc08"}


# --------------------------------------------------------- sdk errors


def _httpx() -> Any:
    """The HTTP module the installed SDK builds its exceptions from (httpx2 in newer releases, httpx before)."""
    try:
        import httpx2 as httpx
    except ImportError:  # pragma: no cover - depends on the SDK release
        import httpx
    return httpx


def _api_errors() -> list[Exception]:
    """One instance of each SDK failure a run meets in practice: rate limit, overload, network."""
    import anthropic

    httpx = _httpx()

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return [
        anthropic.RateLimitError("429", response=httpx.Response(429, request=req), body=None),
        anthropic.APIStatusError("529 overloaded", response=httpx.Response(529, request=req), body=None),
        anthropic.APIConnectionError(request=req),
    ]


@pytest.mark.parametrize("exc", _api_errors(), ids=lambda e: type(e).__name__)
def test_anthropic_sdk_errors_become_llm_errors(exc: Exception) -> None:
    class _Raising:
        def create(self, **kwargs: Any) -> None:
            raise exc

    llm = AnthropicLLM("m", client=SimpleNamespace(messages=_Raising()))
    with pytest.raises(LLMError, match=type(exc).__name__) as info:
        llm.complete_json("judge", "s", "u", prompts.SCHEMAS["judge"])
    assert info.value.__cause__ is exc
