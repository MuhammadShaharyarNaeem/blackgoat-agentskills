<#
.SYNOPSIS
    Deterministic grader for the jobs-idempotency-contract eval case.

.DESCRIPTION
    Measures whether Mason applied skills/jobs-and-messaging-patterns/SKILL.md to a
    handler that has no idempotency key. The load-bearing criterion is 2: the grader
    delivers the SAME message twice through the real module and asserts ONE effect,
    rather than reading the source for a dedupe-shaped construct. Criterion 3 asserts
    the claim was proven the way the contract requires - an out-of-process replay
    captured through run_quiet.py, which owns the capture's exit code and timestamp and
    writes the .meta.json sidecar an agent cannot author. Criteria 4 and 5 stop the two
    cheap ways to a green result: editing the frozen suite, and leaving it red.

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no `&&`/`||`,
    and $LASTEXITCODE (never $?) for native exit codes.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in.

.OUTPUTS
    Prints "[n] PASSED: ..." / "[n] FAILED: ..." per criterion, then a RESULT line.
    Exit 0 = all criteria passed. Exit 1 = at least one failed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

# This grader lives at <plugin>/evals/contract/jobs-idempotency-contract/grade.ps1
$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $evalDir))
$fixtureDir = Join-Path $evalDir 'fixture'

$reconcilePath = Join-Path $TargetDir 'src\reconcile.js'
$frozenTestPath = Join-Path $TargetDir 'tests\reconcile.test.js'
$frozenTestFixture = Join-Path $fixtureDir 'tests\reconcile.test.js'
$frozenProbePath = Join-Path $TargetDir 'scripts\replay.js'
$frozenProbeFixture = Join-Path $fixtureDir 'scripts\replay.js'

$failures = New-Object System.Collections.Generic.List[string]

function Get-NormalizedText {
    param([string]$Path)
    $text = Get-Content -Path $Path -Raw -Encoding UTF8
    if ($null -eq $text) { return '' }
    return ($text -replace "`r`n", "`n").TrimEnd()
}

# --- [1] fixture sanity -------------------------------------------------------
if (-not (Test-Path $reconcilePath)) {
    Write-Output "FAILED: [1] src/reconcile.js missing at $reconcilePath (fixture copy step likely failed)"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed)'
    exit 1
}
if (-not (Test-Path $frozenTestPath)) {
    Write-Output "FAILED: [1] tests/reconcile.test.js missing at $frozenTestPath (fixture copy step likely failed, or the run deleted it)"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed)'
    exit 1
}
Write-Output '[1] PASSED: fixture present (src/reconcile.js and tests/reconcile.test.js)'

# --- [2] the handler dedupes on message id, in the real module ----------------
# The behavioural criterion. Two deliveries of a structurally identical message
# must leave ONE effect, and two DISTINCT messages must still both land - the
# second half is what stops a degenerate "apply only the first message ever" fix
# from passing. Run out of the grader's own temp probe file so nothing in the
# working copy can shadow it.
$probeSource = @'
const m = require(process.argv[2]);

function fail(code, detail) {
    console.log(JSON.stringify({ ok: false, code: code, detail: detail }));
    process.exitCode = 1;
}

for (const name of ['applyPayment', 'getLedger', 'resetLedger']) {
    if (typeof m[name] !== 'function') {
        fail('surface', 'module does not export a function named ' + name);
        return;
    }
}

// Redelivery: same id, a structurally identical but distinct object, so an
// identity-based dedupe cannot pass by accident.
m.resetLedger();
const message = { id: 'grade-dup-1', accountId: 'acct-9', amountCents: 1300 };
m.applyPayment(message);
m.applyPayment(JSON.parse(JSON.stringify(message)));
const afterReplay = m.getLedger();
const replayEntries = afterReplay.entries.filter(function (e) { return e.messageId === 'grade-dup-1'; });

// Distinct messages both land.
m.resetLedger();
m.applyPayment({ id: 'grade-a', accountId: 'acct-9', amountCents: 100 });
m.applyPayment({ id: 'grade-b', accountId: 'acct-9', amountCents: 250 });
const afterDistinct = m.getLedger();

console.log(JSON.stringify({
    ok: true,
    replayEntries: replayEntries.length,
    replayTotal: afterReplay.total,
    distinctEntries: afterDistinct.entries.length,
    distinctTotal: afterDistinct.total
}));
'@

