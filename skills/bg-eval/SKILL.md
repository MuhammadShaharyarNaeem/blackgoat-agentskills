---
name: bg-eval
description: "Turns one sentence into a graded run of the evals/antigravity/ harness against the current plugin checkout, without hand-pasting a prompt into Antigravity: parses the case list, starts in-place fixture copies, performs each case's lane prompt as the Orchestrator itself, then grades and reports the verdict table. Trigger phrases: 'run the antigravity eval', 'run the antigravity evals', 'grade the antigravity eval', '/bg-eval'. Main-session only, Orchestrator-run."
trigger: /bg-eval
category: execution
risk: safe
---

# bg-eval — Antigravity Harness Runner

## Purpose
`evals/antigravity/README.md`'s own workflow assumes a human pastes each case's `prompt.md` into Antigravity by hand and grades the transcripts afterward. This skill runs the same cases without leaving the current session: it starts in-place fixture copies of the plugin checkout, has the Orchestrator perform each case's lane prompt directly, then grades and reports the same verdict table `grade --record` would produce. It exercises the plugin's own contract, not Antigravity's — a real gradable run either way.

## When to Use This Skill
- The user says "run the antigravity eval(s)", "grade the antigravity eval", or `/bg-eval`.
- **NOT** for `evals/`'s `contract/`/`trigger/` suites (`evals/README.md`) — those run headless `claude -p`, unrelated harness.
- **NOT** when the cwd is not a plugin checkout: refuse politely if `evals/antigravity/run.py` does not resolve from the cwd, naming the missing path.

---

## Worker Execution Contract

### Phase 0 — Parse
Parse `/bg-eval [antigravity] [<case>|all] [--parallel N]`. Default case set: `all` (`run-log-discipline`, `skill-load-discipline`, `quiet-runner-discipline`, `round-bound`). Default `--parallel` is 1 — one case's lane at a time. `--parallel N` runs up to N cases' lanes concurrently. Confirm `evals/antigravity/run.py` resolves before doing anything else (refusal above).

### Phase 1 — Start
Run `python evals/antigravity/run.py start --in-place --case <case>` per chosen case, or `--in-place --all-cases [--root <dir>]` once for the whole set. Read the printed table (case, workspace path, marker path) — do not guess a workspace path. `evals/antigravity/cases/<case>/prompt.md` is the lane brief for every case (all four are byte-identical: each targets the same `bgpdd-bugfix` run, and only the fixture and `grade.py` differ per case). State plainly that the Orchestrator now performs that prompt's instructions itself, with ONE substitution: everywhere the prompt says "this working copy", read the case's `eval-runs/<case>-<ts>/` folder from the table. Every path the lane touches — the fixture, `.docs/bugfix/...`, gate invocations (`--repo <that folder>`), the run log — lives under that folder, never the plugin checkout's own root.

### Phase 2 — Run the lane(s)
Perform the prompt exactly as `skills/bgpdd-bugfix/SKILL.md` directs: Quinn (RED), Mason and/or Nova (fix), Quinn (GREEN), Luna (review), delegated via this session's own delegation mechanism — native subagent delegation under Claude Code, or the `define_subagent` → `invoke_subagent` → `kill` lifecycle in `AGENTS.md` under Antigravity. Every worker's briefing MUST name its case's `eval-runs/<case>-<ts>/` folder — the harness attributes transcripts by that path. Run autonomously, no check-in: the prompt itself says not to ask and to take the FAST route where the lane's own routing allows it — **refining Orchestrator Contract §1's phase-transition confirmation, deliberately (convention #8)**, the same exception `bgpdd-quick` already takes for its own single-session run.

In `--parallel` mode, launch independent cases' delegations in one message; keep every path case-scoped and never share a `.docs` root between cases — **lighter than `bgpdd-bugfix-batch`'s git-worktree isolation, deliberately (convention #8)**: these are throwaway fixture copies, not live branches sharing a merge queue.

Two prohibitions:
- Do not open `evals/antigravity/cases/*/grade.py` or `evals/antigravity/run.py`'s own source after `start`, until `grade` has run — the harness records a `self_inspected` flag and taints the run.
- Do not write anything under `evals/antigravity/runs/` or `evals/results/` by hand.

### Phase 3 — Grade
Run `python evals/antigravity/run.py grade --all-runs <this batch's ts pattern> --record`, or per marker with `--case <case> --record` when only one case ran. Paste the verdict table verbatim to the user, with a one-line reading of each FAIL, the INFRA count, and the reminder that one run is one of five (`evals/README.md`'s `runs=5`, 4/5 threshold) — a single run proves nothing on its own.

### Escalation
A lane that halts (a blocker-halt gate, `check_redelegation.py`) ends **that case's** run as FAIL-by-halt with the halt reason pasted verbatim; the other cases in the batch continue. A case whose `start` or `grade` invocation errors is reported to the user as INFRA for that run, not silently retried.

## Limitations
Only `run-log-discipline`'s grader is artifact-only (`.docs/bugfix/.../run-log.jsonl`). `skill-load-discipline`, `quiet-runner-discipline`, and `round-bound` grade Antigravity's own conversation transcripts under `~/.gemini/antigravity/brain/` (`evals/antigravity/README.md`'s "transcript model"), so they yield a real verdict only when this skill runs **under Antigravity**. A lane performed under Claude Code writes none of those transcripts, and those three cases then grade `INFRA` ("no transcripts found") — report that plainly rather than as a pass/fail data point, and re-run under Antigravity when a real verdict is needed.
