<#
.SYNOPSIS
    Deterministic grader for the alex-plan-coverage eval case.

.DESCRIPTION
    Shells out to the plugin's own coverage-gate CLI (skills/pipeline-tools/scripts/
    check_coverage.py) rather than reimplementing its parsing rules, per the pipeline-
    tools single-contract-authority rule. Adds one extra check the CLI does not make on
    its own: whether the deliberately cross-cutting requirement (FR-5) was threaded
    through multiple tasks instead of collapsed into one. See case.md for the numbered
    criteria this implements and why each one matters.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in (the parent of `.docs/`).

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

# This grader lives at <plugin>/evals/contract/alex-plan-coverage/grade.ps1
$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $evalDir))
$checkCoveragePy = Join-Path $pluginRoot 'skills\pipeline-tools\scripts\check_coverage.py'

$requirementsPath = Join-Path $TargetDir '.docs\webhook-notify\requirements.md'
$planPath = Join-Path $TargetDir '.docs\webhook-notify\plan.md'

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

if (-not (Test-Path $planPath)) {
    Write-Output "FAILED: [2] plan.md was not produced at $planPath"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed, plus [1])'
    exit 1
}
Write-Output '[2] PASSED: plan.md exists'

$planContent = Get-Content -Path $planPath -Raw

$output = & python $checkCoveragePy --requirements $requirementsPath --plan $planPath
$exitCode = $LASTEXITCODE
$report = $output | ConvertFrom-Json

# [3] the coverage gate itself passes
if ($exitCode -eq 0 -and $report.result -eq 'PASS' -and ($report.uncovered.Count -eq 0)) {
    Write-Output '[3] PASSED: check_coverage.py exit 0 / result PASS / uncovered empty'
} else {
    $uncoveredList = $report.uncovered -join ', '
    $failures.Add("3: check_coverage.py did not pass (exit=$exitCode, result=$($report.result), uncovered=$uncoveredList)")
    Write-Output "[3] FAILED: check_coverage.py did not pass (exit=$exitCode, result=$($report.result), uncovered=$uncoveredList)"
}

# [4] no task missing its Requirements covered field
$missingFieldWarnings = @($report.warnings | Where-Object { $_ -match "has no 'Requirements covered:' field" })
if ($missingFieldWarnings.Count -eq 0) {
    Write-Output '[4] PASSED: every task carries a Requirements covered field'
} else {
    $joined = $missingFieldWarnings -join '; '
    $failures.Add("4: one or more tasks missing 'Requirements covered:' ($joined)")
    Write-Output "[4] FAILED: one or more tasks missing 'Requirements covered:' ($joined)"
}

# [5] cross-cutting FR-5 (audit logging) threaded through >= 2 tasks, not collapsed into one
$taskBlocks = [regex]::Split($planContent, '(?m)(?=^##\s*Task\s*\[?\d+\]?\s*:)')
$fr5TaskCount = 0
foreach ($block in $taskBlocks) {
    if ($block -match '\*\*Requirements covered:\*\*[^\r\n]*\bFR-5\b') {
        $fr5TaskCount++
    }
}
if ($fr5TaskCount -ge 2) {
    Write-Output "[5] PASSED: cross-cutting FR-5 (audit logging) cited in $fr5TaskCount tasks, not collapsed into one"
} else {
    $failures.Add("5: cross-cutting FR-5 cited in only $fr5TaskCount task(s); expected >= 2")
    Write-Output "[5] FAILED: cross-cutting FR-5 cited in only $fr5TaskCount task(s); expected >= 2"
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
