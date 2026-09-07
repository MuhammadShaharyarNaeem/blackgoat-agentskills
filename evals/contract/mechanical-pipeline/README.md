# Case: mechanical-pipeline

## What this proves

An integration eval for `skills/pipeline-tools/scripts/`: `next_milestone.py`,
`update_state.py`, `check_commit_gate.py`, `run_quiet.py`,
`check_runtime_evidence.py` and `check_acceptance_suite.py` each have their own
`--self-test` (unit level, in-process, no real git). Nothing previously proved that
they **compose** correctly across a real milestone's lifecycle against a real
on-disk git repo — that `next_milestone.py`'s output feeds a milestone title
`check_commit_gate.py` can match, that a blocker `update_state.py` writes actually
gates the same milestone in `check_commit_gate.py`, that a resolved blocker actually
clears the gate, that `--verify-tree` sees real `git status` output, that a real
`--commit` produces a real commit `git log` can see. This case builds a disposable
temp git repo and walks one milestone start-to-finish through all six tools,
asserting exact exit codes and JSON fields at each step.

The two evidence gates (steps 10-11) are here for one composition in particular:
`check_acceptance_suite.py` proves a manual step's cited capture **exists** under
`evidence/runtime/`, while `check_runtime_evidence.py` is what **opens** that same file
and judges whether the observation inside it is honest. Step 11a's manual step cites the
very capture step 10a accepted, so "running both is the point"
(`skills/pipeline-tools/SKILL.md`) is asserted rather than assumed. This is also the only
place the milestone-scoped runtime gate and the feature-scoped acceptance gate are
exercised against the same on-disk tree — and it costs zero tokens, which is why the pair
earns its keep here rather than in an LLM contract case.

The fixtures also carry the provenance half of the contract: step 8c's rendered
evidence is a real 1x1 PNG (non-empty, correct magic bytes, newer than the changed
file), and each capture in steps 10a/10b is written beside a `run_quiet.py`-shaped
`.meta.json` sidecar whose `capture_sha256` matches the artifact. Both were added
when the gates started refusing an empty placeholder and a sidecar-less capture:
the fixture exercises the new contract rather than opting out of it.

## Why this needs no `claude -p` and is exempt from runs=5

This is a **zero-LLM** case — every step is a subprocess call to a deterministic
stdlib-Python CLI against fixture files this script itself writes. There is no
persona invocation and no output-shape judgment call; every assertion is an exact
exit code or JSON field compared against a value that follows mechanically from the
tool's documented contract (`skills/pipeline-tools/SKILL.md`). The suite's `runs=5`
/ threshold `4/5` doctrine (see `evals/README.md`) exists specifically to average
out **LLM output variance** across repeated persona runs — there is no variance
source here to average out. A single run is a legitimate final verdict, which is
also why this case does not follow the `case.md` + `fixture/` + `grade.ps1` shape
`run-evals.ps1` expects: it isn't a `claude -p` contract case, it's a plain script.
It is therefore **not dispatchable** by `run-evals.ps1` (which discovers contract suites
by `case.md` + `grade.ps1`, neither of which this directory has). `weekly-check.ps1` does
surface it, but as a direct command under its zero-token **Mechanical checks** heading
rather than as an eval to be confirmed — running it costs nothing and needs no `-Confirm`
gate.

## How to run

```bash
python run.py
```

Exit 0 only if every step passes. Prints a `[PASS]`/`[FAIL]` line per step and a
final `RESULT:` line; on failure the detail line under a step shows the raw JSON
the tool under test produced. The script builds its own temp directory (git repo +
fixtures) and removes it unconditionally, including on failure.

## When to run it

After any change to `skills/pipeline-tools/scripts/{next_milestone,update_state,
check_commit_gate,run_quiet,check_runtime_evidence,check_acceptance_suite}.py`, any of
those tools' JSON shapes, or the `bgpdd-build` milestone lifecycle it encodes (cursor ->
Request Changes -> blocker -> resolve -> verify-tree -> commit -> advance ->
rendered-evidence gate -> runtime-evidence gate -> acceptance gate). Each tool's own
`--self-test` should still be run first (it's faster and pinpoints unit failures); this
case is the composition check on top of that.

## Fixture shape

A temp dir gets `git init` + a configured `user.name`/`user.email`, then:

- `.docs/proj/implementation/plan.md` — 3 milestones: #1 already `[x]`, #2
  `Milestone 2 — API Layer` ([API], 2 tasks), #3 `Milestone 3 — UI Layer` ([UI],
  1 task).
