---
name: bgpdd-shipping
description: "Phase 3 of the Prompt-Driven Development SOP (Verification & Deployment). Orchestrates a dedicated Launch Squad (Vera, Cipher, and Dep) to execute the pre-launch checklist, harden the application, and orchestrate the final rollout."
trigger: /bgpdd-shipping
---

# bgpdd-shipping

## Purpose

Phase 3 of the Prompt-Driven Development lifecycle: the final deployment gate. Orchestrates a staged Launch Squad — Vera alone in Stage 1, then Cipher and Dep in parallel in Stage 2 — so unverified, unmonitored, or insecure code never reaches production.

## When to Use This Skill

- `/bgpdd-build` (Phase 2 of the PDD SOP — the execution pipeline) has completed all milestones.
- A major feature branch is ready to be merged to `main` and deployed to production.
- The user explicitly requests to "launch", "ship", or "deploy" the application.
- Trigger phrases: `ship it`, `run bgpdd-shipping`, `launch the app`.

---

## Path Resolution

`{PLUGIN_ROOT}` = the plugin's `skills/` directory (this skill's base directory is provided to you); personas live at `{PLUGIN_ROOT}/../agents/`. Every other path rule — list-before-reference, and the base-persona injection guard — has ONE home: `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md`, **Path Resolution** (inside your mandatory first read).

---

## Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Step 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.

Below: this pipeline's refinements on that contract only. Read "phase" as "step" throughout the contract — this pipeline is step-sequenced.

- **Strict Delegation — this pipeline's agents**: Vera (Stage 1), Cipher and Dep (Stage 2, parallel). NEVER roleplay the Launch Squad's work yourself.
- **Upgraded Chain-of-Thought**: before each step, explicitly verify the required artifact exists.
  - *Format*: "Thinking: Step X requires Y. Checking `.docs/{project-name}/Y`... File exists and is populated. Proceeding."

## Global Error Recovery

**The error-recovery skeleton lives in the Orchestrator Contract (§2)** — halt-and-escalate triggers, the circuit breaker you pass to every agent, no-nested-delegation, incremental persistence, context checkpoints, and 2-round bounded autonomous rejection. Read it there; it is not restated here.

This pipeline's only refinement: agents here touch a shipping-ready codebase, so the incremental-persistence instruction you pass MUST cover **committing code changes to the working branch as they are made**, not only writing reports section by section — that is what makes the partial-work commit expectation achievable. Checkpoint your own state via `update_state.py` with `--set-pipeline bgpdd-shipping` — never hand-edit JSON. **If Python is unavailable: HALT** and surface the missing interpreter.

## Path Model

