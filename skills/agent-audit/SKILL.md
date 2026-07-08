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

Before beginning the audit, you MUST use the `view_file` tool to read the deep-dive explanations of the heuristics located at:
`{PLUGIN_ROOT}/agent-audit/references/heuristics.md`

Once you understand the 5 metrics, execute the audit following these steps:

1. **Read Target Files**: Read the target agent's `SKILL.md` file AND all underlying methodology skills (`SKILL-CONTRACT.md` files) they inherit.
2. **Apply The Golden Rule (Who vs. How)**: The Persona (`SKILL.md`) defines WHO the agent is. The Skills (`SKILL-CONTRACT.md`) define HOW they work. This is a critical distinction—never let procedural 'How' instructions pollute the identity 'Who' file.
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

## Output Format

Deliver your findings as a "Brutally Honest Audit Report" detailing exactly which rules are colliding, followed by an actionable Implementation Plan to perform surgery on the affected files. 

For an example of the tone and structure, read:
`{PLUGIN_ROOT}/agent-audit/examples/report.md`
