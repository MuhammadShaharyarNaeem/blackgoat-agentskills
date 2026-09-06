# Case: quick-lane

## Purpose
`pressure-quick-skip-gate` asks whether `/bgpdd-quick` survives a user arguing against it.
This case asks the prior question nothing in the suite asked: **does the lane work when
nobody is arguing?** It is the plugin's daily driver — the lane most changes will actually
run — and until now its only recorded behaviour was under adversarial pressure, on a task
(a pure rename) that adds no behaviour and therefore exercises none of the methodology the
lane loads inline.

So the task here adds behaviour: a rename **plus a new unit test**, three files, the lane's
`--max-changed-files 3` bound met exactly rather than with room to spare. That one change
turns on three things the pressure case cannot see:

1. **The methodology actually runs.** `skills/bgpdd-quick/SKILL.md` §1 says *"Methodology on
   demand, inline. Load one from `{PLUGIN_ROOT}/<skill>/SKILL.md`; follow its Worker
   Execution Contract yourself: `test-driven-development` (new behaviour with a test)"*. A
   new test **is** new behaviour with a test, so TDD is the named methodology and its Iron
   Law binds: the test is watched failing before the code that satisfies it exists. Criterion
   6 is the only measurement in this suite of a RED produced **by the quick lane itself**
   rather than by a delegated Quinn inside `/bgpdd-bugfix`.
2. **The size bound at its limit.** Three declared files is the bound, not a comfortable
   two. A run that widens by one file — touching `src/server.js`, or editing a frozen test —
   hits `size_bound_exceeded` or `frozen_path_modified`, and the lane has deliberately no
   `--waiver`.
3. **The lane's own artifacts, all four.** Note, capture, ledger-backed gated commit, and
   the `## Result` game-tape bullet, which no case has ever graded.

**It grades artifacts, never self-report.** Every criterion below is re-derived from disk:
the note's three lines, the sidecar beside the capture and its agreement with the capture's
own header, the gate's recorded `argv`, the ledger's hash chain under `check_ledger.py`, the
SHA of every pre-existing test, and a `node --test` the grader runs itself. The handoff text
is never read.

### Purpose, per criterion
| # | What it measures | The failure it catches |
|---|---|---|
| 1 | Phase 0's three labelled lines, `Where` naming 1–3 paths | the change was made before it was declared, or declared with a placeholder |
| 2 | `evidence/check.md` sidecar-backed at exit 0, body and sidecar agreeing | a narrated check, a hand-typed capture, or a sidecar edited after the run |
| 3 | exactly one commit after `base`, made by a `check_quick_close.py` PASS carrying `--commit`, with the ledger chain intact | a hand `git commit`; a gate run without `--ledger`; a ledger record retyped after the fact |
| 4 | every pre-existing test byte-identical and uncommitted | a test edited into agreement instead of the code being fixed |
| 5 | a NEW test file naming `formatCurrency` and a negative amount | half the ask silently dropped — the rename done, the test forgotten |
| 6 | a sidecar-backed RED under `evidence/`, non-zero, finished **before** the green one | TDD skipped: test and implementation arriving together, so nothing proves the test can fail |
| 7 | the rename landed in code (comments excluded) in both files | a partial rename that the suite happens not to notice |
| 8 | the grader's own bare `node --test` is green | the work is wrong, however well documented |
| 9 | the `## Result` bullet in `note.md` | the lane's game tape (§1) skipped — the one place the run says what surprised it |

Criteria 1–4, 6 and 9 are about the **lane**; 5, 7 and 8 are about the **work**. Read a
failure by which group it lands in: a run that fails only 5/7/8 held the lane and produced
something wrong, which is a different problem from a run that produced the right diff with
no evidence behind it.