- `.docs/proj/orchestrator-state.json` — schema-shaped, `milestone_cursor` preset
  to milestone 3's title (deliberately stale — the pending milestone is #2).
- An initial **scaffold commit** of `.docs/` and a `src/.gitkeep` before any
  `--verify-tree` step. This is a deliberate fixture choice, not part of the
  literal step list — see "Tool defect found" below for why it's necessary.

Then, in order: derive next milestone (asserts NEXT / milestone 2 / API / stale
cursor) -> set cursor + pipeline -> builder diff + Request-Changes review -> gate
fails on verdict -> add scoped blocker + Approve review -> gate still fails on the
blocker -> resolve the blocker (rejected without `--evidence`, accepted with it,
`blockers-resolved.log` written) -> `--verify-tree` catches an undeclared file ->
remove it, `--verify-tree --commit` succeeds and a real commit lands -> mark
milestone 2 `[x]` -> derive next milestone (asserts NEXT / milestone 3 / UI) ->
`--require-rendered-evidence` fails with no evidence cited -> cite it (with a
**backslash** path, `evidence\review\m3.png` — three segments, because the provenance
predicate requires `evidence/review/` plus at least one more, and rejects a two-segment
`evidence\m3.png`) and create the file -> gate passes -> a noisy
`run_quiet.py` child (80 noise lines + 1 `error CS1002` line, exit 1) is asserted to
keep stdout short while the on-disk log holds all 81 lines.

Then the two evidence gates, on fixtures the script writes into the same repo:

- `.docs/proj/implementation/evidence/runtime/m2-contacts-get.md` and its `-bare`
  sibling — identical captures (out-of-process `curl` transport, `http://localhost:5142`,
  status 200, mtime set from the synthetic clock **after** `src/api.cs`) differing in one
  thing only: the envelope body vs. the bare `{"id":1,"total":9}`. That is the 2026-08
  incident reduced to its single variable, and it is what makes 10a/10b a real pair rather
  than two unrelated cases.
- `.docs/proj/acceptance-matrix.md` — one `AS-1` scenario, 3 steps, one `manual`, with
  `[inverse of 1]` on the delete step; plus a green `acceptance-results.md` whose manual
  step cites the 10a capture, and an `acceptance-results-unevidenced.md` whose manual step
  reports `PASS` on the agent's word alone.

`check_runtime_evidence.py` accepts the envelope capture (exit 0, `fresh: true`,
`status: 200`) and rejects the bare one (exit 1,
`missing_keys: ["isSuccess","notifications"]`, nothing stale, no in-process transport) ->
`check_acceptance_suite.py` passes the green walkthrough (exit 0, 3 gated steps, 3 passed)
and fails the unevidenced one (exit 1, `unevidenced_manual: ["AS-1.3"]`, the same key in
`not_run`, `failed` empty) — an unevidenced manual `PASS` reading as NOT RUN rather than as
a failure is the crux of that gate and is asserted field-by-field.

## Tool defect found

**FIXED 2026-08-09**: `check_commit_gate.py`'s `check_undeclared_tree` now parses a
porcelain path ending in `/` as a directory entry — normalized with its trailing
slash restored, allowed iff it's `.docs/`-prefixed or a declared `--changed-files`
path lies under it, otherwise reported undeclared with the slash preserved. See
`skills/pipeline-tools/references/check_commit_gate.md`'s `--verify-tree`
rules ("Directory-shaped porcelain entries") for the current contract, and `check_commit_gate.py`'s
`--self-test` for the fresh-`git init`-no-scaffold-commit regression cases. The
original writeup below is kept as history — the defect it describes is real and
was reproduced exactly as written before the fix.

**`check_commit_gate.py`'s `--verify-tree` misreports legitimate changes as
undeclared the first time a directory is untracked, because it assumes
`git status --porcelain` always reports individual file paths.** It doesn't:
in its default (non `--untracked-files=all`) mode, git collapses an entirely
untracked directory into a single `"?? <dir>/"` line rather than listing the files
inside it (verified directly: a repo with a brand-new `.docs/` and `src/`, each
containing exactly one new file, produces `?? .docs/` and `?? src/`, not
`?? .docs/proj/... ` / `?? src/api.cs`).

