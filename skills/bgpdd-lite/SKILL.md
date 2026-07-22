---
name: bgpdd-lite
description: The mid-weight PDD pipeline for well-specified work. Skips honing and architecture (no Rex Q&A, no Aria) but keeps FR/NFR traceability and the coverage gate. You write mini-requirements with the Orchestrator, Alex plans, then /bgpdd-build executes. Use when the spec is already known (e.g. applying an established pattern or contract) and full /bgpdd-plan would be overkill.
trigger: /bgpdd-lite
---

# End-to-End Multi-Agent PDD: Lite Planning Phase (bgPDD-Lite)

This Standard Operating Procedure (SOP) is the mid-weight lane between a bare single-agent delegation and the full `/bgpdd-plan` pipeline. It keeps the plugin's spine — stable `FR`/`NFR` IDs, "Requirements covered:" traceability, the coverage gate, game tape, and the `orchestrator-state.json` handoff — while dropping the interactive honing Q&A (no delegated Rex) and the architecture phase (no Aria, no `detailed-design.md`).

**When to use**: the spec is already known — applying an established pattern, implementing a known stack contract, extending a mapped feature in a well-understood direction. **When NOT to use**: contested design, unclear acceptance criteria, cross-boundary contract changes, or anything needing architectural decisions — run the Phase 0 Fit Check below before committing; it routes those cases out.

---

## Path Resolution

Skill and agent paths in this document use `{PLUGIN_ROOT}` as a placeholder for the plugin's `skills/` directory. When this skill is invoked, its base directory is provided to you; `{PLUGIN_ROOT}` is that `skills/` directory (the agents live at `{PLUGIN_ROOT}/../agents/`). List files to confirm a path exists before referencing it.

---

## 1. Global System Constraints

- **Strict Delegation**: You are a MANAGER. For non-interactive phases you MUST NOT roleplay the agent's work yourself — this collapses your context window. Instead, delegate to the named agent (here: Alex). Pass the agent the specific "Working Memory" chunk it needs in the prompt. The agent runs to completion in its own context and returns its `<handoff>` summary as its final message — that returned text is what you read to continue. You cannot message a running agent; each delegation is a single self-contained task.
  - **EXCEPTION — Phase 1 (Mini-Requirements)**: Requirements drafting in lite is interactive (with the user, in the main session). There is no delegated Rex — see Phase 1 below.
- **Phase Transitions**: Never start a new phase until the user explicitly types 'proceed', 'approved', or similar confirmation.
- **Upgraded Chain-of-Thought**: Before transitioning between phases, you MUST explicitly verify that the required artifact exists AND satisfies its content contract — existence and non-emptiness alone are not sufficient. Content contracts:
  - `requirements.md`: has at least one Must-Have requirement carrying an `FR` ID and a Given/When/Then acceptance criterion.
  - `plan.md`: every task cites the requirement ID(s) it satisfies (a "Requirements covered:" field), and every task carries a verification step.
  - *Format*: "Thinking: Phase X requires Y. Checking `.docs/{project-name}/Y`... File exists and satisfies its content contract [state which check(s) passed]. Proceeding."
- **Strict Progressive Disclosure (Working Memory)**: Never pass the entire project history or the full `.docs/` folder to a delegated agent. Extract and pass ONLY the specific "Working Memory" chunk they need for their current task. Overloading context causes downstream hallucination.
- **File Artifacts**: All artifacts must use standard GitHub markdown and be saved under `.docs/{project-name}/`. This folder is the project's persistent **Semantic Memory**.
- **Two-Tier Path Model**: **Tier 1** (`.docs/summary/{feature}/`) is the durable global knowledge base produced by `/bgpdd-discovery` — read-only for this pipeline. **Tier 2** (`.docs/{project-name}/`) is this enhancement's read-write workspace. Never write lite artifacts into Tier 1.

## 2. Global Error Recovery

If *any* delegated agent (or you, the Orchestrator) exhibits the following behaviors:
1. Gets stuck in a continuous tool-call loop without making progress.
2. Hallucinates a file path that does not exist.
3. Fails to complete its objective after 3 consecutive attempts.

**ACTION**: You MUST immediately halt execution, output a structured state summary of what went wrong, and request explicit human intervention. Do not attempt to guess or bypass the failure silently. (There is no "kill" step — a delegated agent terminates on its own when it returns; simply stop delegating and escalate.)

