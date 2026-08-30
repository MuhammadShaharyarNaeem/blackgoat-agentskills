# Signup Email Verification — Requirements

## Vision
A new account must prove control of the email address it signed up with before it can
sign in, and an unused proof must stop working after a day.

## User Personas
- **New user**: signs up, receives one email, clicks one link, is verified.
- **Support engineer**: needs to explain to a user why their link stopped working, using
  only what the system records.

## Functional Requirements (MoSCoW)

### Must Have
- [ ] **FR-1** As a new user, I want a verification email sent the moment I sign up, so
  that I can prove I control the address.
  - **Given** a visitor submits the signup form with a well-formed address no account
    already uses,
  - **When** the account record is created,
  - **Then** the account is stored with `email_verified = false` and exactly one
    verification email is sent to that address.
- [ ] **FR-2** As a new user, I want my verification link to stop working 24 hours after
  it was sent, so that a stale email sitting in my inbox cannot later be used to take
  over my account.
  - **Given** a verification email sent through Mailgrid with that provider's native
    link TTL set to 24 hours,
  - **When** the recipient opens the link more than 24 hours after it was issued,
  - **Then** Mailgrid itself refuses the redirect and the request never reaches this
    service — the service therefore stores no expiry timestamp of its own and performs
    no expiry check of its own.
- [ ] **FR-3** As a new user, I want one click on a valid link to verify me, so that I
  am not asked to do it twice.
  - **Given** a verification link this service issued and has not yet consumed,
  - **When** the recipient opens it,
  - **Then** the account's `email_verified` becomes `true`, the link is consumed, and
    opening the same link again changes nothing further.
- [ ] **FR-4** As a support engineer, I want an unusable link to be rejected without
  telling the caller why, so that the endpoint cannot be used to probe which tokens
  exist.
  - **Given** a verification request carrying a token this service cannot honour,
  - **When** the endpoint handles it,
  - **Then** the response is the same regardless of whether the token never existed, was
    already consumed, or is no longer usable.

### Should Have
- [ ] **FR-5** As a new user, I want to request a fresh verification email, so that I am
  not locked out when the first one stops working. — Given an unverified account, When
  the user asks for a resend, Then a new verification email is sent.

### Won't Have (this version)
- Verifying an address by any means other than an emailed link (SMS, support override).

## Non-Functional Requirements
- **NFR-1** (Must) Security: a verification token is never written to application logs,
  error output, or analytics in a form that could be replayed.

## Open Questions
- None outstanding; the honing transcript resolved the provider and storage questions.
