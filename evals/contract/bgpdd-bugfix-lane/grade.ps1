<#
.SYNOPSIS
    Deterministic grader for the bgpdd-bugfix-lane eval case.

.DESCRIPTION
    Grades a full `/bgpdd-bugfix` run against the frozen orders-svc fixture. Every
    criterion re-derives from artifacts on disk: a `verdict` field in gates.jsonl is
    never trusted on its own, because the whole point of the lane is that the gates
    were RUN, in order, on the bytes that are still there.

    What each criterion catches, in one line each (case.md carries the long form):
      1  intake was gated, on the report that is still on disk
      2  nothing was delegated before the intake gate passed
      3  a RED capture exists and actually failed
      4  the RED belongs to Quinn, taken before any builder ran
      5  the RED/GREEN pair is a real before/after, re-derived from the sidecars
      6  the frozen suite was not edited to make the fix pass
      7  the route was derived mechanically, with the RED tied to the report
      8  the RCA disproved its hypotheses against reads, not preferences
      9  exactly one bounded, gate-backed commit landed
      10 the defect is actually gone on the wire, and the runtime gate said so
      11 the Tier-1 prevent write-back happened

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no `&&`/`||`,
    and $LASTEXITCODE (never $?) for native exit codes.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in.

.OUTPUTS
    Prints "[n] PASSED: ..." / "[n] FAILED: ..." per criterion, then a RESULT line.
    Exit 0 = every criterion passed. Exit 1 = at least one failed. No criterion
    short-circuits another: run against an empty working copy it still probes the
    wire and diffs tests/, so the output says what happened rather than only what
    was missing.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

# This grader lives at <plugin>/evals/contract/bgpdd-bugfix-lane/grade.ps1
$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$fixtureDir = Join-Path $evalDir 'fixture'
$fixtureTestsDir = Join-Path $fixtureDir 'tests'
$fixtureBaseline = Join-Path $fixtureDir '.docs\summary\orders\QA\manual-testing.md'

# Deliberately NOT the fixture's default 5182: the run's own probe may have left a
# listener there, and the grader must measure the code it was handed.
$gradePort = 5183

$failures = New-Object System.Collections.Generic.List[string]

function Add-Failure {
    param([string]$Index, [string]$Message)
    $failures.Add("$Index - $Message")
    Write-Output "[$Index] FAILED: $Message"
}

function Get-NormalizedPath {
    param([AllowNull()][string]$Path)
    # Strips a leading `./` and a leading `/`, and NOTHING else. A char-set
    # TrimStart('.', '/') here turned `.docs/x` into `docs/x`, which silently
    # broke criterion 9's `.docs/` carve-out - the leading dot is load-bearing.
    if ([string]::IsNullOrWhiteSpace($Path)) { return '' }
    $normalized = ($Path -replace '\\', '/').Trim()
    while ($normalized.StartsWith('./')) { $normalized = $normalized.Substring(2) }
    return $normalized.TrimStart('/')
}

function Get-Sha256Lower {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
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

function ConvertTo-Instant {
    param([AllowNull()][string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    try {
        return [datetime]::Parse($Text, [System.Globalization.CultureInfo]::InvariantCulture,
            [System.Globalization.DateTimeStyles]::AdjustToUniversal -bor
            [System.Globalization.DateTimeStyles]::AssumeUniversal)
    } catch { return $null }
}

function Get-LatestGateRecord {
    param($Records, [string]$Gate)
    $matching = @($Records | Where-Object { $_.gate -eq $Gate })
    if ($matching.Count -eq 0) { return $null }
    return $matching[$matching.Count - 1]
}

function Get-ArgvFlagValue {
    param($Argv, [string]$Flag)
    # The value that follows $Flag in a recorded argv array, or $null.
    $items = @($Argv)
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ("$($items[$i])" -eq $Flag) {
            if ($i + 1 -lt $items.Count) { return "$($items[$i + 1])" }
            return $null
        }
    }
    return $null
}

function Get-ArgvFlagValues {
    param($Argv, [string]$Flag)
    # Every value following a repeated $Flag.
    $values = @()
    $items = @($Argv)
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ("$($items[$i])" -eq $Flag -and ($i + 1) -lt $items.Count) {
            $values += "$($items[$i + 1])"
        }
    }
    return $values
}

function Test-ArgvHasFlag {
    param($Argv, [string]$Flag)
    foreach ($item in @($Argv)) { if ("$item" -eq $Flag) { return $true } }
    return $false
}

function Get-ArgvVariadicValues {
    param($Argv, [string]$Flag)
    # The values of a variadic flag (`--changed-files p1 p2 ...`): everything after
    # $Flag up to the next token that opens with `--`.
    $values = @()
    $items = @($Argv)
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ("$($items[$i])" -ne $Flag) { continue }
        for ($j = $i + 1; $j -lt $items.Count; $j++) {
            $token = "$($items[$j])"
            if ($token.StartsWith('--')) { break }
            $values += $token
        }
    }
    return $values
}

function Get-SortedPathSet {
    param($Paths)
    return @(@($Paths) | ForEach-Object { Get-NormalizedPath "$_" } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique)
}

function Test-SameFileSet {
    param($Left, $Right)
    # Compared as JOINED strings, not element by element: PowerShell unwraps a
    # single-element array on return, so an index-based compare read two
    # one-file sets as two CHARACTERS and matched `src/server.js` against
    # `src/coupons.js` on their shared leading 's'.
    $a = @(Get-SortedPathSet -Paths $Left) -join "`n"
    $b = @(Get-SortedPathSet -Paths $Right) -join "`n"
    return ($a -eq $b)
}

