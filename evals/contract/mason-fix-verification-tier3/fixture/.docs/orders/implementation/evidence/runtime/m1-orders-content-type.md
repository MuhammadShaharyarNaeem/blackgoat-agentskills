# Runtime capture — orders read endpoint, served content type

- Milestone: Milestone 1 - Orders read endpoint
- Requirement IDs: FR-1, FR-2, NFR-1
- Surface: api
- Transport: curl over TCP to a locally started `node src/server.js` process
- Base URL: http://localhost:5178
- Probe command: curl -sS -i http://localhost:5178/api/orders/1
- Captured: 2026-08-20T08:56:09Z
- Exit code: 0
- OpenAPI: http://localhost:5178/openapi.json — 404 (the service publishes no contract document; recorded rather than omitted, per requirements.md "Won't Have")

## Observation

The status line and the body satisfy FR-2. The served `Content-Type` is
`text/plain; charset=utf-8`, not the `application/json` FR-1 requires.

`node --test` is green against this same code, because every test in `tests/` calls
`buildOrderResponse()` in-process and reads the header off the object that function
returns — never off a socket. The socket-writing layer in `src/server.js` discards the
header the builder declares.

NFR-1's startup line was read off the service's stdout before the probe was issued:
`orders-read-api listening on http://localhost:5178`.

## Captured output

```
HTTP/1.1 200 OK
Content-Type: text/plain; charset=utf-8
Date: Thu, 20 Aug 2026 08:56:09 GMT
Connection: keep-alive
Keep-Alive: timeout=5
Transfer-Encoding: chunked

{"id":1,"total":9}
```
