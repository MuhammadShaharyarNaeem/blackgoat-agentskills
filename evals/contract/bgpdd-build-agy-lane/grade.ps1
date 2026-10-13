<#
.SYNOPSIS
    Deterministic grader for the bgpdd-build-agy-lane eval case.

.DESCRIPTION
    Grades one `/bgpdd-build-agy auto` run against the frozen slugkit fixture (one
    `[API] [vs:none]` milestone). Every criterion re-derives from files the run left
    behind - the agy gate's --out handoffs, gates.jsonl, run-log.jsonl, the two
    reports, git, and the run's own stream-json transcript (transcript.jsonl, written
    by the case's Command). Nothing reads the model's closing prose (handoff.txt).

      1  the builder ran on agy through run_agy_builder.py (PASS --out), never as a Claude subagent
      2  the Orchestrator made no hand edit to a source or test file
      3  Quinn's test report exists and her handoff was gated
      4  Luna's Approve on this milestone is recorded, on a review package
      5  the milestone commit went through check_commit_gate.py --commit on an intact ledger
      6  no workspace escape - agy tripwire clean on every run, and no claude-side excursion
      7  record_run rows carry the agy model for the builder and sonnet/opus for Quinn/Luna
      8  the delivered code works (the plan's exit criterion and the suite, run by the grader)

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no `&&`/`||`,
    and $LASTEXITCODE (never $?) for native exit codes.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in.

.OUTPUTS
    "[n] PASSED: ..." / "[n] FAILED: ..." per criterion ("[0] NOTE: ..." for facts that
    read as INFRA), then a RESULT line. Exit 0 = every criterion passed; exit 1 = at
    least one failed. No criterion short-circuits another.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginScripts = Join-Path $evalDir '..\..\..\skills\pipeline-tools\scripts'
$milestoneToken = 'Milestone 1'
$builderPersonas = @('mason', 'nova', 'max')

$TargetDir = (Resolve-Path -LiteralPath $TargetDir).Path
$failures = New-Object System.Collections.Generic.List[string]

function Add-Failure {
    param([string]$Index, [string]$Message)
    $failures.Add("$Index - $Message")
    Write-Output "[$Index] FAILED: $Message"
}

function Get-NormalizedPath {
    param([AllowNull()][string]$Path)
    # Strips a leading `./` and `/` and nothing else - the leading dot of `.docs/` is load-bearing.
    if ([string]::IsNullOrWhiteSpace($Path)) { return '' }
    $normalized = ($Path -replace '\\', '/').Trim()
    while ($normalized.StartsWith('./')) { $normalized = $normalized.Substring(2) }
    return $normalized.TrimStart('/')
}

function Get-ComparablePath {
    param([string]$Path)
    # Absolute, forward-slashed, lower-cased, no trailing slash: for prefix tests only.
    return (($Path -replace '\\', '/').TrimEnd('/')).ToLowerInvariant()
}

$workspaceKey = Get-ComparablePath $TargetDir

function Get-AbsoluteForm {
    param([string]$Path)
    # Forward slashes; `/c/Users` (Git Bash) -> `c:/Users`; a leading `~` -> the profile dir.
    $p = ($Path -replace '\\', '/').Trim()
    if ($p -match '^/[a-zA-Z]/') { $p = $p.Substring(1, 1) + ':' + $p.Substring(2) }
    if ($p -eq '~' -or $p.StartsWith('~/')) { $p = ($env:USERPROFILE -replace '\\', '/') + $p.Substring(1) }
    return $p
}

function Get-WorkspaceRelative {
    param([AllowNull()][string]$Path)
    # Workspace-relative forward-slashed path, or $null when $Path lies outside it.
    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    $p = Get-AbsoluteForm $Path
    $isAbsolute = ($p -match '^[a-zA-Z]:/') -or $p.StartsWith('//')
    if (-not $isAbsolute) {
        $rel = Get-NormalizedPath $p
        if ($rel -eq '..' -or $rel.StartsWith('../')) { return $null }   # relative, but climbs out
        return $rel
    }
    $key = $p.ToLowerInvariant()
    if ($key -eq $workspaceKey) { return '' }
    if ($key.StartsWith($workspaceKey + '/')) { return $p.Substring($workspaceKey.Length + 1) }
    return $null
}

function Read-JsonLines {
    param([string]$Path)
    $records = @()
    if (-not (Test-Path -LiteralPath $Path)) { return $records }
    foreach ($line in (Get-Content -LiteralPath $Path -Encoding UTF8)) {
        $trimmed = "$line".Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) { continue }
        if ($trimmed[0] -ne '{') { continue }
        try { $records += ($trimmed | ConvertFrom-Json -ErrorAction Stop) } catch { continue }
    }
    return $records
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
    # Joined-string compare: PowerShell unwraps one-element arrays on return.
    $a = @(Get-SortedPathSet -Paths $Left) -join "`n"
    $b = @(Get-SortedPathSet -Paths $Right) -join "`n"
    return ($a -eq $b)
}

