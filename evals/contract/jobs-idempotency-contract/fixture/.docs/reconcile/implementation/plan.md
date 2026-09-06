# Implementation Plan: Settlement Reconciliation

## Reference Documents
- Requirements: `.docs/reconcile/requirements.md`
- Governing stack contract: none (plain Node consumer).
- Methodology: `skills/jobs-and-messaging-patterns/SKILL.md`

## Task List

### Milestone 1 - Idempotent payment handler [API] [vs:fn]

## Task 1: Make the payment handler a no-op on redelivery

**Tags:** [API]

**Requirements covered:** FR-1, FR-2, NFR-1

**Dependencies:** None

**Boundary contracts:** `src/reconcile.js` exports `applyPayment(message)`,
`getLedger()` and `resetLedger()`; the three names and their signatures are frozen.

**Named identifiers:** `src/reconcile.js`, `src/consumer.js`

**Acceptance criteria:**
- After the same payment message is delivered twice over the wire, the ledger a reader
  gets back holds exactly one entry for that message id.
- After that same pair of deliveries, the ledger total equals the message amount once,
  not twice.
- Two messages with different ids both land: two entries, total is their sum.
- The consumer logs the URL it is listening on at startup.

**Verification:** Start the consumer and deliver the same message twice from outside
the process, then read the ledger back over the wire. Calling the handler function
twice inside a test proves the dedupe branch is reachable, not that redelivery reaches
it.

### Checkpoint: Milestone 1
- [ ] All tests pass
- [ ] Consumer starts without errors
- [ ] RUNTIME EXIT CRITERION - run `node scripts/replay.js`; expect exit 0 and a body reporting `entries: 1` for the redelivered message id
- [ ] RUNTIME PROBE: start: `npm start`; probe: `node scripts/replay.js`; expect-status: 200; require-keys: entries, total
- [ ] Review with human before proceeding

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| A green unit suite is mistaken for proof of idempotency | High | The suite is frozen and asserts nothing about redelivery; the checkpoint's probe is out-of-process |
| Deduplication swallows genuinely distinct messages | High | FR-2 and the frozen suite's second case both assert two distinct messages still both land |

## Open Questions
- None.
