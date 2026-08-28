# Runtime capture — orders read/create, over the wire

- Milestone: Milestone 1 - Tenant-scoped order read and audited create
- Requirement IDs: FR-1, FR-2, FR-3, FR-4 (positive path), NFR-1, NFR-2
- Surface: api
- Transport: curl over TCP to a locally started `node src/server.js` process
- Base URL: http://localhost:5151
- Captured: 2026-08-28T10:07:44Z
- Exit code: 0
- OpenAPI: http://localhost:5151/openapi.json — 404 (the service publishes no contract
  document; recorded rather than omitted)

## Observation

Every claim below was read off the socket, not off an in-process function return.
Response bodies are captured in full — confidentiality claims are proven by the body
that was actually served, not by a status code alone.

- **NFR-1** — startup line on the service's stdout before any probe:
  `orders listening on http://localhost:5151`.
- **FR-1** — own-tenant read `POST /api/orders/lookup` `{"orderId":1}` as `tok-acme`:
  `200`, `Content-Type: application/json`, body
  `{"id":1,"total":9,"memo":"acme quarterly restock"}`.
- **FR-2, both halves** — cross-tenant read `{"orderId":1,"tenantId":"acme"}` as
  `tok-globex` (the body names another tenant): `403 Forbidden`, and the **complete
  served body is `{"error":"forbidden"}`** — no `id`, no `total`, no `memo`. The
  session decides the tenant; the body-supplied `tenantId` is ignored; no part of the
  order's body escapes.
- **FR-3** — create `{"total":12,"memo":"restock"}` as `tok-acme`: `201`, body
  `{"id":3,"total":12}`.
- **FR-4 (positive path)** — the accepted create above is audited (in-process suite
  asserts the ledger append). The fail-loud `500` path is verified in-process per
  FR-4's declared verification scope in `requirements.md`: the unwritable-audit state
  is not producible by any client input, so the suite forces the audit sink to reject
  and asserts `500` plus zero persistence.
- **NFR-2** — malformed body `not json{{`: `400`. JSON `null` body: `400` (and the
  service answered the next request normally — no crash). Create with no `total`:
  `400`, body `{"error":"total must be a positive number"}`, nothing persisted.
- **Unauthenticated** — no `Authorization` header: `401`.

## Captured output

```
$ curl -sS -i -X POST http://localhost:5151/api/orders/lookup \
    -H "Authorization: Bearer tok-globex" -H "Content-Type: application/json" \
    -d '{"orderId":1,"tenantId":"acme"}'
HTTP/1.1 403 Forbidden
Content-Type: application/json

{"error":"forbidden"}

$ curl -sS -i -X POST http://localhost:5151/api/orders \
    -H "Authorization: Bearer tok-acme" -H "Content-Type: application/json" \
    -d 'null'
HTTP/1.1 400 Bad Request
Content-Type: application/json

{"error":"request body must be a JSON object"}

$ curl -sS -X POST http://localhost:5151/api/orders/lookup \
    -H "Authorization: Bearer tok-acme" -H "Content-Type: application/json" \
    -d '{"orderId":1}'
{"id":1,"total":9,"memo":"acme quarterly restock"}   (status 200)
```
