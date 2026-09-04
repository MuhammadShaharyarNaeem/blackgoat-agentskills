---
name: planning-and-task-breakdown
description: Squad-internal execution contract for breaking a spec or requirements set into ordered, implementable tasks with acceptance criteria and verification — loaded by agents via their Methodology Dependencies table; user-facing planning triggers belong to the /bgpdd-plan and /bgpdd-lite pipelines.
---

# Planning and Task Breakdown

Decompose work into small, verifiable tasks with explicit acceptance criteria — each implementable, testable, and verifiable in one focused session.

## Worker Execution Contract

The operational spine — follow it as written. Rationale, worked examples, and observed failures for every rule below: [deep dive](references/planning-deep-dive.md).

### Workflow

**Step 1: Enter Plan Mode.** Read-only: read the spec and relevant codebase, identify existing patterns, map dependencies, note risks. **Do NOT write code during planning.** Output: a plan document.

**Step 2: Identify the Dependency Graph.** You MUST map it in a `<dag_scratchpad>` XML block before writing tasks.

**Step 3: Slice Vertically.** One complete feature path at a time (schema + API + UI for one feature), never layer-by-layer; order is dependency-correct *and* slice-ordered.

**Step 4: Write Tasks.** Each task follows this structure:

```markdown
## Task [N]: [Short descriptive title]

**Description:** One paragraph explaining what this task accomplishes.

**Tags:** [MANDATORY on every task: exactly ONE domain tag — `[UI]` or `[API]` — plus overlay tags as applicable. A task with no domain tag cannot be routed to a builder; write the tag before the description.]

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

**Model tier:** [OPTIONAL — `opus` | `sonnet` | `haiku`. The planner's *recommendation* for the tier this task's builder should run at, based on the judgment the task demands, not its file count.]
```

#### Plans model effects, not artifacts

**A criterion, a dependency identifier, and a prerequisite all name the observable effect the consumer needs — never the existence of the code, module, or decision that will produce it.** No parser catches a violation. Five applications (rationale, example pairs, resolve-time vs run-time distinction: [deep dive](references/planning-deep-dive.md)):

1. **Acceptance criteria assert observable effects, never the existence of code.** Satisfiable by compiling, a file existing, a symbol being defined, or a type checking ⇒ **not a criterion**. Inexpressible as an observable effect ⇒ resolve that before writing the task.
2. **A `provides:` identifier names the effect a consumer needs, not the artifact.** Authoring vs effecting split across tasks (apply, run, deploy, publish) ⇒ separate identifiers: `x.module` for the artifact, `x` for the live resource, owned by the effecting task; consumers of the live resource consume `x`.
3. **External prerequisites are provisioned before they're consumed** — cloud identity/trust, secrets, infrastructure: by a lower-numbered task. **A human ruling is an external prerequisite too:** an earlier, explicitly scheduled task whose deliverable is *obtaining that ruling*, early enough to land before the blocked task's milestone. A `[BLOCKED]` tag with no earlier eliciting task is a scheduled stall, not a flag.
4. **An in-process observation is not the effect.** The criterion lives at the boundary — bytes a client received, pixels a person saw, state a device ended in — never at the handler, query, or assertion inside the serving process. **An in-process probe is never a valid `RUNTIME PROBE:` line.** Recognition list: owned by `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`, deliberately not restated here; enforced by `check_coverage.py`'s plan-mode `runtime-criterion` lint, byte-locked to `check_runtime_evidence.py`; proving tier: that skill's Tier 3.
5. **A criterion stays inside the change's control.** Never gate on: **(a)** diff shape (insertion/deletion counts, "insertions only") — frequently mechanically unsatisfiable; **(b)** a moving external ref — pin the commit, never a branch; **(c)** a value another party allocates (enum ordinal, id, port, reserved slot) — **unreserved until re-read at implementation time**, never frozen as a constant. Constrain the observable effect; where a mechanical shape genuinely is the proof, state the exact deviation it must produce.

| WHEN a task… | The plan MUST |
|---|---|
| interleaves durable state changes with an external effect (gateway, supplier, broker) | declare transaction boundaries, not just step order: which steps share a transaction, where each commit lands relative to the external call, the compensating action when follow-up work fails, how a crash-between-phases record is reclaimed |
| authors a gate, check script, or scanner | specify its **negative-half proof** in that task's Verification — the violation, the command, the failure it must produce (builder-side counterpart: `test-driven-development`'s negative-half proof rule) |

