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

.PARAMETER SelfTest
    Zero-token, offline check of the trigger judge (harness_version 2): feeds canned
    transcripts (a positive substring match, a negated substring match, and a
    tool_use record) through Invoke-TriggerJudge and verifies each comes out the
    expected way. Exits 0 if every case matches, non-zero on any mismatch. Ignores
    every other parameter and never calls `claude` or touches results.jsonl.

.EXAMPLE
    # Dry run - prints plan + cost estimate, spends nothing.
    .\run-evals.ps1 -Suite contract

.EXAMPLE
    # Actually execute the alex-plan-coverage case 5 times.
    .\run-evals.ps1 -Suite contract -Case alex-plan-coverage -Confirm

.EXAMPLE
    # Offline sanity check of the trigger judge logic.
    .\run-evals.ps1 -SelfTest
#>
[CmdletBinding()]
param(
    [ValidateSet('trigger', 'contract', 'all')]
    [string]$Suite = 'all',

    [string]$Case,

    [int]$Runs = 5,

    [switch]$Confirm,

    [switch]$SelfTest
)

$ErrorActionPreference = 'Stop'

$EvalsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EvalsPluginRoot = Split-Path -Parent $EvalsRoot
$ResultsPath = Join-Path $EvalsRoot 'results\results.jsonl'

# Rough, deliberately conservative per-run estimates. These are guesses, not
# measurements - once results.jsonl has real duration/outcome data, replace them.
$EstTokensPerContractRun = 20000
$EstTokensPerTriggerRun = 3000
$EstUsdPerThousandTokens = 0.01

# Bump this string whenever the result-record contract (the set of keys written to
# results.jsonl, or their meaning) changes, so a downstream reader can tell which
# shape a given line was written under without guessing from which keys are present.
# "2" = the provenance + flat-record fix (plugin_sha/plugin_dirty/claude_version/
# case_sha256/judge added; the array-with-record-last stream leak closed). Every
# results.jsonl line written before this fix has no harness_version key at all and
# is a bare JSON array, not an object - see README's "Known stale results" note.
$HarnessVersion = '2'

# --- Provenance helpers ---------------------------------------------------------

function Get-PluginGitSha {
    param([string]$PluginRoot)
    try {
        Push-Location $PluginRoot
        try {
            $sha = git rev-parse HEAD 2>$null
            if ($LASTEXITCODE -eq 0 -and $sha) { return ($sha | Out-String).Trim() }
            return $null
        } finally {
            Pop-Location
        }
    } catch {
        return $null
    }
}

function Test-PluginGitDirty {
    param([string]$PluginRoot)
    try {
        Push-Location $PluginRoot
        try {
            $status = git status --porcelain 2>$null
            if ($LASTEXITCODE -ne 0) { return $false }
            return [bool]($status -and (($status | Out-String).Trim().Length -gt 0))
        } finally {
            Pop-Location
        }
    } catch {
        return $false
    }
}

function Get-ClaudeCliVersion {
    try {
        $v = claude --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { return ($v | Out-String).Trim() }
        return $null
    } catch {
        return $null
    }
}

function Get-Sha256HexOfFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    try {
        $result = Get-FileHash -Path $Path -Algorithm SHA256
        return $result.Hash.ToLowerInvariant()
    } catch {
        return $null
    }
}

function Get-Sha256HexOfText {
    param([string]$Text)
    if ($null -eq $Text) { return $null }
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        $hashBytes = $sha256.ComputeHash($bytes)
        return ([BitConverter]::ToString($hashBytes) -replace '-', '').ToLowerInvariant()
    } finally {
        $sha256.Dispose()
    }
}

# --- Trigger judge ----------------------------------------------------------------
# harness_version 2 tightens the old "expected skill name appears anywhere in the
# transcript as a substring" check, which would happily pass a response that says
# "don't use bgpdd-lite here". Preferred path: parse a structured transcript for an
# actual Skill tool_use record and judge on the FIRST skill invoked. Fallback (used
# only when no tool_use record is present, e.g. an older `claude` CLI that ignores
# --output-format json): a substring match that rejects hits preceded within 40
# characters by a negation word.

