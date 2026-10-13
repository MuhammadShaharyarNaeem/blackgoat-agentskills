# Requirements — slugkit

## Fit Check
- Design decisions to make: no — one pure function in an existing module, no new dependency, no API, no UI.
- Size: one milestone, one builder, one session.

## Functional Requirements
- **FR-1 (Must)**: `slugify(text)` in `src/strings.js` turns a title into a URL slug: lower-case,
  every run of characters outside `a-z` and `0-9` collapsed to a single `-`, no leading or
  trailing `-`. `slugify('  Hello, World! 2026  ')` returns `hello-world-2026`; `slugify('')`
  returns `''`; a non-string argument throws `TypeError`, matching `capitalize`.

## Non-Functional Requirements
- **NFR-1 (Must)**: zero runtime dependencies — Node built-ins only; the existing `capitalize`
  export and its tests are unchanged.
