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
    Zero-token, offline check of the trigger judge (harness_version 3): feeds six
    canned stream-json transcripts - ROUTED_OK, ROUTED_WRONG despite a positive
    mention, NO_ROUTE with and without a mention, a plugin-namespaced skill name, and
    two invocations where the first must decide - through Invoke-TriggerJudge and
    verifies each outcome, pass flag, first_skill and mentioned_only. Exits 0 if every
    case matches, non-zero on any mismatch. Ignores every other parameter and never
    calls `claude` or touches results.jsonl.

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
# Raised from 3000 at harness 3, then raised again from a MEASURED run rather than a
# guess: trigger-1 under harness 3 cost $1.77 over 15 turns and 252s (2026-09-03), because
# a trigger run is no longer a bare routing prompt with nothing to look at - it runs
# against a copied app fixture the model reads, and a NO_ROUTE run keeps exploring
# instead of stopping at a skill invocation. 175000 is what $1.77 comes to under the
# crude per-1k rate below. A full trigger sweep (20 cases x 5 runs) is ~$175, not ~$3.
$EstTokensPerTriggerRun = 175000
$EstUsdPerThousandTokens = 0.01

# Bump this string whenever the result-record contract (the set of keys written to
# results.jsonl, or their meaning) changes, so a downstream reader can tell which
# shape a given line was written under without guessing from which keys are present.
# "2" = the provenance + flat-record fix (plugin_sha/plugin_dirty/claude_version/
# case_sha256/judge added; the array-with-record-last stream leak closed). Every
# results.jsonl line written before this fix has no harness_version key at all and
# is a bare JSON array, not an object - see README's "Known stale results" note.
# "3" = the trigger suite measures ROUTING instead of mention: stream-json transcript,
# a real app-shaped fixture as the working directory, outcome/first_skill/
# mentioned_only/transcript on every trigger record, and NO_ROUTE is a failure.
# EVERY trigger record written under harness_version 1 or 2 measured mention, not
# routing, and must not be read as routing accuracy - see the README.
$HarnessVersion = '3'

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
# harness_version 3 makes the trigger suite measure ROUTING, not mention.
#
# What harness 2 got wrong, empirically (probed 2026-09-03): `claude -p
# --output-format json` returns ONE result object carrying `is_error`, `num_turns`,
# `usage` and a `result` string - and no message content blocks at all. So harness 2's
# tool_use path could never fire, every trigger run silently fell through to the
# substring path, and a run whose model never invoked a skill at all "passed" because
# its clarifying prose happened to name one. `--output-format stream-json --verbose`
# emits one JSON object per line, including
# {"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill",...}]}},
# which is what this judge parses.
#
# Three outcomes, one pass path:
#   ROUTED_OK    - the FIRST Skill tool_use names an acceptable skill. The only pass.
#   ROUTED_WRONG - the first Skill tool_use names something else. Named in the record.
#   NO_ROUTE     - no Skill tool_use anywhere in the transcript. Never a pass, even
#                  when the final answer discusses the right skill in prose; that
#                  diagnostic is recorded as `mentioned_only` and nothing more.
#
# Slash-command note: the CLI's init event lists `Skill` in its `tools` array and has
# no SlashCommand-style tool, and the probe stream contained no such block. Skills are
# invoked exclusively through the `Skill` tool here, so this judge looks for that and
# nothing else. Plugin skills ARE named with a plugin prefix in the CLI's
# `slash_commands` list (`blackgoat-agentskills:bgpdd-plan`), so a skill name is
# normalized by stripping everything up to and including the last colon before it is
# compared against a case's acceptable set.

function ConvertFrom-StreamJsonText {
    param([AllowNull()][string]$Text)
    # One JSON object per line. Non-JSON lines (a stderr warning that got interleaved,
    # a blank line) are skipped rather than fatal.
    $messages = @()
    if ([string]::IsNullOrWhiteSpace($Text)) { return $messages }
    foreach ($jsonLine in ($Text -split "`r?`n")) {
        $trimmed = $jsonLine.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) { continue }
        if ($trimmed[0] -ne '{' -and $trimmed[0] -ne '[') { continue }
        try {
            $messages += ($trimmed | ConvertFrom-Json -ErrorAction Stop)
        } catch {
            continue
        }
    }
    return $messages
}

