# REPR + Vertical Slice Playbook (Mode B) — Code Patterns

Read this when the blueprint declares **Mode B**. Shared EF Core / async / testing discipline lives in [data-and-testing.md](data-and-testing.md). The `BaseResponse<T>` envelope + error/notification/exception model (shared with Mode A) lives in [response-and-errors.md](response-and-errors.md) — **REPR endpoints return that envelope too**, emitted as `IResult` via `.ToResult()` (see "Response Pattern in REPR" below), with failures centralized in an `IExceptionHandler`.

> **Note on names:** concrete project/feature names below (`Gorelo.Integrations.REPR.*`, Pax8) are illustrative examples from the reference implementation. Apply the *pattern*, substituting the target project's own names. Any "do not touch the legacy project" rule applies only when a migration explicitly declares a legacy project to preserve.

## Canonical minimal contrast — GOOD/BAD

```csharp
// API/Endpoints/Orders/GetOrderSummary.cs — everything the route needs, in one file.
public static class GetOrderSummary
{
    public sealed record Request(Guid OrderId);
    public sealed record Response(Guid Id, string Status, decimal Total);   // slice-owned payload

    public static void Map(IEndpointRouteBuilder app) =>
        app.MapGet("/orders/{orderId:guid}/summary", Handle)
           .RequireAuthorization();

    // Returns the shared BaseResponse<T> envelope, emitted as IResult via .ToResult().
    private static async Task<IResult> Handle(
        Guid orderId,
        AppDbContext db,                 // direct DbContext — NO repository in REPR mode
        CancellationToken ct)
    {
        var order = await db.Orders
            .AsNoTracking()
            .Where(o => o.Id == orderId)
            .Select(o => new Response(o.Id, o.Status.ToString(), o.Lines.Sum(l => l.Price * l.Qty)))
            .FirstOrDefaultAsync(ct);

        if (order is null)
            throw new CustomException(                       // → centralized IExceptionHandler → BaseResponse
                ErrorCode.From(MicroserviceCodes.Domain, ErrorTypeCodes.Toast_Validations, 1),
                "Order not found.", HttpStatusCode.NotFound);

        return BaseResponse<Response>.Success(order).ToResult();
    }
}
```

```csharp
// BAD (REPR mode): repository abstraction wrapping EF Core — banned bloat here.
public interface IOrderRepository { Task<Order?> GetByIdAsync(Guid id); }

// BAD (REPR mode): bare payload, no envelope — frontend interceptor can't read it uniformly.
return Results.Ok(order);   // use BaseResponse<Response>.Success(order).ToResult() instead
```

> **Envelope ≠ shared DTO.** The "No Shared DTOs" rule (§3.3) still holds: `Response` is owned by this slice. `BaseResponse<T>` is a cross-cutting *transport envelope* wrapping that slice-owned payload — it is not a shared domain DTO, so it does not violate the rule.

---

## Response Pattern in REPR

REPR endpoints use the same [`BaseResponse<T>` envelope + error model](response-and-errors.md) as CQRS, so the frontend gets one contract across both modes. The difference is purely the *emit mechanism* — no `BaseController`:

