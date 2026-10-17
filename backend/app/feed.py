"""For you: each day's new papers in your arXiv categories and bioRxiv subjects, ranked for you, with a daily goal and a
streak.

Papers come straight from the arXiv API (app/arxiv.py) and the bioRxiv API (app/biorxiv.py), at most once an hour; you
pick what to follow in the tab's Sources panel. The ranking is app/ranker.py. It learns
from your own papers ("Your papers" in the tab: arXiv ids, or an INSPIRE profile, app/profiles.py, re-checked
daily), your Zotero library (a linked BibTeX export, app/zotero.py), More like this / Not for me, the papers you
open, and every library paper that's on arXiv or bioRxiv.
FEED_CATEGORIES in backend/.env sets the arXiv categories followed until you pick some (default astro-ph.CO).
"""

import json
import logging
import os
import re
import threading
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from . import arxiv, biorxiv, db, profiles, ranker, zotero
from .schemas import ArxivPaper

log = logging.getLogger(__name__)

DEFAULT_CATEGORIES = os.environ.get("FEED_CATEGORIES", "astro-ph.CO").split()
FETCHERS = {"arxiv": arxiv, "biorxiv": biorxiv}  # source -> its module, with recent(categories, days)
NAMES = {"arxiv": "arXiv", "biorxiv": "bioRxiv"}
REFRESH_EVERY = timedelta(hours=1)
PROFILE_SYNC_EVERY = timedelta(days=1)  # how often linked profiles are checked for new papers
# Days of papers to fetch the first time, then on each refresh. The first fetch also gives the ranking its "not liked"
# examples, which have to outnumber a big linked library, so it reaches back a month.
FIRST_DAYS, DAYS = 30, 3
DAILY_GOAL = 5  # papers to sort from a listing day for it to count toward the streak; all of them, if fewer
PROFILE_PAPERS = 12  # of your own and of your liked papers, as context for the summaries

ARXIV_ID = arxiv.ID
ARXIV_URL = re.compile(rf"arxiv\.org/(?:abs|pdf|html)/({ARXIV_ID})(?:v\d+)?", re.I)
ARXIV_CLAIM = re.compile(rf"^(?:arxiv:)?\s*({ARXIV_ID})(?:v\d+)?$", re.I)
# bioRxiv DOIs: 10.1101/2026.10.07.757433 (and 10.64898/... since late 2025), or 10.1101/123456 before 2020
BIORXIV_URL = re.compile(r"biorxiv\.org/content/(10\.\d{4,9}/(?:\d{4}\.\d{2}\.\d{2}\.)?\d+)", re.I)

refresh_lock = threading.Lock()
sync_lock = threading.Lock()
corpus: ranker.Corpus | None = None  # rebuilt whenever the number of stored papers changes


class FeedError(Exception):
    """Why the feed is unavailable: `reason` is unreachable (arXiv), profile (couldn't read it) or bad_request."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def arxiv_id(url: str, claimed: str | None = None) -> str | None:
    """A paper's arXiv id, from its URL or else the id read from the paper (e.g. "arXiv:2410.01234v2")."""
    if m := ARXIV_URL.search(url):
        return m.group(1)
    if claimed and (m := ARXIV_CLAIM.match(claimed.strip())):
        return m.group(1)
    return None


def biorxiv_doi(url: str) -> str | None:
    """A bioRxiv preprint's DOI, from its URL (any version, abstract or PDF)."""
    return m.group(1) if (m := BIORXIV_URL.search(url)) else None


def ids_in(text: str) -> list[str]:
    """Every arXiv id in pasted text: bare ids or links, any version."""
    return list(dict.fromkeys(re.findall(rf"(?<![\w.])({ARXIV_ID})(?:v\d+)?", text)))


# --- reading ---


