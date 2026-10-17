"""SQLite storage: one row per paper, the full record kept as JSON."""

import sqlite3
from pathlib import Path

from .schemas import Paper

DB_PATH = Path(__file__).parent.parent / "papers.db"

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.execute("CREATE TABLE IF NOT EXISTS papers (id INTEGER PRIMARY KEY, url TEXT, title TEXT, doi TEXT, data TEXT)")


def save(paper: Paper) -> int:
    cur = conn.execute(
        "INSERT INTO papers (url, title, doi, data) VALUES (?, ?, ?, ?)",
        (paper.url, paper.title, paper.doi, paper.model_dump_json()),
    )
    conn.commit()
    return cur.lastrowid


def get(paper_id: int) -> Paper | None:
    row = conn.execute("SELECT data FROM papers WHERE id = ?", (paper_id,)).fetchone()
    return Paper.model_validate_json(row[0]) if row else None
