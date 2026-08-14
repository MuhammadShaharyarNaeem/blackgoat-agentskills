# agent-audit

A meta-skill designed to systematically audit subagent personas (`SKILL.md`) and methodology dependencies for logical deadlocks, interface collisions, and procedural bloat.

## Why use this skill?
When building autonomous agent squads, it is common for agents to suffer from "cognitive dissonance" caused by conflicting instructions. For example, a global rule might tell an execution agent to write documentation, or an upstream planning agent might change their output format, breaking the downstream agent's input expectations.

This skill applies 18 strict structural heuristics to identify and fix these logical deadlocks before the agents are executed.

## Usage

Simply ask the orchestrator agent to run the audit:

> "Audit the Mason persona for conflicts."
> "Validate the squad."
> "Check this agent's SKILL.md file for interface collisions."

The agent will read the relevant personas, check them against the 18 heuristics, and produce a "Brutally Honest Audit Report" detailing the exact structural flaws, followed by a surgical implementation plan to fix them.

## The 18 Heuristics
1. **Interface Alignment:** Does Agent B's expected input perfectly match Agent A's actual output?
2. **Dependency Conflict Detection:** Do the agent's inherited methodology skills contradict their core identity?
3. **Role Cohesion:** Is the agent's core persona polluted with project-specific API rules that belong in a global `.agents/AGENTS.md` file?
4. **Escalation Path Validity:** Does the agent have a physically possible chain of command to report blockers?
5. **Token Efficiency:** Are there redundant or conflicting formatting instructions wasting context window space?
6. **DRY & Contract Reuse:** Are methodologies shared and role-agnostic, rather than duplicated per agent?
7. **Orchestrator vs Methodology Collision:** Does a methodology try to orchestrate the swarm or manage state that belongs to the Orchestrator?
8. **Context & File Bloat:** Does the persona load only the bare-minimum methodology files at startup, with heavy files loaded on-demand?
9. **ID Traceability:** Do requirements generate stable IDs that are threaded through every downstream stage and checked by gates?
10. **Wake-Up Context Weight:** Measured (not guessed) word count of the persona plus every "Always"-loaded dependency — under the ~2,500-word ceiling?
11. **Frontmatter & Metadata Hygiene:** Are `phase:`, `model:`, `description:`, and `depends-on` consistent across the squad and true to what each file does?
12. **Trigger Collision:** Do worker methodologies avoid end-user trigger language that competes with the orchestrator pipelines?
13. **Cross-Pipeline Consistency:** Do sibling pipelines share the same hardening skeleton, reference the orchestrator contract, and agree field-by-field on `orchestrator-state.json`?
14. **Model Assignment Fit:** Does each agent's `model:` tier match its task complexity?
15. **Skill Content Validity & Cross-Skill Contract Coherence:** Do code samples actually run, does the skill avoid contradicting itself, and do two skills documenting one wire contract describe the same serialized shape?
16. **Defect-Class Enforcement:** Do the methodology skills still *contain* the defect-class rules (supersession register, requirements write-back, Phase 2.5 attack list, the four pipeline-tools lints)?
17. **Output-Rubric Gate Coverage:** Does each of the 8 output-quality dimensions map to at least one enforcing gate, checklist item, or lint?
18. **Convergent Redundancy (Distillation):** Do several rules restate one underlying idea — a cluster to merge into one principle with corollaries, backed by a mechanism, with rationale moved to `references/`?

Full definitions, rationale, and worked examples live in [`references/heuristics.md`](references/heuristics.md).
