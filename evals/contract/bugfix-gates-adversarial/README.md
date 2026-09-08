# Case: bugfix-gates-adversarial

## What this proves

An adversarial composition eval for the four gates `/bgpdd-bugfix` runs:
`check_bugfix_intake.py`, `next_bugfix_route.py`, `check_red_green.py` and
`check_commit_gate.py`'s size terms. Each already has its own `--self-test` (33, 49,
24 and 76 cases) which proves its predicate in-process against synthetic fixtures.
Nothing previously proved that they **refuse a fabricated run when composed in the
order the lane invokes them**, against real `run_quiet.py` captures, a real ledger
that one gate writes and the next reads, and a real on-disk git repo.

Composition is where the interesting refusals live, because three of them are
cross-gate by construction:

- **A route cannot run without a recorded intake PASS** (step 5) and **cannot run on
  a report edited after that PASS** (step 6). Both facts live in the ledger one gate
  wrote and another reads; neither gate can assert them alone.
- **A RED and a GREEN are only a proof if they are the same command** (steps 8 and
  11). Two runs of `run_quiet.py` are what produce the sidecars, and the route gate
  and the red/green gate each read a different half of that pair.
- **The shipped templates must fail their own gates** (steps 1 and 15). A
  `bug-report-template.md` that passes the intake gate makes "copy the template and
  run the gate" a bypass; an `rca-template.md` whose placeholder `## Size waiver`
  satisfies `--waiver` makes "copy the template" a size bypass. Both are asserted
  here against the **real shipped files**, not against a copy this script writes — so
  editing either template breaks this case rather than silently opening the bypass.

The probe under test is deliberately one whose exit code is a pure function of a
sentinel file (`state.txt`), because that is what lets **one identical argv** be a
RED before the fix and a GREEN after it. A fixture where RED and GREEN necessarily
differ in their command cannot exercise `check_red_green.py`'s central term at all.

The reproduction command is quoted — `python probe.py -H "Content-Type:
application/json"` — so step 7 exercises the token-list comparison
(`red_match_strategy`) rather than assuming it. A string compare rejected every
correctly quoted command; this asserts the fix, on a real capture.

## Why this needs no `claude -p` and is exempt from runs=5

This is a **zero-LLM** case: every step is a subprocess call to a deterministic
stdlib-Python CLI against fixture files this script writes. There is no persona
invocation and no output-shape judgement call — every assertion is an exact exit code
plus a naming JSON field, compared against a value that follows mechanically from the
tool's documented contract (`skills/pipeline-tools/SKILL.md`). The suite's `runs=5` /
threshold `4/5` doctrine (see `evals/README.md`) exists to average out **LLM output
variance** across repeated persona runs; there is no variance source here. A single
run is a legitimate final verdict.

That is also why this case does not follow the `case.md` + `fixture/` + `grade.ps1`
shape `run-evals.ps1` expects, and is therefore **not dispatchable** by it —
`Get-ContractCases` discovers a contract case by the presence of *both* `case.md` and
`grade.ps1`, and this directory has neither, exactly like
`contract/mechanical-pipeline/`. Run it as a plain script. It costs nothing and needs
no `-Confirm` gate.

**Every assertion checks the exit code AND a naming JSON field.** These gates have
three exit codes and several problem codes each, so an exit code alone is routinely
right for the wrong reason — a `2` that should have been a `1`, or a size failure that
was really a stale-review failure. Step 14 is the clearest example: it asserts
`size_ok: false` **and** `changed_file_count: 6` **and** `verdict: "Approve"`, so the
step cannot pass because the review was rejected.

## How to run

```bash
python run.py
```

Exit 0 only if every step passes. Prints a `[PASS]`/`[FAIL]` line per step and a final
`RESULT:` line; on failure the detail line under a step shows the raw JSON the tool
under test produced. The script builds its own temp directory (git repo + fixtures) and
removes it unconditionally, including on failure.

It requires `python` **on PATH** (not just as `sys.executable`): the reproduction command
it asserts on is invoked by bare name, because a `- Command:` line has to be a plain
argv-runnable string. If `python` is not on PATH the script prints
`RESULT: ERROR` and exits 2 rather than reporting a vacuous pass.

## When to run it

