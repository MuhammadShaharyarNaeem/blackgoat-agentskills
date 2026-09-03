<#
.SYNOPSIS
    Deterministic grader for the alex-acceptance-matrix eval case.

.DESCRIPTION
    Checks Alex's second plan-time artifact, acceptance-matrix.md, plus the two
    plan-side declarations the runtime-evidence tier depends on ([vs:] surface tags
    and conforming RUNTIME PROBE: lines). It shells out to the plugin's own gates —
    check_acceptance_suite.py for the matrix and check_coverage.py's
    runtime-criterion lint for the probes — rather than reimplementing their parsing
    rules, per the pipeline-tools single-contract-authority rule, and reads the
    matrix structure back out of the gate's JSON instead of re-parsing the markdown.

    check_acceptance_suite.py needs a --results file it exits 2 without, and at plan
    time none exists, so this grader writes a fixed one-line stub to its own temp
    path and removes it afterwards. See case.md criterion 3 for why that keeps the
    matrix the only variable.

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no `&&`/`||`,
    and $LASTEXITCODE (never $?) for native exit codes.

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

# This grader lives at <plugin>/evals/contract/alex-acceptance-matrix/grade.ps1
$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $evalDir))
$checkAcceptancePy = Join-Path $pluginRoot 'skills\pipeline-tools\scripts\check_acceptance_suite.py'
$checkCoveragePy = Join-Path $pluginRoot 'skills\pipeline-tools\scripts\check_coverage.py'

$requirementsPath = Join-Path $TargetDir '.docs\device-mapping\requirements.md'
$matrixPath = Join-Path $TargetDir '.docs\device-mapping\acceptance-matrix.md'
$planPath = Join-Path $TargetDir '.docs\device-mapping\implementation\plan.md'

$failures = New-Object System.Collections.Generic.List[string]

foreach ($tool in @($checkAcceptancePy, $checkCoveragePy)) {
    if (-not (Test-Path $tool)) {
        Write-Output "FAILED: [0] required pipeline-tools script not found at $tool"
        exit 1
    }
}

if (-not (Test-Path $requirementsPath)) {
    Write-Output "FAILED: [1] requirements.md missing at $requirementsPath (fixture copy step likely failed)"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed)'
    exit 1
}
Write-Output '[1] PASSED: requirements.md present'

if (-not (Test-Path $matrixPath)) {
    Write-Output "FAILED: [2] acceptance-matrix.md was not produced at $matrixPath"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed, plus [1])'
    exit 1
}
Write-Output '[2] PASSED: acceptance-matrix.md exists'

$matrixContent = Get-Content -Path $matrixPath -Raw -Encoding UTF8
$matrixContent = $matrixContent -replace "`r`n", "`n"

# --- [3] the real gate can parse the matrix (exit 0 or 1, never 2) ------------
$stubResultsPath = Join-Path $env:TEMP ("grade-acceptance-stub-" + [guid]::NewGuid().ToString('N').Substring(0, 8) + ".md")
$gateReport = $null
$gateExit = $null
try {
    @(
        '# Acceptance Results - grader stub',
        '',
        'Fixed stub written by grade.ps1: check_acceptance_suite.py requires --results and',
        'exits 2 without a parseable one. Keeping it constant makes the matrix the only',
        'variable behind an exit 2. See case.md criterion 3.',
        '',
        '- AS-1.1: PASS - grader stub'
    ) | Set-Content -Path $stubResultsPath -Encoding UTF8

    $gateOutput = & python $checkAcceptancePy --matrix $matrixPath --results $stubResultsPath --repo $TargetDir
    $gateExit = $LASTEXITCODE
    try {
        $gateReport = $gateOutput | ConvertFrom-Json
    } catch {
        $gateReport = $null
    }
} finally {
    Remove-Item -Path $stubResultsPath -Force -ErrorAction SilentlyContinue
}

if ($gateReport -eq $null) {
    $failures.Add("3: check_acceptance_suite.py did not emit parseable JSON (exit=$gateExit)")
    Write-Output "[3] FAILED: check_acceptance_suite.py did not emit parseable JSON (exit=$gateExit)"
} elseif ($gateExit -eq 2) {
    $failures.Add("3: check_acceptance_suite.py returned exit 2 (structural): $($gateReport.error)")
    Write-Output "[3] FAILED: check_acceptance_suite.py returned exit 2 (the matrix is not structurally an acceptance matrix): $($gateReport.error)"
} else {
    Write-Output "[3] PASSED: check_acceptance_suite.py parsed the matrix structurally (exit=$gateExit, result=$($gateReport.result))"
}

