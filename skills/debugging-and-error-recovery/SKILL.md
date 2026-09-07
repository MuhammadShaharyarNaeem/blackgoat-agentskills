---
name: debugging-and-error-recovery
description: "Guides systematic root-cause debugging. Use when tests fail, builds break, behavior doesn't match expectations, or you encounter any unexpected error. Use when you need a systematic approach to finding and fixing the root cause rather than guessing. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Also directly invocable: when a user asks for this on named files outside a pipeline, the Orchestrator applies the Worker Execution Contract itself in the main session — no delegation."
---

# Debugging and Error Recovery

Systematic root-cause debugging for test failures, build errors, runtime bugs, and production incidents: stop, preserve evidence, reproduce, trace — never guess.

## Direct invocation

A user can ask for this directly on named files — a deliberate refinement of agent-audit Metric 12, not a trigger collision. The Orchestrator applies the Worker Execution Contract below inline, in the main session: no delegation, no editing tests to pass, no unobserved claims (`base-persona.md`, Evidence Integrity). Over three files, or shared behaviour: route via `/bg` to a lane.

## Quick card

Derived from the contract below for a ≤ 3-file change; no new rules (convention #8 — deliberately narrower than the full contract, which binds inside any lane).

1. A defect that predates your edit is `/bgpdd-bugfix`, never quick — this card covers only an error your own change just caused (§ Escalate When).
2. Reproduce it before touching anything; unreproduced is unfixable (§ Workflow, REPRODUCE).
3. State one hypothesis, then make one change (§ Rules).
4. Re-run the exact check that failed, at the tier it was reported at (§ Workflow, VERIFY).
5. Past three files or three failed attempts → stop and escalate (§ Escalate When).

- Brief → the quick note (What / Where / How verified)
- Artifact → the capture at `{quick-root}/evidence/check.md`
- Handoff → the `## Result` bullet in `note.md`

## Worker Execution Contract

For a change of ≤ 3 files outside a pipeline, the Quick card above is the contract; the full contract applies inside a lane.

### Core Principle

Never guess. Reproduce first, then trace systematically. Fix the root cause, not the symptom.

### Workflow

1. **REPRODUCE**: Create a minimal reproduction of the failure. If you can't reproduce it, you can't fix it.
2. **ISOLATE**: Narrow the scope. Binary search through the call chain to find where expected behavior diverges from actual.
3. **TRACE**: Read the actual error message, stack trace, and logs. Follow the data flow from input to failure point.
4. **HYPOTHESIZE**: Form ONE specific hypothesis about the root cause. State it explicitly.
5. **TEST**: Write a targeted test or add a log to confirm/deny the hypothesis.
6. **FIX**: Make the smallest possible change that fixes the root cause.
7. **VERIFY**: Confirm the fix resolves the original failure AND doesn't break other tests.
   - **VERIFY runs at the tier the failure was reported at.** Re-run *the exact check that failed* — the named failing test if the report was a unit/integration failure, the declared runtime probe if it was an observed-runtime failure, a fresh render of the critiqued state if it was a rendered-output finding. A green suite at a lower tier does not discharge a failure observed at a higher one (`{PLUGIN_ROOT}/runtime-evidence/SKILL.md`, *Core Principle*).
   - Handed the failure by someone else (a rejection round, a review finding) → report this re-run and its observed output back to them. Could not re-run it → say `NOT VERIFIED — <what blocked you>` rather than asserting the fix from the diff. Reporting shape: your persona's handoff contract.

### Rules

- Read the FULL error message before doing anything. Do not skim.
- Check the most recent change first — it's the most likely cause.
- Don't fix multiple things at once. One change, one verification.
- If a fix requires changing more than 3 files, stop and reassess — you may be treating a symptom.
- Log your debugging steps so the manager can follow your reasoning.

### Verification Checklist

- [ ] Root cause identified and documented
- [ ] Fix is minimal and targeted
- [ ] Original failure no longer reproduces
- [ ] No regressions — all existing tests still pass
- [ ] A regression test has been added for the specific failure

### Escalate When

- **The defect predates the change in front of you** → it is a `/bgpdd-bugfix` item, not a debugging pass inside this change. Report it to the Orchestrator, which routes it; this contract covers an error the current change just caused.
- The bug cannot be reproduced in your environment → ask manager.
- Root cause is in a dependency you cannot modify → ask manager.
- 3 failed fix attempts → halt, document findings, report to manager.

## Deep Dive

For the full triage manual — decision trees, error-type tables, `git bisect` recipes, safe-fallback code samples, instrumentation guidelines, and guidance on treating error output as untrusted data — read:

- [references/debugging-deep-dive.md](references/debugging-deep-dive.md)
