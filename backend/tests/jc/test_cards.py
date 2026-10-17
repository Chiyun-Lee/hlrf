"""Card models, rendering, JSON round-trip and PDF ingest."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

import pytest
from pydantic import ValidationError

from journal_club import cards as cards_mod
from journal_club.cards import (
    EXCERPT_MAX,
    PaperCard,
    Quote,
    coerce_date,
    ingest_pdf,
    load_cards,
    render_card_for_prompt,
    sanitise_loc,
    save_card,
)
from journal_club.llm import QUOTE_RE, MockLLM
from journal_club.quotes import MIN_LEN, verify_quote
from .conftest import FIXTURE_CARDS, make_pdf


def test_fixture_set(cards: list[PaperCard]) -> None:
    assert [c.id for c in cards] == [f"sc{i:02d}" for i in range(1, 9)]
    assert all(2019 <= c.year <= 2024 for c in cards)
    assert all(2 <= len(c.claims) <= 3 and 1 <= len(c.limits) <= 2 for c in cards)


def test_round_trip_json(cards: list[PaperCard], tmp_path: Path) -> None:
    for c in cards:
        p = save_card(c, tmp_path)
        assert p.name == f"{c.id}.json"
        assert PaperCard.model_validate_json(p.read_text()) == c
    assert load_cards(tmp_path) == cards


def test_duplicate_ids_raise(cards: list[PaperCard], tmp_path: Path) -> None:
    save_card(cards[0], tmp_path)
    (tmp_path / "copy.json").write_text(cards[0].model_dump_json())
    with pytest.raises(ValueError, match="duplicate"):
        load_cards(tmp_path)


def test_render_emits_every_quote_once_and_quotes_in_excerpt(cards: list[PaperCard]) -> None:
    all_texts: list[str] = []
    for c in cards:
        rendered = render_card_for_prompt(c)
        found = QUOTE_RE.findall(rendered)
        assert [(pid, loc, text) for pid, loc, text in found] == [
            (q.paper_id, q.loc, q.text) for q in c.quotes()
        ]
        assert rendered.count("QUOTE[") == len(c.quotes())
        assert rendered.startswith(f"PAPER {c.id} | {c.citekey} | ")
        assert rendered.endswith(f"END PAPER {c.id}")
        for q in c.quotes():
            assert q.text in c.fulltext_excerpt
            assert verify_quote(c, q.text)
            all_texts.append(q.text)
    assert len(set(all_texts)) == len(all_texts), "quotes must be unique across the set"


def test_quotes_order(cards: list[PaperCard]) -> None:
    c = cards[0]
    assert c.quotes() == [cl.quote for cl in c.claims] + [l.quote for l in c.limits]


@pytest.mark.parametrize("loc", ["p4 §3]", "p4 | 3", "p4\n3", "   "])
def test_bad_loc_rejected(loc: str) -> None:
    with pytest.raises(ValidationError):
        Quote(paper_id="sc01", text="some text here", loc=loc)


def test_loc_stripped() -> None:
    assert Quote(paper_id="sc01", text="x", loc="  p4 §3  ").loc == "p4 §3"


def test_bad_paper_id_and_empty_text() -> None:
    with pytest.raises(ValidationError):
        Quote(paper_id="sc 01", text="x", loc="p1")
    with pytest.raises(ValidationError):
        Quote(paper_id="sc01", text="   ", loc="p1")


def _base(cards: list[PaperCard]) -> dict:
    """sc01 as a dict."""
    return cards[0].model_dump()


@pytest.mark.parametrize("date", ["2019-3-4", "2019/03/04", "2019-13-01", "March 2019"])
def test_bad_date_rejected(cards: list[PaperCard], date: str) -> None:
    d = _base(cards)
    d["date"] = date
    with pytest.raises(ValidationError):
        PaperCard.model_validate(d)


def test_year_date_mismatch_rejected(cards: list[PaperCard]) -> None:
    d = _base(cards)
    d["year"] = 2020
    with pytest.raises(ValidationError, match="year"):
        PaperCard.model_validate(d)


def test_quote_paper_id_mismatch_rejected(cards: list[PaperCard]) -> None:
    d = _base(cards)
    d["claims"][0]["quote"]["paper_id"] = "sc02"
    with pytest.raises(ValidationError, match="paper_id"):
        PaperCard.model_validate(d)


def test_extra_field_rejected(cards: list[PaperCard]) -> None:
    d = _base(cards)
    d["venue"] = "x"
    with pytest.raises(ValidationError):
        PaperCard.model_validate(d)


def test_fixture_files_are_valid_json() -> None:
    for p in sorted(FIXTURE_CARDS.glob("*.json")):
        json.loads(p.read_text())


PDF_LINES = [
    "Spike-in lines as ground truth 2021",
    "We sequence three spike-in cell lines in every batch of the experiment.",
    "Any difference between spike-in cells after integration is residual batch effect.",
    "The design applies only to newly generated data and not to public datasets.",
    "We release the dataset and code.",
]


def test_ingest_pdf_with_mock(tmp_path: Path) -> None:
    pdf = make_pdf(tmp_path / "oyelaran 2021 (spike-in).pdf", PDF_LINES)
    card = ingest_pdf(pdf, MockLLM())
    assert card.id == "oyelaran_2021__spike-in_"
    assert card.year == 2021 and card.date == "2021-01-01"
    assert len(card.claims) == 2 and len(card.limits) == 1
    for q in card.quotes():
        assert q.paper_id == card.id
        assert verify_quote(card, q.text)
    assert PDF_LINES[1] in card.fulltext_excerpt


def _ingest_with(tmp_path: Path, mutate: Callable[[dict], None], name: str = "kim2019.pdf") -> PaperCard:
    """Ingest a fixture PDF through a mock whose plausible output is mutated by `mutate`."""
    pdf = make_pdf(tmp_path / name, PDF_LINES)
    mock = MockLLM()

    def scripted(user: str) -> dict:
        raw = mock.default("ingest", user, {})
        mutate(raw)
        return raw

    mock.scripted["ingest"] = scripted
    return ingest_pdf(pdf, mock)


def _set_quote(raw: dict, **fields: str) -> None:
    """Overwrite fields of the first claim's quote."""
    raw["claims"][0]["quote"].update(fields)


