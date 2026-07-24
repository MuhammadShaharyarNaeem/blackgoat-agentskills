---
name: bgpdd-shipping
description: "Phase 3 of the Prompt-Driven Development SOP (Verification & Deployment). Orchestrates a dedicated Launch Squad (Vera, Cipher, and Dep) to execute the pre-launch checklist, harden the application, and orchestrate the final rollout."
trigger: /bgpdd-shipping
---

# bgpdd-shipping

## Purpose

To orchestrate Phase 3 of the Prompt-Driven Development (PDD) lifecycle. This skill acts as the final deployment gate. When invoked, it orchestrates a dedicated "Launch Squad" of sub-agents to parallelize the execution of the massive `shipping-and-launch` checklist. It prevents unverified, unmonitored, or insecure code from reaching production.

## When to Use This Skill

- When `bgpdd-build` has successfully completed Phase 2 (Execution & CI/CD).
- When a major feature branch is ready to be merged to `main` and deployed to production.
- When the user explicitly requests to "launch", "ship", or "deploy" the application.
- Trigger phrases: `ship it`, `run bgpdd-shipping`, `launch the app`.

## Core Capabilities

1. **Launch Orchestration**: Delegates to 3 specialized agents to parallelize the pre-launch checklists.
2. **Strict Gatekeeping**: Blocks final deployment until all 3 agents report a fully green checklist.
3. **Automated Documentation**: Compiles the final Changelog, README updates, and Emergency Rollback Plan based on agent reports.

---

## Path Resolution

Skill and agent paths use `{PLUGIN_ROOT}` as a placeholder for the plugin's `skills/` directory (agents live at `{PLUGIN_ROOT}/../agents/`). When this skill is invoked, its base directory is provided to you. List files to confirm a path exists before referencing it.

When you inject a resolved `base-persona.md` path into a delegation brief, it lives at `{PLUGIN_ROOT}/agent-squad/base-persona.md` — inside the `agent-squad` skill folder, NOT the `agents/` folder. The `agents/` folder holds ONLY persona files (`rex.md`, `alex.md`, `scout.md`, …); base-persona is a skill, not a persona. Injecting `{PLUGIN_ROOT}/../agents/base-persona.md` is the recurring defect that makes every delegated agent flag base-persona as missing. Verify the base-persona path resolves to an existing file before delegating.

---

## Global System Constraints

- **Strict Delegation**: You are a MANAGER. You MUST NOT roleplay the Launch Squad's work yourself — this collapses your context window. For each step, delegate to the named agent (e.g. Vera). The agent runs to completion in its own context and returns its `<handoff>` summary as its final message — that returned text is what you read to continue. You cannot message a running agent; each delegation is a single self-contained task.
- **Phase Transitions**: Never advance to the next step until the user explicitly types 'proceed', 'approved', or similar confirmation.
- **Upgraded Chain-of-Thought**: Before each step, explicitly verify the required artifact exists.
  - *Format*: "Thinking: Step X requires Y. Checking `.docs/{project-name}/Y`... File exists and is populated. Proceeding."
- **Strict Progressive Disclosure (Working Memory)**: Never pass the entire project history or the full `.docs/` folder to a delegated agent. Extract and pass ONLY the specific "Working Memory" chunk it needs. Overloading context causes downstream hallucination.
- **Command Timeout Discipline (Anti-Hang)**: The 4-minute rule in `base-persona.md` applies to YOU as well. Every shell command you run directly (coverage gates, git operations, verification checks) MUST carry an explicit timeout of at most 4 minutes (240s). On a timeout: capture partial output, never re-run unchanged — one retry with a stated fix, or a single justified longer bound for a known-long operation. A second timeout on the same command is a failure under Global Error Recovery.

## Global Error Recovery

If *any* delegated agent (or you, the Orchestrator) exhibits the following behaviors:
1. Gets stuck in a continuous tool-call loop without making progress.
2. Hallucinates a file path that does not exist.
3. Fails to complete its objective after 3 consecutive attempts.

**ACTION**: You MUST immediately halt execution, output a structured state summary of what went wrong, and request explicit human intervention. Do not guess or bypass the failure silently. (A delegated agent terminates on its own when it returns — there is no separate "kill" step; simply stop delegating and escalate.)

**CRITICAL CIRCUIT BREAKER**: You must pass the following rule to every delegated agent in its prompt: "If you encounter the exact same error or test failure 3 times in a row, you MUST stop, document the failure state clearly in your `<handoff>` (what you tried and the exact error), and return immediately to escalate to the Orchestrator. Do NOT attempt a 4th fix."

**NO NESTED DELEGATION**: You must pass the following rule to every delegated agent in its prompt: "Do NOT spawn subagents of your own. If a sub-investigation seems necessary, document what is needed in your `<handoff>` and return — the Orchestrator decides whether to delegate it."

