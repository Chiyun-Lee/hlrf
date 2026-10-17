from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import agent, db
from .schemas import Paper

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origin_regex=r"chrome-extension://.*", allow_methods=["*"], allow_headers=["*"])


class SaveRequest(BaseModel):
    url: str
    meta: dict = {}


@app.post("/papers")
def save_paper(req: SaveRequest) -> dict:
    paper = agent.extract(req.url, req.meta)
    return {"id": db.save(paper), "paper": paper}


@app.get("/papers/{paper_id}")
def get_paper(paper_id: int) -> Paper:
    paper = db.get(paper_id)
    if not paper:
        raise HTTPException(404)
    return paper
