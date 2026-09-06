# bgpdd-plan — Rationale, Worked Examples & Path Trees

On-demand depth for `bgpdd-plan/SKILL.md`. **Nothing here is a contract**: every rule this file explains is stated in the spine, and the spine wins on any apparent conflict. Read a section when you want to know *why* a rule is shaped the way it is, when you want the illustrative folder trees, or when you are about to propose relaxing something.


## § Few-shot handoff example, and the two-tier folder trees

## 3. Few-Shot Handoff Examples

When communicating with the user during a phase transition checkpoint, adhere to these examples:

**Good Example (Crisp, action-oriented):**
> Phase 3 (Planning) is complete. Alex has saved the detailed task list to `.docs/my-app/implementation/plan.md`.
> **Blockers**: None.
> **Next Step**: Are you ready to proceed to Phase 4 (Game Tape Checkpoint)?

---

## 4. Folder Structure (Semantic Memory) — TWO TIERS

This pipeline uses two distinct memory scopes. Do not conflate them.

**Tier 1 — Global project knowledge base** (`.docs/summary/`): built by the **`/bgpdd-discovery`**
pipeline (Iris, Scout, Echo) at **project scope** and **persisted across enhancement cycles**. This
skill (`bgpdd-plan`) **consumes** it — it does not produce it; run `/bgpdd-discovery` first for
brownfield work (see the Pre-Flight Check below). It is indexed by durable feature id (`{feature}`,
e.g. `slide`) so the next time a feature is touched, its map already exists.
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

**Tier 2 — Per-enhancement work dir** (`.docs/{project-name}/`): the isolated artifacts for
**this** piece of work, where `{project-name}` is the current enhancement's work slug (e.g.
`slide-enhancement`). Produced by Rex/Aria/Alex; scoped to this cycle.
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

## § Why Phase 1 is hybrid

Honing is an interactive, turn-by-turn conversation with the user, and a delegated (fire-and-forget) agent cannot pause to ask the user and resume. So the **live Q&A runs in the main session**, but the **spec authoring is delegated to an isolated Rex** — preserving the isolation you want for the heavy artifact work.

## § Splitting Phase 2 — why, and when not to

Aria doing open-ended external research *and* authoring the full blueprint in one run is the phase most likely to exhaust its context or return thin on exactly the part the user cares most about. That is the whole reason the split exists — not load-balancing.

Keep `detailed-design.md` as the single authoritative blueprint Alex decomposes; research files are supporting detail it references. For a small or well-bounded feature, one Aria delegation remains correct — do not split by reflex.

## § Verify the fixes, not just the design

Verbatim requirement clauses a fix rewrites (auth posture, endpoint bindings, identifier bindings) are the highest-regression-risk surface in this pipeline, and an observed run regressed a verbatim FR clause and mis-bound three endpoint ids **inside the very round that fixed something else**.

The pass restores the re-loop that tightening the bound to one round removed. Skip it and the gate's own output is the only text in the pipeline that nothing reviews.

## § Why an inverse blocks at plan time but only warns at build

At plan time the matrix *is* the artifact under authorship and the fix is a one-line edit; at build time the code is already written, so blocking would bill QA for a debt the planner incurred weeks earlier, and the check rests on a verb heuristic whose green means only "the heuristic found nothing". Same signal, opposite posture, because both the cost of the fix and the meaning of green differ by phase.

## § The `orchestrator-state.json` shape after Phase 4

Documentation only — do not recreate by hand; `update_state.py` is the only sanctioned writer.

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
    "plan": ".docs/{project-name}/implementation/plan.md",
    "acceptance_matrix": ".docs/{project-name}/acceptance-matrix.md",
    "environment_manifest": "<the resolved manifest path — Tier-1 or Tier-2, written in Phase 3.6>"
  },
  "blockers": [],
  "updated": "<ISO-8601 timestamp>"
}
```

## § Phase 3.6's state writes — why `--init` and `--set-pipeline` are both mandatory

`--init` on a fresh run: Phase 4 step 3 only creates `orchestrator-state.json` later, so without `--init` both Phase 3.6 commands exit 2 (`state file not found`). On a file that already exists `--init` is a warning-level no-op and every other action in the same call still applies (`{PLUGIN_ROOT}/pipeline-tools/SKILL.md`, `update_state.py` → Actions), so it is safe whichever command runs first.

`--set-pipeline bgpdd-plan` alongside it: `--init` on its own writes `pipeline: ""`. `/bgpdd-build`'s hydration whitelist requires `pipeline` to be one of `bgpdd-plan`, `bgpdd-lite`, `bgpdd-build` or `bgpdd-shipping` and HALTs otherwise, so a run interrupted between Phase 3.6 and Phase 4 — which is where the pipeline value used to first appear — leaves a state file build cannot enter and no named route to report. Naming the route here makes 3.6's write self-sufficient; Phase 4 re-stamping the same value is an idempotent no-op.

## § Injecting the discovery knowledge base into Alex's brief

Without `overview.md`, `code-workflow.md` and `manual-testing.md`, Alex plans from requirements plus design alone and cannot see how the feature behaves **today**. This mirrors Rex's Context Hydration in Phase 1: the same knowledge base, injected read-only at the point the agent needs it.

## § Plan versus matrix — two artifacts, two scopes

Milestone evidence proves each brick; only the feature-scoped matrix proves the wall stands. That is why the matrix is derived from `requirements.md` and never from the task list Alex just wrote — a matrix derived from the plan can only confirm the plan, not the feature.
