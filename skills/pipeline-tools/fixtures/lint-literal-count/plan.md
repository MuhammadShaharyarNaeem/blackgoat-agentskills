# Billing API — Implementation Plan

## Task 1: Error code catalogue

**Requirements covered:** FR-1

**Acceptance criteria:**
- The handler maps 7 error codes from the error table.
- The router exposes 4 endpoints under `/billing`.

## Task 2: Retry policy and rounding

**Requirements covered:** FR-2, NFR-1

**Acceptance criteria:**
- A transient failure is retried up to 3 attempts before surfacing an error.
- Each retry backs off for 60 seconds.
- Monetary amounts are rounded to 2 decimal places.