**AUTONOMOUS REJECTION**: If an artifact fails a gate, re-delegate to its producing agent (a fresh delegation) with the rejection notes so it fixes the artifact automatically. **Bound this to 2 rounds per artifact**: track how many auto-fix rounds a given artifact (e.g. `plan.md`) has been through. If, after 2 rounds, the flaw is still unresolved, halt and surface the artifact, the flaw, and both attempts to the user rather than re-delegating a third time.

**CRITICAL CIRCUIT BREAKER**: You must pass the following rule to every delegated agent in its prompt: "If you encounter the exact same error or test failure 3 times in a row, you MUST stop, document the failure state clearly in your `<handoff>` (what you tried and the exact error), and return immediately to escalate to the Orchestrator. Do NOT attempt a 4th fix."

**NO NESTED DELEGATION**: You must pass the following rule to every delegated agent in its prompt: "Do NOT spawn subagents of your own. If a sub-investigation seems necessary, document what is needed in your `<handoff>` and return — the Orchestrator decides whether to delegate it."

**CONTEXT CHECKPOINTS**: A delegated agent's context is bounded by its own run — you do not need to timebox it. If *you* (the Orchestrator) sense your own context is getting large across phases, checkpoint your state to `.docs/{project-name}/orchestrator-state.json` (see Phase 3's schema) so a fresh session can resume. Do NOT instruct delegated agents to schedule timers or spawn their own replacements — that is your responsibility, not theirs.

---

## 3. Detailed Pipeline Phases

### Phase 0: Fit Check (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this check directly, before any artifact is written.
- **Workflow**: Answer five questions about the work:
  1. Are there **decisions to make**, or only work to do?
  2. Can the user alone state acceptance in **≤10 testable bullets**?
  3. Does it **cross a service boundary or shared contract**?
  4. Will anyone need to **trace why** later?
  5. Is it **multi-session**?
- **Routing**:
  - Localized defect → route to **`/bg-bugfix`** instead.
  - A "yes" on question 1 (design decisions exist), OR 2+ "yes" across questions 3/5, OR the design is contested → **HALT** and route to **`/bgpdd-plan`** (and `/bgpdd-discovery` first if the work is brownfield and the feature is unmapped in `.docs/summary/`).
  - Purely mechanical sweep with zero decisions AND no traceability need (question 4 = no) (e.g. a rename) → **no pipeline at all**: one Builder delegation plus a verification checklist (build green, repo-wide search for the old term returns zero hits).
  - Otherwise → confirm the `{project-name}` work slug with the user AND — for brownfield work — the Tier-1 durable `{feature}` id (from `.docs/summary/`); record `null` for greenfield/unmapped work, so Phase 3's state write has a defined `feature` value. Then proceed to Phase 1.

### Phase 1: Mini-Requirements (Orchestrator + user, main session)
- **Delegated Agent**: None — no delegated Rex, no honing transcript. You draft the spec WITH the user in-session.
- **Format authority**: Rex's requirements template and ID rules in `{PLUGIN_ROOT}/../agents/rex.md` — stable `FR-n`/`NFR-n` IDs in one continuous sequence, MoSCoW tiers, and a Given/When/Then acceptance criterion on every Must-Have.
- **Workflow**:
  1. Draft `.docs/{project-name}/requirements.md` with the user using Rex's exact template. For known-contract work, transcribe the governing stack contract into FRs (e.g. Response Pattern FRs come straight from `{PLUGIN_ROOT}/dotnet-backend-patterns/SKILL.md`). When the governing contract is `dotnet-backend-patterns`, the mini-requirements MUST record the sanctioned API mode (Mode A — CQRS+MediatR, or Mode B — REPR) as an explicit constraint line — workers may not infer it.
  2. **ESCALATION**: If the FR list exceeds ~10 Must-Haves, or ambiguity keeps surfacing as you draft, HALT and recommend `/bgpdd-plan` — the work has outgrown lite.
  3. **ESCALATION**: If the premise materially changes during drafting (e.g. infrastructure assumed to exist turns out not to), HALT and re-run the Phase 0 Fit Check before continuing — a scope-class change invalidates the original routing.
  4. The user confirms the file before you proceed to Phase 2.

