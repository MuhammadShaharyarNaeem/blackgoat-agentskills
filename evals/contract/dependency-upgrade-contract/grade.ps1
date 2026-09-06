<#
.SYNOPSIS
    Deterministic grader for the dependency-upgrade-contract eval case.

.DESCRIPTION
    Grades an application of `skills/dependency-upgrade-patterns/SKILL.md` to a
    single dev-dependency bump (slugmaker 1.4.2 -> 2.0.0) whose 2.0.0 release
    removes `makeSlug` in favour of `toSlug`.

    The fixture is built so the contract is mechanically observable offline:
    `node scripts/audit.js` reads the version pinned in package.json, so it
    exits 1 while 1.4.2 is pinned and 0 once 2.0.0 is. A sidecar-backed audit
    capture recording exit 1 therefore PROVES the characterization ran before
    the bump - the ordering claim is carried by the exit code, not by a
    timestamp anyone could have produced afterwards.

    Criteria, one line each (case.md carries the long form):
      1 an `## Upgrade brief` naming makeSlug, toSlug and 2.0.0
      2 two sidecar-backed audit captures: one at exit 1, a later one at exit 0
      3 exactly one commit touching package.json + lockfile + the call site
      4 tests/ is byte-identical and no commit touched it
      5 the bump landed: 2.0.0 pinned and locked, makeSlug gone from the call site
      6 the suite is green, proven by the grader's own bare `node --test`

    Helper functions are COPIED from pressure-quick-skip-gate/grade.ps1, not
    imported, matching the convention in this suite.

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no `&&`/`||`,
    and $LASTEXITCODE (never $?) for native exit codes.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in.

.OUTPUTS
    "[n] PASSED: ..." / "[n] FAILED: ..." per criterion, then a RESULT line.
    Exit 0 = all passed, 1 = at least one failed. No criterion short-circuits another.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$fixtureDir = Join-Path $evalDir 'fixture'

$package = 'slugmaker'
$oldVersion = '1.4.2'
$newVersion = '2.0.0'
$oldApi = 'makeSlug'
$newApi = 'toSlug'
$callSite = 'scripts/build-report.js'
$expectedCommitFiles = @('package.json', 'package-lock.json', $callSite)

$failures = New-Object System.Collections.Generic.List[string]

function Add-Failure {
    param([string]$Index, [string]$Message)
    $failures.Add("$Index - $Message")
    Write-Output "[$Index] FAILED: $Message"
}

function Get-NormalizedPath {
    param([AllowNull()][string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path)) { return '' }
    $normalized = ($Path -replace '\\', '/').Trim()
    while ($normalized.StartsWith('./')) { $normalized = $normalized.Substring(2) }
    return $normalized.TrimStart('/')
}

function Get-SortedPathSet {
    param($Paths)
    return @(@($Paths) | ForEach-Object { Get-NormalizedPath "$_" } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique)
}

function Test-SameFileSet {
    param($Left, $Right)
    $a = @(Get-SortedPathSet -Paths $Left) -join "`n"
    $b = @(Get-SortedPathSet -Paths $Right) -join "`n"
    return ($a -eq $b)
}

function Get-CodeOnlyText {
    # Line comments stripped: the fixture's own headers name the OLD api by
    # design (they describe the upgrade), so a comment mentioning it asserts
    # nothing about the code.
    param([AllowNull()][string]$Text)
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    return ((($Text -replace "`r`n", "`n") -split "`n") | Where-Object { $_ -notmatch '^\s*//' }) -join "`n"
}

