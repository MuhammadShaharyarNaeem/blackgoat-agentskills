# check_section_anchors.py — reference

Depth for `check_section_anchors.py`. The contract of record is the script's own `--help` (`python scripts/tool_registry.py show check_section_anchors`); this page holds only the reasoning behind it.

## Why a citation needs a lint

This plugin is a layered ruleset that works by citation: a pipeline step names the gate section that owns a grammar, a persona names the methodology that owns a rule, a skill defers to another skill's section rather than restating it. That discipline is what keeps one contract in one place (CLAUDE.md convention #1) — and it fails silently. A section renamed or removed leaves every citation of it reading exactly like a live one, and the reader who follows it finds a file with no such heading and improvises.

So the § citation becomes a checkable claim: it resolves, or it is a Blocker in the `agent-audit` preflight.

## The two citation forms, and why the first accepts two targets

**Form A** is a citation to a pipeline-tools script by name. It resolves against either a matching level-2 heading in `pipeline-tools/SKILL.md` **or** the post-split `pipeline-tools/references/<name>.md` file.

Accepting either is the point, and it is what made retiring the spine's per-script sections possible without rewriting every citation in the tree at the same time (CLAUDE.md convention #8 — a deliberate widening of "a citation resolves to a heading"). The spine's per-script headings are gone; the reference docs stand in their place, and the existing citations resolve unchanged. A citation whose script has *neither* is dangling, which is why every retired section had to leave a reference doc behind.

**Form B** is a citation to a heading inside a named file, resolved against this tree's actual conventions — the plugin root, the skills directory, the citing file's own directory and then its parent, which is what a `references/<x>.md` page citing a sibling needs.

## Why "unresolved" is not a failure

A citation whose target file cannot be determined from the text — a runtime path under a dot-directory, a placeholder, a heading named in prose with no file beside it — is counted as unresolved and reported, never failed. The count is informational: it says how much of the tree's cross-referencing this lint can actually see. Failing on it would push authors toward citations that are easy to parse rather than citations that are useful to follow.

Fixture directories are excluded by default, since their content is self-contained example text whose citations are deliberately not live.
