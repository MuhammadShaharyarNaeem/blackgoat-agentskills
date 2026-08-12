---
name: dotnet-backend-patterns
description: "Provides the .NET backend execution contract: solution segregation (Domain/Application/API/Infrastructure), the two sanctioned API modes (CQRS+MediatR pipelines or REPR minimal APIs), EF Core AsNoTracking + DTO projections, async with CancellationToken, and zero-mock integration testing against the real Dev DB. Use if the project uses .NET / C#. Squad-internal execution contract loaded by agents via their Methodology Dependencies table."
---

# .NET Backend Patterns

Strict solution segregation, exactly two sanctioned API modes, lean EF Core queries, and tests that run against reality — never against mocks.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### Solution Segregation

- Segregate the solution into distinct projects: `Domain` (pure logic, zero dependencies), `Application` (use cases, MediatR handlers), `API` (endpoints/controllers), `Infrastructure` (EF Core, external APIs).
- Third-party packages are isolated in their own projects so they can be reused across solutions. `Domain` references nothing.

### API Mode — Two Sanctioned Modes, Never Mixed

The blueprint (Aria's `detailed-design.md`) — or, for lite-originated work, the mode constraint recorded in `requirements.md` — declares which mode the project uses. Follow it. Never mix modes, never invent a third.

- **Mode A — CQRS + MediatR:** Commands/queries with pipeline behaviors for authorization, validation, and domain-event dispatch. Generic base controllers (`BaseController<T>`) map every result to the standardized `BaseResponse<T>` envelope from `BG.Infrastructure.Core` — via `ExecuteWithOKCommandResponse` (`ExecuteWithOKResponse` is deprecated — do not use in new code) — so the frontend receives predictable contracts. Do not hand-roll a per-service response type.
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
- Handle concurrency explicitly where concurrent writes are possible — optimistic via rowversion/concurrency token + `DbUpdateConcurrencyException` handling; pessimistic via row locks (`SELECT ... FOR UPDATE`) taken inside an explicit transaction.
- **Keep the transaction span in-process.** Nothing between `BeginTransactionAsync` and `CommitAsync` may await an out-of-process dependency — no `HttpClient`, supplier SDK, gateway, or broker call. Locking a row that is shared across all callers (a global settlement, clearing, or sequence account) and then awaiting a remote call serializes the whole endpoint at that remote's latency. Where the span existed to make a locked check-then-write atomic, it is replaced by a committed reservation before the call and a second short transaction after it — never merely by widening the gap between check and write.

### Async Discipline

- Async everywhere on the I/O path. Every async method accepts and propagates a `CancellationToken` down to EF Core and HTTP calls. No `.Result`, no `.Wait()`.

### Testing Doctrine — the Tier Ladder (Zero-Mock)

**"Zero-mock" is scoped to the DATABASE boundary.** It says nothing about the transport, and conflating the two is what let a missing response envelope pass every gate in 2026-08. Each tier proves a different class of claim; a higher tier is never substituted by a lower one.

- **Tier 1 — Unit.** Pure logic in `Domain`/`Application`, at function scope. Fast, no I/O.
- **Tier 2 — Integration (in-process host, real Dev DB).** `WebApplicationFactory<Program>` + `CreateClient()` against the real Dev DB. Mocking `DbContext` (or its providers) is forbidden — a test against a mocked database proves nothing. Anything crossing the database boundary lives here.
  **What this tier cannot prove:** it opens no socket, runs no Kestrel, resolves no host startup/config chain, and serves no Swagger. So it cannot falsify a claim about the serialized wire shape, which `JsonSerializerOptions` resolved, middleware/filter ordering, environment-branch behavior, auth challenge shape, content negotiation, or the existence of a contract surface a human can open. See [data-and-testing.md](references/data-and-testing.md) §3 for the assertion form that at least catches an unwrapped body *here*.
- **Tier 3 — Out-of-process wire (mandatory for wire claims).** The application started the way a user starts it — real Kestrel, real `Program.cs` environment branch — probed over a socket by an external client (Postman/newman or an HTTP client), with the response body captured to disk. Required for any requirement about the response envelope, status codes, headers, auth challenge shape, or content negotiation. Contract: `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`. This stack's gate invocation is `--require-key isSuccess --require-key notifications --require-key statusCode --require-openapi-reachable`. The OpenAPI flag belongs in the stack contract rather than left to the caller because a .NET API's Swagger endpoint lives behind the very Development environment branch Tier 2 never resolves — so "the document is reachable" is precisely the assertion that separates a started application from a test host.

The `ErrorCode` serialization hazard in [response-and-errors.md](references/response-and-errors.md) is a **Tier 3** obligation specifically: the envelope travels three distinct serialization paths (`ObjectResult`, `Results.Json`, `WriteAsJsonAsync`), each resolving its own options, so it takes at minimum one success capture and one failure capture — cited separately — to prove both. The failure capture doubles as the negative-half proof.

### Build & Test Log Discipline

- When a Python 3 runtime is available, run builds and test runs through `{PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py` — the full log lands on disk, and only errors-with-context plus a tail enter the transcript. Invocation shape:
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --log <path> -- dotnet build` (same shape for `dotnet test`). `run_quiet.py` defaults to a 240s timeout — pass an explicit `--timeout` (e.g. 900) for integration suites hitting the real Dev DB. Treat exit 124 with a `TIMEOUT:` header as a harness result to escalate — never record it as a test FAIL.
- No Python 3 runtime available → fall back to `dotnet build -nologo -v:q -clp:"ErrorsOnly;Summary"` and `dotnet test -nologo --logger "console;verbosity=quiet"`.
- Never paste a full build/test log into a report. Cite the log path plus the relevant excerpt.
- A full-verbosity rerun (`-v:normal`/`-v:detailed`, or dropping `--logger "console;verbosity=quiet"`) is for diagnosing only what the filtered output cannot localize — not the default way to read results.
- Deliberate divergence (convention #8): the no-Python fallback above is tighter than `run_quiet.py`'s no-information-lost guarantee above — `-clp:ErrorsOnly` suppresses warnings outright at the MSBuild level rather than merely filtering them from the transcript, so they are not recoverable from a log afterward. This is deliberate: warning review stays with the reviewer axis (code-review-and-quality) and CI either way, never agent transcripts, so nothing the agent needed is lost.

### Verification Checklist

Before marking work complete:

- [ ] New code lands in the correct project layer; `Domain` remains dependency-free
- [ ] The API mode matches the blueprint; no mode mixing (no repositories in REPR, no ad-hoc endpoints in CQRS)
- [ ] Every read-only query has `AsNoTracking()` and projects to a DTO where a subset suffices
- [ ] No cascade delete introduced on critical records; concurrency handled where writes race
- [ ] No `BeginTransactionAsync` / `FOR UPDATE` span awaits an out-of-process call; any check-then-write invariant that lost its span is carried by a committed reservation
- [ ] All async methods propagate `CancellationToken`; no sync-over-async
- [ ] Integration tests against the real Dev DB cover DB-crossing behavior — zero mocked `DbContext`. (Builders do not author these — verify they exist or flag the gap to the Orchestrator; QA (Quinn) authors them.)
- [ ] Every response (both modes) is a `BaseResponse<T>` envelope from BG.Core; failures are structured `Error`s (registry-composed `ErrorCode`) in `Notifications`, mapped once via `ToActionResult<T>()` (Mode A) or `ToResult<T>()` + `IExceptionHandler` (Mode B) — no bare payloads, no ad-hoc status codes
- [ ] Every response-envelope claim is backed by a **Tier 3** capture under `evidence/runtime/` — never by a `WebApplicationFactory` test alone, and never by a source read of the wrapper's registration
- [ ] Dependencies point inward (DIP): `Core`/`Domain` defines interfaces, `Infrastructure` implements, concretes bind only at the composition root; no framework/IO types leak into `Domain`/`Core`; no `NotImplementedException` interface members

### Escalate When

- The blueprint does not declare an API mode, or the requested change requires mixing modes → report to the Orchestrator.
- The Dev DB is unreachable or its schema diverges from migrations → report to the Orchestrator; do not fall back to mocks.
- The application cannot be started out-of-process in this environment (Tier 3 impossible) → report to the Orchestrator and record the wire criterion `BLOCKED`. **Never substitute Tier 2** — an in-process pass on a wire claim is a fabrication in effect (`base-persona.md`, Evidence Integrity).
- A requirement demands cascade delete on critical records or an untracked write path → report to the Orchestrator before implementing.

## Deep Dive — Mode-Scoped Playbooks

Read on demand. **Load only the playbook for the mode the blueprint declares**, plus the shared data/testing one — don't load the other mode's playbook (it's noise for this project).

- **Mode A →** [cqrs-playbook.md](references/cqrs-playbook.md) — MediatR validation pipeline behavior, and how Mode A emits the Response Pattern via `BaseController<T>` (`ExecuteWithOKCommandResponse`; `ExecuteWithOKResponse` is deprecated — do not use in new code).
- **Mode B →** [repr-playbook.md](references/repr-playbook.md) — REPR + Vertical Slice: endpoint file structure, endpoint filters (replacing MediatR behaviors), `IQueryable<T>` extensions, DI composition root, migration checklist, worked example, and how REPR emits the Response Pattern via `.ToResult()` + `IExceptionHandler`.
- **Both modes →** [response-and-errors.md](references/response-and-errors.md) — the shared `BaseResponse<T>` envelope, the `Error` / `ErrorCode` model + code registries, `Notifications`, `CustomException`, and the per-mode emit paths.
- **Both modes →** [data-and-testing.md](references/data-and-testing.md) — AsNoTracking + projection GOOD/BAD, async + `CancellationToken` propagation, and the zero-mock integration-test-against-Dev-DB pattern.
