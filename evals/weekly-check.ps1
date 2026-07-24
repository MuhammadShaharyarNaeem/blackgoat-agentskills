<#
.SYNOPSIS
    Zero-token change detector for the blackgoat-agentskills eval suite.

.DESCRIPTION
    Looks at what changed in agents/ and skills/ since the last eval run (or a
    reasonable fallback), maps those changes to the evals they affect, and prints the
    run-evals.ps1 command to run them. Never invokes run-evals.ps1 itself and never
    spends a token - this script only reads files and (if available) git.

    Detection strategy, in order of preference:
      1. If the plugin dir is a git repo: diff agents/ and skills/ since the newest
         timestamp found in results/results.jsonl.
      2. If it is a git repo but results.jsonl has no entries yet: diff since 7 days ago.
      3. If it is not a git repo: fall back to file LastWriteTime, same two windows.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$EvalsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PluginRoot = Split-Path -Parent $EvalsRoot
$ResultsPath = Join-Path $EvalsRoot 'results\results.jsonl'
$DefaultRuns = 5

function Get-LastEvalTimestamp {
    if (-not (Test-Path $ResultsPath)) { return $null }
    $lines = Get-Content -Path $ResultsPath | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    if (-not $lines) { return $null }

    $latest = $null
    foreach ($line in $lines) {
        try {
            $record = $line | ConvertFrom-Json
            $ts = [datetime]$record.timestamp
            if (-not $latest -or $ts -gt $latest) { $latest = $ts }
        } catch {
            continue
        }
    }
    return $latest
}

function Test-IsGitRepo {
    param([string]$Path)
    $isRepo = $false
    Push-Location $Path
    try {
        $null = git rev-parse --is-inside-work-tree 2>&1
        $isRepo = ($LASTEXITCODE -eq 0)
    } catch {
        $isRepo = $false
    } finally {
        Pop-Location
    }
    return $isRepo
}

$lastEvalTime = Get-LastEvalTimestamp
$isGitRepo = Test-IsGitRepo -Path $PluginRoot

$changedFiles = @()
$detectionMethod = $null

if ($isGitRepo) {
    Push-Location $PluginRoot
    try {
        if ($lastEvalTime) {
            $sinceArg = $lastEvalTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
            $detectionMethod = "git diff since last eval run ($sinceArg)"
        } else {
            $sinceArg = '7 days ago'
            $detectionMethod = 'git diff since 7 days ago (no prior results.jsonl entries)'
        }
        $gitOutput = git log "--since=$sinceArg" --name-only --pretty=format: -- agents/ skills/ 2>&1
        $changedFiles = @($gitOutput | Where-Object { $_ -and $_.Trim() -ne '' } | Sort-Object -Unique)
    } finally {
        Pop-Location
    }
} else {
    $cutoff = $lastEvalTime
    if (-not $cutoff) { $cutoff = (Get-Date).AddDays(-7) }
    $detectionMethod = "file LastWriteTime since $($cutoff.ToString('u')) (not a git repo)"

    $agentsPath = Join-Path $PluginRoot 'agents'
    $skillsPath = Join-Path $PluginRoot 'skills'
    $changedFiles = @()
    foreach ($root in @($agentsPath, $skillsPath)) {
        if (Test-Path $root) {
            $changedFiles += Get-ChildItem -Path $root -Recurse -File |
                Where-Object { $_.LastWriteTime -gt $cutoff } |
                ForEach-Object { $_.FullName.Substring($PluginRoot.Length + 1).Replace('\', '/') }
        }
    }
}

Write-Output '=== Weekly Change Check ==='
Write-Output "Detection method: $detectionMethod"
Write-Output ''

if (-not $changedFiles -or $changedFiles.Count -eq 0) {
    Write-Output 'No changes detected in agents/ or skills/. Nothing to run.'
    exit 0
}

Write-Output 'Changed files:'
foreach ($f in $changedFiles) { Write-Output "  - $f" }
Write-Output ''

$affectedEvals = New-Object System.Collections.Generic.HashSet[string]

foreach ($f in $changedFiles) {
    if ($f -match 'agents/rex\.md$') {
        [void]$affectedEvals.Add('contract:rex-requirements-shape')
    }
    if ($f -match 'agents/alex\.md$' -or $f -match 'skills/planning-and-task-breakdown/') {
        [void]$affectedEvals.Add('contract:alex-plan-coverage')
    }
    if ($f -match 'agents/quinn\.md$' -or $f -match 'skills/test-driven-development/' -or $f -match 'skills/debugging-and-error-recovery/') {
        [void]$affectedEvals.Add('contract:quinn-test-report-shape')
    }
    if ($f -match 'agents/echo\.md$' -or $f -match 'skills/bgpdd-discovery/') {
        [void]$affectedEvals.Add('contract:echo-qa-discovery-shape')
    }
    if ($f -match 'agents/vera\.md$' -or $f -match 'skills/shipping-and-launch/') {
        [void]$affectedEvals.Add('contract:vera-verification-shape')
    }
    if ($f -match 'SKILL\.md$') {
        # Any SKILL.md's frontmatter `description` is what drives skill routing.
        [void]$affectedEvals.Add('trigger')
    }
}

if ($affectedEvals.Count -eq 0) {
    Write-Output 'Changed files did not match any known eval mapping. No evals flagged - review manually if that seems wrong.'
    exit 0
}

Write-Output 'Affected evals:'
foreach ($e in $affectedEvals) { Write-Output "  - $e" }
Write-Output ''

$contractCount = @($affectedEvals | Where-Object { $_ -like 'contract:*' }).Count
$triggerFlagged = $affectedEvals.Contains('trigger')

$estRuns = ($contractCount * $DefaultRuns)
if ($triggerFlagged) {
    $triggerLinesPath = Join-Path $EvalsRoot 'trigger\cases.jsonl'
    $triggerLineCount = 0
    if (Test-Path $triggerLinesPath) {
        $triggerLineCount = @(Get-Content -Path $triggerLinesPath | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count
    }
    $estRuns += ($triggerLineCount * $DefaultRuns)
}

Write-Output "Estimated runs (at -Runs $DefaultRuns): ~$estRuns"
Write-Output 'Estimated cost: rough only - run-evals.ps1 without -Confirm for a live dry-run estimate.'
Write-Output ''

$suiteArg = 'all'
if ($contractCount -gt 0 -and -not $triggerFlagged) { $suiteArg = 'contract' }
if ($triggerFlagged -and $contractCount -eq 0) { $suiteArg = 'trigger' }

Write-Output 'To actually run these evals (spends tokens), first dry-run:'
Write-Output "  powershell -File `"$EvalsRoot\run-evals.ps1`" -Suite $suiteArg -Runs $DefaultRuns"
Write-Output 'Then, after reviewing the plan, approve with -Confirm:'
Write-Output "  powershell -File `"$EvalsRoot\run-evals.ps1`" -Suite $suiteArg -Runs $DefaultRuns -Confirm"
