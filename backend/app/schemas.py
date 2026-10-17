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


class CheckedClaim(BaseModel):
    """One of the paper's main claims as an agent review left it, for the Reproduction summary card (web/cards.js)."""

    claim: str  # the paper's claim, in one line
    paper: str  # its number or result as the paper gives it, e.g. "5.4σ"
    rerun: str | None = None  # what re-running the code or testing it gave; None when nothing was run
    status: Literal["holds", "partly", "fails", "untested"]  # after the re-run and the tests
    check: str  # how it was checked, and what was found


class PaperPins(BaseModel):
    """All the pins for one paper: an agent review's for a library paper (stored in the database), or shipped as one
    JSON file per arXiv id in app/pins/. `claims` and `main_problems` fill the summary cards' Reproduction card."""

    arxiv_id: str | None = None  # without the version; None for a paper not on arXiv
    reviewed: str  # what the pins rest on, shown under each pin
    verdict: str | None = None  # the review's bottom line, in 1-2 sentences
    claims: list[CheckedClaim] = []  # the paper's main claims, most important first (a full review gives them)
    main_problems: list[str] = []  # the review's main problems, most important first, one or two sentences each
    targets: list[PinTarget]


class Pitch(BaseModel):
    """For you's summary of a new arXiv paper, for one reader (app/pitch.py)."""

    id: str  # arXiv id
    what: str  # what the paper does and finds
    why: str  # why this reader should care, given their own work


class Pitches(BaseModel):
    pitches: list[Pitch]


class ArxivPaper(BaseModel):
    """A paper as For you stores and ranks it: from arXiv (app/arxiv.py) or bioRxiv (app/biorxiv.py), or one of your
    published papers that isn't on arXiv (source "doi", app/published.py)."""

    id: str  # arXiv: without the version, 2410.01234 or hep-th/0101001; bioRxiv and published papers: the DOI
    version: int = 1
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]  # primary first; a bioRxiv paper has one, its subject
    published: datetime
    listing_date: date  # the day it appears in For you: arXiv's daily "new" listing, or the weekday bioRxiv posted it
    comment: str | None = None
    journal_ref: str | None = None
    doi: str | None = None
    source: Literal["arxiv", "biorxiv", "doi"] = "arxiv"

    @property
    def abs_url(self) -> str:
        if self.source == "biorxiv":
            return f"https://www.biorxiv.org/content/{self.id}v{self.version}"
        if self.source == "doi":
            return f"https://doi.org/{self.id}"
        return f"https://arxiv.org/abs/{self.id}"

    @property
    def pdf_url(self) -> str:
        if self.source == "biorxiv":
            return f"{self.abs_url}.full.pdf"
        if self.source == "doi":
            return self.abs_url  # the publisher's page links its PDF
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
    marks: list[Mark] = []  # filled in by the backend: the figure note's doodles, in the crop's coordinates


class GraphicalAbstract(BaseModel):
    """A one-slide memory jog for the whole paper (rendered as SVG by web/abstract.js)."""

    title: str  # playful
    takeaway: str  # the one-line point of the paper
    flow: list[FlowStep]  # what was done and found, in order
    bullets: list[str]  # the handful of things worth remembering
    figures: list[AbstractFigure]  # one or two key figures


class Stat(BaseModel):
    value: str  # a headline number as printed, e.g. "0.45%"
    label: str  # what it is, a few words


class CardStep(BaseModel):
    title: str  # e.g. "Measure BAO with 2x the volume"
    detail: str  # one line of specifics


class Branch(BaseModel):
    title: str
    points: list[str]


class EvidenceRow(BaseModel):
    claim: str
    evidence: str  # the experiment, dataset or figure/table that supports it


class ChartItem(BaseModel):
    label: str
    value: float
    low: float | None = None  # error bar / interval, when the paper gives one
    high: float | None = None
    printed: str  # the number exactly as printed in the paper, e.g. "0.2975 ± 0.0086"; checked against the text


class Chart(BaseModel):
    """A simple comparison redrawn from numbers the paper states (drawn as a dot plot by web/cards.js)."""

    title: str
    axis: str  # what the values are, with units
    source: str  # where in the paper, e.g. "Table 4"
    caption: str  # one line: what to notice
    items: list[ChartItem]


class CardFigure(BaseModel):
    figure: str  # which figure note, as "p<page>n<note>"
    callout: str  # what to notice
    image: str | None = None  # filled in by the backend, as for AbstractFigure
    width: float | None = None
    height: float | None = None


class SummaryCards(BaseModel):
    """A deck of summary cards for the whole paper (rendered by web/cards.js under the graphical abstract)."""

    tldr: str
    stats: list[Stat]
    flow: list[CardStep]  # question -> what they did -> evidence -> conclusion
    topic: str  # a short name for the centre of the mind map
    mindmap: list[Branch]
    findings: list[str]
    evidence: list[EvidenceRow]
    caveats: list[str]
    charts: list[Chart] = []
    figures: list[CardFigure] = []
    notes_hash: str | None = None  # filled in by the backend: the notes the deck was made from (cards.notes_hash)
    notes_changed: bool = False  # filled in when served: the notes have changed since, so a remake would differ


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
