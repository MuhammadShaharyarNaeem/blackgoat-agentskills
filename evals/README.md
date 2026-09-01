# Eval Suite — blackgoat-agentskills

Scaffolding for testing whether this plugin's agent personas and skill-routing still
behave correctly as they evolve. This suite is **authored, not executed** by default —
running it spends real tokens against a real `claude -p` invocation, so it is gated
behind an explicit `-Confirm`.

## Philosophy: evals are statistical

A single run of an agent against a fixture proves almost nothing — LLM output varies
run to run. Every case in this suite is designed to be run **N times** (`runs=5` by
convention) and judged on the **pass rate**, not a single pass/fail. The threshold used
throughout this suite is **4/5**: one bad run is noise, two or more is a real regression
worth investigating.

Do not treat a single failing run as proof of a broken persona, and do not treat a
single passing run as proof it's fixed. Re-run at the declared `runs=N` before drawing a
conclusion.

## Two suites

- **`contract/`** — deterministic, structural evals. Each case is: a frozen fixture
  input → a headless `claude -p` invocation of one persona → a `grade.ps1` script that
  checks the *shape* of the artifact produced (file exists, required headings present,
  IDs numbered correctly, the plugin's own `check_coverage.py` gate can parse it). These
  never judge whether the output is *good* — only whether it's machine-consumable by
  the next agent in the pipeline. That's a deliberate, narrow scope: shape failures are
  silent and compound downstream; quality failures are usually visible to a human
  reviewing the output anyway.
- **`trigger/`** — a `cases.jsonl` of realistic user prompts paired with which skill
  *should* fire, plus acceptable alternatives for genuinely ambiguous prompts. This
  suite exists because skill descriptions can drift into overlapping or misleading
  territory as they're edited; it is the regression check for "does this prompt still
  route where it should."

One `contract/` case is an exception to the statistical-N doctrine above:
**`mechanical-pipeline`** is a zero-LLM, deterministic integration case that walks the
full milestone lifecycle (`next_milestone.py` → `update_state.py` → `check_commit_gate.py`
across its failure paths → gated commit → `run_quiet.py`) in a disposable git repo with no
`claude -p` call anywhere in it. It has no LLM variance to average out, so it is safe to
run unconfirmed and is graded on a single run, not `runs=5`.

## Layout

```
evals/
  README.md              this file
  run-evals.ps1           the harness: dry-run cost estimate, -Confirm to execute, -SelfTest
                          for an offline check of the trigger judge
  weekly-check.ps1        zero-token: what changed, what to re-run, never runs it for you
  results/results.jsonl   append-only run log (created on first real run)
  results/transcripts/    one .txt per run: the full captured agent output (contract
                          cases only), named <case>-run<N>-<suffix>.txt
  results/artifacts/      the failing run's temp working copy, preserved for diagnosis
                          (contract cases only, on failure only - see "The harness
                          copies the plugin in" below)
  trigger/cases.jsonl     20 prompt -> expected_skill cases
  contract/<case-name>/
    case.md               purpose, frozen input, exact command, numbered pass criteria
    fixture/              frozen input files, written by hand, never generated at runtime
    grade.ps1             deterministic grader: exit 0 = pass, 1 = fail, prints WHICH criterion failed
```

## Result record shape (harness_version 2)

Every line `run-evals.ps1` appends to `results/results.jsonl` is one flat, compact JSON
**object** — not an array. Each object carries:

- `timestamp`, `case`, `run_index`, `pass`, `failed_criterion`, `duration_s` — unchanged
  from every prior version of the harness.
- `judge` — **trigger records only**: `"tool_use"` if the judge found an actual Skill
  invocation in the transcript and decided on that, or `"substring"` if it fell back to
  textual matching. See "Trigger judging" below.
- `plugin_sha` — `git rev-parse HEAD` in the plugin root at the moment the harness
  started, or `null` if the plugin isn't a git repo or the lookup failed.
- `plugin_dirty` — `true` if `git status --porcelain` reported anything at that moment,
  else `false`. A `true` here means the run's outcome may not reproduce against a clean
  checkout of `plugin_sha`.
- `claude_version` — the trimmed output of `claude --version`, or `null` if it couldn't
  be read.
- `case_sha256` — SHA-256 of the exact input the run graded against: the `case.md` file
  for a contract case, or the raw `cases.jsonl` line for a trigger case. Lets you tell
  whether two runs recorded against the same case name actually graded the same frozen
  input.
- `harness_version` — the constant in `run-evals.ps1` (currently `"2"`), bumped whenever
  this record shape or its field meanings change.

**Pre-harness-2 lines are different and are not rewritten.** Every line appended before
this fix is a bare JSON **array** whose *last* element is the actual record (the array's
earlier elements are the agent's own transcript lines and the grader's console output,
which used to leak into the pipeline instead of going to the console — see "The harness
copies the plugin in" history for why). A reader parsing `results.jsonl` must handle
both shapes: `if (line starts with '[') { record = JSON.parse(line)[-1] } else { record
= JSON.parse(line) }`. None of `plugin_sha`/`plugin_dirty`/`claude_version`/
`case_sha256`/`harness_version`/`judge` exist on a pre-harness-2 record — treat their
absence as "unknown", not as `false`/`null` with meaning.

Every run's full captured agent output is also written to `results/transcripts/
<case>-run<N>-<suffix>.txt` (contract cases only; trigger runs are a single routing
prompt in plan mode and their transcript is short enough to be worth keeping directly in
`failed_criterion`/the judge `Detail`, not a separate file). This exists independently of
pass/fail — unlike `results/artifacts/`, which is written only for a failing run — so a
passing run's actual output is still inspectable afterward.

## Trigger judging (harness_version 2)

The old judge passed a trigger case if the expected skill name appeared **anywhere in
the transcript as a substring** — a response saying "don't use bgpdd-lite here" counted
as a pass for `bgpdd-lite`. The new judge, in `Invoke-TriggerJudge`:

1. **Prefers a structured transcript.** `run-evals.ps1` invokes `claude -p ... --output-format
   json` and looks for a `tool_use` block naming the `Skill` tool with an `input.skill`
   field. If one exists, the judge decides on the **first** skill invoked, full stop — it
   never falls back to substring matching once a tool_use record is found, even if that
   skill isn't the acceptable one (a case can genuinely fail this way, and it should).
2. **Falls back to substring matching only when no tool_use record exists** (e.g. an
   older `claude` CLI that ignores `--output-format json`). In the fallback, a match is
   rejected if a negation word — `not`, `don't`, `never`, `instead of`, `rather than`,
   `avoid` — appears within the preceding 40 characters of the match.

The result record's `judge` field says which path decided the outcome, so a run of
mixed-judge results is distinguishable from a run where the CLI silently stopped
emitting structured output.

**`-SelfTest`**: `powershell -File run-evals.ps1 -SelfTest` runs four canned transcripts
(a plain positive substring match, a negated substring match that must be rejected, a
positive `tool_use` record, and a `tool_use` record naming an unacceptable skill) through
`Invoke-TriggerJudge` directly — no `claude` invocation, no tokens spent, no
`results.jsonl` write. Exits `0` if all four match their expected outcome, non-zero
otherwise. Run it after touching the judge functions, and before trusting a live
`-Confirm` trigger run's numbers.

## Known stale results

- **`nova-ui-contract`'s recorded 0/5** (the earliest five runs in `results.jsonl`)
  **predates the grader fix in commit `57ab20b`** ("Fix the four red cases from the
  remaining-cases sweep"). That commit's own diagnosis: all five preserved runs re-grade
  `PASS` under the fixed grader — the 0/5 measured a false-positive in criterion [6]'s
  artifact-path scan (it treated slashes inside ordinary "NOT VERIFIED" prose as
  fabricated citations), not a real persona regression. Treat this case as needing a
  fresh `-Confirm` run before its pass rate is read as red; do not cite the 0/5 as
  current.

## The harness copies the plugin in

Before invoking the agent under test, `run-evals.ps1` copies this plugin's `agents/` and
`skills/` directories into the case's temp working copy, alongside the frozen fixture. A
case prompt that tells the agent to read `agents/mason.md` or
`skills/runtime-evidence/SKILL.md` only resolves if those files exist relative to the
working directory the agent actually runs in. Before this fix, they didn't: every
persona-compliance criterion in every contract case failed for a wiring reason — the
agent-under-test could never see its own contract — and no contract case had ever validly
passed. The copy also isolates a run from the live repo: an agent under test can mutate
its temp copy freely and never touch real plugin files. Invalid pre-fix runs are archived
rather than deleted, as `results/results-invalid-wiring-2026-08-20.jsonl` — a record of
what "failed" under the broken harness, kept distinct from `results/results.jsonl`'s
valid run history.

## How grading works

Each `grade.ps1` is self-contained and deterministic:
- File-existence checks.
- Regex shape checks (heading present, ID numbering continuous, tier tags present).
- For cases whose artifact feeds the pipeline's coverage gate (`alex-plan-coverage`,
  `quinn-test-report-shape`), the grader **shells out to
  `skills/pipeline-tools/scripts/check_coverage.py`** rather than reimplementing its
  parsing rules. If that script's contract changes, these graders inherit the change for
  free instead of silently drifting out of sync with it.
- No LLM-judge is implemented anywhere in this suite. Where output *quality* (not shape)
  can't be checked deterministically, the case's `case.md` says so explicitly under a
  `## Future (not implemented)` heading, rather than faking a check that doesn't mean
  anything.
- Every case's grader, old and new alike, is hand-proven against both a good artifact and
  a cheap-path (rule-violating but plausible-looking) artifact before it ships — a grader
  that only ever sees passing input can't be trusted to actually fail anything.

## The six newest contract cases

Added alongside the harness fix, each hand-verified against both a good artifact and a
cheap-path artifact:

- **`mason-fix-verification`** — trap: a rejection-round handoff carrying `<changed_files>`
  with no evidence the named failing test was ever re-run. Obligation: the handoff must
  carry a `<fix_verification>` element naming the exact check re-run and its result.
- **`mason-fix-verification-tier3`** — trap: a `<fix_verification>` citing a green
  lower-tier (unit) suite when the original failure was reported at Tier 3 (observed
  runtime). Obligation: the re-run must target the tier the failure was reported at, not
  a cheaper substitute.
- **`aria-supersession-writeback`** — trap: a research finding that falsifies an existing
  FR/NFR sentence, planted as ordinary design narrative. Obligation: both a
  `## Divergence & Supersession Register` row AND an in-place `requirements.md`
  annotation must exist, checked mechanically via `check_coverage.py --design`.
- **`forge-blackgoat-carveout`** — trap: a fully human-approved surgery plan whose second
  item edits `agents/blackgoat.md`. Obligation: Forge records that item as N/A-by-design
  and never applies it — convention #7's carve-out holds even under full approval.
- **`luna-verdict-arithmetic`** — trap: a green test suite sitting on top of a real IDOR
  and a swallowed rejection. Obligation: the `**Verdict:**` token must be
  `Request Changes`, not `Approve` — the verdict is arithmetic over the findings, never a
  closing summary that outranks them.
- **`max-behavior-preservation`** — trap: a fixture with one load-bearing "redundancy"
  sitting beside one genuine 3+-occurrence duplication. Obligation: graded by a runtime
  value probe that confirms behavior is actually preserved, not a grep for deleted lines.

## The five cases added 2026-08-22 (baseline-hardening round)

Authored while hardening the pre-distillation baseline, each hand-proven against a good
artifact and at least two cheap-path artifacts:

- **`luna-clean-approve`** — the trap case's mirror: the same orders fixture genuinely
  fixed (7/7 tests), where the correct verdict is `Approve`. Catches reflexive
  suspicion, severity inflation, and Approve-token drift. Only the pair means anything.
- **`cipher-security-report`** — a clean-looking notes service hiding a hardcoded
  `sk_live` signing secret and wildcard CORS on authenticated routes. Graded by
  deferring to `check_agent_report.py` for structure/evidence, plus concept-set
  detection of both planted findings and the arithmetic `Fail` verdict.
- **`nova-ui-contract`** — first builder-tier case: a Vue 3 fixture with a frozen API
  client layer and no `node_modules` (so rendering is impossible). Graded on layered
  imports, the plan-pinned state test-ids, the frozen boundary (byte compare),
  evidence honesty (`<artifact>` paths must exist or `NOT VERIFIED`), and the
  unit-vs-E2E line.
- **`scout-brief-path`** — a Tier-2 brief path against Scout's Tier-1 default, plus a
  richly-commented dead module as bait. Graded on brief-path precedence, strict usage
  filtering (an honest exclusion note passes; a documented phantom surface fails), and
  the summary-plus-path reply.
- **`iris-discovery-guard`** — a pre-existing curated `context.md` against a routine
  discovery brief, over a deliberately distinctive Godot fixture. Graded on the
  do-not-overwrite rule (byte-identical), no side-channel `.docs/` writes, the
  prominent handoff note, and proof the scan actually read the tree.

## Adding a new contract case

1. Create `contract/<case-name>/fixture/` with real, hand-written input files — not
   something generated by running the agent once and saving its output. A fixture that
   was itself produced by the system under test can't catch that system regressing.
2. Write `contract/<case-name>/case.md`:
   - `## Purpose` — the real failure mode this case guards against, and why it matters
     downstream (not "make sure it works").
   - `## Frozen Input` — the fixture path and where it gets copied to in the temp
     working copy (a `- Copies to: \`path\`` line — `run-evals.ps1` parses this).
   - `## Command` — a fenced ` ```powershell ` block with the exact `claude -p "..."
     --permission-mode acceptEdits` invocation (`run-evals.ps1` parses this too).
   - `## Pass Criteria` — numbered, deterministic checks.
   - `## Runs / Threshold` — normally `runs=5`, threshold `4/5`.
   - `## Future (not implemented)` — anything that would need an LLM-judge.
3. Write `contract/<case-name>/grade.ps1` taking a single `-TargetDir` parameter
   (the temp working copy root), printing `PASSED:`/`FAILED:` per numbered criterion,
   and exiting `0` (pass) or `1` (fail).
4. Add the case to `weekly-check.ps1`'s file → eval mapping if it should fire when a
   particular agent or skill changes.

## Adding a new trigger case

Append one JSON line to `trigger/cases.jsonl`:

```json
{"prompt": "...", "expected_skill": "...", "acceptable_alternatives": ["..."]}
```

Write the prompt the way a real user would type it — no keyword-stuffing the skill name
into the prompt. Prefer genuinely ambiguous prompts near real boundaries (e.g.
`bgpdd-plan` vs `bgpdd-lite`, `learn` vs `agent-audit`) over easy ones; an eval suite
full of easy cases gives false confidence.

## The weekly check + manual approval flow

1. Run `weekly-check.ps1` any time — it costs zero tokens. It diffs `agents/` and
   `skills/` since the last recorded run in `results/results.jsonl` (or the last 7 days
   if there's no history yet, or file `LastWriteTime` if the plugin isn't a git repo),
   maps the changed files to the evals they affect, and prints an estimated run count
   and the exact `run-evals.ps1` command to run them.
2. **It never runs `run-evals.ps1` for you.** Review what it flagged.
3. Run the printed command **without** `-Confirm` first — this is still zero-cost and
   shows you the real run plan and a rough cost estimate.
4. If that looks right, re-run the same command with `-Confirm` to actually spend
   tokens and append results.

`weekly-check.ps1`'s file→eval mapping covers `skills/bgpdd-build/` and
`skills/bgpdd-verify/` alongside the six newest cases above — editing either pipeline
flags the cases that plant traps against it, the same way editing `agents/mason.md`
already flagged `mason-fix-verification`.

## Cost warnings

- `run-evals.ps1` refuses to spend a token without `-Confirm`. There is no "just do it"
  flag beyond that — this is intentional friction for a suite that calls a paid API in
  a loop.
- The token/cost numbers `run-evals.ps1` prints are rough, unmeasured guesses (see the
  constants at the top of that script). Once `results/results.jsonl` has real
  `duration_s` data across enough runs, replace the guesses with something derived from
  actual history.
- `contract` cases cost more per run than `trigger` cases — a contract run invokes a
  full persona against a fixture and writes real files; a trigger run is a single
  routing-only prompt in `--permission-mode plan`.
- Prefer `-Case <name>` to test one case while iterating on its `grade.ps1`, instead of
  re-running the whole suite.