def daily(day: date | None = None) -> dict:
    """One listing day's papers (default: the latest), best first, as the For you tab shows them."""
    notice = refresh()
    if due_profiles() and not sync_lock.locked():
        threading.Thread(target=sync_profiles, daemon=True).start()  # new papers show up on the next load
    zotero_link = sync_zotero()
    s = State.load()
    try:
        if s.fetch_missing(s.library.keys() | set(s.kinds["mine"]) | set(s.kinds["zotero"])):
            s = State.load()
    except httpx.HTTPError as e:  # they'll be fetched next time; rank with what we have
        log.info("couldn't fetch library papers from arXiv: %r", e)
    days = sorted({p.listing_date for p in s.listed}, reverse=True)
    day = day or (days[0] if days else None)
    listing = [p for p in s.listed if p.listing_date == day]

    model = s.model(day)
    if model:
        scores = model.score(listing)
        order = sorted(range(len(listing)), key=lambda i: -scores[i])
        ranked = [(listing[i], float(scores[i])) for i in order]
        reasons = model.reasons([p for p, _ in ranked])
    else:
        ranked = [(p, None) for p in sorted(listing, key=lambda p: p.published, reverse=True)]
        reasons = [None] * len(ranked)
    return {
        "day": day.isoformat() if day else None,
        "older": next((d.isoformat() for d in days if day and d < day), None),
        "newer": next((d.isoformat() for d in reversed(days) if day and d > day), None),
        "sources": s.sources,
        "method": "model" if model else "newest",
        "notice": notice,
        "learning": s.learning(),
        "progress": s.progress(day),
        "mine": [{"id": p.id, "title": p.title} for p in s.papers_for(s.kinds["mine"])],
        "profiles": [{"url": p["url"], "label": profiles.label(p)} for p in linked()],
        "zotero": zotero_link,
        "papers": [
            paper_json(p, rank=i, score=score, reasons=why, feedback=s.thumb(p.id), library_id=s.library.get(p.id))
            for i, ((p, score), why) in enumerate(zip(ranked, reasons), start=1)
        ],
    }


def profile() -> dict:
    """Your own and recently liked papers, the context for each summary's "why you'd care"."""
    s = State.load()
    mine = s.papers_for(s.kinds["mine"])[:PROFILE_PAPERS]
    liked = [p for p in s.papers_for(s.kinds["up"]) if p.id not in s.kinds["mine"]][:PROFILE_PAPERS]
    reading = sorted(s.papers_for(s.kinds["zotero"]), key=lambda p: p.published, reverse=True)[:PROFILE_PAPERS]
    brief = lambda p: {"id": p.id, "title": p.title, "abstract": p.abstract}  # noqa: E731
    return {
        "sources": s.sources,
        "mine": [brief(p) for p in mine],
        "liked": [brief(p) for p in liked],
        "zotero": [brief(p) for p in reading],
    }


# --- what to follow ---


def sources() -> dict[str, list[str]]:
    """{"arxiv": categories, "biorxiv": subjects}, as picked in the Sources panel; until then FEED_CATEGORIES."""
    return json.loads(db.get_meta("sources") or "null") or {"arxiv": DEFAULT_CATEGORIES, "biorxiv": []}


def set_sources(categories: list[str], subjects: list[str]) -> dict[str, list[str]]:
    """Follow these arXiv categories and bioRxiv subjects. The next refresh fetches FIRST_DAYS of any new ones."""
    chosen = {"arxiv": list(dict.fromkeys(categories)), "biorxiv": list(dict.fromkeys(subjects))}
    unknown = [c for c in chosen["arxiv"] if c not in arxiv.CATEGORIES] + [s for s in chosen["biorxiv"] if s not in biorxiv.SUBJECTS]
    if unknown:
        raise FeedError("bad_request", f"For you doesn't know {', '.join(unknown)}.")
    if not any(chosen.values()):
        raise FeedError("bad_request", "Pick at least one arXiv category or bioRxiv subject.")
    db.set_meta("sources", json.dumps(chosen))
    return chosen


def source_options() -> dict:
    """Everything the Sources panel offers, grouped as it shows them, and what you follow now."""
    return {
        "arxiv": [{"group": g, "categories": [{"code": c, "name": n} for c, n in cats.items()]} for g, cats in arxiv.CATEGORY_GROUPS.items()],
        "biorxiv": biorxiv.SUBJECTS,
        "selected": sources(),
    }


