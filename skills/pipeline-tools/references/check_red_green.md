# check_red_green.py — depth

Contract spine: `../SKILL.md`, `## check_red_green.py`. This file carries the
rationale, the reuse decision and the self-test inventory.

## What failure this converts

The old `/bgpdd-bugfix` spine already said the right thing in prose: *"A GREEN
with no RED sibling is an unproven test, and she reports it as such rather than
passing it."* That is a restraint asked of an agent at the moment the work looks
finished, which CLAUDE.md convention #9 says must become an artifact.

Three specific escapes the prose could not close:

1. **A green with no red at all.** The builder writes a test that never failed,
   runs it after the fix, and reports green. Nothing distinguishes that from a
   proven fix.
2. **A red and a green of different commands.** The RED was `dotnet test
   --filter CouponTests`; the GREEN was `dotnet test --filter SmokeTests`. Both
   captures are real, both exit codes are honest, and the pair proves nothing.
   This is the escape the identical-`argv` check exists for, and it is the one
   a human reviewer misses most reliably.
3. **Edit the test until it passes.** In the old design the builder owned the
   RED test, so "make it green" and "make it not assert" were the same move.
   The new design splits ownership — Quinn produces RED, the builder produces
   the fix — and this gate is what makes the split *load-bearing* rather than
   procedural: the GREEN run replays the command recorded in the RED sidecar,
   so an edited check fails the gate instead of passing it.

## Why the sidecar, again

Everything in a capture's prose is authored. `run_quiet.py --capture` writes
`<capture>.meta.json` beside every capture, recording the child `argv`, the real
`exit_code`, and `capture_sha256` over the finished file's bytes. That sidecar is
the only part of the pair a gate can believe:

- **No sidecar** → the capture is indistinguishable from a hand-typed one.
- **Hash mismatch** → the artifact was edited after it was recorded, including
  plausibly (a corrected exit code, a trimmed stack).
- **`argv`** → the two runs can be compared as *the same command*, which no
  amount of reading the two capture files can establish.

## Duplicated, not imported

`check_runtime_evidence.py` already validates sidecars this way. This file
duplicates `sidecar_path_for`, `load_sidecar` and `sha256_file` rather than
importing them, per this family's convention (stdlib-only, one file each, no
shared module — `GateError` and `append_ledger` are duplicated across seven
files). The duplication is deliberate and the logic is **not weakened**: the one
difference is that the RED role inverts the exit-code expectation, which is the
entire point of a RED capture and would be wrong to share.

The alternative considered was invoking `check_runtime_evidence.py` as a
subprocess (the pattern `check_commit_gate.py` uses). Rejected: that gate demands
a `**Runtime evidence:**` citation in a durable report, an `evidence/runtime/`
prefix, an out-of-process transport and an allowlisted probe client — none of
which a RED test-runner capture has or should have, and `exit_code != 0` is a
hard failure there. Delegating would mean fighting the child gate's contract
rather than reusing it.

## One-second resolution, and why equality fails closed

`finished` is `%Y-%m-%dT%H:%M:%SZ` — whole seconds. Two runs inside the same
second produce equal stamps, which do **not** order them. Three options existed:

- `green >= red`: accepts a green taken *before* the fix whenever both land in
  one second. Rejected — that is the exact failure the check exists for.
- Tie-break on the capture files' mtimes: mtime is author-mutable, so the
  tie-break would be the weakest link in an otherwise machine-owned chain.
- Strict `>`, equality rejected as `green_not_newer`. **Chosen.** A real RED and
  GREEN are a fix round apart, so the cost is a re-take in the pathological
  case, and the gate never says "ordered" when it cannot tell.

The self-test's end-to-end case (`test_real_run_quiet_pair_passes`) has to sleep
1.1s across a second boundary for exactly this reason, and says so inline.

## Why `green_runs_short` is exit 1, not exit 2

`--green-runs 5` with three `--green` captures *looks* like a usage error. It is
recorded as a gate **failure** instead, because the semantic is "the flake
evidence is short" — and a gate whose evidence is incomplete must fail closed,
not error out in a way a caller might read as "not applicable". The genuine usage
errors here are missing `--red`/`--green` and `--green-runs < 1`.

## Ledger inputs include the sidecars

`ledger_inputs()` records each capture **and** its `.meta.json`. Recording only
the argument paths would leave a hole: `check_commit_gate.py
--require-ledger-gates check_red_green.py` re-hashes the recorded inputs, so a
sidecar whose `exit_code` was edited *after* this gate passed would still satisfy
the commit gate. With the sidecars recorded, that edit is `ledger_stale`.

## Self-test inventory (24 cases)

- **Happy paths (2)** — one RED + one GREEN; five green runs under
  `--green-runs 5`.
- **Provenance (5)** — GREEN with no sidecar; RED with no sidecar; an edited
  capture failing `capture_sha256`; a sidecar that is a JSON array (reads as
  absent); a sidecar whose `exit_code` is the string `"0"`.
- **Pair identity (2)** — mismatched commands; a sidecar with no `argv`.
- **Ordering (3)** — GREEN older than RED; GREEN at the same instant as RED;
  an unparseable `finished`.
- **Exit-code semantics (3)** — a RED that exited 0; a GREEN that still fails;
  4-of-5 green under `--green-runs 5`.
- **Supply (1)** — three greens under `--green-runs 5`.
- **Structure (2)** — a missing capture file; a plain note with no
  `## Captured output` (but a valid sidecar).
- **Encoding (1)** — a BOM-prefixed sidecar still parses.
- **Usage + ledger (3)** — missing `--red` / `--green` are exit 2;
  `--green-runs 0` is exit 2; the ledger records a PASS with capture *and*
  sidecar hashes, and records FAIL and ERROR runs too.
- **End-to-end (1)** — a pair produced by the real `run_quiet.py`, red exiting
  3 and green exiting 0 on the same command.

## Scope limits

- It never runs anything and opens no socket. It compares two recordings.
- It cannot tell whether the command *is* the bug's reproduction — that is
  `check_bugfix_intake.py`'s field and the Orchestrator's brief.
- It cannot tell whether the fix is *correct*, only that the same command
  changed from failing to passing. Luna and the full-suite floor cover the rest.
- **Known and accepted: the sidecar is provenance, not tamper-proofing.** A
  hand-edited `exit_code` in a sidecar is undetectable here -- `capture_sha256`
  covers the capture file's bytes, not the sidecar's own. So is a hand-forged
  ledger PASS carrying the right hashes: `check_commit_gate.py
  --require-ledger-gates` re-hashes the recorded inputs but cannot tell who
  wrote the record. The ledger is an **audit trail** -- it makes a skipped or
  stale gate visible and attributable -- not a tamper-proof log, and no gate in
  this family claims otherwise. What it does buy: every one of those forgeries
  is now a deliberate, written act by the Orchestrator rather than an omission
  nobody can see afterwards.
