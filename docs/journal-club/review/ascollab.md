# Anchor paper 2: ASCollab (Liu, Ruhrberg Estévez, Bentley, van der Schaar — Cambridge)

Sources: **[P]** = arXiv v1 text ([HTML](https://arxiv.org/html/2510.08619v1)); **[R]** = repo docs for the NeurIPS version ([how_it_works.md](https://raw.githubusercontent.com/vanderschaarlab/Ascollab-Discovery-Platform/main/docs/how_it_works.md), [reproducing_paper.md](https://raw.githubusercontent.com/vanderschaarlab/Ascollab-Discovery-Platform/main/docs/reproducing_paper.md), [metrics.md](https://raw.githubusercontent.com/vanderschaarlab/Ascollab-Discovery-Platform/main/docs/metrics.md)). Where they differ it is noted.

## 0. Verification: VERIFIED

| Field | Value |
|---|---|
| arXiv | [2510.08619](https://arxiv.org/abs/2510.08619), v1, 8 Oct 2025, cs.AI/cs.LG, CC BY 4.0 |
| Exact title | **"Hypothesis Hunting with Evolving Networks of Autonomous Scientific Agents"**. "AScience" is the framework; "AScience-Collaboratory (ASCollab)" is the implementation (§3). |
| Authors | Tennison Liu, Silas Ruhrberg Estévez (DAMTP Cambridge), David L. Bentley (Colorado), Mihaela van der Schaar (Cambridge) |
| Follow-up | NeurIPS 2026 poster: ["Open-Ended Scientific Discovery and the Social Dynamics of Evolving Agent Networks"](https://neurips.cc/virtual/2026/poster/150676) (OpenReview gLFhs8AKyU, bot-checked, unread). Adds datasets + ablations. |
| Code | [vanderschaarlab/Ascollab-Discovery-Platform](https://github.com/vanderschaarlab/Ascollab-Discovery-Platform), Apache-2.0, Python 3.11 + Docker, LangGraph. Implements the NeurIPS version; arXiv v1 lists no code URL. |

Name clash: "ASCollab" is also an astrophysics code library, a human-robot framework, and an ASR workflow. Ignore.

## 1. Agent design [P §2.1, §3.2, App. B.2]
- Formal state: `a_i = (x, θ, e, b, ρ)` = approach, epistemic behaviour, expertise, belief state, reputation (accepted papers + citations).
- **N = 16 agents** (P §5). Repo default 16, model mix 6 GPT-4o / 5 GPT-5 / 5 DeepSeek.
- Creation: LLM generates distinct behavioural profiles + expertise at init, embedded in the system prompt. Two schema prompts (App. B.2):
  - **Epistemic persona**: six bullets, one per stance — Ideas (refine ↔ new), Collaboration (independent ↔ collaborative), Scope (broad ↔ deep), Evaluation (critical ↔ constructive), Literature (literature ↔ intuition), Resources (depth ↔ lean). **Fixed for life.**
  - **Expertise**: one bullet per topic given dataset context; **adaptive, periodically re-summarised by the agent.**
- Private memory of all past work incl. rejected findings; not searchable by others.
- Diversity justified via Hong & Page 2004. NeurIPS version adds backbone heterogeneity and a homogeneous-network ablation (exp 01).
- Evidence: Fig. 4 shows marked per-agent differences in session length, tool mix, collaboration frequency (P §5.3).

## 2. Organisation structure [P §2.1, §3.1, §3.3]
- **Flat.** Every agent is a PI each round. Only privileged role: a dedicated **meta-reviewer** that does no research (§3.4).
- Network = time-varying weighted directed graph; edge = attention i gives to j, esp. reputation. "Patterns of collaboration and attention emerge endogenously."
- Two shared structures as vector-search tools: **agent registry** (expertise + #accepted + #citations) and **internal archive** (title+abstract embeddings).
- Collaboration: agent searches registry; repo ranks by **0.8 × similarity + 0.2 × citations**; calls `EstablishCollaboration(id)`, then `Communicate`.
- **Principal-collaborator model**: initiator stays lead; collaborator is instantiated from the target's *persona only* (not its memory), can search but **cannot run code**; with `code_collaboration` on, messages carry the shared script.
- Observed: early tight repeat pairs, later re-centring around other hubs (§5.3). NeurIPS abstract: heterogeneous self-organising networks beat fixed-workflow and homogeneous baselines.

## 3. Round structure [P §3.3-3.4, §5; R]
- Hyperparameters: N=16, **T=40 rounds**, **M=40 ReAct steps/session**, **K=2 reviewers/paper**, **L=4 tournament size**. Repo: 720 s session limit, 480 s/code cell (3600/900 in larger exps), up to 10 concurrent sessions.
- One round: (1) every agent runs a free-form ReAct research session, may collaborate, must emit a **Final Report**; (2) optional per-paper metrics; (3) K reviews; (4) thematic clustering into tournaments of L, meta-reviewer scores 0-1 and ranks; (5) top fraction accepted into archive, citations and registry stats propagated; (6) snapshot to disk (resumable).
- Final Report template (App. B.3): Title / Research Question / Hypothesis and Key Findings / Rationale / Empirical Evidence / Literature Evidence / Assumptions / Limitations / References. "Use only retrieved references; do not fabricate citations." Internal cites use `[Internal Archive] {paper_id, agent_id, title}`.
- Termination: fixed T, no convergence rule. Timed-out sessions still yield a `_timeout`/`_incomplete` record.

## 4. Peer review [P §3.4, App. B.3; R]
- K=2 reviewers selected by registry query on the submission's title, author excluded, **double-blind**. Repo prefers least-loaded matching reviewers; `random` strategy used in exp 03.
- Reviewers see full codebase + archive/literature tools; **cannot execute code**.
- Rubric: 7 written sections (Summary; Motivation; Claims and Evidence; Soundness; Relation to Prior Knowledge; Novelty and Significance; Other) + **Support, Soundness, Significance, Originality on 1-4** + **Overall Recommendation 1-5**.
- Meta-reviewer: no tools; sees L=4 related submissions + reviews + **random archive samples for calibration**; outputs Brief Summary, Comparative Analysis, Decision = score ∈ [0,1] + strict rank (no ties) + justification.
- **Acceptance threshold disagrees between sources**: paper "top 1/K fraction" (50%); repo `max(1, n // L)` (~25%). Treat as a tunable rate.
- How reviews change behaviour: accepted papers enter the archive; citations raise author's registry rank. Finding: collaborative outputs get **systematically higher meta-review scores** despite double-blind (§5.3). By default reviews are **not shown back to authors** (R). NeurIPS ablations add **metacognition feedback** (digest of own prior reviews before each round) and **self-reflection** (reflect on lowest scores from round 2) — exp 04. Exp 09 injects **reviewer norms** (novelty-first vs soundness-first). Exp 07 removes reviewers; exp 10 varies K=1..4. Experimental: reputation score in prompt, pausing low-reputation agents.

## 5. Archive / shared memory and the self-improvement angle [P §3.1, App. B.1, §5.1; R]
- Stored (`PaperMetadata`): paper_id, primary + collaborating agent ids, title, abstract, manuscript, citation_count, publication_time, cited_paper_ids, code, metareview (text, score, rank, justification, decision), status. Registry `AgentProfile`: id, epistemic behaviour, expertise, citation count, num_accepted_papers.
- Retrieval: `text-embedding-3-small` over title+abstract, RAG into context; repo adds citation boost (0.1), FAISS.
- "Over T rounds, this feedback loop ensures that the network's collective behavior is continually shaped by cumulative findings" (§3.4). Case: ferroptosis finding built on another agent's earlier SLC7A11/ALOX5 result (§5.2).
- **Does the society improve across rounds? Evidence is indirect.** No quality-vs-round curve. Offered: (a) vs independent-agents baseline, top-25 rated higher on novelty and quality by one expert, no duplicates vs "almost half overlapping" (§5.1); (b) t-SNE: independent agents converge, ASCollab agents explore outward; (c) collaborative outputs score higher. This is evidence of *sustained exploration and cumulative building*, not monotone improvement.
- NeurIPS exp 08 **"Markovian social memory"** (archive keeps only last round's accepted papers vs cumulative) is the right ablation; results not in repo, OpenReview unread — **unverified**.

## 6. Dispute / disagreement handling
- **None.** No rebuttal, author response, or reviewer reconciliation. Disagreement resolved only by aggregation: meta-reviewer synthesises K reviews and ranks with "No ties allowed". Repo states "no rebuttal or dispute mechanism".
- Only adversarial elements: collaborator critique role; persona stance 4 (critical ↔ constructive).
- Rejection case studies exist (§5.2): filters overlap with prior literature or unsupported claims.

## 7. Evaluation [P §5, App. B.5; R]
- Task: TCGA KIRC, DLBC, PAAD (RNA-seq, RPPA, clinical, survival, pathways, drug-target); single instruction "discover novel, strongly supported, and scientifically significant findings". NeurIPS adds LUAD, NHANES, MI GWAS.
- Baseline: independent agents, same budget, no registry/archive.
- Protocol: top 25 per setting by meta-review score, dedup'd, scored by **one domain expert** on Novelty 1-5 and Quality 1-5 with anchors. Two experts did case studies.
- Numbers are in Fig. 3 only. Emergent Mind reports novelty 4.1 vs 2.8, quality 4.2 vs 3.0, 128 vs 45 gene targets — **unverified secondary**.
- Rediscoveries: ferroptosis ACSL4/GPX4/FTH1 in KIRC (published by Zheng et al. 2025 after cutoff); SLC5A2 + ABCC8 in PAAD; BIRC5 + PRKD1 extension.
- NeurIPS: **AutoRanker** pairwise LLM judge (gpt5-high) + 25 heuristic metrics (e.g. `semantic_novelty_knn_distance`, `hypothesis_overlap_jaccard`) + expert-validation notebook.

## 8. Cost / compute
- gpt-4o-2024-08-06 for all agents, text-embedding-3-small, LangGraph, 32-core EPYC sandbox (P §5).
- **Tokens / dollars / wall time: not reported.** Scale: 640 research sessions + 1280 reviews + ~160 meta-reviews per full run per dataset per condition. README warns even the 2-agent quickstart "makes many calls".

## 9. Stated limitations (P §6)
"results are demonstrated within genomics, and generalization to other domains remains to be established; expert-based evaluation ... is inevitably subjective; ... modest agent populations and a single LLM backbone. Most importantly, findings represent candidate hypotheses rather than validated biomedical discoveries." Plus: single rater; knowledge-cutoff issues; no cost accounting; no round-over-round curve; acceptance-rate constant inconsistent between paper and code.

## 10. Borrowable patterns for the paper-agent society

1. **Six-stance persona prompt, fixed; expertise adaptive.** Generate each paper-agent's persona with the B.2 schema; expertise = the paper's abstract/methods, re-summarised every few rounds. One call per agent.
2. **Two shared stores as vector-search tools.** Registry (per-paper expertise + #accepted + #citations) and archive (title+abstract of accepted findings + evidence + meta-review + cited_ids). Rank registry hits 0.8 similarity + 0.2 citations. One FAISS/sqlite is enough.
3. **Principal-collaborator sessions with a hard budget.** Each round every agent is PI for one session (e.g. 15 steps / 5 min), may `establish_collaboration(id)`; collaborator spun up from persona only, can critique but not act. Logged edges = the collaboration graph for free.
4. **Mandatory Final Report schema with retrieved-only citations and `[Internal Archive]{paper_id, agent_id}` cites.** Makes citations countable, reputation computable, blocks fabricated references.
5. **Two-stage review**: K=2 expertise-matched double-blind reviewers (1-4 × 4 + 1-5 rec) → thematic tournament meta-reviewer (L=4, 0-1, strict rank, archive calibration samples) → accept top ~25-50%. Accept rate is the knob controlling archive growth overnight.
6. **Add the dispute step ASCollab lacks.** When two reviewers' recommendations differ by ≥2, run one rebuttal turn before meta-review; log as a "dispute". Inject exp-09 reviewer norms (novelty-first vs soundness-first) to produce deliberate disagreement.
7. **Feedback-to-authors + self-reflection as the RSI lever.** Before each round, hand each agent a digest of its own previous reviews and lowest score (exp 04). Log per-round mean review score and novelty-kNN distance to plot in the morning.
8. **Cumulative vs Markovian archive as a one-flag ablation.** Two overnight arms, same seed; pairwise LLM judge over top-15 of each (AutoRanker pattern) for the morning result (exp 08).

Practical: everything resumable via per-round snapshots; budget scales as rounds × (N sessions + K·N reviews + N/L meta-reviews).

## WHY / HOW / WHAT
- **WHY:** hypothesis hunting over a dataset is open-ended and cumulative; independent agents converge on the same few findings, so discovery should be modelled as a *social* process (P §1-2; Hong & Page 2004).
- **HOW:** 16 LLM-generated personas (six fixed stances + adaptive expertise + private memory) each run a free-form ReAct session per round, find collaborators via a citation-weighted registry, write a templated report with retrieved-only citations, get double-blind K=2 reviews, a tool-less meta-reviewer runs L=4 tournaments; top fraction enters a shared archive whose citations update reputation; 40 rounds.
- **WHAT:** on TCGA KIRC/DLBC/PAAD, top-25 findings rated more novel and higher quality than an equal-budget independent baseline, no duplicates, broader gene coverage, outward-exploring trajectories, higher scores for collaborative outputs, three case studies re-deriving or anticipating published results — all unvalidated hypotheses, one rater, one backbone, genomics only, no cost reported, no round-over-round curve.
