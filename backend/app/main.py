import base64
import json
import logging
import threading
import zlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import abstract as graphical
from . import cards, db, extract, feed, ink, llm, memory, pins, pitch, proof, quiz, review, revision, summarize, tutor
from .levels import DEFAULT, Level
from .schemas import GraphicalAbstract, Ink, LearnerProfile, Note, PageSummary, Paper, PaperPins, Pitch, Proof, SummaryCards

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origin_regex=r"chrome-extension://.*", allow_methods=["*"], allow_headers=["*"])


class SaveRequest(BaseModel):
    """Sent by the extension, or by the library's "Add a paper" box. html/pdf are captured in the user's browser (or a
    PDF uploaded from disk); without them the backend downloads the URL. An upload may come without a URL."""

    url: str = ""
    meta: dict = {}
    html: str | None = None
    pdf: str | None = None  # base64


@app.post("/papers")
def save_paper(req: SaveRequest) -> dict:
    pdf = base64.b64decode(req.pdf) if req.pdf else None
    if pdf is not None and not extract.is_pdf(pdf):
        raise HTTPException(400, "That file isn't a PDF.")
    if not pdf and not req.url.strip():
        raise HTTPException(400, "Paste a link or choose a PDF.")
    try:
        paper, pdf = extract.extract(req.url.strip(), req.meta, req.html, pdf)
    except Exception as e:
        # Surface the cause in the extension popup rather than a bare 500.
        logging.exception("extraction failed for %s", req.url)
        raise HTTPException(500, f"{type(e).__name__}: {e}")
    return {"id": db.save(paper, pdf), "title": paper.title}


@app.get("/papers")
def list_papers() -> list[dict]:
    """Summaries for the library view; fetch /papers/{id} for the full record."""
    return [
        {"id": pid, "title": title, "authors": [a["raw"] for a in json.loads(authors)], "year": year, "venue": venue, "url": url, "n_pages": n_pages,
         "reviewed": pins.has_pins(pid, url, arxiv_id)}  # has pins from an agent review: the library's "AI reviewed" filter
        for pid, title, authors, year, venue, url, arxiv_id, n_pages in db.listing()
    ]


@app.get("/papers/{paper_id}")
def get_paper(paper_id: int) -> dict:
    paper = db.get(paper_id)
    if not paper:
        raise HTTPException(404)
    return {
        **paper.model_dump(),
        "has_pdf": db.has_pdf(paper_id),
        "abstract_levels": db.abstract_levels(paper_id),
        "card_levels": db.card_levels(paper_id),
        # The paper's arXiv id, normalised as For you stores it, so the reader can add it to "Your papers".
        "feed_id": (feed_id := feed.arxiv_id(paper.url, paper.arxiv_id)),
        "in_your_papers": feed.is_mine(feed_id),
        "reviewed": pins.has_pins(paper_id, paper.url, paper.arxiv_id),  # has pins from an agent review (review.js)
    }


@app.delete("/papers/{paper_id}", status_code=204)
def delete_paper(paper_id: int) -> None:
    if not db.delete(paper_id):
        raise HTTPException(404)
    review.discard(paper_id)  # stop its review and delete its files: SQLite may give its id to the next paper


@app.get("/papers/{paper_id}/pdf")
def get_pdf(paper_id: int, request: Request) -> Response:
    pdf = db.get_pdf(paper_id)
    if not pdf:
        raise HTTPException(404)
    # The browser keeps the PDF and checks back each time, so an unchanged one costs a 304 rather than megabytes. The
    # tag is a checksum of the PDF itself: a deleted paper's id goes to the next paper saved (db.save).
    headers = {"ETag": f'"{len(pdf):x}-{zlib.crc32(pdf):08x}"', "Cache-Control": "no-cache"}
    if headers["ETag"] in request.headers.get("if-none-match", ""):
        return Response(status_code=304, headers=headers)
    return Response(pdf, media_type="application/pdf", headers=headers)


# Notes, abstracts and quizzes are written for one reading level (app/levels.py), passed as ?level=.

summary_locks = defaultdict(threading.Lock)  # one generation per page and level, even if the viewer asks twice


