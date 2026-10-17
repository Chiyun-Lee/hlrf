import pytest

from app.cards import clean, stated
from app.schemas import ChartItem, PageSummary, Paper, SummaryCards

PAPER = Paper(
    url="u",
    title="T",
    authors=[],
    pages=[{"blocks": [{"text": "We find Ωm = 0.2975 ± 0.0086 and H0 = 68.50 ± 0.58, with a 2.3 σ tension."}]}],
)
NOTES = [PageSummary(notes=[{"kind": "summary", "blocks": [0], "bullets": ["x"]}, {"kind": "figure", "blocks": [0], "bullets": ["y"]}])]


def deck(**overrides) -> SummaryCards:
    base = dict(
        tldr="A takeaway.",
        stats=[{"value": "2.3σ", "label": "tension"}] * 6,
        flow=[{"title": "Q", "detail": "d"}],
        topic="BAO",
        mindmap=[{"title": "b", "points": ["p"]}] * 5,
        findings=["f"],
        evidence=[{"claim": "c", "evidence": "e"}],
        caveats=["c"],
        checks=[{"question": "q", "options": ["a", "b"], "answer": 1, "why": "w"}],
    )
    return SummaryCards.model_validate(base | overrides)


def item(printed, value, low=None, high=None):
    return ChartItem(label="x", value=value, low=low, high=high, printed=printed)


def test_numbers_must_be_printed_in_the_paper():
    text = "Ωm=0.2975±0.0086andH0=68.50±0.58"
    assert stated(item("0.2975 ± 0.0086", 0.2975), text)
    assert stated(item("68.50", 68.5), text)
    assert not stated(item("0.3169 ± 0.0065", 0.3169), text)  # not in the text
    assert not stated(item("0.2975", 0.31), text)  # value doesn't match what's printed
    assert not stated(item("about a third", 0.33), text)


def test_clean_trims_and_drops_bad_content():
    cards = deck(
        checks=[
            {"question": "ok", "options": ["a", "b"], "answer": 1, "why": "w"},
            {"question": "bad index", "options": ["a", "b"], "answer": 5, "why": "w"},
            {"question": "one option", "options": ["a"], "answer": 0, "why": "w"},
        ],
        charts=[
            {"title": "real", "axis": "Ωm", "source": "text", "caption": "c",
             "items": [item("0.2975 ± 0.0086", 0.2975, 0.2889, 0.3061), item("68.50", 68.5, 70, 71)]},
            {"title": "made up", "axis": "x", "source": "?", "caption": "c", "items": [item("1.234", 1.234), item("5.678", 5.678)]},
        ],
        figures=[{"figure": "p0n1", "callout": "fig"}, {"figure": "p0n0", "callout": "not a figure"},
                 {"figure": "p9n9", "callout": "missing"}, {"figure": "p0n1", "callout": "duplicate"}],
    )
    cards = clean(cards, PAPER, NOTES)
    assert len(cards.stats) == 4 and len(cards.mindmap) == 4
    assert [q.question for q in cards.checks] == ["ok"]
    assert [c.title for c in cards.charts] == ["real"]
    assert cards.charts[0].items[1].low is None  # interval not containing the value is dropped
    assert [f.figure for f in cards.figures] == ["p0n1"]


def test_clean_rejects_empty_deck():
    with pytest.raises(RuntimeError):
        clean(deck(tldr=" "), PAPER, NOTES)
