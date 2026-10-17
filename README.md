Speed of generation has exploded, and the attention economy has fried our attention spans, but humans still need to understand the latest developments. Apps like Duolingo have shown learning hard things can be gameified, immersive and holds you accountable. 

We all have papers that we've been meaning to read, but never get round to reading -- Can we help researchers understand papers within 5 minutes, so that we never procrastinate?

The goal is to have a Google Chrome widget which allows you to save the contents of a page or research manuscript, and it extracts the citations in a more intelligent manner than how Mendeley and Zotero do it. 

On the app, the user can view an interactive version of the paper's PDF, where the format of the paper is kept intact (so that the user can navigate the original paper still), but blocks of paragraphs are replaced by AI-summaried bullet points in much larger font and occupy the space that the original content occupied. Blocks of text are now encapsulated by a box and in the top-right corner, there is a "switch" button which allows you to flip between the original text and the summarised version. Below the switch button, is a question button where the user can ask an agent a question, after which the agent has the option to modify the summary or bring the user to a side-lesson to explain a wider concept. 
## Running the citation extractor (MVP)

**Backend** (Python, [uv](https://docs.astral.sh/uv/)):
```sh
cd backend
cp .env.example .env   # add your ANTHROPIC_API_KEY
uv sync
uv run uvicorn app.main:app --reload
```
`POST /papers {"url": ..., "meta": {...}}` runs a Claude agent (`app/agent.py`) that reads the paper and resolves authors and references with tool calls (Crossref, Semantic Scholar), then stores the record (`app/schemas.py`) in SQLite. `GET /papers/{id}` returns it.

**Extension**:
```sh
cd extension && npm install && npm run build
```
Then open `chrome://extensions`, turn on Developer mode, choose "Load unpacked" and select `extension/`. On a paper page, click the icon, then **Save this paper**.

**Tests**: `cd backend && uv run pytest` (add `RUN_LIVE=1` to call Claude end to end).
