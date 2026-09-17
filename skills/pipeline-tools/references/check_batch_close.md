# check_batch_close.py — reference

Depth for `check_batch_close.py`. The contract of record is the script's own `--help` (`python scripts/tool_registry.py show check_batch_close`); this page holds only the reasoning behind it.

## What failure this converts

`bgpdd-bugfix-batch`'s close was prose only: write a final table, remove each bug's worktree, and assert that nothing was skipped. All three are asked for at the moment the Orchestrator most wants to be finished — the wave is over, every per-bug lane reported green, and the remaining work is bookkeeping. CLAUDE.md convention #9 says a rule asked for at exactly that moment becomes an artifact that has to be run, not stronger prose.

The three things it makes checkable map one-to-one onto the three ways a batch closed badly:

- **A bug that never reached a terminal status.** A rebase HALT, an escalation, or simply a bug the wave ran out of time for leaves its status open. The final table is hand-written, so an open bug can be omitted from it entirely and the batch reads as closed.
- **A bug marked merged that no commit gate ever passed.** The batch layer records status; the *commit* lives in that bug's own lane. Reading the batch state alone cannot tell a merged bug from one somebody typed `MERGED` beside, so the gate goes to each merged bug's own ledger and looks for its commit gate's recorded pass carrying the commit flag.
- **A worktree still on disk.** The per-bug worktree is the working copy the wave built in; leaving it behind is how a later session picks up a stale tree and rebuilds a fix that already landed. An open bug's worktree is *expected* to still exist and is deliberately not checked — only a terminal bug's removal is asserted.

## Why it verifies its own ledger's chain before reading it

Unlike every other reader in this family, this gate verifies the chain of the ledger it is about to append to, before trusting anything already in it. The batch ledger is the only durable record that the wave happened at all, and this gate is the last thing that reads it; a broken chain discovered after the close is discovered by nobody.

## Why it is the sole writer of the batch ledger

`{batch-root}/gates.jsonl` was claimed as a batch-layer record with no script that ever wrote to it. That is the deliberate divergence (CLAUDE.md convention #8) from `check_ledger.py`'s "the ledger is the subject under test, not an append target": there, appending would extend the chain being reported on; here, appending **is** the reason the file exists. This gate chains its own record on every exit path, exactly like every other gate in the family.

## What it deliberately does not do

It touches no git, commits nothing and removes no worktree. Those are the Orchestrator's own close steps, performed by hand before this runs; the gate verifies what they left behind. A gate that performed the close as well as verifying it would be grading its own submission — the same separation the spine's *Single contract authority* section draws between the gates that decide and the agents that produce.

It also never re-derives a per-bug phase. A bug's state belongs to its own lane driver (`pipeline_driver.py --lane bugfix`), and a second derivation here would be a second table to keep in step.
