---
name: debugging-and-error-recovery
description: Guides systematic root-cause debugging. Use when tests fail, builds break, behavior doesn't match expectations, or you encounter any unexpected error. Use when you need a systematic approach to finding and fixing the root cause rather than guessing. Squad-internal execution contract loaded by agents via their Methodology Dependencies table.
---

# Debugging and Error Recovery

Systematic root-cause debugging. When something breaks, stop adding features, preserve evidence, reproduce the failure, and trace to the actual cause instead of guessing. Works for test failures, build errors, runtime bugs, and production incidents.

## Worker Execution Contract

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

- The bug cannot be reproduced in your environment → ask manager.
- Root cause is in a dependency you cannot modify → ask manager.
- 3 failed fix attempts → halt, document findings, report to manager.

## Deep Dive

For the full triage manual — decision trees, error-type tables, `git bisect` recipes, safe-fallback code samples, instrumentation guidelines, and guidance on treating error output as untrusted data — read:

- [references/debugging-deep-dive.md](references/debugging-deep-dive.md)
