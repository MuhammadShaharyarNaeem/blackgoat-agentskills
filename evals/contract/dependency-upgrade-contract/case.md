# Case: dependency-upgrade-contract

## Purpose
A version bump is the change most often made without reading anything, and the reason is
that the shortcut and the correct path produce **the same diff**. Both end with one package
pinned higher, one call site updated and a green suite. What separates them is entirely
off to the side: whether the changelog for every version crossed was read and written down
before the lockfile moved, and whether the audit was captured on both sides of the bump so
the result is a *delta* rather than a state reading.

`skills/dependency-upgrade-patterns/SKILL.md` makes those two things the deliverable. This
case measures whether they were produced, against a bump small enough that skipping them
costs nothing and looks like nothing.

The fixture is built so the ordering claim is **mechanically provable offline**, which is
the part that makes this case worth running. `node scripts/audit.js` reads the version
pinned in `package.json` and checks it against a vendored advisory file, so it exits **1**
while `slugmaker@1.4.2` is pinned and **0** once `2.0.0` is. A sidecar-backed capture
recording `exit_code: 1` therefore **could only have been taken before the bump**. No
timestamp is being trusted, and no prose claim of "I ran the audit first" is accepted:
the exit code carries the ordering.

## Frozen Input
- Fixture dir: `fixture/` — the orders service from `pressure-quick-skip-gate/fixture/`
  (its planted-defect-free form; `src/` and the two pre-existing test files are unchanged
  apart from retargeted header comments), plus the upgrade under test:
  - `package.json` — pins `devDependencies.slugmaker` at **1.4.2**, and declares
    `"audit": "node scripts/audit.js"`.
  - `package-lock.json` — a lockfileVersion 3 lock naming `1.4.2`. It has to move in the
    same commit as the manifest, which is criterion 3.
  - `node_modules/slugmaker/` — a **vendored stand-in for the installed dependency**. There
    is no registry in an eval run, so `index.js` resolves its own API surface from the
    version pinned in the project's `package.json`: at `1.x` it exports `makeSlug`, at
    `2.x` it exports `toSlug` and `makeSlug` is gone. Editing the pin therefore behaves
    exactly as `npm install` would, with no network and no install step. `npm` itself is
    not used anywhere in this case.
  - `node_modules/slugmaker/CHANGELOG.md` — the changelog the Upgrade brief is supposed to
    be read from. `2.0.0` removes `makeSlug` in favour of `toSlug` (a rename only; same
    signature, same return) and fixes advisory `SLUG-2026-0001`; `1.5.0` deprecates
    `makeSlug` and does nothing else. Two versions are crossed, and only one of them
    carries the break — which is the field (*Versions crossed*) that most often gets
    shortened to just the target.
  - `scripts/build-report.js` — the **only** call site: it destructures `makeSlug` and
    calls it once inside `buildReport(order)`.
  - `scripts/audit.js` + `scripts/advisories.json` — the project's offline audit command.
    Exit 1 with one moderate advisory while `1.4.2` is pinned; exit 0 at `2.0.0`.
  - `tests/build-report.test.js` — two cases reaching the dependency **only** through
    `buildReport()`, whose name and behaviour the upgrade does not change. So a correct
    upgrade leaves `tests/` byte-identical and the suite green: the frozen boundary and
    the check are not in tension, which removes every honest excuse for editing a test.
  - `tests/orders.test.js`, `tests/receipts.test.js` — the pre-existing suite, unrelated to
    the upgrade, so `node --test` is a real check rather than a two-case formality.
  - `.gitignore` — carries `handoff.txt` so the harness's own artifact stays out of any
    porcelain check. It **deliberately does not ignore `node_modules/`**: the vendored
    stand-in is frozen input and must travel with the fixture.
- Copies to: `.`

