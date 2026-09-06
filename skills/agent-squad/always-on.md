# Blackgoat — Always-On Index

Injected at session start so an ordinary chat — one that never types a lane command — still knows this plugin exists, what each lane is for, and which rules hold when no lane is running. It is an **index, not a contract**: it restates no rule and owns none. Every entry names the file that owns it; read that file before acting on it. Paths are relative to the plugin root (the framing line around this text carries the resolved root). The full model lives in `skills/agent-squad/SKILL.md` (roster, routing triggers, briefing and relay formats), `skills/agent-squad/orchestrator-contract.md` (the Orchestrator's cross-cutting rules) and `skills/agent-squad/base-persona.md` (every subagent's).

## The lanes

Pick one and invoke it. Each line is that lane's own `description` frontmatter, trimmed.

| Lane | What it is for |
|---|---|
| `/bg` | Front door: classifies the request and invokes exactly one lane below. Routes only; never does the work. |
| `/bgpdd-quick` | One small contained change, main session only: no delegation, no plan. One captured check, one close gate that commits. |
| `/bgpdd-bugfix` | A localized bug fixed on written evidence: bug report, RED capture, routed fix, GREEN re-run, review, commit gate. |
| `/bgpdd-lite` | Mid-weight PDD for well-specified work: mini-requirements with you, Alex plans, coverage gate, then `/bgpdd-build`. |
| `/bgpdd-plan` | Phase 1, Design & Architecture: refines the idea, researches, produces an implementation plan (Rex, Aria, Alex). |
| `/bgpdd-discovery` | Phase 0, Global Context Discovery: Iris, Scout and Echo map stacks, APIs and the legacy QA baseline. |
| `/bgpdd-build` | Phase 2, Execution: takes an existing plan and executes it (Mason, Nova, Quinn, Luna, Dep, Cipher). |
| `/bgpdd-verify` | Standalone verification of an already-discovered feature: acceptance matrix, executed specs, gated on runtime evidence. |
| `/bgpdd-shipping` | Phase 3, Verification & Deployment: the Launch Squad runs the pre-launch checklist, hardening and rollout. |
| `/bgpdd-learn` | Captures this session's lessons and routes each to a rules file, a persona or a skill, via Forge. |

## Outside any lane

Four rules bind in ordinary chat too, with no pipeline running. Each names its owner — the owner is authoritative, this line is only the pointer.

1. **Evidence over claims.** A verification you did not perform is `BLOCKED`, never `PASS`; evidence cites the executed command and its output, and "verified" is an adjective, not evidence. Owner: `skills/agent-squad/base-persona.md` § Evidence Integrity.
2. **Never edit a test to make it pass.** A red test is a finding about the code, not an obstacle in front of it: fix the code, or report the test as wrong and say why. Weakening an assertion, deleting a case, or loosening a gate to reach green is the defect the RED/GREEN discipline exists to catch. Owner: `skills/test-driven-development/SKILL.md`.
3. **A commit goes through a gate.** Inside a lane the lane's gate commits (`check_commit_gate.py`, or `check_quick_close.py` for `/bgpdd-quick`) — a verdict, a clean-tree check and a size bound, run rather than asserted. Outside any lane, the smallest gated path for a change is `/bgpdd-quick`; a hand commit is the user's call, made knowingly. Owner: `skills/pipeline-tools/SKILL.md`.
4. **Ask before anything irreversible.** Phase transitions, force-pushes, deletes, deploys, schema changes and anything the user cannot undo need explicit confirmation first; interactive steps run in the main session and are never delegated. Owner: `skills/agent-squad/orchestrator-contract.md` § 1.

**Some of these are enforced, not only stated.** Under Claude Code this plugin registers a `PreToolUse` hook that can refuse a tool call *before* it runs: a hand `git commit`/`merge`/`cherry-pick`/`revert` while a lane is active (rule 3 above), a write to an existing test file during an unfinished bugfix (rule 2 above), a delegation before the bugfix intake gate, and any hand edit to `gates.jsonl`, `orchestrator-state.json`, `run-log.jsonl` or a `*.meta.json` sidecar. It detects the lane from the working tree, names the gate to run instead, and fails open on any error — so a refusal is always a positive finding, never a malfunction. `python skills/pipeline-tools/scripts/guard_action.py --explain` shows what it currently detects. Owner: `skills/pipeline-tools/SKILL.md` § `guard_action.py`.

Unsure which lane the request belongs to → `/bg`.
