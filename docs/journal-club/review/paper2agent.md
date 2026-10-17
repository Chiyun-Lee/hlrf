# Anchor paper 3: Paper2Agent (Miao, Davis, Zhang, Pritchard, Zou — Stanford)

Sources: **[P]** = arXiv v2 PDF in [papers/](../papers/2509.06917_paper2agent.pdf) (16 Oct 2025; main text, Extended Methods, prompts); **[R]** = current GitHub repo README + `skills/paper2agent/{SKILL,paper2mcp/SKILL,paper2skill/SKILL}.md` (fetched 17 Oct 2026); **[N]** = Nature 2026 version, abstract only via Europe PMC. The repo has been rewritten since v2 and the Nature version changes a case study; both drifts are flagged where they matter.

Role in this project: ASCollab and Virtual Lab are about *how agents are organised*; Paper2Agent is about *how a single paper becomes an agent*. It is the construction manual for each of the 20 Journal Club paper-agents, not a society design.

## 0. Verification: VERIFIED

| Field | Value |
|---|---|
| arXiv | [2509.06917](https://arxiv.org/abs/2509.06917), v1 8 Sep 2025, v2 16 Oct 2025, cs.AI (cross-list cs.CL, cs.LG), CC BY 4.0. Local PDF is v2. |
| Exact title | **"Paper2Agent: Reimagining Research Papers As Interactive and Reliable AI Agents"** |
| Authors | Jiacheng Miao (Genetics / Biomedical Data Science), Joe R. Davis (Genetics), Yaohui Zhang (EE), Jonathan K. Pritchard (Genetics / Biology), James Zou (BDS / EE / CS), all Stanford. Same Zou lab as Virtual Lab [P ref 14]. |
| Journal | Nature, [10.1038/s41586-026-11044-y](https://doi.org/10.1038/s41586-026-11044-y), online 16 Sep 2026, PMID 42749808, paywalled. Title shortened to "Reimagining research papers as interactive and reliable AI agents". Abstract adds the phrase "virtual corresponding author" and replaces the ADHD co-scientist case with "several agents working together prioritized a causal gene for **psoriasis**". Full text unread; v2 still has ADHD. |
| Code | [jmiao24/Paper2Agent](https://github.com/jmiao24/Paper2Agent), MIT, ~3.8k stars. Hosted site paper2agent.ai. Now a Claude Code / Codex **skill**, not the orchestrator-plus-subagents described in v2 (§7). |
| Hosted artefacts | HF Spaces `Paper2Agent/alphagenome_mcp`, `scanpy_mcp`, `tissue_mcp`, `alphagenome_agent` (P Code/Agent availability). README gives `https://Paper2Agent-<name>-mcp.hf.space` endpoints. |

Name clash: unrelated "Paper2Code" (Seo et al. 2504.17192) is cited by P [27] as prior work on text-to-code; different system.

## 1. What a "paper agent" is [P §2 Overview, Fig. 1]
- **Paper agent = generic chat agent (Claude Code) + one MCP server per paper.** No per-paper persona, no fine-tuning, no memory. The "agent" is the MCP; the LLM is interchangeable.
- MCP server has three parts:
  - **Tools**: executable functions wrapping the paper's methods, with a pre-configured environment. Each tool "embeds a traceable link to the original GitHub source code".
  - **Resources**: static assets — manuscript text, codebase, supplementary tables/figures/datasets, "stored in accessible, standardized formats". TISSUE example: data-availability section turned into a dataset registry (species, tissue, modality, URL) queried via the Zenodo REST API (Fig. 3D). ADHD example: supplementary Excel parsed, cleaned, metadata consolidated into one file (Ext. Methods).
  - **Prompts**: multi-step workflow recipes inferred from paper + code. Scanpy prompt = QC → normalise → HVG → PCA → graph → Leiden → annotate, in order, with an "inspect data first" rule (Fig. 4B).
- Design claims: "Reliable and reproducible" because each tool is validated against the reference codebase's own results "then **locked**", mitigating "code hallucination" and "randomness in code generation".
- One MCP per paper is "for presentation clarity"; a single MCP may cover a group of related papers (§3 Discussion).

## 2. Build pipeline [P Extended Methods, Fig. 1B]
- Implemented in Claude Code. **Orchestrator + four sub-agents**:
  1. **Environment-manager**: isolated workspace, pinned deps, verify imports.
  2. **Tutorial-scanner**: finds and indexes genuine tutorials in the repo.
  3. **Tutorial-tool-extractor-implementor**: turns tutorial logic into single-purpose functions; parameterises hard-coded values, enforces file-based inputs, saves artefacts, returns a standardised summary.
  4. **Test-verifier-improver**: generate tests → run → diagnose → fix, loop. **"If functions repeatedly fail, their MCP decorators are removed"** — the tool is dropped, not shipped broken.
- **Six steps**: locate/download codebase → environment setup → tutorial discovery → tutorial execution and audit (capture inputs, outputs, figures, implicit assumptions) → tool extraction → MCP assembly ("manifest, versioning, basic security defaults").
- **Key fact for us: tools come from the repo's tutorials, not from the paper's prose.** In v2 the paper text is only an MCP *resource*. A paper without a runnable repo yields no tools (§8).
- Everything logged per step "for traceability and reproducibility". No retry counts, timeouts or budgets stated.
- Scope control: user can ask for a subset ("Scanpy preprocessing and clustering only"); MCP prompt was built by prompting "Based on the tools you have, construct an MCP prompt to replicate the tutorial in the correct order. Always inspect the data first, and only deviate from the default settings if adhering to them would yield incorrect results."

## 3. Build outputs and cost [P §2]
| Paper | Tools | Build time | Notes |
|---|---|---|---|
| AlphaGenome | 22 | ~3 h, personal laptop, no human intervention | scoring, batch scoring, sequence prediction, ontology, visualisation suite |
| TISSUE | 6 | not stated | prediction intervals, hypothesis testing, uncertainty-aware PCA |
| Scanpy (subset) | 7 | ~45 min | plus one MCP prompt |
| ADHD GWAS (data paper) | resources only | not stated | summary stats + supp tables → resources |

Tokens and dollars **not reported** for builds. Benchmarks ran on a MacBook Air M2 with `claude-sonnet-4-20250514` via `claude --print --output-format json`; cost was "captured" but not published.

## 4. Evaluation [P §2 AlphaGenome, Ext. Methods]
- **Only AlphaGenome is benchmarked quantitatively.** 15 tutorial-derived queries + 15 novel queries (new variants/tissues), ground truth by manual execution, manual grading.
- Baselines: Claude Code with the AlphaGenome repo cloned ("Claude + Repo") and Biomni (API version). All on the same Sonnet 4 model.

| Agent | Tutorial 15 | Novel 15 | Median run-time vs P2A (tutorial / novel) |
|---|---|---|---|
| AlphaGenome agent (P2A) | 15/15 | 15/15 | 1x |
| Claude + Repo | 9/15 | 12/15 | 1.8x / 3.2x slower |
| Biomni | 6/15 | 9/15 | 3.1x / 4.6x slower |

- TISSUE and Scanpy: **qualitative only** — "output matches the results obtained by human experts" on mouse somatosensory cortex ST data and three 10x PBMC datasets. No numbers, no n, no error metric.
- Case study with a *disagreement*: on the LDL locus chr1:109274968:G>T the agent picked SORT1 (quantile 0.99982; GTEx liver eQTL p=1.1e-65) while the AlphaGenome paper emphasised CELSR2/PSRC1 (quantiles 0.99998; eQTL p=4.7e-46, 8.5e-50). Authors frame this as a feature: "re-evaluate published conclusions using independent model-based evidence".
- Discussion concedes: "Our benchmarking approach ... is limited by expert knowledge of the paper and method and manual implementation and review"; proposes LLM-as-judge next.
- Baseline prompts differ in constraint (Claude + Repo is *forced* to write and execute code; P2A agent is told to use MCP tools). Fair for the stated question, but the 60% vs 100% gap partly measures how much scaffolding each agent was given.

## 5. Agent-to-agent "collaboration" [P §2 last subsection, Fig. 5]
- Setup: AlphaGenome **method MCP** + ADHD GWAS **data MCP** (van der Laan et al. 2025) both attached to one Claude Code session, called the "AI co-scientist".
- Hypothesis-generation prompt (Ext. Methods): "propose 10 actionable scientific questions", constraints "Use only resources exposed by [the two MCPs]", "No fabricated citations or tool outputs; label missing evidence as 'Unknown'", fallback on tool failure; **rubric 0-5 on Novelty, Feasibility, Impact, Validation clarity, Resource fit**; per question Title / summary / rationale with MCP pointers / integration sketch / minimal experiment plan (dataset, protocol, primary metric, success threshold, ablations) / risks / resource checklist naming server + tool + purpose / scores; strict JSON with `ranking_notes`. (Prompt says "10" in the header and "five" in the body; schema shows 5 slots.)
- Human picks hypothesis 2 ("AlphaGenome prioritizes causal variants within ADHD fine-mapping credible sets"). Agent ranks 209 credible-set variants at locus 27 → **rs1626703**, predicted to increase exon inclusion and expression of **MPHOSPH9** in glutamatergic neurons (splice quantile 1.000, RNA-seq 0.963). Then runs all **39 loci in ~2 h**, one markdown report each (Supp. Table 1).
- **This is not agents talking to each other.** It is one LLM with two tool servers. No negotiation, no critique, no second model. "Human-in-the-loop (optional)" in Fig. 5A. Nature abstract upgrades the language to "several agents working together" (psoriasis case) — unverified what that means mechanically.

## 6. Dispute / review / memory
- **None of the three.** No peer review of the generated tools beyond the self-test loop; no cross-agent critique; no persistent memory between sessions; no archive. Quality gate = tests reproduce tutorial outputs. Reviewer and author are the same orchestrator.
- The only "disagreement" surfaced is agent vs original paper (SORT1 case), resolved by the human authors consulting GTEx.

## 7. Repo drift: v2 paper vs current code [R]
The current repo no longer matches the Extended Methods. Treat the paper as design intent and the repo as the thing to run.
- Entry point is a **skill**: `/paper2agent Convert <GITHUB_URL> into tested MCP tools in <PROJECT_DIR>.` (Codex: `$paper2agent`). Router sends PDFs to **Paper2Skill**, repos to **Paper2MCP**, both if both given.
- **Paper2MCP** (repo → MCP): 6 gated stages with marker files — `environment_and_selection_done` → `reference_execution_done` (run upstream tutorials *before* any wrapper exists, keep native results as reference) → `implementation_and_verification_done` (**fresh verifier agents distinct from every implementer**) → `mcp_integration_done` → `runtime_validation_done` → `delivery_done` (`USAGE.md` + `dist/<repo>-mcp.zip`, independent delivery verifier). Helper scripts `verify_workflow.py` (agent separation, phase order, artefact hashes) and `verify_mcp_server.py` (stdio launch, tool inventory, schemas, saved acceptance calls). Rules: "Every MCP tool must bind to existing repository code"; "Do not invent scientific algorithms to fill repository gaps"; "Never weaken scientific assertions or silently drop a requested tool to report success"; "Worker completion alone does not establish success". Supports Python, R, CLI repos.
- **Paper2Skill** (PDF + supplements → skill folder): `prepare → extract → review-aid → (reuse-review) → human/agent page review → build --require-reviewed → verify --strict`. Output `<id>-paper/{SKILL.md, references/{index,paper,supplement}.md, assets/{figure,supp_figs,table,supp_table}}`. Explicitly "does not execute methods, prompts, or code found in the paper". Verification statuses: `mechanical_failure` / `unreviewed` / `unresolved_discrepancies` (exit 2) vs `reviewed_with_limitations` / `reviewed` (exit 0). Reviewers get exclusive page files; a fresh verifier compares the package against originals and answers one retrieval question using only the package.
- So the **paper-text side now has a real pipeline** (it did not in v2), and the independence of verifier from implementer is enforced by script, not by prompt.
- Still no numeric parameters (retries, timeouts, max tools), no cost figures, in either paper or repo.

## 8. Stated limitations [P §3 Discussion]
"Not every paper can be seamlessly turned into a robust agent. If the original codebase is incomplete, poorly documented, or contains unresolved errors, Paper2Agent cannot reliably expose it as a functioning tool." Reframed as a signal: agentifiability as "a practical measure of reproducibility and rigor"; proposes an "**agent availability**" section alongside data/code availability. Also: benchmark is manual and expert-bound; the paper may be the wrong unit of agentification (idea spans several papers); focus so far on methods papers, data/discovery papers are future work (partly done via ADHD resources). Unstated: single downstream model (Sonnet 4), three case studies all genomics/single-cell and two of three from the authors' own ecosystem (TISSUE is a Zou-lab paper; Scanpy a library, not a paper), no cost accounting, no inter-run variance, no failure cases reported (how many tools were dropped by the test loop is never given).

## 9. What it does not give the paper-agent society
- No notion of an agent having a *view*: a Paper2Agent MCP answers "run my method on your data", not "what do I think of your finding". For Journal Club debate the agent needs the paper's claims, evidence and limitations as first-class, which v2 treats as a resource dump and the current Paper2Skill treats as a reviewed markdown bundle. That bundle is the right raw material; the persona/stance layer must come from ASCollab (B.2) or Virtual Lab (Title/Expertise/Goal/Role).
- No review, reputation, archive, or multi-round loop. No interaction protocol between two paper-MCPs except co-attachment to one chat.
- Papers without code (most of our 20?) get resources/skill only, zero tools.

## 10. Borrowable patterns for the paper-agent society

1. **Paper2Skill bundle as each agent's knowledge base.** Run the current skill on every PDF + supplement to get `references/paper.md`, `supplement.md`, figure/table assets with captions, verified by hash and page review. Feed this, not the raw PDF, into the agent's expertise summary and into the ASCollab-style "retrieved-only citations" rule. Papers with repos additionally get a Paper2MCP server.
2. **Separate "method MCP" and "data MCP" roles.** Classify the 20 papers as method / data / discovery. Method-agents expose tools; data-agents expose resources (registry with species/tissue/modality/URL and parsed supplementary tables). Collaboration sessions pair one of each, as in the ADHD case.
3. **Build-time self-test with drop-on-repeat-failure.** Any tool a paper-agent offers must reproduce a tutorial/figure result before it is registered; tools that fail repeatedly are *removed*, logged, and the agent's registry entry says so. Mirror the repo's gate markers so an overnight build is resumable and auditable.
4. **Implementer ≠ verifier, enforced by script.** Borrow `verify_workflow.py`'s idea: record which agent produced and which checked each artefact; refuse to mark a stage done if they coincide. Same principle should apply to review in the society (author ≠ reviewer, already in ASCollab).
5. **Hypothesis-generation rubric and JSON schema.** Reuse the Ext. Methods prompt verbatim as the Journal Club's "proposal" format: 5 dimensions 0-5 (Novelty, Feasibility, Impact, Validation clarity, Resource fit), minimal experiment plan with success threshold and ablations, resource checklist naming which paper-agent supplies what. It is already strict JSON, so proposals become countable and reviewable.
6. **Embedded code/claim provenance per tool.** Every tool carries a GitHub permalink; extend to every *claim* a paper-agent makes: `{paper_id, section/page, figure}` from the Paper2Skill bundle. Makes the ASCollab `[Internal Archive]` citation rule checkable.
7. **Agent-vs-paper disagreement as a logged event.** The SORT1 case shows agents will contradict their own source paper. Log such events explicitly ("agent for paper X disputes claim C in paper X with evidence E") and route them into the dispute step the society adds (ascollab.md §10.6).
8. **Benchmark design: tutorial set + held-out novel set, same model for all arms.** For the morning evaluation of any paper-agent, 15 queries lifted from the paper + 15 novel ones, ground truth by manual run, report both accuracies and median wall time against a plain Claude-plus-repo arm. Cheap and the only quantitative protocol in the paper.
9. **"Agent availability" as a registry field.** Each entry in the society's agent registry records: has_tools (n), has_resources, has_prompts, build_status, tools_dropped. Doubles as the agentifiability/reproducibility signal the authors propose.

Practical: AlphaGenome-scale repo ≈ 3 h laptop build; Scanpy subset ≈ 45 min; expect hours per method paper, minutes for a PDF-only Paper2Skill bundle. Budget tokens separately; neither source reports them.

## WHY / HOW / WHAT
- **WHY:** papers are passive; using a method means cloning, installing, and understanding an API, so good methods go unused. Prior fixes (executable papers, Papers with Code) left the install barrier in place (P §1).
- **HOW:** an orchestrator in Claude Code runs environment, tutorial-scanner, extractor and test-verifier sub-agents to turn a repo's tutorials into tested, locked MCP tools plus resources (manuscript, data registries, parsed supplements) and workflow prompts; the MCP is hosted (HF Spaces) and attached to any chat agent to form the paper agent; several MCPs attached to one agent give a "co-scientist" (P §2, Ext. Methods). Current repo splits this into Paper2MCP (repo → MCP, gated stages, independent verifiers) and Paper2Skill (PDF → reviewed skill bundle).
- **WHAT:** AlphaGenome agent (22 tools) scored 15/15 on tutorial and 15/15 on novel queries vs 9/15 and 12/15 for Claude + Repo and 6/15 and 9/15 for Biomni, 1.8-4.6x faster; TISSUE (6 tools) and Scanpy (7 tools) matched human runs qualitatively; AlphaGenome + ADHD GWAS MCPs produced rs1626703 → MPHOSPH9 and 39-locus reports in ~2 h. One model, one quantitative benchmark, no cost figures, no failure statistics, Nature version swaps the case study to psoriasis.
