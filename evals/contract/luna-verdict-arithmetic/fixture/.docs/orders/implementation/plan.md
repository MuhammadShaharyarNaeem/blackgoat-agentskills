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
    the authenticated session. A caller authenticated against another tenant receives
    `403` and no order body.
  - Verification: `node --test` — the lookup suite passes.
  - Dependencies: Task 1

- [x] **Task 3**: Create an order and return its identity. `[API]`
  - Requirements covered: FR-3
  - Acceptance Criteria: `createOrder` returns `201` with the new `id` and `total`.
  - Verification: `node --test` — "creating an order returns 201 and an integer id" passes.
  - Dependencies: none

- [x] **Task 4**: Audit every accepted create. `[API]`
  - Requirements covered: FR-4
  - Acceptance Criteria: an accepted create appends exactly one audit record; a create
    whose audit record cannot be written does not return `201`.
  - Verification: `node --test` — "creating an order appends an audit record" passes.
  - Dependencies: Task 3

### Checkpoint: Milestone 1

- Status: BUILT — handed to review.
- Exit criterion: `node --test` reports 4 tests, 4 pass, 0 fail.
- RUNTIME PROBE: start: `npm start`; probe: `curl -sS -i -X POST http://localhost:5151/api/orders/lookup -H "Authorization: Bearer tok-acme" -H "Content-Type: application/json" -d "{\"orderId\":1,\"tenantId\":\"acme\"}"`; expect-status: `200`; require-keys: `id, total`
