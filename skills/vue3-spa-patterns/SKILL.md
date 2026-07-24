---
name: vue3-spa-patterns
description: "Provides the Vue 3 SPA execution contract: Composition API authoring, Pinia-only state mutation, composable extraction, a single Axios instance with Response Pattern interceptors, mandatory data-test IDs, lazy routes, and reactivity performance rules. Use if the project uses Vue 3. Squad-internal execution contract loaded by agents via their Methodology Dependencies table."
---

# Vue 3 SPA Patterns

Frontend rigor equal to backend rigor. Components render; stores mutate; one Axios instance talks to the API; every interactive element is testable by ID.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### Authoring & Typing

- Composition API with `<script setup lang="ts">` is the default authoring style for every new component. Do not use the Options API in new code.
- Type all component boundaries: `defineProps<T>()` and `defineEmits<T>()` with explicit interfaces. No untyped or runtime-only prop declarations in new components.

### State Boundary (Architect's state-mutation boundary)

- Shared state is mutated ONLY inside Pinia store actions. Components never write to store state directly — no `store.someField = x`, no `$patch` from a component. Components read state (via getters/`storeToRefs`) and call actions.
- Local, component-private state stays in `ref`/`reactive` inside the component. If two or more components need it, it belongs in a store.

### Reuse — Composables

- Extract shared logic into composables (`useXxx`) applying the Rule of Three: extract on the third occurrence, not speculatively on the first.
- A composable owns its own state and returns a narrow, typed surface. It never reaches into component internals.

### HTTP Layer

- Exactly ONE shared Axios instance for the app. No ad-hoc `axios.create()` or raw `fetch` calls in components or stores.
- Generic response interceptor unwraps the backend's standardized Response Pattern so callers receive typed payloads, never envelope plumbing.
- Request interceptor centralizes auth headers. A 401 triggers the silent refresh-token flow with request queueing — concurrent failures wait on one refresh, then replay.

### Testability

- Every interactive DOM element (buttons, inputs, links, selects, toggles) carries a `data-test` ID so Playwright E2E selectors survive styling and layout changes. This is mandatory, not optional polish.

### Routing & Performance

- Route-level lazy loading (`() => import(...)`) for all non-critical views; only the entry/critical route is eagerly loaded.
- Prefer `computed` over `watch` for derived state; use `watch` only for genuine side effects.
- Use `shallowRef` for large structures where deep reactivity is not needed.
- Add `v-memo` only with profiling evidence showing a real render hotspot — never speculatively.
- Query a dataset once per scope and derive from it: repeated store/entity queries or `.find()` in loops become computed `Map` indexes (`byId`, `groupBy`) with lookups.

### Lifecycle & Reactivity Hygiene

- Every add/join/subscribe (DOM/global listeners, real-time hub groups like SignalR, manual `watch()` handles, store subscriptions) is paired with its remove/leave/unsubscribe on the same target with the same stable function reference — in `onUnmounted`, and ALSO in `onDeactivated` when keep-alive can hide the view.
- Every lodash `debounce`/`throttle` instance is `.cancel()`ed and every timer (`setTimeout`/`setInterval`/`requestAnimationFrame`) cleared on teardown; no deferred callback may touch services, DOM, or refs after unmount.
- Component-owned DOM is reached via template `ref` + subtree queries, never `document.getElementById`/`querySelector` (globals are legitimate only for click-outside, focus traps, teleported nodes).
- Merge watchers only when side-effect, gating, AND options are identical; keep value-specific or `oldVal`-dependent watchers separate.

### Refactor Mode

When the delegation is a **refactor pass** over existing Vue files, follow the sequential zero-regression contract in [references/vue3-refactor-playbook.md](references/vue3-refactor-playbook.md): a phased walk (inventory → loops → query indexes → watchers → reactivity → listeners → timers → DOM refs → null checks) with documented Skipped items and a mandatory phase-checklist report.

### Verification Checklist

Before marking work complete:

- [ ] All new components use `<script setup>` with typed `defineProps`/`defineEmits`
- [ ] No component mutates shared state directly — all writes go through Pinia actions
- [ ] All HTTP traffic flows through the single shared Axios instance and its interceptors
- [ ] Every interactive element added or touched carries a `data-test` ID
- [ ] Non-critical routes are lazy-loaded
- [ ] No watcher exists where a `computed` would do; no `v-memo` without profiling evidence
- [ ] Every listener/subscription/hub-join you added or touched has a matching teardown (`onUnmounted`, plus `onDeactivated` under keep-alive); every debounce/throttle/timer is cancelled on teardown
- [ ] No `document.getElementById`/`querySelector` for component-owned DOM — template refs used instead

### Escalate When

- The backend Response Pattern shape is undocumented or deviates from the standard envelope → report to the Orchestrator.
- A requirement forces direct state mutation outside a store action (e.g., third-party library writes) → report to the Orchestrator before violating the boundary.
- The refresh-token endpoint or auth contract is missing/ambiguous → report to the Orchestrator; do not invent an auth flow.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Vue 3 playbook](references/vue3-playbook.md) — GOOD/BAD code patterns: store action vs direct mutation, composable extraction, the full Axios interceptor setup with refresh-token queueing, `data-test` usage, lazy routes, and the computed-vs-watch anti-pattern.
- [Vue 3 refactor playbook](references/vue3-refactor-playbook.md) — the sequential zero-regression refactor pass: per-phase rules (loops, query indexes, watcher dedupe, reactivity removal, listener/timer cleanup, DOM refs, null checks), safety constraints, and the required Skipped/phase-checklist report format.
