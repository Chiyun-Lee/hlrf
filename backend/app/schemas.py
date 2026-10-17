"""Shared data contract between the extractor, the API and the paper browser."""

from pydantic import BaseModel, field_validator


class Author(BaseModel):
    raw: str  # exactly as printed, so nothing is lost if parsing is wrong
    given: str | None = None
    family: str | None = None
    particle: str | None = None  # "van der", "de la", ...
    suffix: str | None = None  # "Jr.", "III", ...
    is_group: bool = False  # consortium / collaboration authors
    equal_contribution_group: int | None = None  # authors sharing a number contributed equally; only set when the paper says so
    corresponding: bool = False
    affiliations: list[str] = []


class PaperHeader(BaseModel):
    """What Claude reads from the paper."""

    title: str
    authors: list[Author]
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    contribution_notes: str | None = None  # e.g. "* equal contribution; † work done at X"


class Block(BaseModel):
    """A paragraph-ish run of text: a PDF text block, or an HTML heading/paragraph."""

    text: str
    bbox: list[float] | None = None  # [x0, y0, x1, y1] in PDF points from the page's top-left; None for HTML


class Page(BaseModel):
    blocks: list[Block]
    width: float | None = None  # PDF points; None for HTML
    height: float | None = None


class Paper(PaperHeader):
    url: str
    pages: list[Page] = []

    @field_validator("pages", mode="before")
    @classmethod
    def _from_text(cls, pages: list) -> list:
        # Papers saved before blocks existed stored each page as text with paragraphs separated by blank lines.
        return [{"blocks": [{"text": t} for t in p.split("\n\n") if t.strip()]} if isinstance(p, str) else p for p in pages]


class Note(BaseModel):
    """One note laid over a run of consecutive blocks (e.g. a section heading and the paragraphs under it)."""

    first: int  # index of the first block covered
    last: int  # index of the last block covered (inclusive)
    heading: str | None = None  # short, playful title
    bullets: list[str] = []


class PageSummary(BaseModel):
    notes: list[Note]
