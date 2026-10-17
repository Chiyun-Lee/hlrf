"""SQLite storage: one row per paper (the record as JSON, plus the PDF when we have it), cached page summaries, and
For you's cached paper pitches and which library papers arxiv-feed has been told about."""

import os
import sqlite3
import threading
from pathlib import Path

from pydantic import ValidationError

from .schemas import PageSummary, Paper, Pitch

DB_PATH = os.environ.get("PAPERS_DB", Path(__file__).parent.parent / "papers.db")  # override for tests/demos

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
lock = threading.Lock()  # FastAPI runs endpoints in threads; serialise access to the shared connection
conn.execute("CREATE TABLE IF NOT EXISTS papers (id INTEGER PRIMARY KEY, url TEXT, title TEXT, doi TEXT, data TEXT, pdf BLOB)")
if "pdf" not in [col[1] for col in conn.execute("PRAGMA table_info(papers)")]:  # databases from before PDFs were kept
    conn.execute("ALTER TABLE papers ADD COLUMN pdf BLOB")
conn.execute("CREATE TABLE IF NOT EXISTS summaries (paper_id INTEGER, page INTEGER, data TEXT, PRIMARY KEY (paper_id, page))")
conn.execute("CREATE TABLE IF NOT EXISTS pitches (arxiv_id TEXT PRIMARY KEY, data TEXT)")
conn.execute("CREATE TABLE IF NOT EXISTS feed_synced (arxiv_id TEXT PRIMARY KEY)")


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


def synced() -> set[str]:
    """arXiv ids of library papers already marked relevant in arxiv-feed."""
    with lock:
        return {row[0] for row in conn.execute("SELECT arxiv_id FROM feed_synced")}


def mark_synced(arxiv_id: str) -> None:
    with lock, conn:
        conn.execute("INSERT OR IGNORE INTO feed_synced VALUES (?)", (arxiv_id,))
