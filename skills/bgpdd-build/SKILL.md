---
model: gemini-pro-latest
name: bgpdd-build
description: Phase 2 of the Prompt-Driven Development SOP (Execution & Deployment). Takes an existing implementation plan and executes it using Mason, Max, Luna, Quinn, and Dep.
trigger: /bgpdd-build [auto]
role: Execution Orchestrator
phase: building
squad: agent-squad
version: 1.1
---

# End-to-End Multi-Agent PDD: Execution Phase (bgPDD-Build)

This Standard Operating Procedure (SOP) coordinates the execution squad (Mason, Luna, Max, Quinn, Dep) to take an existing `plan.md` through building, review, optimization, testing, and shipping.

---

## Path Resolution

All skill paths in this document use `{PLUGIN_ROOT}` as a placeholder. Before spawning any subagent, resolve it to the root `skills/` directory (the directory two levels above this file). Use `Glob` on the resolved path to confirm it exists before passing it to subagents.

---

## 1. Global System Constraints

- **Strict Subagent Delegation**: You are a MANAGER. You MUST NOT roleplay the phases yourself. This would cause your context window to collapse. For each phase, you MUST use the `invoke_subagent` tool to spawn the specific subagent (Mason, Luna, Max, etc.) with a fresh, isolated workspace. Use the `send_message` tool to communicate with them and wait for their completion.
- **Prerequisites**: This skill MUST NOT be run unless `.docs/{project-name}/implementation/plan.md` exists and is fully populated.
- **Hydration Phase**: Before beginning Phase 1, you MUST read `.docs/{project-name}/orchestrator-state.json` (if it exists) to restore the context from the planning phase.
- **Phase Transitions**: Never start a new phase until the user explicitly types 'proceed', 'approved', or similar confirmation.
- **Upgraded Chain-of-Thought**: Before transitioning between phases, you MUST explicitly verify that the required artifact exists. 
  - *Format*: "Thinking: Phase X requires Y. Checking `.docs/{project-name}/Y`... File exists and is populated. Proceeding."
- **Strict Progressive Disclosure (Working Memory)**: Never pass the entire project history or the full `.docs/` folder to a downstream subagent. You must extract and pass ONLY the specific "Working Memory" chunk they need for their current task in your `invoke_subagent` prompt. Overloading context causes downstream hallucination.
- **File Artifacts**: All artifacts must strictly use standard GitHub markdown formatting and be saved under `.docs/{project-name}/`. This folder acts as the project's persistent **Semantic Memory**.

## 2. Global Safety Mechanisms

If *any* subagent (or the Orchestrator itself) exhibits the following behaviors:
1. Gets stuck in a continuous tool-call loop without making progress.
2. Hallucinates a file path that does not exist.
3. Fails to complete its objective after 3 consecutive attempts.

**ACTION**: You MUST immediately halt execution, use the `manage_subagents` tool to kill the looping subagent if necessary, output a structured state summary of what went wrong, and request explicit human intervention. Do not attempt to guess or bypass the failure silently.

**CRITICAL CIRCUIT BREAKER**: You must pass the following rule to ALL subagents in their prompt: "If you encounter the exact same error or test failure 3 times in a row, you MUST halt execution, document the state in `scratch/error.md`, and immediately terminate to escalate to the user. Do NOT attempt a 4th fix."

**STATE-FLUSH PROTOCOL (Cascading Timeboxes)**:
*   **Orchestrator Limit**: When you (the Orchestrator) begin execution, you MUST immediately use the `schedule` tool to set a 60-minute (3600-second) timer.
*   **Worker Limit**: You must pass the following rule to ALL subagents in their prompt: "When you start a task, your first action MUST be to use the `schedule` tool to set a 15-minute (900-second) timer. When it fires, your context is bloated. Summarize your progress in `scratch/handoff.md` and terminate so a fresh clone can take over."

## 3. Auto Mode (Optional Flag)

If the user invokes this skill with the `auto` flag (e.g., `/bgpdd-build auto`), you must operate in **Autonomous Execution Mode**:
- **Macro-Loop Execution**: Seamlessly transition from [Phase 1 (Build) → Phase 2 (Test) → Phase 3 (Review) → Phase 4 (Refactor)] in a loop for *each milestone* in `plan.md` without asking for "proceed" confirmation.
- **Phase 5 (Epic Shipping)**: Dep deploys with doubt-driven verification.
- **Phase 6 (Agent Improvement)**: Forge analyzes and proposes skill refinements.
- **HALT**: Once ALL milestones are complete, drop out of Auto Mode. You MUST ask for explicit human approval before invoking Phase 5 and Phase 6 for the entire epic.
- **Circuit Breakers**: If Mason loops 3 times, or Luna flags a blocker Mason cannot fix, immediately drop out of Auto Mode and halt for human intervention.

