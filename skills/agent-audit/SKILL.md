---
name: agent-audit
description: Systematically audits agent personas and methodology dependencies for logical deadlocks, input/output collisions, and procedural bloat.
category: meta
risk: safe
---

# Agent Audit Skill

## Purpose
To ensure that autonomous agents operating in a squad or pipeline do not suffer from conflicting constraints, broken escalation paths, or output format collisions that would cause them to hallucinate, crash, or disobey instructions.

## When to Use This Skill
- When a subagent fails to complete a task or outputs the wrong format.
- When expanding a squad with a new agent and you need to ensure they align with the base persona.
- When refactoring a project's methodologies.
- Trigger phrases: "audit this agent", "check the squad for conflicts", "validate [agent] persona"

## Execution Checklist

Before beginning the audit, you MUST read the deep-dive explanations of the heuristics located at:
`{PLUGIN_ROOT}/agent-audit/references/heuristics.md`

Once you understand the audit metrics, execute the audit following these steps:

0. **Discovery (locate the files before reading)**: You cannot audit what you cannot find. First:
   - **Resolve `{PLUGIN_ROOT}`** to the actual directory this skill was loaded from (it varies by install location — do not assume an absolute path). Typically the `skills/` directory, two levels up from a skill's `SKILL.md`.
   - **Locate the target persona** (the agent's `SKILL.md`, or an `agents/<name>.md` file) and read its **"Methodology Dependencies" table** — this table names every inherited file (`base-persona.md`, methodology `SKILL.md` files) and when each is loaded.
   - **Glob/grep for every referenced dependency** and confirm each path resolves to a file that exists on disk. Flag any dangling reference immediately (a dependency pointing at a file that does not exist is an automatic Blocker).
   - **Locate any project overrides**: `.agents/AGENTS.md` in the target project.
   - **List everything you found** (and any missing files) before proceeding to the metrics.

1. **Read Target Files**: Read the target agent's `SKILL.md` file AND all underlying methodology skills (the `SKILL.md` of each skill) they inherit.
2. **Apply The Golden Rule (Who vs. How)**: The Persona (the agent's `SKILL.md` / `agents/<name>.md`) defines WHO the agent is. The methodology skills (each skill's `SKILL.md`) define HOW they work. This is a critical distinction—never let procedural 'How' instructions pollute the identity 'Who' file.
3. **Apply Metric 1 (Interface Alignment)**: Ensure upstream outputs match downstream inputs.
4. **Apply Metric 2 (Dependency Conflict)**: Ensure inherited methodology skills don't contradict the agent's core function.
5. **Apply Metric 3 (Role Cohesion)**: Identify specific API or framework rules bloating the persona. Do not blindly delete all Procedural Memories; use the **Abstraction Rule**:
   - Universal Engineering Principles (e.g. Data Safety) must be KEPT and elevated.
   - Specific project bloat should be generalized into language-agnostic principles if possible.
   - Irreducible project bloat must be moved to the project's `.agents/AGENTS.md`.
6. **Apply Metric 4 (Escalation Hallucination & Path Validity)**: Validate the chain of command for blockers. Ensure isolated subagents are not instructed to manage pipeline state transitions.
7. **Apply Metric 5 (Token Efficiency)**: Look for redundant or conflicting formatting instructions. Ensure generic methodologies do not overwrite persona-specific output formats.
8. **Apply Metric 6 (DRY & Contract Reuse)**: Ensure methodologies are shared rather than duplicated.
9. **Apply Metric 7 (Orchestrator vs Methodology Collision)**: Ensure the methodology does not attempt to orchestrate a swarm or manage state transitions that belong to the Orchestrator. If necessary, split the methodology into explicit "Modes".
10. **Apply Metric 8 (Context & File Bloat)**: Check the persona's "Methodology Dependencies" table. Ensure only the absolute bare minimum files are loaded "Always", and that heavy methodology files are strictly loaded on-demand.
11. **Apply Metric 9 (ID Traceability)**: Ensure requirements generate stable IDs (`FR`/`NFR`) and that every downstream stage threads them through — planning tasks cite the IDs, tests exercise them, and coverage gates check them. Flag any link that drops the ID or falls back to unverifiable prose-matching.

## Output Format

Deliver your findings as a "Brutally Honest Audit Report". It MUST have three parts, in order:

1. **Coverage Table** (required — fill every row, so no metric is silently skipped):

   | # | Metric | Verdict | Severity |
   |---|--------|---------|----------|
   | 1 | Interface Alignment | PASS / FAIL / N/A | Blocker / Warning / Nit |
   | 2 | Dependency Conflict | … | … |
   | 3 | Role Cohesion | … | … |
   | 4 | Escalation Path Validity | … | … |
   | 5 | Token Efficiency | … | … |
   | 6 | DRY & Contract Reuse | … | … |
   | 7 | Orchestrator vs Methodology Collision | … | … |
   | 8 | Context & File Bloat | … | … |
   | 9 | ID Traceability | … | … |

   Every metric gets a row. `N/A` is allowed only with a one-line reason. Only `FAIL` rows need a detailed prose section below.

2. **Findings**: for each `FAIL`, a prose section naming exactly which rules collide and why (brutally honest, concrete file/line references).

3. **Surgery Implementation Plan**: an actionable, ordered plan to fix every `FAIL`.

For an example of the tone and structure, read:
`{PLUGIN_ROOT}/agent-audit/examples/report.md`

## Verify (close the loop)

After the surgery plan is applied, **re-run all 9 metrics against the patched files** and confirm every `FAIL` flips to `PASS`. Report any residual `FAIL`s explicitly — do not declare the audit complete while a Blocker remains.
