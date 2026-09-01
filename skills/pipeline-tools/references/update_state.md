# update_state.py — reference

Depth for the `update_state.py` section of `../SKILL.md`: persistence guarantees and the blocker-ledger rule it mechanizes.

### Output & persistence

- The write is **atomic**: a temp file is written in the same directory (`tempfile.mkstemp`) and swapped into place with `os.replace`. `updated` (UTC ISO-8601, `YYYY-MM-DDTHH:MM:SSZ`) is stamped on every successful write, even one that only resolves a blocker.
- stdout is always the resulting **full state JSON** (indent 2) on success. Warnings (no-op `--init`, a `--resolve-blocker` that matched nothing) go to **stderr** as `Warning: ...` lines, never stdout — stdout stays parseable.
### The ledger rule this mechanizes

Orchestrator Contract §4's blocker-ledger doctrine — **an entry is removed only once its fix is verified** — is enforced here, not just documented: the CLI physically refuses `--resolve-blocker` without a stated `--evidence` string. And every successful removal appends one line per removed entry to a **`blockers-resolved.log`** file beside the state file (`<ISO timestamp>\t<removed entry text>\t<evidence text>`), so a removal always leaves an audit trace even though the state file itself only ever shows the current, post-removal `blockers` array.

## `--ledger` on a state writer

`update_state.py` is not a gate, so its ledger record is not a verdict anyone gates on — it is the durable half of a blocker resolution. `--resolve-blocker` additionally records `"action": "resolve-blocker"` and `"evidence": "<text>"` in the ledger line. The CLI still cannot judge whether "trust me" is real evidence; the ledger makes the claim durable and attributable instead of gone the moment the array shrinks. Pipelines therefore pass `--ledger` on `--resolve-blocker` calls and nowhere else — nothing else here makes a claim that outlives the file it writes.
