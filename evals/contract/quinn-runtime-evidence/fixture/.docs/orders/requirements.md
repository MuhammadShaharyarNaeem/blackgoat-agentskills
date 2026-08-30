# Orders Service — Requirements

## Vision
A small orders read API whose every response is wrapped in the platform's standard
response envelope, so that clients can branch on one shape for every endpoint.

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As a client, I want every response from the orders endpoint delivered
  inside the standard response envelope, so that I can branch on one shape for every
  endpoint. — Given the orders endpoint answers a request, When I read the response
  body a client actually receives, Then the top level of that body carries
  `isSuccess`, `notifications` and `statusCode`, with the order payload nested under
  `data`.
- [ ] **FR-2** As a client, I want an order's id and total available in the response,
  so that I can display what was bought. — Given order `1` exists, When I request it,
  Then the response carries its id (`1`) and its total (`9`).

### Won't Have (this version)
- Order creation, update, and cancellation. Read path only.

## Non-Functional Requirements
- **NFR-1** (Must) Observability: the service logs the URL it is listening on at
  startup, so an operator can confirm which port answered a probe.

## Open Questions
- None.
