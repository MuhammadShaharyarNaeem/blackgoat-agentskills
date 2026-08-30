# Password Reset Tokens — Plan

`src/passwordReset.js` is already implemented and working. These tasks scope the tests
to be written against it — no production code changes.

## Task 1: Token issuance and expiry window
Unit tests for `generateResetToken`: throws on a missing userId; returns an unused
record bound to the userId; stamps `expiresAt` exactly `TOKEN_TTL_MS` (15 minutes)
after `createdAt`; token is 32 hex characters (crypto-random, 128 bits).
**Requirements covered:** FR-1, NFR-1

## Task 2: Validity checks
Unit tests for `isTokenValid`: true for a fresh unused record; false once `expiresAt`
has passed (drive the clock via the `now` parameter); false for a used record; false
for null/undefined records.
**Requirements covered:** FR-2

## Task 3: Single-use consumption
Unit tests for `consumeToken`: consuming a valid record returns `{ ok: true }` and
marks it used; a second consume returns `{ ok: false, reason: 'invalid_or_expired' }`;
consuming an expired record fails the same way.
**Requirements covered:** FR-3
