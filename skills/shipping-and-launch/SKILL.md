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

#### Pre-Merge Local Runtime Smoke

**Vera-owned. Pre-merge, local.** Run from a clean checkout of the branch under review, before it merges — not after a deploy, and not against a shared staging host. In `bgpdd-shipping` this section is part of Vera's Stage 1 assignment alongside Code Quality, Performance, and Accessibility.

- [ ] The application starts from a clean checkout using the start command **declared in the plan** — never one you inferred; a milestone with no declared start command is a planning defect to escalate, not a blank to fill
- [ ] Every endpoint the epic touched returns its declared response envelope, observed from outside the process
- [ ] The contract surface (OpenAPI/Swagger) is reachable, wherever the stack exposes one
- [ ] In a multi-service estate, every service's configuration is repointed at local URLs, and the manifest records which service was reached at which URL

The tier ladder, the out-of-process probe, the capture artifact and the `**Runtime evidence:**` citation that carries it are owned by `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` — read it before running this section; none of it is restated here. An item whose precondition is absent (the app will not start, the environment cannot be repointed, the transport is unavailable) is `BLOCKED` naming what was missing, never `PASS`.

**Deliberate divergence (convention #8) from the deployment-time health checks in this same file.** Those are Dep's, they run against a deployed environment, and this section neither replaces nor duplicates them: Infrastructure's *"Health check endpoint exists and responds"*; Staged Rollout step 1's *"Full test suite in staging environment"* and *"Manual smoke test of critical flows"* and step 2's *"Verify deployment succeeded (health check)"*; Post-Launch Verification's *"Check health endpoint returns 200"* and *"Test the critical user flow manually"*; and the after-deploying Verification items *"Health check returns 200"* and *"Critical user flow works"*. Every one of those presupposes a deployed artifact and answers **did the deploy land**. This section answers a different question, earlier and cheaper: **does the change work at all when a person runs it** — the question a green in-process test suite cannot answer, and the one that went unasked before merge.

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
- [ ] Database migrations applied (or ready to apply) — execution contract: `{PLUGIN_ROOT}/database-migration-patterns/SKILL.md`
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

Ship behind feature flags to decouple deployment from release. **The flag contract itself — declaration fields, owner, `expiry`/`review`, the removal task, default-off, fail-to-safe, config-as-code, both branches tested, no nesting — is owned by `{PLUGIN_ROOT}/feature-flag-patterns/SKILL.md`. Read it there; the rules are deliberately not restated here.** This section owns only the **rollout staging** and what this checklist runs at ship time.

**Rollout staging (this skill's half):**

```
1. DEPLOY with flag OFF     → Code is in production but inactive
2. ENABLE for team/beta     → Internal testing in production environment
3. GRADUAL ROLLOUT          → 5% → 25% → 50% → 100% of users
4. MONITOR at each stage    → Watch error rates, performance, user feedback (§ Staged Rollout)
5. CLEAN UP                 → The removal task written at creation time runs
```

**Ship-time flag rows.** Both are mandated commands, not judgement calls (convention #9):

- [ ] The `expiry` scan ran and its capture was read:

```bash
python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py \
    --capture .docs/{project-name}/implementation/evidence/shipping/flag-expiry.md \
    -- grep -rnE "expiry:|review:" <the committed flag config path>
```

  Every date the capture shows **at or before the ship date** is a plan-level blocker per `feature-flag-patterns` (*Expiry is a blocker*). Reading the config in your head is not this row.

- [ ] The flag-debt review ran over the same capture — the three questions in `{PLUGIN_ROOT}/feature-flag-patterns/references/flag-lifecycle.md` (*The flag-debt review*) — and its output is recorded as findings, not fixes.

> **Cleanup timing — deliberate refinement of `feature-flag-patterns`' per-flag `expiry` (convention #8).** That skill's clock is the date chosen at declaration and is the binding one. This checklist adds a **ceiling on top of it**: a flag still present two weeks after reaching 100 % rollout is a finding at the next shipping run even when its declared `expiry` has not arrived. The tighter of the two applies; neither replaces the other.

### Baseline Capture

**Dep-owned. Before the first rollout step, not during it.** Read the current production values of three metrics from the project's monitoring source and save each reading as its own artifact under `.docs/{project-name}/implementation/evidence/baseline/`:

1. **Error rate** — total, over a stated window
2. **P95 latency** — on the endpoint or flow this release touches
3. **One business metric** — the one this release is meant to move or must not harm (conversion, sign-ups, session length, messages sent)

Then list all three under a `## Baseline` heading in `.docs/{project-name}/implementation/ship-decision.md`, one per line, in the form `- <metric>: <value> — evidence: <path under evidence/baseline/>`. State the source and the window in each artifact; a number with no window is not a baseline, because "0.4%" over an hour and over a week are different claims.

A metric you cannot read is `BLOCKED`, named — never a remembered value and never an estimate from the last release. Where the project exposes no monitoring source at all, that is an Infrastructure gap to escalate before rollout, not a blank to fill: the Rollout Decision Thresholds table above cannot be applied without these three readings, and a canary run against no baseline is a canary that cannot fail.

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

**Every cell of that table is a delta against a baseline, so the table is unusable until the baseline exists.** "Within 10% of baseline" and ">2x baseline" are not thresholds on their own; read at canary time with no recorded baseline, each one resolves to whatever the person watching the dashboard remembers normal looking like, which is how a regression gets waved through as "about the same". Capture the baseline first — see Baseline Capture below — and cite it in the ship decision.

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
6. Compare each Baseline metric against the Rollout Decision Thresholds table
```

**Owner and artifact — this checklist is Dep's, it runs against the *deployed* environment, and it produces a report.** Until it named an owner and a destination it was a list nobody executed: the pipeline's last gate was the ship decision, which is taken *before* the deploy, so nothing downstream ever asked whether the deployed thing worked.

- **Who**: Dep, freshly delegated after the deploy or merge lands — not the Dep who wrote the ship decision, whose context already recorded these items as expected-green.
- **Where**: the deployed environment (production, or whichever environment the user named at deploy time). Every runtime probe is captured out-of-process via `python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture .docs/{project-name}/implementation/evidence/runtime/<name>.md -- <the probe>`, per `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`, and cited by path in the line it backs.
- **What**: `.docs/{project-name}/implementation/post-deploy-report.md`, one line per numbered item above, in the check-line grammar the pipelines parse:

  `- <check>: PASS|FAIL|BLOCKED|NOT RUN — exit <N> — <detail> — capture: evidence/runtime/<file>.md`

  ending in a single `**Verdict:** Pass` or `**Verdict:** Fail` line. A `PASS` or `FAIL` line cites its exit code **and** the `run_quiet.py --capture` artifact whose sidecar recorded that same exit code — an uncited executed line is refused (`check_uncaptured`), because everything else on it is text a delegate types; a `BLOCKED` or `NOT RUN` line gives a reason and cites nothing. The grammar authority is `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` (`check_agent_report.py`) — it is the same grammar as the Security and Verification reports, deliberately, so one parser reads all three.
- **Item 6 is graded, not eyeballed**: each Baseline metric captured before rollout is re-read from the same monitoring source and compared against the Rollout Decision Thresholds table. Red on any row is a `FAIL`, and a `FAIL` verdict is a rollback decision — execute the Rollback Steps within the rehearsed Time to Rollback, then escalate.

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
- Migration [X] rolls back via a tested forward migration:
  `dotnet ef migrations script --idempotent --from <target> --to <previous>`, reviewed and rehearsed on non-prod
  (never a down-migration in production — `{PLUGIN_ROOT}/database-migration-patterns/SKILL.md`)
- Data inserted by new feature: [preserved / cleaned up]

### Time to Rollback
- Feature flag: < 1 minute
- Redeploy previous version: < 5 minutes
- Database rollback: < 15 minutes
```

### Rollback Rehearsal

**Dep-owned. Before the GO, not after the incident.** A written rollback plan is a plan; it is not evidence that anything reverts. Perform the revert **and** the health check that proves the revert landed, timed, on a non-production environment, and record what it actually took.

1. **Run it end to end on a non-production environment** — the same command sequence the Rollback Steps above name, with the health check as the last command in the sequence so a revert that leaves the service down cannot record as a success.
2. **Capture the run**, so the timing and the outcome are recorded by the tool rather than remembered by you:
   `python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture .docs/{project-name}/implementation/evidence/rollback/<date>-rehearsal.md -- <the revert command sequence, health check included>`
3. **Record the result in `ship-decision.md`** on one line, in exactly this grammar:

   `Time to Rollback: <N><unit> — rehearsed <YYYY-MM-DD> on <env> — evidence: <path under evidence/rollback/>`

   `<unit>` is `s`/`sec`/`seconds` or `m`/`min`/`minutes`; either separator may be an em dash, en dash, or hyphen; `<env>` names where you ran it. The pipelines read this line mechanically via `check_ship_decision.py --require-rehearsal`; the grammar authority is `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
4. **The recorded time must fit the Time to Rollback ladder above for the rollback type this release uses** — a feature-flag rollback that measured 6 minutes did not meet the `< 1 minute` rung, and the honest response is to fix the rollback path or re-classify the release's rollback type, never to record the ladder's number instead of the measured one.

**Deliberate refinement of the Time to Rollback ladder (convention #8).** That ladder is a planning estimate — the expected cost of each rollback type. This section makes the *measured* value binding: where the two disagree, the rehearsal wins, because the ladder describes rollbacks in general and the rehearsal describes this one.

A rehearsal you could not perform is `BLOCKED`, naming what was missing (no non-production environment, no revert path, an irreversible migration) — see Escalate When. It is never a `PASS`, and a plan alone is never a rehearsal.

### Documenting the Ship Decision

If running within the `bgpdd-build` or `bgpdd-shipping` pipelines, save your final Rollback Strategy and Launch Checklist to `.docs/{project-name}/implementation/ship-decision.md` with a final `GO` or `NO-GO` recommendation. A **launch** decision additionally carries the `Time to Rollback:` line from Rollback Rehearsal and the `## Baseline` section from Baseline Capture; a **prep** decision written at `bgpdd-build` Phase 5 legitimately carries neither, because neither has happened yet. **Put that verdict on a line beginning `Ship Decision`, `Verdict`, or `Recommendation`** (leading `#`, `>`, `-`, or `*` markers are tolerated), with the `GO` or `NO-GO` token on that same line, and state one verdict per section — a section asserting both is rejected as ambiguous. The pipelines read this line mechanically via `check_ship_decision.py`; the grammar authority is `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.

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
- [ ] Rollback **rehearsed** — performed and timed on a non-production environment, its capture written under `evidence/rollback/`, and its `Time to Rollback:` line recorded in `ship-decision.md` (see Rollback Rehearsal)
- [ ] Baseline captured — three metrics read from the monitoring source into `evidence/baseline/` and listed under `## Baseline` in `ship-decision.md` (see Baseline Capture)
- [ ] Monitoring dashboards set up
- [ ] Team notified of deployment

After deploying:

- [ ] Health check returns 200
- [ ] Error rate is normal — compared against the captured Baseline, not against memory
- [ ] Latency is normal — compared against the captured Baseline
- [ ] Critical user flow works
- [ ] Logs are flowing
- [ ] Post-Launch Verification executed against the deployed environment and written to `post-deploy-report.md` with a machine-read `**Verdict:**` line

### Escalate When

- Any Pre-Launch Checklist section cannot be brought green → report to the Orchestrator (manager) with the failing items and a `NO-GO` recommendation.
- A rollout metric crosses a red threshold and rollback fails or its outcome is unclear → halt and escalate to the Orchestrator immediately.
- No viable rollback plan exists (e.g. an irreversible migration) → escalate to the Orchestrator before deploying, not after.
- The rollback cannot be rehearsed (no non-production environment, no revert path) or the rehearsal fails → report the rehearsal `BLOCKED`/`FAIL` with a `NO-GO`; do not record a ladder estimate as a measured time.
- No monitoring source exposes one of the three Baseline metrics → escalate as an Infrastructure gap before rollout; the threshold table cannot grade a canary without it.
- The Post-Launch Verification report's verdict is `Fail` → this is a live production defect: execute the Rollback Steps within the rehearsed Time to Rollback and escalate to the Orchestrator immediately, in that order.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Shipping deep dive](references/shipping-deep-dive.md) — feature-flag and error-reporting code samples (React ErrorBoundary, Express error handler), when to use this skill, the Common Rationalizations table, and red flags.
