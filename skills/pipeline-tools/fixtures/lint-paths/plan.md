# Itinerary Import — Implementation Plan

## Task 1: Import parser

**Requirements covered:** FR-1

**Named identifiers:** `src/import/itinerary-parser.ts`, `tests/import/itinerary-parser.spec.ts`

Reuse the leg-normalisation logic from `D:\repos\Travel-Goat-v5\src\import\legacy.ts`
and the field notes in `file:///D:/repos/Travel-Goat-v5/docs/import.md`.

## Task 2: Transactional import and error surfacing

**Requirements covered:** FR-2, NFR-1

**Named identifiers:** `src/import/import-service.ts`, `../Travel-Goat-v5/src/import/rollback.ts`

Wraps the import in a single transaction so a failure rolls back cleanly.
