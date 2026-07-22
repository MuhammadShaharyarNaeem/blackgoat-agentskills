---
name: bgpdd-build
description: Phase 2 of the Prompt-Driven Development SOP (Execution). Takes an existing implementation plan and executes it using Mason, Quinn, Luna, Max, and Dep.
trigger: /bgpdd-build
---

# End-to-End Multi-Agent PDD: Execution Phase (bgPDD-Build)

This Standard Operating Procedure (SOP) coordinates the execution squad (Mason, Quinn, Luna, Max, Dep) to take an existing `plan.md` through building, review, optimization, testing, and shipping.

Invoke with `/bgpdd-build` (add the `auto` argument for Autonomous Execution Mode — see §3).

---

## Path Resolution

Skill and agent paths use `{PLUGIN_ROOT}` as a placeholder for the plugin's `skills/` directory (agents live at `{PLUGIN_ROOT}/../agents/`). When this skill is invoked, its base directory is provided to you. List files to confirm a path exists before referencing it.

---

## 1. Global System Constraints

- **Strict Delegation**: You are a MANAGER. You MUST NOT roleplay the phases yourself — this collapses your context window. For each phase, delegate to the named agent (e.g. Mason). The agent runs to completion in its own context and returns its `<handoff>` summary as its final message — that returned text is what you read to continue. You cannot message a running agent; each delegation is a single self-contained task.
- **Prerequisites**: Do NOT run unless `.docs/{project-name}/implementation/plan.md` exists and is fully populated.
- **Hydration Phase**: Before Phase 1, read `.docs/{project-name}/orchestrator-state.json` (if it exists) to restore context from the planning phase. The file follows the schema defined in `bgpdd-plan` Phase 4 (fields: `schema`, `project_name`, `feature`, `pipeline`, `branch`, `phase_completed`, `milestone_cursor`, `artifacts`, `blockers`, `updated`). At hydration, once the working branch is established (see Git Workflow below), record it in the `branch` field. After each milestone completes its Build→Test→Review→Refactor cycle, update the state file: set `pipeline` to `"bgpdd-build"` and `milestone_cursor` to the next pending milestone (or `null` when all milestones are complete).
- **Git Workflow**:
  - At hydration, establish the working branch: ask the user for the repo's branch-naming convention if unknown; default to `feature/{project-name}`. Create it if it does not exist. NEVER build directly on the default branch (main/master).
  - After each milestone goes green (Phase 2 tests pass, and any Phase 3/4 fixes are re-verified), YOU (the Orchestrator) commit the milestone's changes on the working branch with a message citing the milestone name and the `FR`/`NFR` IDs it covers. Committing is pipeline state management, not application-code writing — it does not violate your no-coding rule.
  - A worker that cannot finish in one run commits its partial work to the same working branch before returning its handoff (this makes the CONTEXT CHECKPOINTS rule in §2 explicit — same branch, commit before returning).
- **Phase Transitions**: Never start a new phase until the user explicitly types 'proceed', 'approved', or similar confirmation (except in Auto Mode — see §3).
- **Upgraded Chain-of-Thought**: Before transitioning between phases, explicitly verify the required artifact exists.
  - *Format*: "Thinking: Phase X requires Y. Checking `.docs/{project-name}/Y`... File exists and is populated. Proceeding."
- **Strict Progressive Disclosure (Working Memory)**: Never pass the entire project history or the full `.docs/` folder to a delegated agent. Extract and pass ONLY the specific "Working Memory" chunk they need. Overloading context causes downstream hallucination.
- **File Artifacts**: All artifacts must use standard GitHub markdown and be saved under `.docs/{project-name}/`.

## 2. Global Safety Mechanisms

If *any* delegated agent (or you, the Orchestrator) exhibits the following behaviors:
1. Gets stuck in a continuous tool-call loop without making progress.
2. Hallucinates a file path that does not exist.
3. Fails to complete its objective after 3 consecutive attempts.

**ACTION**: You MUST immediately halt execution, output a structured state summary of what went wrong, and request explicit human intervention. Do not guess or bypass the failure silently. (A delegated agent terminates on its own when it returns — there is no separate "kill" step; simply stop delegating and escalate.)

**CRITICAL CIRCUIT BREAKER**: You must pass the following rule to every delegated agent in its prompt: "If you encounter the exact same error or test failure 3 times in a row, you MUST stop, document the failure state clearly in your `<handoff>` (what you tried and the exact error), and return immediately to escalate to the Orchestrator. Do NOT attempt a 4th fix."

**NO NESTED DELEGATION**: You must pass the following rule to every delegated agent in its prompt: "Do NOT spawn subagents of your own. If a sub-investigation seems necessary, document what is needed in your `<handoff>` and return — the Orchestrator decides whether to delegate it."

