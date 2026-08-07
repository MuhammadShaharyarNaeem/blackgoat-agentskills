# Notifications — Requirements

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As a user, I want to receive a notification, so that I know an event occurred.
  - Given a subscribed event, When it fires, Then a notification is delivered.
- [ ] **FR-2** As a user, I want to manage my subscriptions, so that I control what I receive.

## Non-Functional Requirements

- **NFR-1** (Must) Durability: queued notifications survive a worker restart.
