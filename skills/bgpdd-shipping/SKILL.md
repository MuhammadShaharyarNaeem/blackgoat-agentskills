---
name: bgpdd-shipping
description: "Phase 3 of the Prompt-Driven Development SOP (Verification & Deployment). Orchestrates a dedicated Launch Squad (Vera, Cipher, and Dep) to execute the pre-launch checklist, harden the application, and orchestrate the final rollout."
trigger: /bgpdd-shipping
---

# bgpdd-shipping

## Purpose

To orchestrate Phase 3 of the Prompt-Driven Development (PDD) lifecycle. This skill acts as the final deployment gate. When invoked, it orchestrates a staged "Launch Squad": Vera runs Stage 1 alone, then Cipher and Dep run Stage 2 in parallel. It prevents unverified, unmonitored, or insecure code from reaching production.

## When to Use This Skill

- When `bgpdd-build` has successfully completed Phase 2 (Execution & CI/CD).
- When a major feature branch is ready to be merged to `main` and deployed to production.
- When the user explicitly requests to "launch", "ship", or "deploy" the application.
- Trigger phrases: `ship it`, `run bgpdd-shipping`, `launch the app`.

## Core Capabilities

1. **Launch Orchestration**: Delegates to a staged Launch Squad — Vera (Stage 1), then Cipher+Dep (Stage 2 in parallel) — against the `shipping-and-launch` checklists.
2. **Strict Gatekeeping**: Blocks final deployment until all 3 agents report a fully green checklist.
3. **Automated Documentation**: Compiles the final Changelog, README updates, and Emergency Rollback Plan based on agent reports.

---

## Path Resolution

Skill and agent paths use `{PLUGIN_ROOT}` as a placeholder for the plugin's `skills/` directory (agents live at `{PLUGIN_ROOT}/../agents/`). When this skill is invoked, its base directory is provided to you. List files to confirm a path exists before referencing it.

When you inject a resolved `base-persona.md` path into a delegation brief, it lives at `{PLUGIN_ROOT}/agent-squad/base-persona.md` — inside the `agent-squad` skill folder, NOT the `agents/` folder. The `agents/` folder holds ONLY persona files (`rex.md`, `alex.md`, `scout.md`, …); base-persona is a skill, not a persona. Injecting `{PLUGIN_ROOT}/../agents/base-persona.md` is the recurring defect that makes every delegated agent flag base-persona as missing. Verify the base-persona path resolves to an existing file before delegating.

---

## Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Step 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.

The sections below carry ONLY this pipeline's refinements on top of that contract. Read "phase" as "step" throughout the contract — this pipeline is step-sequenced.

- **Strict Delegation — this pipeline's agents**: Vera (Stage 1), Cipher and Dep (Stage 2, parallel). You MUST NOT roleplay the Launch Squad's work yourself.
- **Upgraded Chain-of-Thought**: Before each step, explicitly verify the required artifact exists.
  - *Format*: "Thinking: Step X requires Y. Checking `.docs/{project-name}/Y`... File exists and is populated. Proceeding."

## Global Error Recovery

**The error-recovery skeleton lives in the Orchestrator Contract (§2)** — halt-and-escalate triggers, the circuit breaker you pass to every agent, no-nested-delegation, incremental persistence, context checkpoints, and 2-round bounded autonomous rejection. Read it there; it is not restated here.

This pipeline's only refinement: agents here touch a shipping-ready codebase, so the incremental-persistence instruction you pass must cover **committing code changes to the working branch as they are made**, not only writing reports section by section — that is what makes the partial-work commit expectation below achievable rather than aspirational. Checkpoint your own state via `update_state.py` with `--set-pipeline bgpdd-shipping` — never hand-edit JSON. If Python is unavailable: HALT and surface the missing interpreter.

## Path Model

