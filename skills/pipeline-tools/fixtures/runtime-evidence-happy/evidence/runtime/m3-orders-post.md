# Runtime capture: POST /api/orders — success

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
- Duration: 0.41s

## Captured output

```
HTTP/1.1 200 OK
content-type: application/json; charset=utf-8

{"statusCode":200,"isSuccess":true,"data":{"id":"9f2c","total":41.5},"dataContext":null,"notifications":[]}
```