**CONTEXT CHECKPOINTS**: If a worker cannot finish in one run, it commits its partial work and returns a `<handoff>` describing the remaining work; **you** then re-delegate a fresh agent with that handoff. If *your own* context grows large, checkpoint to `.docs/{project-name}/orchestrator-state.json` so a fresh session can resume.

## Path Model

- **Tier 1 (global knowledge base)**: `.docs/summary/{feature}/` — produced ONLY by `/bgpdd-discovery`. Read-only in this pipeline.
- **Tier 2 (per-enhancement workspace)**: `.docs/{project-name}/` — this pipeline's read-write workspace (plan.md, test-report.md, ship-decision.md, game-tape.md, orchestrator-state.json). Never write shipping artifacts to Tier 1.

---

## Execution Checklist

As the Orchestrator, you must follow these steps in exact order. Do not skip steps.

### Step 0: Hydration
1. Establish `{project-name}`: take it from the user, or list `.docs/` and confirm the correct project with the user. Do NOT guess.
2. Read `.docs/{project-name}/orchestrator-state.json` (if it exists) to restore context from `bgpdd-build`. The file follows the schema defined in `bgpdd-plan` Phase 4 (fields: `schema`, `project_name`, `feature`, `pipeline`, `branch`, `phase_completed`, `milestone_cursor`, `artifacts`, `blockers`, `updated`). If its `pipeline` is not `"bgpdd-build"`, or its `milestone_cursor` is not null/complete, the build did not finish — apply the Prerequisite Gate below and HALT.
3. **Prerequisite Gate**: Verify that `.docs/{project-name}/implementation/plan.md` exists with ALL milestones marked `[x]`, and that `.docs/{project-name}/implementation/test-report.md` exists. If either check fails, HALT and instruct the user to complete `/bgpdd-build` first.

### Step 1: Read the Skill
Read the full `shipping-and-launch` skill located at `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`. Extract the exact text of each checklist section that each agent needs — you must paste that text into their delegation prompts as their Working Memory, not merely name the section.

### Step 2: Delegate the Launch Squad
Delegate to the following three agents in **two stages**. Each prompt MUST (a) include the exact checklist section text pasted from `shipping-and-launch`, (b) name the skill path `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md` so the agent can consult it, and (c) include the CRITICAL CIRCUIT BREAKER rule verbatim. Each agent returns its pass/fail `<handoff>` as its final message.

- **Stage 1 — Vera alone**: Delegate Vera first and wait for her handoff before starting Stage 2. Vera runs full builds and test suites that take file, build-output, and port locks; running scanners or infra verification concurrently against the same checkout causes lock collisions and flaky failures (especially on Windows).
- **Stage 2 — Cipher and Dep in parallel**: After Vera's handoff returns, delegate Cipher and Dep **in parallel** — start both delegations in a single batch.

1. **Vera (QA & Performance)** — delegate to the **Vera** agent (Stage 1)
   - **Assignment**: `Code Quality`, `Performance`, and `Accessibility` checklists.
   - **Prompt**: "Execute the Code Quality, Performance, and Accessibility sections of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`) against the current codebase. [Paste the exact checklist section text here.] Run all tests, linters, and accessibility checks. Report back with a final pass/fail."

2. **Cipher (Security Auditor)** — delegate to the **Cipher** agent (Stage 2)
   - **Assignment**: `Security` checklist.
   - **Prompt**: "Execute the Security section of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`) against the current codebase. [Paste the exact checklist section text here.] Scan for vulnerabilities, check CORS and headers, and verify auth routes. Report back with a final pass/fail."

3. **Dep (DevOps Engineer)** — delegate to the **Dep** agent (Stage 2)
   - **Assignment**: `Infrastructure`, `Feature Flag Strategy`, `Staged Rollout`, and `Monitoring`.
   - **Prompt**: "Execute the Infrastructure, Feature Flags, and Monitoring sections of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`). [Paste the exact checklist section text here.] Verify production environment variables and define the Staged Rollout sequence. Compile the Emergency Rollback Plan and your `GO`/`NO-GO` verdict into `.docs/{project-name}/implementation/ship-decision.md`. Report back with your findings."

### Step 3: Wait and Block
Read the returned handoffs as each stage completes — Vera's after Stage 1, then Cipher's and Dep's after Stage 2. All three must be in hand before you proceed.
- If any agent reports a failure (e.g., failing tests, high vulnerabilities), you must **BLOCK** the deployment and inform the user of the specific failure.
- You may route the failure to Mason or Max via `/bgpdd-build` to fix the issue, but you cannot proceed until the Launch Squad is fully green.
- **Fix-routing bound**: At most **2 fix-and-reverify rounds per failing checklist area**. If an area is still failing after 2 rounds, **HALT** — surface the area, both fix attempts, and the failing evidence to the user. Do NOT route a third time.

### Step 3.5: Requirements Coverage Gate
Before compiling documentation:
1. Execute the coverage tool via a shell action, using the runtime's available Python 3 interpreter (`python` or `python3`):
   `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --test-report .docs/{project-name}/implementation/test-report.md`
   The full CLI contract (JSON shape, exit codes, parsing rules) lives in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
