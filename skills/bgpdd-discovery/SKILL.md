---
name: bgpdd-discovery
description: Phase 0 of the Prompt-Driven Development SOP (Global Context Discovery). Uses Iris, Scout, and Echo to research global tech stacks, reverse-engineer legacy QA, and map out APIs before detailed feature planning begins.
trigger: /bgpdd-discovery
---

# End-to-End Multi-Agent PDD: Global Discovery (bgPDD-Discovery)

This Standard Operating Procedure (SOP) coordinates the discovery squad (Iris, Scout, Echo) to map out global project context, reverse-engineer undocumented features, and extract legacy QA testing workflows. Its output is the **Tier-1 knowledge base** under `.docs/summary/`, which `/bgpdd-plan` then consumes.

---

## Path Resolution

Skill and agent paths in this document use `{PLUGIN_ROOT}` as a placeholder for the plugin's `skills/` directory. When this skill is invoked, its base directory is provided to you; `{PLUGIN_ROOT}` is that `skills/` directory (the agents live at `{PLUGIN_ROOT}/../agents/`). List files to confirm a path exists before referencing it.

`base-persona.md` resolves at `{PLUGIN_ROOT}/agent-squad/base-persona.md`, never under `{PLUGIN_ROOT}/../agents/` — the injection rule and its rationale live in the Orchestrator Contract §1 (Delegation Discipline). Verify the path resolves before delegating.

---

## 1. Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Phase 0, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.

The sections below carry ONLY this pipeline's refinements on top of that contract.

- **Strict Delegation — this pipeline's agents**: Iris (Phase 1), Scout (Phase 2), Echo (Phase 4). You MUST NOT roleplay the discovery work yourself.
  - **Concurrency matters most here**: this pipeline's Scout fan-out is the canonical parallel case — launch independent Scouts in a single message.
  - **Incremental persistence matters acutely here**: discovery agents are research-heavy and accumulate many tool calls before they have anything to say, so a deferred first write costs the entire run. Emphasize the contract's rule in every discovery brief.
- **Upgraded Chain-of-Thought**: Before transitioning between phases, you MUST explicitly verify that the required artifact exists.
  - *Format*: "Thinking: Phase X requires Y. Checking `.docs/summary/...`... File exists. Proceeding."
  - **Phase 4b → 5 is covered too, with a content contract.** `runtime-environment.md` is the one artifact here a *later* pipeline depends on to start anything, so existence alone is not enough: the file must also **name at least one service start command and at least one readiness check**. A recipe with neither is a heading, and `/bgpdd-build` Phase 0 discovers that months later with no one left to ask. If the user deliberately declined to produce it (Phase 4b step 5), record that skip **explicitly in your closing handoff, as user-approved** — an unrecorded skip is indistinguishable from an omission.
- **Global Context Scope (Architectural Rule)**: The discovery agents (Iris, Scout, Echo) perform **project-scope** repository analysis. Their artifacts MUST be written under `.docs/summary/` (e.g., `.docs/summary/context.md`). Never let them output to a per-enhancement feature directory (`.docs/{project-name}/`) — that is Tier-2, owned by `bgpdd-plan`.
- **Tier-1 provenance stamp — the contract this pipeline offers downstream.** Tier-1 is durable and read months later by pipelines that have no way to tell a current map from a stale one. So every Tier-1 root artifact carries, in its own header, the **repository HEAD commit sha it was derived from and the date** — Iris stamps `.docs/summary/context.md` (one sha per repo on a multi-repo Target Scope, keyed by repo name), Echo stamps `.docs/summary/{feature}/overview.md`. The stamp is read from the repo at write time, never recalled.
  - **The contract**: a downstream pipeline that reads Tier-1 compares the stamped sha against the repo's current HEAD and **warns the user on drift** — naming the artifact, its stamped sha, and current HEAD — so the reader decides whether to trust the map or re-run discovery. Drift is a warning, never a halt: an old map is usually still mostly right, and a hard failure would only teach people to skip Tier-1 entirely. Stating the rule is this pipeline's job because it produces the stamp; the consuming pipelines own their own end of it.

## 2. Global Error Recovery

