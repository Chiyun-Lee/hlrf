"""Map round: one LLM call per pair of papers, quotes verified, verdicts archived."""

from __future__ import annotations

import hashlib
import itertools
import logging
import os
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from journal_club import prompts
from journal_club.archive import Archive, Event, Step
from journal_club.cards import PaperCard, Quote
from journal_club.llm import LLM
from journal_club.quotes import verify_quotes

log = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

Relation = Literal["agree", "disagree", "shared_limitation", "unrelated"]
RELATIONS: tuple[str, ...] = ("agree", "disagree", "shared_limitation", "unrelated")
STEP: Step = "map"
KIND = "map"
DOWNGRADE_NOTE = "quote failed verification"


# --------------------------------------------------------------------- models


class PairVerdict(BaseModel):
    """What the two students concluded about one pair of papers."""

    model_config = ConfigDict(extra="forbid")

    a: str
    b: str
    relation: Relation
    quote_a: Quote
    quote_b: Quote
    note: str

    @model_validator(mode="after")
    def _ordered(self) -> PairVerdict:
        """Invariant a < b in string order."""
        if not self.a < self.b:
            raise ValueError(f"pair must satisfy a < b, got {self.a!r}, {self.b!r}")
        return self

    @property
    def key(self) -> tuple[str, str]:
        """The (a, b) pair key."""
        return (self.a, self.b)


class MapResult(BaseModel):
    """All pair verdicts of one map round, in pair order."""

    model_config = ConfigDict(extra="forbid")

    pairs: list[PairVerdict]

    def by_relation(self, r: Relation) -> list[PairVerdict]:
        """Verdicts with one relation, in pair order."""
        return [p for p in self.pairs if p.relation == r]

    def disagreements(self) -> list[PairVerdict]:
        """The `disagree` pairs that feed the debate."""
        return self.by_relation("disagree")

    def shared_limitations(self) -> list[PairVerdict]:
        """The `shared_limitation` pairs that feed the directions."""
        return self.by_relation("shared_limitation")

    def get(self, a: str, b: str) -> PairVerdict | None:
        """Verdict for an unordered pair, or None."""
        key = pair_key(a, b)
        return next((p for p in self.pairs if p.key == key), None)

    @classmethod
    def from_events(cls, archive: Archive) -> MapResult:
        """Rebuild from `pair_verdict` events (last wins per pair), sorted by pair."""
        done = map_from_events(archive)
        return cls(pairs=[done[k] for k in sorted(done)])


# -------------------------------------------------------------------- helpers


def cards_by_id(cards: Iterable[PaperCard]) -> dict[str, PaperCard]:
    """Index cards by id."""
    return {c.id: c for c in cards}


def pair_key(a: str, b: str) -> tuple[str, str]:
    """Sorted (a, b)."""
    return (a, b) if a < b else (b, a)


def card_ids_sha(cards: Iterable[PaperCard]) -> str:
    """sha256 of the sorted, comma-joined card ids."""
    ids = sorted(c.id for c in cards)
    return hashlib.sha256(",".join(ids).encode()).hexdigest()


def card_content_sha(cards: Iterable[PaperCard]) -> str:
    """sha256 of every card's JSON, sorted by id: changes when a card is re-ingested, not only when ids change."""
    dumps = [c.model_dump_json() for c in sorted(cards, key=lambda c: c.id)]
    return hashlib.sha256("\n".join(dumps).encode()).hexdigest()


def all_pairs(cards: Iterable[PaperCard]) -> list[tuple[str, str]]:
    """Every unordered pair of card ids, sorted."""
    return list(itertools.combinations(sorted(c.id for c in cards), 2))


def workers() -> int:
    """Batch size from JC_CONCURRENCY (default 4, at least 1)."""
    try:
        return max(1, int(os.environ.get("JC_CONCURRENCY", "4")))
    except ValueError:
        return 4


