# Orders API — Implementation Plan

## Task List

### Milestone 1 — Orders: list endpoint [API] [vs:api]

## Task 1: Order list endpoint

**Tags:** [API]

**Requirements covered:** FR-1

**Named identifiers:** `src/api/orders.ts`, `tests/api/orders.spec.ts`

**Acceptance criteria:**
- Requesting the order list returns one entry per stored order.

### Checkpoint: Milestone 1
- [ ] All tests pass
- [ ] Application builds without errors
- [ ] RUNTIME EXIT CRITERION — run `npm test -- --grep orders`; expect a green suite
- [ ] RUNTIME PROBE: start: `npm run start`; probe: `npm test -- --grep orders`; expect-status: 200; require-keys: isSuccess, data
- [ ] Review with human before proceeding

### Milestone 2 — Orders: create endpoint [API] [vs:api]

## Task 2: Order creation endpoint

**Tags:** [API]

**Requirements covered:** FR-2, NFR-1

**Named identifiers:** `src/api/orders-create.ts`, `tests/api/orders-create.spec.ts`

**Acceptance criteria:**
- Placing a valid order returns the created order in the response.
- A rejected order leaves the orders store unchanged.

### Checkpoint: Milestone 2
- [ ] All tests pass
- [ ] Application builds without errors
- [ ] RUNTIME EXIT CRITERION — run `curl -sS -i http://localhost:5142/api/orders`; expect the created order in `data`
- [ ] RUNTIME PROBE: start: `npm run start`; probe: `curl -sS -i -X POST http://localhost:5142/api/orders`
- [ ] Review with human before proceeding

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Partial write on rejection | High | Single transaction per order |