# On exit 2 the gate emits only the minimal {"result","error"} envelope - no
# scenarios/steps/warnings keys - so criteria 4-6 have nothing to read and must say
# so rather than blowing up on a null.
$gateUsable = ($gateReport -ne $null) -and ($gateExit -ne 2)

$scenarios = @()
$steps = @()
$gateWarnings = @()
if ($gateUsable) {
    $scenarios = @($gateReport.scenarios)
    $steps = @($gateReport.steps)
    $gateWarnings = @($gateReport.warnings)
}

# --- [4] scenarios are addressable and prioritized ---------------------------
if (-not $gateUsable) {
    $failures.Add('4: gate could not parse the matrix, scenario metadata not assessable')
    Write-Output '[4] FAILED: gate could not parse the matrix, scenario metadata not assessable (see [3])'
} else {
    $problems = New-Object System.Collections.Generic.List[string]
    if ($scenarios.Count -lt 2) { $problems.Add("only $($scenarios.Count) scenario(s) parsed, expected >= 2") }
    $allReqs = New-Object System.Collections.Generic.List[string]
    foreach ($sc in $scenarios) {
        if ([string]::IsNullOrWhiteSpace($sc.priority)) { $problems.Add("$($sc.id) declares no P0-style priority token") }
        if ([string]::IsNullOrWhiteSpace($sc.surface)) { $problems.Add("$($sc.id) has no 'Surface:' metadata value") }
        $reqs = @($sc.requirements)
        if ($reqs.Count -eq 0) { $problems.Add("$($sc.id) cites no requirement id inside its heading parentheses") }
        foreach ($r in $reqs) { $allReqs.Add($r.ToUpperInvariant()) }
    }
    foreach ($needed in @('FR-1', 'FR-2')) {
        if (-not ($allReqs -contains $needed)) { $problems.Add("no scenario covers Must-Have $needed") }
    }
    if ($problems.Count -eq 0) {
        Write-Output "[4] PASSED: $($scenarios.Count) scenarios, each with a priority, a Surface, and requirement ids; FR-1 and FR-2 both covered"
    } else {
        $joined = $problems -join '; '
        $failures.Add("4: $joined")
        Write-Output "[4] FAILED: $joined"
    }
}

# --- [5] step tables carry Stores and Mode ----------------------------------
if (-not $gateUsable) {
    $failures.Add('5: gate could not parse the matrix, step tables not assessable')
    Write-Output '[5] FAILED: gate could not parse the matrix, step tables not assessable (see [3])'
} else {
    $problems = New-Object System.Collections.Generic.List[string]
    foreach ($w in $gateWarnings) {
        if ($w -match "no 'Mode' column") { $problems.Add('a step table has no Mode column') }
        if ($w -match "no 'Stores' column") { $problems.Add('a step table has no Stores column') }
        if ($w -match 'no step table found') { $problems.Add($w) }
    }
    foreach ($sc in $scenarios) {
        if ($sc.step_count -lt 2) { $problems.Add("$($sc.id) has $($sc.step_count) step(s), expected >= 2") }
    }
    foreach ($st in $steps) {
        if (@($st.stores).Count -eq 0) { $problems.Add("$($st.key) names no Stores") }
        if (@('auto', 'manual') -notcontains $st.mode) { $problems.Add("$($st.key) has mode '$($st.mode)', expected auto or manual") }
    }
    if ($problems.Count -eq 0) {
        Write-Output "[5] PASSED: every step table carries Stores and Mode; $($steps.Count) steps across $($scenarios.Count) scenarios"
    } else {
        $joined = ($problems | Select-Object -Unique) -join '; '
        $failures.Add("5: $joined")
        Write-Output "[5] FAILED: $joined"
    }
}

# --- [6] inverses declared, and none dangling -------------------------------
if (-not $gateUsable) {
    $failures.Add('6: gate could not parse the matrix, inverse declarations not assessable')
    Write-Output '[6] FAILED: gate could not parse the matrix, inverse declarations not assessable (see [3])'
} else {
    $inverseSteps = @($steps | Where-Object { $_.inverse_of -ne $null })
    $dangling = @($gateReport.dangling_inverse)
    if ($dangling.Count -gt 0) {
        $joined = $dangling -join ', '
        $failures.Add("6: dangling [inverse of N] reference(s): $joined")
        Write-Output "[6] FAILED: dangling [inverse of N] reference(s) naming a step that does not exist: $joined"
    } elseif ($inverseSteps.Count -lt 2) {
        $failures.Add("6: only $($inverseSteps.Count) step(s) declare [inverse of N]; expected >= 2 (mapping and install both have one)")
        Write-Output "[6] FAILED: only $($inverseSteps.Count) step(s) declare [inverse of N]; expected >= 2 (the mapping feature and the install feature each have a natural inverse)"
    } else {
        Write-Output "[6] PASSED: $($inverseSteps.Count) steps declare [inverse of N], none dangling"
    }
}

