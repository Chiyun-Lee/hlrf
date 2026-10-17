"""Shared fixtures: counting LLM wrapper, fixture cards, archive, hand-made PDFs."""

from __future__ import annotations

import collections
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from journal_club.archive import Archive
from journal_club.cards import PaperCard, load_cards
from journal_club.llm import LLM

FIXTURE_CARDS = Path(__file__).parent / "fixtures" / "cards"


class CountingLLM:
    """Wraps any LLM and counts calls per kind."""

    def __init__(self, inner: LLM) -> None:
        """Start with an empty counter."""
        self.inner = inner
        self.calls: collections.Counter[str] = collections.Counter()

    @property
    def total(self) -> int:
        """All calls, every kind."""
        return sum(self.calls.values())

    def complete_json(self, kind: str, system: str, user: str, schema: dict) -> dict:
        """Count then delegate."""
        self.calls[kind] += 1
        return self.inner.complete_json(kind, system, user, schema)


@pytest.fixture
def cards() -> list[PaperCard]:
    """The eight synthetic cards."""
    return load_cards(FIXTURE_CARDS)


@pytest.fixture
def tmp_archive(tmp_path: Path) -> Iterator[Archive]:
    """A fresh archive in a temp dir, closed after the test."""
    archive = Archive(tmp_path / "events.jsonl")
    yield archive
    archive.close()


def _pdf_escape(s: str) -> str:
    """Escape backslashes and parentheses for a PDF string literal."""
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(path: Path, lines: list[str]) -> Path:
    """Write a minimal one-page uncompressed PDF with one text line per entry."""
    ops = ["BT", "/F1 12 Tf", "72 720 Td"]
    for i, line in enumerate(lines):
        if i:
            ops.append("0 -14 Td")
        ops.append(f"({_pdf_escape(line)}) Tj")
    ops.append("ET")
    stream = "\n".join(ops).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


def _live_enabled() -> bool:
    """JC_LIVE=1 and some credential resolves."""
    if os.environ.get("JC_LIVE") != "1":
        return False
    return any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")) or (
        Path.home() / ".config" / "anthropic"
    ).exists()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip `live` tests unless JC_LIVE=1 and credentials resolve."""
    if _live_enabled():
        return
    skip = pytest.mark.skip(reason="live API test: set JC_LIVE=1 with credentials")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
