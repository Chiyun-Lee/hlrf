"""Paper cards: pydantic models, JSON I/O, prompt rendering and PDF ingest (via pymupdf, as app/extract.py)."""

from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from journal_club.llm import LLM
from journal_club.quotes import MIN_LEN, contains_quote, normalise, too_short

log = logging.getLogger(__name__)

ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
LOC_RE = re.compile(r"^[^\]|\r\n]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXCERPT_MAX = 8000
PDF_TEXT_MAX = 60_000
# A paper's text kept beside its card as <id>.txt (save_card), for the backtest's judge: a card's abstract and seven
# quoted sentences miss most of what a paper does (on afconf, reading the full text turned 3 of 8 misses into partials).
FULLTEXT_MAX = 120_000


def _one_line(s: str) -> str:
    """Collapse whitespace to single spaces."""
    return " ".join(s.split())


class Quote(BaseModel):
    """A verbatim passage from one paper."""

    model_config = ConfigDict(extra="forbid")

    paper_id: str
    text: str
    loc: str

    @field_validator("paper_id")
    @classmethod
    def _id(cls, v: str) -> str:
        """paper_id is [A-Za-z0-9_-]+."""
        if not ID_RE.match(v):
            raise ValueError(f"bad paper_id {v!r}")
        return v

    @field_validator("text")
    @classmethod
    def _text(cls, v: str) -> str:
        """Non-empty after strip."""
        if not v.strip():
            raise ValueError("quote text is empty")
        return v

    @field_validator("loc")
    @classmethod
    def _loc(cls, v: str) -> str:
        """No ']', '|' or newline; stripped."""
        v = v.strip()
        if not LOC_RE.match(v):
            raise ValueError(f"bad loc {v!r}")
        return v


class Claim(BaseModel):
    """A claim backed by one quote."""

    model_config = ConfigDict(extra="forbid")

    text: str
    quote: Quote


class Limit(BaseModel):
    """A limitation backed by one quote."""

    model_config = ConfigDict(extra="forbid")

    text: str
    quote: Quote


class PaperCard(BaseModel):
    """What one PhD-student agent knows about its paper."""

    model_config = ConfigDict(extra="forbid")

    id: str
    citekey: str
    title: str
    year: int
    date: str
    authors: list[str]
    abstract: str
    claims: list[Claim]
    methods: list[str]
    data: list[str]
    limits: list[Limit]
    fulltext_excerpt: str

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        """id is [A-Za-z0-9_-]+."""
        if not ID_RE.match(v):
            raise ValueError(f"bad id {v!r}")
        return v

    @field_validator("date")
    @classmethod
    def _date(cls, v: str) -> str:
        """ISO YYYY-MM-DD and a real calendar date."""
        if not DATE_RE.match(v):
            raise ValueError(f"date must be YYYY-MM-DD, got {v!r}")
        dt.date.fromisoformat(v)
        return v

    @field_validator("fulltext_excerpt")
    @classmethod
    def _excerpt(cls, v: str) -> str:
        """At most EXCERPT_MAX chars."""
        if len(v) > EXCERPT_MAX:
            raise ValueError(f"fulltext_excerpt longer than {EXCERPT_MAX}")
        return v

    @model_validator(mode="after")
    def _consistent(self) -> PaperCard:
        """year matches date; every quote belongs to this card."""
        if self.year != int(self.date[:4]):
            raise ValueError(f"year {self.year} != date year {self.date[:4]}")
        for q in self.quotes():
            if q.paper_id != self.id:
                raise ValueError(f"quote paper_id {q.paper_id!r} != card id {self.id!r}")
        return self

    def quotes(self) -> list[Quote]:
        """Claims' quotes then limits' quotes, in order."""
        return [c.quote for c in self.claims] + [l.quote for l in self.limits]


# ------------------------------------------------------------------------ I/O


def load_cards(dir: str | Path) -> list[PaperCard]:
    """Every *.json in dir, sorted by id; duplicate ids raise."""
    cards = [PaperCard.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(Path(dir).glob("*.json"))]
    ids = [c.id for c in cards]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"duplicate card ids: {dupes}")
    return sorted(cards, key=lambda c: c.id)


