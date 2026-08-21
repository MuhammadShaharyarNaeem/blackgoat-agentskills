---
name: bgpdd-lite
description: The mid-weight PDD pipeline for well-specified work. Skips honing and architecture (no Rex Q&A, no Aria) but keeps FR/NFR traceability and the coverage gate. You write mini-requirements with the Orchestrator, Alex plans, then /bgpdd-build executes. Use when the spec is already known (e.g. applying an established pattern or contract) and full /bgpdd-plan would be overkill.
trigger: /bgpdd-lite
---

# End-to-End Multi-Agent PDD: Lite Planning Phase (bgPDD-Lite)

The mid-weight lane between a bare single-agent delegation and full `/bgpdd-plan`.

- **Keeps**: stable `FR`/`NFR` IDs, "Requirements covered:" traceability, the coverage gate, game tape, and the `orchestrator-state.json` handoff.
- **Drops**: the interactive honing Q&A (no delegated Rex) and the architecture phase (no Aria, no `detailed-design.md`).
- **Use when**: the spec is already known — an established pattern, a known stack contract, a mapped feature extended in a well-understood direction.
- **Do NOT use for**: contested design, unclear acceptance criteria, cross-boundary contract changes, or anything needing architectural decisions. Phase 0's Fit Check routes those out.

Rationale and divergence reasoning: `references/lite-pipeline-rationale.md` (on demand).

---

## Path Resolution

`{PLUGIN_ROOT}` = the plugin's `skills/` directory (this skill's base directory is provided to you); personas live at `{PLUGIN_ROOT}/../agents/`. Every other path rule — list-before-reference, and the base-persona injection guard — has ONE home: `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md`, **Path Resolution** (inside your mandatory first read).

---

## 1. Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Phase 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.

The sections below carry ONLY this pipeline's refinements on top of that contract.

- **Strict Delegation — this pipeline's agents**: Alex (Phase 2), optionally Scout for bounded research. For non-interactive phases you MUST NOT roleplay the agent's work yourself.
  - **EXCEPTION — Phase 1 (Mini-Requirements)**: interactive with the user, in the main session. There is no delegated Rex.
- **Upgraded Chain-of-Thought**: before every phase transition, verify the required artifact exists AND satisfies its content contract. Existence and non-emptiness are not sufficient.

| Artifact | Content contract |
|---|---|
| `requirements.md` | at least one Must-Have carrying an `FR` ID and a Given/When/Then acceptance criterion |
| `plan.md` | every task cites the requirement ID(s) it satisfies (a "Requirements covered:" field) and carries a verification step |

- *Format*: "Thinking: Phase X requires Y. Checking `.docs/{project-name}/Y`... File exists and satisfies its content contract [state which check(s) passed]. Proceeding."
- **File Artifacts**: standard GitHub markdown, saved under `.docs/{project-name}/` — the project's persistent **Semantic Memory**.
- **Two-Tier Path Model**: **Tier 1** (`.docs/summary/{feature}/`) is the durable global knowledge base produced by `/bgpdd-discovery` — read-only here. **Tier 2** (`.docs/{project-name}/`) is this enhancement's read-write workspace. NEVER write lite artifacts into Tier 1.

## 2. Global Error Recovery

**The error-recovery skeleton lives in the Orchestrator Contract (§2)** — halt-and-escalate triggers, the circuit breaker you pass to every agent, no-nested-delegation, incremental persistence, context checkpoints, and 2-round bounded autonomous rejection. Read it there; it is not restated here.

This pipeline's only refinement: the artifacts subject to the 2-round bound are `requirements.md` and `plan.md`; checkpoint your own state to `.docs/{project-name}/orchestrator-state.json` via `update_state.py` (Phase 3) — never hand-edit.

---

## 3. Detailed Pipeline Phases

### Phase 0: Fit Check (Orchestrator)
- **Delegated Agent**: None — Orchestrator, before any artifact is written.
- **Workflow**: Answer five questions about the work:
  1. Are there **decisions to make**, or only work to do?
  2. Can the user alone state acceptance in **≤10 testable bullets**?
  3. Does it **cross a service boundary or shared contract**?
  4. Will anyone need to **trace why** later?
  5. Is it **multi-session**?
- **Routing**:

