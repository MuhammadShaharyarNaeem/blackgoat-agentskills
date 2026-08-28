# Runtime capture — orders read/create, over the wire

- Milestone: Milestone 1 - Tenant-scoped order read and audited create
- Requirement IDs: FR-1, FR-2, FR-3, FR-4 (positive path), NFR-1, NFR-2
- Surface: api
- Transport: curl over TCP to a locally started `node src/server.js` process
- Base URL: http://localhost:5151
- Probe command: curl -sS -i -X POST http://localhost:5151/api/orders/lookup -H "Authorization: Bearer tok-acme" -H "Content-Type: application/json" -d "{\"orderId\":1}"
- Captured: 2026-08-28T10:31:12Z
- Exit code: 0
- OpenAPI: http://localhost:5151/openapi.json — 404 (the service publishes no contract
  document; recorded rather than omitted)

## Observation

Every claim below is backed by a verbatim entry in the transcript — nothing is
narrated without its captured output. Response bodies are complete, so
confidentiality claims are proven by the body that was actually served.

- **NFR-1** — the startup line is the transcript's first entry, read off the
  service's stdout before any probe.
- **FR-1** — own-tenant read: `200`, `application/json`, full order body.
- **FR-2, both halves** — cross-tenant read with the body naming another tenant:
  `403`, and the complete served body is `{"error":"forbidden"}` — no order field
  escapes.
- **FR-3** — create: `201` with `{"id":3,"total":12}`.
- **FR-4 (positive path)** — the accepted create above is the audited create; the
  fail-loud `500` path is verified in-process per FR-4's declared verification
  scope in `requirements.md` (the unwritable-audit state is not producible by any
  client input).
- **NFR-2** — malformed body → `400`; JSON `null` body → `400`; create with no
  `total` → `400`; each with its refusal body in the transcript, and the service
  answered subsequent requests normally (the `null` probe is followed by three
  more successful exchanges).
- **Unauthenticated** — no `Authorization` header → `401 {"error":"unauthenticated"}`.

## Captured output

The declared probe's exchange, verbatim (the gate reads this block: first status
line, last JSON body):

```
HTTP/1.1 200 OK
Content-Type: application/json

{"id":1,"total":9,"memo":"acme quarterly restock"}
```

## Additional captured probes (verbatim)

Every other claim's exchange, captured in the same session, in order. The service's
startup stdout opens the session; the `null`-body probe is followed by further
successful exchanges, proving the service survived it.

```
$ node src/server.js   (stdout)
orders listening on http://localhost:5151

$ curl -sS -i -X POST http://localhost:5151/api/orders/lookup -H "Authorization: Bearer tok-globex" -d "{\"orderId\":1,\"tenantId\":\"acme\"}"
HTTP/1.1 403 Forbidden
Content-Type: application/json

{"error":"forbidden"}

$ curl -sS -i -X POST http://localhost:5151/api/orders -H "Authorization: Bearer tok-acme" -d "{\"total\":12,\"memo\":\"restock\"}"
HTTP/1.1 201 Created
Content-Type: application/json

{"id":3,"total":12}

$ curl -sS -i -X POST http://localhost:5151/api/orders -H "Authorization: Bearer tok-acme" -d "not json{{"
HTTP/1.1 400 Bad Request
Content-Type: application/json

{"error":"request body must be a JSON object"}

$ curl -sS -i -X POST http://localhost:5151/api/orders -H "Authorization: Bearer tok-acme" -d "null"
HTTP/1.1 400 Bad Request
Content-Type: application/json

{"error":"request body must be a JSON object"}

$ curl -sS -i -X POST http://localhost:5151/api/orders -H "Authorization: Bearer tok-acme" -d "{\"memo\":\"x\"}"
HTTP/1.1 400 Bad Request
Content-Type: application/json

{"error":"total must be a positive number"}

$ curl -sS -i -X POST http://localhost:5151/api/orders/lookup -d "{\"orderId\":1}"   (no Authorization header)
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{"error":"unauthenticated"}

$ curl -sS -i -X POST http://localhost:5151/api/orders/lookup -H "Authorization: Bearer tok-acme" -d "{\"orderId\":1}"
HTTP/1.1 200 OK
Content-Type: application/json

{"id":1,"total":9,"memo":"acme quarterly restock"}
```
