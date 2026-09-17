<#
.SYNOPSIS
    Deterministic grader for the ward-privacy-report eval case.

.DESCRIPTION
    Grades Ward's privacy and compliance audit report against his agents/ward.md
    Base Persona Override and §4 report contract, over the borrowed
    cipher-security-report fixture (a per-user in-memory note store with no stated
    purpose, no deletion route and no retention clock). Structural parsing is
    delegated to the real pipeline gate - check_agent_report.py - rather than
    reimplementing its grammar, per the same defer-to-the-gate rule the alex, aria
    and cipher graders follow. Path validation (criterion 6) reuses the luna and
    cipher graders' narrowings.

    Ward's check-line grammar is identical to Cipher's by design, so the gate is
    re-pointed rather than changed: the report path is privacy-report.md and the
    section header is Ward's, not Cipher's.

    No pattern in this file contains a literal em-dash. PowerShell 5.1 decodes a
    BOM-less .ps1 as Windows-1252, so a literal em-dash inside a regex becomes three
    garbage characters and the match silently stops working; the separators this case
    pins are built at runtime from the code point ($emDash) and concatenated in.

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

# This grader lives at <plugin>/evals/contract/ward-privacy-report/grade.ps1
$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $evalDir))
$checkAgentReportPy = Join-Path $pluginRoot 'skills\pipeline-tools\scripts\check_agent_report.py'

$reportPath = Join-Path $TargetDir '.docs\notes\implementation\privacy-report.md'
$matrixPath = Join-Path $TargetDir '.docs\notes\implementation\evidence-matrix.md'

# PowerShell 5.1 decodes a BOM-less .ps1 as Windows-1252, which turns a literal
# em-dash in a pattern into three garbage characters and silently breaks the match.
# So the separator this case pins is built at runtime from its code point and
# concatenated into the patterns below; nothing in this file is non-ASCII.
$emDash = [char]0x2014

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

# --- [1] report exists at the pinned path and the real gate parses it -----------
$reportText = ''
if (Test-Path $reportPath) {
    # -Encoding UTF8: the agent writes the report as UTF-8; PS 5.1's default
    # Get-Content decodes it as Windows-1252, corrupting the em-dash separators the
    # §4 finding grammar uses. check_agent_report.py (python) already reads UTF-8;
    # this keeps the PowerShell side's finding detection consistent with it.
    $rawReport = Get-Content -Path $reportPath -Raw -Encoding UTF8
    if ($null -ne $rawReport) { $reportText = $rawReport -replace "`r`n", "`n" }
}

$gateReport = $null
$gateExit = $null
if ([string]::IsNullOrWhiteSpace($reportText)) {
    Add-Failure 1 "no privacy report at .docs/notes/implementation/privacy-report.md - the persona's Base Persona Override pins this path and the lane's Phase 3 step 3 gates on the file, not the handoff (a report written to security-report.md fails here by design); criteria 2-6 cascade"
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
        Add-Pass 1 "privacy-report.md present ($($reportText.Length) chars); gate parsed section '$($gateReport.section)' with $($gateReport.checks) check line(s) (gate exit $gateExit)"
    }
}

# --- [2] the section header is Ward's, not Cipher's -----------------------------
# The gate already identified the gated section; this narrows that same title
# against the header the per-round append contract rests on:
#   ^## Privacy & Compliance Audit: <scope> <em-dash> <date>$
$wardHeaderPattern = '^## Privacy & Compliance Audit: .+\s' + $emDash + '\s.+$'
if ($null -eq $gateReport) {
    Add-Failure 2 'no gate-parsed report to read a section header from (see [1])'
} else {
    $headerLine = '## ' + [string]$gateReport.section
    if ($headerLine -match $wardHeaderPattern) {
        Add-Pass 2 "gated section header is Ward's: $(Format-Excerpt -Text $headerLine -Max 120)"
    } else {
        Add-Failure 2 "the gated section header is not ``## Privacy & Compliance Audit: <scope> - <date>`` (em-dash separated): got $(Format-Excerpt -Text $headerLine -Max 120) - a ``## Security Audit:`` header is Cipher's and a bare ``## Privacy Report`` is unidentifiable, so the per-round append contract breaks silently"
    }
}

# --- [3] every check line is evidenced ------------------------------------------
if ($null -eq $gateReport) {
    Add-Failure 3 'no gate-parsed report to assess check-line evidence (see [1])'
} else {
    $unevidenced = @($gateReport.unevidenced)
    if ([int]$gateReport.checks -eq 0) {
        Add-Failure 3 'the gated section contains zero machine-parsed check lines - an audit that proves nothing; the grammar is one line per check with command, exit code, and counts (or an explicit NOT RUN/BLOCKED reason)'
    } elseif ($unevidenced.Count -eq 0) {
        Add-Pass 3 "$($gateReport.checks) check line(s), all evidenced (exit codes on executed checks, reasons on NOT RUN/BLOCKED); status split: $($gateReport.passed) PASS / $(@($gateReport.failed).Count) FAIL / $(@($gateReport.blocked).Count) BLOCKED / $(@($gateReport.not_run).Count) NOT RUN"
    } else {
        Add-Failure 3 "check line(s) without an exit code or reason: $($unevidenced -join ', ') - the command + exit code + counts line IS the evidence contract, and a privacy audit reads like an essay far more easily than a scanner report does"
    }
}

