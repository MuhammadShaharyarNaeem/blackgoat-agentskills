---
name: learn
description: "Captures lessons from the current session and routes them to the right layer — project rules file, agent persona, or methodology skill — via Forge's Learning Triage. Use after any session with corrections, failures, or repeated friction: trigger with /learn, 'capture lessons', 'what did we learn'. Squad-internal: run by the main-session Orchestrator, never by delegated subagents."
---

# Learn — Session Learning Triage

Every working session generates lessons — user corrections, agent failures, friction that repeats — and most of them evaporate when the session ends. This skill captures them on demand and routes each one to the layer where it belongs: the project's rules file, an agent persona, or a methodology skill. The Orchestrator gathers evidence in the main session, then delegates analysis and routing to Forge in Learning Triage mode. Nothing is applied without explicit user approval.

## Orchestrator Execution Contract

This skill runs in the main session, never inside a delegated subagent.

### Step 1: EVIDENCE (main session)

Scan the live conversation for user corrections, agent failures and retries, circuit-breaker trips, and the skills/agents in play. Read the durable artifacts: `.docs/{project-name}/implementation/review-report.md`, `test-report.md`, handoffs relayed in-conversation, and recent `git log`. Compress into an evidence brief of at most 15 bullets: what happened, which skill/agent/rule was involved, what the user had to correct.

**Transcript access:** if the runtime persists session transcripts as files (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`), resolve the current session's transcript path and pass it to Forge alongside the brief. The brief remains the always-available fallback.

### Step 2: DELEGATE (Forge — Learning Triage mode)

Pass Forge: the evidence brief, the list of skills/agents involved, and the transcript path (when available). Forge applies his `agent-orchestration-improve-agent` methodology (Phase 2 root cause, Phase 3 generalized rule + Pruning Protocol) plus its Destination Triage rubric.

State the hard filtered-read rule in the delegation: Forge NEVER full-reads a transcript file — transcripts embed every tool result. He greps targeted slices only (user messages, correction phrases, `<handoff>` blocks, error/circuit-breaker patterns, skill invocations), then reads just those line ranges.

### Step 3: PROPOSAL

Forge does NOT write any proposal file. He returns the improvement plan inside his `<handoff>` — per lesson: the generalized rule, its destination file, and a one-line rationale for that layer. You read the plan from the handoff.

### Step 4: HALT & APPROVE

Relay the plan from Forge's handoff to the user and halt. Never apply without explicit approval.

### Step 5: APPLY

On approval, re-delegate a fresh Forge, pasting the approved lessons (rule + destination per lesson) into the delegation prompt; Forge applies them per his Vector A/B edit scoping.

### Escalate When

- **No substantive lessons found** — say so plainly; do not invent lessons to justify the run.
- **A lesson contradicts an existing rule** — propose a replacement; never append a conflict.
- **A destination file is outside Forge's write boundary and the user has not approved** — halt.

## Relationship to Other Skills

- **Reuses** `agent-orchestration-improve-agent` Phases 2–5 and **extends** it with the Destination Triage rubric.
- **Supersedes** ad-hoc rule appending, such as bg-bugfix's old Phase 5.
- **Complements** the pipeline-end Forge phases (bgpdd-plan Phase 4, bgpdd-build Phase 6, bgpdd-shipping Step 7); it does not replace them.