- **Success:** build `BaseResponse<T>.Success(payload)` and return `.ToResult()` (the `IResult` bridge — minimal APIs don't accept `IActionResult`). ⚠️ `ToResult` is not yet in BG.Core; add it per [response-and-errors.md §5](response-and-errors.md).
- **Failure:** don't build error envelopes inline in every handler. Throw `CustomException` (or let `ValidationException` bubble from the validation filter) and map it **once** in a native `IExceptionHandler` — see the `BaseResponseExceptionHandler` in [response-and-errors.md §5](response-and-errors.md), registered in `Program.cs`. This is the REPR equivalent of the CQRS base-controller try/catch, and it stays consistent with §3.3 "use native ASP.NET Core, don't abstract the framework."

```csharp
// Handler shape under the Response Pattern: return success envelopes, THROW failures.
private static async Task<IResult> HandleAsync(CreateOrderRequest request, AppDbContext db, CancellationToken ct)
{
    // validation already ran via .AddValidation<CreateOrderRequest>() (throws ValidationException on failure)
    var created = /* ... */;
    return BaseResponse<CreateOrderResponse>.Success(created, HttpStatusCode.Created).ToResult();
}
```

> The inline `Results.Ok(...)` samples elsewhere in this guide predate the Response Pattern and illustrate *slice structure*, not the wire contract — in real endpoints, wrap the payload in `BaseResponse<T>` and emit via `.ToResult()`.

---

## 1. Core Philosophy

### 1.1 Locality of Behavior (LoB)
Everything related to a single feature (the route, the request/response models, the validation, and the business logic) must live as close together as possible—ideally in a single file or a single feature folder.

**If an AI or a Developer wants to understand a feature, they should only have to open ONE folder.**

### 1.2 What We Eliminate
| Removed Pattern | Replacement |
|---|---|
| MediatR / CQRS | Direct method calls, Endpoint Filters |
| Controllers | Minimal API Endpoint classes (one per feature) |
| Repository Pattern | `DbContext` injected directly + `IQueryable<T>` extension methods |
| Shared DTOs | Each endpoint owns its own Request/Response models |
| `IPipelineBehavior` (MediatR) | `IEndpointFilter` (ASP.NET Core native) |
| N-Tier (API/BLL/DAL) | Vertical Slices grouped by Feature |

---

## 2. Project Structure

A solution uses a **maximum of 3 projects**. For small microservices, a single project is acceptable.

### 2.1 `YourApp.Api` — The Application Shell + Features
This is the entry point. It contains `Program.cs`, global filters, and all feature slices.

- **References:** `YourApp.Core`, `YourApp.Infrastructure`
- **NuGet:** `FluentValidation`, ASP.NET Core (built-in)
- **Contains:** Feature folders, Endpoint Filters, `Program.cs` (Composition Root)

### 2.2 `YourApp.Core` — The Domain (Pure C#)
This project has **zero framework dependencies**. No EF Core, no ASP.NET, no Azure SDKs.

- **References:** Nothing (or only `Microsoft.Extensions.Logging.Abstractions`)
- **NuGet:** None (or only `Microsoft.Extensions.Logging.Abstractions`)
- **Contains:**
  - **Entities:** Plain C# classes (POCOs). No EF attributes like `[Table]` or `[Column]`.
  - **Value Objects & Enums:** `OrderStatus`, `Money`, etc.
  - **Domain Logic:** Complex business rules that belong to the entity (e.g., `order.ApplyDiscount()`).
  - **Interfaces for external services:** `IEmailService`, `IPaymentGateway`, `IBlobStorageService`.

### 2.3 `YourApp.Infrastructure` — External Integrations & Data Access
This project handles all communication with the outside world.

- **References:** `YourApp.Core`
- **NuGet:** `Microsoft.EntityFrameworkCore`, Azure SDKs, Stripe, etc.
- **Contains:**
  - `AppDbContext` and EF Core configurations (`IEntityTypeConfiguration<T>`).
  - Database Migrations.
  - Implementations of interfaces defined in Core (e.g., `SmtpEmailService : IEmailService`).
  - HTTP Clients for third-party APIs.
  - `IQueryable<T>` extension methods for reusable queries.

### 2.4 Folder Layout

```text
Solution/
├── YourApp.Api/
│   ├── Program.cs                          # Composition Root (DI, Middleware, Route registration)
│   ├── Filters/                            # Global Endpoint Filters
│   │   ├── ValidationFilter.cs
│   │   └── LoggingFilter.cs
│   ├── Endpoints/                           # All Vertical Slices live here
│   │   ├── Customers/
│   │   │   ├── CreateCustomer/
│   │   │   │   ├── CreateCustomerEndpoint.cs    # Request + Response + Handler
│   │   │   │   └── CreateCustomerValidator.cs   # FluentValidation rules
│   │   │   ├── GetCustomerById/
│   │   │   │   └── GetCustomerByIdEndpoint.cs
│   │   │   └── BanCustomer/
│   │   │       ├── BanCustomerEndpoint.cs
│   │   │       └── BanCustomerValidator.cs
│   │   └── Orders/
│   │       └── CreateOrder/
│   │           ├── CreateOrderEndpoint.cs
│   │           └── CreateOrderValidator.cs
│   └── Extensions/                         # Route registration helpers
│       └── EndpointExtensions.cs
│
├── Gorelo.Integrations.REPR.Core/
│   ├── Enums/
│   │   ├── IntegrationEnums.cs             # Full enums (ExternalIntegrationType, EntitySyncMethodEnum, etc.)
│   │   ├── BaseRole.cs                     # Core BaseRole enum
│   │   └── EntitySyncEnum.cs               # Core EntitySyncEnum enum
│   └── Interfaces/
│       ├── pax8/
│       │   └── IPax8AuthCacheService.cs    # Domain interface for Pax8 Token Cache
│       ├── IAzureKeyVaultService.cs
│       └── IBlobStorageService.cs
│
├── Gorelo.Integrations.REPR.DAL.EF/
│   ├── Context/
│   │   └── AppDBContext.cs                 # DBContext for migrations and queries
│   └── Entities/
│       ├── Integration.cs                  # Database Entity representing integrations
│       └── OauthToken.cs                   # Database Entity representing OAuth tokens
│
└── Gorelo.Integrations.REPR.Infrastructure/
    ├── Services/
    │   ├── pax8/
    │   │   └── Pax8AuthCacheService.cs     # Implements IPax8AuthCacheService using Redis StackExchange
    │   ├── AzureKeyVaultService.cs
    │   └── BlobStorageService.cs
    └── Queries/
        └── IntegrationQueries.cs           # IQueryable<T> extension methods
```

---

## 3. The REPR Pattern — Rules

### 3.1 Endpoint File Structure
Every endpoint file follows this exact structure:

```csharp
// File: Features/{Domain}/{FeatureName}/{FeatureName}Endpoint.cs

namespace YourApp.Api.Features.{Domain}.{FeatureName};

// 1. Request Model (owned by this endpoint only)
public record {FeatureName}Request(/* properties */);

// 2. Response Model (owned by this endpoint only)
public record {FeatureName}Response(/* properties */);

// 3. Static Endpoint Class
public static class {FeatureName}Endpoint
{
    // 4. Route Registration
    public static void Map{FeatureName}Endpoint(this IEndpointRouteBuilder app)
    {
        app.Map{HttpVerb}("route", HandleAsync)
           .WithName("{FeatureName}")
           .WithTags("{Domain}")
           .AddValidation<{FeatureName}Request>();  // Pipeline filter
    }

    // 5. Handler — all dependencies injected as method parameters
    private static async Task<IResult> HandleAsync(
        {FeatureName}Request request,
        AppDbContext db,
        // other dependencies...
        CancellationToken ct)
    {
        // Business logic here
        var response = new {FeatureName}Response(/* ... */);
        return BaseResponse<{FeatureName}Response>.Success(response).ToResult();
    }
}
```

### 3.2 Naming Conventions

| Element | Convention | Example |
|---|---|---|
| Endpoint Class | `{Verb}{Entity}Endpoint` | `CreateOrderEndpoint` |
| Request Record | `{Verb}{Entity}Request` | `CreateOrderRequest` |
| Response Record | `{Verb}{Entity}Response` | `CreateOrderResponse` |
| Validator Class | `{Verb}{Entity}Validator` | `CreateOrderValidator` |
| Folder Name | `{Verb}{Entity}` | `CreateOrder/` |
| Route Registration | `Map{Verb}{Entity}Endpoint` | `MapCreateOrderEndpoint()` |

### 3.3 Inviolable Rules

1. **Slices NEVER call other Slices.** `CreateOrderEndpoint` must NEVER inject or call `UpdateInventoryEndpoint`. If two slices need the same logic, extract it to the Core domain model or an Infrastructure service.

2. **No Shared DTOs.** Every endpoint owns its own Request and Response models. Duplication of DTOs is cheaper than the wrong abstraction.

3. **No Abstracting the Framework.** Use `DbContext` directly. Use Minimal APIs directly. Do not build wrappers.

4. **No God Services.** Do not create `CustomerService` with 20 methods. If complex logic is needed for a single feature, create `{FeatureName}Service` in the same feature folder.

5. **Request/Response models are Records.** Use C# `record` types for immutability and conciseness.

6. **Do not modify a declared legacy project.** When a migration declares a legacy project to preserve, that project must remain untouched, intact, and unmodified — do not delete, remove, or refactor any code, files, or folders inside it. All new vertical-slice work happens in the new REPR project. (In the reference implementation this is `Gorelo.API.Integration`; substitute the legacy project the current migration names.)

7. **Use Azure Configuration rather than Environment Variables.** Configuration, connection strings, and application settings must be retrieved using Azure App Configuration (via the standard ASP.NET Core `IConfiguration` abstraction) rather than direct environment variables via `Environment.GetEnvironmentVariable()`. This ensures centralized configuration, dynamic refreshing, and environment consistency.

---

## 4. Cross-Cutting Concerns — Endpoint Filters

### 4.1 Generic Validation Filter
Replaces MediatR's `IPipelineBehavior` for request validation. The filter *throws* `ValidationException`; the centralized `IExceptionHandler` maps it to the `BaseResponse<T>` envelope once (see "Response Pattern in REPR" above).

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
                .GetService<IValidator<TRequest>>();

            if (validator is not null)
            {
                var result = await validator.ValidateAsync(request, context.HttpContext.RequestAborted);
                if (!result.IsValid)
                    throw new ValidationException(result.Errors);
            }
        }

        return await next(context);
    }
}
```

### 4.2 Extension Method for Clean Chaining

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

### 4.3 Other Filter Examples
The same pattern applies to any cross-cutting concern:

- **`LoggingFilter`** — Log request/response timing.
- **`TransactionFilter`** — Wrap the handler in a database transaction and auto-commit/rollback.
- **`AuthorizationFilter`** — Custom per-endpoint authorization checks.

---

## 5. Shared Logic — How to Avoid Duplication

### 5.1 Shared Database Queries → `IQueryable<T>` Extension Methods
When the same query filter is needed across multiple endpoints, extract it as a static extension method.

```csharp
// Infrastructure/Queries/CustomerQueries.cs
public static class CustomerQueries
{
    public static IQueryable<Customer> WhereIsActive(this IQueryable<Customer> query)
    {
        return query.Where(c => c.IsDeleted == false && c.Status == CustomerStatus.Active);
    }

