---
name: bgpdd-plan
description: Phase 1 of the Prompt-Driven Development SOP (Design & Architecture). Refines ideas, conducts research, and creates an implementation plan using Rex, Aria, and Alex.
trigger: /bgpdd-plan
---

# End-to-End Multi-Agent PDD: Planning Phase (bgPDD-Plan)

This Standard Operating Procedure (SOP) coordinates the planning squad (Rex, Aria, Alex) to take a rough idea through requirements gathering, technical research, architecture design, and task breakdown.

---

## Path Resolution

Skill and agent paths in this document use `{PLUGIN_ROOT}` as a placeholder for the plugin's `skills/` directory. When this skill is invoked, its base directory is provided to you; `{PLUGIN_ROOT}` is that `skills/` directory (the agents live at `{PLUGIN_ROOT}/../agents/`). List files to confirm a path exists before referencing it.

When you inject a resolved `base-persona.md` path into a delegation brief, it lives at `{PLUGIN_ROOT}/agent-squad/base-persona.md` — inside the `agent-squad` skill folder, NOT the `agents/` folder. The `agents/` folder holds ONLY persona files (`rex.md`, `alex.md`, `scout.md`, …); base-persona is a skill, not a persona. Injecting `{PLUGIN_ROOT}/../agents/base-persona.md` is the recurring defect that makes every delegated agent flag base-persona as missing. Verify the base-persona path resolves to an existing file before delegating.

---

## 1. Global System Constraints

- **Strict Delegation**: You are a MANAGER. For non-interactive phases you MUST NOT roleplay the agent's work yourself — this collapses your context window. Instead, delegate to the named agent (e.g. Aria). Pass the agent the specific "Working Memory" chunk it needs in the prompt. The agent runs to completion in its own context and returns its `<handoff>` summary as its final message — that returned text is what you read to continue. You cannot message a running agent; each delegation is a single self-contained task.
  - **EXCEPTION — Phase 1 (Honing)**: Requirements honing is interactive (turn-by-turn Q&A with the user). A delegated agent cannot pause to ask the user and resume, so **you (the main session) run Phase 1 yourself** following Rex's persona as the behavioral spec. See Phase 1 below.
- **Phase Transitions**: Never start a new phase until the user explicitly types 'proceed', 'approved', or similar confirmation.
- **Upgraded Chain-of-Thought**: Before transitioning between phases, you MUST explicitly verify that the required artifact exists AND satisfies its content contract — existence and non-emptiness alone are not sufficient. Content contracts:
  - `requirements.md`: has at least one Must-Have requirement carrying an `FR` ID and a Given/When/Then acceptance criterion.
  - `detailed-design.md`: explicitly references the `FR` IDs it addresses (the design must show which requirements it covers).
  - `plan.md`: every task cites the requirement ID(s) it satisfies (a "Requirements covered:" field), and every task carries a verification step.
  - *Format*: "Thinking: Phase X requires Y. Checking `.docs/{project-name}/Y`... File exists and satisfies its content contract [state which check(s) passed]. Proceeding."
- **Strict Progressive Disclosure (Working Memory)**: Never pass the entire project history or the full `.docs/` folder to a delegated agent. Extract and pass ONLY the specific "Working Memory" chunk they need for their current task. Overloading context causes downstream hallucination.
- **File Artifacts**: All artifacts must use standard GitHub markdown and be saved under `.docs/{project-name}/`. This folder is the project's persistent **Semantic Memory**.

## 2. Global Error Recovery

If *any* delegated agent (or you, the Orchestrator) exhibits the following behaviors:
1. Gets stuck in a continuous tool-call loop without making progress.
2. Hallucinates a file path that does not exist.
3. Fails to complete its objective after 3 consecutive attempts.

**ACTION**: You MUST immediately halt execution, output a structured state summary of what went wrong, and request explicit human intervention. Do not attempt to guess or bypass the failure silently. (There is no "kill" step — a delegated agent terminates on its own when it returns; simply stop delegating and escalate.)

**AUTONOMOUS REJECTION**: If an agent reports a blocking flaw in a previous agent's artifact, re-delegate to the previous agent (a fresh delegation) with the rejection notes so it fixes the artifact automatically. **Bound this to 2 rounds per artifact**: track how many auto-fix rounds a given artifact (e.g. `requirements.md`) has been through. If, after 2 rounds, the flaw is still unresolved, halt and surface the artifact, the flaw, and both attempts to the user rather than re-delegating a third time. Do not halt before that unless human input is explicitly required.

