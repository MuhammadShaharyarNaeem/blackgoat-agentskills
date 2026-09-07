---
name: jobs-and-messaging-patterns
description: "Provides the background jobs and messaging execution contract: an idempotency key on every handler, at-least-once delivery assumed, bounded retries with backoff, poison-message routing to a dead letter with the payload preserved, the outbox pattern instead of a dual write, ordering assumptions stated explicitly, and a readable run record per scheduled job. Use if the project runs background jobs, queues, schedulers, or message consumers. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Also directly invocable: when a user asks for this on named files outside a pipeline, the Orchestrator applies the Worker Execution Contract itself in the main session — no delegation."
---

# Jobs and Messaging Patterns

A request that fails is retried by a person who sees the error. A message that fails is retried by a broker that does not, and it will deliver the same payload again while the first attempt is still running. Every rule below follows from that one fact.

## Direct invocation

A user can ask for this directly on named files outside a pipeline — a deliberate refinement of agent-audit Metric 12, not a trigger collision. The Orchestrator applies the Worker Execution Contract below inline, in the main session: no delegation, no claim without the replay capture (`base-persona.md`, Evidence Integrity). **Scope: three files or fewer.** Over three files, or a new queue: route through `/bg`.

## Quick card

Derived from the contract below for a ≤ 3-file change; no new rules (convention #8 — deliberately narrower than the full contract, which binds inside any lane).

1. Message id or business key, recorded in the effect's transaction (§ Idempotency Key on Every Handler).
2. Retries bounded and backed off; a permanent failure dead-letters on attempt one (§ Retries With Backoff, Bounded).
3. Dead-letter the payload intact — never log-and-drop (§ Poison Messages Go to a Dead Letter, Payload Intact).
4. State change and event share one transaction (§ Publish-With-Write Uses the Outbox — Never a Dual Write).
5. A run record a later run can read (§ Run Records for Scheduled Jobs).

- Brief → the quick note (What / Where / How verified)
- Artifact → the capture at `{quick-root}/evidence/check.md`
- Handoff → the `## Result` bullet in `note.md`

## Worker Execution Contract

This is the operational spine. Follow it as written.

### At-Least-Once Is the Only Assumption

Assume every message can arrive **more than once and out of order**, and that the process can die between doing the work and acknowledging it. Exactly-once delivery is not a property a broker gives you; exactly-once *effect* is a property your handler gives itself. Never write a handler whose correctness depends on a delivery guarantee.

### Idempotency Key on Every Handler

Every handler declares, in code and in its plan task, the key that makes a replay a no-op:

- **The message id** when the producer's id is stable across redeliveries, or
- **A business key** — order id + state transition, invoice number, `(tenant, entity, version)` — when it is not, or when the same logical event can legitimately arrive under two different message ids.

The handler resolves the key first, records it in the same transaction as the effect, and returns early on a key already processed. A dedupe record written *after* the effect, or in a separate transaction, is a race, not a guard.

**A handler that "usually" runs once is not idempotent.** The test is whether a duplicate is *harmless*, not whether it is likely.

### Retries With Backoff, Bounded

- Retry transient failures only (timeouts, connection resets, 5xx, lock contention). A validation failure or schema mismatch fails identically forever — dead-letter it on attempt one.
- Back off between attempts, with jitter.
- **The attempt count is bounded and declared in the plan task, not here.** This skill deliberately fixes no global number (convention #8 — refining `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`'s ownership of operational thresholds): the right bound for a payment consumer and for a thumbnail worker are not the same number.

### Poison Messages Go to a Dead Letter, Payload Intact

When the attempt bound is reached, the message moves to a dead-letter destination carrying **the failing payload verbatim**, plus the reason, the attempt count, and the correlation id. Never log-and-drop, and never acknowledge a message you did not process — an acknowledged failure is silent data loss with a green dashboard over it.

Redaction rule: secrets and personal data in a dead-lettered payload follow `{PLUGIN_ROOT}/security-and-hardening/SKILL.md`; a dead letter is storage like any other.

### Publish-With-Write Uses the Outbox — Never a Dual Write

A handler that changes state **and** publishes an event must not do both against two systems in one step. Either the write commits and the publish is lost, or the publish escapes and the write rolls back; no ordering of the two calls removes the window.

Write the event to an **outbox table in the same transaction as the state change**, and let a separate relay publish it and mark it sent. The relay is at-least-once by construction, which is why consumers must be idempotent — the two rules are one design. The outbox table is a schema change: plan it under `{PLUGIN_ROOT}/database-migration-patterns/SKILL.md`.

### Ordering Assumptions Are Stated, Never Assumed

For every consumer, state in the plan task **which of these is true**: order does not matter; order matters within a partition key (name it); or order matters globally (say what enforces it). A handler that silently depends on arrival order is correct only until the queue scales past one consumer.

Where order matters, prefer a design that tolerates disorder: sequence numbers on the message, last-write-wins on a monotonic field, or a state machine that ignores a transition it has already passed.

### A Job's Observable Effect

A job task's acceptance criterion names the **observable effect** the job produces — the row, the queue message, the file, the state transition a later reader can see. Those criteria rules are owned by `{PLUGIN_ROOT}/planning-and-task-breakdown/SKILL.md` (*Plans model effects, not artifacts*); do not restate them. This skill adds only the sink: name it.

Milestones whose effect lands in a queue, cache, table, or blob carry the `[vs:fn]` surface tag from `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`.

### Run Records for Scheduled Jobs

Every scheduled job writes a **run record a later run can read**: start time, finish time, items processed, failures, correlation id — persisted where the next run can query it (a table, not only a log stream), because its purpose is to answer *did last night's run happen, and how much did it do?* Field list and table shape: [`references/run-record-template.md`](references/run-record-template.md).

### Verification

The proof that a handler is idempotent is **a replay observed out of process**, never a unit test that calls the handler function twice:

1. Start the consumer the way it runs, per the environment manifest (`{PLUGIN_ROOT}/runtime-evidence/SKILL.md`).
2. Publish the **same message twice** — same id, same body — through the real broker or the real scheduler entry point.
3. Read the effect back from its sink and assert **one** effect: one row, one charge, one file, one downstream message.
4. Capture the whole thing with `python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture <path> -- <command>`.
5. Cite the capture with the `**Runtime evidence:**` line whose grammar is owned by `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`. Do not invent a second citation form.

An in-process double call proves the dedupe branch is reachable. It does not prove the broker's redelivery path reaches it, which is the claim.

### Verification Checklist

Before marking jobs or messaging work complete:

- [ ] Every handler names its idempotency key (message id or business key) in code and in the plan task
- [ ] The dedupe record is written in the same transaction as the effect
- [ ] Retries are bounded, backed off, and applied to transient failures only
- [ ] The dead-letter destination exists and preserves the failing payload, reason, attempt count and correlation id
- [ ] No publish-with-write path exists outside the outbox
- [ ] Every consumer's ordering assumption is stated in its plan task
- [ ] Every scheduled job writes a run record a later run can read
- [ ] An out-of-process replay (same message twice → one effect) is captured and cited

### Escalate When

- **A handler cannot be made idempotent** — the effect is inherently non-repeatable and no key deduplicates it (an unkeyed external charge, an outbound email with no provider-side idempotency key). This is a design change, not a build task: **escalate to the Orchestrator.** Never ship a handler whose correctness depends on the message arriving once.
- The plan task declares no ordering assumption for a consumer where order plausibly matters → return it unbuilt as a planning defect rather than picking one.
- No broker, scheduler or sink is reachable out of process in this environment → `BLOCKED` naming what was missing, per `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`. Never substitute an in-process double call.
- A destructive replay is the only available test (the effect cannot be reset between runs) → escalate to the Orchestrator before running it.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Outbox and idempotency](references/outbox-and-idempotency.md) — the dual-write failure walked step by step, the relay's own at-least-once behaviour, key-selection worked examples, the dedupe-table shape and its retention, and the anti-pattern table.
- [Run record template](references/run-record-template.md) — the fields, the table shape, and what a later run reads out of it.
