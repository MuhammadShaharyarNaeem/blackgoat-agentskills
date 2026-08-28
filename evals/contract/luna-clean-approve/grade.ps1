<#
.SYNOPSIS
    Deterministic grader for the luna-clean-approve eval case.

.DESCRIPTION
    The mirror half of luna-verdict-arithmetic: the same orders service with both
    planted defects genuinely fixed and the suite extended to cover the previously
    dark paths (7 tests, 7 pass - verified by hand). The correct verdict is Approve;
    this case catches a reviewer who reaches Request Changes reflexively, inflates
    nit-grade residue into blocking findings, or drifts off the exact Approve token
    that check_commit_gate.py machine-reads.

    Finding-block segmentation, verdict-token regexes, and the cited-path check are
    copied from luna-verdict-arithmetic/grade.ps1 so the pair grades on identical
    parsing - a report shape that parses there parses here.

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no `&&`/`||`.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in.

.OUTPUTS
    Prints "[n] PASSED: ..." / "[n] FAILED: ..." for each criterion, then a final
    RESULT line. Exit 0 = all criteria passed. Exit 1 = at least one failed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

$reportPath = Join-Path $TargetDir '.docs\orders\implementation\review-report.md'

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
    param([string]$Text, [int]$Max = 180)
    if ($null -eq $Text) { return '' }
    $flat = ($Text -replace '\s+', ' ').Trim()
    if ($flat.Length -gt $Max) { return $flat.Substring(0, $Max) + '...' }
    return $flat
}

# Identical segmentation to luna-verdict-arithmetic: a block starts at a Step-4
# taxonomy label in label position and runs to the next label or end of text.
function Get-FindingBlocks {
    param([string]$Text)
    $blocks = @()
    if ([string]::IsNullOrWhiteSpace($Text)) { return $blocks }
    # Optional finding-id clause (`L1 — `, `F-2 - `) between the heading marker and the
    # severity: real Luna reviews number findings as `#### L1 — **Critical:** ...`, which
    # the id-less pattern dropped. The em-dash is built from its codepoint (never a
    # literal byte) so PowerShell 5.1's Windows-1252 decode of this .ps1 can't mangle it.
    # Kept byte-identical to the trap grader's segmentation.
    # The label may also end its line (`#### Critical` with the finding text beneath,
    # observed in a real 2026-08-28 run) - hence the end-of-line alternative after it.
    $em = [char]0x2014
    $labelPattern = '(?im)^[\s>*\-+#|]*(?:[\w.\-]+\s*[' + $em + '\-]\s*)?\**\s*(Critical|Important|Suggestion|Nit|FYI)\b\**(?:\s*[:\-' + $em + '|,(]|\s*$)'
    $found = [regex]::Matches($Text, $labelPattern)
    for ($i = 0; $i -lt $found.Count; $i++) {
        $start = $found[$i].Index
        if ($i -lt ($found.Count - 1)) {
            $end = $found[$i + 1].Index
        } else {
            $end = $Text.Length
        }
        $blocks += [PSCustomObject]@{
            Severity = $found[$i].Groups[1].Value
            Body     = $Text.Substring($start, $end - $start)
        }
    }
    return $blocks
}

# --- [1] the report exists, in the contract's location, keyed to the milestone --
$reportText = ''
if (Test-Path $reportPath) {
    # -Encoding UTF8: agents write UTF-8; PS 5.1's default decode mangles em-dashes and
    # breaks `#### Ln — **Sev:**` finding segmentation. See the trap grader for the full note.
    $rawReport = Get-Content -Path $reportPath -Raw -Encoding UTF8
    if ($null -ne $rawReport) { $reportText = $rawReport }
}

$milestoneHeadingPattern = '(?im)^##\s*Review:.*(?<![a-z0-9])(?:milestone\s*1|m1)(?![a-z0-9])'
if ([string]::IsNullOrWhiteSpace($reportText)) {
    Add-Failure 1 "no review report at .docs/orders/implementation/review-report.md - the code-review-and-quality template owns this path; criteria 2-5 will cascade and say nothing about Luna's judgement"
} elseif ($reportText -match $milestoneHeadingPattern) {
    Add-Pass 1 "review-report.md present ($($reportText.Length) chars) with a '## Review:' heading carrying the milestone identifier"
} else {
    $headings = [regex]::Matches($reportText, '(?im)^##\s*Review:.*$')
    if ($headings.Count -eq 0) {
        Add-Failure 1 "review-report.md exists but has no '## Review:' heading at all - check_commit_gate.py finds no section to read"
    } else {
        Add-Failure 1 "'## Review:' heading does not carry the milestone's leading identifier ('Milestone 1' as a whole token, per plan.md); found: $(Format-Excerpt -Text $headings[0].Value -Max 120)"
    }
}

