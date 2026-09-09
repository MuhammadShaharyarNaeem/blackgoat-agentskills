# Runbook template

The shape referenced by *Alert → Runbook → Root Cause* in `../SKILL.md`. One runbook per
alert. Copy it; replace every `<...>`.

## The binding

An alert and its runbook are a pair. The alert definition carries the runbook's location
in its own payload (annotation, description, notification body) so the link arrives with
the page, at 3 a.m., in the notification the responder is already looking at. A runbook
that exists but is not linked from the alert is a wiki page nobody finds under pressure.

If an alert has no runbook, the correct move is to delete the alert or write the runbook —
an alert nobody knows how to answer trains people to ignore alerts, which costs more than
the alert was ever worth.

## Why exactly three first reads

The runbook's job at minute zero is to remove **one** decision: where to look first. Three
reads — one per signal — is enough to place the failure (is it happening at all, how
widely, and where in the call path) and small enough that nobody triages the list itself.
A fifteen-step diagnostic tree restores the decision it was written to remove.

After the three reads, root-causing belongs to
`{PLUGIN_ROOT}/debugging-and-error-recovery/SKILL.md`. Do not fork its method here.

## Mitigation is not a fix

Restarting the pod, draining the queue, flipping the flag, scaling out: each of these can
be the right first action and none of them identifies a cause. Label them **Mitigation**
and keep the incident open until the cause is named. A runbook whose steps are all
mitigations is a runbook that guarantees the incident recurs.

## What a runbook must not contain

- **Credentials, tokens, or connection strings.** Name where the credential comes from, per
  `{PLUGIN_ROOT}/security-and-hardening/SKILL.md`; never the value.
- **A destructive step with no confirmation and no rollback** — a data deletion, a queue
  purge, a forced schema change. If a step can lose data, say what backs it up first.
- **"Check the logs"** with no query. That sentence is the absence of a runbook wearing one.
- **A dashboard named only by vendor** ("check Datadog"). Name the dashboard or the query.

## Template

```markdown
# Runbook: <alert name, verbatim as the alert fires it>

## What this alert means
<One or two sentences. What condition fired, and what a user is experiencing while it
holds. Never the suspected cause.>

## Severity and who to tell
- Severity: <sev level>
- Notify: <role or channel, and at what point>

## First three reads
1. **Log query** — `<the actual query string, in the query language of the named sink>`
   in `<log index / sink>`. Looking for: <what a bad result looks like>.
2. **Metric** — `<metric name>` on `<dashboard name>`, window `<duration>`.
   Looking for: <the shape that confirms or rules out this alert's condition>.
3. **Trace** — `<trace search or service map view>` in `<trace backend>`, filtered by
   `<correlation id | service | error status>`. Looking for: <which hop the time or the
   failure lands in>.

## What each result tells you
| Reads say | Most likely | Go to |
|---|---|---|
| <observation> | <cause class> | <mitigation step or hand-off> |
| <observation> | <cause class> | <mitigation step or hand-off> |

## Mitigations (symptom only — the incident stays open)
1. <step> — reversible by <how>
2. <step> — reversible by <how>

## Root cause
Hand off to `{PLUGIN_ROOT}/debugging-and-error-recovery/SKILL.md`. The correlation ids
gathered above are the reproduction's starting point.

## Produce the bug report
Fill the intake at `{PLUGIN_ROOT}/bgpdd-bugfix/references/bug-report-template.md` from the
telemetry read above — observed behaviour, exact error text, environment, first seen — and
run it through `check_bugfix_intake.py`. Pre-filled from an alert is still linted.

## Last verified
- Date: <when the three reads were last confirmed to resolve>
- By: <who>
```

## Keeping it true

A runbook rots faster than code, because its references (index names, dashboards, query
syntax) live outside the repository and change without a diff. The `Last verified` line
is the cheapest available defence: a runbook whose three reads no longer resolve is a
defect **in the runbook**, reported as such, not a finding about the incident.
