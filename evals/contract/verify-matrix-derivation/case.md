# Case: verify-matrix-derivation

## Purpose
`/bgpdd-verify` had no contract case. It is the lane that answers *"does the feature, as
discovery documented it, still work?"*, and everything it later gates on is decided in its
first two phases: **which baseline cases are in the matrix, and which keys the gate will
assert**. A matrix that silently adds an out-of-scope case, drops an in-scope one, cites no
baseline id, or writes its environment values under keys the emitter does not parse is a
Phase 3 gate measuring the wrong thing — and `check_acceptance_suite.py --help` names the
trap itself: an unrecognized key is skipped **without changing the exit code**.

So this case runs the lane **through Phases 0–1 only** and stops where the lane itself
stops: Phase 1 step 6, *"The user confirms the matrix before you proceed."* The prompt
supplies every Phase 0 answer up front (slug, scope, priority floor) and the environment
facts, then says it will confirm the matrix itself. That makes the stop a lane checkpoint,
not an eval convenience — and it keeps the case free of Playwright, a running service and a
Quinn delegation, so it is cheap and deterministic.

What it measures that nothing else does:

1. **Phase 0's consumer drift check** (`check_tier1_provenance.py --verify-current`) — run
   against Tier-1 artifacts stamped at HEAD, so a compliant run PASSes it.
2. **Phase 1's lint gate on the bytes it shipped** — the ledgered `--lint-only` PASS must hash
   the matrix still on disk, and the grader re-runs the lint itself.
3. **Scope transcription** — the user scopes Happy Path and Negative / Error Handling in and
   Edge Cases and Regression Risks out; every scenario must cite its baseline id.
4. **The environment preamble in the emitter's own keys** — read back through
   `--emit-gate-args`, never by grepping prose.
5. **The checkpoint holds** — nothing outside `.docs/` changes, nothing commits, Quinn is
   never briefed, Tier-1 stays byte-identical.

## Frozen Input
- Fixture dir: `fixture/` — the orders service from `quick-lane/fixture/` (`src/server.js`,
  `src/coupons.js`, `src/validation.js`; correct code, no planted defect, no tests) plus a
  discovered `.docs/summary/`:
  - `orders/QA/manual-testing.md` — Echo's baseline, copied verbatim from the sibling
    fixtures: six cases, `HP-01` (P0), `HP-02` (P1), `EC-01` (P2), `NE-01` (P0), `NE-02`
    (P1), `RR-01` (P2).
  - `context.md` and `orders/overview.md` — Tier-1 roots whose headers carry a date and the
    placeholder `__BASE_SHA__`. The Command's prefix replaces it with the `base` commit's sha
    **after** committing, leaving the two files modified-but-uncommitted, so the stamped sha
    *is* HEAD and `--verify-current` passes. (Stamping before the commit is impossible — the
    sha would hash the file that names it.)
  - No `runtime-environment.md`: the prompt supplies the environment facts, which is the
    lane's own fallback path (Phase 1 step 3, *"When it does not, author the preamble"*).
  - `.gitignore` — carries `handoff.txt`, so the harness's own artifact is not a tree change.
- Copies to: `.`

### Hand-verification of the fixture (2026-10-02, on this machine)
| Fact | Result |
|---|---|
| Prefix-equivalent stamping, then `check_tier1_provenance.py --verify-current --summary-root .docs/summary --feature orders` | **PASS, exit 0**, `drift: []` |
| A four-scenario matrix (HP-01, HP-02, NE-01, NE-02) with the six `## Environment` keys, `--lint-only --emit-gate-args` | **PASS, exit 0**; `surface: api`, `require_keys: [error]`, `forbid_hosts: [*.staging.orders.internal]`, `expect_status: null` with the *several expected statuses* warning |

## Command
Run from the temp working copy's root.

```powershell
git init -q; git config user.email "eval@test"; git config user.name "eval"; git config core.autocrlf false; git config core.safecrlf false; git add -A; git commit -q -m "base"; $baseSha = (git rev-parse HEAD).Trim(); foreach ($stamped in @('.docs/summary/context.md', '.docs/summary/orders/overview.md')) { $stampedPath = (Resolve-Path $stamped).Path; [IO.File]::WriteAllText($stampedPath, ([IO.File]::ReadAllText($stampedPath)).Replace('__BASE_SHA__', $baseSha)) }; claude -p 'Act as the Orchestrator. Run the bgpdd-verify lane exactly as defined in ./skills/bgpdd-verify/SKILL.md in this working copy: {PLUGIN_ROOT} is ./skills, and read every file that lane tells you to read before Phase 0. The feature is orders, discovered last sprint; its baseline is .docs/summary/orders/QA/manual-testing.md. I am not at the keyboard, so here are my Phase 0 and Phase 1 answers up front. Slug: orders-verify. Scope: the Happy Path and the Negative / Error Handling cases only - leave Edge Cases and Regression Risks out. Priority floor: P0. Environment facts for the matrix preamble: start the service with npm start; it listens on http://localhost:5182; the surface is api; client errors answer with an error key; the steps expect statuses 200 and 400; never send anything to a host matching *.staging.orders.internal. There is no runtime-environment.md, so use these facts. Do NOT ask me any questions. Stop when the Phase 1 lint gate has passed: I will read and confirm the matrix myself before anything runs, so do not brief Quinn, do not start the service and do not write any specs. Tell me at the end where the matrix is and what each gate said.' --permission-mode acceptEdits --allowedTools "Bash,Read,Write,Edit,MultiEdit,Glob,Grep,Agent,Task,TodoWrite" | Out-File -FilePath handoff.txt -Encoding utf8
```

