# Antigravity Eval Harness

Companion to `evals/README.md`'s contract/trigger suites, for the runtime that suite
cannot reach: `claude -p` has no equivalent on Google Antigravity, which is where the user
actually runs `/bgpdd-bugfix` and `/bgpdd-quick` day to day (Gemini 3.8 Flash). What's on
disk after an Antigravity run is (1) the workspace's own artifacts -- `.docs/...`,
`run-log.jsonl`, `gates.jsonl`, evidence captures -- and (2) Antigravity's own
conversation transcripts under `~/.gemini/antigravity/brain/<conversation-id>/`. This
harness is a frozen fixture + a prompt the user pastes into Antigravity by hand + a Python
grader that reads both of those back. Same statistical philosophy as `evals/README.md`:
`runs=5`, judged on a 4/5 pass rate, and a run that produced no evidence to grade is
**INFRA**, not a data point.

## How a run works

1. **Start.** `python run.py start --case <case> --workspace <dir>` copies
   `cases/<case>/fixture/` into a fresh `<dir>` and writes a start marker to
   `runs/<case>-<ts>.json` recording the UTC start time and the workspace path. `<dir>`
   must not already exist with files in it -- this is a frozen-fixture copy, not a merge.
2. **Run it by hand.** Open `<dir>` in Antigravity, with the plugin installed and
   `AGENTS.md`'s runtime contract in force, and paste `cases/<case>/prompt.md` verbatim as
   your first message. Let it finish -- there is no way for this harness to drive
   Antigravity itself; a human has to be the one pasting the prompt and watching it
   converge, same as the reason `evals/README.md`'s own suite is `-Confirm`-gated rather
   than automatic.
3. **Grade.** `python run.py grade --run runs/<case>-<ts>.json [--record]`:
   - Computes a time window: `[started_at, <latest ts in the workspace's
     .docs/bugfix/*/run-log.jsonl or gates.jsonl, plus a 2-minute buffer>]`, or `now` if the
     workspace has no such artifact yet (`--end` overrides this).
   - Calls `transcript_tools.find_run_transcripts(window_start, window_end)` to locate the
     parent (human-driven) conversation and every subagent conversation Antigravity spun up
     during that window -- see "The transcript model" below for what that split actually
     looks like on a real run.
   - Runs `cases/<case>/grade.py`'s `grade(workspace, transcripts)`, which returns
     `{pass, metrics, failed_criterion}` or `{infra: True, infra_reason}`.
   - Prints the verdict and metrics, updates the run marker with `graded_at`/`last_result`,
     and, only with `--record`, appends one record to `evals/results/results.jsonl` via
     `eval_record.append_antigravity_record` (default OFF, same convention as the rest of
     the suite's zero-LLM `--record` flags -- see `evals/README.md`'s "Two suites" section).
4. Repeat 1-3 five times per case before reading a pass rate off it.

`python run.py list` prints known cases and every run marker with its graded status.
`python run.py --self-test` runs an offline suite against **synthetic** transcripts and
workspaces (never real ones) and exits 0 with an `OK` line, or non-zero naming which
assertion failed -- see "Self-test" below.

## The transcript model (Part 1 finding)

