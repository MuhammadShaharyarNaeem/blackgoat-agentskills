---
name: planning-and-task-breakdown
description: Breaks work into ordered tasks. Use when you have a spec or clear requirements and need to break work into implementable tasks. Use when a task feels too large to start, when you need to estimate scope, or when parallel work is possible. Squad-internal execution contract loaded by agents via their Methodology Dependencies table.
---

# Planning and Task Breakdown

Decompose work into small, verifiable tasks with explicit acceptance criteria. Every task should be small enough to implement, test, and verify in a single focused session.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### Workflow

**Step 1: Enter Plan Mode.** Operate read-only: read the spec and relevant codebase sections, identify existing patterns and conventions, map dependencies between components, note risks and unknowns. **Do NOT write code during planning.** The output is a plan document, not implementation.

**Step 2: Identify the Dependency Graph.** Before writing tasks, you MUST use a `<dag_scratchpad>` XML block to explicitly map the dependency graph. Map what depends on what. Implementation order follows the dependency graph bottom-up: build foundations first.

**Step 3: Slice Vertically.** Build one complete feature path at a time (schema + API + UI for one feature), not layer-by-layer (all schema, then all API, then all UI). Each vertical slice delivers working, testable functionality.

**Step 4: Write Tasks.** Each task follows this structure:

```markdown
## Task [N]: [Short descriptive title]

**Description:** One paragraph explaining what this task accomplishes.

**Tags:** Include relevant system tags: `[SEC]` for security-sensitive logic (auth, payments), `[EXT]` for external APIs, `[BLOCKED]` for unclear requirements.

**Requirements covered:** [FR/NFR IDs this task satisfies, e.g. `FR-1, FR-3` — required whenever the plan is built from a `requirements.md` with numbered requirements]

**Named identifiers:** [exact file paths to create/modify, and the class/method/endpoint names this task must use — decided here, not by the builder. Authoritative for S/M tasks.]

**Pattern anchor:** [an existing exemplar to mirror — a file in this repo or a GOOD sample in the governing stack contract, cited by path/section. "None" only for genuinely novel work.]

**Boundary contracts:** [where this task's output meets another task, service, or the frontend: the exact shape — signature, envelope, field casing on the wire. "None" if fully internal.]

**Do NOT:** [explicit blast-radius fence — files/patterns this task must not touch or introduce.]

**Acceptance criteria:**
- [ ] [Specific, testable condition]
- [ ] [Specific, testable condition]

**Verification:**
- [ ] Tests pass: `npm test -- --grep "feature-name"`
- [ ] Build succeeds: `npm run build`
- [ ] Manual check: [description of what to verify]

**Dependencies:** [Task numbers this depends on, or "None"]

**Files likely touched:**
- `src/path/to/file.ts`
- `tests/path/to/test.ts`

**Estimated scope:** [Small: 1-2 files | Medium: 3-5 files | Large: 5+ files]
```

**Scope rule for the four new fields:** Named identifiers, Pattern anchor, Boundary contracts, and Do NOT are mandatory for S/M tasks that a mid-tier builder will execute; for L/XL or judgment-heavy tasks they may be proportional, but Named identifiers and Do NOT are always required.

**Task heading constraint:** The `[N]` in `## Task [N]:` MUST be a bare positive integer (`## Task 6:`) — never letter-suffixed or decorated (`## Task 6a:`, `## Task 6.1:` are invalid). When one requirement must be split across multiple tasks, give each task its own distinct integer number (e.g. Task 6 and Task 7), not sub-letters. The deterministic coverage gate matches only `## Task <integer>:`; any non-integer heading makes that entire task block invisible to the gate, silently dropping every requirement it was meant to cover.

When the plan is built from a `requirements.md` with numbered `FR`/`NFR` IDs, every **Must-Have** requirement (`FR` and `NFR` IDs alike) must be covered by at least one task's "Requirements covered:" field — check this before finalizing the plan.

**Step 5: Order and Checkpoint.** Arrange tasks so that:

