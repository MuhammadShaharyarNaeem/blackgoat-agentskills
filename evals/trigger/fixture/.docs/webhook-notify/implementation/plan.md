# Implementation Plan — webhook-notify

### Milestone 1 - Endpoint registration [API] [vs:api]

- [ ] **Task 1**: Persist one webhook endpoint per account. `[API]`
  - Requirements covered: FR-1
  - Acceptance Criteria: `POST /api/webhooks` stores an HTTPS URL and rejects `http://`.
  - Verification: `dotnet test` — "rejects a non-https endpoint" passes.
  - Dependencies: none

- [ ] **Task 2**: Sign every outbound body with an HMAC header. `[API]`
  - Requirements covered: NFR-1
  - Acceptance Criteria: responses carry `X-Signature` computed over the raw body.
  - Verification: `dotnet test` — "signs the delivery body" passes.
  - Dependencies: Task 1

### Checkpoint: Milestone 1

- Exit criterion: `dotnet test` reports 2 tests, 2 pass, 0 fail.

### Milestone 2 - Delivery and retry [API] [vs:api]

- [ ] **Task 3**: Enqueue a delivery when an invoice is finalised. `[API]`
  - Requirements covered: FR-2
  - Acceptance Criteria: finalising an invoice appends one pending delivery row.
  - Verification: `dotnet test` — "enqueues on finalise" passes.
  - Dependencies: Task 1

- [ ] **Task 4**: Retry a failed delivery with exponential backoff, max 5 attempts. `[API]`
  - Requirements covered: FR-3
  - Acceptance Criteria: a 500 from the endpoint schedules attempt N+1 at 2^N seconds; attempt 6 is never scheduled.
  - Verification: `dotnet test` — "stops after five attempts" passes.
  - Dependencies: Task 3

### Checkpoint: Milestone 2

- Exit criterion: `dotnet test` reports 4 tests, 4 pass, 0 fail.
