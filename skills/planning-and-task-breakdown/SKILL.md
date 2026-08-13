---
name: planning-and-task-breakdown
description: Squad-internal execution contract for breaking a spec or requirements set into ordered, implementable tasks with acceptance criteria and verification — loaded by agents via their Methodology Dependencies table; user-facing planning triggers belong to the /bgpdd-plan and /bgpdd-lite pipelines.
---

# Planning and Task Breakdown

Decompose work into small, verifiable tasks with explicit acceptance criteria — each small enough to implement, test, and verify in one focused session.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### Workflow

**Step 1: Enter Plan Mode.** Read-only: read the spec and the relevant codebase, identify existing patterns and conventions, map dependencies, note risks and unknowns. **Do NOT write code during planning.** The output is a plan document.

**Step 2: Identify the Dependency Graph.** Before writing tasks, you MUST use a `<dag_scratchpad>` XML block to explicitly map the dependency graph — what depends on what.

**Step 3: Slice Vertically.** Build one complete feature path at a time (schema + API + UI for one feature), not layer-by-layer. Order is therefore dependency-correct *and* slice-ordered. (Worked examples: [deep dive](references/planning-deep-dive.md).)

**Step 4: Write Tasks.** Each task follows this structure:

```markdown
## Task [N]: [Short descriptive title]

**Description:** One paragraph explaining what this task accomplishes.

**Tags:** `[UI]` user-facing UI changes, `[API]` backend/service-side changes, `[SEC]` security-sensitive logic (auth, payments), `[EXT]` external APIs, `[BLOCKED]` unclear requirements. `[UI]` and `[API]` are DOMAIN tags — every task carries exactly one of them; `[SEC]`/`[EXT]`/`[BLOCKED]` are overlays that combine freely with either domain.

**Requirements covered:** [FR/NFR IDs this task satisfies, e.g. `FR-1, FR-3` — required whenever the plan is built from a numbered `requirements.md`]

**Named identifiers:** [exact file paths to create/modify, and the class/method/endpoint names this task must use — decided here, not by the builder. Authoritative for S/M tasks.]

**Pattern anchor:** [an existing exemplar to mirror — a file in this repo or a GOOD sample in the governing stack contract, cited by path/section. "None" only for genuinely novel work.]

**Boundary contracts:** [where this task's output meets another task, service, or the frontend — **and where it consumes another's** — as the exact shape: signature, envelope, wire field casing, storage mechanism and key names; restate values even when an earlier task declared them. Lead the field with the machine-parseable line `provides: <identifiers>; consumes: <identifiers>` (comma-separated; identifiers `[A-Za-z0-9_./-]`) — every consumed identifier must be provided by a lower-numbered task. The pipeline-tools `consumes-provides` lint enforces this grammar and is its contract authority (`{PLUGIN_ROOT}/pipeline-tools/SKILL.md`). **Terminate that line at the list itself** — end it with `;` or a newline before any prose; never append prose after the list on the same line. **Keep each keyword's list on one physical line** — a wrapped list contributes only its first line to the lint; open a second `provides:`/`consumes:` line rather than wrapping one. "None" if fully internal.]

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

**A criterion, a dependency identifier, and a prerequisite all name the observable effect the consumer needs — never the existence of the code, module, or decision that will eventually produce it.** No parser catches a violation of this. Four applications:

1. **Acceptance criteria assert observable effects, never the existence of code.** Every criterion names an effect observable at the boundary the requirement is actually about. A criterion satisfiable by code compiling, a file existing, a symbol being defined, or a type checking is **not a criterion**; when you cannot express one as an observable effect, resolve that before writing the task.
2. **A `provides:` identifier names the effect a consumer needs, not the artifact.** When a task authors a definition that only takes effect through a later action — infrastructure to apply, a migration to run, config to deploy, a package to publish — the identifier belongs to the task performing the effect, not the authoring one. Where authoring and effecting are separate tasks, use separate identifiers (`x.module` for the artifact, `x` for the live resource) and let consumers of the live resource consume the effect identifier.
3. **External prerequisites are provisioned before they're consumed.** Any external resource a task consumes — cloud identity/trust, secrets, provisioned infrastructure — must be provisioned by a lower-numbered task. **A human ruling is an external prerequisite too:** when a task's precondition is a decision only a person can give (a vendor choice, a policy call, an accepted trade-off), the plan must contain an earlier, explicitly scheduled task whose deliverable is *obtaining that ruling*, early enough that the answer arrives before the blocked task's milestone. A `[BLOCKED]` tag with no earlier eliciting task is a scheduled stall, not a flag.
4. **An in-process observation is not the effect.** A criterion satisfied *inside* the process that serves the behavior names the artifact that ran — the handler, the query, the assertion — not the effect, which is the bytes a client received, the pixels a person saw, or the state a device ended in. **An in-process probe is therefore never a valid `RUNTIME PROBE:` line.** Which frameworks count as in-process test hosts, and which claims they cannot prove, is owned by `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` and deliberately not restated here; `check_coverage.py`'s plan-mode `runtime-criterion` lint enforces that recognition mechanically, from a tell list byte-locked to `check_runtime_evidence.py`. Write the criterion at the boundary; the tier that proves it is that skill's Tier 3.

(Rationale for all four, example pairs, and the resolve-time vs run-time distinction: [deep dive](references/planning-deep-dive.md).)

**A task that interleaves durable state changes with an external effect declares its transaction boundaries, not just its step order.** Where steps mix writes to your own store with a call to a gateway, supplier, or broker, write into the task: which steps share a transaction, where each commit lands relative to the external call, what compensating action undoes an external effect whose follow-up work fails, and how a record left behind by a crash between phases is reclaimed. (A named instance of the two-implementers test; why step order hides it: [deep dive](references/planning-deep-dive.md).)

**A task that authors a gate must also specify how that gate is proven to fail** — the violation to introduce, the command, and the failure it must produce, written into that task's Verification. (Builder-side counterpart: `test-driven-development`'s negative-half proof rule; rationale: [deep dive](references/planning-deep-dive.md).)

**Scope rule for the four new fields:** Named identifiers, Pattern anchor, Boundary contracts, and Do NOT are mandatory for S/M tasks a mid-tier builder will execute; for L/XL or judgment-heavy tasks they may be proportional, but Named identifiers and Do NOT are always required.

**Task heading constraint:** The `[N]` in `## Task [N]:` MUST be a bare positive integer (`## Task 6:`) — never letter-suffixed or decorated (`## Task 6a:`, `## Task 6.1:`). Split a requirement across tasks by giving each its own distinct integer: the coverage gate matches only `## Task <integer>:`, and any other heading makes that whole task block invisible to it.

