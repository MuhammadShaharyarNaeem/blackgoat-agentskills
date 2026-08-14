# Case: quinn-test-report-shape

## Purpose
Guards against Quinn producing a `test-report.md` that pipeline-tools' test-mode
parser can't extract coverage from: missing `#Task [N]:` headers, missing or malformed
Coverage Ledger lines (`- FR-n: PASS — {evidence}`), or IDs mentioned only in prose
without a `PASS`/`FAIL`/`BLOCKED` status token (per `skills/pipeline-tools/SKILL.md`, such
mentions are not counted as covered and only warn). A report with the wrong shape makes
the test-mode coverage gate fail-closed on real, working requirements — indistinguishable
from an actual regression unless someone manually eyeballs the report.

It also guards the shape of the **evidence** on those lines. `agents/quinn.md`'s
strongest rule is her 2026-07-26 procedural memory — *every `PASS` you write carries,
inline, the verbatim command you ran and the captured block of its output* — and until
criteria 6 and 7 were added, her only eval checked for a header, a status token, and a
parseable ledger, but never for a command, an exit code, or any sign that something had
been executed. A report of statuses with no producers named passed cleanly. That is the
gap those two criteria close.

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
4. Contains at least one Coverage Ledger line matching `- FR-n: PASS|FAIL|BLOCKED` or
   `- NFR-n: PASS|FAIL|BLOCKED`. **`BLOCKED` is a first-class coverage token**, not a
   near-miss: `agents/quinn.md` makes it the only honest status for a check whose
   precondition was absent, and `check_coverage.py` reports it in its own `blocked` array
   (where it reads as *not covered*, so honesty routes the work rather than passing it).
   A regex omitting it would read an honest `BLOCKED` report as a shapeless one.
5. `python skills/pipeline-tools/scripts/check_coverage.py --requirements <requirements.md> --test-report <test-report.md>` emits parseable JSON and exits `0` or `1` — **never `2`**.
   Exit `2` means the report is structurally unreadable to the gate (a shape failure);
   exit `0`/`1` both mean the report's *shape* was fine and the gate could form a real
   verdict from it, regardless of whether every individual test happened to pass.
6. **Every** ledger line names what produced its status: the text after the status token
   carries either a backticked span (the command) or a `file::test-name` reference. A
   status token with nothing behind it is an opinion, and Quinn's own rule forbids it.
7. The report shows that something **ran**: at least one fenced output block (an opening
   and a closing ` ``` `), or an `exit <N>` citation.

`grade.ps1` exits `0` only if all seven pass; otherwise it exits `1` and prints which
criterion failed.

### The honest limit of criteria 6 and 7
**A shape checker cannot verify that the output is real — only that the report has the
shape a real one has.** Criterion 6 is satisfied by any backticked span, including a
quoted value rather than a command (`` `{ status: 'ok' }` `` passes it). Criterion 7 is
satisfied by a fenced block containing anything at all, and by the literal string
`exit 0`. Both are trivially satisfiable by a determined fabricator, and neither is
evidence of execution.

What they *do* buy is worth having anyway: they close the gap where a report of bare
statuses — no command, no output, nothing that even claims to have run — passed this eval
cleanly, and they make the fabrication require deliberate effort rather than mere
omission. The check that actually forces an observation is a different one:
`quinn-runtime-evidence`, whose gate opens the cited capture and rejects an in-process
transport. Do not read a `PASS` here as "the tests ran".

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

## Future (not implemented)
- Whether Quinn's tests are actually *good* tests (real edge-case coverage, not
  tautological assertions) is a judgment call outside what a shape-checker can decide.
- Whether the backticked span in criterion 6 is genuinely the command that produced the
  status, and whether the fenced block in criterion 7 is genuinely that command's output.
  Distinguishing a command from a quoted value by regex is not reliable, and nothing on
  disk ties a block of text to a process that ran. Both would need either an LLM-judge or
  a transcript the grader does not have.
