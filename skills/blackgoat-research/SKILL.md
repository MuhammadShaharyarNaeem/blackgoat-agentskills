---
name: blackgoat-research
description: Guides Aria's codebase/technology research and the authoring of the detailed design document during bgpdd-plan Phase 2. Squad-internal execution contract loaded by Aria via her Methodology Dependencies table — user-facing triggers belong to the /bgpdd-plan pipeline.
---

# Blackgoat Research

## Overview

This skill enables collaborative technical research, technology analysis, and system architecture design. It guides the creation of research notes and detailed design documents before writing implementation code.

## Modes

Your Orchestrator's delegation brief tells you which mode applies — do not infer it.

- **Mode 1 — Blueprint** (`bgpdd-plan` Phase 2, the default): execute the full Unified Workflow below (steps 1–8), producing `.docs/{project-name}/design/detailed-design.md`.
- **Mode 2 — Scoped Advisory** (`bgpdd-build` Phase 1 blast-radius review): execute steps 1–3 only, scoped strictly to the blast-radius report in your brief, and return your architectural recommendation directly in your `<handoff>`. Do NOT create or modify `detailed-design.md` — the epic's blueprint is already signed off; skip steps 4–7 entirely. Apply step 6's self-consistency reasoning to any snippet you put in your `<handoff>` regardless.

## Unified Workflow

1. **Identify Investigation Areas**: Analyze the requirements and identify areas where technical investigation, codebase analysis, or API documentation reading is needed.
2. **Conduct Research**: Conduct the necessary research yourself using your available tools (e.g., file reading, web search). Document your findings and save them to `.docs/{project-name}/research/{research_name}.md`.
3. **Synthesize Findings**: Ensure all technical uncertainties have been answered by your research.
4. **Generate Blueprint**: Create the final system design at `.docs/{project-name}/design/detailed-design.md`.
5. **Format and Detail**: Structure `detailed-design.md` with exactly these headings — this skill owns the template — and include **Mermaid diagrams** for architecture, data flow, and component relationships:
   - `## Overview & Goals` — what the design achieves; MUST cite the FR/NFR IDs from `requirements.md` it addresses.
   - `## Architecture Decisions` — the significant choices made, and why, over their alternatives.
   - `## Data Model` — entities, fields, relationships, and storage mechanisms.
   - `## API Contracts` — endpoints/operations with exact request/response shapes.
   - `## Component Breakdown` — modules/components and their responsibilities and boundaries.
   - `## Cross-Cutting Concerns` — authentication/authorization, error handling, logging.
   - `## Divergence & Supersession Register` — one row per design decision that contradicts an FR/NFR, a brief-fixed item (tech stack, entity fields, named business rules), or the honing transcript: what changed, why, what it supersedes.
   - `## Risks & Open Questions` — unresolved items, routed to the Orchestrator via your `<handoff>`.
6. **Self-Consistency Pass (before handoff) — the document must be true wherever a reader lands.** Any statement a reader could act on — a sample, table, diagram, numbered step, frozen section, register row, Open Question, or member of an assertion set — must agree with every other statement in the document and with `requirements.md`, after **every** edit, not only at first authoring — a reader implements the passage they land on, and nothing elsewhere rescues them. Corollaries:
   - **Samples win over prose.** Re-read every code sample, schema fragment, and wire-shape example against the invariants you stated elsewhere; where they disagree, **fix the sample, not the prose beside it**. Closest attention to samples that reshape a payload (unwrapping, mapping, projecting): verify no sibling field the invariants require to survive is discarded. Likewise every boundary your design mandates crossing (module, package, process) must be one the consuming side can actually resolve — name the declaration that makes it resolvable. ([deep dive](references/research-deep-dive.md#samples-are-normative))
   - **Frozen means literal and complete.** Anything you designate frozen, authoritative, or normative carries **zero elisions**: no `…`, no "same as above", no "as in the previous response", no "etc.", no placeholder types, no summarised field lists. Cross-references resolve by **named type**, never by prose pointing at another section. Too long to write out in full = too long to freeze: split it, or do not label it frozen. ([deep dive](references/research-deep-dive.md#frozen-means-literal))
   - **A decision that makes any FR/NFR sentence false is a supersession.** The test is semantic, not editorial: ask *does this decision make any sentence of an existing FR/NFR false?* If yes the obligation attaches — regardless of whether you would rather call it a divergence, a clarification, or an implementation detail, and regardless of which table you file the row under. Such a decision is **NOT complete until** it carries BOTH a row in the Divergence & Supersession Register AND an in-place annotation amending `requirements.md` (`~~...~~ — superseded by D-x, see design register`). NEVER renumber or delete IDs; once assigned, an ID never changes. ([deep dive](references/research-deep-dive.md#the-routing-test))
   - **A revision rewrites in place.** When amending an existing document, rewrite the affected text where it lives; never layer an amendment banner, revision section, or "authoritative override" block over normative text you are retracting, and leave no retracted statement standing anywhere. Refresh the sections that *describe state*, not only the clauses you changed — Open Questions, Assumptions, Risks, and any table of contents. A retraction too large to integrate means the document needs re-authoring, not a banner. ([deep dive](references/research-deep-dive.md#revision-integrity))
   - **Assertion sets are checked as sets.** Pairwise consistency is not set consistency: for any declared set of numbered assertions, invariants, or an enumerated allow-list, check every pair for mutual satisfiability and every member for referential validity — an id naming nothing is a defect. A set whose members were each reviewed alone has never been reviewed. (`bgpdd-plan` Phase 2.5 enforces this at gate time; here it is an authoring obligation.) ([deep dive](references/research-deep-dive.md#sets-as-sets))
7. **Brief-Conformance Diff**: Walk the brief's FIXED sections (tech stack, domain model/entity fields, named business rules) item-by-item, plus every Must-Have FR/NFR: each is either present in the design (cite the section) or has a Divergence & Supersession Register row. Absent from both = defect — fix before handoff. Output: a short conformance table appended to `detailed-design.md` (never to `design/design-review.md` — that file is the Orchestrator's Phase 2.5 output and has a single writer).
8. **Terminate**: Once the design is complete, generate your final handoff response and terminate.

## Deep Dive

Read on demand — not needed to hold the contract above:

- [Research deep dive](references/research-deep-dive.md) — why samples override prose, why frozen sections must be literal, the revision-integrity failures (amendment layering, stale state sections), the supersession routing test's observed evasion, and the set-level consistency instances.

