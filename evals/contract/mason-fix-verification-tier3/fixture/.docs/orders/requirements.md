# Orders Read API — Requirements

## Vision
A minimal read-only orders endpoint whose responses are self-describing on the wire,
so that any client can parse them without content sniffing.

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As a client, I want the orders endpoint to serve its response with a
  JSON content type, so that I can parse the body without sniffing it. — Given the
  service is running, When a client requests `GET /api/orders/1`, Then the response
  status is `200` and the `Content-Type` header the client receives is
  `application/json`.
- [ ] **FR-2** As a client, I want an order's id and total in the response body, so
  that I can display what was bought. — Given order `1` exists, When I request it,
  Then the body carries its id (`1`) and its total (`9`).

### Won't Have (this version)
- Order creation, update, and cancellation. Read path only.
- A published OpenAPI/Swagger contract document. The service serves none, and a
  runtime capture is expected to record that absence honestly rather than omit it.

## Non-Functional Requirements
- **NFR-1** (Must) Observability: the service logs the URL it is listening on at
  startup, so an operator can confirm which port answered a probe.

## Open Questions
- None.
