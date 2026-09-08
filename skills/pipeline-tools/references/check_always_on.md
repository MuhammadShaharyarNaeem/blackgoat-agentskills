# check_always_on.py — reference

Depth for the `check_always_on.py` section of `../SKILL.md`.

## What the index promises, and what breaks it

`skills/agent-squad/always-on.md` is injected at session start, so it is the plugin's first and often only self-description in an ordinary chat that never types a lane command. Its own preamble makes two promises: it is "an index, not a contract" — every entry names the file that owns the rule — and it lists **the** lanes.

Two drifts falsify both, and neither announces itself:

- **A lane exists on disk with no row.** The lane is invisible to every session that reads only the index. Nothing about the plugin looks broken; the capability simply never gets picked.
- **A row or an owner pointer names a file that was renamed.** A pointer to nothing reads exactly like a pointer to something, and "read that file before acting on it" becomes advice nobody can follow.

The index is also the artifact least likely to be re-read: it is injected, not opened. Convention #9 — a rule whose compliance depends on someone choosing to look becomes a command in CI.

## What it checks

| Check | Code |
|---|---|
| Every `/bg*` lane folder with a `SKILL.md` has a table row | `lane_missing_row` |
| Every table row names a lane that exists (and only once) | `lane_row_orphan` |
| Every table cell is at most `--max-words` words (default 20) | `cell_too_long` |
| Every cited path resolves under the plugin root | `path_missing` |
| The `## Outside any lane` section has four numbered rules | `rule_count` |
| Each of those rules names an `Owner:` file that exists | `rule_owner_missing` |
| Both sections are present and the lane table has body rows | `section_missing` |

A lane is a directory under `skills/` named `bg` or `bgpdd-*` **that contains a `SKILL.md`**. The SKILL.md condition matters: a half-built lane folder is not yet a lane, and failing the index for it would make the gate fire during exactly the work that will fix it.

## What counts as a "cited path"

Only two token shapes are read as claims about the tree, and both are checked in every backticked span in the file, not just the table:

- a token containing `/` — resolved relative to the plugin root;
- a bare `*.py` name — resolved under `skills/pipeline-tools/scripts/`, because the index cites `check_commit_gate.py` and `check_quick_close.py` that way.

Everything else is left alone by design. A lane command (`/bgpdd-quick`) starts with `/` and names no file. A template path (`.docs/{project-name}/`) names no one file on disk — any token carrying a space, `<`, `>`, `{` or `}` is skipped for the same reason. Widening this would turn every backticked word in the index into a potential false failure, which is the fastest way to get a lint deleted.

## The 20-word cell budget

The index earns its always-on injection by being small. Twenty words is the bound the shipped table already respects (its longest cell is 19), so the gate holds the line rather than inventing one: the next lane added cannot quietly turn a one-line row into a paragraph. `--max-words` exists so the bound is arguable in one place instead of relitigated per row.

## Exit codes

**0** every check passes; **1** at least one finding; **2** the index file or `--plugin-root` cannot be read, or the root has no `skills/`. Defaults resolve from the script's own location, so bare `python check_always_on.py` is the CI invocation.

## Self-test

`python scripts/check_always_on.py --self-test` runs 18 in-process cases against a synthetic plugin tree: a complete index passing, a lane with no row, a row with no lane, a lane folder without `SKILL.md` correctly ignored, a duplicated row, a 21-word cell failing and a 20-word cell passing, `--max-words` honored, an unresolvable path, a bare script name resolved both ways, lane commands and `{placeholder}` paths not treated as path claims, a rule with no owner, a rule whose owner does not exist, the wrong rule count, both sections missing, unreadable index and root erroring, the ledger recording all three exit paths — and finally `test_the_shipped_index_passes`, which runs the gate against the real `always-on.md` so the file the gate was written for is proven, not assumed.
