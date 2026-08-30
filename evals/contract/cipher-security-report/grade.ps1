<#
.SYNOPSIS
    Deterministic grader for the cipher-security-report eval case.

.DESCRIPTION
    Grades Cipher's shipping-stage security report against his agents/cipher.md §4
    contract, over a fixture with two planted vulnerabilities (a hardcoded sk_live
    signing secret in src/config.js, wildcard CORS on authenticated routes in
    src/server.js). Structural parsing is delegated to the real pipeline gate -
    check_agent_report.py - rather than reimplementing its grammar, per the same
    defer-to-the-gate rule the alex and aria graders follow. Finding detection
    (criteria 3, 4) matches concept sets, not prose. Path validation (criterion 6)
    reuses the luna graders' narrowings.

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no `&&`/`||`,
    and $LASTEXITCODE (never $?) for native exit codes.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in.

.OUTPUTS
    Prints "[n] PASSED: ..." / "[n] FAILED: ..." per criterion, then a final RESULT
    line. Exit 0 = all criteria passed. Exit 1 = at least one failed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

# This grader lives at <plugin>/evals/contract/cipher-security-report/grade.ps1
$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $evalDir))
$checkAgentReportPy = Join-Path $pluginRoot 'skills\pipeline-tools\scripts\check_agent_report.py'

$reportPath = Join-Path $TargetDir '.docs\notes\implementation\security-report.md'

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
    param([string]$Text, [int]$Max = 160)
    if ($null -eq $Text) { return '' }
    $flat = ($Text -replace '\s+', ' ').Trim()
    if ($flat.Length -gt $Max) { return $flat.Substring(0, $Max) + '...' }
    return $flat
}

if (-not (Test-Path $checkAgentReportPy)) {
    Write-Output "FAILED: [0] check_agent_report.py not found at $checkAgentReportPy"
    exit 1
}

# --- [1] report exists and the real gate parses it structurally -----------------
$reportText = ''
if (Test-Path $reportPath) {
    # -Encoding UTF8: the agent writes the report as UTF-8; PS 5.1's default Get-Content
    # decodes it as Windows-1252, corrupting the em-dash `— <file:line>` separators the
    # §4 finding grammar uses. check_agent_report.py (python) already reads UTF-8; this
    # keeps the PowerShell side's finding detection consistent with it.
    $rawReport = Get-Content -Path $reportPath -Raw -Encoding UTF8
    if ($null -ne $rawReport) { $reportText = $rawReport }
}

$gateReport = $null
$gateExit = $null
if ([string]::IsNullOrWhiteSpace($reportText)) {
    Add-Failure 1 "no security report at .docs/notes/implementation/security-report.md - the persona's §4 contract owns this path and the pipelines gate on the file, not the handoff; criteria 2-6 cascade"
} else {
    $gateOutput = & python $checkAgentReportPy --report $reportPath
    $gateExit = $LASTEXITCODE
    try { $gateReport = $gateOutput | ConvertFrom-Json } catch { $gateReport = $null }

    if ($null -eq $gateReport) {
        Add-Failure 1 "check_agent_report.py did not emit parseable JSON (exit=$gateExit)"
    } elseif ($gateReport.result -eq 'ERROR') {
        Add-Failure 1 "check_agent_report.py rejected the report structurally: $($gateReport.error) - the report does not speak the pipeline's grammar"
        $gateReport = $null
    } else {
        Add-Pass 1 "security-report.md present ($($reportText.Length) chars); gate parsed section '$($gateReport.section)' with $($gateReport.checks) check line(s) (gate exit $gateExit)"
    }
}

# --- [2] the verdict token is exactly Fail --------------------------------------
if ($null -eq $gateReport) {
    Add-Failure 2 'no gate-parsed report to read a verdict from (see [1])'
} else {
    $verdict = $gateReport.verdict
    if ($verdict -ceq 'Fail') {
        Add-Pass 2 "**Verdict:** Fail - correct arithmetic over the standing findings"
    } elseif ($verdict -ceq 'Pass') {
        Add-Failure 2 'the verdict is **Verdict:** Pass over a fixture carrying a hardcoded sk_live signing secret and wildcard CORS on authenticated routes - the pass-by-eyeball regression this case guards'
    } else {
        Add-Failure 2 "the latest **Verdict:** line is not a machine-readable token (gate parsed verdict: $(Format-Excerpt -Text ([string]$verdict) -Max 60); warnings: $(Format-Excerpt -Text ($($gateReport.warnings) -join ' | ') -Max 200))"
    }
}

# Finding lines per the §4 contract: `- **<Severity>** — <finding> — <file:line>`.
# Match severity label in bold at line start; tolerate -, — or : as separators.
$findingLinePattern = '(?im)^\s*[-*]\s*\*\*(Critical|Important|Suggestion|Nit|FYI)\*\*\s*[:—\-]?(.*)$'
$findingLines = @()
if (-not [string]::IsNullOrWhiteSpace($reportText)) {
    foreach ($m in [regex]::Matches($reportText, $findingLinePattern)) {
        $findingLines += [PSCustomObject]@{
            Severity = $m.Groups[1].Value
            Body     = $m.Groups[2].Value
            Line     = $m.Value
        }
    }
}

function Test-FindingPresent {
    param([string[]]$Severities, [string]$FilePattern, [string]$ConceptPattern)
    foreach ($f in $findingLines) {
        if ($Severities -notcontains $f.Severity) { continue }
        if ($f.Line -notmatch $FilePattern) { continue }
        if ($f.Line -match $ConceptPattern) { return $f }
    }
    return $null
}

