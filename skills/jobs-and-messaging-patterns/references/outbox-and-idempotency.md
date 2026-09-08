# Outbox and idempotency — deep dive

Read on demand. Nothing here is needed to execute the Worker Execution Contract in
`../SKILL.md`; this is the reasoning behind it, plus the shapes that are easier to copy
than to derive.

## The dual write, walked step by step

A handler that must both persist state and tell the rest of the system about it has, at
first glance, two orderings. Both lose.

**Publish first, then commit.** The event escapes at T1. The transaction rolls back at
T2 — a constraint violation, a deadlock, a pod eviction. Downstream consumers now act on
an order that does not exist. Nothing in the system is inconsistent *locally*; every
service is internally correct and the estate as a whole is wrong. This is the expensive
direction, because the damage propagates before anyone can detect it.

**Commit first, then publish.** The transaction commits at T1. The process dies at T2
before the publish call returns, or the broker is unreachable, or the publish throws and
the catch block logs it. The state change is real and no one downstream hears about it.
Cheaper than the first ordering — but the failure is *silent*, so it is typically found
weeks later by a reconciliation job or a customer.

There is no third ordering. A distributed transaction across the database and the broker
would close the window, and is unavailable in practice on the brokers and managed
databases this plugin's projects use.

## The outbox

Move the second system out of the critical path by making the event *part of the state
change*:

1. In one local transaction: apply the state change **and** insert a row into an
   `outbox` table describing the event.
2. A separate relay — a polling worker, or the database's change feed — reads unsent
   outbox rows, publishes each to the broker, and marks it sent.

The atomicity is now local, which is a property a single database gives you for free.

**The relay is at-least-once, by construction.** It can publish a row and die before
marking it sent; the next pass republishes it. That is not a defect to engineer away —
it is why the consumer-side idempotency rule exists. The two halves of this skill are
one design, and removing either makes the other unsound.

Shape:

| Column | Purpose |
|---|---|
| `id` | Outbox row id; usually the published message id |
| `aggregate_id` | The entity the event is about — also the natural partition key |
| `event_type` | What happened |
| `payload` | The serialized event body |
| `correlation_id` | Carried from the inbound request or job that caused the change |
| `occurred_at` | When the state change committed |
| `sent_at` | `NULL` until the relay publishes it — the relay's only query filter |
| `attempts` | Relay-side attempt count, for the relay's own bound |

Relay ordering: publish in `occurred_at`/`id` order **within an `aggregate_id`**, which
is the only ordering guarantee most consumers actually need (see *Ordering Assumptions*
in the contract). A relay that publishes globally in id order and a broker that
partitions by key will not preserve each other's ordering; assume only the per-key one.

Creating the outbox table is a schema change and follows
`{PLUGIN_ROOT}/database-migration-patterns/SKILL.md` — expand first, deploy the relay
second.

## Choosing the key

| Situation | Key | Why |
|---|---|---|
| Broker assigns a stable id preserved across redelivery | The message id | Cheapest correct answer; verify the id really is stable on redelivery rather than assuming it |
| The same logical event can be republished under a new id (an outbox relay retry after a crash, a manual replay, a producer redeploy) | A business key | The message id changes; the effect must not repeat |
| The effect is a state transition | `(entity_id, target_state)` | Naturally idempotent: the second attempt finds the entity already there |
| The effect is an external side effect (charge, email, provisioning) | A key the *external* system accepts (Stripe's `Idempotency-Key`, a provider request id) | Your dedupe table cannot undo their side effect; push the key to the boundary that performs it |
| The effect is an append (an audit row, a metric) | `(source_id, event_type, occurred_at)` | Appends are the case people skip, and duplicated audit rows are how a reconciliation later disagrees with itself |

**A timestamp alone is not a key.** Two redeliveries carry the same timestamp and two
distinct events can too.

## The dedupe record

- Written **in the same transaction as the effect**. This is the entire mechanism: if the
  effect commits, the record commits; if the effect rolls back, so does the record, and
  the retry legitimately re-runs.
- A unique constraint on the key is the enforcement. Catching the unique-violation and
  returning success is a valid, and often the simplest, implementation — the constraint
  is doing the concurrency control the application would otherwise do badly.
- **Retention is a decision, not an oversight.** The table grows forever unless pruned.
  Prune older than the broker's maximum redelivery window plus the longest manual replay
  you would ever perform, and write that number down where the pruning job can be read
  against it.
- Where the effect's own table can carry the key (a unique `external_ref` column on the
  payment row), prefer that to a separate dedupe table: one row, one constraint, no
  retention question.

## Crash between effect and ack

The third attack the contract's Verification step exists for. The handler completes the
effect, then the process dies before acknowledging. The broker redelivers. Everything
downstream of that point is the idempotency key's job — which is why "the handler
succeeded" is never the same claim as "the message was acknowledged", and why a handler
that treats the ack as part of its own success path is unsound.

The corollary for testing: killing the consumer between effect and ack is a *different*
test from delivering the same message twice, and it is the one that catches a dedupe
record written outside the effect's transaction.

## Anti-patterns

| Anti-pattern | Why it fails |
|---|---|
| "Check if it exists, then insert" without a unique constraint | Two concurrent deliveries both pass the check |
| Dedupe cache in process memory | Lost on restart; not shared between replicas — and the restart is exactly when redelivery happens |
| Acknowledging on failure "so the queue drains" | Silent data loss with a green dashboard over it |
| Unbounded retry on a permanent failure | The same poison message consumes the consumer forever; throughput collapses and the cause is invisible |
| Retry with no jitter | Every replica retries in lockstep and the recovering dependency is knocked over again |
| Relying on a broker's "exactly once" mode | It is exactly-once *delivery to the broker's own log*, not exactly-once effect in your database |
| One consumer, "so ordering is fine" | True until the first scale-out, then wrong intermittently — the worst failure shape to debug |
| Logging the dead letter instead of storing it | A log line is not a payload you can replay |
| Proving idempotency by calling the handler twice in a unit test | Proves the branch is reachable, not that redelivery reaches it |
