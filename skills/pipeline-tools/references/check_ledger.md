# check_ledger.py — reference

Depth for `check_ledger.py`. The contract of record is the script's own `--help` (`python scripts/tool_registry.py show check_ledger`); this page holds only the reasoning behind it.

## Why the ledger had to become a chain

The gate ledger is the evidence four later gates read a verdict out of — `check_commit_gate.py --require-ledger-gates`, `check_ship_decision.py --require-ledger-gates`, `mark_milestone.py --require-gates`, and `check_quick_close.py`'s implied authenticity lookup. Until it was chained it was a text file anybody could retype: a FAIL line edited to PASS, or simply deleted, left no trace at all, and every gate downstream read the doctored file as though a run had produced it.

So each record carries a hash of the previous line's bytes and a hash of its own canonical serialization. A record edited, inserted or removed after the fact now breaks either its own hash or the following line's.

## Why it is not a gate, and writes nothing

Every other script in this family appends its own record to `--ledger`. This one must not: `--ledger` here is the **subject under test**, and appending to the chain it is reporting on would extend the artifact it is meant to read. That is a deliberate divergence (CLAUDE.md convention #8) from the family rule that every gate carries `--ledger`, and it is why this script was documented inside the spine's shared *Gate ledger* section rather than as a gate of its own.

## The limit, stated rather than papered over

The chain detects tampering that is **local**, not tampering that is **thorough**. A forger who rewrites the entire tail — recomputing every previous-hash and self-hash from the edit point onward — passes, and truncating trailing records is undetectable for the same reason: there is no external anchor, no signature and no notary. Closing that needs a secret the runtime does not have, so no flag here pretends to. What the chain buys is that a casual edit stops being free.

That limit is the ledger's half of the family-wide unkeyed-artifact gap the spine states under *The capture sidecar, and why the body witnesses it*; a self-test case asserts the tail-truncation limit so it cannot quietly regress into a claim the tool does not make.

## Migration, and why reverting is a refusal

A record written before the chain contract carries neither hash. Such legacy records are tolerated only **before** the first chained record — a pre-chain ledger migrates forward simply by being appended to. Once a chained record exists, an unchained one after it is refused, because reverting to unchained is exactly what deleting the chain looks like.

The practical consequence for anyone adding a gate to this family: a new script that copies an older, unchained append helper will break every chained ledger it touches. Two drift guards in the self-test exist for that case — the helper block must be byte-identical everywhere it appears, and every chaining gate must actually set both hash fields before it writes.

## Who re-checks the chain, and when

The gates that read a verdict out of a ledger verify the chain **before** looking at any verdict, and fail with their own chain-broken code. The short-circuit is deliberate: naming which gate recorded a PASS is pointless when the file it was read from is not trustworthy. A PASS read out of a tampered ledger is not a weaker PASS; it is no PASS.

## 2026-09-30 — appends are locked

Two concurrent `run_quiet.py --capture` calls broke a real ledger at line 300: both read the same last line, both wrote the same `prev`. On Windows the race was worse than a false chain break — overlapping appends overwrote each other, so records were lost too (a 6-process × 40-record repro kept 216–230 of 240 lines and broke the chain in 10/10 trials).

Every gate now appends through `ledger_append(p, record)`, which lives in the shared, byte-identical helper block beside `ledger_prev_hash`. It holds `LedgerLock` from reading the last line through the closed, flushed write. The lock is an OS lock on the ledger file itself — `fcntl.flock` on POSIX, a `msvcrt.locking` byte far past EOF on Windows, where the lock is mandatory and so has to sit where no read or append reaches. That was chosen over an `O_CREAT|O_EXCL` sidecar file because the OS releases the lock when its holder dies: a killed gate leaves no stale lock file that stalls every later append. The wait is bounded (10 s, 5 ms polls). A timeout or any lock error prints a stderr warning and the append goes ahead unlocked, so the fallback never raises, never skips its own append and never changes an exit code; an unlocked append may still collide with a concurrent one. The 5 s first draft starved under the 240-append burst on a loaded host, which is why the bound is 10 s.

The drift guards follow the call site. The append line now lives inside the helper block, so detection and the chaining check read the source **outside** that block. A gate must call `ledger_append(p, record)` there, and a raw `open(p, "a", …)` or a hand-set `prev` outside it fails. `test_concurrent_appenders_produce_an_intact_chain` runs four processes × 50 records against one ledger. With the lock removed it failed 5/5 runs (120 of 200 records survived).

`record_run.py` is deliberately left out. Its run-log append never reads the last line, so it does not share the `prev` race. It does share the Windows overlapping-append exposure. Six processes × 40 records through `append_record` kept 175–186 of 240 intact lines in 5/5 trials. **Resolved 2026-09-30:** `record_run.py` now takes its own local `RunLogLock` (same design, no chain helper); see the 2026-09-30 entry in `references/record_run.md`.
