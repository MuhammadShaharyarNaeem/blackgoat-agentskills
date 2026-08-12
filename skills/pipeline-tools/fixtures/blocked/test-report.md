# Notifications — Test Report

#Task [1]:

- FR-1: PASS — notification appears after a finished job (test_notification_appears)
- NFR-1: PASS — emitted 1.2s after job completion (test_notification_latency)

#Task [2]:

- FR-2: BLOCKED — the dismiss endpoint is not deployed in the local estate, so no
  check could run; the precondition is absent, not failing.