**Requirement coverage is many-to-one.** Every **Must-Have** requirement (`FR` and `NFR` alike) in a numbered `requirements.md` must be covered by at least one task's "Requirements covered:" field — check before finalizing. Several IDs may, and often should, map to one task: a task is an independently implementable-and-verifiable unit of work, not one ID's worth. (Cost rationale: [deep dive](references/planning-deep-dive.md).)

**Step 5: Order and Checkpoint.** Arrange tasks so that:

1. Dependencies are satisfied, in the dependency-correct slice-ordered sequence of Steps 2–3
2. Each task leaves the system in a working state
3. Verification checkpoints occur after every 2-3 tasks
4. High-risk tasks are early (fail fast)
5. **A verification harness precedes the work it verifies.** When a milestone's exit criterion depends on a gate that does not exist yet — a browser/E2E harness, a contract checker, a fixture pipeline — building that gate is its own earlier milestone. (Rationale: [deep dive](references/planning-deep-dive.md).)
6. **External prerequisites, human rulings included, are provisioned by a lower-numbered task** — corollary 3 of *Plans model effects, not artifacts* (Step 4).
7. **In a multi-frontend workspace, shared package infrastructure precedes application work.** Phase 1 / Foundation breakdowns MUST establish the shared packages (e.g. `packages/ui`), and application tasks MUST list completion of the shared UI component primitives as explicit prerequisites.