**The error-recovery skeleton lives in the Orchestrator Contract (§2)** — halt-and-escalate triggers, the circuit breaker you pass to every agent, no-nested-delegation, incremental persistence, context checkpoints, and 2-round bounded autonomous rejection. Read it there; it is not restated here.

This pipeline's only refinement: it has no `orchestrator-state.json`. If your context grows large, checkpoint to `.docs/summary/{feature}/discovery-state.json` — fields `{schema, feature, phase, updated}`, nothing more. It is **discovery-private**: no downstream pipeline reads it, and none may be written to depend on it. It exists so a fresh session can tell which phase this run reached, not to carry state forward. (Before Phase 2 establishes `{feature}`, checkpoint to `.docs/summary/discovery-state.json` instead.)

---

## 3. Folder Structure (Tier-1 Knowledge Base)

Everything this pipeline produces lands under `.docs/summary/`, indexed by durable feature id
(`{feature}`, e.g. `slide`) so the map is reusable across future enhancement cycles. If a file here
already exists, the responsible agent must flag it so you can ask the user whether to update or keep it.

```text
.docs/summary/
├── context.md                     # Project-wide tech-stack context + Target Scope (Iris) — one file
└── {feature}/                     # Durable per-feature knowledge base (e.g. slide/)
    ├── overview.md                #   Synthesized cross-API overview (Echo)
    ├── {api}.md                   #   Per-API feature-fragment maps, one per API (Scout)
    └── QA/
        ├── code-workflow.md       #   Mermaid sequence diagrams & execution paths (Echo)
        ├── manual-testing.md      #   Reverse-engineered manual test cases (Echo)
        └── runtime-environment.md #   How to actually stand this feature up locally (Orchestrator + user, Phase 4b)
```

---

## 4. Detailed Pipeline Phases

### Phase 0: Fit Check (Orchestrator + user, main session)
- **Delegated Agent**: None — two questions, in the main session, before anything is delegated.
- **Why**: this pipeline **reverse-engineers an existing system**. It is brownfield-only by construction: Iris scans a stack that exists, Scouts map fragments that exist, Echo derives a baseline from behavior that exists. Pointed at an empty or greenfield repo, every agent returns a thin, confident, wrong artifact — and because those artifacts are Tier-1, they are durable, and the next three pipelines trust them.
- **Workflow**:
  1. Ask whether this repo already implements the feature under study, or is about to. **At most two questions** — if the answer is unclear, the cheapest disambiguator is to list the repo root and the primary source directory yourself. Run `python {PLUGIN_ROOT}/pipeline-tools/scripts/detect_stack.py --repo . --markdown` as a third disambiguator: an empty detection (no evidence for any stack) supports treating the repo as greenfield, but is not itself the fit-check answer — a partially-built repo can still show zero stack evidence in an empty `src/` dir.
  2. **Greenfield or empty → HALT and route to `/bgpdd-plan`.** Say plainly that there is nothing to discover yet, and that `/bgpdd-plan` already handles greenfield without this pipeline: its Pre-Flight Check skips straight to Phase 1 for a new project rather than demanding a `.docs/summary/` knowledge base, and its Phase 3.6 authors the environment manifest on the greenfield route — the same manifest Phase 4b below would have produced. Nothing is lost by skipping discovery; something is lost by running it.
  3. **Brownfield → proceed to Phase 1.** A repo that is partly built (an existing system gaining a new feature) is brownfield: discover what is there, and let `/bgpdd-plan` handle the new part.

