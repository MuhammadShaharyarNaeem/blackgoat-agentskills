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

## --domain

The State Transitions table proves every listed change has a case. It says nothing about whether the cases check what the product is *supposed* to do: a case derived from code asserts what the code does, so a rule the code breaks produces a case that passes. The domain pack (`domain.md`) holds those rules as user-confirmed `D-<n>` rows, and `--domain` (FR-6) proves every rule is exercised by a case or set aside with a reasoned `N/A`. It is the same move as the transitions table, one level up: a rule nobody tested becomes a visibly missing row in `## Domain Coverage`, not a silent omission.

**What it checks, and why each part.**
- *The pack's shape.* All seven sections must exist, each exactly once, so a missing section is visible rather than silently skipped. The gate reads the bodies of Rules and Open Questions only; an empty Glossary, Roles, Entity States, Known Bugs or Risk Weights section passes. A repeated heading would let rules under the second copy go unread. Rules need an ID, a rule and a source: a rule with no source cannot be traced back to who said it.
- *Open questions.* Every line under the heading is a `- Q-<n> — …` entry (`Q-1`, `Q-2`; a zero-padded `Q-01` is rejected, never skipped), or the section is a lone `None`. A line the gate cannot read as an entry is a failure, not a skip. Otherwise a plain bullet, a numbered item or a `Q-01` could hide an unresolved question or escape the cap. Each entry is answered by a rule or deferred with a reason. The cap of 10 (NFR-4) keeps the question round short. The rest are written as `Deferred: over the 10-question cap`, which the gate does not count.
- *One Oracle line per case.* `code` marks a case that only records today's behaviour. `D-<n>` / `DS-<n>` marks a case that checks a rule. Coverage counts a case for a rule only when its Oracle names that rule (`oracle_mismatch` otherwise), so a coverage row cannot cite a case that checks something else.
- *Suspected defects.* An `SD-NN` case is where code and rule disagree. It must name the rule and say what the code does instead. It counts as coverage for its rule (EC-3), because the disagreement is exactly what the rule's test needs to show.
- *Shared rules.* `DS-<n>` (in `context.md`'s `## Shared Domain Rules`) may appear in an Oracle and is never looked up or required in coverage (FR-10). The owning feature covers it.

**Unchanged without the flag.** Without `--domain`, the run is byte-identical to the pre-flag gate in stdout, exit code and ledger inputs (FR-9). Legacy baselines have no Oracle lines and behave exactly as before, whatever their result was: the nine eval-fixture baselines fail `transitions_missing` on both the old and the new script.

**Detail prefix.** Problems about the pack carry `domain.md`'s line numbers, and their `detail` starts `domain.md:`. Problems about the baseline carry its own line numbers, so the two files stay distinguishable in one report.

## Self-test inventory

**33 tests: 12 for transitions, 21 for `--domain`.** The 21 `--domain` tests, in method order:

1. A full pack with coverage passes and reports `domain`, `rules_defined`, `rules_uncovered`.
2. A missing section fails `domain_pack_malformed` with a `domain.md:` detail.
3. Blank Source, blank Rule, a bad ID and a repeated ID each fail `domain_pack_malformed`.
4. A reasoned `None:` Rules needs no coverage, with or without a `None:` coverage section; a short one fails.
5. Open questions: unresolved, a short `Deferred:` and `Answered: D-9` fail, while a reasoned `Deferred:` passes.
6. `None`, `None.` and `None: …` pass (EC-2), and an empty section fails.
7. Every non-entry Open Questions shape fails `domain_pack_malformed`: `Q-02`, a plain bullet, `1. Q-2`, `None` beside an entry, a continuation line (2026-10-20 red team).
8. Zero-padded IDs that would escape the cap fail `domain_pack_malformed`.
9. A repeated `## Rules` fails `domain_pack_malformed`.
10. A CommonMark closing-hash heading (`## Rules ##`) is the same section as `## Rules`: a second copy written that way is a repeat, and a lone one satisfies the heading.
11. An SD case cited for a rule its Oracle omits fails `oracle_mismatch`.
12. Eleven counted questions fail the cap, and over-cap deferral passes.
13. The no-`--domain` report carries exactly the legacy keys in order.
14. An unreadable `--domain` exits 2, and the ledger `inputs` gains the pack only with the flag.
15. An empty `--domain ""` exits 2; it is a flag given, not an absent one.
16. A missing D-2 row fails `domain_rule_uncovered`, a reasoned `N/A` fixes it, a short one fails `domain_coverage_malformed`, and no coverage section leaves both rules uncovered.
17. An SD case covers its rule (EC-3).
18. Three `suspected_defect_malformed` forms.
19. `oracle_missing`, `oracle_malformed` (four forms plus `code, D-1`), `domain_rule_unknown` from an Oracle, and `DS-4` passing unresolved.
20. `oracle_mismatch`, `domain_rule_unknown` from a coverage row, and `domain_case_missing`.
21. Six `domain_coverage_malformed` forms.

The 12 transitions tests: a full two-row table passes. The Slide gap (an empty Set → Different cell) fails. A reasoned `N/A` passes, while a bare `N/A` and a short reason fail. A cited ID with no heading fails, including one defined only inside a fence. A missing section, an empty `None:`, and a header-only table each fail. A wrong header and a wrong cell count fail. The ASCII `->` header is accepted. A duplicate row fails. CLI exit codes 0/2 each write a chained ledger record. A BOM and a following `##` section bound the table.
