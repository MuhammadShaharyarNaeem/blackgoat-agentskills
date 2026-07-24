---
name: ui-design-patterns
description: "Provides the UI design execution contract: a committed visual direction (design tokens + signature element) before code, typography/spacing/color/motion discipline, surface modes, anti-generic-AI-aesthetic rules, full state coverage, UX copy rules, and the design-critique review axis. Use when the task involves building or changing user-facing UI. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Adapted from Anthropic's frontend-design skill and pbakaus/impeccable (Apache-2.0)."
---

# UI Design Patterns

Visual craft with the same rigor as engineering correctness. Direction is committed before code; every rule below is checked on the built result, not the intention. **The brief wins**: a pinned aesthetic, palette, font, or era in the requirements or brand guidelines overrides anything here — redirecting a clear brief toward your own taste is failure.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### Design Direction First (plan-time — Aria, or the brief)

Before any UI code exists, a compact direction must be committed — in `detailed-design.md` for pipeline work, or stated in the brief for ad-hoc work:

- **Tokens**: 4–6 named palette values; 2–3 type roles (a characterful display face used with restraint, a complementary body face, a utility face for data/captions if needed); a spacing scale.
- **Layout concept**: one-sentence prose description of the composition.
- **Signature**: the single element this surface will be remembered by. Spend boldness there; keep everything around it quiet.
- **Generic-default check**: AI-generated design clusters around known looks (cream background + high-contrast serif + terracotta accent; near-black + one acid accent; broadsheet hairlines + zero radius). If any committed choice is one you would produce for *any* similar brief, it is a default, not a decision — revise it and say why. A brief that explicitly asks for one of these looks wins, as always.

### Surface Modes

Pick the mode per surface (not per product) and design for what the visitor's success looks like there:

- **Persuade** — the visitor decides and acts (landing, marketing, pricing): design earns attention and action.
- **Operate** — the visitor completes a task (app UI, dashboards, admin, settings): scanability, consistency, and platform expectations outrank expression; brand lives in precise details.
- **Read** — the visitor understands something (docs, guides, changelogs): structure for comprehension first.
- **Experience** — the visitor is inside the work (portfolios, galleries): the artifact leads; the interface recedes.

### Execution Rules (authoring — Mason)

- **Typography carries the personality**: deliberate pairing, a clear scale with obvious size/weight steps, body measure 65–75ch, display ≤6rem, tracking no tighter than −0.04em (−0.02 to −0.03em usually reads better). Run the real copy at every breakpoint; fix what overflows.
- **Spacing is rhythm**: tight within groups, generous between them; more space above a heading than below it. Verify computed values, not intentions.
- **Color**: contrast ≥4.5:1 for body/placeholder text, ≥3:1 for large text. On colored surfaces, tint secondary text from that hue or the foreground — never plain gray. The accent is spent deliberately, not sprayed.
- **Structure encodes information**: numbering, eyebrows, dividers, and labels must state something true about the content (a real sequence, a real category) — never decoration.
- **Depth & elevation**: declare elevation once — border OR shadow, not both (a 1px border under a wide soft shadow is the ghost card). Shadows carry an offset and soft blur; a zero-offset colored halo is decoration.
- **Motion**: one authored moment, not scattered effects and not the same entrance on every section. Exponential ease-out from an already-visible default; respect `prefers-reduced-motion`. No bounce easing by default.
- **States are the design**: hover, focus-visible, disabled, loading, error, and empty states are designed, not defaulted. An empty screen is an invitation to act; an error names the problem and the recovery.
- **Quality floor**: responsive down to mobile, keyboard focus visible, real content and working controls — built without announcing the checklist.

### Category Defaults to Refuse

These are defaults, not bans — the brief's own words can earn any of them. Reaching for one when the axis is free means you were not deciding; rewrite the element rather than softening it:

- Same-size icon+heading+text card grids as page structure; nested cards (always wrong); the hero-metric template (big number, small label, stats, accent).
- A tracked uppercase eyebrow over every section; section numbers (01/02/03) when order carries no information; a modal for a task needing neither interruption nor protected focus.
- Gradient text (emphasis comes from weight or size); glass/blur as decoration; colored side-borders >1px on cards and alerts; monospace as a "technical" costume rather than for code/data.
- Light-or-dark picked by category habit — pick it from the real usage scene (who, where, what ambient light).

### UX Copy

Words are design material. Write from the user's side of the screen: name things by what people control ("notifications", not "webhook config"). Active voice; a control says exactly what happens ("Save changes", not "Submit") and keeps its name through the whole flow (a "Publish" button produces a "Published" toast). Sentence case, plain verbs, no filler; each element does exactly one job.

### Verification Checklist

Before marking UI work complete:

- [ ] A committed direction exists (tokens + signature) and every color/type decision derives from it — no undeclared values
- [ ] The generic-default check ran: no committed choice is a category default on a free axis
- [ ] Contrast, spacing rhythm, and type scale verified on the built result (computed values, real copy, every breakpoint)
- [ ] All interaction states exist: hover, focus-visible, disabled, loading, error, empty
- [ ] Responsive to mobile; keyboard focus visible; `prefers-reduced-motion` respected
- [ ] Copy follows the UX-copy rules (action-named controls, recovery-naming errors)
- [ ] Nothing from "Category Defaults to Refuse" appears without the brief earning it

### Review Mode (Luna — design critique)

When a review delegation covers UI work, run the design-critique axis in [references/design-critique.md](references/design-critique.md): screenshot-driven when browser tooling is available, Nielsen-heuristic scoring, a design-specificity verdict, and the mechanical craft-floor checks — findings labeled with the standard Critical/Important/Suggestion/Nit taxonomy. Audit only; rewrites route to Mason or Max via the Orchestrator.

### Escalate When

- The brief pins no visual direction and the surface is customer-facing → report to the Orchestrator with 2–3 proposed directions; do not silently invent brand identity.
- Brand assets/guidelines are referenced but missing → report; do not substitute lookalikes.
- The committed direction conflicts with an accessibility floor (contrast, focus, reduced motion) → the floor wins; report the conflict rather than shipping either violation.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Design critique](references/design-critique.md) — Luna's review procedure: evidence gathering (screenshots via browser tools), Nielsen 10-heuristic scoring, design-specificity verdict, cognitive-load checks, the mechanical craft-floor checklist, and the severity mapping into her review-report format.

## Attribution

Adapted for this squad from [Anthropic's frontend-design skill](https://github.com/anthropics/skills) and [pbakaus/impeccable](https://github.com/pbakaus/impeccable) (Apache-2.0). Impeccable's command/detector orchestration is intentionally not carried over — orchestration belongs to the squad's Orchestrator, not to a methodology.
