"""Shared data contract between the agent, the API and (later) the reader app."""

from typing import Literal

from pydantic import BaseModel

Source = Literal["document", "crossref", "semantic_scholar", "arxiv", "page_meta"]
Role = Literal["background", "method-used", "compared-against", "dataset", "extends", "contradicts"]


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


class CitationContext(BaseModel):
    sentence: str
    section: str | None = None
    page: int | None = None
    role: Role


class Reference(BaseModel):
    label: str  # "[12]" or "Smith et al. 2020"
    raw: str  # the bibliography entry as printed
    title: str | None = None
    authors: list[Author] = []
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    source: Source = "document"  # where the resolved metadata came from
    confidence: float  # 0-1, how sure we are the metadata identifies the right work
    contexts: list[CitationContext] = []


class Paper(BaseModel):
    url: str
    title: str
    authors: list[Author]
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    contribution_notes: str | None = None  # e.g. "* equal contribution; † work done at X"
    references: list[Reference] = []
