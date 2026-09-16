---
name: bg-eval
description: "Turns one sentence into a graded run of any evals/ suite — antigravity, contract, trigger, or outcome — against the current plugin checkout: parses the case list, starts in-place workspaces via evals/run_suite.py, performs each case's prompt itself (by kind: lane, persona, or bare trigger prompt), then grades and reports the verdict tables. Trigger phrases: 'run the antigravity eval', 'run the antigravity evals', 'grade the antigravity eval', 'run the evals', 'run all the evals', 'run the eval suite', 'run the contract/trigger/outcome evals', 'run the evals headless', 'run the evals on agy', 'run the evals with the claude cli', '/bg-eval'. Main-session only, Orchestrator-run."
trigger: /bg-eval
category: execution
risk: safe
---

# bg-eval — Eval Suite Runner

## Purpose
Every suite under `evals/` assumes a human either pastes a prompt into Antigravity by hand (`evals/antigravity/`) or spends real tokens on a headless `claude -p` batch (`evals/README.md`'s `run-evals.ps1`, `evals/outcome/run-outcome.ps1`). This skill drives a third, cheaper path — `evals/run_suite.py` — that starts a real workspace per case and lets the Orchestrator itself perform the prompt, in this session, then grades from the same artifacts a headless run leaves. It is not a substitute for the cost-gated headless batches; it exercises the plugin's own contract through this session's own execution.

## When to Use This Skill
- "run the antigravity eval(s)", "grade the antigravity eval", "run the evals", "run all the evals", "run the eval suite", "run the contract/trigger/outcome evals", or `/bg-eval`.
- **NOT** `evals/run-evals.ps1` or `evals/outcome/run-outcome.ps1`'s own headless `-Confirm` batches, and **NOT** the four zero-LLM contract cases (`mechanical-pipeline` and its three siblings), which run directly as `python run.py --record` — unrelated, cost-gated harnesses this skill does not touch.
- **NOT** when the cwd is not a plugin checkout: refuse politely if `evals/run_suite.py` does not resolve, naming the missing path.

---

## Worker Execution Contract

### Phase 0 — Parse
Parse `/bg-eval [antigravity|contract|trigger|outcome|all] [<case>|all] [--parallel N] [--runtime agy|claude [--runs N] [--model <name>]]`. Suite defaults to `antigravity` (back-compatible with this skill's original trigger phrases); `all` runs all four suites, each through its own Start → Run → Grade cycle, or a headless `run` call under `--runtime` (Phase 1H). Case defaults to `all`. `--parallel` defaults to 1; unused under `--runtime`. Confirm `evals/run_suite.py` resolves before doing anything else (refusal above).

### Phase 1H — Headless (`--runtime` given)
Collapses Phases 1-3 into one call per suite, deliberately refining (convention #8) Phase 2's own prompt-performing/delegation rule: the run starts, invokes, grades and records itself, so the Orchestrator performs no prompt and delegates nothing. Per selected suite: `python evals/run_suite.py run --runtime <R> --suite <S> (--case <case>|--all-cases) --runs <N> [--model <M>] --record`. `outcome` runs too, plugin arm only (see Limitations). Paste each SUMMARY table verbatim and read out the INFRA count and the one-of-N reminder (`runs=5`, 4/5).

### Phase 1 — Start
For each selected suite, once: `python evals/run_suite.py start --suite <S> --in-place (--case <case>|--all-cases)`. Read the printed `suite | case | workspace | marker` table — never guess a workspace path. Note, per case, whether a `Reply capture:` line followed its prompt block — that decides part of Phase 2. Contract cases arrive with their own git history already prefixed and outcome workspaces are already git repos at a `base` commit; the Orchestrator does not set either up.

### Phase 2 — Run, by prompt kind
This is the heart of the lane. Every path a worker touches — fixture, `.docs/...`, a gate's `--repo`, a run log — must be scoped to that case's workspace; a briefing that omits the path is a wiring bug, not a judgeable run.

- **Lane prompts** ("Act as the Orchestrator. Run the `<lane>` lane ... in this working copy"), **outcome tasks**, and **antigravity cases**: the Orchestrator takes the prompt itself as the entry point, substituting "this working copy" with that case's workspace; it delegates within it exactly as the lane directs (Quinn, Mason/Nova, Luna for `bgpdd-bugfix`), and for an outcome task whether it routes into a lane at all is its own decision, as it would be for a user asking. Run autonomously, no check-in, FAST route where the lane's own routing allows — refining Orchestrator Contract §1's phase-transition confirmation, deliberately (convention #8), the same exception `bgpdd-quick` takes for its own single-session run.
- **Persona prompts** ("Act as `<Name>` per `agents/<name>.md` ..."): delegate exactly one worker whose briefing is that prompt verbatim, plus "Your working copy is `<workspace>`; every relative path in the prompt resolves there." Nothing else — no lane, no added rules; the persona's own compliance is what is graded. When Phase 1 printed a `Reply capture:` line for this case, save the worker's final reply verbatim — the whole `<handoff>` element included — to `<workspace>/handoff.txt`. This is the ONLY file the Orchestrator may hand-write into a workspace.
- **Trigger prompts** (suite `trigger`): delegate one FRESH worker whose briefing is ONLY the bare prompt plus "Your working copy is `<workspace>`." — no persona, no lane name, no mention of skills, plugins, or evals. What's graded is which `skills/<name>/SKILL.md` that worker opens first, so the Orchestrator must not read any SKILL.md on the worker's behalf or hint at one. Deliberately refining (convention #8) `agent-squad/SKILL.md` §4's briefing format, which normally opens `BRIEFING FOR [AGENT NAME]` and names the persona — here the persona is exactly what must not be named.
- **`--parallel N`**: launch up to N cases' delegations in one message, each with its own workspace and never a shared `.docs` root — lighter than `bgpdd-bugfix-batch`'s git-worktree isolation, deliberately (convention #8): these are throwaway fixture copies, not live branches sharing a merge queue.

Delegation uses this session's own mechanism — native subagent delegation under Claude Code, or synchronous invocation of the registered squad agents under Antigravity (the runtime contract in the user's global Antigravity rules).

### Phase 3 — Grade
Per suite that ran: `python evals/run_suite.py grade --all-runs <this batch's ts> --record`. Paste each SUMMARY table verbatim, with a one-line reading of each FAIL, the INFRA count, and the reminder that one run is one of five (`evals/README.md`'s `runs=5`, 4/5 threshold) — a single run proves nothing on its own.

### Escalation
A lane that halts (a blocker-halt gate, `check_redelegation.py`) ends **that case's** run as FAIL-by-halt with the halt reason pasted verbatim; the rest of the batch continues. A `start` or `grade` invocation that errors is reported to the user as INFRA for that run, never silently retried.

## Prohibitions
After a suite's `start` and until its `grade` has run: do not open `evals/run_suite.py`, `evals/antigravity/run.py`, any `grade.ps1`, `outcome.ps1`, `grade.py`, a `hidden/` directory, or `cases.jsonl`. Never hand-write under `evals/runs/`, `evals/antigravity/runs/`, `evals/results/`, `evals/outcome/results/`, or a workspace, except `handoff.txt` as above.

## Limitations
- **Headless `agy` skips permissions by default** (`--dangerously-skip-permissions`, off with `--no-skip-permissions`) — otherwise every tool is auto-denied (`jetski: no output produced`), which grades INFRA and never counts toward `--runs`.
- **Headless runs are sequential, never parallel.** Preflight prints the installed plugin; records carry its sha.
- **A headless run that leaves its workspace grades INFRA `left_workspace`, never a verdict.**
- **Outcome runs the plugin arm only; the baseline arm needs the runtime's plugin disabled and stays on `run-outcome.ps1`** — see `evals/outcome/README.md`. Under `--runtime claude`, `no_unbacked_claim` is excluded (`pass: null`) — no Antigravity transcript exists.
- **The four zero-LLM contract cases are not started here** — see "When to Use" above.
- **Transcript-judged verdicts grade INFRA under Claude Code.** Trigger's routing judge, antigravity's three transcript-based cases (`skill-load-discipline`, `quiet-runner-discipline`, `round-bound`), and outcome's `no_unbacked_claim` all read Antigravity's own conversation transcripts under `~/.gemini/antigravity/brain/` — a lane performed under Claude Code writes none of those, so `grade` reports `INFRA` ("no transcripts found") for those cases. Report that plainly, as a limitation of the runtime this session is in, not a pass/fail data point; re-run under Antigravity for a real verdict. Antigravity's `run-log-discipline` and contract's own artifact-graded cases are unaffected — they grade from workspace files, not transcripts.