function Get-SkillNameFromToolUseBlock {
    param($Block)
    # The bare skill name for a `Skill` tool_use block, or $null for anything else.
    if ($null -eq $Block) { return $null }
    $props = @()
    if ($Block.PSObject) { $props = $Block.PSObject.Properties.Name }
    if ($props -notcontains 'type' -or $Block.type -ne 'tool_use') { return $null }
    if ($props -notcontains 'name' -or $Block.name -ne 'Skill') { return $null }
    if ($props -notcontains 'input' -or $null -eq $Block.input) { return $null }

    $blockInput = $Block.input
    $inputProps = @()
    if ($blockInput.PSObject) { $inputProps = $blockInput.PSObject.Properties.Name }
    $raw = $null
    if ($inputProps -contains 'skill') { $raw = $blockInput.skill }
    elseif ($inputProps -contains 'name') { $raw = $blockInput.name }
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }

    # 'blackgoat-agentskills:bgpdd-plan' -> 'bgpdd-plan'
    return (([string]$raw) -replace '^.*:', '').Trim()
}

function Get-FirstSkillInvocation {
    param([AllowNull()][string]$StreamJsonText)
    foreach ($msg in (ConvertFrom-StreamJsonText -Text $StreamJsonText)) {
        if ($null -eq $msg) { continue }
        $content = $null
        $msgProps = @()
        if ($msg.PSObject) { $msgProps = $msg.PSObject.Properties.Name }
        if ($msgProps -contains 'message' -and $msg.message -and
            $msg.message.PSObject.Properties.Name -contains 'content') {
            $content = $msg.message.content
        } elseif ($msgProps -contains 'content') {
            $content = $msg.content
        }
        if (-not $content) { continue }
        foreach ($block in @($content)) {
            $skillName = Get-SkillNameFromToolUseBlock -Block $block
            if ($skillName) { return $skillName }
        }
    }
    return $null
}

function Get-StreamResultText {
    param([AllowNull()][string]$StreamJsonText)
    # The final `{"type":"result", ..., "result":"..."}` line's text - what the user
    # would have seen. Used ONLY for the `mentioned_only` diagnostic.
    $text = $null
    foreach ($msg in (ConvertFrom-StreamJsonText -Text $StreamJsonText)) {
        if ($null -eq $msg) { continue }
        $msgProps = @()
        if ($msg.PSObject) { $msgProps = $msg.PSObject.Properties.Name }
        if ($msgProps -contains 'type' -and $msg.type -eq 'result' -and $msgProps -contains 'result') {
            $text = [string]$msg.result
        }
    }
    return $text
}

