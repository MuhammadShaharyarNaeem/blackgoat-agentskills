<#
.SYNOPSIS
    Deterministic grader for the echo-qa-discovery-shape eval case.

.DESCRIPTION
    Checks that Echo produced the full discovery QA trio (overview.md,
    QA/code-workflow.md, QA/manual-testing.md) under .docs/summary/invoice-emailing/
    and that manual-testing.md keeps the strict GO -> DO -> ASSERT table structure
    with P0/P1/P2 priority flags required by agents/echo.md. Pure existence and regex
    checks — this eval only checks shape, not whether the test baseline is faithful
    to the fixture's code paths. See case.md for the numbered criteria this implements.

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

$featureDir = Join-Path $TargetDir '.docs\summary\invoice-emailing'
$fixtureSanityPath = Join-Path $featureDir 'billing-api.md'
$overviewPath = Join-Path $featureDir 'overview.md'
$codeWorkflowPath = Join-Path $featureDir 'QA\code-workflow.md'
$manualTestingPath = Join-Path $featureDir 'QA\manual-testing.md'

$failures = New-Object System.Collections.Generic.List[string]

if (-not (Test-Path $fixtureSanityPath)) {
    Write-Output "FAILED: [1] billing-api.md missing at $fixtureSanityPath (fixture copy step likely failed)"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed)'
    exit 1
}
Write-Output '[1] PASSED: per-API fixture files present'

if (Test-Path $overviewPath) {
    Write-Output '[2] PASSED: overview.md exists'
} else {
    $failures.Add('2: overview.md was not produced')
    Write-Output "[2] FAILED: overview.md was not produced at $overviewPath"
}

if (Test-Path $codeWorkflowPath) {
    Write-Output '[3] PASSED: QA/code-workflow.md exists'
} else {
    $failures.Add('3: QA/code-workflow.md was not produced')
    Write-Output "[3] FAILED: QA/code-workflow.md was not produced at $codeWorkflowPath"
}

if (Test-Path $manualTestingPath) {
    Write-Output '[4] PASSED: QA/manual-testing.md exists'

    $manualContent = Get-Content -Path $manualTestingPath -Raw

    # [5] at least one markdown table row with adjacent GO | DO | ASSERT columns
    # (extra columns before GO or after ASSERT are fine)
    if ($manualContent -match '(?m)^\|(?:[^|\r\n]*\|)*?[^|\r\n]*\bGO\b[^|\r\n]*\|[^|\r\n]*\bDO\b[^|\r\n]*\|[^|\r\n]*\bASSERT\b') {
        Write-Output '[5] PASSED: GO -> DO -> ASSERT table structure present'
    } else {
        $failures.Add('5: no markdown table row with GO | DO | ASSERT columns found')
        Write-Output '[5] FAILED: no markdown table row with GO | DO | ASSERT columns found'
    }

    # [6] priority flags: at least one P0 AND at least one P1 or P2
    if ($manualContent -match '\bP0\b' -and $manualContent -match '\bP[12]\b') {
        Write-Output '[6] PASSED: P0 and P1/P2 priority flags present'
    } else {
        $failures.Add('6: missing priority flags (need at least one P0 and one P1 or P2)')
        Write-Output '[6] FAILED: missing priority flags (need at least one P0 and one P1 or P2)'
    }
} else {
    $failures.Add('4: QA/manual-testing.md was not produced')
    Write-Output "[4] FAILED: QA/manual-testing.md was not produced at $manualTestingPath"
    Write-Output '[5] SKIPPED: manual-testing.md missing'
    Write-Output '[6] SKIPPED: manual-testing.md missing'
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
