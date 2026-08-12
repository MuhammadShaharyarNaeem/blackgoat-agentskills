# Planning and Task Breakdown — Deep Dive

On-demand companion to the planning-and-task-breakdown `SKILL.md` — examples, rationale, and anti-patterns that support the Worker Execution Contract.

## When to Use

- You have a spec and need to break it into implementable units
- A task feels too large or vague to start
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

Implementation order is dependency-correct and slice-ordered: foundations are built per slice as that slice needs them, not globally first.

## Horizontal vs. Vertical Slicing

Instead of building all the database, then all the API, then all the UI — build one complete feature path at a time:

**Bad (horizontal slicing):**
```
Task 1: Build entire database schema
Task 2: Build all API endpoints
Task 3: Build all UI components
Task 4: Connect everything
```

**Good (vertical slicing — one slice at a time, each split into its `[API]`/`[UI]` pair):**
```
Task 1: Registration schema + create-account endpoint [API]
Task 2: Registration form calling that endpoint [UI]
Task 3: Auth schema + login endpoint [API]
Task 4: Login form calling that endpoint [UI]
Task 5: Task schema + create-task endpoint [API]
Task 6: Task-creation form calling that endpoint [UI]
Task 7: List-tasks query endpoint [API]
Task 8: Task list view rendering it [UI]
```

Each vertical slice delivers working, testable functionality.

Execution is sequential with a single builder — task order is decided by the dependency graph, not by opportunities to fan work out.

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

## Example Checkpoint Block

The explicit checkpoint block required after every 2-3 tasks (Step 5 of the contract):

```markdown
### Checkpoint: After Tasks 1-3
- [ ] All tests pass
- [ ] Application builds without errors
- [ ] RUNTIME EXIT CRITERION — run `[exact command]`; expect `[exact observable output]`
- [ ] Review with human before proceeding
```

## Plan Document Template

Full template for `.docs/{project-name}/implementation/plan.md` (the required structure is defined in the SKILL.md contract; this is the worked walkthrough).

Why the first-slice deviation must be disclosed in the plan rather than merely accepted: an undisclosed deviation is indistinguishable from not knowing the rule, so the reviewer cannot tell a reasoned trade-off from an oversight.

Worked example below: a "contacts" feature. Milestone 1 (`[API]`) and Milestone 2 (`[UI]`) are the first SLICE — one thin end-to-end path, demoable once both land — with `Boundary contracts:` carrying the seam between them (`provides:` on Task 1, matching `consumes:` on Task 2). Milestone 3 widens the slice with a same-domain `[API]` addition.

