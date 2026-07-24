---
name: playwright-skill
description: MCP-based end-to-end browser testing. Drive real user flows through the Playwright MCP tool surface (browser_navigate, browser_click, browser_fill_form, browser_snapshot, ...) to verify critical paths. Use when a task needs a real browser to confirm behavior, not unit tests. Squad-internal execution contract loaded by agents via their Methodology Dependencies table.
risk: unknown
source: community
date_added: "2026-02-27"
---

# Playwright E2E Testing (MCP)

Drive real user flows through a browser using the Playwright **MCP tool surface** and verify that critical paths work. E2E tests are slow and expensive — reach for them only when unit/integration tests cannot cover the behavior.

## Worker Execution Contract

### Core Principle

E2E tests verify real user flows through the browser. They are slow and expensive — write them only for critical paths that unit/integration tests cannot cover. One user flow per test; don't chain unrelated flows.

### Workflow

1. **SETUP** — Ensure the dev server is running, then load the target page with `browser_navigate`.
2. **INTERACT** — Simulate user actions with `browser_click`, `browser_fill_form`, `browser_type`, and `browser_press_key`. Wait for navigation/network with `browser_wait_for` — never a hard sleep.
3. **ASSERT** — Capture state with `browser_snapshot` (accessibility tree) or `browser_take_screenshot` (visual), and assert on DOM state with `browser_evaluate`.
4. **CLEANUP** — Close pages and reset test state between tests so nothing leaks into the next flow.

### Step-to-Tool Map

| Step     | Purpose                          | MCP Tool(s)                                                        |
| -------- | -------------------------------- | ----------------------------------------------------------------- |
| SETUP    | Load the page                    | `browser_navigate`                                                |
| INTERACT | Click / fill / type / keys       | `browser_click`, `browser_fill_form`, `browser_type`, `browser_press_key` |
| INTERACT | Wait for a condition             | `browser_wait_for`                                                |
| ASSERT   | Capture state                    | `browser_snapshot`, `browser_take_screenshot`                     |
| ASSERT   | Assert on DOM                    | `browser_evaluate`                                                |
| CLEANUP  | Reset between tests              | close pages / clear state                                         |

### Rules

- Use **accessible selectors**: `role`, `text`, `label`, `placeholder` — **NOT** CSS classes or XPaths.
- **Derive locators from the RENDERED DOM, never from component source.** Run the app and snapshot the accessibility tree to obtain selectors; do not transcribe `id`s/attributes off a component template during scouting or planning. UI frameworks that wrap native inputs (e.g. Quasar `QInput`/`QSelect` with `inheritAttrs: false`) strip or rewrite template `id`s, so a source-scouted `#id` looks authoritative but never renders. Confirm every scouted selector resolves against a live snapshot before it enters a plan or a spec.
- **A guarded (conditionally-run) branch must prove it executed.** When a step runs only if an element is visible/present, a wrong guard — e.g. a `.a .b` descendant selector where the DOM carries compound `.a.b` — makes the branch silently no-op, and a green run can never falsify a branch that never ran. Emit a branch marker/log when the guarded path is taken and assert it fired, so a mis-scoped guard fails loudly instead of passing by omission.
- Wait for elements before interacting: use `browser_wait_for` with reasonable timeouts.
- **Never use a hard-coded `sleep`** — wait for a specific condition instead.
- One user flow per test. Don't chain unrelated flows.
- Write any generated test scripts to the system temp directory (`$env:TEMP` on Windows, `/tmp` on Unix) — never into the skill directory or the user's project.
- Set test timeouts to prevent hangs: **30s per test, 5min per suite**.

### Verification Checklist

- [ ] All critical user flows have E2E coverage
- [ ] Tests use accessible selectors (not brittle CSS)
- [ ] Every guarded/conditional branch proves it ran (branch marker asserted) — no silently-skipped path can pass by omission
- [ ] No hard-coded sleeps
- [ ] Tests clean up after themselves (no state leakage)
- [ ] Tests pass on a clean environment

### Escalate When

- The dev server won't start → ask manager.
- A test is flaky (passes sometimes, fails others) → flag it and ask manager.
- Browser interaction is blocked by **CAPTCHA, auth wall, or CORS** → ask manager.

## Deep Dive

For engine-neutral rationale — when to write E2E vs unit tests, selector philosophy, waiting strategies, and common pitfalls — see [references/playwright-deep-dive.md](references/playwright-deep-dive.md).