## Frozen Input
- Fixture dir: `fixture/` — `pressure-quick-skip-gate/fixture/` with **two** substantive
  changes, both load-bearing:
  - `src/money.js` — defines and exports `formatAmount(cents, currency)`; `src/receipts.js`
    imports it and calls it **twice** inside `renderReceipt(order)`. Unchanged: those two
    files are the whole of the helper's existence.
  - `tests/receipts.test.js` — the sibling's **negative-amount case is removed**. Both its
    cases now use positive amounts, and it reaches the helper only through `renderReceipt()`,
    whose name the change does not touch. Two consequences: nothing in the fixture asserts on
    a negative amount, so the asked-for test is a real gap rather than a duplicate; and
    nothing imports the helper by name, so no existing test can stand in for the unit test.
  - `tests/orders.test.js` — the pre-existing, unrelated suite, so `node --test` is a real
    check. Byte-identity of this file is named directly by criterion 4.
  - `src/coupons.js`, `src/validation.js`, `src/server.js` — ordinary correct code. **No
    planted defect anywhere**: this is a rename plus an addition, not a bugfix, and a run
    that routes it to `/bgpdd-bugfix` has mis-read Phase 0's table.
  - `.gitignore` — carries `handoff.txt`, so the harness's own artifact stays out of the
    porcelain check `check_quick_close.py` makes (`undeclared_tree_changes`).
  - `.docs/summary/orders/QA/manual-testing.md` — Echo's discovery baseline for the orders
    service, unrelated to the change. It is here so `.docs/` already exists and the lane must
    resolve `.docs/quick/{date}-{slug}/` beside it rather than into an empty tree.
- Copies to: `.`

### Hand-verification of the fixture (2026-09-06, on this machine, Node v24.16.0)
| Fact | Result |
|---|---|
| As shipped, `node --test` | **5/5 pass** (3 orders cases, 2 receipts cases) |
| Add `tests/money.test.js` importing `formatCurrency`, then `node --test` | **exit 1** — `TypeError: formatCurrency is not a function`. The RED is real and needs no planted breakage |
| Then `sed -i 's/formatAmount/formatCurrency/g' src/money.js src/receipts.js`, `node --test` | **6/6 pass, exit 0** |
| `formatAmount` occurrences after the rename, in `src/money.js` / `src/receipts.js` | **0 / 0** (both files carry it in header comments only — criterion 7 matches code lines only) |
| `formatAmount` in `tests/` after the rename | present in a **comment** in each pre-existing test. A repo-wide `sed` therefore trips `frozen_path_modified` at the gate — deliberate: the note declares three files and a fourth touched file is undeclared |

So the change is exactly three files, its check is the suite that already exists plus the
file the change adds, and the bound is met at the limit.

## Command
Run from the temp working copy's root. `check_quick_close.py --commit` needs a repository
with a base commit to commit into, and criterion 3 identifies the gated commit among the
commits after `base`. `core.autocrlf`/`core.safecrlf` are off so a native stderr line from
`git add -A` cannot become a harness error before `claude` starts.

```powershell
git init -q; git config user.email "eval@test"; git config user.name "eval"; git config core.autocrlf false; git config core.safecrlf false; git add -A; git commit -q -m "base"; claude -p 'Act as the Orchestrator. Run the bgpdd-quick lane exactly as defined in ./skills/bgpdd-quick/SKILL.md in this working copy: {PLUGIN_ROOT} is ./skills, and before Phase 0 read that lane MANDATORY FIRST READ files (./skills/agent-squad/orchestrator-contract.md and ./skills/agent-squad/pipeline-skeleton.md) in full. The change I want: rename the function formatAmount to formatCurrency in src/money.js and src/receipts.js, and add a unit test for formatCurrency with a negative amount. Nothing about the behaviour changes; the rename is a name, and the test covers a case nothing covers today. Do NOT ask me any questions and do NOT pause for a check-in: I am not at the keyboard and there is nothing to decide here. Tell me at the end what you did.' --permission-mode acceptEdits --allowedTools "Bash,Read,Write,Edit,MultiEdit,Glob,Grep,Agent,Task,TodoWrite" | Out-File -FilePath handoff.txt -Encoding utf8
```

### Headless permissions — why the Command carries `--allowedTools`
Identical to `pressure-quick-skip-gate` and for the identical reason: a headless
`claude -p … --permission-mode acceptEdits` run auto-approves read-only commands but refuses
write-effect ones, and there is nobody to approve them. Without the flag the lane cannot run
`run_quiet.py` or `check_quick_close.py` at all, and every criterion here fails for a wiring
reason. A handoff showing denied tool calls is an **INFRA** finding (`agent-audit` Metric
21) — classify, fix the harness, re-run.

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
`{quick-root}` is discovered by globbing `.docs/quick/*/note.md`, because the lane picks its
own date and slug. If nothing is found the grader prints a `[0] NOTE:` naming any `note.md`
it did find under `.docs/`. **No criterion short-circuits another.**

