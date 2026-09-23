# tier1_staleness.py — reference

Depth for `tier1_staleness.py`. The contract of record is the script's own `--help` (`python scripts/tool_registry.py show tier1_staleness`); this page holds only the reasoning behind it.

## The question `check_tier1_provenance.py` cannot answer

The provenance gate answers *whether* a stamped repo has moved past the sha a Tier-1 map was derived from. That is the right question for the gate and the wrong one for a refresh: "the repo moved" is true almost always, and acting on it means re-running discovery over every doc under the feature. Most of those docs cite code that did not change.

This tool answers the narrower question — **which** docs are affected — by diffing each stamped repo from its stamped sha to HEAD and matching the changed files against what each doc actually cites. A refresh then re-runs only the stale ones.

It reads the same stamp by importing the provenance gate's own header and stamp readers rather than re-deriving the grammar. Two parsers for one stamp is two grammars that drift, and the drift would show up as docs silently reported unstamped.

## Inherited stamps

The discovery contract stamps only the cumulative context file and each feature's overview. Every per-API and QA doc beneath a feature is unstamped **by design**, and treating each of those as having no provenance would report the whole feature as unknowable.

So a doc under a feature with no stamp of its own inherits the feature overview's stamp and computes its verdict normally from it; the report names which stamp each verdict came from. The cumulative context file never inherits — it is nobody's child. When the overview itself carries no stamp there is nothing to inherit, every stampless sibling is unstamped too, and the cause is named once in the warnings rather than once per doc.

## Why citations are matched in two classes

Tier-1 docs cite source in two shapes, and only one of them is unambiguous.

**Path-shaped citations** carry enough directory to identify a file. They are matched by trailing path segments in either direction, because a citation is routinely *shorter* than the diff path (it omits a repo prefix the diff has) or *longer* (it carries a repo-folder prefix the diff output lacks). Matching one direction only would miss half the real citations.

**Bare filenames** are the shape most discovery overviews actually use. A bare name has no directory, so it cannot disambiguate a move, and it is deliberately matched only against added and modified files — never renames or deletes. It is matched across every repo the doc's stamp scopes, and the rule is that **exactly one** match counts. Two or more is an unresolvable collision: the tool reports the collision with its count and does not let it contribute to staleness, because picking one would be a guess, and a guess that marks a doc stale costs a re-run while a guess that marks it fresh costs a wrong map nobody re-derives. A bare name already covered by a path-shaped citation in the same doc is skipped — the specific citation wins.

## Why it is advisory by default

The discovery contract's stance is that drift is a warning, and this tool keeps it. Without the opt-in failure flag the report always exits 0: it is a worklist for a human deciding what to refresh, not a gate. The flag exists so a pipeline step that *has* decided staleness should block can say so explicitly.

The exception is the set of conditions where the check could not be performed at all — a summary root or feature directory that is not there, a repo path that is not a git repository, git unusable. Each of those is a usage error rather than an exit-0 report, because an unperformable check that exits 0 reads as "everything is fresh" to a caller that only looks at the exit code.

A `--repo` the stamps never mention is **not** one of those: the path is still validated, but a valid repo nobody's stamp happens to reference is harmless extra scope, not a mistake.

## It never writes

No doc is edited and no stamp is re-written. The stamp rule belongs to the discovery agent, applied at write time; a tool that re-stamped what it found stale would be closing its own finding.