**CRITICAL CIRCUIT BREAKER**: You must pass the following rule to every delegated agent in its prompt: "If you encounter the exact same error or test failure 3 times in a row, you MUST stop, document the failure state clearly in your `<handoff>` (what you tried and the exact error), and return immediately to escalate to the Orchestrator. Do NOT attempt a 4th fix."

**NO NESTED DELEGATION**: You must pass the following rule to every delegated agent in its prompt: "Do NOT spawn subagents of your own. If a sub-investigation seems necessary, document what is needed in your `<handoff>` and return — the Orchestrator decides whether to delegate it."

**CONTEXT CHECKPOINTS**: A delegated agent's context is bounded by its own run — you do not need to timebox it. If *you* (the Orchestrator) sense your own context is getting large across many phases, checkpoint your state to `.docs/{project-name}/orchestrator-state.json` (see Phase 4) so a fresh session can resume. Do NOT instruct delegated agents to schedule timers or spawn their own replacements — that is your responsibility, not theirs.

## 3. Few-Shot Handoff Examples

When communicating with the user during a phase transition checkpoint, adhere to these examples:

**Good Example (Crisp, action-oriented):**
> Phase 3 (Planning) is complete. Alex has saved the detailed task list to `.docs/my-app/implementation/plan.md`.
> **Blockers**: None.
> **Next Step**: Are you ready to proceed to Phase 4 (Game Tape Checkpoint)?

---

## 4. Folder Structure (Semantic Memory) — TWO TIERS

This pipeline uses two distinct memory scopes. Do not conflate them.

**Tier 1 — Global project knowledge base** (`.docs/summary/`): built by the **`/bgpdd-discovery`**
pipeline (Iris, Scout, Quinn) at **project scope** and **persisted across enhancement cycles**. This
skill (`bgpdd-plan`) **consumes** it — it does not produce it; run `/bgpdd-discovery` first for
brownfield work (see the Pre-Flight Check below). It is indexed by durable feature id (`{feature}`,
e.g. `slide`) so the next time a feature is touched, its map already exists.
```text
.docs/summary/
├── context.md                     # Project-wide tech-stack context + Target Scope (Iris) — one file
└── {feature}/                     # Durable per-feature knowledge base (e.g. slide/)
    ├── overview.md                #   Synthesized cross-API overview (Quinn)
    ├── {api}.md                   #   Per-API feature-fragment maps, one per API (Scout)
    └── QA/
        ├── code-workflow.md       #   Mermaid sequence diagrams & execution paths (Quinn)
        └── manual-testing.md      #   Reverse-engineered manual test cases (Quinn)
```

**Tier 2 — Per-enhancement work dir** (`.docs/{project-name}/`): the isolated artifacts for
**this** piece of work, where `{project-name}` is the current enhancement's work slug (e.g.
`slide-enhancement`). Produced by Rex/Aria/Alex; scoped to this cycle.
```text
.docs/{project-name}/
├── rough-idea.md          # Initial concept
├── honing-transcript.md   # Interactive Q&A transcript (Phase 1, main session)
├── requirements.md        # Finalized specification (Phase 1, Rex synthesis)
├── research/              # Technical research & findings (Aria)
├── design/                # System designs & Mermaid diagrams (Aria)
│   └── detailed-design.md
├── implementation/        # Checklists (Alex)
│   ├── plan.md            # Dependency-mapped task list
│   └── game-tape.md       # Per-phase evidence checkpoints (Orchestrator, Phase 4)
└── orchestrator-state.json # Handoff state for bgpdd-build (Phase 4)
```

---

## 5. Detailed Pipeline Phases

> **Brownfield vs Greenfield**: The Pre-Flight Check applies **only when the user is modifying an existing system (Brownfield)**. For a greenfield (new) project, skip directly to Phase 1.

