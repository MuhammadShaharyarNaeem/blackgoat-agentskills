# Requirements: Supplier Contacts

Mini-feature for an existing ERP (Vue 3 SPA frontend + .NET backend API). A supplier record gains a "Contacts" capability: backend endpoints and a UI panel on the supplier detail view.

## Must Have

- [ ] **FR-1** The API exposes `GET /suppliers/{id}/contacts` returning the supplier's contacts as a paginated list (page, pageSize, total). Given a supplier with 25 contacts and pageSize 10, When page 3 is requested, Then 5 contacts and total 25 are returned.
- [ ] **FR-2** The API exposes `POST /suppliers/{id}/contacts` creating a contact with name (required, max 120 chars), email (validated format), and phone (optional). Given a payload with an invalid email, When posted, Then the API returns the standard validation error envelope and no contact is persisted.
- [ ] **FR-3** The supplier detail view shows a Contacts table with pagination controls, a designed empty state, and a loading state. Given a supplier with zero contacts, When the panel loads, Then the designed empty state (invitation to add a contact) is rendered — never a bare empty table.
- [ ] **FR-4** The Contacts panel provides an autocomplete search over contact names: debounced input, keyboard navigation (up/down/Enter/Escape), match highlighting, and a designed no-results state. Given the query "zz" matching nothing, When typed, Then the no-results state names the query.

## Should Have

- [ ] **FR-5** The Contacts table offers CSV export of the currently filtered contact list.

## Non-Functional Requirements

- **NFR-1** (Must) Contact list responses complete in under 300ms at p95 against the seeded dev database.
- **NFR-2** (Must) Every async UI surface in the Contacts panel has designed loading, empty, and error states (no defaulted blanks).
