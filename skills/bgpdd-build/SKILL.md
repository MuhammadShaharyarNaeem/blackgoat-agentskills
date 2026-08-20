---
name: bgpdd-build
description: Phase 2 of the Prompt-Driven Development SOP (Execution). Takes an existing implementation plan and executes it using Mason, Nova, Quinn, Luna, Dep, Cipher, and Aria (advisory, blast-radius only).
trigger: /bgpdd-build
---

# End-to-End Multi-Agent PDD: Execution Phase (bgPDD-Build)

Orchestrator SOP taking an existing `plan.md` through building, review, optimization, testing, and deployment prep. Squad and per-phase routing: §1.

Invoke with `/bgpdd-build` (add the `auto` argument for Autonomous Execution Mode — see §3).

Rationale, failure histories, and divergence reasoning: `references/build-pipeline-rationale.md` (on demand).

---

## Path Resolution

`{PLUGIN_ROOT}` = the plugin's `skills/` directory (this skill's base directory is provided to you); personas live at `{PLUGIN_ROOT}/../agents/`. Every other path rule — list-before-reference, and the base-persona injection guard — has ONE home: `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md`, **Path Resolution** (inside your mandatory first read).

---

## 1. Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Phase 0, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path. **This is most critical in Auto Mode (§3)**, where an unattended run has nobody watching to catch a lost phase.

The sections below carry ONLY this pipeline's refinements on top of that contract.

- **Strict Delegation — this pipeline's agents**: Mason or Nova (Phase 1 — routed by the milestone's domain tag), Quinn (Phase 2), Luna and, for `[SEC]` milestones, Cipher (Phase 3), Dep (Phase 5); Phase 4 is a builder follow-up, not a separate persona; Aria is a conditional blast-radius advisor only. You MUST NOT roleplay the phases yourself.
- **Prerequisites**: Do NOT run unless `.docs/{project-name}/implementation/plan.md` exists and is fully populated.
- **Hydration Phase** (before Phase 0): **require** `.docs/{project-name}/orchestrator-state.json` with `pipeline` ∈ {`bgpdd-plan`, `bgpdd-lite`, `bgpdd-build`} — HALT otherwise. Schema: `bgpdd-plan` Phase 4 (fields `schema`, `project_name`, `feature`, `pipeline`, `branch`, `milestone_cursor`, `artifacts`, `blockers`, `updated`).
  - State file missing entirely with only `plan.md` present → HALT; ask the user to re-run `/bgpdd-plan` or `/bgpdd-lite`, or to explicitly confirm they are continuing from an orphan plan (then initialize state via `update_state.py` before proceeding).
  - Record the working branch in `branch` once established (Git Workflow below).

  | Hydrated field | Do |
  |---|---|
  | `artifacts.design` non-null | Inject `artifacts.design` into every builder/Alex brief as the architecture reference (full plan → `detailed-design.md`; lite → governing stack-contract skill path) |
  | `artifacts.design` `null` | Builders use `requirements` + `plan` only |
  | `artifacts.acceptance_matrix` | Polymorphic (path / JSON `null` / key absent). Resolved at its only consumer — **Phase 5 step 2.5c**; do not re-decide it here |

  - **`plan.md` is the single authority on what to build next; `milestone_cursor` is only a resume hint.** Per Orchestrator Contract §4, the next milestone is **the first milestone whose heading line does not carry `[x]`, in `plan.md`'s own top-to-bottom order** — re-derived by reading the plan, never taken from the stored cursor and never advanced by stepping forward from it. Re-derive at hydration AND after every edit to `plan.md`, including your own mid-run edits.
    - **Primary path**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/next_milestone.py --plan .docs/{project-name}/implementation/plan.md --state .docs/{project-name}/orchestrator-state.json` — returns the next pending milestone, its domain tag, its full task block (use it as the milestone text for delegation briefs), and the stale-cursor verdict. On `stale: true`, reset the cursor and tell the user.
    - **If Python is unavailable: HALT** and surface the missing interpreter — never substitute a manual judgment path for a mechanical gate.
    - Milestone completion is recorded by appending `[x]` to the milestone's heading line in `plan.md` — the convention `next_milestone.py` parses (full contract: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`).
  - **On milestone close** — its Build→Test→Review→Refactor cycle complete AND you have personally observed its runtime exit criterion (Orchestrator Contract §4, *a terminal status is not evidence*: a milestone does not close on returned `COMPLETE` statuses) — update the state file: set `pipeline` to `"bgpdd-build"`, re-derive `milestone_cursor` from `plan.md` (or `null` when no unchecked milestone remains), append every unresolved Critical/Important finding, BLOCKED verification and named proxy substitution to `blockers`, and append this milestone's evidence to `game-tape.md` (Phase 6).
    - **A milestone may not be marked `[x]` while ANY `blockers` entry stands** — scoped to it or not (the same empty-array rule the commit gate enforces below).
    - Perform every state-file write through `{PLUGIN_ROOT}/pipeline-tools/scripts/update_state.py` (cursor, pipeline, branch, blockers — blocker removal requires `--evidence`); NEVER hand-edit the JSON. Contract: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
    - **If Python is unavailable: HALT** and surface the missing interpreter — never hand-edit state JSON as a substitute for the mechanical writer.
