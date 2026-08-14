# AI Tells — The Long-Tail Catalog Behind the Generic-Default Check

The SKILL.md **Category Defaults to Refuse** list holds the tells you hit on almost every surface. This file is the long tail: specific patterns that repeatedly show up in AI-generated UI and read as machine-authored to anyone who has seen a few. Load it when committing a visual direction, when building a surface with substantial static content or demo data, or when running the craft-floor checks in [design-critique.md](design-critique.md).

**Same standing as the SKILL.md list — these are defaults, not bans.** The brief's own words can earn any of them, and the rule that a pinned brief beats this contract is unchanged. Reaching for one when the axis is free means you were not deciding.

**This file carries observed forms, never new rules.** Where an item is a specific instance of a rule that already lives in SKILL.md, it cites that rule and adds only the forms — the rule keeps one home, and the catalog stays a lookup table rather than a second contract to keep in sync.

**Read each group's surface scope.** Most of these were catalogued on Persuade and Experience surfaces (landing, marketing, portfolio). Applying a landing-page tell to an Operate surface is its own error: a status dot on a server-health row, a section number in a numbered wizard, and a version string in an admin footer are all information, and information is never a tell. Group 1 and Group 5 are the ones that apply everywhere.

## 1. Fabricated content and data (every surface)

Demo data, seed fixtures, empty-state examples, and screenshot content all count. This group is the highest-yield tell because it survives every visual revision.

- **Placeholder-canon names.** "John Doe", "Jane Doe", "Sarah Chan", "Acme", "Nexus", "SmartFlow", "Cloudly". Invent names that sound like they belong to the domain and the locale the product actually serves.
- **Fake-perfect numbers.** `99.99%`, exactly `50%`, `1234567`, `$1,000`, round counts everywhere. Real data is uneven — `47.2%`, `1,284`, `$1,047.50`. Perfectly round values in a metrics view read as unimplemented.
- **Generic avatars.** The gray silhouette glyph or an icon-library user icon repeated down a list. Use real assets, deterministic generated placeholders, or initials styled from the committed tokens.
- **Filler verbs** — the recurring forms of SKILL.md's UX-copy rule (*plain verbs, no filler*): "Elevate", "Seamless", "Unleash", "Next-Gen", "Revolutionize", "Supercharge".
- **Broken or hotlinked stock images.** Point at a deterministic seeded placeholder service or a real asset, never a guessed stock URL that 404s in review.

## 2. Decorative metadata (Persuade / Experience surfaces)

SKILL.md's *structure encodes information* execution rule and its refused-default on unearned eyebrows and section numbers own this ground. These are the forms they take in practice:

- **Section-number eyebrows** — `00 / INDEX`, `001 · Capabilities`, `05 · How it works`.
- **`01 / 4`-style counters** on images or tiles the user can already count.
- **Range and locale labels as atmosphere** — "Index of Work, 2018-2026", a city/time/weather strip in the header, "Lisbon 14:23 · 18°C". A real contact address in a footer is fine; ambient locale decoration is not.
- **Scroll cues** — "Scroll", "Scroll to explore", animated wheel icons. The visitor is looking at the hero; they know.
- **Decorative status dots** before nav items, list rows, or badges. A dot conveying real semantic state (live availability, server health) is information; a dot for texture is not.
- **Version or build stamps as texture** — `v0.6`, `BETA`, `Build 0048`, `last sync 4s ago · main` on a marketing surface, or as a hero eyebrow. Keep them where the version is the point (a changelog, a devtool, an admin footer).
- **Pills and photo-credit captions overlaid on images** — `Brand · 02`, `Frame XII · 35mm`, `Plate 03 · House archive`. Either let the image stand or put a functional caption below it. Credit a real photographer for a real photo; otherwise skip.
- **Micro-meta sentences** under an eyebrow, above the headline. Eyebrow + headline + body is enough.
- **Decoration text strips** — `TYPE / FORM / MOTION`, `DESIGN · BUILD · SHIP` in small mono-caps across the hero bottom. Earned only when the strip carries real links or real status.
- **Rotated vertical text** and **hairline/crosshair grid lines drawn purely for texture**. Grid lines that organize real content are fine.
- **Corner-floating sub-text** in a section header: giant left headline with a small unaligned paragraph in the top-right. Put it under the headline or build an aligned two-column header.

## 3. Fake product previews (Persuade surfaces)

- **A product UI built from styled boxes** to simulate a screenshot — a fake task list, fake terminal, fake dashboard in the hero. This is the single most recognizable tell. Use a real screenshot, a real embedded component, or nothing.
- **Fake chrome inside that fake preview** — invented version footers, "last sync" lines, fabricated user rows.

## 4. Marketing copy (Persuade / Read surfaces)

- **Performative-craftsman labels** — "From the field", "Field notes", "On our desks", "Currently on the bench" over a quote or blog section. Use the plain functional label ("Testimonials", "Latest writing") or none.
- **Hedged social proof** — "Quietly in use at", "Quietly trusted by". Say "Trusted by" / "Used at", or let the logos speak.
- **Mock-humble industry asides** in body copy.
- **Live-scarcity counters as decoration** — "Reservation 412 of 800", "One Q4 slot open" without real backing data.

## 5. Separator and dash texture (every surface)

- **The middle dot (`·`) is rationed** — at most one per metadata line. When you need a separator family, reach for line breaks, hairlines, or columns instead of `foo · bar · baz · qux`.
- **Em and en dashes are rationed in rendered UI copy, and refused in short strings** — headlines, eyebrows, pills, button labels, nav items, captions, and alt text. A short label with an em dash inside it is a texture tell; restructure to a period, a comma, a colon, or two elements. In body prose the em dash is legitimate punctuation, used at natural frequency and not as a rhythm crutch. Ranges (`2018-2026`, `40-80k`) take a hyphen. *This is deliberately looser than the upstream source's absolute zero-em-dash ban, which is a stylistic position rather than a craft floor; the rationing rule is what this contract enforces.*
- **Headline splits with a forced line break plus italics** as a default "design move". Let the headline read naturally.

## 6. List and table decoration (every surface)

- **A top border AND a bottom border on every row** of a long list or spec table. Pick one and use it sparsely; hairlines under all ten rows is the laziest available layout.
- **Progress-bar comparison visuals with filled background tracks** used decoratively on a non-dashboard surface. A number plus a small mark, or a bar without a track, carries the same comparison with less noise.

## Attribution

Groups 1–4 and 6 are adapted from the "AI Tells" section of [leonxlnx/taste-skill](https://github.com/leonxlnx/taste-skill) (MIT), whose catalog was derived from production tests of LLM-generated pages. Adapted here for framework neutrality (the source mandates a React/Next/Tailwind stack) and re-scoped by surface mode, since the source explicitly excludes the dashboard and multi-step product UI this squad builds. Group 5 relaxes that source's absolute em-dash ban into a rationing rule, as noted inline.
