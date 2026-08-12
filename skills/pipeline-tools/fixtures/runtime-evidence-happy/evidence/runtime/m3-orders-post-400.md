# Runtime capture: POST /api/orders — validation failure

The failure sibling of `m3-orders-post.md`. A wrapper can shape the success path and
miss the failure path, because they travel different code (a result mapper vs. an
exception handler). One capture proves half a claim. This one doubles as the
negative-half proof required by `test-driven-development`.

- Milestone: M3 — Order envelope [API] [vs:api]
- Requirement IDs: FR-4
- Surface: api
- Transport: out-of-process HTTP (newman)
- Base URL: http://localhost:5142
- Build marker: 1.4.2+sha.9f2c1ab
- Probe command: `newman run postman/orders.json --folder create-order-invalid`
- Captured: 2026-08-12T14:03:19Z
- Exit code: 0
- Duration: 0.22s

## Captured output

```
HTTP/1.1 400 Bad Request
content-type: application/json; charset=utf-8

{"statusCode":400,"isSuccess":false,"data":null,"dataContext":null,"notifications":[{"code":"110402","message":"Order must contain at least one line","propertyName":"lines"}]}
```