def page_summary(paper_id: int, paper: Paper, page: int, level: Level) -> PageSummary:
    """Notes for one page (0-indexed), generated on first request and cached."""
    with summary_locks[paper_id, page, level]:
        if summary := db.get_summary(paper_id, page, level):
            return summary
        summary = summarize.summarize_page(paper, page, level, db.get_pdf(paper_id))
        db.save_summary(paper_id, page, level, summary)
        return summary


def all_summaries(paper_id: int, paper: Paper, level: Level) -> list[PageSummary]:
    """Notes for every page. A page whose notes can't be written is left empty (and retried next time) rather than
    sinking whatever needs the whole paper."""

    def one(i: int) -> PageSummary:
        try:
            return page_summary(paper_id, paper, i, level)
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
def get_summary(paper_id: int, page: int, level: Level = DEFAULT) -> PageSummary:
    paper = get_paper_or_404(paper_id)
    if not 0 <= page < len(paper.pages):
        raise HTTPException(404)
    with claude_errors(f"summary of paper {paper_id} page {page}"):
        return page_summary(paper_id, paper, page, level)


@app.get("/papers/{paper_id}/pins")
def get_pins(paper_id: int) -> PaperPins | None:
    """Methods pins for the paper's figures and tables (app/pins.py): an agent review's, else shipped; null when none."""
    return pins.for_paper(paper_id, get_paper_or_404(paper_id))


# --- Agent review: Claude Code reviews the paper in the background and writes its pins (app/review.py) ---


class ReviewRequest(BaseModel):
    depth: Literal["full", "quick"] = "full"  # full re-runs the authors' code (about 2 h); quick only reads (about 15 min)


@app.post("/papers/{paper_id}/review", status_code=202)
def start_review(paper_id: int, req: ReviewRequest | None = None) -> review.Status:
    get_paper_or_404(paper_id)
    try:
        return review.start(paper_id, (req or ReviewRequest()).depth)
    except review.CantStart as e:
        raise HTTPException(e.status, str(e))


@app.get("/papers/{paper_id}/review")
def get_review(paper_id: int, after: int = 0) -> review.Status | None:
    """The review's state, with its live view from event `after` on; null if the paper was never reviewed."""
    get_paper_or_404(paper_id)
    return review.status(paper_id, after)


@app.delete("/papers/{paper_id}/review", status_code=204)
def stop_review(paper_id: int) -> None:
    get_paper_or_404(paper_id)
    review.stop(paper_id)


@app.get("/papers/{paper_id}/review/report")
def get_review_report(paper_id: int) -> Response:
    """The review itself, as Markdown."""
    if (text := review.report(paper_id)) is None:
        raise HTTPException(404)
    return Response(text, media_type="text/plain; charset=utf-8")


@app.get("/reviews")
def list_reviews() -> dict[str, dict]:
    """{paper_id: {state, depth, progress, stage_title}} for every paper with a review, running or finished."""
    return review.all_reviews()


@app.get("/papers/{paper_id}/abstract")
def get_abstract(paper_id: int, level: Level = DEFAULT) -> GraphicalAbstract:
    if not (abstract := db.get_abstract(paper_id, level)):
        raise HTTPException(404)
    return abstract


@app.post("/papers/{paper_id}/abstract")
def make_abstract(paper_id: int, level: Level = DEFAULT) -> GraphicalAbstract:
    """(Re)make the graphical abstract from the notes, writing notes for any pages not read yet."""
    paper = get_paper_or_404(paper_id)
    with claude_errors(f"abstract of paper {paper_id}"):
        abstract = graphical.make(paper, all_summaries(paper_id, paper, level), db.get_pdf(paper_id), level)
    db.save_abstract(paper_id, level, abstract)
    return abstract


@app.get("/papers/{paper_id}/cards")
def get_cards(paper_id: int, level: Level = DEFAULT) -> SummaryCards:
    if not (deck := db.get_cards(paper_id, level)):
        raise HTTPException(404)
    return deck


