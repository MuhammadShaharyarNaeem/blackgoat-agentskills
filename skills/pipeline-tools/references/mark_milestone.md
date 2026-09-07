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

## `--require-game-tape` — the cadence gate

`bgpdd-build` Phase 6 fires each time a milestone closes, and "write the checkpoint" is a restraint rule asked of the Orchestrator at the exact moment it wants to move to the next milestone — the shape convention #9 says must become a mechanical gate. The two scripts that perform the closing write both carry the flag with a byte-identical implementation: this one, and `update_state.py` on the `--set-cursor` move. Either alone would leave a path around it.

The five checks and their codes are documented once, in `../SKILL.md` under `update_state.py`. Two of them are worth the note here:

- **The epic-summary heading does not count.** `## bgpdd-build — epic summary — <date>` is the roll-up, written once; accepting it would let one section close every milestone in the plan.
- **Fences are blanked before the heading and bullet scan.** A checkpoint pasted inside a fenced example — the way this file's own templates are written — is a template, not a record. The fenced-block *count* is taken from the raw text, because that block is the pasted output the gate is asking for.

## The chain, and what `--require-gates` now checks

The verdict-only divergence below is unchanged. What is new is that the ledger's hash chain is verified before any verdict is read, and a break is `ledger_chain_broken`. That is **not** a divergence from the commit gate — an intact chain is a precondition for reading anything out of the file, not a stricter reading of what is in it.

## `--reopen`: the one write that destroys a verdict (2.6.1)

Completion was a one-way door. `already_complete` refused a second mark,
nothing removed the marker, and a `bgpdd-shipping` finding against a milestone
whose `[x]` was already written had nowhere to go: `next_milestone.py`
reported DONE, this script refused, and the only route back into the plan was
the hand edit this file exists to replace. The 2026-09-07 audit recorded that
as one half of the shipping-to-build re-entry deadlock (Metric 13); the other
half is the missing `--set-pipeline` write.

`--reopen "<milestone>"` removes that milestone's `[x]`. Three flags are
mandatory beside it, all exit 2 when absent:

- **`--evidence <path>`**, and the file must exist. The finding that justifies
  reopening -- a shipping finding, a failing capture, a report. A path that
  does not resolve is not evidence.
- **`--reason "<text>"`**, non-empty after stripping. What the evidence shows,
  in the words of whoever decided.
- **`--ledger <path>`**. This is the only write here that DESTROYS a recorded
  verdict, so it is never unrecorded.

`--require-commit` and `--require-game-tape` are exit 2 beside it: they are
backing terms for a CLOSE, and asking a reopen to prove the milestone was
finished inverts the claim it exists to withdraw. `main_reopen()` is a
separate entry point for the same reason rather than a branch inside the mark
path.

The chained record carries `action: "reopen"`, the evidence path, its sha256
and the reason. **The original close record stays**: a reopen appends a line
to the history, it never edits one, so the ledger reads as "closed on the 4th,
reopened on the 7th because ..." rather than as a milestone that was never
closed.

### Why the marker is removed, not replaced with a `[ ]`

The S1 brief said "flips `[x]` to `[ ]`". This grammar has no `[ ]` token:
completion is the PRESENCE of `[x]`, and `next_milestone.py` builds a
milestone's title by stripping the heading prefix and right-stripping --
nothing else. An appended `[ ]` would therefore become part of the title, and
that title is what every later gate is scoped by (`--milestone`), so one
milestone's ledger records would silently split into two names across the
reopen. Removing the marker restores the heading to exactly its pre-close
bytes, which is what a reopen means and what the round-trip test asserts by
driving the real `next_milestone.py` and reading `NEXT` back.

## The game-tape heading names its own lane

`--require-game-tape`'s heading regex was `bgpdd-build` literally, so the flag
was unusable from every other lane: `bgpdd-bugfix` writes its Phase 5 tape
under a `## bgpdd-bugfix - ` heading and could never satisfy it, leaving that
lane's tape unenforceable (audit Metric 20). It is now `bgpdd-<lane>` for any
lane name. Build is unchanged -- `bgpdd-build` is one value of `<lane>` -- and
every SHAPE requirement (3-6 bullets, a fenced block, a telemetry line, the
epic-summary exclusion, fenced headings not counting) is identical for every
lane. The regex stays byte-identical in `update_state.py`, as it was before.
