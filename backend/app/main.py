import base64
import logging
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import abstract as graphical
from . import cards, db, extract, feed, llm, pins, pitch, proof, quiz, summarize, tutor
from .schemas import GraphicalAbstract, Note, PageSummary, Paper, PaperPins, Pitch, Proof, Quiz, SummaryCards

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origin_regex=r"chrome-extension://.*", allow_methods=["*"], allow_headers=["*"])


class SaveRequest(BaseModel):
    """Sent by the extension. html/pdf are captured in the user's browser; without them the backend downloads the URL."""

    url: str
    meta: dict = {}
    html: str | None = None
    pdf: str | None = None  # base64


@app.post("/papers")
def save_paper(req: SaveRequest) -> dict:
    try:
        paper, pdf = extract.extract(req.url, req.meta, req.html, base64.b64decode(req.pdf) if req.pdf else None)
    except Exception as e:
        # Surface the cause in the extension popup rather than a bare 500.
        logging.exception("extraction failed for %s", req.url)
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    return {"id": db.save(paper, pdf), "title": paper.title}


@app.get("/papers")
def list_papers() -> list[dict]:
    """Summaries for the library view; fetch /papers/{id} for the full record."""
    return [
        {
            "id": pid,
            "title": p.title,
            "authors": [a.raw for a in p.authors],
            "year": p.year,
            "venue": p.venue,
            "url": p.url,
            "n_pages": len(p.pages),
        }
        for pid, p in db.list_all()
    ]


@app.get("/papers/{paper_id}")
def get_paper(paper_id: int) -> dict:
    paper = db.get(paper_id)
    if not paper:
        raise HTTPException(404)
    return {
        **paper.model_dump(),
        "has_pdf": db.has_pdf(paper_id),
        "has_abstract": db.get_abstract(paper_id) is not None,
        "has_cards": db.get_cards(paper_id) is not None,
    }


@app.delete("/papers/{paper_id}", status_code=204)
def delete_paper(paper_id: int) -> None:
    if not db.delete(paper_id):
        raise HTTPException(404)


@app.get("/papers/{paper_id}/pdf")
def get_pdf(paper_id: int) -> Response:
    pdf = db.get_pdf(paper_id)
    if not pdf:
        raise HTTPException(404)
    return Response(pdf, media_type="application/pdf")


summary_locks = defaultdict(threading.Lock)  # one generation per page, even if the viewer asks twice


def page_summary(paper_id: int, paper: Paper, page: int) -> PageSummary:
    """Notes for one page (0-indexed), generated on first request and cached."""
    with summary_locks[paper_id, page]:
        if summary := db.get_summary(paper_id, page):
            return summary
        summary = summarize.summarize_page(paper, page, db.get_pdf(paper_id))
        db.save_summary(paper_id, page, summary)
        return summary


def all_summaries(paper_id: int, paper: Paper) -> list[PageSummary]:
    """Notes for every page. A page whose notes can't be written is left empty (and retried next time) rather than
    sinking whatever needs the whole paper."""

    def one(i: int) -> PageSummary:
        try:
            return page_summary(paper_id, paper, i)
        except Exception:
            logging.exception("notes for paper %s page %s failed; leaving it out", paper_id, i)
            return PageSummary(notes=[])

    with ThreadPoolExecutor(8) as pool:
        return list(pool.map(one, range(len(paper.pages))))


def get_paper_or_404(paper_id: int) -> Paper:
    if not (paper := db.get(paper_id)):
        raise HTTPException(404)
    return paper


@contextmanager
def claude_errors(what: str):
    """Turn a failed Claude call into a 500 whose detail the reader shows, and log it."""
    try:
        yield
    except HTTPException:
        raise
    except Exception as e:
        logging.exception("%s failed", what)
        raise HTTPException(500, f"{type(e).__name__}: {e}") from e


@app.get("/papers/{paper_id}/pages/{page}/summary")
def get_summary(paper_id: int, page: int) -> PageSummary:
    paper = get_paper_or_404(paper_id)
    if not 0 <= page < len(paper.pages):
        raise HTTPException(404)
    with claude_errors(f"summary of paper {paper_id} page {page}"):
        return page_summary(paper_id, paper, page)


