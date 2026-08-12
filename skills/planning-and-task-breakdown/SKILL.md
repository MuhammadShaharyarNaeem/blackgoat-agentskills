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

**Step 2: Identify the Dependency Graph.** Before writing tasks, you MUST use a `<dag_scratchpad>` XML block to explicitly map the dependency graph — what depends on what.

**Step 3: Slice Vertically.** Build one complete feature path at a time (schema + API + UI for one feature), not layer-by-layer (all schema, then all API, then all UI). Each vertical slice delivers working, testable functionality. Implementation order is therefore dependency-correct *and* slice-ordered: foundations are built per slice as that slice needs them, not globally first.

**Step 4: Write Tasks.** Each task follows this structure:

```markdown
## Task [N]: [Short descriptive title]

**Description:** One paragraph explaining what this task accomplishes.

**Tags:** `[UI]` user-facing UI changes, `[API]` backend/service-side changes, `[SEC]` security-sensitive logic (auth, payments), `[EXT]` external APIs, `[BLOCKED]` unclear requirements. `[UI]` and `[API]` are DOMAIN tags — every task carries exactly one of them; `[SEC]`/`[EXT]`/`[BLOCKED]` are overlays that combine freely with either domain.

**Requirements covered:** [FR/NFR IDs this task satisfies, e.g. `FR-1, FR-3` — required whenever the plan is built from a numbered `requirements.md`]

**Named identifiers:** [exact file paths to create/modify, and the class/method/endpoint names this task must use — decided here, not by the builder. Authoritative for S/M tasks.]

**Pattern anchor:** [an existing exemplar to mirror — a file in this repo or a GOOD sample in the governing stack contract, cited by path/section. "None" only for genuinely novel work.]

**Boundary contracts:** [where this task's output meets another task, service, or the frontend — **and where it consumes another's** — as the exact shape: signature, envelope, wire field casing, storage mechanism and key names. Restate values even when an earlier task declared them. Lead the field with the machine-parseable line `provides: <identifiers>; consumes: <identifiers>` (comma-separated; identifiers `[A-Za-z0-9_./-]`) — every consumed identifier must be provided by a lower-numbered task; the pipeline-tools `consumes-provides` lint enforces this grammar and is its contract authority (parsing contract: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`). **Terminate that machine-parseable line at the list itself** — end it with `;` or a newline before any explanatory prose; put prose on the following line(s), never appended after the list on the same line, so the writer's intent can't be lost to the lint's grammar. **Keep each keyword's identifier list on one physical line** — a wrapped `provides:`/`consumes:` list contributes only its first line to the lint; open a second `provides:`/`consumes:` line rather than wrapping one. "None" if fully internal.]

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

