"""SQLite storage: one row per paper (the record as JSON, plus the PDF when we have it) and cached page summaries."""

import os
import sqlite3
import threading
from pathlib import Path

from pydantic import ValidationError

import json

from .schemas import GraphicalAbstract, LearnerProfile, PageSummary, Paper

DB_PATH = os.environ.get("PAPERS_DB", Path(__file__).parent.parent / "papers.db")  # override for tests/demos

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
lock = threading.Lock()  # FastAPI runs endpoints in threads; serialise access to the shared connection
conn.execute("CREATE TABLE IF NOT EXISTS papers (id INTEGER PRIMARY KEY, url TEXT, title TEXT, doi TEXT, data TEXT, pdf BLOB)")
if "pdf" not in [col[1] for col in conn.execute("PRAGMA table_info(papers)")]:  # databases from before PDFs were kept
    conn.execute("ALTER TABLE papers ADD COLUMN pdf BLOB")
conn.execute("CREATE TABLE IF NOT EXISTS summaries (paper_id INTEGER, page INTEGER, data TEXT, PRIMARY KEY (paper_id, page))")
conn.execute("CREATE TABLE IF NOT EXISTS abstracts (paper_id INTEGER PRIMARY KEY, data TEXT)")
# Learning memory (app/memory.py): what the reader did, and the profile distilled from it. One reader per install.
conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, paper_id INTEGER, kind TEXT, data TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)")
conn.execute("CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT)")


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


def delete(paper_id: int) -> bool:
    with lock, conn:
        cur = conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
        conn.execute("DELETE FROM summaries WHERE paper_id = ?", (paper_id,))
        conn.execute("DELETE FROM abstracts WHERE paper_id = ?", (paper_id,))
    return cur.rowcount > 0


def get_summary(paper_id: int, page: int) -> PageSummary | None:
    with lock:
        row = conn.execute("SELECT data FROM summaries WHERE paper_id = ? AND page = ?", (paper_id, page)).fetchone()
    try:
        return PageSummary.model_validate_json(row[0]) if row else None
    except ValidationError:  # cached in an older format; regenerate
        return None


def save_summary(paper_id: int, page: int, summary: PageSummary) -> None:
    with lock, conn:
        conn.execute("INSERT OR REPLACE INTO summaries VALUES (?, ?, ?)", (paper_id, page, summary.model_dump_json()))


def get_abstract(paper_id: int) -> GraphicalAbstract | None:
    with lock:
        row = conn.execute("SELECT data FROM abstracts WHERE paper_id = ?", (paper_id,)).fetchone()
    return GraphicalAbstract.model_validate_json(row[0]) if row else None


def save_abstract(paper_id: int, abstract: GraphicalAbstract) -> None:
    with lock, conn:
        conn.execute("INSERT OR REPLACE INTO abstracts VALUES (?, ?)", (paper_id, abstract.model_dump_json()))


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
