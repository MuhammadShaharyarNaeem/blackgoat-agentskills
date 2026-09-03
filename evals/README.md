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
  *should* fire, plus acceptable alternatives for genuinely ambiguous prompts, run
  against a frozen app fixture in `trigger/fixture/`. This suite exists because skill
  descriptions can drift into overlapping or misleading territory as they're edited; it
  is the regression check for "does this prompt still route where it should." It judges
  an actual `Skill` tool invocation — see "Trigger judging" below.

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
  results/transcripts/    every run's evidence, pass or fail:
                            <case>-run<N>-<suffix>/          contract: stdout.txt, plus
                                                             handoff.txt and .docs/ when
                                                             the run produced them
                            <case>-run<N>-<suffix>.jsonl     trigger: the raw stream-json
                                                             transcript the judge read
                                                             (+ -stderr.txt if non-empty)
  results/artifacts/      the failing run's temp working copy, preserved for diagnosis
                          (contract cases only, on failure only - see "The harness
                          copies the plugin in" below)
  trigger/cases.jsonl     20 prompt -> expected_skill cases
  trigger/fixture/        the frozen app the 20 prompts route about; copied to the temp
                          working directory of every trigger run
  contract/<case-name>/
    case.md               purpose, frozen input, exact command, numbered pass criteria
    fixture/              frozen input files, written by hand, never generated at runtime
    grade.ps1             deterministic grader: exit 0 = pass, 1 = fail, prints WHICH criterion failed
```

## Result record shape (harness_version 3)

Every line `run-evals.ps1` appends to `results/results.jsonl` is one flat, compact JSON
**object** — not an array. Each object carries:

- `timestamp`, `case`, `run_index`, `pass`, `failed_criterion`, `duration_s` — unchanged
  from every prior version of the harness.
- `outcome` — **trigger records only**: `"ROUTED_OK"`, `"ROUTED_WRONG"`, `"NO_ROUTE"`, or
  `"HARNESS_ERROR"`. `pass` is `true` for `ROUTED_OK` and nothing else.
- `first_skill` — **trigger records only**: the skill named by the FIRST `Skill` tool
  invocation in the transcript, plugin namespace stripped, or `null` for `NO_ROUTE`.
- `mentioned_only` — **trigger records only**: whether the final answer text named an
  acceptable skill without a negation word in front of it. A **diagnostic**, never a
  pass condition — see "Trigger judging" below.
- `transcript` — path, relative to `evals/`, of this run's archived evidence: a
  directory for a contract run, a `.jsonl` file for a trigger run.
- `judge` — **trigger records only**: always `"tool_use"` at harness 3. The field is kept
  so a harness-2 line (where it could read `"substring"`) stays distinguishable.
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
- `harness_version` — the constant in `run-evals.ps1` (currently `"3"`), bumped whenever
  this record shape or its field meanings change.

**Pre-harness-2 lines are different and are not rewritten.** Every line appended before
this fix is a bare JSON **array** whose *last* element is the actual record (the array's
earlier elements are the agent's own transcript lines and the grader's console output,
which used to leak into the pipeline instead of going to the console — see "The harness
copies the plugin in" history for why). A reader parsing `results.jsonl` must handle
both shapes: `if (line starts with '[') { record = JSON.parse(line)[-1] } else { record
= JSON.parse(line) }`. None of `plugin_sha`/`plugin_dirty`/`claude_version`/
`case_sha256`/`harness_version`/`judge` exist on a pre-harness-2 record — treat their
absence as "unknown", not as `false`/`null` with meaning. `outcome`/`first_skill`/
`mentioned_only`/`transcript` exist only from harness 3 onward.

Every run's evidence is archived under `results/transcripts/`, independently of pass/fail
— unlike `results/artifacts/`, which is written only for a failing run:

- **Contract runs** get a directory, `<case>-run<N>-<suffix>/`, holding `stdout.txt` plus
  `handoff.txt` and the whole `.docs/` tree when the run produced them. The directory
  (rather than the single `.txt` harness 2 wrote) closes a real gap: four cases —
  `mason-fix-verification`, `mason-fix-verification-tier3`, `iris-discovery-guard`,
  `forge-blackgoat-carveout` — pipe the agent's entire reply into `Out-File handoff.txt`
  inside the temp working copy, so their stdout capture is empty *by construction* and
  the only copy of the graded artifact was deleted with the temp directory on a PASS.
  The copy happens before grading, so a grader that throws still leaves evidence behind.
- **Trigger runs** get `<case>-run<N>-<suffix>.jsonl`: the raw stream-json transcript the
  judge parsed, byte for byte, plus a sibling `-stderr.txt` if the CLI wrote anything to
  stderr. A routing verdict is only auditable if the stream it was read from survives.

## Trigger judging (harness_version 3)

**A trigger run measures routing: did the model actually invoke the right skill.** Two
earlier judges did not measure that, and their records are invalid — see "Known invalid
results" below.

**What a run does.** For each case, `run-evals.ps1`:

1. Creates a temp directory and copies `trigger/fixture/` into it (see "The trigger
   fixture"), then copies the plugin's `agents/`, `skills/` and `references/` in
   alongside, exactly as a contract run does.
2. Invokes `claude -p "<prompt>" --permission-mode plan --output-format stream-json
   --verbose` with that temp directory as the working directory, and with **stdin
   redirected from an empty file**. Without that redirect the CLI waits and writes
   `Warning: no stdin data received in 3s...` to stderr ahead of the stream.
3. Archives stdout verbatim to `results/transcripts/<case>-run<N>-<suffix>.jsonl` and
   judges from it.

**The three outcomes.** `Invoke-TriggerJudge` parses the stream line by line, finds the
**first** `tool_use` block whose `name` is `Skill`, and reads its skill from
`input.skill` (or `input.name`), stripping any plugin namespace so
`blackgoat-agentskills:bgpdd-plan` compares as `bgpdd-plan`:

| Outcome | Meaning | `pass` |
|---|---|---|
| `ROUTED_OK` | the first `Skill` invocation is the expected skill or an acceptable alternative | **true** |
| `ROUTED_WRONG` | the first `Skill` invocation names something else (recorded in `first_skill`) | false |
| `NO_ROUTE` | there is no `Skill` invocation anywhere in the transcript | false |

The first invocation decides, full stop. A wrong first route followed by a correct second
one is still `ROUTED_WRONG` — recovering after the fact is not the thing being measured.

**Why `NO_ROUTE` is not a pass.** This is the whole point of harness 3. A model that
discusses the right skill in prose, asks a clarifying question naming it, or writes "I'd
run `/bgpdd-plan` for this" has *not* routed; the skill's instructions never loaded and
nothing downstream of the routing decision ran. Counting that as a pass is what let the
suite report healthy numbers while the tool_use path was dead code. For diagnosis only,
the record carries `mentioned_only`: `true` means the final answer named an acceptable
skill (with no negation word in the preceding 40 characters), so the failure is "reasoned
right, didn't act" rather than "went somewhere else". It changes nothing about `pass`.

The negation-aware substring matcher that used to be a pass path
(`Test-PositiveSubstringMatch`) survives *only* as the thing that computes
`mentioned_only`. It has no other caller and must not acquire one.

**Slash commands.** The CLI's `system`/`init` event lists `Skill` in its `tools` array and
carries no slash-command-style tool; the 2026-09-03 probe stream contained no such block
either. Plugin skills are invoked through the `Skill` tool and nothing else here, so the
judge looks for exactly that. Plugin skills *are* namespaced in the CLI's
`slash_commands` list, which is why the judge normalizes the name before comparing.

**`-SelfTest`**: `powershell -File run-evals.ps1 -SelfTest` runs six canned stream-json
transcripts — shaped from the real probe — through `Invoke-TriggerJudge`: `ROUTED_OK`;
`ROUTED_WRONG` in a transcript whose final answer positively mentions the acceptable skill
(the harness-2 false pass); `NO_ROUTE` with `mentioned_only=true` (the probe verbatim in
shape); `NO_ROUTE` where the only mention is negated, so `mentioned_only=false`; a
plugin-namespaced skill name that must normalize; and two invocations where the first must
decide. No `claude` invocation, no tokens spent, no `results.jsonl` write. Exits `0` if
every case matches, non-zero otherwise. Run it after touching the judge functions, and
before trusting a live `-Confirm` trigger run's numbers.

## The trigger fixture

`trigger/fixture/` is a small, frozen, app-shaped tree copied to the working directory of
every trigger run. There is no `- Copies to:` line to parse as there is for a contract
case: **the fixture root becomes the temp working directory root**, always.

It exists because the 20 prompts have to have something to route *about*. Harness 2 ran
them from the plugin repo root, where there is no application at all — the 2026-09-03
probe of `trigger-1` ("add a whole new checkout flow…") shows the model globbing for
source files, finding none, and asking *which repo?* instead of routing. Every prompt was
being answered in a context where the honest answer is a question.

The fixture is `dashboard-app`: a Vue 3 SPA (`src/`, with `package.json`, an Axios client,
a dashboard search view and a reports view) over a .NET 8 API (`backend/`, with a
`.csproj`, reporting/ops/billing controllers and a nightly reconciliation job), plus a
`.docs/` tree carrying what specific prompts refer to:

- `.docs/webhook-notify/` — `requirements.md`, `implementation/plan.md` (two milestones),
  `implementation/ship-decision.md` (GO), and an `orchestrator-state.json` for a paused
  epic. Feeds "take the plan.md sitting in .docs/webhook-notify and go build it" and both
  ship-it prompts.
- `.docs/summary/context.md` and `.docs/summary/login/QA/manual-testing.md` — the global
  discovery context plus a locked-account QA baseline asserting `423` with a specific
  error body, which is what the verify-only prompt asks to re-confirm.

The source files carry the defects the bugfix prompts describe (an unguarded
`DateTime.Parse` behind the reports export, a debounce-less search watcher, a swallowed
exception in the reconciliation job, a `requestTimeoutMs` bumped out from under two
tests). The billing controller is deliberately single-tenant: it makes "map the existing
billing APIs" true and "a multi-tenant billing system, nothing like it exists" true at
the same time.

Keep every file small — the whole tree is copied per run. When editing it, re-read
`trigger/cases.jsonl` and check each prompt still has what it refers to;
`weekly-check.ps1` flags the `trigger` suite when anything under `trigger/fixture/`
changes, for exactly this reason.

`cases.jsonl` itself is unchanged by harness 3: same 20 prompts, same expected skills.
Prompts that are ambiguous without project context are left ambiguous on purpose — the
fixture *is* the context.

## Known invalid results

**Every trigger record written before `harness_version: "3"` measured mention, not
routing. Do not read any of them as routing accuracy.** Two distinct generations are
affected, and both are kept in `results.jsonl` rather than rewritten:

- **The original substring judge** passed a case if the expected skill name appeared
  anywhere in the transcript — including inside a sentence saying not to use it.
- **The 2026-09-03 harness-2 records** look better but are not. Harness 2 invoked
  `claude -p ... --output-format json`, which returns **one result object** (`is_error`,
  `num_turns`, `usage`, `result`) with no message content blocks at all. Its `tool_use`
  path could therefore never fire; every run silently fell through to the substring path,
  and every `judge: "substring"` value in those records is the tell. Worse, the runs
  executed from the plugin repo root, so the model had no application to route about and
  in the probed case invoked no skill whatsoever — its clarifying prose named
  `bgpdd-plan`, and that mention alone scored the run a PASS.

A pre-3 trigger pass rate says something like "the model talked about a plausible skill",
which is not a claim this suite is for. Re-run any trigger case under harness 3 before
citing its number.

### Open question: does `--permission-mode plan` suppress routing at all?

The one harness-3 validation run (`trigger-1`, 2026-09-03, transcript
`results/transcripts/trigger-1-run1-bc80e085.jsonl`) scored **`NO_ROUTE`** — with the
fixture in place, with `Skill` present in the CLI's `tools` array, and with all 36 plugin
skills listed in `slash_commands`. The model explored the fixture across 50 tool calls
(31 `Read`, 14 `Bash`, 2 `Agent`, 1 `Grep`, 1 `ToolSearch`, 1 `Write`), never invoked
`Skill`, and finished by writing a plan to `~/.claude/plans/` and asking which of three
readings of "checkout" was meant. So it produced a plan — plan mode's *own* built-in
workflow — instead of routing to `bgpdd-plan`.

That is a genuine, unresolved result, and the harness is reporting it correctly. Two
candidate causes, not yet distinguished:

1. **Plan mode crowds out skill invocation.** The CLI's plan-mode system prompt pushes
   straight to explore-then-write-a-plan, so the model never considers delegating the
   planning to a skill. If so, `--permission-mode plan` is the wrong mode for measuring
   routing, and the suite is measuring the mode rather than the skill descriptions.
2. **The fixture is too thin.** The run's own diagnosis was that `dashboard-app` cannot
   boot (no `Program.cs`, no router, no DB, no auth), and much of its output went to
   saying so. A fixture that reads as a real app might leave the routing decision as the
   only interesting move.

Next experiments, in order, **none of them run yet** (each costs real tokens):

- `--permission-mode default --allowedTools Skill` — isolates cause 1 by removing plan
  mode while still preventing any write.
- `--append-system-prompt "Route by invoking the matching skill"` — tests whether routing
  happens at all when it is explicitly the task, which separates "won't route" from
  "can't route".
- Thicken the fixture (a `Program.cs`, a router, one Pinia store) — tests cause 2.

Until one of those lands, do **not** read a `NO_ROUTE` sweep as "the skill descriptions
are broken". The judge is sound (see `-SelfTest`); what the invocation conditions measure
is still in question.

**Cost note from that run:** one trigger run cost **$1.77** over 15 turns and 252s, not
the few cents harness 2's estimate implied. A full trigger sweep at `runs=5` is roughly
$175. The `$EstTokensPerTriggerRun` constant was raised from 3,000 to 175,000 to reflect
the measurement. The harness pays for the entire session even though the verdict is
decided at the *first* `Skill` invocation — capping turns (e.g. `--max-turns`) is an
obvious cost lever, deliberately not taken yet because a cap could truncate a run before
it routes and turn a slow `ROUTED_OK` into a false `NO_ROUTE`.

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
`skills/` directories into the case's temp working copy, alongside the frozen fixture —
for **both** suites since harness 3, because trigger prompts about the squad itself ("go
through Rex and Alex's persona files…") need those paths to resolve too. Note this does
not determine which skills are *routable*: the `Skill` tool's catalogue comes from the
installed plugin, not from the working directory. A
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

Then make the fixture support it. If the prompt refers to something — an existing
endpoint, a failing job, a `.docs/` artifact — add the smallest file to
`trigger/fixture/` that makes the reference true. A prompt with nothing behind it does
not measure routing; it measures whether the model asks a clarifying question, and it
will score `NO_ROUTE` forever.

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
- `contract` cases still cost more per run than `trigger` cases, but the gap narrowed at
  harness 3: a contract run invokes a full persona against a fixture and writes real
  files, while a trigger run is a routing-only prompt in `--permission-mode plan` that
  now reads a real app fixture before deciding. The per-trigger-run estimate went from
  3,000 to 12,000 tokens to reflect that; it is still a guess.
- Prefer `-Case <name>` to test one case while iterating on its `grade.ps1`, instead of
  re-running the whole suite.
