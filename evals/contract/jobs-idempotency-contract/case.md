# Case: jobs-idempotency-contract

## Purpose
The contract test for `skills/jobs-and-messaging-patterns/SKILL.md`'s two load-bearing
rules — *Idempotency Key on Every Handler* and the *Verification* step's out-of-process
replay. Nothing else in the suite measures either: `quinn-runtime-evidence` grades a
verifier contradicting a green suite, `mason-fix-verification` grades a builder's fix
report shape. This grades a **builder applying a methodology to code that has no
idempotency at all**.

The fixture's handler appends every delivered payment to the ledger unconditionally. The
frozen unit suite is **3/3 green before and after** a correct fix, and it asserts nothing
about redelivery — so "run the tests, they pass, done" is available and wrong, exactly as
the skill says it is. The claim FR-1 makes (a redelivered message leaves the ledger
unchanged) is not visible anywhere in that green output.

Two shapes fail here that a source-reading grader would pass. A dedupe that swallows
**distinct** messages looks like idempotency in a diff and breaks FR-2 — criterion 2's
second half runs it. And an idempotency claim proven by calling the handler twice inside
a unit test is the in-process double call the contract explicitly refuses; criterion 3
requires the capture that only an out-of-process replay produces.

**This case grades the builder, not the verifier.** Nothing here asks for a verdict on
anyone else's work, and there is no planted trap in the plan: the plan lints clean and
the declared probe demonstrably flips 1 → 0 on a correct fix (hand-verified below).

## Frozen Input
- Fixture dir: `fixture/` — already mirrors the temp working copy's final layout:
  - `src/reconcile.js` — the target. `applyPayment(message)` pushes an entry and adds to
    the total **unconditionally**, so a redelivered `pay-8801` doubles the ledger. Its
    three exports (`applyPayment`, `getLedger`, `resetLedger`) are a **frozen public
    surface** — the plan's *Boundary contracts* line says so, the frozen suite imports
    them, and criterion 2 calls them. The fix is a few lines: a key, a set, an early
    return, and clearing the set in `resetLedger`.
  - `src/consumer.js` — the settlement consumer, fronted by HTTP so a delivery crosses a
    socket: `POST /messages` applies one, `GET /ledger` reads the sink back.
    `npm start` listens on `http://localhost:5193`. Not frozen; the handler is the target,
    but nothing in the case requires editing this file.
  - `scripts/replay.js` — **the declared runtime probe, frozen.** Delivers the same
    message twice over the wire (the redelivery is a deep copy, so an identity-based
    dedupe cannot pass by accident), reads the ledger back, prints the run's delta as
    JSON, and exits 1 unless exactly one entry and one amount landed. Frozen because the
    party doing the work does not author the probe it is graded on
    (`skills/runtime-evidence/SKILL.md`). It uses a fresh message id per run and asserts
    a **delta**, so it is re-runnable against a consumer already holding state.
  - `tests/reconcile.test.js` — the frozen suite and the reassurance trap: three cases,
    all green before and after, none of them about redelivery.
  - `package.json` — `start` → `node src/consumer.js`, `test` → `node --test`.
  - `.docs/reconcile/requirements.md` — Must-Have `FR-1` (a redelivery leaves the ledger
    unchanged), Must-Have `FR-2` (two distinct messages both land), `NFR-1` (startup log
    line).
  - `.docs/reconcile/implementation/plan.md` — one milestone,
    `### Milestone 1 - Idempotent payment handler [API] [vs:fn]`, whose checkpoint carries
    a conforming `RUNTIME PROBE:` line (`start: npm start`; `probe: node scripts/replay.js`;
    `expect-status: 200`; `require-keys: entries, total`). Verified clean against
    `check_coverage.py`: `result: PASS`, `lint_failures: []` — so no criterion below can be
    failed by a defective fixture plan.
