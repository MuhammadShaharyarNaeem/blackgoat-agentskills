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

$planContent = Get-Content -Path $planPath -Raw

# --- (a) every ## Task block carries exactly one of [UI] / [API] -----------
$taskBlocks = [regex]::Split($planContent, '(?m)(?=^##\s*Task\s*\[?\d+\]?\s*:)') |
    Where-Object { $_ -match '(?m)^##\s*Task\s*\[?\d+\]?\s*:' }

if ($taskBlocks.Count -eq 0) {
    Write-Output "FAILED: [3] no '## Task [N]:' blocks found in plan.md"
    $failures.Add('3: no task blocks found')
} else {
    $badTasks = New-Object System.Collections.Generic.List[string]
    foreach ($block in $taskBlocks) {
        $headingLine = ($block -split "`n")[0].Trim()
        $hasUI = [regex]::IsMatch($block, '\[UI\]')
        $hasAPI = [regex]::IsMatch($block, '\[API\]')
        # exactly one of [UI]/[API] -- both or neither is a violation
        if ($hasUI -eq $hasAPI) {
            $badTasks.Add($headingLine)
        }
    }
    if ($badTasks.Count -eq 0) {
        Write-Output "[3] PASSED: all $($taskBlocks.Count) task block(s) carry exactly one of [UI]/[API]"
    } else {
        $joined = $badTasks -join '; '
        $failures.Add("3: task(s) missing exactly one domain tag: $joined")
        Write-Output "[3] FAILED: task(s) missing exactly one domain tag: $joined"
    }
}

# --- (b) every ## Milestone block is domain-homogeneous ---------------------
$milestoneBlocks = [regex]::Split($planContent, '(?m)(?=^##\s*Milestone\b\s+\d)') |
    Where-Object { $_ -match '(?m)^##\s*Milestone\b\s+\d' }

if ($milestoneBlocks.Count -eq 0) {
    Write-Output "FAILED: [4] no '## Milestone <n>' headings found in plan.md"
    $failures.Add('4: no milestone headings found')
} else {
    $mixedMilestones = New-Object System.Collections.Generic.List[string]
    foreach ($block in $milestoneBlocks) {
        $headingLine = ($block -split "`n")[0].Trim()
        $hasUI = [regex]::IsMatch($block, '\[UI\]')
        $hasAPI = [regex]::IsMatch($block, '\[API\]')
        if ($hasUI -and $hasAPI) {
            $mixedMilestones.Add($headingLine)
        }
    }
    if ($mixedMilestones.Count -eq 0) {
        Write-Output "[4] PASSED: all $($milestoneBlocks.Count) milestone(s) are domain-homogeneous"
    } else {
        $joined = $mixedMilestones -join '; '
        $failures.Add("4: mixed-domain milestone(s): $joined")
        Write-Output "[4] FAILED: mixed-domain milestone(s): $joined"
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

# --- (d) check_coverage.py --requirements ... --plan ... exits 0 -----------
$coverageOutput = & python $checkCoveragePy --requirements $requirementsPath --plan $planPath
$coverageExit = $LASTEXITCODE
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
