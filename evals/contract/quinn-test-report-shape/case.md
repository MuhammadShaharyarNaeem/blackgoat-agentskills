# Case: quinn-test-report-shape

## Purpose
Guards against Quinn producing a `test-report.md` that pipeline-tools' test-mode
parser can't extract coverage from: missing `#Task [N]:` headers, missing or malformed
Coverage Ledger lines (`- FR-n: PASS — {evidence}`), or IDs mentioned only in prose
without a `PASS`/`FAIL` status token (per `skills/pipeline-tools/SKILL.md`, such mentions
are not counted as covered and only warn). A report with the wrong shape makes the test-mode
coverage gate fail-closed on real, working requirements — indistinguishable from an
actual regression unless someone manually eyeballs the report.

## Frozen Input
- Fixture dir: `fixture/` — already mirrors the temp working copy's final layout:
  `.docs/password-reset/requirements.md` (3 Must FRs, 1 Must NFR) and `plan.md` (3
  tasks, each citing the FR/NFR it covers), plus `src/passwordReset.js` (an
  already-implemented password-reset token module) and `package.json` (`npm test` wired
  to `node --test`) at the fixture root. Quinn does not implement `src/` — it
  already works; her job is only to write and run tests against it.
- Copies to: `.` (the fixture root is copied straight onto the temp working copy's
  root, preserving its internal `.docs/password-reset/` nesting).

## Command
Run from the temp working copy's root:

```powershell
claude -p "Act as Quinn per agents/quinn.md. Read .docs/password-reset/requirements.md and .docs/password-reset/plan.md. Write unit tests into tests/ against the existing src/passwordReset.js (do not modify src/), run them, and append your results to .docs/password-reset/test-report.md using the strict #Task [N]: header and Coverage Ledger format from agents/quinn.md section 6 (one line per exercised requirement ID, e.g. '- FR-1: PASS - {test name}')." --permission-mode acceptEdits
```

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. `.docs/password-reset/requirements.md` is present (fixture sanity check).
2. `.docs/password-reset/test-report.md` was produced.
3. Contains at least one `#Task [N]:` header.
4. Contains at least one Coverage Ledger line matching `- FR-n: PASS|FAIL` or
   `- NFR-n: PASS|FAIL`.
5. `python skills/pipeline-tools/scripts/check_coverage.py --requirements <requirements.md> --test-report <test-report.md>` emits parseable JSON and exits `0` or `1` — **never `2`**.
   Exit `2` means the report is structurally unreadable to the gate (a shape failure);
   exit `0`/`1` both mean the report's *shape* was fine and the gate could form a real
   verdict from it, regardless of whether every individual test happened to pass.

`grade.ps1` exits `0` only if all five pass; otherwise it exits `1` and prints which
criterion failed.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

## Future (not implemented)
Whether Quinn's tests are actually *good* tests (real edge-case coverage, not
tautological assertions) is a judgment call outside what a shape-checker can decide. Not
implemented here.
