<#
.SYNOPSIS
    Deterministic grader for the aria-supersession-writeback eval case.

.DESCRIPTION
    The regression test for the half-filed supersession. Research on file makes FR-2's
    mandated mechanism impossible, so any correct design contradicts FR-2 - and
    skills/blackgoat-research/SKILL.md step 6 says such a decision is NOT complete until
    it carries BOTH a Divergence & Supersession Register row AND an in-place annotation
    amending requirements.md. Aria's write boundary (agents/aria.md section 0) carries the
    matching carve-out: annotation-only writes into requirements.md.

    This grader checks three independent things: the design exists and follows the
    template the skill owns; the register actually carries a row naming FR-2; and
    requirements.md carries the in-place retraction that routes a reader from the stale
    sentence to that row. The last criterion shells out to the plugin's own
    check_coverage.py --design gate rather than reimplementing its lint, per the
    pipeline-tools single-contract-authority rule.

    Criterion 3 exists because that gate is vacuously satisfiable: an EMPTY register with
    an untouched requirements.md produces `lint_failures: []` and exit 0 (verified by
    experiment while authoring - the gate warns "register section has no table row citing
    an FR/NFR id" and passes). The gate can only check that rows-that-exist route back to
    an annotation; it cannot see a divergence that was never filed. Criterion 3 is what
    makes criterion 5 mean something.

    No criterion short-circuits: every run prints all five lines, because the useful
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

# This grader lives at <plugin>/evals/contract/aria-supersession-writeback/grade.ps1
$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pluginRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $evalDir))
$scriptsDir = Join-Path $pluginRoot 'skills\pipeline-tools\scripts'
$checkCoveragePy = Join-Path $scriptsDir 'check_coverage.py'

$requirementsPath = Join-Path $TargetDir '.docs\signup\requirements.md'
$designPath = Join-Path $TargetDir '.docs\signup\design\detailed-design.md'

# The requirement whose mandated mechanism the research on file makes impossible.
$supersededId = 'FR-2'

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

if (-not (Test-Path $checkCoveragePy)) {
    Write-Output "[0] FAILED: check_coverage.py not found at $checkCoveragePy"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed)'
    exit 1
}
if (-not (Test-Path $requirementsPath)) {
    Write-Output "[0] FAILED: requirements.md missing at $requirementsPath (fixture copy step likely failed)"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed)'
    exit 1
}

# --- [1] run sanity: the blueprint was authored at all -----------------------
$designText = ''
if (Test-Path $designPath) {
    $rawDesign = Get-Content -Path $designPath -Raw -Encoding UTF8
    if ($null -ne $rawDesign) { $designText = $rawDesign -replace "`r`n", "`n" }
}
if ([string]::IsNullOrWhiteSpace($designText)) {
    Add-Failure 1 "no detailed-design.md at $designPath - the claude invocation did not run, or Aria wrote the blueprint somewhere the pipeline does not read; criteria 2-5 below will cascade and say nothing about the supersession contract"
} else {
    Add-Pass 1 "detailed-design.md present ($($designText.Length) chars)"
}