@app.post("/papers/{paper_id}/cards")
def make_cards(paper_id: int, level: Level = DEFAULT) -> SummaryCards:
    """(Re)make the summary cards from the notes and the paper's text, writing notes for any pages not read yet."""
    paper = get_paper_or_404(paper_id)
    with claude_errors(f"cards for paper {paper_id}"):
        deck = cards.make(paper, all_summaries(paper_id, paper, level), db.get_pdf(paper_id), level)
    db.save_cards(paper_id, level, deck)
    return deck


@app.post("/papers/{paper_id}/quiz")
def make_quiz(paper_id: int, level: Level = DEFAULT) -> dict:
    """A fresh quiz each time, from the notes and the graphical abstract. Its questions also go into the revision bank
    (app/revision.py); each comes back with its bank `id`, so answers count towards revision."""
    paper = get_paper_or_404(paper_id)
    if not (abstract := db.get_abstract(paper_id, level)):
        raise HTTPException(409, "Make the graphical abstract first.")
    with claude_errors(f"quiz for paper {paper_id}"):
        made = quiz.make(paper, all_summaries(paper_id, paper, level), abstract, level)
    ids = db.add_questions(paper_id, level, made.questions, revision.today().isoformat())
    return {
        "questions": [
            {**q.model_dump(), "id": i, "paper_id": paper_id, "paper": paper.title, "level": level}
            for q, i in zip(made.questions, ids)
        ]
    }


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


@app.get("/revision")
def get_revision() -> dict:
    """The Revision page: XP today, streak, the week, and each paper's questions, due count and strength."""
    return revision.overview()


class SessionRequest(BaseModel):
    paper_ids: list[int] | None = None  # None: every paper
    n: int = revision.SESSION


@app.post("/revision/session")
def revision_session(req: SessionRequest) -> dict:
    """A review: due questions first, mixed across papers."""
    return {"questions": revision.session(req.paper_ids, max(1, min(req.n, 30)))}


class AnswerRequest(BaseModel):
    correct: bool
    first_try: bool = True


@app.post("/revision/questions/{question_id}/answer")
def revision_answer(question_id: int, req: AnswerRequest) -> dict:
    """Record an answer (from a review or a paper's quiz): moves the question between boxes and awards XP."""
    try:
        return revision.answer(question_id, req.correct, req.first_try)
    except KeyError:
        raise HTTPException(404, "No such question")