`check_undeclared_tree`'s `normalize_repo_path()` then resolves that path and takes
it relative to the repo, which strips the trailing slash: `.docs/` -> `.docs`. Two
things break as a result:

1. The `.docs/` carve-out (`norm.startswith(".docs/")`) no longer matches — `.docs`
   does not start with `.docs/` — so a legitimate, always-allowed `.docs/` change is
   flagged as an undeclared change.
2. A **declared** file's own directory, if that directory has never been tracked
   before, is reported as the bare directory rather than the file, so it doesn't
   match the declared set (`{"src/api.cs"}`) either — a correctly-`--changed-files`-declared
   file's own containing directory shows up as undeclared.

Reproduced directly against the shipped module:

```python
>>> import check_commit_gate as g
>>> g.normalize_repo_path(g.parse_porcelain_line('?? .docs/'), '.')
'.docs'
>>> _.startswith('.docs/')
False
```

**Why this eval doesn't just fail on it**: real `bgpdd-build` runs build on an
already-established repo (per `bgpdd-build/SKILL.md`'s Git Workflow — a feature
branch off an existing default branch), so `.docs/` and the code directories are
already tracked from earlier phases by the time a milestone's `--verify-tree` gate
first runs. A brand-new `git init` with zero commits — which is what "build a
disposable temp git repo" literally means — doesn't reproduce that precondition, so
this run's fixture adds one scaffold commit (`.docs/` + `src/.gitkeep`) before any
`--verify-tree` step specifically to match the tool's real operating precondition
instead of tripping over an orthogonal git-porcelain quirk. **The tool itself was
not patched.** The defect is real and worth fixing (e.g. run
`git status --porcelain --untracked-files=all`, or treat a directory-shaped
undeclared entry ending in `/` as a prefix match against the declared set and the
`.docs/` carve-out rather than an exact match) — but per this task's scope, fixing
`skills/pipeline-tools/scripts/check_commit_gate.py` was explicitly out of bounds
for this eval-authoring pass.

## Result of the last authored run

All 17 steps passed (`RESULT: PASS (17/17 steps passed)`), re-run twice more for
determinism (no flakiness from mtime/clock races — the script uses a synthetic
monotonic clock with `os.utime` rather than relying on real-clock resolution for
staleness ordering).

Step count history: 13 steps before the two evidence gates were added (steps 10a, 10b,
11a, 11b), 17 after.

## Added in 2.6.1 (the audit-fix wave)

Steps 12c-12d and 17-21b cover the gate-contract changes that closed the
2026-09-07 audit's Metric-19 and Metric-20 findings. Each is composed against
the same real git repo the rest of the suite builds, and each pairs a refusal
with the clearing case, because a gate proven only against failure is a gate
that fails closed on everything.

- **12c/12d** — `check_agent_report.py`: ONE real capture cited by three
  unrelated check lines is now `capture_command_mismatch` (exit-code equality
  cleared all three, since every clean scan claims 0 or 1), and
  `--allow-uncaptured` does not waive it. 12b was rewritten in the same change:
  its report now names the argv actually recorded, because the eval must not
  model a report that lies about its command.
- **17a-17c** — `check_handoff.py --advisory`: Forge's propose handoff refused
  without the flag, accepted with it, `advisory: true` in the chained ledger
  line, and `<changed_files>` still required for a builder.
- **18a-18c** — `mark_milestone.py --reopen`: the real round trip on this
  suite's own plan, read back through the real `next_milestone.py`, plus the
  four usage refusals that keep a reopen evidenced.
- **19a-19e** — `check_tier1_provenance.py`: a future-dated stamp; drift still
  exit 0 by default; `--verify-current` turning the same drift into
  `tier1_drift`; `--allow-drift` and both of its misuse refusals.
- **20/20b** — `record_run.py`: an unresolvable `--model` is exit 2 and writes
  nothing (it used to record `tier: null` and silently delete the inversion
  check), and `dep` counts as a producer.
- **21/21b** — `guard_action.py` driven through real stdin: eight Bash
  mutations of a ledger and of a frozen test all DENY while three read-only
  commands allow; and the lane's own `--commit` PASS un-arms rule 1 for the
  sanctioned local merge while another milestone's does not.