def _batches(items: list[T], size: int) -> Iterable[list[T]]:
    """Consecutive slices of `size`."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def run_parallel(
    fn: Callable[[T], R],
    items: list[T],
    workers: int,
    after_batch: Callable[[list[R]], None] | None = None,
) -> list[R]:
    """Run fn over items in batches of `workers`; results in input order.

    `after_batch` receives each batch's results on the calling thread, in input
    order. If an item raises, the successful prefix of its batch is still handed
    to `after_batch` before the exception propagates, so a crash loses at most
    the tail of one batch.
    """
    out: list[R] = []
    for batch in _batches(items, max(1, workers)):
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures: list[Future[R]] = [pool.submit(fn, it) for it in batch]
        results: list[R] = []
        for fut in futures:
            exc = fut.exception()
            if exc is not None:
                if after_batch is not None:
                    after_batch(results)
                raise exc
            results.append(fut.result())
        if after_batch is not None:
            after_batch(results)
        out += results
    return out


def _event(round: int, type: str, papers: list[str], payload: dict) -> Event:
    """A map-step event with seq 0 (assigned by the archive)."""
    return Event(round=round, step=STEP, type=type, papers=papers, payload=payload, seq=0)


def _fallback_quote(pid: str) -> Quote:
    """A quote that fails verification by design."""
    return Quote(paper_id=pid, text="no quote available", loc="none")


def _safe_quote(raw: object, pid: str) -> Quote:
    """Quote from an LLM dict, or a fallback that cannot verify."""
    try:
        return Quote.model_validate(raw)
    except ValidationError as exc:
        log.warning("map: malformed quote for %s replaced by fallback: %s", pid, exc.errors()[:1])
        return _fallback_quote(pid)


def _relation(raw: object) -> Relation:
    """Relation from the LLM dict, `unrelated` if illegal."""
    if raw in RELATIONS:
        return raw  # type: ignore[return-value]
    log.warning("map: illegal relation %r treated as unrelated", raw)
    return "unrelated"


# ---------------------------------------------------------------- the round


def map_from_events(archive: Archive) -> dict[tuple[str, str], PairVerdict]:
    """Verdicts keyed by (a, b) from `pair_verdict` events; last wins."""
    done: dict[tuple[str, str], PairVerdict] = {}
    for e in archive.by_step(STEP):
        if e.type != "pair_verdict":
            continue
        try:
            v = PairVerdict.model_validate(e.payload)
        except ValidationError as exc:
            log.warning("map: skipping malformed pair_verdict seq=%d: %s", e.seq, exc.errors()[:1])
            continue
        done[v.key] = v
    return done


def verdict_from_raw(
    a: str, b: str, raw: dict, by_id: dict[str, PaperCard]
) -> tuple[PairVerdict, list[Quote]]:
    """Build the verdict from an LLM dict; returns (verdict, failed quotes)."""
    qa, qb = _safe_quote(raw.get("quote_a"), a), _safe_quote(raw.get("quote_b"), b)
    _, bad_a = verify_quotes(by_id, [qa], require_paper=a)
    _, bad_b = verify_quotes(by_id, [qb], require_paper=b)
    failed = bad_a + bad_b
    if failed:
        verdict = PairVerdict(a=a, b=b, relation="unrelated", quote_a=qa, quote_b=qb, note=DOWNGRADE_NOTE)
    else:
        verdict = PairVerdict(
            a=a, b=b, relation=_relation(raw.get("relation")), quote_a=qa, quote_b=qb, note=str(raw.get("note", ""))
        )
    return verdict, failed


def run_map(
    cards: list[PaperCard],
    llm: LLM,
    archive: Archive,
    agenda: str = "",
    round: int = 1,
) -> MapResult:
    """One `map` call per missing pair; verify quotes; archive every verdict."""
    by_id = cards_by_id(cards)
    pairs = all_pairs(cards)
    done = map_from_events(archive)
    todo = [p for p in pairs if p not in done]
    archive.append(_event(round, "step_started", [], {"label": None, "reused": len(done)}))
    log.info("map: %d pairs, %d reused, %d to run", len(pairs), len(done), len(todo))
    system = prompts.load_prompt(KIND)
    schema = prompts.SCHEMAS[KIND]

    def work(pair: tuple[str, str]) -> tuple[PairVerdict, list[Quote], dict]:
        """Call the LLM for one pair and verify its quotes."""
        a, b = pair
        raw = llm.complete_json(KIND, system, prompts.build_map(agenda, by_id[a], by_id[b]), schema)
        verdict, failed = verdict_from_raw(a, b, raw, by_id)
        return verdict, failed, raw

    def record(results: list[tuple[PairVerdict, list[Quote], dict]]) -> None:
        """Archive a batch's results in input order on the main thread."""
        for verdict, failed, raw in results:
            papers = [verdict.a, verdict.b]
            if failed:
                log.warning("map: %s vs %s downgraded, quote failed verification", verdict.a, verdict.b)
                payload = {
                    "relation_claimed": str(raw.get("relation", "")),
                    "failed": [q.model_dump() for q in failed],
                    "raw": raw,
                }
                archive.append(_event(round, "quote_rejected", papers, payload))
            archive.append(_event(round, "pair_verdict", papers, verdict.model_dump()))
            done[verdict.key] = verdict

    run_parallel(work, todo, workers(), record)
    archive.append(
        _event(round, "step_done", [], {"count": len(pairs), "card_ids_sha": card_ids_sha(cards), "label": None})
    )
    return MapResult(pairs=[done[p] for p in pairs])