- **Tier 1 (global knowledge base)**: `.docs/summary/{feature}/` — produced ONLY by `/bgpdd-discovery`. Read-only here, with **one narrow, deliberate exception (convention #8)**: Step 6.4 folds the proven acceptance results back into `.docs/summary/{feature}/QA/manual-testing.md`. The write happens once, to one file, only after the launch squad is green, and only to record behavior that was just verified — a refinement of the read-only rule, not a break in it ([rationale](references/shipping-rationale.md#tier-1-refresh-exception)). Nothing else under `.docs/summary/` is ever written here.
- **Tier 2 (per-enhancement workspace)**: `.docs/{project-name}/` — this pipeline's read-write workspace (plan.md, test-report.md, verification-report.md, security-report.md, ship-decision.md, game-tape.md, orchestrator-state.json). NEVER write shipping artifacts to Tier 1.

---

## Execution Checklist

Follow these steps in exact order. Do not skip steps.

### Step 0: Hydration
1. Establish `{project-name}`: take it from the user, or list `.docs/` and confirm the correct project with them. NEVER guess.
2. Read `.docs/{project-name}/orchestrator-state.json` if it exists, to restore context from `bgpdd-build`. Schema: `bgpdd-plan` Phase 4 — fields `schema`, `project_name`, `feature`, `pipeline`, `branch`, `milestone_cursor`, `artifacts`, `blockers`, `updated`.

   | Hydrated state | Action |
   |---|---|
   | `pipeline` = `"bgpdd-build"` | Fresh run — proceed |
   | `pipeline` = `"bgpdd-shipping"` | A prior shipping session checkpointed its state here (per Global Error Recovery) — resume from it, do not halt |
   | `pipeline` = any other value | HALT — apply the Prerequisite Gate below |
   | `milestone_cursor` = a milestone id | The build did not finish — HALT, apply the Prerequisite Gate. `null` means build completed all milestones |
3. **Prerequisite Gate**: verify `.docs/{project-name}/implementation/plan.md` exists with ALL milestones marked `[x]`, and `.docs/{project-name}/implementation/test-report.md` exists. Either check fails → HALT and instruct the user to complete `/bgpdd-build` first.
4. **Ship-decision entry ticket**: require `.docs/{project-name}/implementation/ship-decision.md` from build Phase 5 (Dep's prep GO/NO-GO). Gate it mechanically — **the flags depend on the `pipeline` value you just hydrated in step 2**, because entry ticket and exit ticket are the same mutable file ([rationale](references/shipping-rationale.md#ship-decision-flags-differ-between-a-fresh-run-and-a-resume)):
   - **Fresh run** (`pipeline` was `"bgpdd-build"`) — the file still holds build's prep verdict, so require the GO:
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_ship_decision.py --report .docs/{project-name}/implementation/ship-decision.md --require-go`
     Exit 0 = prep GO present — proceed. Exit 1 = NO-GO or incomplete decision — HALT. Exit 2 = structural/missing.
   - **Resume** (`pipeline` was `"bgpdd-shipping"`) — Stage 2 Dep has already rewritten this file, so its content is now an *exit* verdict. Run the **structural check only**, dropping `--require-go`:
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_ship_decision.py --report .docs/{project-name}/implementation/ship-decision.md`
     Exit 0 = a well-formed decision, either verdict — proceed; a standing `NO-GO` is the work this resume exists to finish, closed by Stage 2's refresh plus Step 3's `--require-go` exit ticket. Exit 1/2 = malformed — HALT. **NEVER apply `--require-go` here.**
   - **If Python is unavailable: HALT** and surface the missing interpreter — no manual open-and-read substitute.
5. **Blockers Ledger Gate** — mechanical, no open-and-read substitute:
   `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_blockers.py --state .docs/{project-name}/orchestrator-state.json`
   Exit 0 = empty `blockers` array — proceed. Exit 1 = standing blockers — HALT and list them from the JSON stdout. Exit 2 = structural. **If Python is unavailable: HALT.**

### Step 1: Read the Skill
Read the full `shipping-and-launch` skill at `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`. Extract the exact text of each checklist section each agent needs — you MUST paste that text into their delegation prompts as their Working Memory; naming the section is not enough.

### Step 2: Delegate the Launch Squad
Delegate three agents in **two stages**. Each prompt MUST (a) include the exact checklist section text pasted from `shipping-and-launch`, (b) name the skill path `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md` so the agent can consult it, and (c) include the CRITICAL CIRCUIT BREAKER rule verbatim as worded in the Orchestrator Contract §2. Each agent returns its pass/fail `<handoff>` as its final message.

- **Stage 1 — Vera alone**: delegate Vera first and wait for her handoff before starting Stage 2. Her builds and test suites take file, build-output, and port locks that a concurrent scanner or infra check would collide with ([rationale](references/shipping-rationale.md#stage-1-runs-alone)).
- **Stage 2 — Cipher and Dep in parallel**: after Vera's handoff returns, start both delegations in a single batch.

1. **Vera (QA & Performance)** — delegate to the **Vera** agent (Stage 1)
   - **Assignment**: `Code Quality`, `Pre-Merge Local Runtime Smoke`, `Performance`, and `Accessibility` checklists.
   - **Prompt**: "Execute the Code Quality, **Pre-Merge Local Runtime Smoke**, Performance, and Accessibility sections of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`) against the current codebase. [Paste the exact checklist section text here.] Run all tests, linters, and accessibility checks — and **start the application and probe it**, per the Runtime Smoke section and your `runtime-evidence` dependency: a built codebase is not a running one, and every claim about behavior a client, person, or device can observe needs an out-of-process capture cited by path. Start it from the environment manifest at `artifacts.environment_manifest` (inject the resolved path; `bgpdd-build` Phase 0 wrote it) — start commands, local base URLs, the repointing map and the forbidden hosts all come from there and none of them is yours to infer. If that artifact is `null` or absent, say so and report the affected checks `BLOCKED` rather than reconstructing the estate from the repo. Write your per-item report to `.docs/{project-name}/implementation/verification-report.md` per your persona's Verification Report contract, ending in the machine-read `**Verdict:**` line. Report back with a final pass/fail."
   - **CRITICAL PATHING**: Vera's report path above is mandatory — the Step 3 Report Gate reads that file, not her handoff.
   - **NEVER drop the Runtime Smoke section from the paste.** It is the only item in her assignment that requires a *started* application; omitting it silently returns this pipeline to build-and-lint verification ([the 2026-08 escape](references/shipping-rationale.md#runtime-smoke)).

2. **Cipher (Security Auditor)** — delegate to the **Cipher** agent (Stage 2)
   - **Assignment**: `Security` checklist.
   - **Prompt**: "Execute the Security section of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`) against the current codebase. [Paste the exact checklist section text here.] Scan for vulnerabilities, check CORS and headers, and verify auth routes. Append your audit round to `.docs/{project-name}/implementation/security-report.md` per your persona's Security Report contract, ending in the machine-read `**Verdict:**` line. Report back with a final pass/fail."
   - **CRITICAL PATHING**: Cipher's report path above is mandatory — the Step 3 Report Gate reads that file, not his handoff.

3. **Dep (DevOps Engineer)** — delegate to the **Dep** agent (Stage 2)
   - **Assignment**: `Infrastructure`, `Feature Flag Strategy`, `Staged Rollout`, and `Monitoring and Observability`.
   - **Prompt**: "Execute the Infrastructure, Feature Flag Strategy, and Monitoring and Observability sections of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`). [Paste the exact checklist section text here.] Verify production environment variables and define the Staged Rollout sequence. **Refresh/re-verify** `.docs/{project-name}/implementation/ship-decision.md` for final launch — build Phase 5 wrote the prep GO that was this pipeline's Step 0.4 entry ticket; your refreshed GO is the Step 3 exit ticket. Either rewrite the file or append a new dated verdict section; the gate reads the LAST verdict-bearing section, so both converge. What it rejects is one section stating both GO and NO-GO. Compile the Emergency Rollback Plan and your final `GO`/`NO-GO` verdict into that same path. Report back with your findings."

### Step 3: Wait and Block
Read the returned handoffs as each stage completes — Vera's after Stage 1, then Cipher's and Dep's after Stage 2. All three must be in hand before you proceed.

- **Report Gate (mechanical)**: a "pass" in Vera's or Cipher's handoff is a claim; the report file is the evidence. NEVER accept the handoff at face value. Once both handoffs are in hand, run the gate via a shell action using the runtime's available Python 3 interpreter (`python` or `python3`), once per report:
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_agent_report.py --report .docs/{project-name}/implementation/verification-report.md`
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_agent_report.py --report .docs/{project-name}/implementation/security-report.md`
  Exit 0 = the verdict is a machine-read `Pass` backed by evidenced check lines with zero Critical findings — proceed. Exit 1 = **BLOCK**: the JSON body names the failing/blocked/unrun/unevidenced items and Critical findings — route per the failure rules below. Exit 2 = report missing or structurally non-conforming — a defect in the agent's artifact, not the tool: route back to that agent for a conforming report (counts as a fix-and-reverify round). Full CLI contract: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`. **If Python is unavailable: HALT** — never substitute a manual judgment path for a mechanical gate.
- **Runtime Evidence Gate (mechanical)**: `check_agent_report.py` verifies Vera's verdict is backed by evidenced check lines with exit codes — it does **not** verify anything was ever started. Run once Stage 1's report is in hand, and again after any fix round:
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_runtime_evidence.py --report .docs/{project-name}/implementation/verification-report.md --milestone "<the epic or feature name Vera scoped her report to>" --changed-files <the epic's changed-files union> --repo . [--require-key <k> ...] [--forbid-host <pattern> ...] [--require-openapi-reachable]`
  - Pass `--require-openapi-reachable` when the epic touched an API surface — at shipping it is the cheapest available proof that what Vera probed was a started application and not a test host.
  - The `--milestone` token MUST match the scope Vera wrote into her captures' `Milestone:` field — at shipping that is the epic, not a single build milestone. Brief her with the exact string you will pass.
  - **Deliberately without `--surface`/`--expect-status`** (convention #8, same divergence class as the `--milestone` scope above): both are per-capture, per-milestone assertions, and an epic's captures span milestones with different surfaces and statuses, so no single value could hold across the whole re-run. `--require-key` and `--forbid-host` survive because they assert content meant to hold uniformly ([rationale](references/shipping-rationale.md#why-the-runtime-evidence-gate-omits---surface-and---expect-status)).
  - Exit 0 = at least one fresh out-of-process capture backs her runtime claims — proceed. Exit 1 = **BLOCK**, route per the failure rules below. Exit 2 = a capture is structurally non-conforming — route back to Vera. Full CLI contract: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
  - **If the application cannot be started out-of-process in this environment**: do NOT loop against a gate it cannot pass — **HALT** and surface that launch verification was necessarily in-process only. A release is never shipped on in-process-only evidence, the same line `bgpdd-build` §1 holds for a milestone commit.
  - **If Python is unavailable: HALT.**
- **Acceptance Suite Regression Gate (mechanical)**: `check_acceptance_suite.py` is documented (`{PLUGIN_ROOT}/pipeline-tools/SKILL.md`, `planning-and-task-breakdown/SKILL.md`) as running "again at `bgpdd-shipping` Stage 1 as regression" — this is that invocation, once the gates above are in hand. Resolve the matrix path from `artifacts.acceptance_matrix` on the state hydrated in Step 0. **JSON `null`** (a lite-originated epic with no matrix) → skip this gate and say so explicitly to the user; NEVER re-derive from file absence (deliberately stricter than `bgpdd-build` Hydration's absent-*key* fallback — convention #8: by shipping time the state file is current-schema, so a `null` is a recorded decision, not missing data). Otherwise re-run the walkthrough against the existing results at the same priority scope build used:
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_acceptance_suite.py --matrix <artifacts.acceptance_matrix> --results .docs/{project-name}/implementation/acceptance-results.md --repo . [--require-priority P0,P1]`
  Exit 0 = the feature-scoped walkthrough still holds at shipping — proceed. Exit 1 = **BLOCK**: the JSON names the missing/failing/unevidenced steps; a failure here is a regression since build — route per the failure rules below with the same weight as a fresh Vera/Cipher finding. Exit 2 = matrix or results structurally non-conforming — an artifact defect: route back to Alex (matrix) or Quinn (results) via `/bgpdd-build`. **If Python is unavailable: HALT.**
- **Ship-decision exit ticket (Dep)**: after Vera's and Cipher's `check_agent_report` gates pass, gate Dep's refreshed decision before Step 4:
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_ship_decision.py --report .docs/{project-name}/implementation/ship-decision.md --require-go`
  Exit 0 = final GO — proceed. Exit 1/2 = BLOCK. On a `NO-GO`, route per the failure rules below and re-run this gate after Dep's refresh — the gate reads the LAST verdict-bearing section, so an appended fix round supersedes the earlier verdict rather than reading as ambiguity. **If Python is unavailable: HALT.**

**Failure rules**
- Any agent reporting a failure (failing tests, high vulnerabilities) → **BLOCK** the deployment and inform the user of the specific failure.
- You may route the failure to the milestone's builder via `/bgpdd-build`, but you cannot proceed until the Launch Squad is fully green.
- **Fix-routing bound**: at most **2 fix-and-reverify rounds per failing checklist area**. Still failing after 2 rounds → **HALT** and surface the area, both fix attempts, and the failing evidence. NEVER route a third time.
- After any fix round, the re-verifying agent appends a fresh report section and you re-run the Report Gate — a verdict written against the pre-fix code never carries forward.

### Step 3.5: Requirements Coverage Gate
Before compiling documentation:
1. Run via a shell action, using the runtime's available Python 3 interpreter (`python` or `python3`):
   `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --test-report .docs/{project-name}/implementation/test-report.md`
   Full CLI contract: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
2. Read the JSON object from stdout. Exit 0 = every Must-Have `FR`/`NFR` has at least one passing test or check in the test report — report `warnings` and `uncovered_should` as non-blocking notes, then proceed to Step 4. Exit 1 = the `uncovered` array lists the Must-Have gaps. Exit 2 = the artifact failed its structural contract (no Must-Have IDs, unreadable report) — a defect in the artifact, not the tool.
3. On exit 1 or 2: **BLOCK** and route back to `/bgpdd-build` Phase 2 (Testing) with the exact `uncovered` IDs and `warnings` (or the `error` message). This closes the requirement-traceability chain — Rex's `FR`/`NFR` → Alex's task → Quinn's test — at the final gate.
4. **If Python is unavailable: HALT** — never substitute a manual judgment path for a mechanical gate.

### Step 4: Compile Documentation
Once the squad is fully green and coverage is verified, act as the Documenter:
- Update `CHANGELOG.md` with all features implemented in Phase 2, executing `shipping-and-launch`'s `#### Documentation` checklist section (this step is that section's assigned owner — no Launch Squad agent carries it).
- Update `README.md` if any deployment commands changed.

### Step 4.5: Open the Pull Request
1. Push the working branch (the `branch` field from `orchestrator-state.json`; if absent, confirm the branch with the user — NEVER guess) to the remote.
2. Open a pull request via the user's git hosting tool. The PR description must summarize the epic, the FR/NFR coverage (from the Step 3.5 gate), and link to `.docs/{project-name}/implementation/ship-decision.md`.
3. If the runtime has the `github-pr-review` skill available, offer the user an automated multi-repo PR review pass.

### Step 5: Final Handoff
Present the final "Launch Readiness Report", including the Step 4.5 PR link(s). State that all checks have passed, and give the manual commands the user runs to trigger the production deployment.

### Step 6: Cleanup
**Capture what Step 6.4 needs before deleting.** `{feature}` and the resolved acceptance-matrix path (`artifacts.acceptance_matrix` on the state hydrated in Step 0) are recoverable only from `orchestrator-state.json`, and Step 6.4 runs after this step removes it — note both now if you have not already. Then delete `.docs/{project-name}/orchestrator-state.json`, and ONLY that file: `.docs/{project-name}/implementation/game-tape.md` survives as the epic's durable record and Step 7's primary input.

### Step 6.4: Refresh the Legacy QA Baseline (Orchestrator)
No delegation, no halt — you perform this step directly. **This is the one sanctioned write to Tier 1** (see Path Model, and the named divergence there).

1. Use the `artifacts.acceptance_matrix` path captured in Step 6 (or, when that field was absent at hydration, `.docs/{project-name}/acceptance-matrix.md`). Captured value is JSON `null` (a lite-originated epic) → skip this step and say so in the Step 6.5 game tape. Otherwise read that matrix file and `.docs/{project-name}/implementation/acceptance-results.md`; either absent — a lite or pre-matrix epic — → skip this step and say so in the Step 6.5 game tape.
2. Fold them into `.docs/summary/{feature}/QA/manual-testing.md`, preserving Echo's format exactly (strict `GO → DO → ASSERT` tables, Happy Path / Edge Cases / Negative / Regression Risks categories, P0/P1/P2 flags, preconditions, `[ ] Pass [ ] Fail` checkboxes — the shape `evals/contract/echo-qa-discovery-shape` asserts). Concretely: scenarios that **passed** become or update baseline cases; cases Alex marked **invalidated** or **superseded** during his Baseline Reconciliation are removed or rewritten to match the behavior that now ships.
3. **Record only what was proven.** A scenario that was `BLOCKED`, `NOT RUN`, or never executed NEVER enters the baseline — the next feature's discovery run will trust whatever is written there.
4. Note in the game tape what you changed, so the next discovery run can tell a refreshed baseline from an original one.

### Step 6.5: Game Tape Checkpoint (Orchestrator)
No delegation, no halt — you perform this step directly, before briefing Forge:
1. Append a `## bgpdd-shipping — [date]` section to `.docs/{project-name}/implementation/game-tape.md` (create the file if the earlier phases did not). At most 10 bullets, covering: user corrections made, agent failures/retries, re-delegation rounds and why, circuit-breaker trips, gates that were rubber-stamped vs. genuinely exercised, and this session's id/transcript path if the runtime exposes it (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`).

### Step 7: Agent Improvement (Forge)
- **Delegated Agent**: **Forge** (System Coach). He reads his methodology dependencies (`agent-orchestration-improve-agent`) on-demand.
- **Workflow**:
  1. Delegate to **Forge**, briefed as the SINGLE end-of-epic improvement run — the per-phase pipelines no longer invoke Forge; their evidence has accumulated for him. Instruct him to read, in this order:
     a. `.docs/{project-name}/implementation/game-tape.md` FIRST — the per-phase evidence checkpoints from `bgpdd-plan`, `bgpdd-build`, and this shipping run;
     b. the durable reports — `.docs/{project-name}/implementation/review-report.md` and `test-report.md`;
     c. optionally, the session transcripts listed in the game tape, under the `/bgpdd-learn` filtered-read rule: he must NEVER full-read a transcript file (transcripts embed every tool result) — grep targeted slices only (user messages, correction phrases, `<handoff>` blocks, error/circuit-breaker patterns, skill invocations), then read just those line ranges.

     From those same transcripts, under the same rule, he spot-checks that delegated agents actually READ their Always-tier Methodology Dependencies: grep each subagent's transcript for file-reading calls against the exact dependency paths in its `agents/<name>.md` table, and report any agent that skipped one as a finding. He hunts cross-phase patterns specifically (e.g. build-phase failures tracing back to plan-phase gaps), and writes proposed updates to `.docs/{project-name}/implementation/agent-improvements.md`.
  2. Read Forge's returned handoff.
  3. **HALT EXECUTION**. Explicitly ask the User to review and approve `agent-improvements.md`. Do NOT proceed until you have explicit human approval.
  4. Upon approval, re-delegate to a fresh **Forge** agent to apply the approved changes to the relevant `SKILL.md`/agent files by editing and writing them directly.
