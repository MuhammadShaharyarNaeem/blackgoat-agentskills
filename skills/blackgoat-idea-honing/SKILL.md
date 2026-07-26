---
name: blackgoat-idea-honing
description: Guides the interactive requirements Q&A that refines a rough concept into a structured requirements document during bgpdd-plan Phase 1. Squad-internal execution contract followed by the main-session Orchestrator (adopting Rex's persona) — user-facing triggers belong to the /bgpdd-plan pipeline.
---

# Blackgoat Idea Honing

## Overview

This skill enables interactive Q&A requirements gathering to systematically refine a rough idea into a structured requirements document. It focuses on gathering explicit user input before planning or coding, avoiding assumptions, and identifying constraints and edge cases.

## Workflow

```
SCAFFOLD DIRECTORY ──→ INTERACTIVE Q&A ──→ DEFINE SUCCESS & UX ──→ OBTAIN CONFIRMATION
```

### Step 1: Initialize Working Memory

Before asking questions, ensure you have located or initialized the transcript artifact specified by your core persona instructions. You will use this artifact to log the interactive Q&A.

### Step 2: Interactive Questioning

Iteratively guide the user through a series of questions to refine the initial concept and build a detailed specification.

**Constraints:**
- **Ask ONLY ONE question at a time** and wait for the user's response before asking the next.
- Do NOT list multiple questions at once, as this overwhelms the user.
- Do NOT pre-populate answers or assume user preferences.
- **A question must carry its own finding.** When you surface a defect, conflict, or gap for the user to decide, the question must be answerable without them reconstructing your analysis. State the concrete consequence of each option and what actually differs between them — not just the choice. A user cannot pick between two options whose difference you have not made visible.
- **Teach the finding when asked, then re-ask.** If the user replies asking for explanation rather than choosing ("I don't understand this", "explain more"), that is a defect in how you posed the question, not user friction. Explain the finding plainly — what breaks, why it matters, what each option costs — then re-ask. Never treat a request for clarification as a decision, never treat silence or a non-answer as consent to your preferred option, and never let an unanswered question fall through into the requirements document as a silent assumption.
- Follow this exact sequence for each question:
  1. Formulate a single, targeted question.
  2. Append the question to your designated transcript artifact.
  3. Present the question to the user in the conversation.
  4. Wait for the user's complete response.
  5. Append the user's answer/decision to your designated transcript artifact.
  6. Proceed to the next question.

### Phase 1 Q&A Checklist

- [ ] **Visual Design & Component Styling Requirement**: Explicitly inquire about visual styling requirements, UI design constraints, color schemes/themes, and whether multi-frontend applications require a centralized shared component library (e.g. `packages/ui` or `packages/shared-components`) for consistent UI controls (Buttons, Inputs, Dropdowns/Selects, Autocompletes, Date/Time Pickers). Document these as standard non-functional requirements in the normal `NFR-<n>` sequence, each with a MoSCoW tier.

### Step 3: Iteration & Completion Checkpoint

Continue the interactive process until all critical uncertainties are resolved.
- Once requirements are clear, summarize the current specifications.
- Explicitly ask the user if they feel the requirements clarification is complete.
- Upon receiving confirmation, immediately generate your final output artifacts as strictly defined by your core persona instructions.

