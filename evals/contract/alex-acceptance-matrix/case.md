# Case: alex-acceptance-matrix

## Purpose
Guards Alex's **second** plan-time artifact. `alex-plan-coverage` covers `plan.md`;
nothing covered `acceptance-matrix.md`, which is a different artifact at a different
scope — the plan is per-milestone, the matrix is per-feature — and it is the only thing
in the pipeline that proves the *wall* stands rather than each brick. Its failure mode is
specific and known: **the milestone that adds an operation has no reason to exercise its
inverse.** A feature can pass every milestone commit gate and still ship an unmap that
half-works or an uninstall that leaves the service registered, because nothing ever ran
them.

The matrix is also the input `check_acceptance_suite.py` parses at build Phase 5 and
again at shipping Stage 1. A matrix with the wrong shape does not fail loudly there; it
fails *structurally* (exit 2), which reads as "the gate is broken" rather than "the
artifact is wrong" — so shape drift here is silent and compounds two pipelines
downstream.

The fixture is brownfield on purpose, so Alex's **Baseline Reconciliation** duty
(`agents/alex.md` §4) is genuinely exercised: Echo's `QA/manual-testing.md` records
behavior the system is presumed to still have, including one case (`MT-5`) that is
explicitly the known defect FR-2's reinstall clause exists to fix.

## Frozen Input
- Fixture dir: `fixture/` — already mirrors the temp working copy's final layout:
  - `.docs/device-mapping/requirements.md` — two Must-Have FRs, each carrying its inverse
    **inside** the requirement rather than as a separate FR (deliberately: a matrix that
    just mirrors the FR list one-scenario-per-id would satisfy an id check while still
    never exercising an inverse). `FR-1` is the **mapping** feature (map / unmap, with
    the "unmapping leaves the group untouched" clause); `FR-2` is the **device install**
    feature (install / uninstall / **reinstall**, where reinstall is the idempotency case
    that catches a half-removing uninstall). Plus one Should-Have `FR-3` and one
    Must-Have `NFR-1`.
  - `.docs/summary/device-mapping/overview.md` and
    `.docs/summary/device-mapping/QA/manual-testing.md` — Echo's discovery baseline:
    5 cases (`MT-1`..`MT-5`) across P0/P1/P2 in the same `GO → DO → ASSERT` grammar the
    matrix reuses, including `MT-5`'s recorded known defect (the manual uninstall runbook
    leaves the service registered, so a later install fails).
- Copies to: `.` (the fixture root is copied straight onto the temp working copy's root,
  preserving its internal `.docs/device-mapping/` and `.docs/summary/device-mapping/`
  nesting).

## Command
Run from the temp working copy's root:

```powershell
claude -p "Act as Alex per agents/alex.md. This is brownfield work. Read .docs/device-mapping/requirements.md first, then the discovery knowledge base at .docs/summary/device-mapping/ (overview.md and QA/manual-testing.md). There is no detailed design document - treat this as a lite-originated plan whose only inputs are those files. Produce BOTH plan-time artifacts the planning-and-task-breakdown methodology requires, following that methodology exactly rather than inventing a format: (1) .docs/device-mapping/implementation/plan.md, with every milestone heading carrying its domain tag and its verification-surface tag and every checkpoint carrying a conforming RUNTIME PROBE: line; and (2) .docs/device-mapping/acceptance-matrix.md, derived from requirements.md rather than from the task list you just wrote and reconciled against the QA/manual-testing.md baseline, with scenario ids, priorities, Surface metadata, GO -> DO -> ASSERT step tables carrying Stores and Mode columns, and inverse declarations on state-changing steps." --permission-mode acceptEdits
```

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. `.docs/device-mapping/requirements.md` is present (fixture sanity check).
2. `.docs/device-mapping/acceptance-matrix.md` was produced.
3. `python skills/pipeline-tools/scripts/check_acceptance_suite.py --matrix
   <acceptance-matrix.md> --results <grader stub> --repo <TargetDir>` emits parseable
   JSON and does **not** exit `2`. Exit `0` and exit `1` both mean the matrix's shape was
   readable and the gate could form a real verdict from it — the same distinction
   `quinn-test-report-shape` criterion 5 draws for `check_coverage.py`. Exit `2` means
   "no parseable scenario", i.e. the artifact is not an acceptance matrix.
   **Why a stub results file:** the gate takes `--matrix` *and* `--results` and exits `2`
   if the results file is missing, empty, or has no parseable result line. At plan time no
   results exist, so the grader writes a fixed one-line stub
   (`- AS-1.1: PASS - grader stub`) to its own temp path. The stub is known-good and
   constant, so a `2` can only come from the matrix — which is what this criterion is
   about. Criteria 4-6 then read the gate's own parse of the matrix rather than
   re-implementing it.
