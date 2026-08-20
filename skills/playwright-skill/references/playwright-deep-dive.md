# Playwright E2E — Deep Dive

Engine-neutral rationale behind the Worker Execution Contract in `SKILL.md`. These principles apply regardless of how you drive the browser; the MCP `browser_*` tools are the execution surface.

## Anti-Pattern Illustrations

The three anti-patterns the `SKILL.md` Rules forbid, spelled out. Both of the first two pass against a broken product and are *reported* as coverage, which makes them worse than absent coverage:

| Anti-pattern | The tell |
|---|---|
| **It mocks what it asserts** | a `route`/`fulfill` whose URL matches the endpoint the requirement is about. A QA cannot hand the app its own answer |
| **It teleports** | `goto('/<entity>-detail/<hard-coded-id>')`. A QA reaches a record through the menu, the list and a click — never by typing an id they were handed |

A third failure mode outranks both, because it hides them: **a step that silently does nothing still reports green.** A route matcher on a path the app never serves, a guarded branch whose predicate is false, a negative assertion in an environment that satisfies it anyway. Prove every predicate fired.

## When to Write E2E vs Unit Tests

The testing pyramid:

```
        /\
       /E2E\         <- Few, focused on critical paths
      /-----\
     /Integr.\       <- More, test component interactions
    /---------\
   /Unit Tests \     <- Many, fast, isolated
  /-------------\
```

**Write an E2E test for:**

- Critical user journeys (login, checkout, signup)
- Complex interactions (drag-and-drop, multi-step forms)
- Real API integration and authentication flows

**Do NOT write E2E for:**

- Unit-level logic (use unit tests)
- API contracts (use integration tests)
- Exhaustive edge cases (too slow — cover these lower in the pyramid)
- Internal implementation details

Test user-visible behavior (click, type, see), not implementation internals. Keep each test independent and deterministic.

## Selector Philosophy

Prefer selectors that mirror how a user or assistive technology perceives the page. In order of preference:

1. **Role** — the element's ARIA role plus its accessible name (e.g. a button named "Submit").
2. **Label** — form fields addressed by their visible label.
3. **Text** — unique visible text content.
4. **Placeholder** — when no label is available.

Avoid CSS classes, IDs, and `nth-child`/XPath chains — they encode DOM structure and styling, both of which change often, producing brittle tests. If a component is genuinely unaddressable by role/label/text, that is usually a signal the UI needs an accessible name, not a signal to reach for a CSS selector.

## Waiting Strategies

Never wait a fixed number of seconds — a hard sleep is either too short (flaky) or too long (slow), and it is never correct. Instead wait for the specific condition you actually care about:

- Navigation completed / URL changed
- A specific element became visible, enabled, or detached
- The network went idle or a specific response arrived
- A DOM assertion became true

With the MCP surface, express these through `browser_wait_for` before asserting. Auto-waiting on a concrete condition is what makes a test both fast and reliable.

## Common Pitfalls

- **Flaky tests** — caused by hard sleeps and races; wait on conditions instead.
- **Slow tests** — mock external APIs where possible; don't push edge cases into E2E.
- **Over-testing** — E2E is for critical paths, not every branch.
- **Coupled tests** — each test must run in isolation; no ordering dependencies.
- **Poor selectors** — CSS classes and structural selectors break on refactors.
- **No cleanup** — leaked state from one test contaminates the next.
- **Testing implementation** — assert on what the user sees, not internal state.
