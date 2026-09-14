# Case: run-log-discipline

## Purpose
Artifact-only. `skills/pipeline-tools/scripts/record_run.py`'s whole contract is that a
delegation record is never silently missing a headline field -- see that file's own
"TOKENS ARE MANDATORY ON A DELEGATION RECORD" and the `--tier` inversion-check sections.
This case asks nothing about the Antigravity transcript at all: it asks whether the
`/bgpdd-bugfix` lane, run under Antigravity/Gemini, actually left a `run-log.jsonl` behind
that honours that contract for each agent it delegated to. It exists because the first
four real bugfix runs under this runtime (2026-09-08 - 09-14, `C:\Gorelo\.docs\bugfix\`)
were captured **before** `record_run.py`'s `--runtime`/token-mandatory rules existed, and
every one of their `run-log.jsonl` delegation records carries `runtime: null` and every
token field `null` with no `tokens_unavailable` -- see the dry-run table in
`evals/antigravity/README.md` for the exact numbers. This case is what should catch that
regression the next time it happens.

## Frozen Input
- Fixture dir: `fixture/` -- byte-identical copy of
  `evals/contract/bgpdd-bugfix-lane/fixture/` (the zero-dependency `orders-svc` Node
  service; see that case's `case.md` for the full defect description). Reused rather than
  rewritten because the fixture's job here is unchanged: give the lane a real, reproducible
  bug to fix, nothing about *this* case depends on which bug it is.
- Prompt: `prompt.md` -- pasted verbatim into a fresh Antigravity conversation opened on
  the workspace `run.py start` produced. Supplies only what a user supplies (observed /
  expected behaviour, the verbatim error, one reproduction command, the environment) and
  names no artifact, gate, flag or root cause -- same discipline as the Claude contract
  case's prompt.

## Pass criteria
Glob `.docs/bugfix/*/run-log.jsonl` under the graded workspace (the lane picks its own
bug-slug). **INFRA** if no `bug-report.md` exists anywhere under `.docs/bugfix/`, or a
`bug-report.md` exists with no `run-log.jsonl` beside it.

Otherwise, read every `event: "delegation"` record and require:
1. **quinn, mason and luna all appear** as an `agent` on at least one delegation record.
2. Every delegation record carries a non-null `model`.
3. Every delegation record carries a non-null `tier`.
4. Every delegation record carries `tokens_total`, or both `tokens_in` and `tokens_out`, or
   a non-empty `tokens_unavailable`.
5. Every delegation record carries a non-null, non-empty `runtime`.
6. If `runtime` names a non-Claude runtime (anything other than `"claude"` /
   `"claude-code"` / `"anthropic"` -- in practice `"antigravity"`), `model` must not be one
   of `record_run.py`'s resolvable Claude tier names (`inherit`, `sonnet`, `opus`, `haiku`,
   `fable`), case-insensitively. A record with no `runtime` at all is not checked against
   this rule (the "unless the run really used Claude" exception in this case's own
   parent-task spec) -- criterion 5 already fails it on the missing-`runtime` rule alone.

**Pass** iff all six hold across every delegation record. **Fail** otherwise, naming which
criterion and which record(s).

## Metrics
`records` (delegation record count), `agents_seen`, `missing_required_agents`,
`missing_fields` (one entry per record that failed any of criteria 2-6, naming which).

## Runs / Threshold
`runs=5`, pass rate `4/5` -- same statistical doctrine as the rest of the suite (see
`evals/README.md`). Not a zero-LLM case: the lane's own routing and delegation behaviour
varies run to run.
