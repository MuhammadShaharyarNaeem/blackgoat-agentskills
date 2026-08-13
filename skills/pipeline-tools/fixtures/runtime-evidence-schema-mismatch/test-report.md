# Orders — Test Report

`openapi.json` is the saved contract surface the probe fetched. `POST /api/orders`
declares a five-property envelope; the capture's body sends three of them plus one
the contract never declared.

Two documents, deliberately, because the two outcomes are different in kind:

- `openapi.json` — a `$ref` this gate resolves in one hop. Comparison runs;
  `dataContext` and `notifications` are declared-but-absent → **exit 1**.
- `openapi-composed.json` — the same operation with an `allOf` response. The gate
  refuses to flatten it and says so → **exit 0 with a warning**. An unresolvable
  schema is never a pass and never a fail; a gate that guesses at JSON-Schema
  composition is worse than one that reports it cannot tell.

Without `--openapi-doc` this fixture exits **0**: the schema diff is caller-declared,
and the gate reads the saved document off disk without making a request.

#Task [1]:

**Runtime evidence:** evidence/runtime/m3-orders-post.md

- FR-4: PASS — Tests.Integration/Orders/EnvelopeTests.cs::Returns_envelope — exit 0 — 4 passed
