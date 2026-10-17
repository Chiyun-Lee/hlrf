"""Check that every quote in a summary .md is a verbatim passage of the PDF.

Usage: python check_quotes.py SUMMARY.md PAPER.pdf
Prints one line per quote: OK/FAIL, then a summary line, exit 1 if any FAIL.
Normalisation: lowercase, unify quotes/dashes, de-hyphenate line breaks,
collapse whitespace. A quote must be >= 40 normalised characters.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import pymupdf

MIN_LEN = 40


def normalise(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("−", "-")
    s = re.sub(r"-\s*\n\s*", "", s)  # de-hyphenate line breaks
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9 .,;:()%+\-/'\"=<>]", "", s.lower())
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def pdf_text(path: Path) -> str:
    with pymupdf.open(str(path)) as doc:
        return "\n".join(page.get_text() for page in doc)


def quotes_in(md: str) -> list[tuple[str, str]]:
    """Return (quote, loc) pairs from lines `quote: "..."` followed by `loc: "..."`."""
    out: list[tuple[str, str]] = []
    lines = md.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r'\s*quote:\s*"(.*)"\s*$', line)
        if not m:
            continue
        loc = ""
        if i + 1 < len(lines):
            m2 = re.match(r'\s*loc:\s*"(.*)"\s*$', lines[i + 1])
            if m2:
                loc = m2.group(1)
        out.append((m.group(1), loc))
    return out


def main() -> int:
    md_path, pdf_path = Path(sys.argv[1]), Path(sys.argv[2])
    text = normalise(pdf_text(pdf_path))
    qs = quotes_in(md_path.read_text(encoding="utf-8"))
    fails = 0
    for q, loc in qs:
        nq = normalise(q)
        if len(nq) < MIN_LEN:
            print(f"FAIL (too short, {len(nq)} chars) [{loc}] {q[:80]}")
            fails += 1
        elif nq in text:
            print(f"OK   [{loc}] {q[:80]}")
        else:
            # show the longest prefix that does match, to help fixing
            k = len(nq)
            while k > 0 and nq[:k] not in text:
                k -= 5
            print(f"FAIL (matches first {k}/{len(nq)} chars) [{loc}] {q[:80]}")
            fails += 1
    print(f"SUMMARY quotes={len(qs)} ok={len(qs) - fails} fail={fails} missing_loc={sum(1 for _, l in qs if not l)}")
    return 1 if fails or not qs else 0


if __name__ == "__main__":
    sys.exit(main())
