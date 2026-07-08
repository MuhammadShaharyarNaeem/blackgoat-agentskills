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

## Execution Checklist

As the Orchestrator, you must follow these steps in exact order. Do not skip steps.

### Step 1: Read the Contract
Read the full contract located at `{PLUGIN_ROOT}/shipping-and-launch/shipping-contract.md`. You will use this contract to delegate tasks to your sub-agents.

### Step 2: Delegate the Launch Squad
Delegate to the following three agents **in parallel** — start all three delegations in a single batch. Pass each its exact checklist assignment in its delegation prompt. Each returns its pass/fail handoff as its final message.

1. **Quinn (QA & Performance)** — delegate to the **Quinn** agent
   - **Assignment**: `Code Quality`, `Performance`, and `Accessibility` checklists.
   - **Prompt**: "Execute the Code Quality, Performance, and Accessibility sections of the `shipping-and-launch` contract against the current codebase. Run all tests, linters, and accessibility checks. Report back with a final pass/fail."

2. **Cipher (Security Auditor)** — delegate to the **Cipher** agent
   - **Assignment**: `Security` checklist.
   - **Prompt**: "Execute the Security section of the `shipping-and-launch` contract against the current codebase. Scan for vulnerabilities, check CORS and headers, and verify auth routes. Report back with a final pass/fail."

3. **Dep (DevOps Engineer)** — delegate to the **Dep** agent
   - **Assignment**: `Infrastructure`, `Feature Flag Strategy`, `Staged Rollout`, and `Monitoring`.
   - **Prompt**: "Execute the Infrastructure, Feature Flags, and Monitoring sections of the `shipping-and-launch` contract. Verify production environment variables and define the Staged Rollout sequence. Compile the Emergency Rollback Plan into `.docs/{project-name}/rollback-plan.md`. Report back with your findings."

### Step 3: Wait and Block
Read all three agents' returned handoffs.
- If any agent reports a failure (e.g., failing tests, high vulnerabilities), you must **BLOCK** the deployment and inform the user of the specific failure.
- You may route the failure to Mason or Max via `/bgpdd-build` to fix the issue, but you cannot proceed to Step 4 until the Launch Squad is fully green.

### Step 4: Compile Documentation
Once the squad is fully green, act as the Documenter:
- Update the `CHANGELOG.md` with all features implemented in Phase 2.
- Update the `README.md` if any deployment commands changed.

### Step 5: Final Handoff
Present the user with the final "Launch Readiness Report". Clearly state that all checks have passed and provide the manual commands they need to run to trigger the production deployment.

### Step 6: Cleanup
Delete the `orchestrator-state.json` file as the pipeline lifecycle has successfully completed and the state is no longer needed.