| WHEN | ROUTE TO |
|---|---|
| Localized defect | **`/bg-bugfix`** |
| "Yes" on Q1 (design decisions exist), OR 2+ "yes" across Q3/Q5, OR the design is contested | **HALT** → **`/bgpdd-plan`** (and `/bgpdd-discovery` first if brownfield and the feature is unmapped in `.docs/summary/`) |
| No design decisions (Q1 = no) AND one well-briefed build session can carry the whole deliverable from a single delegation prompt | **No pipeline at all**: one Builder delegation plus a verification checklist |
| Otherwise | Phase 1 (after confirming the slug and feature id, below) |

  - **The no-pipeline exit covers BOTH** a mechanical sweep (a rename; verify build green + a repo-wide search for the old term returns zero hits) AND a zero-decision copy-adapt of an established in-repo pattern (cloning an existing spec/test against a new target; verify it runs / `--list`). Two discriminators: (a) would a fresh session genuinely need durable FR/plan artifacts, or does a good delegation prompt suffice? (b) are there 5+ independent acceptance criteria multiple parties must agree on? BOTH "no" → take the exit, even when a separate build session authors the deliverable. NEVER route into lite merely because a fresh build session follows.
  - **Before Phase 1**: confirm the `{project-name}` work slug with the user AND — for brownfield work — the Tier-1 durable `{feature}` id (from `.docs/summary/`); record `null` for greenfield/unmapped work, so Phase 3's state write has a defined `feature` value.

### Phase 1: Mini-Requirements (Orchestrator + user, main session)
- **Delegated Agent**: None — no delegated Rex, no honing transcript. You draft the spec WITH the user in-session.
- **Format authority**: Rex's requirements template and ID rules in `{PLUGIN_ROOT}/../agents/rex.md` — stable `FR-n`/`NFR-n` IDs in one continuous sequence, MoSCoW tiers, and a Given/When/Then acceptance criterion on every Must-Have.
- **Workflow**:
  1. Draft `.docs/{project-name}/requirements.md` with the user using Rex's exact template. For known-contract work, transcribe the governing stack contract into FRs (e.g. Response Pattern FRs come straight from `{PLUGIN_ROOT}/dotnet-backend-patterns/SKILL.md`). When the governing contract is `dotnet-backend-patterns`, the mini-requirements MUST record the sanctioned API mode (Mode A — CQRS+MediatR, or Mode B — REPR) as an explicit constraint line — workers may not infer it.
  2. **ESCALATION**: FR list exceeds ~10 Must-Haves, or ambiguity keeps surfacing as you draft → HALT and recommend `/bgpdd-plan`; the work has outgrown lite.
  3. **ESCALATION**: the premise materially changes during drafting (e.g. infrastructure assumed to exist turns out not to) → HALT and re-run the Phase 0 Fit Check — a scope-class change invalidates the original routing.
  4. The user confirms the file before you proceed to Phase 2.

### Phase 2: Planning (Alex)
- **Delegated Agent**: **Alex** (Strategist)
- **Workflow**:
  1. Delegate to **Alex**. He reads his own methodology dependencies on-demand.
  2. Pass him `.docs/{project-name}/requirements.md` **and** the relevant stack-contract skill path(s) (e.g. `{PLUGIN_ROOT}/dotnet-backend-patterns/SKILL.md`) as the architecture reference — there is NO `detailed-design.md` in lite. Instruct him that the plan's Reference Documents section links `requirements.md` and the governing stack contract(s) instead of a blueprint, and MUST carry the API mode constraint recorded in `requirements.md`.
  3. **CRITICAL PATHING**: Alex MUST save the checklist exactly to `.docs/{project-name}/implementation/plan.md` (NOT the root `.docs/{project-name}/` folder), using his planning methodology's format.
  4. Read Alex's returned handoff.

- **Scout strategy (research that supports planning)**: lite has no Aria to absorb research. If Alex would need ground truth in neither `requirements.md` nor the governing stack contract — an unmapped call site, a pattern's real shape, a dependency's actual API, a version or pricing fact — do NOT let Alex discover it mid-plan and do NOT gather it inline in your own context. Spawn **Scout** (`{PLUGIN_ROOT}/../agents/scout.md`) first:
  1. One bounded topic per Scout, each writing its own file under `.docs/{project-name}/research/`. Launch multiple Scouts **concurrently in one message**.
  2. Tell each Scout explicitly that it is researching, not designing — no architecture, no task breakdown, no plan authoring.
  3. Then delegate Alex, passing the research file paths alongside `requirements.md` and the stack contract, so the Scout work is consumed rather than orphaned.
  Research that keeps surfacing design decisions rather than facts is the signal lite was the wrong lane — apply the Phase 1 ESCALATION rule and route to `/bgpdd-plan`.

