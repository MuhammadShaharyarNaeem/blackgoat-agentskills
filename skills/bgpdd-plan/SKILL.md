---
name: bgpdd-plan
description: Phase 1 of the Prompt-Driven Development SOP (Design & Architecture). Refines ideas, conducts research, and creates an implementation plan using Rex, Aria, and Alex.
trigger: /bgpdd-plan
---

# End-to-End Multi-Agent PDD: Planning Phase (bgPDD-Plan)

Orchestrator SOP taking a rough idea through requirements gathering (Rex), research and architecture (Aria), and task breakdown (Alex).

Rationale, failure histories, and divergence reasoning: `references/plan-pipeline-rationale.md` (on demand).

---

## Path Resolution

`{PLUGIN_ROOT}` = the plugin's `skills/` directory (this skill's base directory is provided to you); personas live at `{PLUGIN_ROOT}/../agents/`. Every other path rule — list-before-reference, and the base-persona injection guard — has ONE home: `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md`, **Path Resolution** (inside your mandatory first read).

---

## 1. Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Phase 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.

The sections below carry ONLY this pipeline's refinements on top of that contract.

- **Strict Delegation — this pipeline's agents**: Rex (Phase 1 Step B), Aria (Phase 2), Alex (Phase 3), optionally Scout (Phase 2 research split). Phase 2.5 is Orchestrator-run — no delegated agent. For non-interactive phases you MUST NOT roleplay the agent's work yourself.
  - **EXCEPTION — Phase 1 (Honing)**: interactive turn-by-turn Q&A — **you (the main session) run it** with Rex's persona as the behavioral spec.
- **Upgraded Chain-of-Thought**: before every phase transition, verify the required artifact exists AND satisfies its content contract. Existence and non-emptiness are not sufficient.

| Artifact | Content contract |
|---|---|
| `requirements.md` | at least one Must-Have carrying an `FR` ID and a Given/When/Then acceptance criterion |
| `detailed-design.md` | explicitly references the `FR` IDs it addresses AND contains a `## Divergence & Supersession Register`; `requirements.md` carries a matching supersession annotation for every superseded FR |
| `plan.md` | every task cites the requirement ID(s) it satisfies (a "Requirements covered:" field) and carries a verification step |

- *Format*: "Thinking: Phase X requires Y. Checking `.docs/{project-name}/Y`... File exists and satisfies its content contract [state which check(s) passed]. Proceeding."
- **File Artifacts**: standard GitHub markdown, saved under `.docs/{project-name}/` — the project's persistent **Semantic Memory**.

## 2. Global Error Recovery

**The error-recovery skeleton lives in the Orchestrator Contract (§2)** — halt-and-escalate triggers, the circuit breaker you pass to every agent, no-nested-delegation, incremental persistence, context checkpoints, and 2-round bounded autonomous rejection. Read it there; it is not restated here.

