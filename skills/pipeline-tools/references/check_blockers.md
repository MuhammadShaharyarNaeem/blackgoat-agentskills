# check_blockers.py — reference

Depth for the `check_blockers.py` section of `../SKILL.md`.

## Why a whole script for one array

`bgpdd-shipping` Step 0.5 must not enter a launch with standing blockers, and "open the state file and look" is exactly the kind of prose rule convention #9 says to convert: the reader who most wants to proceed is the one being asked to stop. The script makes the check a command whose exit code the pipeline cannot narrate its way past. There is no manual open-and-read substitute.

It is deliberately thin. It does not judge whether a blocker is *real*, whether it belongs to this pipeline, or whether its text is meaningful — `update_state.py --resolve-blocker --evidence` owns the removal discipline, and this gate only asserts the array is empty at the moment it runs. A blocker entry the pipeline invented to satisfy itself is a problem this gate cannot see and does not claim to.

`--ledger` records the run in the family-wide shape so `check_commit_gate.py --require-ledger-gates` and the shipping game tape can tell a gate that fired from a gate that was skipped.

`python scripts/check_blockers.py --self-test` runs 6 in-process cases: the empty array passing, a non-empty array failing, a state object with no `blockers` field, a missing state file, a BOM-prefixed state file still parsing, and the ledger recording every exit path.
