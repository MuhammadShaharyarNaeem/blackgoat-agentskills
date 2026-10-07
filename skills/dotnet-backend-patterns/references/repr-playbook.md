# REPR + Vertical Slice Playbook (Mode B) — Code Patterns

Read this when the blueprint declares **Mode B**. Shared EF Core / async / testing discipline lives in [data-and-testing.md](data-and-testing.md). The `BaseResponse<T>` envelope + error model lives in [response-and-errors.md](response-and-errors.md); whether a REPR API emits it depends on which of the two cases below it is (see "Response Pattern in REPR").

This playbook holds **patterns only**. It serves two cases:

| | Case 1 — a **new** REPR API | Case 2 — REPR on an **existing** controller + MediatR solution |
|---|---|---|
| Projects | `Api` / `Core` / `DAL.EF` / `Infrastructure` (+ `Tests`) — §2.1–§2.5 | The existing `API` / `BLL` / `EF` projects are kept — §2.6 |
| Wire contract | `BaseResponse<T>` envelope + `IExceptionHandler` | **Unchanged** from the legacy controllers — no envelope, legacy routes |
| Route prefix | `MapGroup("api")` + an API version set | The legacy route literal (e.g. `billingfuncinbound/...`) |
| Entities | Scaffolded, database-first, in `DAL.EF` | Scaffolded, database-first, in the existing `EF` project |

> **Note on names:** concrete names below (`Gorelo.Integrations.REPR.*`, `BillingFuncInbound`, Pax8) come from Gorelo's real projects and are illustrative. Apply the *pattern* with the target project's own names.

## Canonical minimal contrast — GOOD/BAD

The one endpoint shape. Every endpoint in this playbook has it; only the return line differs between the two cases.

```csharp
// Api/Endpoints/Orders/GetOrderSummaryEndpoint.cs — everything the route needs, in one file.
public sealed record GetOrderSummaryRequest(Guid OrderId);
public sealed record GetOrderSummaryResponse(Guid Id, string Status, decimal Total);   // slice-owned payload

public static class GetOrderSummaryEndpoint
{
    // Called by OrdersEndpointsExtension.MapOrdersEndpoints() on the "orders" feature group (§4).
    // The route is relative to the group prefix.
    public static void MapGetOrderSummaryEndpoint(this IEndpointRouteBuilder group) =>
        group.MapGet("{orderId:guid}/summary", HandleAsync)
             .WithName("GetOrderSummary")
             .Produces<BaseResponse<GetOrderSummaryResponse>>(StatusCodes.Status200OK);   // case 1

    // public: fast tests call HandleAsync directly (§8.2). Dependencies are method parameters.
    public static async Task<IResult> HandleAsync(
        [AsParameters] GetOrderSummaryRequest request,
        AppDbContext db,                 // direct DbContext — NO repository in REPR mode
        CancellationToken ct)
    {
        var order = await db.Orders
            .AsNoTracking()
            .Where(o => o.Id == request.OrderId)
            .Select(o => new GetOrderSummaryResponse(o.Id, o.Status, o.Lines.Sum(l => l.Price * l.Qty)))
            .FirstOrDefaultAsync(ct);

        if (order is null)
            throw new CustomException(                       // → the one IExceptionHandler
                ErrorCode.From(MicroserviceCodes.Domain, ErrorTypeCodes.Toast_Validations, 1),
                "Order not found.", HttpStatusCode.NotFound);

        // Case 1 (new API): the envelope. Case 2 returns what the legacy action returned — see below.
        return BaseResponse<GetOrderSummaryResponse>.Success(order).ToResult();
    }
}
```

```csharp
// BAD (REPR mode): repository abstraction wrapping EF Core — banned bloat here.
public interface IOrderRepository { Task<Order?> GetByIdAsync(Guid id); }

// BAD (both cases): a try/catch per handler that turns every exception into its own Results.Problem(...).
// Failures are thrown and mapped ONCE by the IExceptionHandler. (Both earlier conversions did this — §12.)
try { /* ... */ } catch (Exception) { return Results.Problem("An unexpected error occurred.", statusCode: 500); }

// BAD (case 2): wrapping a legacy response in BaseResponse<T> — that is a contract change, not a migration.
```

> **Envelope ≠ shared DTO.** The "No Shared DTOs" rule (§3.3) still holds in case 1: `GetOrderSummaryResponse` is owned by this slice. `BaseResponse<T>` is a cross-cutting *transport envelope* wrapping that slice-owned payload — it is not a shared domain DTO, so it does not violate the rule.

---

## Response Pattern in REPR

**Case 1 — a new API, or a separately declared contract change.** REPR endpoints use the same [`BaseResponse<T>` envelope + error model](response-and-errors.md) as CQRS, so the frontend gets one contract across both modes. The difference is purely the *emit mechanism* — no `BaseController`:

