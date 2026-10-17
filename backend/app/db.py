"""SQLite storage: one row per paper (the record as JSON, plus the PDF when we have it), page summaries, graphical
abstracts and summary cards cached per reading level (app/levels.py), and the learning memory. For you adds arXiv
papers, your signals on them (up, down, click, mine) and cached pitches."""

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

import json

from .schemas import ArxivPaper, GraphicalAbstract, LearnerProfile, PageSummary, Paper, Pitch, SummaryCards

DB_PATH = os.environ.get("PAPERS_DB", Path(__file__).parent.parent / "papers.db")  # override for tests/demos

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
lock = threading.Lock()  # FastAPI runs endpoints in threads; serialise access to the shared connection
conn.execute("CREATE TABLE IF NOT EXISTS papers (id INTEGER PRIMARY KEY, url TEXT, title TEXT, doi TEXT, data TEXT, pdf BLOB)")
if "pdf" not in [col[1] for col in conn.execute("PRAGMA table_info(papers)")]:  # databases from before PDFs were kept
    conn.execute("ALTER TABLE papers ADD COLUMN pdf BLOB")


def leveled_table(name: str, create: str) -> None:
    """Create a table keyed by reading level. Tables from before levels existed are moved over: their notes were
    written for lay readers, so they become the outreach level."""
    columns = [col[1] for col in conn.execute(f"PRAGMA table_info({name})")]
    with conn:
        if columns and "level" not in columns:
            conn.execute(f"ALTER TABLE {name} RENAME TO {name}_old")
            conn.execute(create)
            conn.execute(f"INSERT INTO {name} SELECT *, 'outreach' FROM {name}_old")
            conn.execute(f"DROP TABLE {name}_old")
        conn.execute(create)


leveled_table("summaries", "CREATE TABLE IF NOT EXISTS summaries (paper_id INTEGER, page INTEGER, data TEXT, level TEXT, PRIMARY KEY (paper_id, page, level))")
leveled_table("abstracts", "CREATE TABLE IF NOT EXISTS abstracts (paper_id INTEGER, data TEXT, level TEXT, PRIMARY KEY (paper_id, level))")
# Learning memory (app/memory.py): what the reader did, and the profile distilled from it. One reader per install.
conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, paper_id INTEGER, kind TEXT, data TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)")
conn.execute("CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT)")
leveled_table("cards", "CREATE TABLE IF NOT EXISTS cards (paper_id INTEGER, data TEXT, level TEXT, PRIMARY KEY (paper_id, level))")
conn.execute("CREATE TABLE IF NOT EXISTS pitches (arxiv_id TEXT PRIMARY KEY, data TEXT)")
# listed: came from a daily listing (rather than fetched by id, like your own older papers), so it's in a day's feed
conn.execute("CREATE TABLE IF NOT EXISTS arxiv_papers (id TEXT PRIMARY KEY, listed INTEGER, data TEXT)")
conn.execute("CREATE TABLE IF NOT EXISTS feed_signals (arxiv_id TEXT, kind TEXT, at TEXT, PRIMARY KEY (arxiv_id, kind))")
conn.execute("CREATE TABLE IF NOT EXISTS feed_meta (key TEXT PRIMARY KEY, value TEXT)")


def save(paper: Paper, pdf: bytes | None = None) -> int:
    with lock, conn:
        cur = conn.execute(
            "INSERT INTO papers (url, title, doi, data, pdf) VALUES (?, ?, ?, ?, ?)",
            (paper.url, paper.title, paper.doi, paper.model_dump_json(), pdf),
        )
    return cur.lastrowid


