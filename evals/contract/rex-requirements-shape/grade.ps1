<#
.SYNOPSIS
    Deterministic grader for the rex-requirements-shape eval case.

.DESCRIPTION
    Checks the structural shape of the requirements.md Rex produced against a frozen
    fixture. Does not judge content quality — only the machine-parseable shape that
    Alex and the pipeline-tools coverage gate depend on. See case.md for the numbered
    criteria this implements and why each one matters.

.PARAMETER TargetDir
    Root of the temp working copy the eval run executed in (the parent of `.docs/`).

.OUTPUTS
    Prints "PASSED: [n] ..." / "FAILED: [n] ..." lines for each criterion, then a final
    RESULT line. Exit 0 = all criteria passed. Exit 1 = at least one criterion failed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = 'Stop'

$requirementsPath = Join-Path $TargetDir '.docs\csv-export\requirements.md'
$failures = New-Object System.Collections.Generic.List[string]

if (-not (Test-Path $requirementsPath)) {
    Write-Output "FAILED: [1] requirements.md does not exist at $requirementsPath"
    Write-Output ''
    Write-Output 'RESULT: FAIL (1 criteria failed)'
    exit 1
}
Write-Output '[1] PASSED: requirements.md exists'

$content = Get-Content -Path $requirementsPath -Raw

# [2] Vision section present
if ($content -match '(?m)^##\s+Vision\s*$') {
    Write-Output '[2] PASSED: ## Vision section present'
} else {
    $failures.Add('2: missing ## Vision section')
    Write-Output '[2] FAILED: missing ## Vision section'
}

# [3] MoSCoW Must Have structure present
if ($content -match '(?m)^##\s+Functional Requirements' -and $content -match '(?m)^###\s+Must Have') {
    Write-Output '[3] PASSED: Functional Requirements / Must Have headings present'
} else {
    $failures.Add('3: missing Functional Requirements / Must Have headings')
    Write-Output '[3] FAILED: missing Functional Requirements / Must Have headings'
}

# [4] FR IDs continuously numbered starting at FR-1
$frMatches = [regex]::Matches($content, '\*\*FR-(\d+)\*\*')
$frNumbers = @()
foreach ($m in $frMatches) { $frNumbers += [int]$m.Groups[1].Value }
$frNumbersUnique = @($frNumbers | Sort-Object -Unique)

$isContinuous = $false
if ($frNumbersUnique.Count -gt 0) {
    $expected = @(1..($frNumbersUnique.Count))
    $diff = Compare-Object -ReferenceObject $expected -DifferenceObject $frNumbersUnique
    if (-not $diff) { $isContinuous = $true }
}

if ($isContinuous) {
    Write-Output "[4] PASSED: FR IDs continuously numbered starting at FR-1 (found: $($frNumbersUnique -join ', '))"
} else {
    $found = $frNumbersUnique -join ', '
    $failures.Add("4: FR IDs not continuous from FR-1 (found: $found)")
    Write-Output "[4] FAILED: FR IDs not continuous from FR-1 (found: $found)"
}

# [5] At least one tier-tagged NFR
if ($content -match '-\s*\*\*NFR-\d+\*\*\s*\((Must|Should|Could)[^)]*\)') {
    Write-Output '[5] PASSED: at least one tier-tagged NFR present'
} else {
    $failures.Add("5: no tier-tagged NFR (- **NFR-n** (Must|Should|Could) ...) found")
    Write-Output '[5] FAILED: no tier-tagged NFR (- **NFR-n** (Must|Should|Could) ...) found'
}

# [6] Open Questions section present
if ($content -match '(?m)^##\s+Open Questions\s*$') {
    Write-Output '[6] PASSED: ## Open Questions section present'
} else {
    $failures.Add('6: missing ## Open Questions section')
    Write-Output '[6] FAILED: missing ## Open Questions section'
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
