# Vue 3 Refactor Playbook — Sequential Zero-Regression Pass

The execution contract for a **refactor delegation** on Vue 3 + TypeScript files (`.vue` components, `.ts` composables, Options or Composition API). These phases retrofit the authoring rules of `vue3-spa-patterns/SKILL.md` (Data Flow & Computation, Lifecycle & Reactivity Hygiene) onto **legacy code written before that contract** — new code follows the spine directly and never needs this pass. "Sequential" means: work through **every phase below** on the **entire** target file (or every file in the brief). Skipping is allowed only when documented under **Skipped** with a concrete reason (unclear types, needs sibling `.vue` changes, business-logic risk) — never because the first pass "felt enough."

## Safety Constraints (override everything below)

- **Zero regression**: same inputs produce the same outputs. Preserve exact behavior, filter precedence, execution order, and error handling.
- No public API, signature, or data-contract changes. No renames unless necessary for clarity — and then update every reference.
- Do not refactor business logic — structure and readability only.
- If unsure about a change, do NOT make it: document the hunk under **Skipped** with the risk, and continue with the later phases (uncertainty about one hunk never skips a phase).

## Phase 0 — Scope & Inventory (required)

List the targets and their kind (`.vue` / composable / component). Skim the whole file and write a short inventory: repeated loops? repeated store/entity queries? watchers? `debounce`/`setTimeout`/`addEventListener`? `document.getElementById`? redundant null checks?
**Done when** the inventory bullet list exists.

## Phase 1 — Repeated Loops / Filtering

Same array repeatedly filtered/iterated (especially inside an outer loop → N×M scans) → one pass per outer iteration: a single `filter()` predicate with early returns, or one `for` loop that builds results. Precompute repeated values once (lowercased query strings, `Set`/`Map` indexes, parsed JSON) when safe. Preserve filter precedence (e.g. "excluded overrides included") and `null`/`""`/mixed-type handling exactly.
**Done when** every repeated-scan hotspot is refactored or Skipped with reason.

## Phase 2 — Repeated Queries / Indexes

Same store/entity query (Pinia getter chains, Vuex-ORM `Entity.query()`/`.all()`/`.where()`) or the same transform repeated in loops/computed/watchers → query **once per dataset per scope** and derive from that snapshot. Precompute indexes as computed selectors — `byId: ComputedRef<Map<Id, Entity>>`, `grouped: ComputedRef<Map<Key, Entity[]>>` — and replace hot-path `.find()` in loops with `map.get(id)`. Extract `toIdMap`/`groupBy`/`indexBy` helpers at the second occurrence. Indexes must stay reactive to store changes — no stale manual caches without invalidation. Type-safe and null-safe; no new `any`.
**Done when** repeated reads and duplicate transforms are deduplicated or Skipped (e.g. one-off cold path).

## Phase 3 — Watchers Dedupe

Merge watchers **only** when they call the same side-effect with the same gating and the same options. Extract a `run()` wrapper for the shared side-effect. `watch([srcA, srcB], ...)` is valid only if all originals triggered on *any* change (not value-specific) with identical `deep`/`immediate`/`flush`. Keep separate any watcher with value-specific conditions (`if (newVal)`, transitions), different options, or `oldVal` dependence. Verify each original trigger still causes exactly one `run()` and no new trigger paths exist.

## Phase 4 — Unnecessary Reactivity

Drop `ref`/`computed` wrappers only when the value is constant or derived purely from non-reactive inputs AND nothing reactive consumes it (template, watcher, reactive side-effect). Anything depending on props/refs/store/route, or that is watched/rendered, stays reactive.

## Phase 5 — Listeners & Subscriptions Cleanup

Every add/join/subscribe gets a matching remove/leave/unsubscribe on the **same target with the same function reference**: DOM/global listeners (`document`/`window`/element, image `load`/`error`, click-outside patterns), real-time hub groups (e.g. SignalR `joinSignalrGroup` ↔ `leaveSignalrGroup`), manual `watch()` stop handles, store subscriptions, custom emitters. Stable handler references — never an anonymous inline handler that can't be removed. Clean in `onUnmounted`/`onBeforeUnmount`, **and also in `onDeactivated`** when keep-alive can hide the view. No duplicate registrations across mount/activate paths. Verification bar: after navigating away, the component receives no events, hub messages, or DOM callbacks.

## Phase 6 — Debounce / Throttle / Timers

Every lodash `debounce`/`throttle` instance gets `.cancel()` on teardown (cancel the *same* instance — don't recreate per call). Store `setTimeout`/`setInterval`/`requestAnimationFrame` ids and clear them in `onUnmounted` (plus `onDeactivated` under keep-alive). No deferred callback may call services, emit, touch DOM, or update refs after unmount; only when cancellation is impossible, guard with an `isUnmounted`-style flag as fallback.

## Phase 7 — DOM Access via Template Refs

For component-owned DOM, prefer a template `ref` on the smallest owning element + subtree queries (`el.querySelector*`) over `document.getElementById`/`document.querySelector`. Always guard `ref.value` for null; measure after `nextTick`. Exceptions stay as-is: genuinely global concerns (click-outside on `document`, focus trap, scroll lock, third-party scripts, teleported nodes with no ref). If the fix needs a `.vue` template change outside scope → **Skipped: "requires sibling `.vue` ref edit — needs approval."**

## Phase 8 — Redundant Null / Empty Checks

Collapse repeated `null`/`undefined`/`""` checks into one intentional check **only where the type and business rules allow it**: `value != null` covers null+undefined; a bare truthy check is valid only when `0`, `false`, and `""` are impossible or already invalid. Never truthy-check an ID typed `string | number` where `0` is valid.

## Phase 9 — Global Constraints Recheck

Re-read the Safety Constraints and confirm every one holds across the full diff.

## Required Output Format

1. **Phases applied**: Phase 0–9 checklist, one line each — Done / Partial / Skipped (a phase with nothing applicable is **Skipped: N/A**, so the full walk is visible).
2. **What changed**: bullets grouped by phase.
3. **Skipped**: one bullet per item with the concrete reason (never "out of time").
4. **Edge cases / regression risks** to retest.
5. **Commands run** (lint/typecheck/tests) with results.

## Conflict Resolution

| Situation | Resolution |
|-----------|------------|
| "Small refactor" phrasing in the brief | Full sequential pass on the named target(s); minimal *unnecessary* churn — no drive-by renames or unrelated files. |
| "If unsure, do NOT modify" | Skip that **hunk** with a documented reason — never skip whole later phases. |
| Brief names a single phase | Run only that phase, full-file. |
