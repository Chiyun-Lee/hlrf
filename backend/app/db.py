"""SQLite storage: one row per paper (the record as JSON, plus the PDF when we have it) and cached page summaries."""

import os
import sqlite3
import threading
from pathlib import Path

from pydantic import ValidationError

from .schemas import GraphicalAbstract, PageSummary, Paper

DB_PATH = os.environ.get("PAPERS_DB", Path(__file__).parent.parent / "papers.db")  # override for tests/demos

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
lock = threading.Lock()  # FastAPI runs endpoints in threads; serialise access to the shared connection
conn.execute("CREATE TABLE IF NOT EXISTS papers (id INTEGER PRIMARY KEY, url TEXT, title TEXT, doi TEXT, data TEXT, pdf BLOB)")
if "pdf" not in [col[1] for col in conn.execute("PRAGMA table_info(papers)")]:  # databases from before PDFs were kept
    conn.execute("ALTER TABLE papers ADD COLUMN pdf BLOB")
conn.execute("CREATE TABLE IF NOT EXISTS summaries (paper_id INTEGER, page INTEGER, data TEXT, PRIMARY KEY (paper_id, page))")
conn.execute("CREATE TABLE IF NOT EXISTS abstracts (paper_id INTEGER PRIMARY KEY, data TEXT)")


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