- **Git Workflow**:
  - At hydration, establish the working branch: ask the user for the repo's branch-naming convention if unknown; default to `feature/{project-name}`. Create it if it does not exist. NEVER build directly on the default branch (main/master).
  - After each milestone goes green — Phase 2 tests pass, and any Phase 3/4 remediation has completed the **full re-verification cycle defined in Phase 3 step 4** (re-tested by Quinn, re-reviewed by Luna, `Approve` on the current diff) — YOU (the Orchestrator) commit the milestone's changes on the working branch, with a message citing the milestone name and the `FR`/`NFR` IDs it covers. Committing is pipeline state management, not application-code writing.
  - A worker that cannot finish in one run commits its partial work to the same working branch before returning its handoff (the Orchestrator Contract's CONTEXT CHECKPOINTS rule, made concrete here — same branch, commit before returning; see §2).
  - **The commit gate is mechanical and machine-RUN**: its preconditions are artifacts a script reads off disk, not a judgement you form. There is no "commit now, the remaining finding is minor" ([why this is a script](references/build-pipeline-rationale.md#the-commit-gate-is-machine-run)).
    - **Primary path**:
      `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_commit_gate.py --review-report .docs/{project-name}/implementation/review-report.md --state .docs/{project-name}/orchestrator-state.json --milestone "<milestone title>" --changed-files <the milestone's accumulated changed-files union — see Phase 1 step 6> --commit --message "<milestone name + FR/NFR IDs covered>" --verify-tree`

      | Flag | When |
      |---|---|
      | `--verify-tree` | **Always on** — fails the gate if the working tree holds changes beyond the declared `<changed_files>` plus `.docs/` |
      | `--require-rendered-evidence` | Milestone carries `[UI]` tasks, or its surface is `[vs:ui]`/`[vs:web+api]`, AND browser tooling is available on the runtime |
      | `--require-runtime-evidence --runtime-report .docs/{project-name}/implementation/test-report.md`, **plus every** assertion flag you passed at the Phase 2 step 4 gate — `--require-key`, `--expect-status`, `--forbid-host`, `--surface`, `--require-openapi-reachable`, and the `--openapi-doc` trio if you used it | Every milestone whose surface is not `[vs:none]` or `[vs:ui]`. **Repeat them all**: a weaker assertion set here makes the gate that owns the commit the more permissive of the two ([why it runs twice](references/build-pipeline-rationale.md#why-the-runtime-gate-runs-twice)) |

    - **`[vs:ui]` forwards `--require-rendered-evidence` only, never `--require-runtime-evidence`** — the same `[vs:ui]` exemption as Phase 2 step 4 (**convention #8**): the gate the latter feeds cannot accept rendered evidence. `[vs:web+api]` still forwards both.
    - **`[UI]` milestone with NO browser tooling on the runtime**: do NOT run this gate for that milestone at all — HALT and surface the milestone, the fact that the review was necessarily source-only, and the missing-evidence blocker. A `[UI]` milestone is never committed on source-only evidence and never looped against a gate it cannot pass.
    - Exit 0 = gate passed and the commit exists (the script commits, so a skipped gate is loud). Exit 1 = do not commit; the JSON names the failing check — route back into the Phase 3 step 4 cycle. Exit 2 = artifact/environment defect — fix it, never hand-wave past it. Full CLI contract (JSON shape, exit codes, parsing rules): `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` — single authority; do not restate parsing rules here.
    - **If Python is unavailable: HALT** and surface the missing interpreter.
    - **Blockers precondition — the array must be empty.** A milestone commits only when `orchestrator-state.json`'s `blockers` array holds **no** standing entries at all, scoped to this milestone or not — deliberately tighter than a scoped-only reading (**convention #8**; [fail-safe argument](references/build-pipeline-rationale.md#the-blockers-array-must-be-empty)). `check_commit_gate.py` enforces exactly this; `--ignore-unscoped` is its sanctioned override for exceptional cases.
- **Phase Transitions**: per the Orchestrator Contract §1; Auto Mode (§3) is this pipeline's sanctioned suspension of that confirmation rule.
- **Upgraded Chain-of-Thought**: before transitioning between phases, explicitly verify the required artifact exists.
  - *Format*: "Thinking: Phase X requires Y. Checking `.docs/{project-name}/Y`... File exists and is populated. Proceeding."
- **File Artifacts**: standard GitHub markdown, saved under `.docs/{project-name}/`.

## 2. Global Safety Mechanisms

**The error-recovery skeleton lives in the Orchestrator Contract (§2)** — halt-and-escalate triggers, the circuit breaker you pass to every agent, no-nested-delegation, incremental persistence, context checkpoints, and 2-round bounded autonomous rejection. Read it there; it is not restated here.

This pipeline's refinements, because it is the only pipeline where workers write code:
- **Incremental persistence includes committing.** The instruction you pass every agent must cover code as well as documents: partial work is committed to the working branch established in §1's Git Workflow before the agent returns. (Resumption briefs name what already exists — files *and* commits — per the Contract's CONTEXT CHECKPOINTS rule.)
- **Log discipline.** Instruct every builder/tester delegation to run builds and test suites through `{PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --log .docs/{project-name}/implementation/logs/<slug>.log -- <command>` when a Python 3 runtime is available. Default timeout 240s; pass `--timeout` explicitly for long suites (e.g. real-DB integration tests). Exit 124 with a `TIMEOUT:` header is a harness result to escalate, never recorded as a test FAIL. Stack skills (e.g. `dotnet-backend-patterns`) carry the no-Python fallbacks.
- **Auto Mode raises the stakes on all of the above (§3)**: an unattended run may proceed a long time with nobody watching to restart a lost phase.

## 3. Auto Mode (Optional Argument)

If invoked with the `auto` argument (`/bgpdd-build auto`), operate in **Autonomous Execution Mode**:
- **Macro-Loop Execution**: Seamlessly transition [Phase 1 (Build) → Phase 2 (Test) → Phase 3 (Review) → Phase 4 (Refactor)] in a loop for *each milestone* in `plan.md` without asking for "proceed" confirmation.
- **Phase 5 (Epic Shipping Prep)**: Dep writes the prep `ship-decision.md` (GO/NO-GO) — deploy is deferred to `/bgpdd-shipping`.
- **Phase 6 (Game Tape Checkpoint)**: the Orchestrator appends this run's evidence to `game-tape.md`; Forge runs once at epic end, in `bgpdd-shipping` Step 7.
- **HALT**: Once ALL milestones are complete, drop out of Auto Mode. You MUST ask for explicit human approval before invoking Phase 5 for the entire epic (Phase 6 is a free Orchestrator checkpoint — no approval needed).
- **Circuit Breakers**: If the builder loops 3 times, or Luna flags a blocker the builder cannot fix, immediately drop out of Auto Mode and halt for human intervention.

## 4. Few-Shot Handoff Examples

When communicating with the user during a phase transition checkpoint (non-auto mode):

**Good Example (Crisp, action-oriented):**
> Phase 3 (Review) is complete. Luna found no critical issues, and the report is saved to `.docs/my-app/implementation/review-report.md`.
> **Blockers**: None.
> **Next Step**: Are you ready to proceed to Phase 4 (Optimization) (builder follow-up)?

---

## 5. Folder Structure (Semantic Memory)

This is **Tier 2** — the per-enhancement work dir (`.docs/{project-name}/`): this pipeline's read-write workspace, scoped to the current enhancement. **Tier 1** (`.docs/summary/{feature}/`) is the global knowledge base produced by **`/bgpdd-discovery`** — read-only for this pipeline. NEVER write build artifacts to Tier 1.

```text
.docs/{project-name}/
└── implementation/        # Checklists, reviews, and release plans
    ├── plan.md            # Dependency-mapped task list (REQUIRED INPUT)
    ├── environment-manifest.md # Services, repointing map, forbidden hosts, capabilities (Phase 0, user-supplied)
    ├── test-report.md     # Test execution logs and coverage (Quinn)
    ├── review-report.md   # Quality review (Luna)
    ├── acceptance-results.md # Per-step walkthrough results (Quinn, Phase 5 step 2.5)
    ├── ship-decision.md   # Prep GO/NO-GO (Dep, Phase 5); shipping Stage 2 Dep refreshes for final launch
    └── game-tape.md       # Per-phase evidence checkpoints (Orchestrator, Phase 6)
```

---

## 6. Detailed Pipeline Phases

### Phase 0: Verification Readiness (Orchestrator + user, main session)
- **Delegated Agent**: None for authoring — interactive, per the Orchestrator Contract §1 interactive-steps rule. Optionally **Scout** for bounded environment research (step 2).
- **Cadence**: **once per session, before the first builder delegation** — not once per milestone ([why](references/build-pipeline-rationale.md#phase-0-runs-once-per-session)).
- **Format authority**: the **Environment Manifest** section of `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`. Do not restate or vary its blocks here.
- **Workflow**:
  1. **Resolve the manifest by precedence** (grammar and precedence owned by `runtime-evidence`; do not re-decide them here):

     | Order | Source | Then |
     |---|---|---|
     | a | `.docs/summary/{feature}/QA/runtime-environment.md` — the Tier-1 brownfield recipe from `/bgpdd-discovery` Phase 4b. **Authoritative whenever it exists** | Read it, go to step 3 |
     | b | `artifacts.environment_manifest` in `orchestrator-state.json`, else `.docs/{project-name}/implementation/environment-manifest.md` — written by `/bgpdd-plan` Phase 3.6 or a prior run of this phase | Read it, go to step 3 |
     | c | Neither exists (typically a `/bgpdd-lite` epic, which has no Phase 3.6) | Author it now, per step 2 |

     The facts are durable; the **running processes are not** — step 3's preflight runs even when the manifest was resolved rather than authored.
  2. **If neither exists, author it WITH the user** — every block the format authority defines, including the capability inventory the plan's `[vs:]` surfaces require. **This is context the user supplies — do NOT delegate the authoring, and do NOT let any agent infer a value.** You may spawn **Scout** for bounded research into what the repo already declares (compose files, launch profiles, `appsettings.*.json`, CI workflows), writing to `.docs/{project-name}/research/` — research only; the user confirms every value that lands in the manifest.
  3. **Preflight (mechanical) — the minimal subset, not the whole estate.** Select the bring-up steps whose `Needed for` covers the surfaces this plan's milestones actually carry. Start each selected service, observe its readiness check, and capture the output:
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture .docs/{project-name}/implementation/evidence/preflight/<service>-readiness.md -- <the readiness command>`
     - Then confirm each capability in the inventory is present in **this** runtime: browser automation for any `[vs:ui]`/`[vs:web+api]` milestone, device access for `[vs:rmm]`, a sink client for `[vs:fn]`, an out-of-process HTTP client and a Python 3 interpreter throughout. **A capability is confirmed by exercising it once, not by believing it is configured.**
     - Preflight captures live under `evidence/preflight/`, NEVER `evidence/runtime/` — they prove the estate starts, not that any requirement is met, and must never be reachable by Phase 2's gate.
  4. **A gap is requested now and blocks at the evidence boundary — it does NOT halt Phase 1.** Docker not installed, a service that will not start, an absent browser, an unreachable device, a URL nobody can supply: follow the ladder in `runtime-evidence` (*A missing capability is requested immediately and blocks at the evidence boundary*).
     a. Ask the user immediately and specifically — they can install while the builder works.
     b. Record it in the same action: `python {PLUGIN_ROOT}/pipeline-tools/scripts/update_state.py --state .docs/{project-name}/orchestrator-state.json --add-blocker "<the gap>"`
     c. **Proceed into Phase 1** — but never *past* where the gap bites: **Phase 2 does not run against a missing capability**, and the milestone cannot close around it (§1: no `[x]` while any `blockers` entry stands, which is what bounds this deferral).
     d. Clear it with `--resolve-blocker` plus the exercise-it-once evidence when the user reports it ready.
     - **The one gap that still halts immediately** is one blocking the *building*, not just the verifying: a schema you cannot inspect, a package feed you cannot reach, a credential the code needs at compile time.
  5. **Inject the resolved manifest path into every builder and Quinn brief** from Phase 1 onward, alongside the milestone text. Take Phase 2's `--forbid-host` arguments straight from the manifest's forbidden-host block — declared here precisely so they are never invented there.
  5b. **Persist it as an artifact so `/bgpdd-shipping` inherits it** (shipping's Vera brief starts the application too): `python {PLUGIN_ROOT}/pipeline-tools/scripts/update_state.py --state .docs/{project-name}/orchestrator-state.json --set-artifact environment_manifest=.docs/{project-name}/implementation/environment-manifest.md` (`--set-artifact environment_manifest=null` when step 6 skipped).
  6. **Skip only when every milestone in the plan is `[vs:none]`.** Record the skip and the justification lines it rests on in the game tape, and say so to the user — a plan that is entirely `[vs:none]` is itself worth a second look.

### Phase 1: Building
- **Delegated Agent**: **Mason** (Builder, `[API]`/backend milestones) or **Nova** (UI Builder, `[UI]` milestones). Each reads their methodology dependencies (TDD, debugging, SDD) on-demand.
- **Workflow**:
  1. Pick the next milestone — not the stored `milestone_cursor`, and not the one after the milestone you just finished (Hydration Phase rule, §1). Do this **every time you enter Phase 1**, not once per run.
     - **Primary path**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/next_milestone.py --plan .docs/{project-name}/implementation/plan.md --state .docs/{project-name}/orchestrator-state.json`

       | Result | Do |
       |---|---|
       | `NEXT` | Proceed with its `milestone_text` and `domain` for step 2's routing |
       | `MIXED` (exit 1) — including when the script treats `UNTAGGED` as `MIXED` | Step 2's planning defect: halt and surface it; do not improvise a split |
       | `DONE` | Skip ahead to Phase 5's completion gate |

     - **If Python is unavailable: HALT** and surface the missing interpreter — never substitute a manual judgment path for a mechanical gate.
  2. **Route by domain.** Read the domain off the milestone's tasks' domain tags (`[API]` or `[UI]`, assigned at planning) and route the whole milestone to the matching builder: `[API]` → Mason, `[UI]` → Nova.
     - A milestone mixing `[UI]` and `[API]` tasks is a PLANNING DEFECT: halt and surface it to the user for re-planning (route back through Alex) — do NOT improvise a split yourself.
     - An `UNTAGGED` milestone (no `[UI]`/`[API]` on heading or tasks) is the same class of planning defect as `MIXED` — halt and surface it; do not invent a route.
  3. Delegate the milestone to a **single builder agent** (Mason or Nova per step 2), who builds its tasks in plan order.
     - **The milestone is the unit of delegation — do NOT fan its tasks out to parallel builder agents**, even when their `Dependencies:` fields show no ordering constraint between them ([why](references/build-pipeline-rationale.md#the-milestone-is-the-unit-of-delegation)). One builder builds; one Quinn/Luna round verifies the milestone's diff once.
     - **CRITICAL CONTEXT HANDOFF**: copy the exact text of the active milestone from `plan.md` into the delegation prompt.
     - **Point the builder at the probe it is already holding.** The pasted milestone text carries the `[vs:<surface>]` tag and the `RUNTIME PROBE:` line inside its `### Checkpoint:` block. Quote both into the brief explicitly, exactly as Phase 2 step 1b does for Quinn, and instruct the builder to run the declared probe as a **self-check** written to `.docs/{project-name}/implementation/evidence/build/` — NEVER `evidence/runtime/`, the verifier's gating path. This adds no gate ([why it is still required](references/build-pipeline-rationale.md#why-the-builder-is-pointed-at-a-probe-it-already-holds)).
  4. **STRICT BLAST RADIUS RULE**: instruct the builder that *before* modifying any shared DTO or library, it MUST trace dependencies by searching the codebase for all consumers of it. (Optionally a `code-review-graph` MCP server's impact tool, if one happens to be available — it is not wired in this plugin's `.mcp.json`.) A radius extending beyond its active microservice must be documented in its handoff and returned for architectural review.
  5. If the blast radius exceeds the active microservice:
     a. Notify the User: "Blast radius exceeds the current microservice boundary. Architectural review required."
     b. Delegate to **Aria** as a temporary advisor (**Mode 2 — Scoped Advisory** in her `blackgoat-research` methodology — she must NOT write or modify `detailed-design.md` in this mode), passing her the builder's blast-radius report; ask for a scoped architectural recommendation in her `<handoff>`.
     c. Present Aria's recommendation to the User for approval.
     d. After approval, delegate a **fresh builder** (same builder as this milestone's routing), passing it the prior handoff state and Aria's ruling.
  6. Read the builder's returned handoff and extract the strict `<changed_files>` XML list. **Accumulate, do not replace**: the milestone's changed-files set is the union of the builder's `<changed_files>` here, Quinn's from Phase 2 and every retest round, and any Phase 3/4 remediation `<changed_files>` — never replaced by the last handoff. This union feeds `--changed-files` at the commit gate (§1).

### Phase 2: Testing
- **Delegated Agent**: **Quinn** (QA Tester). She reads her methodology dependencies (runtime-evidence always; TDD when authoring new test code; debugging and playwright as scoped) per her dependency table.
- **Workflow**:
  1. Delegate to the **Quinn** agent. **CRITICAL CONTEXT HANDOFF**: pass her the exact text of the active milestone and the `<changed_files>` list from the builder. **CRITICAL PATHING**: instruct her to append results to `.docs/{project-name}/implementation/test-report.md`. If the milestone contains `[UI]`-tagged tasks, inject the resolved path of `{PLUGIN_ROOT}/ui-design-patterns/references/component-mechanics.md` — Quinn derives her [UI] assertions from it (each citing the item's CM-id).
  1b. **Route the runtime probe into her brief.** The milestone's `### Checkpoint:` block already rides inside the verbatim `milestone_text` you pasted in step 1. Quote its **`RUNTIME PROBE:`** line into her brief explicitly and instruct her to: execute it **out-of-process**, save the capture under `.docs/{project-name}/implementation/evidence/runtime/` via `run_quiet.py --capture`, and cite it with a `**Runtime evidence:**` line in her `#Task [N]:` block. Inject the resolved path of `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`.
     - **No `RUNTIME PROBE:` line declared → HALT.** That absence is a planning defect (`planning-and-task-breakdown`, Step 5) — surface it and route back through Alex. **Do NOT let Quinn invent the probe**: a probe authored by the agent it grades is not a criterion.
     - **Surface `[vs:none]`** → pass its written justification instead and skip the probe; step 4's gate is not run for that milestone.
  2. Instruct Quinn to design and directly execute the test strategy for the newly built code.
  3. **Rejection Loop.**
     - **Fix-verification precondition first (Orchestrator-side, mechanical).** A builder's rejection-round handoff MUST carry a `<fix_verification>` element naming the check it re-ran and the observed result (Mason §7 / Nova §3) — convention #9 in force, enforced by a field you must read rather than prose they must remember ([why](references/build-pipeline-rationale.md#fix-verification-before-re-delegation)).

       | `<fix_verification>` | Do |
       |---|---|
       | Absent | Do **NOT** re-delegate to Quinn — return to the same builder for it, and **do not count that return against the 3-round bound** (the bound caps fix *attempts*) |
       | `NOT VERIFIED — <what blocked>` | Legitimate — proceeds to Quinn |
       | Present, naming the check and its observed result | Proceeds to Quinn |

     - **The loop itself**: Quinn's handoff reports failing tests → send her failing-test logs to the milestone's builder **as a follow-up to the same spawned builder agent** (Mason or Nova, Bugfix mode), per Orchestrator Contract §1 *Continuation vs fresh delegation* (fresh only on its mechanical triggers). Loop builder ↔ Quinn — her retest likewise a follow-up to the same spawned Quinn — until tests pass.
     - **Bound this to 3 rounds per milestone.** Track the builder-fix → Quinn-retest rounds this milestone has been through. Still failing after round 3 → HALT and surface the milestone, the builder's attempted fixes across rounds, and Quinn's exact failing-test logs. Do NOT delegate a 4th round. *Deliberate refinement vs Contract §2's 2-round autonomous-rejection bound (**convention #8**) — distinct counters: §2 bounds autonomous rejection of a defective **artifact** after two failed fix attempts; this bounds builder-fix → Quinn-retest cycles on failing **tests**.*     - **Separately**, count follow-ups to a single spawned agent across Phases 2–4: at the 3rd follow-up to the same spawned agent, spawn it fresh per Orchestrator Contract §1. Independent of the round count above.
  4. **Runtime Evidence Gate (mechanical)** — run as soon as Quinn's handoff is in hand, before Phase 3. A `PASS` in her ledger is a claim; the capture is the evidence.
     - **Skip when the surface is `[vs:none]`, and skip `[vs:ui]` too** — a deliberate refinement of the every-surface-except-none rule (**convention #8**): the script structurally requires a `## Captured output` JSON capture, which `[vs:ui]`'s sanctioned rendered evidence cannot produce; that obligation is the commit gate's `--require-rendered-evidence` path (§1) instead ([detail](references/build-pipeline-rationale.md#the-vsui-skip-at-the-runtime-evidence-gate)). **`[vs:web+api]` keeps both obligations.**

     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_runtime_evidence.py --report .docs/{project-name}/implementation/test-report.md --milestone "<milestone title>" --changed-files <the milestone's accumulated changed-files union> --repo . [--surface <the milestone's [vs:] key>] [--require-key <k> ...] [--expect-status <N>] [--forbid-host <pattern> ...]`

     | Assertion flag | Value comes from — never invented here |
     |---|---|
     | `--require-key`, `--expect-status` | The milestone's `RUNTIME PROBE:` line — never the producer (a producer-declared assertion grades itself) |
     | `--forbid-host` | Phase 0's manifest forbidden-host block — the shared dev/staging hostnames this project must never be probed against. In a multi-service estate this catches one service left pointing at dev |
     | `--require-openapi-reachable` | **Add whenever the surface is `[vs:api]` or `[vs:web+api]`** — forces the probe at a real application rather than anything answering on a port. It proves the surface is up and its schema served; response-*body* correctness is `--require-key`'s job ([the split](references/build-pipeline-rationale.md#why---require-openapi-reachable-is-nearly-free)) |
     | `--openapi-doc` / `--openapi-route` / `--openapi-method` | Optional, when a saved OpenAPI document is under version control — diffs declared against observed top-level property names; an unresolvable schema warns rather than passing or failing |

     Exit 0 = a fresh out-of-process capture exists carrying the asserted keys — proceed to Phase 3. Exit 1 = **BLOCK**: route back into the Phase 2 rejection loop with the JSON's per-capture `problems` (counts as one of the 3 rounds). Exit 2 = structurally non-conforming capture — an artifact defect; route back to Quinn. Full CLI contract: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` — single authority; do not restate parsing rules here.
     - **If the application genuinely cannot be started out-of-process here**, do NOT loop against a gate it cannot pass: **HALT** and surface the milestone, the fact that its verification was necessarily in-process only, and the missing-evidence blocker; record it via `update_state.py --add-blocker`. Mirrors §1's `[UI]`-without-browser-tooling rule — a milestone is never committed on in-process-only evidence.
     - **If Python is unavailable: HALT** and surface the missing interpreter.

### Phase 3: Code Review
- **Delegated Agent**: **Luna** (Reviewer). She reads her methodology dependencies on-demand.
- **Workflow**:
  1. Delegate to the **Luna** agent, passing her the exact `<changed_files>` XML list from the builder so her scope is surgical.
  1b. **[SEC] Parallel Security Review**: if the active milestone contains `[SEC]`-tagged tasks, delegate **Cipher** in parallel with Luna in the same batch, passing him the same `<changed_files>` list, scoped to the security surface of those tasks. **CRITICAL PATHING**: instruct Cipher to append his audit round to `.docs/{project-name}/implementation/security-report.md` per his persona's Security Report contract (the shipping pipeline's Report Gate reads the same file). Treat any vulnerability finding in his handoff as a Critical blocker (step 4 routing).
  2. Instruct Luna to run a 6-axis review: Correctness, Readability, Architecture, Security, Performance (tracing impact per the **Impact Analysis** directive in her persona), and Code Simplification (her code-simplification audit — the guaranteed producer for Phase 4's Suggestion-level trigger).
     - **`[UI]` milestone**: additionally instruct her to run the **design-critique axis** from her `ui-design-patterns` dependency (inject the resolved skill path; screenshots via browser tooling when available).
     - **Rendered evidence is mandatory for that axis**: screenshots/computed-value reads saved under `.docs/{project-name}/implementation/evidence/review/` — reviewer-owned, so the builder's `evidence/build/` screenshots do NOT discharge it — cited via `Rendered evidence:` lines (grammar owned by `code-review-and-quality/SKILL.md`). A critique with no rendered evidence cannot support `Approve` on a `[UI]` milestone; the commit gate's `--require-rendered-evidence` enforces this, requiring the cited paths to fall under `evidence/review/` (underlying rule: ui-design-patterns' "source can fail a check but never pass one").
  3. **CRITICAL PATHING**: instruct Luna to save findings to `.docs/{project-name}/implementation/review-report.md`.
  4. **Remediation is a cycle, not a tail.** Luna's or Cipher's handoff flags "Critical" or "Important" blockers (including any Cipher vulnerability finding per step 1b) → send them to the milestone's builder **as a follow-up to the same spawned builder agent** (Mason or Nova), per Orchestrator Contract §1 *Continuation vs fresh delegation* ([the observed failure this stops](references/build-pipeline-rationale.md#remediation-is-a-cycle-not-a-tail)).
     - A remediation is a fix round, so **Phase 2 step 3's `<fix_verification>` precondition applies here too** — for a Luna design-critique finding, a fresh render of the exact state she critiqued — before you re-enter Phase 2.
     - The fix re-enters the pipeline: back to **Phase 2**, where the same spawned Quinn re-tests it as a follow-up (brief her with the exact findings and the remediation `<changed_files>`), then back to **Phase 3**, where **a fresh Luna** re-reviews the **remediation diff itself** and records a new verdict in `review-report.md` (the Contract's independent-verification exemption: the reviewer is always fresh).
     - **Exit the cycle only when Luna's verdict on the CURRENT diff is `Approve`** — never on the builder's assertion that it fixed it, never by carrying a verdict written against the pre-fix code.
     - Bound the cycle with the Orchestrator Contract's 2-round autonomous-rejection rule: findings surviving two full cycles → HALT and surface the milestone, both remediation attempts, and the standing findings.
     - Track the follow-up count to each same-spawned agent (builder and Quinn) across Phases 2–4 together: at the 3rd follow-up to a given spawned agent, spawn it fresh per Orchestrator Contract §1.

### Phase 4: Optimization & Refactoring (Builder Follow-Up)
- **Delegated Agent**: None new — the milestone's builder (Mason or Nova), continued per Orchestrator Contract §1 (*Continuation vs fresh delegation*).
- **Workflow**:
  1. **Conditional**: ONLY run this phase IF Luna's review contains **Suggestion**-level findings (simplification/refactor suggestions from her code-simplification audit) OR performance findings below Critical/Important, or if the user explicitly requests optimization. Otherwise, skip.
  2. Send the findings to the milestone's builder as a follow-up: apply them without behavioral changes, scoped to the `<changed_files>` list.
  3. Quinn (follow-up) re-runs the regression suite to guarantee stability before the commit gate.
- *Note*: Max (Optimizer) is retired from this pipeline (convergent redundancy — [why](references/build-pipeline-rationale.md#max-is-retired-from-phase-4)). He remains available for explicit ad-hoc optimization requests via the agent-squad roster.

### Phase 5: Epic Shipping (Deferred)
- **Delegated Agent**: **Dep** (DevOps). He reads his methodology dependencies (shipping-and-launch) on-demand.
- **Workflow**:
  1. **Completion Gate**: Before invoking Dep, verify that ALL milestones in `implementation/plan.md` are marked complete (`[x]`). If any milestone heading lacks `[x]`, loop back to Phase 1 for the next pending milestone.
  2. **Build Coverage Gate**:
     a. Execute the coverage tool via a shell action, using the runtime's available Python 3 interpreter (`python` or `python3`):
        `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --test-report .docs/{project-name}/implementation/test-report.md`
        Full CLI contract (JSON shape, exit codes, parsing rules): `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
     b. Read the JSON object from stdout. Exit 0 = every Must-Have `FR`/`NFR` has a passing test — report `warnings` and `uncovered_should` as non-blocking notes, then proceed. Exit 1 = the `uncovered` array lists the Must-Have gaps. Exit 2 = the artifact failed its structural contract — a defect in the artifact, not the tool.
     c. On exit 1 or 2, DO NOT proceed — loop back to Phase 2 (Testing) with the exact `uncovered` IDs and `warnings` (or the `error` message) so Quinn closes the gap. (This closes the requirement-traceability chain: Rex's `FR`/`NFR` → Alex's task → Quinn's test.) After the fix, re-run step (a).
     d. **If Python is unavailable: HALT** and surface the missing interpreter — never substitute a manual judgment path for a mechanical gate.
  2.5. **Acceptance Suite Gate (mechanical)** — the feature-scoped walkthrough, and the last gate before Dep. Every gate above is per-milestone; this is the only one that proves the wall stands rather than the bricks ([why the journey needs its own gate](references/build-pipeline-rationale.md#the-acceptance-suite-gate-proves-the-wall-not-the-bricks)).
     a. Resolve the matrix path per step c, then delegate to **Quinn** (a follow-up to the same spawned Quinn if still resumable, else fresh): execute that matrix end to end and record per-step results to `.docs/{project-name}/implementation/acceptance-results.md`.
        - **Quote the exact result-line grammar into her brief** — `` `- <ScenarioId>.<StepNumber>: <PASS|FAIL|BLOCKED|NOT RUN> — <detail>` `` (manual steps cite their evidence path inline in the detail) — naming `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` as the owner of the full contract. **Do NOT let Quinn invent the format she is graded on** — the same principle as the `RUNTIME PROBE:` routing rule at Phase 2 step 1b.
        - Brief her that `manual` steps are legitimate but pass **only** with a capture cited under `evidence/runtime/`; unevidenced, a manual step reads as NOT RUN and blocks. Inject the resolved path of `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`.
     b. Run the gate against the resolved matrix path from step a:
        `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_acceptance_suite.py --matrix <resolved acceptance-matrix path> --results .docs/{project-name}/implementation/acceptance-results.md --repo . [--require-priority P0,P1]`
        Exit 0 = every gated scenario ran, every step is green, every manual step is evidenced, and no `[inverse of N]` dangles — proceed to Dep. Exit 1 = **BLOCK**: the JSON names the missing/failing/unevidenced steps; route the failures back through Phase 1–3 for the affected milestone, then re-run. Exit 2 = the matrix or results file is structurally non-conforming — an artifact defect: route back to Alex (matrix) or Quinn (results). Full CLI contract: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
     c. **Resolve before checking absence** — the single home for `artifacts.acceptance_matrix` polymorphism (§1 defers here).

        | `artifacts.acceptance_matrix` | Do |
        |---|---|
        | A path (non-null) | That path IS the matrix — use it in place of the hardcoded `.docs/{project-name}/acceptance-matrix.md` |
        | JSON `null` | A lite-originated epic with legitimately no matrix — say so explicitly to the user now and record the skip in Phase 6's game tape. NEVER re-derive from file absence; do not check for the file at all |
        | Key absent (older state file) | Fall back to checking whether `.docs/{project-name}/acceptance-matrix.md` exists |
        | Expected (a path or key-absent) but the resolved file does not exist | A planning defect — HALT and route back through Alex. Do NOT let Quinn author the matrix she is about to be graded on, and do NOT skip the gate |

     d. **If Python is unavailable: HALT** and surface the missing interpreter.
  3. If the Epic is 100% complete, every Must-Have `FR`/`NFR` is covered, and the acceptance suite is green, delegate to the **Dep** agent.
  4. Instruct Dep to scan for deployment risks and credentials across the epic and formulate a mandatory **Rollback Plan**.
  5. **CRITICAL PATHING — prep ship-decision**: instruct Dep to generate `.docs/{project-name}/implementation/ship-decision.md` with a prep `GO` or `NO-GO` verdict. This is **build's entry ticket for `/bgpdd-shipping` Step 0** — Dep does **not** deploy here (full ownership split: `agents/dep.md`).
  6. **Ship-decision shape gate (mechanical)**: after Dep returns, verify the artifact he just wrote is one the shipping pipeline can actually gate on — in THIS session, while it can still be fixed cheaply ([why here](references/build-pipeline-rationale.md#the-ship-decision-shape-gate-runs-in-this-session)):
     `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_ship_decision.py --report .docs/{project-name}/implementation/ship-decision.md`
     Deliberately **without** `--require-go`: a prep `NO-GO` is a legitimate result here, and this gate checks the decision's *shape* (one unambiguous verdict, a Rollback heading, a checklist section), not its content. Exit 0 = well-formed — proceed. Exit 1/2 = malformed: route back to Dep as a follow-up to produce a conforming decision (bounded by the Orchestrator Contract §2 2-round rule). **If Python is unavailable: HALT** and surface the missing interpreter.
  7. **Doubt-Driven Check**: YOU (the Orchestrator) run the Doubt-Driven Development cycle on Dep's prep plan before presenting it to the user.
  8. On explicit user confirmation, instruct the User to trigger `/bgpdd-shipping` to orchestrate the final Launch Squad. If Dep's prep verdict is `NO-GO`, say so plainly — shipping's Step 0.4 entry ticket will refuse to start until that verdict is resolved and rewritten to `GO`.

### Phase 6: Game Tape Checkpoint (Orchestrator)
- **Delegated Agent**: None — the Orchestrator performs this phase directly. No delegation, no halt.
- **Cadence — this is NOT an end-of-run phase.** It is numbered 6 only because it is described last. Per the Orchestrator Contract §4, evidence checkpoints fire **at every state persistence**: run step 1 **each time a milestone closes and you update `orchestrator-state.json`**, in the same step, and again at epic end as a roll-up (step 2). A checkpoint deferred to the end of the pipeline records nothing ([the M1–M8 run](references/build-pipeline-rationale.md#game-tape-checkpoints-fire-per-milestone)).
- **Workflow**:
  1. **Per milestone (mandatory, at the cursor update).** Append to `.docs/{project-name}/implementation/game-tape.md` under a `## bgpdd-build — [milestone] — [date]` heading (create the file if absent). 3–6 bullets, written while the milestone is still in your context: user corrections made, agent failures/retries, re-delegation rounds and why, circuit-breaker trips, which gates were genuinely exercised versus rubber-stamped, every BLOCKED or proxy-substituted verification an agent reported, and the runtime exit criterion you personally observed.
     - Record that exit criterion as the **verbatim command plus its captured output block**, never a summary (or, if you could not observe it, exactly what blocked you). **No pasted output, no claim.**
     - Record what actually happened, your own mistakes included — a checkpoint that only logs successes has learned to lie.
  2. **At epic end (roll-up).** Append a short `## bgpdd-build — epic summary — [date]` section: cross-milestone patterns, anything the per-milestone entries reveal only in aggregate, and this session's id/transcript path if the runtime exposes it (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`).
  3. This evidence feeds the SINGLE end-of-epic Forge run in `bgpdd-shipping` Step 7 — do NOT delegate Forge here. If this run went badly enough that lessons should not wait for the epic to ship, offer the user an on-demand `/bgpdd-learn` run now instead.
