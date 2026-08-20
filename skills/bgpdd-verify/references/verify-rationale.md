# bgpdd-verify — Rationale

Why this lane's deliberate divergences (convention #8) are safe. Load on demand; `SKILL.md` carries the rules and their terse labels.

## Verify-only, no rejection loop

`bgpdd-build` Phase 2 runs a builder↔Quinn rejection loop: a failing test routes back to the builder who wrote the code, and the milestone closes when it goes green. This lane deliberately has no such loop.

Two reasons. There is no builder in this pipeline to loop to — the squad here is Quinn alone, plus an optional research Scout. And a verification lane that fixes what it measures grades its own work: the same agent would author the change, re-run its own spec against it, and record the PASS. So a failing product behavior terminates as a **finding** and leaves the pipeline entirely, routed to a fresh `/bg-bugfix` session that can re-enter through the Phase 0 re-verify shortcut once the fix lands.

This is also why Phase 3's product-defect class explicitly forbids looping: the gates exiting 1 on genuine FAILs is the lane producing its output, not failing at it.

## Source divergence

`planning-and-task-breakdown` requires the acceptance matrix be derived from `requirements.md`, *never* from what got built — otherwise the matrix grades the implementation against itself.

There is no `requirements.md` in this lane, because nothing is being specified: the question is whether the feature still behaves as discovery documented it. So "works" is defined by Echo's manual-testing baseline, and the matrix derives from that instead.

The original rule's anti-self-grading intent survives by two mechanisms rather than by the source document:

1. **Authorship** — the Orchestrator and user transcribe the matrix; Quinn, who is graded against it, never touches it.
2. **Traceability** — each scenario heading cites the baseline case IDs it came from (`HP-01`, `RR-03`, …) inside its parentheses, so every scenario points at a row a different agent wrote at a different time.

## Authorship divergence

In `/bgpdd-plan` Phase 3 the acceptance matrix is Alex's artifact, authored as part of planning. Here the Orchestrator authors it interactively with the user.

The work is different in kind: transcribing existing baseline cases and taking the user's scope decisions is not planning, and it needs the turn-by-turn exchange a delegated agent cannot hold. `bgpdd-lite` Phase 1 already carries the same interactive exception for the same reason.

What must not move, and does not, is the invariant both forms exist to protect: **Quinn never authors the matrix she is graded against** — the rule `bgpdd-build` Phase 5 step 2.5c enforces.

## Inline environment manifest

`runtime-evidence`'s *Environment Manifest* section puts the bring-up sequence, services, repointing map, forbidden hosts, test identities and capabilities in a standalone file, written at one of three entry points.

This lane has one matrix, one delegation, and no build phases — nothing that a second file would decouple. Putting the same blocks inside the matrix the user is already confirming means the facts get reviewed in the same pass that scopes the run, instead of in a document nobody re-opens.

The invariant surviving both forms is unchanged: **these values are caller-supplied, and Quinn never declares them.** A producer-declared assertion grades itself, which is exactly what the response-envelope keys and expected statuses exist to prevent.
