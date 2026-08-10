# Component Mechanics — The Craft-Floor Reference

This is the mechanical craft floor beneath visual direction: component behavior that is either correct or broken, independent of palette, type, or taste. A table that doesn't page, an autocomplete that queries on every keystroke, or a form that validates per-character on first entry is wrong regardless of how well the tokens are chosen — these checks fail even a beautifully-directed surface. Nova builds against it when implementing components/views; Quinn's [UI] test assertions cite its CM-ids; Luna's design-critique axis reports its findings per CM-id, alongside the Nielsen heuristics in [design-critique.md](design-critique.md). Every item below is checkable — by a rendered look, a computed-style read, or a driven interaction — never by reading source and inferring the runtime result.

Every `- [ ]` item carries a stable `CM-<section>.<n>` ID (e.g. `CM-1.1`, `CM-1.2`). IDs are permanent and append-only: never renumber or reuse one, even if an item above it is removed — add new items at the end of their section instead.

Run this checklist as each component or view lands, and again before marking the milestone complete (same cadence as the SKILL.md Verification Checklist).

## 1. Tables & Data Grids

- [ ] `CM-1.1` Pagination appears once row count passes a stated threshold (e.g. 25/50/100) — verify by seeding past the threshold and confirming controls render, not by reading the component's props.
- [ ] `CM-1.2` Pagination actually pages: first page, last page, and the final (possibly partial) page all render correct row counts with no off-by-one or duplicate row.
- [ ] `CM-1.3` Page size is sane for the content (dense data: 25–50; cards/rich rows: 10–20) and is visibly stated to the user, not just implied by a control.
- [ ] `CM-1.4` Sortable columns show current sort direction (icon/arrow state), not just a hover affordance — clicking again reverses it visibly.
- [ ] `CM-1.5` Loading state is a skeleton matching the eventual row/column shape, not a spinner that causes layout jump when data arrives.
- [ ] `CM-1.6` Empty state is designed (message + a next action), never a bare blank table body.
- [ ] `CM-1.7` Numeric columns use tabular (monospace-width) numerals so digits align vertically across rows.
- [ ] `CM-1.8` Row height and internal padding are consistent for every row at a given density setting — no row that's visibly taller or tighter than its neighbors.
- [ ] `CM-1.9` Long cell content truncates (ellipsis) within its column and the full value is reachable (title/tooltip, expand, or detail view) — never silently clipped with no recovery.

## 2. Text Inputs & Forms

- [ ] `CM-2.1` Every input has a persistent visible label — a placeholder that disappears on focus or input is never the only label.
- [ ] `CM-2.2` Every focusable control shows a visible focus ring (`:focus-visible`), verified by tabbing through the form, not by reading for the CSS rule.
- [ ] `CM-2.3` Validation timing: nothing validates per keystroke on a field's first pass — errors surface on blur or on submit attempt.
- [ ] `CM-2.4` Once a field has an error, live re-validation on subsequent keystrokes is allowed (clearing the error as the user fixes it), but the original error must not have fired mid-first-entry.
- [ ] `CM-2.5` Error messages sit adjacent to their field (not batched only at the top) and each names both the problem and the fix ("Must include an @" not "Invalid").
- [ ] `CM-2.6` Input width is proportional to expected content — a 5-digit zip code field is not full-width; a URL field is not 6 characters wide.
- [ ] `CM-2.7` Disabled and read-only states are visually distinct from each other and from an active editable field (verify computed opacity/background/cursor, not the attribute alone).
- [ ] `CM-2.8` Required-field marking is applied consistently across the same form (all required fields marked the same way, not a mix of asterisk/label-text/none).
- [ ] `CM-2.9` Submit is either disabled with a visible reason, or enabled and produces an error summary on invalid submission — never silently a no-op click.

## 3. Autocomplete & Comboboxes

