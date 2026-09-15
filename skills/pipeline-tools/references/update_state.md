# update_state.py — reference

Depth for the `update_state.py` section of `../SKILL.md`: persistence guarantees and the blocker-ledger rule it mechanizes.

### Output & persistence

- The write is **atomic**: a temp file is written in the same directory (`tempfile.mkstemp`) and swapped into place with `os.replace`. `updated` (UTC ISO-8601, `YYYY-MM-DDTHH:MM:SSZ`) is stamped on every successful write, even one that only resolves a blocker.
- stdout is always the resulting **full state JSON** (indent 2) on success. Warnings (no-op `--init`, a `--resolve-blocker` that matched nothing) go to **stderr** as `Warning: ...` lines, never stdout — stdout stays parseable.
### The ledger rule this mechanizes

Orchestrator Contract §4's blocker-ledger doctrine — **an entry is removed only once its fix is verified** — is enforced here, not just documented: `--resolve-blocker`'s `--evidence` must be a path that resolves to an existing, non-empty file — tried relative to the state file's own directory first, then the CWD. A missing, empty, or directory path fails the call closed at exit 1 with an `evidence_not_found` / `evidence_empty` / `evidence_is_directory` problem, and nothing is written. And every successful removal appends one line per removed entry to a **`blockers-resolved.log`** file beside the state file (`<ISO timestamp>\t<id>\t<the full entry>\t<evidence text>`), so a removal always leaves an audit trace even though the state file itself only ever shows the current, post-removal `blockers` array.

## The schema migration: why scoping needed a field

`--add-blocker` used to append a freeform string, so scoping one to a milestone downstream meant a **substring guess** against that text. A guess cannot tell "not obviously this milestone's" from "not this milestone's", so the only safe reading was to fail closed on every entry — which is why a blocker raised against one milestone could hold an unrelated one's commit hostage. The writer is the only place that knows the scope, so this is where the field is now supplied: `--blocker-milestone`, `--blocker-capability`, `--blocker-severity`, `--blocker-source`, `--blocker-evidence`, matched downstream by **exact equality** rather than containment (convention #8, labelled in the code comments; the consumer side is in `check_blockers.md`).

Two consequences worth stating:

- **Legacy string entries are never rewritten.** They normalize on read to unscoped Critical, which is the fail-safe reading, and stay on disk as they are. Rewriting them would mean inventing a scope for an entry whose author never stated one.
- **Auto ids are `B-<n>`, one past the highest currently present** — a documented limitation, not a guarantee of uniqueness over time: resolving the top-numbered entry frees its number for reuse. The `blockers-resolved.log` line carries the full entry text, so the audit trail survives an id collision even though the id alone would not distinguish them.

`--resolve-blocker` matches in three widening steps — exact id, then exact text (removing every entry sharing it), then a unique substring — and an **ambiguous substring is exit 2 with a `candidates` list**, never a guess. That ordering exists so the precise target (an id) can never be shadowed by a looser match.

## `--ledger` on a state writer

`update_state.py` is not a gate, so its ledger record is not a verdict anyone gates on — it is the durable half of a blocker resolution. `--resolve-blocker` additionally records `"action": "resolve-blocker"` and `"evidence": "<the --evidence value as given>"` in the ledger line, plus `evidence_resolved` (the resolved path, relative to the state file's directory when possible) and `evidence_sha256` (the resolved file's hash) — so a later reader can verify the exact file that was checked, not just the string typed on the command line. Pipelines therefore pass `--ledger` on `--resolve-blocker` calls and nowhere else — nothing else here makes a claim that outlives the file it writes.

## The game-tape gate on a state writer

`update_state.py` is not a gate, and this is the one place it refuses. The justification is narrow and worth stating: the `--set-cursor` write is the moment a milestone stops being the current one, and `bgpdd-build` Phase 6's checkpoint is evidence *about that milestone* which is cheapest to write while it is still in context and worthless once it is not. So the gate is scoped to exactly that write — `--set-cursor` or `--set-pipeline`, with `--milestone` — and to nothing else. A `--add-blocker` or `--set-artifact` call with the flag warns on stderr and proceeds: a gate that fires when nothing closed is noise, and noise is how a real gate gets waived by habit.

