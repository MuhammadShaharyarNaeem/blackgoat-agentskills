---
name: cloud-deploy-patterns
description: "Provides the cloud deployment execution contract: a provider-agnostic baseline (pinned versions, least-privilege identities, vault-only secrets, staged deploys, health endpoints, structured logs, build-time integration values) plus AWS and Azure checklists. Use if the project deploys to AWS or Azure. Squad-internal execution contract loaded by agents via their Methodology Dependencies table."
---

# Cloud Deploy Patterns

Provider-agnostic contract first, provider checklist second. Nothing ships with `latest`, wildcard permissions, or secrets outside a vault.

## Worker Execution Contract

This is the operational spine. Follow it as written.

The **Baseline** applies to every deploy, including deploys to no named cloud at all — a single VM, a PaaS, a self-hosted runner. The **Provider Checklists** are read on demand once the target is known; they add to the Baseline and never relax it.

### Baseline — Platform Invariants

- Pin image and runtime versions explicitly — never `latest`, never floating major tags.
- Every service runs under a least-privilege identity scoped to exactly what it uses. Never grant broad access "to be safe".
- Secrets live ONLY in the platform's managed vault. No committed `.env` files, no secrets in pipeline variables or app config.
- Staged deploy: staging → production, with an explicit gate (manual approval or automated verification) between them. No direct-to-production.
- Health and readiness endpoints exist and are wired into the platform's probes/health checks — a deploy that can't prove liveness doesn't roll.
- Logs are structured JSON shipped to the platform aggregator; no unstructured console dumps in production.
- Static integration values (endpoints, resource names, connection topology) are resolved at build/synthesis time, not late-bound at runtime — this matches the Architect's Infrastructure Synthesis rule.
- Every generated infrastructure file carries inline comments explaining what it does, so a human can maintain it without you.

### Baseline — Container Rules

- The Dockerfile base image is pinned to an explicit version, never `latest`.
- Use a multi-stage build wherever the runtime image would otherwise carry build tooling — separate build stage from runtime stage.
- The final stage runs as a **non-root user**. Install health-check and diagnostic utilities as root *before* switching to the non-root user, or the container ships without them.
- Copy only the files the runtime needs; a `.dockerignore` excludes dev dependencies, tests, and anything secret-bearing.
- Declare a `HEALTHCHECK` for production containers, and expose (and document) the correct port.
- `docker-compose.yml` for local development brings up every dependent service (DB, cache, queue), with **every** service image version pinned — no `latest` anywhere in the file.

### Baseline — CI Stage Order

