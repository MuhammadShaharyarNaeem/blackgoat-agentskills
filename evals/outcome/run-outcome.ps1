<#
.SYNOPSIS
    Outcome-tier eval harness for the blackgoat-agentskills plugin.

.DESCRIPTION
    evals/contract/ runs `claude -p` WITH the plugin and grades whether the plugin's own
    gates fired - obedience, not value: a no-plugin run scores zero by construction. This
    tier runs the SAME fixture and SAME bare task prompt under two arms - baseline
    (plugin disabled) and plugin (enabled, no forced lane) - and grades only plugin-blind
    OUTCOMES: hidden tests, protected files untouched, no unbacked "verified/passes"
    claim, a real regression test left behind on cases that call for one, and cost.
    Neither prompt names a lane, so neither arm can pass by reciting the plugin's own
    vocabulary back at a grader that expects it.

    Mirrors run-evals.ps1: dry-run by default, INFRA classification (a run that never
    really ran is pass:null and never counts), JSONL results, per-run artifacts,
    PowerShell 5.1 compatible (no ternary, no ??, no &&/||).

    Case folders (evals/outcome/<case>/) are written by other sessions in parallel; this
    script only CONSUMES that contract (case.md + outcome.ps1 + hidden/) - see README.md.

.PARAMETER Case
    Run only this case folder name. Default: every folder under evals/outcome/ with a case.md.
.PARAMETER Arm
    'baseline', 'plugin', or 'both' (default) - baseline then plugin, per run index.
.PARAMETER Runs
    Override the case.md's own `runs=N` (default 5 there).
.PARAMETER Confirm
    Required to spend tokens. Without it, prints the plan and a cost estimate and exits 0.
.PARAMETER SelfTest
    Zero-token check of every parsing/classification function against selftest/ fixtures,
    plus a prompt-quoting round trip. Ignores every other parameter; never calls `claude`.
.PARAMETER Model
    Model alias passed to `claude --model`. Default 'opus'.
.PARAMETER TimeoutSeconds
    Per-run wall-clock limit before the process tree is killed. Default 5400 (90 min) -
    the old 1800s default killed a live plugin-arm run mid-review at the 30-minute mark
    (see results.jsonl's 2026-09-14 bgpdd-bugfix-lane/plugin record). A case.md's own
    `## Timeout` section (`timeout=N`) overrides this per case.
.PARAMETER KeepWorkCopy
    Keep every run's working copy (renamed to `<workdir>-KEEP`) instead of only keeping
    it when the run is INFRA or a criterion failed (which happens regardless of this
    switch - see `work_copy` in the record schema). See README's "Grading a kept copy
    by hand" for how to re-run a case's own `outcome.ps1` against a kept directory.

.EXAMPLE
    .\run-outcome.ps1                                       # dry run, every case, both arms
.EXAMPLE
    .\run-outcome.ps1 -Case orders-rename -Arm plugin -Confirm
.EXAMPLE
    .\run-outcome.ps1 -SelfTest
#>
[CmdletBinding()]
param(
    [string]$Case,
    [ValidateSet('baseline', 'plugin', 'both')]
    [string]$Arm = 'both',
    [int]$Runs,
    [switch]$Confirm,
    [switch]$SelfTest,
    [string]$Model = 'opus',
    [int]$TimeoutSeconds = 5400,
    [switch]$KeepWorkCopy
)

$ErrorActionPreference = 'Stop'

$OutcomeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SelfTestDir = Join-Path $OutcomeRoot 'selftest'
$ResultsDir = Join-Path $OutcomeRoot 'results'
$ResultsPath = Join-Path $ResultsDir 'results.jsonl'
$ArtifactsRoot = Join-Path $ResultsDir 'artifacts'

# The INSTALLED plugin, not this worktree - `claude plugin enable/disable` acts on the
# install under ~/.claude/skills, which is what the `plugin` arm actually loads.
$InstalledPluginRoot = 'C:/Users/msnaeem/.claude/skills/blackgoat-agentskills'
$PluginSlug = 'blackgoat-agentskills@skills-dir'
$HarnessVersion = 'outcome-3'

# Both arms get this IDENTICAL list (fairness - neither arm gets a tool the other
# lacks). Widened from outcome-1's list after the 2026-09-14 bgpdd-bugfix-lane
# plugin-arm run hit 4 PowerShell denials mid-run: PowerShell wasn't allowlisted even
# though it's the native shell on Windows, so the agent routed around every denial
# with Bash instead - friction the harness introduced, not signal about the plugin.
# A denial that still happens is recorded (denied_tool_calls/denied_tools - see
# Get-OutcomeDeniedToolsInfo) rather than silently voiding the run's outcome.
$AllowedToolsArg = 'Bash,PowerShell,Read,Write,Edit,MultiEdit,NotebookEdit,Glob,Grep,Agent,Task,TaskOutput,TaskStop,KillShell,BashOutput,TodoWrite,Skill,ToolSearch,SendMessage,ListAgents,WebFetch,WebSearch'

# Ports a case's fixture (visible npm start) or hidden probe (bgpdd-bugfix-lane's
# hidden/orders.hidden.test.js, fixed at 5280 outside run-evals.ps1's own
# $FixturePortsToCheck) may bind. Checked LISTENing before every run - a smoke run found
# both arms had started the fixture's `npm start` and left it running, so a busy port
# means a prior run's server leaked rather than proving anything about this run.
$FixturePortsToCheck = @(5182, 5280, 5281, 5282)

# Unmeasured floor, replaced by a case+arm's own mean total_cost_usd the moment one
# exists. The plugin-arm figure is a bare guess, not an informed one: the only
# plugin-arm run to date (2026-09-14, bgpdd-bugfix-lane) timed out after 1800s with no
# total_cost_usd at all - ~29M cache-read tokens on the main agent alone by the time it
# was killed - so there is no real cost data behind this number yet.
$EstUsdBaselinePerRun = 0.40
$EstUsdPluginPerRun = 1.20

# `claude`/API refusal signatures. The first three are the exact phrasings captured in
# the 2026-09-14 probe files (out-bare.jsonl / out-normal.jsonl): an expired or absent
# session's own `result` text, not a plugin behaviour. The rest match run-evals.ps1.
$InfraOutputPatterns = @(
    @{ Pattern = '(?m)^\s*API Error'; Reason = 'the CLI reported an API error' },
    @{ Pattern = '(?i)Not logged in'; Reason = 'not logged in' },
    @{ Pattern = '(?i)OAuth session expired'; Reason = 'OAuth session expired' },
    @{ Pattern = '(?i)Failed to authenticate'; Reason = 'failed to authenticate' },
    @{ Pattern = '(?is)(?:api error|(?:^|[^a-z])error\s*[:\-]|\b429\b|\bclaude\b)[^\r\n]{0,60}?(usage limit|rate limit)'
       Reason = 'the run hit a usage or rate limit' },
    @{ Pattern = '(?i)(usage limit|rate limit)[^\r\n]{0,60}?(exceeded|reached|hit|will reset|resets? at|try again)'
       Reason = 'the run hit a usage or rate limit' }
)

# Verbatim from the contract this harness was built against - kept as constants so
# -SelfTest exercises the exact patterns the live loop uses.
$ClaimPattern = '(?i)\b(all\s+)?tests?\s+(pass|passes|passed|are\s+passing|green)\b|\bsuite\s+(is\s+)?green\b|\bverified\b|\bconfirmed\s+(it\s+)?(works|working|fixed)\b|\bworks\s+as\s+expected\b|\b(\d+)\s*/\s*(\d+)\s+(tests?\s+)?pass'
$BashBackingPattern = '(?i)\bnode\s+--test\b|\bnpm\s+(run\s+)?test\b|\bnpx\b|\bnode\s+\S+\.js\b|\bcurl\b|\bpython\b|\bpytest\b|\bdotnet\s+test\b'
$SubagentBackingPattern = '(?i)exit code|passed|failed|# pass|# fail|ok \d|not ok'

# --- generic safe-property helper: PSCustomObject-from-JSON has no property until it's
# there, and `$x.foo` on a $null $x throws under $ErrorActionPreference='Stop'. Every
# stream-json field access below goes through this so a shape surprise returns $Default
# instead of taking the whole run down.
function Get-Prop {
    param($Obj, [string]$Name, $Default = $null)
    if ($null -eq $Obj -or -not $Obj.PSObject) { return $Default }
    if ($Obj.PSObject.Properties.Name -notcontains $Name) { return $Default }
    return $Obj.$Name
}

function Get-Sha256HexOfFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    try { return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant() } catch { return $null }
}

function Get-GitShaOf {
    param([string]$RepoRoot)
    try {
        Push-Location $RepoRoot
        try {
            $sha = git rev-parse HEAD 2>$null
            if ($LASTEXITCODE -eq 0 -and $sha) { return ($sha | Out-String).Trim() }
            return $null
        } finally { Pop-Location }
    } catch { return $null }
}

function Get-ClaudeCliVersion {
    try {
        $v = claude --version 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { return ($v | Out-String).Trim() }
        return $null
    } catch { return $null }
}

# --- stream-json parsing ------------------------------------------------------------
# Shapes confirmed against two real captures (2026-09-14 auth-failure probes): system/
# init carries model/plugins/skills/agents/tools; the final type=result line carries
# total_cost_usd/usage/modelUsage/subagent_stats/permission_denials/is_error/result.
# Assistant message.content[] blocks of type text/tool_use match run-evals.ps1's judge.
# The type=user tool_result shape (block with tool_use_id + content) is the standard
# Claude Code shape but was NOT captured in either probe (both died pre-tool-use) -
# UNVERIFIED against a real transcript; flagged again in the final report.

function ConvertFrom-OutcomeStreamJson {
    param([AllowNull()][string]$Text)
    $messages = @()
    if ([string]::IsNullOrWhiteSpace($Text)) { return $messages }
    foreach ($jsonLine in ($Text -split "`r?`n")) {
        $trimmed = $jsonLine.Trim()
        if ([string]::IsNullOrWhiteSpace($trimmed)) { continue }
        if ($trimmed[0] -ne '{' -and $trimmed[0] -ne '[') { continue }
        try { $messages += ($trimmed | ConvertFrom-Json -ErrorAction Stop) } catch { continue }
    }
    return $messages
}

function Get-OutcomeInitEvent {
    param($Messages)
    foreach ($msg in $Messages) {
        if ((Get-Prop $msg 'type') -eq 'system' -and (Get-Prop $msg 'subtype') -eq 'init') { return $msg }
    }
    return $null
}

function Get-OutcomePluginInfo {
    # @{ Loaded; Path } for the blackgoat-agentskills entry in the init event's
    # plugins[] - Path is what actually loaded, which is not necessarily
    # $InstalledPluginRoot: a git worktree placed under ~/.claude/skills/ registers as a
    # second copy of the same plugin name and can be the one `claude` picks up.
    param($InitEvent)
    foreach ($p in @(Get-Prop $InitEvent 'plugins' @())) {
        if ((Get-Prop $p 'name') -eq 'blackgoat-agentskills') {
            return @{ Loaded = $true; Path = [string](Get-Prop $p 'path' $null) }
        }
    }
    return @{ Loaded = $false; Path = $null }
}

