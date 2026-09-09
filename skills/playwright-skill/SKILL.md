---
name: playwright-skill
description: MCP-based end-to-end browser testing. Drive real user flows through the Playwright MCP tool surface (browser_navigate, browser_click, browser_fill_form, browser_snapshot, ...) to verify critical paths. Use when a task needs a real browser to confirm behavior, not unit tests. Specs reproduce what a manual QA does — real UI, real backend, real navigation — never stubbing the asserted endpoint or deep-linking past the journey. Squad-internal execution contract loaded by agents via their Methodology Dependencies table.
risk: unknown
source: community
date_added: "2026-02-27"
---

# Playwright E2E Testing (MCP)

Drive real user flows through a browser using the Playwright **MCP tool surface** and verify that critical paths work. E2E tests are slow and expensive — reach for them only when unit/integration tests cannot cover the behavior.

## Worker Execution Contract

### Core Principle

**A Playwright spec is an automated pass of what a manual QA would do — no more exotic than that, and no less honest.** The entire value of a browser test is that it exercises the system the way a person does: through the real UI, against the real backend, starting where a user actually starts. Every deviation buys speed by deleting exactly the coverage the test existed to provide.

The governing test, applied to every step you write: **could a QA on a fresh login perform this step by hand, and would they observe what it asserts?** If not, that step is not evidence about the product — it is evidence about your fixture.

Five specs are therefore never authored. All five pass against a broken product, and all five are *reported* as coverage, which makes them worse than absent coverage:

| Anti-pattern | The tell |
|---|---|
| **It mocks what it asserts** | a `route`/`fulfill` whose URL matches the endpoint the requirement is about. A QA cannot hand the app its own answer |
| **It teleports** | `goto('/<entity>-detail/<hard-coded-id>')`. A QA reaches a record through the menu, the list and a click — never by typing an id they were handed |
| **It re-implements what it asserts** | the function/class asserted is defined in the spec or in `page.evaluate`, not imported from `src/`. A QA cannot check the app against a copy of itself (`test_no_production_import`/`test_inline_reimplementation`) |
| **It tests the source text** | `readFileSync` on a `.ts`/`.js` file, sliced with a regex or run through `new Function()`. A QA never reads code — they use the app (`test_source_eval`) |
| **It renders its own HTML** | `page.setContent(...)` in place of `page.goto(...)`. A QA cannot open a page only your test authored (`test_synthetic_dom`) |

This principle is `test-driven-development/SKILL.md`'s (§ Rules) — not restated here.

A sixth failure mode outranks all five, because it hides them: **a step that silently does nothing still reports green.** A route matcher on a path the app never serves, a guarded branch whose predicate is false, a negative assertion in an environment that satisfies it anyway. Prove every predicate fired.

E2E tests are slow and expensive — write them only for critical paths that unit/integration tests cannot cover. One user flow per test; don't chain unrelated flows.

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
- **Anything activated by a predicate must prove it fired — guarded branches and network interception alike.** A conditional step, a route matcher, a stub, an injection: if a predicate decides whether it runs, a wrong predicate makes it a silent no-op, and a green run can never falsify what never ran. Three obligations: **(1)** emit a marker/log when the path is taken and assert the marker, so a mis-scoped predicate fails loudly instead of passing by omission; **(2)** key matchers on the **distinctive tail** of a path, never on a base-URL shape — a prefix or origin the environment can be repointed away from stops matching with no error the moment the app is pointed elsewhere, and the spec still reports itself as mock-driven; **(3)** pair every negative assertion with a positive control — an assertion that something is hidden or absent, in an environment that satisfies it anyway, is vacuous whether or not the setup worked. Verify predicates against the paths the app **actually serves**, not the paths you expect.
- **Never stub, mock, or intercept the endpoint whose behavior the requirement asserts.** A spec that installs a route handler returning the success value and then asserts the success state is testing its own fixture: it passes identically against a broken product, and its green is worse than absent coverage because it is *reported* as coverage. Mock only collaborators outside the claim, and name which ones and why in the spec. Any flow whose requirement is "this call succeeds/fails" is driven against the real endpoint, or recorded BLOCKED.
- **Reach the feature the way a user reaches it — never deep-link past the journey.** A spec that jumps straight to `/<entity>-detail/<hard-coded-id>` skips the menu, list, search and row-open path, so it cannot fail when any of those break, and it silently couples the suite to an id that exists in one environment. Drive the real navigation and locate the target by **user-visible name**, not id. Keep a deep-link case only as an explicitly-labelled **cold-load** test: arriving cold from a bookmark or refresh is a distinct real scenario a warm click-through cannot cover, and it is where uninitialised-state defects surface (a null current-entity on cold load that never fires the detail fetch). A failed journey must fail loudly — never silently fall back to a deep link.
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
- [ ] No spec fails `check_test_authenticity.py` — re-implemented logic, source-text evaluation, or synthetic DOM (`test-driven-development/SKILL.md` § Rules)
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

For engine-neutral rationale — when to write E2E vs unit tests, selector philosophy, waiting strategies, and common pitfalls — see [references/playwright-deep-dive.md](references/playwright-deep-dive.md).