@app.post("/revision/result", status_code=204)
def revision_result(result: QuizResult) -> None:
    """Remember how a review across papers went; `missed` items also carry their "paper"."""
    missed = "\n".join(f"- [{m.get('paper')}] {m.get('prompt')} (answer: {m.get('answer')})" for m in result.missed) or "(none)"
    memory.record(
        None,
        "revision",
        result.model_dump(),
        f"Revision across papers: {result.right_first_time}/{result.total} right first time. Missed:\n{missed}",
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
def show_proof(paper_id: int, req: ProofRequest, level: Level = DEFAULT) -> Proof:
    """The original paragraph behind a quiz answer, with the key words picked out, plus its note."""
    paper = get_paper_or_404(paper_id)
    try:
        p, k = summarize.parse_note_id(req.proof)
        note = db.get_summary(paper_id, p, level).notes[k]
    except (ValueError, IndexError, AttributeError):
        raise HTTPException(404, "No such note")
    with claude_errors(f"proof for paper {paper_id}"):
        return proof.find(paper, p, note, req.question, req.answer, req.explanation)


class AskRequest(BaseModel):
    note: int | None = None  # index of the note over the highlighted passage, if any
    selection: str
    messages: list[dict]  # the chat so far: [{"role": "user"|"assistant", "content": str}], ending with the user


@app.post("/papers/{paper_id}/pages/{page}/ask")
def ask(paper_id: int, page: int, req: AskRequest, level: Level = DEFAULT) -> dict:
    """Answer a question about a highlighted passage. Returns the reply, and the note if the tutor updated it."""
    paper, summary = db.get(paper_id), db.get_summary(paper_id, page, level)
    if not paper or not 0 <= page < len(paper.pages):
        raise HTTPException(404)
    note = summary.notes[req.note] if summary and req.note is not None and 0 <= req.note < len(summary.notes) else None
    with claude_errors(f"tutor for paper {paper_id} page {page}"):
        reply = tutor.answer(paper, page, note, req.selection, req.messages, level)
    chat = "\n".join(f"{'Reader' if m['role'] == 'user' else 'Tutor'}: {m['content']}" for m in req.messages)
    memory.record(
        paper_id,
        "question",
        {"page": page, "level": level, "selection": req.selection, "question": req.messages[-1]["content"], "answer": reply.reply},
        f'Reading "{paper.title}", they highlighted "{req.selection}" and chatted with the tutor:\n{chat}\nTutor: {reply.reply}',
    )
    updated = None
    if note and reply.update_note and (reply.bullets or reply.heading):
        note.bullets = reply.bullets or note.bullets
        note.heading = reply.heading or note.heading
        db.save_summary(paper_id, page, level, summary)
        updated = note
    return {"reply": reply.reply, "updated_note": updated}


@app.put("/papers/{paper_id}/pages/{page}/notes/{index}")
def put_note(paper_id: int, page: int, index: int, note: Note, level: Level = DEFAULT) -> Note:
    """Replace one note (the reader's own edits, and undoing a tutor's edit)."""
    summary = db.get_summary(paper_id, page, level)
    if not summary or not 0 <= index < len(summary.notes):
        raise HTTPException(404)
    summary.notes[index] = note
    db.save_summary(paper_id, page, level, summary)
    return note


# --- Handwriting: write or draw on a paper and Ask about it (app/ink.py, web/ink.js) ---


@app.get("/papers/{paper_id}/ink")
def get_ink(paper_id: int) -> Ink:
    get_paper_or_404(paper_id)
    return db.get_ink(paper_id)


@app.put("/papers/{paper_id}/ink")
def put_ink(paper_id: int, body: Ink) -> Ink:
    """The reader saves all their strokes and answer cards on a paper at once, shortly after each change."""
    get_paper_or_404(paper_id)
    db.save_ink(paper_id, body)
    return body


class InkAskRequest(BaseModel):
    image: str  # base64 JPEG or PNG of the paper on screen, with the ink on it
    media_type: Literal["image/jpeg", "image/png"] = "image/jpeg"
    pages: list[int]  # the pages it shows, top to bottom
    notes: list[str] = []  # the doodle notes on screen
    card: str | None = None  # the card this answers (re-asking replaces it), so it isn't sent as an earlier answer


@app.post("/papers/{paper_id}/ink/ask")
def ask_ink(paper_id: int, req: InkAskRequest, level: Level = DEFAULT) -> dict:
    """Read the handwriting on screen and answer it; the reader puts the answer in a card next to the writing."""
    paper = get_paper_or_404(paper_id)
    if not req.pages or not all(0 <= p < len(paper.pages) for p in req.pages):
        raise HTTPException(422, "No such page")
    earlier = [c for c in db.get_ink(paper_id).cards if c.id != req.card and c.answer]
    with claude_errors(f"ink ask for paper {paper_id}"):
        reply = ink.answer(paper, req.image, req.media_type, req.pages, req.notes, earlier, level)
    memory.record(
        paper_id,
        "question",
        {"page": req.pages[0], "level": level, "selection": f"✎ handwriting on p. {req.pages[0] + 1}", "question": "; ".join(reply.read), "answer": reply.answer},
        f'Reading "{paper.title}", they wrote on page {req.pages[0] + 1}: {"; ".join(reply.read) or "(nothing legible)"}\nAnswer: {reply.answer}',
    )
    return reply.model_dump()


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


@app.get("/feed/sources")
def get_sources() -> dict:
    """The arXiv categories and bioRxiv subjects For you can follow, and which you follow now."""
    return feed.source_options()


class SourcesRequest(BaseModel):
    arxiv: list[str] = []  # category codes, e.g. astro-ph.CO
    biorxiv: list[str] = []  # subject names, e.g. Neuroscience


@app.put("/feed/sources")
def put_sources(req: SourcesRequest) -> dict[str, list[str]]:
    return feed_call(feed.set_sources, req.arxiv, req.biorxiv)


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
