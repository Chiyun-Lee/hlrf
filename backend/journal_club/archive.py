"""Append-only JSONL event archive with a file lock."""

from __future__ import annotations

import fcntl
import json
import logging
import os
from pathlib import Path
from typing import IO, Literal

from pydantic import BaseModel, ConfigDict

log = logging.getLogger(__name__)

Step = Literal[
    "map", "debate", "directions", "hypotheses", "critique", "synthesis", "backtest", "baseline", "judge", "minutes"
]


class Event(BaseModel):
    """One archive line; `seq` is assigned by Archive.append (pass 0)."""

    model_config = ConfigDict(extra="forbid")

    round: int
    step: Step
    type: str
    papers: list[str]
    payload: dict
    seq: int


class ArchiveLocked(RuntimeError):
    """Another process holds the archive lock."""


class Archive:
    """Append-only events.jsonl; never rewrites or truncates."""

    def __init__(self, path: str | Path) -> None:
        """Create the parent dir and take a non-blocking lock on <path>.lock."""
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._lock_fh: IO[str] | None = open(self.lock_path, "a")
        try:
            fcntl.flock(self._lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lock_fh.close()
            self._lock_fh = None
            raise ArchiveLocked(f"archive locked: {self.lock_path}") from exc
        self._last_seq = max((e.seq for e in self.read()), default=0)

    @property
    def last_seq(self) -> int:
        """Highest seq stored, 0 when empty."""
        return self._last_seq

    def append(self, event: Event) -> Event:
        """Assign seq, write one JSON line, flush + fsync, return the stored event."""
        if self._lock_fh is None:
            raise RuntimeError("archive is closed")
        stored = event.model_copy(update={"seq": self._last_seq + 1})
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(stored.model_dump_json() + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._last_seq = stored.seq
        log.debug("archive seq=%d step=%s type=%s", stored.seq, stored.step, stored.type)
        return stored

    def read(self) -> list[Event]:
        """Parse every line of the file."""
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as fh:
            return [Event.model_validate_json(line) for line in fh if line.strip()]

    def by_step(self, step: Step) -> list[Event]:
        """Events of one step, in seq order."""
        return [e for e in self.read() if e.step == step]

    def has_step(self, step: Step, label: str | None = None) -> bool:
        """True iff a step_done event exists for the step (and label, if given)."""
        for e in self.by_step(step):
            if e.type == "step_done" and (label is None or e.payload.get("label") == label):
                return True
        return False

    def close(self) -> None:
        """Release the lock."""
        if self._lock_fh is not None:
            fcntl.flock(self._lock_fh.fileno(), fcntl.LOCK_UN)
            self._lock_fh.close()
            self._lock_fh = None

    def __enter__(self) -> Archive:
        """Context manager entry."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Context manager exit releases the lock."""
        self.close()

    def __del__(self) -> None:
        """Best-effort unlock."""
        try:
            self.close()
        except Exception:  # noqa: BLE001
            pass