## 4. Few-Shot Handoff Examples

When communicating with the user during a phase transition checkpoint (in non-auto mode), adhere to these examples:

**Good Example (Crisp, action-oriented):**
> Phase 3 (Review) is complete. Luna found no critical issues, and the report is saved to `.docs/my-app/implementation/review-report.md`. 
> **Blockers**: None.
> **Next Step**: Are you ready to proceed to Phase 4 (Optimization) with Max?

---

## 5. Folder Structure (Semantic Memory)
```text
.docs/{project-name}/
└── implementation/        # Checklists, reviews, and release plans
    ├── plan.md            # Dependency-mapped task list (REQUIRED INPUT)
    ├── test-report.md     # Test execution logs and coverage (Quinn)
    ├── review-report.md   # Quality review (Luna)
    └── ship-decision.md   # Deployment checklist and rollback plan (Dep)
```

---

## 6. Detailed Pipeline Phases

### Phase 1: Building
- **Role**: Subagent Manager
- **Delegated Subagent**: Mason (Builder)
- **Invoked Skills**: Mason reads his own methodology dependencies on-demand.
  * [agents/mason]({PLUGIN_ROOT}/../agents/mason.md)
- **Workflow**:
  1. Pick the next pending milestone from `implementation/plan.md`.
  2. Use `invoke_subagent` to spawn **Mason**. Since he is natively loaded from the `agents/` folder, you do not need to define him first. He will read his methodology dependencies (TDD, debugging, SDD) on-demand via `Read`.
  4. Instruct Mason to implement the active milestone. **CRITICAL CONTEXT HANDOFF**: You MUST copy the exact text of the active milestone from `plan.md` and pass it to Mason in the `invoke_subagent` prompt so he knows exactly what to build.
  5. **STRICT BLAST RADIUS RULE**: Instruct Mason that *before* he modifies any shared DTO or library, he MUST use the `get_impact_radius_tool` (if `code-review-graph` MCP is available) or manually trace dependencies via `Grep`. If the radius extends beyond his active microservice, he must escalate to the User.
  6. If the blast radius extends beyond the active microservice:
     a. **HALT**: Gracefully TERMINATE Mason, ensuring his partial state is committed to git or `scratch/handoff.md`.
     b. Notify the User: "Blast radius exceeds the current microservice boundary. Architectural review required."
     c. Use `invoke_subagent` to spawn **Aria** as a temporary advisor. Since she is natively loaded from the `agents/` folder, you do not need to define her first.
     d. Pass Aria the blast radius report from `get_impact_radius_tool` and ask for a scoped architectural recommendation.
     e. Present Aria's recommendation to the User for approval.
     f. After user approval, SPAWN A FRESH MASON, passing him the handoff state and Aria's new ruling.
  7. Wait for Mason to confirm he has finished the milestone and the code is committed. MUST extract the strict `<changed_files>` XML list from Mason's completion summary.

### Phase 2: Testing
- **Role**: Subagent Manager
- **Delegated Subagent**: Quinn (QA Tester)
- **Invoked Skills**: Quinn reads her own methodology dependencies on-demand.
  * [agents/quinn]({PLUGIN_ROOT}/../agents/quinn.md)
- **Workflow**:
  1. Use `invoke_subagent` to spawn **Quinn**. Since she is natively loaded from the `agents/` folder, you do not need to define her first. She will read her methodology dependencies (playwright, browser-testing) on-demand via `Read`.
  3. Instruct Quinn to design and directly execute the test strategy for the newly built code. **CRITICAL CONTEXT HANDOFF**: Pass Quinn the exact text of the active milestone and the `<changed_files>` list from Mason so she knows what to test. **CRITICAL PATHING**: Explicitly instruct her to append her results exactly to `.docs/{project-name}/implementation/test-report.md`.
  4. **Rejection Loop**: If Quinn reports failing tests, extract her failing test logs, TERMINATE Quinn, and spawn Mason (in Bugfix mode) passing him the exact failures. Loop between Mason and Quinn until tests pass.
  5. Wait for Quinn to confirm all tests pass.

