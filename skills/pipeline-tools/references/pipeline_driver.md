# `pipeline_driver.py` — depth

Rationale, the per-lane phase tables, the derivation rules, and the self-test
inventory. The lean contract (invocation, flags, JSON keys, exit codes) lives in
`../SKILL.md`; this file is loaded on demand.

## Why it exists

Every other tool in this family answers *"is this artifact good enough?"*. This
one answers *"where am I, and what is the one thing to do next?"* — a question
that until now was answered from prose the Orchestrator recalled.

CLAUDE.md convention #9 says a rule that asks the Orchestrator to restrain
itself at the moment it most wants to proceed must become an artifact that has
to be run. Phase order is exactly that rule. A pipeline spine lists its phases
in order, but nothing between them refuses. The observed failure mode is not
"the Orchestrator forgot Phase 4 exists" — it is "the Orchestrator ran Phase 4's
gate, read a green result, and moved on without noticing that Phase 2's gate had
never run at all", because the only thing tracking the sequence was a reading of
the spine done many turns earlier.

`next_milestone.py` and `next_bugfix_route.py` are the seeds. Each already
converts one decision into a derivation: which milestone is next, and which
route the bug takes. Both stop at their own decision. This generalises the
shape to the whole lane — the artifacts on disk plus the gate ledger are a
complete record of what has happened, so the next step is derivable, not
recalled.

## The exit-code design

The contract is **`exit 1` if and only if `blocked_by` is non-empty**, so the
exit code and the JSON can never tell different stories.

| Situation | `required_gate` | Exit |
|---|---|---|
| The next action is to AUTHOR an artifact (write `bug-report.md`, write `rca.md`, complete `note.md`) | `null` | 0 |
| The next action is to DELEGATE (Quinn for RED or GREEN, a builder, Luna) | `null` | 0 |
| The next action is to RUN a gate that has never run for this unit | that gate, `MISSING` | 1 |
| The gate's latest record is `FAIL` | that gate, `FAIL` | 1 |
| The gate's latest record is `PASS` but a recorded input hash no longer matches disk | that gate, `FAIL` | 1 |
| An artifact is PRESENT and structurally wrong (RED exited 0, no sidecar, edited after capture) | whatever the phase needs | 1 |
| The closing gate `PASS`ed but its `argv` carries no `--commit` | that gate, `PASS` | 0 |
| The closing gate `PASS`ed with `--commit` | that gate, `PASS` | 3 |
| Root unreadable, no lane detected, feature root with no epic state | — | 2 |

Two deliberate choices inside that table:

- **A gate that has never run is a block, not a step.** Read plainly this makes
  "run the next gate" an exit-1 state, which reads oddly the first time. It is
  the intended reading of the refusal: the lane genuinely cannot advance, and
  a caller wiring the driver into `set -e` or a hook gets a stop rather than a
  green light. The driver still prints the exact command, so "blocked" here
  means *there is exactly one thing to do*, never *stop and think*.
- **A stale `PASS` is reported as `FAIL`, not as a fourth status.** The JSON's
  `gate_status` enum stays `PASS|FAIL|MISSING|null` because callers switch on
  it; the distinction lives in `blocked_by`, whose text names the edited file.
  Staleness is deliberately NOT applied to the closing gate: a commit that
  already happened cannot be un-happened by a later edit to `review-report.md`,
  so that case emits a warning and still exits 3.

## bgpdd-bugfix — the phase table

`{R}` is the lane root; `{slug}` is the unit; `{L}` is the ledger
(`{R}/gates.jsonl` unless `--ledger` says otherwise).