    public static IQueryable<Customer> WhereIsPremium(this IQueryable<Customer> query)
    {
        return query.Where(c => c.SubscriptionType == "Premium"
                              && c.SubscriptionExpiry > DateTime.UtcNow);
    }
}
```

**Usage in an Endpoint:**
```csharp
var customers = await db.Customers
    .WhereIsActive()
    .WhereIsPremium()
    .Select(c => new GetPremiumCustomersResponse(c.Id, c.Name))
    .AsNoTracking()
    .ToListAsync(ct);
```

### 5.2 Complex Business Rules → Domain Entity Methods
Business logic that depends only on the entity's own state belongs inside the entity.

```csharp
// Core/Entities/Order.cs
public class Order
{
    public decimal TotalPrice { get; private set; }
    public OrderStatus Status { get; private set; }

    public void ApplyDiscount(string promoCode)
    {
        if (promoCode == "SAVE20") TotalPrice *= 0.8m;
    }

    public void Cancel()
    {
        if (Status == OrderStatus.Shipped)
            throw new InvalidOperationException("Cannot cancel a shipped order.");
        Status = OrderStatus.Cancelled;
    }
}
```

### 5.3 Complex Multi-Step Operations → Dedicated Feature Service
If a single endpoint's handler exceeds ~80 lines, extract its logic into a service that lives **in the same feature folder**.

```text
Features/Orders/CreateOrder/
├── CreateOrderEndpoint.cs
├── CreateOrderService.cs      ← extracted logic
└── CreateOrderValidator.cs
```

The endpoint handler becomes a thin delegation:
```csharp
private static async Task<IResult> HandleAsync(
    CreateOrderRequest request,
    CreateOrderService service,
    CancellationToken ct)
{
    var result = await service.ExecuteAsync(request, ct);
    return Results.Ok(result);
}
```

### 5.4 External Integrations → Infrastructure Services behind Core Interfaces
For talking to the outside world (email, payment, storage), define the interface in Core and implement in Infrastructure.

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

---

## 6. EF Core Placement

| Component | Project | Why |
|---|---|---|
| Entity classes (POCOs) | `Core` | New work places entities in `Core/Entities/` — pure POCOs, no EF dependency. |
| `AppDbContext` | `DAL.EF` | In this repository, the DbContext resides in (`Gorelo.Integrations.REPR.DAL.EF/Context/AppDBContext.cs`). |
| `IEntityTypeConfiguration<T>` | `DAL.EF` / `Infrastructure` | Fluent API configurations. |
| Migrations | `DAL.EF` | Generated and tracked within the DAL project database layer. |
| `IQueryable<T>` extensions | `Infrastructure` | Reusable queries operating on `DbSet<T>`. |

> **IMPORTANT:** Entity classes must match database schemas. Custom mappings can be configured via Fluent API in configuration classes (in `DAL.EF`).

> The historical Gorelo.Integrations.REPR reference implementation keeps entities in `DAL.EF/Entities/` — preserve that only when the blueprint declares legacy-preservation (see the note at the top of this file); for new work, entities live in `Core`.

---

## 7. Dependency Injection — `Program.cs` (Composition Root)

All wiring happens in the API project's `Program.cs`. This is the only place where concrete implementations are bound to their interfaces.

```csharp
// Program.cs
var builder = WebApplication.CreateBuilder(args);

