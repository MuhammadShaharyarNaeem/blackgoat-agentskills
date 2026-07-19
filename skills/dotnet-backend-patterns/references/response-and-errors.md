# Response Pattern, Errors, Notifications & Exceptions (Both Modes) — BG.Core

The standardized response envelope and the error model live in `BG.Infrastructure.Core`. They are used by **both** Mode A (CQRS) and Mode B (REPR) — every API result maps to `BaseResponse<T>` so the frontend interceptor receives one predictable contract. Do NOT hand-roll a per-service response type or a per-endpoint error shape.

How the envelope is *emitted* differs by mode (see [cqrs-playbook.md](cqrs-playbook.md) / [repr-playbook.md](repr-playbook.md) and §5 below); the envelope and error model themselves are shared and defined here.

## 1. `BaseResponse<T>` — the envelope

```csharp
// BG.Infrastructure.Core/Generics/BaseResponse.cs
public record BaseResponse<T>
{
    public HttpStatusCode StatusCode { get; init; }
    public bool IsSuccess { get; init; }
    public T? Data { get; init; }
    public Dictionary<string, object>? DataContext { get; init; }   // e.g. carries pagination
    public IReadOnlyCollection<Error> Notifications { get; init; } = Array.Empty<Error>();  // see §3

    public static BaseResponse<T> Success(T data, HttpStatusCode status = HttpStatusCode.OK) =>
        new() { IsSuccess = true, StatusCode = status, Data = data };

    // Unwraps a BaseCommandResponse<T> and lifts pagination into DataContext.
    public static BaseResponse<T> SuccessCommandResponse(
        BaseCommandResponse<T> commandResponse, HttpStatusCode status = HttpStatusCode.OK) { /* ... */ }

    public static BaseResponse<T> ValidationFailure(
        IEnumerable<Error> errors, HttpStatusCode status = HttpStatusCode.BadRequest) => Failure(errors, status);

    public static BaseResponse<T> Failure(IEnumerable<Error> errors, HttpStatusCode status) =>
        new() { IsSuccess = false, StatusCode = status, Notifications = errors.ToArray() };

    public static BaseResponse<T> Failure(Error? error, HttpStatusCode status) =>
        new() { IsSuccess = false, StatusCode = status, Notifications = [error] };
}
```

## 2. The `Error` record + structured `ErrorCode`

Errors are structured records — **NOT bare strings**. Each carries a machine-readable 6-digit code plus human/UX context.

```csharp
// BG.Infrastructure.Core/ErrorHandling/Error.cs
public sealed record Error(ErrorCode Code, string Message, string? PropertyName = null, string? ActionHint = null);

// BG.Infrastructure.Core/ErrorHandling/ErrorCode.cs — a 6-digit code: MM TT NN
//   MM = Microservice, TT = ErrorType, NN = Number. Implicitly converts to/from string.
public readonly record struct ErrorCode
{
    public const int Length = 6;
    public string Value { get; }
    public byte Microservice => byte.Parse(Value[..2]);
    public byte ErrorType    => byte.Parse(Value[2..4]);
    public byte Number       => byte.Parse(Value[4..6]);

    public static ErrorCode From(byte microservice, byte type, byte number) =>
        new($"{microservice:D2}{type:D2}{number:D2}");

    public static implicit operator string(ErrorCode c) => c.Value;   // "010103"
    public static implicit operator ErrorCode(string raw) => new(raw); // validates 6 digits
    public static bool TryParse(string? raw, out ErrorCode code) { /* ... */ }
}
```

**Code registries** — compose codes from these; do not invent magic numbers inline.

**⚠️ The `MicroserviceCodes` (MM) values below are illustrative, from the BG reference implementation — `MicroserviceCodes` is per-project, never copied wholesale.** Every project defines its own `MicroserviceCodes` registry. Before minting any `ErrorCode`, discover the project's existing registry in its error-handling code — do not blindly reuse these values. A project with no microservices registers a single code: `{ProjectName} = 01`.

```csharp
// MicroserviceCodes (MM)                 // ErrorTypeCodes (TT) — drives frontend UX behavior
Authentication  = 01;                     Field_Validations    = 01;  // inline field error
Domain          = 02;                     Popup_Validations    = 02;  // modal
L1Authorization = 03;                     Toast_Validations    = 03;  // toast
FileExplorer    = 04;                     Redirect_Validations = 04;  // redirect
Subscription    = 05;                     Silent_Validations   = 05;  // no UI
Billing         = 06;

// ToastTypeCodes: SuccessType=01, InformationType=02, WarningType=03, ErrorType=04

// Example: a field-validation error #3 raised by the Subscription microservice
var code = ErrorCode.From(MicroserviceCodes.Subscription, ErrorTypeCodes.Field_Validations, 3); // "050103"
```

## 3. Notifications