- [ ] `CM-3.1` Remote lookups are debounced (a pause after the last keystroke before firing) — verify via network trace, not by reading for a `debounce` call.
- [ ] `CM-3.2` A minimum-character threshold before searching is stated somewhere reachable (placeholder, helper text) if one exists, so an empty query isn't silently rejected with no explanation.
- [ ] `CM-3.3` Full keyboard support: Up/Down moves the active option, Enter selects it, Escape closes the list without selecting, and Tab's behavior (commit highlighted option vs. move focus) is deliberate and consistent.
- [ ] `CM-3.4` The matched substring is highlighted within each option's label.
- [ ] `CM-3.5` A query with zero results shows a designed empty state ("No matches for \"x\"") — never a dropdown that just fails to open or shows nothing.
- [ ] `CM-3.6` A loading indicator appears inside the control (spinner in the input or list) while a remote lookup is in flight, distinct from the empty-results state.
- [ ] `CM-3.7` Selecting an option (mouse or keyboard) populates the field with the selected value and closes the list — no lingering open list after selection.
- [ ] `CM-3.8` Blur behavior is defined and never leaves a half-state: either the typed text commits to a valid selection/reverts to the last valid value, or the field visibly clears — never a raw unmatched string left sitting as if selected.

## 4. Spacing & Whitespace

- [ ] `CM-4.1` Every margin/padding/gap value traces to the token scale — no arbitrary literal (`17px`, `1.3rem`) verified by reading computed styles.
- [ ] `CM-4.2` Spacing within a logical group (label+input, icon+text) is visibly tighter than spacing between groups.
- [ ] `CM-4.3` The gap above a heading exceeds the gap below it, at every instance of that heading level.
- [ ] `CM-4.4` Page/section gutters are consistent at each breakpoint (not merely "roughly similar") — measure computed left/right padding at each stated breakpoint.
- [ ] `CM-4.5` Left edges align to a real grid: labels, fields, and their help/error text share the same left edge within a form.
- [ ] `CM-4.6` No adjacent siblings collapse into a crushed margin (e.g. two 16px margins touching and rendering as 16px instead of the intended 32px gap) — check the computed gap, not the authored value on either element.
- [ ] `CM-4.7` Every spacing claim above is verified on computed values from the rendered page, not the intention in source (matches this skill's rendered-evidence standard).

## 5. Buttons & Actions

- [ ] `CM-5.1` Each surface has exactly one visually primary action; secondary/tertiary actions are visibly subordinate (weight, color, size).
- [ ] `CM-5.2` Destructive actions require a confirmation step or offer an undo window — never a single click with no recovery path.
- [ ] `CM-5.3` Clicking an action that triggers async work immediately disables that control (or otherwise blocks a second click) and shows in-flight progress, preventing double-submit.
- [ ] `CM-5.4` Icon-only buttons carry an accessible name (visible tooltip or accessible label), verified by inspecting the rendered accessibility tree, not by reading for an `aria-label` string in source.
- [ ] `CM-5.5` Every clickable control meets a minimum hit-target size (roughly 24–44px depending on platform convention) — measure the rendered bounding box, not just the visible icon size.

## 6. Feedback & State

- [ ] `CM-6.1` Every surface backed by an async operation has a designed loading state, a designed empty state, and a designed error state — reachable and inspectable, not merely present in a states file that was never wired up.
- [ ] `CM-6.2` Error states name the specific problem and the specific recovery action, not a generic "Something went wrong."
- [ ] `CM-6.3` Outcome notifications (success/failure of an action just taken) use a toast or equivalent transient surface; problems with the user's input use inline messaging at the point of entry — the two are not interchangeable.
- [ ] `CM-6.4` Optimistic UI updates that later fail visibly reconcile (revert the change and surface the error) — never leave a stale optimistic state with no correction shown.

## How This Gates

These checks are the substance behind Quinn's [UI] mechanics assertions — each `- [ ]` above should map to a driven interaction or a computed-style read in her test suite, cited by CM-id — and they form the delegated axis inside Luna's design-critique §5 (Rendered-Property Checks) in [design-critique.md](design-critique.md), which she reports per CM-id. A critique that cannot check an item here on rendered output reports it `NOT VERIFIED — no rendered output` with its CM-id, per this skill's rendered-evidence rule, never a silent pass.
