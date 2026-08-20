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
- Third-party packages are isolated in their own projects for reuse across solutions. `Domain` references nothing.

### API Mode — Two Sanctioned Modes, Never Mixed

The blueprint (Aria's `detailed-design.md`) — or, for lite-originated work, the mode constraint in `requirements.md` — declares the mode. Follow it. NEVER mix modes; NEVER invent a third.

- **Mode A — CQRS + MediatR:** commands/queries with pipeline behaviors (authorization, validation, domain-event dispatch). `BaseController<T>` maps every result to `BaseResponse<T>` via `ExecuteWithOKCommandResponse` (`ExecuteWithOKResponse` deprecated — NEVER in new code); NEVER a hand-rolled per-service response type. Playbook: [cqrs-playbook.md](references/cqrs-playbook.md).
- **Mode B — REPR (Request-Endpoint-Response):** minimal APIs exclusively; everything the route needs lives in the endpoint file; reusable logic extracted strictly as decoupled services. NO repository pattern in REPR — bloat here. Same `BaseResponse<T>` envelope, emitted via `.ToResult()` for success and a native `IExceptionHandler` for failures — no base controller. Playbook: [repr-playbook.md](references/repr-playbook.md).

### Response Pattern, Errors & Exceptions (Both Modes)

Envelope model, error/exception code, and per-mode emit paths: [response-and-errors.md](references/response-and-errors.md) — the single owner. Rules:

- Every API result — **both** modes — maps to the `BaseResponse<T>` envelope from `BG.Infrastructure.Core` (`StatusCode`, `IsSuccess`, `Data`, `DataContext`, `Notifications`) so the frontend reads one contract. NEVER return bare payloads or ad-hoc `{ message }` bodies.
- Failures are structured `Error` records in `Notifications`, never strings. Compose each 6-digit `ErrorCode` from the `MicroserviceCodes`/`ErrorTypeCodes` registries — NEVER magic numbers.
- Throw `CustomException` from handlers/services/domain for expected failures.
- Map failures ONCE per mode: Mode A `BaseController<T>` try/catch → `.ToActionResult()`; Mode B native `IExceptionHandler` → `.ToResult()`. NEVER build error envelopes inline in handlers.

### Design Principles — SOLID & Separation of Concerns

- **SoC** — framework/IO (EF Core, ASP.NET, SDKs) stays out of `Domain`/`Core`; no persistence or transport types in domain logic.
- **DIP** — dependencies point inward: `Domain`/`Core` defines interfaces, `Infrastructure` implements, concretes bind ONLY at the composition root; `Core` depends on nothing.
- **SRP** — one handler/endpoint per use case; no god services (extract `{Feature}Service` over a 20-method `CustomerService`).
- **ISP** — `Core` interfaces narrow and role-specific.
- **OCP/LSP** — extend via new handlers/slices/behaviors, never edits to shared cross-cutting code; contracts honored fully — no `NotImplementedException` members (the observed EF-repository drift failure).

### EF Core & Data Discipline

- Every read-only query uses `AsNoTracking()`. No exceptions.
- Project to DTOs (`Select(x => new Dto {...})`) when only a subset is needed.
- No cascade deletes on critical records — `DeleteBehavior.Restrict`, explicit removal.
- Handle concurrency explicitly where writes race: optimistic (rowversion + `DbUpdateConcurrencyException`) or pessimistic (row locks inside an explicit transaction).
- **Keep the transaction span in-process.** Nothing between `BeginTransactionAsync` and `CommitAsync` may await an out-of-process dependency (`HttpClient`, supplier SDK, gateway, broker). A span that made a locked check-then-write atomic is replaced by a committed reservation before the call plus a second short transaction after — never by widening the check-to-write gap. Rationale: [data-and-testing.md](references/data-and-testing.md), *Why the transaction span stays in-process*.

### Async Discipline

- Async everywhere on the I/O path. Every async method accepts and propagates a `CancellationToken` down to EF Core and HTTP calls. No `.Result`, no `.Wait()`.

### Testing Doctrine — the Tier Ladder (Zero-Mock)

**"Zero-mock" is scoped to the DATABASE boundary** — it says nothing about the transport (conflating the two let a missing envelope pass every gate in 2026-08). A higher tier is NEVER substituted by a lower one.

- **Tier 1 — Unit.** Pure logic in `Domain`/`Application`. Fast, no I/O.
- **Tier 2 — Integration (in-process host, real Dev DB).** `WebApplicationFactory<Program>` + `CreateClient()` against the real Dev DB. Mocking `DbContext` (or its providers) is FORBIDDEN — it proves nothing. Anything crossing the database boundary lives here. What it cannot prove — no socket, no host startup/config chain, no Swagger — is the Tier Ladder's *cannot* column in `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` (the doctrine's owner). Envelope assertion form here: [data-and-testing.md](references/data-and-testing.md) §3.
- **Tier 3 — Out-of-process wire (mandatory for wire claims).** The app started as a user starts it (real Kestrel, real `Program.cs` environment branch), probed over a socket by an external client, response captured to disk. Required for any claim about the envelope, status codes, headers, auth challenge shape, or content negotiation. Contract: `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`. This stack's gate invocation is `--require-key isSuccess --require-key notifications --require-key statusCode --require-openapi-reachable` — the OpenAPI flag is stack-owned, not caller-optional (a .NET Swagger endpoint lives behind the very Development branch Tier 2 never resolves).
- The `ErrorCode` serialization hazard ([response-and-errors.md](references/response-and-errors.md)) is a **Tier 3** obligation: the envelope travels three serialization paths, each resolving its own options — cite at minimum one success capture AND one failure capture separately; the failure capture doubles as the negative-half proof.

