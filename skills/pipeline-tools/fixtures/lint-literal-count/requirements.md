# Billing API — Requirements

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As a client, I want documented error responses, so that I can handle failures.
  - Given any error, When the API responds, Then the body carries a documented error code.
- [ ] **FR-2** As a client, I want a retry policy, so that transient failures recover.

## Non-Functional Requirements

- **NFR-1** (Must) Accuracy: monetary amounts are rounded to 2 decimal places.
