---
name: agent-orchestration-improve-agent
description: "Systematic improvement of existing agents through log parsing and procedural memory generation."
risk: safe
source: community
date_added: "2026-06-26"
---

# Agent Optimization Workflow (Forge Protocol)

This workflow enables an agent (specifically the `forge` persona) to autonomously analyze a build cycle's output, diagnose failures, and formulate "Procedural Memories" (new rules) to inject into the `SKILL.md` files of other agents.

## Use this skill when
- A build cycle has completed (successfully or unsuccessfully).
- You need to analyze why a subagent failed, timed out, or produced bad code.
- You need to update an agent's instructions so they don't repeat the same mistake.
- The user invokes `/bgpdd-learn` after any session (Learning Triage mode) — not only pipeline-end improvement phases.

## Do not use this skill when
- You are actively writing code or designing architecture.
- The user has not provided explicit approval to edit `SKILL.md` files.

## Worker Execution Contract

The protocol is a **two-delegation approval loop**: one delegation to analyze and propose, human approval in between, one delegation to apply. The detailed methodology for each analysis phase is in the [improve-agent deep dive](references/improve-agent-deep-dive.md) — read it on demand when executing that phase.

### Delegation 1 — Analyze & Propose

1. **Parse telemetry**: read the concrete evidence of the run — error output, `<handoff>` texts, `review-report.md`, artifacts under `.docs/{project-name}/`, git history. No statistical analyses. (Deep dive: *Telemetry Parsing*, including the Claude Code transcript filtered-read rule.)
2. **Diagnose root cause**: trace each failure up the chain of command — worker → manager → architect — and identify exactly which persona owns the root cause. (Deep dive: *Root Cause Diagnosis — The 5 Whys*.)
3. **Formulate rules**: translate each root cause into a hard, generally-applicable rule — abstract away symptoms, file names, and project specifics. Before proposing, read the ENTIRE target file and apply the Pruning Protocol: never add a rule already covered, never append a rule that contradicts an existing one without proposing the old one's removal. (Deep dive: *Procedural Memory Formation*, with good/bad rule examples.)
4. **Route each rule to exactly ONE destination layer** — persona, methodology skill, orchestrator contract, project rules file, or discard — per the Destination Triage table, generalizing BEFORE routing. Every proposed lesson names its destination and a one-line rationale. (Deep dive: *Destination Triage*.)
5. **Propose — DO NOT edit any `SKILL.md` or persona files in this delegation.** Write the proposal to `.docs/{project-name}/implementation/agent-improvements.md`, showing exactly which file you intend to modify and the exact text to append. Then terminate and report to the Orchestrator that the proposal awaits Human review.
   - **Learning Triage mode (`/bgpdd-learn`) exception**: skip the review artifact — return the formatted proposal directly in your `<handoff>`; the Orchestrator relays it to the user. Only approved lessons are ever written to destination files.

### Delegation 2 — Apply (Post-Approval Only)

Runs only when the Orchestrator re-invokes you with the User's approval of `agent-improvements.md` (pipeline mode) or passes the approved lessons directly in the delegation prompt (Learning Triage mode). Hard rules:

1. Apply ONLY the approved changes, exactly as enumerated.
2. **Never touch the YAML frontmatter** of any file. **Never delete or modify core persona descriptions.**
3. **Vector A (runtime rules)**: in persona files (`agents/<name>.md`) and project rules files, edits are confined strictly to the `## Procedural Memories (Learned Lessons)` section at the very bottom — create it at the end if missing, and never create it empty. In methodology skills, an approved lesson lands as a contract-level rule inside the relevant rules list of the SKILL.md spine, NOT in a Procedural Memories section — skills carry contracts, not memories.
4. **Vector B (approved structural surgery)**: changes from an approved `agent-audit` surgery plan may edit workflow steps, Methodology Dependencies tables, and persona body text — but ONLY the exact changes enumerated in the approved proposal.
5. **Memory hygiene**: if a `## Procedural Memories` section exceeds 5 bullets, synthesize and compress (Compaction Rule); at 3+ entries, do not append — apply the Abstraction Rule (elevate → generalize → move) instead. (Deep dive: *Editing Details*, including the append format example.)

## Deep Dive

Read on demand — not needed to hold the contract above:

- [Improve-agent deep dive](references/improve-agent-deep-dive.md) — Telemetry Parsing (error logs, code review, evidence, transcript filtered-read rule), Root Cause Diagnosis (5 Whys), Procedural Memory Formation (generalization constraint, rule examples, Pruning Protocol), Destination Triage (routing table and generalize-before-routing strips), and Editing Details (compaction, abstraction, append format).
