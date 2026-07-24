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
- Follow this exact sequence for each question:
  1. Formulate a single, targeted question.
  2. Append the question to your designated transcript artifact.
  3. Present the question to the user in the conversation.
  4. Wait for the user's complete response.
  5. Append the user's answer/decision to your designated transcript artifact.
  6. Proceed to the next question.

### Step 3: Iteration & Completion Checkpoint

Continue the interactive process until all critical uncertainties are resolved.
- Once requirements are clear, summarize the current specifications.
- Explicitly ask the user if they feel the requirements clarification is complete.
- Upon receiving confirmation, immediately generate your final output artifacts as strictly defined by your core persona instructions.

