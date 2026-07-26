---
name: planning-and-task-breakdown
description: Squad-internal execution contract for breaking a spec or requirements set into ordered, implementable tasks with acceptance criteria and verification — loaded by agents via their Methodology Dependencies table; user-facing planning triggers belong to the /bgpdd-plan and /bgpdd-lite pipelines.
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

**Tags:** Include relevant system tags: `[SEC]` for security-sensitive logic (auth, payments), `[UI]` for user-facing UI changes, `[EXT]` for external APIs, `[BLOCKED]` for unclear requirements.

**Requirements covered:** [FR/NFR IDs this task satisfies, e.g. `FR-1, FR-3` — required whenever the plan is built from a `requirements.md` with numbered requirements]

**Named identifiers:** [exact file paths to create/modify, and the class/method/endpoint names this task must use — decided here, not by the builder. Authoritative for S/M tasks.]

**Pattern anchor:** [an existing exemplar to mirror — a file in this repo or a GOOD sample in the governing stack contract, cited by path/section. "None" only for genuinely novel work.]

**Boundary contracts:** [where this task's output meets another task, service, or the frontend — **and where this task consumes another's** — stated as the exact shape: signature, envelope, field casing on the wire, storage mechanism and key names. Restate values here even when an earlier task already declared them. "None" if fully internal.]

**Do NOT:** [explicit blast-radius fence — files/patterns this task must not touch or introduce.]

**Acceptance criteria:**
- [ ] [Specific, testable condition — an *observable effect*, see the rule below]
- [ ] [Specific, testable condition]

**Verification:**
- [ ] Tests pass: `npm test -- --grep "feature-name"`
- [ ] Build succeeds: `npm run build`
- [ ] Negative-half proof (any task that authors a gate, check script, or scanner): [the deliberate violation to introduce, the command to run, and the exact failure/non-zero exit it must produce before the violation is reverted]
- [ ] Manual check: [description of what to verify]

**Dependencies:** [Task numbers this depends on, or "None"]

**Files likely touched:**
- `src/path/to/file.ts`
- `tests/path/to/test.ts`

**Estimated scope:** [Small: 1-2 files | Medium: 3-5 files | Large: 5+ files]
```

**Acceptance criteria assert observable effects, never the existence of code.** Every criterion must name an effect observable at the boundary the requirement is actually about — *"the endpoint responds `409` with `{code}` on a replayed id"*, not *"the handler typechecks"*. A criterion satisfiable by code compiling, a file existing, a symbol being defined, or a type checking is **not a criterion** — those are all true of code that is never reached at runtime, and nothing in the toolchain will fail on unreached code. When you cannot express a criterion as an observable effect, you do not yet understand what the task is for — resolve that before writing the task. (More example pairs and the resolve-time vs run-time distinction: [planning deep dive](references/planning-deep-dive.md).)

**A task that authors a gate must also specify how that gate is proven to fail.** A check script, contract checker, scanner, or state-matrix assertion is trusted only once it has been observed rejecting a deliberate violation, so the plan writes that negative half into the task's Verification: the violation to introduce, the command, and the failure it must produce. Omit it and a hollow gate is indistinguishable from a real one — both are green, and the plan has bought a green light rather than a check. (The builder-side obligation is the negative-half proof rule in `test-driven-development`.)

**Scope rule for the four new fields:** Named identifiers, Pattern anchor, Boundary contracts, and Do NOT are mandatory for S/M tasks that a mid-tier builder will execute; for L/XL or judgment-heavy tasks they may be proportional, but Named identifiers and Do NOT are always required.

**Task heading constraint:** The `[N]` in `## Task [N]:` MUST be a bare positive integer (`## Task 6:`) — never letter-suffixed or decorated (`## Task 6a:`, `## Task 6.1:` are invalid). When one requirement must be split across multiple tasks, give each task its own distinct integer number (e.g. Task 6 and Task 7), not sub-letters. The deterministic coverage gate matches only `## Task <integer>:`; any non-integer heading makes that entire task block invisible to the gate, silently dropping every requirement it was meant to cover.

When the plan is built from a `requirements.md` with numbered `FR`/`NFR` IDs, every **Must-Have** requirement (`FR` and `NFR` IDs alike) must be covered by at least one task's "Requirements covered:" field — check this before finalizing the plan. Coverage is many-to-one, not one-to-one: several `FR`/`NFR` IDs may — and often should — map to a single task when they describe steps of one coherent unit of work (list them together in that task's "Requirements covered:" field). A task is defined by being an independently implementable-and-verifiable unit of work, not by how many IDs it satisfies; minting one task per FR inflates task count, milestone count, and downstream build cost with zero traceability benefit.

**Step 5: Order and Checkpoint.** Arrange tasks so that:

1. Dependencies are satisfied (build foundation first)
2. Each task leaves the system in a working state
3. Verification checkpoints occur after every 2-3 tasks
4. High-risk tasks are early (fail fast)
5. **A verification harness precedes the work it verifies.** When a milestone's exit criterion depends on a gate that does not exist yet — a browser/E2E harness, a contract checker, a fixture pipeline — building that gate is its own earlier milestone. A harness introduced after the features it was meant to gate has already let every one of them through unverified, and retrofitting it produces a backlog of failures with no clean bisect point.