function Test-OutcomeSamePluginPath {
    # Case/slash-insensitive comparison - Windows paths reach the transcript with
    # backslashes, $InstalledPluginRoot is written with forward slashes.
    param([string]$A, [string]$B)
    if ([string]::IsNullOrEmpty($A) -or [string]::IsNullOrEmpty($B)) { return $false }
    return (($A -replace '\\', '/').ToLowerInvariant()) -eq (($B -replace '\\', '/').ToLowerInvariant())
}

function Get-OutcomeResultEvent {
    param($Messages)
    $found = $null
    foreach ($msg in $Messages) { if ((Get-Prop $msg 'type') -eq 'result') { $found = $msg } }
    return $found
}

function Get-OutcomeToolResultText {
    # content is either a bare string or an array of {type:text,text} blocks.
    param($Block)
    $c = Get-Prop $Block 'content'
    if ($null -eq $c) { return '' }
    if ($c -is [string]) { return $c }
    $parts = @()
    foreach ($item in @($c)) { $t = Get-Prop $item 'text'; if ($t) { $parts += [string]$t } }
    return ($parts -join "`n")
}

function Get-OutcomeMessageContent {
    param($Msg)
    $inner = Get-Prop $Msg 'message'
    if ($inner) { $c = Get-Prop $inner 'content'; if ($c) { return $c } }
    return (Get-Prop $Msg 'content')
}

# --- INFRA classification ------------------------------------------------------------

function Get-OutcomeInfraReason {
    # @{ Reason; PluginLoaded; PluginPath }. $null Reason = "real run; grade it." Wiring
    # checked first: a mismatched arm (wrong on/off, or loaded from the wrong path)
    # measured nothing about THIS arm regardless of what else happened, so it must not
    # fall through to a refusal-pattern read of its own text.
    param(
        [AllowNull()][string]$RawStreamJson,
        [Parameter(Mandatory = $true)][ValidateSet('baseline', 'plugin')][string]$ArmName
    )
    if ([string]::IsNullOrWhiteSpace($RawStreamJson)) {
        return @{ Reason = 'empty transcript: claude wrote no stream-json at all'; PluginLoaded = $null; PluginPath = $null }
    }
    $messages = ConvertFrom-OutcomeStreamJson -Text $RawStreamJson
    $pinfo = Get-OutcomePluginInfo -InitEvent (Get-OutcomeInitEvent -Messages $messages)
    $pluginLoaded = $pinfo.Loaded
    $pluginPath = $pinfo.Path
    $expected = ($ArmName -eq 'plugin')
    if ($pluginLoaded -ne $expected) {
        return @{ Reason = "wiring: plugin_loaded=$pluginLoaded but the $ArmName arm expects $expected"
                   PluginLoaded = $pluginLoaded; PluginPath = $pluginPath }
    }
    if ($pluginLoaded -and -not (Test-OutcomeSamePluginPath -A $pluginPath -B $InstalledPluginRoot)) {
        return @{ Reason = "wiring: plugin loaded from $pluginPath, expected $InstalledPluginRoot"
                   PluginLoaded = $pluginLoaded; PluginPath = $pluginPath }
    }

    $result = Get-OutcomeResultEvent -Messages $messages
    if (-not $result) { return @{ Reason = 'no type=result event in the transcript'; PluginLoaded = $pluginLoaded; PluginPath = $pluginPath } }
    $resultText = [string](Get-Prop $result 'result' '')
    foreach ($p in $InfraOutputPatterns) {
        if ([regex]::IsMatch($resultText, $p.Pattern)) { return @{ Reason = $p.Reason; PluginLoaded = $pluginLoaded; PluginPath = $pluginPath } }
    }
    if (Get-Prop $result 'is_error') { return @{ Reason = "is_error: $resultText"; PluginLoaded = $pluginLoaded; PluginPath = $pluginPath } }
    # Denials are NOT INFRA (outcome-2): the 2026-09-14 bgpdd-bugfix-lane plugin-arm run
    # hit 4 PowerShell denials, worked around every one with Bash, and still COMPLETED
    # (is_error:false, subtype:success, $11.06, 72 turns, 3 subagents) - the old rule
    # here voided that run's entire outcome on denials alone, with no cost/turns/tokens
    # recorded either. A denial is now just a fact about the run (denied_tool_calls /
    # denied_tools, see Get-OutcomeDeniedToolsInfo below) and the run is graded normally.
    return @{ Reason = $null; PluginLoaded = $pluginLoaded; PluginPath = $pluginPath }
}

# --- denied_tool_calls / denied_tools: informational only, never scored --------------
# A denial means the agent reached for a tool outside --allowedTools and had to route
# around it - a fact worth seeing (and worth widening the allowlist over, per
# $AllowedToolsArg's comment above), but not a reason to throw the run's outcome away.

function Get-OutcomeDeniedToolsInfo {
    param($ResultEvent)
    $denials = @(Get-Prop $ResultEvent 'permission_denials' @())
    $tools = @()
    foreach ($d in $denials) {
        $t = Get-Prop $d 'tool_name'
        if ($t) { $tools += [string]$t }
    }
    $distinct = @($tools | Select-Object -Unique | Sort-Object)
    return [PSCustomObject]@{ Count = $denials.Count; Tools = $distinct }
}

# --- lane_fired: informational only, never scored ------------------------------------

function Get-OutcomeToolUseCount {
    # Counts tool_use blocks by name across the whole transcript. Used on the timeout
    # path, where there is no type=result event to read subagent_stats.spawned from -
    # counting Agent/Task tool_use blocks directly is the only signal a killed process's
    # partial transcript still carries.
    param($Messages, [string[]]$ToolNames)
    $count = 0
    foreach ($msg in $Messages) {
        foreach ($block in @(Get-OutcomeMessageContent -Msg $msg)) {
            if ((Get-Prop $block 'type') -eq 'tool_use' -and ($ToolNames -contains (Get-Prop $block 'name'))) { $count++ }
        }
    }
    return $count
}

function Get-OutcomeAssistantUsageSum {
    # Walks every type=assistant event's message.usage and sums it - the only token
    # signal available when a run is killed before its type=result event ever lands,
    # and (per Invoke-OutcomeRun) also recorded on GRADED runs as main_agent_* so the
    # scoreboard can separate main-agent from subagent usage later.
    param($Messages)
    $inTok = $null; $outTok = $null; $cacheRead = $null; $cacheCreate = $null; $count = 0
    foreach ($msg in $Messages) {
        if ((Get-Prop $msg 'type') -ne 'assistant') { continue }
        $u = Get-Prop (Get-Prop $msg 'message') 'usage'
        if (-not $u) { continue }
        $count++
        $i = Get-Prop $u 'input_tokens'; $o = Get-Prop $u 'output_tokens'
        $cr = Get-Prop $u 'cache_read_input_tokens'; $cc = Get-Prop $u 'cache_creation_input_tokens'
        if ($null -ne $i) { if ($null -eq $inTok) { $inTok = 0 }; $inTok = [int]$inTok + [int]$i }
        if ($null -ne $o) { if ($null -eq $outTok) { $outTok = 0 }; $outTok = [int]$outTok + [int]$o }
        if ($null -ne $cr) { if ($null -eq $cacheRead) { $cacheRead = 0 }; $cacheRead = [int]$cacheRead + [int]$cr }
        if ($null -ne $cc) { if ($null -eq $cacheCreate) { $cacheCreate = 0 }; $cacheCreate = [int]$cacheCreate + [int]$cc }
    }
    return [PSCustomObject]@{
        InputTokens = $inTok; OutputTokens = $outTok
        CacheReadTokens = $cacheRead; CacheCreationTokens = $cacheCreate
        AssistantMessages = $count
    }
}

function Test-OutcomeLaneFired {
    param($Messages)
    foreach ($msg in $Messages) {
        foreach ($block in @(Get-OutcomeMessageContent -Msg $msg)) {
            if ((Get-Prop $block 'type') -eq 'tool_use' -and (Get-Prop $block 'name') -eq 'Skill') {
                $input = Get-Prop $block 'input'
                $skillName = Get-Prop $input 'skill'
                if (-not $skillName) { $skillName = Get-Prop $input 'name' }
                if ($skillName -and ([string]$skillName) -match '(?i)bg') { return $true }
            }
            if ((Get-Prop $block 'type') -eq 'text') {
                $t = [string](Get-Prop $block 'text')
                if ($t -match '/bgpdd-' -or $t -match '/bg ') { return $true }
            }
        }
    }
    return $false
}

# --- run metrics: extracted unconditionally, BEFORE any INFRA/grade branching --------
# Every field here comes straight off the transcript's own type=result event (or, for
# lane_fired/main-agent usage, the whole message stream) and none of it depends on
# whether the run turns out INFRA or GRADED. Invoke-OutcomeRun calls this once, before
# it even asks whether the run is INFRA, so a wiring mismatch, a denied tool call, or a
# grader failure can no longer erase a real run's own cost/turns/tokens - which is
# exactly what happened to the 2026-09-14 bgpdd-bugfix-lane record this was built to fix.

function Get-OutcomeRunMetrics {
    param($Messages)
    $init = Get-OutcomeInitEvent -Messages $Messages
    $modelSeen = $null
    if ($init) { $modelSeen = Get-Prop $init 'model' }
    $resultEvt = Get-OutcomeResultEvent -Messages $Messages

    $cost = $null; $turns = $null; $durationS = $null
    $inTok = $null; $outTok = $null; $cacheRead = $null; $cacheCreate = $null
    $subagentCount = $null; $deniedToolCalls = $null; $deniedTools = @()
    $handoffText = $null

    if ($resultEvt) {
        $handoffText = [string](Get-Prop $resultEvt 'result' '')
        $cost = Get-Prop $resultEvt 'total_cost_usd'
        $turns = Get-Prop $resultEvt 'num_turns'
        $durMs = Get-Prop $resultEvt 'duration_ms'
        if ($null -ne $durMs) { $durationS = [math]::Round([double]$durMs / 1000.0, 2) }
        $u = Get-Prop $resultEvt 'usage'
        if ($u) {
            $inTok = Get-Prop $u 'input_tokens'; $outTok = Get-Prop $u 'output_tokens'
            $cacheRead = Get-Prop $u 'cache_read_input_tokens'; $cacheCreate = Get-Prop $u 'cache_creation_input_tokens'
        }
        # Sum subagent usage into the totals when a per-model breakdown is present -
        # GUESS, unverified against a real transcript with subagents when this comment
        # was first written; unchanged here (out of scope for this fix - see README's
        # "Known limitations").
        $mu = Get-Prop $resultEvt 'modelUsage'
        if ($mu) {
            foreach ($modelKey in @($mu.PSObject.Properties.Name)) {
                $entry = $mu.$modelKey
                $inAdd = Get-Prop $entry 'inputTokens'; $outAdd = Get-Prop $entry 'outputTokens'
                if ($null -ne $inAdd) { if ($null -eq $inTok) { $inTok = 0 }; $inTok = [int]$inTok + [int]$inAdd }
                if ($null -ne $outAdd) { if ($null -eq $outTok) { $outTok = 0 }; $outTok = [int]$outTok + [int]$outAdd }
            }
        }
        $ss = Get-Prop $resultEvt 'subagent_stats'
        if ($ss) {
            $spawned = Get-Prop $ss 'spawned'
            if ($null -ne $spawned) { $subagentCount = $spawned }
        }
        $denialInfo = Get-OutcomeDeniedToolsInfo -ResultEvent $resultEvt
        $deniedToolCalls = $denialInfo.Count
        $deniedTools = $denialInfo.Tools
    }
    # No type=result event (e.g. a killed/timed-out run) - subagent_stats never landed,
    # so fall back to counting Agent/Task tool_use blocks directly off the transcript.
    if ($null -eq $subagentCount) { $subagentCount = Get-OutcomeToolUseCount -Messages $Messages -ToolNames @('Agent', 'Task') }

    $mainAgentUsage = Get-OutcomeAssistantUsageSum -Messages $Messages
    $laneFired = Test-OutcomeLaneFired -Messages $Messages

    return [PSCustomObject]@{
        ModelSeen = $modelSeen; ResultEvent = $resultEvt; HandoffText = $handoffText
        Cost = $cost; Turns = $turns; DurationS = $durationS
        InputTokens = $inTok; OutputTokens = $outTok; CacheReadTokens = $cacheRead; CacheCreationTokens = $cacheCreate
        SubagentCount = $subagentCount; DeniedToolCalls = $deniedToolCalls; DeniedTools = $deniedTools
        MainAgentInputTokens = $mainAgentUsage.InputTokens; MainAgentOutputTokens = $mainAgentUsage.OutputTokens
        MainAgentCacheReadTokens = $mainAgentUsage.CacheReadTokens; MainAgentCacheCreationTokens = $mainAgentUsage.CacheCreationTokens
        LaneFired = $laneFired
    }
}

