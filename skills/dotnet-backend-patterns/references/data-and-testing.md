# Data & Testing Discipline (Both Modes) — Code Patterns

Shared EF Core, async, and zero-mock testing discipline. Applies to **both** Mode A (CQRS) and Mode B (REPR). Read alongside your mode playbook — [cqrs-playbook.md](cqrs-playbook.md) or [repr-playbook.md](repr-playbook.md).

## 1. AsNoTracking + Projection — GOOD/BAD

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

## 2. Async + CancellationToken Propagation

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

## 3. Integration Test Against the Real Dev DB (Zero-Mock)

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
        var res = await _client.GetFromJsonAsync<BaseResponse<GetOrderSummary.Response>>(
            $"/orders/{order.Id}/summary");

        // Assert
        Assert.True(res!.IsSuccess);
        Assert.Equal(order.Id, res.Data!.Id);
        Assert.Equal(order.Lines.Sum(l => l.Price * l.Qty), res.Data.Total);
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