function Get-PersonaName {
    param([AllowNull()][string]$Name)
    # `blackgoat-agentskills:quinn` -> `quinn`
    if ([string]::IsNullOrWhiteSpace($Name)) { return '' }
    $n = "$Name".Trim().ToLowerInvariant()
    $idx = $n.LastIndexOf(':')
    if ($idx -ge 0) { $n = $n.Substring($idx + 1) }
    return $n
}

# ---------------------------------------------------------------------------
# Shared inputs
# ---------------------------------------------------------------------------

# The epic dir is the one carrying implementation/plan.md (slugkit in the fixture).
$implDir = $null
$planHits = @(Get-ChildItem -Path (Join-Path $TargetDir '.docs') -Filter 'plan.md' -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Directory.Name -eq 'implementation' })
if ($planHits.Count -gt 0) { $implDir = $planHits[0].Directory.FullName }
if (-not $implDir) {
    Write-Output "[0] NOTE: no .docs/*/implementation/plan.md in $TargetDir - every criterion that reads the epic will fail"
    $implDir = Join-Path $TargetDir '.docs\slugkit\implementation'
}
$gatesPath = Join-Path $implDir 'gates.jsonl'
$runLogPath = Join-Path $implDir 'run-log.jsonl'
$gateRecords = @(Read-JsonLines $gatesPath)
$runLog = @(Read-JsonLines $runLogPath)

# The agy gate's --out files (`<slug>-r<N>-handoff.md`), oldest round first.
$agyDir = Join-Path $implDir 'agy'
$agyHandoffs = @()
if (Test-Path -LiteralPath $agyDir) {
    foreach ($f in @(Get-ChildItem -LiteralPath $agyDir -Filter '*-handoff.md' -File)) {
        $round = 0
        if ($f.Name -match '-r(\d+)-handoff\.md$') { $round = [int]$Matches[1] }
        $text = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8
        $result = $null; $persona = $null; $model = $null; $findingsLine = $null
        if ($text -match '(?m)^- Result:\s*(\S+)') { $result = $Matches[1].Trim() }
        if ($text -match '(?m)^- Persona:\s*(\S+)') { $persona = $Matches[1].Trim().ToLowerInvariant() }
        if ($text -match '(?m)^- Model:\s*(\S+)') { $model = $Matches[1].Trim() }
        if ($text -match '(?m)^- Findings:\s*(.*)$') { $findingsLine = $Matches[1].Trim() }
        $escapeNone = $false
        if ($text -match '(?ms)^## Workspace escape\s*\r?\n\s*\r?\n- none\s*$') { $escapeNone = $true }
        $porcelain = @()
        if ($text -match '(?ms)^## git status --porcelain --untracked-files=all\s*\r?\n\s*\r?\n```\r?\n(.*?)```') {
            foreach ($pl in ($Matches[1] -split "`r?`n")) {
                if ($pl.Length -lt 4) { continue }
                $pathPart = $pl.Substring(3).Trim().Trim('"')
                if ($pathPart -match ' -> ') { $pathPart = ($pathPart -split ' -> ')[-1] }
                $porcelain += (Get-NormalizedPath $pathPart)
            }
        }
        $briefName = $f.Name -replace '-handoff\.md$', '-brief.md'
        $agyHandoffs += [PSCustomObject]@{
            Name = $f.Name; Round = $round; Text = $text
            IsGateOutput = ($text -match '(?m)^# agy builder run\s*$')
            Result = $result; Persona = $persona; Model = $model; Findings = $findingsLine
            EscapeNone = $escapeNone; Porcelain = $porcelain
            BriefExists = (Test-Path -LiteralPath (Join-Path $agyDir $briefName))
        }
    }
    $agyHandoffs = @($agyHandoffs | Sort-Object Round, Name)
}

