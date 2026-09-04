---
name: bgpdd-lite
description: The mid-weight PDD pipeline for well-specified work. Skips honing and architecture (no Rex Q&A, no Aria) but keeps FR/NFR traceability and the coverage gate. You write mini-requirements with the Orchestrator, Alex plans, then /bgpdd-build executes. Use when the spec is already known (e.g. applying an established pattern or contract) and full /bgpdd-plan would be overkill.
trigger: /bgpdd-lite
---

# End-to-End Multi-Agent PDD: Lite Planning Phase (bgPDD-Lite)

This Standard Operating Procedure (SOP) is the mid-weight lane between a bare single-agent delegation and the full `/bgpdd-plan` pipeline. It keeps the plugin's spine — stable `FR`/`NFR` IDs, "Requirements covered:" traceability, the coverage gate, game tape, and the `orchestrator-state.json` handoff — while dropping the interactive honing Q&A (no delegated Rex) and the architecture phase (no Aria, no `detailed-design.md`).

**When to use**: the spec is already known — applying an established pattern, implementing a known stack contract, extending a mapped feature in a well-understood direction. **When NOT to use**: contested design, unclear acceptance criteria, cross-boundary contract changes, or anything needing architectural decisions — run the Phase 0 Fit Check below before committing; it routes those cases out.

---

