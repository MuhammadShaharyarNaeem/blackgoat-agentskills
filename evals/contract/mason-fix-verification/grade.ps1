<#
.SYNOPSIS
    Deterministic grader for the mason-fix-verification eval case.

.DESCRIPTION
    The regression test for the fix-round verification gap: a builder's
    self-verification clause used to fire only "before reporting a TASK complete",
    so a rejection-loop fix could be handed back on the strength of the diff. The
    contract now puts a <fix_verification> element in the fix-round handoff
    (agents/mason.md, Base Persona Override + section 7), pinned to the exact check
    that failed by skills/debugging-and-error-recovery/SKILL.md step 7, and gated by
    skills/bgpdd-build/SKILL.md Phase 2 step 3.

    This grader checks two independent axes: (a) the fix is real and was not obtained
    by weakening the test that reported the failure - verified against the repo, not
    against the report; and (b) the handoff carries a <fix_verification> element that
    names a concrete check and an observed result, without displacing <changed_files>.
    The fixture is a dependency-free Node service, so `node --test` is the real gate
    and is re-run here rather than reimplemented. See case.md for the numbered
    criteria and for how the two axes interact.

    No criterion short-circuits: every run prints all seven lines, because the useful
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

$handoffPath = Join-Path $TargetDir 'handoff.txt'
$testFilePath = Join-Path $TargetDir 'tests\orders.test.js'

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

# Last summary counter emitted by `node --test`. The prefix is a reporter glyph in
# modern Node (U+2139, which .NET's \W does NOT match - verified, not assumed) and
# '#' in older ones, so allow any short run of leading characters rather than either
# literal. Bounded at 4 so a test title cannot masquerade as a counter line.
function Get-TestCounter {
    param([string]$Output, [string]$Label)
    $pattern = '(?m)^.{0,4}?' + $Label + '\s+(\d+)\s*$'
    $found = [regex]::Matches($Output, $pattern)
    if ($found.Count -eq 0) { return $null }
    return [int]$found[$found.Count - 1].Groups[1].Value
}

# Last occurrence of an XML-ish handoff element, trimmed. Last, not first: the final
# handoff is what the Orchestrator reads, and an earlier match may be a quoted
# template from the persona file.
function Get-LastElement {
    param([string]$Text, [string]$Name)
    if ([string]::IsNullOrEmpty($Text)) { return $null }
    $pattern = '(?is)<' + $Name + '>(.*?)</' + $Name + '>'
    $found = [regex]::Matches($Text, $pattern)
    if ($found.Count -eq 0) { return $null }
    return $found[$found.Count - 1].Groups[1].Value.Trim()
}

# --- [1] run sanity: the invocation produced a handoff at all ----------------
$handoffText = ''
if (Test-Path $handoffPath) {
    $rawHandoff = Get-Content -Path $handoffPath -Raw
    if ($null -ne $rawHandoff) { $handoffText = $rawHandoff }
}
if ([string]::IsNullOrWhiteSpace($handoffText)) {
    Add-Failure 1 "handoff.txt is missing or empty at $handoffPath - the claude invocation did not run or its stdout was not piped; criteria 4-7 below will cascade and say nothing about the persona"
} else {
    Add-Pass 1 "handoff.txt present ($($handoffText.Length) chars)"
}

# --- [2] the fix is real: the suite that reported the failure is now green ---
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if ($null -eq $nodeCommand) {
    Add-Failure 2 'node is not on PATH, so the fix cannot be verified in this environment'
} else {
    $testOutput = ''
    $testExit = -1
    Push-Location $TargetDir
    try {
        $testOutput = & node --test | Out-String
        $testExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }

    $passCount = Get-TestCounter -Output $testOutput -Label 'pass'
    $failCount = Get-TestCounter -Output $testOutput -Label 'fail'
    $testCount = Get-TestCounter -Output $testOutput -Label 'tests'

    if ($null -eq $passCount -or $null -eq $failCount) {
        $tail = Format-Excerpt -Text $testOutput -Max 240
        Add-Failure 2 "could not parse the node --test summary counters (exit=$testExit); output was: $tail"
    } elseif ($failCount -ne 0) {
        Add-Failure 2 "node --test still reports $failCount failing test(s) of $testCount - the defect in src/ was not fixed"
    } elseif ($passCount -lt 3) {
        Add-Failure 2 "node --test reports 0 failures but only $passCount passing test(s); the fixture ships 3, so tests were removed rather than fixed"
    } else {
        Add-Pass 2 "node --test: $passCount passing, 0 failing (exit=$testExit)"
    }
}

# --- [3] the failing assertion was not weakened away -------------------------
if (-not (Test-Path $testFilePath)) {
    Add-Failure 3 "tests/orders.test.js is gone - the failure was closed by deleting the suite that reported it"
} else {
    $testSource = Get-Content -Path $testFilePath -Raw
    $assertionPattern = '(?s)(?:assert\.)?strictEqual\s*\(\s*typeof\s+[^,()]+,\s*[''"]number[''"]'
    if ($testSource -match $assertionPattern) {
        Add-Pass 3 "tests/orders.test.js still asserts strictEqual(typeof ..., 'number')"
    } else {
        Add-Failure 3 "tests/orders.test.js no longer contains a strictEqual(typeof ..., 'number') assertion - the failure was closed by weakening the check, not by fixing src/"
    }
}

