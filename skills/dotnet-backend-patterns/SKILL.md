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

- **Mode A — CQRS + MediatR:** Commands/queries with pipeline behaviors for authorization, validation, and domain-event dispatch. Generic base controllers (`BaseController<T>`) map every result to the standardized `BaseResponse<T>` envelope from `BG.Infrastructure.Core` — via `ExecuteWithOKResponse` / `ExecuteWithOKCommandResponse` — so the frontend receives predictable contracts. Do not hand-roll a per-service response type.
- **Mode B — REPR minimal APIs:** Request-Endpoint-Response with minimal APIs exclusively. Everything the route needs lives in the endpoint file. Reusable logic is extracted strictly as decoupled services. NO repository pattern in REPR mode — it is bloat here. REPR emits the **same** `BaseResponse<T>` envelope as Mode A (so the frontend sees one contract), via `.ToResult()` (`IResult` bridge) for success and a native `IExceptionHandler` for failures — not a base controller.

### Response Pattern, Errors & Exceptions (Both Modes)

Every API result — in **both** modes — maps to the standardized `BaseResponse<T>` envelope from `BG.Infrastructure.Core` (`StatusCode`, `IsSuccess`, `Data`, `DataContext`, `Notifications`). One contract, so the frontend interceptor reads every response uniformly. Never return bare payloads or ad-hoc `{ message }` bodies.

- **Errors are structured, not strings.** Failures are conveyed as `Error` records in `BaseResponse.Notifications`. Each `Error` carries a 6-digit `ErrorCode` (`MM`=microservice, `TT`=error type, `NN`=number — compose from the `MicroserviceCodes` / `ErrorTypeCodes` registries, never magic numbers), a message, and optional `PropertyName` / `ActionHint`. The `ErrorType` drives frontend UX (field / popup / toast / redirect / silent).
- **Throw `CustomException`** from handlers/services/domain for expected failures — it carries the `ErrorCode`, HTTP status, and UX context, and maps cleanly to an `Error`.
- **Map failures once, per mode:** Mode A via the `BaseController<T>` try/catch → `.ToActionResult()`; Mode B via a native `IExceptionHandler` → `.ToResult()`. Do not build error envelopes inline in each handler.
- Full model + code: [response-and-errors.md](references/response-and-errors.md).

### Design Principles — SOLID & Separation of Concerns

The contract already *is* these principles applied; keep them explicit so they aren't quietly eroded:

- **Separation of Concerns** — enforced by Solution Segregation (above) and, in REPR, by vertical slices (Locality of Behavior). Framework/IO concerns (EF Core, ASP.NET, SDKs) stay out of `Domain`/`Core`. Don't leak persistence or transport types into domain logic.
- **DIP (dependency inversion)** — dependencies point *inward*: `Domain`/`Core` defines interfaces (`IEmailService`, `IPaymentGateway`, …), `Infrastructure` implements them, and the composition root (`Program.cs` / DI registration) is the only place concretes bind. `Core` depends on nothing.
- **SRP** — one reason to change per unit: one handler/endpoint per use case; no god services (extract a `{Feature}Service` over a 20-method `CustomerService`).
- **ISP** — keep `Core` interfaces narrow and role-specific; don't force implementers to stub members they don't use.
- **OCP/LSP** — extend via new handlers/slices/behaviors rather than editing shared cross-cutting code; any interface implementation must honor the contract fully (no `NotImplementedException` members — that failure mode is exactly what surfaced when EF repository implementations drifted from their interfaces).

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
- [ ] Integration tests against the real Dev DB cover DB-crossing behavior — zero mocked `DbContext`. (Builders do not author these — verify they exist or flag the gap to the Orchestrator; QA (Quinn, in her testing mode) authors them.)
- [ ] Every response (both modes) is a `BaseResponse<T>` envelope from BG.Core; failures are structured `Error`s (registry-composed `ErrorCode`) in `Notifications`, mapped once via `ToActionResult<T>()` (Mode A) or `ToResult<T>()` + `IExceptionHandler` (Mode B) — no bare payloads, no ad-hoc status codes
- [ ] Dependencies point inward (DIP): `Core`/`Domain` defines interfaces, `Infrastructure` implements, concretes bind only at the composition root; no framework/IO types leak into `Domain`/`Core`; no `NotImplementedException` interface members

### Escalate When

- The blueprint does not declare an API mode, or the requested change requires mixing modes → report to the Orchestrator.
- The Dev DB is unreachable or its schema diverges from migrations → report to the Orchestrator; do not fall back to mocks.
- A requirement demands cascade delete on critical records or an untracked write path → report to the Orchestrator before implementing.

## Deep Dive — Mode-Scoped Playbooks

Read on demand. **Load only the playbook for the mode the blueprint declares**, plus the shared data/testing one — don't load the other mode's playbook (it's noise for this project).

- **Mode A →** [cqrs-playbook.md](references/cqrs-playbook.md) — MediatR validation pipeline behavior, and how Mode A emits the Response Pattern via `BaseController<T>` (`ExecuteWithOKResponse` / `ExecuteWithOKCommandResponse`).
- **Mode B →** [repr-playbook.md](references/repr-playbook.md) — REPR + Vertical Slice: endpoint file structure, endpoint filters (replacing MediatR behaviors), `IQueryable<T>` extensions, DI composition root, migration checklist, worked example, and how REPR emits the Response Pattern via `.ToResult()` + `IExceptionHandler`.
- **Both modes →** [response-and-errors.md](references/response-and-errors.md) — the shared `BaseResponse<T>` envelope, the `Error` / `ErrorCode` model + code registries, `Notifications`, `CustomException`, and the per-mode emit paths.
- **Both modes →** [data-and-testing.md](references/data-and-testing.md) — AsNoTracking + projection GOOD/BAD, async + `CancellationToken` propagation, and the zero-mock integration-test-against-Dev-DB pattern.