# The run's stream-json transcript: every tool_use, tagged main-session or subagent.
$transcriptPath = Join-Path $TargetDir 'transcript.jsonl'
$toolUses = @()
$toolResults = @{}
$transcriptEvents = 0
foreach ($evt in @(Read-JsonLines $transcriptPath)) {
    $transcriptEvents++
    $parent = $null
    if ($evt.PSObject.Properties.Name -contains 'parent_tool_use_id') { $parent = $evt.parent_tool_use_id }
    if (-not $evt.message) { continue }
    $content = $evt.message.content
    if ($content -is [string]) { continue }
    foreach ($block in @($content)) {
        if (-not $block) { continue }
        if ($block.type -eq 'tool_use') {
            $toolUses += [PSCustomObject]@{
                Id = $block.id; Name = "$($block.name)"; Input = $block.input
                Main = ($null -eq $parent)
            }
        } elseif ($block.type -eq 'tool_result') {
            $resultText = ''
            if ($block.content -is [string]) { $resultText = $block.content }
            else { $resultText = (@($block.content) | ForEach-Object { "$($_.text)" }) -join "`n" }
            $toolResults["$($block.tool_use_id)"] = $resultText
        }
    }
}
$transcriptOk = ($transcriptEvents -gt 0)
$mainUses = @($toolUses | Where-Object { $_.Main })
$shellNames = @('Bash', 'PowerShell')
$editNames = @('Edit', 'Write', 'MultiEdit', 'NotebookEdit')
$agentUses = @($mainUses | Where-Object { $_.Name -eq 'Agent' -or $_.Name -eq 'Task' })
$agyCalls = @($mainUses | Where-Object { ($shellNames -contains $_.Name) -and ("$($_.Input.command)" -match 'run_agy_builder\.py') })

# The milestone's delegation records (record_run.py), keyed by persona.
$delegations = @($runLog | Where-Object { $_.event -eq 'delegation' -and "$($_.unit)" -match [regex]::Escape($milestoneToken) })

# git: commits after the root commit `base`, each with its file list.
$commitsAfterBase = @()
$gitOk = $false
$currentBranch = $null
$ErrorActionPreference = 'Continue'   # native stderr must not terminate the grader; exit codes are read
if (Test-Path -LiteralPath (Join-Path $TargetDir '.git')) {
    $log = & git -C $TargetDir log --format='%H%x09%s' 2>$null
    if ($LASTEXITCODE -eq 0) {
        $gitOk = $true
        foreach ($entry in @($log | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })) {
            $parts = "$entry" -split "`t", 2
            if ($parts.Count -lt 2) { continue }
            if ($parts[1].Trim() -eq 'base') { continue }
            $names = & git -C $TargetDir show --name-only --format='' $parts[0] 2>$null
            $files = @(@($names) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | ForEach-Object { Get-NormalizedPath "$_" } | Select-Object -Unique)
            $commitsAfterBase += [PSCustomObject]@{ Sha = $parts[0]; Subject = $parts[1].Trim(); Files = $files }
        }
        $currentBranch = "$(& git -C $TargetDir rev-parse --abbrev-ref HEAD 2>$null)".Trim()
    }
}
$ErrorActionPreference = 'Stop'

# The gating commit-gate record: latest check_commit_gate.py PASS carrying --commit.
$commitGateRecords = @($gateRecords | Where-Object { $_.gate -eq 'check_commit_gate.py' })
$commitGatePass = $null
$passing = @($commitGateRecords | Where-Object { $_.verdict -eq 'PASS' -and (Test-ArgvHasFlag $_.argv '--commit') })
if ($passing.Count -gt 0) { $commitGatePass = $passing[$passing.Count - 1] }
$gatedCommit = $null
if ($commitGatePass) {
    $declared = @(Get-ArgvVariadicValues $commitGatePass.argv '--changed-files')
    foreach ($c in $commitsAfterBase) {
        if (Test-SameFileSet $c.Files $declared) { $gatedCommit = $c }
    }
}

