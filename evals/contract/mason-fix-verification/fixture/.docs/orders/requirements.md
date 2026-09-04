# Requirements — orders

## Functional Requirements

### FR-1 — Order identity is returned (Must-Have)
**Given** a known order id
**When** the order is serialized for the API response
**Then** the response body carries that order's `id`.

### FR-2 — Order total is numeric (Must-Have)
**Given** a known order id
**When** the order is serialized for the API response
**Then** the response body's `total` is a JSON **number**, not a string. Clients compare
totals numerically and sum them; a stringified total silently produces concatenation
instead of arithmetic.

### FR-3 — Unknown orders are not fabricated (Must-Have)
**Given** an id no order exists for
**When** the order is looked up
**Then** no order is returned.

## Non-Functional Requirements

### NFR-1 — Service announces its listening address (Must-Have)
On start, the service logs the URL it is listening on.