# --- [3] the hardcoded signing secret was found (Critical) ----------------------
$secretConceptPattern = '(?i)(' +
    'hard[-\s]?cod\w*' + '|' +
    '\bsecret\b' + '|' +
    'jwtsecret' + '|' +
    'signing\s+(?:key|secret)' + '|' +
    'sk_live' + '|' +
    '\bcredential\w*' + '|' +
    'api\s*key' + '|' +
    'committed\s+(?:to\s+)?(?:version\s+control|the\s+repo|git)' +
    ')'
$secretFinding = Test-FindingPresent -Severities @('Critical') -FilePattern '(?i)config\.js' -ConceptPattern $secretConceptPattern
if ($null -ne $secretFinding) {
    Add-Pass 3 "hardcoded secret found as Critical: $(Format-Excerpt -Text $secretFinding.Line)"
} else {
    Add-Failure 3 "no Critical finding line names src/config.js together with the hardcoded signing secret (sk_live / jwtSecret / secret / credential) - persona §1 names this duty verbatim; $($findingLines.Count) finding line(s) parsed in total"
}

# --- [4] the wildcard CORS on authenticated routes was found --------------------
$corsConceptPattern = '(?i)(' +
    '\bcors\b' + '|' +
    'access-control-allow-origin' + '|' +
    'wildcard' + '|' +
    '\*\s*(?:origin|cors)' + '|' +
    'any\s+origin' + '|' +
    'all\s+origins' + '|' +
    'cross[-\s]?origin' +
    ')'
$corsFinding = Test-FindingPresent -Severities @('Critical', 'Important') -FilePattern '(?i)server\.js' -ConceptPattern $corsConceptPattern
if ($null -ne $corsFinding) {
    Add-Pass 4 "wildcard CORS found as $($corsFinding.Severity): $(Format-Excerpt -Text $corsFinding.Line)"
} else {
    Add-Failure 4 "no Critical/Important finding line names src/server.js together with the wildcard CORS grant on authenticated routes - persona §2 rejects this configuration verbatim; $($findingLines.Count) finding line(s) parsed in total"
}

# --- [5] every check line is evidenced ------------------------------------------
if ($null -eq $gateReport) {
    Add-Failure 5 'no gate-parsed report to assess check-line evidence (see [1])'
} else {
    $unevidenced = @($gateReport.unevidenced)
    if ([int]$gateReport.checks -eq 0) {
        Add-Failure 5 'the gated section contains zero machine-parsed check lines - an audit that proves nothing; the §4 grammar is one line per check with command, exit code, and counts'
    } elseif ($unevidenced.Count -eq 0) {
        Add-Pass 5 "$($gateReport.checks) check line(s), all evidenced (exit codes on executed checks, reasons on NOT RUN/BLOCKED); status split: $($gateReport.passed) PASS / $(@($gateReport.failed).Count) FAIL / $(@($gateReport.blocked).Count) BLOCKED / $(@($gateReport.not_run).Count) NOT RUN"
    } else {
        Add-Failure 5 "check line(s) without an exit code or reason: $($unevidenced -join ', ') - the command + exit code + counts line IS the evidence contract"
    }
}

# --- [6] anti-hallucination: every cited repo path resolves ---------------------
# Same narrowings as the luna graders: fenced code stripped, separator required,
# proposal-cue lines skipped, suffix matching against real files.
$existingPaths = New-Object System.Collections.Generic.HashSet[string]
if (Test-Path $TargetDir) {
    $rootFull = (Resolve-Path -Path $TargetDir).Path
    Get-ChildItem -Path $rootFull -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '(?i)[\\/](?:node_modules|\.git)[\\/]' } |
        ForEach-Object {
            $rel = $_.FullName.Substring($rootFull.Length).TrimStart('\', '/')
            [void]$existingPaths.Add(($rel -replace '\\', '/').ToLowerInvariant())
        }
}

function Test-CitedPathExists {
    param([string]$Candidate)
    $norm = ($Candidate -replace '\\', '/').ToLowerInvariant().TrimStart('/')
    foreach ($p in $existingPaths) {
        if ($p -eq $norm) { return $true }
        if ($p.EndsWith('/' + $norm)) { return $true }
    }
    return $false
}

$proposalCuePattern = '(?i)\b(extract\w*|create|creating|add|adding|introduc\w*|new\s+(?:file|module|helper)|move|moving|rename|renam\w*|propos\w*|suggest\w*|should\s+live|split\s+into)\b'
$pathCandidatePattern = '(?<![\w.\-/\\])((?:[\w.\-]+[\\/])+[\w.\-]+\.[A-Za-z][A-Za-z0-9]{0,4})(?![\w])'
$bogus = New-Object System.Collections.Generic.List[string]

foreach ($f in $findingLines) {
    $body = [regex]::Replace($f.Line, '(?s)```.*?```', ' ')
    if ($body -match '(?i)https?://') { continue }
    if ($body -match $proposalCuePattern) { continue }
    foreach ($m in [regex]::Matches($body, $pathCandidatePattern)) {
        $candidate = $m.Groups[1].Value
        if ($candidate -match '^\.{1,2}[\\/]') { continue }
        if ($candidate -match '(?i)^node_modules[\\/]') { continue }
        if (-not (Test-CitedPathExists -Candidate $candidate)) {
            if (-not $bogus.Contains($candidate)) { [void]$bogus.Add($candidate) }
        }
    }
}

if ($findingLines.Count -eq 0) {
    Add-Failure 6 'no §4-format finding lines were parsed at all (see [3] and [4] - findings are `- **<Severity>** — <finding> — <file:line>` lines), so there is nothing to check for invented paths'
} elseif ($bogus.Count -eq 0) {
    Add-Pass 6 "every repo path cited in a finding line resolves to a real file ($($findingLines.Count) finding line(s) scanned)"
} else {
    Add-Failure 6 "finding line(s) cite file path(s) that do not exist in the working copy: $($bogus -join ', ')"
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
