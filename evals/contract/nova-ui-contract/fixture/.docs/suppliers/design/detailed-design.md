# Detailed Design — suppliers

## Overview & Goals
Add a contacts panel to the supplier detail view (FR-1, FR-2, FR-3, NFR-1). The
supplier header view exists; this design covers the panel and its data flow.

## API Contracts
The client layer (`src/api/client.js`) is built and frozen for this milestone:

- `getSupplierContacts(supplierId)` → resolves to `[{ id, name, email, role }]`;
  rejects with `ApiError { status, message }` on transport or envelope failure.
- The envelope (`{ data, error }`) is unwrapped inside the client layer. UI code
  sees payloads and thrown `ApiError`s, never the envelope.

## Component Breakdown
- `src/views/SupplierDetail.vue` — existing. Mounts the panel below the header
  (the marked comment is the mount point).
- `src/components/ContactsPanel.vue` — **new, this milestone.** Owns the fetch
  lifecycle (loading / loaded / empty / error), renders the contact list, and
  exposes the retry action. Receives `supplierId` as a prop.
- **Layered import rule:** UI components and composables import from
  `../api/client.js` only. Direct `fetch`/XHR/axios in UI code is an
  architecture violation (NFR-1).

## Design Direction
Committed per `ui-design-patterns` before any UI code:

- **Tokens**: ink `#16211C`, paper `#FAF7F0`, accent `#C2542B` (rust), muted
  `#8A8071`; spacing scale `--space-1..6` = 0.25/0.5/1/1.5/2/2.5rem; type: system
  serif stack for headings (`Georgia, 'Times New Roman', serif`), system sans for
  body; radius 2px throughout (squared, ledger-like).
- **Signature element**: section headers carry a 2px ink rule with a small
  rust-colored index tab (see the supplier header) — the contacts panel reuses it.
- **States**: loading = three skeleton rows in muted at 40% opacity (no spinner);
  empty = a short invitation ("No contacts yet — add the first") set in the serif
  stack; error = ink-on-paper notice with a rust left border, the failure named,
  and a plain retry button.
- Generic-default check: no framework-default spinners, no unstyled `<table>`,
  no blank regions in any state.

## Cross-Cutting Concerns
Errors: surface `ApiError.message` in the error state; never render raw stack
traces. No auth concerns in this milestone (handled upstream).

## Divergence & Supersession Register
(none — this design contradicts no requirement)

## Risks & Open Questions
(none open — the API contract is frozen and the direction is committed)