The pipeline config (GitHub Actions, GitLab CI, CircleCI, or the project's platform) runs these mandatory stages, in this order:

1. `lint` — fail fast on syntax and style errors.
2. `test` — the project's full test suite.
3. `build` — compile/bundle the artifact. Inject the required client/frontend environment values **during this compilation stage**; a value the bundle needs at build time cannot be supplied at runtime.
4. `security-scan` — dependency vulnerability scan, configured to evaluate **transitive** dependencies and to exit non-zero on findings.
5. `deploy` — runs only on the release branches (main, release), staging before production.

- **No deploy stage runs if any prior stage fails.** This is non-negotiable.
- Staging deploy and production deploy are separate definitions — different triggers, different configs. Never one job parameterized into both without a gate.
- Where the hosting platform supports them, recommend branch protection rules on the branches the deploy stage watches.

### Baseline — Environment Configuration

- Produce a `.env.example` naming every required variable, each with a comment explaining what it is. Never a populated `.env`.
- Produce environment-specific config files where the framework uses them (e.g. a `production` config).
- Name the secrets store explicitly (Platform Invariants above); an env file committed to the repo is never it.
- Classify every variable **build-time vs. runtime** — the `build` stage above depends on that split being correct.
- List every external service endpoint that needs an environment-specific value: DB URL, API base URL, CDN origin, queue endpoint.

### Baseline — Infrastructure as Code

Applies when the blueprint names a cloud provider; skip when the target is a plain host or PaaS with no IaC surface.

- Generate the provider's IaC form (Terraform, Pulumi, CloudFormation, Bicep) — never a click-path runbook.
- Size resources **conservatively from measured usage** — right-size, don't over-provision.
- Configure auto-scaling with sensible defaults and stated bounds.
- Define networking explicitly: VPC/VNet, security groups, ingress and egress rules.
- Managed database instances are provisioned with **backups enabled**.
- Resolve dynamic values at synthesis time rather than relying on late-bound deployment-time tokens for static properties (Platform Invariants above).

### Baseline — Observability Setup

- Configure structured JSON log output carrying at minimum request ID, timestamp, level, and message.
- Ensure `/health` and `/ready` endpoints exist, and document each one's expected response.
- Wire the error-tracking integration (Sentry, Datadog, or the project's equivalent) when it is in scope.
- Name the key metrics the application emits — request rate, error rate, database query latency — and recommend one alerting rule per metric.

### Baseline — Deploy Verification and Rollback

- The post-deploy verification sequence is owned by `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md` (Monitoring and Observability → *Post-Launch Verification*). Run it from there; do not restate it.
- **Two deploy-specific items are added to that sequence here, deliberately (convention #8 — a narrow extension, not a competing checklist)**: confirm **database migrations applied successfully**, and confirm the **authentication flow works end to end** against the deployed environment. Both are deploy-shaped failures the generic post-launch sequence does not name.
- Rollback timing is owned by `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md` (Rollback Strategy → *Time to Rollback*) across its tiers: feature flag, redeploy of the previous version, database rollback. Cite that tier ladder; never restate a single flat number here.

### Provider Checklist — AWS

- ECS tasks / Lambda functions right-sized from measured usage, not defaults.
- Static assets on S3 behind CloudFront — never served from compute.
- Secrets in Secrets Manager or SSM Parameter Store (SecureString).
- One IAM role per service; policies name explicit actions and resources — no `"Action": "*"`, no `"Resource": "*"`.
- CloudWatch alarms on error rate and p95 latency for every service, wired to notification.

### Provider Checklist — Azure

- App Service / Functions plans right-sized from measured usage.
- Key Vault accessed via Managed Identity — no connection strings or vault credentials in app configuration.
- Static assets and edge routing through Front Door / CDN.
- Application Insights enabled with alert rules on failure rate and latency.
- RBAC role assignments scoped to resource groups (or tighter) — never subscription-wide.

### Verification Checklist

Before marking work complete:

- [ ] All images/runtimes pinned to explicit versions
- [ ] Container final stage runs as a non-root user, with health-check utilities installed before the switch
- [ ] Every service identity holds only the permissions it demonstrably uses
- [ ] Zero secrets in the repo, pipeline definitions, or app config — vault references only
- [ ] `.env.example` covers every required variable, each classified build-time or runtime
- [ ] Pipeline runs lint → test → build → security-scan → deploy, and no deploy runs after a failed stage
- [ ] Deploy pipeline stages staging before production with a gate between
- [ ] Health/readiness endpoints respond and are registered with the platform
- [ ] Logs are structured JSON and visible in the aggregator; alarms/alerts exist on error rate and latency
- [ ] Integration values resolved at build/synthesis time, not runtime discovery
- [ ] Migrations applied and the auth flow verified end to end against the deployed environment

### Escalate When

- The target platform is ambiguous or the blueprint names neither AWS nor Azure → report to the Orchestrator; do not guess.
- A requested permission exceeds least-privilege (wildcards, subscription-wide RBAC, cross-service admin) → report to the Orchestrator; do not grant it.
- A secret already exists in committed history or a required vault is missing → report to the Orchestrator before deploying.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Cloud playbook](references/cloud-playbook.md) — minimal IaC/pipeline snippets per provider (GitHub Actions deploy job shape, IAM role statement, Key Vault + Managed Identity reference, alarm/alert rules) and the per-provider rollback runbook (flag off → redeploy previous → restore).