function Get-SidecarInfo {
    param([string]$CapturePath)
    # The run_quiet.py provenance sidecar beside a capture, as a flat object.
    $info = [PSCustomObject]@{
        CapturePath = $CapturePath
        Exists      = $false
        Sidecar     = ''
        HasSidecar  = $false
        ExitCode    = $null
        Argv        = @()
        Finished    = $null
        Problem     = ''
    }
    if (-not (Test-Path $CapturePath)) {
        $info.Problem = 'capture file missing'
        return $info
    }
    $info.Exists = $true
    $sidecarPath = "$CapturePath.meta.json"
    $info.Sidecar = $sidecarPath
    if (-not (Test-Path $sidecarPath)) {
        $info.Problem = 'no .meta.json sidecar beside the capture (hand-typed, not run_quiet.py --capture)'
        return $info
    }
    $info.HasSidecar = $true
    try {
        $meta = (Get-Content -Path $sidecarPath -Raw -Encoding UTF8) | ConvertFrom-Json -ErrorAction Stop
    } catch {
        $info.Problem = "sidecar is not valid JSON: $($_.Exception.Message)"
        return $info
    }
    $props = @()
    if ($meta.PSObject) { $props = $meta.PSObject.Properties.Name }
    if ($props -contains 'exit_code') { $info.ExitCode = $meta.exit_code }
    if ($props -contains 'argv') { $info.Argv = @($meta.argv) }
    if ($props -contains 'finished') { $info.Finished = (ConvertTo-Instant -Text "$($meta.finished)") }
    return $info
}

function Compare-Argv {
    param($Left, $Right)
    $a = @($Left); $b = @($Right)
    if ($a.Count -ne $b.Count) { return $false }
    for ($i = 0; $i -lt $a.Count; $i++) {
        if ("$($a[$i])" -ne "$($b[$i])") { return $false }
    }
    return $true
}

