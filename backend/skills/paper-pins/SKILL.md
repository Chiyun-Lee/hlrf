---
name: paper-pins
description: Turn a paper review (a paper2agent run, re-run notebooks, tests through the paper's MCP tools, a reviewer's notes or review.md) into Human Pretraining's methods pins, the buttons on a paper's figures and tables saying where the data come from and what the review found. Use when asked to write, fix or check pins.json for a paper, or when a review job hands you paper.pdf and targets.json.
---

# Paper pins

You write `pins.json`: for every figure and table of one paper, short pins a reader opens beside it. The reader sees
the title on a button, then a plain line and a researcher's line, plus how far the claim was checked.

## Inputs

- The paper, either as a library paper id (interactive use: run the commands below from `backend/`), or a review
  job's work dir holding `paper.pdf` and `targets.json`. In the commands, PAPER is the library id or the path of the
  PDF (`paper.pdf`).
- The review's evidence: paper2agent outputs, notebook re-runs, tests run through the paper's MCP tools, the
  reviewer's notes or `review.md`. Pins only say what this evidence supports.

## Steps

1. List the figures and tables: read `targets.json`, or run `uv run python -m app.pins targets PAPER`. Each target
   has `label`, `page` (0-indexed), `caption` (how its caption starts, as printed) and `bbox` (its box in PDF points
   from the page's top-left, without the caption). Keep those four as they are. If a box looks wrong, or a figure or
   table is missing, draw the page and look: `uv run python -m app.pins render PAPER PAGE out.png` (add `pins.json`
   as a 4th argument to draw your own boxes). A fixed box must keep its caption right against it.
2. For EVERY figure and table, write one **Data provenance** pin (`"kind": "data"`) first: where its numbers come
   from (the dataset, its release or version, whether the values match the official release, which code produces the
   figure or table, and whether that code is released). For a purely theoretical figure, say it plots a calculation
   and from what (which equations, which parameter values).
3. Then **Agent-reviewed concern** pins (`"kind": "concern"`), only where the review's evidence supports them: one
   per distinct concern, the most important first. No evidence, no concern.
4. **Method** pins (`"kind": "method"`) are optional: what was done to get the figure (the model, the fit, the
   statistic), when it helps to read it.
5. At most 4 pins per figure or table.

## Evidence: never claim more than was done

Each pin's `evidence` is one of:

- `"From the paper"`: read in the paper (or its data release) only; nothing was run.
- `"Code re-run"`: the authors' code was run; say whether it reproduced the result.
- `"Tested"`: an independent check was run (a test, a recomputation, a comparison with the official data).

Pick the lowest level that is true for that pin's claim. A pin about released data whose values were compared with
the official file is "Tested"; the same pin without the comparison is "From the paper".

## Style

- `title`: at most 4 words; it is shown on the button.
- `basic`: one plain line anyone can follow, at most 22 words.
- `researcher`: precise, with the numbers, at most 45 words.
- No hype. Never invent numbers: only those in the paper or the review's outputs. If something isn't public, say
  "not released" rather than guess.
- `reviewed` says what the pins rest on: `"Agent review of arXiv:2506.22373v2: the authors' notebooks re-run and
  the claims tested through paper2agent, 17 Oct 2026"` (what was done, then the date).
- `verdict`: the review's bottom line, in 1-2 sentences.
- `arxiv_id`: the arXiv id without its version, or leave it out for a paper not on arXiv.

## Claims and main problems: the Reproduction card

The paper's summary cards end with a Reproduction card drawn from `pins.json`: the verdict, a table of the paper's
main claims against the re-run, and the main problems. It updates whenever a review stores new pins.

- `claims` (when code was re-run or claims were tested; at most 8, most important first): each has
  - `claim`: the paper's claim in one line (at most 20 words);
  - `paper`: its number or result as the paper gives it ("5.4σ", "j₀ = 2.04"; at most 12 words);
  - `rerun`: what the re-run or the test gave, in the same terms (at most 12 words), or null when nothing was run;
  - `status`: `"holds"` (reproduced, and the tests back it), `"partly"` (reproduced but weaker, or holds only in
    part), `"fails"` (not reproduced, or the tests break it) or `"untested"` (nothing run; `rerun` null);
  - `check`: how it was checked and what was found (at most 35 words).
- `main_problems`: the review's main problems, most important first (at most 5, each at most 45 words).

The same evidence rule holds: a claim is only "holds", "partly" or "fails" when something was run.

## Output

Write `pins.json` where the caller says (in a review job: the work dir):

```json
{
  "arxiv_id": "2506.22373",
  "reviewed": "Agent review of arXiv:2506.22373v2: ..., 17 Oct 2026",
  "verdict": "...",
  "claims": [
    {"claim": "...", "paper": "5.4σ", "rerun": "5.42σ; 3.9σ by profile likelihood", "status": "partly", "check": "..."}
  ],
  "main_problems": ["..."],
  "targets": [
    {"label": "Table I", "page": 2, "caption": "Table I.", "bbox": [382, 479, 497, 653], "pins": [
      {"kind": "data", "title": "DESI distances", "basic": "...", "researcher": "...", "evidence": "Tested"}
    ]}
  ]
}
```

Then check it, and fix what it reports until it says `ok`: `uv run python -m app.pins check PAPER pins.json` (or the
job's check tool, if the job gives you one). The check reports every broken rule with what to fix: a box with no
caption right against it (it would not show), a missing or misplaced data pin, too many pins, lines over their word
limits, a figure listed twice, a claim marked tested with nothing run.

For interactive use, `uv run python -m app.pins save PAPER_ID pins.json` checks and stores the pins for that library
paper; the reader then shows them instead of any shipped ones.

## Worked example

`backend/app/pins/2506.22373.json`: the pins from a paper2agent review of arXiv:2506.22373v2 that re-ran the authors'
notebooks and tested the claims.