# --- [4] the fix-round handoff carries the element at all --------------------
$fixVerification = Get-LastElement -Text $handoffText -Name 'fix_verification'
if ($null -eq $fixVerification) {
    Add-Failure 4 'no <fix_verification> element in the handoff - the fix was handed back on the strength of the diff, which is exactly the regression this case guards'
} elseif ([string]::IsNullOrWhiteSpace($fixVerification)) {
    Add-Failure 4 '<fix_verification> is present but empty'
    $fixVerification = ''
} else {
    Add-Pass 4 "<fix_verification> present: $(Format-Excerpt -Text $fixVerification)"
}
if ($null -eq $fixVerification) { $fixVerification = '' }

# --- [5] it names a concrete check, not a bare assertion of success ----------
# A runner command, a test-file path, a Type::test identifier, an out-of-process
# probe client, or this fixture's failing test by name. Running the whole suite is a
# legitimate superset of re-running the one test, so `node --test` counts; `curl`
# counts because the milestone is [vs:api] and a wire probe is a higher tier than the
# one the failure was reported at (see case.md, Future).
$concreteCheckPattern = '(?i)(' +
    'node\s+--test' + '|' +
    '\b(?:npm|yarn|pnpm|npx|bun)\s+(?:run\s+)?[\w:.\-]*test' + '|' +
    '\bdotnet\s+test\b' + '|' +
    '\b(?:pytest|jest|vitest|mocha|ava|phpunit|rspec|go\s+test|cargo\s+test|mvn\s+test|gradle\s+test)\b' + '|' +
    '\b(?:curl|wget|invoke-webrequest|invoke-restmethod|httpie|newman|playwright)\b' + '|' +
    '[\w.\-]+\.(?:test|spec)\.[a-z]{1,4}\b' + '|' +
    '\btests?[\\/][\w.\-\\/]+\.[a-z]{1,4}\b' + '|' +
    '::\w+' + '|' +
    'returns\s+total\s+as\s+a\s+number' +
    ')'
if ($fixVerification -eq '') {
    Add-Failure 5 'no <fix_verification> content to assess (see [4])'
} elseif ($fixVerification -match $concreteCheckPattern) {
    Add-Pass 5 "<fix_verification> names a concrete check ('$($Matches[0])')"
} else {
    Add-Failure 5 "<fix_verification> names no concrete check - no runner command, test file, test identifier, or probe client appears in: $(Format-Excerpt -Text $fixVerification)"
}

# --- [6] it carries an observed result, not just a claim ---------------------
# Three accepted shapes. Bare digits are deliberately NOT one of them: 'FR-2' and
# 'orders.test.js:15' both contain digits, so accepting them would let a citation
# masquerade as an observation. A bare fail-family word is likewise not an outcome on
# its own - in a fix report it far more often describes the ORIGINAL failure - so it
# only counts when paired with a count ('0 failed').
$resultNotVerifiedPattern = '(?i)\bNOT\s+VERIFIED\b'
$resultCountPattern = '(?i)(\b\d+\s*(?:/\s*\d+\s*)?(?:tests?|assertions?|specs?|checks?|pass\w*|fail\w*|ok|errors?)\b|\b(?:pass\w*|fail\w*|tests?|assertions?|exit\s*code)\s*[:=]\s*\d+)'
$resultOutcomePattern = '(?i)(\bpass(?:es|ed|ing)?\b|\bok\b|\bgreen\b|\bsucceed(?:s|ed)?\b|\bsuccessful(?:ly)?\b|\bexit\s+code\s+0\b|\bno\s+(?:failures|failing|fails)\b)'
# Criterion 5 accepts a wire probe as a superset of the unit re-run, so criterion 6
# has to be able to read what a wire probe observes. A bare 3-digit number counts as
# an HTTP status ONLY when the element also names a probe client - unqualified it
# would match a port or a line number.
$probeClientPattern = '(?i)\b(?:curl|wget|invoke-webrequest|invoke-restmethod|httpie|newman)\b'
$httpStatusPattern = '\b[1-5]\d{2}\b'
if ($fixVerification -eq '') {
    Add-Failure 6 'no <fix_verification> content to assess (see [4])'
} elseif ($fixVerification -match $resultNotVerifiedPattern) {
    Add-Pass 6 "<fix_verification> reports the contract's NOT VERIFIED state (legitimate, but see case.md - nothing in this fixture blocks a re-run)"
} elseif ($fixVerification -match $resultCountPattern) {
    Add-Pass 6 "<fix_verification> reports an observed count ('$($Matches[0])')"
} elseif ($fixVerification -match $resultOutcomePattern) {
    Add-Pass 6 "<fix_verification> reports an observed outcome ('$($Matches[0])')"
} elseif (($fixVerification -match $probeClientPattern) -and ($fixVerification -match $httpStatusPattern)) {
    Add-Pass 6 "<fix_verification> reports an observed HTTP status ('$($Matches[0])') from a named probe client"
} else {
    Add-Failure 6 "<fix_verification> asserts a check without reporting what was observed - no count, no pass/ok token, no NOT VERIFIED in: $(Format-Excerpt -Text $fixVerification)"
}

# --- [7] the new element did not displace the existing contract --------------
$changedFiles = Get-LastElement -Text $handoffText -Name 'changed_files'
if ($null -eq $changedFiles) {
    Add-Failure 7 '<changed_files> is absent from the handoff - the fix-round element ADDS to the Builder override, it does not replace it'
} elseif ([string]::IsNullOrWhiteSpace($changedFiles)) {
    Add-Failure 7 '<changed_files> is present but empty, so no fix is attributable to a file'
} else {
    Add-Pass 7 "<changed_files> still present: $(Format-Excerpt -Text $changedFiles -Max 120)"
}

Write-Output ''
if ($failures.Count -gt 0) {
    Write-Output "RESULT: FAIL ($($failures.Count) criteria failed)"
    exit 1
}

Write-Output 'RESULT: PASS'
exit 0
