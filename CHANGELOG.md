# Changelog

All notable changes to the `blackgoat-agentskills` plugin are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [1.1.0] — 2026-07-24

### Added
- **Echo** (`agents/echo.md`) — Legacy QA Analyst: reverse-engineers existing feature behavior during `/bgpdd-discovery` Phase 4 (formerly Quinn Mode A).
- **Vera** (`agents/vera.md`) — Launch Verifier: executes the pre-launch checklist during `/bgpdd-shipping` Stage 1 (formerly Quinn Mode C).
- **Command Timeout Discipline (anti-hang)**: every agent (via `base-persona.md`) and every pipeline Orchestrator caps shell commands at an explicit 4-minute timeout; one justified retry/longer bound, second timeout escalates.
- **Cipher build-phase lane**: `[SEC]`-tagged milestones get a parallel Cipher security review alongside Luna in `bgpdd-build` Phase 3.
- **Vue 3 prevention-first contract** (`vue3-spa-patterns`): new Data Flow & Computation and Lifecycle & Reactivity Hygiene authoring rules (query-once/Map indexes, single-pass iteration, minimal reactivity, listener/timer teardown incl. `onDeactivated`, template refs, null-check discipline), plus `references/vue3-refactor-playbook.md` — the sequential zero-regression retrofit pass for legacy code.
- **Memory Hygiene rule** (`agent-orchestration-improve-agent`): at 3+ accumulated Procedural Memories, Forge elevates/generalizes/moves them instead of appending.
- **Contract evals**: `echo-qa-discovery-shape`, `vera-verification-shape`.

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
