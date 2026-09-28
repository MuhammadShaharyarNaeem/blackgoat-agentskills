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

## --classify (Unreleased)

A stale verdict says a cited file changed; it does not say whether the change could matter to the map. A refresh triggered by a trailing-space cleanup or a line-ending conversion costs a full discovery re-run for a doc whose content is still right. `--classify` labels each stamped repo's change so the person reading the worklist can tell the two apart. It adds a per-doc `change_class` map and a trailing `change class` markdown column, and only under the flag, so every existing caller's output is byte-identical.

Per stamped repo, one of three values:
- **none** — `git diff --name-status -M <sha> HEAD` is empty.
- **cosmetic** — that list is non-empty but carries no `A`, `D` or `R` entry, and `git diff --ignore-space-at-eol --ignore-cr-at-eol --ignore-blank-lines <sha> HEAD` shows no `@@` hunk line.
- **structural** — anything else. A stamp that cannot be resolved, or a stamped repo no `--repo` matched, is `null`.

**Only end-of-line whitespace, line endings and blank lines are cosmetic.** This is deliberately narrower than treating any whitespace change as cosmetic, the plain `git diff -w` rule (convention #8). `-w` also ignores indentation and whitespace inside a line, so it classes a Python dedent and a token join (`return x` → `returnx`) as cosmetic, and both change meaning. The two error directions do not cost the same. A false `structural` costs one unneeded re-discovery. A false `cosmetic` invites a refresh to skip a doc whose map is now wrong. So indentation and intra-line whitespace are structural. The limit, stated plainly: trailing whitespace can itself carry meaning (a space after a shell line-continuation backslash, a Markdown hard line break) and is still classed `cosmetic`, which is one more reason classification never waives staleness.

**The `@@`-hunk rule, not an emptiness rule.** This is also deliberately tighter than a rule that calls a change cosmetic when the whitespace-ignoring diff is empty (convention #8). What decides is the hunk line, the one thing that means a line's content changed, not whether the diff printed anything. On git 2.55 a diff whose changes are all ignored prints nothing at all, so there the two rules agree. The `@@` rule is kept because it does not depend on what a given git version prints for an ignored change.

**Two header-only changes are structural.** A binary change prints `Binary files ... differ` and a chmod prints `old mode`/`new mode`, and neither has a hunk. Whitespace cannot explain either one, so both count as structural.

**A rename is structural.** A pure rename or delete has no hunks at all, yet every path-shaped citation of the old name is now wrong. The `A`/`D`/`R` check in the name-status list catches it before the whitespace-ignoring diff is read.

**Classification informs, never waives.** `change_class` never changes a verdict, the `result` or the exit code. A stale doc whose change is only cosmetic still fails `--fail-on-stale`, exactly as it does without the flag. Waiving it would let a gate lower its own finding.

Both diffs run with `--no-color --no-ext-diff --no-textconv`, so a caller's `color.diff=always`, a `diff.external` or a repository's `diff.<driver>.textconv` cannot reshape what is parsed. They use their own subprocess call rather than the imported `git()` helper. That helper decodes output with the locale codec, which raises on diff content such as UTF-8 `Á` under cp1252. This call decodes UTF-8 with replacement, which cannot fail, and every marker it matches is ASCII. A git failure, a timeout or an unexpected OS error during classification is exit 2, never a verdict.

Self-test count: 19 → 43. The new cases cover none, cosmetic and structural, the two-repo split, rename, binary, mode-only, dedent, token join, trailing whitespace, CRLF-only and blank-line-only edits, UTF-8 content the locale codec cannot decode, hostile colour/external-diff and textconv config, the two `null` cases, the git and OS error paths, the markdown column (present under the flag even with no docs), each repo and stamp classified once per run, output unchanged without the flag, and `--fail-on-stale` never waived.
