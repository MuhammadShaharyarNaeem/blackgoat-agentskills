# Case: mechanical-pipeline

## What this proves

An integration eval for `skills/pipeline-tools/scripts/`: `next_milestone.py`,
`update_state.py`, `check_commit_gate.py`, and `run_quiet.py` each have their own
`--self-test` (unit level, in-process, no real git). Nothing previously proved that
they **compose** correctly across a real milestone's lifecycle against a real
on-disk git repo — that `next_milestone.py`'s output feeds a milestone title
`check_commit_gate.py` can match, that a blocker `update_state.py` writes actually
gates the same milestone in `check_commit_gate.py`, that a resolved blocker actually
clears the gate, that `--verify-tree` sees real `git status` output, that a real
`--commit` produces a real commit `git log` can see. This case builds a disposable
temp git repo and walks one milestone start-to-finish through all four tools,
asserting exact exit codes and JSON fields at each step.

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
It is **not** wired into `run-evals.ps1` or `weekly-check.ps1` for this reason —
running it costs nothing and needs no `-Confirm` gate.

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
check_commit_gate,run_quiet}.py`, `check_commit_gate.py`'s JSON shape, or the
`bgpdd-build` milestone lifecycle it encodes (cursor -> Request Changes -> blocker
-> resolve -> verify-tree -> commit -> advance -> rendered-evidence gate). Each
tool's own `--self-test` should still be run first (it's faster and pinpoints unit
failures); this case is the composition check on top of that.

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
backslash path, `evidence\m3.png`) and create the file -> gate passes -> a noisy
`run_quiet.py` child (80 noise lines + 1 `error CS1002` line, exit 1) is asserted to
keep stdout short while the on-disk log holds all 81 lines.

## Tool defect found

**FIXED 2026-08-09**: `check_commit_gate.py`'s `check_undeclared_tree` now parses a
porcelain path ending in `/` as a directory entry — normalized with its trailing
slash restored, allowed iff it's `.docs/`-prefixed or a declared `--changed-files`
path lies under it, otherwise reported undeclared with the slash preserved. See
`skills/pipeline-tools/SKILL.md`'s `--verify-tree` section ("Directory-shaped
porcelain entries") for the current contract, and `check_commit_gate.py`'s
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

All 13 steps passed (`RESULT: PASS (13/13 steps passed)`), re-run twice more for
determinism (no flakiness from mtime/clock races — the script uses a synthetic
monotonic clock with `os.utime` rather than relying on real-clock resolution for
staleness ordering).
