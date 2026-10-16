# check_qa_baseline.py — reference

Depth for `check_qa_baseline.py`. The contract is its `--help` (`python tool_registry.py show check_qa_baseline`); this file holds the why.

## The miss it was built from

The 2026-09-14 Slide discovery baseline had cases for mapping a client to a Slide client/Box and for unmapping it. It had none for changing an existing mapping to a different one, though that is a real flow (the device agent re-pairs to the new Box), and the gap surfaced only when E2E specs were written against the feature. A re-discovery on 2026-10-16, briefed without mentioning the gap, added a "remap to a different box" case, but still none for "remap to a different Slide client". Echo's own note suggested the box case came from comparing against the archived docs, not from her derivation.

The cause is in the derivation rule. Echo writes cases "reverse-engineered from `code-workflow.md`", meaning one case per code path, and map, remap-to-other-box and remap-to-other-client all go through one handler. A per-path reading writes one case for all three. Unmap got its own case only because it takes a distinct branch.

## Why a table and a gate, not a stronger sentence

Convention #9: the persona already said "reverse-engineer the cases", and the second run missed one of the same family anyway. The table turns "did you think of the change transition?" into a cell that is either filled or visibly empty. The gate checks the cells resolve: each cited ID must have a case heading in the same file, so a row cannot cite a case that was never written.

**The three transitions.** Unset → Set, Set → Unset and Set → Different are the transitions every mutable value has. Set → Different is the one a per-handler derivation drops, because it reuses the Unset → Set handler. Some values genuinely lack one: a boolean has no "different" value distinct from unset/set, and a write-once field has no unset. Those cells take `N/A: <reason>` of at least three words, so the omission is written and reviewable rather than silent.

**One row per dimension, not per entity.** A Slide mapping has two independently changeable targets, the Slide client and the Box. As one row, a single "remap" case would fill the Set → Different cell for both, which is exactly the 2026-10-16 miss.

## Scope limit

The gate cannot see an entity the table never lists. It guarantees completeness *per listed row*, not that the rows are complete. That is why discovery Phase 4 step 6 tells the Orchestrator to read the rows against `code-workflow.md`'s writes before accepting, and why Echo's persona tells her to list every entity `code-workflow.md` shows a write to. Deriving the entity list mechanically from code would need a per-stack write detector, and none exists here.

Existing baselines written before this gate carry no table and fail `transitions_missing`. They are only re-gated when discovery re-runs and Echo rewrites the file. Readers of the baseline (`bgpdd-verify`, `bgpdd-plan`, Alex) do not run this gate.

## Self-test inventory

**12 cases.** A full two-row table passes. The Slide gap (an empty Set → Different cell) fails. A reasoned `N/A` passes, while a bare `N/A` and a short reason fail. A cited ID with no heading fails, including one defined only inside a fence. A missing section, an empty `None:`, and a header-only table each fail. A wrong header and a wrong cell count fail. The ASCII `->` header is accepted. A duplicate row fails. CLI exit codes 0/2 each write a chained ledger record. A BOM and a following `##` section bound the table.