function Test-PositiveSubstringMatch {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text,
        [Parameter(Mandatory = $true)][string]$Needle
    )
    # DIAGNOSTIC ONLY as of harness 3. This used to be a pass path; it is not one any
    # more. Its single remaining caller computes `mentioned_only` for a NO_ROUTE run,
    # so a reader can tell "the model reasoned about the right skill but never invoked
    # it" apart from "the model went somewhere else entirely". Neither passes.
    #
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
        [AllowNull()][string]$StreamJson
    )
    # Returns a PSCustomObject: Outcome ('ROUTED_OK'|'ROUTED_WRONG'|'NO_ROUTE'),
    # Pass (bool - true for ROUTED_OK and nothing else), FirstSkill (string or $null),
    # Judge (always 'tool_use'), MentionedOnly (bool, diagnostic), Detail (string).
    $acceptableClean = @($Acceptable | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })

    $firstSkill = Get-FirstSkillInvocation -StreamJsonText $StreamJson
    $resultText = Get-StreamResultText -StreamJsonText $StreamJson
    if ($null -eq $resultText) { $resultText = '' }

    $mentioned = $false
    foreach ($skillName in $acceptableClean) {
        if (Test-PositiveSubstringMatch -Text $resultText -Needle $skillName) { $mentioned = $true; break }
    }

    if ($firstSkill) {
        $isAcceptable = $false
        foreach ($skillName in $acceptableClean) {
            if ($firstSkill -eq $skillName) { $isAcceptable = $true; break }
        }
        if ($isAcceptable) {
            return [PSCustomObject]@{
                Outcome       = 'ROUTED_OK'
                Pass          = $true
                FirstSkill    = $firstSkill
                Judge         = 'tool_use'
                MentionedOnly = $mentioned
                Detail        = "first Skill invocation was '$firstSkill' (acceptable)"
            }
        }
        return [PSCustomObject]@{
            Outcome       = 'ROUTED_WRONG'
            Pass          = $false
            FirstSkill    = $firstSkill
            Judge         = 'tool_use'
            MentionedOnly = $mentioned
            Detail        = "first Skill invocation was '$firstSkill', not one of [$($acceptableClean -join ', ')]"
        }
    }

    $mentionNote = 'the final answer did not name one either'
    if ($mentioned) { $mentionNote = 'the final answer only MENTIONED an acceptable skill - a mention is not a route' }
    return [PSCustomObject]@{
        Outcome       = 'NO_ROUTE'
        Pass          = $false
        FirstSkill    = $null
        Judge         = 'tool_use'
        MentionedOnly = $mentioned
        Detail        = "no Skill tool_use anywhere in the transcript; $mentionNote (expected one of [$($acceptableClean -join ', ')])"
    }
}

