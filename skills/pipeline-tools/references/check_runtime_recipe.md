# check_runtime_recipe.py — reference

Depth for the `check_runtime_recipe.py` section of `../SKILL.md`.

## The one artifact a later pipeline cannot start without

`bgpdd-discovery/SKILL.md` § 1 singles `runtime-environment.md` out from every other Tier-1 file: *"the one artifact here a later pipeline depends on to start anything, so existence alone is not enough: the file must also name at least one service start command and at least one readiness check. A recipe with neither is a heading, and `/bgpdd-build` Phase 0 discovers that months later with no one left to ask."*

Existence was already checkable by eye; "is it actually fillable" was not, and the reader asked to judge it is the Orchestrator closing Phase 4b with the user's confirmation already in hand. Convention #9: make it a command.

## Format authority stays elsewhere

The Environment Manifest's blocks are defined by `skills/runtime-evidence/SKILL.md` § The Environment Manifest. This gate restates none of them — it asserts the six are present and that two of them are *filled*:

| Block | Recognized by |
|---|---|
| Bring-up sequence | heading or `Label:` matching `bring-up sequence` |
| Services | `services` |
| Repointing map | `repointing map` |
| Forbidden hosts | `forbidden hosts` |
| Test identities & fixtures | `test identities & fixtures` (or `and`) |
| Capabilities | `capabilities` |

If that list changes in `runtime-evidence/SKILL.md`, `MANIFEST_BLOCKS` in this script changes in the same commit. Deriving it by parsing that SKILL at runtime was rejected for the same reason `check_handoff.py` keeps its persona table inline: a gate whose bar moves when prose is reworded is not a gate.

## How a start command and a readiness check are recognized

Two shapes, because the manifest is written both ways in practice:

- **A Services-shaped table.** Any markdown table whose header has a column matching `start command` or `readiness check`; every body row's cell in those columns counts, unless it is a placeholder.
- **Labeled lines.** `Start command: <value>` / `Readiness check: <value>` (also `Ready check`, `Health check`), for a single-service recipe written as a list.

At least one non-placeholder value must be found for each. A **placeholder** is a cell that carries no fact: empty, `-`, `—`, `n/a`, `none`, `TBD`, `TODO`, `?`, `pending`, `unknown`, `...`, or base-persona's own skeleton marker `_TODO: pending_`. Treating `TBD` as a filled cell would let the exact artifact this gate exists to catch — a heading with a shape — pass, so `test_headings_only_recipe_fails_both` pins it: all six blocks present, both content checks failing.

## The sanctioned skip

§ 1: *"If the user deliberately declined to produce it (Phase 4b step 5), record that skip explicitly in your closing handoff, as user-approved — an unrecorded skip is indistinguishable from an omission."* So a line reading

```
Skipped — user-approved: <reason>
```

exits 0 immediately, before any block or content check. Em dash, en dash and a plain hyphen all parse; leading `>` and bold markers are tolerated.

**The reason is required** — an empty one is `skip_unreasoned` and fails. That is deliberately a hair stricter than the words "a `Skipped — user-approved:` line exits 0", and it is the same rule the SKILL states: without a reason, the skip carries exactly as much information as the omission it is meant to be distinguishable from. Equally, a bare `Skipped.` buys nothing (`test_the_word_skipped_alone_is_not_a_sanctioned_skip`) — the escape hatch is the *user-approved* half, not the word.

## Exit codes and codes

**0** the manifest is complete and filled, or a reasoned user-approved skip is recorded; **1** any finding, including the recipe not existing; **2** `--recipe` omitted, or the path exists but is not a readable file.

A missing recipe is a **finding** (exit 1), not a usage error: at the step that invokes this gate the file was supposed to have just been written, so its absence is the result, not a caller mistake.

Codes: `recipe_missing`, `block_missing`, `start_command_missing`, `readiness_check_missing`, `skip_unreasoned`.

## Self-test

`python scripts/check_runtime_recipe.py --self-test` runs 16 in-process cases: a full table-shaped manifest passing, a label-shaped one passing, the `and` spelling of the identities block accepted, no start command, no readiness check, a headings-only recipe failing both content checks while reporting no missing blocks, placeholder cells not counting while a real sibling row still does, one block renamed away, every block missing, a reasoned skip exiting 0, an unreasoned skip failing, the plain-hyphen spelling accepted, a bare `Skipped.` buying nothing, a missing recipe reporting `recipe_missing`, a directory as `--recipe` erroring, and the ledger recording all three exit paths.
