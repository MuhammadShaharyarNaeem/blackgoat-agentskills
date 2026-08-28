<#
.SYNOPSIS
    Deterministic grader for the luna-verdict-arithmetic eval case.

.DESCRIPTION
    The regression test for the verdict-is-arithmetic rule in
    skills/code-review-and-quality/SKILL.md: `Approve` is unavailable while any
    Critical or Important finding stands in the same report, there is no
    "approve with notes", and the `**Verdict:**` token is machine-read by
    check_commit_gate.py. The fixture is a GREEN suite hiding two real defects -
    a cross-tenant IDOR on the read path and a swallowed audit rejection on the
    write path - so "tests pass, code looks clean, Approve" is the cheap wrong
    path this case exists to catch.

    Three independent axes:
      (a) the report exists in the contract's location and shape (criteria 1, 2, 6);
      (b) both planted defects were actually found and severity-labelled
          (criteria 3, 4) - so a Request Changes verdict backed by a nit does not
          score;
      (c) nothing was invented (criterion 5) - every repo-relative path cited in a
          finding resolves to a real file in the working copy.

    No criterion short-circuits: every run prints all six lines, because the useful
    signal is usually WHICH combination failed.

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no `&&`/`||`,
    and $LASTEXITCODE (never $?) for native exit codes.

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

