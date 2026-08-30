---
name: blackgoat-idea-honing
description: Guides the interactive requirements Q&A that refines a rough concept into a structured requirements document during bgpdd-plan Phase 1. Squad-internal execution contract followed by the main-session Orchestrator (adopting Rex's persona) — user-facing triggers belong to the /bgpdd-plan pipeline.
---

# Blackgoat Idea Honing

## Overview

Interactive Q&A that refines a rough idea into a structured requirements document: gather explicit user input before planning or coding, assume nothing, surface constraints and edge cases.

## Workflow

```
SCAFFOLD DIRECTORY ──→ INTERACTIVE Q&A ──→ DEFINE SUCCESS & UX ──→ OBTAIN CONFIRMATION
```

### Step 1: Initialize Working Memory

Before asking anything, locate or initialize the transcript artifact your core persona instructions specify. Every Q&A turn is logged there.

### Step 2: Interactive Questioning

Iteratively refine the initial concept into a detailed specification.

**Constraints:**
- **Ask ONLY ONE question at a time** and wait for the user's response before the next.
- NEVER list multiple questions at once.
- NEVER pre-populate answers or assume user preferences.
- **A question must carry its own finding.** A defect, conflict, or gap you surface must be answerable without the user reconstructing your analysis: state the concrete consequence of each option and what actually differs between them — not just the choice.
- **Teach the finding when asked, then re-ask.** A reply asking for explanation ("I don't understand this", "explain more") is a defect in how you posed the question, not user friction. Explain plainly — what breaks, why it matters, what each option costs — then re-ask.
- NEVER treat a request for clarification as a decision. NEVER treat silence or a non-answer as consent to your preferred option. NEVER let an unanswered question fall through into the requirements document as a silent assumption.
- Follow this exact sequence for each question:
  1. Formulate a single, targeted question.
  2. Append the question to your designated transcript artifact.
  3. Present the question to the user in the conversation.
  4. Wait for the user's complete response.
  5. Append the user's answer/decision to your designated transcript artifact.
  6. Proceed to the next question.

### Phase 1 Q&A Checklist

- [ ] **Visual Design & Component Styling Requirement**: explicitly inquire about visual styling requirements, UI design constraints, color schemes/themes, and whether multi-frontend applications require a centralized shared component library (e.g. `packages/ui` or `packages/shared-components`) for consistent UI controls (Buttons, Inputs, Dropdowns/Selects, Autocompletes, Date/Time Pickers). Document these as standard non-functional requirements in the normal `NFR-<n>` sequence, each with a MoSCoW tier.
- [ ] **Check-then-act gates on counted or summed state**: for every rule of the form "at most N", "only if the total is under X", or "only while capacity remains" — quota, balance, rate, seat, credit — ask explicitly what happens when two requests arrive at once. Ask it for **every** such gate in the domain, not just the first one you find.
- [ ] **Externally-supplied amounts that move money**: for every number arriving from outside the trust boundary — webhook payload, callback, redirect parameter, client-submitted total — that moves money or changes a balance, ask what it is validated against internally. "The provider signs it" answers authenticity, not correctness.
- [ ] **MoSCoW tiers must discriminate**: ask the cut question on every Must candidate — *"if this one thing were missing, would you still ship?"* — and record the answer; a requirement the user would ship without is not a Must. Nearly everything landing in Must-Have means the tiering has failed, not that the list is critical.

### Step 3: Iteration & Completion Checkpoint

Continue until all critical uncertainties are resolved.
- Once requirements are clear, summarize the current specifications.
- Explicitly ask the user whether the requirements clarification is complete.
- On confirmation the transcript is final — this skill ends there. Your caller's pipeline defines who synthesizes the requirements document from the finalized transcript.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Idea honing rationale](references/idea-honing-rationale.md) — why one question at a time, why a clarification request is an authoring defect, and what each Q&A checklist item was patched in to catch.