**Estimated scope:** [Small: 1-2 files | Medium: 3-5 files | Large: 5+ files]
```

#### Plans model effects, not artifacts

**A criterion, a dependency identifier, and a prerequisite all name the observable effect the consumer needs — never the existence of the code, module, or decision that will eventually produce it.** No parser catches a violation of this. Three applications:

1. **Acceptance criteria assert observable effects, never the existence of code.** Every criterion must name an effect observable at the boundary the requirement is actually about. A criterion satisfiable by code compiling, a file existing, a symbol being defined, or a type checking is **not a criterion**; when you cannot express one as an observable effect, resolve that before writing the task.
2. **A `provides:` identifier names the effect a consumer needs, not the artifact.** When a task authors a definition that only takes effect through a later action — infrastructure to apply, a migration to run, config to deploy, a package to publish — the identifier belongs to the task performing the effect, not the authoring one. Where authoring and effecting are separate tasks, use separate identifiers (`x.module` for the authored artifact, `x` for the live resource) and let consumers of the live resource consume the effect identifier.
3. **External prerequisites are provisioned before they're consumed.** Any external resource a task consumes — cloud identity/trust, secrets, provisioned infrastructure — must be provisioned by a lower-numbered task; consuming one no earlier task provisions is a planning defect. **A human ruling is an external prerequisite too:** when a task's precondition is a decision only a person can give (a vendor choice, a policy call, an accepted trade-off), the plan must contain an earlier, explicitly scheduled task whose deliverable is *obtaining that ruling*, early enough that the answer arrives before the blocked task's milestone. A `[BLOCKED]` tag with no earlier eliciting task is a scheduled stall, not a flag.
4. **An in-process observation is not the effect.** A criterion satisfied *inside* the process that serves the behavior names the artifact that ran — the handler, the query, the assertion — rather than the effect, which is the bytes a client received, the pixels a person saw, or the state a device ended in. An in-process test host (`WebApplicationFactory`, `TestServer`, `supertest`, `MockMvc`) executes real code and produces a real green result, which is what makes it the most convincing wrong criterion available: everything about it is true except that it observed the boundary the requirement is about. Write the criterion at the boundary; the tier that can prove it is `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`'s Tier 3.

(Rationale for all three, example pairs, and the resolve-time vs run-time distinction: [deep dive](references/planning-deep-dive.md).)

**A task that interleaves durable state changes with an external effect declares its transaction boundaries, not just its step order.** When a task's steps mix writes to your own store with a call to a gateway, supplier, or broker — "check balance → call supplier → post entry" — an ordered list of steps is not a specification: one implementer wraps the whole sequence in a single transaction, another commits between steps, and only one of them is correct. Write the boundaries into the task: which steps share a transaction, where each commit lands relative to the external call, what compensating action undoes an external effect whose follow-up work fails, and how a record left behind by a crash between phases is reclaimed. This is a named instance of the two-implementers test, called out because the ordering notation hides it: the arrow between two steps says nothing about whether a commit sits on it.

**A task that authors a gate must also specify how that gate is proven to fail** — the violation to introduce, the command, and the failure it must produce, written into that task's Verification. (Builder-side counterpart: `test-driven-development`'s negative-half proof rule; rationale: [deep dive](references/planning-deep-dive.md).)

**Scope rule for the four new fields:** Named identifiers, Pattern anchor, Boundary contracts, and Do NOT are mandatory for S/M tasks that a mid-tier builder will execute; for L/XL or judgment-heavy tasks they may be proportional, but Named identifiers and Do NOT are always required.

**Task heading constraint:** The `[N]` in `## Task [N]:` MUST be a bare positive integer (`## Task 6:`) — never letter-suffixed or decorated (`## Task 6a:`, `## Task 6.1:` are invalid). When one requirement must be split across multiple tasks, give each task its own distinct integer number (e.g. Task 6 and Task 7), not sub-letters — the deterministic coverage gate matches only `## Task <integer>:`, and any non-integer heading makes that entire task block invisible to it.

**Requirement coverage is many-to-one.** When the plan is built from a numbered `requirements.md`, every **Must-Have** requirement (`FR` and `NFR` alike) must be covered by at least one task's "Requirements covered:" field — check before finalizing. Several IDs may, and often should, map to one task when they describe steps of one coherent unit of work: a task is defined by being an independently implementable-and-verifiable unit of work, not by how many IDs it satisfies. (Cost rationale: [deep dive](references/planning-deep-dive.md).)

**Step 5: Order and Checkpoint.** Arrange tasks so that:

1. Dependencies are satisfied, in the dependency-correct slice-ordered sequence of Steps 2–3
2. Each task leaves the system in a working state
3. Verification checkpoints occur after every 2-3 tasks
4. High-risk tasks are early (fail fast)
5. **A verification harness precedes the work it verifies.** When a milestone's exit criterion depends on a gate that does not exist yet — a browser/E2E harness, a contract checker, a fixture pipeline — building that gate is its own earlier milestone. (Rationale: [deep dive](references/planning-deep-dive.md).)
6. **External prerequisites, human rulings included, are provisioned by a lower-numbered task** — corollary 3 of *Plans model effects, not artifacts* (Step 4).

**Milestone economy**: create only as many milestones as the dependency graph genuinely requires; a small deliverable (a handful of tasks with a single verification point) gets ONE milestone, and milestones are never split for cosmetic organization. (Governs milestone/phase count, not the within-plan checkpoints of rule 3; cost model: [deep dive](references/planning-deep-dive.md).) The build pipeline executes a milestone's tasks **sequentially with a single builder** — never shape tasks or milestones around hoped-for parallel execution; granularity is always decided by "independently implementable-and-verifiable unit of work".

**Milestone domain homogeneity**: every milestone contains tasks of ONE domain only — all `[UI]` or all `[API]` — because the build pipeline routes each milestone to a single specialized builder (Mason for `[API]`, Nova for `[UI]`); a mixed milestone is rejected at build time as a planning defect. This is a deliberate refinement, per convention #8, of Step 3's "Slice Vertically" rule: a vertical slice still governs ordering, but it now spans a PAIR of adjacent milestones (the slice's `[API]` milestone immediately followed by its `[UI]` milestone), with the cross-domain seam expressed through `Boundary contracts:` (`provides:` on the API side, `consumes:` on the UI side — already enforced by the pipeline-tools `consumes-provides` lint, since the API milestone's tasks are lower-numbered).

