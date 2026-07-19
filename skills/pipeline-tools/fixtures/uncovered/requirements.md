# Widget — Requirements

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As a user, I want to create a widget, so that I can start tracking data.
  - Given valid input, When I submit the create form, Then the widget is saved.
- [ ] **FR-2** As a user, I want to edit a widget, so that I can correct mistakes.
  - Given an existing widget, When I submit an edit, Then the changes persist.
- [ ] **FR-3** As a user, I want to delete a widget, so that I can remove unwanted data.
  - Given an existing widget, When I confirm deletion, Then the widget is removed.

### Should Have

- [ ] **FR-4** As a user, I want to archive a widget, so that I can hide it without deleting it.

## Non-Functional Requirements

- **NFR-1** (Must) Reliability: Widget writes must be durable across a server restart.
