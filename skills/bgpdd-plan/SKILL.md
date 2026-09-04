---
name: bgpdd-plan
description: Phase 1 of the Prompt-Driven Development SOP (Design & Architecture). Refines ideas, conducts research, and creates an implementation plan using Rex, Aria, and Alex.
trigger: /bgpdd-plan
---

# End-to-End Multi-Agent PDD: Planning Phase (bgPDD-Plan)

This Standard Operating Procedure (SOP) coordinates the planning squad (Rex, Aria, Alex) to take a rough idea through requirements gathering, technical research, architecture design, and task breakdown.

---

## 1. Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Phase 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.
>
> Then read `{PLUGIN_ROOT}/agent-squad/pipeline-skeleton.md` — the shared pipeline skeleton (path resolution, error recovery, upgraded chain of thought, game tape). Refinements below override the skeleton only where labelled (convention #8).

The sections below carry ONLY this pipeline's refinements on top of that contract.

- **Strict Delegation — this pipeline's agents**: Rex (Phase 1 Step B), Aria (Phase 2), Alex (Phase 3), and optionally Scout (Phase 2 research split). Phase 2.5 (Adversarial Design Review) is Orchestrator-run — no delegated agent. For non-interactive phases you MUST NOT roleplay the agent's work yourself.
  - **EXCEPTION — Phase 1 (Honing)**: Requirements honing is interactive (turn-by-turn Q&A with the user). A delegated agent cannot pause to ask the user and resume, so **you (the main session) run Phase 1 yourself** following Rex's persona as the behavioral spec. See Phase 1 below.
- **Upgraded Chain-of-Thought**: Before transitioning between phases, you MUST explicitly verify that the required artifact exists AND satisfies its content contract — existence and non-emptiness alone are not sufficient. Content contracts:
  - `requirements.md`: has at least one Must-Have requirement carrying an `FR` ID and a Given/When/Then acceptance criterion.
  - `detailed-design.md`: explicitly references the `FR` IDs it addresses (the design must show which requirements it covers) AND contains a `## Divergence & Supersession Register`; `requirements.md` carries a matching supersession annotation for every superseded FR.
  - `plan.md`: every task cites the requirement ID(s) it satisfies (a "Requirements covered:" field), and every task carries a verification step.
  - *Format*: "Thinking: Phase X requires Y. Checking `.docs/{project-name}/Y`... File exists and satisfies its content contract [state which check(s) passed]. Proceeding."
- **Mechanical gates**: the missing-interpreter HALT and the never-simulate-a-pass rule are the Orchestrator Contract §1's; the gates below neither restate nor soften them. Every gate invocation carries `--ledger .docs/{project-name}/implementation/gates.jsonl` (Orchestrator Contract §4).
- **Run log** (Contract §4's obligation, bound here; CLI contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`). Per delegation return — Rex (Phase 1 Step B), each Scout (Phase 2 split), Aria (Phase 2 and her one revision round), Alex (Phase 3 and each coverage-fix round): `python {PLUGIN_ROOT}/pipeline-tools/scripts/record_run.py --log .docs/{project-name}/implementation/run-log.jsonl --pipeline bgpdd-plan --phase "<phase>" --event delegation --agent <name> --model <tier> --unit <the artifact the delegation produced, e.g. requirements.md> …` (`--model` is mandatory on a delegation record — exit 2 without it; name the tier the delegation actually ran at, not the one recommended). Add `--rounds <this artifact's round number>` on a re-delegation, plus `--duration-s`/`--tokens-in`/`--tokens-out` (or `--from-json <the completion payload>`) from the runtime's completion notification and `--status` from the handoff. Into Phase 4's game tape: `python {PLUGIN_ROOT}/pipeline-tools/scripts/summarize_run.py --run-log .docs/{project-name}/implementation/run-log.jsonl --ledger .docs/{project-name}/implementation/gates.jsonl --markdown`.
- **File Artifacts**: All artifacts must use standard GitHub markdown and be saved under `.docs/{project-name}/`. This folder is the project's persistent **Semantic Memory**.

## 2. Global Error Recovery

This pipeline's refinements on the skeleton's Error Recovery section: the artifacts subject to the 2-round bound are `requirements.md`, `detailed-design.md`, and `plan.md` — track the round count per artifact, and after 2 rounds surface the flaw and both attempts to the user rather than re-delegating a third time. Phase 2.5 is tighter still: the design gets exactly **one** doubt-driven revision round (deliberately below DDD's own 3-cycle bound), then escalate. Note: `requirements.md` is legitimately mutated in Phase 2 by Aria — supersession annotations only.

## 3. Folder Structure (Semantic Memory) — TWO TIERS

This pipeline uses two distinct memory scopes. Do not conflate them.

- **Tier 1 — global project knowledge base** (`.docs/summary/`): built by **`/bgpdd-discovery`** (Iris, Scout, Echo) at **project scope** and **persisted across enhancement cycles**, indexed by durable feature id (`{feature}`, e.g. `slide`). This pipeline **consumes** it and **never writes it** — run `/bgpdd-discovery` first for brownfield work (see the Pre-Flight Check).
- **Tier 2 — per-enhancement work dir** (`.docs/{project-name}/`): the isolated artifacts for **this** piece of work, produced by Rex/Aria/Alex and scoped to this cycle.

The illustrative file-by-file trees for both tiers, and the phase-transition handoff example, live in `references/plan-rationale.md`.

---

## 4. Detailed Pipeline Phases

### Pre-Flight Check: Global Context Verification (Brownfield only)
- **Delegated Agent**: None — the Orchestrator performs this check directly.
- **Purpose**: verify Tier-1 discovery has already run before planning against an existing system (§3 owns the never-produces rule).
- **Workflow**:
  1. Determine whether this is brownfield (modifying an existing system) or greenfield (new project). If greenfield, skip this check entirely and go to Phase 1.
  2. **Brownfield**: check that the Tier-1 `.docs/summary/context.md` exists, and — for the feature being enhanced — that `.docs/summary/{feature}/overview.md` exists.
  3. **If either is missing**: HALT. Explicitly instruct the user to run **`/bgpdd-discovery`** first to map the global tech stack, per-API feature fragments, and legacy QA baseline. Do NOT attempt to run discovery yourself or hand-author these files — resume Phase 1 only once the knowledge base is present.
  4. **If present**: confirm the `{feature}` id with the user (so downstream phases read the right `.docs/summary/{feature}/` subtree) and proceed to Phase 1.

### Phase 1: Honing & Requirements (HYBRID)
- **Behavioral spec**: `{PLUGIN_ROOT}/../agents/rex.md` (Rex, the Analyst) + `{PLUGIN_ROOT}/blackgoat-idea-honing/SKILL.md`
- **Why hybrid**: the live Q&A runs in the main session (a delegated agent cannot pause to ask the user), the spec authoring is delegated to an isolated Rex. Detail: `references/plan-rationale.md` § Why Phase 1 is hybrid.

- **Step A — Interactive honing (YOU, the main session)**:
  1. Adopt the Behavioral spec above as your behavior for this step.
  2. Save any rough idea the user gave into `.docs/{project-name}/rough-idea.md`. If brownfield, read the Tier-1 knowledge base first — `.docs/summary/context.md` and `.docs/summary/{feature}/overview.md` (drill into `{api}.md` / QA files as needed) — to ground your questions in the real system. (Greenfield: these don't exist; skip.)
  3. Conduct the honing Q&A: ask the user **one targeted question at a time**, probing edge cases deeply, appending each question and answer to `.docs/{project-name}/honing-transcript.md`. Use your runtime's structured multiple-choice question tool (if one exists) for clear multiple-choice decisions; otherwise ask in plain conversation.
  4. Even if the user provides a complete requirements document upfront, still review it for missing edge cases and drive it through the honing checkpoint — do not skip straight to acceptance.
  5. When the user confirms honing is complete, the transcript is final.

- **Step B — Spec synthesis (delegate isolated Rex)**:
  6. Delegate to the **Rex** agent. Pass him the paths to `.docs/{project-name}/honing-transcript.md`, `.docs/{project-name}/rough-idea.md`, and (if brownfield) the `.docs/summary/{feature}/` knowledge base. Instruct him to synthesize `.docs/{project-name}/requirements.md` from the transcript using his requirements template.
  7. Read Rex's returned handoff. If he flags unresolved **open questions** (he cannot ask the user directly), relay them to the user, append answers to the transcript, and re-delegate Rex to finalize. Loop until `requirements.md` is complete.
  8. Request user confirmation to transition to Phase 2.

### Phase 2: Research & Architecture (Aria)
- **Delegated Agent**: **Aria** (Architect)
- **Workflow**:
  1. Delegate to the **Aria** agent (tell her the `{feature}` if brownfield).
  2. Instruct Aria to read `.docs/{project-name}/requirements.md` **and** `.docs/{project-name}/honing-transcript.md` (for intent nuance), and — **if brownfield** — the Tier-1 `.docs/summary/{feature}/overview.md`, drilling into individual `.docs/summary/{feature}/{api}.md` files as the design requires (so the prior Scout research is consumed, not orphaned). She then does her own additional research. Note: Aria cannot delegate to Scout — she reads the existing maps.
  3. **CRITICAL PATHING**: Instruct Aria that she MUST write the final blueprint exactly to `.docs/{project-name}/design/detailed-design.md`.
  3b. **[UI] Design-direction sourcing**: if the requirements include user-facing UI, inject into Aria's brief the resolved paths to both `{PLUGIN_ROOT}/ui-design-patterns/SKILL.md` and its design-DB search tool (`{PLUGIN_ROOT}/ui-design-patterns/tools/design-db/scripts/search.py`), so she can source candidate directions per that skill's **Candidate sourcing** rule before committing the visual direction in the blueprint.
  4. Read Aria's returned handoff.
  5. **Iteration Checkpoint**: After Phase 2.5 completes, present Aria's design to the user **together with the Phase 2.5 gate findings** (`design/design-review.md`), and explicitly offer to bounce back to Phase 1 if research or the review uncovered new questions.

- **Splitting Phase 2 when the design surface is large** (recommended for substantial greenfield builds) — e.g. a complete API contract **plus** costed infrastructure options **plus** a design system. Why, and when not to: `references/plan-rationale.md` § Splitting Phase 2. To split:
  1. Spawn one or more **Scout** agents for the *bounded research* questions (the Orchestrator may spawn Scout; Aria may not). Give each Scout a single topic and its own output file under `.docs/{project-name}/research/`. Launch them **concurrently in one message**. Tell each Scout explicitly that it is researching, not designing — no architecture, no component or endpoint design.
  2. Then delegate **Aria** to author `.docs/{project-name}/design/detailed-design.md`, instructing her to read those research files as inputs so the Scout work is consumed, not orphaned.
  `detailed-design.md` stays the single authoritative blueprint Alex decomposes. For a small or well-bounded feature, one Aria delegation remains correct — do not split by reflex.

### Phase 2.5: Adversarial Design Review (Orchestrator)
- **Delegated Agent**: None — YOU (the Orchestrator) run the Doubt-Driven Development cycle (`{PLUGIN_ROOT}/doubt-driven-development/SKILL.md`) on `detailed-design.md` before the design stands.
- **Workflow**:
  1. **Supersession-annotation lint (mechanical pre-step)**: before the adversarial pass, run:
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --design .docs/{project-name}/design/detailed-design.md --ledger .docs/{project-name}/implementation/gates.jsonl`
     This is the **supersession-annotation lint**, not full FR→design coverage: every FR/NFR named in the design's `## Divergence & Supersession Register` must carry its matching in-place supersession annotation in `requirements.md`. Read the JSON from stdout and fix every reported `lint_failures` entry (`supersession-annotation`, and `fr-citation` when emitted) before proceeding. CLI contract: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
  1b. **FR/NFR citation check (Orchestrator)**: Independently verify that every Must-Have `FR`/`NFR` ID from `requirements.md` appears at least once in `detailed-design.md` (a citation, not necessarily a register row). If `check_coverage` design mode already reports `fr-citation` entries in `lint_failures`, treat those as authoritative and fix them; otherwise perform this citation scan yourself before the adversarial pass. An uncited Must-Have is a design gap — route back to Aria (counts as the Phase 2.5 revision round if unresolved).
  2. Run the doubt cycle **per-section** (the design exceeds DDD's one-read unit, so its decomposition rule applies). Always extract: every money-moving sequence, every state machine, every read-then-decide gate.
  3. Each DOUBT prompt carries this fixed attack list **verbatim**, in addition to DDD's adversarial prompt:
     1. **Crash windows** — for each sequence that moves money and calls an external system, enumerate "process dies after step N" for every N; each must name a recovery mechanism (sweeper / reconciliation / idempotent retry).
     2. **Reversals** — every journal entry / money movement has a defined reversal or an explicit "irreversible, because…".
     3. **Races** — every read-then-decide gate (quota, balance, rate) names its serialization mechanism and a two-concurrent-requests test.
     4. **Trust-boundary amounts** — any externally-supplied number that moves money is validated against an internal record.
     5. **State-machine self-consistency** — every compensation/failure path only performs transitions its own state machine permits; and any declared set of numbered assertions, invariants, or allow-lists is walked as a set — every pair mutually satisfiable, every member referentially valid.
     6. **Config knobs** — every brief "must be configurable" maps to a named options key referenced by the algorithm that uses it (not a literal).
  4. Write the findings to `.docs/{project-name}/design/design-review.md`.
  5. Send the findings to **Aria** as ONE revision round (see §2 — this bound is deliberately tighter than DDD's 3-cycle bound). Unresolved Blockers escalate to the user at the Iteration Checkpoint.
  6. **Verify the fixes, not just the design.** One revision round does not mean one verification: when Aria returns the revised design, check each Blocker's fix is actually present, AND re-read the clauses the fix touched for regressions — a fix round produces a new artifact, not a patch. This pass is NOT a new adversarial cycle and does NOT count against the one-round bound. Why it exists, and the observed regression behind it: `references/plan-rationale.md` § Verify the fixes.

### Phase 3: Planning (Alex)
- **Delegated Agent**: **Alex** (Strategist)
- **Workflow**:
  1. Delegate to the **Alex** agent. He reads his own methodology dependencies on-demand.
  2. Instruct Alex to read `.docs/{project-name}/requirements.md`, `.docs/{project-name}/honing-transcript.md`, and `.docs/{project-name}/design/detailed-design.md`, and convert the blueprint into micro-tasks ordered to satisfy dependencies.
  2b. **Inject the discovery knowledge base (brownfield only).** If `.docs/summary/` exists for this feature, inject the resolved paths of `.docs/summary/{feature}/overview.md`, `.docs/summary/{feature}/QA/code-workflow.md`, and `.docs/summary/{feature}/QA/manual-testing.md` into his brief. `manual-testing.md` is the reverse-engineered baseline his Baseline Reconciliation duty operates on. On a greenfield project these do not exist; say so explicitly in the brief rather than leaving him to infer it from a missing path. Why it matters: `references/plan-rationale.md` § Injecting the discovery knowledge base.
     - This is a **read-only** injection. `.docs/summary/` is Tier 1 and this pipeline never writes it (see Path Model).
  3. **CRITICAL PATHING**: Instruct Alex that he MUST save the checklist exactly to `.docs/{project-name}/implementation/plan.md` (NOT the root `.docs/{project-name}/` folder), using his planning methodology's format. Every milestone heading carries both its `[UI]`/`[API]` domain tag **and** its `[vs:<surface>]` verification-surface tag, and every `### Checkpoint:` carries a conforming `RUNTIME PROBE:` line — a missing surface tag halts `bgpdd-build` before Phase 1, so it is cheaper to catch here.
  3b. **Second artifact, different scope**: Alex MUST also save the feature acceptance matrix to `.docs/{project-name}/acceptance-matrix.md` (the project root, NOT `implementation/`), derived from `requirements.md` and never from the task list he just wrote. The plan is per-milestone; the matrix is per-feature (why: `references/plan-rationale.md` § Plan versus matrix). Every state-changing step declares its inverse or carries a written `[no inverse: <reason>]` exemption.
  4. Read Alex's returned handoff.

### Phase 3.5: Coverage & Acceptance Lint Gate (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this check directly.
- **Workflow**:
  1. Run:
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --plan .docs/{project-name}/implementation/plan.md --ledger .docs/{project-name}/implementation/gates.jsonl`
     The full CLI contract (JSON shape, exit codes, parsing rules) lives in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
  2. Read the JSON object from stdout. Exit 0 = every Must-Have `FR`/`NFR` covered and no lint failed — report `warnings` and `uncovered_should` as non-blocking notes, then proceed. Exit 1 = one of the **two gating arrays** is non-empty, `uncovered` and/or `lint_failures` (a clean-coverage plan with a lint failure still exits 1). Exit 2 = the artifact failed its structural contract — a defect in the artifact, not the tool.
  3. On exit 1 or 2, re-delegate to **Alex** (a fresh delegation) quoting the exact `uncovered` IDs **and** the `lint_failures` entries, plus `warnings` (or the `error` message) — subject to the existing 2-round auto-fix bound. If unresolved after 2 rounds, halt and surface to the user. After each fix, re-run step 1 to verify.
  4. **Lint the acceptance matrix's structure** — the same gate script, structure mode, no results file yet because nothing has been executed:
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_acceptance_suite.py --lint-only --matrix .docs/{project-name}/acceptance-matrix.md --requirements .docs/{project-name}/requirements.md --ledger .docs/{project-name}/implementation/gates.jsonl`
     Exit 0 = structurally sound. Exit 1 = the JSON names the defect (the enumerated defect classes are `check_acceptance_suite.py`'s, in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`). Exit 2 = usage or an unparseable matrix. `--requirements` additionally gates the FR→scenario link — every Must-Have `FR`/`NFR` cited by at least one scenario heading, each gap landing in `lint_failures` as `fr-scenario-coverage`. Re-delegate to **Alex** quoting the exact arrays, under the same 2-round bound as step 3, re-running after each fix.
     **A missing inverse blocks here but only warns at build — a deliberate mode divergence (convention #8), not a contradiction.** Reasoning: `references/plan-rationale.md` § Why an inverse blocks at plan time.
  5. **If `acceptance-matrix.md` does not exist**, treat it as a Phase 3 defect and re-delegate to Alex — do not proceed. (Epics genuinely too small for a matrix belong in `/bgpdd-lite`, which declares `acceptance_matrix=null` explicitly rather than silently.)
  6. Once coverage and the matrix lint are both confirmed, proceed to Phase 3.6.

### Phase 3.6: Environment Manifest & Capability Halt (Orchestrator + user, main session)
- **Delegated Agent**: None — interactive, main session.
- **Format authority**: the **Environment Manifest** section of `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` — its blocks, unchanged.
- **Brownfield: resolve, do not re-author.** If `.docs/summary/{feature}/QA/runtime-environment.md` exists (written by `/bgpdd-discovery` Phase 4b), that Tier-1 recipe is authoritative. Read it, confirm it still covers the surfaces this plan tagged, and skip to step 3. Record any new service or step this feature introduces as a **delta** in the Tier-2 file, naming what it adds.
- **Greenfield: derive first, ask second.** Aria's design names the services and Alex's plan carries every `[vs:<surface>]` tag and `RUNTIME PROBE:` line. Use them:
  1. **Propose the manifest yourself** from the design and plan: the intended services and their start commands, the bring-up order the design's call flow implies, the repointing the architecture requires, and the capability inventory the plan's surfaces demand. Fill the bring-up sequence's `Needed for` column from the surface tags, so a later UI-only milestone can bring up the web app alone rather than the whole estate. Write it to `.docs/{project-name}/implementation/environment-manifest.md`.
  2. **Then ask the user only for what no artifact can hold**, one question at a time: the source of each credential and the test login's username (**never the password itself**), target device or machine names as the product lists them, local ports that differ from the framework default, and any build/copy/install step between "compiles" and "running" that the design does not spell out. Present the proposal for correction; the user is confirming a draft, not filling a form.
- **Capability check (both paths, step 3).** For every distinct `[vs:<surface>]` in the plan, confirm the capability that surface's evidence requires actually exists here, exercising each once: browser automation for `[vs:ui]`/`[vs:web+api]`, device or agent access for `[vs:rmm]`, a sink client for `[vs:fn]`, an out-of-process HTTP client and a Python 3 interpreter throughout.
  - **A missing one does NOT halt planning.** Follow the *request now, block at the evidence boundary* ladder in `runtime-evidence`: ask the user for it immediately and specifically (they can install while planning finishes), record it in the same action with `python {PLUGIN_ROOT}/pipeline-tools/scripts/update_state.py --state .docs/{project-name}/orchestrator-state.json --init --project-name "{project-name}" --set-pipeline bgpdd-plan --add-blocker "<the missing capability>"`, and carry on to Phase 4. The blocker travels to `/bgpdd-build` in `orchestrator-state.json`, where Phase 0 re-checks it and the milestone-close rule refuses to let it be forgotten. **Checking early is what buys the user their parallel install time**, not a gate looking for somewhere to stop.
  - **Do not soften the plan's surface tags to fit the tooling you happen to have** — that converts a temporarily missing tool into a permanently unverifiable requirement.
  - **Capability-only, deliberately narrower than `/bgpdd-build` Phase 0's check (convention #8).** No service is started here: greenfield ones do not exist yet, brownfield ones are build's to start.
- **Persist it so `/bgpdd-build` Phase 0 resolves it instead of re-authoring it**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/update_state.py --state .docs/{project-name}/orchestrator-state.json --init --project-name "{project-name}" --set-pipeline bgpdd-plan --set-artifact environment_manifest=<the resolved path>` — the Tier-1 recipe's path on the brownfield route, the Tier-2 file's on the greenfield one.
  - **`--init` and `--set-pipeline bgpdd-plan` are BOTH mandatory on BOTH commands.** This phase is the first writer of `orchestrator-state.json`, so without `--init` each command exits 2 (`state file not found`) on a fresh run; and `--init` alone writes `pipeline: ""`, which `/bgpdd-build`'s hydration whitelist rejects with no named route. Either omission hands build an unenterable state file if the run is interrupted before Phase 4. Both are idempotent no-ops on a file that already exists. Full semantics: `references/plan-rationale.md` § Phase 3.6's state writes.
- Once the manifest is confirmed, proceed to Phase 4 — with any capability blocker recorded and requested, not resolved.

### Phase 4: Game Tape Checkpoint (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this phase directly. No delegation, no halt.
- **Workflow**:
  1. Write this run's game-tape checkpoint at the skeleton's default cadence and cap — once per run, at most 10 bullets, heading `## bgpdd-plan — [date]`. This pipeline adds no refinement to that section.
  2. This evidence feeds the SINGLE end-of-epic Forge run in `bgpdd-shipping` Step 7 — do NOT delegate Forge here. If this run went badly enough that lessons should not wait for the epic to ship, offer the user an on-demand `/bgpdd-learn` run now instead.
  3. **State Persistence**: Before concluding, write orchestrator state via `update_state.py` — never hand-edit JSON. Schema authority is `update_state.py` (schema version string `"1"`). Its `--init` may already be a no-op here (Phase 3.6 writes the state file first when it records a manifest or a capability blocker) — the warning is expected, and the entries Phase 3.6 wrote are preserved. If Python is unavailable: HALT and surface the missing interpreter.
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
     Field notes: `feature` is the Tier-1 durable feature id from `.docs/summary/{feature}/` (`null` for greenfield). `pipeline` is the last pipeline that wrote the state. `milestone_cursor` and `branch` stay `null` until `bgpdd-build` owns them. The resulting state shape is documented in `references/plan-rationale.md` § The `orchestrator-state.json` shape — documentation only; never hand-write that JSON.
  4. Prompt the user to open a new chat session and trigger `/bgpdd-build` to execute the code.