### Build & Test Log Discipline

- Python 3 available → run builds/tests through run_quiet.py (full log to disk; only errors-with-context plus a tail in the transcript):
  `python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --log <path> -- dotnet build` (same shape for `dotnet test`). Default timeout 240s — pass explicit `--timeout` (e.g. 900) for integration suites hitting the real Dev DB. Exit 124 with a `TIMEOUT:` header is a harness result to escalate — NEVER a test FAIL.
- No Python 3 → fall back to `dotnet build -nologo -v:q -clp:"ErrorsOnly;Summary"` and `dotnet test -nologo --logger "console;verbosity=quiet"`.
- Never paste a full build/test log into a report. Cite the log path plus the relevant excerpt.
- A full-verbosity rerun (`-v:normal`/`-v:detailed`, or dropping the quiet logger) diagnoses only what filtered output cannot localize — never the default.
- Deliberate divergence (convention #8): the no-Python fallback is tighter than `run_quiet.py`'s no-information-lost guarantee — `-clp:ErrorsOnly` drops warnings at the MSBuild level, unrecoverable afterward; acceptable because warning review stays with the reviewer axis (code-review-and-quality) and CI, never agent transcripts.

### Verification Checklist

Before marking work complete:

- [ ] New code lands in the correct project layer; `Domain` stays dependency-free
- [ ] API mode matches the blueprint; no mixing (no repositories in REPR, no ad-hoc endpoints in CQRS)
- [ ] Read-only queries use `AsNoTracking()` and project to DTOs where a subset suffices
- [ ] No cascade delete on critical records; concurrency handled where writes race
- [ ] No transaction span awaits an out-of-process call; a de-spanned check-then-write invariant is carried by a committed reservation
- [ ] All async methods propagate `CancellationToken`; no sync-over-async
- [ ] DB-crossing behavior covered by real-Dev-DB integration tests, zero mocked `DbContext` (Quinn authors these — builders verify they exist or flag the gap)
- [ ] Every response (both modes) is a `BaseResponse<T>` envelope; failures are registry-coded `Error`s in `Notifications`, mapped once (`ToActionResult<T>()` Mode A / `ToResult<T>()` + `IExceptionHandler` Mode B) — no bare payloads, no ad-hoc status codes
- [ ] Every envelope claim backed by a **Tier 3** capture under `evidence/runtime/` — never a `WebApplicationFactory` test alone, never a source read of the wrapper's registration
- [ ] DIP holds; no framework/IO types in `Domain`/`Core`; no `NotImplementedException` interface members

### Escalate When

- The blueprint declares no API mode, or the change requires mixing → report to the Orchestrator.
- Dev DB unreachable, or schema diverges from migrations → report; NEVER fall back to mocks.
- The app cannot start out-of-process (Tier 3 impossible) → report; record the wire criterion `BLOCKED`. **NEVER substitute Tier 2** — an in-process pass on a wire claim is a fabrication in effect (`base-persona.md`, Evidence Integrity).
- A requirement demands cascade delete on critical records or an untracked write path → report before implementing.

## Deep Dive — Mode-Scoped Playbooks

Read on demand. **Load only the declared mode's playbook** plus the two shared ones — the other mode's playbook is noise for this project.

- **Mode A →** [cqrs-playbook.md](references/cqrs-playbook.md) — MediatR validation pipeline behavior; Mode A's Response Pattern emit via `BaseController<T>`.
- **Mode B →** [repr-playbook.md](references/repr-playbook.md) — REPR + Vertical Slice: endpoint structure, endpoint filters, `IQueryable<T>` extensions, composition root, migration checklist, worked example; REPR's emit via `.ToResult()` + `IExceptionHandler`.
- **Both →** [response-and-errors.md](references/response-and-errors.md) — the `BaseResponse<T>` envelope, `Error`/`ErrorCode` + registries, `Notifications`, `CustomException`, per-mode emit paths.
- **Both →** [data-and-testing.md](references/data-and-testing.md) — AsNoTracking + projection GOOD/BAD, the transaction-span hazard, async token propagation, the zero-mock Dev-DB integration pattern.
