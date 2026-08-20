---
name: bgpdd-discovery
description: Phase 0 of the Prompt-Driven Development SOP (Global Context Discovery). Uses Iris, Scout, and Echo to research global tech stacks, reverse-engineer legacy QA, and map out APIs before detailed feature planning begins.
trigger: /bgpdd-discovery
---

# End-to-End Multi-Agent PDD: Global Discovery (bgPDD-Discovery)

Coordinates the discovery squad (Iris, Scout, Echo) to map global project context, reverse-engineer undocumented features, and extract legacy QA workflows. Output: the **Tier-1 knowledge base** under `.docs/summary/`, which `/bgpdd-plan` consumes.

---

## Path Resolution

`{PLUGIN_ROOT}` = the plugin's `skills/` directory (this skill's base directory is provided to you); personas live at `{PLUGIN_ROOT}/../agents/`. Every other path rule — list-before-reference, and the base-persona injection guard — has ONE home: `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md`, **Path Resolution** (inside your mandatory first read).

---

## 1. Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Phase 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.

Below: this pipeline's refinements on that contract only.

- **Strict Delegation — this pipeline's agents**: Iris (Phase 1), Scout (Phase 2), Echo (Phase 4). NEVER roleplay the discovery work yourself.
- **Concurrency**: the Scout fan-out is the canonical parallel case — launch independent Scouts in a single message.
- **Incremental persistence**: emphasize the contract's rule in every discovery brief — a research-heavy agent that defers its first write loses the entire run.
- **Upgraded Chain-of-Thought**: before every phase transition, explicitly verify the required artifact exists.
  - *Format*: "Thinking: Phase X requires Y. Checking `.docs/summary/...`... File exists. Proceeding."
- **Global Context Scope (Architectural Rule)**: discovery agents perform **project-scope** repository analysis and MUST write under `.docs/summary/` (e.g. `.docs/summary/context.md`). NEVER a per-enhancement feature directory (`.docs/{project-name}/`) — that is Tier-2, owned by `bgpdd-plan`.

## 2. Global Error Recovery

**The error-recovery skeleton lives in the Orchestrator Contract (§2)** — halt-and-escalate triggers, the circuit breaker you pass to every agent, no-nested-delegation, incremental persistence, context checkpoints, and 2-round bounded autonomous rejection. Read it there; it is not restated here.

This pipeline's only refinement: it has no `orchestrator-state.json` — checkpoint your own state to a scratch file if your context grows large.

---

## 3. Folder Structure (Tier-1 Knowledge Base)

Everything lands under `.docs/summary/`, indexed by durable feature id (`{feature}`, e.g. `slide`) so the map is reusable across future enhancement cycles. A file here that already exists: the responsible agent flags it, and you ask the user whether to update or keep it.

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

### Phase 1: Project Context Discovery (Iris)
- **Delegated Agent**: **Iris** (Observer). **Trigger**: execute this phase first.
- **Workflow**:
  1. **Target Scope (Orchestrator, before delegating)** — a feature can span several microservice repos. Establish and record up front: (a) the target repository or repositories, (b) the working branch, (c) each repo's local path for multi-repo. Ask the user if context does not make this clear; NEVER guess.
  2. Delegate to **Iris**, passing her the Target Scope.
  3. Instruct her to scan the repository/repositories and determine the global tech stack and overall project context (e.g. 2D Godot game vs Next.js web app).
  4. Instruct her to record the Target Scope (repo set + local paths) alongside her tech-stack findings in `.docs/summary/context.md`, writing the file herself; the Orchestrator MUST NOT create it on her behalf. File already exists → she notes it in her handoff so you can ask the user whether to update it.
  5. Read her returned handoff before proceeding.

### Phase 2: Feature Auto-Scouting (Orchestrator → Scouts)
- **Delegated Agent**: **Scout** (Research Worker). **Trigger**: after Phase 1.
- **Workflow**:
  1. YOU (the Orchestrator) MUST ask the user for the durable **feature id** (`{feature}`, e.g. `slide`) and whether `.docs/summary/{feature}/` already exists (if so: refresh it, or reuse as-is?).
  2. YOU MUST ask which specific microservices or APIs contain fragments of the feature. Cross-reference each against the Phase 1 Target Scope to confirm its repo and local path; ask the user to clarify any API that does not map cleanly to a repo in scope. **Discovery Aid**: if the user does not know, offer to delegate a single Scout to run a cross-repo search and surface the feature's footprint first.
  3. **CRITICAL HALT**: stop generating your response here and await the user's explicit reply. NEVER hallucinate a list of APIs; NEVER proceed to step 4 without the user's input.
  4. Group folders forming a Factory pattern with their implementation and base projects (e.g. `Storage`, `Storage.BlobStorage`, `Storage.Factory`) into a single Scout assignment; one Scout per remaining folder/API. Delegate all Scouts in parallel, in a single batch. Tell each its `{feature}`, its assigned `{api}`(s), and which repo (and local path) those live in per the Target Scope.
  5. Instruct each Scout to deep-dive its API(s), map the feature fragments, and write findings — including that API's own execution-path detail — to ONLY its own `.docs/summary/{feature}/{api}.md`, writing the file itself; the Orchestrator MUST NOT create these. Scouts NEVER write a shared feature-level file (`overview.md`, `QA/code-workflow.md`): that synthesis is Echo's in Phase 4, which keeps two Scouts off one file.
  6. Read all Scouts' returned handoffs before Phase 3.

