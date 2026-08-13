# Runtime capture: POST /api/orders — success

Honest transport, local host, runtime probe, status 200, full envelope in the body.
The one thing missing is the contract surface: the probe asked for the OpenAPI
document and got a 404, so nothing here shows that the thing which answered is the
API under test rather than a stub, a mock, or a previous build that happens to hold
port 5142.

A reachable OpenAPI document is the exact instrument that falsified the 2026-08
envelope claim by hand. Requiring the probe to record it forces the probe at a real
host rather than at anything that merely answers on a port.

- Milestone: M3 — Order envelope [API] [vs:api]
- Requirement IDs: FR-4
- Surface: api
- Transport: out-of-process HTTP (newman)
- Base URL: http://localhost:5142
- Build marker: 1.4.2+sha.9f2c1ab
- OpenAPI: http://localhost:5142/swagger/v1/swagger.json — 404
- Probe command: `newman run postman/orders.json --folder create-order`
- Captured: 2026-08-12T14:03:11Z
- Exit code: 0
- Duration: 0.37s

## Captured output

```
HTTP/1.1 200 OK
content-type: application/json; charset=utf-8

{"statusCode":200,"isSuccess":true,"data":{"id":"9f2c","total":41.5},"dataContext":null,"notifications":[]}
```
