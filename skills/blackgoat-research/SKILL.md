---
name: blackgoat-research
description: Conducts codebase and technology research, documents findings, and develops the system architecture and detailed design document. Used during Phase 2 of Prompt-Driven Development.
---

# Blackgoat Research

## Overview

This skill enables collaborative technical research, technology analysis, and system architecture design. It guides the creation of research notes and detailed design documents before writing implementation code.

## Unified Workflow

1. **Identify Investigation Areas**: Analyze the requirements and identify areas where technical investigation, codebase analysis, or API documentation reading is needed.
2. **Conduct Research**: Conduct the necessary research yourself using your available tools (e.g., file reading, web search). Document your findings and save them to `.docs/{feature}/research/{research_name}.md`.
3. **Synthesize Findings**: Ensure all technical uncertainties have been answered by your research.
4. **Generate Blueprint**: Create the final system design at `.docs/{name}/design/detailed-design.md`.
5. **Format and Detail**: Generate the final detailed design document using the exact structure and constraints specified by your core persona instructions. Include **Mermaid diagrams** for architecture, data flow, and component relationships.
6. **Terminate**: Once the design is complete, generate your final handoff response and terminate.

