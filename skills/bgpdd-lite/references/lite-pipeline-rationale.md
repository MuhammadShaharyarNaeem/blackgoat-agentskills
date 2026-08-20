# `bgpdd-lite` — Rationale

On-demand depth for `skills/bgpdd-lite/SKILL.md`. Every normative rule lives in `SKILL.md`; this file
holds only the reasoning behind them. Nothing here is a rule — do not enforce from this file.

---

## Path Resolution — why base-persona's location is called out

`base-persona.md` lives inside the `agent-squad` **skill** folder, not in `agents/`. The `agents/`
folder holds ONLY persona files (`rex.md`, `alex.md`, `scout.md`, …). Injecting
`{PLUGIN_ROOT}/../agents/base-persona.md` into a delegation brief is the recurring defect that makes
every delegated agent flag base-persona as missing — the brief resolves, the read fails, and the
agent proceeds without its universal invariants.

## Phase 0 — why the no-pipeline exit exists

Lite already costs two durable artifacts, a gate, a game-tape entry, and a state file. Work with no
decisions in it and a deliverable one well-briefed builder can carry does not earn that overhead: a
good delegation prompt carries the same context the artifacts would have. The two discriminators —
"would a fresh session need durable FR/plan artifacts?" and "are there 5+ independent acceptance
criteria multiple parties must agree on?" — exist because the tempting wrong reason to open lite is
simply that the build will happen in a later session. A separate session is not, by itself, a reason
for durable planning artifacts.

## Phase 1 — why the API mode must be recorded, not inferred

`dotnet-backend-patterns` sanctions two API modes (Mode A — CQRS+MediatR, Mode B — REPR). A worker
that infers the mode from surrounding code picks whichever it saw last, and a plan that never names
the mode gives a reviewer nothing to check the choice against. Recording it as an explicit
constraint line in `requirements.md` — and carrying it into the plan's Reference Documents — makes
the decision reviewable at plan time rather than discoverable at merge time.

## Phase 2 — why research is front-loaded into Scouts

Lite has no design phase and no `detailed-design.md`, so there is no Aria to absorb research. The two
failure modes that leaves are Alex discovering ground truth mid-plan (which turns a planning
delegation into an exploration) and the Orchestrator gathering it inline (which burns the main
session's context on facts a disposable worker should hold). Bounded per-topic Scouts avoid both.
Research that keeps surfacing *decisions* rather than *facts* is the clearest available signal that
lite was the wrong lane in the first place.

## Phase 3 — why `acceptance_matrix=null` is emitted explicitly

`/bgpdd-build` Phase 5 step 2.5c has to distinguish "this epic legitimately has no acceptance matrix"
from "a matrix was expected and is missing" — the second is a planning defect that halts and routes
back through Alex. File absence cannot tell those apart. An explicit JSON `null` in the state file
can, which is why lite declares it rather than leaving the key off.