function Get-FirstSkillFromToolUseJson {
    param([string]$JsonText)

    if ([string]::IsNullOrWhiteSpace($JsonText)) { return $null }

    # `claude -p --output-format json` emits one JSON object; `--output-format
    # stream-json` emits one JSON object per line. Accept either: try the whole text
    # as one document first, then fall back to per-line parsing.
    $messages = @()
    try {
        $parsed = $JsonText | ConvertFrom-Json -ErrorAction Stop
        if ($parsed -is [System.Array]) {
            $messages = $parsed
        } else {
            $messages = @($parsed)
        }
    } catch {
        foreach ($jsonLine in ($JsonText -split "`r?`n")) {
            if ([string]::IsNullOrWhiteSpace($jsonLine)) { continue }
            try {
                $messages += ($jsonLine | ConvertFrom-Json -ErrorAction Stop)
            } catch {
                continue
            }
        }
    }
    if ($messages.Count -eq 0) { return $null }

    foreach ($msg in $messages) {
        if ($null -eq $msg) { continue }
        $content = $null
        if ($msg.PSObject.Properties.Name -contains 'message' -and $msg.message -and
            $msg.message.PSObject.Properties.Name -contains 'content') {
            $content = $msg.message.content
        } elseif ($msg.PSObject.Properties.Name -contains 'content') {
            $content = $msg.content
        }
        if (-not $content) { continue }

        foreach ($block in @($content)) {
            if ($null -eq $block) { continue }
            $blockType = $null
            if ($block.PSObject.Properties.Name -contains 'type') { $blockType = $block.type }
            if ($blockType -ne 'tool_use') { continue }

            $toolName = $null
            if ($block.PSObject.Properties.Name -contains 'name') { $toolName = $block.name }

            $skillName = $null
            if ($block.PSObject.Properties.Name -contains 'input' -and $block.input -and
                $block.input.PSObject.Properties.Name -contains 'skill') {
                $skillName = $block.input.skill
            }

            if ($toolName -eq 'Skill' -and $skillName) {
                return $skillName
            }
        }
    }
    return $null
}

function Test-PositiveSubstringMatch {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text,
        [Parameter(Mandatory = $true)][string]$Needle
    )
    # True if $Needle occurs at least once in $Text without a negation word (not,
    # don't, never, instead of, rather than, avoid) within the preceding 40
    # characters. A needle that occurs only in a negated context returns false.
    if ([string]::IsNullOrWhiteSpace($Needle) -or [string]::IsNullOrEmpty($Text)) { return $false }
    $escaped = [regex]::Escape($Needle)
    $found = [regex]::Matches($Text, $escaped)
    foreach ($m in $found) {
        $windowStart = [Math]::Max(0, $m.Index - 40)
        $window = $Text.Substring($windowStart, $m.Index - $windowStart)
        if ($window -notmatch '(?i)\b(not|don''t|never|instead of|rather than|avoid)\b') {
            return $true
        }
    }
    return $false
}

function Invoke-TriggerJudge {
    param(
        [Parameter(Mandatory = $true)][AllowNull()][string[]]$Acceptable,
        [AllowNull()][string]$ToolUseJson,
        [AllowNull()][string]$FallbackText
    )
    # Returns a PSCustomObject: Pass (bool), Judge ('tool_use'|'substring'), Detail
    # (string, only meaningful context - not machine-parsed by callers).
    $acceptableClean = @($Acceptable | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })

    $firstSkill = $null
    if (-not [string]::IsNullOrWhiteSpace($ToolUseJson)) {
        $firstSkill = Get-FirstSkillFromToolUseJson -JsonText $ToolUseJson
    }
    if ($firstSkill) {
        $isAcceptable = $false
        foreach ($skillName in $acceptableClean) {
            if ($firstSkill -eq $skillName) { $isAcceptable = $true; break }
        }
        if ($isAcceptable) {
            return [PSCustomObject]@{
                Pass   = $true
                Judge  = 'tool_use'
                Detail = "first skill invoked: '$firstSkill' (acceptable)"
            }
        }
        return [PSCustomObject]@{
            Pass   = $false
            Judge  = 'tool_use'
            Detail = "first skill invoked was '$firstSkill', not one of [$($acceptableClean -join ', ')]"
        }
    }

    # No tool_use record found - fall back to the textual judge.
    foreach ($skillName in $acceptableClean) {
        if (Test-PositiveSubstringMatch -Text $FallbackText -Needle $skillName) {
            return [PSCustomObject]@{
                Pass   = $true
                Judge  = 'substring'
                Detail = "matched '$skillName' with no negation word in the preceding 40 characters"
            }
        }
    }
    return [PSCustomObject]@{
        Pass   = $false
        Judge  = 'substring'
        Detail = "none of [$($acceptableClean -join ', ')] found in output as a non-negated match"
    }
}

