---
name: bgpdd-lite
description: The mid-weight PDD pipeline for well-specified work. Skips honing and architecture (no Rex Q&A, no Aria) but keeps FR/NFR traceability and the coverage gate. You write mini-requirements with the Orchestrator, Alex plans, then /bgpdd-build executes. Use when the spec is already known (e.g. applying an established pattern or contract) and full /bgpdd-plan would be overkill.
trigger: /bgpdd-lite
---

# End-to-End Multi-Agent PDD: Lite Planning Phase (bgPDD-Lite)

This Standard Operating Procedure (SOP) is the mid-weight lane between a bare single-agent delegation and the full `/bgpdd-plan` pipeline: it keeps `FR`/`NFR` traceability, the coverage gate, the game tape and the `orchestrator-state.json` handoff, and drops the honing Q&A (no delegated Rex) and the architecture phase (no Aria, no `detailed-design.md`).

Rationale, worked examples and the illustrative state shape: `references/lite-rationale.md`, read on demand. The spine wins on any apparent conflict.

**When to use**: the spec is already known — an established pattern, a known stack contract, a mapped feature extended in a well-understood direction. **When NOT to use**: contested design, unclear acceptance criteria, cross-boundary contract changes, anything needing architectural decisions. The Phase 0 Fit Check is the enforced version of both lists; run it before committing to this lane.

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
- **Run log** (Contract §4's obligation, bound here; CLI contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`). Per delegation return — each Scout (Phase 2 research), Alex (Phase 2 and each coverage-fix round): `python {PLUGIN_ROOT}/pipeline-tools/scripts/record_run.py --log .docs/{project-name}/implementation/run-log.jsonl --pipeline bgpdd-lite --phase "<phase>" --event delegation --agent <name> --model <tier> --unit <the artifact the delegation produced, e.g. plan.md> …` (`--model` is mandatory on a delegation record — exit 2 without it; name the tier the delegation actually ran at, not the one recommended). Add `--rounds <this artifact's round number>` on a re-delegation, plus `--duration-s`/`--tokens-in`/`--tokens-out` (or `--from-json <the completion payload>`) from the runtime's completion notification and `--status` from the handoff. Into Phase 3's game tape: `python {PLUGIN_ROOT}/pipeline-tools/scripts/summarize_run.py --run-log .docs/{project-name}/implementation/run-log.jsonl --ledger .docs/{project-name}/implementation/gates.jsonl --markdown`.
- **Upgraded Chain-of-Thought**: Before transitioning between phases, you MUST explicitly verify that the required artifact exists AND satisfies its content contract — existence and non-emptiness alone are not sufficient. Content contracts:
  - `requirements.md`: has at least one Must-Have requirement carrying an `FR` ID and a Given/When/Then acceptance criterion.
  - `plan.md`: every task cites the requirement ID(s) it satisfies (a "Requirements covered:" field), and every task carries a verification step.
  - *Format*: the skeleton's line, extended to name which content-contract check(s) passed.
- **File Artifacts**: All artifacts must use standard GitHub markdown and be saved under `.docs/{project-name}/`. This folder is the project's persistent **Semantic Memory**.
- **Two-Tier Path Model**: **Tier 1** (`.docs/summary/{feature}/`) is the durable global knowledge base produced by `/bgpdd-discovery` — read-only for this pipeline. **Tier 2** (`.docs/{project-name}/`) is this enhancement's read-write workspace. Never write lite artifacts into Tier 1.
- **No environment-manifest phase** — a deliberate refinement of `/bgpdd-plan` Phase 3.6's rule (convention #8), not an omission: the manifest is deferred to `/bgpdd-build` Phase 0, which already declares this fallback. The accepted cost: `references/lite-rationale.md` § No environment-manifest phase.

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
  - No design decisions to make (question 1 = no) AND the whole deliverable is small enough that one well-briefed build session can carry it from a single delegation prompt → **no pipeline at all**: one Builder delegation plus a verification checklist. Two discriminators decide it: (a) will a fresh session genuinely need durable FR/plan artifacts, or does a good delegation prompt alone suffice? (b) are there 5+ independent acceptance criteria multiple parties must agree on? If BOTH are "no", take the no-pipeline exit — even when the deliverable will be authored in a separate build session. Worked examples: `references/lite-rationale.md` § The no-pipeline exit.
  - Otherwise → confirm the `{project-name}` work slug with the user AND, for brownfield work, the Tier-1 durable `{feature}` id (from `.docs/summary/`); record `null` for greenfield/unmapped work so the Phase 1 state write has a defined `feature` value. Then proceed to Phase 1.
- **Tier-1 drift, brownfield only (mechanical, convention #9)** — the consumer half of the provenance contract `bgpdd-discovery` §1 states, run once the `{feature}` id is confirmed: `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_tier1_provenance.py --verify-current --summary-root .docs/summary --feature {feature} --ledger .docs/{project-name}/implementation/gates.jsonl`. Drift warns, never halts: relay the artifact, its stamped sha and current HEAD, and let the user choose between planning against this map and re-running `/bgpdd-discovery`. `--allow-drift "<reason>"` records their explicit word — never supply it yourself.
- **The five answers are written down, verbatim — convention #9.** Carry the five questions and your one-line answer to each into `requirements.md` as a `## Fit Check` block at the very top of the file, before its first requirement (Phase 1 step 1 authors the file; this block is its opening section). If the answers change during drafting, the Phase 1 step 3 re-run of this check rewrites the block. Why written and not thought: `references/lite-rationale.md` § Why the Fit Check is written down.

### Phase 1: Mini-Requirements (Orchestrator + user, main session)
- **Delegated Agent**: None — no delegated Rex, no honing transcript. You draft the spec WITH the user in-session.
- **Format authority**: Rex's requirements template and ID rules in `{PLUGIN_ROOT}/../agents/rex.md` — stable `FR-n`/`NFR-n` IDs in one continuous sequence, MoSCoW tiers, and a Given/When/Then acceptance criterion on every Must-Have.
- **Workflow**:
  1. Draft `.docs/{project-name}/requirements.md` with the user using Rex's exact template, opening the file with the Phase 0 `## Fit Check` block before the first requirement. For known-contract work, transcribe the governing stack contract into FRs. When that contract is `{PLUGIN_ROOT}/dotnet-backend-patterns/SKILL.md`, the mini-requirements MUST record the sanctioned API mode (Mode A — CQRS+MediatR, or Mode B — REPR) as an explicit constraint line — workers may not infer it.
  2. **ESCALATION**: If the FR list exceeds ~10 Must-Haves, or ambiguity keeps surfacing as you draft, HALT and recommend `/bgpdd-plan` — the work has outgrown lite.
  3. **ESCALATION**: If the premise materially changes during drafting (e.g. infrastructure assumed to exist turns out not to), HALT and re-run the Phase 0 Fit Check — a scope-class change invalidates the original routing.
  4. The user confirms the file before you proceed to Phase 2.
  5. **Initialize state the moment the user confirms — deliberately earlier than the Phase 3 write this replaces (convention #8).** Record the artifacts that do not yet exist as `null`. Why here and not Phase 3: `references/lite-rationale.md` § Initializing state at Phase 1.
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
  2. Pass him the path to `.docs/{project-name}/requirements.md` **and** the relevant stack-contract skill path(s) (e.g. `{PLUGIN_ROOT}/dotnet-backend-patterns/SKILL.md`) as the architecture reference — there is NO `detailed-design.md` in lite. Instruct Alex that the plan's Reference Documents section links `requirements.md` and the governing stack contract(s) instead of a blueprint, and that he must carry the recorded API mode constraint from `requirements.md` into the plan's Reference Documents. Point him at the file's opening `## Fit Check` block: it records which decisions were declared already made.
  3. **CRITICAL PATHING**: Instruct Alex that he MUST save the checklist exactly to `.docs/{project-name}/implementation/plan.md` (NOT the root `.docs/{project-name}/` folder), using his planning methodology's format.
  3b. **NO acceptance matrix in lite** — state this explicitly in the brief: Alex MUST NOT author `.docs/{project-name}/acceptance-matrix.md`. A deliberate refinement (convention #8) of `planning-and-task-breakdown`'s **Acceptance Matrix Output** rule, written for full `/bgpdd-plan` epics. Phase 3 records `acceptance_matrix=null`, so downstream pipelines skip their matrix gates rather than reading the absence as a planning defect. On **brownfield** work Alex's Baseline Reconciliation duty still stands — the table goes in a `## Baseline Reconciliation` section of `plan.md` instead. Detail: `references/lite-rationale.md` § No acceptance matrix in lite.
  4. Read Alex's returned handoff, then **validate it before acting on it** (Contract §1's rule, bound here to this lane's returns — Alex, and each Scout below): save it to a file and run `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_handoff.py --handoff <that file> --persona <alex|scout> --repo . --since <the sha HEAD held when you launched the delegation> --ledger .docs/{project-name}/implementation/gates.jsonl`. **`--since` is always passed**; add `--fix-round` on a coverage-fix re-delegation. Exit 1 = his contract was not met — back to Alex under §2's 2-round bound, not on to the coverage gate.

- **Scout strategy (research that supports planning)** — the squad's Scout persona is the default researcher here, never the runtime's generic explore agent (`references/lite-rationale.md` § Procedural memory). If Alex would need ground truth that is in neither `requirements.md` nor the governing stack contract — an unmapped call site, an existing pattern's real shape, a dependency's actual API, a version or pricing fact — do NOT let Alex discover it mid-plan and do NOT gather it inline in your own context. Spawn **Scout** (`{PLUGIN_ROOT}/../agents/scout.md`) first:
  1. One bounded topic per Scout, each writing its own file under `.docs/{project-name}/research/`. Launch multiple Scouts **concurrently in one message**.
  2. Tell each Scout explicitly that it is researching, not designing — no architecture, no task breakdown, no plan authoring.
  3. Then delegate Alex, passing the research file paths alongside `requirements.md` and the stack contract.
  If the research keeps surfacing design decisions rather than facts, that is the signal lite was the wrong lane — apply the Phase 1 ESCALATION rule and route to `/bgpdd-plan`.

### Phase 2.5: Coverage Gate (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this check directly.
- **Workflow**:
  1. Run:
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --plan .docs/{project-name}/implementation/plan.md --ledger .docs/{project-name}/implementation/gates.jsonl`
     CLI contract (JSON shape, exit codes, parsing rules): `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
  2. Read the JSON object from stdout. Exit 0 = every Must-Have `FR`/`NFR` covered and no lint failed — report `warnings` and `uncovered_should` as non-blocking notes, then proceed. Exit 1 = one of the **two gating arrays** is non-empty, `uncovered` and/or `lint_failures` (a clean-coverage plan with a lint failure still exits 1). Exit 2 = the artifact failed its structural contract — a defect in the artifact, not the tool.
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
     **`artifacts.design` polymorphism (schema compatibility):** in lite, `design` is the governing stack-contract skill path, or JSON `null` when none applies — pass the **literal string** `null` (`--set-artifact design=null`). Downstream `/bgpdd-build` MUST inject a non-null `artifacts.design` into builder/Alex briefs as the architecture reference; when `null`, builders use `requirements` + `plan` only. Resulting state shape: `references/lite-rationale.md` § The lite state shape — documentation only; never hand-write that JSON.
  3. Prompt the user to open a fresh chat session and trigger **`/bgpdd-build`** to execute the plan (suggest the `auto` argument — lite work is well-specified by definition).
  4. **Close the branch — only when the user stops here.** **This lane creates no branch of its own**: it plans and hands off, and `/bgpdd-build` establishes and owns the working branch at its hydration. So there is a branch to close here only when the user already had one and stops at the plan; continuing to `/bgpdd-build` leaves it to build's close. When they do stop, run the skeleton's **`## Branch close`** section as written; this lane's only deltas are the capture path `.docs/{project-name}/implementation/evidence/post-merge.md` and, **as a deliberate divergence (convention #8) from `bgpdd-shipping` Step 4.5/6.6**, that this closes one *branch* rather than an *epic* — `orchestrator-state.json` survives.