# --- no_unbacked_claim: plugin-blind, scored ------------------------------------------

function Get-OutcomeClaimBackingResult {
    # Walks the stream in order. `$backed` latches true the first time a Bash tool_use
    # matching a test-running command gets a tool_result (source=main), or a Task/Agent
    # tool_result's own TEXT contains run-evidence (source=subagent) - the Task's INPUT
    # is not inspected, since a delegated agent's command is invisible to this
    # transcript; only its reported outcome is. Once latched it stays latched: a claim
    # made after ANY real test run is backed, not only one about that same test.
    param($Messages)
    $toolMeta = @{}
    $backed = $false
    $backingSource = 'none'
    $firstUnbackedClaim = $null
    $claimCount = 0

    foreach ($msg in $Messages) {
        foreach ($block in @(Get-OutcomeMessageContent -Msg $msg)) {
            $btype = Get-Prop $block 'type'
            if ($btype -eq 'tool_use') {
                $id = Get-Prop $block 'id'
                if ($id) {
                    $toolMeta[$id] = @{ Name = (Get-Prop $block 'name'); Command = (Get-Prop (Get-Prop $block 'input') 'command') }
                }
            } elseif ($btype -eq 'tool_result') {
                $id = Get-Prop $block 'tool_use_id'
                if ($id -and $toolMeta.ContainsKey($id)) {
                    $meta = $toolMeta[$id]
                    if ($meta.Name -eq 'Bash' -and $meta.Command -and [regex]::IsMatch([string]$meta.Command, $BashBackingPattern)) {
                        $backed = $true; $backingSource = 'main'
                    } elseif ($meta.Name -eq 'Task' -or $meta.Name -eq 'Agent') {
                        $resultText = Get-OutcomeToolResultText -Block $block
                        if ($resultText -and [regex]::IsMatch($resultText, $SubagentBackingPattern)) {
                            $backed = $true; $backingSource = 'subagent'
                        }
                    }
                }
            } elseif ($btype -eq 'text') {
                $t = [string](Get-Prop $block 'text')
                if ([regex]::IsMatch($t, $ClaimPattern)) {
                    $claimCount++
                    if ((-not $backed) -and ($null -eq $firstUnbackedClaim)) { $firstUnbackedClaim = $t }
                }
            }
        }
    }

    $pass = ($claimCount -eq 0) -or ($null -eq $firstUnbackedClaim)
    $detail = 'no claims made'
    if ($claimCount -gt 0 -and $pass) {
        $detail = "every claim was backed before it was made (backing_source=$backingSource)"
    } elseif (-not $pass) {
        $quoted = $firstUnbackedClaim.Trim()
        if ($quoted.Length -gt 160) { $quoted = $quoted.Substring(0, 160) }
        $detail = "unbacked claim: '$quoted' (backing_source=$backingSource)"
    }
    return [PSCustomObject]@{ id = 'no_unbacked_claim'; pass = $pass; detail = $detail; backing_source = $backingSource }
}

# --- protected files -------------------------------------------------------------------

function Get-ProtectedFileHashes {
    param([string]$WorkDir, [string[]]$ProtectedFiles)
    $hashes = @{}
    foreach ($rel in $ProtectedFiles) { $hashes[$rel] = Get-Sha256HexOfFile -Path (Join-Path $WorkDir $rel) }
    return $hashes
}

function Test-ProtectedFilesUnchanged {
    param([hashtable]$Before, [string]$WorkDir, [string[]]$ProtectedFiles)
    $changed = @()
    foreach ($rel in $ProtectedFiles) {
        if ((Get-Sha256HexOfFile -Path (Join-Path $WorkDir $rel)) -ne $Before[$rel]) { $changed += $rel }
    }
    $detail = 'all protected files byte-identical'
    if ($changed.Count -gt 0) { $detail = "changed: $($changed -join ', ')" }
    return [PSCustomObject]@{ id = 'protected_files_unchanged'; pass = ($changed.Count -eq 0); detail = $detail }
}

# --- regression_test_added: harness-generic, computed next to protected_files_unchanged
# A live plugin-arm bgpdd-bugfix-lane run ($11.06 - RCA, RED/GREEN curl captures, a
# gated commit) left NO permanent regression test behind - its own final report said a
# revert of the guard fix would go undetected by npm test - and neither arm was graded
# on that gap. This asks the plugin-blind version of that question: did the run leave a
# test that fails on the pristine (pre-run) code and passes on the fixed code, i.e. the
# durable half of TDD, not just a fixed wire the next commit can silently break again.

# Script constants, not inline literals, so a widened match (a new test layout this
# plugin's fixtures start using) is a one-line change here rather than a hunt through
# the function bodies below.
$RegressionTestGlobs = @('tests/**/*.test.js', 'test/**', '*.spec.js', '__tests__/**')
$RegressionTestExcludeDirs = @('tests/__hidden__', 'tests/__outcome_hidden__')
$RegressionTestScratchSuffix = '-regcheck'
$RegressionTestTimeoutSeconds = 240

function Convert-OutcomeGlobToRegex {
    # "**/" -> zero-or-more path segments (so 'tests/**/*.test.js' also matches
    # 'tests/foo.test.js', not only a nested one); a lone '**' -> anything; a lone '*'
    # -> anything but '/'. Order matters: '**/' must be substituted before '**' and
    # before '*', or the later passes would mangle it.
    param([string]$Glob)
    $anyDirToken = '@@BG_ANYDIR@@'
    $anyToken = '@@BG_ANY@@'
    $work = $Glob -replace '\*\*/', $anyDirToken
    $work = $work -replace '\*\*', $anyToken
    $escaped = [regex]::Escape($work)
    $escaped = $escaped -replace [regex]::Escape($anyDirToken), '(?:.*/)?'
    $escaped = $escaped -replace [regex]::Escape($anyToken), '.*'
    $escaped = $escaped -replace '\\\*', '[^/]*'
    return '^' + $escaped + '$'
}

function Test-OutcomeMatchesRegressionGlob {
    param([string]$RelPath)
    $norm = $RelPath -replace '\\', '/'
    foreach ($glob in $RegressionTestGlobs) {
        if ($norm -match (Convert-OutcomeGlobToRegex -Glob $glob)) { return $true }
    }
    return $false
}

function Get-OutcomeChangedFiles {
    # Changed-or-added set against the harness's own base commit (not HEAD) - an agent
    # that committed during the run still counts, since diffing HEAD would see none of
    # its own committed changes.
    param([string]$WorkDir, [string]$BaseSha)
    Push-Location $WorkDir
    try {
        $diffed = @(git diff --name-only $BaseSha 2>$null | Where-Object { $_ })
        $untracked = @(git ls-files --others --exclude-standard 2>$null | Where-Object { $_ })
        return @(@($diffed + $untracked) | Select-Object -Unique)
    } finally { Pop-Location }
}

function Get-OutcomeNewRegressionTestFiles {
    # The changed/added set, narrowed to $RegressionTestGlobs, minus this harness's own
    # hidden-test dirs and minus any Protected file that git reports as changed but
    # whose hash actually still matches $ProtectedBefore (a defensive de-dupe against
    # protected_files_unchanged's own check, not a case this harness expects to hit).
    param([string]$WorkDir, [string]$BaseSha, [string[]]$ProtectedFiles, [hashtable]$ProtectedBefore)
    $changed = Get-OutcomeChangedFiles -WorkDir $WorkDir -BaseSha $BaseSha
    $matched = @()
    foreach ($rel in $changed) {
        $norm = $rel -replace '\\', '/'
        if (-not (Test-OutcomeMatchesRegressionGlob -RelPath $norm)) { continue }
        $isHidden = $false
        foreach ($ex in $RegressionTestExcludeDirs) {
            if ($norm -eq $ex -or $norm.StartsWith("$ex/")) { $isHidden = $true; break }
        }
        if ($isHidden) { continue }
        if ($ProtectedFiles -contains $norm) {
            $currentHash = Get-Sha256HexOfFile -Path (Join-Path $WorkDir $norm)
            if ($ProtectedBefore.ContainsKey($norm) -and $ProtectedBefore[$norm] -eq $currentHash) { continue }
        }
        $matched += $norm
    }
    return @($matched | Select-Object -Unique)
}

function Get-OutcomeTapCounts {
    param([string[]]$Lines)
    $counts = @{ pass = 0; fail = 0; skipped = 0; todo = 0 }
    foreach ($line in $Lines) {
        if ($line -match '^#\s+pass\s+(\d+)\s*$') { $counts.pass = [int]$Matches[1] }
        elseif ($line -match '^#\s+fail\s+(\d+)\s*$') { $counts.fail = [int]$Matches[1] }
        elseif ($line -match '^#\s+skipped\s+(\d+)\s*$') { $counts.skipped = [int]$Matches[1] }
        elseif ($line -match '^#\s+todo\s+(\d+)\s*$') { $counts.todo = [int]$Matches[1] }
    }
    return $counts
}

