import base64
import logging
import threading
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, extract, summarize
from .schemas import PageSummary

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


# The paper browser (../web). Mounted last so the API routes above take precedence.
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent.parent / "web", html=True), name="web")
