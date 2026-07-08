---
name: test-driven-development-contract
description: Condensed TDD contract for worker agents. Core rules and verification only.
---

# Test-Driven Development — Worker Contract

## The Iron Law

Write a FAILING test FIRST. Then write the minimum code to make it pass. Then refactor. **Never skip RED.**

## Workflow

1. **RED**: Write one failing test for the next behavior.
2. **GREEN**: Write the minimum code to pass that test — no more.
3. **REFACTOR**: Clean up without changing behavior. Tests stay green.
4. Repeat for next behavior.

## Rules

- One logical assertion per test.
- Test names describe behavior: `"should reject empty email"` not `"test validateInput"`.
- Never test implementation details (private methods, internal state).
- Mock external dependencies (APIs, DBs, file system), not your own code.
- Run the full test suite after each GREEN step.
- Use AAA structure: Arrange → Act → Assert.
- Parameterize tests for multiple input variants rather than duplicating.

## Verification Checklist

- [ ] Every behavior from the requirements has a corresponding test
- [ ] All tests pass (`GREEN`)
- [ ] No test depends on another test's state or execution order
- [ ] External dependencies are mocked
- [ ] Test names describe behavior, not implementation

## Escalate When

- Test requires infrastructure not available in your environment → ask manager.
- 3 consecutive RED-RED cycles (can't reach GREEN) → halt and report to manager.
- Unclear requirement makes it impossible to define expected behavior → ask manager.
