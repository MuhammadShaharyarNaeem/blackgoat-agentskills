# Observability manifest template

The shape referenced by *The Three Signals, Named Per Service* in `../SKILL.md`.

## Where it lives

The `## Observability manifest` block is a section, not a file of its own:

| Situation | Where the block goes |
|---|---|
| Brownfield, discovered | `.docs/summary/{feature}/QA/runtime-environment.md` — beside the bring-up facts a probe already needs |
| Greenfield, designed | `.docs/{project-name}/implementation/environment-manifest.md` |

Both are the environment-manifest paths owned by
`{PLUGIN_ROOT}/runtime-evidence/SKILL.md`; this block is an addition to that file, never a
competing second copy. When both files exist, the Tier-1 recipe wins and the Tier-2 file
carries deltas only — that precedence is runtime-evidence's, unchanged.

## Rules

- **One row per service**, named as the service names itself in the estate — the name in the
  deploy manifest, not a prose description.
- **A query surface, not a vendor.** "Datadog" is not a query surface; `service:orders-api
  env:prod` in the `orders-*` index is. The test: could a responder paste this into
  something and get results?
- **`none` is a legitimate value and must be written.** A blank cell reads as *nobody filled
  this in* and gets silently trusted; `none` reads as *this service emits no traces*, which
  a reviewer can challenge and an incident can cite. This is the same reasoning
  `runtime-evidence`'s `[vs:none]` uses for verification surfaces.
- **The correlation-id field name is per-service and recorded.** `X-Correlation-Id`,
  `traceparent`, `X-Request-Id` — a responder grepping for the wrong key finds nothing and
  concludes the id is absent.
- No agent fills a gap in this block from convention. An index name you would have to infer
  from a config file is caller-supplied context, escalated, not guessed — the same rule
  `runtime-evidence` applies to start commands and base URLs.

## Template

```markdown
## Observability manifest

| Service | Logs (sink + query) | Metrics (dashboard + key metric) | Traces (backend + entry) | Correlation id field |
|---|---|---|---|---|
| <service-name> | <sink / index> — `<query>` | <dashboard> — `<metric name>` | <backend> — `<service or entry span>` | `<header name>` |
| <service-name> | <sink / index> — `<query>` | <dashboard> — `<metric name>` | none | `<header name>` |

### Retention
- Logs: <duration>
- Metrics: <duration, and at what resolution after downsampling>
- Traces: <duration, and the sampling rate>

### Known gaps
- <service>: <which signal is missing, and what a diagnosis has to do instead>
```

## Retention is part of the manifest

A signal that exists but has already aged out cannot answer *when did this start?* —
which is exactly the intake's **First seen** field. Recording retention next to the query
is what lets a responder tell "it did not happen before Tuesday" from "we cannot see
before Tuesday". Those two conclusions look identical in a dashboard and lead to opposite
fixes.

Trace sampling belongs here for the same reason: at 1% sampling, the absence of a trace
for one failing request is not evidence of anything.

## Known gaps

The section exists so that a gap is *stated once, in the place a diagnosis starts* — rather
than rediscovered per incident. A gap listed here is also the input to the contract's
escalation: no telemetry for the failing path means instrumentation first, routed to
`/bgpdd-lite`, before diagnosis proceeds.