### Phase 2: Planning (Alex)
- **Delegated Agent**: **Alex** (Strategist)
- **Workflow**:
  1. Delegate to the **Alex** agent. He reads his own methodology dependencies on-demand.
  2. Pass him the path to `.docs/{project-name}/requirements.md` **and** the relevant stack-contract skill path(s) (e.g. `{PLUGIN_ROOT}/dotnet-backend-patterns/SKILL.md`) as the architecture reference — there is NO `detailed-design.md` in lite. Instruct Alex that the plan's Reference Documents section links `requirements.md` and the governing stack contract(s) instead of a blueprint, and that he must carry the recorded API mode constraint from `requirements.md` into the plan's Reference Documents.
  3. **CRITICAL PATHING**: Instruct Alex that he MUST save the checklist exactly to `.docs/{project-name}/implementation/plan.md` (NOT the root `.docs/{project-name}/` folder), using his planning methodology's format.
  4. Read Alex's returned handoff.

### Phase 2.5: Coverage Gate (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this check directly.
- **Workflow**:
  1. Execute the coverage tool via a shell action, using the runtime's available Python 3 interpreter (`python` or `python3`):
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --plan .docs/{project-name}/implementation/plan.md`
     The full CLI contract (JSON shape, exit codes, parsing rules) lives in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
  2. Read the JSON object from stdout. Exit code 0 = every Must-Have `FR`/`NFR` is covered — report any `warnings` and `uncovered_should` entries to the user as non-blocking notes, then proceed to Phase 3. Exit code 1 = the `uncovered` array lists the Must-Have gaps. Exit code 2 = an artifact failed its structural contract (e.g. no task blocks, no Must-Have IDs) — treat this as a defect in the artifact, not the tool.
  3. On exit 1 or 2, re-delegate to **Alex** (a fresh delegation) quoting the exact `uncovered` IDs and `warnings` (or the `error` message) — subject to the 2-round auto-fix bound in Global Error Recovery (§2). If unresolved after 2 rounds, halt and surface to the user. After each fix, re-run step 1 to verify.
  4. **Fallback (no Python runtime)**: If the script cannot run because no Python 3 interpreter is available, perform the check manually instead: read `.docs/{project-name}/requirements.md` and `.docs/{project-name}/implementation/plan.md`, verify every Must-Have FR and NFR ID maps to at least one task's "Requirements covered:" field in plan.md, and that every task cites the requirement ID(s) it satisfies; apply the same re-delegation rule as step 3.
  5. Once coverage is confirmed, proceed to Phase 3.

### Phase 3: Handoff to Build (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this phase directly. No delegation, no halt.
- **Workflow**:
  1. **Game Tape checkpoint**: While your session context is still alive, append a `## bgpdd-lite — [date]` section to `.docs/{project-name}/implementation/game-tape.md` (create the file if it does not exist). At most 10 bullets, covering: user corrections made, agent failures/retries, re-delegation rounds and why, circuit-breaker trips, gates that were rubber-stamped vs. genuinely exercised, and this session's id/transcript path if the runtime exposes it.
  2. **State Persistence**: Write `.docs/{project-name}/orchestrator-state.json` using the exact schema defined in `bgpdd-plan` Phase 4 (fields: `schema`, `project_name`, `feature`, `pipeline`, `branch`, `phase_completed`, `milestone_cursor`, `artifacts`, `blockers`, `updated`), with these lite-specific values: `"pipeline": "bgpdd-lite"`, `"phase_completed": 3`, `branch` and `milestone_cursor` `null` (owned by `bgpdd-build`), and `artifacts.design` set to the governing stack-contract skill path (or `null` if none) — `artifacts.requirements` and `artifacts.plan` point at the files produced above.
  3. Prompt the user to open a fresh chat session and trigger **`/bgpdd-build`** to execute the plan (suggest the `auto` argument — lite work is well-specified by definition). Note: `/bgpdd-shipping` still requires build to complete first — lite changes nothing downstream.

## Procedural Memories (Learned Lessons)
- **[2026-07-20]**: When Phase 0/1 needs codebase ground-truth gathering (fact-finding, reverse-engineering, API/pattern mapping) too large to run inline, delegate it to the squad's **Scout** persona (`{PLUGIN_ROOT}/../agents/scout.md`) — the designated disposable research worker — as the default, rather than the generic built-in `Explore` agent. Scout carries the squad's methodology dependencies; the built-in does not. This keeps lite consistent with `/bgpdd-discovery` and `/bgpdd-plan`, which already route research through Scout. Phase 0/1 stay Orchestrator-owned; this governs only sub-delegated research, and deviating to another researcher requires a stated reason.
