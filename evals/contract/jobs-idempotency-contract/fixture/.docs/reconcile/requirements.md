# Settlement Reconciliation — Requirements

## Vision
A settlement consumer that applies payment messages to the ledger exactly once in
effect, on a queue that delivers at least once.

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As the finance team, I want a redelivered payment message to leave the
  ledger unchanged, so that an at-least-once queue cannot double-count a payment. —
  Given a payment message has already been applied, When the settlement queue
  redelivers the identical message, Then the ledger holds exactly one entry for that
  message id and its total is unchanged.
- [ ] **FR-2** As the finance team, I want two distinct payment messages both applied,
  so that deduplication never swallows real payments. — Given two messages with
  different ids, When both are delivered, Then the ledger holds one entry per message
  and the total is their sum.

### Won't Have (this version)
- Persistence. The ledger is in-memory for the lifetime of the consumer process.
- Reversals, refunds, and partial settlement.

## Non-Functional Requirements
- **NFR-1** (Must) Observability: the consumer logs the URL it is listening on at
  startup, so an operator can confirm which port answered a probe.

## Open Questions
- None.