// Infrastructure
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseSqlServer(builder.Configuration.GetConnectionString("Default")));

// External services
builder.Services.AddScoped<IEmailService, SmtpEmailService>();
builder.Services.AddScoped<IPaymentGateway, StripePaymentGateway>();

// Validators (auto-register all validators in the assembly)
builder.Services.AddValidatorsFromAssemblyContaining<Program>();

// Feature-specific services (only when extracted from endpoint)
builder.Services.AddScoped<CreateOrderService>();

var app = builder.Build();

// Route Registration
app.MapCreateOrderEndpoint();
app.MapGetCustomerByIdEndpoint();
app.MapBanCustomerEndpoint();
// ... one line per feature

app.Run();
```

---

## 8. Testing Strategy

### 8.1 Do NOT Mock the Database
Mocking `DbContext` or Repositories tests LINQ-to-Objects, not LINQ-to-SQL. A query that passes with mocks can fail in production. (See [data-and-testing.md](data-and-testing.md) for the shared zero-mock doctrine.)

### 8.2 Integration Tests (Primary)
Test the full Vertical Slice: Route → Filter → Handler → Database.

```csharp
[Fact]
public async Task CreateOrder_ValidRequest_SavesAndReturns200()
{
    using var factory = new WebApplicationFactory<Program>()
        .WithWebHostBuilder(b => b.ConfigureTestDatabase());

    var client = factory.CreateClient();
    var request = new CreateOrderRequest(Guid.NewGuid(), new[] { "item-1" });

    var response = await client.PostAsJsonAsync("/api/orders", request);

    response.EnsureSuccessStatusCode();

    using var scope = factory.Services.CreateScope();
    var db = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    Assert.True(await db.Orders.AnyAsync());
}
```

### 8.3 Unit Tests (For Domain Logic Only)
Unit test pure business logic inside Core entities. No mocks needed because these classes have no dependencies.

```csharp
[Fact]
public void ApplyDiscount_WithValidCode_ReducesPrice()
{
    var order = new Order { TotalPrice = 100m };
    order.ApplyDiscount("SAVE20");
    Assert.Equal(80m, order.TotalPrice);
}
```

### 8.4 Testing Pyramid

| Layer | Test Type | What It Proves |
|---|---|---|
| Endpoint (Route + Filter + Handler) | Integration Test | The full feature works end-to-end |
| `IQueryable<T>` extensions | Integration Test | Queries translate to valid SQL |
| Domain entity methods | Unit Test | Business rules are correct |
| Infrastructure services | Integration Test | External integrations work |

---

## 9. Migration Checklist — From N-Tier/CQRS to REPR

Use this checklist when converting an existing codebase:

### Phase 1: Foundation
- [ ] Create `Filters/ValidationFilter.cs` in the API project.
- [ ] Create `Filters/ValidationFilterExtensions.cs`.
- [ ] Create the `Features/` folder in the API project.

### Phase 2: Tracer Bullet (One Feature)
- [ ] Pick one simple Controller action (e.g., `GET /api/customers/{id}`).
- [ ] Create `Features/Customers/GetCustomerById/GetCustomerByIdEndpoint.cs`.
- [ ] Move the Request/Response DTOs into the endpoint file.
- [ ] Move the handler logic from the MediatR Handler (or BLL Service) into `HandleAsync`.
- [ ] Replace any Repository call with a direct `DbContext` call.
- [ ] Register the route in `Program.cs`.
- [ ] **DO NOT delete or modify** the old Controller action, MediatR Command, or Handler in the declared legacy project. Leave them completely intact.
- [ ] Test the new endpoint.

### Phase 3: Systematic Migration
- [ ] Repeat Phase 2 for each remaining Controller action/MediatR handler (always keeping the legacy code intact).
- [ ] Extract shared queries into `IQueryable<T>` extension methods as they appear.
- [ ] Extract shared business logic into Core entity methods.

### Phase 4: Project Preservation (NO Legacy Cleanup)
- [⚠️] **CRITICAL:** Do NOT delete or modify the `Controllers` folder or any other folders/files inside the declared legacy project or its BLL layers.
- [⚠️] **CRITICAL:** Do NOT delete or modify any legacy BLL or DAL project or handlers.
- [⚠️] **CRITICAL:** Do NOT remove MediatR or other NuGet packages from the legacy projects.
- [ ] Ensure that the new REPR project compiles and runs completely independently without affecting or needing modifications in the legacy project.
- [ ] Clean and rebuild the new REPR solution to verify it builds successfully.

### Phase 5: Testing & Verification
- [ ] Add/migrate unit tests for all domain logic inside Core entities to ensure business rules remain correct.
- [ ] Add integration tests for the vertical slices to verify the end-to-end route, filters, handlers, and DbContext operations.
- [ ] Verify test coverage baseline and ensure no regressions exist.

---

## 10. Quick Reference — Decision Matrix

| Scenario | Where Does It Go? |
|---|---|
| A new API feature | `Api/Features/{Domain}/{FeatureName}/` or `Api/Endpoints/{Domain}/` |
| A database entity | `Core/Entities/` |
| An enum or value object | `Core/Enums/` or `Core/ValueObjects/` |
| A business rule on an entity | Inside the entity class in `Core/Entities/` |
| A reusable database query | `Infrastructure/Queries/` as `IQueryable<T>` extension |
| The DbContext | `DAL.EF/Context/AppDBContext.cs` |
| EF Core entity configuration | `DAL.EF/Context/` or `DAL.EF/Configurations/` |
| An external API integration | `Infrastructure/Services/` implementing a `Core/Interfaces/` contract |
| A FluentValidation validator | Same feature folder as the endpoint |
| A feature-specific service (complex logic) | Same feature folder or subfolder as the endpoint |
| Cross-cutting behavior (logging, auth) | `Api/Filters/` as `IEndpointFilter` |
| Configuration / Application settings | Azure App Configuration (via `IConfiguration`) rather than direct Environment Variables |

---

## 11. Case Study: Pax8 OAuth Flow Migration

This case study (from the reference implementation) documents migrating a legacy `[HttpPost("oauth")]` endpoint from `Pax8Controller.cs` into a REPR structure, highlighting vertical slice best practices.

### 11.1 File Structure and Responsibilities
The migration split the legacy controller logic cleanly across the projects:
- **`Gorelo.Integrations.REPR.Core` (Enums and Interface Contracts)**:
  - `Interfaces/pax8/IPax8AuthCacheService.cs`: Defines the contract for caching authorization tokens, keeping Core completely independent of Redis or StackExchange.
  - `Enums/IntegrationEnums.cs`: The entire enums (`ExternalIntegrationType`, `EntitySyncMethodEnum`, etc.) were imported from the BLL project to prevent duplicate, partial keys and maintain domain consistency.
  - `Enums/BaseRole.cs` and `Enums/EntitySyncEnum.cs`: Moved to Core to house key-value definitions.
- **`Gorelo.Integrations.REPR.Infrastructure` (Implementations & Caching)**:
  - `Services/pax8/Pax8AuthCacheService.cs`: Concrete cache implementation using the `Gorelo.RedisManager` package (via `Pax8Auth`), keeping Redis dependencies out of Core.
- **`Gorelo.Integrations.REPR.API` (Vertical Slice Endpoint Shell)**:
  - `Endpoints/Pax8/CreatePax8OAuthEndpoint.cs`: Houses the DTOs (`Pax8ContactModel`, `Pax8ConfigModel`, `CreatePax8OAuthRequest`), static endpoint mapping route, and HTTP handling method (`HandleAsync`).

### 11.2 Endpoint Structure Sample
Below is the architectural implementation of the migrated endpoint showcasing dependency injection, entity filtering, DbContext access, Redis caching, and Service Bus event publishing:

```csharp
namespace Gorelo.Integrations.REPR.API.Endpoints.Pax8
{
    public record CreatePax8OAuthRequest(string Code, Pax8ConfigModel Config);

