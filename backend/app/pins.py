"""Methods pins: buttons on a paper's figures and tables saying where its data come from, what its methods do and what
a reviewer would worry about, each in a plain line and a researcher's line. They are written offline (e.g. from a
paper2agent review that re-ran the paper's code) as one JSON file per arXiv id in app/pins/."""

import logging
from pathlib import Path

from . import feed
from .schemas import Paper, PaperPins, PinTarget

PINS_DIR = Path(__file__).parent / "pins"
CAPTION_GAP = 40  # PDF points: how far below a figure or table its caption may start

log = logging.getLogger(__name__)


def load(arxiv_id: str) -> PaperPins | None:
    path = PINS_DIR / f"{arxiv_id.replace('/', '_')}.json"  # old-style ids (hep-th/0101001) have a slash
    return PaperPins.model_validate_json(path.read_text()) if path.exists() else None


def for_paper(paper: Paper) -> PaperPins | None:
    """The paper's pins, keeping the figures and tables they fit. Boxes are measured on one version of the PDF, so a
    figure only gets its pins when this PDF has its caption just below the box; on another version they are dropped,
    never misplaced."""
    arxiv_id = feed.arxiv_id(paper.url, paper.arxiv_id)
    pins = load(arxiv_id) if arxiv_id else None
    if not pins:
        return None
    found = [t for t in pins.targets if fits(t, paper)]
    if len(found) < len(pins.targets):
        log.warning("pins for %s: %d of %d targets don't match this PDF", arxiv_id, len(pins.targets) - len(found), len(pins.targets))
    return pins.model_copy(update={"targets": found}) if found else None


def fits(target: PinTarget, paper: Paper) -> bool:
    if not 0 <= target.page < len(paper.pages):
        return False
    bottom = target.bbox[3]
    return any(
        b.bbox and b.text.startswith(target.caption) and 0 <= b.bbox[1] - bottom <= CAPTION_GAP
        for b in paper.pages[target.page].blocks
    )
