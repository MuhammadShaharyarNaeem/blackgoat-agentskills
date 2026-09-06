---
name: bgpdd-verify
description: "The standalone verification lane for an already-discovered feature. Derives a lint-gated acceptance matrix from Echo's QA baseline (.docs/summary/{feature}/QA/manual-testing.md), delegates Quinn to automate it as permanent Playwright specs executed against the running application, and gates the results on runtime evidence — without running the plan/build pipeline. Verify-only: product defects it finds route to /bgpdd-bugfix. Use to regression-test any discovered feature repeatably."
trigger: /bgpdd-verify
---

# End-to-End Multi-Agent PDD: Verification Lane (bgPDD-Verify)

This Standard Operating Procedure (SOP) answers one question with gated evidence: **does the feature, as discovery documented it, still work?** It takes a Tier-1 discovered feature, converts the scoped slice of Echo's manual-testing baseline into an acceptance matrix, has Quinn automate and execute it against the started application, and passes the results through the same mechanical gates the build pipeline uses.

**When to use**: a feature has been through `/bgpdd-discovery` and you want automated regression coverage plus evidence it behaves today — before a refactor, after an upstream dependency change, or on a recurring cadence. **When NOT to use**: building or changing behavior (→ `/bgpdd-plan` or `/bgpdd-lite`), a defect already isolated (→ `/bgpdd-bugfix`), or verifying an epic this squad just built (→ that is `bgpdd-build` Phase 5 / `bgpdd-shipping`, which own their own acceptance gates).

Invoke with `/bgpdd-verify {feature}`.

---

## 1. Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Phase 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.
>
> Then read `{PLUGIN_ROOT}/agent-squad/pipeline-skeleton.md` — the shared pipeline skeleton (path resolution, error recovery, upgraded chain of thought, game tape). Refinements below override the skeleton only where labelled (convention #8).

The sections below carry ONLY this pipeline's refinements on top of that contract.

- **Strict Delegation — this pipeline's agents**: Quinn (Phase 2), and optionally Scout for bounded environment research (Phase 1). You MUST NOT roleplay Quinn's work yourself.
  - **EXCEPTION — Phases 0–1 are interactive** (Orchestrator + user, main session), per the Orchestrator Contract §1's interactive-steps rule — scope selection and matrix confirmation are turn-by-turn decisions a delegated agent cannot pause for.
- **Verify-only, pipeline-wide: no builder in this lane, and a `FAIL` is an output.** No agent here modifies product source code. Quinn's QA write boundary applies unchanged (permanent specs into the target repo's test/e2e directories, reports into `.docs/`); a failing product behavior is a **finding**, never a fix task — deliberately narrower than `bgpdd-build` Phase 2's builder↔Quinn rejection loop (convention #8): there is no builder here to loop to, and a verification lane that fixes what it measures grades its own work. So a gated `FAIL` reproducing real misbehavior is this pipeline **working**: it never opens a fix round, never counts against a round bound, and never routes back to Quinn. Later steps cite this bullet rather than restating it.
- **Bidirectional contract with `/bgpdd-bugfix`.** Product defects found here **route out** to a fresh `/bgpdd-bugfix` session, one per defect (Phase 4 step 2) — contract, not offer. Reciprocally a bug fixed there **re-enters here**: that lane's closing prevent step appends the reproduced case to `.docs/summary/{feature}/QA/manual-testing.md` and points the user at `/bgpdd-verify {feature}`, because a bugfix session proves a fix once and only this lane makes it a permanent executed spec.
- **Quinn never authors what she is graded against** — the invariant that survives every authorship divergence below, and the same rule `bgpdd-build` Phase 5 step 2.5c enforces. Four corollaries:
  1. **The acceptance matrix** is the Orchestrator's artifact here, authored interactively with the user (Phase 1). Quinn receives a resolved read-only path and never edits it.
  2. **The `## Environment` preamble** — start commands, base URLs, forbidden host patterns, and the `--require-key` / `--expect-status` values the Phase 3 gate asserts — is caller-supplied and authored **before** execution (Phase 1 step 3). Quinn declares none of it; a producer-declared assertion grades itself (`{PLUGIN_ROOT}/runtime-evidence/SKILL.md`).
  3. **The Phase 3 gate flags** come from that preamble, never invented at the gate (Phase 3 step 2).
  4. **A matrix defect at Phase 3** re-opens Phase 1 with the user rather than routing to Quinn, and consumes none of her rounds (Phase 3 step 3).