### Pre-Flight Check: Global Context Verification (Brownfield only)
- **Delegated Agent**: None — the Orchestrator performs this check directly.
- **Purpose**: This skill **consumes** the Tier-1 knowledge base but no longer produces it — global discovery (Iris → Scout → Quinn) now lives in the standalone **`/bgpdd-discovery`** pipeline. Verify that discovery has already run before planning against an existing system.
- **Workflow**:
  1. Determine whether this is brownfield (modifying an existing system) or greenfield (new project). If greenfield, skip this check entirely and go to Phase 1.
  2. **Brownfield**: check that the Tier-1 `.docs/summary/context.md` exists, and — for the feature being enhanced — that `.docs/summary/{feature}/overview.md` exists.
  3. **If either is missing**: HALT. Explicitly instruct the user to run **`/bgpdd-discovery`** first to map the global tech stack, per-API feature fragments, and legacy QA baseline. Do NOT attempt to run discovery yourself or hand-author these files — resume Phase 1 only once the knowledge base is present.
  4. **If present**: confirm the `{feature}` id with the user (so downstream phases read the right `.docs/summary/{feature}/` subtree) and proceed to Phase 1.

### Phase 1: Honing & Requirements (HYBRID)
- **Behavioral spec**: `{PLUGIN_ROOT}/../agents/rex.md` (Rex, the Analyst) + `{PLUGIN_ROOT}/blackgoat-idea-honing/SKILL.md`
- **Why hybrid**: honing is an interactive, turn-by-turn conversation with the user, and a delegated (fire-and-forget) agent cannot pause to ask the user and resume. So the **live Q&A runs in the main session**, but the **spec authoring is delegated to an isolated Rex** — preserving the isolation you want for the heavy artifact work.

