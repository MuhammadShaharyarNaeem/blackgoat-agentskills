---
name: test-driven-development
description: "Use when implementing any feature or bugfix, before writing implementation code. Provides the worker execution contract (RED/GREEN/REFACTOR, rules, verification, escalation) plus on-demand deep-dive rationale. Squad-internal execution contract loaded by agents via their Methodology Dependencies table."
risk: unknown
source: community
date_added: "2026-02-27"
---

# Test-Driven Development (TDD)

Write the test first. Watch it fail. Write minimal code to pass. If you didn't watch the test fail, you don't know if it tests the right thing.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

Write a FAILING test FIRST. Then write the minimum code to make it pass. Then refactor. **Never skip RED.**

Wrote code before the test? Delete it. Start over. No exceptions — don't keep it as "reference", don't "adapt" it, don't look at it. Delete means delete. Implement fresh from tests.

### Workflow

1. **RED**: Write one failing test for the next behavior. Verify it fails for the expected reason (feature missing, not a typo or error).
2. **GREEN**: Write the minimum code to pass that test — no more. Verify it passes and all other tests stay green with pristine output.
3. **REFACTOR**: Clean up without changing behavior. Tests stay green.
4. Repeat for the next behavior.

### Rules

- One logical assertion / one behavior per test.
- Test names describe behavior: `"should reject empty email"` not `"test validateInput"`. If the name needs "and", split the test.
- Use AAA structure: Arrange → Act → Assert.
- Parameterize tests for multiple input variants rather than duplicating.
- Never test implementation details (private methods, internal state).
- Prefer real code. Mock ONLY true external boundaries you don't own — network APIs, databases, the filesystem, clock/randomness. Never mock your own code under test.
- Run the full test suite after each GREEN step.
- Write minimal code to pass — no speculative features, options, or abstractions (YAGNI).
- Stack execution contracts (e.g. dotnet-backend-patterns) take precedence over the boundary list above where they conflict — e.g. on .NET, integration tests never mock the database.

### Verification Checklist

Before marking work complete:

- [ ] Every behavior from the requirements has a corresponding test
- [ ] Watched each test fail before implementing, and it failed for the expected reason
- [ ] Wrote minimal code to pass each test
- [ ] All tests pass (`GREEN`), output pristine (no errors, warnings)
- [ ] No test depends on another test's state or execution order
- [ ] Tests use real code; mocks only at true external boundaries
- [ ] Test names describe behavior, not implementation
- [ ] Edge cases and errors covered

Can't check all boxes? You skipped TDD. Start over.

### Escalate When

- Test requires infrastructure not available in your environment → ask manager.
- 3 consecutive RED-RED cycles (can't reach GREEN) → halt and report to manager.
- Unclear requirement makes it impossible to define expected behavior → ask manager.

## Deep Dive

Read these on demand — not needed to execute the contract above:

- [TDD deep dive](references/tdd-deep-dive.md) — worked RED/GREEN examples, the Red-Green-Refactor diagram, "Why Order Matters", the Common Rationalizations table, red flags, a bug-fix walkthrough, and when-stuck guidance.
- [Testing anti-patterns](references/testing-anti-patterns.md) — read when adding mocks or test utilities: testing mock behavior, test-only methods in production, incomplete mocks, and mocking without understanding dependencies.
