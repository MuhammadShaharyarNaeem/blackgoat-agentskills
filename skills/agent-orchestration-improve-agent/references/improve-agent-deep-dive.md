# Agent Optimization (Forge Protocol) — Deep Dive

On-demand companion to the `agent-orchestration-improve-agent` SKILL.md. The two-delegation approval loop and its hard rules live in the SKILL.md spine; this file carries the detailed methodology for each phase.

[Extended thinking: True autonomous agent optimization cannot rely on 100-sample statistical tests. It requires pragmatic analysis of immediate error logs, tracing failures to the specific agent responsible, and implementing targeted "Do Not Do X" rules in that agent's system prompt.]

## Phase 1: Telemetry Parsing (Read the Game Tape)

Do not run statistical analyses. Instead, read and search to parse concrete execution logs from the immediate workspace.

### 1.1 Read the Error Logs
If the build failed, read the error output:
- Read any partial-state or error files the run produced (e.g. an agent's committed partial work, or an `error.md` under `.docs/{project-name}/`), and the failing agent's returned `<handoff>` text relayed by the Orchestrator.
- Look for Circuit Breaker trips or repeated-error loops.

### 1.2 Read the Code Review
Even if the build succeeded, the code may have been flawed.
- Read `.docs/{project-name}/implementation/review-report.md`.
- Identify recurring issues flagged by the code reviewer (e.g., "Mason keeps forgetting to hash passwords").

### 1.3 Read the Evidence
> **Runtime note (Claude Code):** delegated-agent internal transcripts are NOT exposed — reconstruct their behavior from handoffs and artifacts. The MAIN session's transcript, however, may exist as a file (`~/.claude/projects/<project-slug>/<session-id>.jsonl`). When the Orchestrator passes you a transcript path (Learning Triage mode), read it with the filtered-read rule: grep targeted slices only (user messages, corrections, `<handoff>` blocks, error patterns, skill invocations) and read just those line ranges — NEVER full-read the file; it embeds every tool result and will flood your context.

If an agent behaved erratically, inspect the durable evidence:
- The agent's returned `<handoff>` summary (relayed by the Orchestrator) and any artifacts it wrote under `.docs/{project-name}/`.
- Git history of the agent's commits (diff churn, reverted work) via `git log`/`git diff`.
- Any error output or repeated-failure notes the user pasted into the conversation.
- Look for signs of context bloat or tool misuse (e.g. an agent that rewrote the same file many times, or ignored an explicit rule).

## Phase 2: Root Cause Diagnosis (The 5 Whys)

Do not treat symptoms. If a worker failed, trace the error up the chain of command:
1. **Worker Error:** Did the executing agent (e.g., Mason, Quinn) hallucinate a library or ignore an explicit rule?
2. **Manager Error:** Did the planning agent (e.g., Alex) provide an impossible checklist?
3. **Architect Error:** Did the design agent (e.g., Aria) provide a flawed blueprint?

Identify exactly which persona is responsible for the root cause of the gap.

## Phase 3: Procedural Memory Formation

Translate the root cause into a hard, actionable rule for the responsible agent, but **ensure it is generally applicable**.

**Generalization Constraint**: Abstract away the immediate symptoms, exact file names, or specific variable names from the failure. Your formulated rules must be general behavioral heuristics or architectural patterns that the agent can apply broadly across any future project.

- **Bad Rule:** "Mason should be careful about database connections." (Too vague, un-testable).
- **Bad Rule:** "Rule: When establishing database connections in workers, always use the Singleton connection pool defined in `db.ts`." (Too specific, tied to a single file/project).
- **Good Rule:** "Rule: When establishing resources that are prone to exhaustion (like database connections), ensure you utilize a centralized connection pool or Singleton pattern rather than creating new connections per request."

### The Pruning Protocol
Before proposing a new rule, you MUST read the ENTIRE target agent's `SKILL.md` file (their core persona and responsibilities, not just the memories). If your proposed rule is already covered by their core instructions, do not add it—avoid redundancy. If your new rule contradicts an existing rule in their `## Procedural Memories` section, you must propose deleting or replacing the old rule. Do not blindly append conflicting rules.

## Destination Triage (Learning Triage Mode)

When invoked via `/bgpdd-learn` (or whenever a lesson's home is not predetermined), route each formulated rule to exactly ONE layer — this is the agent-audit Golden Rule (personas = WHO, skills = HOW) plus the Abstraction Rule (elevate → generalize → move) applied to learning:

**Generalize BEFORE routing, not after.** Strip the framework, then the role, from the draft rule and route what remains:
- If the rule would hold for *any* agent doing this task, it is HOW, not WHO — route it to the methodology skill, never a persona. Persona destinations are the exception, reserved for judgment, boundaries, and escalation behavior genuinely specific to that one role.
- If the rule would hold beyond the framework that surfaced it, route it to the framework-agnostic skill (e.g. `ui-design-patterns`, `test-driven-development`), never a framework playbook (`vue3-spa-patterns`, `dotnet-backend-patterns`) — a general rule parked in a framework playbook silently stops applying on every other stack.
- Only what survives both strips with framework- or project-specifics intact routes to the playbook or project layer.

| Lesson is... | Destination |
|---|---|
| Project-specific and not generalizable (names this repo's files, stack quirks, local conventions) | The target project's `.agents/AGENTS.md` (or the project's `CLAUDE.md`) |
| About WHO an agent is — judgment, boundaries, escalation behavior | That agent's `agents/<name>.md`, `## Procedural Memories` section |
| About HOW a task is done, role-agnostic | The methodology skill: contract-level rules in the SKILL.md spine, rationale in its `references/` deep-dive |
| About how the **Orchestrator** orchestrates — cross-cutting delegation, error recovery, or role-boundary behavior spanning more than one pipeline | `skills/agent-squad/orchestrator-contract.md`, as a contract rule in the relevant section (never inlined into a pipeline, never `base-persona.md` — that file is subagent-scoped) |
| Already covered by an existing rule, or a one-off with no recurrence risk | Discard (Pruning Protocol) |

Every proposed lesson must name its destination and a one-line rationale for that layer. If a lesson seems to belong at two layers, generalize it until it belongs at one.

## Editing Details (Delegation 2)

- **Vector A scope**: a `## Procedural Memories` heading with no rule under it is placeholder scaffolding and must not be written.
- **Compaction Rule**: If the `## Procedural Memories` section exceeds 5 bullet points, you MUST synthesize and compress them into broader core rules. Never append indefinitely.
- **Memory Hygiene (Abstraction Rule)**: When a persona's `## Procedural Memories` section has accumulated 3 or more entries, do NOT append another — apply the Abstraction Rule instead: elevate universal engineering rules into the persona's Responsibilities (undated), generalize framework-specific lessons into language-agnostic principles, and move irreducible project-specific rules to that project's `.agents/AGENTS.md`. Dated memories are a staging area, not a permanent home.

### Example Append Format:
```markdown
## Procedural Memories (Learned Lessons)
- **[2026-06-26]**: Never use `cat` to write multi-line scripts in Windows environments; write the file directly instead.
```
