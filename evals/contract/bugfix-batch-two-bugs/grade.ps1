<#
.SYNOPSIS
    Deterministic grader for the bugfix-batch-two-bugs eval case.

.DESCRIPTION
    Grades a full `/bgpdd-bugfix-batch` run of TWO bugs against the frozen
    checkout-svc fixture. Every criterion re-derives from artifacts on disk: a
    `verdict` field in a gates.jsonl is never trusted on its own, because the
    lane's whole claim is that the per-bug bugfix contract ran N times, in its
    own tree, on the bytes that are still there.

    What each criterion catches, in one line each (case.md carries the long form):
      1 the batch root exists and names both bugs, each with its own bug root
      2 two worktrees were created and then removed, evidence surviving
      3 each bug's ledger is hash-chained and holds intake + red/green + a
        commit gate carrying --commit
      4 each bug's RED/GREEN pair is a real before/after, re-read from sidecars
      5 each fix landed through its own gate and is an ancestor of the base
      6 batch.md's final table cites both gated commit shas and their records
      7 the overlap was serialised: the later bug re-ran its GREEN after the
        earlier bug's gated commit, and batch.md names the shared file
      8 neither frozen check was edited, in the tree or in any commit

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no
    `&&`/`||`, and $LASTEXITCODE (never $?) for native exit codes.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in (the batch's MAIN
    tree - the per-bug worktrees are expected to be gone by then).

.OUTPUTS
    Prints "[n] PASSED: ..." / "[n] FAILED: ..." per criterion, then a RESULT
    line. Exit 0 = every criterion passed. Exit 1 = at least one failed. No
    criterion short-circuits another: run against an empty working copy it still
    diffs the frozen files and reports what it found.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

# This grader lives at <plugin>/evals/contract/bugfix-batch-two-bugs/grade.ps1
$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$fixtureDir = Join-Path $evalDir 'fixture'
$fixtureTestsDir = Join-Path $fixtureDir 'tests'
$fixtureRepro = Join-Path $fixtureDir 'scripts\repro-tax.js'

# The one file both fixes must touch - the reason the overlap rule has to fire.
$sharedFile = 'src/pricing.js'

$failures = New-Object System.Collections.Generic.List[string]

function Add-Failure {
    param([string]$Index, [string]$Message)
    $failures.Add("$Index - $Message")
    Write-Output "[$Index] FAILED: $Message"
}

function Get-NormalizedPath {
    param([AllowNull()][string]$Path)
    # Strips a leading `./` and a leading `/`, and NOTHING else. A char-set
    # TrimStart('.', '/') would turn `.docs/x` into `docs/x`, and the leading
    # dot is load-bearing wherever a `.docs/` prefix is tested.
    if ([string]::IsNullOrWhiteSpace($Path)) { return '' }
    $normalized = ($Path -replace '\\', '/').Trim()
    while ($normalized.StartsWith('./')) { $normalized = $normalized.Substring(2) }
    return $normalized.TrimStart('/')
}

function Read-TextLf {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return '' }
    return ((Get-Content -Path $Path -Raw -Encoding UTF8) -replace "`r`n", "`n")
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
    $matching = @($Records | Where-Object { "$($_.gate)" -eq $Gate })
    if ($matching.Count -eq 0) { return $null }
    return $matching[$matching.Count - 1]
}

function Test-ArgvHasFlag {
    param($Argv, [string]$Flag)
    foreach ($item in @($Argv)) { if ("$item" -eq $Flag) { return $true } }
    return $false
}

function Get-ArgvFlagValue {
    param($Argv, [string]$Flag)
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
    $values = @()
    $items = @($Argv)
    for ($i = 0; $i -lt $items.Count; $i++) {
        if ("$($items[$i])" -eq $Flag -and ($i + 1) -lt $items.Count) {
            $values += "$($items[$i + 1])"
        }
    }
    return $values
}