### Phase 1: Project Context Discovery (Iris)
- **Delegated Agent**: **Iris** (Observer)
- **Trigger**: Execute after Phase 0 clears the fit check. This is the first delegated phase.
- **Workflow**:
  1. **Target Scope (Orchestrator, before delegating)**: This pipeline may target a single repo or a set of microservice repos, since a single feature can span multiple services. Establish and record, up front: (a) the target repository or repositories, (b) the working branch, and (c) for multi-repo, the local path to each repo. Ask the user if this isn't already clear from context — do not guess.
  2. **Mechanical stack detection (Orchestrator, before delegating)**: run `python {PLUGIN_ROOT}/pipeline-tools/scripts/detect_stack.py --repo . --markdown` (per in-scope repo, for multi-repo) and paste the resulting "Stacks (detected)" block into Iris's brief. This is the mechanical floor a stack-specific methodology skill's "If the project uses X" dependency-table row now checks against — a stack a scan can prove is never left to prose alone.
  3. Delegate to the **Iris** agent, passing her the established Target Scope and the pasted stack-detection block.
  4. Instruct Iris to scan the repository/repositories and determine the global tech stack and overall project context (e.g., 2D Godot game vs Next.js Web App).
  5. Instruct Iris to record the Target Scope (repo set + per-repo local paths) alongside her tech-stack findings in `.docs/summary/context.md`, and to open that file with the **provenance stamp** from §1: the date and each in-scope repo's current HEAD commit sha, read from the repo itself at write time. She must write this file herself with her file-writing tools — the Orchestrator MUST NOT create it on her behalf. If the file already exists, she must note this in her handoff so you can ask the user whether to update it.
  6. Instruct Iris to record the pasted stack-detection block verbatim as a `## Stacks (detected)` section in `.docs/summary/context.md`. She may ADD a stack she finds with her own evidence but may NEVER remove a detected one — convention #8: the detector is the mechanical floor, her judgment is the ceiling. An added stack is labeled as her own finding, distinct from the detector's entries.
  7. Read Iris's returned handoff before proceeding.

### Phase 2: Feature Auto-Scouting (Orchestrator → Scouts)
- **Delegated Agent**: **Scout** (Research Worker)
- **Trigger**: Execute after Phase 1.
- **Workflow**:
  1. YOU (the Orchestrator) MUST ask the user for the durable **feature id** (`{feature}`, e.g. `slide`) and whether a `.docs/summary/{feature}/` knowledge base already exists (if so, ask whether to refresh it or reuse it as-is).
  2. YOU MUST ask the user which specific microservices or APIs contain fragments of the feature that need to be parsed. Cross-reference against the Target Scope from Phase 1 to confirm which repo (and local path) each named API lives in; ask the user to clarify any API that doesn't map cleanly to a repo in scope. **Discovery Aid**: If the user does not know, offer to delegate a single Scout to run a cross-repo search and surface the feature's footprint for them first.
  3. **CRITICAL HALT**: Stop generating your response here and await the user's explicit reply. Do NOT hallucinate a list of APIs; do NOT proceed to step 4 without the user's input.
  4. Once the user provides the list of APIs, group folders that form a Factory pattern with their implementation and base projects (e.g., `Storage`, `Storage.BlobStorage`, `Storage.Factory`) into a single Scout assignment; assign one Scout per remaining folder/API. Delegate all the **Scout** agents in parallel, in a single batch. Tell each Scout its `{feature}`, its assigned `{api}`(s), and which repo (and local path) those live in per the Target Scope.
  5. Instruct each Scout to deep-dive its assigned API(s), map the feature fragments, and write findings to ONLY its own `.docs/summary/{feature}/{api}.md` — including that API's own execution-path detail. Scouts do NOT write any shared feature-level file (no `overview.md`, no `QA/code-workflow.md`); that synthesis is Echo's job in Phase 4, which avoids multiple Scouts racing to write the same file. Each Scout writes its own file with its file-writing tools; the Orchestrator MUST NOT create these files on their behalf.
  6. Read all Scouts' returned handoffs before proceeding to Phase 3.

### Phase 3: Scout Synthesis Gate (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this check directly.
- **Workflow**:
  1. Read each per-API `.docs/summary/{feature}/{api}.md` file the Scouts produced and confirm each named API has a corresponding, non-empty map. If any assigned API is missing its file, re-delegate that single Scout (subject to the error-recovery bound in §2).
  2. Do NOT hand-author `overview.md` or `code-workflow.md` yourself — the cross-API synthesis is Echo's job in Phase 4. This phase only verifies the per-API inputs are complete before Echo consumes them.
  3. Proceed to Phase 4.

