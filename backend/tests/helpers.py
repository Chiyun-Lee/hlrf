from datetime import date, datetime

from app.schemas import ArxivPaper

FRIDAY = date(2026, 10, 16)
THURSDAY = date(2026, 10, 15)

COSMOLOGY = [
    "Galaxy power spectrum constraints from the effective field theory of large-scale structure",
    "The galaxy bispectrum at one loop in the effective field theory",
    "Redshift-space distortions and baryon acoustic oscillations in galaxy clustering",
    "Cosmological parameter inference from galaxy clustering with perturbation theory",
]
QUBITS = [
    "Superconducting qubit coherence improvements with tantalum",
    "Quantum error correction with surface codes on superconducting processors",
    "Decoherence of transmon qubits from two-level systems",
    "Fast readout of superconducting qubits",
]


def arxiv_paper(paper_id, title, day=FRIDAY, authors=("A. Author",), category="astro-ph.CO", abstract=None):
    return ArxivPaper(
        id=paper_id,
        title=title,
        abstract=abstract or title,
        authors=list(authors),
        categories=[category],
        published=datetime(day.year, day.month, day.day),
        listing_date=day,
    )
