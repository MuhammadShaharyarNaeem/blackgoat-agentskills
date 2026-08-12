# Runtime capture: POST /api/orders — success

Transport, host, probe, status and contract surface are all clean. The body carries
`statusCode` and `isSuccess`, so a two-key `--require-key` check would pass it. What
the declared contract says it should also carry — `dataContext` and `notifications` —
is absent, and it carries a `traceId` the contract never declared.

Declared-but-absent is the gating half. Observed-but-undeclared is informational.

- Milestone: M3 — Order envelope [API] [vs:api]
- Requirement IDs: FR-4
- Surface: api
- Transport: out-of-process HTTP (newman)
- Base URL: http://localhost:5142
- Build marker: 1.4.2+sha.9f2c1ab
- OpenAPI: http://localhost:5142/swagger/v1/swagger.json — 200
- Probe command: `newman run postman/orders.json --folder create-order`
- Captured: 2026-08-12T14:03:11Z
- Exit code: 0
- Duration: 0.44s

## Captured output

```
HTTP/1.1 200 OK
content-type: application/json; charset=utf-8

{"statusCode":200,"isSuccess":true,"data":{"id":"9f2c","total":41.5},"traceId":"0af7651916cd43dd"}
```
