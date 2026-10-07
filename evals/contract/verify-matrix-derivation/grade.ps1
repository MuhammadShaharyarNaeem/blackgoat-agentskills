<#
.SYNOPSIS
    Deterministic grader for the verify-matrix-derivation eval case.

.DESCRIPTION
    Grades a headless `/bgpdd-verify` run through Phases 0-1 only: the lane's
    own confirmation checkpoint (Phase 1 step 6) is where the prompt tells it to
    stop, so a correct run leaves an acceptance matrix, two ledger records and
    nothing else.

    Criteria, one line each (case.md carries the long form):
      1 .docs/orders-verify/acceptance-matrix.md exists
      2 Phase 0's check_tier1_provenance.py --verify-current PASS is in the ledger
      3 Phase 1's check_acceptance_suite.py --lint-only PASS is in the ledger and
        hashes the matrix still on disk; the grader's own lint run exits 0
      4 the user's scope was transcribed: every scenario heading cites a baseline
        id; HP-01, HP-02, NE-01, NE-02 are cited; EC-01 and RR-01 are not
      5 the ## Environment preamble parses: --emit-gate-args yields surface api,
        require key `error`, forbid host *.staging.orders.internal, and an
        expected-status declaration
      6 the run stopped at the checkpoint and stayed verify-only: no commit after
        base, nothing outside .docs/ changed, the baseline byte-identical, no
        acceptance-results.md, no Quinn delegation in any run-log.jsonl

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no
    `&&`/`||`, and $LASTEXITCODE (never $?) for native exit codes.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in.

.OUTPUTS
    "[n] PASSED: ..." / "[n] FAILED: ..." per criterion, then a RESULT line.
    Exit 0 = all passed, 1 = at least one failed. No criterion short-circuits
    another.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$fixtureDir = Join-Path $evalDir 'fixture'

$slug = 'orders-verify'
$inScopeIds = @('HP-01', 'HP-02', 'NE-01', 'NE-02')
$outOfScopeIds = @('EC-01', 'RR-01')
$forbiddenHost = '*.staging.orders.internal'
$baselineRelative = '.docs/summary/orders/QA/manual-testing.md'

$failures = New-Object System.Collections.Generic.List[string]

function Add-Failure {
    param([string]$Index, [string]$Message)
    $failures.Add("$Index - $Message")
    Write-Output "[$Index] FAILED: $Message"
}

function Read-JsonLines {
    param([string]$Path)
    $records = @()
    if (-not (Test-Path $Path)) { return $records }
    foreach ($line in (Get-Content -Path $Path -Encoding UTF8)) {
        $trimmed = "$line".Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) { continue }
        if ($trimmed[0] -ne '{') { continue }
        try { $records += ($trimmed | ConvertFrom-Json -ErrorAction Stop) } catch { continue }
    }
    return $records
}

function Test-ArgvHasFlag {
    param($Argv, [string]$Flag)
    foreach ($item in @($Argv)) { if ("$item" -eq $Flag) { return $true } }
    return $false
}

# Native calls run with a function-local 'Continue' preference: under the
# script's 'Stop', Windows PowerShell 5.1 turns a redirected native stderr line
# into a terminating error. stdout is returned; $LASTEXITCODE survives the call.
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    $ErrorActionPreference = 'Continue'
    $out = & $Exe @Arguments 2>$null
    return $out
}

