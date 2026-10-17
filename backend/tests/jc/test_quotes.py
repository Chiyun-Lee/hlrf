"""Normalisation and verification edge cases."""

from __future__ import annotations

import pytest

from journal_club.cards import PaperCard, Quote
from journal_club.quotes import MIN_LEN, contains_quote, normalise, too_short, verify_in_text, verify_quote, verify_quotes


def _card(cards: list[PaperCard], cid: str) -> PaperCard:
    """Card by id."""
    return next(c for c in cards if c.id == cid)


def test_normalise_curly_quotes_and_dashes() -> None:
    assert normalise("“batch” – ‘effect’") == 'batch" - \'effect'


def test_normalise_ligature() -> None:
    assert normalise("ﬁne ﬂow") == "fine flow"


def test_normalise_line_break_hyphenation() -> None:
    assert normalise("integra-\n  tion quality") == "integration quality"


def test_normalise_double_spaces_and_edge_punctuation() -> None:
    assert normalise('  "Hello,  world."  ') == "hello, world"


def test_verify_exact_and_variants(cards: list[PaperCard]) -> None:
    card = _card(cards, "sc01")
    exact = card.claims[0].quote.text
    assert verify_quote(card, exact)
    assert verify_quote(card, exact.upper())
    assert verify_quote(card, "  " + exact.replace(" ", "   ") + ".  ")
    assert verify_quote(card, "within-batch cluster structure in all twelve")


def test_verify_excerpt_only(cards: list[PaperCard]) -> None:
    card = _card(cards, "sc01")
    assert verify_quote(card, "Memory use stays below four gigabytes at that scale")


def test_verify_rejects_short_and_paraphrase(cards: list[PaperCard]) -> None:
    card = _card(cards, "sc01")
    assert not verify_quote(card, "batch effects")
    assert not verify_quote(card, "Anchor alignment removes batch effects while keeping clusters.")


@pytest.mark.parametrize("bad", ["", "   ", "...", "a" * 14, "a" * (MIN_LEN - 1)])
def test_verify_min_length(cards: list[PaperCard], bad: str) -> None:
    assert not verify_quote(_card(cards, "sc01"), bad)


@pytest.mark.parametrize("fragment", ["batch effects wh", "in all twelve d", "cell types, and", "Alignment removes batch effects."])
def test_verify_rejects_trivial_substrings(cards: list[PaperCard], fragment: str) -> None:
    """Short fragments that happen to be substrings of a stored quote are not evidence."""
    assert MIN_LEN >= 40
    assert not verify_quote(_card(cards, "sc01"), fragment)


def test_verify_loc_must_match_the_stored_quote(cards: list[PaperCard]) -> None:
    card = _card(cards, "sc01")
    stored = card.claims[0].quote
    assert verify_quote(card, stored.text, stored.loc)
    assert verify_quote(card, stored.text, " P4 §3.1. ")
    assert verify_quote(card, stored.text.upper(), stored.loc)
    assert not verify_quote(card, stored.text, "p42 Table 9 (fabricated)")
    assert not verify_quote(card, stored.text, "p99 §FAKE")
    assert not verify_quote(card, stored.text, card.claims[1].quote.loc), "a real loc of a different quote"
    assert not verify_quote(card, stored.text, "")
    assert not verify_quote(card, stored.text, "none")


def test_verify_loc_excerpt_only_text_has_no_loc_to_match(cards: list[PaperCard]) -> None:
    card = _card(cards, "sc01")
    excerpt_only = "Memory use stays below four gigabytes at that scale"
    assert verify_quote(card, excerpt_only)
    assert not verify_quote(card, excerpt_only, "p7 §3.4")


def test_verify_quotes_checks_loc(cards: list[PaperCard]) -> None:
    by_id = {c.id: c for c in cards}
    good = by_id["sc01"].claims[0].quote
    faked = Quote(paper_id="sc01", text=good.text, loc="p42 Table 9 (fabricated)")
    ok, failed = verify_quotes(by_id, [good, faked])
    assert ok == [good] and failed == [faked]


def test_verify_quotes_wrong_paper_and_require(cards: list[PaperCard]) -> None:
    by_id = {c.id: c for c in cards}
    good = by_id["sc01"].claims[0].quote
    wrong = Quote(paper_id="sc02", text=good.text, loc="p1")
    unknown = Quote(paper_id="zz99", text=good.text, loc="p1")
    ok, failed = verify_quotes(by_id, [good, wrong, unknown])
    assert ok == [good]
    assert failed == [wrong, unknown]
    ok, failed = verify_quotes(by_id, [good], require_paper="sc02")
    assert ok == [] and failed == [good]
    ok, failed = verify_quotes(by_id, [good], require_paper="sc01")
    assert ok == [good] and failed == []


def test_verify_in_text_and_contains_quote(cards: list[PaperCard]) -> None:
    text = "Intro.\n\n" + "x " * 5000 + _card(cards, "sc01").quotes()[0].text + "\nmore"
    quote = _card(cards, "sc01").quotes()[0].text
    assert verify_in_text(text, quote)
    assert verify_in_text(text, quote.upper()), "normalised match"
    assert contains_quote(normalise(text), quote)
    assert not verify_in_text(text, "not present but long enough to pass the minimum length check")
    assert not verify_in_text(text, "x x x x")  # under MIN_LEN even though it is a substring


def test_too_short() -> None:
    assert too_short("a" * (MIN_LEN - 1)) and too_short("   ")
    assert not too_short("a" * MIN_LEN)
