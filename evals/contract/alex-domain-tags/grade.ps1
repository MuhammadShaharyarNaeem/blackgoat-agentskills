<#
.SYNOPSIS
    Deterministic grader for the alex-domain-tags eval case.

.DESCRIPTION
    Checks whether a plan.md Alex produced from `prompt.md` alone -- a brief that
    never mentions domain tags, milestone homogeneity, or milestone shape -- still
    carries the `planning-and-task-breakdown` methodology's domain-tag and
    homogeneity rules. Per case.md, the brief's silence on this is the test: if Alex
    only gets this right when told directly, that's a real gap the methodology file
    isn't actually closing.

    Criteria (b) and (c) are deliberately not the same check twice: (b) inspects
    EVERY milestone block in the plan; (c) shells out to the real pipeline gate
    (next_milestone.py), which only ever evaluates the first pending milestone (the
    one it would actually route to a builder) -- so (c) proves the real gate a
    freshly generated plan would hit passes, while (b) proves the rest of the plan
    doesn't have a violation the gate simply hasn't reached yet.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in (the parent of `.docs/`).

.OUTPUTS
    Prints "PASSED: [n] ..." / "FAILED: [n] ..." lines for each criterion, then a
    final RESULT line. Exit 0 = all criteria passed. Exit 1 = at least one failed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

# This grader lives at <plugin>/evals/contract/alex-domain-tags/grade.ps1
$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $evalDir))
$nextMilestonePy = Join-Path $pluginRoot 'skills\pipeline-tools\scripts\next_milestone.py'
$checkCoveragePy = Join-Path $pluginRoot 'skills\pipeline-tools\scripts\check_coverage.py'

$requirementsPath = Join-Path $TargetDir '.docs\supplier-contacts\requirements.md'
$planPath = Join-Path $TargetDir '.docs\supplier-contacts\plan.md'

$failures = New-Object System.Collections.Generic.List[string]

if (-not (Test-Path $nextMilestonePy) -or -not (Test-Path $checkCoveragePy)) {
    Write-Output "FAILED: [0] pipeline-tools scripts not found under $pluginRoot\skills\pipeline-tools\scripts"
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

$planContent = Get-Content -Path $planPath -Raw -Encoding UTF8
$planContent = $planContent -replace "`r`n", "`n"

# --- (a)+(b) domain tags and milestone homogeneity: defer to the plugin's
# own domain-tag lint (check_coverage.py plan mode) instead of reimplementing
# its block-splitting here. The previous inline regex split task blocks only
# on task headings, so the LAST task of every milestone swallowed the NEXT
# milestone heading's [UI]/[API] token and false-failed as "both tags" --
# proven against a fully conformant, lint-clean plan on 2026-08-22. The lint
# scopes the check to each task's **Tags:** field; deferring to it keeps this
# grader byte-consistent with the contract the pipeline actually enforces.
$coverageOutput = & python $checkCoveragePy --requirements $requirementsPath --plan $planPath
$coverageExit = $LASTEXITCODE
$report = $null
try { $report = $coverageOutput | ConvertFrom-Json } catch { }

if (-not $report) {
    $failures.Add("3: check_coverage.py output unparseable (raw: $coverageOutput)")
    Write-Output "[3] FAILED: check_coverage.py output unparseable"
    $failures.Add('4: check_coverage.py output unparseable')
    Write-Output "[4] FAILED: check_coverage.py output unparseable"
} else {
    $domainFailures = @($report.lint_failures | Where-Object { $_.check -eq 'domain-tag' })
    $taskLevel = @($domainFailures | Where-Object { $_.task -match '^\d+$' })
    $milestoneLevel = @($domainFailures | Where-Object { $_.task -notmatch '^\d+$' })

    if ($taskLevel.Count -eq 0) {
        Write-Output "[3] PASSED: domain-tag lint reports no task-level violations (every task's **Tags:** line carries exactly one of [UI]/[API])"
    } else {
        $joined = ($taskLevel | ForEach-Object { "Task $($_.task): $($_.detail)" }) -join '; '
        $failures.Add("3: task-level domain-tag lint failure(s): $joined")
        Write-Output "[3] FAILED: task-level domain-tag lint failure(s): $joined"
    }

    $milestoneHeadingCount = ([regex]::Matches($planContent, '(?m)^#{2,3}\s*Milestone\b\s+\d')).Count
    if ($milestoneHeadingCount -eq 0) {
        $failures.Add('4: no milestone headings found')
        Write-Output "FAILED: [4] no '## Milestone <n>' / '### Milestone <n>' headings found in plan.md"
    } elseif ($milestoneLevel.Count -eq 0) {
        Write-Output "[4] PASSED: $milestoneHeadingCount milestone(s), domain-tag lint reports no heading or homogeneity violations"
    } else {
        $joined = ($milestoneLevel | ForEach-Object { "$($_.task): $($_.detail)" }) -join '; '
        $failures.Add("4: milestone-level domain-tag lint failure(s): $joined")
        Write-Output "[4] FAILED: milestone-level domain-tag lint failure(s): $joined"
    }
}

# --- (c) next_milestone.py --plan <plan> exits 0 (1 == MIXED == fail) ------
$null = & python $nextMilestonePy --plan $planPath
$nextMilestoneExit = $LASTEXITCODE
if ($nextMilestoneExit -eq 0) {
    Write-Output '[5] PASSED: next_milestone.py exits 0 (first pending milestone is not MIXED)'
} else {
    $failures.Add("5: next_milestone.py exited $nextMilestoneExit (1 = MIXED = planning defect)")
    Write-Output "[5] FAILED: next_milestone.py exited $nextMilestoneExit (1 = MIXED = planning defect)"
}

# --- (d) check_coverage.py exits 0 (reuses the criterion-3/4 invocation) ---
if ($coverageExit -eq 0) {
    Write-Output '[6] PASSED: check_coverage.py exits 0 (every Must-Have FR/NFR covered, no lint failures)'
} else {
    $report = $null
    try { $report = $coverageOutput | ConvertFrom-Json } catch { }
    $detail = if ($report) { "result=$($report.result) uncovered=$($report.uncovered -join ', ') lint_failures=$($report.lint_failures.Count)" } else { "raw output: $coverageOutput" }
    $failures.Add("6: check_coverage.py exited $coverageExit ($detail)")
    Write-Output "[6] FAILED: check_coverage.py exited $coverageExit ($detail)"
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