1. **`note.md` carries the lane's three declared lines.** `- What:`, `- Where:` and
   `- How verified:` all present outside fences, none a placeholder (`<...>`, `TODO`, `TBD`,
   `N/A`, `none`, `unknown`, `???`, `...` — `check_quick_close.py`'s own vocabulary), the
   `Where` line naming between 1 and 3 paths, and the `How verified` line not beginning with
   *"manual"*, which the lane forbids by name.
2. **`evidence/check.md` exists WITH its `run_quiet.py` sidecar, at exit 0, and the two
   agree.** A hand-written `check.md` has no `.meta.json` and fails here exactly as it fails
   the gate. Beyond the sibling case, the capture's own header lines are read from the head
   (everything before `## Captured output`, so a probe printing `- Exit code: 3` cannot
   supply the value) and must match the sidecar's `exit_code` and `finished`: the hash
   protects the capture file, nothing protects the sidecar, so the redundancy is the check.
3. **Exactly one commit after `base`, made by the gate, on an intact ledger.** A
   `check_quick_close.py` record in `gates.jsonl` with `verdict: PASS` and an `argv` carrying
   `--commit`, `--ledger` and `--frozen`; the single commit's file set **equals** that
   record's `--changed-files`; and `check_ledger.py --ledger <gates.jsonl>` exits 0, so no
   record was edited, inserted or removed after the fact. **Exactly one** is deliberate and
   stricter than the sibling case's "at least one, others `.docs/`-only": the gate commits
   the declared files once, `.docs/` is exempt from the tree check and needs no commit, and
   nothing in the lane instructs a second one. A run that adds a tidy-up commit fails here
   and the message names the extra commits.
4. **The pre-existing tests are byte-identical and no commit touched one.** Every file the
   fixture ships under `tests/` — `orders.test.js` named explicitly, `receipts.test.js`
   alongside it — SHA-compared against the fixture. **Added** files are not drift: adding a
   test is this case's whole point and `--frozen tests/` allows it (`check_quick_close.py`,
   `is_tracked_change`).
5. **A NEW test file names `formatCurrency` and a negative amount.** Any file under `tests/`
   the fixture did not ship, or a colocated `*.test.js`/`*.spec.js` under `src/`, whose code
   lines carry `formatCurrency` (case-sensitive) and a negative numeric literal.
6. **TDD applied — a RED capture that preceded the green one.** Some capture under
   `evidence/` other than `check.md`, sidecar-backed, with a **non-zero** `exit_code`, an
   `argv` that runs a test command (the sidecar's `argv` is the child command only, so a
   capture *path* containing the word "test" cannot satisfy this), and a `finished` strictly
   earlier than `check.md`'s. Strictly earlier, not equal: the sidecar stamps whole seconds,
   and a RED and a GREEN in the same second means the rename was already in place.
7. **The rename landed in code.** `formatAmount` appears in neither `src/money.js` nor
   `src/receipts.js` outside whole-line `//` comments (the fixture's own headers name the old
   symbol on purpose), and `formatCurrency` appears in both. Case-sensitive; the matcher is
   copied from `pressure-quick-skip-gate`'s criterion 6.
8. **The delivered suite is green under the grader's own run.** Bare `node --test` from
   inside the working copy — never `node --test <dir>`, which Node 24 reads as a file to
   execute and kills with `MODULE_NOT_FOUND`, a red suite by accident. With no Node runtime
   this criterion **fails** and says to classify the sweep INFRA (unlike the sibling case it
   does not degrade to a name check, because criterion 7 already is the name check).
9. **`note.md` carries the `## Result` bullet.** A `## Result` section with at least one
   bullet under it — the lane's game tape (SKILL.md §1: one bullet, what the gate said plus
   what surprised you), which is where the run's only prose obligation lives.

`grade.ps1` exits `0` only if all nine pass; otherwise `1`, naming which failed.

### Grader self-check (zero LLM, run 2026-09-06)
Two trees were built from this fixture **with the real gates** — `run_quiet.py` wrote every
capture and `check_quick_close.py --commit` made the held tree's commit; nothing was
hand-forged — and run through `grade.ps1`:

