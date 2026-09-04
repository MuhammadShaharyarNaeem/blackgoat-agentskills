# Manual Testing Baseline — orders

Reverse-engineered by Echo during discovery of the orders service, 2026-08-19. These are
cases the service is presumed to **still** satisfy. A case dropped silently is behaviour
nobody decided to stop supporting.

Format authority: `agents/echo.md`. Every case renders the `GO | DO | ASSERT` table, a
stable `<category-abbrev>-<NN>` id, a priority flag, and a `**Result:**` line.

## Happy Path

### HP-01 — A known coupon prices the order (P0)
**Preconditions:** the service is listening on `http://localhost:5182`
| GO | DO | ASSERT |
|----|----|--------|
| a shell with the service running | `POST /orders` with `{"coupon":"SAVE10"}` | `200`, body carries `coupon: "SAVE10"` and `discountPercent: 10` |
**Result:** [ ] Pass [ ] Fail

### HP-02 — A coupon code is matched case-insensitively (P1)
**Preconditions:** the service is listening on `http://localhost:5182`
| GO | DO | ASSERT |
|----|----|--------|
| a shell with the service running | `POST /orders` with `{"coupon":"save20"}` | `200`, body carries `coupon: "SAVE20"` |
**Result:** [ ] Pass [ ] Fail

## Edge Cases

### EC-01 — An order id round-trips through the read route (P2)
**Preconditions:** the service is listening on `http://localhost:5182`
| GO | DO | ASSERT |
|----|----|--------|
| a shell with the service running | `GET /orders/ord-1` | `200`, body carries `id: "ord-1"` and `status: "open"` |
**Result:** [ ] Pass [ ] Fail

## Negative / Error Handling

### NE-01 — An unknown coupon is a client error, not a server error (P0)
**Preconditions:** the service is listening on `http://localhost:5182`
| GO | DO | ASSERT |
|----|----|--------|
| a shell with the service running | `POST /orders` with `{"coupon":"NOPE"}` | `400`, body `{"error":"unknown coupon code"}` |
**Result:** [ ] Pass [ ] Fail

### NE-02 — A malformed body is a client error (P1)
**Preconditions:** the service is listening on `http://localhost:5182`
| GO | DO | ASSERT |
|----|----|--------|
| a shell with the service running | `POST /orders` with the body `not-json` | `400`, body `{"error":"body must be JSON"}` |
**Result:** [ ] Pass [ ] Fail

## Regression Risks

### RR-01 — The read route still rejects a blank order id (P2)
**Preconditions:** the service is listening on `http://localhost:5182`
| GO | DO | ASSERT |
|----|----|--------|
| a shell with the service running | `GET /orders/%20` | `400`, body `{"error":"order id required"}` |
**Result:** [ ] Pass [ ] Fail
