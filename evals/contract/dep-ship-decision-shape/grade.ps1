<#
.SYNOPSIS
    Deterministic grader for the dep-ship-decision-shape eval case.

.DESCRIPTION
    Checks that Dep produced a ship-decision.md the shipping pipeline can gate on: it
    exists, carries exactly one unambiguous GO/NO-GO verdict (not zero, not both), and
    includes the Rollback Strategy and post-deploy checklist the verdict must accompany
    (per skills/shipping-and-launch/SKILL.md). Pure existence and regex checks — this
    eval only checks that the decision is machine-readable, not that GO/NO-GO is the
    correct call. See case.md for the numbered criteria this implements.

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

$implDir = Join-Path $TargetDir '.docs\checkout-service\implementation'
$fixtureSanityPath = Join-Path $implDir 'test-report.md'
$shipDecisionPath = Join-Path $implDir 'ship-decision.md'

$failures = New-Object System.Collections.Generic.List[string]

if (-not (Test-Path $fixtureSanityPath)) {
    Write-Output "FAILED: [1] test-report.md missing at $fixtureSanityPath (fixture copy step likely failed)"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed)'
    exit 1
}
Write-Output '[1] PASSED: fixture test-report.md present'

if (-not (Test-Path $shipDecisionPath)) {
    Write-Output "FAILED: [2] ship-decision.md was not produced at $shipDecisionPath"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed, plus [1])'
    exit 1
}
Write-Output '[2] PASSED: ship-decision.md exists'

$content = Get-Content -Path $shipDecisionPath -Raw

# [3] exactly one unambiguous verdict. Match labeled verdict lines
# (Ship Decision / Verdict / Recommendation), capturing NO-GO before GO so the GO
# substring inside NO-GO is never mistaken for a standalone GO verdict.
$verdictLineRe = '(?im)^[#>\s\-\*]*(?:Ship\s+Decision|Verdict|Recommendation)\b[^\r\n]*?\b(NO[-\s]?GO|GO)\b'
$verdictMatches = [regex]::Matches($content, $verdictLineRe)
$verdicts = @()
foreach ($m in $verdictMatches) {
    $v = $m.Groups[1].Value.ToUpperInvariant() -replace '\s', '-'
    $verdicts += $v
}
$distinctVerdicts = @($verdicts | Sort-Object -Unique)

if ($verdicts.Count -eq 0) {
    $failures.Add('3: no labeled GO/NO-GO verdict line found')
    Write-Output '[3] FAILED: no labeled GO/NO-GO verdict line found'
} elseif ($distinctVerdicts.Count -gt 1) {
    $failures.Add("3: ambiguous verdict - both $($distinctVerdicts -join ' and ') present")
    Write-Output "[3] FAILED: ambiguous verdict - both $($distinctVerdicts -join ' and ') present"
} else {
    Write-Output "[3] PASSED: single unambiguous verdict ($($distinctVerdicts[0]))"
}

# [4] Rollback section (heading containing "Rollback")
if ($content -match '(?im)^#{1,6}\s*.*\brollback\b') {
    Write-Output '[4] PASSED: Rollback section heading present'
} else {
    $failures.Add('4: no Rollback section heading found')
    Write-Output '[4] FAILED: no Rollback section heading found'
}

# [5] post-deploy checklist: a heading containing "Checklist", OR >= 3 checkbox items
$hasChecklistHeading = $content -match '(?im)^#{1,6}\s*.*\bchecklist\b'
$checkboxCount = ([regex]::Matches($content, '(?m)^\s*[-*]\s*\[[ xX]\]')).Count
if ($hasChecklistHeading -or $checkboxCount -ge 3) {
    Write-Output "[5] PASSED: post-deploy checklist present (heading=$hasChecklistHeading, checkboxes=$checkboxCount)"
} else {
    $failures.Add("5: no checklist heading and fewer than 3 checkbox items (found $checkboxCount)")
    Write-Output "[5] FAILED: no checklist heading and fewer than 3 checkbox items (found $checkboxCount)"
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
