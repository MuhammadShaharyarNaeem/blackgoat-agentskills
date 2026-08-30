---
name: bgpdd-bugfix
description: "Fixes a localized bug: the Orchestrator does root cause analysis in the main session, then runs a minimal delegation chain under the Orchestrator Contract — Mason (or Nova for UI) writes the reproducing test and the fix (TDD), Quinn independently verifies, Luna reviews the diff and its blast radius. Trigger phrases: 'fix this bug', 'debug this error', 'use bgpdd-bugfix'."
category: execution
risk: safe
---

# bgPDD-Bugfix

## Purpose
A lean, sequential methodology for fixing a localized bug: root cause first, then the smallest squad that can prove the fix — one builder, one independent verifier, one reviewer — without the full `/bgpdd-build` milestone machinery (no plan, no requirements, no coverage gate).

## When to Use This Skill
- When the user reports a bug or defect in the code.
- When you need to trace an error stack before writing a fix.
- Trigger phrases: "fix this bug", "debug this error", "use bgpdd-bugfix".

---

## Path Resolution

Skill and agent paths in this document use `{PLUGIN_ROOT}` as a placeholder for the plugin's `skills/` directory. When this skill is invoked, its base directory is provided to you; `{PLUGIN_ROOT}` is that `skills/` directory (the agents live at `{PLUGIN_ROOT}/../agents/`). List files to confirm a path exists before referencing it.

`base-persona.md` resolves at `{PLUGIN_ROOT}/agent-squad/base-persona.md`, never under `{PLUGIN_ROOT}/../agents/` — the injection rule and its rationale live in the Orchestrator Contract §1 (Delegation Discipline). Verify the path resolves before delegating.

---

## 1. Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Phase 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.

The bullets below carry ONLY this skill's refinements on top of that contract.

- **Strict Delegation — this skill's agents**: **Mason** or **Nova** (Phase 2), **Quinn** (Phase 3), **Luna** (Phase 4). Phases 1 and 5 are yours, in the main session. You MUST NOT write the fix, the test, or the review yourself.
- **Artifact verification before each phase transition** — Contract §4's terminal-status rule at bugfix scale: confirm the builder's `<changed_files>`, Quinn's cited capture, and Luna's report actually exist before acting on any handoff.
  - *Format*: "Thinking: Phase 3 requires the builder's changed files. Checking `src/...`... File exists. Proceeding."
