# Password Reset Tokens — Requirements

## Vision
A small self-contained module (`src/passwordReset.js`, already implemented and working)
that issues, validates, and consumes single-use password-reset tokens with a fixed
expiry window.

## Functional Requirements (MoSCoW)
### Must Have
- [ ] **FR-1** As a user requesting a password reset, I want a reset token issued for my
  account that expires 15 minutes after creation, so that stale reset links cannot be
  used later. — Given a userId, When `generateResetToken(userId)` is called, Then the
  returned record's `expiresAt` equals `createdAt + TOKEN_TTL_MS` (15 minutes), and
  calling it without a userId throws.
- [ ] **FR-2** As the platform, I want token validity checks to reject used or expired
  tokens, so that only fresh, unused tokens can authorize a password reset. — Given a
  token record, When `isTokenValid(record, now)` is called, Then it returns true only
  for an unused record whose `expiresAt` is still in the future, and false for used,
  expired, or missing records.
- [ ] **FR-3** As the platform, I want tokens to be single-use, so that a captured reset
  link cannot be replayed. — Given a valid token record, When `consumeToken(record)` is
  called, Then it returns `{ ok: true }` and marks the record used, and any further
  `consumeToken` call on the same record returns
  `{ ok: false, reason: 'invalid_or_expired' }`.
### Won't Have (this version)
- Persistence, token delivery (email/SMS), and rate limiting are out of scope for this
  module.

## Non-Functional Requirements
- **NFR-1** (Must) Security: reset tokens must be generated from a cryptographically
  secure source (`crypto.randomBytes`), never `Math.random`, and be at least 128 bits
  long (32 hex characters).