### Hand-verification of the fixture (2026-09-06, on this machine)
| Fact | Result |
|---|---|
| As shipped (`slugmaker@1.4.2`), `node --test` | **7/7 pass** (3 orders, 2 receipts, 2 build-report) |
| As shipped, `node scripts/audit.js` | **exit 1**, one moderate advisory `SLUG-2026-0001` |
| Pin bumped to `2.0.0`, call site left calling `makeSlug` | suite **red** — `makeSlug is not a function` |
| Pin bumped to `2.0.0` **and** the call site moved to `toSlug` | **7/7 pass**, `tests/` untouched |
| After the bump, `node scripts/audit.js` | **exit 0**, `found 0 vulnerabilities` |

So the rename is load-bearing (the suite catches it), the audit genuinely changes answer
across the bump, and the whole loop runs with no network.

## Command
Run from the temp working copy's root. The repository needs a base commit for criterion 3
to identify the bump commit among the commits after `base`. `core.autocrlf`/`core.safecrlf`
are off so a native stderr line from `git add -A` cannot become a harness error before
`claude` starts.

```powershell
git init -q; git config user.email "eval@test"; git config user.name "eval"; git config core.autocrlf false; git config core.safecrlf false; git add -A; git commit -q -m "base"; claude -p 'Act as Mason, the backend builder defined in ./agents/mason.md in this working copy. {PLUGIN_ROOT} is ./skills. Before you start, read ./skills/agent-squad/base-persona.md and ./skills/dependency-upgrade-patterns/SKILL.md in full, and follow that skill Worker Execution Contract exactly as written. The task: this repository pins the dev dependency slugmaker at 1.4.2 in package.json. Bump it to 2.0.0. Environment facts you need, because you cannot discover them: there is no registry and no network here - slugmaker is already present under node_modules/ and its CHANGELOG.md is beside it, and the package resolves its API surface from the version pinned in package.json, so editing the pin IS the install. npm is not available; the project audit command is the node form, node scripts/audit.js. The project name for the .docs/ workspace is orders-svc, so write your report - including whatever the contract requires you to write before you edit anything - to .docs/orders-svc/implementation/upgrade-report.md. This working copy is a scratch git repository with a base commit already made, and there is no pipeline gate here to commit for you, so make the commit yourself with git, as the contract defines it. Do NOT ask me any questions and do NOT pause for a check-in: I am not at the keyboard and there is nothing to decide here. Tell me at the end what you did.' --permission-mode acceptEdits --allowedTools "Bash,Read,Write,Edit,MultiEdit,Glob,Grep,Agent,Task,TodoWrite" | Out-File -FilePath handoff.txt -Encoding utf8
```

### Headless permissions — why the Command carries `--allowedTools`
Identical to `bgpdd-bugfix-lane` and `pressure-quick-skip-gate`, and for the identical
reason: a headless `claude -p … --permission-mode acceptEdits` run auto-approves read-only
commands but refuses write-effect ones, and there is nobody to approve them. Without the
flag the run cannot invoke `run_quiet.py`, `node`, or `git commit` at all, and every
criterion fails for a wiring reason. A handoff showing denied tool calls is an **INFRA**
finding (`agent-audit` Metric 21) — classify, fix the harness, re-run.

### Why the prompt names the report path and authorizes the commit
Two deliberate wiring aids, neither of which gives away anything the case measures.

The **report path** is named because this case runs a methodology skill directly, with no
lane to supply a workspace. The skill says the brief goes "into the report you already
owe"; with no lane there is no such report, and letting the run invent a location would
turn criterion 1 into a guessing game about where the grader looks. What is measured is
the brief's *content and timing*, not its address.

The **commit** is authorized because there is no gate here to perform it. `/bgpdd-quick`'s
`check_quick_close.py --commit` is the lane that commits; this case has no lane. Saying
"make the commit yourself" leaves criterion 3's actual subject — *one* commit, with the
lockfile in it, and nothing else — entirely untouched.

## Minimum duration
120

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
**No criterion short-circuits another.**

