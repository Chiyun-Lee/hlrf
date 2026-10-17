"""Reading levels: every level has an audience, and notes are cached per level (older databases move to outreach)."""

import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import get_args

from app.levels import AUDIENCE, DEFAULT, Level

BACKEND = Path(__file__).parent.parent


def test_every_level_has_an_audience():
    assert set(get_args(Level)) == set(AUDIENCE) and DEFAULT in AUDIENCE


def run_with_db(db: Path, code: str) -> str:
    """Run `code` with app.db pointed at `db` (in a fresh process, as app.db connects on import)."""
    out = subprocess.run(
        [sys.executable, "-c", f"from app import db\n{code}"],
        cwd=BACKEND, env={"PAPERS_DB": str(db), "PATH": ""}, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def test_old_cache_becomes_outreach_and_levels_are_separate(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE summaries (paper_id INTEGER, page INTEGER, data TEXT, PRIMARY KEY (paper_id, page))")
    old.execute("CREATE TABLE abstracts (paper_id INTEGER PRIMARY KEY, data TEXT)")
    old.execute("""INSERT INTO summaries VALUES (1, 0, '{"notes": []}')""")
    old.commit()
    old.close()

    out = run_with_db(path, """
from app.schemas import Note, PageSummary
expert = PageSummary(notes=[Note(kind="summary", blocks=[0], heading="DENSE")])
db.save_summary(1, 0, "expert", expert)
print(db.get_summary(1, 0, "outreach").notes == [], db.get_summary(1, 0, "expert").notes[0].heading,
      db.get_summary(1, 0, "adjacent"), db.abstract_levels(1))
""")
    assert out == "True DENSE None []"
