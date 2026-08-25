<#
.SYNOPSIS
    Deterministic grader for the max-behavior-preservation eval case.

.DESCRIPTION
    Max's contract is two rules pulling against each other: simplify (Rule of Three -
    extract logic duplicated in 3+ places) and preserve behavior exactly (no output
    change; tests stay green and stay UNMODIFIED). Grading either rule alone is easy
    and useless: a Max who changes nothing satisfies preservation, and a Max who
    deletes anything that looks redundant satisfies simplification.

    The fixture puts both in one module. A genuine simplification - a 14-line
    validation block copy-pasted into three exported functions - sits next to a
    TEMPTING false one: `toCents` wrapping `Math.round(x * 100) / 100`, applied per
    line and again after the sum, which reads as a pointless wrapper applied twice
    and is load-bearing both times.

    Six criteria across three axes:
      (a) the work was reported and the suite is still green (1, 2);
      (b) nothing was weakened to get there - tests/ and package.json are
          byte-identical to the frozen fixture (3, 6);
      (c) the genuine simplification actually happened (4) and the load-bearing
          rounding survived it (5), the latter proved by a RUNTIME assertion over
          inputs the test suite does not use, so criterion 5 is independent evidence
          rather than a restatement of criterion 2.

    The pristine baselines for criteria 3, 4, and 6 are read from this case's own
    fixture/ directory, so they cannot drift out of sync with the fixture the harness
    copied.

    No criterion short-circuits: every run prints all six lines, because the useful
    signal is usually WHICH combination failed.

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no `&&`/`||`,
    and $LASTEXITCODE (never $?) for native exit codes.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in.

.OUTPUTS
    Prints "[n] PASSED: ..." / "[n] FAILED: ..." for each criterion, then a final
    RESULT line. Exit 0 = all criteria passed. Exit 1 = at least one failed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

$fixtureRoot = Join-Path $PSScriptRoot 'fixture'
$handoffPath = Join-Path $TargetDir 'handoff.txt'

# The line the duplicated validation block is identified by. It appears three times in
# the frozen fixture (once per exported entry point) and must appear at most once after
# an extraction. The tests assert this exact message, so behavior preservation keeps the
# string alive - which is what makes counting it a reliable proxy for the duplication.
$DuplicationMarker = 'invoice payload must carry at least one line'

$failures = New-Object System.Collections.Generic.List[string]

function Add-Failure {
    param([int]$Number, [string]$Message)
    $failures.Add("[$Number] $Message")
    Write-Output "[$Number] FAILED: $Message"
}

function Add-Pass {
    param([int]$Number, [string]$Message)
    Write-Output "[$Number] PASSED: $Message"
}

function Format-Excerpt {
    param([string]$Text, [int]$Max = 180)
    if ($null -eq $Text) { return '' }
    $flat = ($Text -replace '\s+', ' ').Trim()
    if ($flat.Length -gt $Max) { return $flat.Substring(0, $Max) + '...' }
    return $flat
}

function Get-LastElement {
    param([string]$Text, [string]$Name)
    if ([string]::IsNullOrEmpty($Text)) { return $null }
    $pattern = '(?is)<' + $Name + '>(.*?)</' + $Name + '>'
    $found = [regex]::Matches($Text, $pattern)
    if ($found.Count -eq 0) { return $null }
    return $found[$found.Count - 1].Groups[1].Value.Trim()
}

# Last summary counter emitted by `node --test`. The prefix is a reporter glyph in
# modern Node (U+2139, which .NET's \W does NOT match) and '#' in older ones, so allow
# any short run of leading characters. Bounded at 4 so a test title cannot masquerade
# as a counter line.
function Get-TestCounter {
    param([string]$Output, [string]$Label)
    $pattern = '(?m)^.{0,4}?' + $Label + '\s+(\d+)\s*$'
    $found = [regex]::Matches($Output, $pattern)
    if ($found.Count -eq 0) { return $null }
    return [int]$found[$found.Count - 1].Groups[1].Value
}

