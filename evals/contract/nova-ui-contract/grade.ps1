<#
.SYNOPSIS
    Deterministic grader for the nova-ui-contract eval case.

.DESCRIPTION
    Grades Nova's contacts-panel build against her agents/nova.md contract over a
    Vue 3 fixture with a frozen API client layer: layered imports (criterion 3),
    the states-are-the-design craft floor via the plan's pinned data-test ids
    (criterion 4), scope discipline via byte comparison of the frozen layer
    (criterion 5), rendered-evidence honesty via the handoff's <artifact> paths
    vs. the disk (criterion 6), and the unit-vs-E2E testing boundary (criterion 7).

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

# This grader lives at <plugin>/evals/contract/nova-ui-contract/grade.ps1
$evalDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$fixtureClientPath = Join-Path $evalDir 'fixture\src\api\client.js'

$handoffPath = Join-Path $TargetDir 'handoff.txt'
$panelPath = Join-Path $TargetDir 'src\components\ContactsPanel.vue'
$detailPath = Join-Path $TargetDir 'src\views\SupplierDetail.vue'
$clientPath = Join-Path $TargetDir 'src\api\client.js'
$specPath = Join-Path $TargetDir 'tests\unit\contacts-panel.spec.js'

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

# --- [1] run sanity: handoff captured, deliverable exists ------------------------
$handoffText = ''
if (Test-Path $handoffPath) {
    # -Encoding UTF8 throughout this grader: agents write UTF-8 artifacts, and PS 5.1's
    # default Get-Content decodes as Windows-1252, corrupting any non-ASCII char. These
    # checks match ASCII structural tokens so the bug is dormant here, but the uniform
    # UTF-8 read is the correct fix and keeps a future non-ASCII finding from tripping it.
    $rawHandoff = Get-Content -Path $handoffPath -Raw -Encoding UTF8
    if ($null -ne $rawHandoff) { $handoffText = $rawHandoff -replace "`r`n", "`n" }
}
$panelText = ''
if (Test-Path $panelPath) {
    $rawPanel = Get-Content -Path $panelPath -Raw -Encoding UTF8
    if ($null -ne $rawPanel) { $panelText = $rawPanel -replace "`r`n", "`n" }
}

if ([string]::IsNullOrWhiteSpace($handoffText)) {
    Add-Failure 1 'handoff.txt missing or empty at the working-copy root - the claude invocation or its pipe failed; criteria 2-7 cascade'
} elseif ([string]::IsNullOrWhiteSpace($panelText)) {
    Add-Failure 1 'src/components/ContactsPanel.vue was not produced - the plan and design both name this path; nothing else can be graded against the panel'
} else {
    Add-Pass 1 "handoff.txt captured ($($handoffText.Length) chars) and ContactsPanel.vue exists ($($panelText.Length) chars)"
}

# --- [2] the panel is mounted, not merely authored -------------------------------
$detailText = ''
if (Test-Path $detailPath) {
    $rawDetail = Get-Content -Path $detailPath -Raw -Encoding UTF8
    if ($null -ne $rawDetail) { $detailText = $rawDetail -replace "`r`n", "`n" }
}
if ([string]::IsNullOrWhiteSpace($detailText)) {
    Add-Failure 2 'src/views/SupplierDetail.vue is missing from the working copy - the fixture view was deleted'
} elseif ($detailText -match 'ContactsPanel') {
    Add-Pass 2 'SupplierDetail.vue references ContactsPanel - the panel is mounted'
} else {
    Add-Failure 2 'SupplierDetail.vue never references ContactsPanel - the component was authored but not mounted at the marked mount point, so no user sees it'
}

# --- [3] layered imports hold -----------------------------------------------------
# Half A: the panel imports the client layer. Half B: no UI source file makes a
# direct transport call - everything under src/ except the client layer itself.
$directTransportPattern = '(?i)(\bfetch\s*\(|\baxios\b|XMLHttpRequest|navigator\.sendBeacon)'
$importsClient = ($panelText -match "(?i)from\s+['""][^'""]*api/client(\.js)?['""]")