def save_card(card: PaperCard, dir: str | Path, fulltext: str | None = None) -> Path:
    """Write <dir>/<id>.json, and the paper's text as <dir>/<id>.txt when given (capped at FULLTEXT_MAX)."""
    out = Path(dir) / f"{card.id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(card.model_dump_json(indent=2), encoding="utf-8")
    if fulltext and fulltext.strip():
        out.with_suffix(".txt").write_text(_CONTROL_RE.sub("", fulltext)[:FULLTEXT_MAX], encoding="utf-8")
    return out


def load_fulltexts(dir: str | Path) -> dict[str, str]:
    """{card id: text} for every <id>.txt beside a card in dir; cards without one are left out."""
    ids = {p.stem for p in Path(dir).glob("*.json")}
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted(Path(dir).glob("*.txt")) if p.stem in ids}


# ------------------------------------------------------------------ rendering


def render_quote_line(q: Quote) -> str:
    """The `QUOTE[id|loc]: text` line, single-line."""
    return f"QUOTE[{q.paper_id}|{q.loc}]: {_one_line(q.text)}"


def render_card_for_prompt(card: PaperCard) -> str:
    """The exact card layout of DESIGN.md §4.2; one QUOTE line per stored quote."""
    lines = [
        f"PAPER {card.id} | {card.citekey} | {_one_line(card.title)} | {card.year} | {card.date}",
        f"AUTHORS: {'; '.join(card.authors)}",
        f"ABSTRACT: {_one_line(card.abstract)}",
        f"METHODS: {'; '.join(card.methods)}",
        f"DATA: {'; '.join(card.data)}",
        "CLAIMS:",
    ]
    for c in card.claims:
        lines.append(f"- {_one_line(c.text)}")
        lines.append(f"  {render_quote_line(c.quote)}")
    lines.append("LIMITS:")
    for l in card.limits:
        lines.append(f"- {_one_line(l.text)}")
        lines.append(f"  {render_quote_line(l.quote)}")
    lines.append(f"END PAPER {card.id}")
    return "\n".join(lines)


# --------------------------------------------------------------------- ingest

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def extract_pdf_text(path: str | Path, cap: int = PDF_TEXT_MAX) -> str:
    """Concatenate page texts, strip control chars, cap at `cap` (PDF_TEXT_MAX for ingest, FULLTEXT_MAX to keep)."""
    import pymupdf

    with pymupdf.open(str(path)) as doc:
        text = "\n\n".join(page.get_text() for page in doc)
    text = _CONTROL_RE.sub("", text)
    if len(text) > cap:
        log.warning("ingest: %s truncated from %d to %d chars", path, len(text), cap)
        text = text[:cap]
    return text


def sanitise_id(stem: str) -> str:
    """Replace every char outside [A-Za-z0-9_-] with '_'."""
    out = re.sub(r"[^A-Za-z0-9_-]", "_", stem)
    return out or "paper"


def _year_hint(name: str) -> str:
    """First 4-digit run in the filename, or ''."""
    m = re.search(r"\d{4}", name)
    return m.group(0) if m else ""


def _gate(items: list[dict], text: str, label: str) -> list[dict]:
    """Keep claims/limits whose quote sits verbatim in the full text the model was shown."""
    hay = normalise(text)
    kept = []
    for item in items:
        quote = str(item["quote"].get("text", ""))
        if contains_quote(hay, quote):
            kept.append(item)
        elif too_short(quote):
            log.warning("ingest: dropped %s with quote under %d chars: %r", label, MIN_LEN, quote[:80])
        else:
            log.warning("ingest: dropped %s with unverifiable quote: %r", label, quote[:80])
    return kept


# -- coercion of plausible-but-strict-invalid model output --------------------

_LOC_BAD = str.maketrans({"|": "/", "]": ")", "[": "(", "\r": " ", "\n": " "})
_PARTIAL_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$")
UNKNOWN_LOC = "unknown"


def sanitise_loc(loc: object) -> str:
    """A loc the Quote validator accepts: no `]`, `|` or newline; `unknown` when empty."""
    cleaned = _one_line(str(loc or "").translate(_LOC_BAD))
    return cleaned or UNKNOWN_LOC


