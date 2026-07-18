---
name: cloud-deploy-patterns
description: "Provides the cloud deployment execution contract: a provider-agnostic baseline (pinned versions, least-privilege identities, vault-only secrets, staged deploys, health endpoints, structured logs, build-time integration values) plus AWS and Azure checklists. Use if the project deploys to AWS or Azure. Squad-internal execution contract loaded by agents via their Methodology Dependencies table."
---

# Cloud Deploy Patterns

Provider-agnostic contract first, provider checklist second. Nothing ships with `latest`, wildcard permissions, or secrets outside a vault.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### Provider-Agnostic Contract (applies before any provider choice)

- Pin image and runtime versions explicitly — never `latest`, never floating major tags.
- Every service runs under a least-privilege identity scoped to exactly what it uses. Never grant broad access "to be safe".
- Secrets live ONLY in the platform's managed vault. No committed `.env` files, no secrets in pipeline variables or app config.
- Staged deploy: staging → production, with an explicit gate (manual approval or automated verification) between them. No direct-to-production.
- Health and readiness endpoints exist and are wired into the platform's probes/health checks — a deploy that can't prove liveness doesn't roll.
- Logs are structured JSON shipped to the platform aggregator; no unstructured console dumps in production.
- Static integration values (endpoints, resource names, connection topology) are resolved at build/synthesis time, not late-bound at runtime — this matches the Architect's Infrastructure Synthesis rule.

### AWS Checklist

- ECS tasks / Lambda functions right-sized from measured usage, not defaults.
- Static assets on S3 behind CloudFront — never served from compute.
- Secrets in Secrets Manager or SSM Parameter Store (SecureString).
- One IAM role per service; policies name explicit actions and resources — no `"Action": "*"`, no `"Resource": "*"`.
- CloudWatch alarms on error rate and p95 latency for every service, wired to notification.

### Azure Checklist

- App Service / Functions plans right-sized from measured usage.
- Key Vault accessed via Managed Identity — no connection strings or vault credentials in app configuration.
- Static assets and edge routing through Front Door / CDN.
- Application Insights enabled with alert rules on failure rate and latency.
- RBAC role assignments scoped to resource groups (or tighter) — never subscription-wide.

### Verification Checklist

Before marking work complete:

- [ ] All images/runtimes pinned to explicit versions
- [ ] Every service identity holds only the permissions it demonstrably uses
- [ ] Zero secrets in the repo, pipeline definitions, or app config — vault references only
- [ ] Deploy pipeline stages staging before production with a gate between
- [ ] Health/readiness endpoints respond and are registered with the platform
- [ ] Logs are structured JSON and visible in the aggregator; alarms/alerts exist on error rate and latency
- [ ] Integration values resolved at build/synthesis time, not runtime discovery

### Escalate When

- The target platform is ambiguous or the blueprint names neither AWS nor Azure → report to the Orchestrator; do not guess.
- A requested permission exceeds least-privilege (wildcards, subscription-wide RBAC, cross-service admin) → report to the Orchestrator; do not grant it.
- A secret already exists in committed history or a required vault is missing → report to the Orchestrator before deploying.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Cloud playbook](references/cloud-playbook.md) — minimal IaC/pipeline snippets per provider (GitHub Actions deploy job shape, IAM role statement, Key Vault + Managed Identity reference, alarm/alert rules) and the per-provider rollback runbook (flag off → redeploy previous → restore).
