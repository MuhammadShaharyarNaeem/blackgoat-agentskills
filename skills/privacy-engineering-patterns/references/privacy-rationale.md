# Privacy Rationale

Depth for `privacy-engineering-patterns/SKILL.md`. Nothing here is needed to execute the
contract — load it when a rule's bound is being argued with, when choosing between
privacy-preserving techniques, or when a reviewer wants the failure the rule was written
against.

## Why the inventory precedes every other control

Each of the other four controls takes the inventory as input, and degrades to a guess
without it:

- Consent enforcement needs to know **which writes** carry personal data. Without the
  inventory, the gate lands on the three obvious writers and misses the event stream.
- Deletion propagation resolves its fan-out from the inventory. A store absent from the
  table is a store the erasure never visits — and the ACK set still comes back complete,
  because every system that was asked did answer.
- Retention automation needs a per-store clock; a store nobody listed has no clock.
- The data-flow map is the inventory read along its edges rather than its rows.

This is why § 1 insists the inventory is **generated then edited**. A typed inventory
records what the author believes the system stores, and the whole point of the artifact is
to contradict that belief. The stores that show up only in a scan, every time, are: error
and trace payloads, cache keys built by string-concatenating an email, analytics event
properties, and free-text columns (`notes`, `description`, `comment`) that users fill with
government IDs nobody asked for.

Re-running the scan each round is not ceremony. Classification drifts in one direction: a
new column, a new log line, a new vendor. Nothing ever quietly stops holding PII.

## Technique table: what you actually have

"Anonymized" is a claim about a transformation, not a label you may apply to an output.

| Technique | Reversible? | Re-identification risk | Use when |
|---|---|---|---|
| Pseudonymization (tokenized id, mapping kept) | Yes, with the mapping | Real if the mapping leaks — still personal data under GDPR | Internal processing where re-linking is required |
| Encryption | Yes, with the key | Protected at rest and in transit; key management is the whole control | Storage and transport of PII that must stay usable |
| Aggregation / k-anonymity | No | Low when k and the quasi-identifier set are both handled | Reporting, dashboards, group-level sharing |
| Differential privacy | No | Provably bounded by the privacy budget | Statistics or ML training over sensitive data needing a formal guarantee |
| "Removed the name" | No | **High** — quasi-identifiers re-identify | Never; this is not anonymization |

The row that costs companies money is the last one. Zip code, birth date and gender
together identify most of a population; an export carrying that trio is pseudonymous at
best and still fully regulated. Test the re-identification risk before the label goes on,
not after the dataset is shared.

## The failure narratives behind each rule

**The missed analytics replica.** An erasure pipeline deleted from the primary, and every
downstream system ACKed the request it was sent. The warehouse replica was never sent one,
because it was not in anybody's model of the system. Nothing failed; the request was simply
never addressed to it. This is the reason § 3 resolves locations from the inventory and
closes on a **re-query** rather than the ACK set: an ACK proves a system answered the
question it was asked, and the missing store was never asked.

**The consent flag nobody read.** The preference was captured, stored, versioned, and shown
back to the user correctly. The analytics writer never looked at it. Every part of the
feature worked except the one that was the control. Hence § 2's insistence that the
enforcement point is the write site — the reader and the storage are not controls, and a
test that asserts the flag is stored asserts nothing about enforcement.

**Reject, do not log.** The near-miss variant of the same bug: the writer *did* check, found
no basis, emitted a warning, and wrote anyway. The warning was in the logs for months. A
control that proceeds after noticing is not a control, and this is the specific reason the
rule is phrased as rejection rather than validation.

**The free-text SSN.** Discovery found government IDs in a support-ticket `notes` column.
No schema named them, no classifier expected them, and no retention rule covered them. This
is the `UNCLASSIFIED` row in § 1: a field the scan found and nobody can classify is a
finding, because omitting it makes the inventory look finished.

## Consent enforcement, worked

The shape, stack-neutral — the point is where the check sits, not the language:

```
write_event(user, event):
    basis = consent.lookup(user.id, purpose="analytics")   # purpose-scoped, versioned
    if basis is absent:
        reject                       # not "log and continue"
    vendor.write(pseudonymize(user.id), event)   # pseudonymized before the boundary
```

Three properties make this testable, and the `consent-write-path` check exercises exactly
them: the lookup is purpose-scoped (so revoking analytics does not revoke marketing), the
absent case rejects (so the test has an observable outcome), and pseudonymization happens
before egress (so the vendor never holds the raw identifier).

## Deletion orchestration, worked

```
erasure_request(subject S):
    targets  = inventory.stores_holding(S)          # resolved, never recalled
    for each target: dispatch idempotent delete job, with retry
    collect ACKs, track partial progress
    re-query S across every target        <-- the evidence; capture THIS
    audit record: deleted what, from where, when, elapsed vs SLA
    exclusions: each retained store with its legal basis
```

Idempotency matters because retries are certain and a second delete must be a no-op rather
than an error that reads as a failure. Backups usually cannot be rewritten in place: the
accepted pattern is a tombstone plus a delete-on-restore policy, and the audit record says
so explicitly rather than letting the backup row read as deleted.

The exclusions list is what makes the record honest. A store retained under a financial
record-keeping obligation and a store the pipeline forgot look identical from the outside
unless one of them is named.

## Retention: why a stated period is not a control

A retention rule written in a schema comment, a policy document, or a wiki page is a
statement of intent. The data is deleted by a job or it is not deleted. § 4 therefore asks
for three things — the job, its cadence, and its **last successful run** — because a
scheduled job that has been failing silently for a quarter produces exactly the same
configuration as one that works, and only the run record tells them apart.
