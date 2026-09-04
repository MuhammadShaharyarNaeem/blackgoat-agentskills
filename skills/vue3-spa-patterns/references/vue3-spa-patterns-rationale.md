# Vue 3 SPA Patterns — Rationale

Deep-dive "why" for contract rules stated tersely in `SKILL.md`. Read on demand; not needed to execute the contract.

## Composable scope: module-scope singletons vs per-caller state

State and effects that belong to *each caller* are created inside the composable body; state and effects that must exist **once per application** (a single watcher on global/persisted state, one media-query listener, one storage sync) are created at **module scope**, outside the exported function, and the function only returns handles to them.

A singleton effect registered inside the body silently multiplies with every call site — the leak has no error, no warning, and no failing test; it only shows up as duplicated side effects under load (e.g. a storage-sync watcher firing N times per write, once per component that called the composable). By the time it's visible in production telemetry, the composable has usually been copied into several more call sites, multiplying the effect further.

## Page-root `data-test` ID vs interactive-element IDs

Interactive-element IDs (buttons, inputs, links) prove that *a control exists* — they let an E2E selector find and act on it. They do not prove *which page* that control rendered on.

The page-root ID is what lets an E2E assertion prove which page actually rendered. Without it, a navigation test that only checks for a familiar-looking control (e.g. a "Submit" button that also exists on an error or fallback page) cannot distinguish the target page from a 404 or a fallback route — and will pass on both, silently certifying a broken navigation as working.
