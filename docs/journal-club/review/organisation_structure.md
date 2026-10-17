# Review track 2: organisation format and structure of multi-agent research systems

Scope: roles, hierarchy vs flat, topology, round format, peer review, shared archive, dispute handling, human steering. All 30 arXiv IDs checked against the abs page; none failed. Three 2026 entries verified from abstract only (noted). Anchor papers (Virtual Lab, ASCollab) have their own files: [virtual_lab.md](virtual_lab.md), [ascollab.md](ascollab.md).

Question this track answers for the Library Journal Club: **how should 20 paper-agents be wired, and what does the evidence say about debate, review and archives?**

## 1. Papers (WHY / HOW / WHAT / org structure)

### Frameworks with explicit organisational design

**MetaGPT** — Hong et al. 2023, [2308.00352](https://arxiv.org/abs/2308.00352)
- WHY: unstructured agent chatter cascades hallucinations; human teams use SOPs.
- HOW: SOPs encoded in prompts; each agent a job function (PM, architect, engineer, QA); structured intermediate documents; agents check upstream outputs.
- Org: hierarchical chain; fixed roles; mediated by structured docs, not free chat.

**ChatDev** — Qian et al. 2023, [2307.07924](https://arxiv.org/abs/2307.07924)
- HOW: waterfall chat chain; every subtask an instructor/assistant pair; stop after 2 unchanged edits or 10 rounds; only solutions carry across phases; "communicative dehallucination" = assistant asks clarifying questions before answering. Removing roles was the largest ablation drop.
- WHAT: ~148 s/run, ~23k tokens.
- Org: chain of pairs; fixed roles; artifact-mediated.

**CAMEL** — Li et al. 2023, [2303.17760](https://arxiv.org/abs/2303.17760)
- HOW: AI user + AI assistant role-play with inception prompts. Org: flat pair.

**AutoGen** — Wu et al. 2023, [2308.08155](https://arxiv.org/abs/2308.08155)
- HOW: GroupChatManager loop = select speaker → collect → broadcast; `human_input_mode` ALWAYS/NEVER, recommended ALWAYS in development then NEVER.
- WHAT: human-in-loop solved a math problem no autonomous system did.
- Org: configurable; broadcast via manager.

**AgentVerse** — Chen, Su et al. 2023, [2308.10848](https://arxiv.org/abs/2308.10848)
- HOW: recruit → decide (horizontal = ensemble; vertical = solver + reviewers to consensus) → execute → evaluate → loop.
- WHAT: with GPT-3.5, groups trailed solo on 2/3 tasks (agents swayed by wrong feedback); more math reviewers = more wrong critiques.
- Org: recruiter + evaluator over flat/vertical core; emergent roles.

### Debate, consensus, and the negative result

**Multiagent Debate** — Du et al. 2023, [2305.14325](https://arxiv.org/abs/2305.14325)
- HOW: N copies answer, see peers, revise; default 3 agents, 2 rounds.
- WHAT: Arithmetic 67→82, GSM8K 77→85, MMLU 64→71 (74 with personas). Flat beyond 4 rounds. "Stubborn" prompts give better consensus. Agents can confidently converge on a wrong answer; models attend mostly to latest turns.
- Org: flat full mesh; identical roles.

**MAD / Encouraging Divergent Thinking** — Liang et al. 2023, [2305.19118](https://arxiv.org/abs/2305.19118)
- WHY: self-reflection suffers Degeneration-of-Thought.
- HOW: affirmative vs negative debater + judge; judge discriminative each round (early stop), extractive at the 3-iteration cap; four tit-for-tat intensity levels.
- WHAT: moderate disagreement best, forced opposition polarises. **Judge bias: with mixed backbones the judge favours its own backbone** — use a distinct LLM for the judge. Tokens 2.46x CoT.
- Org: pair + judge; fixed adversarial roles.

**ReConcile** — Chen, Saha, Bansal 2023, [2309.13007](https://arxiv.org/abs/2309.13007)
- HOW: round-table of heterogeneous LLMs; peers' answers + explanations + confidences; confidence-weighted vote.
- WHAT: model diversity is the driver (+8% MATH with mixed models).

**Should we be going MAD?** — Smit et al. 2023/24, [2311.17371](https://arxiv.org/abs/2311.17371)
- WHAT: no debate protocol dominated; Medprompt was better and cheaper; highly hyperparameter-sensitive; a "devil" agent that always disagrees hurt accuracy. MAD is harder to tune, not necessarily better.

### Topology

**Mixture-of-Agents** — Wang et al. 2024, [2406.04692](https://arxiv.org/abs/2406.04692): layered proposers → aggregator; models improve when shown others' outputs even if weaker.

**DyLAN** — Liu et al. 2023, [2310.02170](https://arxiv.org/abs/2310.02170): temporal feed-forward network; Agent Importance Score selects top-k; **Byzantine early stop when >2/3 of a layer agree**; max 4-6 rounds. MMLU 70.5 at 4.4 calls vs Debate 69.3 at 12.

**GPTSwarm** — Zhuge et al. 2024, [2402.16823](https://arxiv.org/abs/2402.16823): agents as computational graphs; edges learned.

**MacNet / Scaling LLM-based Multi-Agent Collaboration** — Qian et al. 2024, [2406.07155](https://arxiv.org/abs/2406.07155)
- HOW: DAG; node = actor, edge = critic; each edge capped at 3 exchanges; **only final artifacts move along edges** (linear context growth); 1 to 2^6 nodes; chain/star/tree/mesh/layered/random.
- WHAT: **random DAGs win** (0.652) > mesh (0.632) > star (0.627); random ~52% less time than mesh; logistic "collaborative scaling law", ~16 nodes a reasonable size, saturation by ~100; critics' suggestions adopted 93.1%.

**Sparse Communication Topology for MAD** — Li, Du et al. 2024, [2406.11776](https://arxiv.org/abs/2406.11776): sparse matches or beats full mesh at much lower cost; put the strongest LLM on the most-connected node.

**Small-World Networks for MAS** — Wang, Li, Huang 2025, [2512.18094](https://arxiv.org/abs/2512.18094): uncertainty-guided rewiring adds shortcuts between agents with divergent beliefs; more stable consensus (abstract-level).

### Research-community simulations and shared archives

**AgentReview** — Jin et al. 2024, [2406.12708](https://arxiv.org/abs/2406.12708)
- HOW: 3 reviewers/paper with trait knobs, author rebuttals, AC discussion, meta-review, fixed 32% accept; ~500 ICLR papers.
- WHAT: reviewer bias shifts decisions 37.1%; AC discussion cut rating SD 27.2% (conformity); one irresponsible reviewer cut others' review length 18.7%; **knowing authors shifted decisions 27.7%**; **removing rebuttals barely changed outcomes (Jaccard 0.622) but removing numeric ratings changed them a lot (0.200)**.
- Org: AC over reviewers; mediated.

**ResearchTown** — Yu et al. 2024, [2412.17767](https://arxiv.org/abs/2412.17767)
- HOW: agent-data graph (researchers = agent nodes, papers = data nodes); TextGNN message passing: read → write → review; **reviewers = top-5 most related researchers**.
- WHAT: 1→2 agents raises paper similarity 49.0→52.7; too many unrelated domains yields vague questions.

**AgentRxiv** — Schmidgall & Moor 2025, [2503.18102](https://arxiv.org/abs/2503.18102)
- HOW: shared preprint server; labs retrieve prior agent papers by cosine similarity (top-5 + 5 arXiv).
- WHAT: MATH-500 70.2 → 78.2 with archive, plateau ~73.5 without; parallel labs faster per paper but 3x cost, duplicated experiments, and **papers with numbers not matching code**.
- Org: flat labs over a shared archive; no direct chat.

**Agent Laboratory** — Schmidgall et al. 2025, [2501.04227](https://arxiv.org/abs/2501.04227): lit review → experiment → report with human feedback per stage; feedback meaningfully improved quality.

**CycleResearcher** — Weng et al. 2024, [2411.00816](https://arxiv.org/abs/2411.00816): generator + reviewer in an RL loop; reviewer MAE 26.89% below individual humans.

**Paper2Agent** — Miao, Davis, Zhang ... Zou 2025, [2509.06917](https://arxiv.org/abs/2509.06917): paper + code → MCP server with tests; one agent per paper. The unit the Library Journal Club builds on.

**AI Co-Scientist** — Gottweis et al. 2025, [2502.18864](https://arxiv.org/abs/2502.18864): Supervisor + Generation / Reflection (6 review types) / Ranking (Elo from 1200; multi-turn debate for top pairs) / **Proximity (similarity graph, dedup, pairing)** / Evolution / Meta-review (patterns prepended to all prompts); scientists inject goals, hypotheses, reviews.

### Surveys, failure analysis, 2026 societies
- **Tran et al. 2025 survey** [2501.06322](https://arxiv.org/abs/2501.06322): taxonomy by actors, type, structure (p2p / centralised / distributed), strategy, coordination. Vocabulary.
- **MAST** Cemri et al. 2025 [2503.13657](https://arxiv.org/abs/2503.13657): 1,600+ traces; 14 failure modes in 3 categories: system design, inter-agent misalignment, task verification. Postmortem checklist.
- **Clarus** 2026 [2606.30246](https://arxiv.org/abs/2606.30246); **EinsteinArena** 2026 [2606.10402](https://arxiv.org/abs/2606.10402) (verifier + leaderboard + forum, flat, archive-mediated); **MACC** 2026 [2603.03780](https://arxiv.org/abs/2603.03780) (blackboard + incentives, position); **BLAZE** 2026 [2608.02775](https://arxiv.org/abs/2608.02775); **DySCo** 2026 [2606.01828](https://arxiv.org/abs/2606.01828) (trust-weighted sparse consensus). Abstract-only.

## 2. Comparison table

| Paper | Topology | Roles | Review | Shared memory | Dispute | Human |
|---|---|---|---|---|---|---|
| MetaGPT | hierarchical chain | fixed | upstream checks | structured docs | SOP gating | none |
| ChatDev | chain of pairs | fixed | reviewer + tester | solutions only | 2 unchanged edits / 10 rounds | none |
| AutoGen | pair / group / nested | fixed | none | chat history | manager picks speaker | ALWAYS/NEVER |
| AgentVerse | recruiter + core | emergent | vertical reviewers | env state | consensus or cap | optional evaluator |
| Du et al. | flat mesh | identical | peers | all answers | convergence | none |
| Liang MAD | pair + judge | adversarial | judge per round | history | judge, 3-round cap | none |
| ReConcile | flat | identical | confidence | prior round | weighted vote | demos |
| MoA | layered DAG | proposer/aggregator | aggregator | prior layer | aggregator | none |
| DyLAN | temporal graph | emergent | peer rating | prior layer | >2/3 early stop | none |
| MacNet | random DAG | actor/critic by edge | critic per edge | artifacts only | 3 exchanges/edge | none |
| AgentReview | AC over 3 | fixed | reviews + rebuttal + AC | reviews | meta-review, quota | simulated |
| ResearchTown | bipartite graph | from profiles | top-5 related | paper nodes | none | none |
| AgentRxiv | labs over archive | fixed lab roles | internal | preprint server | none | none |
| Co-Scientist | supervisor + tournament | functional | 6 review types | memory + meta-review | Elo debate | goals, reviews |
| Virtual Lab | PI-led | 4-field fixed | standing Critic | structured summaries | PI synthesis | agenda, 1.3% words |
| ASCollab | flat, emergent graph | 6-stance persona | K=2 blind + meta-review | registry + archive | **none** | none |

## 3. What the evidence says

- **Scale saturates early; sparse and irregular beats dense.** MacNet: ~16 nodes is a reasonable size; random DAGs beat mesh at ~52% less time. Sparse debate matches full mesh with the strongest model on the hub. Small-world shortcuts between divergent agents stabilise consensus.
- **Pass artifacts, not transcripts.** MacNet moves only final artifacts; ChatDev carries only solutions across phases; Virtual Lab passes only structured summaries; Du et al. note models attend mostly to latest turns.
- **Debate helps when** agents are "stubborn" not deferential (Du), models are diverse (ReConcile), disagreement is moderate (Liang), rounds are capped at 3-4 (Du, Liang).
- **Debate hurts when** agents are swayed by wrong critiques (AgentVerse), a "devil" always disagrees (Smit), the group converges on a shared wrong answer (Du), or the judge shares a backbone with a debater (Liang). Smit: no protocol dominated; results hyperparameter-sensitive.
- **Review structure matters more than rebuttal.** AgentReview: dropping rebuttals barely changed decisions; dropping numeric ratings did. AC discussion induces conformity; one lazy reviewer drags others; author identity shifts decisions 27.7%.
- **Shared archives compound progress but propagate errors.** AgentRxiv: +11.4% relative with archive vs plateau without; hallucinated numbers needed manual checks; parallel labs duplicate work.
- **Humans are cheap and high-leverage at checkpoints.** AutoGen ALWAYS-mode; Agent Laboratory per-stage feedback; Virtual Lab 1.3% of words at agenda + rewrite.
- **Expect failures from misalignment and missing verification** (MAST's three categories).

## 4. Recommendations for the Library Journal Club (~20 paper-agents, overnight rounds)

1. **Topology: sparse random DAG per round, not a 20-way broadcast.** ~3 critic edges per agent (MacNet); one long-range edge between the two agents with most divergent claims (small-world); strongest model on the most-connected node (sparse MAD).
2. **Unit of exchange = the Zotero note, never chat logs.** Each paper-agent's state is its note (claims, evidence, open disputes). Only notes travel along edges (MacNet, ChatDev, Virtual Lab summaries). Build each paper-agent the Paper2Agent way.
3. **Reviewer matching, 3 per note (AgentReview):** two "near" = top-2 by embedding similarity over the library (ResearchTown top-5-related rule; AgentRxiv cosine; ASCollab registry 0.8 sim + 0.2 citations); one "far" = random from a different cluster (MacNet random edge; Co-Scientist Proximity). Blind authorship. Cap ~3 reviews per agent per night; reject reviews under a length floor. Require numeric score + strengths/weaknesses.
4. **Round format = DyLAN temporal layers with early stop.** Round 1 independent reviews; round 2 author responds, reviewers may update (expect little decision change). Stop a thread when >2/3 of reviewers agree (DyLAN) or after 3-4 rounds (Du, Liang, ChatDev).
5. **Dispute protocol with a neutral judge — stands / contested / unresolved.** Opens when a reviewer scores a claim below threshold, or (ASCollab gap) when two reviewers' recommendations differ by ≥2. Run Liang's MAD: owner = affirmative, challenger = negative, *moderate* tit-for-tat; judge discriminative each round, extractive at cap of 3. Judge uses a different backbone from both debaters and sees no authorship. **stands** = judge sides with owner or a ReConcile confidence-weighted vote clears threshold; **contested** = judge sides with challenger (claim kept, counter-claim linked); **unresolved** = cap hit without verdict (no 2/3 agreement) → human morning triage. No permanent devil's-advocate role (Smit). Log every dispute as a structured record (claim, evidence, verdict, confidence).
6. **Pair collaborations, not triads.** Pairs chosen by Co-Scientist Proximity (one near pair for depth, one cross-cluster for interdisciplinarity; ResearchTown: too many unrelated domains → vague). Run as CAMEL/ChatDev instructor-assistant with communicative dehallucination. Output = one joint note with both parents linked.
7. **Archive write-back with verification tags and nightly meta-review.** Every note/verdict embedded and retrievable next round (AgentRxiv), each claim tagged verified/unverified (AgentRxiv hallucinated numbers). Co-Scientist meta-review agent summarises recurring critique patterns each night and prepends them to every agent's next prompt. Elo from pairwise dispute outcomes picks what gets reviewed first.
8. **Human steering = agenda + morning triage, ~1% of words.** Humans set the agenda Virtual Lab-style; AutoGen ALWAYS for round 1, NEVER overnight; humans adjudicate only "unresolved"; may inject their own claims (Co-Scientist). Day-2 postmortem against MAST's three categories.