**Subagent work under Antigravity lives in a completely separate conversation directory,
never as inline turns inside the parent's own transcript.** Confirmed against a real run
(`slide-agent-alert-rule-engine`, 2026-09-14, `C:\Gorelo\.docs\bugfix\slide-agent-alert-rule-engine\`):

- The parent conversation (`086ffb6a-08b2-4dbc-98d7-52e32812d196`, first step
  `2026-09-14T09:55:21Z`, spanning the whole day) contains `define_subagent` and
  `invoke_subagent` tool calls, but **none of the actual subagent work** -- no `view_file`
  reads of `agents/quinn.md`, no `dotnet test` runs, nothing. Its own `invoke_subagent`
  calls in this run's window:

  | `created_at` | Briefing opener |
  |---|---|
  | `10:09:08Z` | "You are Quinn, the QA Tester." |
  | `10:13:46Z` | "You are Mason, the Backend Builder." |
  | `10:19:07Z` | "You are Quinn, the QA Tester." |
  | `10:23:02Z` | "You are Luna, the Code Reviewer." |

- Each of those four has a **separate conversation directory**, created within seconds of
  the matching `invoke_subagent` call, whose own first `USER_INPUT` step is that exact
  briefing text (not a human message):

  | Conversation dir | First step | Last step | Briefing |
  |---|---|---|---|
  | `22c55891-9e69-40ad-ad2a-5346f136825a` | `10:09:16Z` | `10:11:38Z` | Quinn (RED) |
  | `ac33a832-7a7e-4611-ba33-191e23153d1d` | `10:13:54Z` | `10:18:25Z` | Mason (fix) |
  | `b8caa708-c38a-4faf-85f2-a72a246de4a1` | `10:19:17Z` | `10:21:27Z` | Quinn (GREEN) |
  | `5bc1bc81-f24d-4294-9505-d95cb7d7dff9` | `10:23:09Z` | `10:25:23Z` | Luna (review) |

  Each of these four contains the actual work: Quinn's `view_file` on `agents/quinn.md`,
  `dotnet test` / `run_quiet.py` calls, `git diff`; Mason's edit to
  `SlideAgentPairedNotificationHandler`; Luna's read of `check_commit_gate.py`. This lines
  up with the run's own `run-log.jsonl` (four `event: "delegation"` records at `10:12:44Z`,
  `10:18:51Z`, `10:22:10Z`, `10:25:46Z` -- each a few seconds after the matching subagent
  conversation's last step, i.e. logged right after that subagent finished).

  The parent's remaining `invoke_subagent` calls that day (`12:58:22Z`, `13:05:28Z`,
  `13:12:40Z`) belong to a *different* later conversation in the same day-long parent
  transcript, not this run -- which is exactly why `find_run_transcripts` filters by time
  window rather than by conversation identity alone.

`find_run_transcripts(window_start, window_end)` implements this: it finds every
conversation active in the window, keeps the one that *spans* the whole window and is not
itself a briefing as `parent`, and keeps every other one whose first `USER_INPUT` reads as
a briefing (`"You are <Name>, the <Role>...`) as a `subagent`. A conversation active in the
window that is neither (e.g. an unrelated human aside) is left out of both, but still
returned in `"all"`.

## Files

```
evals/antigravity/
  README.md              this file
  transcript_tools.py     read-only Antigravity transcript parsing (Part 1)
  case_common.py          shared grader helpers (methodology-table parsing, runner
                           regexes, path-suffix normalization, detect_stack.py wiring)
  run.py                  the CLI: start / grade / list / --self-test
  runs/                   start markers, one per run (git-ignored data, not fixtures)
  cases/<name>/
    case.md               purpose, frozen input, pass criteria, metrics, runs/threshold
    prompt.md              exact text pasted into Antigravity
    fixture/               frozen input files (copy of evals/contract/bgpdd-bugfix-lane/fixture/)
    grade.py               grade(workspace, transcripts) -> {pass, metrics, failed_criterion}
                            or {infra: True, infra_reason}; never raises on a missing
                            transcript or artifact
```

Four cases, all against the same kind of `/bgpdd-bugfix` run (same fixture, same prompt)
but grading a different axis of it -- see each `case.md` for the full criterion:

- **`run-log-discipline`** -- artifact-only. `run-log.jsonl`'s delegation records carry a
  real `model`, `tier`, token figures (or an honest `tokens_unavailable`), and `runtime`.
- **`skill-load-discipline`** -- transcript-based. Each subagent's `SKILL.md` reads against
  its persona's `Methodology Dependencies` table (`Always` rows + `detect_stack.py`-matched
  stack rows). Over-reads gate the case; misses are metric-only.
- **`quiet-runner-discipline`** -- transcript-based. Every raw build/test runner
  `run_command` call must be wrapped in `run_quiet.py`.
- **`round-bound`** -- transcript-based. No persona invoked more than twice on one unit
  without a `check_redelegation.py` gate record.

## Result record shape

