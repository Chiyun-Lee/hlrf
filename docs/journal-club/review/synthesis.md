# Synthesis: what the Library Journal Club society layer should borrow

Cross-track synthesis of [virtual_lab.md](virtual_lab.md), [ascollab.md](ascollab.md), [rsi.md](rsi.md) and [organisation_structure.md](organisation_structure.md). Written for the person owning rounds, review, disputes, collaborations and the archive (Person 2). 56 sources verified across the four tracks; 0 fabricated. Two corrections to the pitch doc are listed first.

## 0. Corrections to the pitch doc

1. **ASCollab's real title** is "Hypothesis Hunting with Evolving Networks of Autonomous Scientific Agents" (Liu, Ruhrberg Estévez, Bentley, van der Schaar; arXiv [2510.08619](https://arxiv.org/abs/2510.08619); NeurIPS 2026 follow-up). "ASCollab" is the system name. Cite it that way on stage. It has a code repo (Apache-2.0, LangGraph) that Person 2 can read for the review/meta-review prompts.
2. **"Its agents are invented personas exploring one dataset, not real papers"** is accurate. But also note: **ASCollab has no dispute mechanism at all** (paper and repo both say so). The dispute step is a genuine addition, not a reimplementation. Say that.
3. Virtual Lab is **not on arXiv**: bioRxiv 10.1101/2024.11.11.623004 → Nature 646(8085), 2025. Paper2Agent is arXiv [2509.06917](https://arxiv.org/abs/2509.06917); its "two paper agents finding a genetic variant" claim was not checked in this review — verify before the pitch.

## 1. The two anchors disagree on structure. Pick ASCollab's skeleton, Virtual Lab's prompts.

| Dimension | Virtual Lab | ASCollab | Decision for the Club |
|---|---|---|---|
| Hierarchy | PI leads, synthesises each round | Flat; every agent is PI; one meta-reviewer | **Flat** (papers are peers) + one meta-reviewer + one judge |
| Transcript | One shared thread, swap system prompt | Private ReAct sessions, shared archive | **Shared archive**, sessions per pair/triad (20 agents won't fit one thread) |
| What crosses rounds | Structured summaries only | Accepted reports only (archive) | **Structured notes only**, never transcripts |
| Critique | Standing Critic, 21-33% of words | K=2 blind reviewers + meta-review tournament | **K=2 near + 1 far reviewer**, blind, numeric scores; Critic prompt reused as the reviewer system prompt |
| Disagreement | "you can and should disagree", PI must "choose one" | None | **Add MAD-style dispute with neutral judge** |
| Diversity | Human-defined roles | Six-stance persona, fixed | **Six-stance persona generated from the paper** (free diversity) |
| Human | Agenda + rewrite, 1.3% words | None | Agenda at start, triage of "unresolved" in the morning |

## 2. The round, revised against the evidence

The pitch doc's five steps survive, with these changes:

**Step 1 — Paper agents.** Four-field spec (Virtual Lab) + six-stance persona (ASCollab B.2). Title = citekey; expertise = methods/data; goal = the claims it defends; role = how it argues; persona = six bullets, fixed. One LLM call per paper from Zotero metadata + abstract. Claims must be structured (entity, direction, effect, context) or dispute detection fails.

**Step 2 — Peer review.** Per paper: 2 near reviewers (top-2 embedding similarity; ResearchTown, ASCollab registry) + 1 far reviewer (random other cluster; MacNet). Blind to authorship (AgentReview: 27.7% shift otherwise). ASCollab rubric: Support / Soundness / Significance / Originality 1-4, recommendation 1-5, plus the Virtual Lab Critic boundary "only provide feedback". Cap ~3 reviews per agent per round. Numeric scores are what drive outcomes (AgentReview); rebuttals barely matter — so skip a generic rebuttal step and spend the budget on disputes.

**Step 3 — Disputes.** Trigger: structured claims clash, OR two reviewers differ by ≥2 on recommendation. Protocol (Liang MAD): owner = affirmative, challenger = negative, moderate tit-for-tat, max 3 rounds; a **judge on a different model** (Liang judge-bias) that sees no authorship. Verdicts: **stands** (judge sides with owner), **contested** (judge sides with challenger; both claims kept, linked), **unresolved** (cap hit; → human triage). Allow "no conflict" as an outcome; no permanent devil's advocate (Smit). Log as structured record: claim, evidence quotes with locations, verdict, confidence.

**Step 4 — Collaborations.** Pairs only (ResearchTown: many unrelated domains → vague). One near pair + one cross-cluster pair per round, chosen by Proximity-style similarity (Co-Scientist). ASCollab principal-collaborator: initiator leads, collaborator critiques but cannot run tools. Output = one joint note, both parents linked. Novelty check against the whole archive before acceptance (ASCollab `semantic_novelty_knn_distance`, AgentRxiv duplication).

**Step 5 — Archive.** Never discard (DGM, ADAS): every review, verdict, proposal is stored with its score. Acceptance = top ~25-50% by meta-review (ASCollab; the exact constant is inconsistent between their paper and code, so treat as a knob). Gate for "finding passes": every quoted passage string-matches the source, ≥2 uninvolved reviewers accept, rubric score ≥ threshold. Tag each claim verified/unverified (AgentRxiv hallucinated numbers). Write back to Zotero as a note on each paper involved.

**Between rounds (the RSI lever).** Before round N+1, each agent gets: (a) a one-paragraph meta-review digest of why things lost (Co-Scientist), (b) its own lowest review score (ASCollab exp 04 self-reflection), (c) top-k archive hits by similarity with a 0.2 citation boost. Non-greedy selection of what to re-examine (DGM score + few-children bonus) so the society doesn't collapse onto one topic.

## 3. Budget and caps, from the evidence

- **Rounds: cap at 4.** Debate gains flatten at 4 rounds (Du et al.); every LLM-judged loop in the RSI track is front-loaded within 2-4 rounds. Spend remaining budget on breadth (more pairs), not depth.
- **Per round, ~20 papers:** 20 sessions + 60 reviews + ~5 disputes × ≤3 turns × 3 agents + 4 collaborations + 5 meta-reviews ≈ 150 LLM calls. Four rounds ≈ 600 calls. Checkpoint after every step (ASCollab snapshots are per round and resumable).
- **No source reports a dollar figure.** Virtual Lab: 5-10 min per meeting on gpt-4o. ASCollab: 720 s session cap. Measure your own round-1 cost before 10 pm and extrapolate.
- **Diversity costs little:** mix two backbones if possible (ReConcile: diversity is the driver; ASCollab NeurIPS mixes three).

## 4. What not to claim on stage

- **"Rounds get better."** No paper shows compounding on open-ended research judgments with human ground truth beyond a handful of rounds. With LLM-judged scores only, improvement is indistinguishable from drift toward what the judge likes (Huang et al.; Moltbook trilemma). Say "rounds change" unless you add one external check: citation string-match pass rate per round, or a fixed rubric scored by a different model. Plot that in the morning.
- **"Findings."** Both anchors say candidate hypotheses. ASCollab §6 verbatim: "findings represent candidate hypotheses rather than validated biomedical discoveries."
- **"Reproduces ASCollab."** You are reusing its review/archive skeleton and adding what it lacks (real papers as agents; disputes). That is the contribution; keep it crisp.

## 5. Interfaces to lock with the team (by lunch)

- **In (Person 1):** `paper_card = {id, citekey, claims[{entity, direction, effect, context, quote, loc}], methods, data, limits, tools[], persona[6], expertise}`.
- **Out (Persons 3, 4):** append-only `events.jsonl`: `{round, step, type: review|dispute|collab|finding|meta, papers[], edge: green|red, scores{}, verdict, evidence[{paper, quote, loc}], status: verified|unverified}`. Network view, minutes, Zotero write-back and the stage replay all read this one file.
- **Hook for "ask your library" (Person 3):** `debate(question, paper_ids) -> {positions[], dissent[], evidence[]}` — reuse the dispute machinery; keep dissent, don't average.
- **Hook for People's Choice:** `run_round(subset=[new_paper] + nearest_k)` so adding one paper does not re-run the library.

## 6. Build order for Person 2 today

1. Schemas above → 2. reviewer matching (embeddings over 20 abstracts, trivial) → 3. one end-to-end round on 5 papers with the ASCollab rubric → 4. archive gate + Zotero note format → 5. dispute protocol with judge on a second model → 6. collaborations → 7. meta-review digest + caps + checkpoints → 8. full run by ~10 pm.

## Sources
All claims trace to the four track files, which carry the links. Totals: RSI 27 IDs, organisation 30 IDs, ASCollab 1 arXiv + repo + NeurIPS poster, Virtual Lab bioRxiv + Nature DOI + repo. Unverified items are flagged in each file (ASCollab Fig. 3 numbers; NeurIPS exp 08 results; Virtual Lab ablations; five 2026 abstract-only entries).