**Every milestone declares its verification surface with a `[vs:<surface>]` heading tag.** This is a second axis, orthogonal to `[UI]`/`[API]`: the domain tag says *who builds it*, the surface tag says *what evidence proves it*. Both live on the heading — `### Milestone 3 — Order envelope [API] [vs:web+api]`. The tag is lowercase by design so it cannot collide with `[API]`.

| Tag | Use when the milestone's observable effect is… | Evidence it obligates |
|-----|-----------------------------------------------|-----------------------|
| `[vs:api]` | a response a client receives | out-of-process capture; contract surface (OpenAPI/Swagger) reachable |
| `[vs:ui]` | something a person sees | rendered evidence (screenshot / accessibility-tree read) |
| `[vs:web+api]` | a frontend behavior that depends on local APIs | both, **plus** the environment manifest recording which local URLs were used |
| `[vs:rmm]` | state on a device or agent | device/agent state read back, plus the service set that was running |
| `[vs:fn]` | an async effect (function, queue, cache, bus) | invocation plus the effect read back from its sink |
| `[vs:none]` | nothing a client, person, or device can observe | **a written justification line in the checkpoint** |

**A missing or unknown surface tag is a planning defect**, mechanically: `next_milestone.py` returns `MIXED` (exit 1) and the build pipeline halts before Phase 1, exactly as it does for a mixed or untagged domain. This is deliberate and it is the point — a surface that can be silently omitted is a surface that will be, and the milestone whose evidence requirement nobody declared is the milestone whose claim nobody checks. `[vs:none]` is available and cheap, but it is an *explicit, reviewable claim* rather than an exemption: write why there is nothing to observe, and expect that sentence to be challenged.

**Choose the surface from the requirement, not from the task list.** A milestone that adds a database column and a wrapper around it is `[vs:api]` if a client's response shape changes, `[vs:none]` only if nothing outside the process can tell the difference. Ask what the requirement's grammatical subject *receives*; that names the surface.

### Multi-Frontend Shared Component Dependency Rule
For multi-frontend workspace architectures, initial Phase 1 / Foundation task breakdowns MUST include establishing shared package infrastructure (e.g. `packages/ui`) before application-level development, and application tasks MUST list completion of shared UI component primitives as explicit prerequisites.

**Every milestone and checkpoint declares at least one runtime exit criterion, written as the command plus the expected observable output** — a criterion that names no command is satisfied by opinion. Add an explicit `### Checkpoint:` block at each of rule 3's points, containing at minimum: all tests pass, application builds without errors, a `RUNTIME EXIT CRITERION` line (run `[exact command]`; expect `[exact observable output]`), and review with human before proceeding — level-3, never `## Checkpoint:`: a level-2 checkpoint heading terminates the milestone block `next_milestone.py` extracts, silently dropping the exit criterion from the builder's brief. Example block: [deep dive](references/planning-deep-dive.md).

**Each checkpoint also carries a machine-parseable `RUNTIME PROBE:` line** beside the prose criterion. The prose line carries intent; this line makes the criterion **executable by someone other than its author** — which is the whole point, because a probe invented at verification time is invented by the party motivated to soften it. Shape:

```
RUNTIME EXIT CRITERION — run `<probe>`; expect `<observable>`
RUNTIME PROBE: start: `<start command>`; probe: `<probe command>`; expect-status: <N>; require-keys: <k1, k2>
```

- `start:` is how the application is brought up as a user brings it up. In a multi-service estate, name **every** service that must be running and note that their configuration is repointed at local URLs — a probe against a frontend still pointing at shared dev proves nothing about local.
- `probe:` must exercise the running system. A build, typecheck, bundle, search, **or test-runner** command is not a probe: `dotnet test` proves a suite is green, never that the hosted app emits this. `check_coverage.py`'s plan-mode `runtime-criterion` lint rejects those shapes.
- `expect-status:` and `require-keys:` are required when the surface is `api`, `web+api`, or `fn` — they become the gate's `--expect-status` / `--require-key` arguments verbatim.
- When the surface is `[vs:none]`, replace the probe fields with `justification: <why nothing is observable>`. The lint checks that the sentence is present, not that it is true.
- When no harness can run the probe yet, building it is its own earlier milestone (Step 5, rule 5), and until it exists the criterion is recorded BLOCKED — never PASS.