This pipeline's refinements:
- Artifacts under the 2-round bound: `requirements.md`, `detailed-design.md`, `plan.md`. Track the round count per artifact; after 2 rounds surface the flaw and both attempts to the user rather than re-delegating a third time.
- Phase 2.5 gets exactly **one** doubt-driven revision round (deliberately below DDD's 3-cycle bound), then escalate.
- `requirements.md` is legitimately mutated in Phase 2 by Aria — supersession annotations only.

## 3. Few-Shot Handoff Examples

At a phase-transition checkpoint, message the user in this shape:

> Phase 3 (Planning) is complete. Alex has saved the detailed task list to `.docs/my-app/implementation/plan.md`.
> **Blockers**: None.
> **Next Step**: Are you ready to proceed to Phase 4 (Game Tape Checkpoint)?

---

## 4. Folder Structure (Semantic Memory) — TWO TIERS

Two distinct memory scopes. Do not conflate them.

**Tier 1 — global project knowledge base** (`.docs/summary/`): built by **`/bgpdd-discovery`** (Iris, Scout, Echo) at project scope, persisted across enhancement cycles, indexed by durable feature id (`{feature}`, e.g. `slide`). This pipeline **consumes** it and never produces it — brownfield work runs `/bgpdd-discovery` first (Pre-Flight Check).
```text
.docs/summary/
├── context.md                     # Project-wide tech-stack context + Target Scope (Iris) — one file
└── {feature}/                     # Durable per-feature knowledge base (e.g. slide/)
    ├── overview.md                #   Synthesized cross-API overview (Echo)
    ├── {api}.md                   #   Per-API feature-fragment maps, one per API (Scout)
    └── QA/
        ├── code-workflow.md       #   Mermaid sequence diagrams & execution paths (Echo)
        └── manual-testing.md      #   Reverse-engineered manual test cases (Echo)
```

**Tier 2 — per-enhancement work dir** (`.docs/{project-name}/`): the isolated artifacts for **this** piece of work, `{project-name}` being the current enhancement's work slug (e.g. `slide-enhancement`). Produced by Rex/Aria/Alex; scoped to this cycle.
```text
.docs/{project-name}/
├── rough-idea.md          # Initial concept
├── honing-transcript.md   # Interactive Q&A transcript (Phase 1, main session)
├── requirements.md        # Finalized specification (Phase 1, Rex synthesis)
├── acceptance-matrix.md   # Feature-scoped walkthrough scenarios (Phase 3, Alex)
├── research/              # Technical research & findings (Aria)
├── design/                # System designs & Mermaid diagrams (Aria)
│   ├── detailed-design.md
│   └── design-review.md   # Phase 2.5 findings (Orchestrator)
├── implementation/        # Checklists (Alex)
│   ├── plan.md            # Dependency-mapped task list
│   └── game-tape.md       # Per-phase evidence checkpoints (Orchestrator, Phase 4)
└── orchestrator-state.json # Handoff state for bgpdd-build (Phase 4)
```

---

## 5. Detailed Pipeline Phases

> **Brownfield vs Greenfield**: the Pre-Flight Check applies **only** to brownfield (modifying an existing system). Greenfield → skip straight to Phase 1.

### Pre-Flight Check: Global Context Verification (Brownfield only)
- **Delegated Agent**: None — Orchestrator.
- **Purpose**: verify the Tier-1 knowledge base this pipeline consumes already exists. Discovery itself belongs to **`/bgpdd-discovery`**.
- **Workflow**:
  1. Brownfield or greenfield? Greenfield → skip this check, go to Phase 1.
  2. **Brownfield**: confirm `.docs/summary/context.md` exists AND `.docs/summary/{feature}/overview.md` exists for the feature being enhanced.
  3. **Either missing → HALT.** Instruct the user to run **`/bgpdd-discovery`** first, to map the global tech stack, per-API feature fragments, and legacy QA baseline. NEVER run discovery yourself or hand-author these files; resume Phase 1 only once the knowledge base is present.
  4. **Present** → confirm the `{feature}` id with the user (downstream phases read `.docs/summary/{feature}/`), then Phase 1.

### Phase 1: Honing & Requirements (HYBRID)
- **Behavioral spec**: `{PLUGIN_ROOT}/../agents/rex.md` (Rex, the Analyst) + `{PLUGIN_ROOT}/blackgoat-idea-honing/SKILL.md`
- **Hybrid split**: live Q&A in the main session; spec authoring delegated to an isolated Rex.

- **Step A — Interactive honing (YOU, the main session)**:
  1. Read Rex's persona (`agents/rex.md`) and the `blackgoat-idea-honing` methodology; adopt them as your behavior for this step.
  2. Save the user's rough idea to `.docs/{project-name}/rough-idea.md`. Brownfield: first read `.docs/summary/context.md` and `.docs/summary/{feature}/overview.md` (drill into `{api}.md` / QA files as needed) so your questions are grounded in the real system. Greenfield: these don't exist; skip.
  3. Ask **one targeted question at a time**, probing edge cases deeply; append each question and answer to `.docs/{project-name}/honing-transcript.md`. Use your runtime's structured multiple-choice question tool for clear multiple-choice decisions; otherwise ask in plain conversation.
  4. A complete requirements document supplied upfront does NOT skip honing — still review it for missing edge cases and drive it through the honing checkpoint.
  5. The transcript is final when the user confirms honing is complete.

- **Step B — Spec synthesis (delegate isolated Rex)**:
  6. Delegate to **Rex**, passing the paths to `.docs/{project-name}/honing-transcript.md`, `.docs/{project-name}/rough-idea.md`, and (brownfield) the `.docs/summary/{feature}/` knowledge base. Instruct him to synthesize `.docs/{project-name}/requirements.md` from the transcript using his requirements template.
  7. Read Rex's handoff. Unresolved **open questions** (he cannot ask the user directly) → relay them to the user, append answers to the transcript, re-delegate Rex. Loop until `requirements.md` is complete.
  8. Request user confirmation to transition to Phase 2.

### Phase 2: Research & Architecture (Aria)
- **Delegated Agent**: **Aria** (Architect)
- **Workflow**:
  1. Delegate to **Aria** (tell her the `{feature}` if brownfield).
  2. Instruct Aria to read `.docs/{project-name}/requirements.md` **and** `.docs/{project-name}/honing-transcript.md` (for intent nuance), and — **if brownfield** — `.docs/summary/{feature}/overview.md`, drilling into individual `.docs/summary/{feature}/{api}.md` files as the design requires. She then does her own additional research. Aria cannot delegate to Scout — she reads the existing maps.
  3. **CRITICAL PATHING**: Aria MUST write the final blueprint exactly to `.docs/{project-name}/design/detailed-design.md`.
  3b. **[UI] Design-direction sourcing**: if the requirements include user-facing UI, inject into Aria's brief the resolved paths to both `{PLUGIN_ROOT}/ui-design-patterns/SKILL.md` and its design-DB search tool (`{PLUGIN_ROOT}/ui-design-patterns/tools/design-db/scripts/search.py`), so she can source candidate directions per that skill's **Candidate sourcing** rule before committing the visual direction.
  4. Read Aria's returned handoff.
  5. **Iteration Checkpoint**: after Phase 2.5 completes, present Aria's design to the user **together with the Phase 2.5 gate findings** (`design/design-review.md`), and explicitly offer to bounce back to Phase 1 if research or the review uncovered new questions.

- **Splitting Phase 2 when the design surface is large** (recommended for substantial greenfield builds) — e.g. a complete API contract **plus** costed infrastructure options **plus** a design system:
  1. Spawn one or more **Scout** agents for the *bounded research* questions (the Orchestrator may spawn Scout; Aria may not). One topic per Scout, each with its own output file under `.docs/{project-name}/research/`. Launch them **concurrently in one message**. Tell each Scout explicitly it is researching, not designing — no architecture, no component or endpoint design.
  2. Then delegate **Aria** to author `.docs/{project-name}/design/detailed-design.md`, instructing her to read those research files as inputs so the Scout work is consumed, not orphaned.
  `detailed-design.md` stays the single authoritative blueprint Alex decomposes; research files are supporting detail it references. Small or well-bounded feature → one Aria delegation; do not split by reflex.

### Phase 2.5: Adversarial Design Review (Orchestrator)
- **Delegated Agent**: None — YOU run the Doubt-Driven Development cycle (`{PLUGIN_ROOT}/doubt-driven-development/SKILL.md`) on `detailed-design.md` before the design stands.
- **Workflow**:
  1. **Supersession-annotation lint (mechanical pre-step)**: before the adversarial pass, execute the coverage tool via a shell action, using the runtime's available Python 3 interpreter (`python` or `python3`):
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --design .docs/{project-name}/design/detailed-design.md`
     This is the **supersession-annotation lint** — not full FR→design coverage. It checks that every FR/NFR named in the design's `## Divergence & Supersession Register` carries its matching in-place supersession annotation in `requirements.md`. The full CLI contract (JSON shape, exit codes, parsing rules) lives in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`. Read the JSON object from stdout and fix any reported `lint_failures` (including `supersession-annotation`, and `fr-citation` when the script emits it) before proceeding.
     **If Python is unavailable: HALT** and surface the missing interpreter — do not substitute a manual judgment path for a mechanical gate.
  1b. **FR/NFR citation check (Orchestrator)**: independently verify that every Must-Have `FR`/`NFR` ID from `requirements.md` appears at least once in `detailed-design.md` (a citation, not necessarily a register row). If `check_coverage` design mode already reports `fr-citation` entries in `lint_failures`, treat those as authoritative and fix them; otherwise perform this citation scan yourself before the adversarial pass. An uncited Must-Have is a design gap — route back to Aria (counts as the Phase 2.5 revision round if unresolved).
  2. Run the doubt cycle **per-section** — the design exceeds DDD's one-read unit, so honor its decomposition rule. Always extract: every money-moving sequence, every state machine, every read-then-decide gate.
  3. Each DOUBT prompt carries this fixed attack list **verbatim**, in addition to DDD's adversarial prompt:
     1. **Crash windows** — for each sequence that moves money and calls an external system, enumerate "process dies after step N" for every N; each must name a recovery mechanism (sweeper / reconciliation / idempotent retry).
     2. **Reversals** — every journal entry / money movement has a defined reversal or an explicit "irreversible, because…".
     3. **Races** — every read-then-decide gate (quota, balance, rate) names its serialization mechanism and a two-concurrent-requests test.
     4. **Trust-boundary amounts** — any externally-supplied number that moves money is validated against an internal record.
     5. **State-machine self-consistency** — every compensation/failure path only performs transitions its own state machine permits; and any declared set of numbered assertions, invariants, or allow-lists is walked as a set — every pair mutually satisfiable, every member referentially valid.
     6. **Config knobs** — every brief "must be configurable" maps to a named options key referenced by the algorithm that uses it (not a literal).
  4. Write the findings to `.docs/{project-name}/design/design-review.md`.
  5. Send the findings to **Aria** as ONE revision round (see §2 — deliberately tighter than DDD's 3-cycle bound). Unresolved Blockers escalate to the user at the Iteration Checkpoint.
  6. **Verify the fixes, not just the design.** When Aria returns the revised design: confirm each Blocker's fix is present, AND re-read the clauses the fix touched for regressions — verbatim requirement clauses a fix rewrites (auth posture, endpoint bindings, identifier bindings) are the highest-regression-risk surface here. This pass is NOT a new adversarial cycle and does NOT count against the one-round bound.

### Phase 3: Planning (Alex)
- **Delegated Agent**: **Alex** (Strategist)
- **Workflow**:
  1. Delegate to **Alex**. He reads his own methodology dependencies on-demand.
  2. Instruct Alex to read `.docs/{project-name}/requirements.md`, `.docs/{project-name}/honing-transcript.md`, and `.docs/{project-name}/design/detailed-design.md`, and convert the blueprint into micro-tasks ordered to satisfy dependencies.
  2b. **Inject the discovery knowledge base (brownfield only).** If `.docs/summary/` exists for this feature, inject the resolved paths of `.docs/summary/{feature}/overview.md`, `.docs/summary/{feature}/QA/code-workflow.md`, and `.docs/summary/{feature}/QA/manual-testing.md` into his brief — `manual-testing.md` is the baseline his Baseline Reconciliation duty operates on. On greenfield these do not exist: say so explicitly in the brief rather than leaving him to infer it from a missing path. Mirrors Rex's Context Hydration in `bgpdd-plan` Phase 1.
     - **Read-only** injection. `.docs/summary/` is Tier 1 and this pipeline never writes it.
  3. **CRITICAL PATHING**: Alex MUST save the checklist exactly to `.docs/{project-name}/implementation/plan.md` (NOT the root `.docs/{project-name}/` folder), using his planning methodology's format. Every milestone heading carries both its `[UI]`/`[API]` domain tag **and** its `[vs:<surface>]` verification-surface tag, and every `### Checkpoint:` carries a conforming `RUNTIME PROBE:` line — a missing surface tag halts `bgpdd-build` before Phase 1.
  3b. **Second artifact, different scope**: Alex MUST also save the feature acceptance matrix to `.docs/{project-name}/acceptance-matrix.md` (the project root, NOT `implementation/`), derived from `requirements.md` and never from the task list he just wrote. The plan is per-milestone; the matrix is per-feature. Every state-changing step declares its inverse or carries a written `[no inverse: <reason>]` exemption.
  4. Read Alex's returned handoff.

### Phase 3.5: Coverage & Acceptance Lint Gate (Orchestrator)
- **Delegated Agent**: None — Orchestrator.
- **Workflow**:
  1. Execute the coverage tool via a shell action, using the runtime's available Python 3 interpreter (`python` or `python3`):
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --plan .docs/{project-name}/implementation/plan.md`
     The full CLI contract (JSON shape, exit codes, parsing rules) lives in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
  2. Read the JSON object from stdout. Exit code 0 = every Must-Have `FR`/`NFR` is covered **and no lint failed** — report any `warnings` and `uncovered_should` entries to the user as non-blocking notes, then proceed to step 5 (the matrix lint still gates this phase). Exit code 1 = the `uncovered` array lists the Must-Have gaps, **or `lint_failures` is non-empty** — the five plan-mode lints (`literal-count`, `consumes-provides`, `path-hygiene`, `runtime-criterion`, `domain-tag`) gate exactly like a coverage gap, so exit 1 with an empty `uncovered` and populated `lint_failures` is a lint failure, not a tool defect. Exit code 2 = an artifact failed its structural contract (e.g. no task blocks, no Must-Have IDs) — treat this as a defect in the artifact, not the tool.
  3. On exit 1 or 2, re-delegate to **Alex** (a fresh delegation) quoting the exact `uncovered` IDs, every `lint_failures` entry verbatim (`check` / `task` / `detail`), and `warnings` (or the `error` message) — subject to the existing 2-round auto-fix bound. If unresolved after 2 rounds, halt and surface to the user. After each fix, re-run step 1 to verify.
  4. **If Python is unavailable: HALT** and surface the missing interpreter — do not substitute a manual judgment path for a mechanical gate.
  5. **Lint the acceptance matrix's structure** — the same gate script, structure mode, no results file yet because nothing has been executed:
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_acceptance_suite.py --lint-only --matrix .docs/{project-name}/acceptance-matrix.md --requirements .docs/{project-name}/requirements.md`
     Exit 0 = the matrix is structurally sound. Exit 1 = the JSON names the defect: a scenario with no priority or no step table, a missing `Stores`/`Mode` column, an unrecognized `Mode`, a duplicate scenario id or step number, a phantom row, a dangling `[inverse of N]`, a malformed exemption, or a state-changing step with no inverse and no exemption. Exit 2 = usage or an unparseable matrix. `--requirements` additionally gates the FR→scenario link — every Must-Have `FR`/`NFR` must be cited by at least one scenario heading, each gap landing in `lint_failures` as check `fr-scenario-coverage`. Re-delegate to **Alex** quoting the exact arrays, under the same 2-round bound as step 3, re-running after each fix.
     **A missing inverse blocks here but only warns at build — a deliberate mode divergence (convention #8), not a contradiction**: at plan time the matrix is the artifact under authorship and the fix is a one-line edit. (`references/plan-pipeline-rationale.md`.)
  6. **If `acceptance-matrix.md` does not exist**, treat it as a Phase 3 defect and re-delegate to Alex — do not proceed. A feature with no declared walkthrough is a feature nobody has agreed on the meaning of "works" for. (Epics genuinely too small for a matrix belong in `/bgpdd-lite`, which declares `acceptance_matrix=null` explicitly rather than silently.)
  7. Once coverage and the matrix lint are both confirmed, proceed to Phase 3.6.

### Phase 3.6: Environment Manifest & Capability Halt (Orchestrator + user, main session)
- **Delegated Agent**: None — interactive, main session.
- **Format authority**: the **Environment Manifest** section of `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` — its blocks, unchanged.
- **Brownfield: resolve, do not re-author.** If `.docs/summary/{feature}/QA/runtime-environment.md` exists (written by `/bgpdd-discovery` Phase 4b), that Tier-1 recipe is authoritative. Read it, confirm it still covers the surfaces this plan tagged, and skip to step 3. Record any new service or step this feature introduces as a **delta** in the Tier-2 file, naming what it adds.
- **Greenfield: derive first, ask second.** Aria's design names the services; Alex's plan carries every `[vs:<surface>]` tag and `RUNTIME PROBE:` line. Use them:
  1. **Propose the manifest yourself** from the design and plan: the intended services and their start commands, the bring-up order the design's call flow implies, the repointing the architecture requires, and the capability inventory the plan's surfaces demand. Fill the bring-up sequence's `Needed for` column from the surface tags, so a later UI-only milestone can bring up the web app alone. Write it to `.docs/{project-name}/implementation/environment-manifest.md`.
  2. **Then ask the user only for what no artifact can hold**, one question at a time: the source of each credential and the test login's username (**never the password itself**), target device or machine names as the product lists them, local ports that differ from the framework default, and any build/copy/install step between "compiles" and "running" that the design does not spell out. Present your proposal for correction rather than interrogating from zero.
- **Capability check (both paths, step 3).** For every distinct `[vs:<surface>]` in the plan, confirm the capability that surface's evidence requires actually exists here, exercising each once: browser automation for `[vs:ui]`/`[vs:web+api]`, device or agent access for `[vs:rmm]`, a sink client for `[vs:fn]`, an out-of-process HTTP client and a Python 3 interpreter throughout.
  - **A missing one does NOT halt planning.** Follow the *request now, block at the evidence boundary* ladder in `runtime-evidence`: ask the user for it immediately and specifically (they can install while planning finishes), record it with `update_state.py --add-blocker` in the same action, and carry on to Phase 4. The blocker travels to `/bgpdd-build` in `orchestrator-state.json`, where Phase 0 re-checks it and the milestone-close rule refuses to let it be forgotten.
  - **Do not soften the plan's surface tags to fit the tooling you happen to have.** That converts a temporarily missing tool into a permanently unverifiable requirement.
  - **Capability-only, deliberately narrower than `/bgpdd-build` Phase 0's check (convention #8).** No service is started here: greenfield ones do not exist yet, brownfield ones are build's to start.
- **Persist it so `/bgpdd-build` Phase 0 resolves it instead of re-authoring it**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/update_state.py --state .docs/{project-name}/orchestrator-state.json --set-artifact environment_manifest=<the resolved path>` — the Tier-1 recipe's path on the brownfield route, the Tier-2 file's on the greenfield one.
- Once the manifest is confirmed, proceed to Phase 4 — with any capability blocker recorded and requested, not resolved.

### Phase 4: Game Tape Checkpoint (Orchestrator)
- **Delegated Agent**: None — Orchestrator. No delegation, no halt.
- **Workflow**:
  1. While your session context is still alive, append a `## bgpdd-plan — [date]` section to `.docs/{project-name}/implementation/game-tape.md` (create the file if it does not exist). At most 10 bullets, covering: user corrections made, agent failures/retries, re-delegation rounds and why, circuit-breaker trips, gates that were rubber-stamped vs. genuinely exercised, and this session's id/transcript path if the runtime exposes it (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`).
  2. This evidence feeds the SINGLE end-of-epic Forge run in `bgpdd-shipping` Step 7 — do NOT delegate Forge here. If this run went badly enough that lessons should not wait for the epic to ship, offer the user an on-demand `/bgpdd-learn` run now instead.
  3. **State Persistence**: before concluding, write orchestrator state via `update_state.py` — never hand-edit JSON. Schema authority is `update_state.py` (schema version string `"1"`). If Python is unavailable: HALT and surface the missing interpreter.
     ```bash
     python {PLUGIN_ROOT}/pipeline-tools/scripts/update_state.py \
       --state .docs/{project-name}/orchestrator-state.json \
       --init --project-name "{project-name}" \
       --set-pipeline bgpdd-plan \
       --set-feature <feature|null> \
       --set-artifact requirements=.docs/{project-name}/requirements.md \
       --set-artifact design=.docs/{project-name}/design/detailed-design.md \
       --set-artifact plan=.docs/{project-name}/implementation/plan.md \
       --set-artifact acceptance_matrix=.docs/{project-name}/acceptance-matrix.md
     ```
     Field notes: `feature` is the Tier-1 durable feature id from `.docs/summary/{feature}/` (`null` for greenfield). `pipeline` is the last pipeline that wrote the state. `milestone_cursor` and `branch` stay `null` until `bgpdd-build` owns them. Downstream pipelines hydrate from the resulting shape (documentation only — do not recreate by hand):
```json
{
  "schema": "1",
  "project_name": "slide-enhancement",
  "feature": "slide",
  "pipeline": "bgpdd-plan",
  "branch": null,
  "milestone_cursor": null,
  "artifacts": {
    "requirements": ".docs/{project-name}/requirements.md",
    "design": ".docs/{project-name}/design/detailed-design.md",
    "plan": ".docs/{project-name}/implementation/plan.md"
  },
  "blockers": [],
  "updated": "<ISO-8601 timestamp>"
}
```
  4. Prompt the user to open a new chat session and trigger `/bgpdd-build` to execute the code.
