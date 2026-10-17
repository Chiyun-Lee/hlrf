"""Shared data contract between the extractor, the API and the paper browser."""

from datetime import date, datetime
from typing import Literal

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
    """One note laid over the blocks it covers, e.g. a section heading and all the paragraphs under it on this page."""

    kind: Literal["summary", "figure", "aside"]  # aside: not the science (funding, references, ...), just blurred
    blocks: list[int]  # indices of the blocks covered
    heading: str | None = None  # short, playful title; a plain label for asides
    bullets: list[str] = []


class PageSummary(BaseModel):
    notes: list[Note]


class Pin(BaseModel):
    """One methods pin on a figure or table (app/pins.py), in two levels: a plain line and a researcher's line."""

    kind: Literal["data", "method", "concern"]  # where the numbers come from / what was done / what to worry about
    title: str  # a few words, shown on the button
    basic: str  # plain language, for anyone
    researcher: str  # precise, with numbers, for researchers
    evidence: Literal["From the paper", "Code re-run", "Tested"]  # how far the claim was checked


class PinTarget(BaseModel):
    """A figure or table that carries pins."""

    label: str  # "Figure 1", "Table II"
    page: int  # 0-indexed
    caption: str  # how its caption starts ("Figure 1."); the pins only show if the page has it right below or above `bbox`
    bbox: list[float]  # [x0, y0, x1, y1] in PDF points from the page's top-left, as in Block.bbox; without the caption
    pins: list[Pin]


class PaperPins(BaseModel):
    """All the pins for one paper: an agent review's for a library paper (stored in the database), or shipped as one
    JSON file per arXiv id in app/pins/."""

    arxiv_id: str | None = None  # without the version; None for a paper not on arXiv
    reviewed: str  # what the pins rest on, shown under each pin
    verdict: str | None = None  # the review's bottom line, in 1-2 sentences
    targets: list[PinTarget]


class Pitch(BaseModel):
    """For you's summary of a new arXiv paper, for one reader (app/pitch.py)."""

    id: str  # arXiv id
    what: str  # what the paper does and finds
    why: str  # why this reader should care, given their own work


class Pitches(BaseModel):
    pitches: list[Pitch]


class ArxivPaper(BaseModel):
    """A new arXiv paper as For you stores and ranks it (app/arxiv.py)."""

    id: str  # without the version: 2410.01234 or hep-th/0101001
    version: int = 1
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]  # primary first
    published: datetime
    listing_date: date  # the day it appears in arXiv's daily "new" listing
    comment: str | None = None
    journal_ref: str | None = None
    doi: str | None = None

    @property
    def abs_url(self) -> str:
        return f"https://arxiv.org/abs/{self.id}"

    @property
    def pdf_url(self) -> str:
        return f"https://arxiv.org/pdf/{self.id}"


class TutorReply(BaseModel):
    reply: str  # the answer shown in the chat
    update_note: bool = False  # true when the note should change (added to or reworded)
    heading: str | None = None  # the note's new title, when update_note and it should change
    bullets: list[str] = []  # the note's complete new bullet list, when update_note


class FlowStep(BaseModel):
    kind: Literal["question", "approach", "finding", "meaning"]
    text: str  # a few words; it sits in a small box


class AbstractFigure(BaseModel):
    figure: str  # which figure note, as "p<page>n<note>" (0-indexed), e.g. "p3n1"
    label: str  # a short handwritten callout: what to notice
    image: str | None = None  # filled in by the backend: data: URI of the figure cropped from the PDF
    width: float | None = None
    height: float | None = None


class GraphicalAbstract(BaseModel):
    """A one-slide memory jog for the whole paper (rendered as SVG by web/abstract.js)."""

    title: str  # playful
    takeaway: str  # the one-line point of the paper
    flow: list[FlowStep]  # what was done and found, in order
    bullets: list[str]  # the handful of things worth remembering
    figures: list[AbstractFigure]  # one or two key figures


class QuizQuestion(BaseModel):
    kind: Literal["choice", "blank"]  # blank: `prompt` has "___" and `options` is the word bank
    prompt: str
    options: list[str]
    answer: int  # index into options
    explanation: str  # one line, shown after answering
    proof: str | None = None  # the note backing the answer, as "p<page>n<note>"; see app/proof.py


class Quiz(BaseModel):
    questions: list[QuizQuestion]


class Quote(BaseModel):
    quote: str  # the exact words from the original text that settle the question


class Proof(BaseModel):
    """The original text behind a quiz answer, for the quiz's "Show me the proof"."""

    page: int
    paragraph: str  # the original paragraph holding the quote
    quote: str | None  # the key words, verbatim from `paragraph` (None if they couldn't be pinned down)
    note: Note  # the summarised version