### Phase 2.5: Coverage Gate (Orchestrator)
- **Delegated Agent**: None — Orchestrator.
- **Workflow**:
  1. Execute the coverage tool via a shell action, using the runtime's available Python 3 interpreter (`python` or `python3`):
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --plan .docs/{project-name}/implementation/plan.md`
     The full CLI contract (JSON shape, exit codes, parsing rules) lives in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
  2. Read the JSON object from stdout. Exit code 0 = every Must-Have `FR`/`NFR` is covered **and no lint failed** — report any `warnings` and `uncovered_should` entries to the user as non-blocking notes, then proceed to Phase 3. Exit code 1 = the `uncovered` array lists the Must-Have gaps, **or `lint_failures` is non-empty** — the five plan-mode lints (`literal-count`, `consumes-provides`, `path-hygiene`, `runtime-criterion`, `domain-tag`) gate exactly like a coverage gap, so exit 1 with an empty `uncovered` and populated `lint_failures` is a lint failure, not a tool defect. Exit code 2 = an artifact failed its structural contract (e.g. no task blocks, no Must-Have IDs) — treat this as a defect in the artifact, not the tool.
  3. On exit 1 or 2, re-delegate to **Alex** (a fresh delegation) quoting the exact `uncovered` IDs, every `lint_failures` entry verbatim (`check` / `task` / `detail`), and `warnings` (or the `error` message) — subject to the 2-round auto-fix bound in Global Error Recovery (§2). If unresolved after 2 rounds, halt and surface to the user. After each fix, re-run step 1 to verify.
  4. **If Python is unavailable: HALT** and surface the missing interpreter — do not substitute a manual judgment path for a mechanical gate.
  5. Once coverage is confirmed, proceed to Phase 3.

### Phase 3: Handoff to Build (Orchestrator)
- **Delegated Agent**: None — Orchestrator. No delegation, no halt.
- **Workflow**:
  1. **Game Tape checkpoint**: While your session context is still alive, append a `## bgpdd-lite — [date]` section to `.docs/{project-name}/implementation/game-tape.md` (create the file if it does not exist). At most 10 bullets, covering: user corrections made, agent failures/retries, re-delegation rounds and why, circuit-breaker trips, gates that were rubber-stamped vs. genuinely exercised, and this session's id/transcript path if the runtime exposes it.
  2. **State Persistence**: Write orchestrator state via `update_state.py` — never hand-edit JSON. Schema authority is `update_state.py` (schema version string `"1"`). If Python is unavailable: HALT and surface the missing interpreter.
     ```bash
     python {PLUGIN_ROOT}/pipeline-tools/scripts/update_state.py \
       --state .docs/{project-name}/orchestrator-state.json \
       --init --project-name "{project-name}" \
       --set-pipeline bgpdd-lite \
       --set-feature <feature|null> \
       --set-artifact requirements=.docs/{project-name}/requirements.md \
       --set-artifact design=<governing-stack-contract-skill-path|null> \
       --set-artifact plan=.docs/{project-name}/implementation/plan.md \
       --set-artifact acceptance_matrix=null
     ```
     **`artifacts.design` polymorphism (schema compatibility):** for full `/bgpdd-plan`, `design` is the path to `detailed-design.md`. For lite, it is the governing stack-contract skill path (e.g. `{PLUGIN_ROOT}/dotnet-backend-patterns/SKILL.md`), or JSON `null` when none applies — pass the **literal string** `null` (`--set-artifact design=null`) and `update_state.py` stores JSON `null`, exactly as `--set-cursor`/`--set-feature` do. Downstream `/bgpdd-build` MUST inject a non-null `artifacts.design` into builder/Alex briefs as the architecture reference; when `null`, builders use `requirements` + `plan` only.
     **`artifacts.acceptance_matrix` is always JSON `null` here** — lite authors no acceptance matrix. `/bgpdd-build` Phase 5 step 2.5c reads that `null` as "legitimately no matrix" and says so to the user rather than treating it as a planning defect; emitting it explicitly is what distinguishes a lite epic from a plan epic whose matrix went missing.
     Resulting shape (documentation only):
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
    "plan": ".docs/{project-name}/implementation/plan.md"
  },
  "blockers": [],
  "updated": "<ISO-8601 timestamp>"
}
```
  3. Prompt the user to open a fresh chat session and trigger **`/bgpdd-build`** to execute the plan (suggest the `auto` argument — lite work is well-specified by definition). Note: `/bgpdd-shipping` still requires build to complete first — lite changes nothing downstream.

## Procedural Memories (Learned Lessons)
- **[2026-07-20]**: When Phase 0/1 needs codebase ground-truth gathering (fact-finding, reverse-engineering, API/pattern mapping) too large to run inline, delegate it to the squad's **Scout** persona (`{PLUGIN_ROOT}/../agents/scout.md`) by default — NOT the generic built-in `Explore` agent, which does not carry the squad's methodology dependencies. Phase 0/1 stay Orchestrator-owned; this governs only sub-delegated research, and deviating to another researcher requires a stated reason.
