# mark_milestone.py — reference

Depth for the `mark_milestone.py` section of `../SKILL.md`: why the write side of the `[x]` convention exists, and how its refusals differ from the commit gate's.

## Why a tool writes the marker

`next_milestone.py` reads completion from a `[x]` appended to a milestone heading — and until this file existed, that `[x]` was a hand edit tied to nothing. A milestone could be marked done by typing three characters: no commit, no gate, no evidence. This is convention #9's conversion of the completion rule: the prose said a milestone closes only through its gate, and the artifact that recorded closure was a keystroke.

- `--require-commit` — HEAD's history must carry a commit naming the milestone (`git log --fixed-strings --grep="<title>"`). Nothing found is `no_commit`. Still **opt-in**, because a plan may legitimately be marked up before a repo exists.
- `--require-gates` (default set `check_commit_gate.py`, requires `--ledger`) — the LATEST ledger entry for each named gate, scoped to this milestone, must record `PASS`. Missing is `ledger_missing`; a non-PASS latest entry is `ledger_failed`. **On by default**, see below.

## The default was a documentation claim (fixed 2026-09)

`--require-gates` was opt-in while its own help text read "(default: `check_commit_gate.py`)" — the default described the *value list* used when the flag was passed with no names, not whether the requirement applied. So `mark_milestone.py --plan plan.md --milestone "Milestone 2"` appended the `[x]` and exited 0 with nothing behind it: the same three-keystroke completion this file exists to replace, now performed by a tool and recorded in a ledger as though it were backed. A closed default that only holds when you remember a flag is not a closed default (convention #9 — the restraint has to bind where it is least convenient).

Now: no flag means the default gate set applies, which requires `--ledger`, so a bare invocation is **exit 2** and names both remedies. The opt-out for the genuine docs-only / spike case is **explicit — `--require-gates none`** (`off`/`no`/`-` also accepted), which lands in the ledger record's `argv`; `--require-gates ""` still means the default set, deliberately not the same thing. `bgpdd-build`'s invocation already passed `--ledger --require-commit`, so the change tightens that lane rather than breaking it.

## Matching and the diff it writes

The title match is case-insensitive and **whole-token**: `Milestone 1` never marks `Milestone 10`, the same word-boundary rule `check_commit_gate.py` uses for review sections and `check_runtime_evidence.py` uses for capture scoping. `MILESTONE_HEADING_RE` is duplicated verbatim from `next_milestone.py` — the write side must recognize exactly the headings the read side does, or a marked milestone would be invisible to the router.

Line endings and BOM survive; the diff is one character. Two headings matching the same title is `ambiguous_milestone` rather than a guess, and a heading that already carries `[x]` is `already_complete` rather than a second marker.

## Deliberate divergence (convention #8)

`check_commit_gate.py --require-ledger-gates` re-hashes every input the named gate recorded, so a stale PASS is caught. `mark_milestone.py --require-gates` checks the **verdict only**. The tighter check belongs at the commit, which is the moment the restraint is least convenient; here the commit has already happened and the ledger entry it produced is the thing being recorded. Duplicating the re-hash would make the marker refuse work the gate already let through, for no new signal.
