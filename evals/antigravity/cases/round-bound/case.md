# Case: round-bound

## Purpose
Transcript-based. The Antigravity runtime contract (`AGENTS.md`) makes every delegation a
fresh `define_subagent`/`invoke_subagent` pair rather than one bounded Task-tool call, which
removes whatever implicit ceiling a single-process subagent model puts on how many times the
Orchestrator can re-invoke the same persona on the same unit of work before it should stop
and escalate instead. `check_redelegation.py` (referenced by `check_handoff.py` and
`update_state.py` today, landing in this same wave per the parent task) is meant to be that
ceiling's mechanical gate. This case asks whether an Antigravity run actually stays under it
-- counting `invoke_subagent` calls per (persona, unit) in the parent transcript -- while
grading the escape hatch only by the gate record's *name* existing in `gates.jsonl`, since
the gate script itself is not yet shipped as of this case's authoring.

## Frozen Input
Same `fixture/` and `prompt.md` as `run-log-discipline` (see that case.md) -- a
single-bug run, so "unit" in practice resolves to one `.docs/bugfix/<slug>/` for the whole
run unless a briefing names a different one.

## Pass criteria
`run.py grade` locates the run's parent (orchestrator) transcript. **INFRA** if none is
found in the run window.

Read every `invoke_subagent` call in the parent transcript
(`transcript_tools.extract_invoke_subagent_calls`; falls back to a regex recovery of each
`"You are <Name>, ..."` briefing opener when the call's `Subagents` argument isn't valid
JSON -- observed on real transcripts, see `transcript_tools.py`'s
`_recover_subagents_prompts` docstring). For each subagent entry inside each call:
- **persona** = the name in its own `"You are <Name>, ..."` opener.
- **unit** = the bug-slug named in a `.docs/bugfix/<slug>/` (or `.docs/<slug>/`) mention in
  that same briefing text, else `"run"` (the whole run is one unit).

Count invocations per `(persona, unit)`. A count `> 2` is over the bound **unless**
`gates.jsonl` under any `.docs/bugfix/<slug>/` in the workspace carries at least one record
with `"gate": "check_redelegation.py"` -- graded against that record's presence by name
only, per the parent task's explicit instruction, since the gate script itself does not
exist yet to check anything more specific about it.

**Pass** iff no `(persona, unit)` exceeds 2, or a `check_redelegation.py` record exists
anywhere in the workspace's gate ledgers.

## Metrics
`invocations_per_persona` (persona -> unit -> count), `over_limit` (the offending
`persona@unit` keys and their counts), `has_redelegation_record`.

## Runs / Threshold
`runs=5`, pass rate `4/5`.
