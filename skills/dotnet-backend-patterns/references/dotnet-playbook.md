# .NET Playbook — Code Patterns

GOOD/BAD examples for each contract rule. C# 12 / .NET 8 style.

## 1. Mode A — MediatR Validation Pipeline Behavior

```csharp
// Application/Behaviors/ValidationBehavior.cs
public sealed class ValidationBehavior<TRequest, TResponse>(
    IEnumerable<IValidator<TRequest>> validators)
    : IPipelineBehavior<TRequest, TResponse> where TRequest : notnull
{
    public async Task<TResponse> Handle(
        TRequest request,
        RequestHandlerDelegate<TResponse> next,
        CancellationToken ct)
    {
        if (validators.Any())
        {
            var context = new ValidationContext<TRequest>(request);
            var failures = (await Task.WhenAll(
                    validators.Select(v => v.ValidateAsync(context, ct))))
                .SelectMany(r => r.Errors)
                .Where(f => f is not null)
                .ToList();

            if (failures.Count != 0)
                throw new ValidationException(failures); // caught by base controller → Response Pattern
        }
        return await next();
    }
}

// Registration order matters: Authorization → Validation → DomainEvents → Handler
services.AddMediatR(cfg =>
{
    cfg.RegisterServicesFromAssembly(typeof(ApplicationAssembly).Assembly);
    cfg.AddOpenBehavior(typeof(AuthorizationBehavior<,>));
    cfg.AddOpenBehavior(typeof(ValidationBehavior<,>));
    cfg.AddOpenBehavior(typeof(DomainEventDispatchBehavior<,>));
});
```

## 2. The Standardized Response Pattern

```csharp
// Every API result maps to this envelope — the frontend interceptor depends on it.
public sealed record ApiResponse<T>(bool Success, T? Data, IReadOnlyList<string> Errors)
{
    public static ApiResponse<T> Ok(T data) => new(true, data, []);
    public static ApiResponse<T> Fail(params string[] errors) => new(false, default, errors);
}

// Generic base controller (Mode A) — cross-cutting mapping lives here, once.
public abstract class ApiControllerBase(ISender sender) : ControllerBase
{
    protected async Task<ActionResult<ApiResponse<T>>> Send<T>(
        IRequest<T> request, CancellationToken ct)
    {
        try { return Ok(ApiResponse<T>.Ok(await sender.Send(request, ct))); }
        catch (ValidationException ex)
        { return BadRequest(ApiResponse<T>.Fail(ex.Errors.Select(e => e.ErrorMessage).ToArray())); }
        catch (ForbiddenAccessException)
        { return StatusCode(403, ApiResponse<T>.Fail("Forbidden")); }
    }
}
```

## 3. Mode B — REPR Minimal API Endpoint

```csharp
// API/Endpoints/Orders/GetOrderSummary.cs — everything the route needs, in one file.
public static class GetOrderSummary
{
    public sealed record Request(Guid OrderId);
    public sealed record Response(Guid Id, string Status, decimal Total);

    public static void Map(IEndpointRouteBuilder app) =>
        app.MapGet("/orders/{orderId:guid}/summary", Handle)
           .RequireAuthorization();

    private static async Task<IResult> Handle(
        Guid orderId,
        AppDbContext db,                 // direct DbContext — NO repository in REPR mode
        IPricingService pricing,         // reuse extracted as a decoupled SERVICE
        CancellationToken ct)
    {
        var order = await db.Orders
            .AsNoTracking()
            .Where(o => o.Id == orderId)
            .Select(o => new Response(o.Id, o.Status.ToString(), o.Lines.Sum(l => l.Price * l.Qty)))
            .FirstOrDefaultAsync(ct);

        return order is null ? Results.NotFound() : Results.Ok(order);
    }
}
```

```csharp
// BAD (REPR mode): repository abstraction wrapping EF Core — banned bloat here.
public interface IOrderRepository { Task<Order?> GetByIdAsync(Guid id); }
```

## 4. AsNoTracking + Projection — GOOD/BAD

```csharp
// BAD: tracked, fully hydrated entity graph for a read-only list
var orders = await db.Orders
    .Include(o => o.Lines).Include(o => o.Customer)
    .ToListAsync(ct);
var dtos = orders.Select(o => new OrderListDto(o.Id, o.Customer.Name, o.Lines.Count));
// Change tracker bloat + entire graph pulled over the wire for 3 columns.
```

```csharp
// GOOD: no tracking, projection composed into SQL — only 3 columns fetched
var dtos = await db.Orders
    .AsNoTracking()
    .Select(o => new OrderListDto(o.Id, o.Customer.Name, o.Lines.Count))
    .ToListAsync(ct);
```

```csharp
// Concurrency + no cascade delete on critical records
builder.Entity<Invoice>(e =>
{
    e.Property(i => i.RowVersion).IsRowVersion();
    e.HasMany(i => i.Payments)
     .WithOne(p => p.Invoice)
     .OnDelete(DeleteBehavior.Restrict);   // never cascade critical records
});
```

## 5. Async + CancellationToken Propagation

```csharp
// GOOD: token flows from the endpoint all the way down
private static async Task<IResult> Handle(AppDbContext db, CancellationToken ct)
    => Results.Ok(await db.Orders.AsNoTracking().CountAsync(ct));
```

```csharp
// BAD: sync-over-async and swallowed token
var count = db.Orders.CountAsync().Result;      // deadlock risk
await db.SaveChangesAsync();                    // ct available but not passed
```

## 6. Integration Test Against the Real Dev DB (Zero-Mock)

```csharp
// Tests.Integration/Orders/GetOrderSummaryTests.cs
public sealed class GetOrderSummaryTests : IClassFixture<DevDbApiFactory>
{
    private readonly HttpClient _client;
    private readonly AppDbContext _db;   // REAL DbContext → REAL Dev DB

    public GetOrderSummaryTests(DevDbApiFactory factory)
    {
        _client = factory.CreateClient();
        _db = factory.Services.CreateScope()
            .ServiceProvider.GetRequiredService<AppDbContext>();
    }

    [Fact]
    public async Task Returns_projected_summary_for_existing_order()
    {
        // Arrange: seed real rows in the Dev DB (unique IDs → parallel-safe)
        var order = TestData.NewOrder(lines: 2);
        _db.Orders.Add(order);
        await _db.SaveChangesAsync();

        // Act: real HTTP → real pipeline → real SQL
        var res = await _client.GetFromJsonAsync<GetOrderSummary.Response>(
            $"/orders/{order.Id}/summary");

        // Assert
        Assert.Equal(order.Id, res!.Id);
        Assert.Equal(order.Lines.Sum(l => l.Price * l.Qty), res.Total);
    }
}

// DevDbApiFactory: WebApplicationFactory<Program> pointing the connection string
// at the Dev DB. It does NOT swap in InMemory/SQLite providers.
```

```csharp
// BAD: mocked DbContext — proves nothing about SQL translation, constraints, or concurrency.
var mockDb = new Mock<AppDbContext>();
mockDb.Setup(d => d.Orders).ReturnsDbSet(fakeOrders);   // FORBIDDEN
```