@app.get("/papers/{paper_id}/pins")
def get_pins(paper_id: int) -> PaperPins | None:
    """Methods pins for the paper's figures and tables (app/pins.py); null when it has none."""
    return pins.for_paper(get_paper_or_404(paper_id))


@app.get("/papers/{paper_id}/abstract")
def get_abstract(paper_id: int) -> GraphicalAbstract:
    if not (abstract := db.get_abstract(paper_id)):
        raise HTTPException(404)
    return abstract


@app.post("/papers/{paper_id}/abstract")
def make_abstract(paper_id: int) -> GraphicalAbstract:
    """(Re)make the graphical abstract from the notes, writing notes for any pages not read yet."""
    paper = get_paper_or_404(paper_id)
    with claude_errors(f"abstract of paper {paper_id}"):
        abstract = graphical.make(paper, all_summaries(paper_id, paper), db.get_pdf(paper_id))
    db.save_abstract(paper_id, abstract)
    return abstract


@app.get("/papers/{paper_id}/cards")
def get_cards(paper_id: int) -> SummaryCards:
    if not (deck := db.get_cards(paper_id)):
        raise HTTPException(404)
    return deck


@app.post("/papers/{paper_id}/cards")
def make_cards(paper_id: int) -> SummaryCards:
    """(Re)make the summary cards from the notes and the paper's text, writing notes for any pages not read yet."""
    paper = get_paper_or_404(paper_id)
    with claude_errors(f"cards for paper {paper_id}"):
        deck = cards.make(paper, all_summaries(paper_id, paper), db.get_pdf(paper_id))
    db.save_cards(paper_id, deck)
    return deck


@app.post("/papers/{paper_id}/quiz")
def make_quiz(paper_id: int) -> Quiz:
    """A fresh quiz each time, from the notes and the graphical abstract."""
    paper = get_paper_or_404(paper_id)
    if not (abstract := db.get_abstract(paper_id)):
        raise HTTPException(409, "Make the graphical abstract first.")
    with claude_errors(f"quiz for paper {paper_id}"):
        return quiz.make(paper, all_summaries(paper_id, paper), abstract)


class ProofRequest(BaseModel):
    proof: str  # the question's note id, "p<page>n<note>"
    question: str
    answer: str
    explanation: str = ""


@app.post("/papers/{paper_id}/proof")
def show_proof(paper_id: int, req: ProofRequest) -> Proof:
    """The original paragraph behind a quiz answer, with the key words picked out, plus its note."""
    paper = get_paper_or_404(paper_id)
    try:
        p, k = summarize.parse_note_id(req.proof)
        note = db.get_summary(paper_id, p).notes[k]
    except (ValueError, IndexError, AttributeError):
        raise HTTPException(404, "No such note")
    with claude_errors(f"proof for paper {paper_id}"):
        return proof.find(paper, p, note, req.question, req.answer, req.explanation)


class AskRequest(BaseModel):
    note: int | None = None  # index of the note over the highlighted passage, if any
    selection: str
    messages: list[dict]  # the chat so far: [{"role": "user"|"assistant", "content": str}], ending with the user


@app.post("/papers/{paper_id}/pages/{page}/ask")
def ask(paper_id: int, page: int, req: AskRequest) -> dict:
    """Answer a question about a highlighted passage. Returns the reply, and the note if the tutor updated it."""
    paper, summary = db.get(paper_id), db.get_summary(paper_id, page)
    if not paper or not 0 <= page < len(paper.pages):
        raise HTTPException(404)
    note = summary.notes[req.note] if summary and req.note is not None and 0 <= req.note < len(summary.notes) else None
    with claude_errors(f"tutor for paper {paper_id} page {page}"):
        reply = tutor.answer(paper, page, note, req.selection, req.messages)
    updated = None
    if note and reply.update_note and (reply.bullets or reply.heading):
        note.bullets = reply.bullets or note.bullets
        note.heading = reply.heading or note.heading
        db.save_summary(paper_id, page, summary)
        updated = note
    return {"reply": reply.reply, "updated_note": updated}