# --- writing ---


def feedback(paper_id: str, kind: str) -> dict:
    """kind: up or down (sets that state), none (clears it), or click (you opened the paper)."""
    if kind == "click":
        db.set_signal(paper_id, "click")
    else:
        for thumb in ("up", "down"):
            if thumb != kind:
                db.clear_signal(paper_id, thumb)
        if kind in ("up", "down"):
            db.set_signal(paper_id, kind)
    s = State.load()
    paper = s.stored.get(paper_id)
    return {
        "paper": paper_id,
        "feedback": s.thumb(paper_id),
        "learning": s.learning(),
        "progress": s.progress(paper[0].listing_date if paper else None),
    }


def add_mine(text: str) -> dict:
    """Add your own papers: arXiv ids or links, or an INSPIRE profile link, which is then re-checked daily for new
    papers. Returns which were found."""
    ids = ids_in(text)
    profile = profiles.find(text)
    from_profile, off_arxiv = [], 0
    if profile:
        try:
            from_profile, off_arxiv = profiles.papers(profile)
        except profiles.ProfileError as e:
            raise FeedError("profile", str(e))
        link(profile)
    if not ids and not from_profile:
        raise FeedError(
            "bad_request",
            f"None of the papers on your {profiles.label(profile)} profile are on arXiv."
            if profile
            else "Nothing to add. Paste your INSPIRE profile link, or arXiv ids or links.",
        )
    removed = set(json.loads(db.get_meta("mine_removed") or "[]"))
    db.set_meta("mine_removed", json.dumps(sorted(removed - set(ids))))  # pasting an id again brings it back
    found, unknown = store_mine(ids + [i for i in from_profile if i not in removed])
    return {
        "added": found,
        "unknown": [i for i in unknown if i in ids],
        "profile": profiles.label(profile) if profile else None,
        "from_profile": len(from_profile),
        "off_arxiv": off_arxiv,
    }


def store_mine(ids: list[str]) -> tuple[list[str], list[str]]:
    """Mark these papers as yours, fetching any we don't have. Returns (found, not on arXiv)."""
    ids = list(dict.fromkeys(ids))
    try:
        State.load().fetch_missing(ids)
    except httpx.HTTPError as e:
        raise FeedError("unreachable", f"Couldn't reach arXiv to look those up ({type(e).__name__}). Try again in a moment.")
    s = State.load()
    found = [i for i in ids if i in s.stored]
    for i in found:
        db.set_signal(i, "mine")
    return found, [i for i in ids if i not in s.stored]


def remove_mine(paper_id: str) -> None:
    """Remove one of your papers; a linked profile won't add it back."""
    db.clear_signal(paper_id, "mine")
    removed = set(json.loads(db.get_meta("mine_removed") or "[]")) | {paper_id}
    db.set_meta("mine_removed", json.dumps(sorted(removed)))


# --- a linked Zotero export ---


def link_zotero(path: str) -> dict:
    """Read your Zotero BibTeX export now and whenever it changes; its arXiv papers count as ones you're interested in."""
    file = Path(path.strip().strip("'\"")).expanduser()
    if file.suffix.lower() != ".bib" or not file.is_file():
        raise FeedError("bad_request", f"No .bib file at {file}. In Zotero: File > Export Library..., format BibTeX.")
    db.set_meta("zotero", json.dumps({"path": str(file)}))
    link = sync_zotero()
    try:
        State.load().fetch_missing(db_ids("zotero"))  # so the ranking can read them straight away
    except httpx.HTTPError as e:
        log.info("couldn't fetch Zotero papers from arXiv yet: %r", e)  # the next page load tries again
    return link


def unlink_zotero() -> None:
    db.set_meta("zotero", "")
    db.replace_signals("zotero", [])