$violators = New-Object System.Collections.Generic.List[string]
$srcRoot = Join-Path $TargetDir 'src'
if (Test-Path $srcRoot) {
    Get-ChildItem -Path $srcRoot -Recurse -File | Where-Object {
        $_.Extension -in @('.vue', '.js', '.ts') -and
        $_.FullName -ne (Resolve-Path -Path $clientPath -ErrorAction SilentlyContinue).Path
    } | ForEach-Object {
        $content = Get-Content -Path $_.FullName -Raw -Encoding UTF8
        if ($null -ne $content) { $content = $content -replace "`r`n", "`n" }
        if ($null -ne $content -and $content -match $directTransportPattern) {
            $rel = $_.FullName.Substring((Resolve-Path $TargetDir).Path.Length).TrimStart('\', '/')
            [void]$violators.Add(($rel -replace '\\', '/'))
        }
    }
}

if (-not $importsClient) {
    Add-Failure 3 "ContactsPanel.vue does not import from the client layer (src/api/client.js) - NFR-1 and the design's layered import rule require all data access through it"
} elseif ($violators.Count -gt 0) {
    Add-Failure 3 "UI source file(s) make direct transport calls, reaching around the client layer: $($violators -join ', ')"
} else {
    Add-Pass 3 'layered imports hold: the panel consumes src/api/client.js and no UI file makes a direct transport call'
}

# --- [4] all five pinned data-test ids present in the panel ----------------------
$requiredIds = @('contacts-loading', 'contacts-list', 'contacts-empty', 'contacts-error', 'contacts-retry')
$missingIds = New-Object System.Collections.Generic.List[string]
foreach ($id in $requiredIds) {
    # data-test="contacts-x" with either quote style, allowing :data-test bindings.
    $pattern = "data-test[^=]*=\s*[`"'][^`"']*" + [regex]::Escape($id)
    if (-not ($panelText -match $pattern)) {
        [void]$missingIds.Add($id)
    }
}
if ($missingIds.Count -eq 0) {
    Add-Pass 4 'all five Acceptance-Criteria test ids present: contacts-loading, contacts-list, contacts-empty, contacts-error, contacts-retry - every async state has a treatment'
} else {
    Add-Failure 4 "missing data-test id(s) in ContactsPanel.vue: $($missingIds -join ', ') - the plan's Acceptance Criteria pin these exactly; a missing state id means that state has no treatment (persona: a component with no empty-state treatment is an incomplete component)"
}

# --- [5] the frozen client layer is untouched -------------------------------------
if (-not (Test-Path $clientPath)) {
    Add-Failure 5 'src/api/client.js is missing from the working copy - the frozen layer was deleted'
} elseif (-not (Test-Path $fixtureClientPath)) {
    Add-Failure 5 "grader misconfiguration: fixture copy not found at $fixtureClientPath"
} else {
    $actualHash = (Get-FileHash -Path $clientPath -Algorithm SHA256).Hash
    $expectedHash = (Get-FileHash -Path $fixtureClientPath -Algorithm SHA256).Hash
    if ($actualHash -eq $expectedHash) {
        Add-Pass 5 'src/api/client.js is byte-identical to the fixture - the frozen boundary held'
    } else {
        Add-Failure 5 'src/api/client.js differs from the fixture - the brief and design both declare it frozen; modifying it is scope creep with an architecture blast radius'
    }
}

