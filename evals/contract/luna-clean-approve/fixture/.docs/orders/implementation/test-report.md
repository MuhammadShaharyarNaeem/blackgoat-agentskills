# Test Report — orders

#Task [1]: Milestone 1 - Tenant-scoped order read and audited create

**In-process suite:** `node --test` — 9 passing, 0 failing.

```
✔ a caller reads an order in their own tenant
✔ an unknown order id is a 404
✔ a cross-tenant read is refused with 403 and no order body
✔ the session decides the tenant even when the body names another
✔ creating an order returns 201 and an integer id
✔ creating an order appends an audit record
✔ a create whose audit cannot be written returns 500 and persists nothing
✔ a prototype-chain token resolves to no session, not an inherited member
✔ a prototype-chain order id resolves to no order (404), not a truthy non-order
ℹ tests 9
ℹ pass 9
ℹ fail 0
```

**Out-of-process probe:** started the service with `npm start`, then ran the
checkpoint's declared `RUNTIME PROBE:` and its cross-tenant sibling from outside the
process. Observations recorded in the capture cited below.

**Coverage Ledger**

- FR-1: PASS — `a caller reads an order in their own tenant`, and the same
  `id`/`total`/`memo` read back off the wire (`200`, `application/json`) in the capture.
- FR-2: PASS — `a cross-tenant read is refused with 403 and no order body` and `the
  session decides the tenant even when the body names another`; confirmed over the wire —
  a `tok-globex` caller naming `acme` in the body receives `403` (capture below).
- FR-3: PASS — `creating an order returns 201 and an integer id`, and a `201`/`{"id":3,
  "total":12}` observed off the wire in the capture.
- FR-4: PASS — `creating an order appends an audit record` (positive path), and `a create
  whose audit cannot be written returns 500 and persists nothing` (fail-loud path). The
  fail-loud path is in-process by necessity — it is unreachable over HTTP for a real
  session (see the capture's note) — and the audited-create positive path is observed on
  the wire.
- NFR-1: PASS — `orders listening on http://localhost:5151` observed on the service's
  stdout at startup, before any probe; recorded in the capture.

**Runtime evidence:** evidence/runtime/m1-orders.md

**Verdict:** Milestone 1 APPROVED for verification. Every Must-Have is satisfied by the
running service, observed out-of-process at the wire; the two failure-path guards (audit
fail-loud, prototype-chain lookups) are covered in-process. No Must-Have is uncovered.
