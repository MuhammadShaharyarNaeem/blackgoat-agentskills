# Runtime capture: POST /api/orders — success

- Milestone: M3 — Order envelope [API] [vs:api]
- Requirement IDs: FR-4
- Surface: api
- Transport: in-process host client (WebApplicationFactory<Program>)
- Base URL: http://localhost
- Probe command: `dotnet test --filter Returns_envelope`
- Captured: 2026-08-12T14:03:11Z
- Exit code: 0
- Duration: 3.90s

## Captured output

```
{"statusCode":200,"isSuccess":true,"data":{"id":"9f2c","total":41.5},"dataContext":null,"notifications":[]}
```
