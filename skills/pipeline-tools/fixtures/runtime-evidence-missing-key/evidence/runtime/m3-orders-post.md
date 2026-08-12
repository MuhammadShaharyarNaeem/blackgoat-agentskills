# Runtime capture: POST /api/orders — success

Everything about this capture is honest and well-formed. The transport is real, the
host is local, the probe is a runtime probe, the status is 200. Only the body is
wrong — and only the body reveals it.

- Milestone: M3 — Order envelope [API] [vs:api]
- Requirement IDs: FR-4
- Surface: api
- Transport: out-of-process HTTP (newman)
- Base URL: http://localhost:5142
- Build marker: 1.4.2+sha.9f2c1ab
- Probe command: `newman run postman/orders.json --folder create-order`
- Captured: 2026-08-12T14:03:11Z
- Exit code: 0
- Duration: 0.39s

## Captured output

```
HTTP/1.1 200 OK
content-type: application/json; charset=utf-8

{"id":"9f2c","total":41.5}
```