**A compile, typecheck, bundle, or source-search command is not a runtime exit criterion.** For any milestone delivering user-visible behavior the criterion must exercise the built application as a user reaches it — started, driven, and the asserted effect read back from the running system — and it must exercise the *stateful* behavior the requirement names (a toggle actually toggled, a route actually navigated, a mode actually switched), not the first paint. `tsc --noEmit`, a clean bundle, and a search proving a symbol exists all prove the code was written; none prove it runs. If no harness can do this yet, building it is its own earlier milestone (Step 5, rule 5), and until it exists every such criterion is recorded BLOCKED — never PASS.

**Aggregate green is not an exit criterion.** "All tasks complete, tests pass, review approved" summarizes other people's reports rather than observing the system. Never mix an unfakeable criterion with an aggregate-green one in one exit condition — they are two gates: split them, and put the unfakeable one last so nothing advances past it. (Observed failure mode: [deep dive](references/planning-deep-dive.md).)

### Task Sizing

| Size | Files | Scope | Example |
|------|-------|-------|---------|
| **XS** | 1 | Single function or config change | Add a validation rule |
| **S** | 1-2 | One component or endpoint | Add a new API endpoint |
| **M** | 3-5 | One feature slice | User registration flow |
| **L** | 5-8 | Multi-component feature | Search with filtering and pagination |
| **XL** | 8+ | **Too large — break it down further** | — |

If a task is L or larger, break it into smaller tasks — an agent performs best on S and M. Break-it-down-further triggers: [deep dive](references/planning-deep-dive.md).

### Plan Document Output

Save the finalized plan to `.docs/{project-name}/implementation/plan.md`. Required structure — full template walkthrough: [deep dive](references/planning-deep-dive.md).

