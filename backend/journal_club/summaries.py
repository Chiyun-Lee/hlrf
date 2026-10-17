"""Executive-summary .md files -> PaperCards, with no LLM call.

The summary template (research/summaries/desi/*.md):

    ---
    id: 2404.03002            citekey: desi2024vi      title: ...
    year: 2024                date: 2024-04-03         authors: [..]
    arxiv: 2404.03002         role: before|target
    ---
    # Executive summary      <paragraphs -> abstract>
    ## Claims                - claim: ... / quote: "..." / loc: "..."
    ## Methods               - ...
    ## Data                  - ...
    ## Limitations           - limit: ... / quote: "..." / loc: "..."
    ## Open questions        - ...

The card id is the citekey (ids are [A-Za-z0-9_-]+, so an arXiv id cannot be one);
the arXiv id is kept as the first line of the abstract. Every quote is stored on the
card, so the quote gate verifies against the summary itself.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from journal_club.cards import EXCERPT_MAX, Claim, Limit, PaperCard, Quote, sanitise_loc, save_card
from journal_club.quotes import too_short

log = logging.getLogger(__name__)

_QUOTE_RE = re.compile(r'^\s*quote:\s*"(.*)"\s*$')
_LOC_RE = re.compile(r'^\s*loc:\s*"(.*)"\s*$')
_ITEM_RE = re.compile(r"^-\s*(claim|limit):\s*(.+?)\s*$")
_BULLET_RE = re.compile(r"^-\s+(.+?)\s*$")


class SummaryError(ValueError):
    """A summary file does not follow the template."""


def _unquote(v: str) -> str:
    """Strip one layer of matching quotes."""
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def _list(v: str) -> list[str]:
    """`[a, "b, c"]` -> ['a', 'b, c']; a bare string -> [string]."""
    v = v.strip()
    if not (v.startswith("[") and v.endswith("]")):
        return [_unquote(v)] if v else []
    inner, out, buf, quote = v[1:-1], [], "", None
    for ch in inner:
        if quote:
            if ch == quote:
                quote = None
            else:
                buf += ch
        elif ch in "\"'":
            quote = ch
        elif ch == ",":
            out.append(buf.strip())
            buf = ""
        else:
            buf += ch
    out.append(buf.strip())
    return [x for x in out if x]


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter dict, body) from a file starting with a `---` block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SummaryError("missing frontmatter")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise SummaryError("unterminated frontmatter") from exc
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return meta, "\n".join(lines[end + 1 :])


def split_sections(body: str) -> dict[str, list[str]]:
    """Map lowercase heading text -> its lines (h1 and h2 both count)."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in body.splitlines():
        m = re.match(r"^#{1,2}\s+(.+?)\s*$", line)
        if m:
            current = m.group(1).strip().lower()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return sections


def _quoted_items(lines: list[str], kind: str, paper_id: str) -> list[dict[str, str]]:
    """Parse `- claim:`/`- limit:` items with their quote and loc lines."""
    items: list[dict[str, str]] = []
    for line in lines:
        m = _ITEM_RE.match(line)
        if m and m.group(1) == kind:
            items.append({"text": m.group(2), "quote": "", "loc": ""})
            continue
        if not items:
            continue
        mq = _QUOTE_RE.match(line)
        if mq:
            items[-1]["quote"] = mq.group(1)
            continue
        ml = _LOC_RE.match(line)
        if ml:
            items[-1]["loc"] = ml.group(1)
    for it in items:
        it["paper_id"] = paper_id
    return items


def _bullets(lines: list[str]) -> list[str]:
    """Plain `- text` bullets."""
    return [m.group(1) for line in lines if (m := _BULLET_RE.match(line))]


def _paragraphs(lines: list[str]) -> str:
    """Join non-empty lines with single spaces."""
    return " ".join(l.strip() for l in lines if l.strip())


def card_from_summary(text: str, source: str = "<summary>") -> PaperCard:
    """Build a PaperCard from one summary file's text."""
    meta, body = parse_frontmatter(text)
    for key in ("citekey", "title", "year", "date"):
        if not meta.get(key):
            raise SummaryError(f"{source}: frontmatter missing {key}")
    pid = _unquote(meta["citekey"])
    sections = split_sections(body)
    if "executive summary" not in sections:
        raise SummaryError(f"{source}: missing '# Executive summary'")
    arxiv = _unquote(meta.get("arxiv") or meta.get("id") or "")
    abstract = _paragraphs(sections["executive summary"])
    if arxiv:
        abstract = f"arXiv:{arxiv}. {abstract}"

    def build(kind: str, section: str) -> list[dict[str, str]]:
        kept = []
        for it in _quoted_items(sections.get(section, []), kind, pid):
            if not it["quote"] or too_short(it["quote"]):
                log.warning("%s: dropped %s without a usable quote: %r", source, kind, it["text"][:60])
                continue
            kept.append(it)
        return kept

    claims = [
        Claim(text=it["text"], quote=Quote(paper_id=pid, text=it["quote"], loc=sanitise_loc(it["loc"])))
        for it in build("claim", "claims")
    ]
    limits = [
        Limit(text=it["text"], quote=Quote(paper_id=pid, text=it["quote"], loc=sanitise_loc(it["loc"])))
        for it in build("limit", "limitations")
    ]
    if not claims:
        raise SummaryError(f"{source}: no claims with quotes")
    return PaperCard(
        id=pid,
        citekey=pid,
        title=_unquote(meta["title"]),
        year=int(_unquote(meta["year"])),
        date=_unquote(meta["date"]),
        authors=_list(meta.get("authors", "")),
        abstract=abstract,
        claims=claims,
        methods=_bullets(sections.get("methods", [])),
        data=_bullets(sections.get("data", [])) + _bullets(sections.get("open questions", [])),
        limits=limits,
        fulltext_excerpt=text[:EXCERPT_MAX],
    )


def load_cards_from_summaries(dir: str | Path) -> list[PaperCard]:
    """Every *.md in dir (README.md excluded), sorted by id."""
    cards = []
    for path in sorted(Path(dir).glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        cards.append(card_from_summary(path.read_text(encoding="utf-8"), str(path)))
    ids = [c.id for c in cards]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise SummaryError(f"duplicate citekeys: {dupes}")
    return sorted(cards, key=lambda c: c.id)


def write_cards_from_summaries(summary_dir: str | Path, cards_dir: str | Path) -> list[Path]:
    """Parse every summary and write <cards_dir>/<citekey>.json."""
    return [save_card(c, cards_dir) for c in load_cards_from_summaries(summary_dir)]
