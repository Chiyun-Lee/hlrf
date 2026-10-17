"""System prompts, output schemas and user-prompt builders for every LLM kind."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from journal_club.cards import PaperCard, Quote, render_card_for_prompt, render_quote_line

if TYPE_CHECKING:
    from journal_club.rounds.debate import Dispute, Turn
    from journal_club.rounds.directions import Direction
    from journal_club.rounds.explore import Critique, Hypothesis, Review
    from journal_club.rounds.map_round import PairVerdict

KINDS = (
    "ingest", "map", "debate_turn", "debate_verdict", "directions", "baseline", "judge", "synthesis",
    "hypotheses", "critique", "revise", "compare",
)
# Kinds whose input carries QUOTE[...] lines and whose output copies them; the others never see or emit quotes.
QUOTE_KINDS = ("map", "debate_turn", "directions", "baseline", "synthesis", "hypotheses", "critique")
PROMPT_DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(kind: str) -> str:
    """System prompt text of prompts/<kind>.md (cached)."""
    if kind not in KINDS:
        raise KeyError(f"unknown prompt kind {kind!r}")
    return (PROMPT_DIR / f"{kind}.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------- schemas


def _obj(props: dict[str, dict]) -> dict:
    """Object schema with every key required and no extras."""
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def _arr(items: dict) -> dict:
    """Array schema."""
    return {"type": "array", "items": items}


_S = {"type": "string"}
Q = _obj({"paper_id": _S, "text": _S, "loc": _S})
_QUOTED = _obj({"text": _S, "quote": Q})
_DIRECTION = _obj(
    {
        "text": _S,
        "from_a": _S,
        "to_b": _S,
        "because": _S,
        "papers": _arr(_S),
        "quotes": _arr(Q),
        "confidence": {"type": "number"},
    }
)

SCHEMAS: dict[str, dict] = {
    "ingest": _obj(
        {
            "citekey": _S,
            "title": _S,
            "year": {"type": "integer"},
            "date": _S,
            "authors": _arr(_S),
            "abstract": _S,
            "claims": _arr(_QUOTED),
            "methods": _arr(_S),
            "data": _arr(_S),
            "limits": _arr(_QUOTED),
        }
    ),
    "map": _obj(
        {
            "relation": {"type": "string", "enum": ["agree", "disagree", "shared_limitation", "unrelated"]},
            "quote_a": Q,
            "quote_b": Q,
            "note": _S,
        }
    ),
    "debate_turn": _obj({"text": _S, "quotes": _arr(Q)}),
    "debate_verdict": _obj(
        {"verdict": {"type": "string", "enum": ["stands", "contested", "unresolved"]}, "reason": _S}
    ),
    "directions": _obj({"directions": _arr(_DIRECTION)}),
    "baseline": _obj({"directions": _arr(_DIRECTION)}),
    "synthesis": _obj(
        {
            "overview": _S,
            "key_points": _arr(
                _obj(
                    {
                        "kind": {"type": "string", "enum": ["consensus", "dissent", "gap", "direction"]},
                        "text": _S,
                        "quotes": _arr(Q),
                    }
                )
            ),
        }
    ),
    "judge": _obj(
        {
            "verdict": {"type": "string", "enum": ["hit", "partial", "miss"]},
            "after_paper_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "reason": _S,
        }
    ),
    "hypotheses": _obj(
        {
            "hypotheses": _arr(
                _obj(
                    {
                        "text": _S,
                        "mechanism": _S,
                        "test": _S,
                        "prediction": _S,
                        "source": {"type": "string", "enum": ["combine", "resolve", "gap", "extend"]},
                        "papers": _arr(_S),
                        "quotes": _arr(Q),
                    }
                )
            )
        }
    ),
    "critique": _obj({"stance": {"type": "string", "enum": ["supports", "objects"]}, "text": _S, "quotes": _arr(Q)}),
    "revise": _obj(
        {
            "decision": {"type": "string", "enum": ["keep", "revise", "drop"]},
            "text": _S,
            "mechanism": _S,
            "test": _S,
            "prediction": _S,
            "reason": _S,
        }
    ),
    "compare": _obj({"winner": {"type": "string", "enum": ["A", "B"]}, "reason": _S}),
}


# ------------------------------------------------------------------ builders


def _line(s: str) -> str:
    """Collapse a value to one line."""
    return " ".join(s.split())


def _headers(pairs: list[tuple[str, str]]) -> list[str]:
    """`NAME: value` lines."""
    return [f"{k}: {_line(v)}" for k, v in pairs]


def _quote_lines(quotes: list[Quote], indent: str = "  ") -> list[str]:
    """Indented QUOTE lines."""
    return [indent + render_quote_line(q) for q in quotes]


def build_ingest(paper_id: str, year_hint: str, text: str) -> str:
    """PAPER_ID, YEAR_HINT, then the PDF text wrapped as data."""
    head = _headers([("PAPER_ID", paper_id), ("YEAR_HINT", year_hint)])
    return "\n".join(head + ["TEXT:", "<<<PDF_TEXT_BEGIN>>>", text, "<<<PDF_TEXT_END>>>"])


def build_map(agenda: str, a: PaperCard, b: PaperCard) -> str:
    """AGENDA, PAIR, then both cards."""
    head = _headers([("AGENDA", agenda), ("PAIR", f"{a.id} | {b.id}")])
    return "\n".join(head + ["", render_card_for_prompt(a), "", render_card_for_prompt(b)])


def build_debate_turn(
    agenda: str,
    a: PaperCard,
    b: PaperCard,
    speaker: str,
    claim: str,
    turn_index: int,
    prior_turns: list[Turn],
) -> str:
    """AGENDA, PAIR, SPEAKER, CLAIM, TURN, both cards, then the transcript."""
    head = _headers(
        [
            ("AGENDA", agenda),
            ("PAIR", f"{a.id} | {b.id}"),
            ("SPEAKER", speaker),
            ("CLAIM", claim),
            ("TURN", str(turn_index)),
        ]
    )
    body = ["", render_card_for_prompt(a), "", render_card_for_prompt(b), ""]
    if prior_turns:
        body.append("TRANSCRIPT:")
        body += [f"[{t.speaker}] {_line(t.text)}" for t in prior_turns]
    else:
        body.append("TRANSCRIPT: (none)")
    return "\n".join(head + body)


def build_debate_verdict(agenda: str, a: PaperCard, b: PaperCard, claim: str, turns: list[Turn]) -> str:
    """AGENDA, PAIR, CLAIM, both cards, transcript with verified quotes."""
    head = _headers([("AGENDA", agenda), ("PAIR", f"{a.id} | {b.id}"), ("CLAIM", claim)])
    body = ["", render_card_for_prompt(a), "", render_card_for_prompt(b), "", "TRANSCRIPT:"]
    for t in turns:
        tag = "verified" if t.verified else "unverified"
        body.append(f"[{t.speaker}] ({tag}) {_line(t.text)}")
        body += _quote_lines(t.quotes)
    return "\n".join(head + body)


def _cards_block(cards: list[PaperCard]) -> list[str]:
    """Every card rendered, blank line between."""
    out: list[str] = []
    for c in cards:
        out += ["", render_card_for_prompt(c)]
    return out


def build_directions(
    agenda: str,
    n: int,
    cards: list[PaperCard],
    disputes: list[Dispute],
    shared_pairs: list[PairVerdict],
) -> str:
    """AGENDA, N, all cards, DISPUTES and SHARED_LIMITATIONS blocks."""
    head = _headers([("AGENDA", agenda), ("N", str(n))])
    body = _cards_block(cards) + ["", "DISPUTES:"]
    if disputes:
        for d in disputes:
            body.append(f"- {d.a} vs {d.b} [{d.verdict}]: {_line(d.claim)}")
            for t in d.turns:
                body += _quote_lines(t.quotes)
    else:
        body.append("(none)")
    body += ["", "SHARED_LIMITATIONS:"]
    if shared_pairs:
        for p in shared_pairs:
            body.append(f"- {p.a} and {p.b}: {_line(p.note)}")
            body += _quote_lines([p.quote_a, p.quote_b])
    else:
        body.append("(none)")
    return "\n".join(head + body)


def build_baseline(agenda: str, n: int, cards: list[PaperCard]) -> str:
    """AGENDA, N, all cards; nothing else."""
    head = _headers([("AGENDA", agenda), ("N", str(n))])
    return "\n".join(head + _cards_block(cards))


def build_judge(direction: Direction, after_cards: list[PaperCard]) -> str:
    """DIRECTION, FROM, TO, BECAUSE, AFTER_IDS, then the after-T cards only."""
    head = _headers(
        [
            ("DIRECTION", direction.text),
            ("FROM", direction.from_a),
            ("TO", direction.to_b),
            ("BECAUSE", direction.because),
            ("AFTER_IDS", ",".join(c.id for c in after_cards)),
        ]
    )
    body: list[str] = []
    for c in after_cards:
        body += ["", f"AFTER_PAPER: {c.id}", render_card_for_prompt(c)]
    return "\n".join(head + body)


def build_synthesis(
    agenda: str,
    cards: list[PaperCard],
    agree_pairs: list[PairVerdict],
    shared_pairs: list[PairVerdict],
    disputes: list[Dispute],
    directions: list[Direction],
    hypotheses: list[Review] | None = None,
) -> str:
    """AGENDA, all cards, then CONSENSUS, SHARED_LIMITATIONS, DISPUTES and DIRECTIONS blocks with their quotes, and
    HYPOTHESES (after the critique round) when the night explored."""
    head = _headers([("AGENDA", agenda)])
    body = _cards_block(cards)
    for title, pairs in (("CONSENSUS", agree_pairs), ("SHARED_LIMITATIONS", shared_pairs)):
        body += ["", f"{title}:"]
        if pairs:
            for p in pairs:
                body.append(f"- {p.a} and {p.b}: {_line(p.note)}")
                body += _quote_lines([p.quote_a, p.quote_b])
        else:
            body.append("(none)")
    body += ["", "DISPUTES:"]
    if disputes:
        for d in disputes:
            body.append(f"- {d.a} vs {d.b} [{d.verdict}]: {_line(d.claim)}")
            body.append(f"  reason: {_line(d.judge_reason)}")
            for t in d.turns:
                body += _quote_lines(t.quotes)
    else:
        body.append("(none)")
    body += ["", "DIRECTIONS:"]
    if directions:
        for i, d in enumerate(directions, start=1):
            body.append(f"{i}. ({d.confidence:.2f}) {_line(d.text)}")
            body += _quote_lines(d.quotes)
    else:
        body.append("(none)")
    if hypotheses:
        body += ["", "HYPOTHESES:"]
        for r in hypotheses:
            tally = "dropped" if r.decision == "drop" else f"{r.decision}, won {r.wins} of {r.played}"
            body.append(f"- ({tally}) {_line(r.hypothesis.text)} Test: {_line(r.hypothesis.test)}")
            body += _quote_lines(r.hypothesis.quotes)
    return "\n".join(head + body)


def _pairs_block(title: str, pairs: list[PairVerdict]) -> list[str]:
    """`TITLE:` then one line per pair with its note and both quotes."""
    body = ["", f"{title}:"]
    for p in pairs:
        body.append(f"- {p.a} and {p.b}: {_line(p.note)}")
        body += _quote_lines([p.quote_a, p.quote_b])
    return body if pairs else body + ["(none)"]


def build_hypotheses(
    agenda: str,
    n: int,
    cards: list[PaperCard],
    agree_pairs: list[PairVerdict],
    shared_pairs: list[PairVerdict],
    disputes: list[Dispute],
    directions: list[Direction],
) -> str:
    """AGENDA, N, all cards, then CONSENSUS, SHARED_LIMITATIONS, DISPUTES (every verdict) and DIRECTIONS."""
    body = _cards_block(cards) + _pairs_block("CONSENSUS", agree_pairs) + _pairs_block("SHARED_LIMITATIONS", shared_pairs)
    body += ["", "DISPUTES:"]
    for d in disputes:
        body.append(f"- {d.a} vs {d.b} [{d.verdict}]: {_line(d.claim)}")
        body.append(f"  reason: {_line(d.judge_reason)}")
        for t in d.turns:
            body += _quote_lines(t.quotes)
    if not disputes:
        body.append("(none)")
    body += ["", "DIRECTIONS:"] + [f"- {_line(d.text)}" for d in directions] + ([] if directions else ["(none)"])
    return "\n".join(_headers([("AGENDA", agenda), ("N", str(n))]) + body)


def _hypothesis_lines(h: Hypothesis) -> list[str]:
    """`HYPOTHESIS`, `MECHANISM`, `TEST`, `PREDICTION`, `SOURCE` headers, then its premises."""
    head = _headers(
        [("HYPOTHESIS", h.text), ("MECHANISM", h.mechanism), ("TEST", h.test), ("PREDICTION", h.prediction), ("SOURCE", h.source)]
    )
    return head + ["PREMISES:"] + _quote_lines(h.quotes)


def build_critique(agenda: str, h: Hypothesis, speaker: PaperCard, others: list[PaperCard]) -> str:
    """AGENDA, SPEAKER, the hypothesis with its premises, the speaker's card, then the other cited cards."""
    body = ["", render_card_for_prompt(speaker)] + _cards_block(others)
    return "\n".join(_headers([("AGENDA", agenda), ("SPEAKER", speaker.id)]) + _hypothesis_lines(h) + body)