def sync_zotero() -> dict | None:
    """Re-read the linked export if it changed. Returns {path, entries, on_arxiv, missing?}, or None if none is linked."""
    link = json.loads(db.get_meta("zotero") or "null")
    if not link:
        return None
    file = Path(link["path"])
    try:
        mtime = file.stat().st_mtime
        if mtime != link.get("mtime"):
            ids, entries = zotero.read(file)
            db.replace_signals("zotero", ids)
            link = {"path": link["path"], "mtime": mtime, "entries": entries, "on_arxiv": len(ids)}
            db.set_meta("zotero", json.dumps(link))
    except (OSError, ValueError) as e:
        return {**link, "missing": str(e)}  # keep the papers read last time
    return link


def db_ids(kind: str) -> list[str]:
    return [i for i, k in db.signals() if k == kind]


# --- linked profiles ---


def linked() -> list[dict]:
    """Profiles you've added papers from: {kind, id, url, synced_at}."""
    return json.loads(db.get_meta("profiles") or "[]")


def link(profile: dict) -> None:
    others = [p for p in linked() if p["url"] != profile["url"]]
    db.set_meta("profiles", json.dumps(others + [{**profile, "synced_at": datetime.now(timezone.utc).isoformat()}]))


def unlink(url: str) -> None:
    """Stop checking a profile for new papers; the papers already added stay."""
    db.set_meta("profiles", json.dumps([p for p in linked() if p["url"] != url]))


def due_profiles() -> list[dict]:
    now = datetime.now(timezone.utc)
    return [p for p in linked() if now - datetime.fromisoformat(p["synced_at"]) >= PROFILE_SYNC_EVERY]


def sync_profiles() -> None:
    """Add new papers from linked profiles (not ones you removed). Failures wait for the next day's try."""
    with sync_lock:
        for profile in due_profiles():
            link(profile)  # mark it checked first, so a profile that fails isn't retried on every page load
            try:
                ids, _ = profiles.papers(profile)
                removed = set(json.loads(db.get_meta("mine_removed") or "[]"))
                store_mine([i for i in ids if i not in removed])
            except (profiles.ProfileError, FeedError) as e:
                log.warning("couldn't check %s for new papers: %s", profile["url"], e)


def refresh() -> str | None:
    """Fetch each source's new papers if its last fetch is over an hour old, and FIRST_DAYS of any category you've
    just started following.

    Returns a notice when a source can't be reached but papers fetched earlier can still be shown.
    """
    notices = []
    with refresh_lock:
        for source, wanted in sources().items():
            if not wanted:
                continue
            try:
                refresh_source(source, wanted)
            except (httpx.HTTPError, ValueError) as e:  # ValueError: a reply that isn't what the API promises
                log.warning("%s fetch failed: %r", source, e)
                if not db.arxiv_count():
                    raise FeedError("unreachable", f"Couldn't reach {NAMES[source]} ({type(e).__name__}). Check your connection and try again.")
                notices.append(f"Couldn't reach {NAMES[source]} ({type(e).__name__}), so these are its papers fetched earlier.")
    return " ".join(notices) or None


def refresh_source(source: str, wanted: list[str]) -> None:
    key = f"fetched:{source}"
    # at: the last hourly fetch; have: the categories fetched FIRST_DAYS back (none if FIRST_DAYS has grown since).
    last = json.loads(db.get_meta(key) or "{}")
    have = set(last.get("have", [])) if last.get("days") == FIRST_DAYS else set()
    new, old = [c for c in wanted if c not in have], [c for c in wanted if c in have]
    now = datetime.now(timezone.utc)
    due = bool(old) and now - datetime.fromisoformat(last["at"]) >= REFRESH_EVERY
    if new:
        db.save_arxiv(FETCHERS[source].recent(new, FIRST_DAYS), listed=True)
    if due:
        db.save_arxiv(FETCHERS[source].recent(old, DAYS), listed=True)
    if new or due:
        at = now.isoformat() if due or not old else last["at"]
        db.set_meta(key, json.dumps({"at": at, "have": wanted, "days": FIRST_DAYS}))


# --- one request's view of the data ---


