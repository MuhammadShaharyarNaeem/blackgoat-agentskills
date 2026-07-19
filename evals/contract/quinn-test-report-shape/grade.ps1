<#
.SYNOPSIS
    Deterministic grader for the quinn-test-report-shape eval case.

.DESCRIPTION
    Checks that Quinn's test-report.md has the shape the pipeline-tools test-mode
    parser expects (a #Task [N]: header and at least one Coverage Ledger line), then
    shells out to skills/pipeline-tools/scripts/check_coverage.py to confirm the report
    is structurally parseable. Distinguishes a shape failure (exit 2) from a legitimate
    coverage result (exit 0 or 1) — this eval only checks shape, not whether Quinn's
    tests actually passed. See case.md for the numbered criteria this implements.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in.

.OUTPUTS
    Prints "PASSED: [n] ..." / "FAILED: [n] ..." lines for each criterion, then a final
    RESULT line. Exit 0 = all criteria passed. Exit 1 = at least one criterion failed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

# This grader lives at <plugin>/evals/contract/quinn-test-report-shape/grade.ps1
$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $evalDir))
$checkCoveragePy = Join-Path $pluginRoot 'skills\pipeline-tools\scripts\check_coverage.py'

$requirementsPath = Join-Path $TargetDir '.docs\password-reset\requirements.md'
$testReportPath = Join-Path $TargetDir '.docs\password-reset\test-report.md'

$failures = New-Object System.Collections.Generic.List[string]

if (-not (Test-Path $checkCoveragePy)) {
    Write-Output "FAILED: [0] check_coverage.py not found at $checkCoveragePy"
    exit 1
}

if (-not (Test-Path $requirementsPath)) {
    Write-Output "FAILED: [1] requirements.md missing at $requirementsPath (fixture copy step likely failed)"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed)'
    exit 1
}
Write-Output '[1] PASSED: requirements.md present'

if (-not (Test-Path $testReportPath)) {
    Write-Output "FAILED: [2] test-report.md was not produced at $testReportPath"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed, plus [1])'
    exit 1
}
Write-Output '[2] PASSED: test-report.md exists'

$reportContent = Get-Content -Path $testReportPath -Raw

# [3] at least one #Task [N]: header
if ($reportContent -match '(?m)^#Task\s*\[?\d+\]?\s*:') {
    Write-Output '[3] PASSED: at least one #Task [N]: header present'
} else {
    $failures.Add('3: no #Task [N]: header found')
    Write-Output '[3] FAILED: no #Task [N]: header found'
}

# [4] at least one Coverage Ledger line (- FR-n / NFR-n: PASS or FAIL)
if ($reportContent -match '(?m)^-\s*(FR|NFR)-\d+:\s*(PASS|FAIL)\b') {
    Write-Output '[4] PASSED: at least one Coverage Ledger line (- FR/NFR-n: PASS|FAIL) present'
} else {
    $failures.Add("4: no Coverage Ledger line found in the documented '- FR-n: PASS/FAIL' shape")
    Write-Output "[4] FAILED: no Coverage Ledger line found in the documented '- FR-n: PASS/FAIL' shape"
}

# [5] check_coverage.py can structurally parse the report: exit 0 or 1, never 2
$output = & python $checkCoveragePy --requirements $requirementsPath --test-report $testReportPath
$exitCode = $LASTEXITCODE

$jsonParsedOk = $true
$report = $null
try {
    $report = $output | ConvertFrom-Json
} catch {
    $jsonParsedOk = $false
}

if (-not $jsonParsedOk) {
    $failures.Add('5: check_coverage.py did not emit parseable JSON')
    Write-Output '[5] FAILED: check_coverage.py did not emit parseable JSON'
} elseif ($exitCode -eq 2) {
    $failures.Add("5: check_coverage.py returned exit 2 (structural failure): $($report.error)")
    Write-Output "[5] FAILED: check_coverage.py returned exit 2 (structural failure): $($report.error)"
} else {
    Write-Output "[5] PASSED: check_coverage.py parsed the report structurally (exit=$exitCode, result=$($report.result))"
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