def build_revise(agenda: str, h: Hypothesis, critiques: list[Critique]) -> str:
    """AGENDA, the hypothesis with its premises, then each critique (verified or not) with its quotes."""
    body = ["", "CRITIQUES:"]
    for c in critiques:
        body.append(f"[{c.speaker}] ({'verified' if c.verified else 'unverified'}, {c.stance}) {_line(c.text)}")
        body += _quote_lines(c.quotes)
    if not critiques:
        body.append("(none)")
    return "\n".join(_headers([("AGENDA", agenda)]) + _hypothesis_lines(h) + body)


def build_compare(agenda: str, a: Review, b: Review) -> str:
    """AGENDA, then hypotheses A and B as revised, each with what its papers said and the PI's reason."""
    out = _headers([("AGENDA", agenda)])
    for label, r in (("A", a), ("B", b)):
        h = r.hypothesis
        out += ["", f"{label}: {_line(h.text)}", f"  mechanism: {_line(h.mechanism)}", f"  test: {_line(h.test)}",
                f"  prediction: {_line(h.prediction)}", f"  papers: {', '.join(h.papers)}", f"  PI: {_line(r.reason)}"]
        out += [f"  [{c.speaker}] {c.stance}{'' if c.verified else ' (unverified)'}: {_line(c.text)}" for c in r.critiques]
    return "\n".join(out)
