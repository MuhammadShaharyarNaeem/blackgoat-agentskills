# Runtime capture — orders read/create, over the wire

- Milestone: Milestone 1 - Tenant-scoped order read and audited create
- Requirement IDs: FR-1, FR-2, FR-3, FR-4, NFR-1
- Surface: api
- Transport: curl over TCP to a locally started `node src/server.js` process
- Base URL: http://localhost:5151
- Captured: 2026-08-24T21:40:37Z
- Exit code: 0
- OpenAPI: http://localhost:5151/openapi.json — 404 (the service publishes no contract
  document; recorded rather than omitted)

## Observation

Every claim below was read off the socket, not off an in-process function return.

- **NFR-1** — startup line on the service's stdout before any probe:
  `orders listening on http://localhost:5151`.
- **FR-1** — own-tenant read `POST /api/orders/lookup` `{"orderId":1}` as `tok-acme`:
  `200 OK`, `Content-Type: application/json`, body
  `{"id":1,"total":9,"memo":"acme quarterly restock"}`.
- **FR-2** — cross-tenant read `POST /api/orders/lookup` `{"orderId":1,"tenantId":"acme"}`
  as `tok-globex` (the body names another tenant): `403 Forbidden`, empty of any order
  body. The session decides the tenant; the body-supplied `tenantId` is ignored.
- **FR-3** — create `POST /api/orders` `{"total":12,"memo":"restock"}` as `tok-acme`:
  `201 Created`, `Content-Type: application/json`, body `{"id":3,"total":12}`.
- **Unauthenticated** — the same read with no `Authorization` header: `401`.

The FR-4 fail-loud path (a create whose audit cannot be written must return `500` and
persist nothing) is not reachable over HTTP — every authenticated session carries a
`userId`, so `recordAudit` never rejects for a real caller. It is exercised in-process by
`tests/orders.test.js` ("a create whose audit cannot be written returns 500 and persists
nothing"), which forces the rejection with an unattributable session and asserts the
order table and ledger are both unchanged. Recorded here so the boundary is explicit.

## Captured output

```
$ curl -sS -i -X POST http://localhost:5151/api/orders/lookup \
    -H "Authorization: Bearer tok-acme" -H "Content-Type: application/json" \
    -d '{"orderId":1}'
HTTP/1.1 200 OK
Content-Type: application/json

{"id":1,"total":9,"memo":"acme quarterly restock"}

$ curl -sS -o /dev/null -w '%{http_code}' -X POST \
    http://localhost:5151/api/orders/lookup \
    -H "Authorization: Bearer tok-globex" -H "Content-Type: application/json" \
    -d '{"orderId":1,"tenantId":"acme"}'
403
```
