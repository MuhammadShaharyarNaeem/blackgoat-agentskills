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

### Data Flow & Computation

These rules apply to every line you author AND any existing line you modify — greenfield or brownfield. Code written under them never needs the retrofit pass.

- **Query once per dataset per scope**: never repeat the same store/entity query (Pinia getter chains, Vuex-ORM `Entity.query()`/`.all()`/`.where()`) or the same transform in loops, computed, or watchers — take one snapshot and derive from it.
- **Indexes over scans**: a `.find()`/`.filter()` inside a loop is a design smell at authoring time — build a computed `Map` index (`byId: ComputedRef<Map<Id, Entity>>`, `grouped: ComputedRef<Map<Key, Entity[]>>`) and use `map.get(id)`. Indexes stay reactive to store changes; no manual caches without invalidation.
- **Single-pass iteration**: never filter/iterate the same array repeatedly (especially inside an outer loop — N×M scans). One `filter()` predicate with early returns, or one `for` loop that builds results. Precompute repeated values (lowercased query strings, `Set`s, parsed JSON) once.
- **Pure data helpers at the second occurrence**: extract `toIdMap`/`groupBy`/`indexBy` when the same transform appears twice — stateless helpers are cheaper than composables, so they extract earlier than the Rule of Three that governs composables.
- **Minimal reactivity**: wrap a value in `ref`/`computed` only when something reactive consumes it (template, watcher, reactive side-effect). Constants and pure derivations of non-reactive inputs are plain `const`.
- **One intentional presence check**: match the check to the type — `value != null` covers null+undefined; a bare truthy check only when `0`, `false`, and `""` are impossible or already invalid; never truthy-check an ID typed `string | number`. Don't stack redundant null/empty checks.

### Lifecycle & Reactivity Hygiene

- Every add/join/subscribe (DOM/global listeners, real-time hub groups like SignalR, manual `watch()` handles, store subscriptions) is paired with its remove/leave/unsubscribe on the same target with the same stable function reference — in `onUnmounted`, and ALSO in `onDeactivated` when keep-alive can hide the view. Never register with an anonymous inline handler that can't be removed; mount/activate paths must not register twice without prior cleanup.
- Every lodash `debounce`/`throttle` instance is `.cancel()`ed and every timer (`setTimeout`/`setInterval`/`requestAnimationFrame`) cleared on teardown; no deferred callback may touch services, DOM, or refs after unmount.
- Component-owned DOM is reached via template `ref` + subtree queries, never `document.getElementById`/`querySelector` (globals are legitimate only for click-outside, focus traps, teleported nodes).
- One side effect, one watcher: never write two watchers invoking the same side effect — share a single `run()` wrapper. Merge watchers only when side-effect, gating, AND options are identical; keep value-specific or `oldVal`-dependent watchers separate.

### Refactor Mode (legacy code only)

The rules above make new code retrofit-free. For **existing** code written before this contract, a refactor delegation follows the sequential zero-regression procedure in [references/vue3-refactor-playbook.md](references/vue3-refactor-playbook.md) — the phased walk that retrofits these same rules with documented Skipped items and a mandatory phase-checklist report.

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
- [ ] No repeated queries/scans: datasets queried once per scope, `Map` indexes instead of `.find()` in loops, no same-array multi-pass filtering
- [ ] No `ref`/`computed` wrapping a value nothing reactive consumes; no stacked redundant null/empty checks

### Escalate When

- The backend Response Pattern shape is undocumented or deviates from the standard envelope → report to the Orchestrator.
- A requirement forces direct state mutation outside a store action (e.g., third-party library writes) → report to the Orchestrator before violating the boundary.
- The refresh-token endpoint or auth contract is missing/ambiguous → report to the Orchestrator; do not invent an auth flow.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Vue 3 playbook](references/vue3-playbook.md) — GOOD/BAD code patterns: store action vs direct mutation, composable extraction, the full Axios interceptor setup with refresh-token queueing, `data-test` usage, lazy routes, and the computed-vs-watch anti-pattern.
- [Vue 3 refactor playbook](references/vue3-refactor-playbook.md) — the sequential zero-regression refactor pass: per-phase rules (loops, query indexes, watcher dedupe, reactivity removal, listener/timer cleanup, DOM refs, null checks), safety constraints, and the required Skipped/phase-checklist report format.
