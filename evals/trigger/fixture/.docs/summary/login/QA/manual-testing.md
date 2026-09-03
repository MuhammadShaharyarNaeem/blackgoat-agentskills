# Manual Testing Baseline — login

Reverse-engineered from the running service on 2026-07-14.

| # | Step | Expected |
|---|------|----------|
| 1 | POST `/api/auth/login` with valid credentials | `200`, body carries `token` |
| 2 | POST `/api/auth/login` with a wrong password | `401`, body `{ "code": "invalid_credentials" }` |
| 3 | POST `/api/auth/login` five times with a wrong password, then once more | `423`, body `{ "code": "account_locked", "retryAfterSeconds": 900 }` |

Step 3 is the locked-account baseline: the lock trips on the sixth attempt, not the fifth,
and the `retryAfterSeconds` value is part of the contract the mobile client depends on.
