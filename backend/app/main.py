import base64
import logging
import threading
from collections import defaultdict
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, extract, feed, llm, pitch, summarize
from .schemas import PageSummary, Pitch

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
    return {**paper.model_dump(), "has_pdf": db.has_pdf(paper_id)}


@app.get("/papers/{paper_id}/pdf")
def get_pdf(paper_id: int) -> Response:
    pdf = db.get_pdf(paper_id)
    if not pdf:
        raise HTTPException(404)
    return Response(pdf, media_type="application/pdf")


summary_locks = defaultdict(threading.Lock)  # one generation per page, even if the viewer asks twice


@app.get("/papers/{paper_id}/pages/{page}/summary")
def get_summary(paper_id: int, page: int) -> PageSummary:
    """Notes for one page (0-indexed), generated on first request and cached."""
    with summary_locks[paper_id, page]:
        if summary := db.get_summary(paper_id, page):
            return summary
        paper = db.get(paper_id)
        if not paper or not 0 <= page < len(paper.pages):
            raise HTTPException(404)
        try:
            summary = summarize.summarize_page(paper, page)
        except Exception as e:
            logging.exception("summary failed for paper %s page %s", paper_id, page)
            raise HTTPException(500, f"{type(e).__name__}: {e}")
        db.save_summary(paper_id, page, summary)
        return summary


@app.delete("/papers/{paper_id}", status_code=204)
def delete_paper(paper_id: int) -> None:
    if not db.delete(paper_id):
        raise HTTPException(404)


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