4. **Scenarios are addressable and prioritized.** At least 2 scenarios; every scenario
   has a non-null `priority` (a `P0`-style token in its heading), a non-null `surface`
   (from its `Surface:` metadata line), and at least one requirement id collected from
   inside its heading's parentheses; and the union of those ids covers **both** `FR-1`
   and `FR-2`.
5. **Step tables are complete.** Neither the gate's `no 'Mode' column` nor its
   `no 'Stores' column` warning is present, every scenario has at least 2 steps, and
   every step reports a non-empty `stores` list and a `mode` of `auto` or `manual`.
6. **Inverses are declared and resolve.** At least 2 steps carry `[inverse of N]` (one
   for the mapping feature, one for the install feature), and the gate's
   `dangling_inverse` array is empty — an `[inverse of N]` naming a step that does not
   exist means the matrix misrepresents its own coverage.
7. **Reinstall is covered.** At least one step's `DO` cell names a reinstall (matching
   `reinstall` or `install ... again`). This is the idempotency case
   `planning-and-task-breakdown` calls out by name — the one that catches an uninstall
   that only half-removed, and the exact defect `MT-5` in the baseline records.
8. **Plan milestones declare a verification surface.** `plan.md` was produced, has at
   least one `Milestone` heading, and **every** milestone heading carries a
   `[vs:<surface>]` tag whose value is one of `api`, `ui`, `web+api`, `rmm`, `fn`, `none`.
   (Checked by regex over all headings rather than through `next_milestone.py`, which
   validates only the *next pending* milestone and needs an `orchestrator-state.json`
   that does not exist at plan time. Same assertion, wider coverage, no synthetic input.)
9. **Checkpoint probes conform.** `python skills/pipeline-tools/scripts/check_coverage.py
   --requirements <requirements.md> --plan <plan.md>` reports **no** `lint_failures` entry
   whose `check` is `runtime-criterion` — the sanctioned mechanical check for the
   `RUNTIME PROBE:` grammar (probe present, not a build/typecheck/search/test-runner
   command, `expect-status`/`require-keys` present where the surface demands them). Other
   lint classes and coverage itself are deliberately **not** graded here: those are
   `alex-plan-coverage`'s subject, and duplicating them would make two cases fail for one
   cause.

`grade.ps1` exits `0` only if all nine pass; otherwise it exits `1` and prints which
criterion failed, including the gate's raw JSON fields where relevant.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

## Future (not implemented)
- Whether the scenarios are the **right** scenarios: whether the journey's ordering is
  real, whether an `ASSERT` cell asserts the thing the requirement actually promises, and
  whether the `Stores` list names every source of truth the step should read back. That is
  Alex's authoring judgment and stays reviewable prose — the same scope limit
  `check_acceptance_suite.py` documents for itself.
- Whether the **Baseline Reconciliation** was honest: this case's fixture exercises the
  duty (a 5-case baseline including one known defect) but the grader cannot tell a
  reconciled case from a coincidentally-similar one, and cannot tell a deliberately
  invalidated case from a silently dropped one. An `MT-` id traceability check was
  considered and rejected as measuring format compliance rather than judgment.
- Whether `[no inverse: <reason>]` was used *honestly* where a step genuinely has no
  inverse. Criterion 6 counts declared inverses; nothing here can judge whether an
  undeclared one was legitimately one-way.