- **Step A — Interactive honing (YOU, the main session)**:
  1. Read Rex's persona (`agents/rex.md`) and the `blackgoat-idea-honing` methodology; adopt them as your behavior for this step.
  2. Save any rough idea the user gave into `.docs/{project-name}/rough-idea.md`. If brownfield, read the Tier-1 knowledge base first — `.docs/summary/context.md` and `.docs/summary/{feature}/overview.md` (drill into `{api}.md` / QA files as needed) — to ground your questions in the real system. (Greenfield: these don't exist; skip.)
  3. Conduct the honing Q&A: ask the user **one targeted question at a time**, probing edge cases deeply, appending each question and answer to `.docs/{project-name}/honing-transcript.md`. Use your runtime's structured multiple-choice question tool (if one exists) for clear multiple-choice decisions; otherwise ask in plain conversation.
  4. Even if the user provides a complete requirements document upfront, still review it for missing edge cases and drive it through the honing checkpoint — do not skip straight to acceptance.
  5. When the user confirms honing is complete, the transcript is final.

- **Step B — Spec synthesis (delegate isolated Rex)**:
  6. Delegate to the **Rex** agent. Pass him the paths to `.docs/{project-name}/honing-transcript.md`, `.docs/{project-name}/rough-idea.md`, and (if brownfield) the `.docs/summary/{feature}/` knowledge base. Instruct him to synthesize `.docs/{project-name}/requirements.md` from the transcript using his requirements template.
  7. Read Rex's returned handoff. If he flags unresolved **open questions** (he cannot ask the user directly), relay them to the user, append answers to the transcript, and re-delegate Rex to finalize. Loop until `requirements.md` is complete.
  8. Request user confirmation to transition to Phase 2.

### Phase 2: Research & Architecture (Aria)
- **Delegated Agent**: **Aria** (Architect)
- **Workflow**:
  1. Delegate to the **Aria** agent (tell her the `{feature}` if brownfield).
  2. Instruct Aria to read `.docs/{project-name}/requirements.md` **and** `.docs/{project-name}/honing-transcript.md` (for intent nuance), and — **if brownfield** — the Tier-1 `.docs/summary/{feature}/overview.md`, drilling into individual `.docs/summary/{feature}/{api}.md` files as the design requires (so the prior Scout research is consumed, not orphaned). She then does her own additional research. Note: Aria cannot delegate to Scout — she reads the existing maps.
  3. **CRITICAL PATHING**: Instruct Aria that she MUST write the final blueprint exactly to `.docs/{project-name}/design/detailed-design.md`.
  4. Read Aria's returned handoff.
  5. **Iteration Checkpoint**: Present Aria's design to the user and explicitly offer to bounce back to Phase 1 if research uncovered new questions.

### Phase 3: Planning (Alex)
- **Delegated Agent**: **Alex** (Strategist)
- **Workflow**:
  1. Delegate to the **Alex** agent. He reads his own methodology dependencies on-demand.
  2. Instruct Alex to read `.docs/{project-name}/requirements.md`, `.docs/{project-name}/honing-transcript.md`, and `.docs/{project-name}/design/detailed-design.md`, and convert the blueprint into micro-tasks ordered to satisfy dependencies.
  3. **CRITICAL PATHING**: Instruct Alex that he MUST save the checklist exactly to `.docs/{project-name}/implementation/plan.md` (NOT the root `.docs/{project-name}/` folder), using his planning methodology's format.
  4. Read Alex's returned handoff.

### Phase 3.5: Coverage Gate (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this check directly.
- **Workflow**:
  1. Execute the coverage tool via a shell action, using the runtime's available Python 3 interpreter (`python` or `python3`):
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --plan .docs/{project-name}/implementation/plan.md`
     The full CLI contract (JSON shape, exit codes, parsing rules) lives in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
  2. Read the JSON object from stdout. Exit code 0 = every Must-Have `FR`/`NFR` is covered — report any `warnings` and `uncovered_should` entries to the user as non-blocking notes, then proceed to Phase 4. Exit code 1 = the `uncovered` array lists the Must-Have gaps. Exit code 2 = an artifact failed its structural contract (e.g. no task blocks, no Must-Have IDs) — treat this as a defect in the artifact, not the tool.
  3. On exit 1 or 2, re-delegate to **Alex** (a fresh delegation) quoting the exact `uncovered` IDs and `warnings` (or the `error` message) — subject to the existing 2-round auto-fix bound. If unresolved after 2 rounds, halt and surface to the user. After each fix, re-run step 1 to verify.
  4. **Fallback (no Python runtime)**: If the script cannot run because no Python 3 interpreter is available, perform the check manually instead: read `.docs/{project-name}/requirements.md` and `.docs/{project-name}/implementation/plan.md`, verify every Must-Have FR and NFR ID maps to at least one task's "Requirements covered:" field in plan.md, and that every task cites the requirement ID(s) it satisfies; apply the same re-delegation rule as step 3.
  5. Once coverage is confirmed, proceed to Phase 4.

### Phase 4: Game Tape Checkpoint (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this phase directly. No delegation, no halt.
- **Workflow**:
  1. While your session context is still alive, append a `## bgpdd-plan — [date]` section to `.docs/{project-name}/implementation/game-tape.md` (create the file if it does not exist). At most 10 bullets, covering: user corrections made, agent failures/retries, re-delegation rounds and why, circuit-breaker trips, gates that were rubber-stamped vs. genuinely exercised, and this session's id/transcript path if the runtime exposes it (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`).
  2. This evidence feeds the SINGLE end-of-epic Forge run in `bgpdd-shipping` Step 7 — do NOT delegate Forge here. If this run went badly enough that lessons should not wait for the epic to ship, offer the user an on-demand `/bgpdd-learn` run now instead.
  3. **State Persistence**: Before concluding, write your orchestrator state to `.docs/{project-name}/orchestrator-state.json`. The `bgpdd-build` workflow reads this to hydrate itself. Use exactly this shape:
```json
{
  "schema": 1,
  "project_name": "slide-enhancement",
  "feature": "slide",
  "pipeline": "bgpdd-plan",
  "branch": null,
  "phase_completed": 4,
  "milestone_cursor": null,
  "artifacts": {
    "requirements": ".docs/{project-name}/requirements.md",
    "design": ".docs/{project-name}/design/detailed-design.md",
    "plan": ".docs/{project-name}/implementation/plan.md"
  },
  "blockers": [],
  "updated": "<ISO-8601 timestamp>"
}
```
     Field notes: `feature` is the Tier-1 durable feature id from `.docs/summary/{feature}/` (`null` for greenfield). `pipeline` is the last pipeline that wrote the state. `milestone_cursor` is owned by `bgpdd-build` — the next pending milestone in `plan.md`; leave it `null` until build starts. `blockers` is an array of open blocker strings. `branch` is owned by `bgpdd-build` — the working branch established at build hydration; `bgpdd-shipping` Step 4.5 pushes this branch; `null` until build starts. Downstream pipelines (`bgpdd-build`, `bgpdd-shipping`) hydrate from this exact shape.
  4. Prompt the user to open a new chat session and trigger `/bgpdd-build` to execute the code.
