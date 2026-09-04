# Implementation Plan — orders

### Milestone 1 - Order response serialization [API] [vs:api]

- [ ] **Task 1**: Serialize an order's identity into the response body. `[API]`
  - Requirements covered: FR-1
  - Acceptance Criteria: `buildBody` returns the order's `id` unchanged.
  - Verification: `node --test` — "returns id for a known order" passes.
  - Dependencies: none

- [ ] **Task 2**: Serialize an order's total as a JSON number. `[API]`
  - Requirements covered: FR-2
  - Acceptance Criteria: `buildBody` returns `total` with JavaScript type `number`, and
    the value is unchanged from the stored order.
  - Verification: `node --test` — "returns total as a number" passes.
  - Dependencies: Task 1

- [ ] **Task 3**: Return nothing for an unknown order id. `[API]`
  - Requirements covered: FR-3
  - Acceptance Criteria: `findOrder` returns `undefined` for an id with no order.
  - Verification: `node --test` — "returns undefined for an unknown order" passes.
  - Dependencies: none

### Checkpoint: Milestone 1

- Exit criterion: `node --test` reports 3 tests, 3 pass, 0 fail.
- RUNTIME PROBE: start: `npm start`; probe: `curl -sS -i http://localhost:5143/api/orders/1`; expect-status: `200`; require-keys: `id, total`
