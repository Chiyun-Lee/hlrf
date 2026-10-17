"""Quote normalisation and string-match verification against paper cards."""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from journal_club.cards import PaperCard, Quote

MIN_LEN = 40
_EDGE = ".,;:!?\"'()[]-"
_CHARS = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
    }
)


def normalise(s: str) -> str:
    """NFKC, straight quotes/dashes, de-hyphenate line breaks, lowercase, one space."""
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_CHARS)
    s = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", s)
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip().strip(_EDGE).strip()


def too_short(text: str) -> bool:
    """True if the normalised text is under MIN_LEN: a fragment, not evidence."""
    return len(normalise(text)) < MIN_LEN


def contains_quote(normalised_text: str, quote: str) -> bool:
    """True if `quote` (at least MIN_LEN once normalised) sits verbatim inside an already-normalised text."""
    n = normalise(quote)
    return len(n) >= MIN_LEN and n in normalised_text


def verify_in_text(text: str, quote: str) -> bool:
    """True if `quote` sits verbatim (after normalisation) inside the raw `text`; the ingest gate's check."""
    return contains_quote(normalise(text), quote)


def _matching_quotes(card: PaperCard, n: str) -> list[Quote]:
    """Stored quotes whose normalised text contains the normalised text `n`."""
    return [q for q in card.quotes() if n in normalise(q.text)]


def verify_quote(card: PaperCard, text: str, loc: str | None = None) -> bool:
    """True if the text sits verbatim inside a stored quote (whose loc must match when given) or, without a loc, the excerpt.

    With `loc` given the quote must come from a stored quote at that location:
    a verbatim sentence under an invented location is a fabricated citation and fails.
    """
    n = normalise(text)
    if len(n) < MIN_LEN:
        return False
    matches = _matching_quotes(card, n)
    if loc is None:
        return bool(matches) or contains_quote(normalise(card.fulltext_excerpt), text)
    want = normalise(loc)
    return bool(want) and any(normalise(q.loc) == want for q in matches)


def verify_quotes(
    cards_by_id: dict[str, PaperCard],
    quotes: list[Quote],
    require_paper: str | None = None,
) -> tuple[list[Quote], list[Quote]]:
    """Split quotes into (ok, failed) by paper id, required paper, text match and loc match."""
    ok: list[Quote] = []
    failed: list[Quote] = []
    for q in quotes:
        card = cards_by_id.get(q.paper_id)
        wrong_paper = require_paper is not None and q.paper_id != require_paper
        if card is None or wrong_paper or not verify_quote(card, q.text, q.loc):
            failed.append(q)
        else:
            ok.append(q)
    return ok, failed