**Tag legend:** `[UI]` user-facing UI changes, `[API]` backend/service-side changes, `[SEC]` security-sensitive logic (auth, payments), `[EXT]` external APIs, `[BLOCKED]` unclear requirements. `[UI]` and `[API]` are DOMAIN tags — every task carries exactly one of them, with no exception for design, wiring, export, or search tasks (a "which builder touches the files" question always has an answer); `[SEC]`/`[EXT]`/`[BLOCKED]` are overlays that combine freely with either domain. Before finalizing, sweep every `## Task` heading's block and verify its `**Tags:**` line names exactly one domain tag — an untagged task is unroutable and a planning defect. Enforced mechanically by `check_coverage.py`'s plan-mode `domain-tag` lint (task tags AND milestone homogeneity — contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`); the coverage gate fails the plan on any violation.

**Model tier is a recommendation, not an assignment.** The planner proposes; the **Orchestrator** decides at dispatch and may override — it alone knows what the run has cost so far and what the milestone turned out to need. The rule the recommendation must not violate is **agent-audit Metric 14 (Model Assignment Fit)**: a verifier never runs below the producer it judges. That metric owns the rule and its rationale; do not restate it here. Omitting the field is legitimate — a task with no tier recommendation is a task the planner had no basis to call. Whatever tier the delegation actually runs at is recorded by `record_run.py --model`, which is mandatory on a delegation record (`{PLUGIN_ROOT}/pipeline-tools/SKILL.md`); the recorded tier is the one that ran, never the one recommended here.

**Scope rule for the four new fields:** Named identifiers, Pattern anchor, Boundary contracts, and Do NOT are mandatory for S/M tasks; proportional for L/XL or judgment-heavy tasks — but Named identifiers and Do NOT are always required.

**Task heading constraint:** `[N]` in `## Task [N]:` MUST be a bare positive integer (`## Task 6:`), never letter-suffixed or decorated (`## Task 6a:`, `## Task 6.1:`) — the coverage gate matches only `## Task <integer>:`; any other heading hides the whole task block from it. Split a requirement across tasks by distinct integers.

**Requirement coverage is many-to-one.** Every **Must-Have** requirement (`FR` and `NFR` alike) in a numbered `requirements.md` must appear in at least one task's "Requirements covered:" field — check before finalizing. Several IDs may, and often should, map to one task: a task is an independently implementable-and-verifiable unit of work, not one ID's worth.

**Step 5: Order and Checkpoint.** Arrange tasks so that:

1. Dependencies are satisfied, in the dependency-correct slice-ordered sequence of Steps 2–3
2. Each task leaves the system in a working state
3. Verification checkpoints occur after every 2-3 tasks
4. High-risk tasks are early (fail fast)
5. **A verification harness precedes the work it verifies.** An exit criterion depending on a gate that does not exist yet (browser/E2E harness, contract checker, fixture pipeline) ⇒ building that gate is its own earlier milestone.
6. **External prerequisites, human rulings included, are provisioned by a lower-numbered task** — corollary 3 above.
7. **In a multi-frontend workspace, shared package infrastructure precedes application work**: Foundation breakdowns MUST establish the shared packages (e.g. `packages/ui`); application tasks MUST list the shared UI component primitives as explicit prerequisites.

**Milestone economy**: only as many milestones as the dependency graph genuinely requires; a small deliverable gets ONE; never split for cosmetic organization. (Governs milestone/phase count, not rule 3's within-plan checkpoints.) The build pipeline executes a milestone's tasks **sequentially with a single builder** — never shape tasks or milestones around hoped-for parallel execution.

**Milestone domain homogeneity**: every milestone contains ONE domain only — all `[UI]` or all `[API]`; each milestone routes to a single specialized builder (Mason for `[API]`, Nova for `[UI]`), so a mixed milestone is rejected at build time as a planning defect. (Deliberately refines Step 3's "Slice Vertically" rule, per convention #8: a slice still governs ordering but spans a PAIR of adjacent milestones — `[API]` immediately followed by its `[UI]` — the seam expressed through `Boundary contracts:` `provides:`/`consumes:`, already enforced by the `consumes-provides` lint since the API tasks are lower-numbered.)

**Every milestone declares its verification surface with a `[vs:<surface>]` heading tag** — orthogonal to `[UI]`/`[API]`: the domain tag says *who builds it*, the surface tag says *what evidence proves it*. Both live on the heading — `### Milestone 3 — Order envelope [API] [vs:web+api]`. Lowercase by design, so it cannot collide with `[API]`.

| Tag | Use when the milestone's observable effect is… | Evidence it obligates |
|-----|-----------------------------------------------|-----------------------|
| `[vs:api]` | a response a client receives | out-of-process capture; contract surface (OpenAPI/Swagger) reachable |
| `[vs:ui]` | something a person sees | rendered evidence (screenshot / accessibility-tree read) |
| `[vs:web+api]` | a frontend behavior that depends on local APIs | both, **plus** the environment manifest recording which local URLs were used |
| `[vs:rmm]` | state on a device or agent | device/agent state read back, plus the service set that was running |
| `[vs:fn]` | an async effect (function, queue, cache, bus) | invocation plus the effect read back from its sink |
| `[vs:none]` | nothing a client, person, or device can observe | **a written justification line in the checkpoint** |

- **A missing or unknown surface tag is a planning defect**, mechanically: `next_milestone.py` returns `MIXED` (exit 1) and the build halts before Phase 1, as for a mixed or untagged domain.
- `[vs:none]` is an *explicit, reviewable claim*, not an exemption: write why nothing is observable.
- **Choose the surface from the requirement, not from the task list**: what does the requirement's grammatical subject *receive*? That names the surface.

**Every milestone and checkpoint declares at least one runtime exit criterion — command plus expected observable output.** An explicit `### Checkpoint:` block at each of rule 3's points holds, at minimum: all tests pass, application builds without errors, a `RUNTIME EXIT CRITERION` line, a `RUNTIME PROBE:` line, and review with human before proceeding. Level-3, never `## Checkpoint:` — a level-2 heading terminates the milestone block `next_milestone.py` extracts, silently dropping the exit criterion from the builder's brief.

The prose criterion carries intent; the machine-parseable `RUNTIME PROBE:` line beside it makes the criterion **executable by someone other than its author**. Shape:

```
RUNTIME EXIT CRITERION — run `<probe>`; expect `<observable>`
RUNTIME PROBE: start: `<start command>`; probe: `<probe command>`; expect-status: <N>; require-keys: <k1, k2>
```

- `start:` — how a user brings the application up; in a multi-service estate, name **every** required service and note their configuration is repointed at local URLs.
- `probe:` — the running system exercised as a user reaches it (started, driven, the asserted effect read back), including the *stateful* behavior the requirement names (a toggle actually toggled, a route actually navigated), never just the first paint. **No build, typecheck, bundle, source-search, or test-runner command; no in-process test client** (corollary 4) — the `runtime-criterion` lint rejects those shapes.
- `expect-status:` / `require-keys:` — required when the surface is `api`, `web+api`, or `fn`; they become the gate's `--expect-status` / `--require-key` arguments verbatim.
- `[vs:none]` — replace the probe fields with `justification: <why nothing is observable>`; the lint checks presence, not truth.
- No harness can run the probe yet ⇒ building it is its own earlier milestone (rule 5); until it exists the criterion is recorded BLOCKED — never PASS.

**Aggregate green is not an exit criterion.** "All tasks complete, tests pass, review approved" summarizes reports, not the system. NEVER mix an unfakeable criterion with an aggregate-green one in one exit condition — two gates, the unfakeable one last.

### Task Sizing

XS = 1 file · S = 1-2 · M = 3-5 · L = 5-8 · XL = 8+ (**too large — break it down**). An agent performs best on S and M — break anything L or larger. Also break a task down when any hold: more than one focused session (~2+ hours of agent work); acceptance criteria exceed 3 bullets; two or more independent subsystems (e.g., auth and billing); the title needs "and".

### Plan Document Output

Save the finalized plan to `.docs/{project-name}/implementation/plan.md`. Required structure (worked walkthrough: [deep dive](references/planning-deep-dive.md)):

- `# Implementation Plan: [Feature/Project Name]` title.
- `## Reference Documents` — instructs the builder to first read the Requirements (`.docs/{project-name}/requirements.md`) and the Architecture Blueprint (`.docs/{project-name}/design/detailed-design.md`; lite-originated plans link the governing stack contract(s) instead).
- `## Task List` — tasks grouped into slice-shaped milestones per **Milestone domain homogeneity** above (a deliberate refinement, per convention #8, of the plain one-milestone-per-slice framing): the first SLICE — its `[API]` milestone plus the immediately following `[UI]` milestone — is one thin end-to-end path, demoable at the pair's end; later slices widen. Each milestone is followed by its `### Checkpoint:` block. **If the first slice is NOT thin and end-to-end demoable, say so and why, in the plan** — the forcing constraint and where the first demoable artifact lands; the rule may bend to a real constraint, never silently.
- **Canonical milestone heading, both axes:** `### Milestone <n> — <Title> [<UI|API>] [vs:<surface>]` — level-3, `<n>` a bare integer, both tags in the heading itself. The build Orchestrator records completion by appending `[x]` to that line. Machine consumer: `pipeline-tools/next_milestone.py` parses these headings (level-2 `## Milestone <n>` tolerated for older plans) — full contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
- `## Risks and Mitigations` — table of risk / impact (High/Med/Low) / mitigation.
- `## Open Questions` — questions needing human input.

### Acceptance Matrix Output

Save to `.docs/{project-name}/acceptance-matrix.md` (lite-originated plans author **no** matrix — `/bgpdd-lite` declares `acceptance_matrix=null` and verifies through its coverage gate alone; a deliberate refinement of this section, per convention #8, scoped to that pipeline). **A separate artifact at a different scope from the plan**: the plan is per-milestone, this is per-feature. **Derive it from `requirements.md`, never from the task list you just wrote** — the same rule `shipping-and-launch` states for the launch checklist. On brownfield work, reconcile against the `QA/manual-testing.md` baseline (your Baseline Reconciliation duty) so existing behavior stays covered.

**Baseline Reconciliation table format (this skill owns it; the duty lives in the planner persona's §4).** A `## Baseline Reconciliation` section at the top of `acceptance-matrix.md`, one row per in-scope baseline case (on a brownfield **lite-originated** plan, which has no matrix, the same section lives in `plan.md` instead — same format, same lite divergence; the duty itself never lapses):

```markdown
| Case | Status | Disposition |
|------|--------|-------------|
| HP-01 | holds | regression — covered by scenario S2 |
| RR-03 | invalidated | removed by FR-4 (feature no longer batches) |
| EC-02 | superseded | replaced by FR-6's new limit; covered by scenario S5 |
```

`Status` ∈ `holds | invalidated | superseded`. Every `holds` row names the matrix scenario that carries it forward; every `invalidated`/`superseded` row names the requirement that decided it. A case that fits no row is an open question back to the Orchestrator — never a silent drop.

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
- **`Mode`** is `auto` or `manual`. Manual is first-class, but a manual step **passes only with recorded evidence** under `evidence/runtime/`; unevidenced, it reads as NOT RUN and blocks.
- **`[inverse of N]`** marks a step as the inverse of step N in the same scenario. Every state-changing step needs one, or an explicit `[no inverse: <reason>]` — legitimate one-way steps exist. Cover install→uninstall→**reinstall**.

Machine consumers: `check_acceptance_suite.py` gates execution at build Phase 5 and again at shipping Stage 1; `--lint-only` gates this artifact's structure at plan time, and `--lint-only --requirements <requirements.md>` additionally gates Must-Have FR/NFR→scenario coverage (`fr-scenario-coverage`). Full contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` — single authority, not restated here.

### Verification

Before starting implementation, confirm:

- [ ] Corollaries 1, 4, 5 hold for every criterion — existence verbs ("exists", "is defined", "compiles", "typechecks", "is documented", "is declared") rewritten as the effect guaranteed; nothing observable satisfiable in-process; no diff-shape, moving-ref, or allocated-value gate (enum/list-append criteria checked against the base file's actual trailing-separator state)
- [ ] Every task has a verification step; Step 4's WHEN-table obligations present — negative-half proofs (violation, command, required failure) and transaction boundaries (commit points, compensating action, crash reclamation; never step order alone)
- [ ] Every task cites its requirement ID(s); every Must-Have FR/NFR covered by at least one task
- [ ] Every `Dependencies:` field complete — exact task numbers or `None` (file paths live in `Named identifiers:`)
- [ ] Every non-`None` `Boundary contracts:` field leads with the `provides:`/`consumes:` line, each consumed identifier provided by a lower-numbered task (`consumes-provides` lint)
- [ ] Every task carries exactly one domain tag (`[UI]` or `[API]`); every milestone is domain-homogeneous and its heading carries a valid `[vs:<surface>]` tag; every `[vs:none]` justified in writing
- [ ] Checkpoints exist between major phases, each with a command + expected-output runtime exit criterion; no unfakeable/aggregate-green mix (Step 5)
- [ ] Every checkpoint's `RUNTIME PROBE:` conforms — `probe:` exercises the running system (no build, typecheck, search, or **test-runner** command); `expect-status`/`require-keys` present on `api`/`web+api`/`fn`
- [ ] Environment-readiness is the first task wherever a runnable environment is needed (dependencies installed, lockfile present, tooling available); a system-modifying action a worker cannot take is surfaced as a prerequisite, never silently assumed
- [ ] No task touches more than ~5 files
- [ ] **Artifact self-consistency — trace every assertion back to its support.** Coverage ("every requirement has a task") is not consistency. (Rationale and observed failures per check: [deep dive](references/planning-deep-dive.md#artifact-self-consistency--rationale-and-observed-failures).)
  - **Snippets are normative, not illustrative** — trace every reproduced sample against every governing invariant before any "follow verbatim" / "given as-is" label; where they disagree, fix the sample.
  - **A mandated capability needs its enabling declaration as an explicit task step** — declared where the consuming side resolves it (manifest/package descriptor, DI registration, module export, build config); a `Named identifiers:` listing is not an instruction.
  - **A declared gate needs its executor wiring as explicit task steps** — the exact `package.json` (or equivalent manifest) script name that invokes it **and** the CI job that runs it on PRs.
  - **A consumer without its producer is an unbuildable task** — plan the instruction that *produces* every generated artifact a task reads (build-tool flag, codegen step, config key); a task consuming another's contract (storage keys, envelope shape, wire casing, identifier format) **restates it inline**, or cites the producing task by number *and* reproduces the values.
  - **A convention must be declared at or before its first use** — in the task that first depends on it, never implicitly by a later one.
  - **No task's guard conflicts with existing upstream handling of the same input** — trace the field's full inbound path first; never specify both a sanitizer and a rejecting validator for one field.
- [ ] Two-implementers test per task: structurally different solutions possible from this text ⇒ a decision is missing — resolve it in the plan, not the build
- [ ] Stack Blueprint Verification: every stack-mandated pattern from the active stack methodology skills (Resource project isolation, `.ToResult()` envelopes, FluentValidation, …) maps to a concrete task
- [ ] Non-lite plans only: `acceptance-matrix.md` exists, derived from `requirements.md` not the task list; every Must-Have FR/NFR in at least one scenario (`fr-scenario-coverage` lint). Lite-originated plans author no matrix (see **Acceptance Matrix Output**), so this item and the next are N/A there
- [ ] Every state-changing step declares `[inverse of N]` or an explicit `[no inverse: <reason>]`; install paths cover uninstall **and** reinstall; every step names every store its assertion reads back; `manual` only where automation is genuinely impossible, not merely inconvenient
- [ ] Every High-impact risk traces to an acceptance or checkpoint criterion that would **detect** it — a Risks-table entry alone is unmitigated
- [ ] **The plan-time gate has been RUN, not predicted**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements <path>/requirements.md --plan <path>/plan.md` exits `0` against the finished plan; not complete while it exits non-zero. Its lint classes are the mechanical halves of the rules above — a `literal-count` failure means a criterion transcribed an inventory number ("the table has 5 entries") instead of asserting set-equality against its source; rewrite and re-run. Never hand off over a failing gate: the Orchestrator runs this exact gate next, and a failure there costs a full delegation round instead of a self-fix. (A run gate, not a re-read checklist — same conversion as `blackgoat-research` step 8.)
- [ ] The plan has been surfaced for human review — `<handoff>` to the Orchestrator when delegated, or directly to the user in the main session

### Escalate When

- Requirements missing, ambiguous, or contradictory → tag the affected task `[BLOCKED]` and report the ambiguity to the Orchestrator (manager) — never guess.
- A Must-Have requirement maps to no implementable task → escalate to the Orchestrator.
- Decomposition keeps producing XL tasks however you slice → escalate to the Orchestrator with the blocking constraint.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Planning deep dive](references/planning-deep-dive.md) — when (not) to use this skill, worked dependency-graph and slicing examples, the full plan-document template, the worked acceptance matrix, checkpoint blocks, Common Rationalizations, red flags, and the rationale and observed failures behind every contract rule above.
