# check_blockers.py — reference

Depth for the `check_blockers.py` section of `../SKILL.md`.

## Why a whole script for one array

`bgpdd-shipping` Step 0.5 must not enter a launch with standing blockers, and "open the state file and look" is exactly the kind of prose rule convention #9 says to convert: the reader who most wants to proceed is the one being asked to stop. The script makes the check a command whose exit code the pipeline cannot narrate its way past. There is no manual open-and-read substitute.

It is deliberately thin. It does not judge whether a blocker is *real* or whether its text is meaningful — `update_state.py --resolve-blocker --evidence` owns the removal discipline, and this gate only asserts that nothing blocking stands at the moment it runs. A blocker entry the pipeline invented to satisfy itself is a problem this gate cannot see and does not claim to.

`--ledger` records the run in the family-wide shape so `check_commit_gate.py --require-ledger-gates` and the shipping game tape can tell a gate that fired from a gate that was skipped.

## The schema migration: why scoping needed a field

Blockers used to be freeform strings, so scoping one to a milestone meant a **substring guess** against that text. A guess cannot tell "not obviously this milestone's" from "not this milestone's", so the only safe reading was to fail closed on every entry — which is what both this gate and `check_commit_gate.py` did, and why a blocker raised against `M7` could hold `M2`'s commit hostage.

The fix is an explicit `milestone` field matched by **exact equality** (case/whitespace-insensitive), with `null` meaning unscoped and therefore still blocking. That is a deliberate refinement of the old "gate on all" rule rather than a loosening of it (convention #8, labelled in the code comments): the fail-safe survives for every entry that genuinely says nothing about scope, and lifts only where the writer stated the scope in a field a parser can read. Legacy strings normalize on read to `{milestone: null, severity: "Critical"}` and are **never rewritten** on disk — a migration that edited a live state file would be a silent write from a read-only gate.

`--severity-floor` answers the other half of the same problem: every legacy entry is Critical by construction, so without a floor there was no way to record an `Info` note in the ledger without it blocking a launch.

`python scripts/check_blockers.py --self-test` runs 16 in-process cases: the empty array passing, a non-empty array failing, a state object with no `blockers` field, a missing state file, a BOM-prefixed state file still parsing, the ledger recording every exit path, the JSON reporting normalized objects, an entry scoped to the named milestone blocking, title matching being case- and whitespace-insensitive, a null-milestone entry still blocking under `--milestone`, an entry scoped elsewhere not blocking, the default floor ignoring `Info` but still blocking `Important`, `--severity-floor Critical` ignoring `Important`, `--severity-floor Info` blocking everything, and an invocation without `--milestone` behaving exactly as before.