### Phase 4: Feature Synthesis & Legacy QA Extraction (Echo)
- **Delegated Agent**: **Echo** (Legacy QA Analyst)
- **Trigger**: Execute after Phase 3. **Skip if no per-API `.docs/summary/{feature}/{api}.md` files exist.**
- **Workflow**:
  1. Delegate to the **Echo** agent, telling her the `{feature}`.
  2. Instruct Echo to read ALL per-API `.docs/summary/{feature}/{api}.md` files written by the Scouts in Phase 2.
  3. Instruct Echo to synthesize, in this order, within the same pass:
     a. `.docs/summary/{feature}/overview.md` — the cross-API consolidation: which API owns what, cross-service call flow, integration seams, links to each `{api}.md`. It opens with the **provenance stamp** from §1 — the date and the HEAD commit sha of each repo the feature spans, read at write time, not copied from `context.md` (Iris may have run against an earlier commit).
     b. `.docs/summary/{feature}/QA/code-workflow.md` — Mermaid sequence diagrams and step-by-step execution paths across the services.
     c. `.docs/summary/{feature}/QA/manual-testing.md` — reverse-engineered manual test cases, using the `code-workflow.md` she just produced, per her persona.
  4. Read Echo's returned handoff before proceeding to Phase 5.

### Phase 4b: Runtime Environment Recipe (Orchestrator + user, main session)
- **Delegated Agent**: None — interactive, main session. Echo produced the material in Phase 4; this step turns it into a recipe with the user, and a delegated agent cannot pause to ask which device to test against.
- **Purpose**: record **how this feature is actually stood up locally**, once, durably — so no future build, verify, or bugfix run has to re-derive it at runtime. This is the brownfield entry point for the environment manifest; greenfield projects get theirs at `/bgpdd-plan` Phase 3.6, and a project with neither falls through to `/bgpdd-build` Phase 0.
- **Format authority**: the **Environment Manifest** section of `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` — its blocks, unchanged. Write to `.docs/summary/{feature}/QA/runtime-environment.md`.
- **Workflow**:
  1. **Draft from what discovery already found.** Read `.docs/summary/{feature}/overview.md` and `QA/code-workflow.md`: they name the services the feature spans and the order its calls flow in. Read `.docs/summary/context.md` for the repo set and per-repo local paths. From these, propose the bring-up sequence, the service table, and the repointing map — as a **proposal**, never as settled fact.
  2. **Ask the user for what no artifact can tell you**, one question at a time: the steps that are not "start a service" (build which project, copy which output where, install or register which agent, run which one-off function, connect which service to which), the target device or machine names as they appear in the product's own list, the test login's username and where its password comes from (**never the password itself**), and any local port that differs from the default.
  3. **Scope each step.** Fill the `Needed for` column so a later run can select a subset: an icon fix should bring up the web app alone, not the whole estate. Ask the user to sanity-check the smallest realistic scope — "if someone changed only the UI here, what would they need running?" — because the full-estate answer is the one people give by default and the one that makes the recipe too expensive to follow.
  4. **Record the capability inventory** the feature's surfaces require, each with the cheapest action that proves it exists. Do **not** preflight here — discovery is a mapping pipeline, and the estate a future run needs may not be installed on this machine today. The halt on a missing capability belongs to `/bgpdd-plan` Phase 3.6 and `/bgpdd-build` Phase 0, which know what is about to be built.
  5. The user confirms the file before you proceed. If `runtime-environment.md` already exists from a prior discovery run, flag it and ask whether to refresh or keep it — the same rule §3 applies to every Tier-1 file.

### Phase 5: Session Learning Offer (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this phase directly.
- **Workflow**:
  1. Discovery is global-tier and runs outside any epic — no `.docs/{project-name}/` exists, so there is no game tape to append to and no end-of-epic Forge run will see this session's evidence. Instead, offer the user an on-demand **`/bgpdd-learn`** run now to capture lessons (Did Iris miss any tech-stack details? Did a Scout struggle to map its API?) while this session's evidence is still alive.
  2. If the user declines, simply summarize any run friction in your closing message — do NOT delegate Forge.
  3. The discovery pipeline is complete. Instruct the user to open a new chat session and run `/bgpdd-plan` to begin feature-level planning — it will consume the `.docs/summary/` knowledge base you just built.
