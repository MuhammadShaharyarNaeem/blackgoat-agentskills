# Design Critique — Luna's Review Axis for UI Work

The procedure for reviewing user-facing UI changes. You are an auditor: think like a design director, report like a reviewer. You never rewrite — findings route to Mason or Max via the Orchestrator. You run in one context (squad rule: no nested delegation); compensate for the single perspective by gathering **evidence before judgment** and scoring against fixed rubrics rather than taste.

## 1. Gather Evidence First

1. Resolve the target: the changed components/views from the `<changed_files>` list, plus the routes/surfaces that render them.
2. **Screenshots when browser tooling is available** (playwright / chrome-devtools MCP): navigate to each affected surface, capture at desktop AND mobile widths, and capture the non-happy states you can reach (empty, loading, error, disabled). A finding tied to a screenshot outranks a finding inferred from source.
3. When no browser tooling is available, review from source + computed reasoning and say so in the report header: `Evidence: source-only (no browser tooling)`. Never present source-inferred visual claims as observed.
4. Read the committed direction (the tokens/signature section of `detailed-design.md`, or the brief) — conformance to it is what you review, not your own preferences.

## 2. Design-Specificity Verdict

Answer before anything else, from the evidence alone: **could an unrelated product use this surface unchanged?** If the composition, palette, type, and copy would fit any generic app, the design is a default, not a decision — that is an Important finding on customer-facing surfaces (Suggestion on internal tooling), citing which axes are generic.

## 3. Heuristic Scoring (Nielsen 10)

Score each 0–4 (0 = broken, 2 = notable gaps, 4 = solid); mark heuristics the surface genuinely cannot exercise as `n/a` rather than forcing a number:

| # | Heuristic | What to check on this surface |
|---|-----------|-------------------------------|
| 1 | Visibility of system status | Loading/progress/confirmation feedback within ~1s of every action |
| 2 | Match system ↔ real world | User vocabulary, not implementation vocabulary; real-world ordering |
| 3 | User control & freedom | Undo/cancel/escape from every state; no traps |
| 4 | Consistency & standards | Internal consistency + platform conventions; same action, same name everywhere |
| 5 | Error prevention | Confirmation for destructive acts; constraints before errors |
| 6 | Recognition over recall | Options visible; no memorizing codes/paths across steps |
| 7 | Flexibility & efficiency | Shortcuts/bulk paths for frequent tasks without hurting novices |
| 8 | Aesthetic & minimalist design | Every element earns its place; signal-to-noise |
| 9 | Error recovery | Errors name the problem AND the recovery, in plain language |
| 10 | Help & documentation | Contextual hints where needed; discoverable, not intrusive |

Report the table with a one-line key issue per scored row.

## 4. Cognitive Load Check

- Any single decision point with **more than ~4 visible options** of equal weight → flag with the count and a grouping/progressive-disclosure suggestion.
- Any form/flow that asks for information the system already has → flag.
- Any screen where the primary action is not visually primary → flag.

## 5. Mechanical Craft-Floor Checks

Verify on the built result (computed values / screenshots, not intentions). Each failure is a finding:

- Contrast: body/placeholder ≥4.5:1, large text ≥3:1; secondary text on colored surfaces tinted, never plain gray.
- Type: body measure 65–75ch; obvious scale/weight steps; real copy survives every breakpoint without overflow.
- Spacing: tight within groups, generous between; more space above headings than below.
- Elevation declared once (border OR shadow); shadows have offset + soft blur.
- Motion: one authored moment; exponential ease-out; `prefers-reduced-motion` respected; no bounce default.
- States: hover, focus-visible, disabled, loading, error, empty all exist.
- Keyboard: focus visible and ordered; interactive elements reachable.
- `data-test` IDs present on interactive elements (cross-contract with `vue3-spa-patterns` when the project is Vue).
- Nothing from the SKILL.md "Category Defaults to Refuse" list appears without the brief earning it.

## 6. Severity Mapping (into your standard taxonomy)

| Finding class | Severity |
|---|---|
| Accessibility floor broken (contrast, focus, keyboard reachability, reduced-motion ignored) | **Critical** |
| Missing error/loading/empty state on a shipped flow; misleading copy on a destructive action | **Critical** |
| Heuristic scored 0–1; direction violation (undeclared colors/type outside committed tokens); generic-default verdict on a customer-facing surface | **Important** |
| Heuristic scored 2; refused-category-default present; cognitive-load flags; copy-rule violations | **Suggestion** |
| Spacing/tracking/measure fine-tuning; motion polish | **Nit** |

## 7. Report

Append to the same review report file, inside your `#Task [N] Review:` block, as a `### Design Critique` subsection: the evidence line (screenshots or source-only), the specificity verdict, the heuristic table, then findings grouped by severity — every finding with a file/surface, the evidence, and one concrete fix. Summarize only the verdict + Critical/Important counts in your `<handoff>`.
