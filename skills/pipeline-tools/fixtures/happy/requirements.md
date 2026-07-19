# Demo — Requirements

## Functional Requirements (MoSCoW)

### Must Have

- [ ] **FR-1** As a user, I want to log in, so that I can access my account.
  - Given valid credentials, When I submit the login form, Then I am redirected to the dashboard.
- [ ] **FR-2** As a user, I want to log out, so that I can end my session securely.
  - Given I am logged in, When I click logout, Then my session is terminated.

### Should Have

- [ ] **FR-3** As a user, I want to reset my password, so that I can recover access.

### Could Have

- [ ] **FR-4** As a user, I want a "remember me" checkbox, so that I stay logged in.

### Won't Have (this version)

- Social login (Google/Facebook) is out of scope for this release.

## Non-Functional Requirements

- **NFR-1** (Must) Performance: The login endpoint must respond within 300ms under normal load.
- **NFR-2** (Should) Accessibility: All form fields must have associated ARIA labels.