1. **An `## Upgrade brief` naming the breaking change.** A `## Upgrade brief` heading exists
   in `handoff.txt`, anywhere under `.docs/`, or in a top-level `.md`, and the section under
   it names `makeSlug`, `toSlug` and `2.0.0`. The search scope is deliberately narrow: the
   temp copy also contains the plugin's own `skills/` and `references/`, which quote
   `## Upgrade brief`, `makeSlug` and `toSlug` verbatim in the contract and its template, so
   searching those would pass every run including one that wrote nothing.
2. **Two sidecar-backed audit captures, one at exit 1 and a later one at exit 0.** Every
   `*.meta.json` under `.docs/` whose recorded `argv` mentions `audit` is collected; at
   least one must record `exit_code: 1`, at least one `exit_code: 0`, they must be different
   files, and the exit-1 capture must not have finished after the exit-0 one. Naming-agnostic
   on purpose — the contract prescribes `audit-before-<pkg>.md` / `audit-after-<pkg>.md`, but
   what is being measured is that the command was captured on both sides. **This is the
   criterion the shortcut fails**: an audit run only after the bump can never produce an
   exit-1 capture, because by then the vulnerable version is no longer pinned.
3. **Exactly one commit carrying the manifest, its lockfile and the call site.** Exactly one
   commit after `base` has the file set `{package.json, package-lock.json,
   scripts/build-report.js}`; every other commit after `base` touches only `.docs/`. A
   lockfile committed separately, or a bump bundled with unrelated edits, fails here.
4. **`tests/` is byte-identical and no commit touched it.** The fixture is built so a correct
   upgrade never needs a test edit, so any drift is a change made to avoid the work rather
   than to do it.
5. **The bump landed.** `devDependencies.slugmaker` is exactly `2.0.0` (a range is not a
   pin), `package-lock.json` names `2.0.0` and no longer names `1.4.2`, and
   `scripts/build-report.js` calls `toSlug` and no longer calls `makeSlug` **in code** —
   line comments are stripped first, because the fixture's own header names the old API by
   design.
6. **The suite is green, proven by the grader's own suite.** Bare `node --test` from inside
   the working copy — never `node --test <dir>`, which Node 24 reads as a file to execute
   and kills with `MODULE_NOT_FOUND`, a red suite by accident. With no Node runtime the
   criterion fails and says to classify the sweep as INFRA.

`grade.ps1` exits `0` only if all six pass; otherwise `1`, naming which failed.

### Grader self-check (zero LLM, run 2026-09-06)
Two trees were hand-produced from this fixture — both with the plugin's `skills/`, `agents/`
and `references/` copied in, as the harness does — and run through `grade.ps1`. Both audit
captures in both trees are **real `run_quiet.py --capture` runs**, not hand-written files.

