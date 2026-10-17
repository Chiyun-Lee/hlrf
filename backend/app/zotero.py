"""Your Zotero library as a reading signal for For you. Link the BibTeX file Zotero exports (File > Export Library...,
or Better BibTeX's auto-export, which keeps the file up to date): every entry with an arXiv id counts as a paper
you're interested in. Only the ids are read; the file is re-read whenever it changes."""

import re
from pathlib import Path

from .arxiv import ID

ENTRY = re.compile(r"@(\w+)\s*[{(]")
# Where BibTeX entries keep arXiv ids: eprint = {2207.01501}, arxiv.org/abs/..., the arXiv DOI 10.48550/arXiv.2207.01501,
# or "arXiv:2207.01501" in journal or note fields.
ARXIV_IN_ENTRY = re.compile(rf"(?:\beprint\s*=\s*[{{\"]?\s*|arxiv\.org/(?:abs|pdf)/|10\.48550/arxiv\.|\barxiv:\s*)({ID})", re.I)
MAX_BYTES = 50_000_000


def read(path: Path) -> tuple[list[str], int]:
    """(arXiv ids, number of entries) in a BibTeX file."""
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"{path.name} is over {MAX_BYTES // 1_000_000} MB; that doesn't look like a BibTeX export.")
    text = path.read_text(encoding="utf-8", errors="replace")
    entries = [
        e
        for e in re.split(r"(?m)^\s*(?=@)", text)
        if (m := ENTRY.match(e)) and m.group(1).lower() not in ("comment", "string", "preamble")
    ]
    ids = [m.group(1) for e in entries if (m := ARXIV_IN_ENTRY.search(e))]
    return list(dict.fromkeys(ids)), len(entries)