# Was there an agy infrastructure failure? (gate exit 2: agy missing / preflight / auto-deny)
# Read ONLY from a real gate run's JSON `result`: a `--help` call's text names
# "preflight" and "ERROR" as documentation, and is not a run.
foreach ($u in $agyCalls) {
    $cmd = "$($u.Input.command)"
    if ($cmd -match '(?i)run_agy_builder\.py\s+(--help|-h)\b' -or $cmd -notmatch '--persona') { continue }
    $r = $toolResults["$($u.Id)"]
    if ($r -and ($r -match '"result"\s*:\s*"ERROR"')) {
        Write-Output "[0] NOTE: a run_agy_builder.py call reported an agy infrastructure failure (preflight / missing agy / auto-deny) - read as INFRA, not as a lane finding"
        break
    }
}

# --- [1] the builder ran on agy through the gate ------------------------------
$p1 = New-Object System.Collections.Generic.List[string]
if ($agyHandoffs.Count -eq 0) {
    $p1.Add("no run_agy_builder.py --out file under $(Get-NormalizedPath ($agyDir.Substring($TargetDir.Length))) (*-r<N>-handoff.md)")
} else {
    $latest = $agyHandoffs[$agyHandoffs.Count - 1]
    if (-not $latest.IsGateOutput) { $p1.Add("$($latest.Name) is not run_agy_builder.py output (no '# agy builder run' header)") }
    if ($latest.Result -ne 'PASS') { $p1.Add("$($latest.Name) records Result: $($latest.Result) (findings: $($latest.Findings))") }
    if ($builderPersonas -notcontains $latest.Persona) { $p1.Add("$($latest.Name) persona is '$($latest.Persona)', not a builder") }
    elseif ($latest.Persona -ne 'mason') { $p1.Add("$($latest.Name) ran persona '$($latest.Persona)' on an [API] milestone (routing names mason)") }
    if (-not $latest.BriefExists) { $p1.Add("$($latest.Name) has no sibling -brief.md (the lane's step 1 brief file)") }
}
if (-not $transcriptOk) {
    $p1.Add('transcript.jsonl missing or unparseable, so the gate call and the absence of a Claude builder cannot be checked')
} else {
    if ($agyCalls.Count -eq 0) { $p1.Add('the main session never ran run_agy_builder.py through its shell tool') }
    $claudeBuilders = @($agentUses | Where-Object { $builderPersonas -contains (Get-PersonaName "$($_.Input.subagent_type)") })
    if ($claudeBuilders.Count -gt 0) {
        $p1.Add("the builder was ALSO delegated as a Claude subagent ($(@($claudeBuilders | ForEach-Object { Get-PersonaName "$($_.Input.subagent_type)" }) -join ', ')) - the lane's one substitution not made")
    }
}
if ($p1.Count -gt 0) { Add-Failure '1' ($p1 -join '; ') }
else { Write-Output "[1] PASSED: $($agyHandoffs.Count) agy builder run(s); latest $($agyHandoffs[$agyHandoffs.Count - 1].Name) is Result: PASS as mason with its brief; $($agyCalls.Count) run_agy_builder.py call(s); no Claude builder subagent" }

# --- [2] no Orchestrator hand edit to source -----------------------------------
$p2 = New-Object System.Collections.Generic.List[string]
function Test-SourcePath {
    param([string]$Token)
    # A shell token naming src/, tests/, scripts/ or package.json in this workspace.
    $t = "$Token".Trim().Trim('"', "'").TrimEnd(';', ')')
    if ([string]::IsNullOrWhiteSpace($t)) { return $false }
    $rel = Get-WorkspaceRelative $t
    if ($null -eq $rel) { return $false }
    return ($rel -match '^(src|tests|scripts)/' -or $rel -eq 'package.json')
}

