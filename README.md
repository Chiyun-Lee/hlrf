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

**Paper browser** (`web/`, plain HTML/JS, no build): with the backend running, open http://localhost:8000/ (or click **Open library** in the extension popup). It lists saved papers. Each paper opens in the reader (`web/reader.js`): the PDF rendered with pdf.js, with a "doodle note" over each paragraph, plain-language bullets in a handwritten font that blur the original underneath, in the style of [Claire Lamman's annotated papers](https://clairelamman.com/paper_summaries.html). The switch in each note's top-right corner flips back to the original. Notes are written page by page as you scroll (`app/summarize.py`, `GET /papers/{id}/pages/{n}/summary`) and cached. The **Outreach / Technical / Expert** switch picks who they're written for (`app/levels.py`): anyone, technical people from a neighbouring field, or people in the field. Notes, graphical abstracts and quizzes are written and cached per level (`?level=` on the API), and the tutor pitches its answers to it. Notes come in three kinds: summaries (one per section), figure callouts (Claude also sees the page image, so it reads the figure itself and doodles hand-drawn circles and arrows with short notes on it, `web/marks.js`) and asides (funding, references, author lists...), which are just blurred so the science stands out. Highlight any text, in a note or in the paper, and click **Ask** to chat about it with a tutor (`app/tutor.py`); once you say you've got it, the tutor adds anything important to that note (with undo). Notes can be edited in place (✎ on hover), and the tutor can reword them too when asked. When you're done reading, **Make graphical abstract** (`app/abstract.py`, drawn as SVG by `web/abstract.js`) writes notes for any unread pages and composes one slide: a title, the takeaway, a flow from question to findings, key points and one or two key figures cropped from the PDF; **Export SVG** saves it with the font and images embedded. **Quiz me** (`app/quiz.py`, `web/quiz.js`) then runs a Duolingo-style quiz of multiple-choice and fill-in-the-blank questions; missed ones come back until you get them, and **Show me the proof** (`app/proof.py`) shows the original paragraph with the key words highlighted next to your note. **My learning** (`app/memory.py`, `#/me`) remembers your tutor questions and quiz results and keeps a short learner profile (background, struggles, strengths, interests, preferences) that the notes, tutor and quiz adapt to; you can edit or wipe it there. One reader per install. Papers we could only get as HTML show their text with the same notes. The look (navy ink, xkcd handwriting) is shared by `web/style.css` and `extension/popup.css`. The handwriting font is [xkcd-script](https://github.com/ipython/xkcd-font) (CC BY-NC 3.0).

**Tests**: `cd backend && uv run pytest` (add `RUN_LIVE=1` to call Claude end to end).
