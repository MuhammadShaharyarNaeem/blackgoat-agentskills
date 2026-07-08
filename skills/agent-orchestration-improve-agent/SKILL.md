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

## Do not use this skill when
- You are actively writing code or designing architecture.
- The user has not provided explicit approval to edit `SKILL.md` files.

---

## Phase 1: Telemetry Parsing (Read the Game Tape)

Do not run statistical analyses. Instead, use `Read` and `Grep` to parse concrete execution logs from the immediate workspace.

### 1.1 Read the Error Logs
If the build failed, read the error output:
- Use `Read` on `scratch/error.md` or `scratch/handoff.md`.
- Look for Circuit Breaker trips, timeout errors, or infinite loops.

### 1.2 Read the Code Review
Even if the build succeeded, the code may have been flawed.
- Read `.docs/{project-name}/implementation/review-report.md`.
- Identify recurring issues flagged by the code reviewer (e.g., "Mason keeps forgetting to hash passwords").

### 1.3 Read the Transcripts
If an agent behaved erratically, inspect their conversation transcript:
- Use `Grep` on `transcript.jsonl` in the `.system_generated/logs` directory.
- Search for "ERROR", "invalid tool call", or "is_truncated: true" to find context bloat or tool misuse.

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

## Phase 4: Human-in-the-Loop Proposal [CRITICAL]

**DO NOT edit any `SKILL.md` files yet.**

1. Write your proposed rules to a dedicated review artifact: `.docs/{project-name}/implementation/agent-improvements.md`.
2. Format the file clearly, showing exactly which `SKILL.md` file you intend to modify, and the exact text you intend to append.
3. Terminate your execution and report back to the Orchestrator that the proposal is ready for Human review.

---

## Phase 5: Scoped File Editing (Post-Approval)

If the Orchestrator invokes you a second time to inform you that the User has approved the `agent-improvements.md` file:

1. Use your `replace_file_content` or `Write` tools to apply the changes to the `SKILL.md` files.
2. **Never touch the YAML frontmatter** of any `SKILL.md` file.
3. **Never delete or modify the core persona descriptions.**
4. **Scoped Editing**: You may ONLY append, modify, or delete text strictly within the `## Procedural Memories (Learned Lessons)` section at the very bottom of the target file. If this section does not exist, create it at the end of the file.
5. **Compaction Rule**: If the `## Procedural Memories` section exceeds 5 bullet points, you MUST synthesize and compress them into broader core rules. Never append indefinitely.

### Example Append Format:
```markdown
## Procedural Memories (Learned Lessons)
- **[2026-06-26]**: Never use `cat` to write multi-line scripts in Windows environments; always use `Write`.
```
