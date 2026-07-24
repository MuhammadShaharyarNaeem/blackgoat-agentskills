---
name: bgpdd-discovery
description: Phase 0 of the Prompt-Driven Development SOP (Global Context Discovery). Uses Iris and Scout to research global tech stacks, reverse-engineer legacy QA, and map out APIs before detailed feature planning begins.
trigger: /bgpdd-discovery
---

# End-to-End Multi-Agent PDD: Global Discovery (bgPDD-Discovery)

This Standard Operating Procedure (SOP) coordinates the discovery squad (Iris, Scout, Echo) to map out global project context, reverse-engineer undocumented features, and extract legacy QA testing workflows. Its output is the **Tier-1 knowledge base** under `.docs/summary/`, which `/bgpdd-plan` then consumes.

---

## Path Resolution

Skill and agent paths in this document use `{PLUGIN_ROOT}` as a placeholder for the plugin's `skills/` directory. When this skill is invoked, its base directory is provided to you; `{PLUGIN_ROOT}` is that `skills/` directory (the agents live at `{PLUGIN_ROOT}/../agents/`). List files to confirm a path exists before referencing it.

When you inject a resolved `base-persona.md` path into a delegation brief, it lives at `{PLUGIN_ROOT}/agent-squad/base-persona.md` — inside the `agent-squad` skill folder, NOT the `agents/` folder. The `agents/` folder holds ONLY persona files (`rex.md`, `alex.md`, `scout.md`, …); base-persona is a skill, not a persona. Injecting `{PLUGIN_ROOT}/../agents/base-persona.md` is the recurring defect that makes every delegated agent flag base-persona as missing. Verify the base-persona path resolves to an existing file before delegating.

---

## 1. Global System Constraints

- **Strict Delegation**: You are a MANAGER. You MUST NOT roleplay the discovery work yourself — this collapses your context window. Instead, delegate to the named agent (Iris, Scout, Echo). Pass each agent only the specific "Working Memory" chunk it needs in the prompt. The agent runs to completion in its own context and returns its `<handoff>` summary as its final message — that returned text is what you read to continue. You cannot message a running agent; each delegation is a single self-contained task.
- **Phase Transitions**: Never start a new phase until the user explicitly types 'proceed', 'approved', or similar confirmation.
- **Upgraded Chain-of-Thought**: Before transitioning between phases, you MUST explicitly verify that the required artifact exists.
  - *Format*: "Thinking: Phase X requires Y. Checking `.docs/summary/...`... File exists. Proceeding."
- **Global Context Scope (Architectural Rule)**: The discovery agents (Iris, Scout, Echo) perform **project-scope** repository analysis. Their artifacts MUST be written under `.docs/summary/` (e.g., `.docs/summary/context.md`). Never let them output to a per-enhancement feature directory (`.docs/{project-name}/`) — that is Tier-2, owned by `bgpdd-plan`.

## 2. Global Error Recovery

If *any* delegated agent (or you, the Orchestrator) exhibits the following behaviors:
1. Gets stuck in a continuous tool-call loop without making progress.
2. Hallucinates a file path that does not exist.
3. Fails to complete its objective after 3 consecutive attempts.

**ACTION**: You MUST immediately halt execution, output a structured state summary of what went wrong, and request explicit human intervention. Do not attempt to guess or bypass the failure silently. (There is no "kill" step — a delegated agent terminates on its own when it returns; simply stop delegating and escalate.)

**CRITICAL CIRCUIT BREAKER**: You must pass the following rule to every delegated agent in its prompt: "If you encounter the exact same error or test failure 3 times in a row, you MUST stop, document the failure state clearly in your `<handoff>` (what you tried and the exact error), and return immediately to escalate to the Orchestrator. Do NOT attempt a 4th fix."

**NO NESTED DELEGATION**: You must pass the following rule to every delegated agent in its prompt: "Do NOT spawn subagents of your own. If a sub-investigation seems necessary, document what is needed in your `<handoff>` and return — the Orchestrator decides whether to delegate it."

**CONTEXT CHECKPOINTS**: A delegated agent's context is bounded by its own run — you do not need to timebox it. If *you* (the Orchestrator) sense your own context is getting large across many phases, checkpoint your state to a scratch file so a fresh session can resume. Do NOT instruct delegated agents to schedule timers or spawn their own replacements — that is your responsibility, not theirs.

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
        └── manual-testing.md      #   Reverse-engineered manual test cases (Echo)
```

---

## 4. Detailed Pipeline Phases

### Phase 1: Project Context Discovery (Iris)
- **Delegated Agent**: **Iris** (Observer)
- **Trigger**: Execute this phase first.
- **Workflow**:
  1. **Target Scope (Orchestrator, before delegating)**: This pipeline may target a single repo or a set of microservice repos, since a single feature can span multiple services. Establish and record, up front: (a) the target repository or repositories, (b) the working branch, and (c) for multi-repo, the local path to each repo. Ask the user if this isn't already clear from context — do not guess.
  2. Delegate to the **Iris** agent, passing her the established Target Scope.
  3. Instruct Iris to scan the repository/repositories and determine the global tech stack and overall project context (e.g., 2D Godot game vs Next.js Web App).
  4. Instruct Iris to record the Target Scope (repo set + per-repo local paths) alongside her tech-stack findings in `.docs/summary/context.md`. She must write this file herself with her file-writing tools — the Orchestrator MUST NOT create it on her behalf. If the file already exists, she must note this in her handoff so you can ask the user whether to update it.
  5. Read Iris's returned handoff before proceeding.

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
     a. `.docs/summary/{feature}/overview.md` — the cross-API consolidation: which API owns what, cross-service call flow, integration seams, links to each `{api}.md`.
     b. `.docs/summary/{feature}/QA/code-workflow.md` — Mermaid sequence diagrams and step-by-step execution paths across the services.
     c. `.docs/summary/{feature}/QA/manual-testing.md` — reverse-engineered manual test cases, using the `code-workflow.md` she just produced, per her persona.
  4. Read Echo's returned handoff before proceeding to Phase 5.

### Phase 5: Session Learning Offer (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this phase directly.
- **Workflow**:
  1. Discovery is global-tier and runs outside any epic — no `.docs/{project-name}/` exists, so there is no game tape to append to and no end-of-epic Forge run will see this session's evidence. Instead, offer the user an on-demand **`/bgpdd-learn`** run now to capture lessons (Did Iris miss any tech-stack details? Did a Scout struggle to map its API?) while this session's evidence is still alive.
  2. If the user declines, simply summarize any run friction in your closing message — do NOT delegate Forge.
  3. The discovery pipeline is complete. Instruct the user to open a new chat session and run `/bgpdd-plan` to begin feature-level planning — it will consume the `.docs/summary/` knowledge base you just built.
