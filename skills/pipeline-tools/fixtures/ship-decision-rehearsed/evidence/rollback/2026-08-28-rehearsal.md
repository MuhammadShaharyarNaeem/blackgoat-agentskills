# Runtime capture: rollback rehearsal — checkout-rewrite

- Milestone: checkout-rewrite (epic)
- Environment: staging
- Transport: out-of-process shell against the staging deployment
- Probe command: `flagctl disable checkout-rewrite --env staging && curl -sS -o /dev/null -w "%{http_code}
" https://staging.example.internal/healthz`
- Captured: 2026-08-28T09:14:02Z
- Exit code: 0
- Duration: 47.31s

## Captured output

```
flag checkout-rewrite: enabled -> disabled (staging)
propagated to 4/4 pods in 41.62s
200
```
