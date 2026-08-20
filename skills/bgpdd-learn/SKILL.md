---
name: bgpdd-learn
description: "Captures lessons from the current session and routes them to the right layer — project rules file, agent persona, or methodology skill — via Forge's Learning Triage. Use after any session with corrections, failures, or repeated friction: trigger with /bgpdd-learn, 'capture lessons', 'what did we learn'. Squad-internal: run by the main-session Orchestrator, never by delegated subagents."
trigger: /bgpdd-learn
---

# Learn — Session Learning Triage

Captures this session's lessons on demand and routes each to exactly one layer: the project's rules file, an agent persona, or a methodology skill. The Orchestrator gathers evidence in the main session, then delegates analysis and routing to Forge in Learning Triage mode. NEVER apply anything without explicit user approval.

Rationale (on demand, not needed to execute): [Learning Triage rationale](references/learn-rationale.md).

## Path Resolution

`{PLUGIN_ROOT}` = the plugin's `skills/` directory (this skill's base directory is provided to you); personas live at `{PLUGIN_ROOT}/../agents/`. Every other path rule — list-before-reference, and the base-persona injection guard — has ONE home: `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md`, **Path Resolution** (inside your mandatory first read).

## Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Step 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.

## Orchestrator Execution Contract

This skill runs in the main session, never inside a delegated subagent.

### Step 1: EVIDENCE (main session)

Scan the live conversation for user corrections, agent failures and retries, circuit-breaker trips, and the skills/agents in play. Read the durable artifacts: `.docs/{project-name}/implementation/game-tape.md` (the accumulated per-phase evidence checkpoints, if present), `review-report.md`, `test-report.md`, handoffs relayed in-conversation, and recent `git log`. Compress into an evidence brief of at most 15 bullets: what happened, which skill/agent/rule was involved, what the user had to correct.

**Record confirmations, not only failures.** MUST include at least the confirmations you have evidence for: designs that built and tested first time, gates that caught a real defect, rules whose presence visibly prevented a class of error. A failures-only brief teaches the next optimization pass to delete the rules that were quietly working.

**Transcript access:** if the runtime persists session transcripts as files (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`), resolve the current session's transcript path and pass it to Forge alongside the brief. The brief remains the always-available fallback.

### Step 2: DELEGATE (Forge — Learning Triage mode)

Pass Forge: the evidence brief, the list of skills/agents involved, the transcript path (when available), and **the absolute path of this plugin's `skills/` directory as his `{PLUGIN_ROOT}`**. Resolve that path from this skill's provided base directory (its parent) and state it explicitly in the brief — Forge is a spawned subagent, cannot compute his own on-disk location, and `base-persona.md`'s Path Resolution rule (which he inherits) forbids guessing or scanning for it.

Forge applies his `agent-orchestration-improve-agent` methodology (Phase 2 root cause, Phase 3 generalized rule + Pruning Protocol) plus its Destination Triage rubric.

State the hard filtered-read rule in the delegation: Forge NEVER full-reads a transcript file — transcripts embed every tool result. He greps targeted slices only (user messages, correction phrases, `<handoff>` blocks, error/circuit-breaker patterns, skill invocations), then reads just those line ranges.

### Step 3: PROPOSAL

Forge does NOT write any proposal file. He returns the improvement plan inside his `<handoff>` — per lesson: the generalized rule, its destination file, and a one-line rationale for that layer.

### Step 4: HALT & APPROVE

Relay the plan from Forge's handoff to the user and halt. Never apply without explicit approval.

### Step 5: APPLY

On approval, resume the same Forge instance if the runtime supports warm continuation; otherwise delegate a **fresh** Forge with the approved plan only (align with `bgpdd-shipping` Step 7's fresh-on-apply when non-resumable). Paste only the approved lessons (rule + destination per lesson); Forge applies them per his Vector A/B edit scoping. Do NOT re-send the full evidence brief to a fresh Forge — the approved plan is the briefing.

### Escalate When

- **No substantive lessons found** — say so plainly; do not invent lessons to justify the run.
- **A lesson contradicts an existing rule** — propose a replacement; never append a conflict.
- **A destination file is outside Forge's write boundary and the user has not approved** — halt.

## Relationship to Other Skills

- **Reuses** the `agent-orchestration-improve-agent` analyze/apply contract, including its Destination Triage rubric.
- **Supersedes** ad-hoc rule appending.
- **Complements** the per-phase Game Tape checkpoints and the single end-of-epic Forge run (`bgpdd-shipping` Step 7) — this is the mid-epic escape valve when lessons should not wait for the epic to ship.
