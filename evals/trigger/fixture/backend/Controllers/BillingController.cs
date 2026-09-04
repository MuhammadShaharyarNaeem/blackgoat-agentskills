using Microsoft.AspNetCore.Mvc;

namespace DashboardApi.Controllers;

// Single-tenant billing: one customer per account, no tenant boundary anywhere.
[ApiController]
[Route("api/billing")]
public class BillingController : ControllerBase
{
    [HttpGet("invoices/{accountId:int}")]
    public IActionResult Invoices(int accountId) => Ok(new { accountId, invoices = Array.Empty<object>() });

    [HttpPost("invoices/{invoiceId:int}/void")]
    public IActionResult Void(int invoiceId) => NoContent();

    [HttpGet("plans")]
    public IActionResult Plans() => Ok(new[] { "starter", "team" });
}