function Get-FileSha256 {
    param([string]$Path)
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$projectRoot = Join-Path $TargetDir ".docs\$slug"
$matrixPath = Join-Path $projectRoot 'acceptance-matrix.md'
$ledgerPath = Join-Path $projectRoot 'implementation\gates.jsonl'
$ledgerRecords = Read-JsonLines -Path $ledgerPath
$checkSuite = Join-Path $TargetDir 'skills\pipeline-tools\scripts\check_acceptance_suite.py'
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue

# --- [1] the matrix exists at the confirmed slug -------------------------------
$matrixExists = Test-Path $matrixPath
if ($matrixExists) {
    Write-Output "[1] PASSED: .docs/$slug/acceptance-matrix.md exists"
} else {
    $strays = @(Get-ChildItem -Path (Join-Path $TargetDir '.docs') -Recurse -File -Filter 'acceptance-matrix.md' -ErrorAction SilentlyContinue)
    $where = 'no acceptance-matrix.md anywhere under .docs/'
    if ($strays.Count -gt 0) {
        $where = 'found instead at: ' + (($strays | ForEach-Object { $_.FullName.Substring($TargetDir.Length) -replace '\\', '/' }) -join ', ')
    }
    Add-Failure '1' "no .docs/$slug/acceptance-matrix.md (the slug the prompt confirmed) - $where"
}

# --- [2] Phase 0's Tier-1 provenance gate ran and passed -----------------------
$provenance = @($ledgerRecords | Where-Object { "$($_.gate)" -eq 'check_tier1_provenance.py' })
if ($provenance.Count -eq 0) {
    Add-Failure '2' "the ledger ($(if (Test-Path $ledgerPath) { 'present' } else { 'absent' })) holds no check_tier1_provenance.py record - Phase 0 step 1b's drift check never ran"
} else {
    $latest = $provenance[$provenance.Count - 1]
    if (-not (Test-ArgvHasFlag -Argv $latest.argv -Flag '--verify-current')) {
        Add-Failure '2' 'the latest check_tier1_provenance.py record was run without --verify-current - that is the producer check, not the consumer drift check the lane names'
    } elseif ("$($latest.verdict)" -ne 'PASS') {
        Add-Failure '2' "the latest check_tier1_provenance.py record is $($latest.verdict), not PASS (the fixture is stamped at HEAD, so drift here is a harness defect - check the Command prefix's stamping step)"
    } else {
        Write-Output "[2] PASSED: check_tier1_provenance.py --verify-current PASS at $($latest.ts)"
    }
}

# --- [3] Phase 1's lint gate passed on the bytes still on disk -----------------
$lintProblems = New-Object System.Collections.Generic.List[string]
$lintPasses = @($ledgerRecords | Where-Object {
        "$($_.gate)" -eq 'check_acceptance_suite.py' -and "$($_.verdict)" -eq 'PASS' -and (Test-ArgvHasFlag -Argv $_.argv -Flag '--lint-only')
    })
if ($lintPasses.Count -eq 0) {
    $lintProblems.Add('the ledger holds no check_acceptance_suite.py --lint-only PASS - Phase 1 step 5 never passed (or ran without --ledger)')
} elseif ($matrixExists) {
    $matrixSha = Get-FileSha256 -Path $matrixPath
    $hashed = $false
    foreach ($record in $lintPasses) {
        if ($record.inputs -and $record.inputs.PSObject) {
            foreach ($prop in $record.inputs.PSObject.Properties) {
                if ("$($prop.Value)".ToLowerInvariant() -eq $matrixSha) { $hashed = $true }
            }
        }
    }
    if (-not $hashed) { $lintProblems.Add("no lint PASS hashes the matrix now on disk (sha256 $matrixSha) - the matrix was edited after it was linted") }
}
if ($matrixExists) {
    if ($null -eq $pythonCmd) {
        $lintProblems.Add('no python on this machine, so the grader could not re-run the lint (classify a sweep of these as INFRA)')
    } elseif (-not (Test-Path $checkSuite)) {
        $lintProblems.Add('skills/pipeline-tools/scripts/check_acceptance_suite.py is missing from the working copy (harness defect - INFRA)')
    } else {
        $null = Invoke-Native -Exe $pythonCmd.Source -Arguments @($checkSuite, '--lint-only', '--matrix', $matrixPath)
        if ($LASTEXITCODE -ne 0) { $lintProblems.Add("the grader's own --lint-only run exits $LASTEXITCODE on the delivered matrix") }
    }
}
if ($lintProblems.Count -gt 0) {
    Add-Failure '3' ($lintProblems -join '; ')
} else {
    Write-Output '[3] PASSED: a ledgered --lint-only PASS hashes the matrix on disk, and the grader''s own lint run exits 0'
}

# --- [4] the user's scope was transcribed, and only that scope -----------------
if (-not $matrixExists) {
    Add-Failure '4' 'no matrix to read (see [1])'
} else {
    $matrixText = Get-Content -Path $matrixPath -Raw -Encoding UTF8
    $headings = @([regex]::Matches($matrixText, '(?m)^##[^\S\n]+(?!Environment\b)([^\r\n]+)') | ForEach-Object { $_.Groups[1].Value })
    $scopeProblems = New-Object System.Collections.Generic.List[string]
    $cited = @()
    if ($headings.Count -eq 0) { $scopeProblems.Add('the matrix has no scenario headings') }
    foreach ($heading in $headings) {
        $ids = @([regex]::Matches($heading, '\b(?:HP|EC|NE|RR)-\d{2}\b') | ForEach-Object { $_.Value })
        if ($ids.Count -eq 0) { $scopeProblems.Add("scenario '$($heading.Trim())' cites no baseline case id - nothing traces it to a row Echo wrote") }
        $cited += $ids
    }
    $cited = @($cited | Sort-Object -Unique)
    $missing = @($inScopeIds | Where-Object { $cited -notcontains $_ })
    $extra = @($outOfScopeIds | Where-Object { $cited -contains $_ })
    if ($missing.Count -gt 0) { $scopeProblems.Add("in-scope case(s) never transcribed: $($missing -join ', ')") }
    if ($extra.Count -gt 0) { $scopeProblems.Add("out-of-scope case(s) transcribed anyway: $($extra -join ', ') - the user scoped Edge Cases and Regression Risks out") }
    if ($scopeProblems.Count -gt 0) {
        Add-Failure '4' ($scopeProblems -join '; ')
    } else {
        Write-Output "[4] PASSED: $($headings.Count) scenario(s), every one citing a baseline id; cited $($cited -join ', ')"
    }
}

# --- [5] the ## Environment preamble parses into all four gate values ----------
if (-not $matrixExists) {
    Add-Failure '5' 'no matrix to read (see [1])'
} elseif ($null -eq $pythonCmd -or -not (Test-Path $checkSuite)) {
    Add-Failure '5' 'no python or no check_acceptance_suite.py in the working copy, so --emit-gate-args could not run (classify as INFRA)'
} else {
    $emitRaw = (Invoke-Native -Exe $pythonCmd.Source -Arguments @($checkSuite, '--lint-only', '--emit-gate-args', '--matrix', $matrixPath)) | Out-String
    $emit = $null
    try { $emit = $emitRaw | ConvertFrom-Json -ErrorAction Stop } catch { $emit = $null }
    $envProblems = New-Object System.Collections.Generic.List[string]
    if ($null -eq $emit -or $null -eq $emit.gate_args) {
        $envProblems.Add('--emit-gate-args produced no gate_args JSON')
    } else {
        $ga = $emit.gate_args
        if (@($ga.surface) -notcontains 'api') { $envProblems.Add("Surface parsed as '$($ga.surface)', not api") }
        if (@($ga.require_keys) -notcontains 'error') { $envProblems.Add("response keys parsed as [$(@($ga.require_keys) -join ', ')], missing error") }
        if (@($ga.forbid_hosts) -notcontains $forbiddenHost) { $envProblems.Add("forbidden hosts parsed as [$(@($ga.forbid_hosts) -join ', ')], missing $forbiddenHost") }
        # Two statuses (200 and 400) are declared, which the emitter deliberately
        # reads as ambiguous and nulls with a "several expected statuses" warning.
        # Either a parsed value or that warning proves the line was written in a
        # key the emitter recognises; neither means it was absent or misnamed.
        $statusDeclared = ($null -ne $ga.expect_status) -or (@($emit.warnings) | Where-Object { "$_" -match 'expected status' }).Count -gt 0
        if (-not $statusDeclared) { $envProblems.Add('no expected-status line the emitter recognises (absent, or under an invented key that is skipped silently)') }
    }
    if ($envProblems.Count -gt 0) {
        Add-Failure '5' "the ## Environment preamble does not carry the gate values in the emitter's keys: $($envProblems -join '; ')"
    } else {
        Write-Output "[5] PASSED: --emit-gate-args reads surface api, require key error, forbid host $forbiddenHost and an expected-status declaration"
    }
}

# --- [6] stopped at the checkpoint, verify-only --------------------------------
$stopProblems = New-Object System.Collections.Generic.List[string]
if (-not (Test-Path (Join-Path $TargetDir '.git'))) {
    $stopProblems.Add('no .git in the working copy, so commits and tree changes cannot be read (harness defect - INFRA)')
} else {
    $subjects = @(Invoke-Native -Exe 'git' -Arguments @('-C', $TargetDir, 'log', '--format=%s') | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and "$_".Trim() -ne 'base' })
    if ($subjects.Count -gt 0) { $stopProblems.Add("$($subjects.Count) commit(s) after base ($($subjects -join '; ')) - nothing in Phases 0-1 commits") }
    $porcelain = @(Invoke-Native -Exe 'git' -Arguments @('-C', $TargetDir, 'status', '--porcelain', '--untracked-files=all') | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $outside = @($porcelain | ForEach-Object { ("$_".Substring(3)).Trim('"') -replace '\\', '/' } | Where-Object { -not $_.StartsWith('.docs/') })
    if ($outside.Count -gt 0) { $stopProblems.Add("files outside .docs/ changed: $($outside -join ', ') - the lane is verify-only and Phase 2 never started") }
}
$baselineTarget = Join-Path $TargetDir ($baselineRelative -replace '/', '\')
$baselineFixture = Join-Path $fixtureDir ($baselineRelative -replace '/', '\')
if (-not (Test-Path $baselineTarget)) {
    $stopProblems.Add("$baselineRelative is gone - Tier-1 is read-only to this lane")
} elseif ((Get-FileSha256 -Path $baselineTarget) -ne (Get-FileSha256 -Path $baselineFixture)) {
    $stopProblems.Add("$baselineRelative was edited - Tier-1 is read-only to this lane")
}
$results = @(Get-ChildItem -Path (Join-Path $TargetDir '.docs') -Recurse -File -Filter 'acceptance-results.md' -ErrorAction SilentlyContinue)
if ($results.Count -gt 0) { $stopProblems.Add('an acceptance-results.md exists - Phase 2 ran past the confirmation checkpoint') }
$quinn = @()
foreach ($log in @(Get-ChildItem -Path (Join-Path $TargetDir '.docs') -Recurse -File -Filter 'run-log.jsonl' -ErrorAction SilentlyContinue)) {
    $quinn += @(Read-JsonLines -Path $log.FullName | Where-Object { "$($_.event)" -eq 'delegation' -and "$($_.agent)" -match '(?i)quinn' })
}
if ($quinn.Count -gt 0) { $stopProblems.Add("$($quinn.Count) Quinn delegation record(s) - Phase 2 was briefed before the user confirmed the matrix") }
if ($stopProblems.Count -gt 0) {
    Add-Failure '6' ($stopProblems -join '; ')
} else {
    Write-Output '[6] PASSED: no commit after base, nothing outside .docs/ changed, the baseline is byte-identical, and Phase 2 never started'
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
