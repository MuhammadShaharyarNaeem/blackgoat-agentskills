# UI Design Patterns — Rationale

Why two of the Execution Rules in `SKILL.md` are shaped the way they are. Read on demand; the rules themselves are normative in `SKILL.md`, and nothing here adds a new rule.

## Why font substitution is decided per face, not per project

`font-display: swap` renders the fallback face until the webfont arrives. That is correct whenever substitution costs you only the *look* of the text — body copy and display headings read fine in a fallback for a few hundred milliseconds.

It is wrong whenever the glyphs are semantically load-bearing. An icon ligature font is the canonical case: the browser has no fallback glyph for the ligature, so during the swap window it paints the ligature's **source text** — `arrow_forward`, `account_circle`, `chevron_right` — into the UI, at the size and position where an icon was supposed to be. This happens on every cold load, on every page, to every first-time visitor. `block` (invisible until loaded) or `optional` (skip the webfont entirely on a slow connection) are the correct choices for those faces.

The failure mode this rule targets is not choosing `swap` — it is copying one `@font-face` declaration across every face in the project without asking what the fallback actually shows the user for each one.

## Why an override into a component library's internals is a defect signal

When a component library and a token/utility layer both style the same surface, an unowned visual property means the two layers fight at runtime and the build converges on specificity warfare — each side escalating selector weight until one wins by accident.

`!important`, a selector written against the library's internal class names, or a global element-level override each end that fight locally, and each has the same two costs: the override survives only until the library's internals change (it is pinned to a private API), and the surface it lands on is now silently detached from the design system — a later token change will not reach it, and nothing reports that.

This is why the rule is a *before-code* obligation on the committed direction (name the owning layer per property) rather than a runtime technique, and why a property the library exposes no supported theming surface for escalates as a direction decision instead of being solved locally.

## Where the design-critique failure narrative lives

The concrete failure behind *"source reading can fail a check but never pass one"* — a critique that recorded a hairline as correct from a source read while the file hardcoded the hex value, returning a clean pass over a surface that was wrong on screen — is written up at the point of use in [design-critique.md](design-critique.md) §1.3, not duplicated here.
