---
name: bg-bugfix
description: "Traces and fixes bugs using root cause analysis and test-driven development without squad overhead."
category: execution
risk: safe
---

# BG-Bugfix

## Purpose
To provide a lean, sequential methodology for fixing bugs without the bureaucratic overhead of a multi-agent squad. It enforces root cause analysis and test-driven development (TDD) through structured pair-programming.

## When to Use This Skill
- When the user reports a bug or defect in the code.
- When you need to trace an error stack before writing a fix.
- Trigger phrases: "fix this bug", "debug this error", "use bg-bugfix".

## Execution Workflow

Follow this strict 5-phase sequence sequentially. Do not skip phases.

### Phase 1: Root Cause Analysis (RCA)
1. **Trace**: Use Grep and Read to trace the execution path.
2. **Identify**: Isolate the specific mechanism of the failure.
3. **Constraint**: Do not write or edit functional code during this phase.
4. **Gate**: State the explicit root cause to the user before proceeding.

### Phase 2: The Proof (TDD)
1. **Isolate**: Write a single unit or integration test that perfectly reproduces the bug.
2. **Execute**: Run the test.
3. **Gate**: Verify the test fails for the correct reason before touching application code.

### Phase 3: The Fix
1. **Modify**: Surgically update the application code to address the root cause identified in Phase 1.
2. **Execute**: Run the test suite.
3. **Gate**: Verify the failing test from Phase 2 now passes, and no regressions are introduced.

### Phase 4: Blast Radius Verification
1. **Analyze**: Use Grep to check for other consumers of the modified function or class.
2. **Verify**: Ensure the fix does not break adjacent features.
3. **Gate**: If the blast radius extends beyond the isolated feature, halt and escalate to the user.

### Phase 5: Procedural Memory Update
1. **Evaluate**: Determine if the bug was a unique typo or a systemic misunderstanding.
2. **Route**: If a systemic lesson was learned, tell the user and suggest running `/bgpdd-learn` — lessons are routed through Forge's Destination Triage with pruning and explicit approval, never appended ad-hoc.

## Limitations
- Use this skill only for localized bug fixes. For sweeping architectural changes, use the full `bgpdd-build` methodology instead.
