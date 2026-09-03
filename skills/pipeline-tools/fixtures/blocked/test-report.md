# Notifications — Test Report

#Task [1]:

- FR-1: PASS — `npm test` — exit 0 — tests/notifications.test.js::notification appears after a finished job
- NFR-1: PASS — `npm test` — exit 0 — tests/notifications.test.js::emitted 1.2s after job completion

#Task [2]:

- FR-2: BLOCKED — the dismiss endpoint is not deployed in the local estate, so no
  check could run; the precondition is absent, not failing.