2. Read the JSON object from stdout. Exit code 0 = every Must-Have `FR`/`NFR` has at least one passing test or check recorded in the test report — report any `warnings` and `uncovered_should` entries as non-blocking notes, then proceed to Step 4. Exit code 1 = the `uncovered` array lists the Must-Have gaps. Exit code 2 = the artifact failed its structural contract (e.g. no Must-Have IDs, unreadable report) — treat this as a defect in the artifact, not the tool.
3. On exit 1 or 2, **BLOCK** and route back to `/bgpdd-build` Phase 2 (Testing) with the exact `uncovered` IDs and `warnings` (or the `error` message) to close the gap. (This closes the requirement-traceability chain — Rex's `FR`/`NFR` → Alex's task → Quinn's test — at the final gate.)
4. **Fallback (no Python runtime)**: If the script cannot run because no Python 3 interpreter is available, verify manually instead: read `.docs/{project-name}/requirements.md` and `.docs/{project-name}/implementation/test-report.md`, and confirm every Must-Have `FR` and every Must-Have `NFR` has at least one passing test or check recorded in the test report; apply the same block-and-route rule as step 3.

### Step 4: Compile Documentation
Once the squad is fully green and coverage is verified, act as the Documenter:
- Update the `CHANGELOG.md` with all features implemented in Phase 2.
- Update the `README.md` if any deployment commands changed.

### Step 4.5: Open the Pull Request
Once the squad is fully green and documentation is compiled:
1. Push the working branch (the `branch` field from `orchestrator-state.json`; if absent, confirm the branch with the user — do NOT guess) to the remote.
2. Open a pull request via the user's git hosting tool. The PR description must summarize the epic, the FR/NFR coverage (from the Step 3.5 gate), and link to `.docs/{project-name}/implementation/ship-decision.md`.
3. If the runtime has the `github-pr-review` skill available, offer the user an automated multi-repo PR review pass.

### Step 5: Final Handoff
Present the user with the final "Launch Readiness Report", including the PR link(s) from Step 4.5. Clearly state that all checks have passed and provide the manual commands they need to run to trigger the production deployment.

### Step 6: Cleanup
Delete `.docs/{project-name}/orchestrator-state.json` — the pipeline lifecycle has successfully completed and the state is no longer needed. Delete ONLY that file: `.docs/{project-name}/implementation/game-tape.md` survives as the epic's durable record and is the primary input to Step 7.

### Step 6.5: Game Tape Checkpoint (Orchestrator)
No delegation, no halt — you perform this step directly, before briefing Forge:
1. Append a `## bgpdd-shipping — [date]` section to `.docs/{project-name}/implementation/game-tape.md` (create the file if the earlier phases did not). At most 10 bullets, covering: user corrections made, agent failures/retries, re-delegation rounds and why, circuit-breaker trips, gates that were rubber-stamped vs. genuinely exercised, and this session's id/transcript path if the runtime exposes it (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`).

### Step 7: Agent Improvement (Forge)
- **Delegated Agent**: **Forge** (System Coach). He reads his methodology dependencies (agent-orchestration-improve-agent) on-demand.
- **Workflow**:
  1. Delegate to the **Forge** agent. Brief him as the SINGLE end-of-epic improvement run — the per-phase pipelines no longer invoke Forge; their evidence has accumulated for him. Instruct him to read, in this order: (a) `.docs/{project-name}/implementation/game-tape.md` FIRST — the per-phase evidence checkpoints from `bgpdd-plan`, `bgpdd-build`, and this shipping run; (b) the durable reports — `.docs/{project-name}/implementation/review-report.md` and `test-report.md`; (c) optionally, the session transcripts listed in the game tape, under the `/bgpdd-learn` filtered-read rule: he must NEVER full-read a transcript file (transcripts embed every tool result) — grep targeted slices only (user messages, correction phrases, `<handoff>` blocks, error/circuit-breaker patterns, skill invocations), then read just those line ranges. Using those same session transcript paths and the filtered-read rule, spot-check that delegated agents actually READ their Always-tier Methodology Dependencies files: grep each subagent's transcript for Read (file-reading tool) calls against the exact dependency file paths listed in its `agents/<name>.md` table, and report any agent that skipped one as a finding. Instruct him to hunt cross-phase patterns specifically (e.g. build-phase failures that trace back to plan-phase gaps), and write proposed updates to `.docs/{project-name}/implementation/agent-improvements.md`.
  2. Read Forge's returned handoff.
  3. **HALT EXECUTION**. Explicitly ask the User to review and approve `agent-improvements.md`. Do NOT proceed until you have explicit human approval.
  4. Upon approval, re-delegate to a fresh **Forge** agent to apply the approved changes to the relevant `SKILL.md`/agent files by editing and writing them directly.