`BaseResponse<T>.Notifications` is the collection of `Error`s returned to the client — the "notifications" the frontend renders (inline/popup/toast/redirect/silent, per each error's `ErrorType`). On success it is empty; on failure it holds one or more `Error`s. It is the single channel for conveying problems — never throw raw strings or return ad-hoc `{ message }` bodies.

## 4. `CustomException` — the domain-throwable that maps cleanly to an `Error`

Throw this from handlers/services/domain logic. It carries everything needed to build an `Error` + the HTTP status, so the mapping layer (§5) turns it into a `BaseResponse` without guesswork.

```csharp
// BG.Infrastructure.Core/ExceptionHandling/CustomException.cs
public class CustomException : Exception
{
    public ErrorCode Code { get; }
    public HttpStatusCode StatusCode { get; }
    public string? PropertyName { get; }
    public string? ActionHint { get; }

    public CustomException(string message, HttpStatusCode statusCode = HttpStatusCode.BadRequest) : base(message)
        => StatusCode = statusCode;

    public CustomException(ErrorCode code, string? message = null,
        HttpStatusCode statusCode = HttpStatusCode.BadRequest,
        string? propertyName = null, string? actionHint = null, Exception? inner = null) : base(message, inner)
    { Code = code; StatusCode = statusCode; PropertyName = propertyName; ActionHint = actionHint; }
}

// Throw with a registry-composed code:
throw new CustomException(
    ErrorCode.From(MicroserviceCodes.Billing, ErrorTypeCodes.Popup_Validations, 7),
    "Card was declined.", HttpStatusCode.PaymentRequired, actionHint: "Update payment method");
```

## 5. Mapping failures + emitting the envelope

`BaseResponseExtensions` turns exceptions/validation failures into `BaseResponse<T>` and emits the framework result. **Note the two emit paths — pick the one matching the mode.**

```csharp
// BG.Infrastructure.Core/Extensions/BaseResponseExtensions.cs
public static class BaseResponseExtensions
{
    public static BaseResponse<T> ToBaseResponse<T>(this CustomException ex) =>
        BaseResponse<T>.Failure(new Error((string)ex.Code, ex.Message, ex.PropertyName.ToCamelCase(), ex.ActionHint), ex.StatusCode);

    public static BaseResponse<T> ToBaseResponse<T>(this ValidationException ex) =>       // FluentValidation
        BaseResponse<T>.Failure(ex.Errors.Select(FromFluent), HttpStatusCode.BadRequest);

    // Mode A (MVC controllers) — returns IActionResult:
    public static IActionResult ToActionResult<T>(this BaseResponse<T> response) =>
        new ObjectResult(response) { StatusCode = (int)response.StatusCode };

    // Mode B (Minimal APIs) — returns IResult. ⚠️ NOT yet in BG.Core; add it to consume the
    // envelope from REPR endpoints (minimal APIs do not accept IActionResult):
    public static IResult ToResult<T>(this BaseResponse<T> response) =>
        Results.Json(response, statusCode: (int)response.StatusCode);
}
```

- **Mode A (CQRS):** the generic `BaseController<T>` wraps every send in try/catch and calls `.ToActionResult()`. Mapping lives in one place. → [cqrs-playbook.md](cqrs-playbook.md).
- **Mode B (REPR):** there is no base controller, so centralize the same mapping in a native `IExceptionHandler` (below) and return success envelopes via `.ToResult()`. → [repr-playbook.md](repr-playbook.md).

```csharp
// Mode B centralized exception → envelope (registered once in Program.cs).
public sealed class BaseResponseExceptionHandler : IExceptionHandler
{
    public async ValueTask<bool> TryHandleAsync(HttpContext ctx, Exception ex, CancellationToken ct)
    {
        BaseResponse<object?> response = ex switch
        {
            ValidationException vex => vex.ToBaseResponse<object?>(),
            CustomException cex     => cex.ToBaseResponse<object?>(),
            _ => BaseResponse<object?>.Failure(
                     new Error(ErrorCode.From(MicroserviceCodes.Domain, ErrorTypeCodes.Silent_Validations, 0),
                               "An unexpected error occurred."),
                     HttpStatusCode.InternalServerError)
        };
        ctx.Response.StatusCode = (int)response.StatusCode;
        await ctx.Response.WriteAsJsonAsync(response, ct);
        return true;
    }
}
// Program.cs: builder.Services.AddExceptionHandler<BaseResponseExceptionHandler>(); builder.Services.AddProblemDetails(); ... app.UseExceptionHandler();
```

**Wire format.** The org's APIs use stock serialization (`JsonSerializerDefaults.Web`): C# PascalCase members serialize to **camelCase** JSON (`isSuccess`, `data`, `notifications`). Frontend contracts must use camelCase — see the Vue 3 playbook's interceptor (vue3-spa-patterns/references/vue3-playbook.md §4). Do not set `PropertyNamingPolicy = null`.

⚠️ `ErrorCode` is a `readonly record struct` — without a `JsonConverter<ErrorCode>` it serializes as an object (`{"value":"010103",...}`), not the 6-digit string frontends slice for the TT segment. Add a string round-trip `JsonConverter<ErrorCode>` to BG.Core alongside `ToResult` (not yet present).