function Get-ArgvVariadicValues {
    param($Argv, [string]$Flag)
    # The values of a variadic flag (`--changed-files p1 p2 ...`): everything
    # after $Flag up to the next token that opens with `--`.
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
    # single-element array on return, so an index-based compare reads two
    # one-file sets as two CHARACTERS and matches on a shared leading letter.
    $a = @(Get-SortedPathSet -Paths $Left) -join "`n"
    $b = @(Get-SortedPathSet -Paths $Right) -join "`n"
    return ($a -eq $b)
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
        Problem     = ''
    }
    if (-not (Test-Path $CapturePath)) {
        $info.Problem = 'capture file missing'
        return $info
    }
    $info.Exists = $true
    $sidecarPath = "$CapturePath.meta.json"
    if (-not (Test-Path $sidecarPath)) {
        $info.Problem = 'no .meta.json sidecar beside the capture (hand-typed, not run_quiet.py --capture)'
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

function Get-PythonExe {
    foreach ($name in @('python', 'python3')) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $cmd) { return $cmd.Source }
    }
    return $null
}

function Get-CheckLedgerScript {
    # Prefer the copy the harness put in the working copy (that is the one the
    # run itself used); fall back to this plugin's own, which is the same file.
    $inCopy = Join-Path $TargetDir 'skills\pipeline-tools\scripts\check_ledger.py'
    if (Test-Path $inCopy) { return $inCopy }
    $inPlugin = Join-Path $evalDir '..\..\..\skills\pipeline-tools\scripts\check_ledger.py'
    if (Test-Path $inPlugin) { return (Resolve-Path $inPlugin).Path }
    return $null
}

# --- Locate the run's artifacts ----------------------------------------------
# The fixture has no `.docs/<project>/` epic, so a correct run resolves the
# STANDALONE route per bug: `.docs/bugfix/{slug}/`, created inside that bug's
# worktree and reaching the main tree with its evidence commit.
$bugRoots = @()
$bugfixParent = Join-Path $TargetDir '.docs\bugfix'
if (Test-Path $bugfixParent) {
    foreach ($found in @(Get-ChildItem -Path $bugfixParent -Recurse -File -Filter 'bug-report.md' -ErrorAction SilentlyContinue)) {
        $bugRoots += (Split-Path -Parent $found.FullName)
    }
}
$strayRoots = @()
if ($bugRoots.Count -lt 2) {
    # Say what WAS found - a bug root still sitting in an unremoved worktree, or
    # a mis-resolved route, must read as itself rather than as a missing file.
    foreach ($stray in @(Get-ChildItem -Path $TargetDir -Recurse -File -Filter 'bug-report.md' -ErrorAction SilentlyContinue)) {
        $parent = Split-Path -Parent $stray.FullName
        if ($bugRoots -notcontains $parent) { $strayRoots += $parent }
    }
    if ($strayRoots.Count -gt 0) {
        Write-Output "[0] NOTE: only $($bugRoots.Count) bug root(s) under .docs/bugfix/ in the main tree; a bug-report.md also exists at: $(($strayRoots | ForEach-Object { Get-NormalizedPath ($_.Substring($TargetDir.Length)) }) -join ', ')"
    } else {
        Write-Output "[0] NOTE: only $($bugRoots.Count) bug root(s) found, and nothing named bug-report.md exists anywhere else under the working copy"
    }
}

$bugs = @()
foreach ($root in $bugRoots) {
    $slug = Split-Path -Leaf $root
    $bugs += [PSCustomObject]@{
        Slug         = $slug
        Root         = $root
        Ledger       = (Join-Path $root 'gates.jsonl')
        Records      = (Read-JsonLines -Path (Join-Path $root 'gates.jsonl'))
        GateRecord   = $null   # the check_commit_gate.py PASS carrying --commit
        DeclaredFiles = @()
        GatedCommit  = $null
        RedGreen     = $null
        GreenLatest  = $null
    }
}
$bugs = @($bugs | Sort-Object Slug)

$batchRoot = ''
$batchMd = ''
$batchParent = Join-Path $TargetDir '.docs\bugfix-batch'
if (Test-Path $batchParent) {
    $found = @(Get-ChildItem -Path $batchParent -Recurse -File -Filter 'batch.md' -ErrorAction SilentlyContinue)
    if ($found.Count -gt 0) {
        $batchMd = $found[0].FullName
        $batchRoot = Split-Path -Parent $batchMd
    }
}
$batchText = Read-TextLf -Path $batchMd