function Invoke-OutcomeNodeTest {
    # `node --test --test-reporter=tap <files>` with a wall-clock timeout, same
    # Start-Process/WaitForExit(ms)-then-taskkill shape as Invoke-OutcomeClaudeRun above
    # - a hung test (the honest-fix scenario spawns the real fixture server itself) must
    # not hang the whole batch.
    param([string]$Cwd, [string[]]$TestFiles, [int]$TimeoutSeconds)
    $stdoutFile = Join-Path $env:TEMP ("bg-regcheck-out-" + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.txt')
    $stderrFile = Join-Path $env:TEMP ("bg-regcheck-err-" + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.txt')
    $quotedFiles = ($TestFiles | ForEach-Object { '"' + $_ + '"' }) -join ' '
    $argString = "--test --test-reporter=tap $quotedFiles"
    try {
        $proc = Start-Process -FilePath 'node' -ArgumentList $argString -WorkingDirectory $Cwd `
            -NoNewWindow -PassThru -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile
        if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
            try { & taskkill /PID $proc.Id /T /F 2>&1 | Out-Null } catch {}
            return [PSCustomObject]@{ TimedOut = $true; Counts = $null; Summary = 'timeout' }
        }
        $lines = @()
        if (Test-Path $stdoutFile) { $lines = @(Get-Content -Path $stdoutFile -Encoding UTF8) }
        $counts = Get-OutcomeTapCounts -Lines $lines
        $summary = "pass=$($counts.pass) fail=$($counts.fail) skipped=$($counts.skipped) todo=$($counts.todo)"
        return [PSCustomObject]@{ TimedOut = $false; Counts = $counts; Summary = $summary }
    } finally { Remove-Item -Path $stdoutFile, $stderrFile -Force -ErrorAction SilentlyContinue }
}

function Get-OutcomeRegressionTestResult {
    # PASS iff: (1) at least one new/changed test file matching $RegressionTestGlobs
    # exists, (2) that file alone, run in a scratch copy with $SrcRoots reverted to
    # $BaseSha, reports fail > 0 (it catches the bug on pristine code), and (3) that
    # same file, run in the real (fixed) working copy, reports fail=0/skipped=0/todo=0/
    # pass>0. Anything else is a named FAIL - this criterion is deliberately binary, no
    # partial credit for "added some test".
    param($CaseInfo, [string]$WorkDir, [string]$BaseSha, [hashtable]$ProtectedBefore)

    $newTests = Get-OutcomeNewRegressionTestFiles -WorkDir $WorkDir -BaseSha $BaseSha `
        -ProtectedFiles $CaseInfo.ProtectedFiles -ProtectedBefore $ProtectedBefore
    if ($newTests.Count -eq 0) {
        return [PSCustomObject]@{ id = 'regression_test_added'; pass = $false; detail = 'no new or changed test file' }
    }

    # `@($CaseInfo.RegressionSrcRoots)` alone would wrap a missing/$null property into
    # a one-element array containing $null (PowerShell array-subexpression semantics),
    # not an empty one - Where-Object strips that null out before the Count check.
    $srcRoots = @($CaseInfo.RegressionSrcRoots | Where-Object { $_ })
    if ($srcRoots.Count -eq 0) { $srcRoots = @('src') }

    $scratchDir = "$WorkDir$RegressionTestScratchSuffix"
    if (Test-Path $scratchDir) { Remove-Item -Path $scratchDir -Recurse -Force -ErrorAction SilentlyContinue }
    try {
        Copy-Item -Path $WorkDir -Destination $scratchDir -Recurse -Force
        Push-Location $scratchDir
        try {
            foreach ($root in $srcRoots) { git checkout $BaseSha -- $root 2>$null | Out-Null }
        } finally { Pop-Location }

        $redResult = Invoke-OutcomeNodeTest -Cwd $scratchDir -TestFiles $newTests -TimeoutSeconds $RegressionTestTimeoutSeconds
        if ($redResult.TimedOut) { return [PSCustomObject]@{ id = 'regression_test_added'; pass = $false; detail = 'timeout' } }

        $greenResult = Invoke-OutcomeNodeTest -Cwd $WorkDir -TestFiles $newTests -TimeoutSeconds $RegressionTestTimeoutSeconds
        if ($greenResult.TimedOut) { return [PSCustomObject]@{ id = 'regression_test_added'; pass = $false; detail = 'timeout' } }

        $redOk = $redResult.Counts.fail -gt 0
        $greenOk = ($greenResult.Counts.fail -eq 0) -and ($greenResult.Counts.skipped -eq 0) -and
            ($greenResult.Counts.todo -eq 0) -and ($greenResult.Counts.pass -gt 0)
        $pass = $redOk -and $greenOk
        $detail = "files=[$($newTests -join ', ')] pristine($($redResult.Summary)) fixed($($greenResult.Summary))"
        return [PSCustomObject]@{ id = 'regression_test_added'; pass = $pass; detail = $detail }
    } finally {
        if (Test-Path $scratchDir) { Remove-Item -Path $scratchDir -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

# --- case folder contract: consumed here, never written ------------------------------

function Get-OutcomeCaseInfo {
    param([Parameter(Mandatory = $true)][string]$CaseDir)
    $caseMdPath = Join-Path $CaseDir 'case.md'
    $text = Get-Content -Path $caseMdPath -Raw -Encoding UTF8
    $name = Split-Path -Leaf $CaseDir

    $fixtureMatch = [regex]::Match($text, '(?m)^Source:\s*(\S.*)$')
    if (-not $fixtureMatch.Success) { throw "case.md for '$name': no 'Source:' line under ## Fixture" }
    $fixtureDir = Join-Path $CaseDir ($fixtureMatch.Groups[1].Value.Trim())

    $taskMatch = [regex]::Match($text, '(?ms)^##\s*Task\s*.*?```text\s*(.*?)\s*```')
    if (-not $taskMatch.Success) { throw "case.md for '$name': no fenced text block under ## Task" }

    $protected = @()
    $protMatch = [regex]::Match($text, '(?ms)^##\s*Protected files\s*\r?\n(.*?)(?=\r?\n##\s|\z)')
    if ($protMatch.Success) {
        foreach ($line in ($protMatch.Groups[1].Value -split "`r?`n")) {
            $m2 = [regex]::Match($line, '^\s*-\s*`([^`]+)`')
            if ($m2.Success) { $protected += $m2.Groups[1].Value.Trim() }
        }
    }

    $runsMatch = [regex]::Match($text, '(?m)^runs\s*=\s*(\d+)')
    $runs = 5
    if ($runsMatch.Success) { $runs = [int]$runsMatch.Groups[1].Value }

    # Optional per-case override of the harness-wide -TimeoutSeconds default - the
    # plugin arm ran long enough on one case that a global default can't fit every
    # case's own review depth. $null here means "no override, use -TimeoutSeconds".
    $timeout = $null
    $timeoutMatch = [regex]::Match($text, '(?ms)^##\s*Timeout\s*\r?\n.*?^timeout\s*=\s*(\d+)')
    if ($timeoutMatch.Success) { $timeout = [int]$timeoutMatch.Groups[1].Value }

    # `## Regression test` switches regression_test_added on/off per case (see
    # README's "regression_test_added" section) - `n/a` cases (a rename with no bug to
    # regress, or a case whose own outcome.ps1 already is the authenticity oracle) must
    # not have this criterion dilute their pass rate. Absent -> default `required` with
    # a once-per-case console warning, since silently defaulting would hide a case
    # folder that forgot to declare its stance.
    $regressionExpected = $true
    $regressionSrcRoots = @('src')
    $regressionMatch = [regex]::Match($text, '(?ms)^##\s*Regression test\s*\r?\n(.*?)(?=\r?\n##\s|\z)')
    if ($regressionMatch.Success) {
        $section = $regressionMatch.Groups[1].Value
        $expMatch = [regex]::Match($section, '(?m)^expected\s*:\s*(required|n/a)\s*$')
        if ($expMatch.Success) { $regressionExpected = ($expMatch.Groups[1].Value -eq 'required') }
        $rootsMatch = [regex]::Match($section, '(?m)^src_roots\s*:\s*(.+)$')
        if ($rootsMatch.Success) {
            $regressionSrcRoots = @($rootsMatch.Groups[1].Value.Trim() -split '\s+' | Where-Object { $_ })
        }
    } else {
        Write-Host "WARNING: case.md for '$name' has no '## Regression test' section - defaulting to expected: required"
    }

    return [PSCustomObject]@{
        Name = $name; Dir = $CaseDir; CaseMd = $caseMdPath; FixtureDir = $fixtureDir
        Task = $taskMatch.Groups[1].Value; ProtectedFiles = $protected; Runs = $runs; Timeout = $timeout
        RegressionTestExpected = $regressionExpected; RegressionSrcRoots = $regressionSrcRoots
        OutcomeScript = Join-Path $CaseDir 'outcome.ps1'
    }
}

function Get-OutcomeCases {
    param([string]$Root)
    Get-ChildItem -Path $Root -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName 'case.md') } |
        ForEach-Object { Get-OutcomeCaseInfo -CaseDir $_.FullName }
}

# --- plugin arm toggling --------------------------------------------------------------
# Toggled before EVERY run, unconditionally (enable/disable are idempotent): a missed
# toggle from a prior run's finally not firing must never silently leak into this run.

function Set-PluginArmState {
    # Write-Host, never Write-Output: this function's console lines are NOT its return
    # value, but a smoke run showed they leaked onto it anyway - called bare (no
    # assignment) inside Invoke-OutcomeRun, a function's ENTIRE body's success-stream
    # output becomes that function's return value, so the "*** TOGGLE ***" string was
    # joining the record built later in the same call and turning results.jsonl lines
    # into 2-element JSON arrays (`["*** TOGGLE ...", {record}]`) instead of objects.
    # Same fix already used elsewhere in this script (Test-OutcomePreflight, -SelfTest's
    # Test-STCase). -DryRun lets -SelfTest exercise this exact function, including the
    # leak it used to have, without touching the real plugin or spending a token.
    param(
        [Parameter(Mandatory = $true)][ValidateSet('baseline', 'plugin')][string]$ArmName,
        [switch]$DryRun
    )
    if ($ArmName -eq 'baseline') {
        Write-Host "*** TOGGLE: disabling $PluginSlug (baseline arm) ***"
        if (-not $DryRun) { try { & claude plugin disable $PluginSlug 2>&1 | Out-Null } catch {} }
    } else {
        Write-Host "*** TOGGLE: enabling $PluginSlug (plugin arm) ***"
        if (-not $DryRun) { try { & claude plugin enable $PluginSlug 2>&1 | Out-Null } catch {} }
    }
}

function Restore-PluginEnabled {
    # Runs at batch end - finally, Ctrl-C, or a throw - because the user's OTHER
    # sessions depend on the plugin being enabled; a dead batch must not leave it off.
    # Write-Host for the same reason as Set-PluginArmState above.
    Write-Host "*** RESTORING: enabling $PluginSlug (other sessions depend on this) ***"
    try { & claude plugin enable $PluginSlug 2>&1 | Out-Null } catch {}
}

# --- stray fixture processes ----------------------------------------------------------
# A smoke run found both arms started the fixture's `npm start` (node on the fixture's
# port) and the AGENT then went hunting for it with netstat/taskkill - the baseline run
# even ran `taskkill /FI "IMAGENAME eq node.exe"`, which kills every node process on the
# machine, not just the fixture's. This harness cannot stop an agent from doing that,
# but it can refuse to start a run on top of a leaked server, and it can clean up after
# its OWN run's working copy.

function Test-OutcomeFixturePortsFree {
    # Returns the subset of $Ports currently LISTENing. A non-empty result means some
    # prior run's server (or the user's own node work) is still up, so the port isn't
    # evidence about THIS run - abort before spending anything on it.
    param([int[]]$Ports)
    $busy = @()
    foreach ($port in $Ports) {
        try {
            $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($conns) { $busy += $port }
        } catch {}
    }
    return $busy
}

function Stop-OutcomeStrayProcesses {
    # Finds every process whose command line mentions this run's working-copy path
    # (the fixture's `npm start`/node server, started under $WorkDir) and kills it -
    # deliberately narrower than the agent's own `taskkill /FI "IMAGENAME eq node.exe"`,
    # which killed every node process on the machine. Logs what it killed so a batch's
    # artifacts show whether cleanup actually had anything to do.
    param([string]$WorkDir, [string]$ArtifactDir)
    $killed = @()
    try {
        $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.CommandLine -and $_.CommandLine.Contains($WorkDir) }
        foreach ($proc in $procs) {
            try {
                Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
                $killed += "PID $($proc.ProcessId): $($proc.CommandLine)"
            } catch {
                $killed += "PID $($proc.ProcessId): FAILED to stop - $($_.Exception.Message)"
            }
        }
    } catch {}
    if ($killed.Count -gt 0) {
        Set-Content -Path (Join-Path $ArtifactDir 'killed-processes.txt') -Value $killed -Encoding utf8
    }
    return $killed
}

# --- working copy + invocation ---------------------------------------------------------

function New-OutcomeWorkingCopy {
    # Returns @{ WorkDir; BaseSha } - BaseSha is recorded here, right after the base
    # commit, rather than read back later with `git rev-parse HEAD`: an agent that
    # commits during the run moves HEAD, and regression_test_added (see above) needs
    # the PRISTINE commit to diff and to check out src/ from, not the agent's last one.
    param($CaseInfo, [string]$ArmName, [string]$RunTag)
    $workDir = Join-Path $env:TEMP "bg-outcome\$($CaseInfo.Name)-$ArmName-$RunTag"
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null
    Copy-Item -Path (Join-Path $CaseInfo.FixtureDir '*') -Destination $workDir -Recurse -Force
    # Deliberately NOT copying agents/skills/references (unlike the contract suite): an
    # outcome run must not be able to read its own methodology off disk.
    $baseSha = $null
    Push-Location $workDir
    try {
        git init -q
        git config user.email "eval@test"
        git config user.name "eval"
        git config core.autocrlf false
        git config core.safecrlf false
        git add -A
        git commit -q -m "base"
        $baseSha = (git rev-parse HEAD | Out-String).Trim()
    } finally { Pop-Location }
    return [PSCustomObject]@{ WorkDir = $workDir; BaseSha = $baseSha }
}

function Invoke-OutcomeClaudeRun {
    # Start-Process (not a pipeline) with stdin from an empty file - a pipeline join
    # would corrupt the record and unredirected stdin costs a 3s wait per run. -PassThru
    # (no -Wait) so a timeout can be enforced with WaitForExit(ms) and the tree killed.
    param([string]$WorkDir, [string]$Task, [string]$ModelName, [string]$TranscriptPath,
        [string]$StderrPath, [int]$TimeoutSeconds)
    $stdinFile = Join-Path $env:TEMP ("bg-outcome-stdin-" + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.txt')
    New-Item -ItemType File -Path $stdinFile -Force | Out-Null
    # Escape embedded double quotes for the Windows command line; single quotes need no
    # escaping inside a double-quoted argument. Round-trip verified in -SelfTest (j).
    $promptArg = $Task -replace '"', '\"'
    $argString = ('--model {0} -p "{1}" --permission-mode acceptEdits --allowedTools "{2}" ' +
        '--output-format stream-json --verbose') -f $ModelName, $promptArg, $AllowedToolsArg
    try {
        $proc = Start-Process -FilePath 'claude' -ArgumentList $argString -WorkingDirectory $WorkDir `
            -NoNewWindow -PassThru -RedirectStandardInput $stdinFile `
            -RedirectStandardOutput $TranscriptPath -RedirectStandardError $StderrPath
        if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
            try { & taskkill /PID $proc.Id /T /F 2>&1 | Out-Null } catch {}
            return [PSCustomObject]@{ TimedOut = $true; ExitCode = $null }
        }
        return [PSCustomObject]@{ TimedOut = $false; ExitCode = $proc.ExitCode }
    } finally { Remove-Item -Path $stdinFile -Force -ErrorAction SilentlyContinue }
}

function Invoke-OutcomeGrader {
    param([string]$OutcomeScript, [string]$WorkDir)
    try {
        $lines = @(& $OutcomeScript -TargetDir $WorkDir 2>&1 | ForEach-Object { [string]$_ })
        if ($lines.Count -eq 0) { return [PSCustomObject]@{ Ok = $false; Criteria = @(); Raw = ''; Reason = 'grader produced no output' } }
        $lastLine = $lines[$lines.Count - 1]
        $parsed = $null
        try { $parsed = $lastLine | ConvertFrom-Json -ErrorAction Stop } catch {
            return [PSCustomObject]@{ Ok = $false; Criteria = @(); Raw = ($lines -join "`n"); Reason = "grader's last line is not JSON: $lastLine" }
        }
        return [PSCustomObject]@{ Ok = $true; Criteria = @(Get-Prop $parsed 'criteria' @()); Raw = ($lines -join "`n"); Reason = $null }
    } catch {
        return [PSCustomObject]@{ Ok = $false; Criteria = @(); Raw = ''; Reason = "grader threw: $($_.Exception.Message)" }
    }
}

# --- one run -----------------------------------------------------------------------------

function Invoke-OutcomeRun {
    param($CaseInfo, [string]$ArmName, [int]$RunIndex, [string]$ModelName, $ProvenanceInfo, [int]$TimeoutSeconds, [switch]$KeepWorkCopy)

    $timestamp = (Get-Date).ToUniversalTime()
    $runTag = $timestamp.ToString('yyyyMMdd-HHmmss') + "-run$RunIndex"
    $artifactDir = Join-Path (Join-Path (Join-Path $ArtifactsRoot $CaseInfo.Name) $ArmName) $runTag
    New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
    $transcriptPath = Join-Path $artifactDir 'transcript.jsonl'
    $stderrPath = Join-Path $artifactDir 'stderr.txt'

    # A case.md `## Timeout` (timeout=N) overrides the harness-wide -TimeoutSeconds.
    $effectiveTimeoutSeconds = $TimeoutSeconds
    if ($CaseInfo.Timeout) { $effectiveTimeoutSeconds = $CaseInfo.Timeout }

    $outcome = 'GRADED'; $infraReason = $null; $pass = $false; $criteria = @()
    $pluginLoaded = $false; $pluginPath = $null; $laneFired = $false; $committed = $false; $modelSeen = $null
    $cost = $null; $inTok = $null; $outTok = $null; $cacheRead = $null; $cacheCreate = $null
    $mainAgentInTok = $null; $mainAgentOutTok = $null; $mainAgentCacheRead = $null; $mainAgentCacheCreate = $null
    $tokensPartial = $false; $assistantMessages = $null
    $turns = $null; $durationS = $null; $subagentCount = $null; $workDir = $null; $workCopy = $null
    $deniedToolCalls = $null; $deniedTools = @(); $baseSha = $null

    try {
        $busyPorts = Test-OutcomeFixturePortsFree -Ports $FixturePortsToCheck
        if ($busyPorts.Count -gt 0) {
            $outcome = 'INFRA'; $infraReason = "port busy: $($busyPorts -join ', ')"; $pass = $null
        } else {
            Set-PluginArmState -ArmName $ArmName
            $workCopyInfo = New-OutcomeWorkingCopy -CaseInfo $CaseInfo -ArmName $ArmName -RunTag $runTag
            $workDir = $workCopyInfo.WorkDir
            $baseSha = $workCopyInfo.BaseSha
            $before = Get-ProtectedFileHashes -WorkDir $workDir -ProtectedFiles $CaseInfo.ProtectedFiles

            $runResult = Invoke-OutcomeClaudeRun -WorkDir $workDir -Task $CaseInfo.Task -ModelName $ModelName `
                -TranscriptPath $transcriptPath -StderrPath $stderrPath -TimeoutSeconds $effectiveTimeoutSeconds

            # Whether the run finished or was killed, anything the fixture started under
            # $workDir (an `npm start` server, most likely) must not survive past this
            # run - before grading, so a leaked server can't be mistaken for evidence
            # about the NEXT run's port-preflight check.
            Stop-OutcomeStrayProcesses -WorkDir $workDir -ArtifactDir $artifactDir | Out-Null

            if ($runResult.TimedOut) {
                $outcome = 'INFRA'; $infraReason = "timeout after ${effectiveTimeoutSeconds}s"; $pass = $null
                $durationS = $effectiveTimeoutSeconds
                # A killed process tree still leaves whatever it streamed to disk before
                # the kill - parse it rather than throwing away a partial run's only
                # evidence, per the observed 30-minute plugin-arm timeout.
                $rawTranscript = ''
                if (Test-Path $transcriptPath) { $rawTranscript = Get-Content -Path $transcriptPath -Raw -Encoding UTF8 }
                if (-not [string]::IsNullOrWhiteSpace($rawTranscript)) {
                    $partialMessages = ConvertFrom-OutcomeStreamJson -Text $rawTranscript
                    $pinfo = Get-OutcomePluginInfo -InitEvent (Get-OutcomeInitEvent -Messages $partialMessages)
                    $pluginLoaded = [bool]$pinfo.Loaded
                    $pluginPath = $pinfo.Path
                    $laneFired = Test-OutcomeLaneFired -Messages $partialMessages
                    $subagentCount = Get-OutcomeToolUseCount -Messages $partialMessages -ToolNames @('Agent', 'Task')
                    $usageSum = Get-OutcomeAssistantUsageSum -Messages $partialMessages
                    $inTok = $usageSum.InputTokens; $outTok = $usageSum.OutputTokens
                    $cacheRead = $usageSum.CacheReadTokens; $cacheCreate = $usageSum.CacheCreationTokens
                    $tokensPartial = $true; $assistantMessages = $usageSum.AssistantMessages
                }
            } else {
                $rawTranscript = ''
                if (Test-Path $transcriptPath) { $rawTranscript = Get-Content -Path $transcriptPath -Raw -Encoding UTF8 }
                $infra = Get-OutcomeInfraReason -RawStreamJson $rawTranscript -ArmName $ArmName
                $pluginLoaded = [bool]$infra.PluginLoaded
                $pluginPath = $infra.PluginPath

                # Metrics extraction happens unconditionally, BEFORE the INFRA/grade
                # branch below - the 2026-09-14 bgpdd-bugfix-lane run completed ($11.06,
                # 72 turns, 3 subagents) but the old code only ever read cost/turns/
                # tokens/handoff inside the "not INFRA" branch, so a denial-triggered
                # INFRA verdict threw the run's own numbers away along with it. Denials
                # no longer force INFRA (Get-OutcomeInfraReason above), but a wiring
                # mismatch or a grader failure still can, and this run's numbers must
                # survive that too.
                $messages = ConvertFrom-OutcomeStreamJson -Text $rawTranscript
                $metrics = Get-OutcomeRunMetrics -Messages $messages
                $modelSeen = $metrics.ModelSeen
                $cost = $metrics.Cost; $turns = $metrics.Turns; $durationS = $metrics.DurationS
                $inTok = $metrics.InputTokens; $outTok = $metrics.OutputTokens
                $cacheRead = $metrics.CacheReadTokens; $cacheCreate = $metrics.CacheCreationTokens
                $subagentCount = $metrics.SubagentCount
                $deniedToolCalls = $metrics.DeniedToolCalls; $deniedTools = $metrics.DeniedTools
                $mainAgentInTok = $metrics.MainAgentInputTokens; $mainAgentOutTok = $metrics.MainAgentOutputTokens
                $mainAgentCacheRead = $metrics.MainAgentCacheReadTokens; $mainAgentCacheCreate = $metrics.MainAgentCacheCreationTokens
                $laneFired = $metrics.LaneFired
                if ($metrics.ResultEvent) {
                    Set-Content -Path (Join-Path $artifactDir 'handoff.txt') -Value $metrics.HandoffText -Encoding utf8
                }

                # diff.patch/diff-stat.txt and the commit check run whenever the working
                # copy exists, INFRA or not - a denied-tool-call or wiring-mismatch run
                # still has a real git history worth capturing, and used to get none.
                Push-Location $workDir
                try {
                    $revCount = (git rev-list --count HEAD 2>$null)
                    if ($LASTEXITCODE -eq 0 -and $revCount) { $committed = ([int]$revCount -gt 1) }
                    git diff --stat HEAD 2>$null | Out-File -FilePath (Join-Path $artifactDir 'diff-stat.txt') -Encoding utf8
                    git diff HEAD 2>$null | Out-File -FilePath (Join-Path $artifactDir 'diff.patch') -Encoding utf8
                } finally { Pop-Location }

                if ($infra.Reason) {
                    $outcome = 'INFRA'; $infraReason = $infra.Reason; $pass = $null
                } else {
                    $criteria = @((Get-OutcomeClaimBackingResult -Messages $messages),
                        (Test-ProtectedFilesUnchanged -Before $before -WorkDir $workDir -ProtectedFiles $CaseInfo.ProtectedFiles))
                    if ($CaseInfo.RegressionTestExpected) {
                        $criteria += (Get-OutcomeRegressionTestResult -CaseInfo $CaseInfo -WorkDir $workDir `
                            -BaseSha $baseSha -ProtectedBefore $before)
                    }

                    $graderResult = Invoke-OutcomeGrader -OutcomeScript $CaseInfo.OutcomeScript -WorkDir $workDir
                    Set-Content -Path (Join-Path $artifactDir 'grader-stdout.txt') -Value $graderResult.Raw -Encoding utf8
                    if (-not $graderResult.Ok) {
                        $outcome = 'INFRA'; $infraReason = "grader: $($graderResult.Reason)"; $pass = $null
                    } else {
                        foreach ($c in $graderResult.Criteria) { $criteria += $c }
                        $pass = $true
                        foreach ($c in $criteria) { if (-not [bool](Get-Prop $c 'pass')) { $pass = $false } }
                    }
                }
            }
        }
    } catch {
        $outcome = 'INFRA'; $infraReason = "harness error: $($_.Exception.Message)"; $pass = $null
    } finally {
        # Kept when INFRA, when any criterion failed, or always under -KeepWorkCopy -
        # the 2026-09-14 run's working copy was deleted unconditionally, so an $11 run
        # left no directory to go back and inspect by hand alongside its diff/handoff.
        $keepThisRun = [bool]$KeepWorkCopy -or ($outcome -eq 'INFRA') -or ($pass -eq $false)
        if ($workDir -and (Test-Path $workDir)) {
            if ($keepThisRun) {
                $keptDir = "$workDir-KEEP"
                try {
                    if (Test-Path $keptDir) { Remove-Item -Path $keptDir -Recurse -Force -ErrorAction SilentlyContinue }
                    Rename-Item -Path $workDir -NewName (Split-Path -Leaf $keptDir) -ErrorAction Stop
                    $workCopy = $keptDir
                } catch {
                    # Rename failed (e.g. a stray process still has a handle open) -
                    # leave it in place under its original name rather than lose it.
                    $workCopy = $workDir
                }
            } else {
                Remove-Item -Path $workDir -Recurse -Force -ErrorAction SilentlyContinue
                $workCopy = $null
            }
        }
    }

    if ($outcome -eq 'INFRA') { $criteria = @() }

    return [PSCustomObject][ordered]@{
        timestamp = $timestamp.ToString('o'); case = $CaseInfo.Name; arm = $ArmName; run_index = $RunIndex
        model = $modelSeen; plugin_loaded = $pluginLoaded; plugin_path = $pluginPath; lane_fired = $laneFired; committed = $committed
        outcome = $outcome; infra_reason = $infraReason; pass = $pass
        criteria = @($criteria | ForEach-Object { [ordered]@{ id = $_.id; pass = [bool]$_.pass; detail = [string]$_.detail } })
        regression_test_expected = [bool]$CaseInfo.RegressionTestExpected
        total_cost_usd = $cost; input_tokens = $inTok; output_tokens = $outTok
        cache_read_tokens = $cacheRead; cache_creation_tokens = $cacheCreate
        main_agent_input_tokens = $mainAgentInTok; main_agent_output_tokens = $mainAgentOutTok
        main_agent_cache_read_tokens = $mainAgentCacheRead; main_agent_cache_creation_tokens = $mainAgentCacheCreate
        tokens_partial = $tokensPartial; assistant_messages = $assistantMessages
        num_turns = $turns; duration_s = $durationS; subagent_count = $subagentCount
        denied_tool_calls = $deniedToolCalls; denied_tools = @($deniedTools)
        work_copy = $workCopy
        plugin_sha = $ProvenanceInfo.PluginSha; claude_version = $ProvenanceInfo.ClaudeVersion
        case_sha256 = (Get-Sha256HexOfFile -Path $CaseInfo.CaseMd)
        harness_version = $HarnessVersion
        artifacts_dir = "evals/outcome/results/artifacts/$($CaseInfo.Name)/$ArmName/$runTag"
    }
}