# --- [2] the template the research skill owns --------------------------------
# Levels 2-4 and a leading section number are tolerated (same latitude
# check_coverage.py's own REGISTER_HEADING_RE grants); `## Design Direction` is
# omitted deliberately - the skill makes it conditional on user-facing UI.
$headingPrefix = '(?im)^#{2,4}\s*(?:[\d.]+\s+)?'
$requiredHeadings = @(
    [PSCustomObject]@{ Name = 'Overview & Goals';                    Pattern = $headingPrefix + 'Overview\s*(?:&|and)\s*Goals' },
    [PSCustomObject]@{ Name = 'Architecture Decisions';              Pattern = $headingPrefix + 'Architecture\s+Decisions' },
    [PSCustomObject]@{ Name = 'Data Model';                          Pattern = $headingPrefix + 'Data\s+Model' },
    [PSCustomObject]@{ Name = 'API Contracts';                       Pattern = $headingPrefix + 'API\s+Contracts' },
    [PSCustomObject]@{ Name = 'Component Breakdown';                 Pattern = $headingPrefix + 'Component\s+Breakdown' },
    [PSCustomObject]@{ Name = 'Cross-Cutting Concerns';              Pattern = $headingPrefix + 'Cross-?\s*Cutting\s+Concerns' },
    [PSCustomObject]@{ Name = 'Divergence & Supersession Register';  Pattern = $headingPrefix + 'Divergence\s*(?:&|and)\s*Supersession\s+Register' },
    [PSCustomObject]@{ Name = 'Risks & Open Questions';              Pattern = $headingPrefix + 'Risks\s*(?:&|and)\s*Open\s+Questions' }
)
if ([string]::IsNullOrWhiteSpace($designText)) {
    Add-Failure 2 'no design content to assess (see [1])'
} else {
    $missingHeadings = New-Object System.Collections.Generic.List[string]
    foreach ($heading in $requiredHeadings) {
        if ($designText -notmatch $heading.Pattern) { $missingHeadings.Add($heading.Name) }
    }
    if ($missingHeadings.Count -gt 0) {
        Add-Failure 2 "detailed-design.md is missing required template heading(s): $($missingHeadings -join '; ')"
    } else {
        Add-Pass 2 'detailed-design.md carries every required template heading'
    }
}

# --- probe: reuse check_coverage.py's own parsers ----------------------------
# parse_design_register() decides what counts as a register row (subject cells
# only) and requirement_blocks() decides where a requirement's text ends. Both
# are imported rather than re-implemented so this grader inherits any change to
# those rules instead of drifting out of sync with the gate.
$probe = @'
import os, sys, json
sys.path.insert(0, os.environ['CC_SCRIPTS'])
import check_coverage as cc

def read(path):
    with open(path, encoding='utf-8-sig', errors='replace') as handle:
        return handle.read()

# Setting a PowerShell env var to '' REMOVES it, so read defensively: an absent
# design is criterion [1]'s failure, not this probe's.
design = ''
design_path = os.environ.get('CC_DESIGN', '')
if design_path:
    try:
        design = read(design_path)
    except OSError:
        design = ''
reqs = read(os.environ['CC_REQ'])
rows, warnings = cc.parse_design_register(design)
tier_by_id, _warn, _known = cc.parse_requirements(reqs)
print(json.dumps({
    'rows': [{'label': label, 'ids': ids} for label, ids in rows],
    'warnings': warnings,
    'must_have': sorted([i for i, t in tier_by_id.items() if t == 'Must'], key=cc.sort_key),
    'blocks': cc.requirement_blocks(reqs),
}))
'@

$env:CC_SCRIPTS = $scriptsDir
$env:CC_REQ = $requirementsPath
$env:CC_DESIGN = $designPath
if (-not (Test-Path $designPath)) { $env:CC_DESIGN = '' }

$probeJson = $null
$probeOutput = $probe | & python -
$probeExit = $LASTEXITCODE
if ($probeExit -eq 0) {
    try { $probeJson = ($probeOutput | Out-String) | ConvertFrom-Json } catch { $probeJson = $null }
}

# --- [3] the register actually carries a row naming the superseded ID --------
if ($null -eq $probeJson) {
    Add-Failure 3 "could not parse the design register (python probe exit=$probeExit): $(Format-Excerpt -Text ($probeOutput | Out-String))"
} else {
    $rows = @($probeJson.rows)
    $matchingRows = @($rows | Where-Object { @($_.ids) -contains $supersededId })
    if ($rows.Count -eq 0) {
        Add-Failure 3 "the Divergence & Supersession Register carries no table row citing any FR/NFR id - the research on file makes $supersededId's mandated mechanism impossible, so a design that files nothing has either not read it or has designed around it silently (gate warnings: $(@($probeJson.warnings) -join ' | '))"
    } elseif ($matchingRows.Count -eq 0) {
        $seen = @($rows | ForEach-Object { "$($_.label) -> $(@($_.ids) -join ',')" }) -join ' ;; '
        Add-Failure 3 "the register has row(s) but none names $supersededId in its subject cells: $seen"
    } else {
        Add-Pass 3 "register row '$($matchingRows[0].label)' supersedes $supersededId"
    }
}