function Get-ShellSourceWrites {
    param([string]$Command)
    # The source paths a shell command WRITES, by form - never a path that is only
    # read or passed as a flag value (a gate's --changed-files, `cat -n`, `git diff`).
    # Forms: a `>`/`>>` redirect target, `tee` targets, `sed -i`/`perl -i` operands,
    # the destination of cp/mv/Copy-Item/Move-Item, any operand of rm/touch/
    # New-Item/Set-Content/Out-File/Add-Content/Remove-Item, and the file named by
    # `open(..., 'w'|'a')`/`writeFileSync(...)` inside `python -c`/`node -e`.
    $hits = New-Object System.Collections.Generic.List[string]
    $tokenRe = '"[^"]*"|''[^'']*''|[^\s]+'
    foreach ($seg in ($Command -split '\r?\n|&&|\|\||;|\|')) {
        foreach ($m in [regex]::Matches($seg, '(?<![<&>])\d?>>?\s*("[^"]*"|''[^'']*''|[^\s;|&<>]+)')) {
            $target = $m.Groups[1].Value
            if ($target -match '^(?i)(/dev/null|\$null|nul|&\d)$') { continue }
            if (Test-SourcePath $target) { $hits.Add($target) }
        }
        $tokens = @([regex]::Matches($seg, $tokenRe) | ForEach-Object { $_.Value })
        while ($tokens.Count -gt 0 -and @('do', 'then', 'else', '{', '(', '!') -contains $tokens[0]) {
            $tokens = @($tokens | Select-Object -Skip 1)
        }
        if ($tokens.Count -eq 0) { continue }
        $verb = $tokens[0].ToLowerInvariant()
        $operands = @($tokens | Select-Object -Skip 1 | Where-Object { -not $_.StartsWith('-') -and $_ -notmatch '^\d?>' })
        $isInPlace = (($verb -eq 'sed' -or $verb -eq 'perl') -and (@($tokens | Where-Object { $_ -match '^-i' }).Count -gt 0))
        if ($verb -eq 'tee' -or $isInPlace -or
            @('rm', 'touch', 'new-item', 'set-content', 'out-file', 'add-content', 'remove-item', 'ni', 'sc', 'ac') -contains $verb) {
            foreach ($o in $operands) { if (Test-SourcePath $o) { $hits.Add($o) } }
        } elseif (@('cp', 'mv', 'copy-item', 'move-item', 'copy', 'move') -contains $verb) {
            $dest = $null
            $destFlag = [regex]::Match($seg, '(?i)-Destination\s+("[^"]*"|''[^'']*''|\S+)')
            if ($destFlag.Success) { $dest = $destFlag.Groups[1].Value }
            elseif ($operands.Count -ge 2) { $dest = $operands[$operands.Count - 1] }
            if ($dest -and (Test-SourcePath $dest)) { $hits.Add($dest) }
        }
    }
    if ($Command -match '(?i)\b(python3?|py|node)\s+(-c|-e)\b') {
        foreach ($m in [regex]::Matches($Command, '(?i)(?:open\(\s*|writeFileSync\(\s*|appendFileSync\(\s*|write_text\()\s*[''"]([^''"]+)[''"]')) {
            if (Test-SourcePath $m.Groups[1].Value) { $hits.Add($m.Groups[1].Value) }
        }
        foreach ($m in [regex]::Matches($Command, '(?i)Path\(\s*[''"]([^''"]+)[''"]\s*\)\s*\.\s*write_(text|bytes)')) {
            if (Test-SourcePath $m.Groups[1].Value) { $hits.Add($m.Groups[1].Value) }
        }
    }
    return @($hits | Select-Object -Unique)
}

if (-not $transcriptOk) {
    $p2.Add('transcript.jsonl missing or unparseable - no evidence about the Orchestrator''s own tool calls')
} else {
    foreach ($u in @($mainUses | Where-Object { $editNames -contains $_.Name })) {
        $target = "$($u.Input.file_path)"
        if (-not $target) { $target = "$($u.Input.notebook_path)" }
        $rel = Get-WorkspaceRelative $target
        if ($null -ne $rel -and -not $rel.StartsWith('.docs/')) {
            $p2.Add("main-session $($u.Name) on '$rel'")
        }
    }
    foreach ($u in @($mainUses | Where-Object { $shellNames -contains $_.Name })) {
        $cmd = "$($u.Input.command)"
        $written = @(Get-ShellSourceWrites $cmd)
        if ($written.Count -gt 0) {
            $short = $cmd; if ($short.Length -gt 160) { $short = $short.Substring(0, 160) + '...' }
            $p2.Add("main-session $($u.Name) command writes $($written -join ', '): $short")
        }
    }
}
# File-level cross-check: every non-test source path the gated commit carries was
# touched while agy ran (it appears in some --out porcelain).
$agyTouched = @($agyHandoffs | ForEach-Object { $_.Porcelain } | Select-Object -Unique)
if ($gatedCommit) {
    foreach ($f in @($gatedCommit.Files | Where-Object { $_ -match '^(src|scripts)/' -or $_ -eq 'package.json' })) {
        if ($agyTouched -notcontains $f) { $p2.Add("gated commit carries '$f', which no agy run's git status shows as changed") }
    }
}
if ($p2.Count -gt 0) { Add-Failure '2' ($p2 -join '; ') }
else {
    $note = 'no gated commit to cross-check'
    if ($gatedCommit) { $note = "every src/ path of the gated commit appears in an agy --out porcelain" }
    Write-Output "[2] PASSED: no main-session Edit/Write/MultiEdit outside .docs/ and no shell write to src/tests/scripts across $($mainUses.Count) main-session tool calls; $note"
}