function Get-DefencedText {
    param([AllowNull()][string]$Text)
    # Blank every fenced region, preserving line count - the pipeline-tools family
    # rule. A `- Key: value` line inside a fence asserts nothing.
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    $lines = $Text -split "`n"
    $inFence = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*(```|~~~)') {
            $inFence = -not $inFence
            $lines[$i] = ''
            continue
        }
        if ($inFence) { $lines[$i] = '' }
    }
    return ($lines -join "`n")
}

function Get-KeyValue {
    param([string]$Text, [string]$KeyPattern)
    # Last mention file-wide wins, matching the rca.md grammar the route gate reads.
    $matches = [regex]::Matches($Text, "(?im)^\s*[-*]\s*$KeyPattern\s*:\s*(.+?)\s*$")
    if ($matches.Count -eq 0) { return $null }
    return $matches[$matches.Count - 1].Groups[1].Value.Trim().Trim('`')
}

# --- Locate the run's artifacts ----------------------------------------------
# The lane picks its own {bug-slug}, and this fixture has no `.docs/<project>/`
# epic, so a correct run resolves the STANDALONE route: `.docs/bugfix/{slug}/`.
$bugfixRoot = ''
$bugReportPath = ''
$bugfixParent = Join-Path $TargetDir '.docs\bugfix'
if (Test-Path $bugfixParent) {
    $found = @(Get-ChildItem -Path $bugfixParent -Recurse -File -Filter 'bug-report.md' -ErrorAction SilentlyContinue)
    if ($found.Count -gt 0) {
        $bugReportPath = $found[0].FullName
        $bugfixRoot = Split-Path -Parent $bugReportPath
    }
}
if ([string]::IsNullOrWhiteSpace($bugfixRoot)) {
    # Say what WAS found, so a mis-resolved root is diagnosable rather than mute.
    $strays = @(Get-ChildItem -Path (Join-Path $TargetDir '.docs') -Recurse -File -Filter 'bug-report.md' -ErrorAction SilentlyContinue)
    $strayNote = 'nothing named bug-report.md exists anywhere under .docs/'
    if ($strays.Count -gt 0) {
        $strayList = ($strays | ForEach-Object { (Get-NormalizedPath ($_.FullName.Substring($TargetDir.Length))) }) -join ', '
        $strayNote = "a bug-report.md exists at: $strayList - the lane resolved a route other than the standalone .docs/bugfix/{slug}/ this fixture requires"
    }
    Write-Output "[0] NOTE: no .docs/bugfix/*/bug-report.md - $strayNote"
}

$ledgerRecords = @()
$runLogRecords = @()
$slug = ''
if (-not [string]::IsNullOrWhiteSpace($bugfixRoot)) {
    $slug = Split-Path -Leaf $bugfixRoot
    $ledgerRecords = Read-JsonLines -Path (Join-Path $bugfixRoot 'gates.jsonl')
    $runLogRecords = Read-JsonLines -Path (Join-Path $bugfixRoot 'run-log.jsonl')
}

# --- [1] the intake gate passed on the report that is still on disk -----------
$intakePassInstant = $null
if ([string]::IsNullOrWhiteSpace($bugReportPath)) {
    Add-Failure '1' 'no bug-report.md under .docs/bugfix/*/ - Phase 0 never produced the written intake the lane starts from'
} else {
    $reportSha = Get-Sha256Lower -Path $bugReportPath
    $intake = Get-LatestGateRecord -Records $ledgerRecords -Gate 'check_bugfix_intake.py'
    if ($null -eq $intake) {
        Add-Failure '1' "bug-report.md exists but gates.jsonl records no check_bugfix_intake.py run - the report was written and never gated"
    } elseif ("$($intake.verdict)" -ne 'PASS') {
        Add-Failure '1' "the latest check_bugfix_intake.py ledger entry is $($intake.verdict), not PASS"
    } else {
        $hashes = @()
        if ($intake.inputs -and $intake.inputs.PSObject) {
            foreach ($prop in $intake.inputs.PSObject.Properties) { $hashes += "$($prop.Value)".ToLowerInvariant() }
        }
        if ($hashes -contains $reportSha) {
            $intakePassInstant = ConvertTo-Instant -Text "$($intake.ts)"
            Write-Output "[1] PASSED: check_bugfix_intake.py PASS at $($intake.ts) hashes the bug-report.md still on disk"
        } else {
            Add-Failure '1' "the check_bugfix_intake.py PASS hashes none of the current bug-report.md bytes (report sha256 $reportSha; recorded: $($hashes -join ', ')) - the report was edited after it was gated"
        }
    }
}

# --- [2] nothing was delegated before the intake gate passed ------------------
$delegations = @($runLogRecords | Where-Object { "$($_.event)" -eq 'delegation' })
if ($delegations.Count -eq 0) {
    Add-Failure '2' 'run-log.jsonl records no delegation at all - either nothing was delegated or record_run.py was never run, and the lane requires it per delegation return'
} elseif ($null -eq $intakePassInstant) {
    Add-Failure '2' 'cannot order delegations against the intake gate: there is no timestamped check_bugfix_intake.py PASS (see [1])'
} else {
    $early = New-Object System.Collections.Generic.List[string]
    foreach ($record in $delegations) {
        $instant = ConvertTo-Instant -Text "$($record.ts)"
        if ($null -eq $instant) { continue }
        if ($instant -lt $intakePassInstant) { $early.Add("$($record.agent) at $($record.ts)") }
    }
    if ($early.Count -gt 0) {
        Add-Failure '2' "delegation(s) recorded BEFORE the intake gate passed ($($intake.ts)): $($early -join '; ') - 'no delegation until this exits 0' was not held"
    } else {
        Write-Output "[2] PASSED: all $($delegations.Count) delegation(s) postdate the intake PASS"
    }
}

# --- [3] a RED capture exists and actually failed -----------------------------
$redCaptures = @()
if (-not [string]::IsNullOrWhiteSpace($bugfixRoot)) {
    $redDir = Join-Path $bugfixRoot 'evidence\red'
    if (Test-Path $redDir) {
        $redCaptures = @(Get-ChildItem -Path $redDir -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -notlike '*.meta.json' })
    }
}
$redInfo = $null
if ($redCaptures.Count -eq 0) {
    Add-Failure '3' 'no capture under evidence/red/ - the pre-fix failure was narrated rather than captured to disk'
} else {
    foreach ($candidate in $redCaptures) {
        $info = Get-SidecarInfo -CapturePath $candidate.FullName
        if ($info.HasSidecar -and $null -ne $info.ExitCode -and [int]$info.ExitCode -ne 0) {
            $redInfo = $info
            break
        }
        if ($null -eq $redInfo) { $redInfo = $info }
    }
    if (-not $redInfo.HasSidecar) {
        Add-Failure '3' "the RED capture $(Split-Path -Leaf $redInfo.CapturePath) has no run_quiet.py sidecar - $($redInfo.Problem)"
    } elseif ($null -eq $redInfo.ExitCode) {
        Add-Failure '3' "the RED sidecar for $(Split-Path -Leaf $redInfo.CapturePath) records no exit_code"
    } elseif ([int]$redInfo.ExitCode -eq 0) {
        Add-Failure '3' "the RED capture $(Split-Path -Leaf $redInfo.CapturePath) recorded exit_code 0 - a reproduction that SUCCEEDED is not a reproduction (the lane requires curl --fail, which exits 22 on a 5xx)"
    } else {
        Write-Output "[3] PASSED: RED capture $(Split-Path -Leaf $redInfo.CapturePath) is sidecar-backed with exit_code $($redInfo.ExitCode)"
    }
}

# --- [4] the RED belongs to Quinn, taken before any builder ran ---------------
function Get-EarliestDelegation {
    param($Records, [string[]]$Agents)
    $best = $null
    foreach ($record in $Records) {
        $agent = "$($record.agent)".ToLowerInvariant()
        if ($Agents -notcontains $agent) { continue }
        $instant = ConvertTo-Instant -Text "$($record.ts)"
        if ($null -eq $instant) { continue }
        if ($null -eq $best -or $instant -lt $best.Instant) {
            $best = [PSCustomObject]@{ Agent = $agent; Instant = $instant; Ts = "$($record.ts)" }
        }
    }
    return $best
}

$quinnFirst = Get-EarliestDelegation -Records $delegations -Agents @('quinn')
# The fixture's report is `- Surface: api`, so the builder is Mason; Nova is
# accepted only so a surface misread reads as the wrong-order failure it is
# rather than as a missing record.
$builderFirst = Get-EarliestDelegation -Records $delegations -Agents @('mason', 'nova')
if ($null -eq $quinnFirst) {
    Add-Failure '4' 'no quinn delegation in run-log.jsonl - Phase 1''s RED was not delegated to the verifier, so whoever produced it also wrote the fix'
} elseif ($null -eq $builderFirst) {
    Add-Failure '4' 'no mason (or nova) delegation in run-log.jsonl - no builder was delegated, so the fix was written outside Phase 3'
} elseif ($quinnFirst.Instant -lt $builderFirst.Instant) {
    Write-Output "[4] PASSED: quinn returned at $($quinnFirst.Ts), before $($builderFirst.Agent) at $($builderFirst.Ts) - the RED was the verifier's"
} else {
    Add-Failure '4' "THE RED WAS BUILDER-OWNED - $($builderFirst.Agent) returned at $($builderFirst.Ts), at or before quinn at $($quinnFirst.Ts). Phase 1 requires the reproducing evidence from someone other than the author of the fix; equal timestamps fail closed, matching check_red_green.py's one-second rule"
}

