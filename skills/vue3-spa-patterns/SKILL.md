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

### Component Abstraction & Shared Packages

- **Multi-Frontend Shared Component Package Rule**: In projects with multiple frontends (e.g. monorepos or multi-app workspaces), primitive UI controls (Buttons, Inputs, Dropdowns/Selects, Autocompletes, Date/Time Pickers) MUST be implemented in a shared UI component package or folder (e.g. `packages/ui` or `packages/shared-components`) to guarantee 100% visual, behavioral, and accessibility consistency across all frontends.
- **Component Abstraction & Custom UI Controls**: Direct usage of un-wrapped raw native HTML input elements or un-wrapped third-party UI controls across application features is prohibited. All primitive controls MUST be wrapped/abstracted inside generic shared components within the shared component library.

### State Boundary (Architect's state-mutation boundary)

- Shared state is mutated ONLY inside Pinia store actions. Components never write to store state directly — no `store.someField = x`, no `$patch` from a component. Components read state (via getters/`storeToRefs`) and call actions.
- **Template `v-model` Store Prohibition**: Direct `v-model` binding in templates to Pinia store state properties (e.g., `v-model="store.someField"`) is strictly prohibited as it performs implicit state mutation outside store actions. Use explicit `:model-value` and `@update:model-value` event handlers, store actions, or local computed properties with getter/setter wrappers that call store actions.
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

- **Routing Entry Eager Loading Rule**: Only the main root entry view (`/`) MAY be eagerly loaded; all other route components MUST be lazy-loaded using dynamic imports (`() => import(...)`).
- Prefer `computed` over `watch` for derived state; use `watch` only for genuine side effects.
- Use `shallowRef` for large structures where deep reactivity is not needed.
- Add `v-memo` only with profiling evidence showing a real render hotspot — never speculatively.

### Verification Checklist

Before marking work complete:

- [ ] All new components use `<script setup>` with typed `defineProps`/`defineEmits`
- [ ] In multi-frontend projects, all primitive UI controls reside in a shared UI package (`packages/ui`)
- [ ] No component mutates shared state directly — all writes go through Pinia actions; no direct `v-model="store.someField"` bindings in templates
- [ ] All HTTP traffic flows through the single shared Axios instance and its interceptors
- [ ] Every interactive element added or touched carries a `data-test` ID
- [ ] Only main entry route (`/`) is eagerly loaded; all other non-critical routes are lazy-loaded (`() => import(...)`)
- [ ] No watcher exists where a `computed` would do; no `v-memo` without profiling evidence

### Escalate When

- The backend Response Pattern shape is undocumented or deviates from the standard envelope → report to the Orchestrator.
- A requirement forces direct state mutation outside a store action (e.g., third-party library writes) → report to the Orchestrator before violating the boundary.
- The refresh-token endpoint or auth contract is missing/ambiguous → report to the Orchestrator; do not invent an auth flow.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Vue 3 playbook](references/vue3-playbook.md) — GOOD/BAD code patterns: store action vs direct mutation, composable extraction, the full Axios interceptor setup with refresh-token queueing, `data-test` usage, lazy routes, and the computed-vs-watch anti-pattern.