# --- git facts ----------------------------------------------------------------
$gitOk = $false
$commitsAfterBase = @()
$commitFiles = @()
$branches = @()
$worktreeCount = 0
$trackedInBase = @{}
if (Test-Path (Join-Path $TargetDir '.git')) {
    $log = & git -C $TargetDir log --format='%H%x09%cI%x09%s' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $gitOk = $true
        foreach ($entry in @($log | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
            $parts = "$entry" -split "`t", 3
            if ($parts.Count -lt 3) { continue }
            if ($parts[2].Trim() -eq 'base') { continue }
            $commitsAfterBase += [PSCustomObject]@{
                Sha     = $parts[0]
                Instant = (ConvertTo-Instant -Text $parts[1])
                Subject = $parts[2].Trim()
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

        foreach ($line in @(& git -C $TargetDir branch --format='%(refname:short)' 2>$null)) {
            $name = "$line".Trim()
            if (-not [string]::IsNullOrWhiteSpace($name)) { $branches += $name }
        }
        $wtLines = @(& git -C $TargetDir worktree list --porcelain 2>$null |
            Where-Object { "$_" -match '^worktree ' })
        $worktreeCount = $wtLines.Count

        foreach ($line in @(& git -C $TargetDir ls-files 2>$null)) {
            $p = Get-NormalizedPath "$line"
            if (-not [string]::IsNullOrWhiteSpace($p)) { $trackedInBase[$p] = $true }
        }
    }
}

$mergedBranches = @()
if ($gitOk) {
    foreach ($line in @(& git -C $TargetDir branch --merged HEAD --format='%(refname:short)' 2>$null)) {
        $name = "$line".Trim()
        if (-not [string]::IsNullOrWhiteSpace($name)) { $mergedBranches += $name }
    }
}

# --- [1] the batch root exists and names both bugs ----------------------------
$c1 = New-Object System.Collections.Generic.List[string]
if ([string]::IsNullOrWhiteSpace($batchMd)) {
    $c1.Add('no .docs/bugfix-batch/*/batch.md - the batch left no bug list, so nothing records which bugs this session owned')
}
if ($bugs.Count -ne 2) {
    $c1.Add("expected 2 bug roots under .docs/bugfix/, found $($bugs.Count)$(if ($bugs.Count -gt 0) { ": $(($bugs | ForEach-Object { $_.Slug }) -join ', ')" })")
}
if (-not [string]::IsNullOrWhiteSpace($batchText)) {
    foreach ($bug in $bugs) {
        if ($batchText -notlike "*$($bug.Slug)*") {
            $c1.Add("batch.md never names the bug slug '$($bug.Slug)', so that bug was fixed outside the batch's own record")
        }
    }
}
if ($c1.Count -gt 0) {
    Add-Failure '1' "the batch is not recorded as a batch of two: $($c1 -join '; ')"
} else {
    Write-Output "[1] PASSED: $(Get-NormalizedPath ($batchMd.Substring($TargetDir.Length))) names both bug slugs ($(($bugs | ForEach-Object { $_.Slug }) -join ', ')), each with its own bug root"
}

# --- [2] two worktrees were created and then removed --------------------------
$c2 = New-Object System.Collections.Generic.List[string]
if (-not $gitOk) {
    $c2.Add("no readable git repository at $TargetDir")
} else {
    foreach ($bug in $bugs) {
        $expected = "fix/$($bug.Slug)"
        if ($branches -notcontains $expected) {
            $c2.Add("no branch '$expected' - Phase 1 creates one per bug with `git worktree add -b`, and it is what a merge later closes")
        }
        # The bug's evidence reached the MAIN tree tracked, which is only true if
        # Phase 3 step 2(b) committed it before Phase 4 removed that worktree.
        $ledgerRel = Get-NormalizedPath ($bug.Ledger.Substring($TargetDir.Length))
        if (-not $trackedInBase.ContainsKey($ledgerRel)) {
            $c2.Add("$ledgerRel is not tracked in the base tree - the per-bug evidence was never committed, so `git worktree remove` would have destroyed it (spine Phase 3 step 2b)")
        }
    }
    if ($worktreeCount -ne 1) {
        $c2.Add("`git worktree list` reports $worktreeCount worktree(s), expected 1 - Phase 4 removes every per-bug worktree")
    }
}
if ($c2.Count -gt 0) {
    Add-Failure '2' "the per-bug worktrees were not created and removed cleanly: $($c2 -join '; ')"
} else {
    Write-Output "[2] PASSED: both fix/* branches exist, both bugs' ledgers are tracked in the base tree, and exactly one worktree remains"
}

# --- [3] each bug's ledger is chained and complete -----------------------------
$python = Get-PythonExe
$checkLedger = Get-CheckLedgerScript
$c3 = New-Object System.Collections.Generic.List[string]
if ($bugs.Count -eq 0) {
    $c3.Add('no bug root to read a ledger from (see [1])')
}
foreach ($bug in $bugs) {
    if (-not (Test-Path $bug.Ledger)) {
        $c3.Add("$($bug.Slug): no gates.jsonl - no gate in that bug's lane left a record")
        continue
    }
    if ($null -eq $python -or $null -eq $checkLedger) {
        $c3.Add("$($bug.Slug): cannot verify the hash chain (python or check_ledger.py unavailable) - an unperformable check is not a pass")
    } else {
        & $python $checkLedger --ledger $bug.Ledger 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            $c3.Add("$($bug.Slug): check_ledger.py exited $LASTEXITCODE - the ledger's hash chain is broken, so no PASS can be read out of it")
        }
    }
    foreach ($gate in @('check_bugfix_intake.py', 'check_red_green.py')) {
        $rec = Get-LatestGateRecord -Records $bug.Records -Gate $gate
        if ($null -eq $rec) {
            $c3.Add("$($bug.Slug): the ledger records no $gate run")
        } elseif ("$($rec.verdict)" -ne 'PASS') {
            $c3.Add("$($bug.Slug): the latest $gate entry is $($rec.verdict), not PASS")
        }
    }
    $gating = @($bug.Records | Where-Object {
            "$($_.gate)" -eq 'check_commit_gate.py' -and "$($_.verdict)" -eq 'PASS' -and
            (Test-ArgvHasFlag -Argv $_.argv -Flag '--commit')
        })
    if ($gating.Count -eq 0) {
        $anyGate = Get-LatestGateRecord -Records $bug.Records -Gate 'check_commit_gate.py'
        if ($null -eq $anyGate) {
            $c3.Add("$($bug.Slug): no check_commit_gate.py run at all - that bug's fix was committed outside the gate that IS its close")
        } elseif ("$($anyGate.verdict)" -ne 'PASS') {
            $c3.Add("$($bug.Slug): the latest check_commit_gate.py entry is $($anyGate.verdict), not PASS")
        } else {
            $c3.Add("$($bug.Slug): check_commit_gate.py passed but its argv carries no --commit, so the gate never performed the commit")
        }
    } else {
        $bug.GateRecord = $gating[$gating.Count - 1]
        $bug.DeclaredFiles = @(Get-ArgvVariadicValues -Argv $bug.GateRecord.argv -Flag '--changed-files')
        foreach ($flag in @('--verify-tree', '--max-changed-files')) {
            if (-not (Test-ArgvHasFlag -Argv $bug.GateRecord.argv -Flag $flag)) {
                $c3.Add("$($bug.Slug): the commit gate was run without $flag")
            }
        }
        $required = Get-ArgvFlagValue -Argv $bug.GateRecord.argv -Flag '--require-ledger-gates'
        if ([string]::IsNullOrWhiteSpace($required)) {
            $c3.Add("$($bug.Slug): the commit gate was run without --require-ledger-gates, so no sibling gate had to be backed")
        } else {
            foreach ($needed in @('check_bugfix_intake.py', 'check_red_green.py')) {
                if ($required -notlike "*$needed*") {
                    $c3.Add("$($bug.Slug): --require-ledger-gates '$required' does not name $needed")
                }
            }
        }
    }
}
if ($c3.Count -gt 0) {
    Add-Failure '3' "a bug's gate chain is incomplete: $($c3 -join '; ')"
} else {
    Write-Output "[3] PASSED: both bugs' ledgers verify with check_ledger.py and each holds intake PASS, red/green PASS and a commit-gate PASS carrying --commit"
}

# --- [4] each bug's RED/GREEN pair is a real before/after ----------------------
$c4 = New-Object System.Collections.Generic.List[string]
if ($bugs.Count -eq 0) { $c4.Add('no bug root to read captures from (see [1])') }
foreach ($bug in $bugs) {
    $rg = Get-LatestGateRecord -Records $bug.Records -Gate 'check_red_green.py'
    if ($null -eq $rg) { $c4.Add("$($bug.Slug): no check_red_green.py record"); continue }
    $bug.RedGreen = $rg
    $redPath = Get-ArgvFlagValue -Argv $rg.argv -Flag '--red'
    $greenPaths = @(Get-ArgvFlagValues -Argv $rg.argv -Flag '--green')
    if ([string]::IsNullOrWhiteSpace($redPath)) {
        $c4.Add("$($bug.Slug): the gate invocation named no --red capture")
        continue
    }
    if ($greenPaths.Count -eq 0) {
        $c4.Add("$($bug.Slug): the gate invocation named no --green capture")
        continue
    }
    $red = Get-SidecarInfo -CapturePath (Join-Path $TargetDir $redPath)
    if (-not $red.HasSidecar) {
        $c4.Add("$($bug.Slug): the gated RED $redPath - $($red.Problem)")
        continue
    }
    if ($null -eq $red.ExitCode -or [int]$red.ExitCode -eq 0) {
        $c4.Add("$($bug.Slug): the gated RED recorded exit_code $($red.ExitCode) - a reproduction that SUCCEEDED is not a reproduction")
    }
    $newest = $null
    foreach ($greenPath in $greenPaths) {
        $green = Get-SidecarInfo -CapturePath (Join-Path $TargetDir $greenPath)
        if (-not $green.HasSidecar) { $c4.Add("$($bug.Slug): GREEN $greenPath - $($green.Problem)"); continue }
        if ($null -eq $green.ExitCode -or [int]$green.ExitCode -ne 0) {
            $c4.Add("$($bug.Slug): GREEN $greenPath exit_code=$($green.ExitCode), expected 0")
        }
        if (-not (Compare-Argv -Left $red.Argv -Right $green.Argv)) {
            $c4.Add("$($bug.Slug): GREEN $greenPath ran a DIFFERENT command than the RED - red argv [$($red.Argv -join ' ')] vs green argv [$($green.Argv -join ' ')]; two unrelated runs dressed as a proof")
        }
        if ($null -ne $red.Finished -and $null -ne $green.Finished -and -not ($green.Finished -gt $red.Finished)) {
            $c4.Add("$($bug.Slug): GREEN $greenPath finished $($green.Finished.ToString('o')), not strictly later than RED $($red.Finished.ToString('o'))")
        }
        if ($null -eq $newest -or ($null -ne $green.Finished -and $null -ne $newest.Finished -and $green.Finished -gt $newest.Finished)) {
            $newest = $green
        }
    }
    $bug.GreenLatest = $newest
}
if ($c4.Count -gt 0) {
    Add-Failure '4' "a RED/GREEN pair does not constitute a before/after: $($c4 -join '; ')"
} else {
    Write-Output "[4] PASSED: both bugs' sidecars independently agree - identical argv, RED non-zero, every GREEN at exit 0 and strictly later"
}

# --- [5] each fix landed through its own gate, and is in the base --------------
$c5 = New-Object System.Collections.Generic.List[string]
if (-not $gitOk) {
    $c5.Add("no readable git repository at $TargetDir")
} elseif ($commitsAfterBase.Count -lt 1) {
    $c5.Add("no commit exists after 'base' - no bug's gate ever committed, which is how a skipped gate stays loud")
} else {
    # Pair each bug with ITS gated commit. The file set alone cannot do this in a
    # batch: both bugs legitimately declare the same one file (that is what makes
    # them overlap), so `exactly one commit has this file set` - the single-bug
    # sibling case's test - is ambiguous here by construction. The tie-breaker is
    # the gate record's own timestamp: the gate performs the commit from its own
    # subprocess, so a gated commit lands within seconds of the ledger line that
    # records it. Pairs are assigned globally-closest-first, each commit claimed
    # once, and a gap over 10 minutes is not a pairing at all.
    $maxPairGapSeconds = 600
    $pairs = @()
    foreach ($bug in $bugs) {
        if ($null -eq $bug.GateRecord) {
            $c5.Add("$($bug.Slug): no gating PASS to match a commit against (see [3])")
            continue
        }
        if (@($bug.DeclaredFiles).Count -eq 0) {
            $c5.Add("$($bug.Slug): the gating PASS declared no --changed-files, so no commit can be matched to it")
            continue
        }
        $gateInstant = ConvertTo-Instant -Text "$($bug.GateRecord.ts)"
        foreach ($commit in $commitsAfterBase) {
            if (-not (Test-SameFileSet -Left $commit.Files -Right $bug.DeclaredFiles)) { continue }
            $gap = [double]::MaxValue
            if ($null -ne $gateInstant -and $null -ne $commit.Instant) {
                $gap = [math]::Abs(($commit.Instant - $gateInstant).TotalSeconds)
            }
            $pairs += [PSCustomObject]@{ Slug = $bug.Slug; Bug = $bug; Commit = $commit; Gap = $gap }
        }
    }
    $claimedShas = @()
    $assignedSlugs = @()
    foreach ($pair in @($pairs | Sort-Object Gap)) {
        if ($assignedSlugs -contains $pair.Slug) { continue }
        if ($claimedShas -contains $pair.Commit.Sha) { continue }
        if ($pair.Gap -gt $maxPairGapSeconds) { continue }
        $pair.Bug.GatedCommit = $pair.Commit
        $assignedSlugs += $pair.Slug
        $claimedShas += $pair.Commit.Sha
    }
    foreach ($bug in $bugs) {
        if ($null -eq $bug.GateRecord -or @($bug.DeclaredFiles).Count -eq 0) { continue }
        if ($null -eq $bug.GatedCommit) {
            $declaredList = (Get-SortedPathSet -Paths $bug.DeclaredFiles) -join ', '
            $observed = ($commitsAfterBase | ForEach-Object { "'$($_.Subject)' [$((Get-SortedPathSet -Paths $_.Files) -join ', ')] at $($_.Instant)" }) -join ' ; '
            $c5.Add("$($bug.Slug): no unclaimed commit after 'base' both carries the file set its gating PASS declared ($declaredList) and lands within ${maxPairGapSeconds}s of that PASS at $($bug.GateRecord.ts); commits found: $observed")
            continue
        }
        if (@($bug.GatedCommit.Files).Count -gt 5) {
            $c5.Add("$($bug.Slug): the gated commit touches $(@($bug.GatedCommit.Files).Count) files, above the per-bug bound of 5")
        }
        & git -C $TargetDir merge-base --is-ancestor $bug.GatedCommit.Sha HEAD 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            $c5.Add("$($bug.Slug): its gated commit $($bug.GatedCommit.Sha.Substring(0,7)) is not an ancestor of the base branch - the fix was never merged")
        }
        $expected = "fix/$($bug.Slug)"
        if ($branches -contains $expected -and $mergedBranches -notcontains $expected) {
            $c5.Add("$($bug.Slug): branch '$expected' is not merged into the base branch")
        }
    }
    # No commit after base may change source outside a gated commit.
    $gatedShas = @($bugs | Where-Object { $null -ne $_.GatedCommit } | ForEach-Object { $_.GatedCommit.Sha })
    foreach ($commit in $commitsAfterBase) {
        if ($gatedShas -contains $commit.Sha) { continue }
        $outside = @(@($commit.Files) | Where-Object { $_ -notmatch '(?i)^\.docs/' })
        if ($outside.Count -gt 0) {
            $c5.Add("the ungated commit '$($commit.Subject)' touches paths outside .docs/: $($outside -join ', ') - only a gated commit may change source")
        }
    }
}
if ($c5.Count -gt 0) {
    Add-Failure '5' "the two fixes are not bounded, gate-backed and merged: $($c5 -join '; ')"
} else {
    $summary = ($bugs | ForEach-Object { "$($_.Slug)=$($_.GatedCommit.Sha.Substring(0,7))" }) -join ', '
    Write-Output "[5] PASSED: each bug's gated commit ($summary) matches its own gating PASS, is <= 5 files, and is an ancestor of the base branch; every other commit is .docs/-only"
}