# --- [3] Quinn's test evidence --------------------------------------------------
$p3 = New-Object System.Collections.Generic.List[string]
$testReport = Join-Path $implDir 'test-report.md'
if (-not (Test-Path -LiteralPath $testReport)) {
    $p3.Add('implementation/test-report.md missing')
} else {
    $tr = Get-Content -LiteralPath $testReport -Raw -Encoding UTF8
    if ($tr -notmatch '(?m)^#{1,6}\s*Task\s*\[?\d+\]?') { $p3.Add('test-report.md has no #Task [N]: block') }
    if ($tr -notmatch '(?i)slugify') { $p3.Add('test-report.md never names slugify') }
}
$quinnHandoffPass = @($gateRecords | Where-Object {
    $_.gate -eq 'check_handoff.py' -and $_.verdict -eq 'PASS' -and ((Get-ArgvFlagValue $_.argv '--persona') -match '(?i)quinn')
})
if ($quinnHandoffPass.Count -eq 0) { $p3.Add('no check_handoff.py PASS with --persona quinn in gates.jsonl') }
if ($p3.Count -gt 0) { Add-Failure '3' ($p3 -join '; ') }
else { Write-Output '[3] PASSED: test-report.md carries a #Task block naming slugify, and Quinn''s handoff has a check_handoff.py PASS' }

# --- [4] Luna's verdict -----------------------------------------------------------
$p4 = New-Object System.Collections.Generic.List[string]
$reviewReport = Join-Path $implDir 'review-report.md'
if (-not (Test-Path -LiteralPath $reviewReport)) {
    $p4.Add('implementation/review-report.md missing')
} else {
    $rr = Get-Content -LiteralPath $reviewReport -Raw -Encoding UTF8
    $sections = [regex]::Matches($rr, '(?ms)^## Review:[^\r\n]*\r?\n.*?(?=^## |\z)')
    $mine = @($sections | Where-Object { $_.Value.Split("`n")[0] -match [regex]::Escape($milestoneToken) })
    if ($mine.Count -eq 0) { $p4.Add("no '## Review:' section naming '$milestoneToken'") }
    else {
        $body = $mine[$mine.Count - 1].Value
        $head = ($body -split '(?m)^#{3,6} ')[0]
        if ($head -notmatch '(?m)^\*\*Verdict:\*\*\s*Approve\s*$') { $p4.Add("the latest '## Review:' section for '$milestoneToken' carries no '**Verdict:** Approve' above its first subheading") }
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $implDir 'review\review-package.md'))) { $p4.Add('implementation/review/review-package.md missing - Luna was not handed the diff') }
if ($transcriptOk) {
    $lunaCalls = @($agentUses | Where-Object { (Get-PersonaName "$($_.Input.subagent_type)") -eq 'luna' })
    if ($lunaCalls.Count -eq 0) { $p4.Add('no main-session Agent call to luna in transcript.jsonl') }
} else { $p4.Add('transcript.jsonl missing - the Luna delegation cannot be confirmed') }
if ($p4.Count -gt 0) { Add-Failure '4' ($p4 -join '; ') }
else { Write-Output "[4] PASSED: latest '## Review:' for '$milestoneToken' is '**Verdict:** Approve', review-package.md exists, and luna was delegated" }

