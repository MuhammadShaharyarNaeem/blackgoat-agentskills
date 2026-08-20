# Orchestrator Rationale

On-demand companion to `agent-squad/SKILL.md` and `agent-squad/orchestrator-contract.md`. The rules themselves live in those two files and are complete without this one; this file preserves the "why" — reasoning, observed failure modes, and migration history.

## Why cross-cutting Orchestrator rules live in ONE file

`orchestrator-contract.md` exists so those rules live in one place instead of being inlined per pipeline. Five near-identical copies is why a stale claim once survived in three files at once: a duplicated rule gets fixed in some copies and left stale in the rest. The trade is a visible duplication defect for an invisible omission defect — a pipeline that silently fails to reference the contract loses those rules entirely, with no symptom until an unbounded or work-losing run happens. That is why `agent-audit` Metric 13 greps every `bgpdd-*` pipeline for the mandatory-read reference and treats a missing one as a Blocker.

## Why blocking delegation is banned (§1 Background Execution)

Blocking makes the Orchestrator unreachable for the whole run — no questions, no course correction — and a long phase becomes indistinguishable from a hang. The user cannot tell a working agent from a dead one, and cannot intervene even when they can see the run is going wrong.

## Why non-file write surfaces fail worse than files (§1 concurrency)

Files are the only write surface with an obvious owner, and even they fail silently — concurrent edits lose each other with last-write-wins, no error, no conflict marker. The other surfaces fail worse: a running process, a held port, a singleton external identity (one device, tenant, or session that admits a single connection), a shared cache, an installed artifact. There is no conflict marker and no last-write-wins to reason about — one agent's subject simply vanishes out from under it mid-run. A process an agent cannot account for is therefore a signal to report, never a thing to reap; and because a background delegation's termination takes its child processes with it, a service one agent started is never infrastructure another can rely on.

## Why testers may continue warm but reviewers may not (§1 Continuation)

The continuation rule prefers a warm agent inside a unit of work: the author regaining context is a feature. For an independent verifier it is the opposite — the verifier regaining context is anchoring, and a context that missed a flaw once is primed to miss it again. The split between Quinn and Luna follows from what each produces: Quinn's verdict is captured command output — re-runnable evidence, unaffected by which context produced it — while Luna's verdict is judgment. So a tester may continue warm within a unit, and a reviewer re-examining a remediation is always a fresh delegation.

## Why persona injection was relaxed to three tiers (§1 Delegation construction)

The rule formerly required always-verbatim persona injection, which cost roughly 6–8K characters on every delegation regardless of whether the runtime already knew the persona. The failure that rule guarded against was **from-memory summaries silently dropping constraints**, not file-path indirection. Tiers 1–2 (runtime-native agent type, then path injection) preserve exactly that guarantee at a fraction of the token cost, so the divergence is deliberate and the from-memory ban survives unchanged at every tier.

## Why a deferral must be enumerated phase by phase (§1)

The mechanical check that would have caught a missing phase usually lives *at* a gate the deferral also postpones. So deferring a gate deletes the detection along with the obligation, and the omission has no symptom — every artifact on disk still looks correct. Enumerating every suspended phase and gate by name, including the ones the user did not mention, is the only thing that keeps the withdrawal visible.

## Why Incremental Persistence is passed verbatim to workers (§2)

Same rule as `base-persona.md`'s Incremental Persistence. An agent that defers its first write loses **everything** on interruption or context limit, leaving the Orchestrator nothing to resume from — an observed failure mode that has destroyed entire multi-call runs.

## Why a stale cursor is worse than no cursor (§4)

Read as "resume forward", a stored cursor silently skips every unit inserted behind it. A whole round of corrective work sits inert while every artifact on disk still looks correct — nothing fails, nothing reports, and the plan's own unchecked items are the only witness. Hence: re-derive the next unit from the plan document at every hydration and after any edit to the plan, and treat an earlier unchecked item as proof the cursor is stale.

## Why "small" and "precisely located" are not reasons to defer a blocker (§4)

*"Small"*, *"precisely located"*, and *"handed over"* are the three rationalizations that ship a diagnosed one-line fix as a defect. Precision makes a fix cheap to apply, not safe to defer. The related relay obligation exists for the same reason: a Must-Have the design has declared unsatisfiable-as-worded is not "covered" in the sense the user hears, even where the gate counts it covered under its own rules. The gate measures only what it was built to measure; only the Orchestrator can see the open entry standing beside it.

## Why evidence checkpoints cannot wait for pipeline end (§4)

A checkpoint conditioned on pipeline *completion* is not a checkpoint: the context that held the evidence is long gone by then, and an abandoned run leaves no record at all. Milestones M1–M8 of a real epic ran with **zero** checkpoints for exactly this reason, so the improvement run that followed had a fraction of the evidence it needed.

## Procedural memories migrated out of `agent-squad/SKILL.md`

All six accumulated Orchestrator memories were cross-cutting rules that applied during pipeline runs too, yet `agent-squad/SKILL.md` is not loaded during a pipeline — so they were unreachable exactly when they mattered. They were generalized and elevated into `orchestrator-contract.md`, which IS loaded everywhere:

| Former memory | Now lives in the contract as |
|---|---|
| Architect Coding Delegation Constraint | §3 Role Boundaries — never delegate coding to the Architect |
| Strict Orchestration Boundary under Subagent Tool Friction | §3 Role Boundaries — you never write application code |
| Specialist-First Routing | §1 Delegation construction — route to the matching squad member |
| Verbatim Persona & Tool Capability Delegation Standard | §1 Delegation construction — three-tier persona sourcing (native agent type → path injection → verbatim last resort), declare capabilities |
| Advisor, Not Yes-Man | §3 Role Boundaries — advisor, not yes-man |
| Capture Systemic Lessons on Correction | §3 Role Boundaries — capture systemic lessons on correction |