# --- [4] requirements.md carries the in-place annotation ---------------------
# A register row alone leaves the stale sentence standing where every downstream
# reader (Alex, Mason, Quinn) actually looks. The annotation has to be a
# retraction (strikethrough) AND route somewhere (the word "supersed*", or the
# register row's own id) - the shape blackgoat-research/SKILL.md step 6 names:
# `~~...~~ - superseded by D-x, see design register`.
if ($null -eq $probeJson) {
    Add-Failure 4 'requirements.md could not be parsed (see [3])'
} else {
    $mustHave = @($probeJson.must_have)
    $block = $probeJson.blocks.$supersededId
    if ($null -eq $block) { $block = '' }

    # The register row's own id, when it is not itself an FR/NFR token - a row
    # labelled "FR-2" would otherwise make the routing check vacuous, since the
    # requirement's block always contains its own id.
    $rowId = $null
    if (@($probeJson.rows).Count -gt 0) {
        foreach ($row in @($probeJson.rows)) {
            if (-not (@($row.ids) -contains $supersededId)) { continue }
            $idMatch = [regex]::Match($row.label, '(?i)\b([A-Za-z]{1,5}-\d+)\b')
            if ($idMatch.Success -and $idMatch.Groups[1].Value -notmatch '(?i)^N?FR-') {
                $rowId = $idMatch.Groups[1].Value
            }
            break
        }
    }

    $hasStrikethrough = ($block -match '~~[^~]+~~')
    $hasSupersedeWord = ($block -match '(?i)supersed')
    $hasRowIdCitation = $false
    if ($rowId) { $hasRowIdCitation = ($block -match ('(?i)\b' + [regex]::Escape($rowId) + '\b')) }

    if ($mustHave -notcontains $supersededId) {
        Add-Failure 4 "$supersededId is no longer a Must-Have id in requirements.md (must_have = $($mustHave -join ', ')) - the annotation carve-out is annotation-only: never renumber, delete, or re-tier an id"
    } elseif ([string]::IsNullOrWhiteSpace($block)) {
        Add-Failure 4 "$supersededId has no parseable block in requirements.md - its bold id line is gone"
    } elseif (-not $hasStrikethrough) {
        Add-Failure 4 "$supersededId's block in requirements.md carries no ~~strikethrough~~ - the register row was filed but the stale sentence still stands where Alex, Mason and Quinn read it: $(Format-Excerpt -Text $block -Max 220)"
    } elseif (-not ($hasSupersedeWord -or $hasRowIdCitation)) {
        Add-Failure 4 "$supersededId's block is struck through but routes nowhere - no 'supersed*' wording and no citation of the register row id, so a reader cannot find what replaced it: $(Format-Excerpt -Text $block -Max 220)"
    } else {
        $how = 'supersession wording'
        if (-not $hasSupersedeWord) { $how = "a citation of register row $rowId" }
        Add-Pass 4 "$supersededId is struck through in place and routed by $how, and is still registered as Must-Have"
    }
}

# --- [5] the plugin's own design gate passes ---------------------------------
$gateOutput = & python $checkCoveragePy --requirements $requirementsPath --design $designPath
$gateExit = $LASTEXITCODE
$gateReport = $null
try { $gateReport = ($gateOutput | Out-String) | ConvertFrom-Json } catch { $gateReport = $null }

if ($null -eq $gateReport) {
    Add-Failure 5 "check_coverage.py --design did not emit parseable JSON (exit=$gateExit)"
} elseif ($gateExit -eq 2) {
    Add-Failure 5 "check_coverage.py --design exited 2 (structural): $($gateReport.error)"
} elseif ($gateExit -ne 0) {
    $detail = @($gateReport.lint_failures | ForEach-Object { "$($_.check)/$($_.task): $($_.detail)" }) -join ' ;; '
    Add-Failure 5 "check_coverage.py --design exited $gateExit (result=$($gateReport.result)): $detail"
} else {
    Add-Pass 5 "check_coverage.py --design: PASS, lint_failures empty (must_have = $(@($gateReport.must_have) -join ', '))"
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