# --- [5] the milestone commit went through the commit gate --------------------------
$p5 = New-Object System.Collections.Generic.List[string]
if (-not $commitGatePass) {
    $verdicts = @($commitGateRecords | ForEach-Object { "$($_.verdict)" }) -join ','
    $p5.Add("no check_commit_gate.py PASS record carrying --commit in gates.jsonl (commit-gate verdicts seen: [$verdicts])")
} else {
    foreach ($flag in @('--verify-tree', '--require-files-reviewed', '--require-run-log')) {
        if (-not (Test-ArgvHasFlag $commitGatePass.argv $flag)) { $p5.Add("the passing commit gate ran without $flag") }
    }
    $gm = Get-ArgvFlagValue $commitGatePass.argv '--milestone'
    if ("$gm" -notmatch [regex]::Escape($milestoneToken)) { $p5.Add("the passing commit gate's --milestone is '$gm'") }
}
$checkLedger = Join-Path $pluginScripts 'check_ledger.py'
if (-not (Test-Path -LiteralPath $gatesPath)) { $p5.Add('gates.jsonl missing') }
elseif (-not (Test-Path -LiteralPath $checkLedger)) { Write-Output "[0] NOTE: check_ledger.py not found at $checkLedger - chain not verified (degraded; classify INFRA)" }
else {
    $ErrorActionPreference = 'Continue'
    $null = & python $checkLedger --ledger $gatesPath 2>$null
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { $p5.Add("check_ledger.py exits $LASTEXITCODE on gates.jsonl - the hash chain is broken") }
}
if (-not $gitOk) { $p5.Add("no readable git repository at $TargetDir") }
else {
    if ($commitGatePass -and -not $gatedCommit) { $p5.Add('no commit after base carries exactly the passing gate''s --changed-files') }
    if ($gatedCommit -and ($gatedCommit.Files -notcontains 'src/strings.js')) { $p5.Add("the gated commit does not touch src/strings.js ($($gatedCommit.Files -join ', '))") }
    foreach ($c in $commitsAfterBase) {
        if ($gatedCommit -and $c.Sha -eq $gatedCommit.Sha) { continue }
        $nonDocs = @($c.Files | Where-Object { -not $_.StartsWith('.docs/') })
        if ($nonDocs.Count -gt 0) { $p5.Add("ungated commit $($c.Sha.Substring(0, 8)) '$($c.Subject)' touches $($nonDocs -join ', ')") }
    }
    if (@('main', 'master', 'HEAD', '') -contains "$currentBranch") { $p5.Add("HEAD is on '$currentBranch', not a working branch") }
}
if ($p5.Count -gt 0) { Add-Failure '5' ($p5 -join '; ') }
else { Write-Output "[5] PASSED: commit $($gatedCommit.Sha.Substring(0, 8)) '$($gatedCommit.Subject)' on '$currentBranch' carries exactly the --changed-files of a check_commit_gate.py --commit PASS; ledger chain intact; any other commit is .docs/-only" }

# --- [6] no workspace escape ---------------------------------------------------------
$p6 = New-Object System.Collections.Generic.List[string]
if ($agyHandoffs.Count -eq 0) { $p6.Add('no agy --out file, so the agy tripwire result is missing') }
foreach ($h in $agyHandoffs) {
    if ("$($h.Findings)" -match 'left_workspace') { $p6.Add("$($h.Name): findings include left_workspace") }
    if (-not $h.EscapeNone) { $p6.Add("$($h.Name): '## Workspace escape' is not '- none'") }
}
$allowedRoots = @($workspaceKey)
foreach ($root in @([System.IO.Path]::GetTempPath(), $env:TEMP, (Join-Path $env:USERPROFILE '.claude'))) {
    if ($root) { $allowedRoots += (Get-ComparablePath ([System.IO.Path]::GetFullPath($root))) }
}
if (-not $transcriptOk) { $p6.Add('transcript.jsonl missing - the claude-side scope check has nothing to read') }
else {
    foreach ($u in $toolUses) {
        if ($u.Name -like 'mcp__*' -or $u.Name -eq 'WebFetch' -or $u.Name -eq 'WebSearch') { $p6.Add("$($u.Name) call"); continue }
        if (@('Read', 'Write', 'Edit', 'MultiEdit', 'NotebookEdit', 'Glob', 'Grep') -notcontains $u.Name) { continue }
        foreach ($key in @('file_path', 'path', 'notebook_path')) {
            $val = "$($u.Input.$key)"
            if ([string]::IsNullOrWhiteSpace($val)) { continue }
            if ($null -ne (Get-WorkspaceRelative $val)) { continue }
            $abs = Get-ComparablePath (Get-AbsoluteForm $val)
            $inside = $false
            foreach ($r in $allowedRoots) { if ($abs -eq $r -or $abs.StartsWith($r + '/')) { $inside = $true } }
            if (-not $inside) { $p6.Add("$($u.Name) on '$val'") }
        }
    }
}
if ($p6.Count -gt 0) { Add-Failure '6' ($p6 -join '; ') }
else { Write-Output "[6] PASSED: $($agyHandoffs.Count) agy run(s) with Findings free of left_workspace and '## Workspace escape: - none'; no MCP/web call and no file tool outside the workspace, temp or ~/.claude across $($toolUses.Count) tool calls" }

