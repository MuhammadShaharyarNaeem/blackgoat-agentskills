---
name: bg-bugfix
description: "Traces and fixes bugs using root cause analysis and test-driven development without squad overhead."
category: execution
risk: safe
---

# BG-Bugfix

## Purpose

Lean, sequential bugfix methodology — no multi-agent squad. Enforces root cause analysis before any edit, and a test-driven proof before any fix.

## When to Use This Skill
- The user reports a bug or defect in the code.
- You need to trace an error stack before writing a fix.
- Trigger phrases: "fix this bug", "debug this error", "use bg-bugfix".

## Execution Workflow

Run the 5 phases in order. NEVER skip a phase.

`{PLUGIN_ROOT}` = this plugin's `skills/` directory (the directory containing this skill's folder).

**Main-session adaptation**: you are the main session, not a delegated subagent. Where a loaded contract says to escalate via `<handoff>` or report to the Orchestrator, ask or tell the user directly.

### Conditional methodology loading (read before Phase 2)

| WHEN | READ |
|---|---|
| The bug involves a PowerShell script — a standalone `.ps1`, or one embedded in a host-language string (e.g. a C# string literal) | `{PLUGIN_ROOT}/powershell-script-patterns/SKILL.md` — follow its Worker Execution Contract |
| The bug is observable at a boundary a client, person, or device reaches — wrong response body/status/header, wrong rendered state, wrong device effect — **or** it arrived with a runtime capture (e.g. routed from `/bgpdd-verify`) | `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` — then apply the rules below |

Runtime-observable bugs (deliberately refines Phase 2's "unit or integration test" wording for this bug class — convention #8):
- An in-process test can FAIL this bug; it can NEVER prove it fixed.
- Phase 2's reproduction adds an out-of-process capture of the wrong behavior.
- Phase 3's gate additionally requires a fresh post-fix capture of the correct behavior.
- Both stay — the in-process regression test AND the capture. Neither substitutes for the other.
- MUST cite both capture paths when stating the fix, so the claim is checkable against files rather than the suite's green.

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