```markdown
# Implementation Plan: [Feature/Project Name]

## Reference Documents
Before starting implementation, you MUST read the following documents to understand the full context and architectural constraints. Do not proceed until you have read them.

- [Requirements](file:///.docs/[project-name]/requirements.md)
- [Architecture Blueprint](file:///.docs/[project-name]/design/detailed-design.md) (when one exists; lite-originated plans link the governing stack contract(s) instead)

## Task List

### Milestone 1 — Contacts: list/create endpoints [API]

## Task 1: Contacts table and list/create endpoints

**Description:** Add the `contacts` table and the two endpoints the list view needs: `GET /api/contacts` and `POST /api/contacts`.

**Tags:** `[API]`

**Requirements covered:** FR-1, FR-2

**Named identifiers:** `db/migrations/0007_contacts.sql` (table `contacts`), `src/api/contacts.ts` (`listContacts`, `createContact`)

**Pattern anchor:** `src/api/tasks.ts` (existing list/create pair)

**Boundary contracts:** provides: contacts.list_endpoint, contacts.create_endpoint;
Response envelope for both endpoints is `{ data: Contact[] | Contact, error: null }`; `Contact` is `{ id: string, name: string, email: string }` (camelCase over the wire, snake_case in the `contacts` table).

**Do NOT:** touch `src/api/tasks.ts` or any other existing endpoint.

**Acceptance criteria:**
- [ ] `POST /api/contacts` with a valid body returns `201` and the created `Contact`
- [ ] `GET /api/contacts` returns every row previously created via `POST`

**Verification:**
- [ ] Tests pass: `npm test -- --grep "contacts api"`
- [ ] Build succeeds: `npm run build`
- [ ] Manual check: `curl -X POST localhost:3000/api/contacts -d '{"name":"A","email":"a@x.com"}'`, then `curl localhost:3000/api/contacts` shows it

**Dependencies:** None

**Estimated scope:** S: 1-2 files

### Checkpoint: Milestone 1
- [ ] All tests pass
- [ ] Application builds without errors
- [ ] RUNTIME EXIT CRITERION — run `curl -s localhost:3000/api/contacts`; expect `{"data":[],"error":null}` on a clean DB
- [ ] Review with human before proceeding

### Milestone 2 — Contacts list view [UI]

## Task 2: Contacts list page

**Description:** Render the contacts list and create form by calling the endpoints Milestone 1 provides.

**Tags:** `[UI]`

**Requirements covered:** FR-3

**Named identifiers:** `src/pages/ContactsPage.tsx`, `src/api-client/contacts.ts` (`fetchContacts`, `postContact`)

**Pattern anchor:** `src/pages/TasksPage.tsx`

**Boundary contracts:** consumes: contacts.list_endpoint, contacts.create_endpoint;
Reads the `{ data: Contact[], error: null }` envelope from `GET /api/contacts` and posts `{ name, email }` (camelCase) to `POST /api/contacts`, per Task 1's contract.

**Do NOT:** add a new endpoint — this task only consumes Milestone 1's.

**Acceptance criteria:**
- [ ] Navigating to `/contacts` renders one row per contact returned by the API
- [ ] Submitting the create form adds a row to the rendered list without a full page reload

**Verification:**
- [ ] Tests pass: `npm test -- --grep "contacts page"`
- [ ] Build succeeds: `npm run build`
- [ ] Manual check: open `/contacts`, submit the form, confirm the new row appears

**Dependencies:** 1

**Estimated scope:** S: 1-2 files

### Checkpoint: Milestone 2
- [ ] All tests pass
- [ ] Application builds without errors
- [ ] RUNTIME EXIT CRITERION — open `/contacts`, submit the create form; expect the new contact to appear in the rendered list without a reload
- [ ] Review with human before proceeding

### Milestone 3 — Contacts: search and pagination [API]

## Task 3: Search and pagination on the list endpoint

**Description:** Extend `GET /api/contacts` with `?q=` and `?page=` so a later widened list view can filter and page.

**Tags:** `[API]`

**Requirements covered:** FR-4

**Named identifiers:** `src/api/contacts.ts` (`listContacts` gains `q`, `page` params)

**Pattern anchor:** `src/api/tasks.ts` (`listTasks` pagination)

**Boundary contracts:** provides: contacts.list_endpoint.query_params;
`GET /api/contacts?q=<string>&page=<int>` narrows/pages the same response envelope as Task 1; omitting either param preserves Task 1's behavior exactly.

**Do NOT:** change the response envelope shape.

**Acceptance criteria:**
- [ ] `GET /api/contacts?q=smith` returns only contacts whose name matches `smith`
- [ ] `GET /api/contacts?page=2` returns the second page, not the first

**Verification:**
- [ ] Tests pass: `npm test -- --grep "contacts pagination"`
- [ ] Build succeeds: `npm run build`
- [ ] Manual check: `curl "localhost:3000/api/contacts?q=smith"` returns only matches

**Dependencies:** 1

**Estimated scope:** S: 1-2 files

### Checkpoint: Milestone 3
- [ ] All tests pass
- [ ] Application builds without errors
- [ ] RUNTIME EXIT CRITERION — run `curl -s "localhost:3000/api/contacts?q=smith"`; expect only name-matching contacts in `data`
- [ ] Review with human before proceeding

## Risks and Mitigations
| Risk | Impact | Mitigation |
|------|--------|------------|
| [Risk] | [High/Med/Low] | [Strategy] |

## Open Questions
- [Question needing human input]
```

Once the build Orchestrator finishes a milestone, it appends `[x]` to that heading line and nothing else — the completed form of Milestone 1 above reads `### Milestone 1 — Contacts: list/create endpoints [API] [x]`.

## Plans Model Effects, Not Artifacts — Rationale and More Example Pairs

Supporting the Step 4 principle and its three corollaries.

### Corollary 1 — acceptance criteria

**Why existence-shaped criteria are not criteria.** Code compiling, a file existing, a symbol being defined, or a type checking are all true of code that is never reached at runtime, and nothing in the toolchain will fail on unreached code. And when you cannot express a criterion as an observable effect, you do not yet understand what the task is for — the observable-effect requirement is a comprehension check on the planner, not just a formatting rule.

- *"the endpoint responds `409` with `{code}` on a replayed id"*, not *"the handler typechecks"*
- *"navigating to `/x` renders the results table"*, not *"the page component exists"*
- *"a request is issued to the B2 endpoint with the tokenised reference"*, not *"the B2 endpoint is documented"*
- *"the mock engine returns a populated response for every operation the flow calls"*, not *"the mock engine compiles"*

This corollary is distinct from the cross-boundary declaration check in the contract's Verification list: that one catches things that fail at *resolve* time; this one catches things that fail at *run* time, silently, in front of the user.

### Corollary 2 — `provides:` identifiers

Attaching the identifier to the authoring task rather than the effecting one cannot be caught by a parser: the `consumes-provides` lint sees a satisfied edge and passes while the consumer is still scheduled before the resource exists — which is the prerequisite-ownership defect the lint was installed to prevent, reappearing through its own grammar. That is why authoring and effecting get separate identifiers (`x.module` vs `x`).

