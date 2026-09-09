# bgpdd-lite — Rationale & Worked Detail

On-demand depth for `bgpdd-lite/SKILL.md`. **Nothing here is a contract**: every rule this file explains is stated in the spine, and the spine wins on any apparent conflict. Read a section when you want to know *why* a rule is shaped the way it is, or when you are about to propose relaxing it.


## § No environment-manifest phase

`/bgpdd-build` Phase 0 already declares the fallback ("typically a `/bgpdd-lite` epic, which has no Phase 3.6" → author it now), so nothing is lost from the chain — only moved.

The cost is real and accepted: a lite epic buys no parallel install time for a missing capability, because it is small enough not to earn a phase for it.


## § The no-pipeline exit — what it covers

The exit covers BOTH a mechanical sweep (e.g. a rename; verify build green + a repo-wide search for the old term returns zero hits) AND a zero-decision copy-adapt of an established in-repo pattern (e.g. cloning an existing spec/test against a new target; verify it runs / `--list`).

Do NOT route into lite merely because a fresh build session follows: a good delegation prompt carries the context.


## § Why the Fit Check is written down

This check is Orchestrator self-restraint at the exact moment you want to proceed, so it does not stay a thought. Written down, the routing decision is auditable by every downstream reader — Alex, `/bgpdd-build`, `/bgpdd-shipping` — and a wrong "no" on question 1 is visible instead of inferred.


## § Initializing state at Phase 1

State used to be written only at Phase 3, so an interruption anywhere between the user's confirmation and Alex's return left `requirements.md` and `plan.md` on disk with no state file at all: exactly the orphan plan `/bgpdd-build` §1 HALTs on.


## § No acceptance matrix in lite

lite verifies through the Phase 2.5 FR/NFR coverage gate alone; the matrix plus `check_acceptance_suite.py` belong to `/bgpdd-plan` Phase 3.5, where the epic is large enough for a feature-scoped walkthrough to be worth authoring.


## § Why Scout, and why before Alex

lite has no design phase and no `detailed-design.md`, so there is no Aria to absorb research — the research has nowhere to land unless it is gathered before the plan is authored.


## § The lite state shape after Phase 3

For full `/bgpdd-plan`, `artifacts.design` is the path to `detailed-design.md`; the lite value is polymorphic with it, which is what keeps one schema serving both lanes.

Passing the **literal string** `null` (`--set-artifact design=null`) makes `update_state.py` store JSON `null`, exactly as `--set-cursor`/`--set-feature` do.

Documentation only — do not recreate by hand; `update_state.py` is the only sanctioned writer.

```json
{
  "schema": "1",
  "project_name": "{project-name}",
  "feature": null,
  "pipeline": "bgpdd-lite",
  "branch": null,
  "milestone_cursor": null,
  "artifacts": {
    "requirements": ".docs/{project-name}/requirements.md",
    "design": "{PLUGIN_ROOT}/dotnet-backend-patterns/SKILL.md",
    "plan": ".docs/{project-name}/implementation/plan.md",
    "acceptance_matrix": null
  },
  "blockers": [],
  "updated": "<ISO-8601 timestamp>"
}
```

## § Procedural memory — [2026-07-20] research goes to Scout, not the generic explorer

- **[2026-07-20]**: When Phase 0/1 needs codebase ground-truth gathering (fact-finding, reverse-engineering, API/pattern mapping) too large to run inline, delegate it to the squad's **Scout** persona (`{PLUGIN_ROOT}/../agents/scout.md`) — the designated disposable research worker — as the default, rather than the generic built-in `Explore` agent. Scout carries the squad's methodology dependencies; the built-in does not. This keeps lite consistent with `/bgpdd-discovery` and `/bgpdd-plan`, which already route research through Scout. Phase 0/1 stay Orchestrator-owned; this governs only sub-delegated research, and deviating to another researcher requires a stated reason.

## § What lite keeps and what it drops

Kept from the full pipeline: stable `FR`/`NFR` IDs in one continuous sequence, "Requirements covered:" traceability on every task, the `check_coverage.py` Must-Have gate, the game-tape checkpoint, and the `orchestrator-state.json` handoff that `/bgpdd-build` hydrates from.

Dropped: the interactive honing Q&A (no delegated Rex — Phase 1 drafts with the user directly), the architecture phase (no Aria and no `detailed-design.md` — `artifacts.design` carries a stack-contract path instead), the acceptance matrix, and the environment-manifest phase.

## § Baseline Reconciliation on a brownfield lite epic

Alex's Baseline Reconciliation duty never lapses. With no matrix to head, the table lives as a dedicated `## Baseline Reconciliation` section in `plan.md` — same format, owned by `planning-and-task-breakdown`, same lite divergence.

## § lite changes nothing downstream

`/bgpdd-shipping` still requires `/bgpdd-build` to complete first. The only downstream differences are the two `null` artifacts lite records — `acceptance_matrix` and sometimes `design` — which the build and shipping gates already branch on.