# --- [6] batch.md's final table cites both shas and their gate records --------
$c6 = New-Object System.Collections.Generic.List[string]
if ([string]::IsNullOrWhiteSpace($batchText)) {
    $c6.Add('no batch.md to read a final table from (see [1])')
} else {
    foreach ($bug in $bugs) {
        if ($null -eq $bug.GatedCommit) {
            $c6.Add("$($bug.Slug): no gated commit to look for (see [5])")
            continue
        }
        $sha = $bug.GatedCommit.Sha
        $cited = $false
        # Any abbreviation of 7 chars or more that prefixes the real sha counts:
        # `batch.md` legitimately writes a short sha.
        foreach ($m in [regex]::Matches($batchText, '(?i)\b([0-9a-f]{7,40})\b')) {
            if ($sha.StartsWith($m.Groups[1].Value.ToLowerInvariant())) { $cited = $true; break }
        }
        if (-not $cited) {
            $c6.Add("$($bug.Slug): batch.md cites no sha that prefixes its gated commit $($sha.Substring(0,7)) - the final table does not say what landed")
        }
        # And the row must point at the record, not just the commit.
        $slugPattern = [regex]::Escape($bug.Slug)
        $rowMatch = [regex]::Match($batchText, "(?im)^.*$slugPattern.*$")
        $namesRecord = $false
        foreach ($m in [regex]::Matches($batchText, "(?im)^.*$slugPattern.*$")) {
            if ($m.Value -match '(?i)(check_commit_gate|gates\.jsonl|check_ledger)') { $namesRecord = $true; break }
        }
        if (-not $namesRecord) {
            $c6.Add("$($bug.Slug): no line in batch.md mentioning that slug also names its gate record (check_commit_gate.py, its gates.jsonl, or the check_ledger.py run)")
        }
    }
}
if ($c6.Count -gt 0) {
    Add-Failure '6' "batch.md's final table is not evidence-citing: $($c6 -join '; ')"
} else {
    Write-Output "[6] PASSED: batch.md cites both gated commit shas and names each bug's gate record"
}