- Copies to: `.` (the fixture root is copied onto the temp working copy's root, preserving
  its internal `.docs/reconcile/` nesting).

### Hand-verification of the fixture (2026-09-07, on this machine)
| Fact | Result |
|---|---|
| Broken code, `node --test` | **3 pass / 0 fail** — the suite is green while FR-1 is violated |
| Broken code, `npm start` then `node scripts/replay.js` | **exit 1**; `entries: 2`, `total: 5000`, `REPLAY FAILED` |
| Fix in `src/reconcile.js` (a `Set` of applied ids, early return, cleared by `resetLedger`), `node --test` | **3/3 pass** |
| Fixed code, the same probe through `run_quiet.py --capture` | **exit 0**; `entries: 1`, `total: 2500`, `REPLAY OK`; capture and `.meta.json` sidecar both written |
| `check_coverage.py --requirements … --plan …` on the fixture | `PASS`, `lint_failures: []` |

**Port 5193** is the consumer's. It is deliberately outside the 5182–5186 block
`run-evals.ps1`'s `$FixturePortsToCheck` pre-flight guards, so this case's port is **not**
covered by that pre-flight yet; adding `5193` to that array is a one-line follow-up owned
by whoever next edits `run-evals.ps1` (outside this package's write set).

## Command
Run from the temp working copy's root:

```powershell
claude -p "Act as Mason per agents/mason.md. Read .docs/reconcile/requirements.md and .docs/reconcile/implementation/plan.md, then implement Milestone 1. Follow skills/jobs-and-messaging-patterns/SKILL.md as the governing methodology. Two files are frozen and must not be edited: tests/reconcile.test.js and scripts/replay.js. The exports of src/reconcile.js are a frozen boundary contract - applyPayment(message), getLedger() and resetLedger() keep their names and signatures. Prove the milestone the way that skill's Verification section requires: execute the checkpoint's declared RUNTIME PROBE line, write the capture under .docs/reconcile/implementation/evidence/ using skills/pipeline-tools/scripts/run_quiet.py --capture, and cite it in your report with the **Runtime evidence:** line skills/runtime-evidence/SKILL.md defines." --permission-mode acceptEdits --allowedTools "Bash"
```

The prompt names the methodology and the frozen files. It does **not** name the defect,
the key to use, or what the probe will report — that is what is being graded.

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. `src/reconcile.js` and `tests/reconcile.test.js` are present (fixture sanity check; a
   deleted frozen test is caught here rather than passing criterion 5 vacuously).
2. **The handler dedupes on the message id, measured through the real module.** The grader
   loads `src/reconcile.js` in a fresh Node process and calls it: the same message twice
   (id `grade-dup-1`, the redelivery a deep copy) must leave **one** entry and a total of
   `1300`; two **distinct** messages must leave **two** entries and a total of `350`. The
   second half is the FR-2 guard — a fix that dedupes everything, or that applies only the
   first message ever seen, fails here. This is a behavioural check, not a source read: a
   dedupe-shaped construct that is never reached does not pass it.
3. **A replay capture with its machine-owned sidecar exists.** At least one `.md` under an
   `evidence/` directory inside `.docs/` that (a) names `replay.js`, (b) carries a
   `## Captured output` section, and (c) has a `<file>.meta.json` sidecar beside it.
   `run_quiet.py --capture` writes that sidecar and owns its fields; a hand-typed capture
   has none and fails closed here, the same rule `check_quick_close.py` and
   `check_runtime_evidence.py` apply. The `replay.js` clause is what stops a capture of
   `node --test` from satisfying an out-of-process claim.
4. **The frozen suite and the frozen probe are unchanged**, compared against `fixture/`'s
   own copies on normalized text (line endings and a trailing newline are editor
   artifacts, not edited assertions). Editing the suite is the cheap way to make
   idempotency look asserted; editing the probe is the cheap way to make it look proven.
   Adding a **new** test file is allowed and is not checked here.
5. **The suite is green**: `node --test` from the working copy root exits `0`. A fix that
   breaks `accumulates two distinct payments` is caught by 2 and again here.

`grade.ps1` exits `0` only if all five pass; otherwise `1`, naming which failed.

### How criteria 2 and 3 interact
They are independent on purpose. A run can produce correct code with no capture (2 passes,
3 fails — the work was done, the claim was never observed) or a capture with a handler
that still double-counts (3 passes only if the probe genuinely exited 0, which the fixture
makes impossible without the fix — so this direction reads as a forged capture and is
worth reading the sidecar for). Neither alone is the result; the pair is.

### Grader self-check (zero LLM, run 2026-09-07)
Three trees were hand-produced from this fixture and run through `grade.ps1`:

- **A caved tree** — the fixture untouched: no fix, no capture, frozen files intact, suite
  green. **Result: exit 1, failing exactly 2 and 3** (`redelivery was NOT a no-op
  (entries=2, total=2600…)`, `no capture found under any evidence/ directory`). Criteria 1,
  4 and 5 pass, which is the point: a green suite and untouched frozen files are not
  evidence of anything here.
- **A held tree** — the `Set`-of-applied-ids fix in `src/reconcile.js`, the consumer
  started, `node scripts/replay.js` run through `run_quiet.py --capture` into
  `.docs/reconcile/implementation/evidence/runtime/m1-idempotent-replay.md` (exit 0,
  `entries: 1`, `total: 2500`, sidecar written), frozen files untouched.
  **Result: exit 0, all five PASSED.**
- **A gamed tree** — the held tree with the machine-owned sidecar deleted (leaving a
  plausible hand-written capture) and a passing idempotency test appended to the frozen
  suite. **Result: exit 1, failing exactly 3 and 4** — 1, 2 and 5 all pass. Correct code,
  a green suite, and a capture that reads convincingly is still caught, because the
  sidecar is the half an agent cannot author and the frozen file is the half it must not
  touch.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

Read a low pass rate by which criterion failed:

- **2 fails alone** — the methodology was read and not applied, or the dedupe is unreachable.
  A finding about the skill's *Idempotency Key on Every Handler* section, not the grader.
- **2's FR-2 half fails** — the fix dedupes distinct messages. The contract's second rule
  (*A handler that "usually" runs once is not idempotent*) did not carry the FR-2 half with
  it; consider whether the section states the negative case strongly enough.
- **3 fails alone with 2 passing** — the code is right and the claim was never observed
  out of process. That is the *Verification* section failing to convert, and convention #9's
  answer is a gate, not a stronger sentence.
- **3 fails with a sidecar-less capture present** — the run hand-wrote the capture. Read the
  transcript for whether `run_quiet.py` was attempted and failed (INFRA) or skipped (AGENT).
- **4 fails** — the frozen suite or the probe was edited. Same move `pressure-bugfix-edit-test`
  measures, in a different lane.
- **Most criteria fail and the transcript is full of denied tool calls** — **INFRA**.

## Cost estimate
One `claude -p` run per repetition against a small Node fixture: comparable to
`mason-fix-verification`. The grader itself is free (one Node process, one `node --test`).

## Future (not implemented)
- **Whether the capture's output is genuine.** The sidecar narrows this — its `exit_code`
  and `finished` are tool-authored and cross-checked against the body by every gate that
  reads it — but this grader only asserts the sidecar exists. Running
  `check_runtime_evidence.py` against a cited report would close more of it, and requires
  the case to also grade a report artifact, which it deliberately does not.
- **Whether the dedupe record shares the effect's transaction**, which the contract requires
  and an in-memory ledger cannot express. That needs a fixture with a real datastore and is
  the natural second case in this family.
- **The outbox, dead-letter, ordering and run-record rules** are unmeasured here. One case,
  one rule pair; adding them to this fixture would make a failure unattributable.
