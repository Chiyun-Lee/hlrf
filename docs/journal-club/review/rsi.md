# Review track 1: recursive self-improvement (RSI) and cross-round improvement in agent societies

Scope: systems where an archive, memory, or population lets later rounds build on earlier ones. Window 2023-2026. Every arXiv ID was fetched from its `arxiv.org/abs/` page (title, authors, date confirmed). Full text was checked for DGM, AI co-scientist, ReST-EM and multiagent debate. No candidate failed verification. STaR (2022) excluded on date; FunSearch excluded (no arXiv ID).

Question this track answers for the Library Journal Club: **can overnight rounds of paper-agents get better, and what mechanism would make that true?**

## Core papers (13)

### 1. Darwin Gödel Machine — [arXiv:2505.22954](https://arxiv.org/abs/2505.22954)
Zhang, Hu, Lu, Lange, Clune (Sakana / UBC), May 2025.
- WHY: provable self-improvement is intractable; replace proofs with empirical validation on benchmarks.
- HOW: a coding agent rewrites its own code; every variant is kept in an archive; parents sampled by score plus child-count (quality-diversity), so all archive members keep non-zero sampling probability.
- WHAT: SWE-bench 20.0% -> 50.0%, Polyglot 14.2% -> 30.7% over 80 iterations; baseline without archive/self-modification "tapers off quickly".
- Loop: store = all generated agents + scores; select = performance x novelty (few children); feedback = child's benchmark score enters archive.

### 2. Huxley-Gödel Machine — [arXiv:2510.21614](https://arxiv.org/abs/2510.21614)
Wang, Piękos, Nanbo, Laakom, Chen, Ostaszewski, Zhuge, Schmidhuber (KAUST), Oct 2025.
- WHY: an agent's own score does not predict how good its *descendants* will be.
- HOW: clade metaproductivity (CMP) = aggregate performance of descendants; used to pick which archive node to expand.
- WHAT: beats DGM on SWE-bench Verified and Polyglot.
- Loop: store = lineage tree; select = estimated descendant productivity; feedback = descendants' scores propagate up.

### 3. AlphaEvolve — [arXiv:2506.13131](https://arxiv.org/abs/2506.13131)
Novikov et al. (Google DeepMind), June 2025.
- WHY: scale LLM-guided code evolution from single functions (FunSearch) to whole programs.
- HOW: LLMs propose code diffs; automated evaluator scores; program database feeds next prompts.
- WHAT: 4x4 complex matrix multiplication in 48 scalar multiplications; data-centre scheduling and kernel improvements; open math problems.
- Loop: store = program database + scores; select = fitness + diversity; feedback = top programs become prompt context.

### 4. Automated Design of Agentic Systems (Meta Agent Search) — [arXiv:2408.08435](https://arxiv.org/abs/2408.08435)
Hu, Lu, Clune, Aug 2024.
- WHY: hand-designed agent architectures will be outpaced by learned ones.
- HOW: a meta-agent writes new agents in code "based on an ever-growing archive of previous discoveries"; each is evaluated and appended.
- WHAT: discovered agents beat hand-designed baselines; transfer across domains and models.
- Loop: store = archive of agent code + scores; select = meta-agent reads whole archive; feedback = evaluation score.

### 5. Gödel Agent — [arXiv:2410.04444](https://arxiv.org/abs/2410.04444)
Yin, Wang, Pan, Lin, Wan, Wang, Oct 2024.
- WHY: fixed agent components cannot explore the full design space.
- HOW: self-referential agent modifies its own logic under a prompt-given objective.
- WHAT: claims continuous self-improvement on math reasoning and agent tasks (abstract-level; smaller scale than DGM).
- Loop: store = current agent code (no archive); select = the agent itself; feedback = task performance.

### 6. The AI Scientist v1 — [arXiv:2408.06292](https://arxiv.org/abs/2408.06292) and v2 — [arXiv:2504.08066](https://arxiv.org/abs/2504.08066)
v1: Lu, Lu, Lange, Foerster, Clune, Ha (Aug 2024). v2: Yamada, Lange, Lu, Hu, Lu, Foerster, Clune, Ha (Apr 2025).
- WHY: automate idea -> experiment -> paper -> review.
- HOW: v1 is a pipeline with an automated reviewer near human level; v2 removes code templates and uses progressive agentic tree search under an experiment-manager agent.
- WHAT: v2 produced a paper above average human acceptance threshold at an ICLR workshop.
- Loop: v1: prior ideas + review scores seed the next idea prompt. v2: tree of experiment nodes, best nodes expanded. No cross-run persistent archive by default.