# --- [7] the overlap was serialised -------------------------------------------
$c7 = New-Object System.Collections.Generic.List[string]
if ($bugs.Count -ne 2) {
    $c7.Add('need exactly two bugs to order (see [1])')
} elseif (@($bugs | Where-Object { $null -eq $_.GatedCommit }).Count -gt 0) {
    # The `@()` is load-bearing: a Where-Object that matches exactly ONE
    # PSCustomObject is unwrapped to a scalar, and a PSCustomObject has no
    # `Count` property, so the unwrapped form evaluated to $null -gt 0 = $false
    # and this criterion silently passed on a tree where one bug had no gated
    # commit at all (caught by the caved self-check, 2026-09-08).
    $c7.Add('both bugs need a gated commit before their order can be read (see [5])')
} else {
    $ordered = @($bugs | Sort-Object { $_.GatedCommit.Instant })
    $first = $ordered[0]
    $second = $ordered[1]
    if ($null -eq $second.GreenLatest -or $null -eq $second.GreenLatest.Finished) {
        $c7.Add("$($second.Slug): no dated GREEN capture to compare against the earlier bug's commit (see [4])")
    } elseif (-not ($second.GreenLatest.Finished -gt $first.GatedCommit.Instant)) {
        $c7.Add("$($second.Slug)'s newest GREEN finished $($second.GreenLatest.Finished.ToString('o')), which is NOT after $($first.Slug)'s gated commit at $($first.GatedCommit.Instant.ToString('o')) - both bugs change $sharedFile, so the second must re-run its GREEN on the merged base (spine Phase 3 step 3), and this run proved its fix only against a tree that no longer exists")
    }
    if ([string]::IsNullOrWhiteSpace($batchText)) {
        $c7.Add('no batch.md to record the overlap in')
    } elseif ($batchText -notlike "*$sharedFile*") {
        $c7.Add("batch.md never names $sharedFile, the file both fixes touch - the overlap that forced the ordering is unrecorded")
    }
}
if ($c7.Count -gt 0) {
    Add-Failure '7' "the overlap was not serialised on the record: $($c7 -join '; ')"
} else {
    $ordered = @($bugs | Sort-Object { $_.GatedCommit.Instant })
    Write-Output "[7] PASSED: $($ordered[1].Slug)'s GREEN was re-run after $($ordered[0].Slug)'s gated commit, and batch.md names the shared $sharedFile"
}

