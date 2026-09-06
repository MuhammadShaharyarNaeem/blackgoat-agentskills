# check_acceptance_suite.py — reference

Depth for the `check_acceptance_suite.py` section of `../SKILL.md`: structure mode's blocking conditions, the results grammar, the parsing rules, the scope limits and mode divergences, and the fixture inventory.

### Structure mode (`--lint-only`)

Two gates, one script, because they read the same grammar and a second file would drift into a shadow contract. `--lint-only` runs at **plan time on Alex's output**, before any code exists and therefore before there is anything to execute.

`--results` **with** `--lint-only` is a usage error (exit 2), not a silent ignore: the two modes answer different questions, and a caller who passes both has misunderstood which one they wanted. `--require-priority` is still validated but **does not scope linting** — structural validity is priority-blind, since a broken scenario is broken at every priority — and passing it emits a warning saying so. `--repo` is accepted and ignored (nothing resolves paths in structure mode, and nothing reads an mtime, so there is no freshness dimension here).

Blocking conditions, each with its own JSON array so the failure is addressable rather than a single boolean:

| Array | Defect |
|---|---|
| `missing_priority` | scenario heading declares no `P0`–`P3` — cannot be execution-scoped honestly |
| `missing_step_table` | no table with `GO`/`DO`/`ASSERT` columns — the scenario proves nothing |
| `missing_columns` | no `Stores` or no `Mode` column |
| `unrecognized_mode` | a `Mode` cell that is neither `auto` nor `manual` |
| `missing_stores` | `DO` reads as state-changing but `Stores` is empty — the inverse check cannot run |
| `duplicate_keys` | a scenario id on two headings, or a step number twice in one scenario — `[inverse of N]` and result keys would both be ambiguous |
| `malformed_steps` | `GO`, `DO` and `ASSERT` all empty — a phantom row |
| `dangling_inverse` | `[inverse of N]` naming a step that does not exist |
| `invalid_exemption` | `[no inverse: …]` with no reason text, or on a step that also declares `[inverse of N]` |
| `undeclared_inverse` | a state-changing step with neither an inverse nor an exemption |
| `lint_failures` | check `fr-scenario-coverage` — a Must-Have FR/NFR cited by no scenario heading (only with `--requirements`) |

**`--requirements <path>` gates the FR→scenario link**, and is accepted **only** with `--lint-only` — passing it in execution mode is exit **2**, the same mode-separation rule `--results`-with-`--lint-only` enforces read from the other end: the link is a plan-time question about the matrix, and answering it says nothing about whether the matrix was run. Must-Have tiers are read with `check_coverage.py`'s parser, duplicated verbatim so the two gates recognize one document convention rather than two dialects; every Must-Have ID must appear in at least one scenario heading's parenthesized requirement list, and each one that does not appends a `lint_failures` entry `{check: "fr-scenario-coverage", task: <ID>, detail: …}` and forces exit **1**. **Should-Haves never gate** — an uncited one lands in `uncovered_should` with an advisory warning. An ID cited by a heading but absent from requirements.md **warns**, matching `check_coverage.py`'s unknown-id path; only FR/NFR-shaped tokens are considered, so a heading citing `EC-2` is not accused of naming an unknown requirement. A requirements file that is unreadable or declares **zero** Must-Haves is exit **2** — same posture as `check_coverage.py`, because a gate with nothing to gate must not report green. Omitting the flag leaves the link unchecked, which is why `bgpdd-plan` Phase 3.5 passes it. Presence in a heading is checkable; whether the scenario *exercises* the requirement is not, and stays with the human reading the matrix.

