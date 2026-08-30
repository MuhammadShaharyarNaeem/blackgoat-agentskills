# Implementation Plan: Orders Read API

## Reference Documents
- Requirements: `.docs/orders/requirements.md`
- Governing stack contract: none (plain Node HTTP service, no dependencies).

## Task List

### Milestone 1 - Orders read endpoint [API] [vs:api]

## Task 1: Serve the orders read response with a JSON content type

**Tags:** [API]

**Requirements covered:** FR-1, FR-2, NFR-1

**Dependencies:** None

**Boundary contracts:** None

**Named identifiers:** `src/orders.js`, `src/server.js`, `tests/orders.test.js`

**Acceptance criteria:**
- The response a client receives from `GET /api/orders/1` answers `200` and carries
  `Content-Type: application/json`.
- That same response body carries the order's id (`1`) and its total (`9`).
- The service logs the URL it is listening on at startup.

**Verification:** Start the service and read the response — status line, headers and
body — off the wire from outside the process. The served header is produced by the
socket-writing layer, so a call into the request-building function cannot observe it.

### Checkpoint: Milestone 1
- [ ] All tests pass
- [ ] Application starts without errors
- [ ] RUNTIME EXIT CRITERION - run `curl -sS -i http://localhost:5178/api/orders/1`; expect `HTTP/1.1 200` and a `Content-Type: application/json` response header
- [ ] RUNTIME PROBE: start: `npm start`; probe: `curl -sS -i http://localhost:5178/api/orders/1`; expect-status: 200; require-keys: id, total
- [ ] Review with human before proceeding

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| A green in-process suite is mistaken for a wire observation | High | The checkpoint's probe is out-of-process; its capture is gated by `check_runtime_evidence.py` |
| The served header diverges from the header the response builder declares | High | The checkpoint asserts the header a client receives, not the one the builder returns |

## Open Questions
- None.
