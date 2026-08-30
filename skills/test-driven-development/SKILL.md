---
name: test-driven-development
description: "Use when implementing any feature or bugfix, before writing implementation code. Provides the worker execution contract (RED/GREEN/REFACTOR, rules, verification, escalation) plus on-demand deep-dive rationale. Squad-internal execution contract loaded by agents via their Methodology Dependencies table."
risk: unknown
source: community
date_added: "2026-02-27"
---

# Test-Driven Development (TDD)

## Worker Execution Contract

### The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

**Never skip RED** (RED-before-implementation). Wrote code before the test? DELETE it — not kept as "reference", not adapted, not looked at. Delete means delete; implement fresh from tests.

### Workflow

1. **RED**: Write one failing test for the next behavior. Verify it fails for the expected reason (feature missing — not a typo or error).
2. **GREEN**: Write the minimum code to pass — no speculative features, options, or abstractions (YAGNI). Verify it passes; run the full suite and confirm all green, output pristine.
3. **REFACTOR**: Clean up without changing behavior. Tests stay green.
4. Repeat for the next behavior.

### Rules

- One logical assertion / one behavior per test.
- Test names describe behavior: `"should reject empty email"`, not `"test validateInput"`. Name needs "and" → split the test.
- AAA structure: Arrange → Act → Assert.
- Parameterize tests for multiple input variants rather than duplicating.
- NEVER test implementation details (private methods, internal state).
- NEVER write dummy assertions (`expect(true).toBe(true)`) or stub tests: tests must rigorously mount, exercise, and assert the full state, style variations, and behavior of the target component or function.
- Prefer real code. Mock ONLY true external boundaries you don't own — network APIs, databases, the filesystem, clock/randomness. NEVER mock your own code under test.
- Stack execution contracts (e.g. `dotnet-backend-patterns`) take precedence over the boundary list above where they conflict — e.g. on .NET, integration tests never mock the database.
- **Negative-half proof — no gate or test is trusted until it has been observed FAILING on a deliberate violation.** This is RED applied to everything that renders a verdict, including checks that are not TDD output: a lint or contract-check script, an accessibility scan, a state-matrix assertion, a CI job. Introduce the violation the gate exists to catch, run it, capture the non-zero exit or failure output, revert, and record that capture alongside the passing run. Until then, a hollow assertion and a real one are indistinguishable — both are green. (Failure modes and rationale: [deep dive](references/tdd-deep-dive.md).)
- **Permanent regression test for permanent invariants**: a hard invariant or Must-Have NFR that must hold permanently (a stable wire/serialization format, byte-for-byte compatibility, a public-API surface) MUST be covered by a PERMANENT automated regression test committed to the suite. A throwaway harness may supplement, never replace it — this overrides any plan or checklist step that says "manual check", "temporary check", or "verify once".
- **Mock Fidelity Rule** (supersedes the narrower "Network Client Mocking Rule"): a mock is derived from the authoritative contract, never authored from the consumer's expectations.
  - **Shape**: the mocked return matches the **post-middleware/post-interceptor** structure the application actually receives at runtime, not the raw HTTP envelope.
  - **Field identity**: field names, casing, nullability, and nesting come from the contract artifact — the API spec, schema, or frozen interface definition; every mocked field must trace back to it. Type the contract boundary from the contract too — no `any`, no untyped destructuring.
  - **Fixture identity**: the rule covers **seeded state**, not only mocked responses. Any fixture pre-populating application state (auth storage-state, cookies, cached entities, feature flags) derives its storage mechanism *and* its exact keys from the application's own accessor code, never from the test framework's default idiom.
  - No contract artifact? Capture one real response first and derive the mock from that. "I read the calling code and matched it" is the failure mode, not the method. (Why field identity bites: [testing anti-patterns](references/testing-anti-patterns.md).)
- **Closed-set assertions pin exact cardinality and membership**: asserting anything about a set meant to be closed — an exemption or allowlist, a route table, enum members, registered handlers or providers, a public export surface — assert its **exact length and exact members** (`=== n` plus the membership check), NEVER `<=`, `>=`, or "contains".
- **A feature is not done until a test reaches it through its real composition root** (the composition-root rule). Register new units where the application actually resolves them — route table, DI container, module export, plugin/handler registry — and the test that authorizes the feature must arrive through that entry point, not by importing the unit directly.

### Verification Checklist

Before marking work complete:

- [ ] Every behavior from the requirements has a corresponding test
- [ ] Watched each test fail before implementing, and it failed for the expected reason
- [ ] Every gate or check script authored or touched has been observed failing on a deliberate violation, with the failure output captured (negative-half proof)
- [ ] Wrote minimal code to pass each test
- [ ] All tests pass (`GREEN`), output pristine (no errors, warnings)
- [ ] No test depends on another test's state or execution order
- [ ] Tests use real code; mocks only at true external boundaries
- [ ] Test names describe behavior, not implementation
- [ ] Edge cases and errors covered

Can't check all boxes? You skipped TDD. Start over.

### Escalate When

- Repo has no test infrastructure → do NOT silently skip verification and do NOT unilaterally drop TDD. The manager sets the verification standard in the briefing; absent test infra it degrades to build-success plus public-API-surface invariance (no unintended signature/contract changes), never "no verification". No standard in the briefing → escalate for one before writing code.
- 3 consecutive RED-RED cycles (can't reach GREEN) → halt and report to manager.
- Unclear requirement makes it impossible to define expected behavior → ask manager.

## Deep Dive

Read these on demand — not needed to execute the contract above:

- [TDD deep dive](references/tdd-deep-dive.md) — worked RED/GREEN examples, the Red-Green-Refactor diagram, "Why Order Matters", the Common Rationalizations table, red flags, a bug-fix walkthrough, when-stuck guidance, and rule rationale (negative-half proof, closed-set assertions, composition root).
- [Testing anti-patterns](references/testing-anti-patterns.md) — read when adding mocks or test utilities: testing mock behavior, test-only methods in production, incomplete mocks, mocking without understanding dependencies, and mock-fidelity rationale.
