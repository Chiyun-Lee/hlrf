<p align="center"><img src="docs/images/banner.png" alt="HLRF: human learning + reinforced feedback. Team Seedless Grapes: Alex, Chiyun, Jacky, Jialin, Richard" width="760"></p>

# HLRF: understand a paper in five minutes

**Human learning + reinforced feedback.** Save any paper from Chrome. HLRF turns it into a paper you can actually get through. Hand-drawn notes sit on top of the original PDF, a tutor answers your questions, Duolingo-style quizzes make it stick, and AI agents check whether the results hold up.

AI now discovers faster than we can read. Duolingo showed that people can learn hard things when learning is gamified and immersive. HLRF puts the two together: discovery at AI speed, paired with learning that sticks.

<p align="center"><img src="docs/images/problem.png" alt="The problem: AI discovers faster than we can read; Duolingo cracked hard learning; can we get the best of both worlds?" width="760"></p>

## Quick start

You need [uv](https://docs.astral.sh/uv/), Node and Chrome.

```sh
# 1. Backend: also serves the app at http://localhost:8000
cd backend
cp .env.example .env            # add your ANTHROPIC_API_KEY
uv sync --extra claude-code
uv run --extra claude-code uvicorn app.main:app --reload

# 2. Chrome extension
cd extension && npm install && npm run build
```

Load the extension:

1. Open `chrome://extensions` and turn on Developer mode.
2. Choose **Load unpacked** and select `extension/`.
3. On any paper page, click the HLRF icon, then **Save this paper**.

> Keep `--extra claude-code` on every `uv sync` and `uv run`. Without it, uv removes the Claude Agent SDK and the agent review stops working. If you'd rather use your Claude subscription than an API key, set `LLM_BACKEND=claude-code` in `.env`.

Run the tests with `cd backend && uv run --extra claude-code pytest`.

## What you get

### 📝 Notes drawn on the paper
The original PDF stays intact. Each paragraph gets plain-language bullets handwritten over it. Figures get circles, arrows and scribbled callouts, and a switch flips any note back to the original text. You can pitch everything at **Outreach**, **Technical** or **Expert** level.

<img src="docs/images/notes.png" alt="Doodle notes over the AlphaFold paper" width="760">

### ✎ Ask about anything, or write on the whiteboard
To ask the tutor about a passage, highlight it and click **Ask**. You can also open a paper in **✎ Whiteboard** mode and write on it with a pen or finger. **Ask ✦** then reads your handwriting and pins an answer next to it.

### 🔬 Agent-reviewed figures
An agent review re-runs the authors' code and tests the paper's claims. It then pins **Data**, **Concern** and **Method** cards on every figure.

<img src="docs/images/figures.png" alt="Figure scribbles and agent-review pins" width="760">

### 🖼️ A graphical abstract and summary cards
The paper on one slide: the question, what they did, what they found, and the key figures. Below it are cards for the TL;DR, the logic, the evidence and the caveats, plus charts redrawn from numbers checked against the paper.

<img src="docs/images/abstract.png" alt="Graphical abstract" width="760">

### 🔥 Quizzes, streaks and spaced repetition
Duolingo-style questions about each paper. **Show me the proof** jumps to the exact paragraph behind each answer. Questions come back on a spaced-repetition schedule, and you earn XP, a daily goal and a streak.

<img src="docs/images/quiz.png" alt="A revision quiz" width="760">

### 🧪 And more
- **For you**: each day's new arXiv and bioRxiv papers, ranked for you, with a two-line pitch for each.
- **My learning**: a learner profile that the notes, tutor and quizzes adapt to.
- **Journal club**: your papers become PhD-student agents. Overnight they debate each other and propose new hypotheses, each backed by quotes checked against the papers.

<img src="docs/journal-club/journal_club_debate.svg" alt="How a journal club night works: the paper agents map every pair of papers as agreeing, clashing or sharing a limitation, debate the clashes under a PI, and turn consensus, unresolved clashes and shared limitations into ranked research directions and hypotheses" width="760">

<img src="docs/images/journal-club.png" alt="The pair map of a journal club night on DESI papers, with the desi2024vi and planck2018vi cell selected: they disagree, with the note and a checked quote from each paper" width="760">

## How it fits together

| Part | What it is |
|---|---|
| `extension/` | A Chrome extension (MV3, TypeScript) that saves the page or PDF you're on |
| `backend/` | A FastAPI and SQLite backend that makes every Claude call |
| `web/` | The reader app: plain HTML and JS, with no build step |

**Every feature, its code, and its settings are in [docs/features.md](docs/features.md).**

The handwriting font is [xkcd-script](https://github.com/ipython/xkcd-font) (CC BY-NC 3.0). The note style is inspired by [Claire Lamman's annotated papers](https://clairelamman.com/paper_summaries.html).

## Licence

Apache 2.0, see [LICENSE](LICENSE). Built by Team Seedless Grapes: Alex, Chiyun, Jacky, Jialin and Richard.