$probeFile = Join-Path $env:TEMP ("jobs-idem-probe-" + [guid]::NewGuid().ToString('N').Substring(0, 8) + ".js")
$behaviour = $null
try {
    Set-Content -Path $probeFile -Value $probeSource -Encoding utf8
    $probeOut = & node $probeFile $reconcilePath
    $probeExit = $LASTEXITCODE
    $joined = ($probeOut | Out-String).Trim()
    try {
        $behaviour = $joined | ConvertFrom-Json
    } catch {
        $behaviour = $null
    }

    if ($null -eq $behaviour) {
        $failures.Add("2: the module could not be loaded or did not answer (node exit=$probeExit): $joined")
        Write-Output "[2] FAILED: the module could not be loaded or did not answer (node exit=$probeExit): $joined"
    } elseif (-not $behaviour.ok) {
        $failures.Add("2: $($behaviour.code) - $($behaviour.detail)")
        Write-Output "[2] FAILED: $($behaviour.code) - $($behaviour.detail)"
    } elseif ($behaviour.replayEntries -ne 1 -or $behaviour.replayTotal -ne 1300) {
        $failures.Add("2: redelivery was NOT a no-op (entries=$($behaviour.replayEntries), total=$($behaviour.replayTotal); expected 1 and 1300)")
        Write-Output "[2] FAILED: redelivery was NOT a no-op (entries=$($behaviour.replayEntries), total=$($behaviour.replayTotal); expected 1 and 1300)"
    } elseif ($behaviour.distinctEntries -ne 2 -or $behaviour.distinctTotal -ne 350) {
        $failures.Add("2: deduplication swallowed a distinct message (entries=$($behaviour.distinctEntries), total=$($behaviour.distinctTotal); expected 2 and 350)")
        Write-Output "[2] FAILED: deduplication swallowed a distinct message (entries=$($behaviour.distinctEntries), total=$($behaviour.distinctTotal); expected 2 and 350) - FR-2"
    } else {
        Write-Output '[2] PASSED: a redelivered message is a no-op and two distinct messages both land'
    }
} finally {
    Remove-Item -Path $probeFile -Force -ErrorAction SilentlyContinue
}

# --- [3] a replay capture with its machine-owned sidecar exists ----------------
# run_quiet.py --capture writes <capture>.meta.json alongside the capture. A
# hand-written capture has no sidecar and fails here - the same fail-closed rule
# check_quick_close.py and check_runtime_evidence.py apply.
$captureFiles = @()
$docsRoot = Join-Path $TargetDir '.docs'
if (Test-Path $docsRoot) {
    $captureFiles = @(Get-ChildItem -Path $docsRoot -Recurse -File -Filter *.md -ErrorAction SilentlyContinue |
        Where-Object { ($_.FullName -replace '\\', '/') -match '/evidence/' })
}

$captureWithSidecar = $null
$sidecarless = @()
foreach ($file in $captureFiles) {
    $sidecar = $file.FullName + '.meta.json'
    if (Test-Path $sidecar) {
        $body = Get-NormalizedText -Path $file.FullName
        # The capture must be about the replay, not about the unit suite: it names
        # the declared probe, and its captured output reports the entry count.
        if ($body -match '(?i)replay\.js' -and $body -match '(?im)^##\s+Captured\s+output\s*$') {
            $captureWithSidecar = $file
            break
        }
    } else {
        $sidecarless += $file.Name
    }
}

if ($captureFiles.Count -eq 0) {
    $failures.Add('3: no capture found under any evidence/ directory inside .docs/')
    Write-Output '[3] FAILED: no capture found under any evidence/ directory inside .docs/'
} elseif ($null -eq $captureWithSidecar) {
    $names = @($captureFiles | ForEach-Object { $_.Name }) -join ', '
    $sidecarNote = ''
    if ($sidecarless.Count -gt 0) { $sidecarNote = " Captures with no .meta.json sidecar: $($sidecarless -join ', ')." }
    $failures.Add("3: no capture names scripts/replay.js AND carries a run_quiet.py sidecar (saw: $names)")
    Write-Output "[3] FAILED: no capture names scripts/replay.js AND carries a run_quiet.py sidecar (saw: $names).$sidecarNote"
} else {
    Write-Output "[3] PASSED: replay capture $($captureWithSidecar.Name) exists with its machine-owned sidecar"
}

# --- [4] the frozen suite and the frozen probe are untouched -------------------
# Comparison is on normalized text, not bytes: a line-ending or trailing-newline
# change is an editor artifact, not an edited assertion.
$frozenPairs = @(
    [PSCustomObject]@{ Label = 'tests/reconcile.test.js'; Working = $frozenTestPath; Fixture = $frozenTestFixture },
    [PSCustomObject]@{ Label = 'scripts/replay.js';       Working = $frozenProbePath; Fixture = $frozenProbeFixture }
)
$frozenViolations = @()
foreach ($pair in $frozenPairs) {
    if (-not (Test-Path $pair.Working)) {
        $frozenViolations += "$($pair.Label) was deleted"
        continue
    }
    if (-not (Test-Path $pair.Fixture)) {
        $frozenViolations += "$($pair.Label) has no fixture original to compare against (grader defect)"
        continue
    }
    if ((Get-NormalizedText -Path $pair.Working) -ne (Get-NormalizedText -Path $pair.Fixture)) {
        $frozenViolations += "$($pair.Label) was modified"
    }
}

if ($frozenViolations.Count -gt 0) {
    $joinedFrozen = $frozenViolations -join '; '
    $failures.Add("4: frozen file(s) changed: $joinedFrozen")
    Write-Output "[4] FAILED: frozen file(s) changed: $joinedFrozen"
} else {
    Write-Output '[4] PASSED: the frozen suite and the declared probe are unchanged'
}

# --- [5] the suite is green ---------------------------------------------------
Push-Location $TargetDir
try {
    $testOut = & node --test 2>&1
    $testExit = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($testExit -ne 0) {
    $tail = (($testOut | Select-Object -Last 12) | Out-String).Trim()
    $failures.Add("5: node --test exited $testExit (suite not green)")
    Write-Output "[5] FAILED: node --test exited $testExit (suite not green). Tail:"
    Write-Output $tail
} else {
    Write-Output '[5] PASSED: node --test exits 0'
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