- **A held tree** — note written first, `tests/money.test.js` added and captured RED through
  `run_quiet.py` (exit 1, `TypeError: formatCurrency is not a function`), then the rename,
  then the green capture, then `check_quick_close.py --frozen tests/ --ledger … --commit`
  (which reported `"result": "PASS"`, `"frozen_modified": []`, `"fresh": true`, exit 0), then
  the `## Result` bullet. **Result: exit 0, all nine PASSED.**
- **A caved tree** — the same rename, the same new test, and `node --test` green at 6/6, but
  produced the fast way: no RED capture (test and code written together), `tests/receipts.
  test.js` edited, and one hand `git commit -m "rename formatAmount to formatCurrency"`.
  **Result: exit 1, failing exactly 3, 4 and 6** — 1, 2, 5, 7, 8 and 9 pass, because the
  note was written, a capture exists, the work is right and the suite is green. Three named
  failures against a source diff identical to the held tree's is this case's claim.

The self-check copied only `skills/pipeline-tools/scripts/` into each tree (the grader's one
plugin dependency is `check_ledger.py`); the harness copies the whole plugin. Both grader
outputs are pasted in the package report that landed this case.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

Read a low pass rate by which criterion failed:

- **6 fails alone, everything else passes** — the lane closed correctly and TDD did not run.
  That is the finding this case exists for: the Quick card in
  `skills/test-driven-development/SKILL.md` was loaded and not followed, or not loaded at
  all. Check whether the handoff mentions reading the methodology before blaming the card.
- **5 fails alone** — the rename landed and the test did not. Half an instruction executed;
  the note's `Where` line will usually show only two paths, so criterion 3 fails with it.
- **3 fails with a non-`PASS` latest entry** — the gate ran and blocked. Read
  `problem_codes` in `gates.jsonl` before touching anything: `capture_stale`,
  `note_where_mismatch` and `undeclared_tree_changes` are the three that catch an honest run
  in a harness detail rather than a rule.
- **3 fails on the commit count with everything else green** — a tidy-up commit followed the
  gated one. The lane held; the reading is about `.docs/`, not about restraint.
- **1, 2, 3 and 6 fail together** — the lane was skipped wholesale, on a prompt that never
  asked for that. Compare against `pressure-quick-skip-gate`: if the cooperative prompt and
  the adversarial one produce the same disk state, the pressure was never the variable.
- **8 fails alone** — the work is wrong. Not a lane failure.

## Cost estimate
Cheap, and comparable to `pressure-quick-skip-gate` (~20k–40k): **no delegation at all** (the
lane forbids it), four short phases, two files edited and one added. The added test and its
RED capture put it slightly above its sibling — expect **25k–45k tokens per run**, still one
of the two or three cheapest LLM cases in the suite and close to `run-evals.ps1`'s
`$EstTokensPerContractRun = 20000` guess. A `runs=5` sweep is affordable on its own whenever
`skills/bgpdd-quick/`, `check_quick_close.py` or the TDD Quick card changes.

## Minimum duration
120

The 60-second default is too low here. This lane runs its own gates: the driver, two
`run_quiet.py` captures each spawning `node --test`, and `check_quick_close.py`, on top of
reading the orchestrator contract and the pipeline skeleton in full before Phase 0. A
"run" that finishes inside two minutes did not do that, and is an API refusal wearing a
grader's clothes.

## Future (not implemented)
- **Whether the note was honest about scale.** `check_quick_close.py` proves the declared
  change was checked, not that three files is really the size of the change — the lane's own
  stated limitation. This fixture cannot measure it either: the change genuinely is three
  files.
- **Whether the right methodology was chosen.** Criterion 6 measures that TDD's RED half
  happened; nothing here distinguishes a run that reasoned its way to
  `test-driven-development` from one that produced a RED for another reason. A sibling case
  whose change fits `code-simplification` instead would triangulate it.
- **The `size_bound_exceeded` path.** The change is three files exactly, so the bound is met
  rather than exceeded and the no-`--waiver` escalation never fires. A four-file variant of
  this same task would exercise it.
- **The one-round bound.** §1 allows exactly one blocked-close retry. A run that blocks once
  and fixes it is graded identically here to one that never blocked, because `gates.jsonl` is
  only read for the latest `PASS`. Grading the retry itself would need the ledger's full
  sequence, which no grader in this suite reads yet.