## 1. Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Phase 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.
>
> Then read `{PLUGIN_ROOT}/agent-squad/pipeline-skeleton.md` — the shared pipeline skeleton (path resolution, error recovery, upgraded chain of thought, game tape). Refinements below override the skeleton only where labelled (convention #8).

The sections below carry ONLY this pipeline's refinements on top of that contract.

- **Strict Delegation — this pipeline's agents**: Alex (Phase 2), and optionally Scout for bounded research. For non-interactive phases you MUST NOT roleplay the agent's work yourself.
  - **EXCEPTION — Phase 1 (Mini-Requirements)**: Requirements drafting in lite is interactive (with the user, in the main session). There is no delegated Rex — see Phase 1 below.
- **Mechanical gates**: the missing-interpreter HALT and the never-simulate-a-pass rule are the Orchestrator Contract §1's; the gates below neither restate nor soften them.
- **Upgraded Chain-of-Thought**: Before transitioning between phases, you MUST explicitly verify that the required artifact exists AND satisfies its content contract — existence and non-emptiness alone are not sufficient. Content contracts:
  - `requirements.md`: has at least one Must-Have requirement carrying an `FR` ID and a Given/When/Then acceptance criterion.
  - `plan.md`: every task cites the requirement ID(s) it satisfies (a "Requirements covered:" field), and every task carries a verification step.
  - *Format*: "Thinking: Phase X requires Y. Checking `.docs/{project-name}/Y`... File exists and satisfies its content contract [state which check(s) passed]. Proceeding."
- **File Artifacts**: All artifacts must use standard GitHub markdown and be saved under `.docs/{project-name}/`. This folder is the project's persistent **Semantic Memory**.
- **Two-Tier Path Model**: **Tier 1** (`.docs/summary/{feature}/`) is the durable global knowledge base produced by `/bgpdd-discovery` — read-only for this pipeline. **Tier 2** (`.docs/{project-name}/`) is this enhancement's read-write workspace. Never write lite artifacts into Tier 1.
- **No environment-manifest phase.** lite has no counterpart to `/bgpdd-plan` Phase 3.6 (environment manifest + capability preflight) — a deliberate refinement of that phase's rule (convention #8), not an omission: the manifest is deferred to `/bgpdd-build` Phase 0, which already declares this fallback ("typically a `/bgpdd-lite` epic, which has no Phase 3.6" → author it now). The cost is real and accepted — a lite epic buys no parallel install time for a missing capability, because it is small enough not to earn a phase for it.

## 2. Global Error Recovery

This pipeline's only refinement on the skeleton's Error Recovery section: the artifacts subject to the 2-round bound are `requirements.md` and `plan.md`; checkpoint your own state to `.docs/{project-name}/orchestrator-state.json` via `update_state.py` (initialized at Phase 1 step 5, updated at Phase 3) — never hand-edit.

---

## 3. Detailed Pipeline Phases

### Phase 0: Fit Check (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this check directly, before any artifact is written.
- **Workflow**: Answer five questions about the work:
  1. Are there **decisions to make**, or only work to do?
  2. Can the user alone state acceptance in **≤10 testable bullets**?
  3. Does it **cross a service boundary or shared contract**?
  4. Will anyone need to **trace why** later?
  5. Is it **multi-session**?
- **Routing**:
  - Localized defect → route to **`/bgpdd-bugfix`** instead.
  - A "yes" on question 1 (design decisions exist), OR 2+ "yes" across questions 3/5, OR the design is contested → **HALT** and route to **`/bgpdd-plan`** (and `/bgpdd-discovery` first if the work is brownfield and the feature is unmapped in `.docs/summary/`).
  - No design decisions to make (question 1 = no) AND the whole deliverable is small enough that one well-briefed build session can carry it from a single delegation prompt → **no pipeline at all**: one Builder delegation plus a verification checklist. This covers BOTH a mechanical sweep (e.g. a rename; verify build green + a repo-wide search for the old term returns zero hits) AND a zero-decision copy-adapt of an established in-repo pattern (e.g. cloning an existing spec/test against a new target; verify it runs / `--list`). Two discriminators decide it: (a) will a fresh session genuinely need durable FR/plan artifacts to build this, or does a good delegation prompt alone suffice? (b) are there 5+ independent acceptance criteria that multiple parties must agree on? If BOTH are "no", take the no-pipeline exit — even when the deliverable will be authored in a separate build session. Do NOT route into lite merely because a fresh build session follows; a good delegation prompt carries the context.
  - Otherwise → confirm the `{project-name}` work slug with the user AND — for brownfield work — the Tier-1 durable `{feature}` id (from `.docs/summary/`); record `null` for greenfield/unmapped work, so the Phase 1 state write has a defined `feature` value. Then proceed to Phase 1.
- **The five answers are written down, verbatim — convention #9.** This check is Orchestrator self-restraint at the exact moment you want to proceed, so it does not stay a thought: carry the five questions and your one-line answer to each into `requirements.md` as a `## Fit Check` block at the very top of the file, before its first requirement (Phase 1 step 1 authors the file; this block is its opening section). Written down, the routing decision is auditable by every downstream reader — Alex, `/bgpdd-build`, `/bgpdd-shipping` — and a wrong "no" on question 1 is visible instead of inferred. If the answers change during drafting, the Phase 1 step 3 re-run of this check rewrites the block.

### Phase 1: Mini-Requirements (Orchestrator + user, main session)
- **Delegated Agent**: None — no delegated Rex, no honing transcript. You draft the spec WITH the user in-session.
- **Format authority**: Rex's requirements template and ID rules in `{PLUGIN_ROOT}/../agents/rex.md` — stable `FR-n`/`NFR-n` IDs in one continuous sequence, MoSCoW tiers, and a Given/When/Then acceptance criterion on every Must-Have.
- **Workflow**:
  1. Draft `.docs/{project-name}/requirements.md` with the user using Rex's exact template, opening the file with the Phase 0 `## Fit Check` block before the first requirement. For known-contract work, transcribe the governing stack contract into FRs (e.g. Response Pattern FRs come straight from `{PLUGIN_ROOT}/dotnet-backend-patterns/SKILL.md`). When the governing contract is `dotnet-backend-patterns`, the mini-requirements MUST record the sanctioned API mode (Mode A — CQRS+MediatR, or Mode B — REPR) as an explicit constraint line — workers may not infer it.
  2. **ESCALATION**: If the FR list exceeds ~10 Must-Haves, or ambiguity keeps surfacing as you draft, HALT and recommend `/bgpdd-plan` — the work has outgrown lite.
  3. **ESCALATION**: If the premise materially changes during drafting (e.g. infrastructure assumed to exist turns out not to), HALT and re-run the Phase 0 Fit Check before continuing — a scope-class change invalidates the original routing.
  4. The user confirms the file before you proceed to Phase 2.
  5. **Initialize state the moment the user confirms — deliberately earlier than the Phase 3 write this replaces (convention #8).** State used to be written only at Phase 3, so an interruption anywhere between here and Alex's return left `requirements.md` and `plan.md` on disk with no state file at all: exactly the orphan plan `/bgpdd-build` §1 HALTs on. Write it now instead, with the artifacts that do not yet exist recorded as `null`:
     ```bash
     python {PLUGIN_ROOT}/pipeline-tools/scripts/update_state.py \
       --state .docs/{project-name}/orchestrator-state.json \
       --init --project-name "{project-name}" \
       --set-pipeline bgpdd-lite \
       --set-feature <feature|null> \
       --set-artifact requirements=.docs/{project-name}/requirements.md \
       --set-artifact plan=null \
       --set-artifact design=null \
       --set-artifact acceptance_matrix=null
     ```
     Phase 3 then **updates** this file (cursor and the artifacts Alex produced); it does not re-init it.

### Phase 2: Planning (Alex)
- **Delegated Agent**: **Alex** (Strategist)
- **Workflow**:
  1. Delegate to the **Alex** agent. He reads his own methodology dependencies on-demand.
  2. Pass him the path to `.docs/{project-name}/requirements.md` **and** the relevant stack-contract skill path(s) (e.g. `{PLUGIN_ROOT}/dotnet-backend-patterns/SKILL.md`) as the architecture reference — there is NO `detailed-design.md` in lite. Instruct Alex that the plan's Reference Documents section links `requirements.md` and the governing stack contract(s) instead of a blueprint, and that he must carry the recorded API mode constraint from `requirements.md` into the plan's Reference Documents. Point him at the file's opening `## Fit Check` block as the record of why this work is in the lite lane — it is what tells him which decisions were declared already made.
  3. **CRITICAL PATHING**: Instruct Alex that he MUST save the checklist exactly to `.docs/{project-name}/implementation/plan.md` (NOT the root `.docs/{project-name}/` folder), using his planning methodology's format.
  3b. **NO acceptance matrix in lite** — state this explicitly in the brief: Alex MUST NOT author `.docs/{project-name}/acceptance-matrix.md`. A deliberate refinement (convention #8) of `planning-and-task-breakdown`'s **Acceptance Matrix Output** rule, which is written for full `/bgpdd-plan` epics: lite verifies through the Phase 2.5 FR/NFR coverage gate alone, and the matrix plus `check_acceptance_suite.py` belong to `/bgpdd-plan` Phase 3.5. Phase 3 records this as `acceptance_matrix=null`, so downstream pipelines skip their matrix gates rather than reading the absence as a planning defect. On **brownfield** lite work Alex's Baseline Reconciliation duty still stands: instruct him to write the table as a dedicated `## Baseline Reconciliation` section in `plan.md` instead of at the top of the (absent) matrix — same format, owned by `planning-and-task-breakdown`, same lite divergence.
  4. Read Alex's returned handoff.

- **Scout strategy (research that supports planning)**: lite has no design phase and no `detailed-design.md`, so there is no Aria to absorb research. If Alex would need ground truth that is in neither `requirements.md` nor the governing stack contract — an unmapped call site, an existing pattern's real shape, a dependency's actual API, a version or pricing fact — do NOT let Alex discover it mid-plan and do NOT gather it inline in your own context. Spawn **Scout** (`{PLUGIN_ROOT}/../agents/scout.md`) first:
  1. One bounded topic per Scout, each writing its own file under `.docs/{project-name}/research/`. Launch multiple Scouts **concurrently in one message**.
  2. Tell each Scout explicitly that it is researching, not designing — no architecture, no task breakdown, no plan authoring.
  3. Then delegate Alex, passing the research file paths alongside `requirements.md` and the stack contract, so the Scout work is consumed rather than orphaned.
  If the research keeps surfacing design decisions rather than facts, that is the signal lite was the wrong lane — apply the Phase 1 ESCALATION rule and route to `/bgpdd-plan`.

### Phase 2.5: Coverage Gate (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this check directly.
- **Workflow**:
  1. Execute the coverage tool via a shell action, using the runtime's available Python 3 interpreter (`python` or `python3`):
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --plan .docs/{project-name}/implementation/plan.md --ledger .docs/{project-name}/implementation/gates.jsonl`
     The full CLI contract (JSON shape, exit codes, parsing rules) lives in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
  2. Read the JSON object from stdout. Exit code 0 = every Must-Have `FR`/`NFR` is covered and no lint failed — report any `warnings` and `uncovered_should` entries to the user as non-blocking notes, then proceed to Phase 3. Exit code 1 = at least one of the **two gating arrays** is non-empty: `uncovered` (Must-Have coverage gaps) and/or `lint_failures` (lint violations) — a clean-coverage plan with a lint failure still exits 1. Exit code 2 = an artifact failed its structural contract (e.g. no task blocks, no Must-Have IDs) — treat this as a defect in the artifact, not the tool.
  3. On exit 1 or 2, re-delegate to **Alex** (a fresh delegation) quoting the exact `uncovered` IDs **and** the `lint_failures` entries, plus `warnings` (or the `error` message) — subject to the 2-round auto-fix bound in Global Error Recovery (§2). If unresolved after 2 rounds, halt and surface to the user. After each fix, re-run step 1 to verify.
  4. Once coverage is confirmed, proceed to Phase 3.

### Phase 3: Handoff to Build (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this phase directly. No delegation, no halt.
- **Workflow**:
  1. **Game Tape checkpoint**: write it at the skeleton's default cadence and cap — once per run, at most 10 bullets, heading `## bgpdd-lite — [date]`. This pipeline adds no refinement to that section.
  2. **State Persistence**: Update the state file Phase 1 step 5 initialized — via `update_state.py`, never by hand-editing JSON, and **without `--init`** (this is an update of the artifacts Alex produced, not a fresh file). Schema authority is `update_state.py` (schema version string `"1"`).
     ```bash
     python {PLUGIN_ROOT}/pipeline-tools/scripts/update_state.py \
       --state .docs/{project-name}/orchestrator-state.json \
       --set-artifact design=<governing-stack-contract-skill-path|null> \
       --set-artifact plan=.docs/{project-name}/implementation/plan.md
     ```
     `pipeline`, `project_name`, `feature`, `requirements` and `acceptance_matrix=null` were set at Phase 1 step 5 and are not rewritten here.
     **`artifacts.design` polymorphism (schema compatibility):** for full `/bgpdd-plan`, `design` is the path to `detailed-design.md`. For lite, it is the governing stack-contract skill path (e.g. `{PLUGIN_ROOT}/dotnet-backend-patterns/SKILL.md`), or JSON `null` when none applies — pass the **literal string** `null` (`--set-artifact design=null`) and `update_state.py` stores JSON `null`, exactly as `--set-cursor`/`--set-feature` do. Downstream `/bgpdd-build` MUST inject a non-null `artifacts.design` into builder/Alex briefs as the architecture reference; when `null`, builders use `requirements` + `plan` only. Resulting shape (documentation only):
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
  3. Prompt the user to open a fresh chat session and trigger **`/bgpdd-build`** to execute the plan (suggest the `auto` argument — lite work is well-specified by definition). Note: `/bgpdd-shipping` still requires build to complete first — lite changes nothing downstream.
  4. **Close the branch** (interactive; never delegated — Contract §1) — **only when the user stops here**; continuing to `/bgpdd-build` leaves the branch to build's close. **Deliberate divergence (convention #8) from `bgpdd-shipping` Step 4.5/6.6**: those close an *epic*, this one *branch*; `orchestrator-state.json` survives.
     - Read the base branch from the repo (`git symbolic-ref refs/remotes/origin/HEAD`, else its default), never guessing.
     - Offer exactly three: **merge locally**; **publish the branch and open a pull request through the runtime's tooling**; **keep the branch**. Discarding requires typing the branch name.
     - **After a merge, done is a capture (convention #9)**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture .docs/{project-name}/implementation/evidence/post-merge.md -- <the project's test command>`. Non-zero exit → report it; stop.
     - Worktree branch: offer to remove it after merging.

## Procedural Memories (Learned Lessons)
- **[2026-07-20]**: When Phase 0/1 needs codebase ground-truth gathering (fact-finding, reverse-engineering, API/pattern mapping) too large to run inline, delegate it to the squad's **Scout** persona (`{PLUGIN_ROOT}/../agents/scout.md`) — the designated disposable research worker — as the default, rather than the generic built-in `Explore` agent. Scout carries the squad's methodology dependencies; the built-in does not. This keeps lite consistent with `/bgpdd-discovery` and `/bgpdd-plan`, which already route research through Scout. Phase 0/1 stay Orchestrator-owned; this governs only sub-delegated research, and deviating to another researcher requires a stated reason.