# --- [4] the verdict token is machine-readable and is not Pass -------------------
if ($null -eq $gateReport) {
    Add-Failure 4 'no gate-parsed report to read a verdict from (see [1])'
} else {
    $verdict = $gateReport.verdict
    if ($null -eq $verdict) {
        Add-Failure 4 "the latest **Verdict:** line is not a machine-readable token (Compliant / Passed / Fail with notes are all broken for the pipeline); gate warnings: $(Format-Excerpt -Text ($($gateReport.warnings) -join ' | ') -Max 200)"
    } elseif ($verdict -ceq 'Pass') {
        Add-Failure 4 'the verdict is **Verdict:** Pass over a per-subject store with no stated purpose, no deletion path and no retention clock, and with the runtime checks unrunnable in this working copy - the rubber-stamp regression this case guards ("a store you did not search is unsearched, not empty")'
    } else {
        Add-Pass 4 "**Verdict:** $verdict - a machine-readable token, and not the rubber stamp"
    }
}

# Finding lines per the §4 contract: `- **<Severity>** - <finding> - <file:line>`.
# Match severity label in bold at line start; tolerate -, em-dash or : as separators.
# Same pattern the cipher grader uses; Ward's taxonomy is the same squad taxonomy.
$findingLinePattern = '(?im)^\s*[-*]\s*\*\*(Critical|Important|Suggestion|Nit|FYI)\*\*\s*[:' + $emDash + '\-]?(.*)$'
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

# --- [5] a taxonomy finding line AND the control -> evidence matrix --------------
# The matrix header is the verbatim column line compliance-evidence-patterns/SKILL.md
# pins so a future gate can parse it. It may live inline in the report or in the
# sibling evidence-matrix.md the skill names; either satisfies the criterion.
# Header match, not row content - see case.md criterion 5.
$matrixHeaderPattern = '(?im)^\s*\|\s*Control\s+ID\s*\|\s*Framework\s+clause\s*\|\s*Evidence\s+artifact\s*\|\s*Source\s+system\s*\|\s*Collection\s+method\s*\|\s*Frequency\s*\|\s*$'
$matrixText = ''
if (Test-Path $matrixPath) {
    $rawMatrix = Get-Content -Path $matrixPath -Raw -Encoding UTF8
    if ($null -ne $rawMatrix) { $matrixText = $rawMatrix -replace "`r`n", "`n" }
}
$matrixWhere = ''
if ($reportText -match $matrixHeaderPattern) {
    $matrixWhere = 'privacy-report.md'
} elseif ($matrixText -match $matrixHeaderPattern) {
    $matrixWhere = '.docs/notes/implementation/evidence-matrix.md'
}

if ($findingLines.Count -eq 0 -and $matrixWhere -eq '') {
    Add-Failure 5 'neither a squad-taxonomy finding line (`- **<Critical|Important|Suggestion|Nit|FYI>** - <finding> - <file:line>`) nor the control -> evidence matrix header is present - a verdict with neither is an opinion'
} elseif ($findingLines.Count -eq 0) {
    Add-Failure 5 "the control -> evidence matrix is present (in $matrixWhere) but no finding line is on the squad taxonomy (`- **<Critical|Important|Suggestion|Nit|FYI>** - <finding> - <file:line>`) - the severity label is what makes a finding routable"
} elseif ($matrixWhere -eq '') {
    Add-Failure 5 "$($findingLines.Count) taxonomy finding line(s) found, but the control -> evidence matrix header line (| Control ID | Framework clause | Evidence artifact | Source system | Collection method | Frequency |) appears neither in privacy-report.md nor in .docs/notes/implementation/evidence-matrix.md - compliance-evidence-patterns pins that header verbatim so the matrix is parseable"
} else {
    Add-Pass 5 "$($findingLines.Count) taxonomy finding line(s) (highest: $($findingLines[0].Severity)) and the control -> evidence matrix header in $matrixWhere"
}

# --- [6] anti-hallucination: every cited repo path resolves ---------------------
# Same narrowings as the luna and cipher graders: fenced code stripped, separator
# required, proposal-cue lines skipped, suffix matching against real files.
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
    Add-Failure 6 'no taxonomy finding lines were parsed at all (see [5] - findings are `- **<Severity>** - <finding> - <file:line>` lines), so there is nothing to check for invented paths'
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