### Phase 3: Code Review
- **Role**: Subagent Manager
- **Delegated Subagent**: Luna (Reviewer)
- **Invoked Skills**: Luna reads her own methodology dependencies on-demand.
  * [agents/luna]({PLUGIN_ROOT}/../agents/luna.md)
- **Workflow**:
  1. Use `invoke_subagent` to spawn **Luna**. Since she is natively loaded from the `agents/` folder, you do not need to define her first. Pass her the exact `<changed_files>` XML list from Mason so her scope is surgical.
  3. Instruct Luna to review the code using MCP tools or file-based navigation (per her MCP Fallback rule).
  4. Instruct Luna to run a 5-axis review: Correctness, Readability, Architecture, Security, Performance.
  5. **CRITICAL PATHING**: Instruct Luna to save findings exactly to `.docs/{project-name}/implementation/review-report.md`.
  6. If Luna finds "Critical" or "Important" blockers, you must spawn Mason again to resolve them before proceeding.

### Phase 4: Optimization & Refactoring
- **Role**: Subagent Manager
- **Delegated Subagent**: Max (Optimizer)
- **Invoked Skills**: Max reads his own methodology dependencies on-demand.
  * [agents/max]({PLUGIN_ROOT}/../agents/max.md)
- **Workflow**:
  1. **Conditional Invocation**: ONLY invoke Max IF Luna's review explicitly contains `[LOW]` / Refactor tags, or if the user explicitly requests optimization. Otherwise, skip this phase.
  2. Use `invoke_subagent` to spawn **Max**. Since he is natively loaded from the `agents/` folder, you do not need to define him first. Pass him the exact `<changed_files>` XML list from Mason so his scope is surgical.
  4. Instruct Max to analyze the freshly approved code for unnecessary complexity or duplicate logic.
  5. Instruct Max to refactor for clarity without behavioral changes.
  6. Wait for Max to run regression tests to guarantee stability (or trigger Quinn to run the suite).

### Phase 5: Epic Shipping (Deferred)
- **Role**: Subagent Manager
- **Delegated Subagent**: Dep (DevOps)
- **Invoked Skills**: Dep reads his own methodology dependencies on-demand.
  * [agents/dep]({PLUGIN_ROOT}/../agents/dep.md)
- **Workflow**:
  1. **Completion Gate**: Before invoking Dep, you MUST verify that ALL milestones in `implementation/plan.md` are marked as complete (`[x]`). If any `[ ]` tasks remain, DO NOT proceed to Phase 5. Instead, loop back to Phase 1 (Building) for the next pending milestone.
  2. If the Epic is 100% complete, use `invoke_subagent` to spawn **Dep**. Since he is natively loaded from the `agents/` folder, you do not need to define him first. He will read his methodology dependencies (shipping-and-launch) on-demand via `Read`.
  4. Instruct Dep to scan for deployment risks and credentials across the entire epic.
  5. Instruct Dep to formulate a mandatory **Rollback Plan**.
  6. **CRITICAL PATHING**: Instruct Dep to generate exactly `.docs/{project-name}/implementation/ship-decision.md` with `GO` or `NO-GO`.
  7. **Doubt-Driven Check**: After Dep generates the plan, YOU (the Orchestrator) MUST run the Doubt-Driven Development cycle on Dep's plan before presenting it to the human user.
  8. Wait for explicit user confirmation. Once confirmed, explicitly instruct the User to trigger `/bgpdd-shipping` to orchestrate the final Launch Squad.

### Phase 6: Agent Improvement
- **Role**: Subagent Manager
- **Delegated Subagent**: Forge (System Coach)
- **Invoked Skills**: Forge reads his own methodology dependencies on-demand.
  * [agents/forge]({PLUGIN_ROOT}/../agents/forge.md)
- **Workflow**:
  1. Use `invoke_subagent` to spawn **Forge**. Since he is natively loaded from the `agents/` folder, you do not need to define him first. He will read his methodology dependencies (agent-orchestration-improve-agent) on-demand via `Read`.
  3. Instruct Forge to analyze the project metrics, error logs, and review reports, and to write his proposed updates to `.docs/{project-name}/implementation/agent-improvements.md`.
  4. Wait for Forge to confirm the proposal is ready and terminate.
  5. **HALT EXECUTION**. Explicitly ask the User to review and approve the `agent-improvements.md` file. Do NOT proceed until you have explicit human approval.
  6. Upon User approval, invoke Forge a second time and instruct him to use his file editing tools to apply the approved changes to the `SKILL.md` files.

