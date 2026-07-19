# Webhook Notification Service — Requirements

## Vision
A service that lets tenants register webhook endpoints and receive reliable, auditable
delivery of event notifications from the platform.

## User Personas
- **Tenant Admin**: configures webhook endpoints for their organization and needs
  confidence that deliveries are reliable and inspectable when something goes wrong.
- **Platform Compliance Officer**: needs a complete, tamper-evident audit trail of every
  webhook-related action across the system.

## Functional Requirements (MoSCoW)
### Must Have
- [ ] **FR-1** As a tenant admin, I want to register a webhook endpoint URL, so that my
  systems can receive event notifications. — Given a valid HTTPS URL, When I submit the
  registration form, Then the endpoint is saved and marked active.
- [ ] **FR-2** As a tenant admin, I want event payloads delivered to my registered
  webhook URL when a trigger event occurs, so that my systems stay in sync. — Given an
  active webhook and a qualifying event, When the event fires, Then a POST request with
  the event payload is sent to the registered URL.
- [ ] **FR-3** As a tenant admin, I want failed deliveries retried with exponential
  backoff, so that transient outages on my side don't cause permanent data loss. — Given
  a delivery attempt returns a non-2xx response, When the retry window has not expired,
  Then the delivery is retried with exponentially increasing delay up to a maximum
  number of attempts.
- [ ] **FR-4** As a tenant admin, I want to view delivery history and status per
  webhook, so that I can diagnose integration problems myself. — Given at least one
  delivery attempt has occurred, When I open the webhook's detail page, Then I see a
  list of attempts with timestamp, status code, and outcome.
- [ ] **FR-5** As a compliance officer, I want every webhook registration, delivery
  attempt, and configuration change audit-logged across all endpoints, so that we have a
  complete, tamper-evident trail. — Given any webhook-related action occurs on any
  endpoint, When the action completes, Then an audit log entry is written recording who
  did what, when, and to which webhook.
### Should Have
- [ ] **FR-6** As a tenant admin, I want each delivered payload signed with a shared
  secret, so that my systems can verify the request genuinely came from the platform. —
  Given a webhook has a configured signing secret, When a payload is delivered, Then the
  request includes an HMAC signature header computed from that secret.
### Could Have
- [ ] **FR-7** As a tenant admin, I want to replay a specific failed delivery on demand,
  so that I don't have to wait for the automatic retry schedule. — Given a delivery
  attempt with a non-2xx outcome, When I click "Replay", Then the same payload is
  re-sent immediately and logged as a new attempt.
### Won't Have (this version)
- A visual webhook payload builder / transformation UI is out of scope for this release.

## Non-Functional Requirements
- **NFR-1** (Must) Performance: 95% of webhook deliveries must be dispatched within 2
  seconds of the triggering event under normal load.
- **NFR-2** (Must) Security: Webhook signing secrets must be encrypted at rest and never
  returned in any API response after initial creation.

## Open Questions
- Should audit log entries be retained indefinitely, or is there a retention/purge
  policy to define later?
