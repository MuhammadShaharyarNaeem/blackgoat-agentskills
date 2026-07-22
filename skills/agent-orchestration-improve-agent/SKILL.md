---
name: agent-orchestration-improve-agent
description: "Systematic improvement of existing agents through log parsing and procedural memory generation."
risk: safe
source: community
date_added: "2026-06-26"
---

# Agent Optimization Workflow (Forge Protocol)

This workflow enables an agent (specifically the `forge` persona) to autonomously analyze a build cycle's output, diagnose failures, and formulate "Procedural Memories" (new rules) to inject into the `SKILL.md` files of other agents.

[Extended thinking: True autonomous agent optimization cannot rely on 100-sample statistical tests. It requires pragmatic analysis of immediate error logs, tracing failures to the specific agent responsible, and implementing targeted "Do Not Do X" rules in that agent's system prompt.]

## Use this skill when
- A build cycle has completed (successfully or unsuccessfully).
- You need to analyze why a subagent failed, timed out, or produced bad code.
- You need to update an agent's instructions so they don't repeat the same mistake.
- The user invokes `/bgpdd-learn` after any session (Learning Triage mode) — not only pipeline-end improvement phases.

## Do not use this skill when
- You are actively writing code or designing architecture.
- The user has not provided explicit approval to edit `SKILL.md` files.

---

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

---

## Phase 2: Root Cause Diagnosis (The 5 Whys)

Do not treat symptoms. If a worker failed, trace the error up the chain of command:
1. **Worker Error:** Did the executing agent (e.g., Mason, Quinn) hallucinate a library or ignore an explicit rule?
2. **Manager Error:** Did the planning agent (e.g., Alex) provide an impossible checklist?
3. **Architect Error:** Did the design agent (e.g., Aria) provide a flawed blueprint?

Identify exactly which persona is responsible for the root cause of the gap.

---

## Phase 3: Procedural Memory Formation

Translate the root cause into a hard, actionable rule for the responsible agent, but **ensure it is generally applicable**.

**Generalization Constraint**: Abstract away the immediate symptoms, exact file names, or specific variable names from the failure. Your formulated rules must be general behavioral heuristics or architectural patterns that the agent can apply broadly across any future project.

- **Bad Rule:** "Mason should be careful about database connections." (Too vague, un-testable).
- **Bad Rule:** "Rule: When establishing database connections in workers, always use the Singleton connection pool defined in `db.ts`." (Too specific, tied to a single file/project).
- **Good Rule:** "Rule: When establishing resources that are prone to exhaustion (like database connections), ensure you utilize a centralized connection pool or Singleton pattern rather than creating new connections per request."

### The Pruning Protocol
Before proposing a new rule, you MUST read the ENTIRE target agent's `SKILL.md` file (their core persona and responsibilities, not just the memories). If your proposed rule is already covered by their core instructions, do not add it—avoid redundancy. If your new rule contradicts an existing rule in their `## Procedural Memories` section, you must propose deleting or replacing the old rule. Do not blindly append conflicting rules.

---

## Destination Triage (Learning Triage Mode)

When invoked via `/bgpdd-learn` (or whenever a lesson's home is not predetermined), route each formulated rule to exactly ONE layer — this is the agent-audit Golden Rule (personas = WHO, skills = HOW) plus the Abstraction Rule (elevate → generalize → move) applied to learning:

| Lesson is... | Destination |
|---|---|
| Project-specific and not generalizable (names this repo's files, stack quirks, local conventions) | The target project's `.agents/AGENTS.md` (or the project's `CLAUDE.md`) |
| About WHO an agent is — judgment, boundaries, escalation behavior | That agent's `agents/<name>.md`, `## Procedural Memories` section |
| About HOW a task is done, role-agnostic | The methodology skill: contract-level rules in the SKILL.md spine, rationale in its `references/` deep-dive |
| Already covered by an existing rule, or a one-off with no recurrence risk | Discard (Pruning Protocol) |

Every proposed lesson must name its destination and a one-line rationale for that layer. In Learning Triage mode, the proposal is returned in your `<handoff>` — do not write a proposal file; only approved lessons are ever written to their destination files. (Pipeline improvement phases still use `agent-improvements.md` as their review artifact.) If a lesson seems to belong at two layers, generalize it until it belongs at one.

---

## Phase 4: Human-in-the-Loop Proposal [CRITICAL]

**DO NOT edit any `SKILL.md` files yet.**

1. Write your proposed rules to a dedicated review artifact: `.docs/{project-name}/implementation/agent-improvements.md`.
2. Format the file clearly, showing exactly which `SKILL.md` file you intend to modify, and the exact text you intend to append.
3. Terminate your execution and report back to the Orchestrator that the proposal is ready for Human review.

> **Learning Triage mode (`/bgpdd-learn`) exception**: skip the review artifact — return the formatted proposal directly in your `<handoff>` instead of writing `agent-improvements.md`. The Orchestrator relays it to the user.

---

## Phase 5: Scoped File Editing (Post-Approval)

If the Orchestrator invokes you a second time to inform you that the User has approved the `agent-improvements.md` file (pipeline mode) or passes you the approved lessons directly in the delegation prompt (Learning Triage mode):

1. Edit the `SKILL.md` files directly to apply the changes.
2. **Never touch the YAML frontmatter** of any `SKILL.md` file.
3. **Never delete or modify the core persona descriptions.**
4. **Scoped Editing (Vector A — runtime rules)**: Procedural-memory rules may ONLY be appended, modified, or deleted strictly within the `## Procedural Memories (Learned Lessons)` section at the very bottom of the target file. If this section does not exist, create it at the end of the file.
5. **Compaction Rule**: If the `## Procedural Memories` section exceeds 5 bullet points, you MUST synthesize and compress them into broader core rules. Never append indefinitely.
6. **Scoped Editing (Vector B — approved structural surgery)**: Structural changes originating from an approved `agent-audit` surgery plan may edit workflow steps, Methodology Dependencies tables, and persona body text — but ONLY the exact changes enumerated in the approved `agent-improvements.md` proposal. YAML frontmatter remains untouchable in all cases.

### Example Append Format:
```markdown
## Procedural Memories (Learned Lessons)
- **[2026-06-26]**: Never use `cat` to write multi-line scripts in Windows environments; write the file directly instead.
```
