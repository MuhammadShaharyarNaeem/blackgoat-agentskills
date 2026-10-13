# Shipping and Launch — Deep Dive

On-demand companion to the shipping-and-launch `SKILL.md` — rationale, code samples, and anti-patterns that support the Worker Execution Contract.

## When to Use

- Deploying a feature to production for the first time
- Releasing a significant change to users
- Migrating data or infrastructure
- Opening a beta or early access program
- Any deployment that carries risk (all of them)

## Feature Flag Check (code sample)

```typescript
// Feature flag check
const flags = await getFeatureFlags(userId);

if (flags.taskSharing) {
  // New feature: task sharing
  return <TaskSharingPanel task={task} />;
}

// Default: existing behavior
return null;
```

## Error Reporting (code samples)

```typescript
// Set up error boundary with reporting
class ErrorBoundary extends React.Component {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // Report to error tracking service
    reportError(error, {
      componentStack: info.componentStack,
      userId: getCurrentUser()?.id,
      page: window.location.pathname,
    });
  }

  render() {
    if (this.state.hasError) {
      return <ErrorFallback onRetry={() => this.setState({ hasError: false })} />;
    }
    return this.props.children;
  }
}

// Server-side error reporting
app.use((err: Error, req: Request, res: Response, next: NextFunction) => {
  reportError(err, {
    method: req.method,
    url: req.url,
    userId: req.user?.id,
  });

  // Don't expose internals to users
  res.status(500).json({
    error: { code: 'INTERNAL_ERROR', message: 'Something went wrong' },
  });
});
```

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It works in staging, it'll work in production" | Production has different data, traffic patterns, and edge cases. Monitor after deploy. |
| "We don't need feature flags for this" | Every feature benefits from a kill switch. Even "simple" changes can break things. |
| "Monitoring is overhead" | Not having monitoring means you discover problems from user complaints instead of dashboards. |
| "We'll add monitoring later" | Add it before launch. You can't debug what you can't see. |
| "Rolling back is admitting failure" | Rolling back is responsible engineering. Shipping a broken feature is the failure. |

## Red Flags

- Deploying without a rollback plan
- No monitoring or error reporting in production
- Big-bang releases (everything at once, no staging)
- Feature flags with no expiration or owner
- No one monitoring the deploy for the first hour
- Production environment configuration done by memory, not code
- "It's Friday afternoon, let's ship it"

## Contract Rationale

Moved from the `SKILL.md` spine so the spine carries only the rules. Each entry names the spine section it explains.

### Requirements rows, not a feature list (*The Pre-Launch Checklist*)

A requirement with no row is not a pass — it is an unperformed check. Enumerate from the requirements document, never from the built feature list: requirements expressed as *qualities* rather than features (accessibility, contrast, performance, theming, responsiveness) are exactly the ones a feature-shaped review cannot see and a generic template silently omits.

### Pre-merge smoke versus deployment health checks (*Pre-Merge Local Runtime Smoke*)

The deployment-time checks this section deliberately does not duplicate are: Infrastructure's *"Health check endpoint exists and responds"*; Staged Rollout step 1's *"Full test suite in staging environment"* and *"Manual smoke test of critical flows"* and step 2's *"Verify deployment succeeded (health check)"*; Post-Launch Verification's *"Check health endpoint returns 200"* and *"Test the critical user flow manually"*; and the after-deploying Verification items *"Health check returns 200"* and *"Critical user flow works"*. Every one of those presupposes a deployed artifact and answers **did the deploy land**. The smoke answers a different question, earlier and cheaper: **does the change work at all when a person runs it** — the question a green in-process test suite cannot answer, and the one that went unasked before merge.

### Baselines carry a window and a sidecar (*Baseline Capture*)

A `touch`ed or hand-typed file at the cited path used to satisfy the baseline citation; the capture wrapper's provenance sidecar is what `check_ship_decision.py --require-baseline` now reads. A number with no window is not a baseline, because "0.4%" over an hour and over a week are different claims. A canary run against no baseline is a canary that cannot fail.

### Deltas need a recorded baseline (*Staged Rollout*)

"Within 10% of baseline" and ">2x baseline" are not thresholds on their own. Read at canary time with no recorded baseline, each one resolves to whatever the person watching the dashboard remembers normal looking like, which is how a regression gets waved through as "about the same".

### Why Post-Launch Verification has an owner and an artifact (*Monitoring and Observability*)

Until it named an owner and a destination it was a list nobody executed: the pipeline's last gate was the ship decision, which is taken *before* the deploy, so nothing downstream ever asked whether the deployed thing worked. A fresh Dep runs it because the Dep who wrote the ship decision already recorded these items as expected-green. An uncited executed line is refused because everything else on it is text a delegate types.

### The rehearsal beats the ladder (*Rollback Rehearsal*)

A written rollback plan is a plan; it is not evidence that anything reverts. Capturing each step separately means the timing and the outcome are recorded by the tool rather than remembered. A feature-flag rollback that measured 6 minutes did not meet the `< 1 minute` rung, and the honest response is to fix the path or re-classify, never to record the ladder's number. The ladder describes rollbacks in general; the rehearsal describes this one.

### Reconciling against the ledger (*Documenting the Ship Decision*)

Uncommitted changes at verdict time are a `NO-GO`, not a footnote; leaving a decision in place after the tree moves leaves a document that certifies a tree no longer on disk. Writing `blockers: None` asserts that you read the ledger and found it empty; it is never a summary of your own view of the build, and never a statement about the blockers *you personally* encountered. No aggregate phrasing ("all features, NFRs, and gates complete") converts an absent row into a satisfied one, and a summary sentence that outruns the rows above it is the defect the section exists to prevent.
