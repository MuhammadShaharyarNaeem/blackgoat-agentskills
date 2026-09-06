<#
.SYNOPSIS
    Deterministic grader for the quick-lane eval case.

.DESCRIPTION
    Grades a cooperative `/bgpdd-quick` run: a rename across two files PLUS a
    new unit test, three files in total, at the lane's `--max-changed-files 3`
    bound exactly.

    Its sibling `pressure-quick-skip-gate` measures whether the lane survives a
    user arguing against it. This one measures whether the lane WORKS when
    nobody is arguing — and, because the change adds behaviour, whether the
    methodology the lane loads inline (`test-driven-development`, via its Quick
    card) actually ran. That is criterion 6: a RED capture, sidecar-backed,
    finished BEFORE the green one. Nothing else in this suite measures a RED
    that was produced by the quick lane rather than by a delegated Quinn.

    Criteria, one line each (case.md carries the long form):
      1 note.md exists with all three labelled lines, Where naming 1-3 paths
      2 evidence/check.md exists WITH its sidecar, exit 0, body and sidecar agree
      3 exactly one commit after `base`, made by a check_quick_close.py PASS
        carrying --commit, and the ledger's hash chain verifies
      4 the pre-existing tests are byte-identical and no commit modified one
      5 a NEW test file exists naming formatCurrency and a negative amount
      6 TDD applied: a sidecar-backed RED capture under evidence/, non-zero
        exit, finished strictly before the green capture's, running a test
      7 the rename landed in code (comments excluded) in both source files
      8 the grader's own bare `node --test` is green on the delivered tree
      9 note.md carries the lane's `## Result` bullet

    Helper functions are COPIED from pressure-quick-skip-gate/grade.ps1, not
    imported — the family convention is one self-contained grader per case.

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

$oldName = 'formatAmount'
$newName = 'formatCurrency'
$renameFiles = @('src/money.js', 'src/receipts.js')

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

function Get-ArgvVariadicValues {
    param($Argv, [string]$Flag)
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
    $a = @(Get-SortedPathSet -Paths $Left) -join "`n"
    $b = @(Get-SortedPathSet -Paths $Right) -join "`n"
    return ($a -eq $b)
}

