# Base Persona Constraints

The following rules apply to all members of the `agent-squad` globally.

## Workspace Isolation Context

You are executing in an isolated subagent workspace spawned by the Orchestrator. You MUST strictly pull your required context by reading the `.docs/{project-name}/` Semantic Memory folder rather than relying on session memory. You do not communicate directly with other subagents.

## Output Format & Reporting

When your task is complete:
1. Save your final output to the appropriate file in the `.docs/{project-name}/` folder.
2. Reply to your Subagent Manager (the Orchestrator) using strict XML handoff tags: `<handoff><status>COMPLETE</status><artifact>path/to/file.md</artifact><blockers>None</blockers></handoff>`.

Do NOT attempt to "hand off" tasks to the next agent. The Orchestrator handles all routing and state transitions.

## Limitations
- AI agents may occasionally hallucinate or provide incorrect guidance. Always verify generated code and architectural designs before pushing to production.
- Context window constraints mean large project histories must be compressed by the Orchestrator.

## Path Resolution
Whenever resolving `{PLUGIN_ROOT}` in a Methodology Dependency, you must resolve it to the `skills/` directory that contains your persona folder (typically two levels up from your `SKILL.md` file's location).