- `# Implementation Plan: [Feature/Project Name]` title.
- `## Reference Documents` — instructs the builder to read the Requirements (`.docs/{project-name}/requirements.md`) and the Architecture Blueprint (`.docs/{project-name}/design/detailed-design.md`, when one exists; lite-originated plans link the governing stack contract(s) instead) before proceeding.
- `## Task List` — tasks grouped into slice-shaped milestones: per the **Milestone domain homogeneity** rule above (a deliberate refinement, per convention #8, of the plain one-milestone-per-slice framing, made necessary because a slice now spans a pair of single-domain milestones rather than one mixed one), the first SLICE — its `[API]` milestone plus the immediately following `[UI]` milestone — is one thin end-to-end path, demoable at the pair's end; later slices widen. Each milestone is followed by its `### Checkpoint:` block carrying a runtime exit criterion. **Canonical milestone heading:** each milestone is headed `### Milestone <n> — <Title> [<UI|API>]` — a level-3 heading, `<n>` a bare integer, the milestone's domain tag carried in the heading itself. The build Orchestrator records milestone completion by appending `[x]` to that heading line. Machine consumer: `pipeline-tools/next_milestone.py` parses these headings (it tolerates level-2 `## Milestone <n>` for older plans; new plans use level-3) — full contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`. **If the first slice is NOT thin and end-to-end demoable, say so and why, in the plan** — name the constraint that forced the horizontal ordering and where the first demoable artifact does land. The rule may bend to a real constraint; it may never bend silently.
- `## Risks and Mitigations` — table of risk / impact (High/Med/Low) / mitigation.
- `## Open Questions` — questions needing human input.
- **Canonical milestone heading, both axes:** `### Milestone <n> — <Title> [<UI|API>] [vs:<surface>]`. The domain tag routes the builder; the surface tag selects the evidence. A missing or unknown `[vs:]` tag halts the build pipeline before Phase 1.

### Acceptance Matrix Output

Save to `.docs/{project-name}/acceptance-matrix.md`. **A separate artifact at a different scope from the plan**: the plan is per-milestone, this is per-feature. Milestone evidence proves each brick; only this proves the wall stands, because the journey is ordered and stateful and because **the milestone that adds an operation has no reason to exercise its inverse.**

**Derive it from `requirements.md`, never from the task list you just wrote.** This is the same rule `shipping-and-launch` states for the launch checklist — *"Enumerate from the requirements document, never from the built feature list"* — and the reason is identical: a matrix derived from the plan inherits the plan's blind spots, and it is written by the party who would have to redo work if it found something. On brownfield work, reconcile against the `QA/manual-testing.md` baseline (see your Baseline Reconciliation duty) so existing behavior stays covered rather than silently dropped.

```markdown
## AS-2 Client mapping lifecycle — P0 — (FR-3, FR-4, EC-2)
Surface: web+api | Preconditions: integration connected (AS-1)

| # | GO | DO | ASSERT | Stores | Mode |
|---|----|----|--------|--------|------|
| 1 | Clients list | map client A | 200 + mapping row | api, db | auto |
| 2 | Clients list | reload | green tick on A | ui | auto |
| 3 | Clients list | unmap A [inverse of 1] | 200 + row gone | api, db | auto |
| 4 | Agent console | distribute [no inverse: a queued job cannot be un-queued] | agent installed | device | manual |
```

- **Scenario heading**: `## <ID> <title> — P<0-3> — (<requirement IDs>)`. The ID is short and stable (`AS-2`); requirement IDs go **inside the parentheses** so the scenario's own id is never mistaken for one. Every scenario carries a priority — an unprioritized scenario cannot be filtered honestly and is gated anyway.
- **Metadata line**: `|`-separated `key: value` pairs. `Surface:` uses the same keys as the `[vs:]` axis. `Preconditions:` may name an earlier scenario, which is how an ordered journey is expressed without the gate having to replay it.
- **Step table**: reuses the `GO → DO → ASSERT` grammar Echo already uses for `QA/manual-testing.md`, deliberately, so the two artifacts stay diffable and the write-back at end of shipping is a merge rather than a translation. Header cells must include `GO`, `DO`, `ASSERT`; columns are read by name, so order is free.
- **`Stores`** names every source of truth the step reads back. **An effect asserted in one store is not asserted**: a mapping that shows a green tick, a row in the database, and a paired agent on the device is three claims, and reading one and inferring the others is a proxy substitution.
- **`Mode`** is `auto` or `manual`. Manual is first-class — device state, an agent console, a pairing code genuinely cannot be automated — but a manual step **passes only with recorded evidence** under `evidence/runtime/`; unevidenced, it reads as NOT RUN and blocks.
- **`[inverse of N]`** marks a step as the inverse of step N in the same scenario. Every state-changing step needs one, or an explicit `[no inverse: <reason>]` — legitimate one-way steps exist (nothing un-distributes a queued job, nothing un-reinstalls). Cover install→uninstall→**reinstall**: reinstall is the idempotency case, and it is the one that catches an uninstall that only half-removed.

Machine consumers: `check_acceptance_suite.py` gates execution at build Phase 5 and again at shipping Stage 1; its `--lint-only` mode gates this artifact's structure at plan time. Full contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` — single authority, not restated here.

### Verification

Before starting implementation, confirm:

- [ ] Every task has acceptance criteria, all in observable-effect form, never the existence, compilation, or type-correctness of the code producing it (corollary 1) — scan for the tell-tale verbs ("exists", "is defined", "compiles", "typechecks", "is documented", "is declared") and rewrite each as the effect it guarantees
- [ ] Every task has a verification step; every gate- or check-script-authoring task carries its negative-half proof (violation, command, required failure) among them
- [ ] Every task cites its requirement ID(s); every Must-Have requirement (FR and NFR) is covered by at least one task
- [ ] Task dependencies are identified and ordered correctly, with every `Dependencies:` field complete — exact task numbers or `None`, so build order is unambiguous. (File paths live in `Named identifiers:`.)
- [ ] Every non-`None` `Boundary contracts:` field leads with the `provides:`/`consumes:` line, each consumed identifier provided by a lower-numbered task — machine-checked by the pipeline-tools `consumes-provides` lint
- [ ] Every task carries exactly one domain tag (`[UI]` or `[API]`), and every milestone is domain-homogeneous
- [ ] Work needing a runnable environment declares an environment-readiness precondition as its first task (dependencies installed, lockfile present, tooling available) — never assume provisioning; if it needs a system-modifying action a worker cannot take, surface it as a prerequisite for the Orchestrator/human, not a silent assumption
- [ ] No task touches more than ~5 files
- [ ] **Artifact self-consistency — trace every assertion back to its support.** Coverage ("every requirement has a task") is not consistency: trace every concrete assertion the plan makes back to the declaration that makes it true. (Rationale and observed failures per check: [deep dive](references/planning-deep-dive.md#artifact-self-consistency--rationale-and-observed-failures).)
  - **Snippets are normative, not illustrative.** Trace any code sample a task reproduces against every invariant the governing artifacts state about the data it touches; never label one "follow verbatim" / "given as-is" before that trace completes. Where invariant and sample disagree, fix the sample — never restate the invariant beside it, never let an acceptance criterion codify the sample's lossy behaviour.
  - **A mandated capability needs its enabling declaration as an explicit task step.** Every design-mandated module/package/process-boundary crossing needs a task instruction declaring the dependency where the consuming side resolves it (manifest/package descriptor, DI registration, module export, build config); listing the descriptor file under `Named identifiers:` is not an instruction.
  - **A declared gate needs its executor wiring as explicit task steps.** No verification script, contract checker, or scanner may be declared without also specifying, as task steps, the exact `package.json` (or equivalent manifest) script name that invokes it **and** the CI job that runs it on PRs.
  - **A consumer without its producer is an unbuildable task.** Where a task reads a generated artifact, the plan must also contain the instruction that *produces* it (build-tool flag, codegen step, config key); where a task consumes a contract another established — storage keys, envelope shape, wire casing, identifier format — the consuming task **restates that contract inline** (or cites the producing task by number *and* reproduces the values).
  - **A convention must be declared at or before its first use.** Any structural convention a task depends on — directory layout, naming scheme, layer boundary — must be stated in the task that first depends on it, never established implicitly by a later task.
  - **No task's guard conflicts with existing upstream handling of the same input.** Before adding a validator/guard on a field, trace that field's full inbound path; where both a sanitizer and a rejecting validator are specified for one field, explicitly choose one policy (reject-with-error vs. silently-sanitize) and delete the other.
- [ ] Every task whose steps mix durable writes with an external call states its transaction boundaries, its commit points relative to that call, its compensating action, and how a crash between phases is reclaimed — never step order alone
- [ ] Two-implementers test per task: could two competent implementers produce structurally different solutions from this task's text? If yes, a decision is missing — resolve it in the plan, not the build
- [ ] Stack Blueprint Verification: all stack-mandated patterns (e.g. Resource project isolation, Response envelope `.ToResult()`, FluentValidation for .NET backend APIs) from active stack methodology skills are explicitly mapped to concrete tasks
- [ ] Checkpoints exist between major phases; every milestone/checkpoint carries a command + expected-output runtime exit criterion, with no gate mixing an unfakeable criterion and an aggregate-green one (Step 5)
- [ ] Every milestone heading carries a valid `[vs:<surface>]` tag alongside its `[UI]`/`[API]` domain tag; every `[vs:none]` carries its written justification
- [ ] Every checkpoint carries a conforming `RUNTIME PROBE:` line whose `probe:` exercises the running system — no build, typecheck, search, or **test-runner** command; `expect-status`/`require-keys` present wherever the surface is `api`, `web+api`, or `fn`
- [ ] No acceptance criterion for a client-, person-, or device-observable effect is satisfiable in-process (Step 1, corollary 4)
- [ ] `acceptance-matrix.md` exists, is derived from `requirements.md` (not from the task list), and every Must-Have FR appears in at least one scenario
- [ ] Every state-changing step declares `[inverse of N]` or an explicit `[no inverse: <reason>]`; install paths cover uninstall **and** reinstall
- [ ] Every step names every store its assertion reads back, and every `manual` step is one where automation is genuinely impossible rather than merely inconvenient
- [ ] Every High-impact risk named by research or design traces to a specific acceptance or checkpoint criterion that would **detect** it — a risk whose only entry is prose in the Risks table is unmitigated, because nothing in the plan fails when the mitigation does not hold
- [ ] The plan has been surfaced for human review — via your `<handoff>` to the Orchestrator when delegated, or directly to the user in the main session

### Escalate When

- Requirements are missing, ambiguous, or contradictory → tag the affected task `[BLOCKED]` and report the ambiguity to the Orchestrator (manager) instead of guessing.
- A Must-Have requirement cannot be mapped to any implementable task → escalate to the Orchestrator.
- Decomposition keeps producing XL tasks no matter how you slice → escalate to the Orchestrator with the blocking constraint.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Planning deep dive](references/planning-deep-dive.md) — when (not) to use this skill, worked dependency-graph and slicing examples, the full plan-document template and checkpoint blocks, Common Rationalizations, red flags, and the rationale and observed failures behind every contract rule above.
