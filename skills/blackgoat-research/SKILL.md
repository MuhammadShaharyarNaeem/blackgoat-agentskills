---
name: blackgoat-research
description: Guides Aria's codebase/technology research and the authoring of the detailed design document during bgpdd-plan Phase 2. Squad-internal execution contract loaded by Aria via her Methodology Dependencies table — user-facing triggers belong to the /bgpdd-plan pipeline.
---

# Blackgoat Research

## Overview

This skill enables collaborative technical research, technology analysis, and system architecture design. It guides the creation of research notes and detailed design documents before writing implementation code.

## Modes

Your Orchestrator's delegation brief tells you which mode applies — do not infer it.

- **Mode 1 — Blueprint** (`bgpdd-plan` Phase 2, the default): execute the full Unified Workflow below (steps 1–7), producing `.docs/{project-name}/design/detailed-design.md`.
- **Mode 2 — Scoped Advisory** (`bgpdd-build` Phase 1 blast-radius review): execute steps 1–3 only, scoped strictly to the blast-radius report in your brief, and return your architectural recommendation directly in your `<handoff>`. Do NOT create or modify `detailed-design.md` — the epic's blueprint is already signed off; skip steps 4–6 entirely. Apply step 6's self-consistency reasoning to any snippet you put in your `<handoff>` regardless.

## Unified Workflow

1. **Identify Investigation Areas**: Analyze the requirements and identify areas where technical investigation, codebase analysis, or API documentation reading is needed.
2. **Conduct Research**: Conduct the necessary research yourself using your available tools (e.g., file reading, web search). Document your findings and save them to `.docs/{project-name}/research/{research_name}.md`.
3. **Synthesize Findings**: Ensure all technical uncertainties have been answered by your research.
4. **Generate Blueprint**: Create the final system design at `.docs/{project-name}/design/detailed-design.md`.
5. **Format and Detail**: Generate the final detailed design document using the exact structure and constraints specified by your core persona instructions. Include **Mermaid diagrams** for architecture, data flow, and component relationships.
6. **Self-Consistency Pass (before handoff)**: A blueprint states invariants in prose and illustrates them in samples; the two must agree. Before terminating, re-read every code sample, schema fragment, and wire-shape example you wrote and check each against the invariants you stated elsewhere in the same document — a document that mandates a rule in one section and violates it in a sample in another **will be implemented as the sample**, because downstream agents copy samples and only read prose. Fix the sample, not the prose beside it. Pay closest attention to samples that reshape a payload (unwrapping, mapping, projecting): verify no sibling field the invariants require to survive is discarded. Also confirm that every boundary your design mandates crossing (module, package, process) is one the consuming side can actually resolve, and name the declaration that makes it resolvable — a mandated import with no declared dependency is a blueprint that cannot be built.
7. **Terminate**: Once the design is complete, generate your final handoff response and terminate.