@pytest.mark.parametrize(
    ("label", "mutate", "check"),
    [
        ("paper_id=citekey", lambda r: _set_quote(r, paper_id="kim2019batchalign"), lambda c: c.quotes()[0].paper_id == "kim2019"),
        ("loc with pipe", lambda r: _set_quote(r, loc="p3 | Table 2"), lambda c: c.quotes()[0].loc == "p3 / Table 2"),
        ("loc with bracket", lambda r: _set_quote(r, loc="[p3]"), lambda c: c.quotes()[0].loc == "(p3)"),
        ("loc with newline", lambda r: _set_quote(r, loc="p3\nTable 2"), lambda c: c.quotes()[0].loc == "p3 Table 2"),
        ("empty loc", lambda r: _set_quote(r, loc=""), lambda c: c.quotes()[0].loc == "unknown"),
        ("date=2019", lambda r: r.update(date="2019"), lambda c: (c.date, c.year) == ("2019-01-01", 2019)),
        ("date=2019-03", lambda r: r.update(date="2019-03"), lambda c: (c.date, c.year) == ("2019-03-01", 2019)),
        ("year!=date", lambda r: r.update(year=2018, date="2019-03-04"), lambda c: (c.date, c.year) == ("2019-03-04", 2019)),
        ("date prose", lambda r: r.update(date="March 2019", year=2019), lambda c: c.date == "2019-01-01"),
        ("date and year junk", lambda r: r.update(date="soon", year=0), lambda c: c.date == "2019-01-01"),
        ("date not a calendar day", lambda r: r.update(date="2019-02-30", year=2019), lambda c: c.date == "2019-01-01"),
    ],
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_ingest_coerces_plausible_model_output(tmp_path: Path, label: str, mutate: Callable[[dict], None], check: Callable[[PaperCard], bool]) -> None:
    card = _ingest_with(tmp_path, mutate)
    assert card.id == "kim2019"
    assert check(card), label
    assert len(card.claims) == 2 and len(card.limits) == 1, "coercion never costs a verified claim"
    for q in card.quotes():
        assert q.paper_id == card.id and verify_quote(card, q.text)


def test_ingest_with_no_surviving_claim_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no claim survived"):
        _ingest_with(tmp_path, lambda r: r.update(claims=[]))
    with pytest.raises(ValueError, match="no claim survived"):
        _ingest_with(tmp_path, lambda r: [_set_quote(r, text="not in the paper, long enough to pass the length gate"), r["claims"].pop(1)])


def test_ingest_drops_claim_with_empty_quote_text(tmp_path: Path) -> None:
    card = _ingest_with(tmp_path, lambda r: _set_quote(r, text="   "))
    assert len(card.claims) == 1 and len(card.limits) == 1


def test_coerce_date_and_sanitise_loc_units() -> None:
    assert coerce_date("2021-06-15", 2021, "") == "2021-06-15"
    assert coerce_date("2021-6-5", 2021, "") == "2021-06-05"
    assert coerce_date("2021", 1999, "") == "2021-01-01"
    assert coerce_date("", 2021, "") == "2021-01-01"
    assert coerce_date(None, "x", "2020") == "2020-01-01"
    with pytest.raises(ValueError):
        coerce_date("soon", 0, "")
    assert sanitise_loc("p3 | Table 2]") == "p3 / Table 2)"
    assert sanitise_loc(None) == "unknown" and sanitise_loc("  ") == "unknown"
    assert Quote(paper_id="x", text="t", loc=sanitise_loc("[a|b]\nc")).loc == "(a/b) c"


def test_ingest_drops_unverifiable_quote(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    pdf = make_pdf(tmp_path / "paper.pdf", PDF_LINES)
    mock = MockLLM()

    def bad_ingest(user: str) -> dict:
        out = mock.default("ingest", user, {})
        out["claims"].append(
            {"text": "invented", "quote": {"paper_id": "paper", "text": "This sentence is not in the paper at all.", "loc": "p9"}}
        )
        return out

    mock.scripted["ingest"] = bad_ingest
    with caplog.at_level(logging.WARNING):
        card = ingest_pdf(pdf, mock)
    assert len(card.claims) == 2
    assert any("unverifiable quote" in r.message for r in caplog.records)


# ----------------------------------------------------------- ingest gate window


def _long_paper_text() -> tuple[str, str, str]:
    """A 30k-char paper text with one quotable sentence early and one deep in the discussion (past EXCERPT_MAX)."""
    early = "We propose a mutual-neighbour graph that aligns matching populations across sequencing batches."
    late = "A limitation of our approach is that the runtime scales quadratically with the number of batches."
    filler = "This filler sentence pads the introduction and the results so the text grows past the excerpt window. "
    text = "Title of the paper\n" + early + " " + filler * 160 + late + " " + filler * 140
    assert len(text) > 3 * EXCERPT_MAX and text.index(late) > 2 * EXCERPT_MAX
    return text, early, late


def _scripted_ingest(items: list[tuple[str, str]], limits: list[tuple[str, str]]) -> Callable[[str], dict]:
    """An honest model that quotes exactly the given sentences."""

    def go(user: str) -> dict:
        pid = user.splitlines()[0].split(": ", 1)[1]

        def item(label: str, sentence: str) -> dict:
            return {"text": label, "quote": {"paper_id": pid, "text": sentence, "loc": "p12 §5"}}

        return {
            "citekey": "x2021y", "title": "T", "year": 2021, "date": "2021-01-01", "authors": ["A"], "abstract": "ab",
            "claims": [item(*i) for i in items], "methods": ["m"], "data": ["d"], "limits": [item(*i) for i in limits],
        }

    return go


def test_ingest_gate_checks_the_full_text_the_model_saw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A verbatim quote from beyond EXCERPT_MAX (results, discussion, limitations) must survive the gate."""
    text, early, late = _long_paper_text()
    monkeypatch.setattr(cards_mod, "extract_pdf_text", lambda p: text)
    pdf = make_pdf(tmp_path / "paper_2021.pdf", ["x"])
    mock = MockLLM(scripted={"ingest": _scripted_ingest([("early claim", early), ("late claim", late)], [("late limit", late)])})
    card = ingest_pdf(pdf, mock)
    assert [c.text for c in card.claims] == ["early claim", "late claim"]
    assert [l.text for l in card.limits] == ["late limit"]
    assert card.fulltext_excerpt == text[:EXCERPT_MAX] and late not in card.fulltext_excerpt
    for q in card.quotes():
        assert verify_quote(card, q.text, q.loc), "stored quotes verify in later rounds regardless of the excerpt"


def test_ingest_card_with_only_late_quotes_is_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text, _, late = _long_paper_text()
    monkeypatch.setattr(cards_mod, "extract_pdf_text", lambda p: text)
    pdf = make_pdf(tmp_path / "paper_2021.pdf", ["x"])
    card = ingest_pdf(pdf, MockLLM(scripted={"ingest": _scripted_ingest([("late claim", late)], [])}))
    assert len(card.claims) == 1 and card.claims[0].quote.text == late


def test_ingest_gate_still_rejects_text_beyond_the_model_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate checks what the model saw: a sentence the truncation removed cannot be quoted."""
    text, _, late = _long_paper_text()
    beyond = "This sentence only exists past the sixty thousand character truncation point of the extractor."
    monkeypatch.setattr(cards_mod, "extract_pdf_text", lambda p: text)
    pdf = make_pdf(tmp_path / "paper_2021.pdf", ["x"])
    mock = MockLLM(scripted={"ingest": _scripted_ingest([("late claim", late), ("beyond", beyond)], [])})
    card = ingest_pdf(pdf, mock)
    assert [c.text for c in card.claims] == ["late claim"]


def test_ingest_short_quote_is_dropped_with_its_own_reason(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    short = "We release the dataset and code."
    assert short in PDF_LINES and len(short) < MIN_LEN
    pdf = make_pdf(tmp_path / "paper.pdf", PDF_LINES)
    mock = MockLLM()

    def with_short(user: str) -> dict:
        out = mock.default("ingest", user, {})
        out["limits"].append({"text": "short", "quote": {"paper_id": "paper", "text": short, "loc": "p9"}})
        return out

    mock.scripted["ingest"] = with_short
    with caplog.at_level(logging.WARNING):
        card = ingest_pdf(pdf, mock)
    assert len(card.limits) == 1
    assert any(f"under {MIN_LEN} chars" in r.message for r in caplog.records)