function Invoke-TriggerJudgeSelfTest {
    $failures = 0

    # Case 1: plain positive substring match, no tool_use record available.
    $r1 = Invoke-TriggerJudge -Acceptable @('bgpdd-lite') -ToolUseJson $null `
        -FallbackText 'The spec is already known, so I will route this to bgpdd-lite instead of full planning.'
    if ($r1.Pass -eq $true -and $r1.Judge -eq 'substring') {
        Write-Host "SELFTEST PASSED: case 1 (positive substring) - $($r1.Detail)"
    } else {
        Write-Host "SELFTEST FAILED: case 1 (positive substring) - got Pass=$($r1.Pass) Judge=$($r1.Judge)"
        $failures++
    }

    # Case 2: a negated mention must NOT count as a match - the exact bug this
    # rewrite closes ("don't use bgpdd-lite here").
    $r2 = Invoke-TriggerJudge -Acceptable @('bgpdd-lite') -ToolUseJson $null `
        -FallbackText "This needs full discovery, so don't use bgpdd-lite here."
    if ($r2.Pass -eq $false -and $r2.Judge -eq 'substring') {
        Write-Host "SELFTEST PASSED: case 2 (negated substring rejected) - $($r2.Detail)"
    } else {
        Write-Host "SELFTEST FAILED: case 2 (negated substring rejected) - got Pass=$($r2.Pass) Judge=$($r2.Judge)"
        $failures++
    }

    # Case 3: a tool_use record naming the acceptable skill passes via the tool_use
    # path even though the same transcript also carries a negated mention of a
    # different skill - proof the tool_use path is preferred over the substring one.
    $toolUseJsonPositive = '{"type":"message","message":{"content":[' +
        '{"type":"text","text":"do not use bgpdd-build for this"},' +
        '{"type":"tool_use","name":"Skill","input":{"skill":"bgpdd-verify"}}' +
        ']}}'
    $r3 = Invoke-TriggerJudge -Acceptable @('bgpdd-verify') -ToolUseJson $toolUseJsonPositive -FallbackText $toolUseJsonPositive
    if ($r3.Pass -eq $true -and $r3.Judge -eq 'tool_use') {
        Write-Host "SELFTEST PASSED: case 3 (tool_use positive) - $($r3.Detail)"
    } else {
        Write-Host "SELFTEST FAILED: case 3 (tool_use positive) - got Pass=$($r3.Pass) Judge=$($r3.Judge)"
        $failures++
    }

    # Case 4: a tool_use record naming a skill NOT in the acceptable list must fail
    # via the tool_use path - it must never silently fall back to a substring match
    # that happens to find the acceptable skill's name in surrounding prose.
    $toolUseJsonNegative = '{"type":"message","message":{"content":[' +
        '{"type":"tool_use","name":"Skill","input":{"skill":"bgpdd-build"}}' +
        ']}}'
    $r4 = Invoke-TriggerJudge -Acceptable @('bgpdd-verify') -ToolUseJson $toolUseJsonNegative -FallbackText $toolUseJsonNegative
    if ($r4.Pass -eq $false -and $r4.Judge -eq 'tool_use') {
        Write-Host "SELFTEST PASSED: case 4 (tool_use negative) - $($r4.Detail)"
    } else {
        Write-Host "SELFTEST FAILED: case 4 (tool_use negative) - got Pass=$($r4.Pass) Judge=$($r4.Judge)"
        $failures++
    }

    return $failures
}

if ($SelfTest) {
    Write-Output '=== Trigger Judge Self-Test (offline, zero tokens) ==='
    $selfTestFailures = Invoke-TriggerJudgeSelfTest
    Write-Output ''
    if ($selfTestFailures -gt 0) {
        Write-Output "SELF-TEST FAILED: $selfTestFailures case(s) did not match the expected outcome."
        exit 1
    }
    Write-Output 'SELF-TEST PASSED: all judge cases matched the expected outcome.'
    exit 0
}