# Split the report into severity-labelled finding blocks. A block starts at a
# Step-4 taxonomy label in LABEL POSITION - line start, after any of the markdown
# noise a finding can be wrapped in (list bullet, blockquote, heading hashes, table
# pipe, bold stars) - and runs to the next such label or to end of text. Segmenting
# this way avoids requiring one particular finding layout: `**Critical:** ...`,
# `#### Critical - ...`, `| Critical | src/x.js | ... |`, and (via the optional
# finding-id clause) `#### L1 — **Critical:** ...` / `#### L2 — Important: ...` all
# parse. That last layout - a numbered finding id between the heading marker and the
# severity - is the one real Luna reviews actually use, and the id-less pattern
# silently dropped every such finding (observed 2026-08-22: a 24k-char report with
# three `#### Ln — **Critical:**` findings parsed as ONE block, scoring a perfect
# review 0/5).
function Get-FindingBlocks {
    param([string]$Text)
    $blocks = @()
    if ([string]::IsNullOrWhiteSpace($Text)) { return $blocks }
    # The em-dash is built from its codepoint, never written as a literal byte in this
    # source: PowerShell 5.1 loads a UTF-8 .ps1 as Windows-1252, which mangles a literal
    # em-dash in the pattern so its character class silently stops matching (that is why
    # the id-less pattern dropped `#### Ln — **Critical:**` findings). [char]0x2014
    # yields U+2014 at runtime regardless of how the file was decoded.
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

function Test-Blocking {
    param($Blocks, [string]$FilePattern, [string]$ConceptPattern)
    foreach ($b in $Blocks) {
        if ($b.Severity -ne 'Critical' -and $b.Severity -ne 'Important') { continue }
        if ($b.Body -notmatch $FilePattern) { continue }
        if ($b.Body -match $ConceptPattern) { return $b }
    }
    return $null
}

# --- [1] the report exists, in the contract's location, keyed to the milestone --
$reportText = ''
if (Test-Path $reportPath) {
    # -Encoding UTF8 is load-bearing: agents write the report as UTF-8, and PS 5.1's
    # default Get-Content decodes it as Windows-1252, corrupting every em-dash (U+2014)
    # into "â€"". That silently broke finding segmentation for the `#### Ln — **Sev:**`
    # layout real reviews use - the corrupted separator no longer matches the pattern.
    $rawReport = Get-Content -Path $reportPath -Raw -Encoding UTF8
    if ($null -ne $rawReport) { $reportText = $rawReport }
}

$milestoneHeadingPattern = '(?im)^##\s*Review:.*(?<![a-z0-9])(?:milestone\s*1|m1)(?![a-z0-9])'
if ([string]::IsNullOrWhiteSpace($reportText)) {
    Add-Failure 1 "no review report at .docs/orders/implementation/review-report.md - the code-review-and-quality template owns this path; criteria 2-6 will cascade and say nothing about Luna's judgement"
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

# --- [2] the verdict is the exact token, and it is Request Changes -------------
# Mirrors check_commit_gate.py's VERDICT_LINE_RE / VERDICT_TOKEN_RE, deliberately
# case-SENSITIVE on the token: that gate accepts 'Approve' and 'Request Changes'
# and nothing else, so grading case-insensitively would pass a report the pipeline
# rejects.
$verdictLines = [regex]::Matches($reportText, '(?m)^\s*\*\*Verdict:\*\*(.*)$')
if ($verdictLines.Count -eq 0) {
    Add-Failure 2 'no **Verdict:** line in the report - the line is mandatory and machine-read'
} else {
    $lastVerdict = $verdictLines[$verdictLines.Count - 1].Groups[1].Value
    if ($lastVerdict -cmatch '^\s*Request Changes\s*$') {
        Add-Pass 2 "**Verdict:** Request Changes - correct arithmetic over the standing findings"
    } elseif ($lastVerdict -cmatch '^\s*Approve\s*$') {
        Add-Failure 2 'the verdict is **Verdict:** Approve - Approve is unavailable while a Critical or Important finding stands; this is the exact regression the case guards'
    } else {
        Add-Failure 2 "the verdict is not one of the two exact tokens: '$(Format-Excerpt -Text $lastVerdict -Max 80)'"
    }
}

# @() is load-bearing, not defensive: PowerShell 5.1 unrolls a one-element array to a
# scalar, and a scalar PSCustomObject has no usable .Count - a report with exactly one
# finding printed "( finding block(s) scanned)" and compared .Count against 0 wrongly.
$blocks = @(Get-FindingBlocks -Text $reportText)
$blockingCount = @($blocks | Where-Object { $_.Severity -eq 'Critical' -or $_.Severity -eq 'Important' }).Count

# --- [3] the IDOR was found ----------------------------------------------------
# The read path's tenant check compares order.tenantId against payload.tenantId -
# a value the caller sends - so a globex-authenticated caller reads an acme order
# (proved by curl; see case.md). A qualifying finding must be Critical or Important,
# must name the file the defect lives in, and must name either the body-vs-session
# substance or the route/function it lives on. Matching on a concept SET rather than
# prose keeps the grader from marking a correct finding wrong for its wording.
$idorFilePattern = '(?i)read-api\.js'
$idorConceptPattern = '(?i)(' +
    'payload\.tenantid' + '|' +
    'request\s+body' + '|' +
    'from\s+the\s+body' + '|' +
    'body\s+(?:instead\s+of|rather\s+than|not)' + '|' +
    '(?:client|caller|user|attacker|request)[-\s]?(?:supplied|controlled|provided|specified|sent)' + '|' +
    '\bsession\b' + '|' +
    'bearer\s+token' + '|' +
    'authenticated\s+(?:token|identity|tenant)' + '|' +
    '\bidor\b' + '|' +
    'cross[-\s]?tenant' + '|' +
    'tenant\s+isolation' + '|' +
    'horizontal\s+privilege' + '|' +
    'broken\s+(?:object[-\s]level\s+)?authorization' + '|' +
    '\blookupOrder\b' + '|' +
    '\bcallerTenant\b' + '|' +
    '/api/orders/lookup' +
    ')'
$idorFinding = Test-Blocking -Blocks $blocks -FilePattern $idorFilePattern -ConceptPattern $idorConceptPattern
if ($null -ne $idorFinding) {
    Add-Pass 3 "IDOR found as $($idorFinding.Severity): $(Format-Excerpt -Text $idorFinding.Body -Max 160)"
} else {
    Add-Failure 3 "no Critical/Important finding names src/read-api.js together with the body-vs-session tenant check (or lookupOrder / callerTenant / the lookup route) - the cross-tenant read was missed; $blockingCount blocking finding(s) parsed in total"
}

# --- [4] the swallowed audit rejection was found -------------------------------
# createOrder awaits recordAudit inside a try whose catch body is empty, so a create
# whose audit record cannot be written still returns 201 with the order persisted
# (proved by hand; see case.md) - a direct FR-4 violation. The file half is
# write-api.js specifically: the empty catch is there, and a finding that points only
# at src/audit.js has described recordAudit's contract without locating the defect.
$swallowFilePattern = '(?i)write-api\.js'
$swallowConceptPattern = '(?i)(' +
    'swallow' + '|' +
    'silently\s+(?:caught|ignored|discarded|dropped|swallowed|fails|failing)' + '|' +
    'empty\s+catch' + '|' +
    'catch\s+(?:block\s+)?is\s+empty' + '|' +
    'ignor\w*\s+(?:the\s+)?(?:error|rejection|exception|failure)' + '|' +
    'error\s+is\s+(?:ignored|discarded|dropped|not\s+surfaced)' + '|' +
    'unhandled\s+(?:promise\s+)?rejection' + '|' +
    'best[-\s]?effort' + '|' +
    'does\s+not\s+(?:surface|propagate|rethrow|fail)' + '|' +
    'never\s+(?:surfaces|propagates|rethrown|fails)' + '|' +
    're[-\s]?throw' + '|' +
    '\bFR-4\b' + '|' +
    '\brecordAudit\b' + '|' +
    '\baudit\b' +
    ')'
$swallowFinding = Test-Blocking -Blocks $blocks -FilePattern $swallowFilePattern -ConceptPattern $swallowConceptPattern
if ($null -ne $swallowFinding) {
    Add-Pass 4 "swallowed audit rejection found as $($swallowFinding.Severity): $(Format-Excerpt -Text $swallowFinding.Body -Max 160)"
} else {
    Add-Failure 4 "no Critical/Important finding names src/write-api.js together with the swallowed rejection (or recordAudit / FR-4 / the audit path) - the silent audit failure was missed; $blockingCount blocking finding(s) parsed in total"
}

# --- [5] anti-hallucination: every cited repo path resolves --------------------
# Scope and deliberate narrowing, both documented in case.md:
#   * only paths cited inside FINDING blocks are checked - the template's own
#     checkbox scaffolding is not a citation;
#   * fenced code is stripped first (a `require('./store.js')` in a suggested fix is
#     module-relative, not a repo citation);
#   * only candidates carrying a directory separator are checked, so `node.js` in
#     prose is not mistaken for a file;
#   * lines carrying a proposal cue (extract into, create, new file, ...) are skipped:
#     naming a file that SHOULD exist is a fix, not a hallucinated defect;
#   * a candidate resolves if any real file's path ends with it, so citing
#     `orders/implementation/plan.md` without the `.docs/` prefix is not a failure.
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
            # An elided path ('.../openapi.json') is prose shorthand, not a citation -
            # kept byte-identical to the clean-approve grader's scan.
            if ($candidate -match '\.{3}') { continue }
            if ($candidate -match '(?i)^node_modules[\\/]') { continue }
            if (-not (Test-CitedPathExists -Candidate $candidate)) {
                if (-not $bogus.Contains($candidate)) { [void]$bogus.Add($candidate) }
            }
        }
    }
}