**Milestone economy**: create only as many milestones as the dependency graph genuinely requires; a small deliverable (a handful of tasks with a single verification point) gets ONE milestone, and milestones are never split for cosmetic organization. (Governs milestone/phase count, not rule 3's within-plan checkpoints; cost model: [deep dive](references/planning-deep-dive.md).) The build pipeline executes a milestone's tasks **sequentially with a single builder** — never shape tasks or milestones around hoped-for parallel execution.

**Milestone domain homogeneity**: every milestone contains tasks of ONE domain only — all `[UI]` or all `[API]` — because the build pipeline routes each milestone to a single specialized builder (Mason for `[API]`, Nova for `[UI]`); a mixed milestone is rejected at build time as a planning defect. This is a deliberate refinement, per convention #8, of Step 3's "Slice Vertically" rule: a vertical slice still governs ordering, but it now spans a PAIR of adjacent milestones (the slice's `[API]` milestone immediately followed by its `[UI]` milestone), with the cross-domain seam expressed through `Boundary contracts:` (`provides:` on the API side, `consumes:` on the UI side — already enforced by the pipeline-tools `consumes-provides` lint, since the API milestone's tasks are lower-numbered).

**Every milestone declares its verification surface with a `[vs:<surface>]` heading tag** — a second axis, orthogonal to `[UI]`/`[API]`: the domain tag says *who builds it*, the surface tag says *what evidence proves it*. Both live on the heading — `### Milestone 3 — Order envelope [API] [vs:web+api]`. Lowercase by design, so it cannot collide with `[API]`.

| Tag | Use when the milestone's observable effect is… | Evidence it obligates |
|-----|-----------------------------------------------|-----------------------|
| `[vs:api]` | a response a client receives | out-of-process capture; contract surface (OpenAPI/Swagger) reachable |
| `[vs:ui]` | something a person sees | rendered evidence (screenshot / accessibility-tree read) |
| `[vs:web+api]` | a frontend behavior that depends on local APIs | both, **plus** the environment manifest recording which local URLs were used |
| `[vs:rmm]` | state on a device or agent | device/agent state read back, plus the service set that was running |
| `[vs:fn]` | an async effect (function, queue, cache, bus) | invocation plus the effect read back from its sink |
| `[vs:none]` | nothing a client, person, or device can observe | **a written justification line in the checkpoint** |

**A missing or unknown surface tag is a planning defect**, mechanically: `next_milestone.py` returns `MIXED` (exit 1) and the build pipeline halts before Phase 1, exactly as for a mixed or untagged domain. `[vs:none]` is available and cheap, but it is an *explicit, reviewable claim*, not an exemption: write why nothing is observable, and expect that sentence to be challenged. (Why absence halts instead of defaulting: [deep dive](references/planning-deep-dive.md).)

**Choose the surface from the requirement, not from the task list**: ask what the requirement's grammatical subject *receives*; that names the surface. (Worked case: [deep dive](references/planning-deep-dive.md).)

**Every milestone and checkpoint declares at least one runtime exit criterion, as the command plus the expected observable output.** Put an explicit `### Checkpoint:` block at each of rule 3's points holding, at minimum: all tests pass, application builds without errors, a `RUNTIME EXIT CRITERION` line, a `RUNTIME PROBE:` line, and review with human before proceeding. Level-3, never `## Checkpoint:` — a level-2 heading terminates the milestone block `next_milestone.py` extracts, silently dropping the exit criterion from the builder's brief. Example block: [deep dive](references/planning-deep-dive.md).

The prose criterion carries intent; the machine-parseable `RUNTIME PROBE:` line beside it makes the criterion **executable by someone other than its author**. Shape:

```
RUNTIME EXIT CRITERION — run `<probe>`; expect `<observable>`
RUNTIME PROBE: start: `<start command>`; probe: `<probe command>`; expect-status: <N>; require-keys: <k1, k2>
```

- `start:` is how the application is brought up as a user brings it up. In a multi-service estate, name **every** service that must be running and note that their configuration is repointed at local URLs.
- `probe:` must exercise the running system as a user reaches it — started, driven, the asserted effect read back — and must exercise the *stateful* behavior the requirement names (a toggle actually toggled, a route actually navigated, a mode actually switched), not the first paint. **A build, typecheck, bundle, source-search, or test-runner command is not a probe**, and neither is an in-process test client (corollary 4). `check_coverage.py`'s plan-mode `runtime-criterion` lint rejects those shapes.
- `expect-status:` and `require-keys:` are required when the surface is `api`, `web+api`, or `fn` — they become the gate's `--expect-status` / `--require-key` arguments verbatim.
- When the surface is `[vs:none]`, replace the probe fields with `justification: <why nothing is observable>`. The lint checks that the sentence is present, not that it is true.
- When no harness can run the probe yet, building it is its own earlier milestone (Step 5, rule 5), and until it exists the criterion is recorded BLOCKED — never PASS.

**Aggregate green is not an exit criterion.** "All tasks complete, tests pass, review approved" summarizes other people's reports rather than observing the system. Never mix an unfakeable criterion with an aggregate-green one in one exit condition — they are two gates: split them, and put the unfakeable one last. (Observed failure mode: [deep dive](references/planning-deep-dive.md).)

### Task Sizing

XS = 1 file · S = 1-2 · M = 3-5 · L = 5-8 · XL = 8+ (**too large — break it down**). An agent performs best on S and M, so break anything L or larger. Break a task down further when any of these hold: it needs more than one focused session (~2+ hours of agent work); its acceptance criteria won't fit in 3 or fewer bullets; it touches two or more independent subsystems (e.g., auth and billing); its title needs "and" — a sign it is two tasks. Sizing examples: [deep dive](references/planning-deep-dive.md).

### Plan Document Output

Save the finalized plan to `.docs/{project-name}/implementation/plan.md`. Required structure below; a full worked-example walkthrough lives in the [deep dive](references/planning-deep-dive.md) — consult it for shape reference, the structure itself is this list.

- `# Implementation Plan: [Feature/Project Name]` title.
- `## Reference Documents` — instructs the builder to read the Requirements (`.docs/{project-name}/requirements.md`) and the Architecture Blueprint (`.docs/{project-name}/design/detailed-design.md`; lite-originated plans link the governing stack contract(s) instead) first.
- `## Task List` — tasks grouped into slice-shaped milestones: per **Milestone domain homogeneity** above (a deliberate refinement, per convention #8, of the plain one-milestone-per-slice framing), the first SLICE — its `[API]` milestone plus the immediately following `[UI]` milestone — is one thin end-to-end path, demoable at the pair's end; later slices widen. Each milestone is followed by its `### Checkpoint:` block carrying a runtime exit criterion. **If the first slice is NOT thin and end-to-end demoable, say so and why, in the plan** — name the constraint that forced the horizontal ordering and where the first demoable artifact lands. The rule may bend to a real constraint; never silently.
- **Canonical milestone heading, both axes:** `### Milestone <n> — <Title> [<UI|API>] [vs:<surface>]` — level-3, `<n>` a bare integer, both tags in the heading itself. The build Orchestrator records completion by appending `[x]` to that line. Machine consumer: `pipeline-tools/next_milestone.py` parses these headings (level-2 `## Milestone <n>` tolerated for older plans) — full contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
- `## Risks and Mitigations` — table of risk / impact (High/Med/Low) / mitigation.
- `## Open Questions` — questions needing human input.

### Acceptance Matrix Output

Save to `.docs/{project-name}/acceptance-matrix.md`. **A separate artifact at a different scope from the plan**: the plan is per-milestone, this is per-feature. **Derive it from `requirements.md`, never from the task list you just wrote** — the same rule `shipping-and-launch` states for the launch checklist. On brownfield work, reconcile against the `QA/manual-testing.md` baseline (see your Baseline Reconciliation duty) so existing behavior stays covered. (Why both rules hold: [deep dive](references/planning-deep-dive.md).)

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

- **Scenario heading**: `## <ID> <title> — P<0-3> — (<requirement IDs>)`. The ID is short and stable (`AS-2`); requirement IDs go **inside the parentheses** so the scenario's own id is never mistaken for one. Every scenario carries a priority.
- **Metadata line**: `|`-separated `key: value` pairs. `Surface:` uses the same keys as the `[vs:]` axis. `Preconditions:` may name an earlier scenario, expressing an ordered journey without the gate replaying it.
- **Step table**: reuses the `GO → DO → ASSERT` grammar Echo already uses for `QA/manual-testing.md`. Header cells must include `GO`, `DO`, `ASSERT` plus the two columns below; columns are read by name, so order is free.
- **`Stores`** names every source of truth the step reads back. **An effect asserted in one store is not asserted.**
- **`Mode`** is `auto` or `manual`. Manual is first-class — some device and console state genuinely cannot be automated — but a manual step **passes only with recorded evidence** under `evidence/runtime/`; unevidenced, it reads as NOT RUN and blocks.
- **`[inverse of N]`** marks a step as the inverse of step N in the same scenario. Every state-changing step needs one, or an explicit `[no inverse: <reason>]` — legitimate one-way steps exist (nothing un-distributes a queued job). Cover install→uninstall→**reinstall**.

Machine consumers: `check_acceptance_suite.py` gates execution at build Phase 5 and again at shipping Stage 1; its `--lint-only` mode gates this artifact's structure at plan time, and `--lint-only --requirements <requirements.md>` additionally gates Must-Have FR/NFR→scenario coverage (`fr-scenario-coverage`). Full contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` — single authority, not restated here.

### Verification

Before starting implementation, confirm:

- [ ] Every acceptance criterion is in observable-effect form (corollary 1) — scan for the tell-tale verbs ("exists", "is defined", "compiles", "typechecks", "is documented", "is declared") and rewrite each as the effect it guarantees
- [ ] Every task has a verification step; every gate- or check-script-authoring task carries its negative-half proof (violation, command, required failure) among them
- [ ] Every task cites its requirement ID(s); every Must-Have FR and NFR is covered by at least one task
- [ ] Every `Dependencies:` field is complete — exact task numbers or `None`. (File paths live in `Named identifiers:`.)
- [ ] Every non-`None` `Boundary contracts:` field leads with the `provides:`/`consumes:` line, each consumed identifier provided by a lower-numbered task — machine-checked by the pipeline-tools `consumes-provides` lint
- [ ] Every task carries exactly one domain tag (`[UI]` or `[API]`); every milestone is domain-homogeneous
- [ ] Work needing a runnable environment declares environment-readiness as its first task (dependencies installed, lockfile present, tooling available); a system-modifying action a worker cannot take is surfaced as a prerequisite, never silently assumed
- [ ] No task touches more than ~5 files
- [ ] **Artifact self-consistency — trace every assertion back to its support.** Coverage ("every requirement has a task") is not consistency. (Rationale and observed failures per check: [deep dive](references/planning-deep-dive.md#artifact-self-consistency--rationale-and-observed-failures).)
  - **Snippets are normative, not illustrative.** Trace any code sample a task reproduces against every invariant the governing artifacts state about the data it touches; never label one "follow verbatim" / "given as-is" before that trace completes. Where invariant and sample disagree, fix the sample.
  - **A mandated capability needs its enabling declaration as an explicit task step.** Every design-mandated module/package/process-boundary crossing needs a task instruction declaring the dependency where the consuming side resolves it (manifest/package descriptor, DI registration, module export, build config); listing the descriptor file under `Named identifiers:` is not an instruction.
  - **A declared gate needs its executor wiring as explicit task steps.** No verification script, contract checker, or scanner may be declared without also specifying, as task steps, the exact `package.json` (or equivalent manifest) script name that invokes it **and** the CI job that runs it on PRs.
  - **A consumer without its producer is an unbuildable task.** Where a task reads a generated artifact, the plan must also contain the instruction that *produces* it (build-tool flag, codegen step, config key); where a task consumes a contract another established — storage keys, envelope shape, wire casing, identifier format — the consuming task **restates that contract inline** (or cites the producing task by number *and* reproduces the values).
  - **A convention must be declared at or before its first use** — directory layout, naming scheme, layer boundary — stated in the task that first depends on it, never established implicitly by a later task.
  - **No task's guard conflicts with existing upstream handling of the same input.** Trace a field's full inbound path before adding a validator; where a sanitizer and a rejecting validator are both specified for one field, choose one policy and delete the other.
- [ ] Every task mixing durable writes with an external call states its transaction boundaries, commit points, compensating action, and crash-between-phases reclamation — never step order alone
- [ ] Two-implementers test per task: if two competent implementers could produce structurally different solutions from this text, a decision is missing — resolve it in the plan, not the build
- [ ] Stack Blueprint Verification: every stack-mandated pattern from the active stack methodology skills (Resource project isolation, `.ToResult()` envelopes, FluentValidation, …) maps to a concrete task
- [ ] Checkpoints exist between major phases; each carries a command + expected-output runtime exit criterion, with no gate mixing an unfakeable criterion and an aggregate-green one (Step 5)
- [ ] Every milestone heading carries a valid `[vs:<surface>]` tag alongside its domain tag; every `[vs:none]` carries its written justification
- [ ] Every checkpoint carries a conforming `RUNTIME PROBE:` line whose `probe:` exercises the running system — no build, typecheck, search, or **test-runner** command; `expect-status`/`require-keys` present wherever the surface is `api`, `web+api`, or `fn`
- [ ] No acceptance criterion for a client-, person-, or device-observable effect is satisfiable in-process (Step 4, corollary 4)
- [ ] `acceptance-matrix.md` exists and is derived from `requirements.md`, not the task list; every Must-Have FR/NFR appears in at least one scenario — machine-checked by `check_acceptance_suite.py --lint-only --requirements`'s `fr-scenario-coverage` lint at the plan pipeline's lint step
- [ ] Every state-changing step declares `[inverse of N]` or an explicit `[no inverse: <reason>]`; install paths cover uninstall **and** reinstall
- [ ] Every step names every store its assertion reads back; every `manual` step is one where automation is genuinely impossible, not merely inconvenient
- [ ] Every High-impact risk from research or design traces to an acceptance or checkpoint criterion that would **detect** it — a Risks-table entry alone is unmitigated
- [ ] The plan has been surfaced for human review — via your `<handoff>` to the Orchestrator when delegated, or directly to the user in the main session

### Escalate When

- Requirements are missing, ambiguous, or contradictory → tag the affected task `[BLOCKED]` and report the ambiguity to the Orchestrator (manager) instead of guessing.
- A Must-Have requirement cannot be mapped to any implementable task → escalate to the Orchestrator.
- Decomposition keeps producing XL tasks no matter how you slice → escalate to the Orchestrator with the blocking constraint.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Planning deep dive](references/planning-deep-dive.md) — when (not) to use this skill, worked dependency-graph and slicing examples, the full plan-document template, the worked acceptance matrix, checkpoint blocks, Common Rationalizations, red flags, and the rationale and observed failures behind every contract rule above.