**CONTEXT CHECKPOINTS**: A delegated agent's context is bounded by its own run — you do not timebox it, and you must NOT instruct agents to schedule timers or spawn their own replacements. If a worker cannot finish in one run, it commits its partial work to the working branch (see Git Workflow in §1) and returns a `<handoff>` describing the remaining work; **you** then re-delegate a fresh agent with that handoff. If *your own* context grows large, checkpoint to `.docs/{project-name}/orchestrator-state.json` so a fresh session can resume.

## 3. Auto Mode (Optional Argument)

If invoked with the `auto` argument (`/bgpdd-build auto`), operate in **Autonomous Execution Mode**:
- **Macro-Loop Execution**: Seamlessly transition [Phase 1 (Build) → Phase 2 (Test) → Phase 3 (Review) → Phase 4 (Refactor)] in a loop for *each milestone* in `plan.md` without asking for "proceed" confirmation.
- **Phase 5 (Epic Shipping)**: Dep deploys with doubt-driven verification.
- **Phase 6 (Game Tape Checkpoint)**: the Orchestrator appends this run's evidence to `game-tape.md`; Forge runs once at epic end, in `bgpdd-shipping` Step 7.
- **HALT**: Once ALL milestones are complete, drop out of Auto Mode. You MUST ask for explicit human approval before invoking Phase 5 for the entire epic (Phase 6 is a free Orchestrator checkpoint — no approval needed).
- **Circuit Breakers**: If Mason loops 3 times, or Luna flags a blocker Mason cannot fix, immediately drop out of Auto Mode and halt for human intervention.

## 4. Few-Shot Handoff Examples

When communicating with the user during a phase transition checkpoint (non-auto mode):

**Good Example (Crisp, action-oriented):**
> Phase 3 (Review) is complete. Luna found no critical issues, and the report is saved to `.docs/my-app/implementation/review-report.md`.
> **Blockers**: None.
> **Next Step**: Are you ready to proceed to Phase 4 (Optimization) with Max?

---

## 5. Folder Structure (Semantic Memory)

This is **Tier 2** — the per-enhancement work dir (`.docs/{project-name}/`): this pipeline's read-write workspace, scoped to the current enhancement. **Tier 1** (`.docs/summary/{feature}/`) is the global knowledge base produced by **`/bgpdd-discovery`** — read-only for this pipeline. NEVER write build artifacts to Tier 1.

```text
.docs/{project-name}/
└── implementation/        # Checklists, reviews, and release plans
    ├── plan.md            # Dependency-mapped task list (REQUIRED INPUT)
    ├── test-report.md     # Test execution logs and coverage (Quinn)
    ├── review-report.md   # Quality review (Luna)
    ├── ship-decision.md   # Deployment checklist and rollback plan (Dep)
    └── game-tape.md       # Per-phase evidence checkpoints (Orchestrator, Phase 6)
```

---

## 6. Detailed Pipeline Phases

