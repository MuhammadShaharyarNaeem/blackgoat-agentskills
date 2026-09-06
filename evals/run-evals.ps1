<#
.SYNOPSIS
    Eval harness for the blackgoat-agentskills plugin.

.DESCRIPTION
    Runs headless `claude -p` invocations against frozen fixtures (contract suite)
    and/or checks skill-routing prompts (trigger suite), then appends pass/fail
    records to results/results.jsonl.

    Evals are statistical: a single run proves nothing. Read the pass RATE over N
    runs (see each case.md's Runs/Threshold section), not a single pass/fail. An
    INFRA run is not one of the N - it never reaches results.jsonl at all.

    This script never spends a token unless -Confirm is passed. Without -Confirm it
    only prints the run plan and a rough, unmeasured cost estimate, then exits 0.

    A confirmed batch runs two pre-flight checks first (see Invoke-BatchPreflight):
    one cheap `claude -p` READY probe, and a listen-port check over 5182-5186 for
    every case whose fixture declares a `start` script. Either failing aborts the
    batch before any case runs and records nothing.

    A confirmed contract batch also runs the two zero-LLM cases
    (contract/mechanical-pipeline, contract/bugfix-gates-adversarial) with
    --record first. They cost nothing and their records are the only history those
    cases have.

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
    Zero-token, offline check of the trigger judge and the INFRA classifier
    (harness_version 4): feeds nine canned stream-json transcripts - ROUTED_OK,
    ROUTED_WRONG despite a positive mention, NO_ROUTE with and without a mention, a
    plugin-namespaced skill name, two invocations where the first must decide, and
    three two-hop `expected_chain` cases (routed on correctly, misrouted on, never
    routed on at all) - through Invoke-TriggerJudge and
    verifies each outcome, pass flag, first_skill, skills_invoked and mentioned_only,
    then runs Get-InfraReason against its own classification table. Exits 0 if every
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
# INFRA runs are quarantined here, never appended to results.jsonl: an INFRA run
# measured the harness/API, not the plugin, so counting it consumes one of the N a
# case's threshold is read over and drags a pass rate down for a reason that has
# nothing to do with the persona under test. One file per date, matching the archive
# names the 2026-09-03/04 hand-triage rounds already wrote.
$InfraResultsPath = Join-Path $EvalsRoot ("results\results-invalid-infra-{0}.jsonl" -f (Get-Date).ToString('yyyy-MM-dd'))

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

# --- INFRA classification -------------------------------------------------------
# A run that never really ran must not be recorded as a FAIL. Observed ten times on
# 2026-09-04: `claude` produced zero bytes in 2-30 s, or died with
# `API Error: Connection closed`, and the grader dutifully failed every criterion
# against an empty working copy - a red row that says nothing about the plugin.
#
# Default floor for "this finished far too fast to have been a real agent run", in
# seconds. Overridable per case with a `## Minimum duration` section in case.md
# holding a bare number of seconds (see Get-ContractCaseMinDuration). Every real
# contract run in results.jsonl is minutes; every hand-triaged INFRA run was 2-30 s.
$InfraMinDurationSecondsDefault = 60

# Text patterns in the agent's own output that mean the CLI or API refused, not that
# the persona produced a bad artifact. Anchored where anchoring is safe: `API Error`
# is a line-start CLI banner, while an approval refusal and a quota message can be
# mid-line.
$InfraOutputPatterns = @(
    @{ Pattern = '(?m)^\s*API Error'; Reason = 'the CLI reported an API error' },
    @{ Pattern = '(?i)requires approval'; Reason = 'the run hit a permission prompt (requires approval)' },
    @{ Pattern = '(?i)(usage limit|rate limit)'; Reason = 'the run hit a usage or rate limit' }
)

# Listen ports the node-server fixtures and their graders bind (bgpdd-bugfix-lane,
# the pressure cases, quinn-runtime-evidence, luna-*, dep-ship-decision-shape). A
# stray process holding one of these makes a grader's own wire probe read the wrong
# service, so the pre-flight refuses to start a confirmed batch over it.
$FixturePortsToCheck = 5182, 5183, 5184, 5185, 5186, 5193

# The two zero-LLM cases. Invisible to Get-ContractCases by design (neither has a
# case.md or a grade.ps1) and free to run, so a confirmed contract batch runs both
# with --record before spending a token - previously they left no history at all.
$ZeroLlmCases = @(
    @{ Name = 'mechanical-pipeline'; Script = 'contract\mechanical-pipeline\run.py' },
    @{ Name = 'bugfix-gates-adversarial'; Script = 'contract\bugfix-gates-adversarial\run.py' }
    @{ Name = 'openapi-diff-adversarial'; Script = 'contract\openapi-diff-adversarial\run.py' }
)

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
# "4" = INFRA is classified mechanically instead of by hand. `outcome` is now on
# CONTRACT records too ('GRADED' or 'INFRA'); an INFRA record carries `pass: null`,
# `triage: "INFRA"` and goes to results-invalid-infra-<date>.jsonl, never to
# results.jsonl, so it does not consume one of a case's N. Trigger records gained
# `skills_invoked` (the full ordered invocation list) and a case may assert an
# `expected_chain` prefix over it. The two zero-LLM cases now write their own flat
# records with `judge: "script"`.
$HarnessVersion = '4'

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

# --- INFRA classifier -------------------------------------------------------------
# The one predicate that decides whether a run is EVIDENCE or NOISE. Called after the
# agent invocation and BEFORE grading, so a grader never gets to fail eleven criteria
# against a working copy the agent never touched.
#
# Returns a reason string (the run is INFRA) or $null (the run is real; grade it).
# Order matters only for which reason gets reported first; any single hit is enough.

function Get-InfraReason {
    param(
        [AllowNull()][AllowEmptyString()][string]$OutputText,
        [double]$DurationSeconds = -1,
        [int]$MinDurationSeconds = 0
    )
    # 1. Zero bytes. The 2026-09-04 signature: the CLI exits without writing a word,
    #    so there is no artifact, no handoff and nothing to grade.
    if ([string]::IsNullOrWhiteSpace($OutputText)) {
        return 'the agent produced no output at all (empty or whitespace stdout)'
    }

    # 2. The CLI/API said no. `API Error: Connection closed`, a permission prompt the
    #    headless run cannot answer, a usage or rate limit.
    foreach ($entry in $InfraOutputPatterns) {
        $match = [regex]::Match($OutputText, $entry.Pattern)
        if ($match.Success) {
            $excerpt = ($match.Value -replace '\s+', ' ').Trim()
            return "$($entry.Reason) [matched: $excerpt]"
        }
    }

    # 3. Impossibly fast. A real persona run against a fixture is minutes; every run
    #    hand-triaged INFRA so far finished in 2-30 s. Only applied when a floor is
    #    in force (contract runs; see Get-ContractCaseMinDuration).
    if ($MinDurationSeconds -gt 0 -and $DurationSeconds -ge 0 -and
        $DurationSeconds -lt $MinDurationSeconds) {
        return ("the run finished in ${DurationSeconds}s, under this case's " +
                "${MinDurationSeconds}s minimum expected duration")
    }

    return $null
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

function Get-ContractCaseMinDuration {
    param([Parameter(Mandatory = $true)][string]$CaseMdPath)

    # Optional `## Minimum duration` section holding a bare number of seconds:
    #
    #     ## Minimum duration
    #     240
    #
    # A run that finishes faster than this did not really run - see Get-InfraReason
    # rule 3. Absent (the normal case) means $InfraMinDurationSecondsDefault, which
    # is why a case only needs this section when its floor should be HIGHER than 60.
    # An unparseable value falls back to the default rather than throwing: a typo in
    # a case.md must not take the whole batch down.
    if (-not (Test-Path $CaseMdPath)) { return $InfraMinDurationSecondsDefault }
    $text = Get-Content -Path $CaseMdPath -Raw -Encoding UTF8
    $match = [regex]::Match($text, '(?ms)^##\s*Minimum duration\s*\r?\n+\s*(\d+)')
    if (-not $match.Success) { return $InfraMinDurationSecondsDefault }
    $parsed = 0
    if ([int]::TryParse($match.Groups[1].Value, [ref]$parsed) -and $parsed -gt 0) {
        return $parsed
    }
    return $InfraMinDurationSecondsDefault
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

function Get-SkillInvocations {
    param([AllowNull()][string]$StreamJsonText)
    # EVERY `Skill` tool_use in the transcript, in stream order. The first element is
    # what `first_skill` and the default first-invocation rule read; the whole list is
    # recorded as `skills_invoked` and is what an `expected_chain` case asserts a
    # prefix of. Without the full list a `/bg` case can only ever prove "the front
    # door opened" - the router's entire job is the SECOND hop.
    $invocations = @()
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
            if ($skillName) { $invocations += $skillName }
        }
    }
    # Returned to the pipeline unwrapped, and EVERY caller must re-wrap with @(): a
    # comma-wrapped `return ,$invocations` survives @() as a one-element array holding
    # the array, which reads back as 'System.Object[]' and makes $skillsInvoked[0] an
    # array instead of a skill name (caught by the self-test on the first run).
    return $invocations
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
        [AllowNull()][string]$StreamJson,
        [AllowNull()][string[]]$ExpectedChain
    )
    # Returns a PSCustomObject: Outcome ('ROUTED_OK'|'ROUTED_WRONG'|'NO_ROUTE'),
    # Pass (bool - true for ROUTED_OK and nothing else), FirstSkill (string or $null),
    # SkillsInvoked (string[], every Skill invocation in stream order),
    # Judge (always 'tool_use'), MentionedOnly (bool, diagnostic), Detail (string).
    #
    # TWO judging rules, and the default is unchanged:
    #   - No -ExpectedChain (every case but the two `/bg` ones): the FIRST invocation
    #     decides, full stop. A wrong first route followed by a correct second one is
    #     still ROUTED_WRONG.
    #   - With -ExpectedChain: `skills_invoked` must START WITH that exact ordered
    #     chain. This is the only way to judge a router: `/bg` is SUPPOSED to invoke a
    #     second skill, so a first-invocation judge can only ever see `bg` and prove
    #     the front door opened. A chain case does not consult $Acceptable at all
    #     (except for the mentioned_only diagnostic) - the chain IS the assertion.
    $acceptableClean = @($Acceptable | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    $chainClean = @($ExpectedChain | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })

    $skillsInvoked = @(Get-SkillInvocations -StreamJsonText $StreamJson)
    $firstSkill = $null
    if ($skillsInvoked.Count -gt 0) { $firstSkill = $skillsInvoked[0] }
    $resultText = Get-StreamResultText -StreamJsonText $StreamJson
    if ($null -eq $resultText) { $resultText = '' }

    $mentioned = $false
    foreach ($skillName in $acceptableClean) {
        if (Test-PositiveSubstringMatch -Text $resultText -Needle $skillName) { $mentioned = $true; break }
    }

    $mentionNote = 'the final answer did not name one either'
    if ($mentioned) { $mentionNote = 'the final answer only MENTIONED an acceptable skill - a mention is not a route' }

    if ($chainClean.Count -gt 0) {
        if ($skillsInvoked.Count -eq 0) {
            return [PSCustomObject]@{
                Outcome       = 'NO_ROUTE'
                Pass          = $false
                FirstSkill    = $null
                SkillsInvoked = $skillsInvoked
                Judge         = 'tool_use'
                MentionedOnly = $mentioned
                Detail        = "no Skill tool_use anywhere in the transcript; $mentionNote (expected the chain [$($chainClean -join ' -> ')])"
            }
        }
        $chainOk = ($skillsInvoked.Count -ge $chainClean.Count)
        if ($chainOk) {
            for ($idx = 0; $idx -lt $chainClean.Count; $idx++) {
                if ($skillsInvoked[$idx] -ne $chainClean[$idx]) { $chainOk = $false; break }
            }
        }
        if ($chainOk) {
            return [PSCustomObject]@{
                Outcome       = 'ROUTED_OK'
                Pass          = $true
                FirstSkill    = $firstSkill
                SkillsInvoked = $skillsInvoked
                Judge         = 'tool_use'
                MentionedOnly = $mentioned
                Detail        = "the invocation chain [$($skillsInvoked -join ' -> ')] starts with the expected [$($chainClean -join ' -> ')]"
            }
        }
        return [PSCustomObject]@{
            Outcome       = 'ROUTED_WRONG'
            Pass          = $false
            FirstSkill    = $firstSkill
            SkillsInvoked = $skillsInvoked
            Judge         = 'tool_use'
            MentionedOnly = $mentioned
            Detail        = "the invocation chain was [$($skillsInvoked -join ' -> ')], which does not start with the expected [$($chainClean -join ' -> ')]"
        }
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
                SkillsInvoked = $skillsInvoked
                Judge         = 'tool_use'
                MentionedOnly = $mentioned
                Detail        = "first Skill invocation was '$firstSkill' (acceptable)"
            }
        }
        return [PSCustomObject]@{
            Outcome       = 'ROUTED_WRONG'
            Pass          = $false
            FirstSkill    = $firstSkill
            SkillsInvoked = $skillsInvoked
            Judge         = 'tool_use'
            MentionedOnly = $mentioned
            Detail        = "first Skill invocation was '$firstSkill', not one of [$($acceptableClean -join ', ')]"
        }
    }

    return [PSCustomObject]@{
        Outcome       = 'NO_ROUTE'
        Pass          = $false
        FirstSkill    = $null
        SkillsInvoked = $skillsInvoked
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
            [bool]$ExpectedMentionedOnly,
            [AllowNull()][string[]]$ExpectedSkillsInvoked
        )
        # FirstSkill is compared as a string on both sides: the judge returns $null for
        # NO_ROUTE, while [AllowNull()][string] coerces the expected $null to '', and
        # `$null -eq ''` is false in PowerShell. SkillsInvoked is compared as a joined
        # string for the same reason - an array compare in PS 5.1 is an element-wise
        # filter, not an equality test.
        $gotChain = (@($Result.SkillsInvoked) -join ' -> ')
        $wantChain = (@($ExpectedSkillsInvoked) -join ' -> ')
        $ok = ($Result.Outcome -eq $ExpectedOutcome) -and
              ($Result.Pass -eq $ExpectedPass) -and
              (([string]$Result.FirstSkill) -eq ([string]$ExpectedFirstSkill)) -and
              ($Result.MentionedOnly -eq $ExpectedMentionedOnly) -and
              ($gotChain -eq $wantChain) -and
              ($Result.Judge -eq 'tool_use')
        if ($ok) {
            Write-Host "SELFTEST PASSED: $Label - $($Result.Outcome), first_skill=$($Result.FirstSkill), skills_invoked=[$gotChain], mentioned_only=$($Result.MentionedOnly)"
            return 0
        }
        Write-Host ("SELFTEST FAILED: $Label - got Outcome=$($Result.Outcome) Pass=$($Result.Pass) " +
            "FirstSkill=$($Result.FirstSkill) SkillsInvoked=[$gotChain] MentionedOnly=$($Result.MentionedOnly) Judge=$($Result.Judge); " +
            "expected Outcome=$ExpectedOutcome Pass=$ExpectedPass FirstSkill=$ExpectedFirstSkill SkillsInvoked=[$wantChain] MentionedOnly=$ExpectedMentionedOnly")
        return 1
    }

    function Test-InfraCase {
        param(
            [string]$Label,
            [AllowNull()][AllowEmptyString()][string]$OutputText,
            [double]$DurationSeconds,
            [int]$MinDurationSeconds,
            [bool]$ExpectInfra,
            [AllowNull()][string]$ExpectedReasonMatch
        )
        # The classifier is the gate between "this is evidence" and "this is noise",
        # so it is proven here against both directions: a real-looking run must NOT be
        # quarantined, and each refusal signature must be.
        $reason = Get-InfraReason -OutputText $OutputText -DurationSeconds $DurationSeconds `
            -MinDurationSeconds $MinDurationSeconds
        $isInfra = ($null -ne $reason)
        $ok = ($isInfra -eq $ExpectInfra)
        if ($ok -and $ExpectInfra -and $ExpectedReasonMatch) {
            $ok = ($reason -match $ExpectedReasonMatch)
        }
        if ($ok) {
            Write-Host "SELFTEST PASSED: $Label - infra=$isInfra reason='$reason'"
            return 0
        }
        Write-Host ("SELFTEST FAILED: $Label - got infra=$isInfra reason='$reason'; " +
            "expected infra=$ExpectInfra matching '$ExpectedReasonMatch'")
        return 1
    }

    # Case 1: ROUTED_OK. The transcript also carries a negated mention of a different
    # skill; the invocation decides, not the prose.
    $s1 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"This is a verify-only ask."},{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"bgpdd-verify"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"Ran bgpdd-verify. I did not use bgpdd-build."}'
    $failures += Test-JudgeCase -Label 'case 1 (ROUTED_OK)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-verify') -StreamJson $s1) `
        -ExpectedOutcome 'ROUTED_OK' -ExpectedPass $true -ExpectedFirstSkill 'bgpdd-verify' -ExpectedMentionedOnly $true `
        -ExpectedSkillsInvoked @('bgpdd-verify')

    # Case 2: ROUTED_WRONG. The final answer names the acceptable skill positively -
    # under harness 2 that was a pass. It must not be one.
    $s2 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"bgpdd-build"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"I went to build; bgpdd-verify would also have been reasonable."}'
    $failures += Test-JudgeCase -Label 'case 2 (ROUTED_WRONG despite a positive mention)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-verify') -StreamJson $s2) `
        -ExpectedOutcome 'ROUTED_WRONG' -ExpectedPass $false -ExpectedFirstSkill 'bgpdd-build' -ExpectedMentionedOnly $true `
        -ExpectedSkillsInvoked @('bgpdd-build')

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
        -ExpectedOutcome 'NO_ROUTE' -ExpectedPass $false -ExpectedFirstSkill $null -ExpectedMentionedOnly $true `
        -ExpectedSkillsInvoked @()

    # Case 4: NO_ROUTE where the only mention is negated - mentioned_only must be false,
    # which is how the negation-aware matcher stays honest as a diagnostic.
    $s4 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Glob","input":{"pattern":"**/*.cs"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"This is contained, so do not use bgpdd-plan here."}'
    $failures += Test-JudgeCase -Label 'case 4 (NO_ROUTE, negated mention not counted)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-plan') -StreamJson $s4) `
        -ExpectedOutcome 'NO_ROUTE' -ExpectedPass $false -ExpectedFirstSkill $null -ExpectedMentionedOnly $false `
        -ExpectedSkillsInvoked @()

    # Case 5: a plugin-namespaced skill name must normalize to its bare name, or every
    # correct route in a plugin-installed CLI would read as ROUTED_WRONG.
    $s5 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"blackgoat-agentskills:bgpdd-discovery"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"Discovery started."}'
    $failures += Test-JudgeCase -Label 'case 5 (namespaced skill name normalized)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-discovery') -StreamJson $s5) `
        -ExpectedOutcome 'ROUTED_OK' -ExpectedPass $true -ExpectedFirstSkill 'bgpdd-discovery' -ExpectedMentionedOnly $false `
        -ExpectedSkillsInvoked @('bgpdd-discovery')

    # Case 6: FIRST invocation decides. A wrong first route is not redeemed by a
    # correct second one - that is the routing failure the suite exists to catch.
    $s6 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"bgpdd-plan"}}]}}' + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t2","name":"Skill","input":{"skill":"bgpdd-bugfix"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"Fixed."}'
    $failures += Test-JudgeCase -Label 'case 6 (first invocation decides)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-bugfix') -StreamJson $s6) `
        -ExpectedOutcome 'ROUTED_WRONG' -ExpectedPass $false -ExpectedFirstSkill 'bgpdd-plan' -ExpectedMentionedOnly $false `
        -ExpectedSkillsInvoked @('bgpdd-plan', 'bgpdd-bugfix')

    # --- Two-hop cases: -ExpectedChain, for the `/bg` router -------------------
    # Cases 7-9 are the whole reason `skills_invoked` exists. Note what the FIRST
    # transcript below would have scored under the default rule with `bg` in
    # acceptable_alternatives (which is how trigger-28/29 were written): ROUTED_OK -
    # and so would case 8's and case 9's. Three different router behaviours, one
    # green. That is the false pass the chain judge closes.

    # Case 7: the router routed, and to the right place. The only two-hop pass.
    $s7 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"blackgoat-agentskills:bg"}}]}}' + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t2","name":"Skill","input":{"skill":"blackgoat-agentskills:bgpdd-quick"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"Routed to bgpdd-quick and renamed it."}'
    $failures += Test-JudgeCase -Label 'case 7 (two-hop chain bg -> bgpdd-quick, ROUTED_OK)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-quick', 'bg') -StreamJson $s7 `
            -ExpectedChain @('bg', 'bgpdd-quick')) `
        -ExpectedOutcome 'ROUTED_OK' -ExpectedPass $true -ExpectedFirstSkill 'bg' -ExpectedMentionedOnly $true `
        -ExpectedSkillsInvoked @('bg', 'bgpdd-quick')

    # Case 8: the front door opened and the router misrouted - a contained rename
    # sent to the mid-weight spec lane. The failure a first-invocation judge cannot
    # see, and the reason the README's "does not verify the destination" caveat
    # existed.
    $s8 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"bg"}}]}}' + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t2","name":"Skill","input":{"skill":"bgpdd-lite"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"Routed to bgpdd-lite."}'
    $failures += Test-JudgeCase -Label 'case 8 (two-hop misroute bg -> bgpdd-lite, ROUTED_WRONG)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-quick', 'bg') -StreamJson $s8 `
            -ExpectedChain @('bg', 'bgpdd-quick')) `
        -ExpectedOutcome 'ROUTED_WRONG' -ExpectedPass $false -ExpectedFirstSkill 'bg' -ExpectedMentionedOnly $true `
        -ExpectedSkillsInvoked @('bg', 'bgpdd-lite')
    # mentioned_only is $true above for a reason worth knowing: `bg` is a SUBSTRING of
    # `bgpdd-lite`, and Test-PositiveSubstringMatch is a plain substring matcher. That
    # is harmless now (the diagnostic never decides anything) but it is precisely why
    # a `/bg` case must not be judged on prose - "bg" positively "appears" in the name
    # of every lane it could possibly misroute to.

    # Case 9: the router opened and did the work itself - no second hop at all. A
    # chain shorter than the expected one is ROUTED_WRONG, not ROUTED_OK-by-prefix.
    $s9 = $sysLine + "`n" +
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"tool_use","id":"t1","name":"Skill","input":{"skill":"bg"}}]}}' + "`n" +
        '{"type":"result","subtype":"success","is_error":false,"result":"Renamed it for you."}'
    $failures += Test-JudgeCase -Label 'case 9 (router opened, never routed on)' `
        -Result (Invoke-TriggerJudge -Acceptable @('bgpdd-quick', 'bg') -StreamJson $s9 `
            -ExpectedChain @('bg', 'bgpdd-quick')) `
        -ExpectedOutcome 'ROUTED_WRONG' -ExpectedPass $false -ExpectedFirstSkill 'bg' -ExpectedMentionedOnly $false `
        -ExpectedSkillsInvoked @('bg')

    # --- INFRA classifier ------------------------------------------------------
    Write-Host ''
    $failures += Test-InfraCase -Label 'infra 1 (empty stdout)' `
        -OutputText '' -DurationSeconds 4.2 -MinDurationSeconds 60 `
        -ExpectInfra $true -ExpectedReasonMatch 'no output at all'
    $failures += Test-InfraCase -Label 'infra 2 (whitespace-only stdout)' `
        -OutputText "  `r`n `t " -DurationSeconds 900 -MinDurationSeconds 60 `
        -ExpectInfra $true -ExpectedReasonMatch 'no output at all'
    $failures += Test-InfraCase -Label 'infra 3 (API Error banner, long run)' `
        -OutputText "Reading the fixture...`nAPI Error: Connection closed`n" `
        -DurationSeconds 540 -MinDurationSeconds 60 `
        -ExpectInfra $true -ExpectedReasonMatch 'API error'
    $failures += Test-InfraCase -Label 'infra 4 (permission prompt)' `
        -OutputText "I tried to run the gate but Bash(git commit) requires approval." `
        -DurationSeconds 300 -MinDurationSeconds 60 `
        -ExpectInfra $true -ExpectedReasonMatch 'permission prompt'
    $failures += Test-InfraCase -Label 'infra 5 (usage limit)' `
        -OutputText "Claude usage limit reached. Your limit will reset at 3pm." `
        -DurationSeconds 6 -MinDurationSeconds 60 `
        -ExpectInfra $true -ExpectedReasonMatch 'usage or rate limit'
    $failures += Test-InfraCase -Label 'infra 6 (real output, impossibly fast)' `
        -OutputText "Wrote .docs/orders/implementation/plan.md with 3 milestones." `
        -DurationSeconds 12.5 -MinDurationSeconds 60 `
        -ExpectInfra $true -ExpectedReasonMatch 'under this case'
    $failures += Test-InfraCase -Label 'infra 7 (real output, real duration -> NOT infra)' `
        -OutputText "Wrote .docs/orders/implementation/plan.md with 3 milestones." `
        -DurationSeconds 240 -MinDurationSeconds 60 `
        -ExpectInfra $false -ExpectedReasonMatch $null
    # The floor is the ONLY rule a trigger run does not get (no case.md, so no
    # declared minimum): a fast NO_ROUTE is a real routing result, not noise.
    $failures += Test-InfraCase -Label 'infra 8 (no floor in force -> fast run is NOT infra)' `
        -OutputText "no skill for this" -DurationSeconds 3 -MinDurationSeconds 0 `
        -ExpectInfra $false -ExpectedReasonMatch $null
    # A grader FAILURE is not an INFRA signature. The classifier must never swallow a
    # real red run - that would be the same category error in the other direction.
    $failures += Test-InfraCase -Label 'infra 9 (a genuine failing run is NOT infra)' `
        -OutputText "I could not find requirements.md, so I stopped without writing a plan." `
        -DurationSeconds 180 -MinDurationSeconds 60 `
        -ExpectInfra $false -ExpectedReasonMatch $null

    # --- `## Minimum duration` parsing ----------------------------------------
    # The floor the classifier's third rule reads. An unproven parser here fails in
    # the two worst directions available: silently returning the default would make
    # a case's declared floor a comment, and throwing on a typo in a markdown file
    # would take a whole confirmed batch down.
    Write-Host ''
    $tempCaseDir = Join-Path $env:TEMP ("eval-selftest-minduration-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $tempCaseDir | Out-Null
    try {
        $minCases = @(
            @{ Label = 'min 1 (no section -> default)'
               Body = "## Purpose`nx`n`n## Runs / Threshold`n``runs=5``, threshold **4/5**.`n"
               Expect = $InfraMinDurationSecondsDefault },
            @{ Label = 'min 2 (declared 240 -> 240)'
               Body = "## Purpose`nx`n`n## Minimum duration`n240`n`n## Future (not implemented)`nnone`n"
               Expect = 240 },
            @{ Label = 'min 3 (blank lines and indent before the number)'
               Body = "## Minimum duration`n`n`n  180`n"
               Expect = 180 },
            @{ Label = 'min 4 (garbage -> default, does not throw)'
               Body = "## Minimum duration`nsomewhere north of a while`n"
               Expect = $InfraMinDurationSecondsDefault },
            @{ Label = 'min 5 (zero -> default; a floor of 0 disables the rule by accident)'
               Body = "## Minimum duration`n0`n"
               Expect = $InfraMinDurationSecondsDefault }
        )
        $caseIndex = 0
        foreach ($minCase in $minCases) {
            $caseIndex++
            $casePath = Join-Path $tempCaseDir "case-$caseIndex.md"
            Set-Content -Path $casePath -Value $minCase.Body -Encoding utf8 -NoNewline
            $got = Get-ContractCaseMinDuration -CaseMdPath $casePath
            if ($got -eq $minCase.Expect) {
                Write-Host "SELFTEST PASSED: $($minCase.Label) - got $got"
            } else {
                Write-Host "SELFTEST FAILED: $($minCase.Label) - got $got, expected $($minCase.Expect)"
                $failures++
            }
        }
        # A missing case.md must fall back, not throw. Get-ContractCases only lists
        # directories that have one, but a file deleted mid-batch would otherwise
        # take the run down.
        $absent = Get-ContractCaseMinDuration -CaseMdPath (Join-Path $tempCaseDir 'does-not-exist.md')
        if ($absent -eq $InfraMinDurationSecondsDefault) {
            Write-Host "SELFTEST PASSED: min 6 (missing case.md -> default) - got $absent"
        } else {
            Write-Host "SELFTEST FAILED: min 6 (missing case.md -> default) - got $absent, expected $InfraMinDurationSecondsDefault"
            $failures++
        }
        # And the real cases must all still parse to a sane floor - the parser
        # running against the actual suite, not only against synthetic input.
        $realCases = @(Get-ContractCases)
        $badFloors = @()
        foreach ($realCase in $realCases) {
            $floor = Get-ContractCaseMinDuration -CaseMdPath $realCase.CaseMd
            if ($floor -lt 1 -or $floor -gt 3600) { $badFloors += "$($realCase.Name)=$floor" }
        }
        if ($badFloors.Count -eq 0) {
            Write-Host "SELFTEST PASSED: min 7 (all $($realCases.Count) real case.md files parse to a sane floor)"
        } else {
            Write-Host "SELFTEST FAILED: min 7 - implausible floors: $($badFloors -join ', ')"
            $failures++
        }
    } finally {
        Remove-Item -Path $tempCaseDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    return $failures
}

if ($SelfTest) {
    Write-Output '=== Harness self-test: trigger judge, INFRA classifier, case.md floors (offline, zero tokens) ==='
    $selfTestFailures = Invoke-TriggerJudgeSelfTest
    Write-Output ''
    if ($selfTestFailures -gt 0) {
        Write-Output "SELF-TEST FAILED: $selfTestFailures case(s) did not match the expected outcome."
        exit 1
    }
    Write-Output 'SELF-TEST PASSED: every judge, classifier and floor case matched the expected outcome.'
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

function Get-TriggerCases {
    $triggerPath = Join-Path $EvalsRoot 'trigger\cases.jsonl'
    if (-not (Test-Path $triggerPath)) { return @() }

    $lineNumber = 0
    $results = @()
    foreach ($line in Get-Content -Path $triggerPath) {
        $lineNumber++
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $obj = $line | ConvertFrom-Json
        # expected_chain is optional and, when present, supersedes the
        # first-invocation rule for that case (see Invoke-TriggerJudge). Only the two
        # `/bg` router cases carry one.
        $expectedChain = @()
        if ($obj.PSObject.Properties.Name -contains 'expected_chain' -and $obj.expected_chain) {
            $expectedChain = @($obj.expected_chain)
        }
        $results += [PSCustomObject]@{
            Name                   = "trigger-$lineNumber"
            Type                   = 'trigger'
            Prompt                 = $obj.prompt
            ExpectedSkill          = $obj.expected_skill
            AcceptableAlternatives = $obj.acceptable_alternatives
            ExpectedChain          = $expectedChain
            RawLine                = $line
        }
    }
    return $results
}

# --- Pre-flight -------------------------------------------------------------------
# Two checks that run once, after -Confirm and before the FIRST case executes. Both
# exist because a whole confirmed batch has been spent on a broken precondition: ten
# runs on 2026-09-04 recorded FAIL against an API that was refusing every call, and a
# grader that probes a fixture's own port reads whatever is listening there, not
# necessarily the service the run started.
#
# A failing pre-flight ABORTS and records nothing. That is the point: a batch that
# cannot produce evidence must not produce rows.

function Test-ClaudeCliReady {
    # One cheap `claude -p` round trip. Costs a handful of tokens - orders of
    # magnitude less than one contract run, and it is the only way to distinguish
    # "the plugin regressed" from "the API is down" BEFORE spending the batch.
    $suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)
    $stdinFile = Join-Path $env:TEMP "eval-preflight-stdin-$suffix.txt"
    $stdoutFile = Join-Path $env:TEMP "eval-preflight-stdout-$suffix.json"
    $stderrFile = Join-Path $env:TEMP "eval-preflight-stderr-$suffix.txt"
    try {
        New-Item -ItemType File -Path $stdinFile -Force | Out-Null
        $proc = Start-Process -FilePath 'claude' `
            -ArgumentList '-p "reply with the word READY" --output-format json' `
            -WorkingDirectory $EvalsRoot -NoNewWindow -Wait -PassThru `
            -RedirectStandardInput $stdinFile `
            -RedirectStandardOutput $stdoutFile `
            -RedirectStandardError $stderrFile

        $stdout = ''
        if (Test-Path $stdoutFile) { $stdout = Get-Content -Path $stdoutFile -Raw -Encoding UTF8 }
        $stderr = ''
        if (Test-Path $stderrFile) { $stderr = Get-Content -Path $stderrFile -Raw -Encoding UTF8 }
        if ($null -eq $stdout) { $stdout = '' }
        if ($null -eq $stderr) { $stderr = '' }

        if ($proc.ExitCode -ne 0) {
            return [PSCustomObject]@{ Ready = $false
                Detail = "claude exited $($proc.ExitCode). stderr: $($stderr.Trim()) stdout: $($stdout.Trim())" }
        }
        if ([string]::IsNullOrWhiteSpace($stdout)) {
            return [PSCustomObject]@{ Ready = $false
                Detail = "claude exited 0 but wrote nothing. stderr: $($stderr.Trim())" }
        }
        $parsed = $null
        try {
            $parsed = $stdout | ConvertFrom-Json -ErrorAction Stop
        } catch {
            return [PSCustomObject]@{ Ready = $false
                Detail = "could not parse --output-format json: $($stdout.Trim())" }
        }
        $props = @()
        if ($parsed.PSObject) { $props = $parsed.PSObject.Properties.Name }
        if ($props -contains 'is_error' -and $parsed.is_error) {
            return [PSCustomObject]@{ Ready = $false
                Detail = "the CLI reported is_error: $($parsed.result)" }
        }
        $answer = ''
        if ($props -contains 'result') { $answer = [string]$parsed.result }
        if ($answer -notmatch '(?i)READY') {
            return [PSCustomObject]@{ Ready = $false
                Detail = "expected READY, got: $($answer.Trim())" }
        }
        return [PSCustomObject]@{ Ready = $true; Detail = $answer.Trim() }
    } catch {
        return [PSCustomObject]@{ Ready = $false; Detail = "probe threw: $($_.Exception.Message)" }
    } finally {
        foreach ($scratch in @($stdinFile, $stdoutFile, $stderrFile)) {
            Remove-Item -Path $scratch -Force -ErrorAction SilentlyContinue
        }
    }
}

function Test-CaseNeedsFixturePorts {
    param($CaseInfo)
    # A case needs the port range iff its fixture is a startable service. Read off
    # `scripts.start` in the fixture's own package.json rather than a hand-maintained
    # case list, so a new server-shaped fixture is covered the day it lands.
    if ($CaseInfo.Type -ne 'contract') { return $false }
    $pkg = Join-Path $CaseInfo.FixtureDir 'package.json'
    if (-not (Test-Path $pkg)) { return $false }
    try {
        $parsed = (Get-Content -Path $pkg -Raw -Encoding UTF8) | ConvertFrom-Json -ErrorAction Stop
    } catch {
        return $false
    }
    if (-not $parsed.PSObject) { return $false }
    if ($parsed.PSObject.Properties.Name -notcontains 'scripts' -or -not $parsed.scripts) { return $false }
    if ($parsed.scripts.PSObject.Properties.Name -notcontains 'start') { return $false }
    return (-not [string]::IsNullOrWhiteSpace([string]$parsed.scripts.start))
}

function Get-BusyFixturePorts {
    # Every port in $FixturePortsToCheck that already has a LISTENer, with the owning
    # PID and process name so the message is actionable rather than just alarming.
    $busy = @()
    if (-not (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)) {
        Write-Output '  (Get-NetTCPConnection unavailable on this host - port check skipped)'
        return $busy
    }
    foreach ($port in $FixturePortsToCheck) {
        $listeners = @()
        try {
            $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
        } catch {
            $listeners = @()
        }
        foreach ($listener in $listeners) {
            $owner = 'unknown'
            try {
                $ownerProc = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
                if ($ownerProc) { $owner = $ownerProc.ProcessName }
            } catch {
                $owner = 'unknown'
            }
            $busy += "port $port is held by PID $($listener.OwningProcess) ($owner)"
        }
    }
    return $busy
}

function Invoke-BatchPreflight {
    param($Cases)
    Write-Output '=== Pre-flight (runs before the first case; a failure aborts and records nothing) ==='

    $portCases = @($Cases | Where-Object { Test-CaseNeedsFixturePorts -CaseInfo $_ })
    if ($portCases.Count -gt 0) {
        Write-Output "  Port check: $($FixturePortsToCheck -join ', ') for $($portCases.Count) startable-fixture case(s)."
        $busy = @(Get-BusyFixturePorts)
        if ($busy.Count -gt 0) {
            Write-Output ''
            Write-Output 'PRE-FLIGHT FAILED: a fixture port is already in use.'
            foreach ($line in $busy) { Write-Output "  - $line" }
            Write-Output ''
            Write-Output ("A grader that probes one of these ports would read whatever is listening " +
                "there instead of the service the run started, so the verdict would be about the " +
                "wrong process. Stop the owning process (or wait for a previous batch to finish) " +
                "and re-run. Nothing was recorded.")
            return $false
        }
        Write-Output '  Port check: all clear.'
    } else {
        Write-Output '  Port check: skipped - no case in this batch has a startable fixture.'
    }

    Write-Output '  CLI probe: claude -p "reply with the word READY" --output-format json ...'
    $ready = Test-ClaudeCliReady
    if (-not $ready.Ready) {
        Write-Output ''
        Write-Output 'PRE-FLIGHT FAILED: the READY probe did not come back clean.'
        Write-Output "  $($ready.Detail)"
        Write-Output ''
        Write-Output ("Every case in this batch would have been recorded against a CLI or API that " +
            "is not answering - which is exactly the ten-run INFRA sweep of 2026-09-04. Fix the " +
            "CLI/API and re-run. Nothing was recorded.")
        return $false
    }
    Write-Output "  CLI probe: READY ($($ready.Detail))."
    Write-Output ''
    return $true
}

function Invoke-ZeroLlmCases {
    # The two zero-LLM cases, with --record. They cost nothing, they are the only
    # gate-composition proof in the suite, and until this ran they left no history at
    # all - so a confirmed contract batch always starts here. A red step is reported
    # loudly and does NOT abort the batch: the LLM cases measure something else.
    Write-Output '=== Zero-LLM cases (free, recorded, run first) ==='
    foreach ($zero in $ZeroLlmCases) {
        $script = Join-Path $EvalsRoot $zero.Script
        if (-not (Test-Path $script)) {
            Write-Output "  $($zero.Name): SKIPPED - $script not found"
            continue
        }
        Write-Output "  --- $($zero.Name) ---"
        $out = & python $script --record 2>&1
        $zeroExit = $LASTEXITCODE
        foreach ($line in $out) { Write-Host "    $line" }
        if ($zeroExit -eq 0) {
            Write-Output "  $($zero.Name): PASS (recorded)"
        } else {
            Write-Output "  $($zero.Name): FAIL (exit $zeroExit, recorded) - the gate chain itself is red; read the steps above before trusting any LLM case that invokes these gates."
        }
    }
    Write-Output ''
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

# What a confirmed batch does BEFORE the first case, printed on the dry run so the
# plan a reviewer approves is the plan that runs.
$portCasePlan = @($allCases | Where-Object { Test-CaseNeedsFixturePorts -CaseInfo $_ })
Write-Output 'On -Confirm, before the first case:'
Write-Output '  1. CLI probe: claude -p "reply with the word READY" (aborts the batch if it does not answer READY)'
if ($portCasePlan.Count -gt 0) {
    Write-Output "  2. Port check: $($FixturePortsToCheck -join ', ') must be free ($($portCasePlan.Count) case(s) with a startable fixture: $(($portCasePlan | ForEach-Object { $_.Name }) -join ', '))"
} else {
    Write-Output '  2. Port check: skipped - no case in this batch has a startable fixture'
}
if (@($allCases | Where-Object { $_.Type -eq 'contract' }).Count -gt 0) {
    Write-Output "  3. Zero-LLM cases (free, recorded): $(($ZeroLlmCases | ForEach-Object { $_.Name }) -join ', ')"
}
Write-Output 'An INFRA run (empty output, API/permission/quota refusal, or under the case''s minimum duration)'
Write-Output "is retried once, then quarantined in results-invalid-infra-<date>.jsonl and does NOT consume one of the $Runs."
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
    $outcome = 'GRADED'
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
        $minDurationSeconds = Get-ContractCaseMinDuration -CaseMdPath $CaseInfo.CaseMd
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
        # Measured at the agent boundary, not at the end of the function: the INFRA
        # duration floor is a claim about how long the AGENT ran, and grading a
        # fixture can add seconds of its own (bgpdd-bugfix-lane's grader starts a
        # service and probes it).
        $agentDurationSeconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 2)
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

        # --- INFRA classification: AFTER the agent, BEFORE grading --------------
        # This ordering is the whole fix. Grading an empty working copy produces a
        # row that fails every criterion and means nothing - ten of them on
        # 2026-09-04, each of which had to be recognised and moved out by hand.
        # An INFRA run is quarantined with `pass: null` and never reaches
        # results.jsonl, so it does not consume one of the case's N.
        $infraReason = Get-InfraReason -OutputText $agentOutputText `
            -DurationSeconds $agentDurationSeconds -MinDurationSeconds $minDurationSeconds
        if ($infraReason) {
            $outcome = 'INFRA'
            $pass = $null
            $failedCriterion = "INFRA: $infraReason"
            Write-Host "    INFRA: $infraReason - not graded, not counted"
        } else {
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
        }
    } catch {
        # A thrown harness error means grading NEVER RAN, so `pass: false` would be a
        # claim about the persona that nothing measured. Classified INFRA, matching
        # the hand triage this replaces - all three records in
        # results-invalid-infra-2026-09-03.jsonl are exactly this shape (a git CRLF
        # warning on stderr taking the whole run down at ~3 s).
        # READ THESE FIRST when triaging: unlike an API refusal, a harness error can
        # be a defect in the harness or the fixture, which the retry will not fix.
        $outcome = 'INFRA'
        $pass = $null
        $failedCriterion = "INFRA: harness error (grading never ran): $($_.Exception.Message)"
        Write-Host "    INFRA: harness error (grading never ran): $($_.Exception.Message)"
    } finally {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
    }

    $duration = [math]::Round(((Get-Date) - $started).TotalSeconds, 2)
    $record = [PSCustomObject]@{
        timestamp        = (Get-Date).ToUniversalTime().ToString('o')
        case             = $CaseInfo.Name
        run_index        = $RunIndex
        pass             = $pass
        outcome          = $outcome
        failed_criterion = $failedCriterion
        duration_s       = $duration
        plugin_sha       = $PluginSha
        plugin_dirty     = $PluginDirty
        claude_version   = $ClaudeVersion
        case_sha256      = (Get-Sha256HexOfFile -Path $CaseInfo.CaseMd)
        transcript       = "results/transcripts/$transcriptDirRel"
        harness_version  = $HarnessVersion
    }
    if ($outcome -eq 'INFRA') {
        # Written on the record itself, not left for a reader to infer, because the
        # archive files this lands in are read by the agent-audit eval-suite-health
        # metric, which requires every red to carry a triage class.
        $record | Add-Member -NotePropertyName 'triage' -NotePropertyValue 'INFRA'
    }
    return $record
}

function Invoke-TriggerRun {
    param($CaseInfo, [int]$RunIndex)

    $started = Get-Date
    $pass = $false
    $failedCriterion = $null
    $outcome = $null
    $firstSkill = $null
    $skillsInvoked = @()
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

        # --- INFRA classification, before the judge sees anything ---------------
        # A NO_ROUTE verdict over an EMPTY transcript is not a routing measurement:
        # the model never got a turn. Same for a CLI/API refusal. Both used to be
        # recorded as a routing failure, which is how a quota outage reads as a
        # regression in the skill descriptions (see
        # results-invalid-quota-2026-09-02.jsonl: 65 records, 3-7 s each).
        #
        # The one rule a trigger run does NOT get is the duration floor: there is no
        # case.md to declare a minimum, and a genuinely fast route or refusal-to-route
        # is a real result. Emptiness and the refusal patterns carry it instead.
        $infraReason = $null
        if ([string]::IsNullOrWhiteSpace($output)) {
            $infraReason = 'the transcript is empty - claude wrote no stream-json at all'
            if ($proc -and $proc.ExitCode -ne 0) {
                $infraReason += " (claude exited $($proc.ExitCode))"
            }
            if ($stderrText -and $stderrText.Trim().Length -gt 0) {
                $infraReason += "; stderr: $($stderrText.Trim())"
            }
        } else {
            # stdout AND stderr: `API Error: Connection closed` is written to whichever
            # the CLI picks, and the stream itself can carry the banner mid-transcript.
            $infraReason = Get-InfraReason -OutputText ($output + "`n" + $stderrText) `
                -MinDurationSeconds 0
        }

        if ($infraReason) {
            $outcome = 'INFRA'
            $pass = $null
            $failedCriterion = "INFRA: $infraReason"
            Write-Host "    INFRA: $infraReason - not judged, not counted"
        } else {
            $acceptable = @($CaseInfo.ExpectedSkill) + @($CaseInfo.AcceptableAlternatives)
            $judgeResult = Invoke-TriggerJudge -Acceptable $acceptable -StreamJson $output `
                -ExpectedChain @($CaseInfo.ExpectedChain)

            $pass = $judgeResult.Pass
            $outcome = $judgeResult.Outcome
            $firstSkill = $judgeResult.FirstSkill
            $skillsInvoked = @($judgeResult.SkillsInvoked)
            $mentionedOnly = $judgeResult.MentionedOnly
            Write-Host "    $($judgeResult.Outcome): $($judgeResult.Detail)"
            if (-not $pass) {
                $failedCriterion = $judgeResult.Detail
                if ($proc -and $proc.ExitCode -ne 0) {
                    $failedCriterion = "claude exited $($proc.ExitCode); $failedCriterion"
                }
            }
        }
    } catch {
        # `HARNESS_ERROR` is retired as an outcome value: it always meant the run
        # produced no judgeable transcript, which is what INFRA now names. The
        # message is preserved verbatim in failed_criterion.
        $outcome = 'INFRA'
        $pass = $null
        $failedCriterion = "INFRA: harness error (the run was never judged): $($_.Exception.Message)"
        Write-Host "    INFRA: harness error (the run was never judged): $($_.Exception.Message)"
    } finally {
        Remove-Item -Path $tempDir -Recurse -Force -ErrorAction SilentlyContinue
        foreach ($scratch in @($stdinFile, $stdoutFile, $stderrFile)) {
            Remove-Item -Path $scratch -Force -ErrorAction SilentlyContinue
        }
    }

    $duration = [math]::Round(((Get-Date) - $started).TotalSeconds, 2)
    $record = [PSCustomObject]@{
        timestamp        = (Get-Date).ToUniversalTime().ToString('o')
        case             = $CaseInfo.Name
        run_index        = $RunIndex
        pass             = $pass
        outcome          = $outcome
        first_skill      = $firstSkill
        # The FULL ordered invocation list, always - not only for expected_chain
        # cases. A single-hop case's `skills_invoked` is what tells a later reader
        # whether a ROUTED_WRONG recovered on its second hop, which `first_skill`
        # alone destroys.
        skills_invoked   = @($skillsInvoked)
        expected_chain   = @($CaseInfo.ExpectedChain)
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
    if ($outcome -eq 'INFRA') {
        $record | Add-Member -NotePropertyName 'triage' -NotePropertyValue 'INFRA'
    }
    return $record
}

if (-not (Invoke-BatchPreflight -Cases $allCases)) {
    exit 3
}

if (@($allCases | Where-Object { $_.Type -eq 'contract' }).Count -gt 0) {
    Invoke-ZeroLlmCases
}

$infraCount = 0
$recordedCount = 0

foreach ($caseInfo in $allCases) {
    Write-Output "--- $($caseInfo.Name) ---"
    for ($i = 1; $i -le $Runs; $i++) {
        Write-Output "  run $i/$Runs"
        if ($caseInfo.Type -eq 'contract') {
            $record = Invoke-ContractRun -CaseInfo $caseInfo -RunIndex $i
        } else {
            $record = Invoke-TriggerRun -CaseInfo $caseInfo -RunIndex $i
        }

        # Retry ONCE, and only on INFRA. A graded FAIL is a measurement and must
        # never be re-rolled - that would turn the suite into a best-of-two, which is
        # the opposite of what the 4/5 threshold is for. An INFRA run measured
        # nothing, so re-running it costs one run and buys one datum.
        if ($record.outcome -eq 'INFRA') {
            Write-Output "  run $i/$Runs classified INFRA - retrying once (INFRA only; a graded FAIL is never retried)"
            if ($caseInfo.Type -eq 'contract') {
                $record = Invoke-ContractRun -CaseInfo $caseInfo -RunIndex $i
            } else {
                $record = Invoke-TriggerRun -CaseInfo $caseInfo -RunIndex $i
            }
        }

        if ($record.outcome -eq 'INFRA') {
            # NOT results.jsonl. An INFRA run does not consume one of the N a
            # threshold is read over, and a reader counting rows in results.jsonl
            # must never see it.
            ($record | ConvertTo-Json -Compress) | Add-Content -Path $InfraResultsPath
            $infraCount++
            Write-Output "  run $i/$Runs -> INFRA after retry; quarantined in $(Split-Path -Leaf $InfraResultsPath), NOT counted toward $($caseInfo.Name)'s N"
        } else {
            ($record | ConvertTo-Json -Compress) | Add-Content -Path $ResultsPath
            $recordedCount++
        }
    }
}

Write-Output ''
Write-Output "Done. $recordedCount graded run(s) appended to $ResultsPath"
if ($infraCount -gt 0) {
    Write-Output "$infraCount run(s) classified INFRA and quarantined in $InfraResultsPath."
    Write-Output ('An INFRA run measured the harness or the API, not the plugin: it is NOT one of the ' +
        'N, and a case whose runs were mostly INFRA has no pass rate yet. Triage these before ' +
        'reporting any number - a harness error in particular can be a defect in the fixture, which ' +
        'the retry will not fix.')
}
