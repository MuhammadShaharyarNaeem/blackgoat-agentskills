---
name: bgpdd-shipping
description: "Phase 3 of the Prompt-Driven Development SOP (Verification & Deployment). Orchestrates a dedicated Launch Squad (Vera, Cipher, and Dep) to execute the pre-launch checklist, harden the application, and orchestrate the final rollout."
trigger: /bgpdd-shipping
---

# bgpdd-shipping

## Purpose

Phase 3 of the Prompt-Driven Development (PDD) lifecycle: the final deployment gate. It orchestrates a staged Launch Squad — Vera runs Stage 1 alone, then Cipher and Dep run Stage 2 in parallel — and prevents unverified, unmonitored, or insecure code from reaching production. Capabilities in full: `references/shipping-rationale.md` § Core capabilities, in full.

## When to Use This Skill

- When `bgpdd-build` has successfully completed Phase 2 (Execution & CI/CD).
- When a major feature branch is ready to be merged to `main` and deployed to production.
- When the user explicitly requests to "launch", "ship", or "deploy" the application.
- Trigger phrases: `ship it`, `run bgpdd-shipping`, `launch the app`.

---

## Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Step 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.
>
> Then read `{PLUGIN_ROOT}/agent-squad/pipeline-skeleton.md` — the shared pipeline skeleton (path resolution, error recovery, upgraded chain of thought, game tape). Refinements below override the skeleton only where labelled (convention #8).

The sections below carry ONLY this pipeline's refinements on top of that contract. Read "phase" as "step" throughout the contract — this pipeline is step-sequenced.

- **Strict Delegation — this pipeline's agents**: Vera (Stage 1), Cipher and Dep (Stage 2, parallel), a fresh Quinn for the Step 3 acceptance re-run, and a fresh Dep for the Step 5.5 post-deploy verification. You MUST NOT roleplay the Launch Squad's work yourself.

### Gate conventions (stated once; not restated per gate)

- **Every gate here is a Python 3 script.** The missing-interpreter HALT is Orchestrator Contract §1's Python-3 rule and governs every `pipeline-tools` invocation below.
- **Gate ledger path (this pipeline)**: every gate invocation below carries `--ledger .docs/{project-name}/implementation/gates.jsonl`. The obligation is Orchestrator Contract §4's; this binds only the path, so Step 6.5's game tape has one file to cite.
- **Full CLI contracts** — invocation, flags, JSON shape, exit codes, parsing rules — live in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`, the single authority. This pipeline states only how to *route* each verdict.
- **Exit-code routing, default**: **0** → proceed. **1** → **BLOCK** and route per Step 3's failure rules, quoting the JSON body's named arrays. **2** → **a defect in the producing agent's artifact, not in the tool** — route back to that agent for a conforming artifact, counting a fix-and-reverify round under Step 3's bound. Gates that route differently say so at their call site.

## Global Error Recovery

**Refinement of Orchestrator Contract §2 (skeleton owns the rest):** the incremental-persistence instruction you pass must cover **committing code changes to the working branch as they are made**, not only writing reports section by section — agents here touch a shipping-ready codebase (rationale: `references/shipping-rationale.md` § Why agents here commit as they go). Checkpoint your own state via `update_state.py` with `--set-pipeline bgpdd-shipping` — never hand-edit JSON.

## Path Model

- **Tier 1 (global knowledge base)**: `.docs/summary/{feature}/` — produced ONLY by `/bgpdd-discovery`. Read-only in this pipeline, with **one narrow, deliberate exception (convention #8)**: Step 6.4 folds the proven acceptance results back into `.docs/summary/{feature}/QA/manual-testing.md`. This refines the read-only rule rather than breaking it — the write happens once, to one file, only after the launch squad is green, and only to record behavior that was just verified. **Nothing else under `.docs/summary/` is ever written by this pipeline.** (`/bgpdd-bugfix`'s prevent step declares a second, narrower exception to the same file — one appended case, post-commit-gate; the two are complementary and neither is the sole non-Echo writer.) Why the exception exists: `references/shipping-rationale.md` § Why the Step 6.4 write to Tier 1 exists.
- **Tier 2 (per-enhancement workspace)**: `.docs/{project-name}/` — this pipeline's read-write workspace (plan.md, test-report.md, verification-report.md, security-report.md, ship-decision.md, post-deploy-report.md, game-tape.md, gates.jsonl, orchestrator-state.json). Never write shipping artifacts to Tier 1.

---

## Execution Checklist

As the Orchestrator, you must follow these steps in exact order. Do not skip steps.

### Step 0: Hydration
1. Establish `{project-name}`: take it from the user, or list `.docs/` and confirm the correct project with the user. Do NOT guess.
2. Read `.docs/{project-name}/orchestrator-state.json` (if it exists) to restore context from `bgpdd-build`; it follows the schema defined in `bgpdd-plan` Phase 4. Its `pipeline` must be `"bgpdd-build"` or `"bgpdd-shipping"` — a `"bgpdd-shipping"` value means a prior shipping session checkpointed its state here (per Global Error Recovery); resume from that state, do not halt. HALT (apply the Prerequisite Gate below) if `pipeline` holds any other value, or if `milestone_cursor` is a non-null milestone id — a milestone id means the build did not finish; `null` means build completed all milestones.
3. **Prerequisite Gate (mechanical, convention #9)**: do not eyeball `plan.md`. Run:
   `python {PLUGIN_ROOT}/pipeline-tools/scripts/next_milestone.py --plan .docs/{project-name}/implementation/plan.md --state .docs/{project-name}/orchestrator-state.json --ledger .docs/{project-name}/implementation/gates.jsonl`
   Result `DONE` = every milestone is checked and the cursor is not stale — proceed. **Any other result HALTs**: `NEXT` → surface the returned milestone id and instruct the user to complete `/bgpdd-build`; `MIXED`/`UNTAGGED` → the plan is malformed and never passed build's own routing gate; a stale-cursor verdict → the plan holds unchecked work behind the stored cursor (Orchestrator Contract §4), so reset it and surface the discrepancy before anything else. Also verify `.docs/{project-name}/implementation/test-report.md` exists; if it does not, HALT and instruct the user to complete `/bgpdd-build` first.
4. **Ship-decision entry ticket**: Require `.docs/{project-name}/implementation/ship-decision.md` from build Phase 5 (Dep's prep GO/NO-GO). Gate it mechanically — **the flags depend on the `pipeline` value you just hydrated in step 2**, because entry ticket and exit ticket are the same mutable file:
   - **Fresh run** (`pipeline` was `"bgpdd-build"`): the file still holds build's prep verdict, so require the GO.
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_ship_decision.py --report .docs/{project-name}/implementation/ship-decision.md --require-go --ledger .docs/{project-name}/implementation/gates.jsonl`
     Exit 0 = prep GO present — proceed. Exit 1 = NO-GO or incomplete decision — HALT. Exit 2 = structural/missing.
   - **Resume** (`pipeline` was `"bgpdd-shipping"`): Stage 2 Dep has already rewritten this file, so its content is now an *exit* verdict, not an entry one. Run the **structural check only** — drop `--require-go`:
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_ship_decision.py --report .docs/{project-name}/implementation/ship-decision.md --ledger .docs/{project-name}/implementation/gates.jsonl`
     Exit 0 = a well-formed decision (either verdict) — proceed into the pipeline; a standing `NO-GO` is the work this resume exists to finish, and Stage 2's refresh plus Step 3's `--require-go` exit ticket is what closes it. Exit 1/2 = malformed decision — HALT. **Do NOT apply `--require-go` here**: a legitimate NO-GO refresh would then block re-entry to the only stage that can resolve it, and the pipeline could never converge on its own output.
5. **Blockers Ledger Gate**: mechanical — no open-and-read substitute. Run:
   `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_blockers.py --state .docs/{project-name}/orchestrator-state.json --ledger .docs/{project-name}/implementation/gates.jsonl`
   Exit 0 = empty `blockers` array — proceed. Exit 1 = standing blockers — **HALT and list them from the JSON stdout**.

### Step 1: Read the Skill
Read the full `shipping-and-launch` skill located at `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`. Extract the exact text of each checklist section that each agent needs — you must paste that text into their delegation prompts as their Working Memory, not merely name the section.

### Step 2: Delegate the Launch Squad
Delegate to the following three agents in **two stages**. Each prompt MUST (a) include the exact checklist section text pasted from `shipping-and-launch`, (b) name the skill path `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md` so the agent can consult it, and (c) include the CRITICAL CIRCUIT BREAKER rule verbatim as worded in the Orchestrator Contract §2. Each agent returns its pass/fail `<handoff>` as its final message.

- **Stage 1 — Vera alone**: Delegate Vera first and wait for her handoff before starting Stage 2. Vera runs full builds and test suites that take file, build-output, and port locks; running scanners or infra verification concurrently against the same checkout causes lock collisions and flaky failures (especially on Windows).
- **Stage 2 — Cipher and Dep in parallel**: After Vera's handoff returns, delegate Cipher and Dep **in parallel** — start both delegations in a single batch.

**Paste each agent's prompt verbatim from `references/shipping-delegation-briefs.md` § <agent>.** The bullets below are the enforceable content of each brief; that file is the wording.

1. **Vera (QA & Performance)** — delegate to the **Vera** agent (Stage 1)
   - **Assignment**: `Code Quality`, `Pre-Merge Local Runtime Smoke`, `Performance`, and `Accessibility` checklists.
   - She must **start the application and probe it**, not only build and lint it, from the environment manifest at `artifacts.environment_manifest` (inject the resolved path; `bgpdd-build` Phase 0 wrote it) — start commands, local base URLs, the repointing map and forbidden hosts all come from there and none of them is hers to infer. If that artifact is `null` or absent, the affected checks are `BLOCKED`, never reconstructed from the repo.
   - **CRITICAL PATHING**: her report goes to `.docs/{project-name}/implementation/verification-report.md`, ending in the machine-read `**Verdict:**` line — the Step 3 Report Gate reads that file, not her handoff.
   - Her report section and every capture's `Milestone:` field are scoped to the epic or feature name, verbatim — the same token Step 3 passes to `check_runtime_evidence.py --milestone`.
   - **Do not drop the Runtime Smoke section from the paste.** It is the only item in her assignment that requires a *started* application; omitting it silently returns this pipeline to build-and-lint verification (`references/shipping-rationale.md` § Why the Runtime Smoke section may not be dropped from Vera's paste).
   - **Mechanical check of the paste (convention #9)**: after Vera's handoff returns and **before** the Step 3 gates, search `.docs/{project-name}/implementation/verification-report.md` for the heading `Pre-Merge Local Runtime Smoke`. Absent = the section never reached her: treat it as a defect in her artifact and route it back to Vera with the section text pasted in full (this counts as a fix-and-reverify round under Step 3's bound). Do not proceed to the Runtime Evidence Gate on a report that has no smoke section — the gate would then be reading captures nobody was asked to produce.

2. **Cipher (Security Auditor)** — delegate to the **Cipher** agent (Stage 2)
   - **Assignment**: `Security` checklist — scan for vulnerabilities, check CORS and headers, verify auth routes.
   - **CRITICAL PATHING**: he **appends** his audit round to `.docs/{project-name}/implementation/security-report.md`, ending in the machine-read `**Verdict:**` line — the Step 3 Report Gate reads that file, not his handoff.

3. **Dep (DevOps Engineer)** — delegate to the **Dep** agent (Stage 2)
   - **Assignment**: `Infrastructure`, `Feature Flag Strategy`, `Baseline Capture`, `Staged Rollout`, `Rollback Rehearsal`, and `Monitoring and Observability` — the exact section headings in `shipping-and-launch`, which forbids renaming or dropping them.
   - **Capture the rollout baseline** (three metrics read from the project's monitoring source into `.docs/{project-name}/implementation/evidence/baseline/`, listed under a `## Baseline` heading in the ship decision) and **rehearse the rollback** (the timed revert-plus-health-check on a non-production environment, captured with `run_quiet.py --capture` under `.docs/{project-name}/implementation/evidence/rollback/`, with the `Time to Rollback:` line in the grammar that section defines). **Neither is optional and neither is satisfiable by prose**: Step 3's exit ticket reads both mechanically.
   - He **refreshes/re-verifies** `.docs/{project-name}/implementation/ship-decision.md` for final launch — build Phase 5's prep GO was this pipeline's Step 0.4 entry ticket; his refreshed GO is the Step 3 exit ticket. Either a rewrite or an appended dated verdict section converges, because the gate reads the LAST verdict-bearing section; what it rejects is one section stating both GO and NO-GO. The Emergency Rollback Plan and the final `GO`/`NO-GO` go to that same path.
   - **CRITICAL PATHING**: the baseline and rehearsal evidence directories above are mandatory — the Step 3 exit ticket resolves the cited paths under `evidence/baseline/` and `evidence/rollback/` and fails a citation that lands anywhere else.

### Step 3: Wait and Block
Read the returned handoffs as each stage completes — Vera's after Stage 1, then Cipher's and Dep's after Stage 2. All three must be in hand before you proceed.
- **Report Gate (mechanical)**: a "pass" in Vera's or Cipher's handoff is a claim; the report file is the evidence. Once their handoffs are in hand, run the gate once per report:
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_agent_report.py --report .docs/{project-name}/implementation/verification-report.md --ledger .docs/{project-name}/implementation/gates.jsonl`
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_agent_report.py --report .docs/{project-name}/implementation/security-report.md --ledger .docs/{project-name}/implementation/gates.jsonl`
  Route per the default exit-code convention above; on exit 1 the JSON body names the failing/blocked/unrun/unevidenced items and Critical findings.
- **Runtime Evidence Gate (mechanical)**: `check_agent_report.py` verifies Vera's verdict is backed by evidenced check lines with exit codes — it does **not** verify that anything was ever started. Run this once Stage 1's report is in hand, and again after any fix round:
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_runtime_evidence.py --report .docs/{project-name}/implementation/verification-report.md --milestone "<the epic or feature name Vera scoped her report to>" --changed-files <the epic's changed-files union> --repo . --ledger .docs/{project-name}/implementation/gates.jsonl [--require-key <k> ...] [--forbid-host <pattern> ...] [--require-openapi-reachable]`
  **Derive `--changed-files` mechanically, do not reassemble it from build's per-milestone handoffs**: run `git diff --name-only <default-branch>...<branch>` — `<branch>` is the `branch` field hydrated in Step 0, `<default-branch>` is the repo's default branch (`main`/`master`) — and pass that file list. If `branch` is absent from the state file, confirm the branch with the user — do NOT guess.
  Pass `--require-openapi-reachable` when the epic touched an API surface. The `--milestone` token must match the scope Vera wrote into her captures' `Milestone:` field — at shipping that is the epic, not a single build milestone, so brief her with the exact string you will pass. **Deliberately without `--surface`/`--expect-status` (convention #8, same divergence class as the `--milestone` scope above):** both are per-capture assertions that no epic-level value could hold across every capture it claims to cover; `--require-key` and `--forbid-host` survive because they assert content meant to hold uniformly (`references/shipping-rationale.md` § Why `--surface` and `--expect-status` are deliberately not passed at shipping). Exit 0 = at least one fresh out-of-process capture backs her runtime claims — proceed. Exit 1/2 route per the default convention; exit 2's producing agent is Vera.
  - **If the application cannot be started out-of-process in this environment**, do NOT loop against a gate it cannot pass: **HALT** and surface that launch verification was necessarily in-process only. A release is never shipped on in-process-only evidence — the same line `bgpdd-build` §1 holds for a milestone commit.
- **Acceptance Suite Re-execution Gate (mechanical)**: this is the `bgpdd-shipping` Stage 1 regression run that `check_acceptance_suite.py` is documented to have. **Re-reading build's `acceptance-results.md` is not that run** — the walkthrough has to be *executed again* against the code that is about to ship (`references/shipping-rationale.md` § Why the acceptance suite is re-executed rather than re-read). Resolve the matrix path from `artifacts.acceptance_matrix` on the state hydrated in Step 0. **If it is JSON `null`** (a lite-originated epic with no matrix), skip this gate and say so explicitly to the user — do not re-derive from file absence. Otherwise:
  1. **Delegate a fresh Quinn to re-execute the matrix end to end** — a fresh delegation, not a continuation of any build-phase Quinn (Orchestrator Contract §1's independent-verification exemption). Brief: `references/shipping-delegation-briefs.md` § Fresh Quinn.
  2. She **appends** a new `## bgpdd-shipping — [date]` results section to `.docs/{project-name}/implementation/acceptance-results.md` — append, never overwrite: build's section is the baseline a regression is read against. Every step's evidence is a fresh capture written via `{PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture` under `.docs/{project-name}/implementation/evidence/runtime/`, cited inline in the result line's detail field per `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`.
  3. Then run the gate with the freshness assertion:
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_acceptance_suite.py --matrix <artifacts.acceptance_matrix> --results .docs/{project-name}/implementation/acceptance-results.md --repo . --changed-files <see below> --ledger .docs/{project-name}/implementation/gates.jsonl [--require-priority P0,P1]`
     **Derive `--changed-files` mechanically**: `git diff --name-only <the commit that closed build's last milestone>..HEAD` — everything that landed after the walkthrough was last executed, which is precisely the set the results file must post-date.
  - **Deliberate divergence from `bgpdd-build` Phase 5 step 2.5 (convention #8)**: same script, same matrix, same priority scope — the refinement here is `--changed-files`, because shipping would otherwise grade a file that is by construction older than the code.
  - Exit 0 = the walkthrough still holds against what is about to ship — proceed. Exit 1 = **BLOCK**: a failure here is a regression since build, so route it with the same weight as a fresh Vera/Cipher finding. Exit 2 = a structural defect or a nonexistent `--changed-files` path — route back to Alex (matrix) or Quinn (results) via `/bgpdd-build` per the re-entry rule below.
- **Ship-decision exit ticket (Dep)**: after Vera/Cipher's `check_agent_report` gates pass, gate Dep's refreshed ship-decision before Step 4:
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_ship_decision.py --report .docs/{project-name}/implementation/ship-decision.md --require-go --require-rehearsal --require-baseline --repo . --ledger .docs/{project-name}/implementation/gates.jsonl`
  Exit 0 = final GO, backed by a sidecar-evidenced rollback rehearsal and an evidenced rollout baseline — proceed. Exit 1/2 = BLOCK. On a `NO-GO`, route per the failure rules below and re-run this gate after Dep's refresh — the gate reads the LAST verdict-bearing section, so an appended fix round supersedes the earlier verdict rather than reading as ambiguity. On a `rehearsal_*` or `baseline_*` problem code, the route is back to **Dep**: the rehearsal or the baseline reading has to actually be performed, and no re-wording of the decision document closes it.
  - **Deliberately tighter than Step 0.4's invocation of the same script (convention #8).** Step 0.4 stays shape-only: a *prep* decision legitimately predates any rehearsal and any rollout baseline, so requiring them there would make the entry ticket unobtainable. The exit ticket gates a *launch* decision, where both must exist — the same mutable file read at two different moments in its life (`references/shipping-rationale.md` § Why the Step 0.4 entry ticket and the Step 3 exit ticket run the same script with different flags).
  - `--max-rehearsal-age-days` defaults to 30. Pass a smaller value where the deploy pipeline changes faster than that; a rehearsal older than the bound is `rehearsal_stale` and has to be re-run, not re-dated.
- If any agent reports a failure (e.g., failing tests, high vulnerabilities), you must **BLOCK** the deployment and inform the user of the specific failure.
- **Routing a shipping finding back to `/bgpdd-build`**: `bgpdd-build`'s hydration accepts `pipeline: bgpdd-shipping` as a re-entry — it resets the state to `bgpdd-build` and records the shipping finding in the game tape, so you no longer have to launder the state to get back in. **Before you hand the user the `/bgpdd-build` instruction, record the finding as a blocker**:
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/update_state.py --state .docs/{project-name}/orchestrator-state.json --add-blocker "<the shipping finding, with the gate that produced it and its evidence path>" --blocker-source shipping --blocker-milestone "<the milestone the finding affects>"`
  **Scope it, do not leave it unscoped.** `--blocker-milestone` is what lets build's commit gate hold exactly the milestone this finding lands in while the rest of the plan stays commitable; an unscoped entry still blocks everything, which is the fail-safe reading for a finding whose owner is genuinely unknown, not a default to reach for when you know it (contract: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`; why the entry comes first: `references/shipping-rationale.md` § Why a shipping finding is recorded as a blocker *before* the re-entry instruction). Then re-enter shipping at Step 0 — the resume branch of Step 0.4 exists for exactly this round trip. You cannot proceed past Step 3 until the Launch Squad is fully green.
- **Fix-routing bound**: At most **2 fix-and-reverify rounds per failing checklist area**. If an area is still failing after 2 rounds, **HALT** — surface the area, both fix attempts, and the failing evidence to the user. Do NOT route a third time.
  - **Deliberately a different unit from the Orchestrator Contract §2's "2 rounds per artifact" (convention #8)**: the count here is per *checklist area* (Code Quality, Security, Infrastructure, …), not per artifact — one agent writes one report covering several areas. Same bound of 2, deliberately coarser scope (`references/shipping-rationale.md` § Why the fix-routing bound counts checklist areas, not artifacts).
- After any fix round, the re-verifying agent appends a fresh report section and you re-run the Report Gate — a verdict written against the pre-fix code never carries forward.

### Step 3.5: Requirements Coverage Gate
Before compiling documentation:
1. Run:
   `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --test-report .docs/{project-name}/implementation/test-report.md --ledger .docs/{project-name}/implementation/gates.jsonl`
2. Read the JSON object from stdout. Exit code 0 = every Must-Have `FR`/`NFR` has at least one passing test or check recorded in the test report — report any `warnings` and `uncovered_should` entries as non-blocking notes, then proceed to Step 4. Exit code 1 = the `uncovered` array lists the Must-Have gaps. Exit code 2 = the artifact failed its structural contract (e.g. no Must-Have IDs, unreadable report).
3. On exit 1 or 2, **BLOCK** and route back to `/bgpdd-build` Phase 2 (Testing) with the exact `uncovered` IDs and `warnings` (or the `error` message) to close the gap, following Step 3's re-entry rule (record the blocker first). This closes the requirement-traceability chain — Rex's `FR`/`NFR` → Alex's task → Quinn's test — at the final gate.

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

### Step 5.5: Post-Deploy Verification

**Numbered 5.5, not 8, deliberately.** This step must run *after* the deploy of Step 5 and *before* the Step 6.4/6.5/6.6 close-out and the Step 7 Forge run — 6.6 deletes `orchestrator-state.json`, and 6.5's game tape is where this step's outcome is recorded. Sequence position wins over the number (why the number, and why this step exists at all: `references/shipping-rationale.md` § Why Step 5.5 exists, and why it is numbered 5.5).

1. **Wait for the deploy to land.** Step 5 hands the user the manual deployment commands; this step needs the result. Ask the user to confirm the deploy or merge completed and to name the environment it landed in (production, or whichever they deployed to). If they have not deployed in this session, do **not** simulate the checks: say so plainly, record `post-deploy: NOT RUN — user has not deployed` in the Step 6.5 game tape, and continue.
2. **Delegate a fresh Dep** — fresh, not the Stage 2 Dep; Orchestrator Contract §1's independent-verification exemption applies for the same reason it does to the Step 3 Quinn re-run. Brief (contents and wording): `references/shipping-delegation-briefs.md` § Fresh Dep. Every check runs **against the deployed environment the user just named**, never a local checkout; the report destination is `.docs/{project-name}/implementation/post-deploy-report.md` and the milestone token every capture must carry is `post-deploy`.
3. **Gate the report (mechanical).** Dep's handoff is a claim; the report is the evidence. Run both, in this order:
   `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_agent_report.py --report .docs/{project-name}/implementation/post-deploy-report.md --milestone "post-deploy" --ledger .docs/{project-name}/implementation/gates.jsonl`
   `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_runtime_evidence.py --report .docs/{project-name}/implementation/post-deploy-report.md --milestone "post-deploy" --changed-files <the epic's changed-files union, the same set Step 3 derived> --repo . --ledger .docs/{project-name}/implementation/gates.jsonl [--require-key <k> ...] [--forbid-host <pattern> ...]`
   The second is not redundant on the first — the same pairing Step 3 applies to Vera, applied here to the deployed environment (`references/shipping-rationale.md` § Why the two Step 5.5 gates are not redundant).
4. **Route the outcome.**
   - Both exit 0 → the deploy is verified. Proceed to Step 6.4.
   - Either gate exit 2 → an artifact defect: route back to this same Dep for a conforming report. Counts as a fix-and-reverify round under Step 3's bound.
   - Either gate exit 1, or a `**Verdict:** Fail` → **this is a live production defect, not a pipeline failure.** Do not open a fix round first. Take the rollback decision immediately, using the Rollout Decision Thresholds table and the `Time to Rollback:` value recorded in `ship-decision.md` for the rollback type this release uses — that recorded time is what tells the user how long the revert takes and therefore whether to revert now or hold. Present the failing rows, the recorded rollback time, and the rollback steps to the user, and **HALT** for their decision: executing a production rollback is theirs to authorize, not yours. Then record the finding as a blocker per Step 3's re-entry rule before any `/bgpdd-build` round trip.
5. **Record it.** The Step 6.5 game tape gets one bullet naming this step's verdict and the environment; the gate ledger (`.docs/{project-name}/implementation/gates.jsonl`) already carries the argv, input hashes and verdicts, so the tape cites it rather than restating it.

### Step 6.4: Refresh the Legacy QA Baseline (Orchestrator)
No delegation, no halt — you perform this step directly. **This is the one sanctioned write to Tier 1** (see Path Model, and the named divergence there). `orchestrator-state.json` is still on disk at this point — Step 6.6 deletes it — so read `{feature}` and `artifacts.acceptance_matrix` from it directly.

1. Read `artifacts.acceptance_matrix` from `.docs/{project-name}/orchestrator-state.json` (or, when that field is absent, `.docs/{project-name}/acceptance-matrix.md`): if the value is JSON `null` (a lite-originated epic), take the **lite path** in step 5 below instead of steps 2–4. Otherwise read that matrix file and `.docs/{project-name}/implementation/acceptance-results.md`; if either is absent — a pre-matrix epic — take the lite path as well.
2. Fold them into `.docs/summary/{feature}/QA/manual-testing.md`, **preserving Echo's format exactly** — strict `GO → DO → ASSERT` tables, Happy Path / Edge Cases / Negative / Regression Risks categories, P0/P1/P2 flags, preconditions, `[ ] Pass [ ] Fail` checkboxes; format authority is `agents/echo.md`, and `evals/contract/echo-qa-discovery-shape` is what asserts it. Scenarios that **passed** become or update baseline cases; cases Alex marked **invalidated** or **superseded** during his Baseline Reconciliation are removed or rewritten to match the behavior that now ships.
3. **Record only what was proven.** A scenario that was `BLOCKED`, `NOT RUN`, or never executed does not enter the baseline — an unverified case written into the durable baseline is worse than an absent one, because the next feature's discovery run will trust it.
4. Note in the game tape what you changed, so the next discovery run can tell a refreshed baseline from an original one.
5. **Lite path (no acceptance matrix).** Record the change even without scenarios: append to `.docs/summary/{feature}/QA/manual-testing.md` a dated `## Shipped without matrix — {project-name}` note listing (a) the FR/NFR IDs this epic shipped, taken from `.docs/{project-name}/requirements.md`, and (b) the evidence lines that proved them, taken from `.docs/{project-name}/implementation/test-report.md`. No `GO → DO → ASSERT` cases — there are none to write, and inventing them is the failure step 3 forbids. If there is no `{feature}` (a greenfield or Tier-1-less epic), there is no baseline to refresh: skip and say so in the Step 6.5 game tape.
   - **Deliberate refinement of step 3's "record only what was proven" (convention #8)**: step 3 bars an unverified *scenario*; this note asserts no scenario (`references/shipping-rationale.md` § Why the lite path still writes something).

### Step 6.5: Game Tape Checkpoint (Orchestrator)
No delegation, no halt — you perform this step directly, before briefing Forge. Cadence, cap, heading grammar, path and the ledger-citation rule are the skeleton's Game Tape section, unchanged. This pipeline's two additions:

1. One bullet names **the Step 5.5 post-deploy verdict and the environment it ran against** (or that it was `NOT RUN`, and why).
2. **Paste the whole-epic run-log roll-up** under the bullets — the epic's only cross-pipeline cost record, and the one place the fired-versus-rubber-stamped column is computed rather than remembered:
   `python {PLUGIN_ROOT}/pipeline-tools/scripts/summarize_run.py --run-log .docs/{project-name}/implementation/run-log.jsonl --ledger .docs/{project-name}/implementation/gates.jsonl --markdown`
   **No `--unit`** — deliberately unscoped, unlike `bgpdd-build` Phase 6 step 1b's per-milestone block (convention #8): a unit filter would drop every phase-level and null-milestone record the epic-wide view exists to show. **Not a duplicate of build's own epic roll-up** (Phase 6 step 2) either — that one closes the build phase, this one is the first and only roll-up covering the whole epic *including its launch*. Paste the block verbatim and **do not narrate cost in prose alongside it**. If the run log is absent (a pre-telemetry epic), say so in one bullet and move on. (Both divergences in full: `references/shipping-rationale.md` § Why the Step 6.5 roll-up is unscoped, and not a duplicate of build's.)

### Step 6.6: Cleanup
Last sub-step of Step 6 — it runs **after** 6.4 and 6.5, both of which read `orchestrator-state.json`. Delete `.docs/{project-name}/orchestrator-state.json`: the pipeline lifecycle has successfully completed and the state is no longer needed. Delete ONLY that file — `.docs/{project-name}/implementation/game-tape.md` and `gates.jsonl` survive as the epic's durable record and are the primary inputs to Step 7.

### Step 7: Agent Improvement (Forge)
- **Delegated Agent**: **Forge** (System Coach). He reads his methodology dependencies (agent-orchestration-improve-agent) on-demand.
- **Entry gate — a populated game tape (convention #9)**: before delegating, read `.docs/{project-name}/implementation/game-tape.md` and confirm it holds **at least one `## bgpdd-build —` or `## bgpdd-plan —` section besides the `## bgpdd-shipping —` section Step 6.5 just wrote.** If there is none, the tape records only this pipeline. **Say that plainly to the user, skip Forge entirely, and state that the improvement run has no evidence to run on**; tell the user the fix is Phase 6 checkpoints during the *next* epic, not a Forge run now (why: `references/shipping-rationale.md` § Why Step 7 gates Forge on a populated game tape).
- **Workflow**:
  1. Delegate to the **Forge** agent — brief contents and wording: `references/shipping-delegation-briefs.md` § Forge. Load-bearing in that brief: the **mechanical records are read FIRST** (run-log summary + gate ledger, before the game tape), the `/bgpdd-learn` filtered-read rule on transcripts (**never** full-read one), the Always-tier dependency-read spot-check, and the destination `.docs/{project-name}/implementation/agent-improvements.md`.
  2. Read Forge's returned handoff.
  3. **HALT EXECUTION**. Explicitly ask the User to review and approve `agent-improvements.md`. Do NOT proceed until you have explicit human approval.
  4. **Before applying — offer the eval bracket.** Run `evals/weekly-check.ps1` (zero-token: it only reads files and git, and never invokes the eval runner). It prints the affected eval cases and the `run-evals.ps1` command for them. Relay that command to the user and **offer** it as a before/after bracket around the apply — run the "before" leg only if they say to. Do NOT run the eval suite unasked.
  5. Upon approval, re-delegate to a fresh **Forge** agent to apply the approved changes to the relevant `SKILL.md`/agent files by editing and writing them directly. His `<changed_skills>` must list **each approved lesson with its destination file**, one lesson per destination — that pairing is what makes a single bad lesson revertible without unwinding the whole apply.
  6. **After the apply — verify the write boundary mechanically (convention #9).** Run `git diff --name-only` and **HALT**, surfacing the offending paths to the user, if any changed path:
     - is `agents/blackgoat.md` — untouchable by any agent (CLAUDE.md convention #7);
     - lies outside this plugin's directory — Forge's destinations are `SKILL.md` and `agents/<name>.md` files here, nothing in the target product repo;
     - touches a frontmatter block (the `---`-delimited header of any file) — trigger, name and description are the routing surface; a lesson never lands there.

     **Reverting is the user's call, not yours.** Report what changed and stop; Forge's `<changed_skills>` pairing from step 5 tells them which lesson to drop.
  7. If the user took the bracket in step 4, run the "after" leg with the same printed command and report the before/after delta alongside the diff.
