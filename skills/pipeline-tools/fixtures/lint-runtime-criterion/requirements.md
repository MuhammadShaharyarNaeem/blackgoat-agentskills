# Orders API — Requirements

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As a client, I want to list my orders, so that I can review what I bought.
  - Given I have orders, When I request the order list, Then each order appears in the response.
- [ ] **FR-2** As a client, I want to place an order, so that I can buy something.
  - Given a valid basket, When I place the order, Then the response carries the created order.

## Non-Functional Requirements

- **NFR-1** (Must) Reliability: a rejected order leaves no partial row behind.
