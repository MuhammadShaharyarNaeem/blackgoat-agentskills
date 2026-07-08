---
name: playwright-skill-contract
description: Condensed Playwright contract for E2E test workers. Core patterns and verification only.
---

# Playwright — Worker Contract

## Core Principle

E2E tests verify real user flows through the browser. They are slow and expensive — write them only for critical paths that unit/integration tests cannot cover.

## Workflow

1. **SETUP**: Ensure the dev server is running before launching tests. Use the Playwright MCP tools or direct `browser_navigate` to load the target page.
2. **INTERACT**: Use `browser_click`, `browser_fill_form`, `browser_type`, `browser_press_key` to simulate user actions. Always wait for navigation/network with `browser_wait_for`.
3. **ASSERT**: Take snapshots with `browser_snapshot` or `browser_take_screenshot` to verify visual state. Use `browser_evaluate` to assert on DOM state.
4. **CLEANUP**: Close pages and clean up test state between tests.

## Rules

- Use accessible selectors: `role`, `text`, `label`, `placeholder` — NOT CSS classes or XPaths.
- Wait for elements before interacting: use `browser_wait_for` with reasonable timeouts.
- Never use hard-coded `sleep` — wait for specific conditions instead.
- One user flow per test. Don't chain unrelated flows.
- Write test scripts to the system temp directory (use `$env:TEMP` on Windows, `/tmp` on Unix).
- Set test timeouts (30s per test, 5min per suite) to prevent hangs.

## Verification Checklist

- [ ] All critical user flows have E2E coverage
- [ ] Tests use accessible selectors (not brittle CSS)
- [ ] No hard-coded sleeps
- [ ] Tests clean up after themselves (no state leakage)
- [ ] Tests pass on a clean environment

## Escalate When

- The dev server won't start → ask manager.
- A test is flaky (passes sometimes, fails others) → flag it and ask manager.
- Browser interaction is blocked by CAPTCHA, auth wall, or CORS → ask manager.
