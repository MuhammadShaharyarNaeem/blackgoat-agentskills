# Case: test-authenticity-adversarial

## What this proves

An adversarial eval for `check_test_authenticity.py`, the gate that turns "a
test went green" into a claim that has to survive a structural reading of the
test file (convention #9).

The gate ships an 83-case `--self-test` which proves each predicate in-process
against synthetic fixtures. This case proves the four things that self-test
structurally cannot:

- **It judges a real tree as a SUBPROCESS**, the way the build, verify and
  bugfix lanes invoke it: `--repo <dir> --changed-files <paths>`, a real src
  root discovered from a real `package.json` and a real `.csproj`, a real
  ledger, and the exit code plus the per-file `code` list read back off
  stdout. A self-test asserting `judge_file()` in-process proves the
  predicate, not the CLI contract the pipelines call.
- **Every legitimate near-miss stays green.** Nine legitimate files, each one
  a fake with exactly one fact changed:

  | fake | legitimate near-miss | the one differing fact |
  | --- | --- | --- |
  | `synthetic-setcontent.spec.ts` | `real-setcontent-after-goto.spec.ts` | the `setContent` follows a `page.goto` and replays the app's own markup |
  | `source-eval-newfunction.spec.ts` | `real-fixture-read.spec.ts` | the `readFileSync` reads a JSON fixture, not production source |
  | `tautology-toplevel.spec.ts` | `real-tiny-helper.spec.ts` | the same-named helper is two statements, below the size floor |
  | `tautology-module.spec.ts` | `real-e2e-helpers.spec.ts` | five helpers, every one of them driving `page` |
  | `tautology-module.spec.ts` | `real-one-local-def.spec.ts` | one local definition, not two distinct ones |
  | `hermetic-enum.spec.ts` | `real-import.spec.ts` / `real-e2e.spec.ts` | it imports production code / it navigates the app |
  | `Api.Tests/CopyTests.cs` | `Api.Tests/OrderHandlerTests.cs` | `using Api.Handlers;` and `new OrderHandler(...)` |
  | `tests/test_copy.py` | `tests/test_rules.py` | `from pkg.rules import classify_total` |

  A gate that flagged everything would pass a suite made only of fakes and be
  deleted the first week. Those pairs are what makes the twelve positives mean
  something.
- **The assertion is the EXACT problem-code set, per file.** Steps 3–14 name
  the full sorted code list for each fake rather than "it failed": the four
  codes fire independently and co-occur constantly (nine of the twelve fakes
  carry two or three), so a roll-up over the whole set stays green when one
  detection rule regresses and another fires on the same file. Step 2 is the
  roll-up, and it is deliberately the weaker assertion of the two.
- **The waiver's floor holds, and the ledger records are a chain a hand edit
  breaks.** `--reason "   "` and an `--allow` with no paired `--reason` are
  exit 2, not silent passes; a *reasoned* waiver reports `ALLOWED` with the
  findings still listed and lands its text in the ledger record as
  `allow_reasons`; a waiver naming a different file leaves the failure
  standing. Steps 38–42 then verify the chain end to end: every record the run
  wrote verifies intact, a recorded `FAIL` hand-edited to `PASS` — the exact
  forgery that would make a downstream `--require-ledger-gates
  check_test_authenticity.py` read a green over a suite of fakes — fails
  `self-mismatch` **on that line**, and a removed record fails the following
  line's `prev`.

**The empty-index refusal is the step that matters most** (step 37). The gate's
whole discrimination rests on a symbol index built from the src roots. A repo
where no src root is discoverable would index nothing, match nothing, and
report every test file in the tree as authentic — a PASS over a tree it never
read, which is strictly worse than a refusal. That case is exit 2 with `no src
root` in the error, on the same grounds as `check_openapi_diff.py`'s
`unanalyzable_schema`.

**The `.csproj`-beside-its-code root is the shape that justifies the fixture's
layout.** `Api/Api.csproj` has no `src/` subdirectory, so a discovery
heuristic that only looked for conventional subdirectories would find no
production code for the C# half and mark `Api.Tests/CopyTests.cs` authentic on
the tautology axis. The C# method pattern is likewise the reason `Classify`
has to be indexed at all: `public string Classify(int total)` puts a return
type between the modifiers and the name, which the TS/JS method pattern reads
as the name itself.

## Why this needs no `claude -p` and is exempt from runs=5

This is a **zero-LLM** case: every step is a subprocess call to a deterministic
stdlib-Python CLI against fixture files this script writes. There is no persona
invocation and no output-shape judgement call — every assertion is an exact
exit code plus a naming JSON field, compared against a value that follows
mechanically from the tool's documented contract
(`skills/pipeline-tools/SKILL.md` § `check_test_authenticity.py`). The suite's
`runs=5` / threshold `4/5` doctrine (see `evals/README.md`) exists to average
out **LLM output variance** across repeated persona runs; there is no variance
source here. A single run is a legitimate final verdict.

That is also why this case does not follow the `case.md` + `fixture/` +
`grade.ps1` shape `run-evals.ps1` expects, and is therefore **not
dispatchable** by `Get-ContractCases` — which discovers a contract case by the
presence of *both* `case.md` and `grade.ps1`, and this directory has neither,
exactly like `contract/mechanical-pipeline/`,
`contract/bugfix-gates-adversarial/` and `contract/openapi-diff-adversarial/`.
It is registered instead in `run-evals.ps1`'s `$ZeroLlmCases` and run with
`--record` at the start of every confirmed contract batch. It costs nothing and
needs no `-Confirm` gate.

Unlike `bugfix-gates-adversarial`, this case needs **no git repository and no
`run_quiet.py` capture** — the gate reads files and writes one ledger line per
run, so the fixture is a directory tree and a temp directory.

## The fixtures are synthetic

Every fake here reproduces a *shape* observed in a real Playwright suite; none
of them contains that suite's code. The production module the fakes transcribe
(`src/asset/backup-card.ts`, `src/asset/policy-visibility.ts`,
`Api/Handlers/OrderHandler.cs`, `src/pkg/rules.py`) is written for this case
and exists only to give the symbol index something true to match against.

## When to re-run it

- Any change to `skills/pipeline-tools/scripts/check_test_authenticity.py`, or
  to the heuristics documented in
  `skills/pipeline-tools/references/check_test_authenticity.md` — the
  `STOPWORDS` list, the driver-token set, the statement floor and the src-root
  discovery order all move verdicts, and this is where that shows.
- Any change to the pipeline wiring that invokes the gate (the lanes' gate
  ladders) that alters the flag shape: `--repo`, `--changed-files`,
  `--allow`/`--reason`, `--milestone`, `--ledger`.
- Any change to the shared ledger-chain helper (steps 39–41 are this gate's
  end-to-end chain coverage; `check_ledger.py`'s drift guard covers the helper
  itself, and its `CHAINED_GATES` list must keep naming this gate).

## Running it

```bash
python evals/contract/test-authenticity-adversarial/run.py            # print only
python evals/contract/test-authenticity-adversarial/run.py --record   # + results.jsonl
```

Exit 0 only if all 42 steps pass. The script creates and removes its own temp
directory; it writes nothing under the repository except the `--record` line.