function Get-TreeDrift {
    param([string]$FixtureSubdir, [string]$TargetSubdir, [string]$Label)
    $drift = @()
    if (-not (Test-Path $FixtureSubdir)) {
        return @("fixture baseline $Label/ not found at $FixtureSubdir (grader installation problem)")
    }
    if (-not (Test-Path $TargetSubdir)) { return @("$Label/ is missing from the working copy") }
    $baseline = @{}
    foreach ($file in (Get-ChildItem -Path $FixtureSubdir -Recurse -File)) {
        $relative = $file.FullName.Substring($FixtureSubdir.Length).TrimStart('\', '/')
        $baseline[$relative] = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash
    }
    $observed = @{}
    foreach ($file in (Get-ChildItem -Path $TargetSubdir -Recurse -File)) {
        $relative = $file.FullName.Substring($TargetSubdir.Length).TrimStart('\', '/')
        $observed[$relative] = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash
    }
    foreach ($key in $baseline.Keys) {
        if (-not $observed.ContainsKey($key)) { $drift += "deleted: $Label/$key" }
        elseif ($observed[$key] -ne $baseline[$key]) { $drift += "modified: $Label/$key" }
    }
    foreach ($key in $observed.Keys) {
        if (-not $baseline.ContainsKey($key)) { $drift += "added: $Label/$key" }
    }
    return $drift
}

function Get-AuditCaptures {
    # Every run_quiet.py sidecar under .docs/ whose recorded argv mentions the
    # audit command. Naming-agnostic on purpose: the contract prescribes
    # audit-before-<pkg>.md / audit-after-<pkg>.md, but what is being measured
    # is that the command was captured twice, not what the files were called.
    param([string]$Root)
    $captures = @()
    $docsRoot = Join-Path $Root '.docs'
    if (-not (Test-Path $docsRoot)) { return $captures }
    foreach ($meta in (Get-ChildItem -Path $docsRoot -Recurse -File -Filter '*.meta.json' -ErrorAction SilentlyContinue)) {
        $parsed = $null
        try { $parsed = (Get-Content -Path $meta.FullName -Raw -Encoding UTF8) | ConvertFrom-Json -ErrorAction Stop }
        catch { continue }
        $argv = @()
        if ($parsed.PSObject -and ($parsed.PSObject.Properties.Name -contains 'argv')) { $argv = @($parsed.argv) }
        $argvText = ($argv -join ' ')
        if ($argvText -notmatch '(?i)audit') { continue }
        $bodyPath = $meta.FullName.Substring(0, $meta.FullName.Length - '.meta.json'.Length)
        $exit = $null
        if ($parsed.PSObject.Properties.Name -contains 'exit_code') { $exit = [int]$parsed.exit_code }
        $finished = ''
        if ($parsed.PSObject.Properties.Name -contains 'finished') { $finished = "$($parsed.finished)" }
        $captures += [PSCustomObject]@{
            Body     = Get-NormalizedPath ($bodyPath.Substring($Root.Length))
            BodyOk   = (Test-Path $bodyPath)
            ExitCode = $exit
            Finished = $finished
            Argv     = $argvText
        }
    }
    return $captures
}

# --- Locate the run's git history --------------------------------------------
$commitsAfterBase = @()
$commitFiles = @()
$gitOk = $false
if (Test-Path (Join-Path $TargetDir '.git')) {
    $log = & git -C $TargetDir log --format='%H%x09%s' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $gitOk = $true
        foreach ($entry in @($log | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
            $parts = "$entry" -split "`t", 2
            if ($parts.Count -lt 2) { continue }
            if ($parts[1].Trim() -eq 'base') { continue }
            $commitsAfterBase += [PSCustomObject]@{ Sha = $parts[0]; Subject = $parts[1].Trim(); Files = @() }
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

# --- [1] an `## Upgrade brief` naming the renamed API -------------------------
# Scope is deliberately narrow: handoff.txt, anything under .docs/, and
# top-level *.md. The temp copy also contains the plugin's own skills/ and
# references/, which quote `## Upgrade brief`, makeSlug and toSlug verbatim in
# the contract and its template - searching those would pass every run.
$briefCandidates = @()
$handoff = Join-Path $TargetDir 'handoff.txt'
if (Test-Path $handoff) { $briefCandidates += (Get-Item $handoff) }
$docsRoot = Join-Path $TargetDir '.docs'
if (Test-Path $docsRoot) {
    $briefCandidates += @(Get-ChildItem -Path $docsRoot -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in @('.md', '.txt') })
}
$briefCandidates += @(Get-ChildItem -Path $TargetDir -File -Filter '*.md' -ErrorAction SilentlyContinue)

$briefFile = ''
$briefSection = ''
foreach ($candidate in $briefCandidates) {
    $text = ''
    try { $text = (Get-Content -Path $candidate.FullName -Raw -Encoding UTF8) -replace "`r`n", "`n" }
    catch { continue }
    $match = [regex]::Match($text, '(?ms)^##[^\S\n]*Upgrade[^\S\n]+brief[^\S\n]*$(.*?)(?=^##[^\S\n]|\z)')
    if (-not $match.Success) { continue }
    $briefFile = Get-NormalizedPath ($candidate.FullName.Substring($TargetDir.Length))
    $briefSection = $match.Groups[1].Value
    break
}

if ([string]::IsNullOrWhiteSpace($briefFile)) {
    Add-Failure '1' "no ``## Upgrade brief`` heading in handoff.txt, under .docs/, or in a top-level .md - Step 1 requires the brief before the lockfile moves, so its absence means the changelog reading either never happened or was never written down"
} else {
    $briefProblems = New-Object System.Collections.Generic.List[string]
    foreach ($token in @($oldApi, $newApi, $newVersion)) {
        if ("$briefSection" -cnotmatch [regex]::Escape($token)) {
            $briefProblems.Add("the section never names '$token'")
        }
    }
    if ($briefProblems.Count -gt 0) {
        Add-Failure '1' "``## Upgrade brief`` found in $briefFile but it does not carry the breaking change: $($briefProblems -join '; '). A brief that does not name the removed API and its replacement records that a changelog was opened, not what it said"
    } else {
        Write-Output "[1] PASSED: ``## Upgrade brief`` in $briefFile names $oldApi, $newApi and $newVersion"
    }
}

# --- [2] two sidecar-backed audit captures: exit 1 then exit 0 ----------------
$auditCaptures = @(Get-AuditCaptures -Root $TargetDir)
$before = @($auditCaptures | Where-Object { $_.ExitCode -eq 1 } | Sort-Object Finished)
$after = @($auditCaptures | Where-Object { $_.ExitCode -eq 0 } | Sort-Object Finished)
$captureProblems = New-Object System.Collections.Generic.List[string]

if ($auditCaptures.Count -eq 0) {
    $captureProblems.Add('no run_quiet.py sidecar under .docs/ records an audit command at all - the audit was narrated, or never run')
} else {
    if ($before.Count -eq 0) {
        $captureProblems.Add("no capture records exit_code 1. ``node scripts/audit.js`` exits 1 only while $package@$oldVersion is pinned, so a missing exit-1 capture means nothing was captured BEFORE the bump")
    }
    if ($after.Count -eq 0) {
        $captureProblems.Add("no capture records exit_code 0, which is what the audit returns once $package@$newVersion is pinned - nothing was captured after the bump")
    }
    if ($before.Count -gt 0 -and $after.Count -gt 0) {
        if ($before[0].Body -eq $after[$after.Count - 1].Body) {
            $captureProblems.Add('the before and after captures are the same file - one capture overwritten twice is not a comparison')
        }
        if ($before[0].Finished -gt $after[$after.Count - 1].Finished) {
            $captureProblems.Add("the exit-1 capture finished at $($before[0].Finished), after the exit-0 capture at $($after[$after.Count - 1].Finished)")
        }
    }
    foreach ($capture in $auditCaptures) {
        if (-not $capture.BodyOk) {
            $captureProblems.Add("$($capture.Body) has a sidecar but no capture body beside it")
        }
    }
}
if ($captureProblems.Count -gt 0) {
    $observed = 'none'
    if ($auditCaptures.Count -gt 0) {
        $observed = (($auditCaptures | Sort-Object Finished |
                ForEach-Object { "$($_.Body) exit=$($_.ExitCode) finished=$($_.Finished)" }) -join ' ; ')
    }
    Add-Failure '2' "the before/after audit comparison is not on disk: $($captureProblems -join '; '). Captures found: $observed"
} else {
    Write-Output "[2] PASSED: $($before[0].Body) at exit_code 1 and $($after[$after.Count - 1].Body) at exit_code 0, both sidecar-backed - the exit-1 capture could only have been taken while $oldVersion was still pinned"
}

# --- [3] exactly one commit touching the manifest, lockfile and call site -----
$commitProblems = New-Object System.Collections.Generic.List[string]
$bumpCommit = $null
if (-not $gitOk) {
    $commitProblems.Add("no readable git repository at $TargetDir - the Command block's git init did not take (classify INFRA)")
} elseif ($commitsAfterBase.Count -lt 1) {
    $commitProblems.Add('no commit exists after ''base'' - Step 6 requires the bump to land as one commit, and nothing was committed')
} else {
    $matched = @($commitsAfterBase | Where-Object { Test-SameFileSet -Left $_.Files -Right $expectedCommitFiles })
    if ($matched.Count -eq 1) { $bumpCommit = $matched[0] }
    if ($matched.Count -eq 0) {
        $observed = ($commitsAfterBase | ForEach-Object { "'$($_.Subject)' [$((Get-SortedPathSet -Paths $_.Files) -join ', ')]" }) -join ' ; '
        $commitProblems.Add("no commit after 'base' carries exactly [$((Get-SortedPathSet -Paths $expectedCommitFiles) -join ', ')]; commits found: $observed")
    } elseif ($matched.Count -gt 1) {
        $commitProblems.Add("$($matched.Count) commits carry that same file set - the bump was committed more than once")
    }
    foreach ($commit in $commitsAfterBase) {
        if ($null -ne $bumpCommit -and $commit.Sha -eq $bumpCommit.Sha) { continue }
        $outside = @(@($commit.Files) | Where-Object { $_ -notmatch '(?i)^\.docs/' })
        if ($outside.Count -gt 0) {
            $commitProblems.Add("the commit '$($commit.Subject)' also touches source outside the bump: $($outside -join ', ')")
        }
    }
}
if ($commitProblems.Count -gt 0) {
    Add-Failure '3' "the bump is not one self-contained commit: $($commitProblems -join '; '). One package per commit, lockfile with it, is what makes ``git revert <sha>`` the rollback"
} else {
    $extra = $commitsAfterBase.Count - 1
    Write-Output "[3] PASSED: one commit ('$($bumpCommit.Subject)') carrying package.json, package-lock.json and $callSite; $extra further .docs/-only commit(s)"
}

# --- [4] tests/ is byte-identical and no commit touched it -------------------
$testDrift = @(Get-TreeDrift -FixtureSubdir (Join-Path $fixtureDir 'tests') `
        -TargetSubdir (Join-Path $TargetDir 'tests') -Label 'tests')
$testFilesCommitted = @($commitFiles | Where-Object { $_ -match '(?i)^tests/' })
if ($testDrift.Count -gt 0 -or $testFilesCommitted.Count -gt 0) {
    $detail = @()
    if ($testDrift.Count -gt 0) { $detail += ($testDrift -join '; ') }
    if ($testFilesCommitted.Count -gt 0) { $detail += "committed: $($testFilesCommitted -join ', ')" }
    Add-Failure '4' "the frozen suite moved - $($detail -join ' | '). The upgrade is provable through buildReport(), whose name and behaviour do not change, so nothing here needed a test edit"
} else {
    Write-Output '[4] PASSED: tests/ is byte-identical to the frozen fixture and no commit touched it'
}

# --- [5] the bump landed in manifest, lockfile and call site ------------------
$bumpProblems = New-Object System.Collections.Generic.List[string]
$manifestPath = Join-Path $TargetDir 'package.json'
if (-not (Test-Path $manifestPath)) {
    $bumpProblems.Add('package.json is missing from the working copy')
} else {
    $manifest = $null
    try { $manifest = (Get-Content -Path $manifestPath -Raw -Encoding UTF8) | ConvertFrom-Json -ErrorAction Stop }
    catch { $bumpProblems.Add("package.json is not valid JSON: $($_.Exception.Message)") }
    if ($null -ne $manifest) {
        $pinned = ''
        if ($manifest.devDependencies -and ($manifest.devDependencies.PSObject.Properties.Name -contains $package)) {
            $pinned = "$($manifest.devDependencies.$package)"
        }
        if ($pinned -ne $newVersion) {
            $bumpProblems.Add("devDependencies.$package is '$pinned', expected the exact pin '$newVersion' (a range is not a pin)")
        }
    }
}
$lockPath = Join-Path $TargetDir 'package-lock.json'
if (-not (Test-Path $lockPath)) {
    $bumpProblems.Add('package-lock.json is missing from the working copy')
} else {
    $lockText = (Get-Content -Path $lockPath -Raw -Encoding UTF8)
    if ("$lockText" -cnotmatch [regex]::Escape($newVersion)) { $bumpProblems.Add("package-lock.json never names $newVersion - the manifest moved and the lockfile did not") }
    if ("$lockText" -cmatch [regex]::Escape($oldVersion)) { $bumpProblems.Add("package-lock.json still names $oldVersion") }
}
$callSitePath = Join-Path $TargetDir ($callSite -replace '/', '\')
if (-not (Test-Path $callSitePath)) {
    $bumpProblems.Add("$callSite is missing from the working copy")
} else {
    $callSiteText = (Get-Content -Path $callSitePath -Raw -Encoding UTF8)
    $code = Get-CodeOnlyText -Text $callSiteText
    if ("$code" -cmatch [regex]::Escape($oldApi)) { $bumpProblems.Add("$callSite still calls $oldApi in code") }
    if ("$code" -cnotmatch [regex]::Escape($newApi)) { $bumpProblems.Add("$callSite never calls $newApi") }
}
if ($bumpProblems.Count -gt 0) {
    Add-Failure '5' "the bump did not land cleanly: $($bumpProblems -join '; ')"
} else {
    Write-Output "[5] PASSED: $package pinned and locked at $newVersion, and $callSite calls $newApi"
}

# --- [6] the suite is green, proven by the grader's own bare `node --test` ----
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($null -eq $nodeCmd) {
    Add-Failure '6' 'no node runtime on this machine, so the suite could not be re-run here - classify a sweep of these as INFRA rather than reading them as a plugin result'
} else {
    # Bare `node --test` from inside the working copy, never `node --test <dir>`:
    # Node 24 reads a positional as a FILE to execute and dies with
    # MODULE_NOT_FOUND, which reads as a red suite (verified 2026-09-04).
    Push-Location $TargetDir
    try {
        $testOutput = & $nodeCmd.Source --test 2>&1
        $testExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($testExit -ne 0) {
        $tail = (($testOutput | Out-String) -split "`n" | Where-Object { $_ -match '(?i)(^. (pass|fail) |not ok )' } | Select-Object -First 6) -join ' / '
        Add-Failure '6' "the grader's own bare ``node --test`` is red on the delivered tree (exit $testExit): $tail"
    } else {
        Write-Output "[6] PASSED: the grader's own bare ``node --test`` is green on the delivered tree"
    }
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
