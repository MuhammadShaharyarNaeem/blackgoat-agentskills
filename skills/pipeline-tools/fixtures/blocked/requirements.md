# Notifications — Requirements

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As a user, I want an in-app notification when a job finishes, so that I don't poll.
  - Given a finished job, When I open the app, Then its notification appears.
- [ ] **FR-2** As a user, I want to dismiss a notification, so that my list stays short.
  - Given a notification, When I dismiss it, Then it does not reappear.

## Non-Functional Requirements

- **NFR-1** (Must) Delivery: a notification is emitted within 5s of the job finishing.
