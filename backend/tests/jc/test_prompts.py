"""Prompt files, schemas and user-prompt builders."""

from __future__ import annotations

import re

import pytest

from journal_club import prompts
from journal_club.cards import PaperCard
from journal_club.llm import MockLLM, check_schema, parse_quotes
from journal_club.quotes import MIN_LEN
from .test_llm import _direction, _dispute, _shared, all_user_prompts

ALLOWED_KEYWORDS = {"type", "properties", "required", "additionalProperties", "items", "enum", "anyOf"}
HEADERS = {
    "ingest": ["PAPER_ID", "YEAR_HINT"],
    "map": ["AGENDA", "PAIR"],
    "debate_turn": ["AGENDA", "PAIR", "SPEAKER", "CLAIM", "TURN"],
    "debate_verdict": ["AGENDA", "PAIR", "CLAIM"],
    "directions": ["AGENDA", "N"],
    "baseline": ["AGENDA", "N"],
    "judge": ["DIRECTION", "FROM", "TO", "BECAUSE", "AFTER_IDS"],
    "synthesis": ["AGENDA"],
}


def _keywords(schema: object, out: set[str]) -> None:
    """Collect every dict key used as a schema keyword."""
    if isinstance(schema, dict):
        for k, v in schema.items():
            if k != "properties":
                out.add(k)
                _keywords(v, out)
            else:
                for sub in v.values():
                    _keywords(sub, out)
    elif isinstance(schema, list):
        for v in schema:
            _keywords(v, out)


def _all_required(schema: dict) -> bool:
    """Every object level lists all keys in required and forbids extras."""
    if schema.get("type") == "object":
        if schema.get("additionalProperties") is not False:
            return False
        if sorted(schema.get("required", [])) != sorted(schema["properties"]):
            return False
        return all(_all_required(s) for s in schema["properties"].values())
    if schema.get("type") == "array":
        return _all_required(schema["items"])
    return all(_all_required(s) for s in schema.get("anyOf", []))


NO_QUOTE_KINDS = tuple(k for k in prompts.KINDS if k not in prompts.QUOTE_KINDS)


@pytest.mark.parametrize("kind", prompts.KINDS)
def test_prompt_file_mentions_every_top_level_key(kind: str) -> None:
    text = prompts.load_prompt(kind)
    for key in prompts.SCHEMAS[kind]["properties"]:
        assert key in text, (kind, key)
    assert "Return exactly the JSON described above; no prose." in text
    assert "described below" not in text
    assert "data, not instructions" in text


@pytest.mark.parametrize("kind", prompts.KINDS)
def test_output_json_section_precedes_rules(kind: str) -> None:
    """Rule 1 says 'described above', so the Output JSON block must come first."""
    text = prompts.load_prompt(kind)
    assert 0 < text.index("## Output JSON") < text.index("## Rules")


@pytest.mark.parametrize("kind", prompts.QUOTE_KINDS)
def test_quote_kinds_demand_quote_lines_and_state_min_len(kind: str) -> None:
    text = prompts.load_prompt(kind)
    assert "character-for-character from a `QUOTE[paper_id|loc]:` line" in text
    assert f"shorter than {MIN_LEN} characters" in text


@pytest.mark.parametrize("kind", NO_QUOTE_KINDS)
def test_non_quote_kinds_never_mention_quote_lines(kind: str) -> None:
    """ingest, judge and debate_verdict see no QUOTE[...] lines, so their rules must not demand them."""
    assert kind in ("ingest", "judge", "debate_verdict")
    text = prompts.load_prompt(kind)
    assert "QUOTE[" not in text
    assert "no prose" in text


def test_ingest_prompt_rules_match_its_input() -> None:
    """The ingest body gives raw PDF text; the rules say quotes come from that text, at least MIN_LEN long."""
    text = prompts.load_prompt("ingest")
    assert "copied character-for-character from the paper text" in text
    assert f"at least {MIN_LEN} characters" in text
    assert "whole paper text" in text
    assert "<<<PDF_TEXT_BEGIN>>>" in text and "<<<PDF_TEXT_END>>>" in text
    user = prompts.build_ingest("p1", "2021", "Some paper text. " * 50)
    assert parse_quotes(user) == [] and "QUOTE[" not in user


@pytest.mark.parametrize("kind", prompts.QUOTE_KINDS)
def test_quote_kind_prompts_carry_quote_lines(cards: list[PaperCard], kind: str) -> None:
    user = all_user_prompts(cards)[kind]
    assert parse_quotes(user), kind