After any change to `skills/pipeline-tools/scripts/{check_bugfix_intake,
next_bugfix_route,check_red_green,check_commit_gate,run_quiet}.py`, to either template
under `skills/bgpdd-bugfix/references/`, or to the gate chain
`skills/bgpdd-bugfix/SKILL.md` encodes (intake -> RED -> route -> fix -> GREEN ->
red/green -> commit). Each tool's own `--self-test` should still be run first — it is
faster and pinpoints unit failures; this case is the composition and adversarial check
on top of that.

Its LLM sibling is `contract/bgpdd-bugfix-lane/`, which measures whether the lane
*invokes* these gates at all. This case measures whether they hold when invoked. Neither
substitutes for the other: a lane that runs every gate on fabricated input passes the
sibling case's ledger criteria and is caught here, and a set of gates that refuse
everything correctly is worthless if the lane never runs them.

## Fixture shape

A temp dir gets `git init` + a configured `user.name`/`user.email`, then:

- `probe.py` — exits `22` if `state.txt` reads `broken`, `0` otherwise, and prints its
  state either way so the capture has a body.
- `state.txt` — `broken` at first; flipped to `fixed` between step 8 and step 9, which
  is the "fix" this case's RED/GREEN pair brackets.
- `.docs/bugfix/probe-exit-code/` — the standalone-route bugfix root: `bug-report.md`
  (conforming), `bug-report-see-chat.md` (the unquoted-command variant),
  `rca.md` (one root-cause file, green baseline, estimate 1 — routes FAST),
  `rca-oversized.md` (estimate 6 plus a hand-typed `## Size waiver`),
  `review-report.md` (`**Verdict:** Approve`), `orchestrator-state.json` (no blockers),
  `gates.jsonl`, `gates-empty.jsonl`, and `evidence/red/` + `evidence/green/`.
- `src-1.txt` .. `src-6.txt` — six real declared files for the commit-gate size steps.
  Their mtimes and the review report's come from a **synthetic monotonic clock**
  (`os.utime`, the same device `mechanical-pipeline` uses), so the staleness term is
  ordered by construction rather than by real-clock resolution.

Then, in order: shipped bug-report template refused -> conforming report accepted and
its PASS written to the ledger -> unquoted `see chat` refused -> RED captured (exit 22)
-> route refused with an empty ledger -> route refused after the report is edited ->
route accepted as FAST off the matched RED -> route BLOCKED on a RED of a different
argv -> fix applied, GREEN captured on the identical argv (exit 0) -> hand-typed GREEN
refused for its missing sidecar -> GREEN of a different argv refused -> the honest pair
accepted -> 4 greens under `--green-runs 5` refused -> six declared files against a
bound of five refused -> the shipped `rca-template.md` refused as a waiver -> a
hand-typed waiver clears the size term.

## The one step that is not adversarial, and why

Step 12 (the honest RED/GREEN pair passing) and step 16 (a real waiver clearing the
size term) are **positive** controls. Without them, every refusal in this file could be
produced by a gate that fails closed on everything, which is not the property being
claimed. A gate suite is only trustworthy if the same run shows it accepting the honest
case and refusing the fabricated one.

## Result of the last authored run

All 17 steps passed (`RESULT: PASS (17/17 steps passed)`), re-run twice more for
determinism (no flakiness — the synthetic clock removes the mtime race, and every other
assertion is a pure function of its inputs).

One contract observation was made while authoring, and is asserted rather than
reported as a defect: `check_bugfix_intake.py`'s JSON returns `runtime_observable` and
`regression` as **JSON booleans**, not as the `yes`/`no` strings the report writes.
`skills/pipeline-tools/SKILL.md` lists both keys without their types, so step 2 pins
the observed contract — a reader following the field rules alone would guess wrong.

## Added in 2.6.1 (the audit-fix wave)

Steps 13b-13d close the 2026-09-07 audit's F4: `--green-runs N` counted
`--green` OCCURRENCES, so the flag that exists to say "this bug is flaky
enough to need five clean runs" was satisfied by one run cited five times.

- **13b** — the same capture path cited 5x under `--green-runs 5` is
  `green_runs_not_distinct`, and explicitly NOT `green_runs_short`: five were
  supplied.
- **13c** — five byte-identical copies under five names, made by copying the
  capture and its sidecar together. The step asserts that no hash term fires,
  which is the point: copying preserves exactly what the hashes protect, so
  distinctness needs the OUTPUT key (`capture_sha256`) as well as the process
  key (`started` + `pid`).
- **13d** — five genuine re-runs of the probe still pass. A distinctness rule
  that also refused honest evidence would be worse than none.