def coerce_date(raw_date: object, year: object, year_hint: str) -> str:
    """ISO date from `YYYY`, `YYYY-MM`, `YYYY-MM-DD`, else `<year>-01-01` from `year` or the filename hint."""
    m = _PARTIAL_DATE_RE.match(str(raw_date or "").strip())
    if m:
        y, mo, d = m.group(1), int(m.group(2) or 1), int(m.group(3) or 1)
        try:
            return dt.date(int(y), mo, d).isoformat()
        except ValueError:
            log.warning("ingest: date %r is not a calendar date, falling back to the year", raw_date)
    for candidate in (year, year_hint):
        if re.fullmatch(r"\d{4}", str(candidate)):
            log.warning("ingest: date %r unusable, using %s-01-01", raw_date, candidate)
            return f"{candidate}-01-01"
    raise ValueError(f"ingest: no usable date in {raw_date!r} / year {year!r} / hint {year_hint!r}")


def _coerce_quoted(items: list[dict], paper_id: str, label: str) -> list[dict]:
    """Force every quote onto the known paper id and a legal loc; skip items with no quote text."""
    out: list[dict] = []
    for item in items:
        quote = dict(item.get("quote") or {})
        text = str(quote.get("text", ""))
        if not text.strip():
            log.warning("ingest: dropped %s with empty quote", label)
            continue
        if quote.get("paper_id") != paper_id:
            log.warning("ingest: %s quote paper_id %r replaced by %r", label, quote.get("paper_id"), paper_id)
        loc = sanitise_loc(quote.get("loc"))
        if loc != quote.get("loc"):
            log.warning("ingest: %s quote loc %r sanitised to %r", label, quote.get("loc"), loc)
        out.append({"text": str(item.get("text", "")), "quote": {"paper_id": paper_id, "text": text, "loc": loc}})
    return out


def coerce_ingest(raw: dict, paper_id: str, year_hint: str) -> dict:
    """Repair the shapes a real model plausibly returns so the PaperCard validator accepts them."""
    fixed = dict(raw)
    fixed["date"] = coerce_date(raw.get("date"), raw.get("year"), year_hint)
    year = int(fixed["date"][:4])
    if raw.get("year") != year:
        log.warning("ingest: year %r != date year %d, using the date", raw.get("year"), year)
    fixed["year"] = year
    fixed["claims"] = _coerce_quoted(list(raw.get("claims") or []), paper_id, "claim")
    fixed["limits"] = _coerce_quoted(list(raw.get("limits") or []), paper_id, "limit")
    return fixed


def ingest_text(text: str, paper_id: str, year_hint: str, llm: LLM, source: str = "") -> PaperCard:
    """Paper text -> one `ingest` LLM call -> coercion -> quote gate -> PaperCard (no claim left raises).

    `text` is any plain text of the paper: a PDF's (ingest_pdf) or a library paper's pages (app/club.py)."""
    from journal_club import prompts

    source = source or paper_id
    text = _CONTROL_RE.sub("", text)
    if len(text) > PDF_TEXT_MAX:
        log.warning("ingest: %s truncated from %d to %d chars", source, len(text), PDF_TEXT_MAX)
        text = text[:PDF_TEXT_MAX]
    user = prompts.build_ingest(paper_id=paper_id, year_hint=year_hint, text=text)
    raw = llm.complete_json("ingest", prompts.load_prompt("ingest"), user, prompts.SCHEMAS["ingest"])
    raw = coerce_ingest(raw, paper_id, year_hint)
    # The gate checks the same text the model saw; only the stored excerpt is capped at EXCERPT_MAX.
    raw["claims"] = _gate(raw["claims"], text, "claim")
    raw["limits"] = _gate(raw["limits"], text, "limit")
    if not raw["claims"]:
        raise ValueError(f"ingest: {source}: no claim survived the quote gate; card not written")
    return PaperCard(id=paper_id, fulltext_excerpt=text[:EXCERPT_MAX], **raw)


def ingest_pdf(path: str | Path, llm: LLM) -> PaperCard:
    """A PDF file through ingest_text: its id from the file name, its year hint from the first 4-digit run in it."""
    path = Path(path)
    return ingest_text(extract_pdf_text(path), sanitise_id(path.stem), _year_hint(path.name), llm, source=path.name)
