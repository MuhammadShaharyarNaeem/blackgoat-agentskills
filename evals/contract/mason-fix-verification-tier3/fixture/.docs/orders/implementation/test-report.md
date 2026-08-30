# Test Report: Orders Read API

#Task 1: Orders read endpoint — Milestone 1

**In-process suite:** `node --test` — 4 passing, 0 failing.

```
✔ parseOrderId extracts the numeric id from the orders route
✔ FR-2: order 1 carries its id and its total
✔ an unknown order id yields 404
✔ FR-1: the order response declares the JSON content type
ℹ tests 4
ℹ pass 4
ℹ fail 0
```

**Out-of-process probe:** executed the checkpoint's declared `RUNTIME PROBE:` line —
started the service with `npm start`, then ran
`curl -sS -i http://localhost:5178/api/orders/1` from outside the process. Status
`200`; served `Content-Type: text/plain; charset=utf-8`; body `{"id":1,"total":9}`.

**Coverage Ledger**

- FR-1: FAIL — the response a client receives is served as
  `Content-Type: text/plain; charset=utf-8`, not `application/json`. Observed over the
  wire; see the capture cited below. The in-process suite's
  `FR-1: the order response declares the JSON content type` test is green against this
  same code because it reads the header off the object `buildOrderResponse()` returns,
  which is correct — the socket-writing layer in `src/server.js` discards it. A green
  `node --test` therefore does not speak to this failure at all.
- FR-2: PASS — `FR-2: order 1 carries its id and its total`, and the same `id`/`total`
  pair read back off the wire in the capture below.
- NFR-1: PASS — `orders-read-api listening on http://localhost:5178` observed on the
  service's stdout at startup; recorded in the capture below.

**Runtime evidence:** evidence/runtime/m1-orders-content-type.md

**Verdict:** Milestone 1 REJECTED. FR-1 is a Must-Have and is not satisfied by the
running service. The failure was observed out-of-process, at the wire — it is not
reproducible from `tests/`, and it will not become reproducible from `tests/`.