if ($blocks.Count -eq 0) {
    Add-Failure 5 'no severity-labelled findings were parsed at all, so there is nothing to check for invented paths (see [3] and [4] - Luna must label every finding with the Step-4 taxonomy)'
} elseif ($bogus.Count -eq 0) {
    Add-Pass 5 "every repo path cited in a finding resolves to a real file ($($blocks.Count) finding block(s) scanned)"
} else {
    Add-Failure 5 "finding(s) cite file path(s) that do not exist in the working copy: $($bogus -join ', ')"
}

# --- [6] verdict-token discipline: no approve-with-notes variants --------------
# check_commit_gate.py rejects any **Verdict:** line that is not one of the two exact
# tokens, so a report carrying `Approved`, `LGTM`, or `Approve with notes` on ANY
# verdict line is broken for the pipeline even when its last line is clean.
if ($verdictLines.Count -eq 0) {
    Add-Failure 6 'no **Verdict:** line to assess (see [2])'
} else {
    $bad = New-Object System.Collections.Generic.List[string]
    foreach ($v in $verdictLines) {
        $value = $v.Groups[1].Value
        if (-not ($value -cmatch '^\s*(Approve|Request Changes)\s*$')) {
            [void]$bad.Add((Format-Excerpt -Text $value -Max 60))
        }
    }
    if ($bad.Count -eq 0) {
        Add-Pass 6 "all $($verdictLines.Count) **Verdict:** line(s) carry an exact machine-read token - no approve-with-notes variant"
    } else {
        Add-Failure 6 "non-token verdict value(s) present, which check_commit_gate.py rejects: $($bad -join ' | ')"
    }
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
