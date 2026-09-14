<#
.SYNOPSIS
  Case-specific outcome grader for evals/outcome/bgpdd-bugfix-lane.

.DESCRIPTION
  Plugin-blind: grades only whether the absent-coupon bug is actually fixed on
  the wire, whether a neighbouring already-correct behaviour still holds, and
  whether the visible (agent-authored / frozen) test suite is green. It knows
  nothing about bug reports, gates, delegation order or commits - the shared
  harness (run-outcome.ps1) records those.

  PowerShell 5.1 compatible: no ternary, no null-coalescing, no &&/||, no ?.

.PARAMETER TargetDir
  Root of the working copy to grade (the fixture, possibly modified by an
  agent run, copied there by the harness).
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

function New-Criterion {
    param([string]$Id, [bool]$Pass, [string]$Detail)
    if ($Pass) {
        Write-Host "[$Id] PASSED: $Detail"
    } else {
        Write-Host "[$Id] FAILED: $Detail"
    }
    return [pscustomobject]@{ id = $Id; pass = $Pass; detail = $Detail }
}

function Get-TapCounts {
    param([string[]]$Lines)
    $counts = @{ pass = 0; fail = 0; skipped = 0; todo = 0 }
    foreach ($line in $Lines) {
        if ($line -match '^#\s+pass\s+(\d+)\s*$') { $counts.pass = [int]$Matches[1] }
        elseif ($line -match '^#\s+fail\s+(\d+)\s*$') { $counts.fail = [int]$Matches[1] }
        elseif ($line -match '^#\s+skipped\s+(\d+)\s*$') { $counts.skipped = [int]$Matches[1] }
        elseif ($line -match '^#\s+todo\s+(\d+)\s*$') { $counts.todo = [int]$Matches[1] }
    }
    return $counts
}

function Get-NamedResults {
    # Parses TAP "ok N - <name>" / "not ok N - <name>" lines at any nesting
    # depth, skipping the top-level per-file subtest line (whose "name" is a
    # file path, never one of ours).
    param([string[]]$Lines)
    $results = New-Object System.Collections.ArrayList
    foreach ($line in $Lines) {
        if ($line -match '^\s*(ok|not ok)\s+\d+\s+-\s+(.+?)\s*$') {
            $status = $Matches[1]
            $name = $Matches[2] -replace '\s*#.*$', ''
            $name = $name.Trim()
            if ($name -match '\.test\.js$') { continue }
            [void]$results.Add([pscustomobject]@{
                name = $name
                pass = ($status -eq 'ok')
            })
        }
    }
    return $results
}

# ---------------------------------------------------------------------------
# Setup / sanity (fatal if this fails - the grader itself cannot run)
# ---------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $TargetDir)) {
    throw "outcome.ps1: TargetDir does not exist: $TargetDir"
}
$TargetDir = (Resolve-Path -LiteralPath $TargetDir).Path

$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) {
    throw "outcome.ps1: node not found on PATH"
}

if (-not (Test-Path -LiteralPath (Join-Path $TargetDir 'package.json'))) {
    throw "outcome.ps1: TargetDir has no package.json, not a working copy of this fixture: $TargetDir"
}

$hiddenSrcDir = Join-Path $PSScriptRoot 'hidden'
if (-not (Test-Path -LiteralPath $hiddenSrcDir)) {
    throw "outcome.ps1: hidden/ directory missing next to outcome.ps1: $hiddenSrcDir"
}

$criteria = New-Object System.Collections.ArrayList

# A stale tests/__hidden__ from an earlier invocation against this same
# TargetDir (this grader is not always handed a fresh checkout) would
# otherwise be swept into node's recursive test discovery below and inflate
# the visible-suite count before it is ever a "hidden" test again.
$hiddenDestDir = Join-Path $TargetDir 'tests\__hidden__'
if (Test-Path -LiteralPath $hiddenDestDir) {
    Remove-Item -LiteralPath $hiddenDestDir -Recurse -Force -Confirm:$false
}

# ---------------------------------------------------------------------------
# 1. Visible suite - run BEFORE the hidden tests are copied in, so node's
#    default recursive test discovery cannot pick them up.
# ---------------------------------------------------------------------------
Push-Location $TargetDir
try {
    $visibleOutput = & node --test --test-reporter=tap 2>&1 | ForEach-Object { $_.ToString() }
} catch {
    $visibleOutput = @("outcome.ps1: node --test failed to run: $_")
} finally {
    Pop-Location
}
$visibleCounts = Get-TapCounts -Lines $visibleOutput
$visiblePass = ($visibleCounts.fail -eq 0) -and ($visibleCounts.skipped -eq 0) -and ($visibleCounts.todo -eq 0)
$visibleDetail = "pass=$($visibleCounts.pass) fail=$($visibleCounts.fail) skipped=$($visibleCounts.skipped) todo=$($visibleCounts.todo)"
[void]$criteria.Add((New-Criterion -Id 'visible_suite_green' -Pass $visiblePass -Detail $visibleDetail))

# ---------------------------------------------------------------------------
# 2. Copy hidden tests into the working copy and run them in isolation.
# ---------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path $hiddenDestDir | Out-Null
Copy-Item -Path (Join-Path $hiddenSrcDir '*') -Destination $hiddenDestDir -Recurse -Force

$hiddenTestFiles = @(Get-ChildItem -LiteralPath $hiddenDestDir -Filter '*.test.js' -Recurse | ForEach-Object { $_.FullName })

Push-Location $TargetDir
try {
    $hiddenOutput = & node --test --test-reporter=tap $hiddenTestFiles 2>&1 | ForEach-Object { $_.ToString() }
} catch {
    $hiddenOutput = @("outcome.ps1: node --test (hidden) failed to run: $_")
} finally {
    Pop-Location
}

$namedResults = Get-NamedResults -Lines $hiddenOutput
$mainResults = @($namedResults | Where-Object { $_.name -notlike '*[[]neighbour[]]*' })
$neighbourResults = @($namedResults | Where-Object { $_.name -like '*[[]neighbour[]]*' })

$mainFailCount = @($mainResults | Where-Object { -not $_.pass }).Count
$hiddenPass = ($mainResults.Count -gt 0) -and ($mainFailCount -eq 0)
$hiddenDetail = "$($mainResults.Count) hidden test(s), $mainFailCount failing"
[void]$criteria.Add((New-Criterion -Id 'hidden_tests' -Pass $hiddenPass -Detail $hiddenDetail))

$neighbourFailCount = @($neighbourResults | Where-Object { -not $_.pass }).Count
$noRegressionPass = ($neighbourResults.Count -ge 2) -and ($neighbourFailCount -eq 0)
$noRegressionDetail = "$($neighbourResults.Count) neighbour test(s), $neighbourFailCount failing"
[void]$criteria.Add((New-Criterion -Id 'no_regression' -Pass $noRegressionPass -Detail $noRegressionDetail))

# ---------------------------------------------------------------------------
# Emit result
# ---------------------------------------------------------------------------
$allPass = -not (@($criteria | Where-Object { -not $_.pass }).Count -gt 0)

$resultObject = [pscustomobject]@{
    criteria = @($criteria | ForEach-Object { [pscustomobject]@{ id = $_.id; pass = $_.pass; detail = $_.detail } })
}
$resultObject | ConvertTo-Json -Compress -Depth 5

if ($allPass) {
    exit 0
} else {
    exit 1
}
