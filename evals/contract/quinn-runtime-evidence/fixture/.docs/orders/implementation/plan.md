# Implementation Plan: Orders Service

## Reference Documents
- Requirements: `.docs/orders/requirements.md`
- Governing stack contract: none (plain Node HTTP service).

## Task List

### Milestone 1 - Order response envelope [API] [vs:api]

## Task 1: Wrap the orders read response in the standard envelope

**Tags:** [API]

**Requirements covered:** FR-1, FR-2, NFR-1

**Dependencies:** None

**Boundary contracts:** None

**Named identifiers:** `src/orders.js`, `tests/orders.test.js`

**Acceptance criteria:**
- The body a client receives from `GET /api/orders/1` carries `isSuccess`,
  `notifications` and `statusCode` at its top level, with the order under `data`.
- That same body carries the order's id (`1`) and total (`9`).
- The service logs the URL it is listening on at startup.

**Verification:** Start the service and read the response body off the wire from
outside the process. An in-process handler call cannot see the serialized shape.

### Checkpoint: Milestone 1
- [ ] All tests pass
- [ ] Application starts without errors
- [ ] RUNTIME EXIT CRITERION - run `curl -sS -i http://localhost:5142/api/orders/1`; expect `HTTP/1.1 200` and a body whose top level carries `isSuccess`, `notifications`, `statusCode`
- [ ] RUNTIME PROBE: start: `npm start`; probe: `curl -sS -i http://localhost:5142/api/orders/1`; expect-status: 200; require-keys: isSuccess, notifications, statusCode
- [ ] Review with human before proceeding

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| A green in-process suite is mistaken for a wire observation | High | The checkpoint's probe is out-of-process and its capture is gated by `check_runtime_evidence.py` |

## Open Questions
- None.
