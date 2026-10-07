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

> The inline `Results.Ok(...)` above predates the Response Pattern and illustrates *token propagation*, not the wire contract — in real endpoints, wrap the payload in `BaseResponse<T>` and emit via `.ToResult()` (see [response-and-errors.md](response-and-errors.md)).

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

        // Act: IN-PROCESS pipeline via WebApplicationFactory — real handlers,
        // real middleware registrations, real SQL. NOT a socket: no Kestrel, no
        // host startup/config chain, no Swagger. This tier cannot falsify a
        // wire-shape claim (see the Tier ladder in SKILL.md).
        var res = await _client.GetAsync($"/api/v1/orders/{order.Id}/summary");

        // Assert the ENVELOPE on the raw body BEFORE binding. Closed-set over
        // top-level property names, per test-driven-development's closed-set
        // rule: a superset means payload fields leaked to the top level, a
        // subset means the envelope was only partly applied. All five keys are
        // expected because BaseResponse is serialized with stock
        // JsonSerializerDefaults.Web, which writes nulls (response-and-errors.md).
        var raw = await res.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(raw);
        Assert.Equal(
            new HashSet<string> { "statusCode", "isSuccess", "data", "dataContext", "notifications" },
            doc.RootElement.EnumerateObject().Select(p => p.Name).ToHashSet());

        // Only now bind and assert the payload.
        var envelope = JsonSerializer.Deserialize<BaseResponse<GetOrderSummaryResponse>>(
            raw, new JsonSerializerOptions(JsonSerializerDefaults.Web));
        Assert.True(envelope!.IsSuccess);
        Assert.Equal(order.Id, envelope.Data!.Id);
        Assert.Equal(order.Lines.Sum(l => l.Price * l.Qty), envelope.Data.Total);
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

```csharp
// BAD: binding straight into BaseResponse<T> and asserting a member.
var res = await _client.GetFromJsonAsync<BaseResponse<GetOrderSummaryResponse>>(url);
Assert.True(res!.IsSuccess);
```

Deserializing an **unwrapped** body into `BaseResponse<T>` throws nothing: no property
matches, so every member takes its default and `IsSuccess` is `false`. The test fails —
but it fails looking exactly like a logic bug, and the cheapest way to make it green is
to change the generic parameter to the bare DTO. That "fix" makes the test pass and
leaves the API wrong. This is the observed 2026-08 failure: the envelope was green in
this tier and absent in local Swagger. Assert the wire shape on the raw body, and prove
the wire shape itself at Tier 3 — never here.

### 3.1 Mode B Fast Tests — SQLite In-Memory (deliberate divergence)

Deliberate divergence (convention #8) from the rule above and from SKILL.md's Tier 2 bullet,
which put every DB-crossing test against the real Dev DB: in **Mode B**, a *fast*
handler/endpoint test may run the real `AppDbContext` model on **EF Core SQLite in-memory**.
This is not the forbidden kind of fake. SQLite executes real SQL — query translation,
constraints, `ExecuteUpdateAsync`, transactions — where `Mock<AppDbContext>` and the EF
InMemory provider execute none of it; both stay forbidden.

```csharp
// The shape of BillingFuncInbound's Tests/Common/SqliteTestDatabase.cs:
// one open in-memory connection per test, the real model created on it.
var connection = new SqliteConnection("DataSource=:memory:");
connection.CreateFunction("getutcdate", () => DateTime.UtcNow);   // shim for a SQL Server default
connection.Open();
var options = new DbContextOptionsBuilder<AppDbContext>()
    .UseSqlite(connection)
    .ConfigureWarnings(w => w.Ignore(SqliteEventId.SchemaConfiguredWarning))   // SQLite has no schemas
    .Options;
using (var db = new AppDbContext(options)) db.Database.EnsureCreated();
```

**The limit: SQLite is not SQL Server's dialect.** No schemas, no SQL Server functions (each
one used by a column default needs a shim), different collation and case sensitivity,
different `datetime`/`decimal` storage, no `rowversion`, different locking and isolation. A
SQLite pass proves the logic over real SQL; it does not prove SQL Server translation of a
dialect-specific query, concurrency behaviour, or anything on the wire. Those stay with the
Dev DB tests above and with Tier 3 — including, for a Mode B migration, the proof that the
wire contract did not change.
