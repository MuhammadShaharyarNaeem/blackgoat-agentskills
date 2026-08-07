---
name: shipping-and-launch
description: Squad-internal execution contract for production launch preparation — pre-launch checklist, monitoring, staged rollout, and rollback strategy — loaded by agents via their Methodology Dependencies table; user-facing shipping and deployment triggers belong to the /bgpdd-shipping pipeline.
---

# Shipping and Launch

Ship with confidence. The goal is not just to deploy — it's to deploy safely, with monitoring in place, a rollback plan ready, and a clear understanding of what success looks like. Every launch should be reversible, observable, and incremental.

## Worker Execution Contract

This is the operational spine. Follow it as written. Pipelines delegate the checklist sections below by name — do not rename or drop them.

### The Pre-Launch Checklist

The Security, Performance, and Accessibility sections below are the delegation subset — the root `{PLUGIN_ROOT}/../references/` checklists (see "See Also") are authoritative; update those first.

**The sections below are a floor, not the whole checklist.** Where the project has a numbered requirements set, every Must-Have FR and NFR additionally gets its own row, cited by ID, each carrying the evidence that verified it. A requirement with no row is not a pass — it is an unperformed check, and the recommendation is `NO-GO` until it has one. Enumerate from the requirements document, never from the built feature list: requirements expressed as *qualities* rather than features (accessibility, contrast, performance, theming, responsiveness) are exactly the ones a feature-shaped review cannot see and a generic template silently omits.

#### Code Quality

- [ ] All tests pass (unit, integration, e2e)
- [ ] Build succeeds with no warnings
- [ ] Lint and type checking pass
- [ ] Code reviewed and approved
- [ ] No TODO comments that should be resolved before launch
- [ ] No `console.log` debugging statements in production code
- [ ] Error handling covers expected failure modes

#### Security

- [ ] No secrets in code or version control
- [ ] `npm audit` shows no critical or high vulnerabilities
- [ ] Input validation on all user-facing endpoints
- [ ] Authentication and authorization checks in place
- [ ] Security headers configured (CSP, HSTS, etc.)
- [ ] Rate limiting on authentication endpoints
- [ ] CORS configured to specific origins (not wildcard)

#### Performance

- [ ] Core Web Vitals within "Good" thresholds
- [ ] No N+1 queries in critical paths
- [ ] Images optimized (compression, responsive sizes, lazy loading)
- [ ] Bundle size within budget
- [ ] Database queries have appropriate indexes
- [ ] Caching configured for static assets and repeated queries

#### Accessibility

- [ ] Keyboard navigation works for all interactive elements
- [ ] Screen reader can convey page content and structure
- [ ] Color contrast meets WCAG 2.1 AA (4.5:1 for text)
- [ ] Focus management correct for modals and dynamic content
- [ ] Error messages are descriptive and associated with form fields
- [ ] No accessibility warnings in axe-core or Lighthouse

#### Infrastructure

- [ ] Environment variables set in production
- [ ] Database migrations applied (or ready to apply)
- [ ] DNS and SSL configured
- [ ] CDN configured for static assets
- [ ] Logging and error reporting configured
- [ ] Health check endpoint exists and responds

#### Documentation

- [ ] README updated with any new setup requirements
- [ ] API documentation current
- [ ] ADRs written for any architectural decisions
- [ ] Changelog updated
- [ ] User-facing documentation updated (if applicable)

### Feature Flag Strategy

Ship behind feature flags to decouple deployment from release.

**Feature flag lifecycle:**

```
1. DEPLOY with flag OFF     → Code is in production but inactive
2. ENABLE for team/beta     → Internal testing in production environment
3. GRADUAL ROLLOUT          → 5% → 25% → 50% → 100% of users
4. MONITOR at each stage    → Watch error rates, performance, user feedback
5. CLEAN UP                 → Remove flag and dead code path after full rollout
```

**Rules:**
- Every feature flag has an owner and an expiration date
- Clean up flags within 2 weeks of full rollout
- Don't nest feature flags (creates exponential combinations)
- Test both flag states (on and off) in CI

### Staged Rollout

**The Rollout Sequence:**

```
1. DEPLOY to staging
   └── Full test suite in staging environment
   └── Manual smoke test of critical flows

2. DEPLOY to production (feature flag OFF)
   └── Verify deployment succeeded (health check)
   └── Check error monitoring (no new errors)

3. ENABLE for team (flag ON for internal users)
   └── Team uses the feature in production
   └── 24-hour monitoring window

4. CANARY rollout (flag ON for 5% of users)
   └── Monitor error rates, latency, user behavior
   └── Compare metrics: canary vs. baseline
   └── 24-48 hour monitoring window
   └── Advance only if all thresholds pass (see table below)

5. GRADUAL increase (25% -> 50% -> 100%)
   └── Same monitoring at each step
   └── Ability to roll back to previous percentage at any point

6. FULL rollout (flag ON for all users)
   └── Monitor for 1 week
   └── Clean up feature flag
```

**Rollout Decision Thresholds** — use these to decide whether to advance, hold, or roll back at each stage:

| Metric | Advance (green) | Hold and investigate (yellow) | Roll back (red) |
|--------|-----------------|-------------------------------|-----------------|
| Error rate | Within 10% of baseline | 10-100% above baseline | >2x baseline |
| P95 latency | Within 20% of baseline | 20-50% above baseline | >50% above baseline |
| Client JS errors | No new error types | New errors at <0.1% of sessions | New errors at >0.1% of sessions |
| Business metrics | Neutral or positive | Decline <5% (may be noise) | Decline >5% |

**When to Roll Back** — roll back immediately if:
- Error rate increases by more than 2x baseline
- P95 latency increases by more than 50%
- User-reported issues spike
- Data integrity issues detected
- Security vulnerability discovered

### Monitoring and Observability

**What to Monitor:**

- Application metrics: error rate (total and by endpoint); response time (p50, p95, p99); request volume; active users; key business metrics (conversion, engagement)
- Infrastructure metrics: CPU and memory utilization; database connection pool usage; disk space; network latency; queue depth (if applicable)
- Client metrics: Core Web Vitals (LCP, INP, CLS); JavaScript errors; API error rates from client perspective; page load time

**Post-Launch Verification** — in the first hour after launch:

```
1. Check health endpoint returns 200
2. Check error monitoring dashboard (no new error types)
3. Check latency dashboard (no regression)
4. Test the critical user flow manually
5. Verify logs are flowing and readable
6. Confirm rollback mechanism works (dry run if possible)
```

### Rollback Strategy

Every deployment needs a rollback plan before it happens:

```markdown
## Rollback Plan for [Feature/Release]

### Trigger Conditions
- Error rate > 2x baseline
- P95 latency > [X]ms
- User reports of [specific issue]

### Rollback Steps
1. Disable feature flag (if applicable)
   OR
1. Deploy previous version: `git revert <commit> && git push`
2. Verify rollback: health check, error monitoring
3. Communicate: notify team of rollback

### Database Considerations
- Migration [X] has a rollback: `npx prisma migrate rollback`
- Data inserted by new feature: [preserved / cleaned up]

### Time to Rollback
- Feature flag: < 1 minute
- Redeploy previous version: < 5 minutes
- Database rollback: < 15 minutes
```

### Documenting the Ship Decision

If running within the `bgpdd-build` or `bgpdd-shipping` pipelines, save your final Rollback Strategy and Launch Checklist to `.docs/{project-name}/implementation/ship-decision.md` with a final `GO` or `NO-GO` recommendation.

The decision certifies **one exact tree state**: record the commit SHA it was taken against and confirm the working tree is clean at the moment of the verdict. Uncommitted changes at verdict time are a `NO-GO`, not a footnote. Any change landing afterward invalidates the artifact — reissue the decision against the new SHA rather than leaving a document that certifies a tree no longer on disk.

**Reconcile against the ledger before you write the verdict, and reproduce it.** The pipeline's persisted state file (`.docs/{project-name}/orchestrator-state.json` or its equivalent) carries the run's open blocker entries; read it and copy **every open entry verbatim** into the decision document. An open entry forces `NO-GO` unless the user has explicitly waived that specific entry, and a waiver is recorded beside the entry it waives — never inferred from silence, an elapsed phase, or another agent's confidence that the item is minor. Writing `blockers: None` asserts that you read the ledger and found it empty; it is never a default value, never a summary of your own view of the build, and never a statement about the blockers *you personally* encountered. The same holds for the checklist beside it: **a verification the checklist never performed is an unperformed check, not a pass** — no aggregate phrasing ("all features, NFRs, and gates complete") converts an absent row into a satisfied one, and a summary sentence that outruns the rows above it is the defect this section exists to prevent.

### See Also

- For security pre-launch checks, see `{PLUGIN_ROOT}/../references/security-checklist.md`
- For performance pre-launch checklist, see `{PLUGIN_ROOT}/../references/performance-checklist.md`
- For accessibility verification before launch, see `{PLUGIN_ROOT}/../references/accessibility-checklist.md`

### Verification

Before deploying:

- [ ] Pre-launch checklist completed (all sections green)
- [ ] Feature flag configured (if applicable)
- [ ] Rollback plan documented
- [ ] Monitoring dashboards set up
- [ ] Team notified of deployment

After deploying:

- [ ] Health check returns 200
- [ ] Error rate is normal
- [ ] Latency is normal
- [ ] Critical user flow works
- [ ] Logs are flowing
- [ ] Rollback tested or verified ready

### Escalate When

- Any Pre-Launch Checklist section cannot be brought green → report to the Orchestrator (manager) with the failing items and a `NO-GO` recommendation.
- A rollout metric crosses a red threshold and rollback fails or its outcome is unclear → halt and escalate to the Orchestrator immediately.
- No viable rollback plan exists (e.g. an irreversible migration) → escalate to the Orchestrator before deploying, not after.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Shipping deep dive](references/shipping-deep-dive.md) — feature-flag and error-reporting code samples (React ErrorBoundary, Express error handler), when to use this skill, the Common Rationalizations table, and red flags.