### 7. AI co-scientist — [arXiv:2502.18864](https://arxiv.org/abs/2502.18864)
Gottweis et al. (Google), Feb 2025.
- WHY: hypothesis quality should scale with test-time compute.
- HOW: generate / reflect / rank / evolve / proximity / meta-review agents. Ranking agent runs an Elo tournament (Sec 3.3.3); meta-review agent summarises review patterns and feeds them back to generators (Sec 3.3.6).
- WHAT: AML drug-repurposing candidates validated in vitro; Elo rises with compute, "no evidence of performance saturation as measured by Elo" (Sec 4.2, Fig 4) — but Elo is auto-evaluated, not ground truth, and the paper says so.
- Loop: store = hypothesis pool with Elo; select = tournament winners; feedback = meta-review digest injected into next round.

### 8. Generative Agents — [arXiv:2304.03442](https://arxiv.org/abs/2304.03442)
Park, O'Brien, Cai, Morris, Liang, Bernstein, Apr 2023.
- WHY: believable long-horizon behaviour needs memory that accumulates and abstracts.
- HOW: memory stream; periodic reflection synthesises higher-level insights; retrieval by recency / importance / relevance.
- WHAT: 25 agents in a sandbox produce emergent social behaviour; ablations show reflection and memory each matter.
- Loop: store = memory stream + reflections; select = retrieval score; feedback = reflections become retrievable. Behavioural coherence, not task-performance improvement.

### 9. Voyager — [arXiv:2305.16291](https://arxiv.org/abs/2305.16291)
Wang, Xie, Jiang, Mandlekar, Xiao, Zhu, Fan, Anandkumar, May 2023.
- WHY: lifelong learning without gradient updates.
- HOW: automatic curriculum; iterative prompting fixes code from errors; verified programs go into an ever-growing skill library retrieved by embedding.
- WHAT: 3.3x more unique items, 2.3x longer travel in Minecraft; skills transfer to new worlds.
- Loop: store = executable skills; select = embedding retrieval; feedback = only self-verified skills are added (monotone library).

### 10. Reflexion — [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)
Shinn, Cassano, Berman, Gopinath, Narasimhan, Yao, Mar 2023.
- WHY: trial-and-error improvement without weight updates.
- HOW: after a failed trial the agent writes a verbal reflection stored in an episodic buffer and conditioned on next attempt.
- WHAT: 91% pass@1 on HumanEval vs 80% for GPT-4.
- Loop: store = reflections per task; feedback = pass/fail. Within-task, over a handful of trials.

### 11. Multiagent Debate ("society of minds") — [arXiv:2305.14325](https://arxiv.org/abs/2305.14325)
Du, Li, Torralba, Tenenbaum, Mordatch, May 2023.
- WHY: multiple instances critiquing each other should converge on better answers.
- HOW: N instances answer, read each other's answers, revise over R rounds.
- WHAT: gains on arithmetic, GSM8K, MMLU, biography factuality. Full text: "additional debate rounds above four led to a similar final performance to 4 rounds of debate".
- Loop: store = current-round answers only; no persistent memory. Saturates within ~4 rounds.

### 12. Group-Evolving Agents — [arXiv:2602.04837](https://arxiv.org/abs/2602.04837) (2026)
Weng, Antoniades, Nathani, Zhang, Pu, Wang, Feb 2026.
- WHY: tree-structured self-evolution isolates branches; experience never crosses lineages.
- HOW: the group is the evolutionary unit; agents share and reuse experience.
- WHAT: 71.0% vs 56.7% SWE-bench Verified against prior self-evolving methods.
- Loop: store = pooled group experience; select = group-level; feedback = cross-lineage sharing. Directly relevant to a "society" framing.

### 13. CORAL — [arXiv:2604.01658](https://arxiv.org/abs/2604.01658) (2026)
Qu et al. (MIT / NUS), Apr 2026.
- WHY: fixed evolutionary search rules are hand-coded; let long-running agents decide how to explore.
- HOW: multiple long-running agents explore, reflect and collaborate via shared persistent memory, asynchronously.
- WHAT: SOTA on 10 math / algorithmic / systems tasks with fewer evaluations than fixed evolutionary baselines.
- Loop: store = shared persistent memory; select = agent-driven; feedback = evaluator scores + peer reflections.

