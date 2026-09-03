using Microsoft.AspNetCore.Mvc;

namespace DashboardApi.Controllers;

[ApiController]
[Route("api")]
public class OpsController : ControllerBase
{
    [HttpGet("metrics")]
    public IActionResult Metrics() => Ok(new
    {
        uptimeSeconds = (int)(DateTime.UtcNow - System.Diagnostics.Process.GetCurrentProcess().StartTime.ToUniversalTime()).TotalSeconds,
        queueDepth = 0
    });
}
