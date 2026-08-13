# Orders — Test Report

A real out-of-process probe against a real running gateway — the shared **dev** gateway,
not the local one. The envelope is present because dev already has it. Nothing here
proves the local change works, and without the `Environment` field nothing in the
artifact would reveal which system answered.

This is the "I had to repoint every service at local URLs" failure: one service left
pointing at dev is enough.

#Task [1]:

**Runtime evidence:** evidence/runtime/m3-orders-post.md

- FR-4: PASS — Tests.Integration/Orders/EnvelopeTests.cs::Returns_envelope — exit 0 — 4 passed