def get(paper_id: int) -> Paper | None:
    with lock:
        row = conn.execute("SELECT data FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return Paper.model_validate_json(row[0]) if row else None


def get_pdf(paper_id: int) -> bytes | None:
    with lock:
        row = conn.execute("SELECT pdf FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return row[0] if row else None


def has_pdf(paper_id: int) -> bool:
    with lock:
        return conn.execute("SELECT pdf IS NOT NULL FROM papers WHERE id = ?", (paper_id,)).fetchone() == (1,)


def list_all() -> list[tuple[int, Paper]]:
    with lock:
        rows = conn.execute("SELECT id, data FROM papers ORDER BY id DESC").fetchall()
    return [(pid, Paper.model_validate_json(data)) for pid, data in rows]


def sources() -> list[tuple[int, str, str | None]]:
    """(id, url, arxiv_id) per saved paper, without loading the full records."""
    with lock:
        return conn.execute("SELECT id, url, json_extract(data, '$.arxiv_id') FROM papers ORDER BY id").fetchall()


def delete(paper_id: int) -> bool:
    with lock, conn:
        cur = conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
        conn.execute("DELETE FROM summaries WHERE paper_id = ?", (paper_id,))
        conn.execute("DELETE FROM abstracts WHERE paper_id = ?", (paper_id,))
        conn.execute("DELETE FROM cards WHERE paper_id = ?", (paper_id,))
    return cur.rowcount > 0


def get_summary(paper_id: int, page: int, level: str) -> PageSummary | None:
    with lock:
        row = conn.execute(
            "SELECT data FROM summaries WHERE paper_id = ? AND page = ? AND level = ?", (paper_id, page, level)
        ).fetchone()
    try:
        return PageSummary.model_validate_json(row[0]) if row else None
    except ValidationError:  # cached in an older format; regenerate
        return None


def save_summary(paper_id: int, page: int, level: str, summary: PageSummary) -> None:
    with lock, conn:
        conn.execute(
            "INSERT OR REPLACE INTO summaries (paper_id, page, data, level) VALUES (?, ?, ?, ?)",
            (paper_id, page, summary.model_dump_json(), level),
        )


def get_abstract(paper_id: int, level: str) -> GraphicalAbstract | None:
    with lock:
        row = conn.execute("SELECT data FROM abstracts WHERE paper_id = ? AND level = ?", (paper_id, level)).fetchone()
    return GraphicalAbstract.model_validate_json(row[0]) if row else None


def abstract_levels(paper_id: int) -> list[str]:
    """The reading levels this paper has a graphical abstract for."""
    with lock:
        return [r[0] for r in conn.execute("SELECT level FROM abstracts WHERE paper_id = ?", (paper_id,))]


def save_abstract(paper_id: int, level: str, abstract: GraphicalAbstract) -> None:
    with lock, conn:
        conn.execute(
            "INSERT OR REPLACE INTO abstracts (paper_id, data, level) VALUES (?, ?, ?)",
            (paper_id, abstract.model_dump_json(), level),
        )


def add_event(paper_id: int | None, kind: str, data: dict) -> None:
    with lock, conn:
        conn.execute("INSERT INTO events (paper_id, kind, data) VALUES (?, ?, ?)", (paper_id, kind, json.dumps(data)))


def events(limit: int = 300) -> list[dict]:
    """Most recent first, with the paper's title (None once the paper is deleted)."""
    with lock:
        rows = conn.execute(
            "SELECT e.id, e.paper_id, p.title, e.kind, e.data, e.created FROM events e LEFT JOIN papers p ON p.id = e.paper_id"
            " ORDER BY e.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"id": i, "paper_id": pid, "paper": t, "kind": k, "data": json.loads(d), "created": c} for i, pid, t, k, d, c in rows]


def get_profile() -> LearnerProfile:
    with lock:
        row = conn.execute("SELECT data FROM profile WHERE id = 1").fetchone()
    return LearnerProfile.model_validate_json(row[0]) if row else LearnerProfile()


def save_profile(profile: LearnerProfile) -> None:
    with lock, conn:
        conn.execute("INSERT OR REPLACE INTO profile VALUES (1, ?)", (profile.model_dump_json(),))


def forget_everything() -> None:
    with lock, conn:
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM profile")


def get_pitches(arxiv_ids: list[str]) -> dict[str, Pitch]:
    with lock:
        rows = conn.execute(
            f"SELECT data FROM pitches WHERE arxiv_id IN ({','.join('?' * len(arxiv_ids))})", arxiv_ids
        ).fetchall()
    pitches = []
    for (data,) in rows:
        try:
            pitches.append(Pitch.model_validate_json(data))
        except ValidationError:  # cached in an older format; regenerate
            pass
    return {p.id: p for p in pitches}


def save_pitch(pitch: Pitch) -> None:
    with lock, conn:
        conn.execute("INSERT OR REPLACE INTO pitches VALUES (?, ?)", (pitch.id, pitch.model_dump_json()))


def save_arxiv(papers: list[ArxivPaper], listed: bool) -> None:
    """Store papers, or update them to their newest version; a paper once listed stays listed."""
    rows = [(p.id, int(listed), p.model_dump_json()) for p in papers]
    with lock, conn:
        conn.executemany(
            "INSERT INTO arxiv_papers VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data, listed = max(listed, excluded.listed)",
            rows,
        )


def arxiv_count() -> int:
    with lock:
        return conn.execute("SELECT count(*) FROM arxiv_papers").fetchone()[0]


def all_arxiv() -> list[tuple[ArxivPaper, bool]]:
    """Every stored arXiv paper, with whether it came from a daily listing."""
    with lock:
        rows = conn.execute("SELECT data, listed FROM arxiv_papers").fetchall()
    return [(ArxivPaper.model_validate_json(data), bool(listed)) for data, listed in rows]


def signals() -> list[tuple[str, str]]:
    """(arxiv_id, kind) for every signal, newest first. kind: up, down, click, mine (your own paper) or zotero."""
    with lock:
        return conn.execute("SELECT arxiv_id, kind FROM feed_signals ORDER BY at DESC").fetchall()


def set_signal(arxiv_id: str, kind: str) -> None:
    with lock, conn:
        conn.execute("INSERT OR IGNORE INTO feed_signals VALUES (?, ?, ?)", (arxiv_id, kind, datetime.now(timezone.utc).isoformat()))


def replace_signals(kind: str, arxiv_ids: list[str]) -> None:
    """Make `arxiv_ids` the whole set of signals of this kind (e.g. what a linked Zotero export contains)."""
    now = datetime.now(timezone.utc).isoformat()
    with lock, conn:
        conn.execute("DELETE FROM feed_signals WHERE kind = ?", (kind,))
        conn.executemany("INSERT INTO feed_signals VALUES (?, ?, ?)", [(i, kind, now) for i in dict.fromkeys(arxiv_ids)])


def clear_signal(arxiv_id: str, kind: str) -> None:
    with lock, conn:
        conn.execute("DELETE FROM feed_signals WHERE arxiv_id = ? AND kind = ?", (arxiv_id, kind))


def get_meta(key: str) -> str | None:
    with lock:
        row = conn.execute("SELECT value FROM feed_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(key: str, value: str) -> None:
    with lock, conn:
        conn.execute("INSERT OR REPLACE INTO feed_meta VALUES (?, ?)", (key, value))


def get_cards(paper_id: int, level: str) -> SummaryCards | None:
    with lock:
        row = conn.execute("SELECT data FROM cards WHERE paper_id = ? AND level = ?", (paper_id, level)).fetchone()
    try:
        return SummaryCards.model_validate_json(row[0]) if row else None
    except ValidationError:  # saved in an older format; remake
        return None


def card_levels(paper_id: int) -> list[str]:
    """The reading levels this paper has summary cards for."""
    with lock:
        return [r[0] for r in conn.execute("SELECT level FROM cards WHERE paper_id = ?", (paper_id,))]


def save_cards(paper_id: int, level: str, cards: SummaryCards) -> None:
    with lock, conn:
        conn.execute(
            "INSERT OR REPLACE INTO cards (paper_id, data, level) VALUES (?, ?, ?)", (paper_id, cards.model_dump_json(), level)
        )