**`missing_columns` blocks here where execution mode only warns** — a labelled divergence (convention #8). Without `Stores` and `Mode`, the Mode check, the Stores check and the inverse check all silently no-op, so a green lint would mean "nothing was checkable": precisely the failure mode this whole tier exists to close.

**The exemption escape hatch.** `[no inverse: <reason>]` anywhere on the row, case-insensitive, satisfies the inverse requirement. The reason must contain at least one letter — `[no inverse: -]` is refused. **Presence is checkable; truth is not.** The gate cannot know whether "a queued distribution job cannot be un-queued" is true. The marker buys an author nothing except a place to be wrong in writing, where a human reviewer can see it. That is still strictly better than the alternative, which is an inverse silently absent.

### The results grammar Quinn emits

`acceptance-results.md` reuses `check_agent_report.py`'s check-line grammar, keyed by step:

```
- AS-2.1: PASS — exit 0 — 200, mapping row client A -> slide-c-882
- AS-3.5: PASS — evidence/runtime/as3-5-agent-uninstalled.md — agent absent, service deregistered
```

`- <ScenarioId>.<StepNumber>: <PASS|FAIL|BLOCKED|NOT RUN> — <detail>`. The separator is a **dot**, deliberately not a dash (`AS-2-4` is ambiguous with the id's own dash); a mis-keyed line lands in `extra_results` as a warning while the step it meant to cover lands in `missing_results` as a block, so the mistake fails loud rather than silently binding the wrong step. Step keys are self-describing, so `##` headings in the results file are informational and never parsed — that removes the whole "which section was this result under" scoping problem `test-report.md`'s human-only `#Task [N]:` headers force on other parsers. Duplicate keys: **latest wins**, so a retest appends rather than edits.
### Parsing rules (condensed)

- **Scenario** = a `##` heading containing an id matching `\b[A-Za-z]{1,6}-\d+\b`; priority from `\bP([0-3])\b` in the heading; requirement IDs collected only from **inside parentheses** in the heading, so the scenario's own `AS-2` is never mistaken for a requirement. A scenario with **no** priority token is gated anyway, with a warning — an unprioritized scenario cannot be filtered honestly.
- **Step table** = the first table under the scenario whose header cells include `go`, `do`, and `assert`; columns are looked up **by header name**, so column order is free. `Stores` splits on `, / ; +`.
- **`Mode` fails closed.** `manual` demands evidence, so an unrecognized value must not be the cheaper option: a cell that is present but is neither `auto` nor `manual` — `Manual!`, `semi`, `manual (device)` — is gated **as manual**, with a warning saying it was gated that way because the mode was unrecognized rather than because it declared manual. A blank cell or an absent column still defaults to `auto`; that boundary is deliberate, since retroactively making a pre-`Mode` matrix evidence-bearing would break callers, and `--lint-only` blocks the missing column anyway. Before this, `semi` was silently read as `auto` and a device step citing nothing passed green — verified against the previous revision, not assumed.
- **A gated scenario whose step table does not parse blocks.** One misspelled header cell (`Asserts` for `ASSERT`) drops the entire table, so its steps never enter the step list and can never land in `missing_results`, `not_run` or `unevidenced_manual` — an unevidenced manual device step exited 0/PASS on nothing but a spelling. It now lands in `missing_step_table` in **both** modes. Scoped to *gated* scenarios in execution mode so priority filtering keeps its meaning. This is the same class as `dangling_inverse`, which already blocks in both modes: the artifact misrepresenting its own coverage, not a coverage judgment — and unlike `undeclared_inverse` it rests on no heuristic.
- **`[inverse of N]`** is matched over the whole row line, so placement is free, and resolves **scenario-locally**.
- **Manual evidence** is accepted only if the cited token is path-shaped, passes the same `..`-refusing `evidence/runtime/` containment scan `check_runtime_evidence.py` uses, **and** resolves to an existing file against the results file's directory, then `--repo`, then `.`, then as given.

### Scope limits

Verifies the matrix was **executed and evidenced** — never that a scenario is the *right* scenario, that its ASSERT column asserts the right thing, or that preconditions and ordering were honored; authoring is Alex's judgment and stays reviewable prose. It **never opens** a cited capture beyond an existence check — whether the capture is honest (out-of-process transport, freshness, response keys) is `check_runtime_evidence.py`'s job, and running both is the point. **Auto steps are trusted on their `PASS` token** with no exit code required — deliberately narrower than `check_agent_report.py`, because auto steps are already covered by the per-milestone test and commit gates.

**`undeclared_inverse` blocks under `--lint-only` and stays advisory in execution mode.** A deliberate mode divergence (convention #8), refining the "every state-changing step exercises its inverse" doctrine rather than contradicting it: same signal, opposite posture, because both the cost of the fix and the meaning of green differ by phase.

At **plan time** the matrix *is* the artifact under authorship, the fix is a one-line edit, and there is nothing else green could mean — so it blocks. At **build time** the code is already written, so blocking would ask Quinn to author a scenario Alex owed weeks earlier; the `state_changing` detector rests on a mutating-verb **allowlist** and is knowably incomplete, and a blocking gate built on an incomplete heuristic teaches that green means "the heuristic found nothing"; and legitimate one-way steps exist (nothing un-distributes a queued job, nothing un-reinstalls) — so it warns. A **dangling** `[inverse of N]` blocks in both modes at every priority, because that is the artifact misrepresenting its own coverage rather than a coverage judgment. The consequence of a genuinely missing inverse is still caught and still blocks at build — as `missing_results`, if Alex wrote the step and Quinn didn't run it.

### Fixtures & self-test

`fixtures/acceptance-happy/` (exit **0**), `-missing-inverse/`, `-unevidenced-manual/`, `-notrun/` (exit **1** each) — all four modelling the Slide RMM journey: connect → map → green tick → add policy → distribute → verify installed on device → remove → verify uninstalled → reinstall, across 4 scenarios and 14 steps with 3 manual steps citing real captures. The happy fixture deliberately carries a non-empty `undeclared_inverse` while still exiting 0, which is the proof the advisory is genuinely non-blocking.

**`acceptance-happy` exits 0 in execution mode and 1 under `--lint-only`, and that is correct, not a broken fixture.** It is the mode divergence demonstrated on one unchanged input: the same two uninstall/reinstall steps that are legitimately one-way are tolerated at build time and demanded in writing at plan time. Read it as documentation of the posture change rather than as a defect.

`fixtures/acceptance-lint-inverse/` is structure-mode only — a matrix with no results file and no evidence directory, isolating one signal. Two matrices differing by exactly one marker: `acceptance-matrix.md` exits **1** with `undeclared_inverse: ["AL-2.2"]` (a policy distribution nothing undoes) and every other array empty; `acceptance-matrix-exempt.md` adds `[no inverse: a queued distribution job cannot be un-queued; AL-2.4 removes the policy instead]` and exits **0** with `exempt_steps: ["AL-2.2"]`. The pair is the escape hatch's proof that the blocking path is satisfiable rather than a dead end.

`python scripts/check_acceptance_suite.py --self-test` runs 102 in-process cases covering the twelve `--emit-gate-args` cases below and the manual-evidence capture shape and `--changed-files` freshness plus matrix/results parsing, every blocking condition in both modes, the FR→scenario link (a covered Must-Have, an uncited one naming `fr-scenario-coverage`, an uncited Should-Have that stays green, an unknown cited ID that only warns, a non-FR citation that is not an unknown ID, and both exit-2 paths), the manual-evidence paths (missing file, `evidence/build/` instead of `evidence/runtime/`, `..` traversal, resolution against `--repo`, a `.docs/`-prefixed citation keeping its leading dot), dangling vs undeclared inverses, cross-scenario inverse non-resolution, priority-scope semantics, every structural lint condition, the exemption grammar including the both-markers contradiction and the no-op-on-a-read-only-step warning, the two fail-closed regressions (an unrecognized `Mode`, an unparsed step table) with their ungated/blank-cell boundaries, key parity between the two modes' output, and every exit-2 trigger.

## `--emit-gate-args` — the transcription step, removed

`bgpdd-verify` Phase 3 runs `check_runtime_evidence.py` with `--surface`, `--require-key`, `--expect-status` and `--forbid-host` taken **from the matrix's `## Environment` preamble**, and told the Orchestrator to copy them by eye — while labelling itself an interim, because a rule that asks for careful transcription is exactly the shape convention #9 says becomes a tool. The failure it invites is silent and total: a mistyped `--require-key` or a loosened `--expect-status` turns the runtime gate into one that passes an assertion nobody chose, and the paste-the-argv-into-the-game-tape rule only makes it *auditable after the fact*.

This flag emits them instead. It is the counterpart of `next_milestone.py --emit-gate-args`, which reads a plan's `RUNTIME PROBE:` line, and it borrows that parser's posture wholesale:

- **Advisory.** It never changes an exit code, in either mode. It is a reader of the matrix, not a judge of it.
- **Conservative.** A field it cannot read confidently comes back null/empty **with a warning naming why**, so the caller supplies it explicitly. A guess that reads as a declaration is worse than no emission.
- **Ambiguity is not last-wins.** A repeated `Surface` or `Expect status` — which a per-surface preamble legitimately writes — emits nothing for that field and names the conflict. Silently picking one is precisely the transcription error the flag exists to prevent.
- **No new lint.** Nothing here requires the preamble to exist: the build and lite lanes' matrices legitimately have none, and adding a structural requirement would fail them for a flag they never pass.

Grammar and key names live in `../SKILL.md`. The self-test covers: reading a full preamble into `argv`; absence without the flag; verdict-invariance with and without it; lint-mode emission; a missing preamble; two statuses; two surfaces; a non-identifier key; placeholder values; a **fenced** preamble declaring nothing (family rule); the section ending at the next heading, so a scenario's own `Surface: api | …` line is not the preamble; and the CLI path.

## Manual evidence must BE a capture, and freshness (P2b)

A cited manual evidence file must live under `evidence/runtime/`, exist, be **non-empty**, and carry a `## Captured output` section. The previous existence-only check accepted an empty placeholder file with the right name: the citation was checkable, the artifact proved nothing. Whether the capture is HONEST — out-of-process transport, real client, sidecar — stays `check_runtime_evidence.py`'s job, and running both is still the point.

**`--changed-files` adds the freshness dimension**: the results file's mtime must be `>=` the newest changed file, else `stale_results: true`, exit 1; a nonexistent path is exit 2 (`changed_file_missing`), never a warning. The same mtime-proxy limitation the sibling gates document applies. With `--lint-only` it is exit 2 — structure mode reads no mtimes.

**Auto steps keep PASS-token trust** — a documented scope limit, unchanged: they are already covered by the per-milestone test and commit gates.

**Where `--changed-files` is deliberately NOT passed (convention #8 — refining the freshness rule above, not contradicting it).** `bgpdd-build` Phase 5 step 2.5b and `bgpdd-verify` Phase 3 invoke this gate immediately after the Quinn delegation that produced `acceptance-results.md`, so freshness holds by construction and the flag would only add a way to mis-declare it. `bgpdd-shipping`'s re-execution runs against a tree that moved since the build closed, which is the one place staleness is actually possible — so that is the one call site that passes it.
