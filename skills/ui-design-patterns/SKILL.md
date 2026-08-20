---
name: ui-design-patterns
description: "Provides the UI design execution contract: a committed visual direction (design tokens + signature element) before code, typography/spacing/color/motion discipline, surface modes, anti-generic-AI-aesthetic rules, full state coverage, a component-mechanics craft floor, UX copy rules, and the design-critique review axis. Use when the task involves building or changing user-facing UI. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Adapted from Anthropic's frontend-design skill and pbakaus/impeccable (Apache-2.0)."
---

# UI Design Patterns

Visual craft held to engineering rigor. Direction is committed before code; every rule below is checked on the built result, not the intention. **The brief wins**: a pinned aesthetic, palette, font, or era in the requirements or brand guidelines overrides anything here — redirecting a clear brief toward your own taste is failure.

## Worker Execution Contract

### Design Direction First (plan-time — Aria, or the brief)

Commit a compact direction before any UI code — in `detailed-design.md` for pipeline work, in the brief for ad-hoc work:

- **Candidate sourcing (design DB tool)** — brief pins no direction:
  - SHOULD query first, for 2–3 candidate styles, palettes, and font pairings: `python <this skill's resolved path>/tools/design-db/scripts/search.py "<product/surface description>" --domain style` (also `--domain color|typography|ux`; stdlib-only Python 3).
  - Results are candidate input, never authority: every pick still passes the generic-default check, and **this contract wins over any database recommendation** — the DB freely suggests looks this skill refuses by default.
  - No Python 3 runtime → skip the query; commit from the brief and these rules alone.
  - NEVER run `search.py`'s `--design-system`/`--persist` mode — it writes `design-system/<slug>/MASTER.md` outside the `.docs/` boundary (makes the Attribution section's "not adopted" claim enforceable).
- **Tokens**: 4–6 named palette values; 2–3 type roles (a characterful display face used with restraint, a complementary body face, a utility face for data/captions if needed); a spacing scale.
- **Layout concept**: one-sentence prose description of the composition.
- **Signature**: the single element this surface will be remembered by. Spend boldness there; keep everything around it quiet.
- **Generic-default check**: known AI clusters — cream background + high-contrast serif + terracotta accent; near-black + one acid accent; broadsheet hairlines + zero radius. A committed choice you would produce for *any* similar brief is a default, not a decision — revise it and say why (a brief that explicitly asks for one of these looks still wins). Long-tail catalog: [references/ai-tells.md](references/ai-tells.md) — read it when the surface carries substantial static content or demo data.

### Surface Modes

Pick the mode per surface (not per product); design for the visitor's success there:

- **Persuade** — visitor decides and acts (landing, marketing, pricing): design earns attention and action.
- **Operate** — visitor completes a task (app UI, dashboards, admin, settings): scanability, consistency, and platform expectations outrank expression; brand lives in precise details.
- **Read** — visitor understands something (docs, guides, changelogs): structure for comprehension first.
- **Experience** — visitor is inside the work (portfolios, galleries): the artifact leads; the interface recedes.

### Execution Rules (authoring — the UI Builder, Nova)

- **No placeholder/empty wrappers**: NEVER scaffold an empty HTML wrapper (e.g. `<div class="Wrapper"></div>`) — implement the specified logic and markup fully, so QA runs against the true implementation.
- **Typography carries the personality**: deliberate pairing; a clear scale with obvious size/weight steps; body measure 65–75ch; display ≤6rem; tracking no tighter than −0.04em (−0.02 to −0.03em usually reads better). Run the real copy at every breakpoint; fix what overflows.
- **Spacing is rhythm**: tight within groups, generous between them; more space above a heading than below it. Verify computed values, not intentions.
- **Color**: contrast ≥4.5:1 body/placeholder text, ≥3:1 large text. On colored surfaces tint secondary text from that hue or the foreground — never plain gray. Spend the accent deliberately; never spray it.
- **Structure encodes information**: numbering, eyebrows, dividers, and labels must state something true about the content (a real sequence, a real category) — never decoration.
- **Depth & elevation**: declare elevation once — border OR shadow, never both (a 1px border under a wide soft shadow is the ghost card). Shadows carry an offset and soft blur; a zero-offset colored halo is decoration.
- **Motion**: one authored moment — never scattered effects, never the same entrance on every section. Exponential ease-out from an already-visible default; respect `prefers-reduced-motion`. No bounce easing by default.
- **States are the design**: hover, focus-visible, disabled, loading, error, and empty states are designed, not defaulted. An empty screen is an invitation to act; an error names the problem and the recovery.
- **NEVER `font-display: swap` on a face whose glyphs are semantically load-bearing** — icon ligature fonts above all: the swap window paints the ligature's source text (`arrow_forward`, `account_circle`) to the user. Use `block` or `optional` there; keep `swap` for body and display text. Decide per face, never by copying one `@font-face` rule across all of them. (Mechanism: `references/ui-design-rationale.md`.)
- **Component library + token/utility layer coexisting**: the committed direction names which layer owns each visual property — surface color, radius, border, elevation, typography, density — *before* code. `!important`, a selector into the library's internal class names, or a global element-level override to land a design decision is a **defect signal, not a technique** — that surface is now silently detached from the design system. Extend the token/theme layer through the library's own supported theming surface; where it exposes none for that property, escalate as a direction decision rather than overriding locally. (Why: `references/ui-design-rationale.md`.)
- **Quality floor**: responsive down to mobile, keyboard focus visible, real content and working controls.

