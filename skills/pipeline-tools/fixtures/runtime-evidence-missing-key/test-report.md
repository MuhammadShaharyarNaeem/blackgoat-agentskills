# Orders — Test Report

The observed 2026-08 failure, reproduced. The in-process suite is green and the
ledger line reads PASS, but the capture shows the gateway returning a bare payload:
no `isSuccess`, no `notifications`, no envelope at all. This is the shape the gate
exists to reject.

#Task [1]:

**Runtime evidence:** evidence/runtime/m3-orders-post.md

- FR-4: PASS — Tests.Integration/Orders/EnvelopeTests.cs::Returns_envelope — exit 0 — 4 passed