- **Bugfix workspace (deliberate divergence, convention #8)**: a bugfix has no epic — no `requirements.md`, no `plan.md`, no `orchestrator-state.json`. State lives in **this conversation and the fix branch**, and the mechanical pipeline gates (`check_coverage.py`, `check_commit_gate.py`) have nothing to read here. Where an agent's contract requires a durable artifact (Quinn's test report and captures, Luna's review report), resolve it under `.docs/{project-name}/implementation/` when this bug belongs to a feature that already has that folder, otherwise `.docs/bugfix/{bug-slug}/` — refining `base-persona.md`'s `.docs/{project-name}/` model and `runtime-evidence`'s capture path for a run with no project folder. Pick `{bug-slug}` in Phase 1 and **name the resolved path in every brief**: a subagent cannot ask you where to write.

## 2. Global Error Recovery

**The error-recovery skeleton lives in the Orchestrator Contract (§2)** — halt-and-escalate triggers, the circuit breaker you pass to every agent, no-nested-delegation, incremental persistence, context checkpoints, and 2-round bounded autonomous rejection. Read it there; it is not restated here.

This skill's only refinement: it has no `orchestrator-state.json`, so checkpoint your own state to a scratch file if your context grows large.

---

## 3. Execution Workflow

Follow this 5-phase sequence. Do not skip phases.

> **Conditional methodology routing — PowerShell**: If the bug involves a PowerShell script — a standalone `.ps1` or a script embedded in a host-language string (e.g. a C# string literal) — name `{PLUGIN_ROOT}/powershell-script-patterns/SKILL.md` in the Phase 2 builder's brief (it is already an on-demand entry in their dependency table) and instruct them to follow its Worker Execution Contract: extract-test-re-embed, real execution testing, external URL verification. Un-inferable parameters are escalated in the `<handoff>`, per that contract and `base-persona.md` — never invented, and never routed to the user by the builder.

> **Conditional methodology routing — runtime-observable bugs**: If the bug is observable at a boundary a client, person, or device reaches — a wrong response body/status/header, a wrong rendered state, a wrong device effect — or it arrived with a runtime capture (e.g. routed from `/bgpdd-verify`), it takes Phase 3's out-of-process capture **in addition to** the in-process regression test — an in-process test can fail this bug but never prove it fixed, so neither substitutes for the other (this refines Phase 2's plain "reproducing test" wording for this bug class; deliberate, convention #8). Cite both the pre-fix and post-fix capture paths when you state the fix to the user, so the claim is checkable against files rather than taken on the suite's green.

### Phase 1: Root Cause Analysis (Orchestrator, main session)
- **Delegated Agent**: None — you trace directly. Reading and searching is not writing application code (Contract §3).
- **Workflow**:
  1. **Trace**: search and read the execution path.
  2. **Identify**: isolate the specific mechanism of the failure.
  3. **Record the reproduction evidence** verbatim: the failing command and its output, the stack trace, or the observed wrong response/render — this is what the builder's RED test must reproduce, and Contract §3 forbids relaying a prediction read from source as an observation.
  4. **Constraint**: do NOT write or edit functional code during this phase.
  5. **Gate (user-facing)**: state the explicit root cause to the user before proceeding. First run the cheapest read that would *disprove* your leading hypothesis (Contract §3) — a confident wrong cause costs the whole chain a round trip.
  6. Pick the `{bug-slug}` (§1) and the fix branch here; reuse both in every brief.

### Phase 2: The Fix (TDD)
- **Delegated Agent**: **Mason** (`[API]`/backend bugs) or **Nova** (`[UI]`/user-facing bugs). Both always-load `test-driven-development`; each returns work of the other's surface unbuilt as a routing defect (Mason §1, Nova §1).
- **Workflow**:
  1. **Route by surface.** The bug's fix lands in backend code → Mason; in user-facing UI code → Nova. A fix that genuinely spans both surfaces is the routing defect their personas refuse: HALT and surface it to the user — split it into two runs or route it to `/bgpdd-build`; do NOT hand a mixed fix to one builder.
  2. **Delegate one builder.** **CRITICAL CONTEXT HANDOFF**: the brief carries (a) the root cause exactly as you stated it in Phase 1, (b) the reproduction evidence verbatim, (c) the resolved `{bug-slug}` artifact path from §1, and (d) the TDD obligation their always-loaded contract already governs — **write the single reproducing test first, run it, confirm it fails for the correct reason (RED), then fix surgically and make it pass (GREEN)**. Name the obligation; do not restate the TDD contract's rules in the brief.
  3. **Blast radius instruction**: before modifying any shared DTO, model, or library, the builder traces every consumer; if the radius extends past the bug's own module or service, it documents that in the `<handoff>` and returns rather than absorbing it (Mason §2).
  4. **The reproducing test is the builder's, not Quinn's** — deliberate (convention #8): splitting it would collide with the builder's own always-loaded TDD contract, which requires them to see RED before writing the fix. Quinn's job in Phase 3 is the *independent* run, which is a different thing.
  5. Read the returned `<handoff>` and extract the `<changed_files>` list. Verify those paths exist (§1) before Phase 3.

### Phase 3: Independent Verification
- **Delegated Agent**: **Quinn** (QA Tester). She always-loads `runtime-evidence`.
- **Workflow**:
  1. Delegate to **Quinn**, passing the root cause, the reproduction evidence, the builder's `<changed_files>`, and the resolved artifact path from §1.
  2. Instruct her to **run the affected test suite herself** — the builder's new test plus everything that could regress around the changed files — reporting the verbatim command, its exit code, and the failure detail for anything red. Contract §4: the builder's green is a claim; her run is the evidence.
  3. **Runtime-observable bug** (per the conditional block above): additionally instruct her to produce a **fresh post-fix out-of-process capture** per her `runtime-evidence` contract, written under the resolved capture directory, and to cite it in her report and `<handoff>`.
  4. **No coverage-gate machinery here.** There is no `requirements.md`, so no `FR`/`NFR` IDs exist for her ledger to trace — she must not invent them, and `check_coverage.py` is not run. Her evidence discipline is untouched: every status carries the command and output that produced it, and a check whose precondition was missing stays `BLOCKED`, never upgraded to `PASS`.
  5. **Red on her run** → return to the **same spawned builder** as a delta-only follow-up with her exact failing output (Contract §1, *Continuation vs fresh delegation*), then re-verify. Bound this with Contract §2's **2-round** autonomous-rejection rule — deliberately tighter than `bgpdd-build` Phase 2's 3-round bound (convention #8): here a stated root cause already exists, so a fix that fails twice means Phase 1's diagnosis is wrong, and the answer is a return to Phase 1 with the user, not a third attempt.

### Phase 4: Review & Blast Radius
- **Delegated Agent**: **Luna** (Reviewer). She always-loads `code-review-and-quality`, which owns her review axes, report format and location, and her Critical/Important/Suggestion/Nit/FYI severity labels.
- **Workflow**:
  1. Delegate to **Luna** with the builder's `<changed_files>` so her scope is surgical, plus the root cause and Quinn's evidence, and the resolved report path from §1.
  2. Instruct her to review the fix diff **and to run her Impact Analysis directive explicitly**: search every caller and consumer of each modified function, class, or DTO, and state per consumer whether the fix is safe for it. A bugfix's characteristic failure is a correct local fix that breaks a second caller — name that axis rather than assume it.
  3. **Critical or Important finding** → remediate as a follow-up to the same spawned builder, then re-enter **Phase 3** (Quinn re-runs) and return here for a **fresh Luna** on the remediation diff — reviewers are always a fresh delegation (Contract §1, independent-verification exemption). Bounded by Contract §2's 2-round rule; exit only on a fresh `Approve` against the *current* diff.
  4. **Gate (user-facing)**: if the blast radius extends beyond the isolated bug — other consumers must change, or the fix implies a contract or architecture change — **HALT and surface it to the user**. That work is `/bgpdd-plan` / `/bgpdd-build` scope; never absorb it here.
  5. On `Approve`, state the fix to the user: the root cause, the builder's changed files, Quinn's command and exit code, and — for a runtime-observable bug — both capture paths.

### Phase 5: Procedural Memory Update
1. **Evaluate**: Determine if the bug was a unique typo or a systemic misunderstanding.
2. **Route**: If a systemic lesson was learned, tell the user and suggest running `/bgpdd-learn` — lessons are routed through Forge's Destination Triage with pruning and explicit approval, never appended ad-hoc.

## Limitations
- Use this skill only for localized bug fixes. For sweeping architectural changes, use the full `bgpdd-build` methodology instead.