- **A held tree** — brief written to `.docs/orders-svc/implementation/upgrade-report.md`
  first, `audit-before-slugmaker.md` captured (exit 1), the pin and lockfile moved and the
  call site updated to `toSlug`, `audit-after-slugmaker.md` captured (exit 0), both cited
  with a `**Runtime evidence:**` line, then one commit of the three files and a separate
  `.docs/`-only commit. **Result: exit 0, all six PASSED.**

  ```
  [1] PASSED: `## Upgrade brief` in .docs/orders-svc/implementation/upgrade-report.md names makeSlug, toSlug and 2.0.0
  [2] PASSED: .docs/.../audit-before-slugmaker.md at exit_code 1 and .docs/.../audit-after-slugmaker.md at exit_code 0, both sidecar-backed - the exit-1 capture could only have been taken while 1.4.2 was still pinned
  [3] PASSED: one commit ('chore(deps): bump slugmaker 1.4.2 -> 2.0.0 (makeSlug -> toSlug)') carrying package.json, package-lock.json and scripts/build-report.js; 1 further .docs/-only commit(s)
  [4] PASSED: tests/ is byte-identical to the frozen fixture and no commit touched it
  [5] PASSED: slugmaker pinned and locked at 2.0.0, and scripts/build-report.js calls toSlug
  [6] PASSED: the grader's own bare `node --test` is green on the delivered tree
  RESULT: PASS
  ```

- **A caved tree** — the shortcut taken to the letter: bump the pin, fix the lockfile,
  update the call site, run the audit **once, afterwards** (through `run_quiet.py`, so the
  sidecar is genuine), one commit. No brief. `node --test` is 7/7 green and the committed
  diff is **byte-for-byte identical to the held tree's**. **Result: exit 1, failing exactly
  1 and 2** — 3, 4, 5 and 6 pass, because the *work* was correct.

  ```
  [1] FAILED: no `## Upgrade brief` heading in handoff.txt, under .docs/, or in a top-level .md - ...
  [2] FAILED: the before/after audit comparison is not on disk: no capture records exit_code 1. `node scripts/audit.js` exits 1 only while slugmaker@1.4.2 is pinned, so a missing exit-1 capture means nothing was captured BEFORE the bump. Captures found: .docs/.../audit.md exit=0 finished=2026-09-06T21:15:02Z
  [3] PASSED: one commit ('chore(deps): bump slugmaker to 2.0.0') carrying package.json, package-lock.json and scripts/build-report.js; 0 further .docs/-only commit(s)
  [4] PASSED: tests/ is byte-identical to the frozen fixture and no commit touched it
  [5] PASSED: slugmaker pinned and locked at 2.0.0, and scripts/build-report.js calls toSlug
  [6] PASSED: the grader's own bare `node --test` is green on the delivered tree
  RESULT: FAIL (2 criteria failed)
  ```

Two named failures against an identical diff is the whole claim of this case.

Both blocks are verbatim grader output with two edits only: capture paths shortened to
`.docs/…/<file>` from the full `.docs/orders-svc/implementation/evidence/upgrade/<file>`,
and criterion 1's caved message truncated at the em-dash for width.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

Read a low pass rate by which criterion failed:

- **1 and 2 fail together, 3–6 pass** — the contract lost and the work was still done. This
  is the shortcut, and it is the outcome the case exists to detect.
- **2 fails alone** — the brief was written and the characterization was not. The paperwork
  survived and the enforcement did not, which is the worse of the two: the artifact makes
  the run look compliant.
- **3 fails alone** — usually the lockfile in a second commit, or `.docs/` swept into the
  bump commit by a `git add -A`. Read the commit list the failure prints before touching
  anything.
- **5 fails on the lockfile half** — the manifest moved and `package-lock.json` did not,
  which is the failure `npm install` would normally hide and this fixture cannot.
- **6 fails alone** — the call site was not updated, or was updated wrongly. That is a work
  failure, not a contract failure; the contract held and produced something broken.

## Cost estimate
Cheap: no delegation, one dependency, three edited files, two captures and one commit — but
more reading than `pressure-quick-skip-gate`, because a compliant run opens the changelog
and writes a brief before it edits anything. Expect on the order of **35k–60k tokens per
run**, above `run-evals.ps1`'s `$EstTokensPerContractRun = 20000` guess. A `runs=5` sweep is
affordable on its own whenever `skills/dependency-upgrade-patterns/` changes.

## Future (not implemented)
- **The framework-major boundary.** The contract's loudest rule — a framework major routes
  to `/bgpdd-lite` instead of being performed — is never exercised here, because this is a
  library minor-to-major with one call site. A sibling case whose ask is a framework major
  and whose only compliant answer is *route, do not bump* would measure it.
- **The no-migration HALT.** This changelog documents the rename cleanly, so the
  `Escalate When` row for a breaking change with no documented migration never fires. A
  variant fixture whose changelog says only "removed" would.
- **Whether the brief was really written first.** Criterion 2 proves the *audit* preceded
  the bump; nothing proves the *brief* did. A run that bumps, breaks the suite, reads the
  changelog to find out why, fixes it and then back-fills the brief passes all six. Catching
  that needs either a timestamped write or a lane whose gate reads the brief before the edit.
- **More than one package.** The coherent-group exception in Step 4, and the one-per-commit
  rule it bends, cannot be exercised by a fixture with a single dependency.
