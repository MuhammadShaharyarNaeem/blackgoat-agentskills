# Requirements — suppliers

## Functional Requirements

### FR-1 — The supplier detail view lists the supplier's contacts (Must-Have)
**Given** a user viewing a supplier's detail page
**When** the supplier's contacts have loaded
**Then** each contact's `name`, `email`, and `role` are visible in a contacts panel.

### FR-2 — Every async state of the contacts panel is designed (Must-Have)
**Given** the contacts panel
**When** the request is in flight, returns zero contacts, or fails
**Then** the panel shows a designed loading state, a designed empty state (inviting the
next action), or a designed error state (naming what failed and offering retry) —
never a blank region, a spinner-only default, or a raw error string.

### FR-3 — A failed load can be retried in place (Must-Have)
**Given** the contacts panel in its error state
**When** the user activates the retry action
**Then** the request is re-issued and the panel re-enters its loading state.

## Non-Functional Requirements

### NFR-1 — The UI consumes the API client layer only (Must-Have)
All data access from UI code goes through `src/api/client.js`. No component or
composable issues its own transport calls.