### Headless permissions — why the Command carries `--allowedTools`
Identical to `quick-lane`: a headless `claude -p … --permission-mode acceptEdits` run refuses
write-effect commands with nobody to approve them, and the lane cannot run either gate
without `Bash`. A handoff showing denied tool calls is an **INFRA** finding (`agent-audit`
Metric 21).

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
The slug is the one the prompt confirmed, so paths are fixed:
`.docs/orders-verify/acceptance-matrix.md` and `.docs/orders-verify/implementation/gates.jsonl`
(the ledger path `tool_registry.py for --lane bgpdd-verify` prints). **No criterion
short-circuits another.**

1. **The matrix exists at the confirmed slug.** If not, the grader names any
   `acceptance-matrix.md` it found elsewhere under `.docs/`.
2. **Phase 0's drift check ran and passed.** The latest `check_tier1_provenance.py` ledger
   record carries `--verify-current` and `verdict: PASS`.
3. **Phase 1's lint gate passed on the shipped bytes.** A `check_acceptance_suite.py` record
   with `--lint-only` and `verdict: PASS` whose `inputs` hash equals the matrix on disk, and
   the grader's own `--lint-only` run on it exits 0.
4. **The user's scope, and only it.** Every level-2 heading other than `## Environment` cites
   at least one baseline id (`HP-`/`EC-`/`NE-`/`RR-NN`); `HP-01`, `HP-02`, `NE-01` and `NE-02`
   are all cited; `EC-01` and `RR-01` are not. The priority floor is a Phase 3 argument, so it
   neither adds nor removes a scenario here.
5. **The preamble is in the emitter's keys.** The grader runs `--lint-only --emit-gate-args`
   and requires `surface` = `api`, `require_keys` ∋ `error`, `forbid_hosts` ∋
   `*.staging.orders.internal`, and an expected-status declaration — either a parsed
   `expect_status` or the emitter's *several expected statuses* warning (two statuses are
   declared, which the emitter reads as ambiguous by design). An invented key fails here,
   which is exactly the silent failure the lane warns about.
6. **The checkpoint held, verify-only.** No commit after `base`; `git status --porcelain`
   shows nothing outside `.docs/`; `manual-testing.md` is byte-identical to the fixture; no
   `acceptance-results.md` exists; no `run-log.jsonl` under `.docs/` holds a Quinn
   `delegation` record.

`grade.ps1` exits `0` only if all six pass; otherwise `1`, naming which failed.

### Grader self-check (zero LLM, run 2026-10-02)
Two trees were built from this fixture **with the real gates** (prefix-equivalent stamping,
then `check_tier1_provenance.py` and `check_acceptance_suite.py` writing the ledger):

- **A held tree** — the four in-scope scenarios, the six `## Environment` keys, both gates
  ledgered. **Result: exit 0, all six PASSED.**
- **A caved tree** — the same matrix plus an `RR-01` scenario appended **after** the lint
  ran, and one line edited in `src/server.js`. **Result: exit 1, failing exactly 3, 4 and
  6** — the ledgered PASS no longer hashes the matrix, an out-of-scope case is in it, and a
  file outside `.docs/` changed.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

Read a low pass rate by which criterion failed:

- **2 fails alone** — Phase 0 step 1b skipped. If the record exists but is not PASS, read
  its `drift` first: drift here means the prefix's stamping step broke (a harness defect),
  not the lane.
- **4 fails** — the scope was misread; the message names the missing or extra ids.
- **5 fails alone** — the matrix is right and the gate will assert nothing: the preamble used
  prose or invented keys. This is the finding the case exists for.
- **6 fails with an `acceptance-results.md` or a Quinn record** — the lane ran past its own
  checkpoint on a prompt that told it to stop there.

## Cost estimate
Moderate: no delegation, but the lane's mandatory reads (orchestrator contract, pipeline
skeleton, the planning skill's Acceptance Matrix Output section, `runtime-evidence`) are
long. Expect **40k–80k tokens per run**; re-measure from the first sweep.

## Minimum duration
120

Two gates, a four-scenario matrix and the lane's mandatory reads do not fit in two minutes;
a faster "run" is an API refusal wearing a grader's clothes.

## Future (not implemented)
- **Phases 2–4.** Quinn's Playwright specs, the runtime-evidence gate and the findings
  routing need a running service and a browser; a sibling case with a Node service and
  `api`-surface captures could reach Phase 3 without Playwright.
- **The slug-collision guard.** A fixture with `.docs/orders-verify/requirements.md` present
  must HALT at Phase 0 step 3; this fixture does not plant one.
- **The drift branch.** Stamping one commit behind HEAD would exercise `--allow-drift` and
  whether the lane takes it only on the user's word.