- **Tier 1 (global knowledge base)**: `.docs/summary/{feature}/` — produced ONLY by `/bgpdd-discovery`. Read-only in this pipeline, with **one narrow, deliberate exception (convention #8)**: Step 6.4 folds the proven acceptance results back into `.docs/summary/{feature}/QA/manual-testing.md`. This refines the read-only rule rather than breaking it — the write happens once, to one file, only after the launch squad is green, and only to record behavior that was just verified. The alternative is a baseline that rots after the first feature ships and a discovery re-run that re-derives it from scratch every time. Nothing else under `.docs/summary/` is ever written here.
- **Tier 2 (per-enhancement workspace)**: `.docs/{project-name}/` — this pipeline's read-write workspace (plan.md, test-report.md, verification-report.md, security-report.md, ship-decision.md, game-tape.md, orchestrator-state.json). Never write shipping artifacts to Tier 1.

---

## Execution Checklist

As the Orchestrator, you must follow these steps in exact order. Do not skip steps.

### Step 0: Hydration
1. Establish `{project-name}`: take it from the user, or list `.docs/` and confirm the correct project with the user. Do NOT guess.
2. Read `.docs/{project-name}/orchestrator-state.json` (if it exists) to restore context from `bgpdd-build`. The file follows the schema defined in `bgpdd-plan` Phase 4 (fields: `schema`, `project_name`, `feature`, `pipeline`, `branch`, `milestone_cursor`, `artifacts`, `blockers`, `updated`). Its `pipeline` must be `"bgpdd-build"` or `"bgpdd-shipping"` — a `"bgpdd-shipping"` value means a prior shipping session checkpointed its state here (per Global Error Recovery); resume from that state, do not halt. HALT (apply the Prerequisite Gate below) if `pipeline` holds any other value, or if `milestone_cursor` is a non-null milestone id — a milestone id means the build did not finish; `null` means build completed all milestones.
3. **Prerequisite Gate**: Verify that `.docs/{project-name}/implementation/plan.md` exists with ALL milestones marked `[x]`, and that `.docs/{project-name}/implementation/test-report.md` exists. If either check fails, HALT and instruct the user to complete `/bgpdd-build` first.
4. **Ship-decision entry ticket**: Require `.docs/{project-name}/implementation/ship-decision.md` from build Phase 5 (Dep's prep GO/NO-GO). Gate it mechanically — **the flags depend on the `pipeline` value you just hydrated in step 2**, because entry ticket and exit ticket are the same mutable file:
   - **Fresh run** (`pipeline` was `"bgpdd-build"`): the file still holds build's prep verdict, so require the GO.
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_ship_decision.py --report .docs/{project-name}/implementation/ship-decision.md --require-go`
     Exit 0 = prep GO present — proceed. Exit 1 = NO-GO or incomplete decision — HALT. Exit 2 = structural/missing.
   - **Resume** (`pipeline` was `"bgpdd-shipping"`): Stage 2 Dep has already rewritten this file, so its content is now an *exit* verdict, not an entry one. Run the **structural check only** — drop `--require-go`:
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_ship_decision.py --report .docs/{project-name}/implementation/ship-decision.md`
     Exit 0 = a well-formed decision (either verdict) — proceed into the pipeline; a standing `NO-GO` is the work this resume exists to finish, and Stage 2's refresh plus Step 3's `--require-go` exit ticket is what closes it. Exit 1/2 = malformed decision — HALT. **Do NOT apply `--require-go` here**: a legitimate NO-GO refresh would then block re-entry to the only stage that can resolve it, and the pipeline could never converge on its own output.
   - **If Python is unavailable: HALT** and surface the missing interpreter — no manual open-and-read substitute.
5. **Blockers Ledger Gate**: mechanical — no open-and-read substitute. Run:
   `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_blockers.py --state .docs/{project-name}/orchestrator-state.json`
   Exit 0 = empty `blockers` array — proceed. Exit 1 = standing blockers — HALT and list them from the JSON stdout. Exit 2 = structural. **If Python is unavailable: HALT** and surface the missing interpreter.

### Step 1: Read the Skill
Read the full `shipping-and-launch` skill located at `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`. Extract the exact text of each checklist section that each agent needs — you must paste that text into their delegation prompts as their Working Memory, not merely name the section.

### Step 2: Delegate the Launch Squad
Delegate to the following three agents in **two stages**. Each prompt MUST (a) include the exact checklist section text pasted from `shipping-and-launch`, (b) name the skill path `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md` so the agent can consult it, and (c) include the CRITICAL CIRCUIT BREAKER rule verbatim as worded in the Orchestrator Contract §2. Each agent returns its pass/fail `<handoff>` as its final message.

- **Stage 1 — Vera alone**: Delegate Vera first and wait for her handoff before starting Stage 2. Vera runs full builds and test suites that take file, build-output, and port locks; running scanners or infra verification concurrently against the same checkout causes lock collisions and flaky failures (especially on Windows).
- **Stage 2 — Cipher and Dep in parallel**: After Vera's handoff returns, delegate Cipher and Dep **in parallel** — start both delegations in a single batch.

1. **Vera (QA & Performance)** — delegate to the **Vera** agent (Stage 1)
   - **Assignment**: `Code Quality`, `Pre-Merge Local Runtime Smoke`, `Performance`, and `Accessibility` checklists.
   - **Prompt**: "Execute the Code Quality, **Pre-Merge Local Runtime Smoke**, Performance, and Accessibility sections of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`) against the current codebase. [Paste the exact checklist section text here.] Run all tests, linters, and accessibility checks — and **start the application and probe it**, per the Runtime Smoke section and your `runtime-evidence` dependency: a built codebase is not a running one, and every claim about behavior a client, person, or device can observe needs an out-of-process capture cited by path. Write your per-item report to `.docs/{project-name}/implementation/verification-report.md` per your persona's Verification Report contract, ending in the machine-read `**Verdict:**` line. Report back with a final pass/fail."
   - **CRITICAL PATHING**: Vera's report path above is mandatory — the Step 3 Report Gate reads that file, not her handoff.
   - **Do not drop the Runtime Smoke section from the paste.** It is the only item in her assignment that requires a *started* application, and it is the section that would have caught the 2026-08 response-envelope escape. Omitting it silently returns this pipeline to build-and-lint verification.

2. **Cipher (Security Auditor)** — delegate to the **Cipher** agent (Stage 2)
   - **Assignment**: `Security` checklist.
   - **Prompt**: "Execute the Security section of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`) against the current codebase. [Paste the exact checklist section text here.] Scan for vulnerabilities, check CORS and headers, and verify auth routes. Append your audit round to `.docs/{project-name}/implementation/security-report.md` per your persona's Security Report contract, ending in the machine-read `**Verdict:**` line. Report back with a final pass/fail."
   - **CRITICAL PATHING**: Cipher's report path above is mandatory — the Step 3 Report Gate reads that file, not his handoff.

3. **Dep (DevOps Engineer)** — delegate to the **Dep** agent (Stage 2)
   - **Assignment**: `Infrastructure`, `Feature Flag Strategy`, `Staged Rollout`, and `Monitoring`.
   - **Prompt**: "Execute the Infrastructure, Feature Flags, and Monitoring sections of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`). [Paste the exact checklist section text here.] Verify production environment variables and define the Staged Rollout sequence. **Refresh/re-verify** `.docs/{project-name}/implementation/ship-decision.md` for final launch — build Phase 5 wrote the prep GO that was this pipeline's Step 0.4 entry ticket; your refreshed GO is the Step 3 exit ticket. Either rewrite the file or append a new dated verdict section; the gate reads the LAST verdict-bearing section, so both converge. What it rejects is one section stating both GO and NO-GO. Compile the Emergency Rollback Plan and your final `GO`/`NO-GO` verdict into that same path. Report back with your findings."

### Step 3: Wait and Block
Read the returned handoffs as each stage completes — Vera's after Stage 1, then Cipher's and Dep's after Stage 2. All three must be in hand before you proceed.
- **Report Gate (mechanical)**: a "pass" in Vera's or Cipher's handoff is a claim, not evidence — the report file is the evidence, and you verify it with the gate tool, never by accepting the handoff at face value. Once their handoffs are in hand, execute the gate via a shell action, using the runtime's available Python 3 interpreter (`python` or `python3`), once per report:
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_agent_report.py --report .docs/{project-name}/implementation/verification-report.md`
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_agent_report.py --report .docs/{project-name}/implementation/security-report.md`
  The full CLI contract (JSON shape, exit codes, parsing rules) lives in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`. Exit code 0 = the report's verdict is a machine-read `Pass` backed by evidenced check lines and zero Critical findings — proceed. Exit code 1 = **BLOCK**: the JSON body names the failing/blocked/unrun/unevidenced items and Critical findings — route per the failure rules below. Exit code 2 = the report is missing or structurally non-conforming — treat this as a defect in the agent's artifact, not the tool: route back to that agent to produce a conforming report (this counts as a fix-and-reverify round).
  - **If Python is unavailable: HALT** and surface the missing interpreter — do not substitute a manual judgment path for a mechanical gate.
- **Runtime Evidence Gate (mechanical)**: `check_agent_report.py` verifies Vera's verdict is backed by evidenced check lines with exit codes — it does **not** verify that anything was ever started. Run this once Stage 1's report is in hand, and again after any fix round:
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_runtime_evidence.py --report .docs/{project-name}/implementation/verification-report.md --milestone "<the epic or feature name Vera scoped her report to>" --changed-files <the epic's changed-files union> --repo . [--require-key <k> ...] [--forbid-host <pattern> ...] [--require-openapi-reachable]`
  Pass `--require-openapi-reachable` when the epic touched an API surface — at shipping it is the cheapest available proof that the thing Vera probed was a started application and not a test host. The `--milestone` token must match the scope Vera wrote into her captures' `Milestone:` field — at shipping that is the epic, not a single build milestone, so brief her with the exact string you will pass. Exit 0 = at least one fresh out-of-process capture backs her runtime claims — proceed. Exit 1 = **BLOCK** and route per the failure rules below. Exit 2 = a capture is structurally non-conforming — route back to Vera. Full CLI contract: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
  - **If the application cannot be started out-of-process in this environment**, do NOT loop against a gate it cannot pass: **HALT** and surface that launch verification was necessarily in-process only. A release is never shipped on in-process-only evidence — the same line `bgpdd-build` §1 holds for a milestone commit.
  - **If Python is unavailable: HALT.**
- **Ship-decision exit ticket (Dep)**: after Vera/Cipher's `check_agent_report` gates pass, gate Dep's refreshed ship-decision before Step 4:
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_ship_decision.py --report .docs/{project-name}/implementation/ship-decision.md --require-go`
  Exit 0 = final GO — proceed. Exit 1/2 = BLOCK. On a `NO-GO`, route per the failure rules below and re-run this gate after Dep's refresh — the gate reads the LAST verdict-bearing section, so an appended fix round supersedes the earlier verdict rather than reading as ambiguity. **If Python is unavailable: HALT.**
- If any agent reports a failure (e.g., failing tests, high vulnerabilities), you must **BLOCK** the deployment and inform the user of the specific failure.
- You may route the failure to the milestone's builder via `/bgpdd-build` to fix the issue, but you cannot proceed until the Launch Squad is fully green.
- **Fix-routing bound**: At most **2 fix-and-reverify rounds per failing checklist area**. If an area is still failing after 2 rounds, **HALT** — surface the area, both fix attempts, and the failing evidence to the user. Do NOT route a third time.
- After any fix round, the re-verifying agent appends a fresh report section and you re-run the Report Gate — a verdict written against the pre-fix code never carries forward.

### Step 3.5: Requirements Coverage Gate
Before compiling documentation:
1. Execute the coverage tool via a shell action, using the runtime's available Python 3 interpreter (`python` or `python3`):
   `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --test-report .docs/{project-name}/implementation/test-report.md`
   The full CLI contract (JSON shape, exit codes, parsing rules) lives in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
2. Read the JSON object from stdout. Exit code 0 = every Must-Have `FR`/`NFR` has at least one passing test or check recorded in the test report — report any `warnings` and `uncovered_should` entries as non-blocking notes, then proceed to Step 4. Exit code 1 = the `uncovered` array lists the Must-Have gaps. Exit code 2 = the artifact failed its structural contract (e.g. no Must-Have IDs, unreadable report) — treat this as a defect in the artifact, not the tool.
3. On exit 1 or 2, **BLOCK** and route back to `/bgpdd-build` Phase 2 (Testing) with the exact `uncovered` IDs and `warnings` (or the `error` message) to close the gap. (This closes the requirement-traceability chain — Rex's `FR`/`NFR` → Alex's task → Quinn's test — at the final gate.)
4. **If Python is unavailable: HALT** and surface the missing interpreter — do not substitute a manual judgment path for a mechanical gate.

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

### Step 6.4: Refresh the Legacy QA Baseline (Orchestrator)
No delegation, no halt — you perform this step directly. **This is the one sanctioned write to Tier 1** (see Path Model, and the named divergence there).

1. Read `.docs/{project-name}/acceptance-matrix.md` and `.docs/{project-name}/implementation/acceptance-results.md`. If either is absent — a lite or pre-matrix epic — skip this step and say so in the Step 6.5 game tape.
2. Fold them into `.docs/summary/{feature}/QA/manual-testing.md`, preserving Echo's format exactly (strict `GO → DO → ASSERT` tables, Happy Path / Edge Cases / Negative / Regression Risks categories, P0/P1/P2 flags, preconditions, `[ ] Pass [ ] Fail` checkboxes — the shape `evals/contract/echo-qa-discovery-shape` asserts). Concretely: scenarios that **passed** become or update baseline cases; cases Alex marked **invalidated** or **superseded** during his Baseline Reconciliation are removed or rewritten to match the behavior that now ships.
3. **Record only what was proven.** A scenario that was `BLOCKED`, `NOT RUN`, or never executed does not enter the baseline — an unverified case written into the durable baseline is worse than an absent one, because the next feature's discovery run will trust it.
4. Note in the game tape what you changed, so the next discovery run can tell a refreshed baseline from an original one.

**Why this exception exists**: without it the baseline captures only how the system behaved before the *first* feature ever shipped, every subsequent discovery run re-derives it from scratch, and Alex's reconciliation duty compares against a document that is progressively more wrong. The write is narrow by construction — one file, once, post-proof, recording only verified behavior.

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
