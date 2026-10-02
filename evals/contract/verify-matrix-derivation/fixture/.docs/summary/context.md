# Global Context — orders-svc

Derived by Iris during discovery, 2026-08-19.
Repository HEAD: __BASE_SHA__

## Target Scope
- `orders-svc` (this repository) — a single Node HTTP service, no database.

## Stack
- Node 24, `node:http`, no framework, no dependencies.
- Start: `npm start` (runs `node src/server.js`), listening on `PORT` or `5182`.

## Features
- `orders` — pricing an order with an optional coupon, and reading an order back by id.
  Baseline: `.docs/summary/orders/QA/manual-testing.md`.