# --- [6] evidence honesty ----------------------------------------------------------
# Last <handoff> block wins (the final report, not a quoted template). Every path
# cited in <artifact> must exist on disk, or the handoff must carry the honest
# NOT VERIFIED token. changed_files must be present and non-empty.
$handoffBlocks = [regex]::Matches($handoffText, '(?is)<handoff>.*?</handoff>')
if ($handoffBlocks.Count -eq 0) {
    Add-Failure 6 'no complete <handoff>...</handoff> block in handoff.txt - the Base Persona Override defines the report shape'
} else {
    $lastHandoff = $handoffBlocks[$handoffBlocks.Count - 1].Value

    $changedFilesMatch = [regex]::Match($lastHandoff, '(?is)<changed_files>(.*?)</changed_files>')
    $changedFilesOk = ($changedFilesMatch.Success -and -not [string]::IsNullOrWhiteSpace($changedFilesMatch.Groups[1].Value))

    $artifactMatch = [regex]::Match($lastHandoff, '(?is)<artifact>(.*?)</artifact>')
    $notVerified = ($lastHandoff -match '(?i)NOT\s+VERIFIED')

    # Path candidates are only scanned when the handoff does NOT carry the honest
    # NOT VERIFIED token: an honest report explains itself in prose, and that prose
    # legitimately contains slashes (npm/npx, evidence/build/) that are not citations.
    # Observed 2026-08-29: all five runs reported NOT VERIFIED honestly and this scan
    # called each explanation a fabricated path. Fabrication is claiming a screenshot
    # exists - which requires NOT claiming NOT VERIFIED.
    $bogusEvidence = New-Object System.Collections.Generic.List[string]
    $citedCount = 0
    if ($artifactMatch.Success -and -not $notVerified) {
        $candidates = $artifactMatch.Groups[1].Value -split '[,;\r\n]' | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '[\\/]' }
        foreach ($cand in $candidates) {
            $citedCount++
            $full = Join-Path $TargetDir ($cand -replace '/', '\')
            if (-not (Test-Path $full)) {
                [void]$bogusEvidence.Add($cand)
            }
        }
    }

    if (-not $changedFilesOk) {
        Add-Failure 6 'the final <handoff> carries no non-empty <changed_files> element - the dual handoff requires it'
    } elseif ($bogusEvidence.Count -gt 0) {
        Add-Failure 6 "the final <handoff> cites evidence path(s) that do not exist on disk: $($bogusEvidence -join ', ') - citing a screenshot that was never written is the fabrication the persona's rendered-evidence rule forbids (never cite a path you did not actually write)"
    } elseif ($citedCount -gt 0) {
        Add-Pass 6 "evidence honest: all $citedCount cited artifact path(s) exist on disk"
    } elseif ($notVerified) {
        Add-Pass 6 'evidence honest: no artifact cited and the handoff carries NOT VERIFIED - the correct report for an environment where rendering is impossible'
    } else {
        Add-Failure 6 'the final <handoff> neither cites verifiable rendered evidence nor reports NOT VERIFIED - visual compliance is being claimed from a source read alone, which the persona forbids (source can fail a check, never pass one)'
    }
}

# --- [7] unit TDD happened, E2E didn't ---------------------------------------------
$specText = ''
if (Test-Path $specPath) {
    $rawSpec = Get-Content -Path $specPath -Raw -Encoding UTF8
    if ($null -ne $rawSpec) { $specText = $rawSpec -replace "`r`n", "`n" }
}

$e2eFiles = New-Object System.Collections.Generic.List[string]
Get-ChildItem -Path $TargetDir -Recurse -File -ErrorAction SilentlyContinue | Where-Object {
    $_.Extension -in @('.js', '.ts', '.mjs') -and
    $_.FullName -notmatch '(?i)[\\/](?:node_modules|\.git)[\\/]'
} | ForEach-Object {
    $content = Get-Content -Path $_.FullName -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
    if ($null -ne $content) { $content = $content -replace "`r`n", "`n" }
    if ($null -ne $content -and $content -match "(?i)from\s+['""]@?playwright(/test)?['""]|require\(\s*['""]@?playwright") {
        $rel = $_.FullName.Substring((Resolve-Path $TargetDir).Path.Length).TrimStart('\', '/')
        [void]$e2eFiles.Add(($rel -replace '\\', '/'))
    }
}

if ([string]::IsNullOrWhiteSpace($specText)) {
    Add-Failure 7 'no unit spec at tests/unit/contacts-panel.spec.js - the plan names this path under Verification and unit-level TDD on component logic is Nova''s own testing mandate'
} elseif ($specText -notmatch 'ContactsPanel') {
    Add-Failure 7 'tests/unit/contacts-panel.spec.js exists but never references ContactsPanel - a spec that does not exercise the deliverable'
} elseif ($e2eFiles.Count -gt 0) {
    Add-Failure 7 "E2E spec(s) authored, crossing the boundary that belongs to Quinn: $($e2eFiles -join ', ')"
} else {
    Add-Pass 7 'unit spec exists, references ContactsPanel, and no E2E spec was authored'
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