# --- [8] neither frozen check was edited --------------------------------------
$c8 = New-Object System.Collections.Generic.List[string]
$targetTestsDir = Join-Path $TargetDir 'tests'
if (-not (Test-Path $targetTestsDir)) {
    $c8.Add('tests/ is missing from the working copy - the frozen suite was deleted')
} elseif (-not (Test-Path $fixtureTestsDir)) {
    $c8.Add("fixture baseline tests/ not found at $fixtureTestsDir (grader installation problem)")
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
        if (-not $observed.ContainsKey($key)) { $c8.Add("deleted: tests/$key") }
        elseif ($observed[$key] -ne $baseline[$key]) { $c8.Add("modified: tests/$key") }
    }
    foreach ($key in $observed.Keys) {
        if (-not $baseline.ContainsKey($key)) { $c8.Add("added: tests/$key") }
    }
}

# The second bug's reproduction is a script in the repo, so unlike an HTTP
# reproduction this half is NOT vacuous: editing it is how a RED is made to pass.
$targetRepro = Join-Path $TargetDir 'scripts\repro-tax.js'
if (-not (Test-Path $targetRepro)) {
    $c8.Add('scripts/repro-tax.js is missing - the reproduction handed over with the second report was deleted')
} elseif (Test-Path $fixtureRepro) {
    $a = (Get-FileHash -Path $targetRepro -Algorithm SHA256).Hash
    $b = (Get-FileHash -Path $fixtureRepro -Algorithm SHA256).Hash
    if ($a -ne $b) { $c8.Add('modified: scripts/repro-tax.js - the reproduction was edited to agree with the fix') }
}

