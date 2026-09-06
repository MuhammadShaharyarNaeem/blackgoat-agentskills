# check_quick_close.py — depth

Contract spine: `../SKILL.md`, `## check_quick_close.py`. This file carries the
rationale, the two labelled divergences, the reuse decision and the self-test
inventory.

## What failure this converts

`/bgpdd-quick` has one gate where the other lanes have five, because it has no
squad to distribute restraint across. Everything it checks is something the
Orchestrator would otherwise be asked to police in itself, at the moment it
least wants to (CLAUDE.md convention #9). Specifically:

1. **"I'll write the note after."** Then the note is a summary, the Where line
   always matches, and the declaration checks nothing. The gate cannot see when
   the note was written — but `note_where_mismatch` makes a note written *first*
   and then diverged from a hard failure, which is the only half of the problem
   a script can hold.
2. **"The check passed, I ran it."** A narrated result is a claim. The sidecar
   is the difference between a capture and a sentence; `sidecar_missing` and
   `sidecar_hash_mismatch` are copied verbatim from `check_red_green.py` for
   exactly the reason that gate has them — as is
   `sidecar_body_disagrees`, which covers the one thing the hash does not:
   the sidecar's own `exit_code` and `finished`, both of which this gate reads
   and either of which a one-line edit could set.
3. **"I ran it, then made one more tweak."** `capture_stale`. The single most
   likely honest error in this lane, because the whole lane is fast enough for
   the check and the edit to blur together.
4. **"While I was in there…"** `undeclared_tree_changes`. A quick lane with no
   review is the easiest place in the plugin to ship an unreviewed extra edit,
   and the size bound is worthless if uncounted files can ride along.
5. **"The test was wrong anyway."** `frozen_path_modified`. The oldest way to
   turn red green.
6. **"It's four files, but they're tiny."** `size_bound_exceeded`, with no
   waiver. See below.

## The two labelled divergences (convention #8)

### Freshness compares at one-second resolution with `>=`

`check_red_green.py` orders RED against GREEN with a strict `>` and rejects
equal stamps, reasoning that a real RED and GREEN are a fix round apart so a
pair inside one second is suspect. That reasoning does not transfer. Here the
two things compared are *an edit* and *the check of that edit*, and a one-line
edit followed immediately by `run_quiet.py` routinely lands inside the same
wall-clock second. The sidecar's `finished` stamp is whole seconds, so the file
mtime is floored to the second before comparison and equality passes.

What this costs: a check that ran a few hundred milliseconds *before* an edit
inside the same second is accepted. What a strict `>` would cost: every honest
same-second run rejected, which is the failure mode that gets a gate routed
around rather than satisfied.

### `--max-changed-files` defaults to 3, and there is no `--waiver`

Both halves diverge from `check_commit_gate.py`.

- **Default-on.** In the bugfix lane the bound is an extra assertion the caller
  opts into; unset, `check_commit_gate.py` simply does not apply it. Here the
  bound *is* the lane — a "quick change" that touches nine files is not one —
  so a forgotten flag silently deleting the definition is precisely the defect
  this gate exists to prevent. It is applied unless overridden.
- **No waiver.** `check_commit_gate.py --waiver` is deliberately hand-typed: no
  script can verify a judgement call, so it buys durability and attributability
  instead. That trade is right when there is nowhere else for the work to go.
  It is wrong here, because there *is*: an overrun in this lane has three named
  destinations, and the gate's message prints them. A waiver would let the one
  bound that defines the lane be self-certified by the person exceeding it, and
  the lane would decay into `/bgpdd-lite` without the traceability.

## Why the frozen check reads status letters

`--frozen tests/` has to forbid *editing* an existing test while permitting
*adding* one — "add a test" is a stated use case of the lane, and a rule that
forbids its own use case gets dropped rather than obeyed. `git status
--porcelain` already carries the distinction: `??` (untracked) and `A`/`AM`
(newly added to the index) are new files; `M`, `D`, `R`, `C`, `U` in either the
index or worktree column are changes to something that already existed. Both
columns are read, so staging a frozen edit first is not a way around it.

The residual: a frozen file already **committed** before the gate runs is
invisible to `git status`. This lane's gate performs the commit itself, so the
only way to reach that state is to commit by hand — which also skips the gate
entirely, and no flag can defend against not being run.

## Why `--frozen` takes globs, and why it still has no default

`--frozen tests/` only works in a repo that keeps its tests in a directory.
Several stacks the plugin supports do not: a Vue SPA colocates `Foo.spec.ts`
beside `Foo.vue`, a .NET solution scatters `*.Tests` projects, a Node package
colocates `*.test.js`. In those repos the operator either froze nothing — and
the oldest way to turn red green was open again — or froze `src/`, which also
forbids the change. Neither is a rule anyone keeps. So a `--frozen` value
carrying `*`, `?` or `[` is now matched as a glob against the repo-relative
forward-slash path; anything else is still a path or directory prefix, so every
existing `--frozen tests/` caller is untouched.

The matcher is hand-rolled rather than `fnmatch`, for one reason worth naming:
`fnmatch`'s `*` crosses `/`, so `tests/*.py` would silently mean
`tests/**/*.py`. A freeze *wider* than written is the failure mode that gets a
flag distrusted — the operator narrows the pattern, sees it still catch
everything, and drops the flag. Segment semantics instead: `**/` is zero or more
leading segments, a trailing `**` is the rest of the path, `*` and `?` stop at
`/`, `[...]`/`[!...]` are character classes. Patterns are folded to forward
slashes and `normcase`d exactly as the candidate paths are, so a Windows-typed
`tests\**\test_*.py` matches and a case-insensitive platform compares like one.

**There is still no default, and that is the point.** `detect_stack.py` can now
name the right globs per stack, so the temptation is to bake them in here. A
gate that guesses what is frozen and guesses wrong produces the same output as a
change with genuinely no test to protect: a clean pass. That is the
silent-no-op class convention #9 exists to prevent, and it would be worse here
than a missing flag — a missing flag is visible in `gates.jsonl` under `argv`,
a wrong guess is not. The detector proposes, the spine passes the globs
explicitly, the ledger records exactly which ones fired.

## Two operational residuals, found in the shipping smoke

1. **A repo that does not gitignore its build detritus blocks itself.** In the
   first smoke run, `python -c "import src.coupon"` — the note's own
   `How verified` command — created `src/__pycache__/`, which `git status`
   reported and the gate correctly called `undeclared_tree_changes`. That is
   the repo's `.gitignore` defect, not the gate's: `git status` is the right
   notion of "dirty", and a gate that carved out an ignore list of its own
   would be inventing policy about which untracked files do not count. Adding
   `__pycache__/` to `.gitignore` cleared it. Expect the same for `node_modules`,
   `bin/`, `obj/`, `dist/` — if the check's own byproducts show up here, fix the
   repo.
2. **`--commit` commits the source files, not the `.docs/` record.** Only the
   declared `--changed-files` are staged (the same behaviour as
   `check_commit_gate.py`), so `note.md`, the capture and `gates.jsonl` remain
   in the working tree. This is deliberate and not fixable by staging them
   here: the ledger line for *this* run is appended AFTER the commit, so any
   `gates.jsonl` committed by the gate would necessarily be the stale
   pre-verdict version. The lane's artifacts are a durable on-disk record; who
   commits them is the user's call.

## Why copy rather than import

Family convention: pure stdlib, one self-contained file per script, no shared
module. `sha256_file`, `append_ledger`, `GateError`, `sidecar_path_for`,
`load_sidecar`, `parse_finished`, `run_git`, `parse_porcelain_line`,
`normalize_repo_path`, `check_undeclared_tree` and `perform_commit` are copied
from `check_commit_gate.py`, `check_red_green.py` and
`check_runtime_evidence.py`. Nothing is weakened in the copy; the two
intentional differences (freshness comparison, the status-letter filter in the
frozen check) are the divergences above, both asserted by a named self-test.

## Self-test inventory (46 cases)

Every case builds a real temp git repo (`git init`, one base commit) so the
tree, staging and commit checks run against real `git`, not a mock.

**Happy path** — a clean one-file change passes; `.docs/` artifacts are never
counted undeclared.

**The note** — missing file; a missing `How verified` line; placeholder text;
note lines inside a fence not counting; a Where line naming a different file;
a Where line short of the declared set; comma/backtick Where forms accepted;
a BOM-prefixed note still parsing.

**The capture** — missing file; a file that is not a capture; hand-typed
(no sidecar); edited after recording (hash mismatch); non-zero exit; a
non-integer `exit_code`; a capture older than the edit; a capture in the *same
second* as the edit passing (`test_capture_in_the_same_second_as_the_edit_is_fresh`
— the freshness divergence above); an unparseable `finished`.

**The sidecar's own fields** — the hash covers the capture FILE, so the six
agreement cases cover what it cannot: a flipped `exit_code` (a check that
FAILED, sidecar set to 0) caught by the body; a `finished` pushed past the
edit's mtime, caught *before* `capture_stale` can be satisfied; an agreeing
pair recording `capture_body_agrees`; a 1s pre-2.4 render skew still passing;
a capture with no header pair (`capture_header_missing`); and a command
transcript that PRINTS `- Exit code: 1` inside the fence supplying nothing.

**The tree** — a declared path that does not exist; a fourth file slipped in
undeclared; an edited test caught by `--frozen`; a declared test edit caught
anyway; a *staged* frozen edit caught anyway; a newly added test passing
(`test_a_newly_added_test_passes_the_frozen_check`); a clean run leaving
`frozen_modified` empty.

**`--frozen` as a glob** — a colocated `src/widget.spec.ts` caught by
`**/*.spec.ts` where `tests/` sees nothing; `tests/*.py` NOT matching
`tests/deep/test_b.py` while `tests/**` does (the anti-`fnmatch` case); a
leading `**/` matching zero segments; a Windows-separator pattern
(`tests\**\test_*.py`) matching; a NEW file matching a glob still passing; a
metacharacter-free value still behaving as a prefix; and
`test_glob_to_regex_unit_cases`, a seventeen-row table over the translator
itself (`**/*.test.*`, `**/*.Tests/**`, `**/test_*.py`, `**/__tests__/**`,
`**/*.Tests.ps1`, `?`, `[ab]`, `[!ab]`).

**The size bound** — an overrun whose message names both `/bgpdd-bugfix` and
`/bgpdd-lite`; `test_the_size_bound_applies_without_the_flag` (the default-on
divergence).

**The commit** — `--commit` commits *exactly* the declared files, asserted by
reading `git show --name-only` back; and a failing gate with `--commit` commits
nothing.

**Usage and ledger** — six exit-2 usage forms; a PASS ledger record carrying the
note's and the sidecar's hashes and the verbatim `argv`; FAIL and ERROR records.

**End to end** — `test_real_run_quiet_capture_passes` drives the real
`run_quiet.py` to produce the capture and sidecar, proving the composition
rather than the fixture.