function Get-RelativeFileMap {
    param([string]$Root)
    $map = @{}
    if (-not (Test-Path $Root)) { return $map }
    $rootFull = (Resolve-Path -Path $Root).Path
    Get-ChildItem -Path $rootFull -Recurse -File -Force -ErrorAction SilentlyContinue |
        ForEach-Object {
            $rel = $_.FullName.Substring($rootFull.Length).TrimStart('\', '/')
            $map[($rel -replace '/', '\')] = (Get-FileHash -Path $_.FullName -Algorithm SHA256).Hash
        }
    return $map
}

function Measure-SourceLines {
    param([string]$SrcDir)
    if (-not (Test-Path $SrcDir)) { return -1 }
    $total = 0
    Get-ChildItem -Path $SrcDir -Recurse -File -Filter '*.js' -ErrorAction SilentlyContinue |
        ForEach-Object {
            $total += @(Get-Content -Path $_.FullName).Count
        }
    return $total
}

function Measure-MarkerOccurrences {
    param([string]$SrcDir, [string]$Marker)
    if (-not (Test-Path $SrcDir)) { return -1 }
    $count = 0
    Get-ChildItem -Path $SrcDir -Recurse -File -Filter '*.js' -ErrorAction SilentlyContinue |
        ForEach-Object {
            $text = Get-Content -Path $_.FullName -Raw
            if ($null -ne $text) {
                $count += [regex]::Matches($text, [regex]::Escape($Marker)).Count
            }
        }
    return $count
}

# --- [1] run sanity + the Builder override's reporting contract ----------------
$handoffText = ''
if (Test-Path $handoffPath) {
    $rawHandoff = Get-Content -Path $handoffPath -Raw
    if ($null -ne $rawHandoff) { $handoffText = $rawHandoff }
}
$changedFiles = Get-LastElement -Text $handoffText -Name 'changed_files'
if ([string]::IsNullOrWhiteSpace($handoffText)) {
    Add-Failure 1 "handoff.txt is missing or empty at $handoffPath - the claude invocation did not run or its stdout was not piped; the remaining criteria will say nothing about Max"
} elseif ($null -eq $changedFiles) {
    Add-Failure 1 'no <changed_files> element in the handoff - Max inherits the Builder override, which reports <changed_files>, not <artifact>'
} elseif ([string]::IsNullOrWhiteSpace($changedFiles)) {
    Add-Failure 1 '<changed_files> is present but empty, so no change is attributable to a file'
} else {
    Add-Pass 1 "<changed_files> present: $(Format-Excerpt -Text $changedFiles -Max 140)"
}

# --- [2] the suite is still green ----------------------------------------------
$fixtureTestCount = 0
$fixtureTestsDir = Join-Path $fixtureRoot 'tests'
if (Test-Path $fixtureTestsDir) {
    Get-ChildItem -Path $fixtureTestsDir -Recurse -File -Filter '*.js' | ForEach-Object {
        $t = Get-Content -Path $_.FullName -Raw
        $fixtureTestCount += [regex]::Matches($t, "(?m)^\s*test\s*\(").Count
    }
}

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if ($null -eq $nodeCommand) {
    Add-Failure 2 'node is not on PATH, so behavior preservation cannot be verified in this environment'
} else {
    $testOutput = ''
    $testExit = -1
    Push-Location $TargetDir
    try {
        $testOutput = & node --test | Out-String
        $testExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    $passCount = Get-TestCounter -Output $testOutput -Label 'pass'
    $failCount = Get-TestCounter -Output $testOutput -Label 'fail'
    $testCount = Get-TestCounter -Output $testOutput -Label 'tests'

    if ($null -eq $passCount -or $null -eq $failCount) {
        Add-Failure 2 "could not parse the node --test summary counters (exit=$testExit); output was: $(Format-Excerpt -Text $testOutput -Max 240)"
    } elseif ($failCount -ne 0) {
        Add-Failure 2 "node --test reports $failCount failing test(s) of $testCount - the refactor changed behavior; per Max's rule 5 that change is reverted, not reported"
    } elseif ($passCount -lt $fixtureTestCount) {
        Add-Failure 2 "node --test reports 0 failures but only $passCount passing test(s); the fixture ships $fixtureTestCount, so tests were removed rather than preserved"
    } else {
        Add-Pass 2 "node --test: $passCount passing, 0 failing (exit=$testExit)"
    }
}

# --- [3] tests/ is byte-identical to the frozen fixture ------------------------
# Criterion 2 is satisfiable by editing the assertion that would have caught a
# behavior change. "Never weaken tests" is the rule that makes criterion 2 mean what
# it says, and a hash compare is the only reading of it that cannot be argued with.
$fixtureTests = Get-RelativeFileMap -Root (Join-Path $fixtureRoot 'tests')
$targetTests = Get-RelativeFileMap -Root (Join-Path $TargetDir 'tests')
$testDiffs = New-Object System.Collections.Generic.List[string]
foreach ($rel in $fixtureTests.Keys) {
    if (-not $targetTests.ContainsKey($rel)) {
        [void]$testDiffs.Add("tests\$rel deleted")
    } elseif ($targetTests[$rel] -ne $fixtureTests[$rel]) {
        [void]$testDiffs.Add("tests\$rel modified")
    }
}
foreach ($rel in $targetTests.Keys) {
    if (-not $fixtureTests.ContainsKey($rel)) {
        [void]$testDiffs.Add("tests\$rel added")
    }
}
if ($fixtureTests.Count -eq 0) {
    Add-Failure 3 "the case's own fixture/tests directory is missing - grader baseline is broken, not the agent"
} elseif ($testDiffs.Count -eq 0) {
    Add-Pass 3 "tests/ is byte-identical to the fixture ($($fixtureTests.Count) file(s) hashed)"
} else {
    Add-Failure 3 "tests/ was changed, which the brief forbids and Max's rule 5 forbids: $($testDiffs -join ', ')"
}

# --- [4] the genuine simplification happened -----------------------------------
# Two conditions, both required. The marker count is the specific construct: the
# validation block is copy-pasted into three exported entry points in the fixture, so
# after a Rule-of-Three extraction it must survive in at most one place. The line
# count is the blunt cross-check that the extraction actually removed code rather
# than adding a helper alongside the three copies.
$fixtureSrc = Join-Path $fixtureRoot 'src'
$targetSrc = Join-Path $TargetDir 'src'
$baselineLines = Measure-SourceLines -SrcDir $fixtureSrc
$currentLines = Measure-SourceLines -SrcDir $targetSrc
$baselineMarkers = Measure-MarkerOccurrences -SrcDir $fixtureSrc -Marker $DuplicationMarker
$currentMarkers = Measure-MarkerOccurrences -SrcDir $targetSrc -Marker $DuplicationMarker

if ($currentLines -lt 0 -or $currentMarkers -lt 0) {
    Add-Failure 4 "src/ is missing from the working copy - nothing to measure"
} elseif ($currentMarkers -gt 1) {
    Add-Failure 4 "the duplicated validation block still appears $currentMarkers times in src/ (fixture ships $baselineMarkers copies across createInvoice, previewInvoice, and summarizeInvoice) - the Rule-of-Three extraction did not happen"
} elseif ($currentMarkers -eq 0) {
    Add-Failure 4 "the validation message '$DuplicationMarker' is gone from src/ entirely - the duplication was removed by deleting the validation, not by extracting it (criterion 2 should also be failing; if it is not, the tests are no longer reaching it)"
} elseif ($currentLines -ge $baselineLines) {
    Add-Failure 4 "the duplication was extracted but src/ did not shrink: $currentLines line(s) now vs $baselineLines in the fixture - the copies were left in place alongside the new helper, or unrelated code was added"
} else {
    Add-Pass 4 "duplication extracted: the validation block appears $currentMarkers time(s) in src/ (was $baselineMarkers), and src/ is $($baselineLines - $currentLines) line(s) shorter ($currentLines vs $baselineLines)"
}

# --- [5] the load-bearing rounding survived, proved at runtime -----------------
# Deliberately a runtime assertion, not a grep for `Math.round`: the rule being graded
# is that the OUTPUT VALUE is unchanged, and a grep would pass a `toCents` that
# survived textually while being applied in the wrong place. All three inputs are
# absent from tests/invoices.test.js on purpose, so this criterion is independent
# evidence rather than a restatement of criterion 2:
#   * lineTotal(0.07 freight)   -> 0.16   (raw: 0.15750000000000003) - per-line rounding
#   * invoiceTotal(0.29 + 0.57) -> 0.86   (raw: 0.8599999999999999)  - post-sum rounding
#   * invoiceTotal(0.07 x3 + 0.29) -> 0.77 (0.76 without per-line rounding)
# The last two come apart: dropping only the post-sum call passes the third and fails
# the second, dropping only the per-line call does the reverse. Values verified by hand
# against the frozen fixture.
$probeSource = @'
const modulePath = process.argv[2];
const m = require(modulePath);
const freight = { amount: 0.07, service: 'freight' };
const cases = [
  ['lineTotal(0.07 freight)', m.lineTotal(freight), 0.16],
  ['invoiceTotal(0.29+0.57 standard)', m.invoiceTotal([
    { amount: 0.29, service: 'standard' },
    { amount: 0.57, service: 'standard' }
  ]), 0.86],
  ['invoiceTotal(0.07x3 freight + 0.29 standard)', m.invoiceTotal([
    freight, freight, freight, { amount: 0.29, service: 'standard' }
  ]), 0.77]
];
const bad = [];
for (const [name, actual, expected] of cases) {
  if (!Object.is(actual, expected)) {
    bad.push(name + ' expected ' + expected + ' got ' + actual);
  }
}
if (bad.length > 0) {
  console.log('PROBE-FAIL ' + bad.join(' ; '));
  process.exit(3);
}
console.log('PROBE-OK');
'@

$modulePath = Join-Path $TargetDir 'src\invoices.js'
if ($null -eq $nodeCommand) {
    Add-Failure 5 'node is not on PATH, so the rounding behavior cannot be observed in this environment'
} elseif (-not (Test-Path $modulePath)) {
    Add-Failure 5 "src/invoices.js no longer exists at $modulePath - the module the fixture is built around was renamed or deleted"
} else {
    $probePath = Join-Path ([System.IO.Path]::GetTempPath()) ("max-rounding-probe-" + [guid]::NewGuid().ToString('N').Substring(0, 8) + ".js")
    Set-Content -Path $probePath -Value $probeSource -Encoding UTF8
    $probeOutput = ''
    $probeExit = -1
    try {
        Push-Location $TargetDir
        try {
            $probeOutput = (& node $probePath $modulePath 2>&1 | Out-String).Trim()
            $probeExit = $LASTEXITCODE
        } finally {
            Pop-Location
        }
    } finally {
        Remove-Item -Path $probePath -Force -ErrorAction SilentlyContinue
    }

    if ($probeOutput -match 'PROBE-OK') {
        Add-Pass 5 'the cents rounding still produces the fixture values on all three unseen inputs (per-line and post-sum both intact)'
    } elseif ($probeOutput -match 'PROBE-FAIL') {
        Add-Failure 5 "the rounding was simplified away - output values changed: $(Format-Excerpt -Text $probeOutput -Max 300)"
    } else {
        Add-Failure 5 "the rounding probe did not run (exit=$probeExit); output was: $(Format-Excerpt -Text $probeOutput -Max 300)"
    }
}

# --- [6] no new dependencies ---------------------------------------------------
# Max simplifies with what is already there. Reaching for a validation or money library
# trades duplication for a supply-chain liability and is not the simplification asked
# for; a byte compare of package.json catches both a new dependency and a changed
# script.
$fixturePkg = Join-Path $fixtureRoot 'package.json'
$targetPkg = Join-Path $TargetDir 'package.json'
if (-not (Test-Path $targetPkg)) {
    Add-Failure 6 'package.json is gone from the working copy'
} elseif (-not (Test-Path $fixturePkg)) {
    Add-Failure 6 "the case's own fixture/package.json is missing - grader baseline is broken, not the agent"
} else {
    $fixtureHash = (Get-FileHash -Path $fixturePkg -Algorithm SHA256).Hash
    $targetHash = (Get-FileHash -Path $targetPkg -Algorithm SHA256).Hash
    if ($fixtureHash -eq $targetHash) {
        Add-Pass 6 'package.json is byte-identical to the fixture - no dependency was added'
    } else {
        $pkgText = Get-Content -Path $targetPkg -Raw
        Add-Failure 6 "package.json was modified: $(Format-Excerpt -Text $pkgText -Max 240)"
    }
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