| Phase | Name | Current until | Required gate | Next action |
|---|---|---|---|---|
| 0 | Intake | `{R}/bug-report.md` exists AND `check_bugfix_intake.py` has a `PASS` in `{L}` whose recorded hash still matches the report | `check_bugfix_intake.py` (once the report exists) | write the report, else run the intake gate |
| 1 | Reproduce — RED | a capture under `{R}/evidence/red/` exists with a sidecar, and both the sidecar and the capture body record a **non-zero** exit | none | delegate Quinn, with the report's `- Command:` value inlined |
| 2 | Isolate — RCA and route | `{R}/rca.md` exists AND `next_bugfix_route.py` has a `PASS` in `{L}` | `next_bugfix_route.py` (once `rca.md` exists) | write the RCA, else run the route gate |
| 3 | Fix | `{R}/run-log.jsonl` holds a record with `event: delegation` and `agent` in `mason`/`nova` | none | delegate the builder(s) the report's `- Surface:` names |
| 4 | Verify — GREEN | a GREEN capture exists (exit 0, sidecar-backed) AND `check_red_green.py` is `PASS`; plus `check_runtime_evidence.py` `PASS` when the report says `- Runtime observable: yes` | those one or two gates | delegate Quinn for GREEN, else run the pending gate |
| 5 | Review and Close | `{R}/review-package.md` exists, `{R}/review-report.md` carries a `## Review:` section whose title holds `{slug}` as a whole token with a `**Verdict:**` line, AND `check_commit_gate.py` is `PASS` **with `--commit` in its recorded argv** | `check_commit_gate.py` (once the verdict exists) | run `review_package.py`, else delegate a fresh Luna, else run the commit gate |
| 6 | Complete | — | — | the close steps: Tier-1 write-back, leave the state standing, name exactly one onward command, and (standalone only) close the branch |

**Route detection.** The two workspaces are told apart by folder shape, not by
file presence, because Phase 0 has not created the standalone state file yet:

- root basename is `implementation` → **feature route**, and `{state-file}` is
  the epic's own `orchestrator-state.json` **one level up**. If that file does
  not exist the driver exits 2 rather than guessing — the spine's Phase 0
  step 4 says HALT on exactly that condition, and a driver that silently
  invented a standalone route there would have converted a HALT into a wrong
  answer.
- anything else → **standalone route**, `{state-file}` inside the root.

**Slug derivation**, in order: `--milestone`; the latest
`check_bugfix_intake.py` ledger record's `milestone`; the RED capture's
filename stem; the root basename. `--milestone` exists for the feature route,
where the basename names the *epic* and never the bug — with several bugs
sharing one `implementation/` root, the ledger fallback picks the most recent,
which is right only by luck.

**FAST vs FULL.** `next_bugfix_route.py` records no `route` field in its ledger
line, so the driver cannot recover which of FAST/FULL it printed. It says so:
the Phase 3 warning names the re-run command rather than guessing at a pause
the user may be owed. If the route gate ever starts recording `route` in its
ledger `extra`, the driver reports it verbatim — the code already looks.

## bgpdd-quick — the phase table

| Phase | Name | Current until | Required gate | Next action |
|---|---|---|---|---|
| 0 | Scope | `{R}/note.md` exists with three real, non-placeholder lines (`- What:`, `- Where:`, `- How verified:`) | none | write or complete the note; the missing keys are named |
| 1 | Change and Prove | `{R}/evidence/check.md` exists with a sidecar and exit 0 | none | edit only the Where paths, then run the `run_quiet.py --capture` |
| 3 | Close | `check_quick_close.py` is `PASS` **with `--commit`** | `check_quick_close.py` | run the close gate, with `--changed-files` filled from the note's Where line |
| 4 | Complete | — | — | append the one-bullet `## Result` game tape to `note.md` |

**Phases 1 and 2 are fused, deliberately.** An edit leaves no artifact of its
own, so no reading of the tree can see Phase 1 end. The capture is the only
observable either phase has, and it is what Phase 3 reads. The alternative
considered and rejected was an mtime heuristic — "a Where file newer than
`note.md` means the edit landed" — which would report Phase 2 for a file
touched by anything at all, and would not change the emitted action anyway.
There is no phase 2 key in the driver's output for this lane.

## What is deliberately NOT derived

- **Whether a gate would pass.** The driver reads verdicts; it never re-runs a
  gate or reimplements one. `capture_state()` is the narrowest possible copy of
  `check_red_green.evaluate_capture()` — enough to tell "this phase produced its
  artifact" from "it did not" — and it does not compare RED and GREEN argv,
  check ordering, or read `finished` at all. Those are `check_red_green.py`'s
  terms and the driver defers to its ledger verdict for them.