# Computed once, not per-run: these describe the harness invocation as a whole, not
# any one case. Skipped above for -SelfTest so the self-check stays instant/offline.
$PluginSha = Get-PluginGitSha -PluginRoot $EvalsPluginRoot
$PluginDirty = Test-PluginGitDirty -PluginRoot $EvalsPluginRoot
$ClaudeVersion = Get-ClaudeCliVersion

function Get-ContractCaseCommand {
    param([Parameter(Mandatory = $true)][string]$CaseMdPath)

    # -Encoding UTF8 is load-bearing: case.md files are BOM-less UTF-8, and PS 5.1's
    # ANSI default mangles an em-dash into a sequence containing U+201D — a smart
    # quote PowerShell accepts as a string delimiter, so the extracted command
    # becomes unparseable (dep-ship-decision-shape died this way on every run).
    $text = Get-Content -Path $CaseMdPath -Raw -Encoding UTF8
    $pattern = '(?ms)^##\s*Command.*?```(?:powershell)?\s*(.*?)\s*```'
    $match = [regex]::Match($text, $pattern)
    if (-not $match.Success) {
        throw "No fenced powershell block found under '## Command' in $CaseMdPath"
    }
    return $match.Groups[1].Value.Trim()
}

function Get-ContractCaseDocsPath {
    param([Parameter(Mandatory = $true)][string]$CaseMdPath)

    $text = Get-Content -Path $CaseMdPath -Raw -Encoding UTF8
    $match = [regex]::Match($text, '(?m)^-\s*Copies to:\s*`([^`]+)`')
    if (-not $match.Success) {
        throw "No '- Copies to: ``path``' line found in $CaseMdPath"
    }
    return $match.Groups[1].Value.Trim()
}

