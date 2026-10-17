# Anchor paper 1: The Virtual Lab (Swanson, Wu, Bulaong, Pak, Zou)

**Correction:** there is **no arXiv version**. Preprint is bioRxiv; journal version is Nature. Sections 2-8 are sourced from bioRxiv v1 full text plus the released code (Nature text is paywalled).

## 1. Verified identifiers

| Item | Value | Status |
|---|---|---|
| arXiv | — | **FAIL** (arXiv API returns 0 results) |
| Preprint | bioRxiv [10.1101/2024.11.11.623004](https://www.biorxiv.org/content/10.1101/2024.11.11.623004v1), v1, 2024-11-12, CC-BY-NC | VERIFIED |
| Preprint title | *The Virtual Lab: AI Agents Design New SARS-CoV-2 Nanobodies with Experimental Validation* | VERIFIED |
| Journal | Nature 646(8085), [10.1038/s41586-025-09442-9](https://doi.org/10.1038/s41586-025-09442-9), online 2025-07-29, print 2025-10-01, PMID 40730228, paywalled | VERIFIED ([Europe PMC](https://europepmc.org/article/MED/40730228)) |
| Journal title (differs) | *The Virtual Lab of AI agents designs new SARS-CoV-2 nanobodies* | VERIFIED |
| Code | [github.com/zou-group/virtual-lab](https://github.com/zou-group/virtual-lab), MIT; `pip install virtual-lab` | VERIFIED |

Repo has drifted from the paper: `constants.py` now defaults to `gpt-5.2`; the paper ran on `gpt-4o-2024-08-06` (`nanobody_design/nanobody_constants.py`). Cite the paper's model.

## 2. Organisation structure
Source: §Agents; [`prompts.py`](https://github.com/zou-group/virtual-lab/blob/main/src/virtual_lab/prompts.py), [`agent.py`](https://github.com/zou-group/virtual-lab/blob/main/src/virtual_lab/agent.py).

- **Every agent is four fields**: Title, Expertise, Goal, Role. System prompt is one template: `"You are a {title}. Your expertise is in {expertise}. Your goal is to {goal}. Your role is to {role}."` No other per-agent state.
- **Human hand-defines two agents**: Principal Investigator and Scientific Critic (constants in `prompts.py`).
- **PI writes the rest of the team** from a short project description, "using its own prompt as an example". Nanobody team: Immunologist, ML Specialist, Computational Biologist, plus Critic.
- **Hierarchy is one level, conversational not architectural.** PI is team lead; everyone else a peer.
- **Everyone talks to one shared transcript.** [`run_meeting.py`](https://github.com/zou-group/virtual-lab/blob/main/src/virtual_lab/run_meeting.py) keeps a single `messages` list; each turn builds `[agent.message] + messages` — swap the system prompt, replay the same conversation. No private memory, no direct addressing.

## 3. Meeting format
Source: §Meetings, §Team meeting, §Individual meeting, §Parallel meetings.

Inputs to both meeting types: Agenda (required), Agenda questions, Agenda rules, Summaries of previous meetings, Contexts, Rounds (required, "typically N=3").

**Team meeting:** opening prompt introduces lead + members, injects contexts/summaries/agenda; PI gives initial thoughts; each scientist then the Critic speaks one-by-one in human-set order; end of round the PI must "synthesize ... make decisions ... ask follow-up questions"; repeat N rounds; PI writes summary.

**Individual meeting:** team hard-wired to `[team_member, SCIENTIFIC_CRITIC]`. N≥1 → answer → critique → revise, N times.

Paper parameters: `num_iterations = 5`, `num_rounds = 3`.

**Parallel + merge:** same meeting run 5x concurrently at **T=0.8**, the 5 summaries fed into one individual meeting at **T=0.2** with `MERGE_PROMPT`, which demands provenance: "explain what components of your answer came from each individual answer and why." Paper contrasts this with majority voting. Example: 5 team-selection runs proposed 5 rosters; merge picked the consensus three and the best-worded expertise string.

52 saved transcripts across 8 workflow phases (each = 5 parallel + 1 merged, plus occasional `improved.md`).

## 4. Memory / archive
- **Only summaries propagate, never transcripts.** `load_summaries()` reads the last message of a saved discussion; injected as `[begin summary 1] ... [end summary 1]` blocks.
- **Rigid summary structure**: `### Agenda` → `### Team Member Input` → `### Recommendation` (must choose one option; may overrule members if justified) → `### Answers` (per question: Answer + Justification) → `### Next Steps`.
- **Explicit dependency graph between phases**, wired by hand in the notebook.
- **Dual persistence**: every meeting saved as `.json` (reloadable) and `.md` (auditable), both committed.

## 5. Critique mechanism
- `SCIENTIFIC_CRITIC` is a standing constant: goal "ensure ... rigorous, detailed, feasible, and scientifically sound"; role "provide critical feedback to identify and correct all errors".
- Auto-injected into every individual meeting; last speaker in each team-meeting round, before PI synthesis.
- Four jobs: suggest improvements addressing the agenda; prefer simple but demand detail; **validate strict adherence to agenda and questions**; corrective feedback. Hard boundary: "Only provide feedback; do not implement the answer yourself."
- Measured: Critic writes 21.0% of words in project-specification team meetings, ~33% in individual meetings.
- Concrete catch: flagged "random numbers as a placeholder for ESM log-likelihoods".

## 6. Human steering
- **1,596 words = 1.3%** of all words vs 122,462 (98.7%) by agents (§Analyses of Virtual Lab interactions).
- Five levers, all upstream: define PI + Critic; write agendas/questions/rules; set speaking order and N; choose which summaries feed which meeting; targeted rewrite requests (`REWRITE_PROMPT`: "rewrite ... to make the following improvements without changing anything else").
- Human injects constraints agents cannot know (real tool runtimes).

## 7. Cost / compute
- `gpt-4o-2024-08-06`; `gpt-4o-mini-2024-07-18` as `model_mini`.
- Temperatures 0.8 (parallel) / 0.2 (merge, rewrite).
- "each meeting (or a set of parallel meetings) only taking the agents about 5-10 minutes."
- **No dollar figure in the preprint.** Do not quote one.
- One optional tool: PubMed Central search, off by default.

## 8. Stated limitations (§Discussion)
1. Stale knowledge: proposed AlphaFold-Multimer not AlphaFold 3; wrote code against old function names. Fix: RAG.
2. Tool fallibility inherited (AlphaFold imperfect).
3. Prompt-engineering dependence: "Without appropriate guidance, the LLM agents can give vague answers."
4. **Decision avoidance**: "frequently said to do both until they were specifically asked to 'choose only one.'"

Repo contains ablation machinery (`ablations.ipynb`, `human_eval.ipynb`) not in bioRxiv v1 — likely added for Nature revision; unverified against published text.

## 9. Borrowable patterns for the paper-agent society

1. **Four-field agent spec, one f-string.** For papers: title = citekey, expertise = method/domain, goal = the claim it defends, role = how to argue. Generate the roster from Zotero metadata + abstract in one pass.
2. **One shared transcript, swap the system prompt.** No message bus, no inboxes. A 20-paper society is one list and a loop. Cap roster per meeting at ~5 (context grows linearly).
3. **A convener that drafts its own roster.** Give a Convener the question + library index; it emits the 3-5 papers that belong in the room.
4. **Two forums.** Team meeting = plenary dispute; individual meeting = one paper + Critic for a specific deliverable. Separate code paths, separate prompts.
5. **Engineer disagreement in one sentence.** Ship verbatim: *"If you do not have anything new or relevant to add, you may say 'pass'. Remember that you can and should (politely) disagree with other team members if you have a different perspective."*
6. **Standing Critic with hard role boundary.** Add one check: *does the claim actually appear in the cited source?*
7. **Structured summaries are the only thing that crosses a meeting boundary.** Save `.json` + `.md`. "Recommendation must choose one option" stops the archive filling with hedges.
8. **Parallel-and-merge with temperature split and mandatory provenance.** 5x at T=0.8, merge once at T=0.2, merge states which component came from which run. Scale to 3x if budget-bound.

Caution: put forcing language in agenda rules from the first run (`"choose only one"`, `"name the paper you disagree with"`).

## WHY / HOW / WHAT
- **WHY:** interdisciplinary research needs teams most groups cannot assemble; prior systems stayed in one domain or stopped before real-world validation. Claim: shift "from AI as a tool to AI as a partner."
- **HOW:** thin scaffold around one chat thread; four-string agents; PI writes the roster; team meetings (N=3, PI synthesises) and individual meetings (specialist + Critic); 5x parallel at T=0.8 merged at T=0.2; only structured summaries cross meetings; human writes 1.3% of words.
- **WHAT:** agent-specified ESM → AlphaFold-Multimer → Rosetta pipeline; 92 nanobodies assayed, >90% expressed and soluble, two with improved binding to JN.1/KP.3. Nature 646(8085), 2025.
