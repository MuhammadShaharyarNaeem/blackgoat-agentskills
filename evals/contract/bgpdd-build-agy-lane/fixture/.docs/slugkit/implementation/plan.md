# Implementation Plan — slugkit

## Reference Documents
- Requirements: `.docs/slugkit/requirements.md`
- Architecture reference: none (lite epic; `artifacts.design` is `null`) — follow the existing
  style of `src/strings.js`.

### Milestone 1 - slugify helper [API] [vs:none]

- [ ] **Task 1**: Add `slugify(text)` to `src/strings.js` and export it beside `capitalize`. `[API]`
  - Requirements covered: FR-1, NFR-1
  - Acceptance Criteria: `slugify('  Hello, World! 2026  ')` returns `hello-world-2026`;
    `slugify('')` returns `''`; `slugify(42)` throws `TypeError`; `capitalize` and
    `tests/strings.test.js` are unchanged.
  - Verification: `node --test` — new tests for the three cases above pass, and the existing
    three `capitalize` tests still pass.
  - Dependencies: none

### Checkpoint: Milestone 1

- All tests pass: `node --test` green.
- RUNTIME EXIT CRITERION — run `node scripts/demo-slug.js`; expect `hello-world-2026`
- RUNTIME PROBE: justification: slugify is a pure library function with no network, UI, device or async surface; nothing a client can reach exists, and the exit criterion above runs it in a separate node process.
- Review with human before proceeding.