function Get-ContractCases {
    $contractRoot = Join-Path $EvalsRoot 'contract'
    if (-not (Test-Path $contractRoot)) { return @() }

    # A contract case is a directory carrying BOTH case.md and grade.ps1. The
    # filter is load-bearing, not defensive: `contract/mechanical-pipeline/` is a
    # zero-token run.py harness with neither file, so enumerating directories
    # alone listed it in the plan and then threw when execution reached it.
    Get-ChildItem -Path $contractRoot -Directory | Where-Object {
        (Test-Path (Join-Path $_.FullName 'case.md')) -and
        (Test-Path (Join-Path $_.FullName 'grade.ps1'))
    } | ForEach-Object {
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
            RawLine                = $line
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
Write-Output "Plugin SHA:       $PluginSha$(if ($PluginDirty) { ' (dirty working tree)' })"
Write-Output "claude CLI:       $ClaudeVersion"
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

    # Every run's full agent transcript is archived here - not just failing runs -
    # so a run's output survives after $tempDir is deleted in the finally block below.
    $transcriptDir = Join-Path $resultsDir 'transcripts'
    New-Item -ItemType Directory -Force -Path $transcriptDir | Out-Null
    $transcriptPath = Join-Path $transcriptDir "$($CaseInfo.Name)-run$RunIndex-$suffix.txt"

    try {
        $docsRelPath = Get-ContractCaseDocsPath -CaseMdPath $CaseInfo.CaseMd
        $destination = Join-Path $tempDir $docsRelPath
        New-Item -ItemType Directory -Force -Path $destination | Out-Null
        Copy-Item -Path (Join-Path $CaseInfo.FixtureDir '*') -Destination $destination -Recurse -Force

        # Copy the plugin's agents/ and skills/ into the temp working copy so the
        # case prompts' relative paths (agents/mason.md, skills/runtime-evidence/...)
        # resolve for the agent-under-test. Without this, every persona-compliance
        # criterion fails for a wiring reason: the agent codes fine but never sees
        # its contract. The copy also isolates the run from the live repo, so an
        # agent-under-test can never mutate real plugin files.
        # references/ is included because personas point at it ({PLUGIN_ROOT}/../references/
        # security-checklist.md and friends); without it an agent-under-test citing its own
        # contract's checklist names a file that does not exist in the working copy - which
        # both starves the agent of the checklist and false-fails anti-hallucination path
        # checks in graders (observed: luna-clean-approve 2026-08-28 run 5).
        $pluginRoot = Split-Path -Parent $EvalsRoot
        foreach ($pluginDir in @('agents', 'skills', 'references')) {
            $src = Join-Path $pluginRoot $pluginDir
            $dst = Join-Path $tempDir $pluginDir
            New-Item -ItemType Directory -Force -Path $dst | Out-Null
            Copy-Item -Path (Join-Path $src '*') -Destination $dst -Recurse -Force
        }

        $command = Get-ContractCaseCommand -CaseMdPath $CaseInfo.CaseMd

        Push-Location $tempDir
        try {
            # Captured into a variable, not left to stream: a PowerShell function
            # returns everything written to its success stream, and this
            # Invoke-Expression's un-redirected output used to join the agent's
            # whole transcript into the JSON record built at the bottom of this
            # function - turning every results.jsonl line into an array with the
            # record last instead of a flat object. Capturing it here is the fix.
            $agentOutput = Invoke-Expression $command
        } finally {
            Pop-Location
        }
        # Echoed to the host (not the success/pipeline stream, so it still can't
        # leak into $record below) so a live run stays visible on the console, and
        # archived to a transcript file for every run - see $transcriptPath above.
        $agentOutputText = ($agentOutput | Out-String)
        Write-Host $agentOutputText
        Set-Content -Path $transcriptPath -Value $agentOutputText -Encoding utf8

        $gradeOutput = & $CaseInfo.GradeScript -TargetDir $tempDir
        $gradeExit = $LASTEXITCODE
        # Write-Host, not Write-Output: grade output is for the console, never for
        # this function's return value.
        foreach ($gradeLine in $gradeOutput) { Write-Host "    $gradeLine" }

        $pass = ($gradeExit -eq 0)
        if (-not $pass) {
            $failedLines = @($gradeOutput | Where-Object { $_ -match 'FAILED:' })
            if ($failedLines.Count -gt 0) {
                $failedCriterion = ($failedLines -join ' | ')
            } else {
                $failedCriterion = "grade.ps1 exited $gradeExit"
            }

            # Preserve the failing run's working copy before the finally block
            # deletes it - without this the only evidence of WHY a criterion
            # failed (the plan/report/code the agent actually produced) is
            # destroyed, and a failure like "lint_failures=2" is undiagnosable.
            # agents/ and skills/ are excluded: they are verbatim copies of the
            # plugin tree, not run output.
            $artifactDir = Join-Path $resultsDir "artifacts\$($CaseInfo.Name)-run$RunIndex-$suffix"
            New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
            Get-ChildItem -Path $tempDir -Force |
                Where-Object { $_.Name -notin @('agents', 'skills', 'references', 'node_modules') } |
                Copy-Item -Destination $artifactDir -Recurse -Force -ErrorAction SilentlyContinue
            Set-Content -Path (Join-Path $artifactDir 'grade-output.txt') `
                -Value ($gradeOutput -join "`r`n") -Encoding utf8
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
        plugin_sha       = $PluginSha
        plugin_dirty     = $PluginDirty
        claude_version   = $ClaudeVersion
        case_sha256      = (Get-Sha256HexOfFile -Path $CaseInfo.CaseMd)
        harness_version  = $HarnessVersion
    }
}

function Invoke-TriggerRun {
    param($CaseInfo, [int]$RunIndex)

    $started = Get-Date
    $pass = $false
    $failedCriterion = $null
    $judgeUsed = $null

    try {
        # One call only, with --output-format json: a structured transcript lets
        # Invoke-TriggerJudge check for an actual Skill tool_use record instead of
        # substring-matching prose (a response saying "don't use bgpdd-lite here"
        # used to count as a pass for bgpdd-lite). The same text doubles as the
        # substring fallback's input - a second plain-text call would double the
        # token cost of every trigger run for no benefit, since the raw JSON text
        # still contains any skill name mentioned in it.
        $output = claude -p $CaseInfo.Prompt --permission-mode plan --output-format json 2>&1 | Out-String

        $acceptable = @($CaseInfo.ExpectedSkill) + @($CaseInfo.AcceptableAlternatives)
        $judgeResult = Invoke-TriggerJudge -Acceptable $acceptable -ToolUseJson $output -FallbackText $output

        $pass = $judgeResult.Pass
        $judgeUsed = $judgeResult.Judge
        if (-not $pass) {
            $failedCriterion = $judgeResult.Detail
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
        judge            = $judgeUsed
        plugin_sha       = $PluginSha
        plugin_dirty     = $PluginDirty
        claude_version   = $ClaudeVersion
        case_sha256      = (Get-Sha256HexOfText -Text $CaseInfo.RawLine)
        harness_version  = $HarnessVersion
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