`eval_record.append_antigravity_record` (added to `evals/eval_record.py`, additive only --
see that file's docstring) writes to the same `evals/results/results.jsonl` the rest of the
suite uses, with every field `append_script_record` writes plus two new ones: `runtime`
(`"antigravity"`) and `model` (`"gemini-3.8-flash"`). `judge` is `"harness"` -- distinct
from `"tool_use"` (a `claude -p` trigger run) and `"script"` (a zero-LLM contract case) --
so a reader computing a pass rate must group by `(case, judge)`, never mix `judge:
"harness"` rows into a `judge: "tool_use"`/`"script"` case's rate. `run-evals.ps1` never
reads `runtime`/`judge: "harness"`, so its own pooling for contract/trigger cases is
unaffected; no antigravity case name collides with an existing contract/trigger case name
today. `case_sha256` hashes the case's `case.md` (there is no zero-LLM `run.py` here to
hash instead).

## Self-test

`python run.py --self-test` builds a small synthetic Antigravity brain root (one parent
conversation with `define_subagent`/`invoke_subagent`/`run_command` calls, three subagent
conversations for Quinn/Mason/Luna with `view_file` calls, one unrelated later human
conversation to prove window filtering excludes it) and a synthetic workspace, entirely
under a temp directory -- **28 assertions**, none of them touching a real transcript or the
real `evals/results/results.jsonl`:

- `transcript_tools`: arg-unwrapping, path normalization across `\`/`/`, briefing
  detection, conversation listing, window-based parent/subagent discovery, `view_file`/
  `run_command`/`invoke_subagent` extraction.
- `case_common`: raw-vs-wrapped runner detection, path-suffix normalization, skill-read
  classification, `Methodology Dependencies` table parsing (against the real
  `agents/mason.md` in this repo -- the one real-file dependency the self-test takes, since
  it is the thing being graded against, not a transcript).
- Each of the four graders' `grade()`, both a passing and a failing synthetic case
  (`run-log-discipline`: complete vs. missing-fields; `skill-load-discipline`: within vs.
  over the over-read limit; `quiet-runner-discipline`: raw vs. wrapped; `round-bound`:
  within vs. over the invocation limit, with and without a `check_redelegation.py` record)
  plus an INFRA case per grader (no artifact / no transcript).
- `run.py`'s own `start` -> `grade` CLI round trip (redirecting the module's `RUNS_DIR` to
  a temp dir for the duration, so the self-test never leaves a marker behind in the real
  `runs/`), and `eval_record.append_antigravity_record`'s record shape.

Exits `0` and prints `SELF-TEST: 28/28 passed. OK` when every assertion holds.

## Judgment calls

- **Window end** defaults to the latest `ts` across the workspace's `run-log.jsonl`/
  `gates.jsonl` plus a 2-minute buffer, not "now" -- a human may sit with the finished
  Antigravity conversation open for a while before running `grade`, and using wall-clock
  "now" would pull in whatever the user does in that same conversation afterward.
- **`Subagents` JSON is not always valid JSON on real transcripts.** Real data (this run's
  own parent transcript) embeds literal control characters and, in some calls, unescaped
  quotes inside a briefing's `Prompt` text, breaking a strict `json.loads`. `strict=False`
  fixes the control-character case; a regex-based recovery
  (`transcript_tools._recover_subagents_prompts`) handles the rest by re-splitting on each
  `"You are <Name>, ..."` opener found in the raw text. This is enough for `round-bound`
  (persona + unit-slug text), not a faithful reconstruction of the original call.
- **Path comparison is always by `skills/...`-relative suffix, never by absolute path.**
  Every `view_file` path a real transcript records is on the *user's* machine (their
  plugin install location); this repo's own absolute path never matches it byte for byte.
- **Expected-skill-read stacks are derived by literally importing `detect_stack.py`'s
  `SKILL_MAP`**, not by re-typing the stack->skill mapping in `case_common.py`, so the two
  can't drift apart the way `judge: "substring"` and the harness that wrote it did (see
  `evals/README.md`'s "Known invalid results").
- **`round-bound`'s escape hatch is graded by gate-record name only**, per the task: the
  parent task's own wave has not yet shipped `check_redelegation.py`, so there is nothing
  more specific to check about that record today.
- **What the transcript cannot tell us, stated explicitly: there is no token usage
  anywhere in an Antigravity transcript.** Duration and tool-call counts are the only cost
  proxies available, which is exactly why `run-log-discipline` requires a `tokens_total`
  figure OR an honest `tokens_unavailable` string, never a bare null -- a run that can't
  measure tokens has to say so, not omit the field.