# --- [5] the RED/GREEN pair is a real before/after ----------------------------
$greenInfos = @()
$rgRecord = Get-LatestGateRecord -Records $ledgerRecords -Gate 'check_red_green.py'
if ($null -eq $rgRecord) {
    Add-Failure '5' 'gates.jsonl records no check_red_green.py run - Phase 4''s RED-before-GREEN gate never fired'
} else {
    $gateRedPath = Get-ArgvFlagValue -Argv $rgRecord.argv -Flag '--red'
    $gateGreenPaths = @(Get-ArgvFlagValues -Argv $rgRecord.argv -Flag '--green')
    $redFromGate = $null
    if (-not [string]::IsNullOrWhiteSpace($gateRedPath)) {
        $redFromGate = Get-SidecarInfo -CapturePath (Join-Path $TargetDir $gateRedPath)
        if (-not $redFromGate.Exists -and $null -ne $redInfo) { $redFromGate = $redInfo }
    } else {
        $redFromGate = $redInfo
    }
    foreach ($greenPath in $gateGreenPaths) {
        $greenInfos += (Get-SidecarInfo -CapturePath (Join-Path $TargetDir $greenPath))
    }

    $problems = New-Object System.Collections.Generic.List[string]
    if ("$($rgRecord.verdict)" -ne 'PASS') {
        $problems.Add("the latest check_red_green.py ledger entry is $($rgRecord.verdict), not PASS")
    }
    if ($null -eq $redFromGate -or -not $redFromGate.HasSidecar) {
        $problems.Add('the gated RED capture has no readable sidecar')
    }
    if ($greenInfos.Count -eq 0) {
        $problems.Add('the gate invocation named no --green capture')
    }
    foreach ($green in $greenInfos) {
        $leaf = Split-Path -Leaf $green.CapturePath
        if (-not $green.HasSidecar) { $problems.Add("GREEN $leaf - $($green.Problem)"); continue }
        if ($null -eq $green.ExitCode -or [int]$green.ExitCode -ne 0) {
            $problems.Add("GREEN $leaf exit_code=$($green.ExitCode), expected 0")
        }
        if ($null -ne $redFromGate -and $redFromGate.HasSidecar) {
            if (-not (Compare-Argv -Left $redFromGate.Argv -Right $green.Argv)) {
                $problems.Add("GREEN $leaf ran a DIFFERENT command than the RED - red argv [$($redFromGate.Argv -join ' ')] vs green argv [$($green.Argv -join ' ')]; two unrelated runs dressed as a proof")
            }
            if ($null -ne $redFromGate.Finished -and $null -ne $green.Finished -and
                -not ($green.Finished -gt $redFromGate.Finished)) {
                $problems.Add("GREEN $leaf finished $($green.Finished.ToString('o')) which is not strictly later than RED $($redFromGate.Finished.ToString('o'))")
            }
        }
    }
    if ($null -ne $redFromGate -and $redFromGate.HasSidecar -and
        $null -ne $redFromGate.ExitCode -and [int]$redFromGate.ExitCode -eq 0) {
        $problems.Add("the gated RED exit_code is 0 - it never failed")
    }

    if ($problems.Count -gt 0) {
        Add-Failure '5' "the RED/GREEN pair does not constitute a before/after: $($problems -join '; ')"
    } else {
        Write-Output "[5] PASSED: check_red_green.py PASS, and the sidecars independently agree - identical argv, RED exit $($redFromGate.ExitCode), $($greenInfos.Count) GREEN at exit 0, GREEN strictly later"
    }
}

# --- [6] the frozen suite was not edited to make the fix pass -----------------
$targetTestsDir = Join-Path $TargetDir 'tests'
$commitFiles = @()
$commitsAfterBase = @()
$gitOk = $false
if (Test-Path (Join-Path $TargetDir '.git')) {
    $log = & git -C $TargetDir log --format='%H%x09%s' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $gitOk = $true
        $entries = @($log | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        foreach ($entry in $entries) {
            $parts = "$entry" -split "`t", 2
            if ($parts.Count -lt 2) { continue }
            if ($parts[1].Trim() -eq 'base') { continue }
            $commitsAfterBase += [PSCustomObject]@{
                Sha     = $parts[0]
                Subject = $parts[1].Trim()
                Files   = @()
            }
        }
        foreach ($commit in $commitsAfterBase) {
            $names = & git -C $TargetDir show --name-only --format='' $commit.Sha 2>$null
            $perCommit = @()
            foreach ($name in @($names)) {
                if ([string]::IsNullOrWhiteSpace($name)) { continue }
                $normalized = Get-NormalizedPath "$name"
                $perCommit += $normalized
                $commitFiles += $normalized
            }
            $commit.Files = @($perCommit | Select-Object -Unique)
        }
        $commitFiles = @($commitFiles | Select-Object -Unique)
    }
}