- **Two-Tier Path Model**: **Tier 1** (`.docs/summary/{feature}/`) is the durable knowledge base from `/bgpdd-discovery` — read-only here. **Tier 2** (`.docs/{project-name}/`) is this verification run's read-write workspace. Never write verify artifacts into Tier 1.
- **Run log** (Contract §4's obligation, bound here; CLI contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`). Per delegation return — each Scout (Phase 1 step 3), Quinn (Phase 2), and every Phase 3 delta-only follow-up round: `python {PLUGIN_ROOT}/pipeline-tools/scripts/record_run.py --log .docs/{project-name}/implementation/run-log.jsonl --pipeline bgpdd-verify --phase "<phase>" --event delegation --agent <name> --model <tier> --unit "<the run title>" …` (`--model` is mandatory on a delegation record — exit 2 without it; name the tier the delegation actually ran at, not the one recommended). Add `--rounds <this artifact's round number>` on a re-delegation, plus `--duration-s`/`--tokens-in`/`--tokens-out` (or `--from-json <the completion payload>`) from the runtime's completion notification and `--status` from the handoff. Into Phase 4's game tape: `python {PLUGIN_ROOT}/pipeline-tools/scripts/summarize_run.py --run-log .docs/{project-name}/implementation/run-log.jsonl --ledger .docs/{project-name}/implementation/gates.jsonl --unit "<the run title>" --markdown`.
- **Content contracts, refining the skeleton's Upgraded Chain of Thought**: `acceptance-matrix.md` passes `--lint-only` (Phase 1 step 5); `acceptance-results.md` has a parseable result line for every gated step (the Phase 3 gate's `missing_results` check is the authority).
- **File Artifacts**: standard GitHub markdown, saved under `.docs/{project-name}/`.

## 2. Global Error Recovery

**Refinement of Orchestrator Contract §2 (skeleton owns the rest):** the artifacts subject to the 2-round bound are `acceptance-matrix.md` (structural lint failures) and Quinn's `acceptance-results.md` / runtime captures (conformance failures — a non-conforming capture, a missing result line). **A gated step that FAILs because the product misbehaves is outside the bound entirely** — see §1's verify-only bullet.

---

## 3. Detailed Pipeline Phases

### Phase 0: Fit Check & Hydration (Orchestrator)
- **Delegated Agent**: None — interactive, main session.
- **Workflow**:
  1. **Entry ticket**: `.docs/summary/{feature}/QA/manual-testing.md` must exist (Echo's baseline, written by `/bgpdd-discovery`). If it does not, HALT and route the user to `/bgpdd-discovery` first — this lane transcribes a baseline; it never reverse-engineers one.
  2. **Route out what this lane is not for** (see "When NOT to use" above). If the user's real goal surfaces as new behavior or a known defect mid-conversation, re-route rather than absorbing scope.
  3. Confirm with the user: the Tier-2 work slug `{project-name}` (default `{feature}-verify`), **which baseline sections/cases are in scope** (e.g. all Happy Path + Regression Risk, or specific case IDs), and the **priority floor** for the Phase 3 gate (`P0`, or `P0,P1` — `check_acceptance_suite.py`'s "at or above" semantics mean the floor can never skip P0). **Slug-collision guard (mechanical)**: if `.docs/{project-name}/requirements.md` or `.docs/{project-name}/implementation/plan.md` already exists, HALT — that slug belongs to a plan/build project whose `acceptance-matrix.md` Alex owns and derives from requirements; two writers with two derivation doctrines on one path silently destroy each other. Pick a different slug.
  4. **Re-verify shortcut**: if `.docs/{project-name}/acceptance-matrix.md` already exists from a prior confirmed run and the user wants a re-run (e.g. after a `/bgpdd-bugfix` fix, or on cadence), skip Phase 1 and go straight to Phase 2 — the specs are permanent and the matrix is durable; re-running is the point of this lane.

### Phase 1: Acceptance Matrix Derivation (Orchestrator + user, main session)
- **Delegated Agent**: None for authoring; optionally **Scout** for environment facts (step 3).
- **Format authority**: the **Acceptance Matrix Output** section of `{PLUGIN_ROOT}/planning-and-task-breakdown/SKILL.md` — scenario headings with priority, the `GO → DO → ASSERT` step table with `Stores` and `Mode` columns, `[inverse of N]` / `[no inverse: <reason>]` markers. Do not restate or vary that grammar.
- **Workflow**:
  1. Draft `.docs/{project-name}/acceptance-matrix.md` WITH the user by transcribing the in-scope baseline cases into matrix scenarios. **Source divergence, deliberate (convention #8)**: `planning-and-task-breakdown` derives the matrix from `requirements.md`; here there is no `requirements.md`, and "works" *means* "behaves as discovery documented", so it derives from Echo's baseline instead. The original rule's anti-self-grading intent is preserved by authorship (step 2) and by **citing each scenario's source case IDs** (`HP-01`, `RR-03`, …) in the heading's parentheses, so every scenario traces to a baseline row a different agent wrote.
  2. **Authorship divergence, deliberate (convention #8)**: in `/bgpdd-plan` Phase 3 the matrix is Alex's artifact; here the Orchestrator authors it interactively — this is transcription plus user scope decisions, not planning, mirroring `bgpdd-lite` Phase 1's interactive exception. §1's Quinn-never-authors invariant (corollary 1) survives the divergence unchanged.
  3. **Environment preamble (required)** — this lane's inline form of the environment manifest (**deliberate divergence, convention #8**): `runtime-evidence`'s *Environment Manifest* section puts these facts in a standalone file; here one matrix, one delegation and no build phases means the same blocks ride inside the matrix the user is already confirming. §1's corollary 2 survives both forms unchanged.
     - **Transcribe, do not re-derive.** The entry ticket already required `/bgpdd-discovery` to have run, so `.docs/summary/{feature}/QA/runtime-environment.md` should exist (discovery Phase 4b's Tier-1 recipe). When it does, copy its bring-up sequence, services, repointing map, forbidden hosts and test identities into the preamble rather than asking the user again, **and bring the `Needed for` column with them** so the run starts the minimal subset the in-scope scenarios need; ask the user only about what the scoped cases add. When it does not exist, author the preamble from scratch as below and tell the user their next `/bgpdd-discovery` run should capture it durably.
     Open the matrix with an `## Environment` section recording, from the baseline's overview docs or the user: the application start command(s), each service's local base URL, the forbidden shared-dev/staging host patterns, and — per API-touching surface — the response-envelope keys and expected statuses the Phase 3 gate will assert (`--require-key` / `--expect-status` values). If these facts are unknown and too large to gather inline, spawn **Scout** (`{PLUGIN_ROOT}/../agents/scout.md`) with one bounded topic per delegation, writing to `.docs/{project-name}/research/` — research only, no matrix authoring.
  4. Steps a browser cannot reach (database rows, cache/Redis hashes, vault secrets, device state) stay in the matrix as `Mode: manual` steps with their `Stores` named — legitimate, but they pass only with a cited capture under `evidence/runtime/`. Expect one-way baseline operations to need written `[no inverse: <reason>]` exemptions; the lint blocks undeclared ones by design.
  5. **Lint gate (mechanical)**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_acceptance_suite.py --lint-only --matrix .docs/{project-name}/acceptance-matrix.md --ledger .docs/{project-name}/implementation/gates.jsonl` — exit 0 required before Phase 2; on exit 1/2 fix the named arrays and re-run (2-round bound, then halt and surface).
  6. The user confirms the matrix before you proceed.

### Phase 2: Automation & Execution (Quinn)
- **Delegated Agent**: **Quinn** (QA Tester), one delegation, launched in the background. She reads her methodology dependencies per her table (`runtime-evidence` always; `playwright-skill` — this pipeline's runtime probes drive a browser surface, so it is in scope by her own table's condition).
- **Workflow**:
  1. Brief Quinn with: the matrix path; the in-scope baseline file path (Tier-1, read-only); the target repo root and its existing e2e suite location; a **run title** (use the `{project-name}` slug) she must use as her `#Task [N]:` block header in `test-report.md`; the resolved paths of `{PLUGIN_ROOT}/agent-squad/base-persona.md`, `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`, and `{PLUGIN_ROOT}/playwright-skill/SKILL.md`; and the Orchestrator Contract §2 rules verbatim (circuit breaker, no nested delegation, incremental persistence).
  2. Instruct her to: **(a)** write **permanent** Playwright specs into the target repo's e2e suite (her QA override: never the temp directory), grouped to mirror the matrix's scenarios, deriving every locator from the **rendered DOM** per her `playwright-skill` contract — never from component source; **(b)** start the application per the matrix's `## Environment` preamble and execute the suite through `{PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py`; **(c)** capture runtime evidence for `manual` steps and API-surface claims under `.docs/{project-name}/implementation/evidence/runtime/` via `run_quiet.py --capture`, stamping every capture with `--capture-field Milestone="<run title>"` — the Phase 3 gate scopes captures by the capture's own `Milestone` header field, never by the report's `#Task` header; **(d)** record per-step results to `.docs/{project-name}/implementation/acceptance-results.md` in the results grammar (`- <ScenarioId>.<Step>: PASS|FAIL|BLOCKED|NOT RUN — <detail>`; grammar authority: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`, quoted here per the acceptance-results exception in Quinn's persona), and her ledger + `**Runtime evidence:**` citations to `.docs/{project-name}/implementation/test-report.md` under the run title.
  3. Instruct her explicitly that this run is **verify-only** (§1): a failing step is recorded as `FAIL` with its evidence and the exact failing assertion — she does not fix product code, and her persona's Out-of-Scope Failure Bound (reproduce once, document, stop) applies to every product defect she hits. If the application will not start, every dependent step is `BLOCKED` naming what was missing — never `PASS`, never omitted.
  4. Read her dual handoff; extract `<changed_files>` (her spec files) and `<artifact>` paths.

