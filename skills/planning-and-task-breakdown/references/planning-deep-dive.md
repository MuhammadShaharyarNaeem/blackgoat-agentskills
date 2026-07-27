# Planning and Task Breakdown — Deep Dive

On-demand companion to the planning-and-task-breakdown `SKILL.md` — examples, rationale, and anti-patterns that support the Worker Execution Contract.

## When to Use

- You have a spec and need to break it into implementable units
- A task feels too large or vague to start
- Work needs to be parallelized across multiple agents or sessions
- You need to communicate scope to a human
- The implementation order isn't obvious

**When NOT to use:** Single-file changes with obvious scope, or when the spec already contains well-defined tasks.

## Dependency Graph Example

Map what depends on what:

```
Database schema
    │
    ├── API models/types
    │       │
    │       ├── API endpoints
    │       │       │
    │       │       └── Frontend API client
    │       │               │
    │       │               └── UI components
    │       │
    │       └── Validation logic
    │
    └── Seed data / migrations
```

Implementation order follows the dependency graph bottom-up: build foundations first.

## Horizontal vs. Vertical Slicing

Instead of building all the database, then all the API, then all the UI — build one complete feature path at a time:

**Bad (horizontal slicing):**
```
Task 1: Build entire database schema
Task 2: Build all API endpoints
Task 3: Build all UI components
Task 4: Connect everything
```

**Good (vertical slicing):**
```
Task 1: User can create an account (schema + API + UI for registration)
Task 2: User can log in (auth schema + API + UI for login)
Task 3: User can create a task (task schema + API + UI for creation)
Task 4: User can view task list (query + API + UI for list view)
```

Each vertical slice delivers working, testable functionality.

## Parallelization Opportunities

When multiple agents or sessions are available:

- **Safe to parallelize:** Independent feature slices, tests for already-implemented features, documentation
- **Must be sequential:** Database migrations, shared state changes, dependency chains
- **Needs coordination:** Features that share an API contract (define the contract first, then parallelize)

## Break-It-Down-Further Triggers

Break a task down further when any of these hold:
- It needs more than one focused session (~2+ hours of agent work).
- Its acceptance criteria won't fit in 3 or fewer bullets.
- It touches two or more independent subsystems (e.g., auth and billing).
- Its title needs "and" — a sign it is two tasks.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "I'll figure it out as I go" | That's how you end up with a tangled mess and rework. 10 minutes of planning saves hours. |
| "The tasks are obvious" | Write them down anyway. Explicit tasks surface hidden dependencies and forgotten edge cases. |
| "Planning is overhead" | Planning is the task. Implementation without a plan is just typing. |
| "I can hold it all in my head" | Context windows are finite. Written plans survive session boundaries and compaction. |

## Red Flags

- Starting implementation without a written task list
- Tasks that say "implement the feature" without acceptance criteria
- No verification steps in the plan
- All tasks are XL-sized
- No checkpoints between tasks
- Dependency order isn't considered

## Checkpoint Example Block

The explicit checkpoint block required after every 2-3 tasks (Step 5 of the contract):

```markdown
## Checkpoint: After Tasks 1-3
- [ ] All tests pass
- [ ] Application builds without errors
- [ ] RUNTIME EXIT CRITERION — run `[exact command]`; expect `[exact observable output]`
- [ ] Review with human before proceeding
```

## Plan Document Template

Full template for `.docs/{project-name}/implementation/plan.md` (the required structure is defined in the SKILL.md contract; this is the worked walkthrough):

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
- [ ] Runtime exit criterion: run `[command]` → expect `[observable output]`

### Phase 2: Core Features
- [ ] Task 3: ...
- [ ] Task 4: ...

### Checkpoint: Core Features
- [ ] Runtime exit criterion: run `[command]` → expect `[observable output]`

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

## Observable-Effect Criteria — More Example Pairs

Supporting the Step 4 rule "Acceptance criteria assert observable effects, never the existence of code":

- *"navigating to `/x` renders the results table"*, not *"the page component exists"*
- *"a request is issued to the B2 endpoint with the tokenised reference"*, not *"the B2 endpoint is documented"*
- *"the mock engine returns a populated response for every operation the flow calls"*, not *"the mock engine compiles"*

This rule is distinct from the cross-boundary declaration check in the contract's Verification list: that one catches things that fail at *resolve* time; this one catches things that fail at *run* time, silently, in front of the user.