`--require-game-tape` without `--milestone` is exit 2, not a skip. The refusal exits **1** and writes nothing at all — not a partial state with the cursor moved.

`--milestone` also becomes this run's ledger `milestone` value, replacing the previous `--set-cursor`-derived fallback. That fallback recorded the milestone being moved *to*; `--milestone` names the one being closed, which is what the record is about.

## The game-tape heading names its own lane (2.6.1)

`--require-game-tape`'s heading regex was `bgpdd-build` literally, so the flag
was unusable from every other lane: `bgpdd-bugfix` writes its Phase 5 tape
under a `## bgpdd-bugfix - ` heading and could never satisfy a gate that
looked for one word, leaving that lane's tape unenforceable (2026-09-07 audit,
Metric 20 -- "the `--require-game-tape` regex hard-codes `bgpdd-build` so
bugfix's tape is unenforceable"). It is now `bgpdd-<lane>` for any lane name,
with the lane captured so a future message can name it.

Build is unchanged: `bgpdd-build` is one value of `<lane>`. Every SHAPE
requirement is identical for every lane -- 3-6 bullets, at least one fenced
block, a `summarize_run` mention or a table row, the epic-summary heading
excluded, a heading inside a fence not counting, last matching section wins.
The regex and the whole `check_game_tape()` block stay byte-identical in
`mark_milestone.py`, which is the point of duplicating rather than importing
them: the two scripts that perform the closing write must agree exactly.

The near-misses are asserted too: `bgpdd`, `build`, `pdd-build` and
`BGPDD-BUILD` are all `no-section`. The lane token is lower-case by
convention, and a case-insensitive match would let a heading that is not a
lane name satisfy a lane gate.

## `--set-halt` / `--clear-halt` (Unreleased)

`check_redelegation.py` needed a write path for the standing halt it computes: `state["halt"]` is a single object, not a list, because a unit is either halted or it isn't — a second halt on the same unit replaces the first rather than accumulating. `--set-halt` takes the halt as a JSON object (`unit`, `agent`, `code`, `reason`, all required non-empty strings) and merges it in, stamping `added`; a malformed or incomplete object is exit 2 and writes nothing, matching every other structural-failure case in this script.

`--clear-halt <unit>` is deliberately narrow: it only removes `state["halt"]` when the CURRENT halt's `unit` matches the one named, and it requires a non-empty `--reason` naming what changed in the world. Both restrictions trace to the same design decision made in `check_redelegation.py`'s own contract — that script never clears its own halt, on any result, from any agent, because a blocker in the `environment`/`credentials`/`dependency` category is a fact about the unit's surroundings, not about whether the latest handoff happened to read clean. Clearing is therefore a human act with a recorded justification, and `--reason` is where that justification lives; omitting it (or passing blank) is exit 2, the same shape as `--resolve-blocker`'s mandatory `--evidence`. A `--clear-halt` naming a unit that isn't the one currently halted — or naming one when nothing is halted at all — is a no-op warning, not an error: there is no malformed state to refuse, just nothing to do.

Self-test count: 47 → 60, adding the `--set-halt`/`--clear-halt` round trips (merge, malformed JSON, missing keys, blank-reason clear, matching-unit clear, mismatched-unit clear, no-op-when-absent, and the ledger record's `action`/`unit`/`code`/`reason` fields) through both `apply_updates` directly and `main`.

## `--set-status` (Unreleased)

Merges `state["status"] = STATUS` plus a `status_updated` timestamp, the same shape `--set-halt` stamps `ts` in. `STATUS` is one of `active`, `escalated`, `closed`, validated by argparse `choices` — an unknown value exits 2 before anything is read or written. `--reason` is optional here (unlike `--clear-halt`, which requires it) and, when given, is recorded on the ledger line alongside the new status and the status this call overwrote (`previous_status`, omitted when there was none to overwrite).

Written by `bgpdd-bugfix` Phase 2 step 5 and Phase 5 step 4 (standalone route) when a lane HALTs and escalates to another pipeline, so `guard_action.py`'s `lane_is_closed()`/`unfixed_bugfix_lanes()` can treat the lane as closed without waiting on the 12h freshness window to age it out — see `guard_action.md`.

Self-test count: 60 → 69.
