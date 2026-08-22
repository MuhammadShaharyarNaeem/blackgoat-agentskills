# Test Report — orders

#Task [1]: Milestone 1 - Order response serialization

Command run: `node --test`
Result: 3 tests, 2 pass, 1 fail.

- FR-1: PASS — tests/orders.test.js "returns id for a known order"
- FR-3: PASS — tests/orders.test.js "returns undefined for an unknown order"
- FR-2: FAIL — tests/orders.test.js "returns total as a number"

Failing assertion, verbatim:

```
✖ returns total as a number (1.9ms)
  AssertionError [ERR_ASSERTION]: expected number, got string
      at TestContext.<anonymous> (tests/orders.test.js:14:3)
    actual: 'string',
    expected: 'number',
    operator: 'strictEqual'
```

FR-2 is a Must-Have and is not covered by a passing test. Returning to the builder.
