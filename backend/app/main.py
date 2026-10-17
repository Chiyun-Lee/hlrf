import base64
import logging
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import abstract as graphical
from . import db, extract, memory, proof, quiz, summarize, tutor
from .schemas import GraphicalAbstract, LearnerProfile, Note, PageSummary, Paper, Proof, Quiz

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
    return {**paper.model_dump(), "has_pdf": db.has_pdf(paper_id), "has_abstract": db.get_abstract(paper_id) is not None}


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


@app.post("/papers/{paper_id}/quiz")
def make_quiz(paper_id: int) -> Quiz:
    """A fresh quiz each time, from the notes and the graphical abstract."""
    paper = get_paper_or_404(paper_id)
    if not (abstract := db.get_abstract(paper_id)):
        raise HTTPException(409, "Make the graphical abstract first.")
    with claude_errors(f"quiz for paper {paper_id}"):
        return quiz.make(paper, all_summaries(paper_id, paper), abstract)


class QuizResult(BaseModel):
    right_first_time: int
    total: int
    missed: list[dict] = []  # [{"prompt": ..., "answer": ...}]


@app.post("/papers/{paper_id}/quiz/result", status_code=204)
def quiz_result(paper_id: int, result: QuizResult) -> None:
    """Remember how a quiz went; what was missed feeds the learner profile."""
    paper = get_paper_or_404(paper_id)
    missed = "\n".join(f"- {m.get('prompt')} (answer: {m.get('answer')})" for m in result.missed) or "(none)"
    memory.record(
        paper_id,
        "quiz",
        result.model_dump(),
        f'Quiz on "{paper.title}": {result.right_first_time}/{result.total} right first time. Missed:\n{missed}',
    )


@app.get("/me")
def get_me() -> dict:
    """The My learning page: the learner profile and recent questions and quizzes."""
    return {"profile": db.get_profile(), "events": db.events()}


@app.put("/me/profile")
def put_profile(profile: LearnerProfile) -> LearnerProfile:
    """The reader's own edits to what the app has learned about them."""
    db.save_profile(profile)
    return profile


@app.delete("/me", status_code=204)
def forget_me() -> None:
    db.forget_everything()


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
    chat = "\n".join(f"{'Reader' if m['role'] == 'user' else 'Tutor'}: {m['content']}" for m in req.messages)
    memory.record(
        paper_id,
        "question",
        {"page": page, "selection": req.selection, "question": req.messages[-1]["content"], "answer": reply.reply},
        f'Reading "{paper.title}", they highlighted "{req.selection}" and chatted with the tutor:\n{chat}\nTutor: {reply.reply}',
    )
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


# The paper browser (../web). Mounted last so the API routes above take precedence.
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent.parent / "web", html=True), name="web")
