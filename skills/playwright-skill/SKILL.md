---
name: playwright-skill
description: MCP-based end-to-end browser testing. Drive real user flows through the Playwright MCP tool surface (browser_navigate, browser_click, browser_fill_form, browser_snapshot, ...) to verify critical paths. Use when a task needs a real browser to confirm behavior, not unit tests. Specs reproduce what a manual QA does — real UI, real backend, real navigation — never stubbing the asserted endpoint or deep-linking past the journey. Squad-internal execution contract loaded by agents via their Methodology Dependencies table.
risk: unknown
source: community
date_added: "2026-02-27"
---

# Playwright E2E Testing (MCP)

Drive real user flows through the Playwright **MCP tool surface** to verify critical paths. E2E tests are slow and expensive — reach for them only when unit/integration tests cannot cover the behavior.

## Worker Execution Contract

### Core Principle

**A Playwright spec is an automated pass of what a manual QA would do — no more exotic than that, and no less honest.** It exercises the system the way a person does: real UI, real backend, starting where a user starts. Every deviation buys speed by deleting exactly the coverage the test existed to provide.

The governing test for every step you write: **could a QA on a fresh login perform this step by hand, and would they observe what it asserts?** If not, the step is evidence about your fixture, not the product.

Three failure modes follow from this — mocking what you assert, teleporting past the journey, and a predicate-guarded step silently doing nothing while still reporting green — each fully specified as a Rule below (anti-pattern illustrations: [deep dive](references/playwright-deep-dive.md)).

### Workflow

1. **SETUP** — Ensure the dev server is running, then enter the app where a user enters it (sign-in / home) and **navigate to the target through the UI**. `browser_navigate` is for the entry point, not for skipping the journey.
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
- **Anything activated by a predicate must prove it fired — guarded branches and network interception alike.** If a predicate decides whether a conditional step, route matcher, stub, or injection runs, a wrong predicate makes it a silent no-op that a green run can never falsify. Three obligations: **(1)** emit a marker/log when the path is taken and assert it, so a mis-scoped predicate fails loudly instead of passing by omission; **(2)** key matchers on the **distinctive tail** of a path, never a base-URL shape — a prefix the environment can be repointed away from stops matching silently; **(3)** pair every negative assertion with a positive control — asserting something hidden/absent in an environment that satisfies it anyway is vacuous either way. Verify predicates against the paths the app **actually serves**, not the paths you expect.
- **Never stub, mock, or intercept the endpoint whose behavior the requirement asserts** (rationale: [deep dive](references/playwright-deep-dive.md), "It mocks what it asserts"). Mock only collaborators outside the claim, naming which ones and why. A flow whose requirement is "this call succeeds/fails" drives against the real endpoint, or is recorded BLOCKED.
- **Reach the feature the way a user reaches it — never deep-link past the journey** (rationale: deep dive, "It teleports"). Drive real navigation; locate the target by **user-visible name**, not id. A deep-link case is allowed only as an explicitly-labelled **cold-load** test — arriving cold from a bookmark/refresh is a distinct scenario a warm click-through can't cover, and is where uninitialised-state defects surface (e.g. a null current-entity that never fires the detail fetch on cold load). A failed journey must fail loudly — never silently fall back to a deep link.
- Wait for elements before interacting: use `browser_wait_for` with reasonable timeouts.
- **Never use a hard-coded `sleep`** — wait for a specific condition instead.
- One user flow per test. Don't chain unrelated flows.
- Write any generated test scripts to the system temp directory (`$env:TEMP` on Windows, `/tmp` on Unix) — never into the skill directory or the user's project.
- Set test timeouts to prevent hangs: **30s per test, 5min per suite**.

### Verification Checklist

- [ ] All critical user flows have E2E coverage
- [ ] Tests use accessible selectors (not brittle CSS)
- [ ] Every predicate-activated thing proves it fired — guarded branches, route matchers, stubs, injections (marker asserted); matchers keyed on a path tail, not a base-URL shape; every negative assertion paired with a positive control
- [ ] No spec stubs the endpoint whose behavior its requirement asserts
- [ ] Every step is one a manual QA could perform by hand, and every assertion one they could observe
- [ ] The target is reached through real navigation and located by user-visible name — no deep link, no hard-coded id
- [ ] Any deep-link test is labelled as a deliberate cold-load case, not used as a shortcut
- [ ] No hard-coded sleeps
- [ ] Tests clean up after themselves (no state leakage)
- [ ] Tests pass on a clean environment

### Escalate When

- The dev server won't start → ask manager.
- A test is flaky (passes sometimes, fails others) → flag it and ask manager.
- Browser interaction is blocked by **CAPTCHA, auth wall, or CORS** → ask manager.

## Deep Dive

For engine-neutral rationale — anti-pattern illustrations, when to write E2E vs unit tests, selector philosophy, waiting strategies, and common pitfalls — see [references/playwright-deep-dive.md](references/playwright-deep-dive.md).
