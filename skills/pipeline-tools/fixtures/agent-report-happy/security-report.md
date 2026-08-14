# Security Report — demo-project

## Security Audit: Shipping — 2026-08-11

- Secrets scan: PASS — `git grep -nE "(api_key|secret|BEGIN RSA)" -- ':!*.md'` — exit 1 — 0 matches
- Dependency audit: PASS — `npm audit --audit-level=high` — exit 0 — 0 critical, 0 high
- Security headers: PASS — `node scripts/check-headers.js` — exit 0 — 6/6 headers configured
- CORS policy: PASS — `git grep -n "origin: '\*'" src/` — exit 1 — no wildcard origins
- Rate limiting: PASS — `git grep -n rateLimit src/routes/auth.js` — exit 0 — limiter on login and reset

**Verdict:** Pass