## Secondary / supporting (all verified)

| Paper | ID | Role in this scan |
|---|---|---|
| Self-Refine (Madaan et al. 2023) | [2303.17651](https://arxiv.org/abs/2303.17651) | Single-LLM generate / critique / revise; no memory across tasks. |
| ReST-EM (Singh et al. 2023) | [2312.06585](https://arxiv.org/abs/2312.06585) | Weight-level self-training; "exceeding a couple of iterations ... leads to diminishing improvement"; regression on APPS at iteration 2. |
| Agent Laboratory (Schmidgall et al. 2025) | [2501.04227](https://arxiv.org/abs/2501.04227) | Staged pipeline with human feedback per stage; no cross-run archive. |
| SciAgents (Ghafarollahi & Buehler 2024) | [2409.05556](https://arxiv.org/abs/2409.05556) | Ontological KG + multi-agent hypothesis generation/critique; single-pass. |
| HypoGeniC (Zhou et al. 2024) | [2404.04326](https://arxiv.org/abs/2404.04326) | Hypothesis bank updated with bandit-style reward; clean small-scale archive+selection loop. |
| MOOSE-Chem (Yang et al. 2024) | [2410.07076](https://arxiv.org/abs/2410.07076) | Retrieve inspirations -> compose -> rank hypotheses. |
| ShinkaEvolve (Lange, Imajuku, Cetin 2025) | [2509.19349](https://arxiv.org/abs/2509.19349) | Open-source AlphaEvolve-style; balanced parent sampling, novelty rejection. |
| Meta-Team (Hao et al. 2026) | [2605.29790](https://arxiv.org/abs/2605.29790) | Multi-agent system improves from its own execution history at agent / coordination / team levels. |
| DecentMem (Hao, Long, Zhao 2026) | [2605.22721](https://arxiv.org/abs/2605.22721) | Per-agent dual-pool memory reweighted by LLM-judge; up to +23.8% over centralised memory. |
| MAGE (Yang et al. 2026) | [2605.10064](https://arxiv.org/abs/2605.10064) | Co-evolving knowledge graph + two bandits for a frozen backbone. |
| "The Devil Behind Moltbook" (Wang et al. 2026) | [2602.09877](https://arxiv.org/abs/2602.09877) | Self-evolution trilemma; safety erodes under closed-loop evolution. |
| Survey of Self-Evolving Agents (Gao et al. 2025) | [2507.21046](https://arxiv.org/abs/2507.21046) | What / when / how taxonomy. |
| Huang et al. 2023 (counter-evidence) | [2310.01798](https://arxiv.org/abs/2310.01798) | Without external feedback, LLM self-correction "even degrades" reasoning. |
| Smit et al. 2023 (counter-evidence) | [2311.17371](https://arxiv.org/abs/2311.17371) | Multi-agent debate does not reliably beat self-consistency; hyperparameter-sensitive. |

## Synthesis

### (a) Common WHY
A frozen LLM called once has a fixed quality ceiling; the cheapest lever is *state that persists between calls* plus *a selection signal*. The discovery papers (AI Scientist, co-scientist, AlphaEvolve, CORAL) add: test-time compute should convert into result quality, which needs a loop, not a pipeline. The RSI papers (DGM, HGM, ADAS, Gödel Agent, GEA) add: the improver itself should be a target of improvement.

### (b) Divergent HOW

| Loop type | Papers | What is stored | What selects | What feeds back |
|---|---|---|---|---|
| Archive + selection (evolutionary) | DGM, HGM, AlphaEvolve, ShinkaEvolve, ADAS, GEA, HypoGeniC | Every candidate + score | Score x novelty (DGM), descendant productivity (HGM), evaluator fitness, bandit reward | Parent context for next generation |
| Reflection / memory | Reflexion, Generative Agents, Voyager, DecentMem, MAGE, CORAL, Meta-Team | Verbal reflections, skills, trajectories | Retrieval or LLM-judge reweighting | Retrieved memory in next prompt |
| Tournament / Elo | AI co-scientist | Hypothesis pool with Elo | Pairwise debate matches | Winners evolved; losers pruned |
| Meta-review | AI co-scientist, AI Scientist v1 | Digest of review patterns | — | Digest conditions all generators |
| Code self-modification | DGM, HGM, Gödel Agent, ADAS | Agent source code | Benchmark score | New agent version |
| Rounds with no persistent state | Multiagent Debate, Self-Refine | Current-round outputs only | None | Peer / self critique |

Systems with sustained multi-round gains all combine (i) an archive that never discards, (ii) non-greedy selection, (iii) an external evaluator. Systems that saturate fastest have no persistent store (debate, Self-Refine) or no external signal (intrinsic self-correction).

### (c) Does improvement compound or saturate?

For compounding:
- DGM: 20 -> 50% over 80 iterations; no-archive baseline "tapers off quickly". Strongest evidence, but single-lineage benchmark.
- HGM and GEA each beat DGM on the same benchmarks: loop design matters more than raw iterations.
- AI co-scientist: "no evidence of performance saturation as measured by Elo" — self-assessed Elo; the paper calls continued gains a projection.
- AlphaEvolve: genuinely new maths, but reports end states, not learning curves.

For saturation or regression:
- Multiagent Debate: rounds beyond 4 equal 4.
- ReST-EM: diminishing after 1-2 iterations; regression from overfitting.
- Huang et al.: intrinsic self-correction without external feedback degrades reasoning.
- Smit et al.: debate does not reliably beat self-consistency.
- Moltbook paper: closed-loop self-evolution erodes alignment (same drift mechanism, different axis).

**Net:** compounding over many rounds is documented only with a hard external evaluator (tests, benchmark, numeric objective) plus an archive with non-greedy selection. Where the signal is the model's own judgment, gains are real but front-loaded, within 2-4 rounds. No paper shows compounding on open-ended research-quality judgments with human ground truth beyond a handful of rounds.

### (d) What the Library Journal Club can borrow in 2 days

Borrowable:
1. **Never-discard archive with scores** (DGM, ADAS): every review, dispute verdict, collaboration proposal and finding from round N is stored with a score and shown (or sampled) to round N+1. The single component every compounding system has.
2. **Non-greedy selection** (DGM score + few-children bonus; ShinkaEvolve novelty rejection): a weighted sampler stops 20 agents collapsing onto one idea by round 2.
3. **Elo tournament + meta-review digest** (co-scientist): pairwise LLM-judged matches rank proposals cheaply; a one-paragraph meta-review of *why* items lost, injected into the next round, is the nearest thing to a feedback gradient without an evaluator. Expect a plateau within 3-4 rounds.
4. **Per-agent reflection buffer** (Reflexion) and a **verified-snippet library** (Voyager): verified facts, quotes with locations, and reusable queries that pass a check get added and retrieved.
5. **Shared experience across agents** (GEA, CORAL): a shared memory read by all agents beats isolated lineages on the same budget; per-agent memory (DecentMem) adds diversity if homogenisation appears.
6. **Cap rounds at ~4** for any purely LLM-judged loop (Du et al.); spend the rest of the budget on breadth (more pairs) not depth.

Not borrowable in 2 days:
- Code self-modification of the agents (DGM, HGM, Gödel Agent): needs a hard benchmark, sandboxing, 80 iterations.
- Weight-level self-training (ReST-EM): no fine-tuning budget; regresses after 1-2 iterations anyway.
- Descendant-productivity selection (HGM): lineages too shallow at 3-4 rounds.
- **Claims of compounding**: with LLM-judged scores only, the society cannot distinguish improvement from drift toward what the judge likes (Huang et al., Moltbook). If any round-over-round claim goes on stage, one small external check is needed (held-out human rating, citation-verification pass rate, or a fixed rubric scored by a different model). Otherwise say "rounds change", not "rounds get better".

## Verification summary
- 27 arXiv IDs fetched; 27 confirmed; 0 FAIL.
- Excluded: STaR (2022), FunSearch (no arXiv ID).
- Full-text checks: DGM numbers and 80-iteration count; co-scientist Elo / meta-review / "no saturation" sentence; ReST-EM diminishing returns; multiagent-debate 4-round plateau.
- Weak-evidence flags: Gödel Agent (abstract only), Meta-Team and CORAL (abstracts do not specify store/select), co-scientist Elo (self-assessed).
