<#
.SYNOPSIS
    Deterministic grader for the quinn-test-report-shape eval case.

.DESCRIPTION
    Checks that Quinn's test-report.md has the shape the pipeline-tools test-mode
    parser expects (a #Task [N]: header and at least one Coverage Ledger line), then
    shells out to skills/pipeline-tools/scripts/check_coverage.py to confirm the report
    is structurally parseable. Distinguishes a shape failure (exit 2) from a legitimate
    coverage result (exit 0 or 1) — this eval only checks shape, not whether Quinn's
    tests actually passed. Criteria 6 and 7 add the shape of *evidence*: agents/quinn.md
    requires every PASS to carry the verbatim command and its captured output, and until
    they were added nothing in her only eval looked for a command, an exit code, or any
    sign that something ran. See case.md for the numbered criteria this implements and
    for the honest limit on what a shape checker can conclude from them.

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

# [4] at least one Coverage Ledger line (- FR-n / NFR-n: PASS, FAIL or BLOCKED).
# BLOCKED is a real coverage token, not a near-miss: agents/quinn.md makes it the only
# honest status for a check whose precondition was absent, and check_coverage.py reports
# it in its own `blocked` array. A regex that omitted it would read an honest BLOCKED
# report as a shapeless one.
$ledgerLineRe = '^-\s*((?:FR|NFR)-\d+):\s*(PASS|FAIL|BLOCKED)\b(.*)$'
$ledgerMatches = [regex]::Matches($reportContent, $ledgerLineRe, 'Multiline')
if ($ledgerMatches.Count -gt 0) {
    Write-Output "[4] PASSED: $($ledgerMatches.Count) Coverage Ledger line(s) (- FR/NFR-n: PASS|FAIL|BLOCKED) present"
} else {
    $failures.Add("4: no Coverage Ledger line found in the documented '- FR-n: PASS/FAIL/BLOCKED' shape")
    Write-Output "[4] FAILED: no Coverage Ledger line found in the documented '- FR-n: PASS/FAIL/BLOCKED' shape"
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

# [6] every ledger line names what produced its status: a backticked command or a
# `file::test-name` reference. agents/quinn.md's strongest rule - every PASS carries the
# verbatim command and its captured output - was entirely unenforced by her only eval
# before this criterion existed. A status token with no producer named is an opinion.
$backtickedRe = '`[^`]+`'
$testRefRe = '[\w./\\-]+::[\w.\-]+'
$unevidenced = New-Object System.Collections.Generic.List[string]
foreach ($m in $ledgerMatches) {
    $id = $m.Groups[1].Value
    $rest = $m.Groups[3].Value
    if (($rest -notmatch $backtickedRe) -and ($rest -notmatch $testRefRe)) {
        $unevidenced.Add($id)
    }
}
if ($ledgerMatches.Count -eq 0) {
    $failures.Add('6: no ledger line to check for an evidence field (see [4])')
    Write-Output '[6] FAILED: no ledger line to check for an evidence field (see [4])'
} elseif ($unevidenced.Count -gt 0) {
    $joined = ($unevidenced | Select-Object -Unique) -join ', '
    $failures.Add("6: ledger line(s) name no command and no file::test-name reference: $joined")
    Write-Output "[6] FAILED: ledger line(s) name no command and no file::test-name reference: $joined"
} else {
    Write-Output "[6] PASSED: all $($ledgerMatches.Count) ledger line(s) name a backticked command or a file::test-name reference"
}

# [7] the report shows that something RAN: at least one fenced output block, or an
# `exit <N>` citation. Cheapest possible discriminator between a report written from a
# terminal and one written from memory.
$fenceCount = @([regex]::Matches($reportContent, '(?m)^\s*```')).Count
$hasExitCitation = $reportContent -match '(?i)\bexit\s+(?:code\s+)?-?\d+\b'
if ($fenceCount -ge 2 -or $hasExitCitation) {
    Write-Output "[7] PASSED: report carries run output (fenced blocks=$fenceCount, exit-code citation=$hasExitCitation)"
} else {
    $failures.Add('7: report carries neither a fenced output block nor an exit-code citation - nothing indicates a command was executed')
    Write-Output '[7] FAILED: report carries neither a fenced output block nor an exit-code citation - nothing indicates a command was executed'
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