@app.put("/papers/{paper_id}/pages/{page}/notes/{index}")
def put_note(paper_id: int, page: int, index: int, note: Note) -> Note:
    """Replace one note (the reader uses this to undo a tutor's edit)."""
    summary = db.get_summary(paper_id, page)
    if not summary or not 0 <= index < len(summary.notes):
        raise HTTPException(404)
    summary.notes[index] = note
    db.save_summary(paper_id, page, summary)
    return note


# --- For you: each day's arXiv papers ranked for you (app/feed.py) ---


def feed_call(fn, *args):
    """Run a feed request, turning a FeedError into an error the For you tab can explain."""
    try:
        return fn(*args)
    except feed.FeedError as e:
        raise HTTPException(400 if e.reason == "bad_request" else 503, {"reason": e.reason, "message": str(e)})


@app.get("/feed")
def get_feed(day: date | None = None) -> dict:
    """One listing day's papers (default: the latest), best first, each with `library_id` if it's in the library."""
    return feed_call(feed.daily, day)


class FeedbackRequest(BaseModel):
    kind: Literal["up", "down", "none", "click"]


@app.post("/feed/{arxiv_id:path}/feedback")
def post_feedback(arxiv_id: str, req: FeedbackRequest) -> dict:
    return feed_call(feed.feedback, arxiv_id, req.kind)


class MineRequest(BaseModel):
    text: str  # arXiv ids or links, or an INSPIRE profile link


@app.post("/feed/mine")
def add_mine(req: MineRequest) -> dict:
    """Your own papers: what For you ranks by and writes "why you'd care" from."""
    return feed_call(feed.add_mine, req.text)


@app.delete("/feed/mine/{arxiv_id:path}", status_code=204)
def remove_mine(arxiv_id: str) -> None:
    feed.remove_mine(arxiv_id)


@app.delete("/feed/profiles", status_code=204)
def unlink_profile(url: str) -> None:
    """Stop checking a profile for new papers; the papers already added stay."""
    feed.unlink(url)


class ZoteroRequest(BaseModel):
    path: str  # where Zotero's BibTeX export is on this machine, e.g. ~/Zotero/My Library.bib


@app.post("/feed/zotero")
def link_zotero(req: ZoteroRequest) -> dict | None:
    """Your Zotero library, from its BibTeX export: re-read whenever the file changes."""
    return feed_call(feed.link_zotero, req.path)


@app.delete("/feed/zotero", status_code=204)
def unlink_zotero() -> None:
    feed.unlink_zotero()


class SummariesRequest(BaseModel):
    papers: list[dict]  # {id, title, abstract, reasons} as GET /feed returned them


pitch_locks = defaultdict(threading.Lock)  # one generation per paper, even if the tab asks twice


@app.post("/feed/summaries")
def feed_summaries(req: SummariesRequest) -> dict[str, Pitch]:
    """What each paper does and why you'd care, keyed by arXiv id; written in one Claude call on first request, then cached."""
    papers = {p["id"]: p for p in req.papers if p.get("id") and p.get("title") and p.get("abstract")}
    with ExitStack() as stack:
        for arxiv_id in sorted(papers):  # sorted, so overlapping requests can't deadlock
            stack.enter_context(pitch_locks[arxiv_id])
        found = db.get_pitches(list(papers))
        missing = [p for i, p in papers.items() if i not in found]
        if missing:
            if reason := llm.ready():
                raise HTTPException(503, {"reason": "no_key", "message": reason})
            try:
                written = pitch.write(missing, feed.profile())
            except Exception as e:
                logging.exception("summaries failed for %s", [p["id"] for p in missing])
                raise HTTPException(500, f"{type(e).__name__}: {e}")
            for p in written:
                db.save_pitch(p)
                found[p.id] = p
    return found


# The paper browser (../web). Mounted last so the API routes above take precedence.
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent.parent / "web", html=True), name="web")