- **`--changed-files`.** No artifact records what the builder touched, so the
  emitted commit-gate and runtime-gate commands carry
  `<the builder's paths>` verbatim. Every other flag is exact.
- **The commit message.** Emitted as `<the commit message>`.

## Extending it to the other lanes

The four remaining lanes (`bgpdd-build`, `bgpdd-lite`, `bgpdd-plan`,
`bgpdd-shipping`, `bgpdd-verify`) are not covered, and adding them needs one
thing each that does not exist yet:

- **build / lite** — a milestone is the unit, not the lane, so a driver has to
  compose with `next_milestone.py` rather than replace it: phase within a
  milestone, then milestone within the plan. The missing piece is a durable
  record of which *phase* of the milestone is current; today only the milestone
  cursor is written. Either `update_state.py` grows a phase cursor, or the
  driver derives it from the per-milestone gate set the way it does here.
- **shipping** — its stages are numbered `0.3`–`6.6` rather than `0`–`5`, and
  several are conditional on the ship decision. A stage table would need the
  spine to declare, mechanically, which stages a given run skips.
- **verify** — closest to coverable today; its artifacts (`acceptance-matrix.md`,
  `acceptance-results.md`) and its one gate (`check_acceptance_suite.py`) map
  onto this shape almost directly.

## Self-test inventory — 52 cases

Four suites, every case in a fresh temp directory.

- **`BugfixPhaseTests` (33)** — every phase boundary 0→1→2→3→4→5→complete; no
  lane detected; root not a directory; the ledger absent at Phase 0 giving the
  intake command; an intake `FAIL` record; a report edited after its intake
  `PASS`; a RED that exited 0; a RED with no sidecar; a RED edited after
  capture; the deliberate skip (a builder delegation recorded while the route
  gate never ran — the driver stays at Phase 2); a route-gate `FAIL`; Mason for
  `api` and both builders for `both`; the FAST/FULL note in both its recorded
  and unrecorded forms; a non-builder delegation not advancing Phase 3; a
  missing GREEN; a GREEN that exited non-zero; runtime-observable requiring the
  runtime gate and non-observable not; the Phase 5 sequence
  (package → Luna → commit gate); a review section for another slug not
  counting; a commit-gate `PASS` without `--commit`; a commit-gate `FAIL`; and
  the complete lane at exit 3 with its close steps.
- **`BugfixRouteTests` (4)** — standalone state file inside the root; feature
  state file one level up; a feature root with no epic state exiting 2; a slug
  derived from the ledger when `--milestone` is absent.
- **`QuickTests` (10)** — the missing note; an incomplete note naming the
  missing key; a placeholder value counting as absent; the fused Change/Prove
  action; a failing check capture blocking; the close command's exact flags;
  a close `FAIL`; a close `PASS` without `--commit`; the complete lane at
  exit 3; `--lane auto` picking quick, and warning when both lanes' artifacts
  are present.
- **`OutputTests` (5)** — auto-detecting bugfix; every contract key present;
  the human render; the `exit 1` ⟺ `blocked_by` invariant; an explicit
  `--ledger` path honoured.

## Live walk (recorded 2026-09-07)

A standalone bugfix lane driven end to end in a throwaway git repo against the
real gates, with the driver consulted at each boundary: Phase 0 (exit 0, write
the report) → Phase 0 (exit 1, intake `MISSING`) → intake `PASS` → Phase 1
(exit 0) → RED captured → Phase 2 (exit 0, write the RCA) → RCA written →
**Phase 2 (exit 1, route gate `MISSING`)** → route `PASS` (`FAST`) → Phase 3
(exit 0) → delegation recorded → Phase 4 (exit 0, GREEN missing) → GREEN
captured → Phase 4 (exit 1, `check_red_green.py` `MISSING`) → gate `PASS` →
Phase 5 (exit 0, `review_package.py`) → package written → Phase 5 (exit 0,
delegate Luna) → verdict appended → Phase 5 (exit 1, commit gate `MISSING`) →
commit gate `--commit` `PASS` → **exit 3** with the close steps.

The skip was taken one step further on a copy of the root: a builder delegation
was recorded while the route gate had still never run, and the driver stayed at
Phase 2 at exit 1 rather than reading past it to Phase 4.
