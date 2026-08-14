# Orders — Test Report

The capture passes every other check in the gate. Only the recorded contract surface
gives it away: `OpenAPI: ... — 404`.

Like `--forbid-host`, `--require-openapi-reachable` is **caller-declared**: this
fixture exits **0** without the flag and **1** with it. The gate reads the recorded
field and makes no request of its own — it proves the probe *reported* a reachable
contract surface, never that one exists now.

#Task [1]:

**Runtime evidence:** evidence/runtime/m3-orders-post.md

- FR-4: PASS — Tests.Integration/Orders/EnvelopeTests.cs::Returns_envelope — exit 0 — 4 passed
