"""Command-line entry point `jc`: ingest, run, backtest, minutes (DESIGN.md §10.2)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer

from journal_club.archive import Archive, ArchiveLocked
from journal_club.llm import LLMError

log = logging.getLogger(__name__)

app = typer.Typer(name="jc", help="Library Journal Club.", no_args_is_help=True)

EXIT_ERROR = 1
FAILURES = (LLMError, ArchiveLocked, ValueError, OSError)

CardsDir = Annotated[Path, typer.Argument(help="Directory of PaperCard *.json files.", show_default=False)]
Out = Annotated[Path, typer.Option("--out", help="Run directory for events.jsonl, minutes.md, report.md.", show_default=False)]
Agenda = Annotated[str, typer.Option("--agenda", help="What the club should look for tonight.", show_default=False)]
Resume = Annotated[
    bool,
    typer.Option("--resume", help="Accepted for compatibility: an existing run directory is always resumed."),
]


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="DEBUG logging instead of INFO.")] = False,
) -> None:
    """Library Journal Club: ingest papers, run a night, backtest, write minutes."""
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")


# ---------------------------------------------------------------- helpers


def _open_archive(run_dir: Path, resume: bool = True) -> Archive:
    """Archive at RUN_DIR/events.jsonl; an existing file is resumed (finished steps make no LLM calls)."""
    path = run_dir / "events.jsonl"
    if path.exists():
        log.info("resuming existing archive %s%s", path, "" if resume else " (--resume is implied)")
    return Archive(path)


def _failures() -> tuple[type[BaseException], ...]:
    """FAILURES plus the lazily imported ones: ResumeMismatch and every SDK error (rate limit, auth, network)."""
    import anthropic

    from journal_club.night import ResumeMismatch

    return (*FAILURES, ResumeMismatch, anthropic.AnthropicError)


def _guarded(fn: Callable[[], None]) -> None:
    """Run fn; known failures are logged as one line and exit 1 (the run stays resumable)."""
    try:
        fn()
    except _failures() as exc:
        log.error("%s: %s", type(exc).__name__, exc)
        raise typer.Exit(EXIT_ERROR) from exc


# --------------------------------------------------------------- commands


@app.command()
def ingest(
    pdf_dir: Annotated[Path, typer.Argument(help="Directory of PDFs.", show_default=False)],
    cards_dir: CardsDir,
) -> None:
    """Turn every PDF in PDF_DIR into a PaperCard JSON in CARDS_DIR."""
    from pydantic import ValidationError
    import pymupdf

    from journal_club.cards import ingest_pdf, save_card
    from journal_club.llm import get_llm

    def go() -> None:
        pdfs = sorted(pdf_dir.glob("*.pdf"))
        if not pdfs:
            raise ValueError(f"no *.pdf in {pdf_dir}")
        llm = get_llm()
        failed: list[str] = []
        for pdf in pdfs:
            try:
                out = save_card(ingest_pdf(pdf, llm), cards_dir)
            except (*FAILURES, ValidationError, pymupdf.FileDataError, RuntimeError) as exc:
                log.error("ingest: %s skipped: %s: %s", pdf.name, type(exc).__name__, exc)
                failed.append(pdf.name)
                continue
            typer.echo(f"{pdf.name} -> {out}")
        typer.echo(f"{len(pdfs) - len(failed)} of {len(pdfs)} PDF(s) ingested")
        if failed:
            typer.echo(f"failed: {', '.join(failed)}", err=True)
            raise typer.Exit(EXIT_ERROR)

    _guarded(go)


@app.command(name="cards-from-summaries")
def cards_from_summaries(
    summary_dir: Annotated[Path, typer.Argument(help="Directory of executive-summary *.md files.", show_default=False)],
    cards_dir: CardsDir,
) -> None:
    """Parse templated summaries into PaperCard JSON files; no LLM call."""
    from journal_club.summaries import write_cards_from_summaries

    def go() -> None:
        paths = write_cards_from_summaries(summary_dir, cards_dir)
        typer.echo(f"{len(paths)} cards -> {cards_dir}")

    _guarded(go)


@app.command()
def run(cards_dir: CardsDir, out: Out, agenda: Agenda, resume: Resume = False) -> None:
    """Run one night (map -> debate -> directions) on CARDS_DIR and write minutes.md."""
    from journal_club.cards import load_cards
    from journal_club.llm import get_llm
    from journal_club.minutes import write_minutes
    from journal_club.night import run_night

    def go() -> None:
        cards = load_cards(cards_dir)
        with _open_archive(out, resume) as archive:
            result = run_night(cards, get_llm(), archive, agenda)
            write_minutes(archive, cards, out / "minutes.md")
        typer.echo(
            f"{len(result.map.pairs)} pairs, {len(result.disputes)} disputes, "
            f"{len(result.directions)} directions -> {out / 'minutes.md'}"
        )

    _guarded(go)


@app.command()
def backtest(
    cards_dir: CardsDir,
    t: Annotated[str, typer.Option("--t", help="Split date YYYY-MM-DD; papers dated >= T are held out.", show_default=False)],
    out: Out,
    agenda: Agenda,
    resume: Resume = False,
) -> None:
    """Split CARDS_DIR at T, run club and baseline on before-T, judge on after-T, write report.md."""
    from journal_club.backtest import run_backtest
    from journal_club.cards import load_cards
    from journal_club.llm import get_llm
    from journal_club.minutes import write_minutes

    def go() -> None:
        cards = load_cards(cards_dir)
        with _open_archive(out, resume) as archive:
            report = run_backtest(cards, t, get_llm(), archive, agenda)
            write_minutes(archive, cards, out / "minutes.md")
        typer.echo(
            f"club {report.club_rate:.2f} ({len(report.club_hits)} judged) vs baseline "
            f"{report.baseline_rate:.2f} ({len(report.baseline_hits)} judged) -> {out / 'report.md'}"
        )

    _guarded(go)


@app.command()
def minutes(run_dir: Annotated[Path, typer.Argument(help="An existing run directory.", show_default=False)]) -> None:
    """Rewrite RUN_DIR/minutes.md from its archive; cards come from the run_started snapshot."""
    from journal_club.minutes import cards_from_archive, write_minutes

    def go() -> None:
        path = run_dir / "events.jsonl"
        if not path.exists():
            raise ValueError(f"no archive at {path}")
        with Archive(path) as archive:
            cards = cards_from_archive(archive)
            write_minutes(archive, cards, run_dir / "minutes.md")
        typer.echo(f"minutes -> {run_dir / 'minutes.md'}")

    _guarded(go)
