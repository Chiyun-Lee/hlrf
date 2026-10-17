"""Minutes and per-paper notes rendered purely from archive events and cards (no LLM)."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from journal_club.archive import Archive, Event, Step
from journal_club.cards import PaperCard, Quote
from journal_club.rounds.explore import hypotheses_from, ranked, reviews_from

log = logging.getLogger(__name__)

REJECTED_TYPES = ("quote_rejected", "turn_unverified", "direction_rejected", "hypothesis_rejected", "critique_unverified")


# ------------------------------------------------------------------ events


def _window(events: list[Event], step: Step) -> list[Event]:
    """Events of `step` after its last step_started, if a step_done follows; else all of them."""
    evs = [e for e in events if e.step == step]
    starts = [i for i, e in enumerate(evs) if e.type == "step_started"]
    if not starts:
        return evs
    tail = evs[starts[-1] :]
    if any(e.type == "step_done" for e in tail):
        return tail
    return evs


def _directions(events: list[Event], step: Step = "directions") -> list[dict]:
    """Direction payloads of one step, ranked by confidence (stable)."""
    found = [e.payload for e in _window(events, step) if e.type == "direction"]
    return sorted(found, key=lambda d: -float(d.get("confidence", 0.0)))


def _disputes(events: list[Event]) -> list[dict]:
    """Dispute payloads keyed by (a, b), last wins, in first-seen order."""
    by_pair: dict[tuple[str, str], dict] = {}
    for e in _window(events, "debate"):
        if e.type == "dispute":
            by_pair[(e.payload["a"], e.payload["b"])] = e.payload
    return list(by_pair.values())


def _hypotheses(events: list[Event]) -> list[dict]:
    """Review payloads, ranked by the round-2 tournament (dropped last), then any hypotheses not reviewed yet, with
    `decision` None."""
    proposed = hypotheses_from([e for e in events if e.step == "hypotheses"])
    done = reviews_from([e for e in events if e.step == "critique"])
    reviewed = [r.model_dump() for r in ranked([done[h.id] for h in proposed if h.id in done])]
    waiting = [
        {"hypothesis": h.model_dump(), "original": None, "critiques": [], "decision": None, "reason": "", "wins": 0, "played": 0}
        for h in proposed
        if h.id not in done
    ]
    return reviewed + waiting


def _run_started(events: list[Event]) -> dict:
    """Payload of the first run_started event, or {}."""
    return next((e.payload for e in events if e.type == "run_started"), {})


def _agenda(events: list[Event]) -> str:
    """The latest agenda: last agenda_changed.new, else run_started.agenda."""
    changes = [e.payload.get("new", "") for e in events if e.type == "agenda_changed"]
    return changes[-1] if changes else str(_run_started(events).get("agenda", ""))


def _rejected_counts(events: list[Event]) -> dict[str, int]:
    """Count of every rejection event type across the archive."""
    return {t: sum(1 for e in events if e.type == t) for t in REJECTED_TYPES}


def _pairs(events: list[Event], relation: str) -> list[dict]:
    """Pair-verdict payloads of one relation from the last map window, in event order."""
    return [e.payload for e in _window(events, "map") if e.type == "pair_verdict" and e.payload.get("relation") == relation]


def _synthesis(events: list[Event]) -> dict | None:
    """Payload of the last synthesis event, if any."""
    found = [e.payload for e in _window(events, "synthesis") if e.type == "synthesis"]
    return found[-1] if found else None


def _report(events: list[Event]) -> dict | None:
    """Payload of the last backtest report event, if any."""
    reports = [e.payload for e in events if e.step == "backtest" and e.type == "report"]
    return reports[-1] if reports else None


def cards_from_archive(archive: Archive) -> list[PaperCard]:
    """Rebuild the cards from the run_started snapshot, sorted by id."""
    snapshot = _run_started(archive.read()).get("cards")
    if snapshot is None:
        raise ValueError(f"no run_started event with a card snapshot in {archive.path}")
    return sorted((PaperCard.model_validate(c) for c in snapshot), key=lambda c: c.id)


# ---------------------------------------------------------------- rendering


def _citekey(by_id: dict[str, PaperCard], pid: str) -> str:
    """Citekey of a card id, or the id itself when unknown."""
    card = by_id.get(pid)
    return card.citekey if card else pid


def _quote_line(by_id: dict[str, PaperCard], raw: dict) -> str:
    """`> text (citekey, loc)` for one dumped quote."""
    q = Quote.model_validate(raw)
    return f"> {' '.join(q.text.split())} ({_citekey(by_id, q.paper_id)}, {q.loc})"


def _direction_block(i: int, d: dict, by_id: dict[str, PaperCard]) -> list[str]:
    """Markdown lines for one ranked direction."""
    papers = ", ".join(_citekey(by_id, p) for p in d.get("papers", []))
    lines = [
        f"{i}. **{d['text']}** (confidence {float(d.get('confidence', 0.0)):.2f})",
        f"   from {d.get('from_a', '')} to {d.get('to_b', '')}, because {d.get('because', '')}; papers: {papers}",
    ]
    lines.extend(f"   {_quote_line(by_id, q)}" for q in d.get("quotes", []))
    return lines


DECISIONS = {"keep": "kept", "revise": "revised", "drop": "dropped", None: "not reviewed yet"}


def _hypothesis_block(i: int, r: dict, by_id: dict[str, PaperCard]) -> list[str]:
    """Markdown lines for one hypothesis: the idea, its test, its premises and what round 2 made of it."""
    h = r["hypothesis"]
    tally = f", won {r['wins']} of {r['played']}" if r.get("played") else ""
    lines = [
        f"{i}. **{h['text']}** ({DECISIONS.get(r.get('decision'), r.get('decision'))}{tally}; {h['source']})",
        f"   mechanism: {h['mechanism']}",
        f"   test: {h['test']}",
        f"   prediction: {h['prediction']}",
    ]
    if r.get("original"):
        lines.append(f"   revised from: {r['original']}")
    lines.extend(f"   {_quote_line(by_id, q)}" for q in h.get("quotes", []))
    for c in r.get("critiques", []):
        flag = "" if c.get("verified") else ", unverified"
        lines.append(f"   - {_citekey(by_id, c['speaker'])} {c['stance']}{flag}: {' '.join(str(c['text']).split())}")
    if r.get("reason"):
        lines.append(f"   - PI: {r['reason']}")
    return lines


def _turn_line(t: dict) -> str:
    """`- [speaker] (verified|unverified) text` for one turn."""
    flag = "verified" if t.get("verified") else "unverified"
    return f"- [{t.get('speaker', '?')}] ({flag}) {' '.join(str(t.get('text', '')).split())}"


def _dispute_block(d: dict, by_id: dict[str, PaperCard]) -> list[str]:
    """Markdown lines for one dispute."""
    lines = [
        f"### {_citekey(by_id, d['a'])} vs {_citekey(by_id, d['b'])}",
        f"- claim: {d.get('claim', '')}",
        f"- verdict: **{d.get('verdict', '')}**",
        f"- reason: {d.get('judge_reason', '')}",
    ]
    lines.extend(_turn_line(t) for t in d.get("turns", []))
    return lines


def _hits_summary(hits: list[dict], weighted: float) -> str:
    """`h/n hits, p partial (weighted w)` for one arm."""
    n_hit = sum(1 for h in hits if h.get("verdict") == "hit")
    n_partial = sum(1 for h in hits if h.get("verdict") == "partial")
    return f"{n_hit}/{len(hits)} hits, {n_partial} partial (weighted {weighted:.2f})"


def _backtest_section(report: dict) -> list[str]:
    """The `## Backtest` lines from a report payload."""
    club = _hits_summary(report.get("club_hits", []), float(report.get("club_weighted_rate", 0.0)))
    base = _hits_summary(report.get("baseline_hits", []), float(report.get("baseline_weighted_rate", 0.0)))
    return ["## Backtest", "", f"Club: {club}. Baseline: {base}. Judge model: {report.get('judge_model', '')}.", ""]


KIND_LABELS = {"consensus": "Agreed", "dissent": "Disputed", "gap": "Open", "direction": "Next"}


def _overview_section(synthesis: dict | None, by_id: dict[str, PaperCard]) -> list[str]:
    """`## Overview`: the prose, then the key points grouped by kind with their quotes."""
    lines = ["## Overview", ""]
    if synthesis is None:
        return lines + ["(no synthesis in the archive)", ""]
    lines += [" ".join(str(synthesis.get("overview", "")).split()), ""]
    for kind, label in KIND_LABELS.items():
        points = [k for k in synthesis.get("key_points", []) if k.get("kind") == kind]
        for k in points:
            lines.append(f"- **{label}:** {' '.join(str(k.get('text', '')).split())}")
            lines.extend(f"  {_quote_line(by_id, q)}" for q in k.get("quotes", []))
    lines.append("")
    return lines


def _pairs_section(title: str, pairs: list[dict], by_id: dict[str, PaperCard]) -> list[str]:
    """A section listing pair verdicts of one relation, each with its two quotes."""
    lines = [title, ""]
    if not pairs:
        return lines + ["(none)", ""]
    for p in pairs:
        lines.append(f"- {_citekey(by_id, p['a'])} and {_citekey(by_id, p['b'])}: {' '.join(str(p.get('note', '')).split())}")
        lines.append(f"  {_quote_line(by_id, p['quote_a'])}")
        lines.append(f"  {_quote_line(by_id, p['quote_b'])}")
    lines.append("")
    return lines


def render_minutes(events: list[Event], cards: list[PaperCard]) -> str:
    """Markdown minutes from events and cards; pure."""
    by_id = {c.id: c for c in cards}
    started = _run_started(events)
    directions = _directions(events)
    disputes = _disputes(events)
    lines = [
        "# Minutes",
        "",
        f"- agenda: {_agenda(events)}",
        f"- date: {dt.date.today().isoformat()}",
        f"- model: {started.get('model', '')}",
        f"- cards: {len(cards)}",
        "",
    ]
    lines.extend(_overview_section(_synthesis(events), by_id))
    lines.extend(_pairs_section("## Consensus", _pairs(events, "agree"), by_id))
    lines.extend(_pairs_section("## Shared limitations", _pairs(events, "shared_limitation"), by_id))
    lines.extend(["## Directions", ""])
    if directions:
        for i, d in enumerate(directions, start=1):
            lines.extend(_direction_block(i, d, by_id))
            lines.append("")
    else:
        lines.extend(["(none)", ""])
    hypotheses = _hypotheses(events)
    if hypotheses or any(e.step == "hypotheses" for e in events):
        lines.extend(["## Hypotheses", ""])
        for i, r in enumerate(hypotheses, start=1):
            lines.extend(_hypothesis_block(i, r, by_id))
            lines.append("")
        if not hypotheses:
            lines.extend(["(none)", ""])
    lines.extend(["## Disputes", ""])
    if disputes:
        for d in disputes:
            lines.extend(_dispute_block(d, by_id))
            lines.append("")
    else:
        lines.extend(["(none)", ""])
    lines.extend(["## Unresolved", ""])
    unresolved = [d for d in disputes if d.get("verdict") == "unresolved"]
    lines.extend(
        [f"- {_citekey(by_id, d['a'])} vs {_citekey(by_id, d['b'])}: {d.get('claim', '')}" for d in unresolved] or ["(none)"]
    )
    lines.append("")
    lines.extend(["## Rejected", ""])
    lines.extend(f"- {t}: {n}" for t, n in _rejected_counts(events).items())
    lines.append("")
    report = _report(events)
    if report is not None:
        lines.extend(_backtest_section(report))
    return "\n".join(lines)


def write_minutes(archive: Archive, cards: list[PaperCard], path: str | Path) -> str:
    """Render the minutes, write them to `path`, append a `written` event, return the markdown."""
    events = archive.read()
    md = render_minutes(events, cards)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    payload = {"path": str(out), "n_directions": len(_directions(events)), "n_disputes": len(_disputes(events))}
    archive.append(Event(round=1, step="minutes", type="written", papers=[], payload=payload, seq=0))
    log.info("minutes written to %s (%d directions, %d disputes)", out, payload["n_directions"], payload["n_disputes"])
    return md


# ------------------------------------------------------------- zotero notes


def _direction_note(d: dict, by_id: dict[str, PaperCard]) -> list[str]:
    """`- text (confidence)` then every verified quote as `> text (citekey, loc)`."""
    lines = [f"- {d['text']} (confidence {float(d.get('confidence', 0.0)):.2f})"]
    lines.extend(f"  {_quote_line(by_id, q)}" for q in d.get("quotes", []))
    return lines


def _dispute_note(card: PaperCard, d: dict, by_id: dict[str, PaperCard]) -> list[str]:
    """`- vs other: verdict`, the claim, the ruling, then each verified turn quote with its loc."""
    other = d["b"] if d["a"] == card.id else d["a"]
    lines = [
        f"- vs {other}: {d.get('verdict', '')}",
        f"  - claim: {' '.join(str(d.get('claim', '')).split())}",
        f"  - reason: {' '.join(str(d.get('judge_reason', '')).split())}",
    ]
    seen: set[str] = set()
    for t in d.get("turns", []):
        for q in t.get("quotes", []):
            line = _quote_line(by_id, q)
            if line not in seen:
                seen.add(line)
                lines.append(f"  {line}")
    return lines


def _note(card: PaperCard, directions: list[dict], disputes: list[dict], by_id: dict[str, PaperCard]) -> str:
    """One markdown note for a card, with the quotes and locs that back each item."""
    lines = [f"# {card.citekey}", "", card.title, "", "## Directions", ""]
    mine = [d for d in directions if card.id in d.get("papers", [])]
    for d in mine:
        lines.extend(_direction_note(d, by_id))
    if not mine:
        lines.append("(none)")
    lines.extend(["", "## Disputes", ""])
    named = [d for d in disputes if card.id in (d["a"], d["b"])]
    for d in named:
        lines.extend(_dispute_note(card, d, by_id))
    if not named:
        lines.append("(none)")
    lines.append("")
    return "\n".join(lines)


def zotero_notes(archive: Archive, cards: list[PaperCard]) -> dict[str, str]:
    """One markdown note per card id: its directions and disputes with their quotes and locs; empty sections when unnamed."""
    by_id = {c.id: c for c in cards}
    events = archive.read()
    directions = _directions(events)
    disputes = _disputes(events)
    return {c.id: _note(c, directions, disputes, by_id) for c in cards}
