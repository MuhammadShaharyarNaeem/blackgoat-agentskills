# Ship Decision — checkout-rewrite

Taken against commit `9f2c1ab`; working tree clean at the moment of this verdict.
Blockers copied verbatim from `orchestrator-state.json`: None.

## Baseline

Read from the monitoring source immediately before rollout. Every row of the
Rollout Decision Thresholds table in `shipping-and-launch` is a delta against
these numbers, so a rollout without them has no advance/hold/roll-back rule.

- Error rate: 0.42% of requests, trailing 24h — evidence: evidence/baseline/error-rate.md
- P95 latency: 184ms on POST /api/checkout — evidence: evidence/baseline/latency.md
- Checkout conversion: 3.14% of sessions — evidence: evidence/baseline/conversion.md

## Rollback Strategy

### Trigger Conditions
- Error rate above 0.84% (2x baseline)
- P95 latency above 276ms (50% above baseline)
- Checkout conversion down more than 5%

### Rollback Steps
1. Disable the `checkout-rewrite` feature flag
2. Verify rollback: health check plus error monitoring
3. Communicate: notify the release channel

### Rehearsal

Time to Rollback: 47 sec — rehearsed 2026-08-28 on staging — evidence: evidence/rollback/2026-08-28-rehearsal.md

47s fits the feature-flag rung of the Time to Rollback ladder (< 1 minute), which
is the rollback type this release uses.

## Post-deploy Checklist

- [x] Health endpoint returns 200
- [x] Error monitoring shows no new error types
- [x] Latency dashboard shows no regression
- [x] Critical user flow exercised against the deployed environment
- [x] Logs flowing and readable

Ship Decision: GO
