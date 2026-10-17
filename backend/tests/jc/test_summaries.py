"""Summary .md -> PaperCard parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from journal_club.backtest import split_by_date
from journal_club.quotes import verify_quote
from journal_club.summaries import (
    SummaryError,
    card_from_summary,
    load_cards_from_summaries,
    parse_frontmatter,
    write_cards_from_summaries,
)

DESI = Path(__file__).resolve().parents[2] / "journal_club" / "examples" / "summaries" / "desi"

SAMPLE = '''---
id: 2408.07175
citekey: efstathiou2024
title: Evolving Dark Energy or Supernovae: Systematics?
year: 2024
date: 2024-08-13
authors: [George Efstathiou, "DES Collaboration (T. Abbott)"]
arxiv: 2408.07175
role: before
---

# Executive summary
The paper asks whether the evidence for evolving dark energy is real.
It concludes that it depends on the supernova sample.

## Claims
- claim: The evidence depends strongly on the SN sample.
  quote: "The strength of the evidence for evolving dark energy ranges from 3.9 sigma for the DES5Y SN sample to 2.5 sigma for the Pantheon+ sample."
  loc: "Abstract"
- claim: A fragment that must be dropped.
  quote: "too short"
  loc: "Sec. 9"
- claim: Pantheon+ alone is consistent with Planck LCDM.
  quote: "The cosmology inferred from Pantheon+ sample alone is consistent with the Planck LCDM model and shows no preference for evolving dark energy."
  loc: "Sec. 2 | p. 4"

## Methods
- Fit each catalogue alone to Planck LCDM and w0-wa.

## Data
- Pantheon+ (1417 SN) and DES5Y (1754 SN).

## Limitations
- limit: Union3 could not be analysed because its individual SN are not public.
  quote: "The Union3 compilation for individual SN is not yet in the public domain and would, in any case, require a very different type of analysis."
  loc: "Sec. 1"

## Open questions
- Whether the offset is in Pantheon+, DES5Y, or both.
'''


def test_frontmatter_keeps_colons_in_values() -> None:
    meta, body = parse_frontmatter(SAMPLE)
    assert meta["title"] == "Evolving Dark Energy or Supernovae: Systematics?"
    assert body.lstrip().startswith("# Executive summary")


def test_card_from_sample() -> None:
    card = card_from_summary(SAMPLE, "sample")
    assert card.id == "efstathiou2024" and card.citekey == "efstathiou2024"
    assert card.year == 2024 and card.date == "2024-08-13"
    assert card.authors == ["George Efstathiou", "DES Collaboration (T. Abbott)"]
    assert card.abstract.startswith("arXiv:2408.07175. The paper asks")
    assert [c.text for c in card.claims] == [
        "The evidence depends strongly on the SN sample.",
        "Pantheon+ alone is consistent with Planck LCDM.",
    ]  # the short-quote claim is dropped
    assert card.claims[1].quote.loc == "Sec. 2 / p. 4"  # '|' sanitised
    assert card.methods == ["Fit each catalogue alone to Planck LCDM and w0-wa."]
    assert card.data == [
        "Pantheon+ (1417 SN) and DES5Y (1754 SN).",
        "Whether the offset is in Pantheon+, DES5Y, or both.",
    ]
    assert len(card.limits) == 1
    for q in card.quotes():
        assert q.paper_id == card.id
        assert verify_quote(card, q.text)


def test_missing_frontmatter_raises() -> None:
    with pytest.raises(SummaryError):
        card_from_summary("# Executive summary\nno frontmatter\n", "x")


def test_no_claims_raises() -> None:
    text = SAMPLE.split("## Claims")[0] + "## Claims\n- claim: nothing\n  quote: \"short\"\n  loc: \"p1\"\n"
    with pytest.raises(SummaryError):
        card_from_summary(text, "x")


def test_write_and_reload(tmp_path: Path) -> None:
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "a.md").write_text(SAMPLE, encoding="utf-8")
    (tmp_path / "s" / "README.md").write_text("not a summary", encoding="utf-8")
    paths = write_cards_from_summaries(tmp_path / "s", tmp_path / "cards")
    assert [p.name for p in paths] == ["efstathiou2024.json"]
    from journal_club.cards import load_cards

    assert load_cards(tmp_path / "cards")[0].id == "efstathiou2024"


@pytest.mark.skipif(not DESI.exists(), reason="DESI summaries not present")
def test_real_desi_summaries_parse_and_split() -> None:
    cards = load_cards_from_summaries(DESI)
    assert len(cards) == 9
    before, after = split_by_date(cards, "2025-01-01")
    assert len(before) == 8 and [c.id for c in after] == ["desidr2ii"]
    for card in cards:
        assert len(card.claims) >= 4 and len(card.limits) >= 2
        for q in card.quotes():
            assert verify_quote(card, q.text), (card.id, q.text[:60])
