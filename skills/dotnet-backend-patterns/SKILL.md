---
name: dotnet-backend-patterns
description: "Provides the .NET backend execution contract: solution segregation (Domain/Application/API/Infrastructure), the two sanctioned API modes (CQRS+MediatR pipelines or REPR minimal APIs), EF Core AsNoTracking + DTO projections, async with CancellationToken, and zero-mock integration testing against the real Dev DB. Use if the project uses .NET / C#. Squad-internal execution contract loaded by agents via their Methodology Dependencies table."
---

# .NET Backend Patterns

Strict solution segregation, exactly two sanctioned API modes, lean EF Core queries, and tests that run against reality — never against mocks.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### Solution Segregation

- Segregate the solution into distinct projects: `Domain` (pure logic, zero dependencies), `Application`/`Core` (use cases, MediatR handlers), `API` (endpoints/controllers), `Infrastructure` (EF Core, external APIs).
- Third-party packages are isolated in their own projects so they can be reused across solutions. `Domain` references nothing.

### API Mode — Two Sanctioned Modes, Never Mixed

The blueprint (Aria's `detailed-design.md`) declares which mode the project uses. Follow it. Never mix modes, never invent a third.

- **Mode A — CQRS + MediatR:** Commands/queries with pipeline behaviors for authorization, validation, and domain-event dispatch. Generic base controllers map every result to the standardized generic Response Pattern so the frontend receives predictable contracts.
- **Mode B — REPR minimal APIs:** Request-Endpoint-Response with minimal APIs exclusively. Everything the route needs lives in the endpoint file. Reusable logic is extracted strictly as decoupled services. NO repository pattern in REPR mode — it is bloat here.

### EF Core & Data Discipline

- Every read-only query uses `AsNoTracking()`. No exceptions.
- Project to DTOs (`Select(x => new Dto {...})`) instead of hydrating full entities when only a subset is needed.
- No cascade deletes on critical records — configure `DeleteBehavior.Restrict` and handle removal explicitly.
- Handle concurrency explicitly (rowversion/concurrency token + `DbUpdateConcurrencyException` handling) where concurrent writes are possible.

### Async Discipline

- Async everywhere on the I/O path. Every async method accepts and propagates a `CancellationToken` down to EF Core and HTTP calls. No `.Result`, no `.Wait()`.

### Testing Doctrine (Zero-Mock)

- Integration tests run against the real Dev DB. Mocking `DbContext` (or its providers) is forbidden — a test against a mocked database proves nothing.
- Unit-level TDD stays at function scope: pure logic in `Domain`/`Application` gets fast unit tests; anything crossing the database boundary is an integration test against the Dev DB.

### Verification Checklist

Before marking work complete:

- [ ] New code lands in the correct project layer; `Domain` remains dependency-free
- [ ] The API mode matches the blueprint; no mode mixing (no repositories in REPR, no ad-hoc endpoints in CQRS)
- [ ] Every read-only query has `AsNoTracking()` and projects to a DTO where a subset suffices
- [ ] No cascade delete introduced on critical records; concurrency handled where writes race
- [ ] All async methods propagate `CancellationToken`; no sync-over-async
- [ ] Integration tests against the real Dev DB cover DB-crossing behavior — zero mocked `DbContext`. (Builders do not author these — verify they exist or flag the gap to the Orchestrator; QA — Quinn, Mode B — authors them.)
- [ ] Responses conform to the standardized Response Pattern (Mode A) or the declared endpoint contract (Mode B)

### Escalate When

- The blueprint does not declare an API mode, or the requested change requires mixing modes → report to the Orchestrator.
- The Dev DB is unreachable or its schema diverges from migrations → report to the Orchestrator; do not fall back to mocks.
- A requirement demands cascade delete on critical records or an untracked write path → report to the Orchestrator before implementing.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [.NET playbook](references/dotnet-playbook.md) — validation pipeline behavior sample, REPR endpoint sample, AsNoTracking + projection GOOD/BAD, the Response Pattern shape, and the integration-test-against-Dev-DB pattern.
