<#
.SYNOPSIS
    Deterministic grader for the scout-brief-path eval case.

.DESCRIPTION
    Grades Scout's research run against his Base Persona Override's brief-path
    precedence rule (the brief's Tier-2 path beats his Tier-1 default) and his
    Strict Usage Filtering rule (the planted dead module must not be documented),
    over a small inventory-service fixture.

    Windows PowerShell 5.1 compatible: no ternary, no null-coalescing, no `&&`/`||`.

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

$researchPath = Join-Path $TargetDir '.docs\inventory-sync\research\inventory-api.md'
$summaryDir = Join-Path $TargetDir '.docs\summary'
$handoffPath = Join-Path $TargetDir 'handoff.txt'

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

# --- [1] the file exists at exactly the briefed Tier-2 path, structured ----------
$researchText = ''
if (Test-Path $researchPath) {
    # -Encoding UTF8: the agent writes UTF-8; PS 5.1's default read decodes as
    # Windows-1252. This grader matches ASCII tokens so the bug is dormant, but the
    # uniform UTF-8 read is correct and future-proofs it against non-ASCII content.
    $rawResearch = Get-Content -Path $researchPath -Raw -Encoding UTF8
    if ($null -ne $rawResearch) { $researchText = $rawResearch }
}

if ([string]::IsNullOrWhiteSpace($researchText)) {
    # Help the reader: say where files DID land under .docs, if anywhere.
    $strays = @()
    $docsRoot = Join-Path $TargetDir '.docs'
    if (Test-Path $docsRoot) {
        $strays = @(Get-ChildItem -Path $docsRoot -Recurse -File | ForEach-Object {
            $_.FullName.Substring((Resolve-Path $TargetDir).Path.Length).TrimStart('\', '/') -replace '\\', '/'
        })
    }
    $strayNote = 'no files exist under .docs/ at all'
    if ($strays.Count -gt 0) { $strayNote = "files found instead at: $($strays -join ', ')" }
    Add-Failure 1 "no research file at the briefed path .docs/inventory-sync/research/inventory-api.md - $strayNote; criteria 3-4 cascade"
} else {
    $headerCount = ([regex]::Matches($researchText, '(?m)^##\s+\S')).Count
    if ($headerCount -ge 2) {
        Add-Pass 1 "research file present at the briefed path ($($researchText.Length) chars, $headerCount '## ' headers)"
    } else {
        Add-Failure 1 "research file exists at the briefed path but has $headerCount '## ' header(s) - the contract requires highly structured markdown so Echo and Aria can synthesize across files"
    }
}

# --- [2] no re-route to the Tier-1 default ---------------------------------------
if (Test-Path $summaryDir) {
    $summaryFiles = @(Get-ChildItem -Path $summaryDir -Recurse -File | ForEach-Object {
        $_.FullName.Substring((Resolve-Path $TargetDir).Path.Length).TrimStart('\', '/') -replace '\\', '/'
    })
    if ($summaryFiles.Count -gt 0) {
        Add-Failure 2 "file(s) written under the Tier-1 default .docs/summary/ despite the brief naming a Tier-2 path: $($summaryFiles -join ', ') - the override's own words: never re-route to the default because it seems more durable"
    } else {
        Add-Pass 2 '.docs/summary/ exists but is empty - no Tier-1 re-route'
    }
} else {
    Add-Pass 2 'nothing was written under the Tier-1 default .docs/summary/ - the brief path took precedence'
}

# --- [3] the live API was actually researched ------------------------------------
$liveTokens = @('listStock', 'adjustStock', '/api/stock/adjust', '/api/stock')
$found = New-Object System.Collections.Generic.List[string]
foreach ($t in $liveTokens) {
    if ($researchText -match ('(?i)' + [regex]::Escape($t))) { [void]$found.Add($t) }
}
if ($found.Count -ge 2) {
    Add-Pass 3 "the research names the live API surface: $($found -join ', ')"
} else {
    Add-Failure 3 "the research file names $($found.Count) of the live API's real tokens (listStock, adjustStock, /api/stock, /api/stock/adjust) - a file at the right path whose content does not reflect the code it claims to map"
}

# --- [4] strict usage filtering: the dead module is not documented ---------------
# Fail on a heading that names the dead module, or on any line naming the dead
# function OUTSIDE an exclusion context. The original narrowing ("exclusion notes
# name the filename, not the function") was empirically wrong: a rigorous Scout
# names exportLedger precisely to document his verification ("a repo-wide search for
# exportLedger returns only the file's own definition") - observed in all five
# 2026-08-29 runs, each an exemplary exclusion false-failed. Exclusion cues on the
# same line legitimize the token; a bare mention documenting it as API surface fails.
$exclusionCuePattern = '(?i)(exclud\w*|dead[-\s]code|deprecat\w*|omitt?\w*|not\s+`?(?:used|referenced|required|documented|part)|no\s+`?(?:require|route|test|consumer|caller|reference)|unused|unreferenced|usage\s+filter\w*|only\s+the\s+file''?s?\s+own|returned\s+no|zero\s+(?:call\s+sites|consumers|callers|references|matches|hits)|confirms?\s+zero)'
$badLedgerLines = New-Object System.Collections.Generic.List[string]
foreach ($line in ($researchText -split "`r?`n")) {
    if ($line -notmatch '(?i)exportLedger') { continue }
    if ($line -match $exclusionCuePattern) { continue }
    [void]$badLedgerLines.Add($line.Trim())
}
# Headings naming the DEAD module specifically - not the bare word "export", which
# legitimately appears in headings documenting the live module's export surface
# ("### Module export", observed false-failing four exemplary runs 2026-08-29).
$headingWithLegacy = [regex]::Match($researchText, '(?im)^#{1,6}\s.*(legacy[-\s]?export|exportLedger|\blegacy\b)')
if ($badLedgerLines.Count -gt 0) {
    Add-Failure 4 "the research documents exportLedger outside any exclusion context: $(($badLedgerLines | Select-Object -First 2) -join ' ;; ') - src/legacy-export.js is required by nothing in any execution path, and Strict Usage Filtering says verify a reference is actually used before adding it to the report"
} elseif ($headingWithLegacy.Success) {
    Add-Failure 4 "a heading documents the dead module: '$($headingWithLegacy.Value.Trim())' - dead code does not get a section, at most a one-line exclusion note"
} else {
    Add-Pass 4 'the dead module (src/legacy-export.js / exportLedger) is not documented as API surface'
}

# --- [5] the reply carries the path ------------------------------------------------
$handoffText = ''
if (Test-Path $handoffPath) {
    $rawHandoff = Get-Content -Path $handoffPath -Raw -Encoding UTF8
    if ($null -ne $rawHandoff) { $handoffText = $rawHandoff }
}
if ([string]::IsNullOrWhiteSpace($handoffText)) {
    Add-Failure 5 'handoff.txt missing or empty at the working-copy root - the claude invocation or its pipe failed'
} elseif ($handoffText -match '(?i)inventory-api\.md') {
    Add-Pass 5 'the reply cites the research file path (summary-plus-path contract)'
} else {
    Add-Failure 5 'the reply never cites inventory-api.md - the Orchestrator gets a summary with no pointer to the deliverable'
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