### Phase 1: Building
- **Delegated Agent**: **Mason** (Builder). He reads his methodology dependencies (TDD, debugging, SDD) on-demand.
- **Workflow**:
  1. Pick the next pending milestone from `implementation/plan.md`.
  2. Delegate to the **Mason** agent. **CRITICAL CONTEXT HANDOFF**: copy the exact text of the active milestone from `plan.md` into the delegation prompt so he knows exactly what to build.
  3. **STRICT BLAST RADIUS RULE**: Instruct Mason that *before* modifying any shared DTO or library, he MUST trace dependencies by searching the codebase for all consumers of the DTO/library. (Optionally, if a `code-review-graph` MCP server happens to be available — it is not wired in this plugin's `.mcp.json` — its impact tool may be used instead.) If the radius extends beyond his active microservice, he must document it in his handoff and return for architectural review.
  4. If the blast radius exceeds the active microservice:
     a. Notify the User: "Blast radius exceeds the current microservice boundary. Architectural review required."
     b. Delegate to the **Aria** agent as a temporary advisor, passing her Mason's blast-radius report; ask for a scoped architectural recommendation.
     c. Present Aria's recommendation to the User for approval.
     d. After approval, delegate a **fresh Mason** agent, passing him Mason's prior handoff state and Aria's ruling.
  5. Read Mason's returned handoff and extract the strict `<changed_files>` XML list from it.

### Phase 2: Testing
- **Delegated Agent**: **Quinn** (QA Tester). She reads her methodology dependencies (debugging, playwright) on-demand.
- **Workflow**:
  1. Delegate to the **Quinn** agent. **CRITICAL CONTEXT HANDOFF**: pass her the exact text of the active milestone and the `<changed_files>` list from Mason. **CRITICAL PATHING**: instruct her to append results to `.docs/{project-name}/implementation/test-report.md`.
  2. Instruct Quinn to design and directly execute the test strategy for the newly built code.
  3. **Rejection Loop**: If Quinn's returned handoff reports failing tests, extract her failing-test logs and delegate a fresh Mason agent (Bugfix mode) with the exact failures. Loop Mason ↔ Quinn (fresh delegation each round) until tests pass. **Bound this to 3 rounds per milestone**: track how many Mason-fix → Quinn-retest rounds the current milestone has been through. If tests still fail after round 3, HALT and surface to the user: the milestone, Mason's attempted fixes across rounds, and Quinn's exact failing-test logs. Do NOT delegate a 4th round.

### Phase 3: Code Review
- **Delegated Agent**: **Luna** (Reviewer). She reads her methodology dependencies on-demand.
- **Workflow**:
  1. Delegate to the **Luna** agent, passing her the exact `<changed_files>` XML list from Mason so her scope is surgical.
  2. Instruct Luna to run a 5-axis review: Correctness, Readability, Architecture, Security, Performance (tracing impact per the **Impact Analysis** directive in her persona).
  3. **CRITICAL PATHING**: instruct Luna to save findings to `.docs/{project-name}/implementation/review-report.md`.
  4. If Luna's handoff flags "Critical" or "Important" blockers, delegate a fresh Mason agent to resolve them before proceeding.

### Phase 4: Optimization & Refactoring
- **Delegated Agent**: **Max** (Optimizer). He reads his methodology dependencies on-demand.
- **Workflow**:
  1. **Conditional Invocation**: ONLY invoke Max IF Luna's review contains **Suggestion**-level findings (simplification/refactor suggestions from her code-simplification audit), or if the user explicitly requests optimization. Otherwise, skip this phase.
  2. Delegate to the **Max** agent, passing him the exact `<changed_files>` XML list so his scope is surgical.
  3. Instruct Max to refactor for clarity without behavioral changes, then run regression tests to guarantee stability (or you re-delegate to a Quinn agent to run the suite).

### Phase 5: Epic Shipping (Deferred)
- **Delegated Agent**: **Dep** (DevOps). He reads his methodology dependencies (shipping-and-launch) on-demand.
- **Workflow**:
  1. **Completion Gate**: Before invoking Dep, verify that ALL milestones in `implementation/plan.md` are marked complete (`[x]`). If any `[ ]` remain, loop back to Phase 1 for the next pending milestone.
  2. **Build Coverage Gate**:
     a. Execute the coverage tool via a shell action, using the runtime's available Python 3 interpreter (`python` or `python3`):
        `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --test-report .docs/{project-name}/implementation/test-report.md`
        The full CLI contract (JSON shape, exit codes, parsing rules) lives in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
     b. Read the JSON object from stdout. Exit code 0 = every Must-Have `FR`/`NFR` has a passing test — report any `warnings` and `uncovered_should` entries as non-blocking notes, then proceed. Exit code 1 = the `uncovered` array lists the Must-Have gaps. Exit code 2 = the artifact failed its structural contract (e.g. no Must-Have IDs, unreadable report) — treat this as a defect in the artifact, not the tool.
     c. On exit 1 or 2, DO NOT proceed — loop back to Phase 2 (Testing) with the exact `uncovered` IDs and `warnings` (or the `error` message) so Quinn closes the gap. (This closes the requirement-traceability chain: Rex's `FR`/`NFR` → Alex's task → Quinn's test.) After the fix, re-run step (a) to verify.
     d. **Fallback (no Python runtime)**: If the script cannot run because no Python 3 interpreter is available, verify manually instead: check that `implementation/test-report.md` contains at least one passing test for every Must-Have `FR` and `NFR` in `.docs/{project-name}/requirements.md`; apply the same loop-back rule as step (c).
  3. If the Epic is 100% complete and every Must-Have `FR`/`NFR` is covered, delegate to the **Dep** agent.
  4. Instruct Dep to scan for deployment risks and credentials across the epic and formulate a mandatory **Rollback Plan**.
  5. **CRITICAL PATHING**: instruct Dep to generate `.docs/{project-name}/implementation/ship-decision.md` with a `GO` or `NO-GO` verdict.
  6. **Doubt-Driven Check**: after Dep returns, YOU (the Orchestrator) run the Doubt-Driven Development cycle on Dep's plan before presenting it to the user.
  7. On explicit user confirmation, instruct the User to trigger `/bgpdd-shipping` to orchestrate the final Launch Squad.

### Phase 6: Game Tape Checkpoint (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this phase directly. No delegation, no halt.
- **Workflow**:
  1. While your session context is still alive, append a `## bgpdd-build — [date]` section to `.docs/{project-name}/implementation/game-tape.md` (create the file if it does not exist). At most 10 bullets, covering: user corrections made, agent failures/retries, re-delegation rounds and why, circuit-breaker trips, gates that were rubber-stamped vs. genuinely exercised, and this session's id/transcript path if the runtime exposes it (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`).
  2. This evidence feeds the SINGLE end-of-epic Forge run in `bgpdd-shipping` Step 7 — do NOT delegate Forge here. If this run went badly enough that lessons should not wait for the epic to ship, offer the user an on-demand `/bgpdd-learn` run now instead.
