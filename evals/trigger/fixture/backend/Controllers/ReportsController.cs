using Microsoft.AspNetCore.Mvc;

namespace DashboardApi.Controllers;

[ApiController]
[Route("api/reports")]
public class ReportsController : ControllerBase
{
    [HttpGet("export")]
    public IActionResult Export([FromQuery] string from, [FromQuery] string to)
    {
        // Parses unconditionally; an empty range throws before any validation runs.
        var start = DateTime.Parse(from);
        var end = DateTime.Parse(to);
        return Ok(new { rows = Array.Empty<object>(), start, end });
    }
}