    public static class CreatePax8OAuthEndpoint
    {
        public static void MapCreatePax8OAuthEndpoint(this IEndpointRouteBuilder app)
        {
            app.MapPost("pax8/oauth", HandleAsync)
               .WithName("CreatePax8OAuth")
               .WithTags("Pax8")
               .RequireGoreloContext() // Native IEndpointFilter
               .Produces<bool>(StatusCodes.Status200OK);
        }

        private static async Task<IResult> HandleAsync(
            CreatePax8OAuthRequest request,
            AppDBContext db,
            IPax8AuthCacheService cacheService,
            ITopicSender topicSender,
            IHttpClientFactory httpClientFactory,
            ILogger<CreatePax8OAuthEndpoint> logger,
            CancellationToken ct)
        {
            // 1. Retrieve ServiceProviderId & TechnicianId cleanly from custom Endpoint Filter
            // 2. Perform external Token exchange via named HttpClient
            // 3. Persist tokens into DB and Redis cache using IPax8AuthCacheService
            // 4. Publish SignalR Sync notification via ServiceBus Topic
            return Results.Ok(true);
        }
    }
}
```

### 11.3 Core Rules Demonstrated
1. **Locality of Behavior (LoB)**: The HTTP POST endpoint, its route metadata, and unique request models live together in `CreatePax8OAuthEndpoint.cs`.
2. **Infrastructure Decoupling**: Database interactions occur directly through `AppDBContext`, while Redis interactions are hidden behind `IPax8AuthCacheService`, keeping the endpoint slice clean, testable, and SRP-compliant.
3. **No CQRS overhead**: Replaced complex MediatR workflows with a direct, compile-time type-safe handler method.
