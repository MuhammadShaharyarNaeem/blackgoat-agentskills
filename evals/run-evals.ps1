<#
.SYNOPSIS
    Eval harness for the blackgoat-agentskills plugin.

.DESCRIPTION
    Runs headless `claude -p` invocations against frozen fixtures (contract suite)
    and/or checks skill-routing prompts (trigger suite), then appends pass/fail
    records to results/results.jsonl.

    Evals are statistical: a single run proves nothing. Read the pass RATE over N
    runs (see each case.md's Runs/Threshold section), not a single pass/fail.

    This script never spends a token unless -Confirm is passed. Without -Confirm it
    only prints the run plan and a rough, unmeasured cost estimate, then exits 0.

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no `&&`/`||`.

.PARAMETER Suite
    Which suite to run: 'trigger', 'contract', or 'all' (default).

.PARAMETER Case
    Optional: run only the named case - a contract folder name (e.g.
    'alex-plan-coverage') or a trigger line identifier (e.g. 'trigger-3').

.PARAMETER Runs
    Number of repetitions per case. Default 5, matching the 4/5 pass-threshold
    convention documented in each case.md.

.PARAMETER Confirm
    Required to actually spend tokens. Without it, prints the plan and exits 0.

.EXAMPLE
    # Dry run - prints plan + cost estimate, spends nothing.
    .\run-evals.ps1 -Suite contract

.EXAMPLE
    # Actually execute the alex-plan-coverage case 5 times.
    .\run-evals.ps1 -Suite contract -Case alex-plan-coverage -Confirm
#>
[CmdletBinding()]
param(
    [ValidateSet('trigger', 'contract', 'all')]
    [string]$Suite = 'all',

    [string]$Case,

    [int]$Runs = 5,

    [switch]$Confirm
)

$ErrorActionPreference = 'Stop'

$EvalsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ResultsPath = Join-Path $EvalsRoot 'results\results.jsonl'

# Rough, deliberately conservative per-run estimates. These are guesses, not
# measurements - once results.jsonl has real duration/outcome data, replace them.
$EstTokensPerContractRun = 20000
$EstTokensPerTriggerRun = 3000
$EstUsdPerThousandTokens = 0.01

function Get-ContractCaseCommand {
    param([Parameter(Mandatory = $true)][string]$CaseMdPath)

    $text = Get-Content -Path $CaseMdPath -Raw
    $pattern = '(?ms)^##\s*Command.*?```(?:powershell)?\s*(.*?)\s*```'
    $match = [regex]::Match($text, $pattern)
    if (-not $match.Success) {
        throw "No fenced powershell block found under '## Command' in $CaseMdPath"
    }
    return $match.Groups[1].Value.Trim()
}

function Get-ContractCaseDocsPath {
    param([Parameter(Mandatory = $true)][string]$CaseMdPath)

    $text = Get-Content -Path $CaseMdPath -Raw
    $match = [regex]::Match($text, '(?m)^-\s*Copies to:\s*`([^`]+)`')
    if (-not $match.Success) {
        throw "No '- Copies to: ``path``' line found in $CaseMdPath"
    }
    return $match.Groups[1].Value.Trim()
}

function Get-ContractCases {
    $contractRoot = Join-Path $EvalsRoot 'contract'
    if (-not (Test-Path $contractRoot)) { return @() }

    Get-ChildItem -Path $contractRoot -Directory | ForEach-Object {
        [PSCustomObject]@{
            Name        = $_.Name
            Type        = 'contract'
            CaseMd      = Join-Path $_.FullName 'case.md'
            GradeScript = Join-Path $_.FullName 'grade.ps1'
            FixtureDir  = Join-Path $_.FullName 'fixture'
        }
    }
}

function Get-TriggerCases {
    $triggerPath = Join-Path $EvalsRoot 'trigger\cases.jsonl'
    if (-not (Test-Path $triggerPath)) { return @() }

    $lineNumber = 0
    $results = @()
    foreach ($line in Get-Content -Path $triggerPath) {
        $lineNumber++
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $obj = $line | ConvertFrom-Json
        $results += [PSCustomObject]@{
            Name                   = "trigger-$lineNumber"
            Type                   = 'trigger'
            Prompt                 = $obj.prompt
            ExpectedSkill          = $obj.expected_skill
            AcceptableAlternatives = $obj.acceptable_alternatives
        }
    }
    return $results
}

$allCases = @()
if ($Suite -eq 'contract' -or $Suite -eq 'all') { $allCases += Get-ContractCases }
if ($Suite -eq 'trigger' -or $Suite -eq 'all') { $allCases += Get-TriggerCases }

if ($Case) {
    $allCases = @($allCases | Where-Object { $_.Name -eq $Case })
}

if (-not $allCases -or $allCases.Count -eq 0) {
    Write-Error "No matching cases for -Suite '$Suite' -Case '$Case'."
    exit 2
}

$totalRuns = 0
$estTokens = 0
foreach ($c in $allCases) {
    $totalRuns += $Runs
    if ($c.Type -eq 'contract') {
        $estTokens += ($Runs * $EstTokensPerContractRun)
    } else {
        $estTokens += ($Runs * $EstTokensPerTriggerRun)
    }
}
$estUsd = [math]::Round(($estTokens / 1000.0) * $EstUsdPerThousandTokens, 2)

Write-Output '=== Eval Run Plan ==='
Write-Output "Suite:            $Suite"
Write-Output "Cases:            $($allCases.Count)"
foreach ($c in $allCases) {
    Write-Output "  - $($c.Name) [$($c.Type)]"
}
Write-Output "Runs per case:    $Runs"
Write-Output "Total agent runs: $totalRuns"
Write-Output "Rough tokens:     ~$estTokens (very approximate, not measured)"
Write-Output "Rough cost (USD): ~`$$estUsd (very approximate, not measured)"
Write-Output ''

if (-not $Confirm) {
    Write-Output 'Dry run only - no tokens spent. Re-run with -Confirm to execute.'
    exit 0
}

Write-Output "Confirmed. Executing $totalRuns run(s)..."
Write-Output ''

$resultsDir = Split-Path -Parent $ResultsPath
if (-not (Test-Path $resultsDir)) {
    New-Item -ItemType Directory -Force -Path $resultsDir | Out-Null
}
if (-not (Test-Path $ResultsPath)) {
    New-Item -ItemType File -Path $ResultsPath | Out-Null
}

function Invoke-ContractRun {
    param($CaseInfo, [int]$RunIndex)

    $failedCriterion = $null
    $pass = $false
    $started = Get-Date
    $suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)
    $tempDir = Join-Path $env:TEMP "eval-$($CaseInfo.Name)-$RunIndex-$suffix"
    New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

    try {
        $docsRelPath = Get-ContractCaseDocsPath -CaseMdPath $CaseInfo.CaseMd
        $destination = Join-Path $tempDir $docsRelPath
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        Copy-Item -Path (Join-Path $CaseInfo.FixtureDir '*') -Destination $destination -Recurse -Force

        $command = Get-ContractCaseCommand -CaseMdPath $CaseInfo.CaseMd

        Push-Location $tempDir
        try {
            Invoke-Expression $command
        } finally {
            Pop-Location
        }

        $gradeOutput = & $CaseInfo.GradeScript -TargetDir $tempDir
        $gradeExit = $LASTEXITCODE
        foreach ($gradeLine in $gradeOutput) { Write-Output "    $gradeLine" }

        $pass = ($gradeExit -eq 0)
        if (-not $pass) {
            $failedLines = @($gradeOutput | Where-Object { $_ -match 'FAILED:' })
            if ($failedLines.Count -gt 0) {
                $failedCriterion = ($failedLines -join ' | ')
            } else {
                $failedCriterion = "grade.ps1 exited $gradeExit"
            }
        }
    } catch {
        $failedCriterion = "harness error: $($_.Exception.Message)"
    } finally {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    $duration = [math]::Round(((Get-Date) - $started).TotalSeconds, 2)
    return [PSCustomObject]@{
        timestamp        = (Get-Date).ToUniversalTime().ToString('o')
        case             = $CaseInfo.Name
        run_index        = $RunIndex
        pass             = $pass
        failed_criterion = $failedCriterion
        duration_s       = $duration
    }
}

function Invoke-TriggerRun {
    param($CaseInfo, [int]$RunIndex)

    $started = Get-Date
    $pass = $false
    $failedCriterion = $null

    try {
        # Read-only routing check: plan mode so no files are touched, we only care
        # which skill/persona the prompt surfaces in the transcript. This is a
        # best-effort textual match, not a verified introspection API - see README.
        $output = claude -p $CaseInfo.Prompt --permission-mode plan 2>&1 | Out-String

        $acceptable = @($CaseInfo.ExpectedSkill) + @($CaseInfo.AcceptableAlternatives)
        $matched = $false
        foreach ($skillName in $acceptable) {
            if ([string]::IsNullOrWhiteSpace($skillName)) { continue }
            if ($output -match [regex]::Escape($skillName)) {
                $matched = $true
                break
            }
        }
        $pass = $matched
        if (-not $pass) {
            $failedCriterion = "none of [$($acceptable -join ', ')] found in output"
        }
    } catch {
        $failedCriterion = "harness error: $($_.Exception.Message)"
    }

    $duration = [math]::Round(((Get-Date) - $started).TotalSeconds, 2)
    return [PSCustomObject]@{
        timestamp        = (Get-Date).ToUniversalTime().ToString('o')
        case             = $CaseInfo.Name
        run_index        = $RunIndex
        pass             = $pass
        failed_criterion = $failedCriterion
        duration_s       = $duration
    }
}

foreach ($caseInfo in $allCases) {
    Write-Output "--- $($caseInfo.Name) ---"
    for ($i = 1; $i -le $Runs; $i++) {
        Write-Output "  run $i/$Runs"
        if ($caseInfo.Type -eq 'contract') {
            $record = Invoke-ContractRun -CaseInfo $caseInfo -RunIndex $i
        } else {
            $record = Invoke-TriggerRun -CaseInfo $caseInfo -RunIndex $i
        }
        ($record | ConvertTo-Json -Compress) | Add-Content -Path $ResultsPath
    }
}

Write-Output ''
Write-Output "Done. Results appended to $ResultsPath"
