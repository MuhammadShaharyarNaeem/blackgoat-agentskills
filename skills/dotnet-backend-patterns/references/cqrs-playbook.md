# CQRS + MediatR Playbook (Mode A) — Code Patterns

GOOD/BAD examples for the CQRS execution path. C# 12 / .NET 8 style. Read this when the blueprint declares **Mode A**. Shared EF Core / async / testing discipline lives in [data-and-testing.md](data-and-testing.md); the `BaseResponse<T>` envelope + error/notification/exception model (used by both modes) lives in [response-and-errors.md](response-and-errors.md).

## 1. MediatR Validation Pipeline Behavior

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

## 2. Emitting the Response Pattern (Mode A)

The `BaseResponse<T>` envelope and the full error/notification/exception model are defined once in [response-and-errors.md](response-and-errors.md) — read that for the envelope shape, `Error`/`ErrorCode`, `Notifications`, and `CustomException`. **This section covers only how Mode A emits it:** the generic `BaseController<T>` wraps every MediatR send in try/catch and maps success/`ValidationException`/`CustomException` to `BaseResponse<T>` via `.ToActionResult()` (MVC `IActionResult`), so the mapping lives in exactly one place.

```csharp
// Generic base controller (Mode A) — cross-cutting try/catch → BaseResponse mapping lives here, once.
// Real implementation: BG.Infrastructure.Core/Generics/BaseController.cs
public abstract class BaseController<T> : ControllerBase where T : ControllerBase
{
    private readonly IMediator _mediator;

    protected BaseController(IMediator mediator) => _mediator = mediator;

    // DEPRECATED — do not call in new code; use ExecuteWithOKCommandResponse
    protected async Task<IActionResult> ExecuteWithOKResponse<TResponse>(IRequest<TResponse> request)
    {
        try { return BaseResponse<TResponse>.Success(await _mediator.Send(request, HttpContext.RequestAborted)).ToActionResult(); }
        catch (ValidationException vex) { return vex.ToBaseResponse<TResponse>().ToActionResult(); }
        catch (CustomException cex)     { return cex.ToBaseResponse<TResponse>().ToActionResult(); }
    }

    // For paginated/command results: unwraps BaseCommandResponse<T> and lifts pagination into DataContext.
    protected async Task<IActionResult> ExecuteWithOKCommandResponse<TData>(IRequest<BaseCommandResponse<TData>> request)
    {
        try { return BaseResponse<TData>.SuccessCommandResponse(await _mediator.Send(request, HttpContext.RequestAborted)).ToActionResult(); }
        catch (ValidationException vex) { return vex.ToBaseResponse<TData>().ToActionResult(); }
        catch (CustomException cex)     { return cex.ToBaseResponse<TData>().ToActionResult(); }
    }
}
```