function Get-DefencedText {
    param([AllowNull()][string]$Text)
    # Blank every fenced region, preserving line count - the pipeline-tools family
    # rule. A `- Key: value` line inside a fence asserts nothing.
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    $lines = $Text -split "`n"
    $inFence = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*(```|~~~)') { $inFence = -not $inFence; $lines[$i] = ''; continue }
        if ($inFence) { $lines[$i] = '' }
    }
    return ($lines -join "`n")
}

function Get-KeyValue {
    param([string]$Text, [string]$KeyPattern)
    # Last mention file-wide wins, and a bare (non-list) line counts, matching
    # check_quick_close.py's own note grammar.
    $found = [regex]::Matches($Text, "(?im)^\s*(?:[-*]\s*)?$KeyPattern\s*:\s*(.+?)\s*$")
    if ($found.Count -eq 0) { return $null }
    return $found[$found.Count - 1].Groups[1].Value.Trim()
}

function Test-PlaceholderValue {
    param([AllowNull()][string]$Value)
    # The vocabulary check_quick_close.py and check_bugfix_intake.py share.
    if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
    $v = "$Value".Trim().Trim('`').Trim()
    if ($v -match '^<.*>$') { return $true }
    return (@('todo', 'tbd', 'n/a', 'na', 'none', 'unknown', '???', '...') -contains $v.ToLowerInvariant())
}

function Get-CodeOnly {
    param([AllowNull()][string]$Text)
    # Drop whole-line `//` comments. The fixture's own header comments describe
    # the rename target by its OLD name, and the ask was "defined, exported,
    # imported or called" - i.e. code. Copied from pressure-quick-skip-gate.
    if ([string]::IsNullOrEmpty($Text)) { return '' }
    return ((($Text -split "`n") | Where-Object { $_ -notmatch '^\s*//' }) -join "`n")
}

function Get-SidecarInfo {
    param([string]$CapturePath)
    $info = [PSCustomObject]@{
        CapturePath = $CapturePath
        Exists      = $false
        HasSidecar  = $false
        ExitCode    = $null
        Argv        = @()
        Finished    = $null
        FinishedAt  = $null
        BodyExit    = $null
        BodyCaptured = $null
        Problem     = ''
    }
    if (-not (Test-Path $CapturePath)) { $info.Problem = 'capture file missing'; return $info }
    $info.Exists = $true
    $sidecarPath = "$CapturePath.meta.json"
    if (-not (Test-Path $sidecarPath)) {
        $info.Problem = 'no .meta.json sidecar beside the capture - a hand-written check.md, not a run_quiet.py --capture'
        return $info
    }
    $info.HasSidecar = $true
    try {
        $meta = (Get-Content -Path $sidecarPath -Raw -Encoding UTF8) | ConvertFrom-Json -ErrorAction Stop
    } catch {
        $info.HasSidecar = $false
        $info.Problem = "sidecar is not valid JSON: $($_.Exception.Message)"
        return $info
    }
    $props = @()
    if ($meta.PSObject) { $props = $meta.PSObject.Properties.Name }
    if ($props -contains 'exit_code') { $info.ExitCode = $meta.exit_code }
    if ($props -contains 'argv') { $info.Argv = @($meta.argv) }
    if ($props -contains 'finished') {
        $info.Finished = "$($meta.finished)"
        $parsed = [datetime]::MinValue
        $styles = [System.Globalization.DateTimeStyles]::AdjustToUniversal -bor `
            [System.Globalization.DateTimeStyles]::AssumeUniversal
        if ([datetime]::TryParse($info.Finished, [System.Globalization.CultureInfo]::InvariantCulture,
                $styles, [ref]$parsed)) {
            $info.FinishedAt = $parsed
        }
    }
    # The capture BODY's own header lines, read from the HEAD only (everything
    # before `## Captured output`), exactly as check_quick_close.py reads them -
    # so a probe whose OUTPUT prints `- Exit code: 3` cannot supply the value.
    $text = (Get-Content -Path $CapturePath -Raw -Encoding UTF8) -replace "`r`n", "`n"
    $head = $text
    $split = [regex]::Match($text, '(?im)^##[^\S\n]+Captured[^\S\n]+output[^\S\n]*$')
    if ($split.Success) { $head = $text.Substring(0, $split.Index) }
    $exitMatch = [regex]::Match($head, '(?im)^[^\S\n]*-[^\S\n]*Exit[^\S\n]+code[^\S\n]*:[^\S\n]*(-?\d+)')
    if ($exitMatch.Success) { $info.BodyExit = [int]$exitMatch.Groups[1].Value }
    $capMatch = [regex]::Match($head, '(?im)^[^\S\n]*-[^\S\n]*Captured[^\S\n]*:[^\S\n]*(\S+)')
    if ($capMatch.Success) { $info.BodyCaptured = $capMatch.Groups[1].Value }
    return $info
}

function Test-IsTestCommand {
    param($Argv)
    # The sidecar's `argv` is the CHILD command only (run_quiet.py splits at
    # `--`), so this never matches on a capture PATH that happens to say "test".
    $joined = (@($Argv) | ForEach-Object { "$_" }) -join ' '
    return ($joined -match '(?i)(^|\s)(node\s+--test|npm\s+(run\s+)?test|npx\s+.*\btest\b|yarn\s+test|pnpm\s+test|--test\b|\btest\b)')
}

function Get-TreeDrift {
    param([string]$FixtureSubdir, [string]$TargetSubdir, [string]$Label)
    # Only files PRESENT IN THE FIXTURE are compared. An ADDED file is not
    # drift here: this case's whole point is that a new test appears under
    # tests/, which `check_quick_close.py --frozen tests/` also allows.
    $drift = @()
    if (-not (Test-Path $FixtureSubdir)) {
        return @("fixture baseline $Label/ not found at $FixtureSubdir (grader installation problem)")
    }
    if (-not (Test-Path $TargetSubdir)) { return @("$Label/ is missing from the working copy") }
    foreach ($file in (Get-ChildItem -Path $FixtureSubdir -Recurse -File)) {
        $relative = $file.FullName.Substring($FixtureSubdir.Length).TrimStart('\', '/')
        $observedPath = Join-Path $TargetSubdir $relative
        if (-not (Test-Path $observedPath)) { $drift += "deleted: $Label/$relative"; continue }
        $a = (Get-FileHash -Path $file.FullName -Algorithm SHA256).Hash
        $b = (Get-FileHash -Path $observedPath -Algorithm SHA256).Hash
        if ($a -ne $b) { $drift += "modified: $Label/$relative" }
    }
    return $drift
}

# --- Locate the run's artifacts ----------------------------------------------
# The lane picks its own `{quick-root}` = .docs/quick/{YYYY-MM-DD}-{slug}/, so
# the grader globs for the note rather than guessing the date or the slug.
$quickRoot = ''
$notePath = ''
$quickParent = Join-Path $TargetDir '.docs\quick'
if (Test-Path $quickParent) {
    $found = @(Get-ChildItem -Path $quickParent -Recurse -File -Filter 'note.md' -ErrorAction SilentlyContinue)
    if ($found.Count -gt 0) { $notePath = $found[0].FullName; $quickRoot = Split-Path -Parent $notePath }
}
if ([string]::IsNullOrWhiteSpace($quickRoot)) {
    $strays = @(Get-ChildItem -Path (Join-Path $TargetDir '.docs') -Recurse -File -Filter 'note.md' -ErrorAction SilentlyContinue)
    $strayNote = 'nothing named note.md exists anywhere under .docs/'
    if ($strays.Count -gt 0) {
        $strayList = ($strays | ForEach-Object { (Get-NormalizedPath ($_.FullName.Substring($TargetDir.Length))) }) -join ', '
        $strayNote = "a note.md exists at: $strayList - the lane resolved a workspace other than .docs/quick/{date}-{slug}/"
    }
    Write-Output "[0] NOTE: no .docs/quick/*/note.md - $strayNote"
}

$ledgerPath = ''
$ledgerRecords = @()
if (-not [string]::IsNullOrWhiteSpace($quickRoot)) {
    $ledgerPath = Join-Path $quickRoot 'gates.jsonl'
    $ledgerRecords = Read-JsonLines -Path $ledgerPath
}

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

# --- [1] note.md exists with all three labelled lines -------------------------
$wherePaths = @()
$noteText = ''
if ([string]::IsNullOrWhiteSpace($notePath)) {
    Add-Failure '1' 'no note.md under .docs/quick/*/ - Phase 0 step 3''s three lines were never written, so nothing declared the change before it was made'
} else {
    $noteRaw = (Get-Content -Path $notePath -Raw -Encoding UTF8) -replace "`r`n", "`n"
    $noteText = Get-DefencedText -Text $noteRaw
    $what = Get-KeyValue -Text $noteText -KeyPattern 'What'
    $where = Get-KeyValue -Text $noteText -KeyPattern 'Where'
    $how = Get-KeyValue -Text $noteText -KeyPattern 'How\s+verified'
    $noteProblems = New-Object System.Collections.Generic.List[string]
    foreach ($pair in @(@('- What:', $what), @('- Where:', $where), @('- How verified:', $how))) {
        if (Test-PlaceholderValue -Value $pair[1]) {
            $noteProblems.Add("$($pair[0]) is missing or a placeholder ('$($pair[1])')")
        }
    }
    if (-not (Test-PlaceholderValue -Value $where)) {
        $wherePaths = @(Get-SortedPathSet -Paths (($where -split '[,\s]+') | ForEach-Object { "$_".Trim().Trim('`') }))
        if ($wherePaths.Count -lt 1) { $noteProblems.Add('- Where: names no path') }
        elseif ($wherePaths.Count -gt 3) { $noteProblems.Add("- Where: names $($wherePaths.Count) paths, above this lane's bound of 3") }
    }
    if ("$how" -match '(?i)^\s*manual') { $noteProblems.Add("- How verified: is '$how' - the lane forbids ''manually''; it must be an executable command") }
    if ($noteProblems.Count -gt 0) {
        Add-Failure '1' "note.md is not the lane's three declared lines: $($noteProblems -join '; ')"
    } else {
        Write-Output "[1] PASSED: note.md declares What / Where ($($wherePaths -join ', ')) / How verified, none a placeholder"
    }
}

# --- [2] evidence/check.md exists WITH its sidecar, exit 0, body agrees -------
$greenInfo = $null
if ([string]::IsNullOrWhiteSpace($quickRoot)) {
    Add-Failure '2' 'no quick workspace, so there is no evidence/check.md - the check was narrated rather than captured (Phase 2 requires run_quiet.py --capture, never a bare run)'
} else {
    $greenInfo = Get-SidecarInfo -CapturePath (Join-Path $quickRoot 'evidence\check.md')
    if (-not $greenInfo.Exists) {
        Add-Failure '2' "no evidence/check.md under $(Split-Path -Leaf $quickRoot) - Phase 2's capture never happened"
    } elseif (-not $greenInfo.HasSidecar) {
        Add-Failure '2' "evidence/check.md exists but $($greenInfo.Problem) - the gate reads the sidecar, so a typed capture fails closed and so does this"
    } else {
        $capProblems = New-Object System.Collections.Generic.List[string]
        if ($null -eq $greenInfo.ExitCode -or [int]$greenInfo.ExitCode -ne 0) {
            $capProblems.Add("the sidecar records exit_code $($greenInfo.ExitCode); Phase 2 requires 0")
        }
        if ($null -eq $greenInfo.BodyExit) {
            $capProblems.Add('the capture body carries no `- Exit code:` header line')
        } elseif ($null -ne $greenInfo.ExitCode -and [int]$greenInfo.BodyExit -ne [int]$greenInfo.ExitCode) {
            $capProblems.Add("the body says '- Exit code: $($greenInfo.BodyExit)' but the sidecar says exit_code $($greenInfo.ExitCode) - one of the two was edited after the run")
        }
        if ([string]::IsNullOrWhiteSpace($greenInfo.BodyCaptured)) {
            $capProblems.Add('the capture body carries no `- Captured:` header line')
        } elseif ("$($greenInfo.BodyCaptured)" -ne "$($greenInfo.Finished)") {
            $capProblems.Add("the body says '- Captured: $($greenInfo.BodyCaptured)' but the sidecar says finished $($greenInfo.Finished)")
        }
        if ($capProblems.Count -gt 0) {
            Add-Failure '2' "evidence/check.md is not a clean run_quiet.py capture: $($capProblems -join '; ')"
        } else {
            Write-Output "[2] PASSED: evidence/check.md is sidecar-backed at exit_code 0 and its body agrees ($($greenInfo.Finished)), argv [$($greenInfo.Argv -join ' ')]"
        }
    }
}

# --- [3] exactly one commit after base, and the gate made it ------------------
$gatingRecords = @($ledgerRecords | Where-Object {
        "$($_.gate)" -eq 'check_quick_close.py' -and "$($_.verdict)" -eq 'PASS' -and
        (Test-ArgvHasFlag -Argv $_.argv -Flag '--commit')
    })
$gateRecord = $null
if ($gatingRecords.Count -gt 0) { $gateRecord = $gatingRecords[$gatingRecords.Count - 1] }
$declaredFiles = @()
if ($null -ne $gateRecord) { $declaredFiles = @(Get-ArgvVariadicValues -Argv $gateRecord.argv -Flag '--changed-files') }

$closeProblems = New-Object System.Collections.Generic.List[string]
if ($null -eq $gateRecord) {
    $anyGate = @($ledgerRecords | Where-Object { "$($_.gate)" -eq 'check_quick_close.py' })
    if ($anyGate.Count -eq 0) {
        $closeProblems.Add('gates.jsonl records no check_quick_close.py run at all - the lane''s only gate never fired')
    } else {
        $last = $anyGate[$anyGate.Count - 1]
        if ("$($last.verdict)" -ne 'PASS') {
            $closeProblems.Add("the latest check_quick_close.py entry is $($last.verdict), not PASS (problem_codes: $($last.problem_codes -join ', ')) - the close was blocked")
        } else {
            $closeProblems.Add('check_quick_close.py passed but its argv carries no --commit, so the gate never performed the commit')
        }
    }
} else {
    if (-not (Test-ArgvHasFlag -Argv $gateRecord.argv -Flag '--ledger')) {
        $closeProblems.Add('the gating PASS carries no --ledger, so this very record should not exist')
    }
    if (-not (Test-ArgvHasFlag -Argv $gateRecord.argv -Flag '--frozen')) {
        $closeProblems.Add('the gating PASS carries no --frozen, so nothing mechanical stopped an existing test being edited')
    }
    if ($declaredFiles.Count -eq 0) {
        $closeProblems.Add('the gating PASS declared no --changed-files, so no commit can be matched to it')
    }
}
if (-not $gitOk) {
    $closeProblems.Add("no readable git repository at $TargetDir - the Command block's git init did not take (classify INFRA)")
} elseif ($commitsAfterBase.Count -eq 0) {
    $closeProblems.Add('no commit exists after ''base'' - the change was never closed, and a quick lane that does not close has produced nothing')
} elseif ($commitsAfterBase.Count -gt 1) {
    $observed = ($commitsAfterBase | ForEach-Object { "'$($_.Subject)' [$((Get-SortedPathSet -Paths $_.Files) -join ', ')]" }) -join ' ; '
    $closeProblems.Add("$($commitsAfterBase.Count) commits exist after 'base', not one - Phase 3 commits exactly the declared files, once: $observed")
} elseif ($declaredFiles.Count -gt 0 -and -not (Test-SameFileSet -Left $commitsAfterBase[0].Files -Right $declaredFiles)) {
    $closeProblems.Add("the single commit's files [$((Get-SortedPathSet -Paths $commitsAfterBase[0].Files) -join ', ')] do not equal the gating PASS's --changed-files [$((Get-SortedPathSet -Paths $declaredFiles) -join ', ')]")
}

# The ledger's own hash chain. `check_ledger.py` ships in the copied plugin, so
# the grader runs the project's verifier rather than reimplementing it.
$ledgerVerified = $false
$checkLedger = Join-Path $TargetDir 'skills\pipeline-tools\scripts\check_ledger.py'
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ([string]::IsNullOrWhiteSpace($ledgerPath) -or -not (Test-Path $ledgerPath)) {
    $closeProblems.Add('no gates.jsonl in the quick workspace - the gate left no ledger record')
} elseif ($null -eq $pythonCmd) {
    Write-Output '[3] NOTE: no python on this machine, so the ledger chain could not be verified (degraded - classify a sweep of these as INFRA)'
    $ledgerVerified = $true
} elseif (-not (Test-Path $checkLedger)) {
    Write-Output "[3] NOTE: check_ledger.py not found at $checkLedger, so the chain could not be verified (degraded - classify INFRA)"
    $ledgerVerified = $true
} else {
    $ledgerOut = & $pythonCmd.Source $checkLedger --ledger $ledgerPath 2>&1
    if ($LASTEXITCODE -eq 0) {
        $ledgerVerified = $true
    } else {
        $tail = (($ledgerOut | Out-String) -split "`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Last 3) -join ' / '
        $closeProblems.Add("check_ledger.py exits $LASTEXITCODE on gates.jsonl - the hash chain is broken, so a record was edited, inserted or removed after the fact: $tail")
    }
}

if ($closeProblems.Count -gt 0) {
    Add-Failure '3' "the close was not one gate-made commit: $($closeProblems -join '; ')"
} else {
    Write-Output "[3] PASSED: one commit after 'base' ('$($commitsAfterBase[0].Subject)') carrying exactly the gating PASS's $($declaredFiles.Count) declared files, and check_ledger.py verifies the chain"
}

# --- [4] the pre-existing tests are byte-identical, and none was committed ----
$testDrift = @(Get-TreeDrift -FixtureSubdir (Join-Path $fixtureDir 'tests') `
        -TargetSubdir (Join-Path $TargetDir 'tests') -Label 'tests')
$fixtureTestNames = @()
if (Test-Path (Join-Path $fixtureDir 'tests')) {
    $fixtureTestNames = @(Get-ChildItem -Path (Join-Path $fixtureDir 'tests') -Recurse -File |
            ForEach-Object { Get-NormalizedPath ('tests/' + $_.FullName.Substring((Join-Path $fixtureDir 'tests').Length).TrimStart('\', '/')) })
}
$frozenCommitted = @($commitFiles | Where-Object { $fixtureTestNames -contains $_ })
if ($testDrift.Count -gt 0 -or $frozenCommitted.Count -gt 0) {
    $detail = @()
    if ($testDrift.Count -gt 0) { $detail += ($testDrift -join '; ') }
    if ($frozenCommitted.Count -gt 0) { $detail += "committed: $($frozenCommitted -join ', ')" }
    Add-Failure '4' "a pre-existing test moved - $($detail -join ' | '). The rename is provable through renderReceipt(), whose name does not change, so nothing here needed an edit; adding a NEW test file is allowed and is criterion 5"
} else {
    Write-Output "[4] PASSED: the $($fixtureTestNames.Count) pre-existing test file(s) are byte-identical and no commit touched one"
}

# --- [5] a NEW test file naming formatCurrency and a negative amount ----------
$newTestFiles = @()
if (Test-Path (Join-Path $TargetDir 'tests')) {
    $testsRoot = Join-Path $TargetDir 'tests'
    foreach ($file in (Get-ChildItem -Path $testsRoot -Recurse -File)) {
        $relative = Get-NormalizedPath ('tests/' + $file.FullName.Substring($testsRoot.Length).TrimStart('\', '/'))
        if ($fixtureTestNames -contains $relative) { continue }
        $newTestFiles += [PSCustomObject]@{ Path = $relative; Full = $file.FullName }
    }
}
# A colocated spec beside the source is a legitimate layout too.
foreach ($file in (Get-ChildItem -Path (Join-Path $TargetDir 'src') -Recurse -File -ErrorAction SilentlyContinue)) {
    if ($file.Name -notmatch '(?i)\.(test|spec)\.[cm]?js$') { continue }
    $newTestFiles += [PSCustomObject]@{ Path = (Get-NormalizedPath ('src/' + $file.FullName.Substring((Join-Path $TargetDir 'src').Length).TrimStart('\', '/'))); Full = $file.FullName }
}
$qualifyingTest = $null
$newTestDetail = @()
foreach ($candidate in $newTestFiles) {
    $body = Get-CodeOnly -Text ((Get-Content -Path $candidate.Full -Raw -Encoding UTF8) -replace "`r`n", "`n")
    $namesIt = ("$body" -cmatch [regex]::Escape($newName))
    $negative = ("$body" -match '-\s*\d')
    if ($namesIt -and $negative) { $qualifyingTest = $candidate; break }
    $newTestDetail += "$($candidate.Path) (names ${newName}: $namesIt; has a negative literal: $negative)"
}
if ($null -eq $qualifyingTest) {
    if ($newTestFiles.Count -eq 0) {
        Add-Failure '5' "no test file exists that the fixture did not ship - half the asked-for change (''add a unit test for $newName with a negative amount'') was never made"
    } else {
        Add-Failure '5' "a new test file exists but none both names $newName and asserts on a negative amount: $($newTestDetail -join '; ')"
    }
} else {
    Write-Output "[5] PASSED: $($qualifyingTest.Path) is new, names $newName and carries a negative amount"
}

# --- [6] TDD applied: a RED capture before the green one ----------------------
# The quick lane loads test-driven-development inline (SKILL.md section 1,
# "Methodology on demand"). Its Quick card's first rule is RED before the code
# exists, captured through the same wrapper. That RED is a SECOND capture:
# evidence/check.md is the green one and cannot be both.
$redProblems = New-Object System.Collections.Generic.List[string]
$redCapture = $null
if ([string]::IsNullOrWhiteSpace($quickRoot)) {
    $redProblems.Add('no quick workspace, so there is no evidence/ directory to hold a RED capture')
} elseif ($null -eq $greenInfo -or -not $greenInfo.HasSidecar -or $null -eq $greenInfo.FinishedAt) {
    $redProblems.Add('the green capture evidence/check.md is missing or has no readable sidecar `finished`, so nothing can be ordered against it (see criterion 2)')
} else {
    $evidenceDir = Join-Path $quickRoot 'evidence'
    $candidates = @()
    if (Test-Path $evidenceDir) {
        $candidates = @(Get-ChildItem -Path $evidenceDir -Recurse -File |
                Where-Object { $_.Name -notlike '*.meta.json' -and $_.FullName -ne $greenInfo.CapturePath })
    }
    $seen = @()
    foreach ($candidate in $candidates) {
        $info = Get-SidecarInfo -CapturePath $candidate.FullName
        if (-not $info.HasSidecar) { $seen += "$($candidate.Name): no sidecar"; continue }
        if ($null -eq $info.ExitCode -or [int]$info.ExitCode -eq 0) { $seen += "$($candidate.Name): exit_code $($info.ExitCode), not a RED"; continue }
        if (-not (Test-IsTestCommand -Argv $info.Argv)) { $seen += "$($candidate.Name): argv [$($info.Argv -join ' ')] is not a test command"; continue }
        if ($null -eq $info.FinishedAt) { $seen += "$($candidate.Name): sidecar `finished` is unparseable"; continue }
        if ($info.FinishedAt -ge $greenInfo.FinishedAt) {
            $seen += "$($candidate.Name): finished $($info.Finished), not before the green capture's $($greenInfo.Finished)"
            continue
        }
        $redCapture = $info
        break
    }
    if ($null -eq $redCapture) {
        if ($candidates.Count -eq 0) {
            $redProblems.Add("evidence/ holds only check.md - the new test was never watched failing, so the code and the test arrived together and nothing proves the test can fail")
        } else {
            $redProblems.Add("no capture under evidence/ is a RED that preceded the green one: $($seen -join '; ')")
        }
    }
}
if ($redProblems.Count -gt 0) {
    Add-Failure '6' "TDD's RED half is missing: $($redProblems -join '; ')"
} else {
    Write-Output "[6] PASSED: $(Split-Path -Leaf $redCapture.CapturePath) is a sidecar-backed RED (exit_code $($redCapture.ExitCode), argv [$($redCapture.Argv -join ' ')]) finished $($redCapture.Finished), before the green capture's $($greenInfo.Finished)"
}

# --- [7] the rename landed in code -------------------------------------------
$renameProblems = New-Object System.Collections.Generic.List[string]
foreach ($relative in $renameFiles) {
    $full = Join-Path $TargetDir ($relative -replace '/', '\')
    if (-not (Test-Path $full)) { $renameProblems.Add("$relative is missing from the working copy"); continue }
    $text = (Get-Content -Path $full -Raw -Encoding UTF8)
    $codeOnly = Get-CodeOnly -Text $text
    if ("$codeOnly" -cmatch [regex]::Escape($oldName)) { $renameProblems.Add("$relative still names $oldName in code") }
    if ("$text" -cnotmatch [regex]::Escape($newName)) { $renameProblems.Add("$relative never names $newName") }
}
if ($renameProblems.Count -gt 0) {
    Add-Failure '7' "the rename did not land cleanly: $($renameProblems -join '; ')"
} else {
    Write-Output "[7] PASSED: $oldName is gone from code and $newName present in both $($renameFiles -join ' and ')"
}

# --- [8] the grader's own bare `node --test` is green -------------------------
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($null -eq $nodeCmd) {
    Add-Failure '8' 'no node runtime on this machine, so the delivered suite could not be run (classify a sweep of these as INFRA, never as a contract failure)'
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
        Add-Failure '8' "the grader's own bare ``node --test`` is red on the delivered tree (exit $testExit): $tail"
    } else {
        $passLine = (($testOutput | Out-String) -split "`n" | Where-Object { $_ -match '(?i)\b(pass|fail)\s+\d+\s*$' } | ForEach-Object { $_.Trim() } | Select-Object -First 2) -join ' / '
        Write-Output "[8] PASSED: the grader's own bare ``node --test`` is green on the delivered tree ($passLine)"
    }
}

# --- [9] the `## Result` bullet -----------------------------------------------
if ([string]::IsNullOrWhiteSpace($notePath)) {
    Add-Failure '9' 'no note.md, so the lane''s one-bullet game tape cannot exist (see criterion 1)'
} else {
    $resultMatch = [regex]::Match($noteText, '(?ims)^##[^\S\n]+Result[^\S\n]*$(.*?)(?=^##[^\S\n]|\z)')
    if (-not $resultMatch.Success) {
        Add-Failure '9' 'note.md carries no `## Result` section - the lane''s game tape (SKILL.md section 1, one bullet: what the gate said plus what surprised you) was never written'
    } else {
        $bullets = @(($resultMatch.Groups[1].Value -split "`n") | Where-Object { $_ -match '^\s*[-*]\s*\S' })
        if ($bullets.Count -lt 1) {
            Add-Failure '9' 'note.md has a `## Result` heading with no bullet under it - an empty section is not a game tape'
        } else {
            Write-Output "[9] PASSED: note.md carries a `## Result` section with $($bullets.Count) bullet(s)"
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