### Phase 3: Scout Synthesis Gate (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this check directly.
- **Workflow**:
  1. Read each per-API `.docs/summary/{feature}/{api}.md` and confirm every named API has a corresponding, non-empty map. An assigned API missing its file → re-delegate that single Scout (subject to §2's error-recovery bound).
  2. NEVER hand-author `overview.md` or `code-workflow.md` yourself — the cross-API synthesis is Echo's job in Phase 4. This phase only verifies the per-API inputs are complete before Echo consumes them.
  3. Proceed to Phase 4.

### Phase 4: Feature Synthesis & Legacy QA Extraction (Echo)
- **Delegated Agent**: **Echo** (Legacy QA Analyst). **Trigger**: after Phase 3. **Skip if no per-API `.docs/summary/{feature}/{api}.md` files exist.**
- **Workflow**:
  1. Delegate to **Echo**, telling her the `{feature}`.
  2. Instruct her to read ALL per-API `.docs/summary/{feature}/{api}.md` files the Scouts wrote in Phase 2.
  3. Instruct her to synthesize, in this order, within the same pass:
     a. `.docs/summary/{feature}/overview.md` — the cross-API consolidation: which API owns what, cross-service call flow, integration seams, links to each `{api}.md`.
     b. `.docs/summary/{feature}/QA/code-workflow.md` — Mermaid sequence diagrams and step-by-step execution paths across the services.
     c. `.docs/summary/{feature}/QA/manual-testing.md` — reverse-engineered manual test cases, using the `code-workflow.md` she just produced, per her persona.
  4. Read her returned handoff before Phase 5.

### Phase 4b: Runtime Environment Recipe (Orchestrator + user, main session)
- **Delegated Agent**: None — interactive, main session. Echo produced the material in Phase 4; this step turns it into a recipe with the user, and a delegated agent cannot pause to ask which device to test against.
- **Purpose**: record **how this feature is actually stood up locally**, once, durably — so no future build, verify, or bugfix run re-derives it at runtime. This is the brownfield entry point for the environment manifest; greenfield projects get theirs at `/bgpdd-plan` Phase 3.6, and a project with neither falls through to `/bgpdd-build` Phase 0.
- **Format authority**: the **Environment Manifest** section of `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` — its blocks, unchanged. Write to `.docs/summary/{feature}/QA/runtime-environment.md`.
- **Workflow**:
  1. **Draft from what discovery already found.** Read `.docs/summary/{feature}/overview.md` + `QA/code-workflow.md` (the services the feature spans, the order its calls flow in) and `.docs/summary/context.md` (repo set, local paths). Propose the bring-up sequence, the service table and the repointing map — as a **proposal**, NEVER as settled fact.
  2. **Ask the user for what no artifact can tell you, one question at a time**: the steps that are not "start a service" (build which project, copy which output where, install or register which agent, run which one-off function, connect which service to which); the target device or machine names as they appear in the product's own list; the test login's username and where its password comes from (**never the password itself**); any local port differing from the default.
  3. **Scope each step.** Fill the `Needed for` column so a later run can select a subset — an icon fix brings up the web app alone, not the whole estate. Ask the user to sanity-check the smallest realistic scope ("if someone changed only the UI here, what would they need running?"): full-estate is the default answer, and the one that makes the recipe too expensive to follow.
  4. **Record the capability inventory** the feature's surfaces require, each with the cheapest action that proves it exists. Do **NOT** preflight here — discovery maps, and the estate a future run needs may not be installed on this machine today. The halt on a missing capability belongs to `/bgpdd-plan` Phase 3.6 and `/bgpdd-build` Phase 0, which know what is about to be built.
  5. The user confirms the file before you proceed. `runtime-environment.md` already exists from a prior discovery run → flag it and ask refresh-or-keep (§3's rule for every Tier-1 file).

### Phase 5: Session Learning Offer (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this phase directly.
- **Workflow**:
  1. Discovery is global-tier and runs outside any epic: no `.docs/{project-name}/` exists, so there is no game tape to append to and no end-of-epic Forge run will ever see this session's evidence. Offer the user an on-demand **`/bgpdd-learn`** run now, while that evidence is still alive (Did Iris miss tech-stack details? Did a Scout struggle to map its API?).
  2. User declines → summarize any run friction in your closing message; NEVER delegate Forge.
  3. The pipeline is complete. Instruct the user to open a new chat session and run `/bgpdd-plan` for feature-level planning — it consumes the `.docs/summary/` knowledge base you just built.