# @() is load-bearing: PowerShell 5.1 unrolls a one-element array to a scalar.
$blocks = @(Get-FindingBlocks -Text $reportText)
$blockingBlocks = @($blocks | Where-Object { $_.Severity -eq 'Critical' -or $_.Severity -eq 'Important' })

# --- [2] the verdict is the exact token, and it is Approve ----------------------
# Case-SENSITIVE, mirroring check_commit_gate.py's VERDICT_TOKEN_RE.
$verdictLines = [regex]::Matches($reportText, '(?m)^\s*\*\*Verdict:\*\*(.*)$')
if ($verdictLines.Count -eq 0) {
    Add-Failure 2 'no **Verdict:** line in the report - the line is mandatory and machine-read'
} else {
    $lastVerdict = $verdictLines[$verdictLines.Count - 1].Groups[1].Value
    if ($lastVerdict -cmatch '^\s*Approve\s*$') {
        Add-Pass 2 "**Verdict:** Approve - correct arithmetic over a clean fixture"
    } elseif ($lastVerdict -cmatch '^\s*Request Changes\s*$') {
        Add-Failure 2 'the verdict is **Verdict:** Request Changes on a genuinely clean fixture (7/7 tests, both trap-case defect classes fixed and covered) - this is the reflexive-suspicion regression the case guards; read [3] for what justified it'
    } else {
        Add-Failure 2 "the verdict is not one of the two exact tokens: '$(Format-Excerpt -Text $lastVerdict -Max 80)'"
    }
}

# --- [3] no Critical or Important finding stands --------------------------------
# Round 1 on a clean fixture: no prior findings exist, so no RESOLVED marker can be
# legitimate, and any blocking finding is invented or severity-inflated. The
# deliberate residue (leaked id on the audit-failure path, console.error) is
# Suggestion/Nit material - filing it as blocking fails here by design.
if ($blockingBlocks.Count -eq 0) {
    $nonBlocking = @($blocks | Where-Object { $_.Severity -ne 'Critical' -and $_.Severity -ne 'Important' }).Count
    Add-Pass 3 "no Critical/Important finding stands ($nonBlocking non-blocking finding block(s) present - Suggestion/Nit/FYI are fine in any number)"
} else {
    $labels = @($blockingBlocks | ForEach-Object { "$($_.Severity): $(Format-Excerpt -Text $_.Body -Max 100)" })
    Add-Failure 3 "the fixture is clean but $($blockingBlocks.Count) blocking finding(s) stand: $($labels -join ' ;; ')"
}

# --- [4] verdict-token discipline: no approve-with-notes variants ---------------
if ($verdictLines.Count -eq 0) {
    Add-Failure 4 'no **Verdict:** line to assess (see [2])'
} else {
    $bad = New-Object System.Collections.Generic.List[string]
    foreach ($v in $verdictLines) {
        $value = $v.Groups[1].Value
        if (-not ($value -cmatch '^\s*(Approve|Request Changes)\s*$')) {
            [void]$bad.Add((Format-Excerpt -Text $value -Max 60))
        }
    }
    if ($bad.Count -eq 0) {
        Add-Pass 4 "all $($verdictLines.Count) **Verdict:** line(s) carry an exact machine-read token - no approve-with-notes variant"
    } else {
        Add-Failure 4 "non-token verdict value(s) present, which check_commit_gate.py rejects: $($bad -join ' | ')"
    }
}

# --- [5] anti-hallucination: every cited repo path resolves ---------------------
# Same four narrowings as the trap case's criterion 5. One deliberate divergence,
# per case.md: zero finding blocks PASSES here - on a clean fixture a report with
# no findings at all is a legitimate shape, not an unparseable one.
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

foreach ($b in $blocks) {
    $body = [regex]::Replace($b.Body, '(?s)```.*?```', ' ')
    $body = [regex]::Replace($body, '(?s)~~~.*?~~~', ' ')
    foreach ($line in ($body -split "`r?`n")) {
        if ($line -match '(?i)https?://') { continue }
        if ($line -match $proposalCuePattern) { continue }
        foreach ($m in [regex]::Matches($line, $pathCandidatePattern)) {
            $candidate = $m.Groups[1].Value
            if ($candidate -match '^\.{1,2}[\\/]') { continue }
            if ($candidate -match '(?i)^node_modules[\\/]') { continue }
            if (-not (Test-CitedPathExists -Candidate $candidate)) {
                if (-not $bogus.Contains($candidate)) { [void]$bogus.Add($candidate) }
            }
        }
    }
}

if ($blocks.Count -eq 0) {
    Add-Pass 5 'no severity-labelled finding blocks in the report - a legitimate shape on a clean fixture, nothing to check for invented paths'
} elseif ($bogus.Count -eq 0) {
    Add-Pass 5 "every repo path cited in a finding resolves to a real file ($($blocks.Count) finding block(s) scanned)"
} else {
    Add-Failure 5 "finding(s) cite file path(s) that do not exist in the working copy: $($bogus -join ', ')"
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
