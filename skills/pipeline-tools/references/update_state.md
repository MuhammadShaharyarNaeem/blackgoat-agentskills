# update_state.py — reference

Depth for the `update_state.py` section of `../SKILL.md`: persistence guarantees and the blocker-ledger rule it mechanizes.

### Output & persistence

- The write is **atomic**: a temp file is written in the same directory (`tempfile.mkstemp`) and swapped into place with `os.replace`. `updated` (UTC ISO-8601, `YYYY-MM-DDTHH:MM:SSZ`) is stamped on every successful write, even one that only resolves a blocker.
- stdout is always the resulting **full state JSON** (indent 2) on success. Warnings (no-op `--init`, a `--resolve-blocker` that matched nothing) go to **stderr** as `Warning: ...` lines, never stdout — stdout stays parseable.
### The ledger rule this mechanizes

Orchestrator Contract §4's blocker-ledger doctrine — **an entry is removed only once its fix is verified** — is enforced here, not just documented: the CLI physically refuses `--resolve-blocker` without a stated `--evidence` string. And every successful removal appends one line per removed entry to a **`blockers-resolved.log`** file beside the state file (`<ISO timestamp>\t<id>\t<the full entry>\t<evidence text>`), so a removal always leaves an audit trace even though the state file itself only ever shows the current, post-removal `blockers` array.

## The schema migration: why scoping needed a field

`--add-blocker` used to append a freeform string, so scoping one to a milestone downstream meant a **substring guess** against that text. A guess cannot tell "not obviously this milestone's" from "not this milestone's", so the only safe reading was to fail closed on every entry — which is why a blocker raised against one milestone could hold an unrelated one's commit hostage. The writer is the only place that knows the scope, so this is where the field is now supplied: `--blocker-milestone`, `--blocker-capability`, `--blocker-severity`, `--blocker-source`, `--blocker-evidence`, matched downstream by **exact equality** rather than containment (convention #8, labelled in the code comments; the consumer side is in `check_blockers.md`).

Two consequences worth stating:

- **Legacy string entries are never rewritten.** They normalize on read to unscoped Critical, which is the fail-safe reading, and stay on disk as they are. Rewriting them would mean inventing a scope for an entry whose author never stated one.
- **Auto ids are `B-<n>`, one past the highest currently present** — a documented limitation, not a guarantee of uniqueness over time: resolving the top-numbered entry frees its number for reuse. The `blockers-resolved.log` line carries the full entry text, so the audit trail survives an id collision even though the id alone would not distinguish them.

`--resolve-blocker` matches in three widening steps — exact id, then exact text (removing every entry sharing it), then a unique substring — and an **ambiguous substring is exit 2 with a `candidates` list**, never a guess. That ordering exists so the precise target (an id) can never be shadowed by a looser match.

## `--ledger` on a state writer

`update_state.py` is not a gate, so its ledger record is not a verdict anyone gates on — it is the durable half of a blocker resolution. `--resolve-blocker` additionally records `"action": "resolve-blocker"` and `"evidence": "<text>"` in the ledger line. The CLI still cannot judge whether "trust me" is real evidence; the ledger makes the claim durable and attributable instead of gone the moment the array shrinks. Pipelines therefore pass `--ledger` on `--resolve-blocker` calls and nowhere else — nothing else here makes a claim that outlives the file it writes.