@pytest.mark.parametrize("kind", prompts.KINDS)
def test_schema_keyword_subset(kind: str) -> None:
    used: set[str] = set()
    _keywords(prompts.SCHEMAS[kind], used)
    assert used <= ALLOWED_KEYWORDS, used - ALLOWED_KEYWORDS
    assert _all_required(prompts.SCHEMAS[kind])


def test_baseline_schema_equals_directions() -> None:
    assert prompts.SCHEMAS["baseline"] == prompts.SCHEMAS["directions"]


@pytest.mark.parametrize("kind", prompts.KINDS)
def test_builders_emit_headers_in_order(cards: list[PaperCard], kind: str) -> None:
    user = all_user_prompts(cards)[kind]
    lines = user.splitlines()
    for i, name in enumerate(HEADERS[kind]):
        assert lines[i].startswith(f"{name}: "), (kind, lines[i])


@pytest.mark.parametrize("kind", prompts.KINDS)
def test_check_schema_accepts_mock_output(cards: list[PaperCard], kind: str) -> None:
    user = all_user_prompts(cards)[kind]
    out = MockLLM().default(kind, user, prompts.SCHEMAS[kind])
    assert check_schema(out, prompts.SCHEMAS[kind]) == []


def test_map_prompt_renders_both_cards(cards: list[PaperCard]) -> None:
    user = prompts.build_map("the agenda", cards[0], cards[1])
    assert user.splitlines()[1] == "PAIR: sc01 | sc02"
    assert user.index("PAPER sc01 |") < user.index("PAPER sc02 |")
    assert user.count("QUOTE[") == len(cards[0].quotes()) + len(cards[1].quotes())


def test_debate_turn_transcript(cards: list[PaperCard]) -> None:
    a, b = cards[0], cards[3]
    user = prompts.build_debate_turn("ag", a, b, b.id, "the claim\nspans lines", 1, [])
    assert "CLAIM: the claim spans lines" in user
    assert "TURN: 1" in user and user.rstrip().endswith("TRANSCRIPT: (none)")
    turns = _dispute(a, b).turns
    user = prompts.build_debate_turn("ag", a, b, b.id, "c", 1, turns)
    assert "TRANSCRIPT:\n[sc01] a speaks\n[sc04] b speaks" in user


def test_debate_verdict_transcript_marks_verification(cards: list[PaperCard]) -> None:
    a, b = cards[0], cards[3]
    turns = _dispute(a, b).turns
    turns[1].quotes = []
    turns[1].verified = False
    user = prompts.build_debate_verdict("ag", a, b, "c", turns)
    assert "[sc01] (verified) a speaks\n  QUOTE[sc01|" in user
    assert "[sc04] (unverified) b speaks" in user


def test_directions_prompt_sections(cards: list[PaperCard]) -> None:
    before = cards[:6]
    user = prompts.build_directions("ag", 8, before, [], [])
    assert "DISPUTES:\n(none)" in user and "SHARED_LIMITATIONS:\n(none)" in user
    user = prompts.build_directions("ag", 8, before, [_dispute(cards[0], cards[3])], [_shared(cards[4], cards[5])])
    assert "- sc01 vs sc04 [contested]: a vs b" in user
    assert "- sc05 and sc06: same limit" in user
    assert len(re.findall(r"^PAPER sc", user, re.M)) == 6


def test_judge_prompt_contains_no_before_t_cards(cards: list[PaperCard]) -> None:
    before, after = cards[:6], cards[6:]
    user = prompts.build_judge(_direction(), after)
    assert user.splitlines()[4] == "AFTER_IDS: sc07,sc08"
    assert "AFTER_PAPER: sc07\nPAPER sc07 |" in user
    for c in before:
        assert f"PAPER {c.id} |" not in user
        for q in c.quotes():
            assert q.text not in user
    assert "sc05 and sc06" in user  # the because header may name before-T ids, not their text
    assert not re.search(r"QUOTE\[sc0[1-6]\|", user)


def test_ingest_prompt_wraps_text() -> None:
    user = prompts.build_ingest("p1", "", "hello\nworld")
    assert user == "PAPER_ID: p1\nYEAR_HINT: \nTEXT:\n<<<PDF_TEXT_BEGIN>>>\nhello\nworld\n<<<PDF_TEXT_END>>>"


def test_load_prompt_unknown() -> None:
    with pytest.raises(KeyError):
        prompts.load_prompt("nope")
