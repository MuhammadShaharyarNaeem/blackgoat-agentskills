# Implementation Plan — orders

### Milestone 1 - Tenant-scoped order read and audited create [API] [vs:api]

- [x] **Task 1**: Look up an order and return its body to a caller in the same tenant. `[API]`
  - Requirements covered: FR-1
  - Acceptance Criteria: `lookupOrder` returns `200` with `id`, `total`, and `memo` for an
    order in the caller's own tenant.
  - Verification: `node --test` — "a caller reads an order in their own tenant" passes.
  - Dependencies: none

- [x] **Task 2**: Refuse a cross-tenant read. `[API]`
  - Requirements covered: FR-2
  - Acceptance Criteria: the tenant compared against `order.tenantId` is the one carried by
    the authenticated session; a body-supplied tenant name is ignored. A caller
    authenticated against another tenant receives `403` and no order body.
  - Verification: `node --test` — "a cross-tenant read is refused with 403 and no order
    body" and "the session decides the tenant even when the body names another" pass.
  - Dependencies: Task 1

- [x] **Task 3**: Create an order and return its identity. `[API]`
  - Requirements covered: FR-3
  - Acceptance Criteria: `createOrder` returns `201` with the new `id` and `total`.
  - Verification: `node --test` — "creating an order returns 201 and an integer id" passes.
  - Dependencies: none

- [x] **Task 4**: Audit every accepted create; fail loudly when the audit cannot be written. `[API]`
  - Requirements covered: FR-4
  - Acceptance Criteria: an accepted create appends exactly one audit record; a create
    whose audit record cannot be written returns `500` and persists nothing.
  - Verification: `node --test` — "creating an order appends an audit record" and "a create
    whose audit cannot be written returns 500 and persists nothing" pass.
  - Dependencies: Task 3

- [x] **Task 5**: Announce the listening address on startup, and reject prototype-chain
  keys in the store lookups. `[API]`
  - Requirements covered: NFR-1
  - Acceptance Criteria: the service logs `orders listening on <url>` on start (observed
    out-of-process); `sessionFor`/`orderById` resolve inherited keys (`__proto__`,
    `constructor`) to `null`, not to an `Object.prototype` member.
  - Verification: `node --test` — the two prototype-chain tests pass; the startup line is
    captured out-of-process in the runtime evidence.
  - Dependencies: none

### Checkpoint: Milestone 1

- Status: BUILT — handed to review.
- Exit criterion: `node --test` reports 9 tests, 9 pass, 0 fail; the `[vs:api]` wire
  claims (FR-1..FR-4, NFR-1) are captured out-of-process in
  `evidence/runtime/m1-orders.md`.
- RUNTIME PROBE: start: `npm start`; probe: `curl -sS -i -X POST http://localhost:5151/api/orders/lookup -H "Authorization: Bearer tok-acme" -H "Content-Type: application/json" -d "{\"orderId\":1}"`; expect-status: `200`; require-keys: `id, total`
