Speed of generation has exploded, and the attention economy has fried our attention spans, but humans still need to understand the latest developments. Apps like Duolingo have shown learning hard things can be gameified, immersive and holds you accountable. 

We all have papers that we've been meaning to read, but never get round to reading -- Can we help researchers understand papers within 5 minutes, so that we never procrastinate?

The goal is to have a Google Chrome widget which allows you to save the contents of a page or research manuscript, and it extracts the citations in a more intelligent manner than how Mendeley and Zotero do it. 

On the app, the user can view an interactive version of the paper's PDF, where the format of the paper is kept intact (so that the user can navigate the original paper still), but blocks of paragraphs are replaced by AI-summaried bullet points in much larger font and occupy the space that the original content occupied. Blocks of text are now encapsulated by a box and in the top-right corner, there is a "switch" button which allows you to flip between the original text and the summarised version. Below the switch button, is a question button where the user can ask an agent a question, after which the agent has the option to modify the summary or bring the user to a side-lesson to explain a wider concept. 
## Running the MVP

**Backend** (Python, [uv](https://docs.astral.sh/uv/)):
```sh
cd backend
cp .env.example .env   # add your ANTHROPIC_API_KEY
uv sync
uv run uvicorn app.main:app --reload
```
`POST /papers {"url": ..., "meta": {...}}` downloads the paper, extracts its text page by page (`app/extract.py`), and makes one Claude call to read the title and authors (including equal-contribution and corresponding markers). The record (`app/schemas.py`) is stored in SQLite. `GET /papers/{id}` returns it. Set `EXTRACT_MODEL` / `EXTRACT_EFFORT` in `.env` to trade speed for accuracy.

**Extension**:
```sh
cd extension && npm install && npm run build
```
Then open `chrome://extensions`, turn on Developer mode, choose "Load unpacked" and select `extension/`. On a paper page, click the icon, then **Save this paper**.

**Paper browser** (`web/`, plain HTML/JS, no build): with the backend running, open http://localhost:8000/ (or click **Open library** in the extension popup). It lists saved papers. Each paper opens in the reader (`web/reader.js`): the PDF rendered with pdf.js, with a "doodle note" over each paragraph, plain-language bullets in a handwritten font that blur the original underneath, in the style of [Claire Lamman's annotated papers](https://clairelamman.com/paper_summaries.html). The switch in each note's top-right corner flips back to the original. Notes are written page by page as you scroll (`app/summarize.py`, `GET /papers/{id}/pages/{n}/summary`) and cached. Papers we could only get as HTML show their text with the same notes. The handwriting font is [xkcd-script](https://github.com/ipython/xkcd-font) (CC BY-NC 3.0).

**For you** (`web/foryou.js`, the second tab): each day's new arXiv papers in your categories, fetched straight from the arXiv API (`app/arxiv.py`) and ranked for you (`app/feed.py`, `app/ranker.py`: logistic regression on TF-IDF words, phrases and authors). Add your own papers under **Your papers** (arXiv ids or links); the ranking also learns from More like this, Not for me, the papers you open and everything in the library. Every paper gets a two-line summary from Claude, top five picks first: what it does and why you'd care given your papers (`app/pitch.py`, batched and cached). Sorting 5 of a day's papers meets the daily goal, and doing that on consecutive listing days builds a streak. Keys: `j`/`k` move, `a` add to library, `m` more like this, `n` not for me, `o` open. Set `FEED_CATEGORIES` in `.env` to follow other categories (default `astro-ph.CO`). Without `ANTHROPIC_API_KEY` it shows abstracts instead of summaries.

**Claude through your subscription**: set `LLM_BACKEND=claude-code` in `backend/.env` and run `uv sync --extra claude-code`. Every Claude call (summaries, saving papers, page notes) then goes through the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview), which runs Claude Code with the login from `claude` instead of an API key (`app/llm.py`). For running the app yourself: Anthropic doesn't allow offering claude.ai login in products you distribute.

**Tests**: `cd backend && uv run pytest` (add `RUN_LIVE=1` to call Claude end to end).
