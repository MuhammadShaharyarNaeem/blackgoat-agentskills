---
name: blackgoat-research
description: Guides Aria's codebase/technology research and the authoring of the detailed design document during bgpdd-plan Phase 2. Squad-internal execution contract loaded by Aria via her Methodology Dependencies table — user-facing triggers belong to the /bgpdd-plan pipeline.
---

# Blackgoat Research

## Overview

This skill enables collaborative technical research, technology analysis, and system architecture design. It guides the creation of research notes and detailed design documents before writing implementation code.

## Modes

Your Orchestrator's delegation brief tells you which mode applies — do not infer it.

- **Mode 1 — Blueprint** (`bgpdd-plan` Phase 2, the default): execute the full Unified Workflow below (steps 1–6), producing `.docs/{project-name}/design/detailed-design.md`.
- **Mode 2 — Scoped Advisory** (`bgpdd-build` Phase 1 blast-radius review): execute steps 1–3 only, scoped strictly to the blast-radius report in your brief, and return your architectural recommendation directly in your `<handoff>`. Do NOT create or modify `detailed-design.md` — the epic's blueprint is already signed off; skip steps 4–5 entirely.

## Unified Workflow

1. **Identify Investigation Areas**: Analyze the requirements and identify areas where technical investigation, codebase analysis, or API documentation reading is needed.
2. **Conduct Research**: Conduct the necessary research yourself using your available tools (e.g., file reading, web search). Document your findings and save them to `.docs/{project-name}/research/{research_name}.md`.
3. **Synthesize Findings**: Ensure all technical uncertainties have been answered by your research.
4. **Generate Blueprint**: Create the final system design at `.docs/{project-name}/design/detailed-design.md`.
5. **Format and Detail**: Generate the final detailed design document using the exact structure and constraints specified by your core persona instructions. Include **Mermaid diagrams** for architecture, data flow, and component relationships.
6. **Terminate**: Once the design is complete, generate your final handoff response and terminate.