class State:
    """Stored papers, your signals and the library, loaded once per request."""

    def __init__(
        self,
        stored: dict[str, tuple[ArxivPaper, bool]],
        signals: list[tuple[str, str]],
        library: dict[str, int],
        follows: dict[str, list[str]],
    ):
        self.stored = stored
        self.kinds = {k: [i for i, kind in signals if kind == k] for k in ("up", "down", "click", "mine", "zotero")}  # newest first
        self.library = library  # arXiv id or bioRxiv DOI -> library paper id
        self.sources = follows
        # Papers in a day's feed: from a daily listing, in a category you follow on that source.
        wanted = {source: set(cats) for source, cats in follows.items()}
        self.listed = [p for p, listed in stored.values() if listed and wanted.get(p.source, set()) & set(p.categories)]

    @classmethod
    def load(cls) -> "State":
        library = {}
        for pid, url, claimed in db.sources():
            if key := arxiv_id(url, claimed) or biorxiv_doi(url):
                library.setdefault(key, pid)
        return cls({p.id: (p, listed) for p, listed in db.all_arxiv()}, db.signals(), library, sources())

    def papers_for(self, ids: list[str]) -> list[ArxivPaper]:
        return [self.stored[i][0] for i in ids if i in self.stored]

    def thumb(self, paper_id: str) -> str | None:
        return next((k for k in ("up", "down") if paper_id in self.kinds[k]), None)

    def positives(self) -> set[str]:
        liked = {*self.kinds["up"], *self.kinds["click"], *self.kinds["mine"], *self.kinds["zotero"], *self.library}
        return liked - set(self.kinds["down"])

    def model(self, day: date | None) -> ranker.Model | None:
        """Your model for ranking `day`. Its random "not liked" examples come from other days only: a paper being
        ranked must not also be a training example, or the model just learns it back."""
        global corpus
        everything = [p for p, _ in self.stored.values()]
        if not everything:
            return None
        if corpus is None or corpus.n != len(everything):
            corpus = ranker.Corpus(everything)
        positives = self.papers_for(sorted(self.positives()))
        negatives = self.papers_for(self.kinds["down"])
        return ranker.train(corpus, [p for p in self.listed if p.listing_date != day], positives, negatives)

    def learning(self) -> dict:
        """How close you are to a personal ranking."""
        return {"positives": len(self.positives()), "needed": ranker.MIN_POSITIVES}

    def progress(self, day: date | None) -> dict:
        """The daily goal on `day`, and your streak: consecutive listing days on which you sorted DAILY_GOAL papers
        (up or down), counting back from the latest. The latest day can still be open without breaking it."""
        sizes = Counter(p.listing_date for p in self.listed)
        listed = {p.id: p for p in self.listed}
        done = Counter(listed[i].listing_date for i in {*self.kinds["up"], *self.kinds["down"]} if i in listed)
        streak = 0
        for i, d in enumerate(sorted(sizes, reverse=True)):
            if done[d] >= min(DAILY_GOAL, sizes[d]):
                streak += 1
            elif i:
                break
        return {"goal": min(DAILY_GOAL, sizes.get(day, 0)), "sorted": done.get(day, 0), "streak": streak}

    def fetch_missing(self, ids) -> int:
        """Store any of these papers we don't have yet (older papers of yours, library papers), fetched by id.
        Returns how many were stored; ids arXiv doesn't know are remembered and not asked for again. bioRxiv papers
        only come from the daily fetch, so their DOIs are skipped."""
        unknown = set((db.get_meta("not_on_arxiv") or "").split())
        missing = sorted(i for i in ids if i not in self.stored and i not in unknown and re.fullmatch(ARXIV_ID, i))
        if not missing:
            return 0
        papers = arxiv.by_ids(missing)
        db.save_arxiv(papers, listed=False)
        if gone := set(missing) - {p.id for p in papers}:
            db.set_meta("not_on_arxiv", " ".join(sorted(unknown | gone)))
        return len(papers)


def paper_json(p: ArxivPaper, *, rank: int, score: float | None, reasons: dict | None, feedback: str | None, library_id: int | None) -> dict:
    return {
        **p.model_dump(mode="json"),
        "rank": rank,
        "abs_url": p.abs_url,
        "pdf_url": p.pdf_url,
        "score": score,
        "reasons": reasons,
        "feedback": feedback,
        "library_id": library_id,
    }
