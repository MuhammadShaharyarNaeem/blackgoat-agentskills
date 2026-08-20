---
name: agent-orchestration-improve-agent
description: "Systematic improvement of existing agents through log parsing and procedural memory generation."
risk: safe
source: community
date_added: "2026-06-26"
---

# Agent Optimization Workflow (Forge Protocol)

Lets the `forge` persona analyze a build cycle's output, diagnose failures, and formulate "Procedural Memories" (new rules) for other agents' `SKILL.md` and persona files.

## Use this skill when
- A build cycle has completed (successfully or unsuccessfully).
- You need to analyze why a subagent failed, timed out, or produced bad code.
- You need to update an agent's instructions so they don't repeat the same mistake.
- The user invokes `/bgpdd-learn` after any session (Learning Triage mode) — not only pipeline-end improvement phases.

## Do not use this skill when
- You are actively writing code or designing architecture.
- The user has not provided explicit approval to edit `SKILL.md` files.

## Worker Execution Contract

A **two-delegation approval loop**: delegation 1 analyzes and proposes, a human approves, delegation 2 applies. Per-phase methodology: [improve-agent deep dive](references/improve-agent-deep-dive.md) — read on demand when executing that phase.

### Delegation 1 — Analyze & Propose

1. **Parse telemetry**: read the run's concrete evidence — error output, `<handoff>` texts, `review-report.md`, artifacts under `.docs/{project-name}/`, git history. NEVER run statistical analyses. (Deep dive: *Telemetry Parsing*, including the Claude Code transcript filtered-read rule.)
2. **Diagnose root cause**: trace each failure up the chain of command — worker → manager → architect — and name exactly which persona owns it. (Deep dive: *Root Cause Diagnosis — The 5 Whys*.)
3. **Formulate rules**: translate each root cause into a hard, generally-applicable rule; abstract away symptoms, file names, and project specifics. Before proposing, read the ENTIRE target file and apply the Pruning Protocol — NEVER add a rule already covered; NEVER append a rule that contradicts an existing one without proposing the old one's removal. (Deep dive: *Procedural Memory Formation*, with good/bad rule examples.)
4. **Route each rule to exactly ONE destination layer** — persona, methodology skill, orchestrator contract, project rules file, or discard — per the Destination Triage table, generalizing BEFORE routing. Every proposed lesson names its destination and a one-line rationale. (Deep dive: *Destination Triage*.)
5. **Propose — NEVER edit any `SKILL.md` or persona file in this delegation.** Write the proposal to `.docs/{project-name}/implementation/agent-improvements.md`: each file you intend to modify, and the exact text to append. **A rule needing an actor to write outside its current write boundary gets that boundary amendment as its own line item, with its exact scope limits** — a behavioral change and a permission change are two approvals, not one. (Deep dive: *Proposal Scoping*.) Then terminate and report to the Orchestrator that the proposal awaits Human review.
   - **Learning Triage mode (`/bgpdd-learn`) exception**: skip the review artifact — return the formatted proposal directly in your `<handoff>`; the Orchestrator relays it to the user. Only approved lessons are ever written to destination files.

### Delegation 2 — Apply (Post-Approval Only)

Runs only when the Orchestrator re-invokes you with the User's approval of `agent-improvements.md` (pipeline mode) or passes the approved lessons directly in the delegation prompt (Learning Triage mode). Hard rules:

1. Apply ONLY the approved changes, exactly as enumerated.
2. **Never touch the YAML frontmatter** of any file. **Never delete or modify core persona descriptions.**
3. **Vector A (runtime rules)**: in persona files (`agents/<name>.md`) and project rules files, edits are confined strictly to the `## Procedural Memories (Learned Lessons)` section at the very bottom — create it at the end if missing, NEVER create it empty. In a methodology skill, the lesson lands as a contract-level rule in the relevant rules list of the SKILL.md spine, NEVER a Procedural Memories section — skills carry contracts, not memories.
4. **Vector B (approved structural surgery)**: changes from an approved `agent-audit` surgery plan may edit workflow steps, Methodology Dependencies tables, and persona body text — but ONLY the exact changes enumerated in the approved proposal.
5. **Memory hygiene**: if a `## Procedural Memories` section exceeds 5 bullets, synthesize and compress (Compaction Rule); at 3+ entries, do not append — apply the Abstraction Rule (elevate → generalize → move) instead. (Deep dive: *Editing Details*, including the append format example.)

## Deep Dive

[Improve-agent deep dive](references/improve-agent-deep-dive.md) — read on demand, not needed to hold the contract above. Each step names its section inline.
