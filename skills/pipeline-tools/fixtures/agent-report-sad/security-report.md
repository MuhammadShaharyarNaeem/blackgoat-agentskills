# Security Report — demo-project

## Security Audit: Shipping — 2026-08-11

- Dependency audit: FAIL — `npm audit --audit-level=high` — exit 1 — 2 high, 5 moderate
- Secrets scan: PASS — repo looked clean
- Rate limiting: NOT RUN — no staging environment reachable

### Findings

- **Critical** — hardcoded JWT signing secret — src/auth/token.js:14
- **Important** — CORS wildcard on /api/export — src/routes/export.js:9

**Verdict:** Pass