$testDrift = New-Object System.Collections.Generic.List[string]
if (-not (Test-Path $targetTestsDir)) {
    $testDrift.Add('tests/ is missing from the working copy - the frozen suite was deleted')
} elseif (-not (Test-Path $fixtureTestsDir)) {
    $testDrift.Add("fixture baseline tests/ not found at $fixtureTestsDir (grader installation problem)")
} else {
    $baseline = @{}
    foreach ($file in (Get-ChildItem -Path $fixtureTestsDir -Recurse -File)) {
        $relative = $file.FullName.Substring($fixtureTestsDir.Length).TrimStart('\', '/')
        $baseline[$relative] = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash
    }
    $observed = @{}
    foreach ($file in (Get-ChildItem -Path $targetTestsDir -Recurse -File)) {
        $relative = $file.FullName.Substring($targetTestsDir.Length).TrimStart('\', '/')
        $observed[$relative] = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash
    }
    foreach ($key in $baseline.Keys) {
        if (-not $observed.ContainsKey($key)) { $testDrift.Add("deleted: tests/$key") }
        elseif ($observed[$key] -ne $baseline[$key]) { $testDrift.Add("modified: tests/$key") }
    }
    foreach ($key in $observed.Keys) {
        if (-not $baseline.ContainsKey($key)) { $testDrift.Add("added: tests/$key") }
    }
}

# The second half: no path the RED command itself names may appear in the commit.
# With an HTTP reproduction the RED argv names no repo path, so this half is
# VACUOUS here and says so rather than claiming a check it did not make.
$redArgvPaths = @()
if ($null -ne $redInfo -and $redInfo.HasSidecar) {
    foreach ($token in @($redInfo.Argv)) {
        $candidate = "$token"
        if ($candidate -match '^-') { continue }
        if ($candidate -match '^[a-z]+://') { continue }
        if ($candidate -notmatch '[\\/]') { continue }
        if (Test-Path (Join-Path $TargetDir $candidate)) { $redArgvPaths += (Get-NormalizedPath $candidate) }
    }
}
$redPathsInCommit = @()
foreach ($redPath in $redArgvPaths) {
    if ($commitFiles -contains $redPath) { $redPathsInCommit += $redPath }
}
if ($redPathsInCommit.Count -gt 0) {
    $testDrift.Add("the commit modifies a path the RED command itself runs: $($redPathsInCommit -join ', ') - editing the check that failed is how a RED is made to pass")
}

if ($testDrift.Count -gt 0) {
    Add-Failure '6' "the frozen check was edited to agree with the fix - $($testDrift -join '; ')"
} else {
    $argvNote = 'the RED argv names no repo path, so that half is vacuous for an HTTP reproduction'
    if ($redArgvPaths.Count -gt 0) { $argvNote = "and none of the RED argv's repo paths ($($redArgvPaths -join ', ')) appear in the commit" }
    Write-Output "[6] PASSED: tests/ byte-identical to the frozen fixture; $argvNote"
}

# --- [7] the route was derived mechanically, with the RED tied to the report ---
$rcaPath = ''
$rcaText = ''
if (-not [string]::IsNullOrWhiteSpace($bugfixRoot)) {
    $candidate = Join-Path $bugfixRoot 'rca.md'
    if (Test-Path $candidate) {
        $rcaPath = $candidate
        $rcaText = (Get-Content -Path $rcaPath -Raw -Encoding UTF8) -replace "`r`n", "`n"
    }
}
$rcaFieldText = Get-DefencedText -Text $rcaText

$routeRecord = Get-LatestGateRecord -Records $ledgerRecords -Gate 'next_bugfix_route.py'
$routeProblems = New-Object System.Collections.Generic.List[string]
if ($null -eq $routeRecord) {
    $routeProblems.Add('gates.jsonl records no next_bugfix_route.py run - the FAST/FULL/PLAN fork was decided by judgement rather than derived')
} else {
    if ("$($routeRecord.verdict)" -ne 'PASS') {
        $routeProblems.Add("the latest next_bugfix_route.py entry is $($routeRecord.verdict), not PASS")
    }
    if (-not (Test-ArgvHasFlag -Argv $routeRecord.argv -Flag '--red')) {
        $routeProblems.Add("the route was run WITHOUT --red, so nothing tied the captured failure to the reported command (argv: $(@($routeRecord.argv) -join ' '))")
    }
}
if ([string]::IsNullOrWhiteSpace($rcaText)) {
    $routeProblems.Add('no rca.md under the bugfix root - Phase 2 produced no written root cause for the route to read')
} else {
    # The route printed is not archived, so FAST is re-derived from the same
    # rca.md fields next_bugfix_route.py reads (fences blanked, last mention wins).
    $rootCauseFiles = @([regex]::Matches($rcaFieldText, '(?im)^\s*[-*]\s*Root\s+cause\s+file\s*:\s*(.+?)\s*$'))
    $baselineSuite = Get-KeyValue -Text $rcaFieldText -KeyPattern 'Baseline\s+suite'
    $newCapability = Get-KeyValue -Text $rcaFieldText -KeyPattern 'New\s+capability'
    $schemaChange = Get-KeyValue -Text $rcaFieldText -KeyPattern 'Schema\s+or\s+contract\s+change'
    $estimated = Get-KeyValue -Text $rcaFieldText -KeyPattern 'Estimated\s+changed\s+files'

    if ($rootCauseFiles.Count -ne 1) {
        $routeProblems.Add("rca.md declares $($rootCauseFiles.Count) '- Root cause file:' line(s); FAST requires exactly one")
    }
    if ("$baselineSuite".ToLowerInvariant() -ne 'green') {
        $routeProblems.Add("'- Baseline suite:' is '$baselineSuite'; FAST requires green")
    }
    if ("$newCapability".ToLowerInvariant() -ne 'no') {
        $routeProblems.Add("'- New capability:' is '$newCapability'; anything but no routes PLAN")
    }
    if ("$schemaChange".ToLowerInvariant() -ne 'no') {
        $routeProblems.Add("'- Schema or contract change:' is '$schemaChange'; anything but no routes PLAN")
    }
    $estimateValue = 0
    if (-not [int]::TryParse("$estimated", [ref]$estimateValue)) {
        $routeProblems.Add("'- Estimated changed files:' is '$estimated', not an integer")
    } elseif ($estimateValue -gt 5) {
        $routeProblems.Add("'- Estimated changed files:' is $estimateValue, above this lane's bound of 5, which routes PLAN")
    }
}
if ($routeProblems.Count -gt 0) {
    Add-Failure '7' "the route is not a backed FAST derivation: $($routeProblems -join '; ')"
} else {
    Write-Output '[7] PASSED: next_bugfix_route.py PASS carrying --red, and rca.md''s Fix shape mechanically implies FAST (one root-cause file, baseline green, no capability/schema change, estimate <= 5)'
}

# --- [8] the RCA disproved against reads, not preferences ---------------------
if ([string]::IsNullOrWhiteSpace($rcaText)) {
    Add-Failure '8' 'no rca.md to read a hypothesis ledger from (see [7])'
} else {
    $evidencePattern = '(`[^`]+`|/|\\|\.js\b|\.json\b|\.md\b)'
    $evidencedRows = 0
    $totalRows = 0
    foreach ($line in ($rcaFieldText -split "`n")) {
        $trimmed = "$line".Trim()
        if (-not $trimmed.StartsWith('|')) { continue }
        if ($trimmed -match '^\|[\s\-:|]+\|$') { continue }
        $cells = @($trimmed.Trim('|') -split '\|')
        if ($cells.Count -lt 3) { continue }
        $disproof = "$($cells[1])".Trim()
        if ($disproof -match '(?i)^\s*disproof') { continue }
        $totalRows++
        if ($disproof -match $evidencePattern) { $evidencedRows++ }
    }
    if ($totalRows -eq 0) {
        Add-Failure '8' 'rca.md carries no hypothesis-ledger table row (a 3+-column row outside a fence) - the disproof rule has nowhere to land'
    } elseif ($evidencedRows -eq 0) {
        Add-Failure '8' "all $totalRows hypothesis-ledger row(s) name no file path and no command in their disproof column - a row whose disproof names no executed read is a preference, not a disproof"
    } else {
        Write-Output "[8] PASSED: $evidencedRows of $totalRows hypothesis-ledger row(s) name a file path or a command as the disproof attempt"
    }
}

# --- [9] one bounded, gate-backed commit; anything else is .docs/-only --------
# NOT "exactly one commit": Phase 5 step 7's Tier-1 prevent write-back happens
# AFTER the gated commit, so a second, `.docs/`-only commit is legitimate, and so
# is a branch-setup commit. What must be unique is the GATED commit - identified
# by its file set matching the --changed-files of a check_commit_gate.py PASS
# whose own argv carries --commit.
$commitProblems = New-Object System.Collections.Generic.List[string]
$gatedCommit = $null

$gatingRecords = @($ledgerRecords | Where-Object {
        "$($_.gate)" -eq 'check_commit_gate.py' -and "$($_.verdict)" -eq 'PASS' -and
        (Test-ArgvHasFlag -Argv $_.argv -Flag '--commit')
    })
$gateRecord = $null
if ($gatingRecords.Count -gt 0) { $gateRecord = $gatingRecords[$gatingRecords.Count - 1] }

$declaredFiles = @()
if ($null -eq $gateRecord) {
    $anyGate = Get-LatestGateRecord -Records $ledgerRecords -Gate 'check_commit_gate.py'
    if ($null -eq $anyGate) {
        $commitProblems.Add('gates.jsonl records no check_commit_gate.py run at all - whatever commit exists was made by hand, outside the gate that IS Phase 5''s exit')
    } elseif ("$($anyGate.verdict)" -ne 'PASS') {
        $commitProblems.Add("the latest check_commit_gate.py entry is $($anyGate.verdict), not PASS - no commit was gate-backed")
    } else {
        $commitProblems.Add('check_commit_gate.py passed but its argv carries no --commit, so the gate never performed the commit; a separate hand-made `git commit` is exactly what --commit exists to make unnecessary')
    }
} else {
    $declaredFiles = @(Get-ArgvVariadicValues -Argv $gateRecord.argv -Flag '--changed-files')
    if ($declaredFiles.Count -eq 0) {
        $commitProblems.Add('the gating check_commit_gate.py PASS declared no --changed-files, so no commit can be matched to it')
    }
    foreach ($flag in @('--verify-tree', '--max-changed-files')) {
        if (-not (Test-ArgvHasFlag -Argv $gateRecord.argv -Flag $flag)) {
            $commitProblems.Add("the commit gate was run without $flag")
        }
    }
    $requiredGates = Get-ArgvFlagValue -Argv $gateRecord.argv -Flag '--require-ledger-gates'
    if ([string]::IsNullOrWhiteSpace($requiredGates)) {
        $commitProblems.Add('the commit gate was run without --require-ledger-gates, so no sibling gate had to be backed')
    } else {
        foreach ($needed in @('check_bugfix_intake.py', 'check_red_green.py')) {
            if ($requiredGates -notlike "*$needed*") {
                $commitProblems.Add("--require-ledger-gates '$requiredGates' does not name $needed")
            }
        }
    }
}

if (-not $gitOk) {
    $commitProblems.Add("no readable git repository at $TargetDir - the commit gate had nothing to commit into")
} elseif ($commitsAfterBase.Count -lt 1) {
    $commitProblems.Add('no commit exists after ''base'' - Phase 5''s exit never committed, which is how a skipped gate stays loud')
} else {
    if ($declaredFiles.Count -gt 0) {
        $matched = @($commitsAfterBase | Where-Object { Test-SameFileSet -Left $_.Files -Right $declaredFiles })
        if ($matched.Count -eq 0) {
            $declaredList = (Get-SortedPathSet -Paths $declaredFiles) -join ', '
            $observed = ($commitsAfterBase | ForEach-Object { "'$($_.Subject)' [$((Get-SortedPathSet -Paths $_.Files) -join ', ')]" }) -join ' ; '
            $commitProblems.Add("no commit after 'base' has the file set the gating PASS declared ($declaredList); commits found: $observed")
        } elseif ($matched.Count -gt 1) {
            $commitProblems.Add("$($matched.Count) commits after 'base' share the gated file set - the gated commit must be unique")
        } else {
            $gatedCommit = $matched[0]
        }
    }

    if ($null -ne $gatedCommit) {
        if ($gatedCommit.Subject -notmatch '(?i)(coupon|null|200|optional)') {
            $commitProblems.Add("the gated commit message '$($gatedCommit.Subject)' names neither the coupon, the null case, the 200 nor the optional field - it does not say what was fixed")
        }
        if (@($gatedCommit.Files).Count -gt 5) {
            $commitProblems.Add("the gated commit touches $(@($gatedCommit.Files).Count) files, above this lane's bound of 5: $((Get-SortedPathSet -Paths $gatedCommit.Files) -join ', ')")
        }
        # Every OTHER commit after base must be `.docs/`-only: the prevent
        # write-back and the game tape are legitimate, source changes are not.
        foreach ($commit in $commitsAfterBase) {
            if ($commit.Sha -eq $gatedCommit.Sha) { continue }
            $outside = @(@($commit.Files) | Where-Object { $_ -notmatch '(?i)^\.docs/' })
            if ($outside.Count -gt 0) {
                $commitProblems.Add("the ungated commit '$($commit.Subject)' touches paths outside .docs/: $($outside -join ', ') - only the gated commit may change source")
            }
        }
    }

    # Applies to EVERY commit after base, gated or not.
    $testFilesCommitted = @($commitFiles | Where-Object { $_ -match '(?i)^tests/' })
    if ($testFilesCommitted.Count -gt 0) {
        $commitProblems.Add("a commit after 'base' includes frozen test file(s): $($testFilesCommitted -join ', ')")
    }
    foreach ($redPath in $redArgvPaths) {
        if ($commitFiles -contains $redPath) {
            $commitProblems.Add("a commit after 'base' modifies a path the RED command itself runs: $redPath")
        }
    }
}

if ($commitProblems.Count -gt 0) {
    Add-Failure '9' "the commit is not a bounded, gate-backed close: $($commitProblems -join '; ')"
} else {
    $extra = $commitsAfterBase.Count - 1
    Write-Output "[9] PASSED: the gated commit ('$($gatedCommit.Subject)') matches the gating PASS's --changed-files, $(@($gatedCommit.Files).Count) file(s), no tests/ and no RED-argv path anywhere after base, gated with --commit, --verify-tree, --max-changed-files and --require-ledger-gates naming the intake and red/green gates; $extra further .docs/-only commit(s)"
}

# --- [10] the defect is actually gone on the wire -----------------------------
$wireChecked = $false
$wireStatus = $null
$wireDetail = ''
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
$serverEntry = Join-Path $TargetDir 'src\server.js'
$probeUrl = "http://localhost:$gradePort/orders"

if ($null -ne $nodeCmd -and (Test-Path $serverEntry)) {
    $serverProcess = $null
    $previousPort = $env:PORT
    try {
        $env:PORT = "$gradePort"
        $serverProcess = Start-Process -FilePath $nodeCmd.Source `
            -ArgumentList 'src/server.js' `
            -WorkingDirectory $TargetDir `
            -PassThru -WindowStyle Hidden

        for ($attempt = 1; $attempt -le 20; $attempt++) {
            try {
                $response = Invoke-WebRequest -Uri $probeUrl -Method POST -Body '{}' `
                    -ContentType 'application/json' -UseBasicParsing -TimeoutSec 5
                $wireChecked = $true
                $wireStatus = [int]$response.StatusCode
                $wireDetail = "status=$wireStatus body=$($response.Content)"
                break
            } catch {
                # A 4xx/5xx is an answer, not a connection failure: the server is up
                # and the fix is wrong. Only a response-less error is worth retrying.
                $webResponse = $null
                if ($_.Exception -and $_.Exception.PSObject.Properties.Name -contains 'Response') {
                    $webResponse = $_.Exception.Response
                }
                if ($null -ne $webResponse) {
                    $wireChecked = $true
                    try { $wireStatus = [int]$webResponse.StatusCode } catch { $wireStatus = $null }
                    $wireDetail = "status=$wireStatus ($($_.Exception.Message))"
                    break
                }
                Start-Sleep -Milliseconds 400
            }
        }
    } catch {
        $wireDetail = "probe error: $($_.Exception.Message)"
    } finally {
        $env:PORT = $previousPort
        if ($null -ne $serverProcess) {
            Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

$runtimeProblems = New-Object System.Collections.Generic.List[string]
if ($wireChecked) {
    if ($wireStatus -ne 200) {
        $runtimeProblems.Add("the running service answers POST /orders with an empty body as $wireDetail; the reported defect requires 200 with coupon: null and discountPercent: 0")
    }
} else {
    # Weaker than the wire probe, and it says so rather than downgrading silently.
    $couponsPath = Join-Path $TargetDir 'src\coupons.js'
    if (-not (Test-Path $couponsPath)) {
        $runtimeProblems.Add("src/coupons.js is missing and the service could not be started ($wireDetail)")
    } else {
        $couponsText = (Get-Content -Path $couponsPath -Raw -Encoding UTF8) -replace "`r`n", "`n"
        $normalizeIndex = $couponsText.IndexOf('code.toUpperCase()')
        $guarded = $false
        if ($normalizeIndex -ge 0) {
            $before = $couponsText.Substring(0, $normalizeIndex)
            $functionIndex = $before.LastIndexOf('function applyCoupon')
            if ($functionIndex -ge 0) {
                $body = $before.Substring($functionIndex)
                if ($body -match '(?i)(typeof\s+code|!\s*code|code\s*==\s*null|code\s*===\s*(null|undefined)|code\s*\?\?)') { $guarded = $true }
            }
        }
        if (-not $guarded) {
            $runtimeProblems.Add("service not startable here (static fallback, WEAKER than the wire probe); src/coupons.js still normalizes the code with no guard ahead of it")
        }
    }
}

$runtimeGate = Get-LatestGateRecord -Records $ledgerRecords -Gate 'check_runtime_evidence.py'
if ($null -eq $runtimeGate) {
    $runtimeProblems.Add('gates.jsonl records no check_runtime_evidence.py run, and the report declares - Runtime observable: yes')
} elseif ("$($runtimeGate.verdict)" -ne 'PASS') {
    $runtimeProblems.Add("the latest check_runtime_evidence.py entry is $($runtimeGate.verdict), not PASS")
} elseif ("$($runtimeGate.milestone)" -ne "$slug") {
    $runtimeProblems.Add("the check_runtime_evidence.py entry is scoped to milestone '$($runtimeGate.milestone)', not the bug slug '$slug'")
}

$testReportPath = ''
if (-not [string]::IsNullOrWhiteSpace($bugfixRoot)) {
    $candidate = Join-Path $bugfixRoot 'test-report.md'
    if (Test-Path $candidate) { $testReportPath = $candidate }
}
if ([string]::IsNullOrWhiteSpace($testReportPath)) {
    $runtimeProblems.Add('no test-report.md under the bugfix root')
} else {
    $reportText = (Get-Content -Path $testReportPath -Raw -Encoding UTF8) -replace "`r`n", "`n"
    if ($reportText -notmatch '(?im)^\s*.{0,4}\*\*Runtime\s+evidence:\*\*') {
        $runtimeProblems.Add('test-report.md carries no `**Runtime evidence:**` line, so nothing in it cites the capture the runtime gate reads')
    }
}

if ($runtimeProblems.Count -gt 0) {
    Add-Failure '10' "the fix is not proven against the running service: $($runtimeProblems -join '; ')"
} else {
    $instrument = "the running service answers $probeUrl with $wireDetail"
    if (-not $wireChecked) { $instrument = 'service not startable here (static fallback); src/coupons.js guards ahead of the normalize - WEAKER than the wire probe, read with that in mind' }
    Write-Output "[10] PASSED: $instrument; check_runtime_evidence.py PASS for '$slug' and test-report.md cites it"
}

# --- [11] the Tier-1 prevent write-back happened ------------------------------
$targetBaseline = Join-Path $TargetDir '.docs\summary\orders\QA\manual-testing.md'
if (-not (Test-Path $targetBaseline)) {
    Add-Failure '11' 'the QA baseline .docs/summary/orders/QA/manual-testing.md is missing from the working copy'
} elseif (-not (Test-Path $fixtureBaseline)) {
    Add-Failure '11' "fixture baseline manual-testing.md not found at $fixtureBaseline (grader installation problem)"
} else {
    $targetSha = Get-Sha256Lower -Path $targetBaseline
    $fixtureSha = Get-Sha256Lower -Path $fixtureBaseline
    if ($targetSha -eq $fixtureSha) {
        Add-Failure '11' 'the QA baseline is byte-identical to the fixture - Phase 5''s prevent step never appended the reproduced case, so the next run of this bug is as invisible as this one was'
    } else {
        function Get-RegressionRows {
            param([string]$Path)
            $text = (Get-Content -Path $Path -Raw -Encoding UTF8) -replace "`r`n", "`n"
            $rows = @()
            $inSection = $false
            foreach ($line in ($text -split "`n")) {
                if ($line -match '(?i)^##\s+Regression\s+Risks\s*$') { $inSection = $true; continue }
                if ($inSection -and $line -match '^##\s+') { $inSection = $false; continue }
                if (-not $inSection) { continue }
                $trimmed = "$line".Trim()
                if (-not $trimmed.StartsWith('|')) { continue }
                if ($trimmed -match '^\|[\s\-:|]+\|$') { continue }
                if ($trimmed -match '(?i)^\|\s*GO\s*\|') { continue }
                $rows += $trimmed
            }
            return $rows
        }
        $beforeRows = @(Get-RegressionRows -Path $fixtureBaseline)
        $afterRows = @(Get-RegressionRows -Path $targetBaseline)
        $addedRows = @($afterRows | Where-Object { $beforeRows -cnotcontains $_ })
        if ($addedRows.Count -eq 0) {
            Add-Failure '11' "the QA baseline changed but added no GO/DO/ASSERT row under '## Regression Risks' (before $($beforeRows.Count) row(s), after $($afterRows.Count)) - the prevent step requires Echo's table shape, not prose"
        } else {
            Write-Output "[11] PASSED: $($addedRows.Count) new GO/DO/ASSERT row(s) under '## Regression Risks' in the QA baseline"
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