1. Dependencies are satisfied (build foundation first)
2. Each task leaves the system in a working state
3. Verification checkpoints occur after every 2-3 tasks
4. High-risk tasks are early (fail fast)

Add explicit checkpoints:

```markdown
## Checkpoint: After Tasks 1-3
- [ ] All tests pass
- [ ] Application builds without errors
- [ ] Core user flow works end-to-end
- [ ] Review with human before proceeding
```

### Task Sizing

| Size | Files | Scope | Example |
|------|-------|-------|---------|
| **XS** | 1 | Single function or config change | Add a validation rule |
| **S** | 1-2 | One component or endpoint | Add a new API endpoint |
| **M** | 3-5 | One feature slice | User registration flow |
| **L** | 5-8 | Multi-component feature | Search with filtering and pagination |
| **XL** | 8+ | **Too large — break it down further** | — |

If a task is L or larger, break it into smaller tasks. An agent performs best on S and M tasks. Break a task down further when: it needs more than one focused session (roughly 2+ hours of agent work); its acceptance criteria won't fit in 3 or fewer bullets; it touches two or more independent subsystems (e.g., auth and billing); or its title needs "and" (a sign it is two tasks).

### Plan Document Output

Save the finalized plan to `.docs/{project-name}/implementation/plan.md`.

```markdown
# Implementation Plan: [Feature/Project Name]

## Reference Documents
Before starting implementation, you MUST read the following documents to understand the full context and architectural constraints. Do not proceed until you have read them.

- [Requirements](file:///.docs/[project-name]/requirements.md)
- [Architecture Blueprint](file:///.docs/[project-name]/design/detailed-design.md) (when one exists; lite-originated plans link the governing stack contract(s) instead)

## Task List

### Phase 1: Foundation
- [ ] Task 1: ...
- [ ] Task 2: ...

### Checkpoint: Foundation
- [ ] Tests pass, builds clean

### Phase 2: Core Features
- [ ] Task 3: ...
- [ ] Task 4: ...

### Checkpoint: Core Features
- [ ] End-to-end flow works

### Phase 3: Polish
- [ ] Task 5: ...
- [ ] Task 6: ...

### Checkpoint: Complete
- [ ] All acceptance criteria met
- [ ] Ready for review

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| [Risk] | [High/Med/Low] | [Strategy] |

## Open Questions
- [Question needing human input]
```

### Verification

Before starting implementation, confirm:

- [ ] Every task has acceptance criteria
- [ ] Every task has a verification step
- [ ] Every task cites the requirement ID(s) it covers, and every Must-Have requirement is covered by at least one task (FR and NFR)
- [ ] Task dependencies are identified and ordered correctly
- [ ] No task touches more than ~5 files
- [ ] No task's guard conflicts with existing upstream handling of the same input. Before adding a validator/guard on any field, trace that field's full inbound path: if an upstream layer already sanitizes it (clamp, normalize, default, coerce, truncate), the new guard is unreachable dead code and any task asserting rejection of that input can never pass. When both a sanitizer and a rejecting validator are specified for one field, the plan must explicitly choose one policy (reject-with-error vs. silently-sanitize) and delete the other — never leave both.
- [ ] Two-implementers test per task: could two competent implementers produce structurally different solutions from this task's text? If yes, a decision is missing — resolve it in the plan, not in the build.
- [ ] Checkpoints exist between major phases
- [ ] The plan has been surfaced for human review — via your `<handoff>` to the Orchestrator when delegated, or directly to the user when running in the main session

### Escalate When

- Requirements are missing, ambiguous, or contradictory → tag the affected task `[BLOCKED]` and report the ambiguity to the Orchestrator (manager) instead of guessing.
- A Must-Have requirement cannot be mapped to any implementable task → escalate to the Orchestrator.
- Decomposition keeps producing XL tasks no matter how you slice → escalate to the Orchestrator with the blocking constraint.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Planning deep dive](references/planning-deep-dive.md) — when (not) to use this skill, a worked dependency-graph example, horizontal-vs-vertical slicing examples, parallelization guidance, the Common Rationalizations table, and red flags.
