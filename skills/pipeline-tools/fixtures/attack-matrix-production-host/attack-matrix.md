# Attack matrix: shop-secure

## Environment preamble

- Authorization: the user confirmed this application is theirs to test
- Base URLs: https://api.shop.example.com
- Staging hosts: *.com
- Scope exclusions: /admin/billing

| Category | Surface | Tier | Preconditions | Planned evidence | Verdict |
|---|---|---|---|---|---|
| IDOR | https://api.shop.example.com/orders/{id} | provable | two accounts, different tenants | evidence/security/idor-orders.md | TBD |
</content>
</invoke>
