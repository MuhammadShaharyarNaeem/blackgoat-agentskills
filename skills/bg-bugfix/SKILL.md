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

> **Conditional methodology loading**: If the bug involves a PowerShell script — a standalone `.ps1` or a script embedded in a host-language string (e.g. a C# string literal) — read `{PLUGIN_ROOT}/powershell-script-patterns/SKILL.md` before Phase 2 and follow its Worker Execution Contract (extract-test-re-embed, execution testing, external URL verification). `{PLUGIN_ROOT}` = this plugin's `skills/` directory (the directory containing this skill's folder). You are the main session, not a delegated subagent — where that contract says to escalate via `<handoff>` to the Orchestrator, ask the user directly instead.

> **Conditional methodology loading — runtime-observable bugs**: If the bug is observable at a boundary a client, person, or device reaches — a wrong response body/status/header, a wrong rendered state, a wrong device effect — or it arrived with a runtime capture (e.g. routed from `/bgpdd-verify`), read `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` before Phase 2 and hold its line: an in-process test can fail this bug but never prove it fixed. Phase 2's reproduction then includes an out-of-process observation of the wrong behavior (a capture per that contract), and Phase 3's gate additionally requires a fresh post-fix capture showing the correct behavior — the in-process regression test stays, the capture is added, neither substitutes for the other (this refines Phase 2's "unit or integration test" wording for this bug class; deliberate, convention #8). Cite both capture paths when you state the fix to the user, so the claim is checkable against files rather than taken on the suite's green. Same main-session adaptation as above: where that contract says to report to the Orchestrator, tell the user directly.

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
