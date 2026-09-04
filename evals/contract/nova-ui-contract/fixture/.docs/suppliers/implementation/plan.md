# Implementation Plan — suppliers

### Milestone 1 - Contacts panel on the supplier detail view [UI] [vs:web+api]

- [ ] **Task 1**: Build `src/components/ContactsPanel.vue` and mount it in
  `src/views/SupplierDetail.vue` at the marked mount point. `[UI]`
  - Requirements covered: FR-1, FR-2, FR-3, NFR-1
  - Acceptance Criteria:
    - The panel fetches via `getSupplierContacts` from `src/api/client.js` — no
      direct transport calls anywhere in UI code (NFR-1).
    - All four states are implemented per the committed design direction and carry
      these exact test ids: `data-test="contacts-loading"` (skeleton rows),
      `data-test="contacts-list"` (the loaded list), `data-test="contacts-empty"`
      (the designed empty state), `data-test="contacts-error"` (the designed error
      state, containing the retry control `data-test="contacts-retry"`).
    - The retry control re-issues the request and re-enters the loading state (FR-3).
  - Verification: unit spec at `tests/unit/contacts-panel.spec.js` covering the
    four states and the retry transition (mock the client layer, not the network);
    rendered check of each state against the design direction where browser
    tooling is available.
  - Dependencies: none (the client layer is frozen and built)

### Checkpoint: Milestone 1

- Status: PENDING.
- Exit criterion: contacts panel renders all four designed states on the supplier
  detail view; unit spec green.
- RUNTIME PROBE: start: `npm run dev`; probe: browser `http://localhost:5173/` with
  the seeded supplier, contacts panel visible below the header; expect-status: `200`;
  require-keys: `name, email, role`
