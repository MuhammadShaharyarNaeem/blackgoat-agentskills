# Attack matrix: shop-secure

## Environment preamble

- Authorization: the user confirmed this application is theirs to test
- Non-production: local dev stack plus the shared staging slot
- Base URLs: http://localhost:5000, `127.0.0.1:5173`, https://shop.staging.example.com
- Staging hosts: shop.staging.example.com
- Forbidden hosts: https://shop.example.com, https://api.shop.example.com
- Scope exclusions:
  - https://payments.example.com (third-party processor)
  - /admin/billing

| Category | Surface | Tier | Preconditions | Planned evidence | Verdict |
|---|---|---|---|---|---|
| IDOR | http://127.0.0.1:5000/api/orders/{id} | provable | two accounts, different tenants | evidence/security/idor-orders.md | TBD |
| Security Misconfiguration | https://shop.staging.example.com/ | provable | none beyond a running app | evidence/security/headers.md | TBD |