**Milestone economy**: Each milestone/phase boundary carries downstream execution cost — in a fan-out build pipeline every milestone is executed by a fresh multi-agent round (typically an implementer, a tester, and a reviewer), so N milestones expand into roughly 3×N delegations. Create only as many milestones as the dependency graph genuinely requires; for a small deliverable (a handful of tasks with a single verification point), use ONE milestone, and never split milestones for cosmetic organization. (This governs milestone/phase count, separate from the within-plan review checkpoints in this step.) **Parallelism is a scheduling optimization applied OVER natural task and milestone boundaries**: build-pipeline fan-out (see bgpdd-build) reduces wall-clock only — never split tasks or milestones to "unlock" parallelism; granularity is always decided by "independently implementable-and-verifiable unit of work".

### Multi-Frontend Shared Component Dependency Rule
For multi-frontend workspace architectures, initial Phase 1 / Foundation task breakdowns MUST include establishing shared package infrastructure (e.g. `packages/ui`) before application-level development. Application tasks MUST list completion of shared UI component primitives as explicit prerequisites.

Add an explicit `## Checkpoint:` block after every 2-3 tasks, containing at minimum: all tests pass, application builds without errors, a `RUNTIME EXIT CRITERION` line (run `[exact command]`; expect `[exact observable output]`), and review with human before proceeding. Full example block in the [planning deep dive](references/planning-deep-dive.md).

**Every milestone and checkpoint declares at least one runtime exit criterion, written as the command plus the expected observable output.** "Core user flow works end-to-end" is the right *shape* and useless as written — it names no command, so it is satisfied by whoever reads it deciding that it probably does. Write the thing someone must actually run and what they must actually see.

**Aggregate green is not an exit criterion.** "All tasks complete, tests pass, review approved" is a summary of other people's reports, not an observation of the system. And a milestone whose exit condition *mixes* an unfakeable criterion with an aggregate-green one **will close on the aggregate** — that is the observed failure, not a hypothetical: the unfakeable half is the expensive half, so it is the half that gets deferred, while the cheap half goes green and advances the milestone. If a unit of work needs both, they are two gates, not one condition with two clauses. Split them, and put the unfakeable one last so nothing advances past it.

### Task Sizing

| Size | Files | Scope | Example |
|------|-------|-------|---------|
| **XS** | 1 | Single function or config change | Add a validation rule |
| **S** | 1-2 | One component or endpoint | Add a new API endpoint |
| **M** | 3-5 | One feature slice | User registration flow |
| **L** | 5-8 | Multi-component feature | Search with filtering and pagination |
| **XL** | 8+ | **Too large — break it down further** | — |

If a task is L or larger, break it into smaller tasks — an agent performs best on S and M tasks. The concrete break-it-down-further triggers are in the [planning deep dive](references/planning-deep-dive.md).

### Plan Document Output

Save the finalized plan to `.docs/{project-name}/implementation/plan.md`. Required structure — the full template walkthrough is in the [planning deep dive](references/planning-deep-dive.md):

- `# Implementation Plan: [Feature/Project Name]` title.
- `## Reference Documents` — instructs the builder to read the Requirements (`.docs/{project-name}/requirements.md`) and the Architecture Blueprint (`.docs/{project-name}/design/detailed-design.md`, when one exists; lite-originated plans link the governing stack contract(s) instead) before proceeding.
- `## Task List` — tasks grouped into phases, each phase followed by its `### Checkpoint:` block carrying a runtime exit criterion (run `[command]` → expect `[observable output]`).
- `## Risks and Mitigations` — table of risk / impact (High/Med/Low) / mitigation.
- `## Open Questions` — questions needing human input.

### Verification

Before starting implementation, confirm:

