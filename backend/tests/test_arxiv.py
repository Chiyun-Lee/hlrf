from datetime import date, datetime
from pathlib import Path

import pytest

from app.arxiv import listing_date, parse, query

FIXTURE = Path(__file__).parent / "fixtures" / "arxiv_sample.xml"


def test_parse_reads_every_field():
    first, old = parse(FIXTURE.read_bytes())
    assert (first.id, first.version) == ("2610.01234", 2)
    assert first.title == "The galaxy bispectrum at one loop"
    assert first.abstract == "We compute the one-loop galaxy bispectrum in the EFTofLSS."
    assert first.authors == ["Jane Doe", "John Smith"]
    assert first.categories == ["astro-ph.CO", "gr-qc"]  # primary first
    assert first.published == datetime(2026, 10, 12, 19, 30)
    assert first.listing_date == date(2026, 10, 14)
    assert (first.comment, first.journal_ref, first.doi) == ("30 pages, 8 figures", "JCAP 10 (2026) 001", "10.1000/xyz123")
    assert (old.id, old.version, old.comment) == ("astro-ph/0601001", 1, None)


def test_error_entries_are_skipped():
    xml = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/api/errors#bad_id</id></entry></feed>'
    assert parse(xml) == []


@pytest.mark.parametrize(
    ("submitted_utc", "expected"),
    [
        (datetime(2026, 10, 12, 14, 0), date(2026, 10, 13)),  # Mon 10:00 ET -> Tue
        (datetime(2026, 10, 12, 19, 30), date(2026, 10, 14)),  # Mon 15:30 ET, past the deadline -> Wed
        (datetime(2026, 10, 16, 14, 0), date(2026, 10, 19)),  # Fri 10:00 ET -> Mon
        (datetime(2026, 10, 17, 12, 0), date(2026, 10, 20)),  # Saturday -> Tue
        (datetime(2026, 1, 12, 18, 30), date(2026, 1, 13)),  # Mon 13:30 EST in winter, before the deadline -> Tue
    ],
)
def test_listing_date_follows_the_14h_eastern_deadline(submitted_utc, expected):
    assert listing_date(submitted_utc) == expected


def test_query():
    q = query(["astro-ph.CO", "gr-qc"], date(2026, 10, 14), date(2026, 10, 16))
    assert q == "(cat:astro-ph.CO OR cat:gr-qc) AND submittedDate:[202610140000 TO 202610162359]"


def test_titles_match_across_latex_and_punctuation():
    from app.arxiv import same_title, words

    assert words("$\\texttt{SwiftC}_\\ell$: fast differentiable") == ["fast", "differentiable"]
    assert same_title("SwiftCℓ: fast differentiable angular power spectra beyond Limber", "$\\texttt{SwiftC}_\\ell$: fast differentiable angular power spectra beyond Limber")
    assert same_title("Restoring concordance with early dark energy?", "Restoring Concordance with Early Dark Energy")
    assert not same_title("Dark energy", "Dark energy and massive neutrinos in the CMB")  # too short to count as contained
