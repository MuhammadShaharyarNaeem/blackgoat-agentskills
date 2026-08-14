# Runtime capture: POST /api/orders — success

- Milestone: M3 — Order envelope [API] [vs:web+api]
- Requirement IDs: FR-4
- Surface: web+api
- Transport: out-of-process HTTP (newman)
- Base URL: http://localhost:5173
- Environment: web=http://localhost:5173, gateway=https://gateway.dev.internal, crm=http://localhost:5210
- Config repointed: web/.env.local ApiBase -> localhost:5173
- Build marker: 1.4.2+sha.9f2c1ab
- Probe command: `newman run postman/orders.json --folder create-order`
- Captured: 2026-08-12T14:03:11Z
- Exit code: 0
- Duration: 0.51s

## Captured output

```
HTTP/1.1 200 OK
content-type: application/json; charset=utf-8

{"statusCode":200,"isSuccess":true,"data":{"id":"9f2c","total":41.5},"dataContext":null,"notifications":[]}
```