# Every repo path any RED sidecar's own argv names, in any commit after base.
$redArgvPaths = @()
foreach ($bug in $bugs) {
    if ($null -eq $bug.RedGreen) { continue }
    $redPath = Get-ArgvFlagValue -Argv $bug.RedGreen.argv -Flag '--red'
    if ([string]::IsNullOrWhiteSpace($redPath)) { continue }
    $red = Get-SidecarInfo -CapturePath (Join-Path $TargetDir $redPath)
    if (-not $red.HasSidecar) { continue }
    foreach ($token in @($red.Argv)) {
        $candidate = "$token"
        if ($candidate -match '^-') { continue }
        if ($candidate -match '^[a-z]+://') { continue }
        if ($candidate -notmatch '[\\/]') { continue }
        if (Test-Path (Join-Path $TargetDir $candidate)) {
            $norm = Get-NormalizedPath $candidate
            if ($redArgvPaths -notcontains $norm) { $redArgvPaths += $norm }
        }
    }
}
foreach ($redPath in $redArgvPaths) {
    if ($commitFiles -contains $redPath) {
        $c8.Add("a commit after 'base' modifies a path a RED command itself runs: $redPath")
    }
}
$testFilesCommitted = @($commitFiles | Where-Object { $_ -match '(?i)^tests/' })
if ($testFilesCommitted.Count -gt 0) {
    $c8.Add("a commit after 'base' includes frozen test file(s): $($testFilesCommitted -join ', ')")
}

if ($c8.Count -gt 0) {
    Add-Failure '8' "a frozen check was edited to agree with a fix: $($c8 -join '; ')"
} else {
    $argvNote = 'no RED argv named a repo path'
    if ($redArgvPaths.Count -gt 0) { $argvNote = "and none of the RED argv paths ($($redArgvPaths -join ', ')) appear in any commit" }
    Write-Output "[8] PASSED: tests/ and scripts/repro-tax.js byte-identical to the frozen fixture; $argvNote"
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
