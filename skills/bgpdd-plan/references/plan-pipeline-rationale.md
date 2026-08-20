# `bgpdd-plan` — Rationale & Failure History

On-demand depth for `skills/bgpdd-plan/SKILL.md`. Every normative rule lives in `SKILL.md`; this file
holds only the reasoning, failure histories, and divergence arguments behind them. Nothing here is a
rule — do not enforce from this file.

---

## Path Resolution — why base-persona's location is called out

`base-persona.md` lives inside the `agent-squad` **skill** folder, not in `agents/`. The `agents/`
folder holds ONLY persona files (`rex.md`, `alex.md`, `scout.md`, …). Injecting
`{PLUGIN_ROOT}/../agents/base-persona.md` into a delegation brief is the recurring defect that makes
every delegated agent flag base-persona as missing — the brief resolves, the read fails, and the
agent proceeds without its universal invariants. Hence the explicit "verify it resolves before
delegating" obligation.

## Phase 1 — why the honing phase is hybrid rather than delegated

Honing is an interactive, turn-by-turn conversation with the user, and a delegated (fire-and-forget)
agent cannot pause to ask the user and resume. So the live Q&A runs in the main session, while the
heavy artifact work — synthesizing `requirements.md` from the transcript — is still delegated to an
isolated Rex. That split preserves context isolation for the expensive half without pretending a
subagent can hold a conversation.

## Phase 2 — why a large design surface is split into Scouts + Aria

Aria doing open-ended external research *and* authoring the full blueprint in one run is the phase
most likely to exhaust its context or return thin on exactly the part the user cares most about.
When the surface is large — a complete API contract **plus** costed infrastructure options **plus** a
design system — bounded per-topic Scouts front-load the research into their own contexts, and Aria
consumes their files as inputs. For a small or well-bounded feature the split is pure overhead,
which is why the SOP says "do not split by reflex".

## Phase 2.5 step 6 — why the revised design is re-verified

One revision round does not mean one verification. A fix round produces a new artifact, not a patch.
Verbatim requirement clauses that a fix rewrites — auth posture, endpoint bindings, identifier
bindings — are the highest-regression-risk surface in this pipeline: an observed run regressed a
verbatim FR clause and mis-bound three endpoint ids *inside the very round that fixed something
else*. This pass restores the re-loop that tightening the bound to one round removed. Skip it and
the gate's own output is the only text in the pipeline that nothing reviews.

## Phase 3 step 2b — why the discovery knowledge base must be injected

Without `overview.md`, `QA/code-workflow.md`, and `QA/manual-testing.md`, Alex plans from
requirements plus design alone and cannot see how the feature behaves **today**. `manual-testing.md`
in particular is the reverse-engineered baseline his Baseline Reconciliation duty operates on.

## Phase 3 step 3b — why the acceptance matrix is a second, differently-scoped artifact

The plan is per-milestone; the matrix is per-feature. Milestone evidence proves each brick; only the
matrix proves the wall stands. Deriving the matrix from the task list rather than from
`requirements.md` would grade the build against itself.

## Phase 3.5 step 5 — why a missing inverse blocks at plan time but only warns at build

Same signal, opposite posture, because both the cost of the fix and the meaning of green differ by
phase. At plan time the matrix *is* the artifact under authorship and the fix is a one-line edit. At
build time the code is already written, so blocking would bill QA for a debt the planner incurred
weeks earlier — and the build-side check rests on a verb heuristic whose green means only "the
heuristic found nothing".

## Phase 3.5 step 6 — why a missing matrix is a hard stop

A feature with no declared walkthrough is a feature nobody has agreed on the meaning of "works" for.
Epics genuinely too small for a matrix belong in `/bgpdd-lite`, which declares
`acceptance_matrix=null` explicitly rather than silently.

## Phase 3.6 — why the capability check runs here and does not halt

Halting a plan on a missing capability wastes the one resource the situation gives you: the human
can install Docker, provision the test device, or supply the credential source while you finish
planning. Checking early is what buys that parallel install time; it is not a gate looking for
somewhere to stop. The blocker recorded via `update_state.py --add-blocker` is what keeps the
deferral honest — `/bgpdd-build` Phase 0 re-checks it and the milestone-close rule refuses to let it
be forgotten. Softening a surface tag to match the tooling on hand is the one failure this step
exists to prevent: it converts a temporarily missing tool into a permanently unverifiable
requirement. The full ladder is owned by `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`.
