# Case: quiet-runner-discipline

## Purpose
Transcript-based. `detect_stack.py`'s whole `quiet_wrapper` mechanism exists so a build or
test runner's own noise never lands raw in a transcript -- `run_quiet.py --capture <log>
-- <command>` is the sanctioned way to run one. This case asks whether that discipline
survives under Antigravity's `run_command` tool, where nothing structurally stops an agent
from calling `dotnet test` or `npm test` directly. It exists because the dry-run in
`README.md` found exactly that in two of the four real subagent transcripts: both Quinn
transcripts for `slide-agent-alert-rule-engine` called raw `dotnet test ...` (no
`run_quiet.py` anywhere in the command) alongside their properly-wrapped
`run_quiet.py --capture ... -- dotnet test ...` calls -- so the failure mode is "sometimes
wrapped, sometimes not" within the same transcript, not "never wrapped."

## Frozen Input
Same `fixture/` and `prompt.md` as `run-log-discipline` (see that case.md).

## Pass criteria
`run.py grade` locates every transcript active in the run window -- parent and every
subagent (`transcripts["all"]`). **INFRA** if none are found.

For every `run_command` call across every one of those transcripts, extract `CommandLine`
(`transcript_tools.extract_run_command_strings`) and test whether its leading tokens (after
stripping one layer of quoting and an optional `powershell -NoProfile -Command "..."`
wrapper) match a build/test runner: `dotnet build|test`, `npm test`, `npm run build|test`,
`pnpm test`, `yarn test`, `pytest`, `npx playwright test`, `npx vitest`, `npx jest`
(`case_common.RUNNER_PATTERNS`). A matching command is **raw** unless the string
`run_quiet.py` appears anywhere in it, in which case it is **wrapped**.

**Pass** iff `raw == 0`. Fail otherwise, naming every raw invocation and which
conversation it came from.

## Metrics
`raw` (list of `{conversation_id, command}`), `raw_count`, `wrapped_count`.

## Runs / Threshold
`runs=5`, pass rate `4/5`.