function Invoke-TriggerJudgeSelfTest {
    # Every canned transcript below is shaped like a real `--output-format stream-json
    # --verbose` stream: one JSON object per line, assistant messages carrying a
    # `message.content` array, and a final `{"type":"result","result":"..."}` line.
    # The line shapes are copied from the 2026-09-03 probe of trigger-1, so a CLI
    # output-shape change breaks this self-test rather than silently zeroing the suite.
    $failures = 0
    $sysLine = '{"type":"system","subtype":"init","permissionMode":"plan"}'

    function Test-JudgeCase {
        param(
            [string]$Label,
            $Result,
            [string]$ExpectedOutcome,
            [bool]$ExpectedPass,
            [AllowNull()][string]$ExpectedFirstSkill,
            [bool]$ExpectedMentionedOnly
        )
        # FirstSkill is compared as a string on both sides: the judge returns $null for
        # NO_ROUTE, while [AllowNull()][string] coerces the expected $null to '', and
        # `$null -eq ''` is false in PowerShell.
        $ok = ($Result.Outcome -eq $ExpectedOutcome) -and
              ($Result.Pass -eq $ExpectedPass) -and
              (([string]$Result.FirstSkill) -eq ([string]$ExpectedFirstSkill)) -and
              ($Result.MentionedOnly -eq $ExpectedMentionedOnly) -and
              ($Result.Judge -eq 'tool_use')
        if ($ok) {
            Write-Host "SELFTEST PASSED: $Label - $($Result.Outcome), first_skill=$($Result.FirstSkill), mentioned_only=$($Result.MentionedOnly)"
            return 0
        }
        Write-Host ("SELFTEST FAILED: $Label - got Outcome=$($Result.Outcome) Pass=$($Result.Pass) " +
            "FirstSkill=$($Result.FirstSkill) MentionedOnly=$($Result.MentionedOnly) Judge=$($Result.Judge); " +
            "expected Outcome=$ExpectedOutcome Pass=$ExpectedPass FirstSkill=$ExpectedFirstSkill MentionedOnly=$ExpectedMentionedOnly")
        return 1
    }

    # Case 1: ROUTED_OK. The transcript also carries a negated mention of a different
    # skill; the invocation decides, not the prose.
    $s1 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"This is a verify-only ask."},{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"bgpdd-verify"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"Ran bgpdd-verify. I did not use bgpdd-build."}'
    $failures += Test-JudgeCase -Label 'case 1 (ROUTED_OK)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-verify') -StreamJson $s1) `
        -ExpectedOutcome 'ROUTED_OK' -ExpectedPass $true -ExpectedFirstSkill 'bgpdd-verify' -ExpectedMentionedOnly $true

    # Case 2: ROUTED_WRONG. The final answer names the acceptable skill positively -
    # under harness 2 that was a pass. It must not be one.
    $s2 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"bgpdd-build"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"I went to build; bgpdd-verify would also have been reasonable."}'
    $failures += Test-JudgeCase -Label 'case 2 (ROUTED_WRONG despite a positive mention)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-verify') -StreamJson $s2) `
        -ExpectedOutcome 'ROUTED_WRONG' -ExpectedPass $false -ExpectedFirstSkill 'bgpdd-build' -ExpectedMentionedOnly $true

    # Case 3: NO_ROUTE with mentioned_only. This is the 2026-09-03 probe verbatim in
    # shape: the model explored with Glob/ToolSearch/Bash, invoked no skill, and only
    # named bgpdd-plan in its closing prose. Harness 2 scored this a PASS.
    $s3 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Glob","input":{"pattern":"**/*.vue"}}]}}' + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t2","name":"ToolSearch","input":{"query":"select:AskUserQuestion","max_results":3}}]}}' + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t3","name":"Bash","input":{"command":"git remote -v"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"Which repo is the app? Once I know, I would run bgpdd-plan for the spec proper."}'
    $failures += Test-JudgeCase -Label 'case 3 (NO_ROUTE, mentioned_only)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-plan', 'bgpdd-lite') -StreamJson $s3) `
        -ExpectedOutcome 'NO_ROUTE' -ExpectedPass $false -ExpectedFirstSkill $null -ExpectedMentionedOnly $true

    # Case 4: NO_ROUTE where the only mention is negated - mentioned_only must be false,
    # which is how the negation-aware matcher stays honest as a diagnostic.
    $s4 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Glob","input":{"pattern":"**/*.cs"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"This is contained, so do not use bgpdd-plan here."}'
    $failures += Test-JudgeCase -Label 'case 4 (NO_ROUTE, negated mention not counted)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-plan') -StreamJson $s4) `
        -ExpectedOutcome 'NO_ROUTE' -ExpectedPass $false -ExpectedFirstSkill $null -ExpectedMentionedOnly $false

    # Case 5: a plugin-namespaced skill name must normalize to its bare name, or every
    # correct route in a plugin-installed CLI would read as ROUTED_WRONG.
    $s5 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"blackgoat-agentskills:bgpdd-discovery"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"Discovery started."}'
    $failures += Test-JudgeCase -Label 'case 5 (namespaced skill name normalized)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-discovery') -StreamJson $s5) `
        -ExpectedOutcome 'ROUTED_OK' -ExpectedPass $true -ExpectedFirstSkill 'bgpdd-discovery' -ExpectedMentionedOnly $false

    # Case 6: FIRST invocation decides. A wrong first route is not redeemed by a
    # correct second one - that is the routing failure the suite exists to catch.
    $s6 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"bgpdd-plan"}}]}}' + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t2","name":"Skill","input":{"skill":"bgpdd-bugfix"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"Fixed."}'
    $failures += Test-JudgeCase -Label 'case 6 (first invocation decides)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-bugfix') -StreamJson $s6) `
        -ExpectedOutcome 'ROUTED_WRONG' -ExpectedPass $false -ExpectedFirstSkill 'bgpdd-plan' -ExpectedMentionedOnly $false

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

    # Every run's evidence is archived here - not just failing runs - so it survives
    # after $tempDir is deleted in the finally block below. A DIRECTORY, not a single
    # .txt: four cases (mason-fix-verification, mason-fix-verification-tier3,
    # iris-discovery-guard, forge-blackgoat-carveout) pipe the agent's reply into
    # `Out-File handoff.txt` inside the temp copy, so their stdout capture is empty by
    # construction and the entire graded artifact - the handoff element, and whatever
    # the agent wrote under .docs/ - used to be deleted with the temp directory on a
    # PASS. It holds stdout.txt plus handoff.txt and .docs/ when the run produced them.
    $transcriptDirRel = "$($CaseInfo.Name)-run$RunIndex-$suffix"
    $transcriptDir = Join-Path (Join-Path $resultsDir 'transcripts') $transcriptDirRel
    New-Item -ItemType Directory -Force -Path $transcriptDir | Out-Null
    $transcriptPath = Join-Path $transcriptDir 'stdout.txt'

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

        # Copied BEFORE grading, so a grader that throws still leaves the evidence
        # behind. handoff.txt is where the four Out-File cases put the agent's entire
        # reply; .docs/ is where every artifact-producing case writes its output.
        $handoffSrc = Join-Path $tempDir 'handoff.txt'
        if (Test-Path $handoffSrc) {
            Copy-Item -Path $handoffSrc -Destination (Join-Path $transcriptDir 'handoff.txt') -Force
        }
        $docsSrc = Join-Path $tempDir '.docs'
        if (Test-Path $docsSrc) {
            Copy-Item -Path $docsSrc -Destination (Join-Path $transcriptDir '.docs') -Recurse -Force
        }

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
        transcript       = "results/transcripts/$transcriptDirRel"
        harness_version  = $HarnessVersion
    }
}

function Invoke-TriggerRun {
    param($CaseInfo, [int]$RunIndex)

    $started = Get-Date
    $pass = $false
    $failedCriterion = $null
    $outcome = $null
    $firstSkill = $null
    $mentionedOnly = $false

    $suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)
    $tempDir = Join-Path $env:TEMP "eval-$($CaseInfo.Name)-$RunIndex-$suffix"
    $stdinFile = Join-Path $env:TEMP "eval-stdin-$suffix.txt"
    $stdoutFile = Join-Path $env:TEMP "eval-stdout-$suffix.jsonl"
    $stderrFile = Join-Path $env:TEMP "eval-stderr-$suffix.txt"

    $transcriptDir = Join-Path $resultsDir 'transcripts'
    $transcriptName = "$($CaseInfo.Name)-run$RunIndex-$suffix.jsonl"
    $transcriptPath = Join-Path $transcriptDir $transcriptName
    $transcriptRel = "results/transcripts/$transcriptName"

    try {
        New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
        New-Item -ItemType Directory -Force -Path $transcriptDir | Out-Null

        # A trigger run needs something to route ABOUT. Run from the plugin repo root
        # (what harness 2 did), every prompt is unanswerable - the 2026-09-03 probe
        # found no application, asked "which repo?", and invoked no skill at all. The
        # working directory is a per-run copy of trigger/fixture/: a small app-shaped
        # tree (Vue 3 SPA + .NET API + a .docs/ tree) the 20 prompts refer to.
        $fixtureRoot = Join-Path $EvalsRoot 'trigger\fixture'
        if (-not (Test-Path $fixtureRoot)) {
            throw "trigger fixture missing at $fixtureRoot - a trigger run has nothing to route about without it"
        }
        Copy-Item -Path (Join-Path $fixtureRoot '*') -Destination $tempDir -Recurse -Force

        # Same plugin copy-in as Invoke-ContractRun: the prompts that ask about the
        # squad itself (Rex/Alex persona contradictions) need agents/ and skills/ to
        # resolve relative to the working directory, and the copy keeps a run from
        # touching the live repo. Note this does NOT determine which skills are
        # routable - the Skill tool's catalogue comes from the installed plugin, not
        # from the working directory.
        $pluginRoot = Split-Path -Parent $EvalsRoot
        foreach ($pluginDir in @('agents', 'skills', 'references')) {
            $src = Join-Path $pluginRoot $pluginDir
            if (-not (Test-Path $src)) { continue }
            $dst = Join-Path $tempDir $pluginDir
            New-Item -ItemType Directory -Force -Path $dst | Out-Null
            Copy-Item -Path (Join-Path $src '*') -Destination $dst -Recurse -Force
        }

        # stdin redirected from an empty file, not left attached to the console: the
        # CLI otherwise waits and emits "Warning: no stdin data received in 3s..." on
        # stderr ahead of the JSON stream. Start-Process (not a PS pipeline) because
        # it is the only PS 5.1 form that redirects all three streams to files
        # deterministically; the prompt goes through as a single quoted argument.
        New-Item -ItemType File -Path $stdinFile -Force | Out-Null
        $promptArg = ([string]$CaseInfo.Prompt) -replace '"', '\"'
        $argString = '-p "' + $promptArg + '" --permission-mode plan --output-format stream-json --verbose'

        $proc = Start-Process -FilePath 'claude' -ArgumentList $argString `
            -WorkingDirectory $tempDir -NoNewWindow -Wait -PassThru `
            -RedirectStandardInput $stdinFile `
            -RedirectStandardOutput $stdoutFile `
            -RedirectStandardError $stderrFile

        $output = ''
        if (Test-Path $stdoutFile) { $output = Get-Content -Path $stdoutFile -Raw -Encoding UTF8 }
        if ($null -eq $output) { $output = '' }

        # Archived for every run, pass or fail - a routing verdict is only auditable if
        # the stream it was read from survives the temp directory's deletion. Copied,
        # not Set-Content'd: PS 5.1's `-Encoding utf8` prepends a BOM, which makes the
        # archived transcript's FIRST line (the system/init event) unparseable to a
        # plain JSON reader. The archive has to be the bytes the judge read.
        if (Test-Path $stdoutFile) { Copy-Item -Path $stdoutFile -Destination $transcriptPath -Force }

        $stderrText = ''
        if (Test-Path $stderrFile) { $stderrText = (Get-Content -Path $stderrFile -Raw -Encoding UTF8) }
        if ($stderrText -and $stderrText.Trim().Length -gt 0) {
            Copy-Item -Path $stderrFile -Destination ($transcriptPath -replace '\.jsonl$', '-stderr.txt') -Force
            Write-Host "    stderr: $($stderrText.Trim())"
        }

        $acceptable = @($CaseInfo.ExpectedSkill) + @($CaseInfo.AcceptableAlternatives)
        $judgeResult = Invoke-TriggerJudge -Acceptable $acceptable -StreamJson $output

        $pass = $judgeResult.Pass
        $outcome = $judgeResult.Outcome
        $firstSkill = $judgeResult.FirstSkill
        $mentionedOnly = $judgeResult.MentionedOnly
        Write-Host "    $($judgeResult.Outcome): $($judgeResult.Detail)"
        if (-not $pass) {
            $failedCriterion = $judgeResult.Detail
            if ($proc -and $proc.ExitCode -ne 0) {
                $failedCriterion = "claude exited $($proc.ExitCode); $failedCriterion"
            }
        }
    } catch {
        $outcome = 'HARNESS_ERROR'
        $failedCriterion = "harness error: $($_.Exception.Message)"
    } finally {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
        foreach ($scratch in @($stdinFile, $stdoutFile, $stderrFile)) {
            Remove-Item -Path $scratch -Force -ErrorAction SilentlyContinue
        }
    }

    $duration = [math]::Round(((Get-Date) - $started).TotalSeconds, 2)
    return [PSCustomObject]@{
        timestamp        = (Get-Date).ToUniversalTime().ToString('o')
        case             = $CaseInfo.Name
        run_index        = $RunIndex
        pass             = $pass
        outcome          = $outcome
        first_skill      = $firstSkill
        judge            = 'tool_use'
        mentioned_only   = $mentionedOnly
        transcript       = $transcriptRel
        failed_criterion = $failedCriterion
        duration_s       = $duration
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