### Corollary 3 — external prerequisites and human rulings

A `[BLOCKED]` tag with no earlier eliciting task is a scheduled stall rather than a flag: an autonomous build reaches that milestone and stops by construction, having forfeited all the work that could have proceeded in parallel with the question. Scheduling the ruling-elicitation task early converts the block into a question answered off the critical path.

## Negative-Half Proof for Gates — Rationale

Supporting the Step 4 rule "A task that authors a gate must also specify how that gate is proven to fail":

A check script, contract checker, scanner, or state-matrix assertion is trusted only once it has been observed rejecting a deliberate violation. Omit the negative half and a hollow gate is indistinguishable from a real one — both are green, and the plan has bought a green light rather than a check.

## Requirement Coverage Is Many-to-One — Cost Rationale

Supporting the Step 4 rule "Requirement coverage is many-to-one": minting one task per FR inflates task count, milestone count, and downstream build cost with zero traceability benefit. Several `FR`/`NFR` IDs describing steps of one coherent unit of work belong together in a single task's "Requirements covered:" field.

## Verification Harness Ordering — Rationale

Supporting Step 5 ordering rule 5 ("A verification harness precedes the work it verifies"):

A harness introduced after the features it was meant to gate has already let every one of them through unverified, and retrofitting it produces a backlog of failures with no clean bisect point.

## Milestone Economy — Cost Model

Supporting the Step 5 milestone-economy rule:

Each milestone/phase boundary carries downstream execution cost — in the build pipeline every milestone is executed by a fresh multi-agent round (typically an implementer, a tester, and a reviewer), so N milestones expand into roughly 3×N delegations. That is why milestone count is governed strictly by the dependency graph, and why a small deliverable gets exactly one milestone.

## Runtime Exit Criteria and Aggregate Green — Observed Failure

Supporting the Step 5 rules on runtime exit criteria and aggregate green:

"Core user flow works end-to-end" is the right *shape* for an exit criterion and useless as written — it names no command, so it is satisfied by whoever reads it deciding that it probably does.

A milestone whose exit condition *mixes* an unfakeable criterion with an aggregate-green one **will close on the aggregate** — that is the observed failure, not a hypothetical: the unfakeable half is the expensive half, so it is the half that gets deferred, while the cheap half goes green and advances the milestone. That is why mixed conditions must be split into two gates with the unfakeable one last.

## Artifact Self-Consistency — Rationale and Observed Failures

Supporting the Verification checklist's "Artifact self-consistency" checks. Each check below has shipped bugs the builder could not have avoided, precisely *because* the builder followed the plan exactly.

### Snippets are normative, not illustrative

A sample that drops, renames, or reshapes a field the invariants require to survive is a defect even when the surrounding prose is correct. Builders execute the nearest concrete instruction, not the distant rule — so a sample that contradicts an invariant wins over the prose that states the invariant. A verbatim anchor ("follow verbatim" / "given as-is") transfers authority from the reviewed invariant to the unreviewed sample and suppresses the builder's own judgement, which is why it may only be applied after the sample has been traced against every invariant governing the data it touches.

### A mandated capability needs its enabling declaration

Untraced cross-boundary references fail at build/resolve time, not at review time. A plan can read as complete while omitting the manifest entry, DI registration, module export, or build-config key that makes the mandated crossing resolvable — the omission only surfaces when the builder's code fails to build.

### A declared gate needs its executor wiring

This extends the enabling-declaration rule from *resolution* to *execution*. A gate expressed only as "a command to run" is unenforced: nothing in the toolchain will ever call it, and unlike an unresolved import its absence produces no signal whatsoever — not a build error, not a failing test, not a red PR. An observed run shipped four correct gate scripts wired to no script entry and no CI job; every one of them was authored, reviewed, committed, and never executed once.

### A consumer without its producer

Whenever a task reads a generated artifact — a build manifest, a codegen output, a lockfile, a coverage or metadata file — nothing guarantees it exists at that path unless the plan contains the producing instruction. And do not rely on the builder having read the earlier task that established a contract: builders execute one task at a time, and where the contract is absent the framework's default idiom fills the gap silently — the resulting code compiles, runs, and does nothing.

### A convention declared at or before its first use

If the first consuming task does not name the convention, the builder will invent one, and every later task that assumed the unstated version is now mis-wired. A convention introduced implicitly by a later task is not a convention.

### Guards vs. upstream handling (worked example)

This check is a worked example of the trace principle. If an upstream layer already sanitizes a field (clamp, normalize, default, coerce, truncate), a new rejecting guard on that field is unreachable dead code, and any task asserting rejection of that input can never pass — which is why the field's full inbound path must be traced before the guard is planned, and why a sanitizer and a rejecting validator may never coexist for one field.
