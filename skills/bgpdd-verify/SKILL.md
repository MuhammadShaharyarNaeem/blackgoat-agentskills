---
name: bgpdd-verify
description: The standalone verification lane for an already-discovered feature. Derives a lint-gated acceptance matrix from Echo's QA baseline (.docs/summary/{feature}/QA/manual-testing.md), delegates Quinn to automate it as permanent Playwright specs executed against the running application, and gates the results on runtime evidence — without running the plan/build pipeline. Verify-only: product defects it finds route to /bg-bugfix. Use to regression-test any discovered feature repeatably.
trigger: /bgpdd-verify
---

# End-to-End Multi-Agent PDD: Verification Lane (bgPDD-Verify)

Answers one question with gated evidence: **does the feature, as discovery documented it, still work?** Takes a Tier-1 discovered feature, converts the scoped slice of Echo's manual-testing baseline into an acceptance matrix, has Quinn automate and execute it against the started application, and passes the results through the same mechanical gates the build pipeline uses.

| Situation | Route |
|---|---|
| Automated regression coverage plus evidence a discovered feature behaves today — before a refactor, after an upstream dependency change, on a recurring cadence | **this lane** |
| Building or changing behavior | `/bgpdd-plan` or `/bgpdd-lite` |
| A defect already isolated | `/bg-bugfix` |
| Verifying an epic this squad just built | `bgpdd-build` Phase 5 / `bgpdd-shipping` — they own their own acceptance gates |

Invoke with `/bgpdd-verify {feature}`.

---

## Path Resolution

`{PLUGIN_ROOT}` = the plugin's `skills/` directory (this skill's base directory is provided to you); personas live at `{PLUGIN_ROOT}/../agents/`. Every other path rule — list-before-reference, and the base-persona injection guard — has ONE home: `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md`, **Path Resolution** (inside your mandatory first read).

---

## 1. Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Phase 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.

Below: this pipeline's refinements on that contract only.

- **Strict Delegation — this pipeline's agents**: Quinn (Phase 2), and optionally Scout for bounded environment research (Phase 1). NEVER roleplay Quinn's work yourself.
  - **EXCEPTION — Phases 0–1 are interactive** (Orchestrator + user, main session), per the Orchestrator Contract §1's interactive-steps rule: scope selection and matrix confirmation are turn-by-turn decisions a delegated agent cannot pause for.
