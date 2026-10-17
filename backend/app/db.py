"""SQLite storage: one row per paper (the record as JSON, plus the PDF when we have it) and cached page summaries.
For you adds arXiv papers, your signals on them (up, down, click, mine) and cached pitches."""

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .schemas import ArxivPaper, GraphicalAbstract, PageSummary, Paper, Pitch

DB_PATH = os.environ.get("PAPERS_DB", Path(__file__).parent.parent / "papers.db")  # override for tests/demos

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
lock = threading.Lock()  # FastAPI runs endpoints in threads; serialise access to the shared connection
conn.execute("CREATE TABLE IF NOT EXISTS papers (id INTEGER PRIMARY KEY, url TEXT, title TEXT, doi TEXT, data TEXT, pdf BLOB)")
if "pdf" not in [col[1] for col in conn.execute("PRAGMA table_info(papers)")]:  # databases from before PDFs were kept
    conn.execute("ALTER TABLE papers ADD COLUMN pdf BLOB")
conn.execute("CREATE TABLE IF NOT EXISTS summaries (paper_id INTEGER, page INTEGER, data TEXT, PRIMARY KEY (paper_id, page))")
conn.execute("CREATE TABLE IF NOT EXISTS abstracts (paper_id INTEGER PRIMARY KEY, data TEXT)")
conn.execute("CREATE TABLE IF NOT EXISTS paper_pins (paper_id INTEGER PRIMARY KEY, data TEXT)")  # an agent review's methods pins
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
        conn.execute("DELETE FROM paper_pins WHERE paper_id = ?", (paper_id,))
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


def get_paper_pins(paper_id: int) -> "PaperPins | None":
    """An agent review's methods pins for a library paper (app/pins.py)."""
    from .schemas import PaperPins

    with lock:
        row = conn.execute("SELECT data FROM paper_pins WHERE paper_id = ?", (paper_id,)).fetchone()
    return PaperPins.model_validate_json(row[0]) if row else None


def has_paper_pins(paper_id: int) -> bool:
    with lock:
        return conn.execute("SELECT 1 FROM paper_pins WHERE paper_id = ?", (paper_id,)).fetchone() is not None


def save_paper_pins(paper_id: int, pins: "PaperPins") -> None:
    with lock, conn:
        conn.execute("INSERT OR REPLACE INTO paper_pins VALUES (?, ?)", (paper_id, pins.model_dump_json()))


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
