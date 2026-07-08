---
name: debugging-and-error-recovery-contract
description: Condensed debugging contract for worker agents. Systematic root-cause analysis only.
---

# Debugging & Error Recovery — Worker Contract

## Core Principle

Never guess. Reproduce first, then trace systematically. Fix the root cause, not the symptom.

## Workflow

1. **REPRODUCE**: Create a minimal reproduction of the failure. If you can't reproduce it, you can't fix it.
2. **ISOLATE**: Narrow the scope. Binary search through the call chain to find where expected behavior diverges from actual.
3. **TRACE**: Read the actual error message, stack trace, and logs. Follow the data flow from input to failure point.
4. **HYPOTHESIZE**: Form ONE specific hypothesis about the root cause. State it explicitly.
5. **TEST**: Write a targeted test or add a log to confirm/deny the hypothesis.
6. **FIX**: Make the smallest possible change that fixes the root cause.
7. **VERIFY**: Confirm the fix resolves the original failure AND doesn't break other tests.

## Rules

- Read the FULL error message before doing anything. Do not skim.
- Check the most recent change first — it's the most likely cause.
- Don't fix multiple things at once. One change, one verification.
- If a fix requires changing more than 3 files, stop and reassess — you may be treating a symptom.
- Log your debugging steps so the manager can follow your reasoning.

## Verification Checklist

- [ ] Root cause identified and documented
- [ ] Fix is minimal and targeted
- [ ] Original failure no longer reproduces
- [ ] No regressions — all existing tests still pass
- [ ] A regression test has been added for the specific failure

## Escalate When

- The bug cannot be reproduced in your environment → ask manager.
- Root cause is in a dependency you cannot modify → ask manager.
- 3 failed fix attempts → halt, document findings, report to manager.
