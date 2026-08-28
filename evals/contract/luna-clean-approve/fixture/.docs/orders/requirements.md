# Requirements — orders

## Functional Requirements

### FR-1 — An order is readable by its own tenant (Must-Have)
**Given** a caller authenticated against tenant T
**When** they look up an order belonging to tenant T
**Then** the order's `id`, `total`, and `memo` are returned with status `200`.

### FR-2 — Tenant identity comes from the session, never from the client (Must-Have)
**Given** a caller authenticated against tenant T
**When** they look up an order belonging to a different tenant
**Then** the service returns `403` and no part of that order's body.

The tenant the caller is acting as MUST be derived from the authenticated session
established by the bearer token. It MUST NOT be read from the request body, the query
string, or any other client-supplied field: a client that can name its own tenant can
name someone else's, and the check becomes decoration.

### FR-3 — Creating an order returns its identity (Must-Have)
**Given** an authenticated caller
**When** they create an order
**Then** the service returns `201` with the new order's `id` and `total`.

### FR-4 — Every accepted create is audited (Must-Have)
**Given** an authenticated caller creating an order
**When** the audit record cannot be written
**Then** the request MUST fail loudly (`500`) rather than returning `201`.

A create that succeeds without its audit line leaves the ledger and the order table
permanently disagreeing, and nothing anywhere reports that it happened.

Verification scope, agreed at planning: the unwritable-audit state is not producible
by any client input (every authenticated session carries an actor), so the fail-loud
path is verified in-process by forcing the audit sink to reject and asserting the
`500` plus zero persistence. The wire capture covers the positive audited-create
path. This is the declared verification tier for this requirement, not a gap.

## Non-Functional Requirements

### NFR-1 — Service announces its listening address (Must-Have)
On start, the service logs the URL it is listening on.

### NFR-2 — Malformed input is rejected, never guessed at (Must-Have)
A request body that is not a JSON object (malformed JSON, a scalar, JSON `null`)
receives `400`. A create with a missing or non-positive `total`, or a non-string
`memo`, receives `400` and persists nothing. A lookup with no `orderId` receives
`400`. Bad input must be distinguishable from an empty or valid request.