- [ ] Every task has acceptance criteria
- [ ] Every acceptance criterion names an **observable effect**, not the existence, compilation, or type-correctness of the code that produces it (see the rule in Step 4). Scan for the tell-tale verbs — "exists", "is defined", "compiles", "typechecks", "is documented", "is declared" — and rewrite every one as the effect it was meant to guarantee.
- [ ] Every task has a verification step, and every task that authors a gate or check script carries its negative-half proof (the violation, the command, the required failure) as one of those steps
- [ ] Every task cites the requirement ID(s) it covers, and every Must-Have requirement is covered by at least one task (FR and NFR)
- [ ] Task dependencies are identified and ordered correctly
- [ ] Every task's `Dependencies:` and `Files likely touched:` fields are complete and authoritative — the build Orchestrator uses them as the machine-readable contract to compute conflict-free parallel execution groups. State `Dependencies:` as exact task numbers (or `None`). Under `Files likely touched:` list EVERY file the task will create or modify, not a representative sample — an omitted file can cause two colliding tasks to be scheduled in parallel. Whenever a plan may be executed with parallel fan-out, treat "likely touched" as "authoritative touched".
- [ ] Work that requires a runnable environment (installing dependencies, starting a dev server, executing tests in a real runtime) declares an explicit environment-readiness precondition as its first task — dependencies installed, lockfile present, required tooling available. Never assume the environment is already provisioned; if provisioning needs a system-modifying action a worker cannot take, surface it as a prerequisite for the Orchestrator/human, not a silent assumption.
- [ ] No task touches more than ~5 files
- [ ] **Artifact self-consistency — trace every assertion back to its support.** Coverage ("every requirement has a task") is not consistency. Before finalizing, trace every concrete assertion the plan makes back to the declaration that makes it true. Each check below has shipped bugs the builder could not have avoided, precisely *because* the builder followed the plan exactly:
  - **Snippets are normative, not illustrative.** Any code sample a task reproduces must be traced against every invariant the governing artifacts state about the data it touches. A sample that drops, renames, or reshapes a field the invariants require to survive is a defect even when the surrounding prose is correct — builders execute the nearest concrete instruction, not the distant rule. Never label a snippet "follow verbatim" / "given as-is" unless you have completed that trace: a verbatim anchor transfers authority from the reviewed invariant to the unreviewed sample and suppresses the builder's own judgement. If the invariant and the sample disagree, fix the sample — do not restate the invariant beside it, and never let a task's acceptance criterion codify the sample's lossy behaviour.
  - **A mandated capability needs its enabling declaration as an explicit task step.** Whenever the design mandates crossing a module, package, or process boundary, the plan must contain an instruction to declare that dependency where the consuming side resolves it — manifest/package descriptor, DI registration, module export, build config. Listing the descriptor file under `Files likely touched:` is not an instruction. Untraced cross-boundary references fail at build/resolve time, not at review time.
  - **A declared gate needs its executor wiring as explicit task steps.** This extends the rule above from *resolution* to *execution*. A plan may not declare a verification script, contract checker, or scanner without also specifying, as its own task steps, the exact `package.json` (or equivalent manifest) script name that invokes it **and** the CI job that runs it on PRs. A gate expressed only as "a command to run" is unenforced: nothing in the toolchain will ever call it, and unlike an unresolved import its absence produces no signal whatsoever — not a build error, not a failing test, not a red PR. An observed run shipped four correct gate scripts wired to no script entry and no CI job; every one of them was authored, reviewed, committed, and never executed once.
  - **A consumer without its producer is an unbuildable task.** Whenever a task reads a generated artifact — a build manifest, a codegen output, a lockfile, a coverage or metadata file — the plan must also contain the instruction that *produces* it: the build-tool flag, codegen step, or config key that guarantees the artifact exists at that path. Symmetrically, whenever a task consumes a contract another task established — storage keys, envelope shape, wire casing, identifier format — the consuming task **restates that contract inline** (or cites the producing task by number *and* reproduces the values). Do not rely on the builder having read the earlier task: builders execute one task at a time, and where the contract is absent the framework's default idiom fills the gap silently and the resulting code compiles, runs, and does nothing.
  - **A convention must be declared at or before its first use.** Any structural convention a task depends on — directory layout, naming scheme, layer boundary — must be stated in the task that first depends on it, not established implicitly by later tasks. If the first consuming task does not name the convention, the builder will invent one, and every later task that assumed the unstated version is now mis-wired. A convention introduced implicitly by a later task is not a convention.
  - **Worked example — no task's guard conflicts with existing upstream handling of the same input.** Before adding a validator/guard on any field, trace that field's full inbound path: if an upstream layer already sanitizes it (clamp, normalize, default, coerce, truncate), the new guard is unreachable dead code and any task asserting rejection of that input can never pass. When both a sanitizer and a rejecting validator are specified for one field, the plan must explicitly choose one policy (reject-with-error vs. silently-sanitize) and delete the other — never leave both.
- [ ] Two-implementers test per task: could two competent implementers produce structurally different solutions from this task's text? If yes, a decision is missing — resolve it in the plan, not in the build.
- [ ] Stack Blueprint Verification: Verify that all stack-mandated patterns (e.g., Resource project isolation, Response envelope `.ToResult()`, FluentValidation for .NET backend APIs) from active stack methodology skills are explicitly mapped to concrete implementation tasks.
- [ ] Checkpoints exist between major phases, and every milestone/checkpoint carries a runtime exit criterion stated as command + expected observable output — with no gate mixing an unfakeable criterion and an aggregate-green one in a single condition (see Step 5)
- [ ] The plan has been surfaced for human review — via your `<handoff>` to the Orchestrator when delegated, or directly to the user when running in the main session

### Escalate When

- Requirements are missing, ambiguous, or contradictory → tag the affected task `[BLOCKED]` and report the ambiguity to the Orchestrator (manager) instead of guessing.
- A Must-Have requirement cannot be mapped to any implementable task → escalate to the Orchestrator.
- Decomposition keeps producing XL tasks no matter how you slice → escalate to the Orchestrator with the blocking constraint.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Planning deep dive](references/planning-deep-dive.md) — when (not) to use this skill, a worked dependency-graph example, horizontal-vs-vertical slicing examples, parallelization guidance, the full plan-document template and checkpoint example blocks, the Common Rationalizations table, and red flags.
