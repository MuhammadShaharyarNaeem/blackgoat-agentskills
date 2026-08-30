# Test Report — orders

#Task [1]: Milestone 1 - Tenant-scoped order read and audited create

**In-process suite:** `node --test` — 13 passing, 0 failing.

```
✔ a caller reads an order in their own tenant
✔ an unknown order id is a 404
✔ a cross-tenant read is refused with 403 and no order body
✔ the session decides the tenant even when the body names another
✔ creating an order returns 201 and an integer id
✔ creating an order appends an audit record
✔ a create whose audit cannot be written returns 500 and persists nothing
✔ a lookup with no orderId is a 400, not a 404 guess
✔ a lookup whose orderId is a non-primitive is a 400, not a crash
✔ a create with a missing or non-positive total is a 400 and persists nothing
✔ a create with a non-string memo is a 400
✔ a prototype-chain token resolves to no session, not an inherited member
✔ a prototype-chain order id resolves to no order (404), not a truthy non-order
ℹ tests 13
ℹ pass 13
ℹ fail 0
```

**Out-of-process probe:** started the service with `npm start` and probed every wire
claim from outside the process, capturing full response bodies. Observations recorded
in the capture cited below.

**Coverage Ledger**

- FR-1: PASS — `a caller reads an order in their own tenant`, and the same
  `id`/`total`/`memo` read off the wire (`200`, `application/json`) in the capture.
- FR-2: PASS — both tests, and both halves proven over the wire: a `tok-globex` caller
  naming `acme` in the body receives `403` whose complete served body is
  `{"error":"forbidden"}` — refusal and confidentiality captured together.
- FR-3: PASS — `creating an order returns 201 and an integer id`, and `201`/
  `{"id":3,"total":12}` observed off the wire.
- FR-4: PASS — positive path (`creating an order appends an audit record`) with the
  accepted create observed on the wire; fail-loud path (`a create whose audit cannot
  be written returns 500 and persists nothing`) verified in-process **per FR-4's own
  declared verification scope in `requirements.md`** — the unwritable-audit state is
  not producible by any client input, so forcing the audit sink to reject is the
  agreed tier for this requirement, not a substitute for an available capture.
- NFR-1: PASS — `orders listening on http://localhost:5151` observed on the service's
  stdout at startup, before any probe; recorded in the capture.
- NFR-2: PASS — the boundary tests, and over the wire: all three enumerated non-object
  forms (malformed JSON, JSON `null`, JSON scalar) → `400`; a non-primitive `orderId`
  → `400`; create with no `total` → `400` with nothing persisted.
- NFR-3: PASS — `a lookup whose orderId is a non-primitive is a 400, not a crash`, and
  over the wire the non-primitive `orderId` that formerly threw returns `400` and the
  service answers the next request `200` (capture below) — the handler error boundary
  contains any unexpected throw as `500` rather than a process crash.

**Runtime evidence:** evidence/runtime/m1-orders.md

**Verdict:** Milestone 1 APPROVED for verification. Every Must-Have is satisfied by
the running service and observed at its declared tier — wire captures with full bodies
for every client-producible claim, in-process forcing for the one state no client
input can produce (per FR-4's verification scope). No Must-Have is uncovered.