### Phase 3: Mechanical Gates (Orchestrator)
- **Delegated Agent**: None — the Orchestrator runs both gates directly, under the Orchestrator Contract §1 interpreter rule (not restated here, and not softened by either gate).
- **Workflow**:
  1. **Acceptance gate**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_acceptance_suite.py --matrix .docs/{project-name}/acceptance-matrix.md --results .docs/{project-name}/implementation/acceptance-results.md --repo <target repo root> --require-priority <the Phase 0 floor> --ledger .docs/{project-name}/implementation/gates.jsonl`. **No `--changed-files` here (convention #8, refining `pipeline-tools`' freshness rule rather than contradicting it):** the results file is produced by the Quinn delegation immediately before this gate, so freshness holds by construction; `bgpdd-shipping`'s later re-execution is the one call site where staleness is possible.
  2. **Runtime-evidence gate**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_runtime_evidence.py --report .docs/{project-name}/implementation/test-report.md --milestone "<run title>" --changed-files <Quinn's spec-file union> --repo <target repo root> --ledger .docs/{project-name}/implementation/gates.jsonl` plus, taken from the matrix's `## Environment` preamble and never invented here: `--surface`, `--require-key`, `--expect-status`, `--forbid-host`, and `--require-openapi-reachable` when the surface is `api`/`web+api`. Freshness runs against Quinn's spec files: a capture older than the specs that supposedly produced it fails.
     - **Copy those values verbatim from the preamble — do not retype them from memory or from the shape of the response you expect — and paste the full command you actually ran into the Phase 4 game tape beside its captured output.** A silently mistyped `--require-key` or a loosened `--expect-status` turns this gate into one that passes on an assertion nobody chose; pasting the argv beside the preamble's lines makes a transcription error visible to the next reader instead of invisible to everyone. **Interim, not the destination (convention #9)**: a rule asking the Orchestrator to transcribe carefully is exactly the prose-restraint shape that should become mechanical, and it stays prose only until an emitter exists to hand these flags over the way `next_milestone.py --emit-gate-args` does for `bgpdd-build`. Until then the game-tape paste is the audit trail.
  3. **Route by failure class — this is where verify diverges from build (deliberate, convention #8: there is no rejection loop to a builder, per §1)**:
     - **Results/capture defects** (exit 1 arrays `missing_results`, `unevidenced_manual`; a non-conforming or stale capture; exit 2 on an unreadable results file): route back to Quinn as a delta-only follow-up quoting the JSON's named problems — 2-round bound (§2), then halt and surface.
     - **Matrix defects** (`missing_step_table`, an unreadable matrix): re-open Phase 1 with the user, re-lint, then re-run both gates. Consumes none of Quinn's rounds (§1 corollary 4).
     - **Gate-invocation defects** (a bad `--require-priority` token, an incomplete `--openapi-*` flag combination): your own usage error — fix the invocation and re-run. Consumes no round.
     - **Product defects** (a gated step whose `FAIL` reproduces real application misbehavior): do **NOT** loop. Carry them to Phase 4 as findings (§1).
     - **Environment blocks** (app cannot start out-of-process, transport unavailable): HALT and surface — never loop Quinn against a gate she cannot pass, and never accept an in-process substitute (`runtime-evidence`, the Tier Ladder).
  4. Full CLI contracts (JSON shapes, exit codes, parsing rules): `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` — single authority; do not restate parsing rules here.

### Phase 4: Verdict, Findings Routing & Game Tape (Orchestrator)
- **Delegated Agent**: None. No delegation, no halt.
- **Workflow**:
  1. **Relay the verdict** to the user: per-scenario PASS/FAIL/BLOCKED with the evidence path backing each claim. The durable evidence of "the feature worked" is the triplet `acceptance-results.md` + `test-report.md` + `evidence/runtime/` — machine-gated, not asserted. Qualify the verdict with any standing `BLOCKED` lines in the same breath (Orchestrator Contract §4).
  2. **Route findings** (§1's bidirectional contract): for each product defect, give the user the failing scenario/step, the reproduction from Quinn's report, and the evidence path, and route it to a fresh `/bgpdd-bugfix` session — one per defect. After a fix lands, it comes back through the Phase 0 re-verify shortcut, which is what makes this lane repeatable.
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
     Append `--add-blocker` entries for environment blocks and BLOCKED verifications (not for product-defect findings — those are output, routed in step 2, and live in the results artifact).
  5. **Re-entry: this state file is terminal by design.** `bgpdd-build` and `bgpdd-shipping` hydration reject `pipeline: bgpdd-verify`, and that rejection is the intent, not a gap — the way out is a fresh `/bgpdd-bugfix` per defect (step 2) and the way back in is the Phase 0 re-verify shortcut. **A later `/bgpdd-plan` or `/bgpdd-lite` run must never `--init` its own state over this file**: an init on the same slug replaces the verify run's `acceptance_matrix` and pipeline value, and the durable evidence triplet stops matching the state that points at it — which is what Phase 0 step 3's slug default and slug-collision HALT exist to make impossible, rather than leaving it to vigilance.