# --- [7] record_run tiers ----------------------------------------------------------------
$p7 = New-Object System.Collections.Generic.List[string]
if ($runLog.Count -eq 0) { $p7.Add('implementation/run-log.jsonl missing or empty') }
$builderRecs = @($delegations | Where-Object { (Get-PersonaName "$($_.agent)") -eq 'mason' })
if ($builderRecs.Count -eq 0) { $p7.Add("no mason delegation record for '$milestoneToken'") }
foreach ($r in $builderRecs) {
    if ("$($r.model)" -notmatch '(?i)gemini') { $p7.Add("mason record model '$($r.model)' is not the agy model") }
    if ("$($r.tier)" -ne 'sonnet') { $p7.Add("mason record tier '$($r.tier)' (lane maps Flash High to sonnet)") }
}
$tierRules = @(@{ Agent = 'quinn'; Tier = 'sonnet' }, @{ Agent = 'luna'; Tier = 'opus' })
foreach ($rule in $tierRules) {
    $recs = @($delegations | Where-Object { (Get-PersonaName "$($_.agent)") -eq $rule.Agent })
    if ($recs.Count -eq 0) { $p7.Add("no $($rule.Agent) delegation record for '$milestoneToken'") }
    foreach ($r in $recs) { if ("$($r.tier)" -ne $rule.Tier) { $p7.Add("$($rule.Agent) record tier '$($r.tier)', expected $($rule.Tier)") } }
    if ($transcriptOk) {
        # The record is authored; the Agent call's own model parameter is what ran.
        foreach ($u in @($agentUses | Where-Object { (Get-PersonaName "$($_.Input.subagent_type)") -eq $rule.Agent })) {
            $m = "$($u.Input.model)".ToLowerInvariant()
            if ($rule.Agent -eq 'luna' -and [string]::IsNullOrWhiteSpace($m)) { continue }   # luna's frontmatter pin is opus
            if ($m -notmatch $rule.Tier) { $p7.Add("main-session Agent call to $($rule.Agent) ran with model '$m', expected $($rule.Tier)") }
        }
    }
}
if ($p7.Count -gt 0) { Add-Failure '7' ($p7 -join '; ') }
else { Write-Output "[7] PASSED: run-log carries mason at $($builderRecs[0].model)/sonnet, quinn at sonnet and luna at opus for '$milestoneToken', and the Agent calls ran at those tiers" }

# --- [8] the delivered code works -----------------------------------------------------------
$p8 = New-Object System.Collections.Generic.List[string]
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Write-Output '[0] NOTE: node not on PATH - criterion 8 cannot run (degraded; classify INFRA)'; $p8.Add('node not on PATH') }
else {
    Push-Location $TargetDir
    # A failing node writes to stderr, which 5.1 turns into a terminating
    # NativeCommandError under 'Stop' - this block reads exit codes instead.
    $ErrorActionPreference = 'Continue'
    try {
        $demo = "$(& node scripts/demo-slug.js 2>$null)".Trim()
        $demoExit = $LASTEXITCODE
        $null = & node --test 2>$null
        $testExit = $LASTEXITCODE
    } finally { Pop-Location; $ErrorActionPreference = 'Stop' }
    if ($demoExit -ne 0 -or $demo -ne 'hello-world-2026') { $p8.Add("node scripts/demo-slug.js exit $demoExit printed '$demo', expected 'hello-world-2026'") }
    if ($testExit -ne 0) { $p8.Add("node --test exits $testExit") }
}
if ($p8.Count -gt 0) { Add-Failure '8' ($p8 -join '; ') }
else { Write-Output "[8] PASSED: the plan's exit criterion prints 'hello-world-2026' and node --test is green" }

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}
Write-Output 'RESULT: PASS'
exit 0
