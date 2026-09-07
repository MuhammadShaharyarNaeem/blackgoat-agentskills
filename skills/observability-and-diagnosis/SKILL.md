---
name: observability-and-diagnosis
description: "Provides the observability execution contract: a correlation id on every request and job, the three signals named per service in an observability manifest, an alert that names its runbook and a runbook that names its first three reads, diagnosis that starts from telemetry rather than from code, and incidents that convert into a lint-gated bug report. Use if the project runs a service anyone has to diagnose in production. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Also directly invocable: when a user asks for this on named files outside a pipeline, the Orchestrator applies the Worker Execution Contract itself in the main session — no delegation."
---

# Observability and Diagnosis

The cost of an incident is set long before it happens, by whether the failing path emitted anything. Diagnosis that starts by reading code is a search of everything the system *could* have done; diagnosis that starts from telemetry is a search of what it *did*.

## Direct invocation

A user can ask for this directly on named files outside a pipeline — a deliberate refinement of agent-audit Metric 12, not a trigger collision. The Orchestrator applies the Worker Execution Contract below inline, in the main session: no delegation, no claim without a capture (`base-persona.md`, Evidence Integrity). **Scope: three files or fewer.** Over three files, or new signal wiring: route through `/bg`.

## Quick card

Derived from the contract below for a ≤ 3-file change; no new rules (convention #8 — deliberately narrower than the full contract, which binds inside any lane).

1. Accept the inbound `X-Correlation-Id`; generate only when absent; log it on every line (§ A Correlation Id on Every Request and Job).
2. Each manifest row gains a query surface or an explicit `none` (§ The Three Signals, Named Per Service).
3. The alert names its runbook; the runbook names three concrete reads (§ Alert → Runbook → Root Cause).
4. Observe the failing execution before opening a source file (§ Diagnose From Telemetry, Not From Code).
5. An incident's output is the lint-gated bug report (§ Every Incident Produces a Bug Report).

- Brief → the quick note (What / Where / How verified)
- Artifact → the capture at `{quick-root}/evidence/check.md`
- Handoff → the `## Result` bullet in `note.md`

## Worker Execution Contract

This is the operational spine. Follow it as written.

### Scope, and What This Skill Does Not Own

Two neighbours own adjacent ground; cite them, never restate them:

- `{PLUGIN_ROOT}/cloud-deploy-patterns/SKILL.md` (*Baseline — Observability Setup*) owns **provisioning**: structured JSON log output, `/health` and `/ready`, error-tracking wiring, one alerting rule per key metric.
- `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md` (*Monitoring and Observability*, *Baseline Capture*) owns **what to watch at launch** and the rollout threshold numbers.

This skill owns the space between: the identifier that ties a failure together, the per-service signal inventory, the path from alert to root cause, and the handoff from incident into the bugfix lane.

### A Correlation Id on Every Request and Job

Every inbound request, message, and scheduled job run carries a correlation id, and every log line it produces includes it. This **extends** `cloud-deploy-patterns`'s structured-log baseline, which requires a per-request id — deliberately wider (convention #8): the id must survive **across** process boundaries, not just within one request.

- **The canonical tokens are `X-Correlation-Id` on the wire and `correlation_id` in a log line, a run record and the manifest.** A project using a different token declares it once in the manifest's *Correlation id field* column; leaving it unnamed is the failure ([manifest-template.md](references/manifest-template.md)).
- Accept an inbound id from the caller's header when present; generate one when absent. Never generate a second id for a request that already had one.
- Propagate it outward on every downstream call, published message, and outbox row.
- A background job's run record carries it (`{PLUGIN_ROOT}/jobs-and-messaging-patterns/SKILL.md`), so a queued effect is traceable back to the request that caused it.
- Never put a secret or personal data in the id, and never reuse a business identifier as one.

### The Three Signals, Named Per Service

The project records a `## Observability manifest` block naming, **for each service**, all three of **logs, metrics and traces** and where each is actually read. Each row names the query surface — which log index, which dashboard, which trace backend — not just the vendor: a signal nobody can name the query for is not available.

**A missing signal is recorded as missing, never left blank.** `none` is a reviewable claim; a blank row reads as an oversight and is silently trusted. What each signal answers and cannot answer, and the block's shape: [`references/manifest-template.md`](references/manifest-template.md).

### Alert → Runbook → Root Cause

- **Every alert names its runbook.**
- **Every runbook names its first three reads**: *which log query*, *which metric*, *which trace* — actual query strings and dashboard names, not "check the logs". Three, not fifteen: the point is removing the decision of where to start.
- After those three reads, root-causing proceeds under `{PLUGIN_ROOT}/debugging-and-error-recovery/SKILL.md`, which owns the method. This skill adds nothing to it.
- A step that resolves the symptom without identifying the cause is labelled **mitigation**, not fix, and leaves the incident open.

Shape: [`references/runbook-template.md`](references/runbook-template.md).

### Diagnose From Telemetry, Not From Code

When a production behaviour is wrong, the first artifact read is **telemetry for the failing execution** — the log lines carrying its correlation id, its trace, the metric that moved. The order is: observe what happened → reproduce it → then read the code the evidence points at.

A production claim supported only by source reading is one-directional evidence: it can *fail* a hypothesis, never *pass* one (`{PLUGIN_ROOT}/runtime-evidence/SKILL.md`, Core Principle).

### Every Incident Produces a Bug Report

An incident's output is the intake artifact `/bgpdd-bugfix` Phase 0 lints, filled from telemetry rather than memory. The field names below are the template's own:

| Intake field | Copied from |
|---|---|
| **Observed behaviour** | The alert's condition and affected requests — behaviour only, no diagnosis |
| **Exact error text or log excerpt** | The verbatim log lines or stack trace, uncut, carrying the correlation id |
| **Environment** — `Repository / branch`, `Version or commit`, `Runtime / OS`, `How it was run` | What the failing instance reported: where it was deployed from, at what version, on what runtime, started how |
| **`Regression` / `Last known good`** | The earliest timestamp the signal shows the behaviour, resolved to a commit, tag or date |

Field rules and the gate are owned by `{PLUGIN_ROOT}/bgpdd-bugfix/references/bug-report-template.md`; the intake is still linted by `check_bugfix_intake.py` when the fields came from an alert. A pre-filled report is a convenience, never an exemption.

### Verification

The proof that a path is observable is **a log line carrying its correlation id, read out of process**:

1. Start the service the way it runs, per the environment manifest (`{PLUGIN_ROOT}/runtime-evidence/SKILL.md`).
2. Drive the path with a known correlation id — send it on the inbound `X-Correlation-Id` header rather than hunting a generated one afterwards.
3. Read the line back **from where the manifest says logs are read** — the log sink, not the process's own stdout buffer inside the test host.
4. Capture it with `python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture <path> -- <command>`.
5. Cite it with the `**Runtime evidence:**` line whose grammar is owned by `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`.

An assertion that the logging call exists is not evidence the line reaches the sink — the gap between a logger and a log.

### Verification Checklist

Before marking observability work complete:

- [ ] Every inbound request, message and job run carries a correlation id, accepted from the caller when present
- [ ] The manifest names the correlation-id token, and it is the same token every service uses
- [ ] The id appears on every log line of that execution and propagates to downstream calls and published messages
- [ ] The `## Observability manifest` block names all three signals per service, each with a query surface or an explicit `none`
- [ ] Every alert names its runbook; every runbook names its first three reads as concrete queries
- [ ] A log line carrying a known correlation id was read back from the real sink, captured and cited
- [ ] Any incident handled has produced a lint-passing bug report

### Escalate When

- **The failing path emits no telemetry at all** — no log line, no metric, no span. The fix is **instrumentation first**: report it to the Orchestrator as a finding, which routes the instrumentation work; never reason from source alone about a production failure.
- The manifest names a signal the project does not actually have, or names none for a service being diagnosed → report the gap to the Orchestrator; do not infer a query surface from a config file.
- Logs are reachable only through a shared dev or staging sink you cannot attribute to the local run → `BLOCKED`, naming what was missing, per `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`.
- A runbook's first three reads no longer resolve (renamed dashboard, deleted index) → report it as a defect in the runbook, not as an incident finding.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Runbook template](references/runbook-template.md) — the alert-to-runbook binding, the first-three-reads block, mitigation-versus-fix, and what a runbook must not contain.
- [Manifest template](references/manifest-template.md) — the `## Observability manifest` block, per-service rows, where it lives, and how a `none` row is reviewed.