### Category Defaults to Refuse

Defaults, not bans — the brief's own words can earn any. Reaching for one on a free axis means you were not deciding; rewrite the element rather than soften it.

- Same-size icon+heading+text card grids as page structure; nested cards (always wrong); the hero-metric template (big number, small label, stats, accent).
- A tracked uppercase eyebrow over every section; section numbers (01/02/03) when order carries no information; a modal for a task needing neither interruption nor protected focus.
- Gradient text (emphasis comes from weight or size); glass/blur as decoration; colored side-borders >1px on cards and alerts; monospace as a "technical" costume rather than for code/data.
- Light-or-dark picked by category habit — pick it from the real usage scene (who, where, what ambient light).

### UX Copy

Write from the user's side of the screen:

- Name things by what people control ("notifications", not "webhook config").
- Active voice; a control says exactly what happens ("Save changes", not "Submit").
- A control keeps its name through the whole flow (a "Publish" button produces a "Published" toast).
- Sentence case, plain verbs, no filler; each element does exactly one job.

### Verification Checklist

Run this as each component or view lands, and again before marking the milestone complete:

- [ ] A committed direction exists (tokens + signature) and every color/type decision derives from it — no undeclared values
- [ ] The generic-default check ran: no committed choice is a category default on a free axis
- [ ] Contrast, spacing rhythm, and type scale verified on the built result (computed values, real copy, every breakpoint)
- [ ] All interaction states exist: hover, focus-visible, disabled, loading, error, empty
- [ ] Responsive to mobile; keyboard focus visible; `prefers-reduced-motion` respected
- [ ] Copy follows the UX-copy rules (action-named controls, recovery-naming errors)
- [ ] Nothing from "Category Defaults to Refuse" appears without the brief earning it
- [ ] Demo/seed/empty-state content passes the fabricated-content group in [references/ai-tells.md](references/ai-tells.md) — no placeholder-canon names, fake-perfect numbers, or generic avatars

### Review Mode (Luna — design critique)

A review delegation covering UI work runs the design-critique axis — procedure in [references/design-critique.md](references/design-critique.md). Audit only; rewrites route to the milestone's builder (Nova for [UI] work) via the Orchestrator.

**A design critique without rendered output does not pass rendered properties.** The axis is defined on the built result, so its evidence is a screenshot or a computed-style read from a real browser. No browser tooling, app unbuilt, or it will not boot → every check on a computed or rendered property is reported `NOT VERIFIED — no rendered output` and raised as a blocker on the review. NEVER quietly marked satisfied. Which properties, and the failure narrative behind this rule: `references/design-critique.md` §1.3 and §5.

Source reading is a strictly one-directional instrument here: it can **fail** a check but never **pass** one. Report every source-visible defect — a hardcoded literal where the design system mandates a token, a missing `:focus-visible` rule, an absent empty state. NEVER pass a rendered property from a source read: a correct token reference still renders wrong if the token is undefined, overridden, or the stylesheet never loads.

### Escalate When

- No visual direction pinned and the surface is customer-facing → report to the Orchestrator with 2–3 proposed directions; NEVER silently invent brand identity.
- Brand assets/guidelines referenced but missing → report; NEVER substitute lookalikes.
- Committed direction conflicts with an accessibility floor (contrast, focus, reduced motion) → the floor wins; report the conflict rather than shipping either violation.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [AI tells](references/ai-tells.md) — the long-tail catalog behind the generic-default check; each group scoped to the surface modes it applies to.
- [Design critique](references/design-critique.md) — Luna's full review procedure (loaded via Review Mode above).
- [Component mechanics](references/component-mechanics.md) — mechanical craft floor for tables, forms, autocompletes, spacing, and feedback states: pass/fail on rendered output. Listed here but NOT read-on-demand — Nova (building components/views), Quinn (`[UI]` assertions), and Luna (`[UI]` reviews) load it per their own dependency tables; deliberately refines the read-on-demand default (convention #8).
- [Rationale](references/ui-design-rationale.md) — why the font-substitution and library-ownership rules are shaped as they are.

## Attribution

Adapted for this squad from [Anthropic's frontend-design skill](https://github.com/anthropics/skills) and [pbakaus/impeccable](https://github.com/pbakaus/impeccable) (Apache-2.0). Impeccable's command/detector orchestration is intentionally not carried over — orchestration belongs to the squad's Orchestrator, not to a methodology.

The AI-tells catalog in `references/ai-tells.md` is adapted from the "AI Tells" section of [leonxlnx/taste-skill](https://github.com/leonxlnx/taste-skill) (MIT). Only that section is carried over, made framework-neutral and re-scoped by surface mode (grounds: that file's own Attribution). Its stack conventions, dial system, and brief-inference stage are intentionally not adopted — stack rules belong to the framework playbooks (`vue3-spa-patterns`, `dotnet-backend-patterns`), brief inference to the pipeline's requirements and design-direction phases.

The `tools/design-db/` search tool (BM25 CSV database of UI styles, palettes, font pairings, and UX guidelines) is vendored from [nextlevelbuilder/ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) (MIT — see `tools/design-db/LICENSE`). Only its data and search scripts are carried over: its self-activating skill surface, doctrine, and design-system generator are intentionally not adopted — this contract remains the sole authority on what ships, and the DB is consulted only as candidate input during Design Direction.
