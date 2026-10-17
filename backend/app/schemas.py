"""Shared data contract between the extractor, the API and the paper browser."""

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


class Mark(BaseModel):
    """A doodle on a figure: a circle around a feature, or an arrow to it, with a short handwritten note.
    Coordinates are 0-1000 across the page's width and height (for abstract figures: across the cropped figure)."""

    shape: Literal["circle", "arrow"]
    box: list[float]  # [x0, y0, x1, y1] around the feature
    text: str  # a few words
    text_at: list[float]  # [x, y]: centre of the text, in empty space near the feature


class Note(BaseModel):
    """One note laid over the blocks it covers, e.g. a section heading and all the paragraphs under it on this page."""

    kind: Literal["summary", "figure", "aside"]  # aside: not the science (funding, references, ...), just blurred
    blocks: list[int]  # indices of the blocks covered
    heading: str | None = None  # short, playful title; a plain label for asides
    bullets: list[str] = []
    marks: list[Mark] = []  # figure notes: doodles on the figure itself


class PageSummary(BaseModel):
    notes: list[Note]


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
    marks: list[Mark] = []  # filled in by the backend: the figure note's doodles, in the crop's coordinates


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


class Fact(BaseModel):
    kind: Literal["background", "struggle", "strength", "interest", "preference"]
    text: str  # short and concrete, e.g. "Shaky on what a protein backbone is"


class LearnerProfile(BaseModel):
    """What the app has learned about the reader (app/memory.py); they can see and edit it on the My learning page."""

    facts: list[Fact] = []