- **Success:** build `BaseResponse<T>.Success(payload)` and return `.ToResult()` (the `IResult` bridge — minimal APIs don't accept `IActionResult`). ⚠️ `ToResult` is not yet in BG.Core; add it per [response-and-errors.md §5](response-and-errors.md).
- **Failure:** throw `CustomException` (or let `ValidationException` bubble from the validation filter) and map it **once** in the `BaseResponseExceptionHandler` of [response-and-errors.md §5](response-and-errors.md), registered in `Program.cs`. This is the REPR equivalent of the CQRS base-controller try/catch, consistent with §3.3 "use native ASP.NET Core, don't abstract the framework."

**Case 2 — REPR on an existing API: the wire contract is preserved.** This is a deliberate refinement (convention #8) of [SKILL.md](../SKILL.md)'s Response Pattern rule "every API result maps to `BaseResponse<T>`": that rule binds new APIs; a migration to REPR is a pattern change, not a contract change. Routes and verbs, request shapes, response bodies, status codes, content types and headers stay as the legacy controllers emit them. No envelope, and no `/api` or `/api/v1` prefix unless the legacy route already has one. Each handler returns the `Results.*` value that reproduces what the legacy action returned — and "reproduces" is a Tier 3 claim proven on the running app, never by reading source: `Results.Ok(x)` is not wire-identical to MVC's `Ok(x)` for every `x` (MVC writes a `string` through its text formatter, and turns a `null` value into `204`).

**Failures, both cases: exactly one `IExceptionHandler`.** In case 2 it reproduces the legacy error body instead of the envelope. A controller-era Gorelo API typically maps exceptions in an `ErrorController` behind `UseExceptionHandler("/error")`, returning `ControllerBase.Problem(...)`. BillingFuncInbound's (`Controllers/ErrorController.cs:54-70`, wired at `Startup.cs:304`) is:

| Exception type **name** | Status | Body (`application/problem+json`) |
|---|---|---|
| `ValidationException` | 400 | `type` = the framework's link for the status, `title` = `ex.Message`, `status`, `detail` = `ex.StackTrace`, `instance` = the request path, `traceId` |
| `KeyNotFoundException` | 404 | same fields |
| anything else | 500 | same fields |

The REPR handler reproduces that rule — same name-based mapping, same fields, same log call — in one place:

```csharp
// Api/Infrastructure/LegacyProblemDetailsExceptionHandler.cs — case 2 only.
// Mirrors the legacy ErrorController.Error action. Registered with AddExceptionHandler<T>() + AddProblemDetails()
// and run by app.UseExceptionHandler() (§7).
public sealed class LegacyProblemDetailsExceptionHandler(ILogger<LegacyProblemDetailsExceptionHandler> logger)
    : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(HttpContext httpContext, Exception exception, CancellationToken ct)
    {
        var typeName = exception.GetType().Name;
        logger.LogError(exception, typeName);                    // the legacy log call

        var status = typeName switch                              // by type NAME, as the legacy switch did
        {
            "ValidationException" => StatusCodes.Status400BadRequest,
            "KeyNotFoundException" => StatusCodes.Status404NotFound,
            _ => StatusCodes.Status500InternalServerError,
        };

        var problem = new ProblemDetails
        {
            // Copy each `type` value from the legacy capture; do not assume today's framework default matches.
            Type = status switch
            {
                400 => "https://tools.ietf.org/html/rfc9110#section-15.5.1",
                404 => "https://tools.ietf.org/html/rfc9110#section-15.5.5",
                _ => "https://tools.ietf.org/html/rfc9110#section-15.6.1",
            },
            Title = exception.Message,
            Status = status,
            Detail = exception.StackTrace,                        // legacy leaks this; see §12
            Instance = httpContext.Request.Path.Value,
        };
        problem.Extensions["traceId"] = Activity.Current?.Id ?? httpContext.TraceIdentifier;   // as MVC's factory does

        httpContext.Response.StatusCode = status;
        await httpContext.Response.WriteAsJsonAsync(problem, (JsonSerializerOptions?)null, "application/problem+json", ct);
        return true;
    }
}
```

The legacy *Development* branch (`/error-local-development`, a wider type map) is not reproduced: clients only ever see the non-Development branch. Say so where the conversion is declared.

---

## 1. Core Philosophy

### 1.1 Locality of Behavior (LoB)
Everything related to a single feature (the route, the request/response models, the validation, and the business logic) must live as close together as possible—ideally in a single file or a single feature folder.

**If an AI or a Developer wants to understand a feature, they should only have to open ONE folder.**

### 1.2 What We Eliminate
| Removed Pattern | Replacement |
|---|---|
| MediatR / CQRS | Direct method calls, Endpoint Filters |
| Controllers | Minimal API Endpoint classes (one per route), grouped per feature (§4) |
| Repository Pattern | `DbContext` injected directly + `IQueryable<T>` extension methods |
| Shared DTOs | Each endpoint owns its own Request/Response models (case 2 keeps legacy wire shapes — §3.3) |
| `IPipelineBehavior` (MediatR) | `IEndpointFilter` (ASP.NET Core native) |
| N-Tier (API/BLL/DAL) | Vertical Slices grouped by Feature (case 2 keeps the BLL as the service layer — §2.6) |

---

## 2. Project Structure

**Case 1 (new API)** uses **4 projects** — `Api`, `Core`, `DAL.EF`, `Infrastructure` — plus a `Tests` project and, for scaffolding only, a `DAL.EF.Design` project (§6.5). There is no `Application` project: REPR has no MediatR handlers to put in one. The four-project split holds for a small microservice too — `dotnet-backend-patterns/SKILL.md` Mode B grants no single-project exception. The `Api` project's name is not fixed (`.Api`, `.API` or bare — the real projects use all three); pick one per solution. **Case 2** keeps the existing projects — §2.6.

| Project | References |
|---|---|
| `Api` | `Core`, `DAL.EF`, `Infrastructure` |
| `Core` | nothing |
| `DAL.EF` | nothing — scaffolded entities need no Core type |
| `Infrastructure` | `Core`, `DAL.EF` (services and cache fillers query `AppDbContext`) |
| `DAL.EF.Design` | `DAL.EF` — scaffold-time startup project only, never referenced, not in the `.sln` |
| `Tests` | the four above |

### 2.1 `YourApp.Api` — The Application Shell + Features
This is the entry point. It contains `Program.cs`, global filters, and all feature slices.

- **NuGet:** `FluentValidation`, `FluentValidation.DependencyInjectionExtensions` (for `AddValidatorsFromAssemblyContaining`), `Swashbuckle.AspNetCore` (Swagger document + dev-only UI — what both real REPR projects use), `Asp.Versioning.Http` + `Asp.Versioning.Mvc.ApiExplorer` (the version set, §4), ASP.NET Core (built-in)
- **Contains:** `Endpoints/{Feature}/` folders (§4), `Extensions/` (the central `EndpointExtensions` registry and an `Add{App}Services(services, configuration)` DI extension), `Filters/`, the one `IExceptionHandler`, `Program.cs` (Composition Root)

### 2.2 `YourApp.Core` — Contracts (Pure C#)
Core stays **pure**: no EF Core, no ASP.NET, no Redis, no Service Bus, no vendor SDK.

- **References / NuGet:** nothing
- **Contains:**
  - **`Config/`** — configuration POCOs (`AppConfiguration` and its nested sections), bound with `IOptions<AppConfiguration>`.
  - **`Interfaces/`** — service contracts (`IXeroService`, `ITopicSender`, `IPax8AuthCacheService`). Their signatures use Core types only — an interface exposing `ServiceBusMessage` drags the SDK into Core.
  - **`Models/`** — DTOs shared between services and their interfaces.
  - **`Enums/`**, **`Constants/`** (e.g. topic names).
  - Pure static business rules over Core models, when they exist (§6.2).
- **Contains no entities.** Entities are scaffolded in `DAL.EF` (§2.3).

Both real REPR projects violate this — their Core references `Gorelo.RedisManager` and `Azure.Messaging.ServiceBus`, and one also EF Core and four vendor SDKs (§12). That is the anti-pattern, not the pattern: those packages belong in `Infrastructure`.

### 2.3 `YourApp.DAL.EF` — The Database Layer (database-first)
This project owns EF Core. The **database** owns the schema: entities and the `DbContext` are **scaffolded from SQL Server** and regenerated, never hand-written.

- **NuGet:** `Microsoft.EntityFrameworkCore.SqlServer` only. `Microsoft.EntityFrameworkCore.Design` lives in the separate `DAL.EF.Design` project so it never ships (§6.5).
- **Contains:**
  - `AppDbContext.cs` — scaffolded `public partial class AppDbContext : DbContext`, Fluent configuration inline in `OnModelCreating`, ending in `partial void OnModelCreatingPartial(ModelBuilder)`.
  - `Entities/*.cs` — scaffolded `public partial class` POCOs, one per table.
  - `AppDbContext.Partial.cs` — the **only** hand-written model code: it implements `OnModelCreatingPartial` and survives a re-scaffold.
  - `CodeTemplates/EFCore/*.t4`, `scaffold.ps1`, `.config/dotnet-tools.json` (the pinned local `dotnet-ef`).
- **Does not contain:** `IEntityTypeConfiguration<T>` classes, a `Migrations/` folder, or behaviour on entities.

### 2.4 `YourApp.Infrastructure` — External Integrations
This project handles all communication with the outside world.

- **NuGet:** `Gorelo.RedisManager`, `Azure.Messaging.ServiceBus`, vendor SDKs (`Duende.IdentityModel`, `IppDotNetSdkForQuickBooksApiV3`, `Gorelo.Sdk.*`), etc.
- **Contains:**
  - Implementations of Core interfaces (`XeroService : IXeroService`, `TopicSender : ITopicSender`), including services that query `AppDbContext`.
  - Redis cache services (wrappers over `Gorelo.RedisManager`), named `HttpClient` configuration.
  - `IQueryable<T>` extension methods over the scaffolded entities (§6.1).

### 2.5 Folder Layout (case 1)

```text
Solution/
├── YourApp.Api/
│   ├── Program.cs                          # Composition Root (registers services, calls MapFeatureEndpoints)
│   ├── Filters/
│   │   ├── GoreloContextFilter.cs          # §5.3
│   │   ├── ValidationFilter.cs             # §5.1
│   │   └── ValidationFilterExtensions.cs
│   ├── Infrastructure/
│   │   └── BaseResponseExceptionHandler.cs # the one IExceptionHandler (response-and-errors.md §5)
│   ├── Endpoints/                          # one flat folder per feature (§4)
│   │   ├── Customers/
│   │   │   ├── CustomersEndpointsExtension.cs  # creates the "customers" group, maps every customer endpoint
│   │   │   ├── CreateCustomerEndpoint.cs       # Request + Response + Handler
│   │   │   ├── CreateCustomerRequestValidator.cs
│   │   │   └── GetCustomerByIdEndpoint.cs
│   │   └── Orders/
│   │       ├── OrdersEndpointsExtension.cs
│   │       ├── CreateOrderEndpoint.cs
│   │       ├── CreateOrderRequestValidator.cs  # validators live beside their endpoint
│   │       ├── CreateOrderService.cs           # feature-local service (§6.3)
│   │       └── GetOrderSummaryEndpoint.cs
│   └── Extensions/
│       ├── EndpointExtensions.cs           # central registry: MapGroup("api") + version set, calls each Map{Feature}Endpoints
│       └── ServiceExtensions.cs            # AddYourAppServices(services, configuration)
│
├── YourApp.Core/
│   ├── Config/AppConfiguration.cs
│   ├── Constants/TopicConstants.cs
│   ├── Enums/OrderStatus.cs
│   ├── Interfaces/IEmailService.cs
│   └── Models/CustomerDto.cs
│
├── YourApp.DAL.EF/                         # scaffolded — §6.5
│   ├── .config/dotnet-tools.json
│   ├── CodeTemplates/EFCore/{DbContext,EntityType}.t4
│   ├── AppDbContext.cs                     # GENERATED — never edit
│   ├── AppDbContext.Partial.cs             # hand-written OnModelCreatingPartial
│   ├── Entities/OrderEntity.cs             # GENERATED — never edit
│   └── scaffold.ps1
├── YourApp.DAL.EF.Design/
│   └── DesignTimeServices.cs               # scaffold-time naming only
│
├── YourApp.Infrastructure/
│   ├── Services/SmtpEmailService.cs        # implements Core's IEmailService
│   └── Queries/CustomerQueries.cs          # IQueryable<T> extension methods
│
└── YourApp.Tests/
    └── Endpoints/Orders/CreateOrderEndpointTests.cs
```

### 2.6 REPR on an existing API / BLL / EF solution (case 2)

REPR can sit on a controller + MediatR solution **without restructuring its projects**. This is the layout pattern; how to get there is out of scope (§9).

| Existing project | Role under REPR | Holds |
|---|---|---|
| `Gorelo.API.{X}` | `Api` | `Program.cs` (minimal hosting), `Endpoints/{Feature}/` (endpoint files, each feature's `{Feature}EndpointsExtension.cs`, validators, feature-local services), `Extensions/EndpointExtensions.cs`, `Filters/`, the legacy-shape `IExceptionHandler`, `AppConfig/`. **No** `Controllers/`, no `Startup.cs`. |
| `Gorelo.Layers.{X}.BLL` | the service layer (Core + Infrastructure in one) | `Service/`, `Models/`, `Helpers/` (static rules), enums, constants, cache services, `ITopicSender` — the services endpoints call. **No** `Features/` (MediatR commands, queries, handlers), no `IPipelineBehavior`, no MediatR package. |
| `Gorelo.Layers.{X}.EF` (+ `.EF.Design`) | `DAL.EF` | Unchanged: scaffolded `AppDbContext` + `Entities/`, `AppDbContext.Partial.cs`, `CodeTemplates/`, `scaffold.ps1`. |
| `Gorelo.API.{X}.Tests` | `Tests` | Endpoint tests (§8). |

Deliberate divergence (convention #8): the BLL keeps Redis, Service Bus and vendor SDKs beside its models, which is looser than §2.2's "Core stays pure". §2.2 binds the projects of a new API; splitting an existing BLL into Core and Infrastructure is a separate refactor, never a side effect of adopting REPR. The other rules of this playbook — one endpoint shape (§3.1), feature grouping (§4), one `IExceptionHandler`, no repositories, `AsNoTracking` + projection — bind in both cases.

```text
Gorelo.API.{X}/
├── Program.cs
├── AppConfig/AppConfiguration.cs
├── Filters/GoreloContextFilter.cs
├── Infrastructure/LegacyProblemDetailsExceptionHandler.cs
├── Endpoints/
│   ├── Invoice/
│   │   ├── InvoiceEndpointsExtension.cs    # group "billingfuncinbound" (the legacy prefix), tag "Invoice"
│   │   ├── CreatePdfEndpoint.cs            # POST billingfuncinbound/createpdf — legacy literal
│   │   └── CreatePdfForEmailEndpoint.cs
│   └── QuickBooks/
│       ├── QuickBooksEndpointsExtension.cs
│       └── GetQuickBooksClientsEndpoint.cs # POST billingfuncinbound/getclientsforquickbooks
└── Extensions/EndpointExtensions.cs        # MapFeatureEndpoints() — no "api" prefix in case 2
Gorelo.Layers.{X}.BLL/
├── Service/  Models/  Helpers/             # kept: what the endpoints call
Gorelo.Layers.{X}.EF/  Gorelo.Layers.{X}.EF.Design/   # unchanged
```

---

## 3. The REPR Pattern — Rules

### 3.1 Endpoint File Structure
Every endpoint file follows this exact structure — the same shape as the canonical sample above:

```csharp
// File: Endpoints/{Feature}/{Verb}{Entity}Endpoint.cs
// Example: Endpoints/Orders/CreateOrderEndpoint.cs

namespace YourApp.Api.Endpoints.Orders;                 // namespace = folder path

// 1. Request model (owned by this endpoint)
public sealed record CreateOrderRequest(Guid CustomerId, List<string> ItemIds);

// 2. Response model (owned by this endpoint)
public sealed record CreateOrderResponse(Guid OrderId, string Status);

// 3. Static endpoint class
public static class CreateOrderEndpoint
{
    // 4. Route mapping — called by OrdersEndpointsExtension.MapOrdersEndpoints() on the "orders" group (§4).
    //    The route is relative to the group; prefix, tags and shared filters come from the group.
    public static void MapCreateOrderEndpoint(this IEndpointRouteBuilder group) =>
        group.MapPost("/", HandleAsync)
             .WithName("CreateOrder")
             .WithSummary("Create an order")
             .AddValidation<CreateOrderRequest>()
             .Produces<BaseResponse<CreateOrderResponse>>(StatusCodes.Status201Created);   // case 1

    // 5. Handler — public static; every dependency is a method parameter.
    public static async Task<IResult> HandleAsync(
        CreateOrderRequest request,
        AppDbContext db,
        ILoggerFactory loggerFactory,
        CancellationToken ct)
    {
        var logger = loggerFactory.CreateLogger(typeof(CreateOrderEndpoint));
        logger.LogInformation("Creating order for CustomerId {CustomerId}", request.CustomerId);
        var response = new CreateOrderResponse(Guid.NewGuid(), "Pending");   // business logic here
        // Case 1. In case 2 return the legacy action's result instead ("Response Pattern in REPR").
        return BaseResponse<CreateOrderResponse>.Success(response, HttpStatusCode.Created).ToResult();
    }
}
```

In case 2 the mapping keeps the legacy literal and declares the legacy result type — `group.MapPost("createpdf", HandleAsync).Produces<string>(StatusCodes.Status200OK).ProducesProblem(StatusCodes.Status500InternalServerError)` on the `billingfuncinbound` group.

### 3.2 Naming & Mapping Conventions

| Element | Convention | Example |
|---|---|---|
| Endpoint Class | `public static class {Verb}{Entity}Endpoint` | `CreateOrderEndpoint` |
| Request Model | `{Verb}{Entity}Request` — top-level in the endpoint file | `CreateOrderRequest` |
| Response Model | `{Verb}{Entity}Response` — top-level in the endpoint file; omitted when the route returns a primitive | `CreateOrderResponse` |
| Endpoint Mapping Method | `Map{Verb}{Entity}Endpoint(this IEndpointRouteBuilder group)` in the endpoint class (both real REPR projects end it in `Endpoint`) | `MapCreateOrderEndpoint(...)` |
| Handler Method | `public static async Task<IResult> HandleAsync(...)`; a synchronous `public static IResult Handle(...)` when the route does no I/O | `HandleAsync` |
| Logger | `ILoggerFactory` parameter + `CreateLogger(typeof({Verb}{Entity}Endpoint))` — a static class cannot be `ILogger<T>`'s argument (CS0718) | `CreateLogger(typeof(CreateOrderEndpoint))` |
| Validator Class | `{Verb}{Entity}RequestValidator` — same folder as the endpoint | `CreateOrderRequestValidator` |
| Feature Folder | `Endpoints/{Feature}/` — flat, one per feature (§4) | `Endpoints/Orders/` |
| Feature Extension File | `{Feature}EndpointsExtension.cs`, in the feature folder | `OrdersEndpointsExtension.cs` |
| Feature Registration Method | `Map{Feature}Endpoints(this IEndpointRouteBuilder app)` — creates the feature group, calls each `Map{Verb}{Entity}Endpoint()` on it | `MapOrdersEndpoints(...)` |
| Central Registry | `Extensions/EndpointExtensions.cs`, `MapFeatureEndpoints(this IEndpointRouteBuilder app)` | `app.MapFeatureEndpoints()` |
| Route literal | Case 1: lower-case, relative to the group. Case 2: the legacy literal, verb and casing unchanged | `"{orderId:guid}/summary"`, `"TimeSpentPDFExport"` |

One file maps one route. A real exception exists (FunctionInbound's `CreatePDFEndpoint.cs` maps `createpdf` and `createpdfforemail`); split it into two endpoint files.

### 3.3 Inviolable Rules

1. **Slices NEVER call other Slices.** `CreateOrderEndpoint` must NEVER inject or call `UpdateInventoryEndpoint`. If two slices need the same logic, extract it to a service or a static helper (§6.2–§6.4) — never into a scaffolded entity.

2. **No Shared DTOs.** Every endpoint owns its own Request and Response models. Duplication of DTOs is cheaper than the wrong abstraction. Deliberate divergence (convention #8): in case 2 a request or response type that *is* a legacy wire shape keeps that shape exactly — same property names, types and nullability — because the contract is frozen; reuse an existing BLL `Models/` type rather than re-declaring it with drift. A Core/BLL model consumed by a service interface is not a slice DTO.

3. **No Abstracting the Framework.** Use `DbContext` directly. Use Minimal APIs directly. Do not build wrappers.

4. **No God Services.** Do not create `CustomerService` with 20 methods. If complex logic is needed for a single feature, create `{FeatureName}Service` in the same feature folder.

5. **Request/Response models are Records** (`sealed record`). Deliberate divergence (convention #8): a case-2 legacy wire shape may stay a mutable class (rule 2 above).

### 3.4 Configuration — Azure App Configuration

Read configuration through `IConfiguration`, never `Environment.GetEnvironmentVariable()`: non-secret settings live in **Azure App Configuration**; secrets, connection strings included, live in **Key Vault** and reach `IConfiguration` as Key Vault references (owner: `cloud-deploy-patterns/SKILL.md` § Baseline — Platform Invariants). Bind it to `Core/Config/AppConfiguration` (case 2: the solution's existing `AppConfiguration`) and inject it as `IOptions<AppConfiguration>`. The real projects agree on this shape:

- **Connect:** Development connects with `AzureAppConfiguration:ConnectionString`; every other environment with `AzureAppConfiguration:EndpointUrl` + `DefaultAzureCredential`.
- **Label:** `AppConfig_Label` is **required** — resolve it and throw `InvalidOperationException` when it is missing. Never default it.
- **Select:** one `Select(keyFilter, labelFilter)` per key prefix the app reads (`{App}:*`, `Topic:*`, `Queue:*`, `AppInsights:*` under the label). `GoreloAPI:*` is selected under **`{label}-vnet`**.
- **Bind a section, not the root:** `Configure<AppConfiguration>(configuration.GetSection("{App}"))`. Read values through `IOptions<AppConfiguration>`; a raw `configuration["{App}:Key"]` string read is for composition-root wiring only (a connection string handed to `AddDbContext`).
- **Fail fast** on a required key at startup (BillingFuncInbound's `Startup.RegisterAppDbContext` throws when `{App}:SQLServerConnectionString` is empty) rather than starting healthy with a dead dependency.

---

## 4. Feature Endpoint Grouping — All Endpoints of a Feature in One Place

Every endpoint of a feature lives in one folder and is registered by one extension in that folder. To understand or change a feature you open one folder; to see every route the API serves you open one registry.

**The three pieces:**

1. **One folder per feature** — `Endpoints/{Feature}/` holds every endpoint file of the feature, its validators, and its feature-local services (§6.3). Flat: no per-endpoint subfolders. Namespace = folder path.
2. **One `{Feature}EndpointsExtension.cs` in that folder** exposing `Map{Feature}Endpoints(this IEndpointRouteBuilder app)`. It creates the feature's **route group** — the shared prefix, `WithTags`, and the filters every endpoint of the feature needs (`RequireGoreloContext()`) — and maps every endpoint of the feature on that group. An endpoint declares only what differs from its siblings (its route, name, summary, `Produces`, its own validation).
3. **One central `Extensions/EndpointExtensions.MapFeatureEndpoints()`** — the only route call `Program.cs` makes (health checks aside). It builds what is shared by the whole API (the version set, the `api` prefix in case 1) and calls each feature's extension, one line per feature.

The shape comes from Gorelo.Integrations.REPR, whose nine feature extensions (`Pax8EndpointsExtension`, `HuntressEndpointsExtension`, `XeroEndpointsExtension`, …) each live in their feature folder and are called from one `MapFeatureEndpoints()`. This playbook takes one step further than that code: Integrations.REPR's extensions are flat call lists on the shared `api` group, repeating the feature prefix, the tag and `.RequireGoreloContext()` on every endpoint; here the feature group carries them once. FunctionInbound.REPR is the counter-example — two flat lists (`MapInboundEndpoints`, and `MapXeroExtensions`, which also registers two System endpoints) and no feature extension at all.

**Full sample — a feature extension (case 1):**

```csharp
// Api/Endpoints/Pax8/Pax8EndpointsExtension.cs
namespace YourApp.Api.Endpoints.Pax8;

public static class Pax8EndpointsExtension
{
    public static void MapPax8Endpoints(this IEndpointRouteBuilder app)
    {
        var group = app.MapGroup("pax8")           // shared prefix → /api/pax8/...
            .WithTags("Pax8")                      // shared Swagger tag
            .RequireGoreloContext();               // shared filter, once for the whole feature (§5.3)

        group.MapGetOAuthUrlEndpoint();
        group.MapCreatePax8OAuthEndpoint();        // POST /api/pax8/oauth
        group.MapListPax8CompaniesEndpoint();
        group.MapListPax8ClientSubscriptionsEndpoint();
        group.MapSyncPax8SubscriptionsAndProductsEndpoint();
        group.MapGetPax8ExpiryDaysEndpoint();
        group.MapCreatePax8CompanyEndpoint();
    }
}
```

```csharp
// Api/Endpoints/Pax8/CreatePax8OAuthEndpoint.cs — one of the endpoints it maps (shape only; §11 has the real one)
public static class CreatePax8OAuthEndpoint
{
    public static void MapCreatePax8OAuthEndpoint(this IEndpointRouteBuilder group) =>
        group.MapPost("oauth", HandleAsync)                        // relative to "pax8"
             .WithName("CreatePax8OAuth")
             .WithSummary("Create Pax8 OAuth")
             .Produces<BaseResponse<bool>>(StatusCodes.Status200OK);   // case 1

    public static async Task<IResult> HandleAsync(
        HttpContext httpContext, CreatePax8OAuthRequest request, CreatePax8OAuthService service, CancellationToken ct)
    {
        await service.ExecuteAsync(httpContext.GetGoreloContext(), request, ct);   // throws on failure
        return BaseResponse<bool>.Success(true).ToResult();                        // case 1
    }
}
```

**Full sample — the central registry (case 1):**

```csharp
// Api/Extensions/EndpointExtensions.cs
namespace YourApp.Api.Extensions;

public static class EndpointExtensions
{
    public static void MapFeatureEndpoints(this IEndpointRouteBuilder app)
    {
        var versionSet = app.NewApiVersionSet()
            .HasApiVersion(new ApiVersion(1, 0))
            .ReportApiVersions()
            .Build();

        // Version set, not a URL segment: the path is /api/pax8/oauth, not /api/v1/pax8/oauth
        // (AssumeDefaultVersionWhenUnspecified). Add "{version:apiVersion}" only if the API versions by URL.
        var api = app.MapGroup("api").WithApiVersionSet(versionSet);

        api.MapHuntressEndpoints();
        api.MapPax8Endpoints();
        api.MapXeroEndpoints();
        api.MapQuickBooksEndpoints();
        api.MapIntegrationEndpoints();
    }

    public static void MapHealthCheckEndpoints(this IEndpointRouteBuilder app)
    {
        app.MapHealthChecks("/live", new HealthCheckOptions { Predicate = r => r.Tags.Contains("live"), ResponseWriter = HealthCheckResponseWriter.WriteJsonResponse });
        app.MapHealthChecks("/ready", new HealthCheckOptions { Predicate = r => r.Tags.Contains("ready"), ResponseWriter = HealthCheckResponseWriter.WriteJsonResponse });
        // /startup and /health likewise — health checks stay outside the feature groups.
    }
}
```

**Case 2 — the same three pieces, with the legacy prefix.** The feature group's prefix is the legacy controller's `[Route]` prefix, and the central registry adds no `api` group. Several features may share one legacy prefix — each creates its own group on it:

```csharp
// Gorelo.API.BillingFuncInbound/Endpoints/QuickBooks/QuickBooksEndpointsExtension.cs
public static class QuickBooksEndpointsExtension
{
    public static void MapQuickBooksEndpoints(this IEndpointRouteBuilder app)
    {
        var group = app.MapGroup("billingfuncinbound")   // the legacy controller's [Route] prefix, verbatim
            .WithTags("QuickBooks");

        group.MapGetQuickBooksClientsEndpoint();     // POST billingfuncinbound/getclientsforquickbooks
        group.MapGetQuickBooksProductsEndpoint();    // POST billingfuncinbound/getproductsforquickbooks
        group.MapGetQuickBooksOAuthEndpoint();       // POST billingfuncinbound/getoauthforquickbooks
    }
}

// Gorelo.API.BillingFuncInbound/Extensions/EndpointExtensions.cs
public static void MapFeatureEndpoints(this IEndpointRouteBuilder app)
{
    // The legacy controllers carried [ApiVersion("1.0")] with ReportApiVersions = true, so their responses carry an
    // api-supported-versions header. An unprefixed group with the same version set keeps it; the capture decides.
    var versionSet = app.NewApiVersionSet().HasApiVersion(new ApiVersion(1, 0)).ReportApiVersions().Build();
    var legacy = app.MapGroup(string.Empty).WithApiVersionSet(versionSet);   // no "api" prefix in case 2

    legacy.MapInvoiceEndpoints();
    legacy.MapQuickBooksEndpoints();
    legacy.MapXeroEndpoints();
    legacy.MapIntegrationEndpoints();
}
```

A shared filter extension must target `TBuilder : IEndpointConventionBuilder`, not `RouteHandlerBuilder`, or it cannot be applied to a group (§5.3).

---

## 5. Cross-Cutting Concerns — Endpoint Filters

A MediatR `IPipelineBehavior` becomes an `IEndpointFilter` on the feature group or the endpoint. A behavior that nothing registers is dead code and is deleted, not converted — BillingFuncInbound's `RequestValidationBehavior` is one: `AddMediatR` registers handlers only, and no `AddBehavior`/`AddOpenBehavior` call exists.

### 5.1 Generic Validation Filter
Replaces MediatR's `IPipelineBehavior` for request validation. The filter *throws* `ValidationException`; the one `IExceptionHandler` maps it — to the envelope in case 1, to the legacy 400 body in case 2 (its name match catches FluentValidation's `ValidationException` too). In case 2, adding validation that the legacy endpoint did not run is a contract change (new `400`s) — declare it or leave it out.

```csharp
// Filters/ValidationFilter.cs
using FluentValidation;

public class ValidationFilter<TRequest> : IEndpointFilter
{
    public async ValueTask<object?> InvokeAsync(
        EndpointFilterInvocationContext context,
        EndpointFilterDelegate next)
    {
        var request = context.Arguments.OfType<TRequest>().FirstOrDefault();

        if (request is not null)
        {
            var validator = context.HttpContext.RequestServices
                .GetRequiredService<IValidator<TRequest>>();

            var result = await validator.ValidateAsync(request, context.HttpContext.RequestAborted);
            if (!result.IsValid)
                throw new ValidationException(result.Errors);
        }

        return await next(context);
    }
}
```

`GetRequiredService`, not `GetService`: applying `.AddValidation<T>()` declares that a validator for `T` exists, so a missing registration must fail loudly rather than silently skip validation.

### 5.2 Extension Method for Clean Chaining

```csharp
// Filters/ValidationFilterExtensions.cs
public static class ValidationFilterExtensions
{
    public static RouteHandlerBuilder AddValidation<TRequest>(this RouteHandlerBuilder builder)
    {
        return builder.AddEndpointFilter<ValidationFilter<TRequest>>();
    }
}
```

Validation is per endpoint (it is typed by the request), so `AddValidation<T>()` stays on `RouteHandlerBuilder`. Both earlier conversions shipped this filter with **zero** call sites and zero validators (§12) — a filter nothing applies is not validation.

### 5.3 Request Context — `GoreloContextFilter` / `RequireGoreloContext()`

Replaces the legacy `BaseController` properties. BillingFuncInbound's `BaseController` (`Controllers/BaseController.cs:14-17`) reads four query-string values with `Convert.ToInt64(HttpContext.Request.Query[...])`: `ServiceProviderId`, `RoleId`, `TechnicianId`, `tick`. The filter reads the same four once, stores them in `HttpContext.Items`, and the handler takes `HttpContext` and calls `GetGoreloContext()`. This is the real shape (Gorelo.Integrations.REPR `Filters/GoreloContextFilter.cs`, used by 52 of its 56 endpoints), with the registration extension made group-capable:

```csharp
// Api/Filters/GoreloContextFilter.cs — namespace = this project's, never the legacy project's (§12)
namespace YourApp.Api.Filters;

public record GoreloContext(long ServiceProviderId, long TechnicianId, long RoleId, long Tick);

public class GoreloContextFilter : IEndpointFilter
{
    public async ValueTask<object?> InvokeAsync(EndpointFilterInvocationContext context, EndpointFilterDelegate next)
    {
        var query = context.HttpContext.Request.Query;
        context.HttpContext.Items["GoreloContext"] = new GoreloContext(
            ServiceProviderId: long.TryParse(query["ServiceProviderId"], out var spId) ? spId : 0,
            TechnicianId: long.TryParse(query["TechnicianId"], out var techId) ? techId : 0,
            RoleId: long.TryParse(query["RoleId"], out var roleId) ? roleId : 0,
            Tick: long.TryParse(query["tick"], out var tick) ? tick : 0);
        return await next(context);
    }
}

public static class GoreloContextExtensions
{
    public static GoreloContext GetGoreloContext(this HttpContext httpContext)
        => (GoreloContext)httpContext.Items["GoreloContext"]!;

    // TBuilder, not RouteHandlerBuilder: applies to a feature group (§4) as well as to one endpoint.
    public static TBuilder RequireGoreloContext<TBuilder>(this TBuilder builder) where TBuilder : IEndpointConventionBuilder
        => builder.AddEndpointFilter<TBuilder, GoreloContextFilter>();
}
```

**Security weakness — do not mistake it for a design.** The context is client-asserted: it comes from the query string, and neither real REPR project (nor BillingFuncInbound) authenticates the caller. A missing or malformed id becomes `0`, so a request with no tenant is processed as tenant `0` instead of being rejected.

- **Case 1:** fail closed — return `400` when `ServiceProviderId` is absent or `≤ 0`, and derive identity from an authenticated principal once the API has authentication.
- **Case 2:** the weakness is inherited, not introduced; fixing it is a declared contract change. Note the parse difference: the legacy `Convert.ToInt64` gives `0` for a missing value but throws `FormatException` (a `500` through the legacy error handler) for a malformed one, while the filter's `TryParse` gives `0` for both. Keep the legacy parse in a case-2 filter, or declare the change. Apply the filter only where the legacy action read `BaseController` — in BillingFuncInbound that is `TimeSpentPDFExport` alone; the other routes take `ServiceProviderId` in the body.

### 5.4 Other Filter Examples
The same pattern applies to any cross-cutting concern:

- **`LoggingFilter`** — Log request/response timing.
- **`TransactionFilter`** — Wrap the handler in a database transaction and auto-commit/rollback. **Apply it only to handlers whose work is entirely in-process database work.** The filter's span covers the whole handler, so any outbound HTTP, SDK, or queue call the handler makes executes *inside* the transaction, holding a pooled connection and every locked row for the remote round-trip. A handler that must call an external dependency does not get this filter — it manages its own short transactions on either side of the call.
- **`AuthorizationFilter`** — Custom per-endpoint authorization checks.

Not every "filter" is an endpoint filter. An Application Insights `ITelemetryProcessor` — BillingFuncInbound's `TelemetryFilter`, which drops `OPTIONS` and `404` request telemetry — is independent of MVC and of REPR, and stays registered with `AddApplicationInsightsTelemetryProcessor<T>()`.

---

## 6. Shared Logic & EF Core

### 6.1 Shared Database Queries → `IQueryable<T>` Extension Methods
When the same query filter is needed across multiple endpoints, extract it as a static extension method over the scaffolded entity. Neither real REPR project has one yet (their queries are inline LINQ) — this is the target, not an observed practice.

```csharp
// Infrastructure/Queries/IntegrationQueries.cs   (case 2: Gorelo.Layers.{X}.BLL/Helpers/)
public static class IntegrationQueries
{
    public static IQueryable<IntegrationEntity> WhereActiveFor(
        this IQueryable<IntegrationEntity> query, long serviceProviderId, int externalIntegrationId)
        => query.Where(i => i.IsActive
                         && i.ServiceProviderId == serviceProviderId
                         && i.ExternalIntegrationId == externalIntegrationId);
}
```

**Usage in an Endpoint:**
```csharp
var integration = await db.Integration
    .AsNoTracking()
    .WhereActiveFor(ctx.ServiceProviderId, (int)ExternalIntegrationType.Xero)
    .Select(i => new GetXeroIntegrationResponse(i.IntegrationId, i.Config))
    .FirstOrDefaultAsync(ct);
```

### 6.2 Business Rules → a Static Helper or a Service, Never the Entity
Scaffolded entities are regenerated with `--force`; anything written into an entity file is deleted by the next scaffold, and a hand-written entity partial turns a table mirror into a domain object. Entities stay data. A business rule lives where the real code already puts it:

| The rule… | Lives in | Real example |
|---|---|---|
| is pure, over primitives or Core models | a `static` helper — `Core` (case 1) or the BLL's `Helpers/` (case 2) | `ExternalZeroValueLineRules.IsWaived(int? billableStatus)` (BLL `Helpers/`) |
| is a data-access idiom over EF results | a `static` extension next to the queries | `EfUpdateExtensions.ThrowIfNoRowsAffected(this int rowsAffected, string entityName)` (BLL `Helpers/`) |
| needs I/O or several collaborators | a service — `Infrastructure` behind a Core interface (case 1) or the BLL's `Service/` (case 2) | `QBOTaxService`, `XeroContactService` (BLL `Service/`) |
| is used by one feature only | a feature-local service in `Endpoints/{Feature}/` (§6.3) | `CreatePDFService` (FunctionInbound.REPR) |

```csharp
// Core/Rules/ExternalZeroValueLineRules.cs (case 1)  |  Gorelo.Layers.{X}.BLL/Helpers/ExternalZeroValueLineRules.cs (case 2)
public static class ExternalZeroValueLineRules
{
    private const int NotBillable = 2;
    private const int NotBillableHidden = 3;

    // Branch on BillableStatus, never on the discount.
    public static bool IsWaived(int? billableStatus) =>
        billableStatus == NotBillable || billableStatus == NotBillableHidden;
}
```

A static rule is tested directly, with no database (§8.5).

### 6.3 Complex Multi-Step Operations → Dedicated Feature Service
If a single endpoint's handler exceeds ~80 lines, extract its logic into a service that lives **in the same feature folder**.

```text
Endpoints/Orders/
├── CreateOrderEndpoint.cs
├── CreateOrderService.cs              ← extracted logic
└── CreateOrderRequestValidator.cs
```

The service is a concrete class registered `Scoped`, injected as itself — as in the real code — and tested against a real `AppDbContext` (§8.2), so its methods are never made `virtual` just to be mocked. The endpoint handler becomes a thin delegation:
```csharp
public static async Task<IResult> HandleAsync(
    CreateOrderRequest request,
    CreateOrderService service,
    CancellationToken ct)
{
    CreateOrderResponse result = await service.ExecuteAsync(request, ct);
    return BaseResponse<CreateOrderResponse>.Success(result, HttpStatusCode.Created).ToResult();   // case 1
}
```

### 6.4 External Integrations → Infrastructure Services behind Core Interfaces
For talking to the outside world, define the interface in Core and implement it in Infrastructure (case 2: both in the BLL, interface beside implementation as the BLL already does).

```csharp
// Core/Interfaces/IEmailService.cs
public interface IEmailService
{
    Task SendAsync(string to, string subject, string body, CancellationToken ct);
}

// Infrastructure/Services/SmtpEmailService.cs
public class SmtpEmailService : IEmailService
{
    public async Task SendAsync(string to, string subject, string body, CancellationToken ct)
    {
        // Actual SMTP implementation
    }
}
```

The real projects agree on these lifetimes and clients, registered in one `Add{App}Services(services, configuration)`:

- `RedisConnectionManager` and the `Gorelo.RedisManager` cache wrappers (`XeroOAuth`, `Pax8Auth`, …) — **singleton**; the cache services over them singleton.
- `ServiceBusClient` (via `AddAzureClients`) and `ITopicSender` — **singleton**.
- Named `HttpClient`s: `"ExternalApis"`, and `"GoreloApis"` with the `api-auth` header from configuration.
- Stateless services — scoped or transient; anything holding `AppDbContext` — **scoped**.

### 6.5 EF Core — Database-First Scaffolding

| Component | Project | Notes |
|---|---|---|
| `AppDbContext` | `DAL.EF` | Scaffolded `partial` class at the project root (`--context-dir .`). Named `AppDbContext` — the earlier REPR projects' `AppDBContext` is the inconsistency (§12). |
| Entities | `DAL.EF/Entities/` | Scaffolded `partial` POCOs, one per table; never hand-edited. |
| Hand-written model fixes | `DAL.EF/AppDbContext.Partial.cs` | The other half of the `partial` class: implements `OnModelCreatingPartial`. Survives a re-scaffold. |
| Scaffold templates | `DAL.EF/CodeTemplates/EFCore/` | `DbContext.t4`, `EntityType.t4` — customised T4, checked in. |
| Scaffold naming | `DAL.EF.Design/DesignTimeServices.cs` | `IDesignTimeServices`, picked up by `dotnet ef` at scaffold time only. |
| Schema changes | the database | No EF migrations, no `Migrations/` folder, no `IEntityTypeConfiguration<T>`. The schema is changed in the database, then re-scaffolded. |
| `IQueryable<T>` extensions | `Infrastructure` (case 2: BLL) | §6.1. |

**How BillingFuncInbound scaffolds** (`Gorelo.Layers.Integration.EF/scaffold.ps1`, the shape to copy):

1. Reads the connection string from Azure App Configuration — `az appconfig kv show --name gorelo-dev --key BillingFunc:SQLServerConnectionString --label usw` — resolving a Key Vault reference with `az keyvault secret show` when the value is one. The connection string is never written to disk.
2. Names the tables explicitly (`--table Integration.<Name>` for each of the 18), so the scaffold never picks up a table the app does not map.
3. Runs `dotnet tool restore`, then the **local** `dotnet-ef` pinned in `.config/dotnet-tools.json` (8.0.0, matching the EF Core packages):

```powershell
dotnet ef dbcontext scaffold $conn Microsoft.EntityFrameworkCore.SqlServer `
    --project Gorelo.Layers.Integration.EF.csproj `
    --startup-project ..\Gorelo.Layers.Integration.EF.Design\Gorelo.Layers.Integration.EF.Design.csproj `
    --context AppDbContext --context-dir . --output-dir Entities `
    --namespace Gorelo.Layers.Integration.EF.Entities --context-namespace Gorelo.Layers.Integration.EF `
    --no-onconfiguring --force @tables
```

- **`--startup-project` is the `.Design` project**, so `Microsoft.EntityFrameworkCore.Design` is referenced only there; the runtime `.EF` project references `Microsoft.EntityFrameworkCore.SqlServer` alone. The `.Design` project is not in the `.sln` and nothing references it.
- **`--no-onconfiguring`**: the connection string is supplied by `AddDbContext` at the composition root, never baked into the context.
- **Naming:** `DesignTimeServices` registers a `CandidateNamingService` that appends `Entity` (`IntegrationEntity` — the LLBLGen-era name, and no clash with the `Integration` namespace), and the customised `DbContext.t4` strips that suffix from the `DbSet` name (`DbSet<IntegrationEntity> Integration`). Both earlier REPR projects scaffolded with default naming instead; pick one per solution.
- **`AppDbContext.Partial.cs`** is where a scaffold default is corrected. BillingFuncInbound's sets `HasSentinel(true)` on `bool` columns the scaffold maps with `HasDefaultValue(true)`, so an explicit `false` is written instead of being swallowed by the database default.

**Registration.** `AddDbContext<AppDbContext>(o => o.UseSqlServer(connectionString, sql => { sql.EnableRetryOnFailure(...); sql.CommandTimeout(...); }))`, with the connection string read from App Configuration and checked at startup (§3.4). BillingFuncInbound registers `AddDbContextFactory<AppDbContext>` as a transitional step — it also registers the scoped `AppDbContext` that endpoints inject. With `EnableRetryOnFailure`, a user-initiated `BeginTransactionAsync` throws unless it runs inside `db.Database.CreateExecutionStrategy().ExecuteAsync(...)`; a single `SaveChangesAsync` is already atomic and needs neither.

---

## 7. Dependency Injection — `Program.cs` (Composition Root)

All wiring happens in the API project's `Program.cs` (minimal hosting — no `Startup` class), with service registration grouped in the Api project's `Extensions/ServiceExtensions.cs`. This is the only place where concrete implementations are bound to their interfaces.

```csharp
// Program.cs
ThreadPool.SetMinThreads(100, 100);                       // as BillingFuncInbound and Integrations.REPR do
var builder = WebApplication.CreateBuilder(args);

// Azure App Configuration — the label and connect rules of §3.4.
var label = builder.Configuration["AppConfig_Label"]?.Trim();
if (string.IsNullOrEmpty(label))
    throw new InvalidOperationException("AppConfig_Label is required.");

builder.Configuration.AddAzureAppConfiguration(options =>
{
    var connected = builder.Environment.IsDevelopment()
        ? options.Connect(builder.Configuration["AzureAppConfiguration:ConnectionString"])
        : options.Connect(new Uri(builder.Configuration["AzureAppConfiguration:EndpointUrl"]!), new DefaultAzureCredential());
    connected
        .Select(keyFilter: "YourApp:*", labelFilter: label)
        .Select(keyFilter: "GoreloAPI:*", labelFilter: $"{label}-vnet")
        .Select(keyFilter: "Topic:*", labelFilter: label)
        .Select(keyFilter: "AppInsights:*", labelFilter: label);
});
builder.Services.Configure<AppConfiguration>(builder.Configuration.GetSection("YourApp"));

// Data access (DAL.EF) — connection string from App Configuration, checked at startup (§6.5).
var sql = builder.Configuration["YourApp:SQLServerConnectionString"];
if (string.IsNullOrWhiteSpace(sql))
    throw new InvalidOperationException("YourApp:SQLServerConnectionString is required.");
builder.Services.AddDbContext<AppDbContext>(o => o.UseSqlServer(sql, s => s.EnableRetryOnFailure()));

// Services, caches, named HttpClients, Service Bus (§6.4) and feature-local services (§6.3).
builder.Services.AddYourAppServices(builder.Configuration);

// Validators beside their endpoints (§5.1).
builder.Services.AddValidatorsFromAssemblyContaining<Program>();

// The one failure path. Case 1: BaseResponseExceptionHandler (response-and-errors.md §5).
// Case 2: LegacyProblemDetailsExceptionHandler ("Response Pattern in REPR").
builder.Services.AddExceptionHandler<BaseResponseExceptionHandler>();
builder.Services.AddProblemDetails();                     // UseExceptionHandler() without a path needs it

// Versioning + Swagger document (Swashbuckle, as both real REPR projects use).
builder.Services.AddApiVersioning(o => { o.AssumeDefaultVersionWhenUnspecified = true; o.ReportApiVersions = true; })
                .AddApiExplorer(o => o.GroupNameFormat = "'v'VVV");
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c => c.CustomSchemaIds(t => t.FullName));

builder.Services.AddHealthChecks();                       // + SQL Server / Redis / Service Bus checks
// Authentication: neither real REPR project has any (see §5.3). An API that authenticates adds
// AddAuthentication(...)/AddAuthorization() here and UseAuthentication()/UseAuthorization() below.

var app = builder.Build();

// Conventional order — see 7.1 for what the order does and does not change.
app.UseExceptionHandler();          // 1. first, so it wraps everything after it

app.UseSwagger();                   // 2. the contract document — case 2 keeps whatever environments the legacy app served it in
if (app.Environment.IsDevelopment())
    app.UseSwaggerUI();

// Central Route Registration — registers endpoints only; it is not terminal (7.1).
app.MapFeatureEndpoints();
app.MapHealthCheckEndpoints();

app.Run();
```

### 7.1 Middleware order

`MapFeatureEndpoints()` (any `Map*`) only **registers** endpoints; it is not terminal. Under
`WebApplication` minimal hosting the framework adds routing at the start of the pipeline and
endpoint execution at its end, so `app.Use(...)`, `UseExceptionHandler()` and
`UseAuthentication()`/`UseAuthorization()` placed *after* the `Map*` calls still run before the
endpoint. Order becomes load-bearing only once the app calls `app.UseEndpoints(...)`
explicitly (flagged by analyzer ASP0014 — don't call it in minimal hosting): matched requests
end there, and anything registered after it is skipped.

Observed with an out-of-process probe (.NET 10, Production environment, 2026-10-02): routes
`/ok`, `/boom` (throws), `/secure` (`.RequireAuthorization()`, cookie scheme); then an
`app.Use` adding `X-After-Map: 1`, `UseExceptionHandler` writing a marker body, and
`UseAuthentication()`/`UseAuthorization()` — all registered after the `Map*` calls.

| Pipeline | `/ok` | `/boom` | `/secure` |
|---|---|---|---|
| `Map*` first, everything else after (with or without an explicit `UseRouting()` before the `Map*`) | 200, `X-After-Map: 1` | 500, handler's marker body | 302 to login — auth ran |
| An explicit `UseEndpoints()` before the `Use`/handler/auth | 200, **no** `X-After-Map` | 500, **empty body** — handler bypassed | **500** `InvalidOperationException: … contains authorization metadata, but a middleware was not found that supports authorization` |

The misorderings that do fail, and how:

| Misordering | Failure |
|---|---|
| An envelope-shaping middleware **after an explicit `UseEndpoints()`** | Never sees matched requests. Bare payloads ship, silently. |
| `UseExceptionHandler()` **after an explicit `UseEndpoints()`** | Thrown exceptions bypass the `BaseResponseExceptionHandler` (case 2: the legacy-shape handler); clients get a bare 500, not `Notifications` (case 2: not the legacy ProblemDetails body) |
| Auth **after an explicit `UseEndpoints()`** | Every `.RequireAuthorization()` endpoint returns 500 — loud, not a silent bypass |
| An envelope wrapper inside `if (app.Environment.IsDevelopment())` | Works locally, absent in every deployed environment — invisible to a local probe |

The 2026-08 envelope failure is described in [data-and-testing.md](data-and-testing.md) §3;
the probe above does not show middleware placed after `Map*` to be its cause.

**None of these is detectable by reading `Program.cs` alone** — a correctly-written wrapper
in the wrong position is indistinguishable from a correct one on the page. They are
detectable only at **Tier 3**: start the app and read the bytes back. Two captures, one
success and one deliberately-thrown failure, cover the envelope and exception-handler rows. See
[SKILL.md](../SKILL.md)'s Tier ladder and `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`.

---

## 8. Testing Strategy

### 8.1 Do NOT Mock the Database
Mocking `DbContext` or Repositories tests LINQ-to-Objects, not LINQ-to-SQL. A query that passes with mocks can fail in production. `Mock<AppDbContext>` and the EF Core **InMemory** provider stay forbidden — InMemory is not a relational database, and cannot even run `ExecuteUpdateAsync`. (See [data-and-testing.md](data-and-testing.md) for the shared zero-mock doctrine.) Fakes for *out-of-process* collaborators — Redis, an HTTP API, Service Bus — are allowed; the database is never faked.

### 8.2 Fast Endpoint Tests — EF Core SQLite In-Memory

Deliberate divergence (convention #8) from [SKILL.md](../SKILL.md)'s Tier 2 rule and [data-and-testing.md](data-and-testing.md) §3, which put every DB-crossing test against the real Dev DB: a Mode B **fast** test may run the real `AppDbContext` model on **SQLite in-memory** (data-and-testing.md §3.1). SQLite executes real SQL, so translation, constraints, `ExecuteUpdateAsync` and transactions are exercised — which Moq and InMemory are not. The Dev DB rule still binds the Tier 2 tests in §8.3.

The shape is BillingFuncInbound's `Tests/Common/SqliteTestDatabase.cs`: one open `SqliteConnection("DataSource=:memory:")` per test, `EnsureCreated()` from the real model, a context for arranging and asserting and a separate one handed to the code under test. Endpoint tests call `HandleAsync` directly — it is `public static` for this reason:

```csharp
public sealed class IsExternalIntegrationExistEndpointTests
{
    [Fact]
    public async Task Returns_true_when_an_active_xero_integration_exists()
    {
        using var database = new SqliteTestDatabase();
        await using (var seed = database.CreateContext())
        {
            seed.Integration.Add(TestRows.ActiveIntegration(serviceProviderId: 10045, ExternalIntegrationType.Xero));
            await seed.SaveChangesAsync();
        }

        await using var db = database.CreateInterceptedContext();
        var result = await IsExternalIntegrationExistEndpoint.HandleAsync(10045, db, CancellationToken.None);

        // Asserts the handler's result — NOT the wire. What a client receives is a Tier 3 claim (§8.4).
        result.Should().BeOfType<Ok<bool>>().Which.Value.Should().BeTrue();
    }
}
```

**The limit, stated honestly: SQLite is not SQL Server's dialect.** It has no schemas (the provider ignores `Integration.` — `SqliteEventId.SchemaConfiguredWarning` is silenced), no `getutcdate()` (the test registers a shim on the connection), different collation and case sensitivity, different `datetime`/`decimal` storage, no `rowversion`, and different locking and isolation. A test that passes here proves the handler's logic over real SQL; it does not prove the SQL Server query plan, a SQL Server–only function, collation-sensitive comparisons, concurrency behaviour, or the wire. Anything that depends on those belongs in §8.3 or §8.4.

### 8.3 Integration Tests (Tier 2 — in-process host, real Dev DB)
Test the full Vertical Slice: Route → Filter → Handler → Database.

`WebApplicationFactory` + `CreateClient()` is an **in-process** transport over an
in-memory pipe. It exercises real handlers, real filter registrations and real SQL — but
it opens no socket, runs no Kestrel, resolves no host startup/config chain, and serves no
Swagger. It therefore **cannot** prove the serialized wire shape, which
`JsonSerializerOptions` resolved, middleware/filter ordering, environment-branch
behavior, or that a contract surface a human can open exists. Any requirement about those
is proven at **Tier 3** only (see the Tier ladder in [SKILL.md](../SKILL.md)); asserting them
here is the observed 2026-08 envelope failure. Assert wire shape on the raw body, per
[data-and-testing.md](data-and-testing.md) §3.

The sample is case 1 (the envelope). In case 2 the raw-body assertion is against the legacy body's keys instead.

```csharp
public sealed class CreateOrderTests : IClassFixture<DevDbApiFactory>   // real Dev DB, per data-and-testing.md §3
{
    private readonly DevDbApiFactory _factory;
    public CreateOrderTests(DevDbApiFactory factory) => _factory = factory;

    [Fact]
    public async Task CreateOrder_ValidRequest_SavesAndReturns201()
    {
        var client = _factory.CreateClient();
        var request = new CreateOrderRequest(Guid.NewGuid(), new List<string> { "item-1" });

        var res = await client.PostAsJsonAsync("/api/orders", request);   // "api" group + "orders" feature group (§4)

        Assert.Equal(HttpStatusCode.Created, res.StatusCode);

        // Envelope on the raw body BEFORE binding — closed set of top-level keys.
        var raw = await res.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(raw);
        Assert.Equal(
            new HashSet<string> { "statusCode", "isSuccess", "data", "dataContext", "notifications" },
            doc.RootElement.EnumerateObject().Select(p => p.Name).ToHashSet());

        var envelope = JsonSerializer.Deserialize<BaseResponse<CreateOrderResponse>>(
            raw, new JsonSerializerOptions(JsonSerializerDefaults.Web));
        Assert.True(envelope!.IsSuccess);

        // Assert on THIS order's id — AnyAsync() would pass on any pre-existing Dev DB row.
        using var scope = _factory.Services.CreateScope();
        var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
        Assert.True(await db.Orders.AnyAsync(o => o.Id == envelope.Data!.OrderId));
    }
}
```

### 8.4 Wire Claims (Tier 3 — the running application)

Anything a client observes — the body bytes, status codes, content type, headers, the Swagger document — is proven only by capturing the running application out of process (the Tier ladder in [SKILL.md](../SKILL.md); `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`). In case 2 the central claim, "the wire contract is unchanged", is such a claim: it is proven by capturing the legacy app and the REPR app with the same requests and comparing them — never by §8.2 or §8.3.

### 8.5 Unit Tests (Tier 1 — pure rules)
Unit test the static rules of §6.2 directly. No database and no fakes, because they have no dependencies.

```csharp
[Theory]
[InlineData(2, true)]      // NotBillable
[InlineData(3, true)]      // NotBillableHidden
[InlineData(1, false)]     // Billable — a typed 100% discount stays a discount
[InlineData(null, false)]  // legacy rows stay on the old path
public void IsWaived_branches_on_billable_status(int? billableStatus, bool expected)
    => Assert.Equal(expected, ExternalZeroValueLineRules.IsWaived(billableStatus));
```

### 8.6 Testing Pyramid

| Layer | Test Type | What It Proves |
|---|---|---|
| Static business rules (§6.2) | Unit (Tier 1) | The rule is correct |
| Endpoint handler, feature service | Fast endpoint test on SQLite in-memory (§8.2) | The logic works over real SQL |
| `IQueryable<T>` extensions | §8.2, then §8.3 for SQL Server–specific translation | Queries translate to valid SQL |
| Endpoint (Route + Filter + Handler) on the Dev DB | Integration (Tier 2, §8.3) | Routing, filters and the SQL Server dialect |
| What a client receives | Out-of-process capture (Tier 3, §8.4) | The wire contract |

---

## 9. Migration Procedure

Migration procedure is out of scope for this playbook.

---

## 10. Quick Reference — Decision Matrix

| Scenario | Case 1 — new API | Case 2 — existing API / BLL / EF |
|---|---|---|
| A feature's endpoints | `Api/Endpoints/{Feature}/` + `{Feature}EndpointsExtension.cs` (§4) | `Gorelo.API.{X}/Endpoints/{Feature}/`, same shape |
| The route registry | `Api/Extensions/EndpointExtensions.cs`: `MapGroup("api")` + version set | Same file; no `api` prefix — feature groups use the legacy prefix |
| A database entity | Scaffolded into `DAL.EF/Entities/` — never hand-written (§6.5) | The existing `EF` project, unchanged |
| A hand-written model fix | `DAL.EF/AppDbContext.Partial.cs` (`OnModelCreatingPartial`) | Same |
| A schema change | The database, then re-run `scaffold.ps1` — no EF migrations | Same |
| An enum, constant, config POCO, DTO, service interface | `Core/` | The BLL (`Models/`, enums, `Config`) |
| A pure business rule | `static` helper in `Core` (§6.2) | `static` helper in BLL `Helpers/` |
| A reusable database query | `Infrastructure/Queries/` `IQueryable<T>` extension | BLL `Helpers/` |
| An external API, Redis, Service Bus | `Infrastructure/Services/` behind a `Core/Interfaces/` contract | BLL `Service/` |
| A FluentValidation validator | Same feature folder as the endpoint | Same — and only if the legacy endpoint validated (§5.1) |
| A feature-specific service (complex logic) | Same feature folder as the endpoint (§6.3) | Same, or an existing BLL service |
| Cross-cutting behavior | `Api/Filters/` as `IEndpointFilter`, applied on the feature group | Same |
| Request context (`ServiceProviderId`, …) | `RequireGoreloContext()` — fail closed (§5.3) | `RequireGoreloContext()` where the legacy action read `BaseController` |
| Failures | One `BaseResponseExceptionHandler` | One `LegacyProblemDetailsExceptionHandler` |
| The response body | `BaseResponse<T>` | Exactly what the legacy action returned |
| Configuration | Azure App Configuration via `IOptions<AppConfiguration>` (§3.4) | Same |

---

## 11. Case Study: `CreatePax8OAuthEndpoint` — What Was Built, and What It Should Have Been

The real file is Gorelo.Integrations.REPR `Gorelo.Integrations.REPR.API/Endpoints/Pax8/CreatePax8OAuthEndpoint.cs` (May 2026, converted from a legacy `Pax8Controller` `[HttpPost("oauth")]`). It is a useful case study because it gets the slice boundaries right and nearly everything inside the handler wrong. Nothing below is a cleaned-up rewrite presented as real: §11.1–§11.2 describe the file as it is, §11.4 is labelled as a sketch.

### 11.1 What the file contains
- **One file, four public types besides the endpoint:** `Pax8ContactModel`, `Pax8ConfigModel` (mutable classes), `CreatePax8OAuthRequest(string Code, Pax8ConfigModel Config)` (a record), and `SendMessage` — the SignalR relay message shape.
- **Mapping:** `app.MapPost("pax8/oauth", HandleAsync)` with `.WithName("CreatePax8OAuth")`, `.WithTags("Pax8")`, `.WithSummary`, `.WithDescription`, `.Produces<bool>(200)`, `.ProducesProblem(400)`, `.ProducesProblem(500)`, `.RequireGoreloContext()` — called from `Pax8EndpointsExtension.MapPax8Endpoints()` on the shared `api` group.
- **Signature:** `public static async Task<IResult> HandleAsync(HttpContext httpContext, CreatePax8OAuthRequest request, AppDBContext dbContext, IHttpClientFactory httpClientFactory, ITopicSender topicSender, IPax8AuthCacheService cacheService, IOptions<AppConfiguration> appConfigOptions, ILoggerFactory loggerFactory, CancellationToken ct)`.

### 11.2 What the handler does, in order (lines 67–253, about 190 lines)
1. `loggerFactory.CreateLogger("CreatePax8OAuthEndpoint")`; `ctx = httpContext.GetGoreloContext()`.
2. Empty `Code` → `Results.BadRequest("Authorization code is required.")` — a bare string body.
3. Inside an outer `try`: three configuration checks, each → `Results.Problem("... is not configured.", statusCode: 500)`.
4. Token exchange: named client `"ExternalApis"`, Duende `AuthorizationCodeTokenRequest`, `RequestAuthorizationCodeTokenAsync`; an error or an empty token → `Results.Problem(..., 500)`.
5. **Redis first:** read the cached token, remove it, write the new one through `IPax8AuthCacheService`.
6. **Explicit transaction:** `BeginTransactionAsync`; tracked upsert of the `OauthToken` row and the `Integration` row (new rows get `CreatedById = 1`, `StatusId = 1`, `Config = JsonConvert.SerializeObject(request.Config)`); `SaveChangesAsync`; `CommitAsync`. Inner `catch`: `RollbackAsync`, remove the Redis token, rethrow.
7. **After commit:** `topicSender.SendMessage("signalr-message-send", new SendMessage { ... }, ct)`.
8. `return Results.Ok(true)`. Outer `catch (Exception)` → `Results.Problem("An unexpected error occurred during Pax8 OAuth exchange.", 500)`.

### 11.3 Critique
**What it gets right** — and is worth copying:
- The slice boundary: route, metadata and request types in one file, registered by the feature's extension; no MediatR, no repository.
- The external HTTP call happens **before** the transaction and the Service Bus publish **after** the commit, so the transaction span stays in-process (SKILL.md's span rule). Publish-after-commit is still a dual write, though — see item 4.
- Redis sits behind a Core interface (`IPax8AuthCacheService`), its implementation in Infrastructure.

**What it gets wrong:**
1. **Size.** About 190 lines inline — well past §6.3's ~80-line extraction point — mixing an OAuth exchange, a cache, persistence and messaging in one method.
2. **Per-handler try/catch.** The outer catch-all turns every failure — including `OperationCanceledException` — into the same 500 with a generic message, discarding the exception type the caller and the logs need. Failures belong to the one `IExceptionHandler`.
3. **Three error-body shapes from one endpoint:** a bare string (400), `ProblemDetails` with a specific message (500), `ProblemDetails` with a generic message (500).
4. **Partial-failure ordering.** The token is written to Redis *before* the database commit and compensated by hand on rollback; and when the publish in step 7 fails, the outer catch returns 500 although the database and the cache are already committed — the client sees a failed exchange that succeeded, and an OAuth code is single-use, so its retry fails. No ordering of a commit and a direct publish closes that window; an outbox does (`{PLUGIN_ROOT}/jobs-and-messaging-patterns/SKILL.md` § Publish-With-Write Uses the Outbox — Never a Dual Write).
5. **A transaction it does not need.** Two tracked changes saved by one `SaveChangesAsync` are already atomic. If the context is registered with `EnableRetryOnFailure`, the explicit `BeginTransactionAsync` also throws unless wrapped in an execution strategy (§6.5).
6. **Tenant and actor.** `ctx.ServiceProviderId` is `0` when the query string omits it (§5.3), so the handler can write a token row for tenant `0`; `CreatedById = 1` is hard-coded although `ctx.TechnicianId` is in hand.
7. **Misplaced types.** `SendMessage` is a cross-service message contract, not a slice DTO; it belongs in Core `Models/` beside `ITopicSender`. The file also imports the legacy project's namespace (`Gorelo.API.Integration.Filters`) for the context filter.
8. **Logger category** is a string literal that silently drifts from the class name on a rename.

### 11.4 What it should have been — a sketch, not existing code
- **The endpoint** — about 15 lines: map on the `pax8` group (which carries the tag and `RequireGoreloContext()`), validate with a `CreatePax8OAuthRequestValidator` via `.AddValidation<CreatePax8OAuthRequest>()` instead of the inline guard, delegate, return. No try/catch.

```csharp
// SKETCH — illustrates the target shape; this is not the file in the repository.
public static async Task<IResult> HandleAsync(
    HttpContext httpContext, CreatePax8OAuthRequest request, CreatePax8OAuthService service, CancellationToken ct)
{
    var ctx = httpContext.GetGoreloContext();          // fail-closed filter: ServiceProviderId > 0 (§5.3)
    await service.ExecuteAsync(ctx, request, ct);       // throws on failure → the one IExceptionHandler
    return BaseResponse<bool>.Success(true).ToResult(); // case 1; a case-2 conversion keeps Results.Ok(true)
}
```

- **`CreatePax8OAuthService`** in `Endpoints/Pax8/` (one feature uses it), in this order: exchange the code (outside any transaction) → one `SaveChangesAsync` upserting both rows with `CreatedById = ctx.TechnicianId` **and** adding the SignalR-sync outbox row, so state and event commit atomically → refresh Redis **after** the commit. The service takes no `ITopicSender`: the outbox relay publishes the row to the `signalr-message-send` topic (`{PLUGIN_ROOT}/jobs-and-messaging-patterns/SKILL.md` § Publish-With-Write Uses the Outbox — Never a Dual Write), so a broker outage delays the event rather than failing a request whose data is already committed. Configuration validated at startup (§3.4), not per request.
- **Tests:** the service against SQLite in-memory (§8.2) with fakes for the token endpoint and Redis, asserting the outbox row is written in the same save; the wire at Tier 3 (§8.4).

---

## 12. Anti-patterns Seen in Earlier Conversions

Seen in Gorelo.FunctionInbound.REPR (an earlier conversion of BillingFuncInbound), Gorelo.Integrations.REPR, and the legacy code they came from. Do not copy them.

1. **A try/catch in every handler** returning its own `Results.Problem(...)` — 13 of 13 handlers in one project, 56 `Results.Problem` calls in the other. Use the one `IExceptionHandler`.
2. **Mixed error bodies** in one API: `Results.BadRequest("string")`, `Results.NotFound()` (empty), `Results.NotFound(new { Message = ... })`, `Results.Problem(...)`.
3. **Unverified wire compatibility.** FunctionInbound.REPR kept the legacy routes but returned `Results.Ok(string)` (always JSON) where the legacy action returned MVC's `Ok(string)`, whose string formatter writes `text/plain` unless the request's `Accept` selects JSON — a difference only a capture of both apps settles, and none was taken. (It did map the `Ok(null)` → `204` case correctly, with `Results.NoContent()`.)
4. **A dead validation pipeline.** `ValidationFilter<T>` and `AddValidation<T>()` copied into both projects with zero call sites and zero validators; the legacy `RequestValidationBehavior` was never registered either.
5. **An impure Core.** `Gorelo.RedisManager` and `Azure.Messaging.ServiceBus` in both Core projects (one also EF Core, Huntress, Pax8, MailGun and Slide SDKs); `ITopicSender` exposes `ServiceBusMessage`.
6. **Entities and the context in the wrong naming.** `AppDBContext` (both earlier REPR projects) vs `AppDbContext` (BillingFuncInbound's EF Core scaffold) for the same thing; default-named entities in one solution, `Entity`-suffixed in another. Pick one per solution — this playbook uses `AppDbContext`.
7. **No feature extension, or a misnamed one.** FunctionInbound's flat `MapInboundEndpoints`, and `MapXeroExtensions` / `AddXeroExtensions` that register System endpoints and `ISystemService`. Names must say what they register.
8. **Folder/namespace drift.** Folder `Endpoints/Integration/`, namespace `...Endpoints.GeneralIntegrations`; filters in a REPR project under the legacy namespace `Gorelo.API.Integration.Filters`; directory `Gorelo.Integration.REPR` holding `Gorelo.Integrations.REPR.*` projects.
9. **A client-asserted tenant, defaulting to 0** (§5.3).
10. **Tracked reads.** One `AsNoTracking()` per project across dozens of read queries.
11. **Mocked data access.** `new Mock<AppDBContext>(options)`, service methods made `virtual` only so Moq can intercept them, EF InMemory; tests that assert only the handler's return type, so routing, filters, binding and serialization were never exercised.
12. **Unsafe and duplicate routes.** A state-changing `GET integration/deactivate/{id:guid}`; one Huntress list served at two spellings (`huntress/organization/list` and `integration/huntress/organization/list`). In case 2 they are the contract and stay; never add new ones.
13. **Configuration smells.** `Configure<AppConfiguration>(configuration)` binding the root; a section named `EnvVariables` that is App Configuration–backed; `IOptions` mixed with raw `configuration["..."]` reads in services; BillingFuncInbound's `StartupExtension.LoadAllEnvironmentVariables` copying configuration into environment variables.
14. **Stack traces in production error bodies.** The legacy `ErrorController` puts `ex.StackTrace` in `detail` outside Development. A case-2 conversion reproduces it because the contract is frozen; removing it is a declared contract change, and the right one.
15. **Unused package references** — EF Core in a Core that never uses it, EF InMemory in a test project that never calls it, `Microsoft.AspNetCore.OpenApi` without `AddOpenApi`.
