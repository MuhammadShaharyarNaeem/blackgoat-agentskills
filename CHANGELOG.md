# Changelog

All notable changes to the `blackgoat-agentskills` plugin are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **Background Execution (mandatory)** across all five pipeline Orchestrators (`bgpdd-discovery`, `bgpdd-plan`, `bgpdd-lite`, `bgpdd-build`, `bgpdd-shipping`): delegated agents are always launched in the background, never as a blocking call, and independent delegations are launched in a single message so they run concurrently. A blocking delegation makes the Orchestrator unreachable for the agent's entire run — the user cannot ask a question, correct a bad brief, or stop work heading the wrong way, and a long phase is indistinguishable from a hang. Orchestrators must also refuse to guess, predict, or fabricate a still-running agent's results.
- **Incremental Persistence (Anti-Loss)** in `agent-squad/base-persona.md` — therefore inherited by all 14 personas in every pipeline: create the output file with its section skeleton early, then fill and save section by section; mark unfinished sections in-file; resume from existing files rather than restarting or overwriting; and report `PARTIAL` rather than `COMPLETE` when sections remain. Reinforced with delegation-brief rules in all five pipelines, phrased per pipeline (document sections for discovery/plan/lite, code commits plus reports for build/shipping).
- **Scout-then-Aria split for `bgpdd-plan` Phase 2**, with a stated trigger (a large design surface — e.g. a full API contract *plus* costed infrastructure options *plus* a design system), a "do not split by reflex" guard for small features, and the rule that research Scouts write bounded per-topic files to `research/` which Aria then consumes so the work is not orphaned.
- **Scout strategy for `bgpdd-lite` Phase 2**: since lite has no design phase to absorb research, ground truth that is in neither `requirements.md` nor the governing stack contract is gathered by Scouts before Alex plans — with the tie-in that research surfacing *decisions* rather than *facts* is the signal lite was the wrong lane.
- **Scope block on `agent-squad/SKILL.md`** declaring it governs ad-hoc squad use, that a running `bgpdd-*` pipeline's own constraints are authoritative and this file is not loaded, that the pipeline wins on any disagreement, and that cross-cutting *subagent* rules belong in `base-persona.md` instead.
- **`ui-design-patterns` skill**: UI design execution contract — committed visual direction (tokens + signature element) before code, typography/spacing/color/motion discipline, surface modes, category-defaults-to-refuse (anti-generic-AI aesthetics), full state coverage, UX copy rules, and `references/design-critique.md` (Luna's screenshot-driven Nielsen-heuristic review axis). Loaded conditionally by Aria, Mason, and Luna. Adapted from Anthropic's frontend-design skill and pbakaus/impeccable (Apache-2.0).
- **`[UI]` task tag** in `planning-and-task-breakdown`; `bgpdd-build` Phase 3 instructs Luna to run the design-critique axis on `[UI]`-tagged milestones.

- **Learning triage 2026-07-26 — enforcement mechanisms for unverified gates.** A 5-milestone build run reported clean while shipping four gate scripts wired to no `package.json` script and no CI job, hollow assertions no gate had ever been shown to reject, a test report recording PASS from file existence with invented specifics, and three milestones committed over standing `Request changes`. The existing prose rules ("green is not evidence", the `blockers` ledger) were in force and were followed past, so this pass adds checkable artifacts and hard preconditions rather than restatements:
  - **Negative-half proof** (`test-driven-development`, `planning-and-task-breakdown`): no gate or check script is trusted until observed FAILING on a deliberate violation, with the failure output captured. Planned as an explicit task Verification step; enforced in the TDD checklist.
  - **Gate executor wiring** (`planning-and-task-breakdown`): a plan may not declare a verification script without also specifying the manifest script name and the CI job that run it, as their own task steps.
  - **Mechanical commit gate** (`bgpdd-build` §1): the milestone commit's preconditions are two file reads — latest `review-report.md` verdict is `Approve` and postdates the last diff, and `orchestrator-state.json`'s `blockers` array is empty for the milestone.
  - **Remediation is a cycle, not a tail** (`bgpdd-build` Phase 3): a Critical/Important fix re-enters Phase 2 (Quinn re-tests) and Phase 3 (Luna re-reviews the remediation diff), exiting only on `Approve` against the current diff, bounded by the contract's 2-round rule.
  - **Remediation fidelity** (`code-review-and-quality`): a fix is verified against the rule the finding protects, not the finding's literal text — a placeholder route that closes a "missing route" finding is rejected.
  - **Evidence-bearing PASS lines** (`quinn.md`, `bgpdd-build` Phase 6): every `test-report.md` PASS and every game-tape exit criterion embeds the verbatim command and its captured output; no pasted output, no claim.
  - **Gates you author fail closed** (`agent-squad/base-persona.md`): any code producing a verdict must read its contracted evidence input and treat absence/emptiness/unreadability as FAIL/DENY — never a permissive default, never a synthetic stand-in.
- **Learning triage 2026-07-26 — build-correctness rules.** Literal values copied from the governing artifact, never defaulted (`mason.md`); composition-root reachability and fixture-identity mock fidelity (`test-driven-development`); consumer-without-producer and harness-before-features planning rules (`planning-and-task-breakdown`); composable singleton scoping, page-root `data-test` IDs, executed `vue-tsc --noEmit`, and the no-fallback 401 refresh path (`vue3-spa-patterns`).

### Changed
- **README Core Concepts** is now five ideas rather than four, adding **Background delegation** (with incremental persistence as its paired rule).
- **`bgpdd-build` §1 Git Workflow** no longer says milestone fixes are merely "re-verified" — it names the Phase 3 step 4 re-verification cycle explicitly and gates the commit on it.
- **`planning-and-task-breakdown` `Boundary contracts:` task field** now covers contracts a task *consumes* as well as produces, including storage mechanism and key names, and requires values restated inline even when an earlier task declared them.

### Fixed
- **Removed the stale "you cannot message a running agent" claim** from all five pipelines and from README Core Concept 2. The runtime does support continuing an already-spawned agent, so the pipelines now prefer sending a follow-up message to an existing agent over re-briefing a fresh one when work must continue with its context intact.
- **`base-persona.md`'s "When your task is complete: save your final output"** wording actively taught deferred writing — the exact behaviour that loses an entire run on interruption. Step 1 now requires progressive writing and points at the new Incremental Persistence section.
- `bgpdd-shipping` and `bgpdd-discovery` were missing the delegation-durability rules their sibling pipelines received, which would have shipped contradictory delegation guidance inside one release.

## [1.1.0] — 2026-07-24

### Added
- **Echo** (`agents/echo.md`) — Legacy QA Analyst: reverse-engineers existing feature behavior during `/bgpdd-discovery` Phase 4 (formerly Quinn Mode A).
- **Vera** (`agents/vera.md`) — Launch Verifier: executes the pre-launch checklist during `/bgpdd-shipping` Stage 1 (formerly Quinn Mode C).
- **Command Timeout Discipline (anti-hang)**: every agent (via `base-persona.md`) and every pipeline Orchestrator caps shell commands at an explicit 4-minute timeout; one justified retry/longer bound, second timeout escalates.
- **Cipher build-phase lane**: `[SEC]`-tagged milestones get a parallel Cipher security review alongside Luna in `bgpdd-build` Phase 3.
- **Vue 3 prevention-first contract** (`vue3-spa-patterns`): new Data Flow & Computation and Lifecycle & Reactivity Hygiene authoring rules (query-once/Map indexes, single-pass iteration, minimal reactivity, listener/timer teardown incl. `onDeactivated`, template refs, null-check discipline), plus `references/vue3-refactor-playbook.md` — the sequential zero-regression retrofit pass for legacy code.
- **Memory Hygiene rule** (`agent-orchestration-improve-agent`): at 3+ accumulated Procedural Memories, Forge elevates/generalizes/moves them instead of appending.
- **Contract evals**: `echo-qa-discovery-shape`, `vera-verification-shape`, `dep-ship-decision-shape`.

### Changed
- **Quinn** is now a single-purpose build-phase QA Tester (`phase: 5 — Testing`); the three-mode persona is retired. Delegations for discovery QA go to Echo, launch verification to Vera.
- **Max** trigger widened: `bgpdd-build` Phase 4 also fires on performance findings below Critical/Important; his persona no longer claims he is "never invoked automatically."
- **Wake-up loads trimmed**: `planning-and-task-breakdown` deduplicated; `luna.md`/`mason.md` defer to their Always-loaded methodologies; Mason's and Quinn's dated Procedural Memories elevated into undated persona rules (Abstraction Rule).
- **`blackgoat-research`** split into Mode 1 (Blueprint) / Mode 2 (Scoped Advisory) so advisor-Aria in `bgpdd-build` never overwrites a signed-off `detailed-design.md`.
- Squad-internal descriptions for `blackgoat-research` and `blackgoat-idea-honing` (trigger-collision fix).

### Fixed
- `bgpdd-plan` and `bgpdd-discovery` were missing the CRITICAL CIRCUIT BREAKER and NO NESTED DELEGATION delegation rules their sibling pipelines carry (audit Metric 13 Blocker).
- `bgpdd-shipping` was missing the base-persona path-injection guard (the recurring "base-persona missing" defect).
- Stale "Mode B" wording in the `quinn-test-report-shape` eval.

## [1.0.0]

Initial release: the agent squad (13 personas), the PDD pipelines (`/bgpdd-discovery`, `/bgpdd-plan`, `/bgpdd-lite`, `/bgpdd-build`, `/bgpdd-shipping`), `/bg-bugfix`, methodology skills, deterministic coverage gates (`pipeline-tools`), and the eval harness.