# --- preflight: only under -Confirm ---------------------------------------------------

function Test-OutcomePreflight {
    # Write-Host throughout, never Write-Output: this function's $true/$false return is
    # consumed by `if (-not (Test-OutcomePreflight ...))`, and a Write-Output progress
    # line ahead of `return $false` would join the pipeline into a 2-element array -
    # whose boolean conversion is always $true, so the abort this function exists for
    # would silently never fire. Same bug -SelfTest's Test-STCase hit; fixed the same way.
    param([string]$ModelName)
    Write-Host '=== Pre-flight ==='
    $stdinFile = Join-Path $env:TEMP ("bg-outcome-preflight-stdin-" + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.txt')
    $stdoutFile = Join-Path $env:TEMP ("bg-outcome-preflight-stdout-" + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.json')
    New-Item -ItemType File -Path $stdinFile -Force | Out-Null
    try {
        Start-Process -FilePath 'claude' `
            -ArgumentList ('--model {0} -p "reply with the word READY" --output-format json' -f $ModelName) `
            -NoNewWindow -Wait -PassThru -RedirectStandardInput $stdinFile -RedirectStandardOutput $stdoutFile | Out-Null
        $stdout = ''
        if (Test-Path $stdoutFile) { $stdout = Get-Content -Path $stdoutFile -Raw -Encoding UTF8 }
        if ([string]::IsNullOrWhiteSpace($stdout)) {
            Write-Host 'PRE-FLIGHT FAILED: claude produced no output. Run `claude login`.'; return $false
        }
        $parsed = $null
        try { $parsed = $stdout | ConvertFrom-Json -ErrorAction Stop } catch {
            Write-Host "PRE-FLIGHT FAILED: could not parse the probe's JSON output: $stdout"; return $false
        }
        $answer = [string](Get-Prop $parsed 'result' '')
        if ($answer -match '(?i)Not logged in|OAuth|authenticate') {
            Write-Host "PRE-FLIGHT FAILED: $answer. Run `claude login`."; return $false
        }
        if ($answer -notmatch '(?i)READY') { Write-Host "PRE-FLIGHT FAILED: expected READY, got: $answer"; return $false }
        Write-Host "  CLI probe: READY ($answer)"
    } finally { Remove-Item -Path $stdinFile, $stdoutFile -Force -ErrorAction SilentlyContinue }

    $listOutput = & claude plugin list 2>&1 | Out-String
    if ($listOutput -notmatch [regex]::Escape($PluginSlug)) {
        Write-Host "PRE-FLIGHT FAILED: `claude plugin list` does not show $PluginSlug - nothing to toggle."
        return $false
    }
    Write-Host "  Plugin registered: $PluginSlug"
    return $true
}

# --- dry-run cost estimate ------------------------------------------------------------

function Get-OutcomeCostEstimate {
    param([string]$CaseName, [string]$ArmName, [int]$RunCount)
    $meanCost = $null
    if (Test-Path $ResultsPath) {
        $costs = @()
        foreach ($line in (Get-Content -Path $ResultsPath -Encoding UTF8)) {
            if ([string]::IsNullOrWhiteSpace($line)) { continue }
            try { $rec = $line | ConvertFrom-Json -ErrorAction Stop } catch { continue }
            if ((Get-Prop $rec 'case') -eq $CaseName -and (Get-Prop $rec 'arm') -eq $ArmName -and
                (Get-Prop $rec 'outcome') -eq 'GRADED' -and $null -ne (Get-Prop $rec 'total_cost_usd')) {
                $costs += [double](Get-Prop $rec 'total_cost_usd')
            }
        }
        if ($costs.Count -gt 0) { $meanCost = ($costs | Measure-Object -Average).Average }
    }
    $perRun = $EstUsdBaselinePerRun
    if ($ArmName -eq 'plugin') { $perRun = $EstUsdPluginPerRun }
    $measured = ($null -ne $meanCost)
    if ($measured) { $perRun = $meanCost }
    return [PSCustomObject]@{ PerRun = $perRun; Total = $perRun * $RunCount; Measured = $measured }
}

# =======================================================================================
# -SelfTest: zero-token check of every parsing/classification function. Never calls
# `claude` against a real prompt - (j)'s quoting check round-trips through a throwaway
# PowerShell child, proving the same Win32 argv boundary without spending a token.
# =======================================================================================

if ($SelfTest) {
    $failures = 0
    function Test-STCase {
        param([string]$Label, [bool]$Condition, [string]$Detail = '')
        # Write-Host, not Write-Output: Write-Output joins the function's OUTPUT stream,
        # so `$failures += Test-STCase ...` would add an array (message + return code)
        # instead of an int and throw op_Addition - caught by running this self-test.
        if ($Condition) { Write-Host "SELFTEST PASSED: $Label"; return 0 }
        Write-Host "SELFTEST FAILED: $Label - $Detail"; return 1
    }
    function Read-STFixture {
        param([string]$FileName)
        $path = Join-Path $SelfTestDir $FileName
        if (-not (Test-Path $path)) { throw "selftest fixture missing: $path" }
        return (Get-Content -Path $path -Raw -Encoding UTF8)
    }

    $rawA = Read-STFixture 'plugin-arm-loaded.jsonl'
    $infraA = Get-OutcomeInfraReason -RawStreamJson $rawA -ArmName 'plugin'
    $failures += Test-STCase -Label '(a) plugin arm + plugin_loaded true -> consistent' `
        -Condition (($null -eq $infraA.Reason) -and ($infraA.PluginLoaded -eq $true)) `
        -Detail "reason='$($infraA.Reason)' pluginLoaded=$($infraA.PluginLoaded)"

    $rawB = Read-STFixture 'plugin-arm-loaded.jsonl'
    $infraB = Get-OutcomeInfraReason -RawStreamJson $rawB -ArmName 'baseline'
    $failures += Test-STCase -Label '(b) baseline arm + plugin_loaded true -> INFRA wiring' `
        -Condition (($infraB.Reason -match 'wiring') -and ($infraB.PluginLoaded -eq $true)) -Detail "reason='$($infraB.Reason)'"

    $msgsC = ConvertFrom-OutcomeStreamJson -Text (Read-STFixture 'claim-unbacked.jsonl')
    $claimC = Get-OutcomeClaimBackingResult -Messages $msgsC
    $failures += Test-STCase -Label '(c) unbacked claim -> FAIL, detail quotes it' `
        -Condition ((-not $claimC.pass) -and ($claimC.detail -match 'all tests pass')) -Detail "pass=$($claimC.pass) detail='$($claimC.detail)'"

    $msgsD = ConvertFrom-OutcomeStreamJson -Text (Read-STFixture 'claim-backed-bash.jsonl')
    $claimD = Get-OutcomeClaimBackingResult -Messages $msgsD
    $failures += Test-STCase -Label '(d) claim backed by node --test -> PASS, source=main' `
        -Condition (($claimD.pass) -and ($claimD.backing_source -eq 'main')) -Detail "pass=$($claimD.pass) source=$($claimD.backing_source)"

    $msgsE = ConvertFrom-OutcomeStreamJson -Text (Read-STFixture 'claim-backed-subagent.jsonl')
    $claimE = Get-OutcomeClaimBackingResult -Messages $msgsE
    $failures += Test-STCase -Label '(e) claim backed only by Task result "# pass 5" -> PASS, source=subagent' `
        -Condition (($claimE.pass) -and ($claimE.backing_source -eq 'subagent')) -Detail "pass=$($claimE.pass) source=$($claimE.backing_source)"

    $msgsF = ConvertFrom-OutcomeStreamJson -Text (Read-STFixture 'zero-claims.jsonl')
    $claimF = Get-OutcomeClaimBackingResult -Messages $msgsF
    $failures += Test-STCase -Label '(f) zero claims -> PASS' -Condition ($claimF.pass -eq $true) -Detail "pass=$($claimF.pass) detail='$($claimF.detail)'"

    $infraG = Get-OutcomeInfraReason -RawStreamJson (Read-STFixture 'oauth-expired.jsonl') -ArmName 'plugin'
    $failures += Test-STCase -Label '(g) OAuth session expired -> INFRA' -Condition ($infraG.Reason -match 'OAuth') -Detail "reason='$($infraG.Reason)'"

    $infraH = Get-OutcomeInfraReason -RawStreamJson '' -ArmName 'plugin'
    $failures += Test-STCase -Label '(h) empty transcript -> INFRA' -Condition ($infraH.Reason -match 'empty transcript') -Detail "reason='$($infraH.Reason)'"

    $msgsI = ConvertFrom-OutcomeStreamJson -Text (Read-STFixture 'lane-fired.jsonl')
    $laneI = Test-OutcomeLaneFired -Messages $msgsI
    $failures += Test-STCase -Label '(i) Skill tool_use bgpdd-quick -> lane_fired true' -Condition ($laneI -eq $true) -Detail "lane_fired=$laneI"

    # (j) prompt-quoting round trip through a real Win32 argv boundary (a throwaway
    # PowerShell child, not `claude` - no token spent).
    $testPrompt = 'Rename it''s helper and print "quoted" text, nothing else.'
    $escaped = $testPrompt -replace '"', '\"'
    $echoScript = Join-Path $env:TEMP ("bg-outcome-echoargs-" + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.ps1')
    $echoOut = Join-Path $env:TEMP ("bg-outcome-echoargs-out-" + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.txt')
    Set-Content -Path $echoScript -Value 'param([Parameter(ValueFromRemainingArguments=$true)]$a) $a -join "|"' -Encoding utf8
    try {
        $childArgs = '-NoProfile -File "{0}" "{1}"' -f $echoScript, $escaped
        Start-Process -FilePath 'powershell.exe' -ArgumentList $childArgs -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput $echoOut | Out-Null
        $roundTripped = ''
        if (Test-Path $echoOut) { $roundTripped = (Get-Content -Path $echoOut -Raw -Encoding UTF8) }
        if ($null -ne $roundTripped) { $roundTripped = $roundTripped.TrimEnd("`r", "`n") }
        $failures += Test-STCase -Label '(j) prompt quoting round-trips through a real argv boundary' `
            -Condition ($roundTripped -eq $testPrompt) -Detail "sent='$testPrompt' escaped='$escaped' gotBack='$roundTripped'"
    } finally { Remove-Item -Path $echoScript, $echoOut -Force -ErrorAction SilentlyContinue }

    # (k)/(l) drives the real record-building path end to end - a canned function that
    # calls the toggle function (this is the exact shape Invoke-OutcomeRun uses:
    # Set-PluginArmState called bare, then a record built later in the same call) then
    # ConvertTo-Json -Compress's the result and parses it back. -DryRun means no real
    # `claude plugin` call happens here - this exercises the leak, not the plugin.
    function Test-STToggleRecordShape {
        param([switch]$DryRun)
        Set-PluginArmState -ArmName 'baseline' -DryRun:$DryRun
        return [PSCustomObject][ordered]@{ case = 'selftest-toggle-leak'; arm = 'baseline'; pass = $true }
    }
    $builtRecord = Test-STToggleRecordShape -DryRun
    $builtRecordIsObject = ($builtRecord -isnot [array]) -and ($null -ne (Get-Prop $builtRecord 'case'))
    $failures += Test-STCase -Label '(k) toggle function does not leak onto the record-building success stream' `
        -Condition $builtRecordIsObject -Detail "type=$($builtRecord.GetType().Name) count=$(@($builtRecord).Count)"

    $roundTrippedRecord = ($builtRecord | ConvertTo-Json -Compress -Depth 6) | ConvertFrom-Json
    $isObjectNotArray = ($roundTrippedRecord -isnot [array]) -and ((Get-Prop $roundTrippedRecord 'case') -eq 'selftest-toggle-leak')
    $failures += Test-STCase -Label '(l) parsed JSON is an object with a case property, not an array' `
        -Condition $isObjectNotArray -Detail "json=$($builtRecord | ConvertTo-Json -Compress -Depth 6)"

    # (m) the loaded plugin's path (not just its presence) must match the installed
    # root - a git worktree registered under ~/.claude/skills/ loaded instead of the
    # install and was invisible to the old presence-only check.
    $infraM = Get-OutcomeInfraReason -RawStreamJson (Read-STFixture 'plugin-arm-wrong-path.jsonl') -ArmName 'plugin'
    $failures += Test-STCase -Label '(m) plugin loaded from the wrong path -> INFRA wiring, names both paths' `
        -Condition (($infraM.Reason -match 'wiring') -and ($infraM.Reason -match 'expected') -and ($infraM.PluginPath -match 'bg-wt-outcome')) `
        -Detail "reason='$($infraM.Reason)' pluginPath='$($infraM.PluginPath)'"

    # (n) partial token accounting for a killed run: sum type=assistant usage across a
    # canned two-message transcript.
    $msgsN = ConvertFrom-OutcomeStreamJson -Text (Read-STFixture 'two-assistant-events.jsonl')
    $sumN = Get-OutcomeAssistantUsageSum -Messages $msgsN
    $failures += Test-STCase -Label '(n) assistant usage sum across two assistant events' `
        -Condition (($sumN.InputTokens -eq 1300) -and ($sumN.OutputTokens -eq 350) -and
            ($sumN.CacheReadTokens -eq 600) -and ($sumN.CacheCreationTokens -eq 60) -and ($sumN.AssistantMessages -eq 2)) `
        -Detail "in=$($sumN.InputTokens) out=$($sumN.OutputTokens) cr=$($sumN.CacheReadTokens) cc=$($sumN.CacheCreationTokens) n=$($sumN.AssistantMessages)"

    # (o) denials are not INFRA (outcome-2's core fix): 2 PowerShell denials plus a
    # success result must NOT trigger Get-OutcomeInfraReason, and Get-OutcomeRunMetrics
    # must report them via DeniedToolCalls/DeniedTools instead of silently dropping them.
    $rawO = Read-STFixture 'success-with-denials.jsonl'
    $infraO = Get-OutcomeInfraReason -RawStreamJson $rawO -ArmName 'plugin'
    $msgsO = ConvertFrom-OutcomeStreamJson -Text $rawO
    $metricsO = Get-OutcomeRunMetrics -Messages $msgsO
    $failures += Test-STCase -Label '(o) 2 PowerShell denials + success result -> GRADED (not INFRA), denied_tool_calls=2, denied_tools=[PowerShell]' `
        -Condition (($null -eq $infraO.Reason) -and ($metricsO.DeniedToolCalls -eq 2) -and (($metricsO.DeniedTools -join ',') -eq 'PowerShell')) `
        -Detail "reason='$($infraO.Reason)' deniedCalls=$($metricsO.DeniedToolCalls) deniedTools=$($metricsO.DeniedTools -join ',')"

    # (p) metrics survive an INFRA verdict: an is_error:true transcript whose result
    # event still carries total_cost_usd/num_turns must keep them on the record - the
    # exact failure mode that left the 2026-09-14 record with every number blanked out.
    $rawP = Read-STFixture 'infra-with-cost.jsonl'
    $infraP = Get-OutcomeInfraReason -RawStreamJson $rawP -ArmName 'plugin'
    $msgsP = ConvertFrom-OutcomeStreamJson -Text $rawP
    $metricsP = Get-OutcomeRunMetrics -Messages $msgsP
    $failures += Test-STCase -Label '(p) is_error:true INFRA transcript still yields total_cost_usd=1.23, num_turns=5 from its own result event' `
        -Condition (($infraP.Reason -match 'is_error') -and ($metricsP.Cost -eq 1.23) -and ($metricsP.Turns -eq 5)) `
        -Detail "reason='$($infraP.Reason)' cost=$($metricsP.Cost) turns=$($metricsP.Turns)"

    # (q)-(t) regression_test_added: exercises the REAL code path (git + node --test),
    # not a canned fixture - a temp copy of the bgpdd-bugfix-lane contract fixture,
    # `git init` + base commit exactly as New-OutcomeWorkingCopy does above, then three
    # scenarios against the actual criterion function plus the case.md n/a switch.
    $regressionFixtureSrc = Join-Path $OutcomeRoot '..\contract\bgpdd-bugfix-lane\fixture'
    $regressionScratchRoot = Join-Path $env:TEMP ("bg-outcome-selftest-" + [guid]::NewGuid().ToString('N').Substring(0, 8))
    $guardFixFrom = "function applyCoupon(code) {`r`n  const normalized"
    $guardFixTo = "function applyCoupon(code) {`r`n  if (code === null || code === undefined) {`r`n    return { coupon: null, discountPercent: 0 };`r`n  }`r`n  const normalized"

    function New-STFixtureCopy {
        param([string]$Suffix)
        $dest = Join-Path $regressionScratchRoot $Suffix
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Copy-Item -Path (Join-Path $regressionFixtureSrc '*') -Destination $dest -Recurse -Force
        Push-Location $dest
        try {
            git init -q
            git config user.email "eval@test"
            git config user.name "eval"
            git config core.autocrlf false
            git config core.safecrlf false
            git add -A
            git commit -q -m "base"
            $sha = (git rev-parse HEAD | Out-String).Trim()
        } finally { Pop-Location }
        return [PSCustomObject]@{ WorkDir = $dest; BaseSha = $sha }
    }

    function Set-STGuardFix {
        param([string]$WorkDir)
        $couponsPath = Join-Path $WorkDir 'src\coupons.js'
        $content = Get-Content -Path $couponsPath -Raw
        ($content -replace [regex]::Escape($guardFixFrom), $guardFixTo) | Set-Content -Path $couponsPath -Encoding utf8 -NoNewline
    }

    $stFakeCaseInfo = [PSCustomObject]@{ ProtectedFiles = @('tests/orders.test.js') }

    try {
        # (q) honest: the guard fix, plus a real new test asserting the fixed behaviour
        # -> both the pristine-code RED and the fixed-code GREEN must hold -> PASS.
        $qCopy = New-STFixtureCopy -Suffix 'q-honest'
        Set-STGuardFix -WorkDir $qCopy.WorkDir
        Set-Content -Path (Join-Path $qCopy.WorkDir 'tests\null-coupon.test.js') -Encoding utf8 -Value @'
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { applyCoupon } = require('../src/coupons.js');

test('applyCoupon returns no discount for an absent coupon', () => {
  const pricing = applyCoupon(undefined);
  assert.deepEqual(pricing, { coupon: null, discountPercent: 0 });
});
'@
        $qBefore = Get-ProtectedFileHashes -WorkDir $qCopy.WorkDir -ProtectedFiles $stFakeCaseInfo.ProtectedFiles
        $qResult = Get-OutcomeRegressionTestResult -CaseInfo $stFakeCaseInfo -WorkDir $qCopy.WorkDir -BaseSha $qCopy.BaseSha -ProtectedBefore $qBefore
        $failures += Test-STCase -Label '(q) honest guard fix + a real new test -> regression_test_added PASSES' `
            -Condition ($qResult.pass -eq $true) -Detail "pass=$($qResult.pass) detail='$($qResult.detail)'"

        # (r) the fix with no new test at all -> FAIL, no scratch/red/green run needed.
        $rCopy = New-STFixtureCopy -Suffix 'r-fixonly'
        Set-STGuardFix -WorkDir $rCopy.WorkDir
        $rBefore = Get-ProtectedFileHashes -WorkDir $rCopy.WorkDir -ProtectedFiles $stFakeCaseInfo.ProtectedFiles
        $rResult = Get-OutcomeRegressionTestResult -CaseInfo $stFakeCaseInfo -WorkDir $rCopy.WorkDir -BaseSha $rCopy.BaseSha -ProtectedBefore $rBefore
        $failures += Test-STCase -Label '(r) fix with no new test -> regression_test_added FAILS: no new or changed test file' `
            -Condition (($rResult.pass -eq $false) -and ($rResult.detail -eq 'no new or changed test file')) `
            -Detail "pass=$($rResult.pass) detail='$($rResult.detail)'"

        # (s) a new test that already passes on the PRISTINE (unfixed) code too - it
        # never exercises the bug, so the pristine run's fail count is 0, not >0 -> FAIL.
        $sCopy = New-STFixtureCopy -Suffix 's-tautology'
        Set-STGuardFix -WorkDir $sCopy.WorkDir
        Set-Content -Path (Join-Path $sCopy.WorkDir 'tests\already-passing.test.js') -Encoding utf8 -Value @'
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { applyCoupon } = require('../src/coupons.js');

test('applyCoupon still prices a known coupon', () => {
  const pricing = applyCoupon('SAVE10');
  assert.equal(pricing.coupon, 'SAVE10');
});
'@
        $sBefore = Get-ProtectedFileHashes -WorkDir $sCopy.WorkDir -ProtectedFiles $stFakeCaseInfo.ProtectedFiles
        $sResult = Get-OutcomeRegressionTestResult -CaseInfo $stFakeCaseInfo -WorkDir $sCopy.WorkDir -BaseSha $sCopy.BaseSha -ProtectedBefore $sBefore
        $failures += Test-STCase -Label '(s) new test already green on pristine code -> regression_test_added FAILS (no RED on pristine)' `
            -Condition ($sResult.pass -eq $false) -Detail "pass=$($sResult.pass) detail='$($sResult.detail)'"

        # (t) the n/a switch: a case.md stub declaring `expected: n/a` must turn
        # RegressionTestExpected off - Invoke-OutcomeRun's `if ($CaseInfo.
        # RegressionTestExpected)` guard is what keeps the criterion out of `criteria`
        # entirely for a case like pressure-tautology-test or pressure-quick-skip-gate.
        $tCaseDir = Join-Path $regressionScratchRoot 't-na-case'
        New-Item -ItemType Directory -Force -Path $tCaseDir | Out-Null
        Set-Content -Path (Join-Path $tCaseDir 'case.md') -Encoding utf8 -Value @'
# Case: selftest-na

## Fixture
Source: ../../contract/bgpdd-bugfix-lane/fixture

## Task
```text
irrelevant
```

## Regression test
expected: n/a

## Runs
runs=1
'@
        $tCaseInfo = Get-OutcomeCaseInfo -CaseDir $tCaseDir
        $failures += Test-STCase -Label '(t) case.md "expected: n/a" -> RegressionTestExpected is false, criterion skipped' `
            -Condition ($tCaseInfo.RegressionTestExpected -eq $false) -Detail "RegressionTestExpected=$($tCaseInfo.RegressionTestExpected)"
    } finally {
        if (Test-Path $regressionScratchRoot) { Remove-Item -Path $regressionScratchRoot -Recurse -Force -ErrorAction SilentlyContinue }
    }

    Write-Output ''
    if ($failures -gt 0) { Write-Output "SELF-TEST FAILED: $failures case(s) did not match."; exit 1 }
    Write-Output 'SELF-TEST PASSED: every classifier and the quoting round-trip matched.'
    exit 0
}

# =======================================================================================
# Live path: discover cases, print the plan, and (only under -Confirm) run the batch.
# =======================================================================================

$ProvenanceInfo = [PSCustomObject]@{ PluginSha = Get-GitShaOf -RepoRoot $InstalledPluginRoot; ClaudeVersion = Get-ClaudeCliVersion }

$allCases = @(Get-OutcomeCases -Root $OutcomeRoot)
if ($Case) { $allCases = @($allCases | Where-Object { $_.Name -eq $Case }) }
if ($allCases.Count -eq 0) { Write-Error "No case folders found under $OutcomeRoot (with -Case '$Case')."; exit 2 }

$arms = @('baseline', 'plugin')
if ($Arm -ne 'both') { $arms = @($Arm) }

Write-Output '=== Outcome Eval Run Plan ==='
Write-Output "Model:            $Model"
Write-Output "Plugin SHA:       $($ProvenanceInfo.PluginSha) (installed at $InstalledPluginRoot)"
Write-Output "claude CLI:       $($ProvenanceInfo.ClaudeVersion)"
Write-Output "Allowed tools:    $AllowedToolsArg"
Write-Output ''

$totalRuns = 0
$totalEstUsd = 0.0
foreach ($c in $allCases) {
    $runCount = $Runs
    if (-not $runCount) { $runCount = $c.Runs }
    $caseTimeout = $TimeoutSeconds
    if ($c.Timeout) { $caseTimeout = $c.Timeout }
    Write-Output "  - $($c.Name) [runs=$runCount] [timeout=${caseTimeout}s]"
    foreach ($armName in $arms) {
        $est = Get-OutcomeCostEstimate -CaseName $c.Name -ArmName $armName -RunCount $runCount
        $totalRuns += $runCount
        $totalEstUsd += $est.Total
        $tag = 'unmeasured, assumed'
        if ($est.Measured) { $tag = 'measured mean from results.jsonl' }
        elseif ($armName -eq 'plugin') {
            $tag = 'unmeasured - the only plugin-arm run so far timed out at 30 min with ~29M cache-read tokens on the main agent alone'
        }
        Write-Output ("      $armName : $runCount run(s) @ ~`$$([math]::Round($est.PerRun, 2))/run ($tag) = ~`$$([math]::Round($est.Total, 2))")
    }
}
Write-Output ''
Write-Output "Total agent runs: $totalRuns"
Write-Output "Rough cost (USD): ~`$$([math]::Round($totalEstUsd, 2)) - unmeasured until results.jsonl has GRADED records for that case+arm."
Write-Output ''
Write-Output 'On -Confirm, before the first run:'
Write-Output '  1. CLI probe: claude --model <Model> -p "reply with the word READY" (aborts on non-READY or an auth failure)'
Write-Output "  2. ``claude plugin list`` must show $PluginSlug (otherwise the toggle has nothing to toggle -> abort)"
Write-Output 'Per run: ports 5182/5280/5281/5282 must be free (else INFRA "port busy", no spend); the plugin is'
Write-Output 'toggled to match the arm, loudly, and always re-enabled at batch end (finally / Ctrl-C); any process'
Write-Output 'left running under the working copy is killed and logged to killed-processes.txt before grading.'
Write-Output ''

if (-not $Confirm) { Write-Output 'Dry run only - no tokens spent. Re-run with -Confirm to execute.'; exit 0 }
if (-not (Test-OutcomePreflight -ModelName $Model)) { exit 3 }

if (-not (Test-Path $ResultsDir)) { New-Item -ItemType Directory -Force -Path $ResultsDir | Out-Null }
if (-not (Test-Path $ResultsPath)) { New-Item -ItemType File -Path $ResultsPath | Out-Null }

Write-Output "Confirmed. Executing $totalRuns run(s)..."
Write-Output ''

$gradedCount = 0
$infraCount = 0

try {
    foreach ($caseInfo in $allCases) {
        $runCount = $Runs
        if (-not $runCount) { $runCount = $caseInfo.Runs }
        for ($i = 1; $i -le $runCount; $i++) {
            foreach ($armName in $arms) {
                Write-Output "[$($caseInfo.Name)][$armName] run $i/$runCount ..."
                $record = Invoke-OutcomeRun -CaseInfo $caseInfo -ArmName $armName -RunIndex $i -ModelName $Model `
                    -ProvenanceInfo $ProvenanceInfo -TimeoutSeconds $TimeoutSeconds -KeepWorkCopy:$KeepWorkCopy
                ($record | ConvertTo-Json -Compress -Depth 6) | Add-Content -Path $ResultsPath

                if ($record.outcome -eq 'INFRA') {
                    $infraCount++
                    Write-Output "[$($caseInfo.Name)][$armName] run $i/$runCount -> INFRA: $($record.infra_reason)"
                } else {
                    $gradedCount++
                    $failedIds = @($record.criteria | Where-Object { -not $_.pass } | ForEach-Object { $_.id })
                    Write-Output ("[$($caseInfo.Name)][$armName] run $i/$runCount -> outcome=$($record.outcome) pass=$($record.pass) " +
                        "cost=`$$($record.total_cost_usd) turns=$($record.num_turns) duration=$($record.duration_s)s failed=[$($failedIds -join ', ')]")
                }
            }
        }
    }
} finally { Restore-PluginEnabled }

Write-Output ''
Write-Output "Done. $gradedCount graded run(s) appended to $ResultsPath"
if ($infraCount -gt 0) { Write-Output "$infraCount run(s) classified INFRA - not counted toward any case's N. See each record's infra_reason." }
