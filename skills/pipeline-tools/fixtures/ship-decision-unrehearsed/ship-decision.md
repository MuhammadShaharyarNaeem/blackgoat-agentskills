# Ship Decision — checkout-rewrite

Taken against commit `9f2c1ab`; working tree clean at the moment of this verdict.
Blockers copied verbatim from `orchestrator-state.json`: None.

## Rollback Strategy

### Trigger Conditions
- Error rate more than 2x baseline
- P95 latency more than 50% above baseline

### Rollback Steps
1. Disable the `checkout-rewrite` feature flag
2. Verify rollback: health check plus error monitoring
3. Communicate: notify the release channel

### Time to Rollback
- Feature flag: < 1 minute
- Redeploy previous version: < 5 minutes

## Post-deploy Checklist

- [x] Health endpoint returns 200
- [x] Error monitoring shows no new error types
- [x] Confirm rollback mechanism works (dry run if possible)

Ship Decision: GO
