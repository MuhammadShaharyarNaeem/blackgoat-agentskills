# Feature Overview — orders

Derived by Echo during discovery, 2026-08-19.
Repository HEAD: __BASE_SHA__

## Surfaces
| Route | Purpose | Source |
|---|---|---|
| `POST /orders` | price an order; optional `coupon`, matched case-insensitively | `src/server.js`, `src/coupons.js` |
| `GET /orders/:id` | read an order back; blank id is a 400 | `src/server.js`, `src/validation.js` |

## Error envelope
Every client error answers `{"error": "<message>"}` with a 4xx status; anything else is a
generic 500.

## Baseline
`QA/manual-testing.md` — six cases across Happy Path, Edge Cases, Negative / Error Handling
and Regression Risks.
