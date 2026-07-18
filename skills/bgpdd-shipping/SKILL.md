---
name: bgpdd-shipping
description: "Phase 3 of the Prompt-Driven Development SOP (Verification & Deployment). Orchestrates a dedicated Launch Squad (Quinn, Cipher, and Dep) to execute the pre-launch checklist, harden the application, and orchestrate the final rollout."
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

---

## Global System Constraints

- **Strict Delegation**: You are a MANAGER. You MUST NOT roleplay the Launch Squad's work yourself — this collapses your context window. For each step, delegate to the named agent (e.g. Quinn). The agent runs to completion in its own context and returns its `<handoff>` summary as its final message — that returned text is what you read to continue. You cannot message a running agent; each delegation is a single self-contained task.
- **Phase Transitions**: Never advance to the next step until the user explicitly types 'proceed', 'approved', or similar confirmation.
- **Upgraded Chain-of-Thought**: Before each step, explicitly verify the required artifact exists.
  - *Format*: "Thinking: Step X requires Y. Checking `.docs/{project-name}/Y`... File exists and is populated. Proceeding."
- **Strict Progressive Disclosure (Working Memory)**: Never pass the entire project history or the full `.docs/` folder to a delegated agent. Extract and pass ONLY the specific "Working Memory" chunk it needs. Overloading context causes downstream hallucination.

## Global Error Recovery

If *any* delegated agent (or you, the Orchestrator) exhibits the following behaviors:
1. Gets stuck in a continuous tool-call loop without making progress.
2. Hallucinates a file path that does not exist.
3. Fails to complete its objective after 3 consecutive attempts.

**ACTION**: You MUST immediately halt execution, output a structured state summary of what went wrong, and request explicit human intervention. Do not guess or bypass the failure silently. (A delegated agent terminates on its own when it returns — there is no separate "kill" step; simply stop delegating and escalate.)

**CRITICAL CIRCUIT BREAKER**: You must pass the following rule to every delegated agent in its prompt: "If you encounter the exact same error or test failure 3 times in a row, you MUST stop, document the failure state clearly in your `<handoff>` (what you tried and the exact error), and return immediately to escalate to the Orchestrator. Do NOT attempt a 4th fix."

**CONTEXT CHECKPOINTS**: If a worker cannot finish in one run, it commits its partial work and returns a `<handoff>` describing the remaining work; **you** then re-delegate a fresh agent with that handoff. If *your own* context grows large, checkpoint to `.docs/{project-name}/orchestrator-state.json` so a fresh session can resume.

---

## Execution Checklist

As the Orchestrator, you must follow these steps in exact order. Do not skip steps.

### Step 0: Hydration
1. Establish `{project-name}`: take it from the user, or list `.docs/` and confirm the correct project with the user. Do NOT guess.
2. Read `.docs/{project-name}/orchestrator-state.json` (if it exists) to restore context from `bgpdd-build`.
3. **Prerequisite Gate**: Verify that `.docs/{project-name}/implementation/plan.md` exists with ALL milestones marked `[x]`, and that `.docs/{project-name}/implementation/test-report.md` exists. If either check fails, HALT and instruct the user to complete `/bgpdd-build` first.

### Step 1: Read the Skill
Read the full `shipping-and-launch` skill located at `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`. Extract the exact text of each checklist section that each agent needs — you must paste that text into their delegation prompts as their Working Memory, not merely name the section.

### Step 2: Delegate the Launch Squad
Delegate to the following three agents **in parallel** — start all three delegations in a single batch. Each prompt MUST (a) include the exact checklist section text pasted from `shipping-and-launch`, (b) name the skill path `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md` so the agent can consult it, and (c) include the CRITICAL CIRCUIT BREAKER rule verbatim. Each agent returns its pass/fail `<handoff>` as its final message.

1. **Quinn (QA & Performance)** — delegate to the **Quinn** agent
   - **Assignment**: `Code Quality`, `Performance`, and `Accessibility` checklists.
   - **Prompt**: "This is Mode C — Launch Verification (not Mode A or B). Execute the Code Quality, Performance, and Accessibility sections of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`) against the current codebase. [Paste the exact checklist section text here.] Run all tests, linters, and accessibility checks. Report back with a final pass/fail."

2. **Cipher (Security Auditor)** — delegate to the **Cipher** agent
   - **Assignment**: `Security` checklist.
   - **Prompt**: "Execute the Security section of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`) against the current codebase. [Paste the exact checklist section text here.] Scan for vulnerabilities, check CORS and headers, and verify auth routes. Report back with a final pass/fail."

3. **Dep (DevOps Engineer)** — delegate to the **Dep** agent
   - **Assignment**: `Infrastructure`, `Feature Flag Strategy`, `Staged Rollout`, and `Monitoring`.
   - **Prompt**: "Execute the Infrastructure, Feature Flags, and Monitoring sections of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`). [Paste the exact checklist section text here.] Verify production environment variables and define the Staged Rollout sequence. Compile the Emergency Rollback Plan and your `GO`/`NO-GO` verdict into `.docs/{project-name}/implementation/ship-decision.md`. Report back with your findings."

### Step 3: Wait and Block
Read all three agents' returned handoffs.
- If any agent reports a failure (e.g., failing tests, high vulnerabilities), you must **BLOCK** the deployment and inform the user of the specific failure.
- You may route the failure to Mason or Max via `/bgpdd-build` to fix the issue, but you cannot proceed until the Launch Squad is fully green.

### Step 3.5: Requirements Coverage Gate
Before compiling documentation:
1. Read `.docs/{project-name}/requirements.md` and `.docs/{project-name}/implementation/test-report.md`.
2. Verify that every **Must-Have `FR`** and every **Must-Have `NFR`** has at least one passing test or check recorded in the test report.
3. If any Must-Have requirement is uncovered, **BLOCK** and route back to `/bgpdd-build` Phase 2 (Testing) to close the gap. (This closes the requirement-traceability chain — Rex's `FR`/`NFR` → Alex's task → Quinn's test — at the final gate.)

### Step 4: Compile Documentation
Once the squad is fully green and coverage is verified, act as the Documenter:
- Update the `CHANGELOG.md` with all features implemented in Phase 2.
- Update the `README.md` if any deployment commands changed.

### Step 5: Final Handoff
Present the user with the final "Launch Readiness Report". Clearly state that all checks have passed and provide the manual commands they need to run to trigger the production deployment.

### Step 6: Cleanup
Delete `.docs/{project-name}/orchestrator-state.json` — the pipeline lifecycle has successfully completed and the state is no longer needed.

### Step 7: Agent Improvement (Forge)
- **Delegated Agent**: **Forge** (System Coach). He reads his methodology dependencies (agent-orchestration-improve-agent) on-demand.
- **Workflow**:
  1. Delegate to the **Forge** agent. Instruct him to analyze the launch run (agent handoffs, blockers, checklist failures) and write proposed updates to `.docs/{project-name}/implementation/agent-improvements.md`.
  2. Read Forge's returned handoff.
  3. **HALT EXECUTION**. Explicitly ask the User to review and approve `agent-improvements.md`. Do NOT proceed until you have explicit human approval.
  4. Upon approval, re-delegate to a fresh **Forge** agent to apply the approved changes to the relevant `SKILL.md`/agent files by editing and writing them directly.
