# mark_milestone.py — reference

Depth for the `mark_milestone.py` section of `../SKILL.md`: why the write side of the `[x]` convention exists, and how its refusals differ from the commit gate's.

## Why a tool writes the marker

`next_milestone.py` reads completion from a `[x]` appended to a milestone heading — and until this file existed, that `[x]` was a hand edit tied to nothing. A milestone could be marked done by typing three characters: no commit, no gate, no evidence. This is convention #9's conversion of the completion rule: the prose said a milestone closes only through its gate, and the artifact that recorded closure was a keystroke.

Both backings are **opt-in**, because a plan may legitimately be marked up before a repo exists (a docs-only milestone, a spike). What is not optional is that the marker is written by a tool that leaves a ledger record, so a completion is always attributable afterwards.

- `--require-commit` — HEAD's history must carry a commit naming the milestone (`git log --fixed-strings --grep="<title>"`). Nothing found is `no_commit`.
- `--require-gates` (default `check_commit_gate.py`, requires `--ledger`) — the LATEST ledger entry for each named gate, scoped to this milestone, must record `PASS`. Missing is `ledger_missing`; a non-PASS latest entry is `ledger_failed`.

## Matching and the diff it writes

The title match is case-insensitive and **whole-token**: `Milestone 1` never marks `Milestone 10`, the same word-boundary rule `check_commit_gate.py` uses for review sections and `check_runtime_evidence.py` uses for capture scoping. `MILESTONE_HEADING_RE` is duplicated verbatim from `next_milestone.py` — the write side must recognize exactly the headings the read side does, or a marked milestone would be invisible to the router.

Line endings and BOM survive; the diff is one character. Two headings matching the same title is `ambiguous_milestone` rather than a guess, and a heading that already carries `[x]` is `already_complete` rather than a second marker.

## Deliberate divergence (convention #8)

`check_commit_gate.py --require-ledger-gates` re-hashes every input the named gate recorded, so a stale PASS is caught. `mark_milestone.py --require-gates` checks the **verdict only**. The tighter check belongs at the commit, which is the moment the restraint is least convenient; here the commit has already happened and the ledger entry it produced is the thing being recorded. Duplicating the re-hash would make the marker refuse work the gate already let through, for no new signal.