- **Verify-only, pipeline-wide.** No agent here modifies product source code. Quinn's QA write boundary applies unchanged (permanent specs into the target repo's test/e2e directories, reports into `.docs/`). A failing product behavior is a **finding**, never a fix task — deliberately narrower than `bgpdd-build` Phase 2's builder↔Quinn rejection loop (convention #8 — no builder here, and a lane that fixes what it measures grades itself; [rationale](references/verify-rationale.md#verify-only-no-rejection-loop)). Findings route to `/bg-bugfix` (Phase 4).
- **Two-Tier Path Model**: **Tier 1** (`.docs/summary/{feature}/`) is the durable knowledge base from `/bgpdd-discovery` — read-only here. **Tier 2** (`.docs/{project-name}/`) is this run's read-write workspace. NEVER write verify artifacts into Tier 1.
- **Upgraded Chain-of-Thought**: before each phase transition, verify the required artifact exists AND satisfies its content contract — `acceptance-matrix.md` passes `--lint-only` (Phase 1 step 5); `acceptance-results.md` carries a parseable result line for every gated step (authority: the Phase 3 gate's `missing_results` check).
- **File Artifacts**: standard GitHub markdown, saved under `.docs/{project-name}/`.

## 2. Global Error Recovery

**The error-recovery skeleton lives in the Orchestrator Contract (§2)** — halt-and-escalate triggers, the circuit breaker you pass to every agent, no-nested-delegation, incremental persistence, context checkpoints, and 2-round bounded autonomous rejection. Read it there; it is not restated here.

This pipeline's refinement — artifacts subject to the 2-round bound: `acceptance-matrix.md` (structural lint failures) and Quinn's `acceptance-results.md` / runtime captures (conformance failures — a non-conforming capture, a missing result line). **A gated step that FAILs because the product misbehaves is outside the bound entirely**: it is this pipeline's legitimate output, not a defect to loop on (Phase 3 step 3).

---

## 3. Detailed Pipeline Phases

### Phase 0: Fit Check & Hydration (Orchestrator)
- **Delegated Agent**: None — interactive, main session.
- **Workflow**:
  1. **Entry ticket**: `.docs/summary/{feature}/QA/manual-testing.md` must exist (Echo's baseline, written by `/bgpdd-discovery`). Absent → HALT and route the user to `/bgpdd-discovery` first; this lane transcribes a baseline, never reverse-engineers one.
  2. **Route out what this lane is not for** (routing table above). A real goal that surfaces mid-conversation as new behavior or a known defect → re-route rather than absorbing scope.
  3. Confirm with the user: the Tier-2 work slug `{project-name}` (default `{feature}-verify`); **which baseline sections/cases are in scope** (e.g. all Happy Path + Regression Risk, or specific case IDs); and the **priority floor** for the Phase 3 gate (`P0`, or `P0,P1` — `check_acceptance_suite.py`'s "at or above" semantics mean the floor can never skip P0).
     - **Slug-collision guard (mechanical)**: `.docs/{project-name}/requirements.md` or `.docs/{project-name}/implementation/plan.md` already exists → HALT and pick a different slug. That slug belongs to a plan/build project whose `acceptance-matrix.md` Alex owns and derives from requirements; two writers with two derivation doctrines on one path silently destroy each other.
  4. **Re-verify shortcut**: `.docs/{project-name}/acceptance-matrix.md` exists from a prior confirmed run and the user wants a re-run (after a `/bg-bugfix` fix, or on cadence) → skip Phase 1, go straight to Phase 2. The specs are permanent and the matrix durable; re-running is the point of this lane.

### Phase 1: Acceptance Matrix Derivation (Orchestrator + user, main session)
- **Delegated Agent**: None for authoring; optionally **Scout** for environment facts (step 3).
- **Format authority**: the **Acceptance Matrix Output** section of `{PLUGIN_ROOT}/planning-and-task-breakdown/SKILL.md` — scenario headings with priority, the `GO → DO → ASSERT` step table with `Stores` and `Mode` columns, `[inverse of N]` / `[no inverse: <reason>]` markers. Do not restate or vary that grammar.
- **Workflow**:
  1. Draft `.docs/{project-name}/acceptance-matrix.md` WITH the user, transcribing the in-scope baseline cases into matrix scenarios. Cite each scenario's source case IDs (`HP-01`, `RR-03`, …) inside the heading's parentheses, so every scenario traces to a baseline row another agent wrote. **Source divergence, deliberate (convention #8)**: derived from Echo's baseline, not from `requirements.md` as `planning-and-task-breakdown` requires — there is none here, and "works" *means* "behaves as discovery documented" ([how the anti-self-grading intent survives](references/verify-rationale.md#source-divergence)).
  2. **Authorship divergence, deliberate (convention #8)**: the Orchestrator authors the matrix interactively where `/bgpdd-plan` Phase 3 makes it Alex's artifact — transcription plus user scope decisions, not planning, mirroring `bgpdd-lite` Phase 1's interactive exception. Invariant unchanged across both divergences: **Quinn never authors the matrix she is graded against** (the rule `bgpdd-build` Phase 5 step 2.5c enforces).
  3. **Environment preamble (required)** — the environment manifest's blocks ride inside the matrix instead of a standalone file (**deliberate divergence from `runtime-evidence`'s *Environment Manifest* section, convention #8** — one matrix, one delegation, no build phases). Invariant unchanged: **these values are caller-supplied and Quinn never declares them.**
     - **Transcribe, do not re-derive.** The entry ticket already required `/bgpdd-discovery`, so `.docs/summary/{feature}/QA/runtime-environment.md` — discovery Phase 4b's Tier-1 recipe — should exist. When it does: copy its bring-up sequence, services, repointing map, forbidden hosts and test identities into the preamble, bring the `Needed for` column with them so the run starts the minimal subset the in-scope scenarios need, and ask the user only what the scoped cases add. When it does not: author the preamble from scratch as below, and tell the user their next `/bgpdd-discovery` run should capture it durably.
     - Open the matrix with an `## Environment` section recording, from the baseline's overview docs or the user: the application start command(s); each service's local base URL; the forbidden shared-dev/staging host patterns; and — per API-touching surface — the response-envelope keys and expected statuses the Phase 3 gate will assert (`--require-key` / `--expect-status` values). Caller-supplied, authored **before** execution; Quinn never declares them (`runtime-evidence`: a producer-declared assertion grades itself).
     - Facts unknown and too large to gather inline → spawn **Scout** (`{PLUGIN_ROOT}/../agents/scout.md`), one bounded topic per delegation, writing to `.docs/{project-name}/research/`. Research only — never matrix authoring.
  4. Steps a browser cannot reach (database rows, cache/Redis hashes, vault secrets, device state) stay in the matrix as `Mode: manual` with their `Stores` named — legitimate, but they pass only with a cited capture under `evidence/runtime/`. Expect one-way baseline operations to need written `[no inverse: <reason>]` exemptions; the lint blocks undeclared ones by design.
  5. **Lint gate (mechanical)**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_acceptance_suite.py --lint-only --matrix .docs/{project-name}/acceptance-matrix.md` — exit 0 required before Phase 2; on exit 1/2 fix the named arrays and re-run (2-round bound, then halt and surface). **If Python is unavailable: HALT** and surface the missing interpreter — never substitute a manual judgment path for a mechanical gate.
  6. The user confirms the matrix before you proceed.

### Phase 2: Automation & Execution (Quinn)
- **Delegated Agent**: **Quinn** (QA Tester), one delegation, launched in the background. She reads her dependencies per her own table (`runtime-evidence` always; `playwright-skill` — this lane's probes drive a browser surface, so it is in scope by her table's own condition).
- **Workflow**:
  1. Brief her with: the matrix path; the in-scope baseline file path (Tier-1, read-only); the target repo root and its existing e2e suite location; a **run title** (the `{project-name}` slug) she must use as her `#Task [N]:` block header in `test-report.md`; the resolved paths of `{PLUGIN_ROOT}/agent-squad/base-persona.md`, `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`, and `{PLUGIN_ROOT}/playwright-skill/SKILL.md`; and the Orchestrator Contract §2 rules verbatim (circuit breaker, no nested delegation, incremental persistence).
  2. Instruct her to:
     **(a)** write **permanent** Playwright specs into the target repo's e2e suite (her QA override: never the temp directory), grouped to mirror the matrix's scenarios, deriving every locator from the **rendered DOM** per her `playwright-skill` contract — never from component source;
     **(b)** start the application per the matrix's `## Environment` preamble and execute the suite through `{PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py`;
     **(c)** capture runtime evidence for `manual` steps and API-surface claims under `.docs/{project-name}/implementation/evidence/runtime/` via `run_quiet.py --capture`, stamping every capture with `--capture-field Milestone="<run title>"` — the Phase 3 gate scopes captures by the capture's own `Milestone` header field, never by the report's `#Task` header;
     **(d)** record per-step results to `.docs/{project-name}/implementation/acceptance-results.md` in the results grammar (`- <ScenarioId>.<Step>: PASS|FAIL|BLOCKED|NOT RUN — <detail>`; grammar authority: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`, quoted here only because Quinn's persona does not carry it), and her ledger + `**Runtime evidence:**` citations to `.docs/{project-name}/implementation/test-report.md` under the run title.
  3. Tell her explicitly this run is **verify-only**: a failing step is recorded `FAIL` with its evidence and the exact failing assertion — she does not fix product code, and her persona's Out-of-Scope Failure Bound (reproduce once, document, stop) applies to every product defect. Application will not start → every dependent step is `BLOCKED` naming what was missing; never `PASS`, never omitted.
  4. Read her dual handoff; extract `<changed_files>` (her spec files) and `<artifact>` paths.

### Phase 3: Mechanical Gates (Orchestrator)
- **Delegated Agent**: None — the Orchestrator runs both gates directly. **If Python is unavailable: HALT** and surface the missing interpreter.
- **Workflow**:
  1. **Acceptance gate**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_acceptance_suite.py --matrix .docs/{project-name}/acceptance-matrix.md --results .docs/{project-name}/implementation/acceptance-results.md --repo <target repo root> --require-priority <the Phase 0 floor>`.
  2. **Runtime-evidence gate**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_runtime_evidence.py --report .docs/{project-name}/implementation/test-report.md --milestone "<run title>" --changed-files <Quinn's spec-file union> --repo <target repo root>` plus, taken from the matrix's `## Environment` preamble and never invented here: `--surface`, `--require-key`, `--expect-status`, `--forbid-host`, and `--require-openapi-reachable` when the surface is `api`/`web+api`. Freshness runs against Quinn's spec files: a capture older than the specs that supposedly produced it fails.
  3. **Route by failure class** — this is where verify diverges from build (deliberate, convention #8: there is no rejection loop to a builder):

     | Failure class | Route |
     |---|---|
     | **Results/capture defects** — exit 1 arrays `missing_results`, `unevidenced_manual`; a non-conforming or stale capture; exit 2 on an unreadable results file | Back to Quinn as a delta-only follow-up quoting the JSON's named problems — 2-round bound (§2), then halt and surface |
     | **Matrix defects** — `missing_step_table`, an unreadable matrix | The matrix is the Orchestrator's artifact; Quinn never edits the file she is graded against (Phase 1 step 2's invariant). Re-open Phase 1 with the user, re-lint, then re-run both gates. Consumes none of Quinn's rounds |
     | **Gate-invocation defects** — a bad `--require-priority` token, an incomplete `--openapi-*` flag combination | Your own usage error: fix the invocation and re-run. Consumes no round |
     | **Product defects** — a gated step whose `FAIL` reproduces real application misbehavior | Do NOT loop. Carry them to Phase 4 as findings. The gates exiting 1 on genuine FAILs is this pipeline **working**, not failing |
     | **Environment blocks** — app cannot start out-of-process, transport unavailable | HALT and surface. Never loop Quinn against a gate she cannot pass; never accept an in-process substitute (`runtime-evidence`, the Tier Ladder) |
  4. Full CLI contracts (JSON shapes, exit codes, parsing rules): `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` — single authority; do not restate parsing rules here.

### Phase 4: Verdict, Findings Routing & Game Tape (Orchestrator)
- **Delegated Agent**: None. No delegation, no halt.
- **Workflow**:
  1. **Relay the verdict** to the user: per-scenario PASS/FAIL/BLOCKED with the evidence path backing each claim. The durable evidence that the feature worked is the triplet `acceptance-results.md` + `test-report.md` + `evidence/runtime/` — machine-gated, not asserted. Qualify the verdict with any standing `BLOCKED` lines in the same breath (Orchestrator Contract §4).
  2. **Route findings**: per product defect, give the user the failing scenario/step, the reproduction from Quinn's report, and the evidence path, and recommend a fresh `/bg-bugfix` session per defect. After a fix lands, re-verify via the Phase 0 re-verify shortcut — the specs and matrix are already in place, which is what makes this lane repeatable.
  3. **Game tape**: append a `## bgpdd-verify — [date]` section to `.docs/{project-name}/implementation/game-tape.md` (create if absent) — at most 10 bullets: scope chosen, gate results as verbatim command + captured output tail, findings raised, BLOCKED verifications, retry rounds and why.
  4. **State persistence** via `update_state.py` — never hand-edit JSON:
     ```bash
     python {PLUGIN_ROOT}/pipeline-tools/scripts/update_state.py \
       --state .docs/{project-name}/orchestrator-state.json \
       --init --project-name "{project-name}" \
       --set-pipeline bgpdd-verify \
       --set-feature {feature} \
       --set-artifact acceptance_matrix=.docs/{project-name}/acceptance-matrix.md \
       --set-artifact requirements=null \
       --set-artifact design=null \
       --set-artifact plan=null
     ```
     Append `--add-blocker` entries for environment blocks and BLOCKED verifications — not for product-defect findings, which are this lane's output, routed in step 2 and living in the results artifact.