# --- [7] reinstall is covered ------------------------------------------------
$tableRows = @([regex]::Matches($matrixContent, '(?m)^\|.*$') | ForEach-Object { $_.Value })
$reinstallRows = @($tableRows | Where-Object {
    ($_ -match '(?i)re-?install') -or ($_ -match '(?i)install\b[^|]*\bagain\b')
})
if ($reinstallRows.Count -gt 0) {
    Write-Output "[7] PASSED: $($reinstallRows.Count) step row(s) cover reinstall (the idempotency case)"
} else {
    $failures.Add('7: no step row covers reinstall - the idempotency case that catches a half-removing uninstall')
    Write-Output '[7] FAILED: no step row covers reinstall - the idempotency case that catches a half-removing uninstall'
}

# --- [8] every milestone heading carries a valid [vs:<surface>] tag ----------
# Regexes mirror next_milestone.py's MILESTONE_HEADING_RE / VS_TAG_RE verbatim,
# including the deliberately case-SENSITIVE lowercase tag (so [vs:api] can never
# collide with the [API] domain tag).
$validSurfaces = @('api', 'ui', 'web+api', 'rmm', 'fn', 'none')
if (-not (Test-Path $planPath)) {
    $failures.Add("8: plan.md was not produced at $planPath")
    Write-Output "[8] FAILED: plan.md was not produced at $planPath"
} else {
    $planContent = Get-Content -Path $planPath -Raw -Encoding UTF8
    $planContent = $planContent -replace "`r`n", "`n"
    $milestoneHeadings = @([regex]::Matches($planContent, '(?m)^#{2,3}\s*Milestone\b\s+\d.*$') | ForEach-Object { $_.Value })
    $badHeadings = New-Object System.Collections.Generic.List[string]
    foreach ($h in $milestoneHeadings) {
        $tag = [regex]::Match($h, '\[vs:([a-z+]{2,12})\]')
        if (-not $tag.Success) {
            $badHeadings.Add("no [vs:] tag on: $($h.Trim())")
        } elseif ($validSurfaces -notcontains $tag.Groups[1].Value) {
            $badHeadings.Add("unknown surface [vs:$($tag.Groups[1].Value)] on: $($h.Trim())")
        }
    }
    if ($milestoneHeadings.Count -eq 0) {
        $failures.Add('8: plan.md carries no "Milestone <n>" heading')
        Write-Output '[8] FAILED: plan.md carries no "Milestone <n>" heading'
    } elseif ($badHeadings.Count -gt 0) {
        $joined = $badHeadings -join ' | '
        $failures.Add("8: $joined")
        Write-Output "[8] FAILED: $joined"
    } else {
        Write-Output "[8] PASSED: all $($milestoneHeadings.Count) milestone heading(s) carry a valid [vs:<surface>] tag"
    }
}

# --- [9] checkpoint RUNTIME PROBE lines conform (runtime-criterion lint) -----
if (-not (Test-Path $planPath)) {
    $failures.Add('9: plan.md absent, runtime-criterion lint not assessable')
    Write-Output '[9] FAILED: plan.md absent, runtime-criterion lint not assessable (see [8])'
} else {
    $covOutput = & python $checkCoveragePy --requirements $requirementsPath --plan $planPath
    $covExit = $LASTEXITCODE
    $covReport = $null
    try {
        $covReport = $covOutput | ConvertFrom-Json
    } catch {
        $covReport = $null
    }
    if ($covReport -eq $null) {
        $failures.Add("9: check_coverage.py did not emit parseable JSON (exit=$covExit)")
        Write-Output "[9] FAILED: check_coverage.py did not emit parseable JSON (exit=$covExit)"
    } else {
        $probeFailures = @($covReport.lint_failures | Where-Object { $_.check -eq 'runtime-criterion' })
        if ($probeFailures.Count -eq 0) {
            Write-Output '[9] PASSED: no runtime-criterion lint failure - every checkpoint carries a conforming RUNTIME PROBE: line'
        } else {
            $joined = @($probeFailures | ForEach-Object { "$($_.task): $($_.detail)" }) -join ' | '
            $failures.Add("9: runtime-criterion lint failure(s): $joined")
            Write-Output "[9] FAILED: runtime-criterion lint failure(s): $joined"
        }
    }
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
