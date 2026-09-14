# Case: skill-load-discipline

## Purpose
Transcript-based. Every persona's `agents/<name>.md` carries a `## Methodology
Dependencies` table naming which `skills/*/SKILL.md` files it must read and when
(`Always`, or a stack trigger `detect_stack.py` resolves). Under Claude Code that
contract is enforced by convention only; this case asks whether it survives translation
into Antigravity's `define_subagent`/`invoke_subagent` model, where each subagent is a
brand-new conversation that has to `view_file` its own dependencies from scratch with no
memory of the parent's context. It exists because the dry-run in `README.md` found real
subagent transcripts (the same four 2026-09-08 - 09-14 runs) that read their `Always` rows
inconsistently -- Luna read both her `Always` rows, Mason read one of two, one Quinn
transcript read zero -- while never over-reading. A grader that only checked "did it read
*something* plausible" would have missed that gap entirely.

## Frozen Input
Same `fixture/` and `prompt.md` as `run-log-discipline` (see that case.md) -- this case
grades a different axis of the same kind of `/bgpdd-bugfix` run, not a different run.

## Pass criteria
`run.py grade` locates the run's subagent transcripts (`transcript_tools.find_run_transcripts`).
**INFRA** if none are found in the run window.

For each subagent transcript:
1. Read its persona off the briefing's `"You are <Name>, ..."` opener
   (`transcript_tools.briefing_persona`).
2. Collect every `view_file` call whose path is a `skills/<name>/SKILL.md` or
   `skills/agent-squad/base-persona.md` read (`case_common.is_skill_read` -- path compared
   by its `skills/...`-relative suffix, since an absolute path never matches across
   machines).
3. Derive the expected set from `agents/<persona>.md`'s Methodology Dependencies table:
   every `Always` row, plus every row whose trigger names a stack `detect_stack.py --repo
   <workspace> --json` actually reports (matched through `detect_stack.py`'s own
   `SKILL_MAP`, imported directly so this can't drift from it).
4. `over_reads = reads - expected`; `misses = (Always rows only) - reads`.

**Pass** iff every subagent transcript has `len(over_reads) <= 1`. `misses` is a metric
only -- a stack-triggered row not firing, or even an `Always` row not read, does not fail
this case; it is exactly the kind of drift the metric exists to surface without making the
case red on day one, when the real dry-run data already shows every transcript passing
this bar while missing most of its `Always` rows.

## Metrics
`per_subagent`: for each subagent conversation, `{persona, reads, expected, over_reads,
misses}`.

## Runs / Threshold
`runs=5`, pass rate `4/5`.
