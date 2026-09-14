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

`evals/run_suite.py --suite antigravity` (`evals/README.md`'s "Running any suite from
Antigravity" section) and `/bg-eval antigravity` (`skills/bg-eval/SKILL.md`) are the
one-command way to run these four cases without hand-pasting `prompt.md` — the
Orchestrator itself performs the case's lane prompt in a started workspace. This harness
(`run.py`, `cases/`, the manual paste-and-grade flow below) is unchanged by that; it is
what both paths ultimately grade with.

## How a run works

1. **Start.** `python run.py start --case <case> --workspace <dir>` copies
   `cases/<case>/fixture/` into a fresh `<dir>` and writes a start marker to
   `runs/<case>-<ts>.json` recording the UTC start time and the workspace path. `<dir>`
   must not already exist with files in it -- this is a frozen-fixture copy, not a merge.

   **In-place mode**, for running the eval from inside an Antigravity conversation that's
   already open on the plugin workspace (so it never has to reopen itself on another
   folder), and for running several cases in parallel without a human hand-copying fixtures:
   `python run.py start --in-place --case <case> [--root <dir>]` copies the fixture into
   `<root>/eval-runs/<case>-<ts>/` instead (default `--root`: cwd) and prints the same
   `STARTED`/marker/`Next` lines. `--in-place --all-cases [--root <dir>]` does this for
   every known case in one call, sharing one timestamp, and prints a `case | workspace |
   marker` table instead. Either way, refuses to overwrite an existing workspace, same as
   the explicit-`--workspace` form. **`eval-runs/` must be git-ignored by the consuming
   workspace** (it is disposable, per-run fixture-copy data, the same category as this
   harness's own `runs/`) -- add it to that workspace's own `.gitignore`; this harness does
   not touch a consuming workspace's `.gitignore` for you (this repository's own
   `.gitignore` already lists `eval-runs/` and `evals/antigravity/runs/`, so an in-place run
   from the plugin checkout itself needs nothing).
2. **Run it by hand.** Open `<dir>` in Antigravity, with the plugin installed and
   `AGENTS.md`'s runtime contract in force, and paste `cases/<case>/prompt.md` verbatim as
   your first message. Let it finish -- there is no way for this harness to drive
   Antigravity itself; a human has to be the one pasting the prompt and watching it
   converge, same as the reason `evals/README.md`'s own suite is `-Confirm`-gated rather
   than automatic. (Real transcripts show no Antigravity subagent has ever defined or
   invoked a subagent of its own, so when an eval orchestrator drives several `--all-cases`
   workspaces from one conversation, it runs each case's lane itself, in turn, against each
   fixture copy -- see "Attribution by workspace" below for how grading tells the resulting
   transcripts apart.)
3. **Grade.** `python run.py grade --run runs/<case>-<ts>.json [--record]`:
   - Computes a time window: `[started_at, <latest ts in the workspace's
     .docs/bugfix/*/run-log.jsonl or gates.jsonl, plus a 2-minute buffer>]`, or `now` if the
     workspace has no such artifact yet (`--end` overrides this).
   - Calls `transcript_tools.find_run_transcripts(window_start, window_end,
     workspace=<marker's workspace>)` to locate the parent (human-driven) conversation and
     every subagent conversation Antigravity spun up during that window **and attributed to
     this run's workspace** -- see "The transcript model" and "Attribution by workspace"
     below.
   - Runs `cases/<case>/grade.py`'s `grade(workspace, transcripts)`, which returns
     `{pass, metrics, failed_criterion}` or `{infra: True, infra_reason}`.
   - Prints the verdict, metrics, and a `SELF_INSPECTED` line (see "Self-contamination
     guard" below), updates the run marker with `graded_at`/`last_result` (`self_inspected`
     included), and, only with `--record`, appends one record to
     `evals/results/results.jsonl` via `eval_record.append_antigravity_record` (default OFF,
     same convention as the rest of the suite's zero-LLM `--record` flags -- see
     `evals/README.md`'s "Two suites" section); `self_inspected` rides along inside that
     record's `metrics` dict (`eval_record.py` itself was not touched -- see "Judgment
     calls").
   - `--case <other case>` grades this marker's workspace/transcripts with a **different**
     case's grader instead of the one it was started as -- the four case prompts are
     identical, so one Antigravity run can feed all four graders. The marker records
     `last_graded_as_case` when this diverges from how it was started.
   - `--all-runs <ts-or-glob>` grades every marker under `runs/` whose filename matches
     (a bare timestamp is wrapped `*<pattern>*`; anything with `*`/`?` is used as-is) and
     prints one `SUMMARY:` table (marker, case, outcome, pass, self_inspected) instead of
     one verdict block per marker crowding the tail of the output -- each marker is still
     graded (and, with `--record`, recorded) exactly as `--run` would.
4. Repeat 1-3 five times per case before reading a pass rate off it.

`python run.py list` prints known cases and every run marker with its graded status
(`[SELF-INSPECTED]` appended when that marker's last grade set the flag).
`python run.py --self-test` runs an offline suite against **synthetic** transcripts and
workspaces (never real ones) and exits 0 with an `OK` line, or non-zero naming which
assertion failed -- see "Self-test" below.

## Attribution by workspace (Part 2)

`find_run_transcripts`'s optional `workspace=` keyword (used by `grade` automatically; also
available on `transcript_tools.py`'s own `window --workspace` CLI) restricts every list it
returns to conversations that actually mention that workspace -- in a `USER_INPUT`, a
`tool_calls` arg, or a `content` field -- via `workspace_match_key`/
`text_mentions_workspace`/`conversation_mentions_workspace`. The match key is the
`eval-runs/<case>-<ts>` tail of the path when present (so a machine-prefix difference
between where `run.py` ran and where Antigravity recorded the path never breaks the match),
else the full normalized path (classic external `--workspace <dir>` runs). This is what lets
several `--all-cases` workspaces run from **one** Antigravity conversation without one
case's transcripts leaking into another's grade:

- The **parent** stays attributed to every case whose workspace its own
  `invoke_subagent`/`define_subagent` calls (or briefing text) mention -- one shared
  Orchestrator conversation is the parent for each case it drove, in turn.
- A **subagent** conversation belongs to whichever case's workspace its own briefing names;
  `skill-load-discipline` and `quiet-runner-discipline` re-check this themselves
  (`case_common`/`transcript_tools.conversation_mentions_workspace`) as defense in depth,
  in case a caller ever hands them an unfiltered `transcripts` dict directly.
- `round-bound` filters at the `invoke_subagent`-entry level, not just by conversation: a
  shared parent's invocations for a *different* case's workspace never inflate this case's
  per-(persona, unit) count.
- `quiet-runner-discipline` filters the **parent's own** `run_command` calls at the
  per-call level too (by `Cwd`/command text naming the workspace) -- a parent driving
  several cases can run raw/wrapped commands for each in the same conversation, and only
  the ones for THIS case's workspace should count toward it. A subagent conversation needs
  no such per-call check: attribution already scopes it to one case.

`workspace=None` (never passed by `grade`, available to a caller that wants the old
unscoped behavior) keeps every active-in-window conversation, exactly as before this
attribution existed.

## Self-contamination guard

Every `grade` also asks: did any transcript attributed to this run `view_file` this
harness's own `evals/antigravity/run.py` or an `evals/antigravity/cases/*/grade.py` **after**
the marker's `started_at`? If so, the run is still graded (never skipped), but flagged
`self_inspected: true` in the printed `SELF_INSPECTED:` line, the run marker's
`last_result`, `list`'s output, and (inside `metrics`) any `--record`ed result -- a run that
inspected the very grader that will judge it is a real signal worth keeping visible, not a
reason to throw the data point away.

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
  eval-runs/              (only under `--root` for `start --in-place`, default cwd) --
                          one fixture-copy workspace per in-place run, `<case>-<ts>/`;
                          disposable, must be git-ignored by the CONSUMING workspace
                          (this harness does not edit that workspace's .gitignore)
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
conversation with `define_subagent`/`invoke_subagent`/`run_command` calls for BOTH a case A
and a case B workspace -- the "one Orchestrator conversation, several cases" shape --,
three case-A subagent conversations for Quinn/Mason/Luna, one case-B subagent conversation
for a second Mason, one unrelated later human conversation to prove window filtering
excludes it) and two synthetic workspaces (`eval-runs/case-a-...`, `eval-runs/case-b-...`),
entirely under a temp directory -- **38 assertions** (test methods), none of them touching a
real transcript or the real `evals/results/results.jsonl`:

- `transcript_tools`: arg-unwrapping, path normalization across `\`/`/`, briefing
  detection, conversation listing, window-based parent/subagent discovery, `view_file`/
  `run_command`/`invoke_subagent` extraction, `workspace_match_key`'s `eval-runs/` tail vs.
  full-path fallback, `conversation_mentions_workspace`, and `find_run_transcripts`'s
  `workspace=` filter keeping case A's subagents out of case B's list and vice versa.
- `case_common`: raw-vs-wrapped runner detection, path-suffix normalization, skill-read
  classification, `Methodology Dependencies` table parsing (against the real
  `agents/mason.md` in this repo -- the one real-file dependency the self-test takes, since
  it is the thing being graded against, not a transcript).
- Each of the four graders' `grade()`, both a passing and a failing synthetic case
  (`run-log-discipline`: complete vs. missing-fields; `skill-load-discipline`: within vs.
  over the over-read limit; `quiet-runner-discipline`: raw vs. wrapped; `round-bound`:
  within vs. over the invocation limit, with and without a `check_redelegation.py` record)
  plus an INFRA case per grader (no artifact / no transcript), plus `round-bound` and
  `quiet-runner-discipline` each grading the shared two-case fixture once per workspace to
  prove their per-entry/per-call workspace split (not just conversation-level filtering).
- `run.py`'s own `start` -> `grade` CLI round trip (redirecting the module's `RUNS_DIR` to
  a temp dir for the duration, so the self-test never leaves a marker behind in the real
  `runs/`), `eval_record.append_antigravity_record`'s record shape, `grade --case` grading
  one marker's transcripts with a different case's grader, `grade --all-runs` batch-grading
  two markers into one summary, and `_check_self_inspection` on a synthetic transcript that
  views a grader file after/before the marker's start time.

Exits `0` and prints `SELF-TEST: 38/38 passed. OK` when every assertion holds.

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
- **`workspace_match_key` falls back to the FULL normalized path, not the workspace
  directory's bare basename**, when there is no `eval-runs/` tail -- a classic external
  `--workspace <dir>` run is referenced by its full absolute path in real transcripts (a
  human pastes the prompt into a conversation already rooted at that path), so the fuller
  key is the one that actually appears in the text; confirmed on the real
  `slide-agent-alert-rule-engine` run's parent transcript (471/830 steps mention
  `C:\Gorelo` in some form) during the dry run below.
- **`skill-load-discipline` and `quiet-runner-discipline` re-filter by workspace
  themselves**, even though `grade`'s call into `find_run_transcripts` already scopes
  `transcripts` to one workspace -- defense in depth for the case a caller (a future CLI
  path, or a grader's own `__main__` block) hands them a `transcripts` dict it built without
  the `workspace=` filter.
- **`self_inspected` rides inside `--record`'s `metrics` dict, not as a new top-level
  field on `eval_record.append_antigravity_record`** -- that function lives in
  `evals/eval_record.py`, outside this task's edit scope (`evals/antigravity/` only). The
  run marker's own `last_result.self_inspected` (written directly by `run.py`) is the
  authoritative field; the copy inside a recorded `metrics` dict is how it survives into
  `results.jsonl` without touching the shared file.
- **`--all-runs`'s pattern is glob-or-substring**: a bare timestamp like `20260914T101112Z`
  is wrapped to `*20260914T101112Z*` so it matches regardless of which case prefixes it;
  anything already containing `*`/`?` is used as a literal glob against `runs/*.json`
  filenames, for a caller that wants to be precise about which cases are included.
