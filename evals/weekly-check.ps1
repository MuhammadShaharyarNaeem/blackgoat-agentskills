<#
.SYNOPSIS
    Zero-token change detector for the blackgoat-agentskills eval suite.

.DESCRIPTION
    Looks at what changed in agents/ and skills/ since the last eval run (or a
    reasonable fallback), maps those changes to the evals they affect, and prints the
    run-evals.ps1 command to run them. Never invokes run-evals.ps1 itself and never
    spends a token - this script only reads files and (if available) git.

    Detection strategy, in order of preference:
      1. If the plugin dir is a git repo: diff agents/ and skills/ since the newest
         timestamp found in results/results.jsonl.
      2. If it is a git repo but results.jsonl has no entries yet: diff since 7 days ago.
      3. If it is not a git repo: fall back to file LastWriteTime, same two windows.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$EvalsRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PluginRoot = Split-Path -Parent $EvalsRoot
$ResultsPath = Join-Path $EvalsRoot 'results\results.jsonl'
$DefaultRuns = 5

function Get-LastEvalTimestamp {
    if (-not (Test-Path $ResultsPath)) { return $null }
    $lines = Get-Content -Path $ResultsPath | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    if (-not $lines) { return $null }

    $latest = $null
    foreach ($line in $lines) {
        try {
            $record = $line | ConvertFrom-Json
            $ts = [datetime]$record.timestamp
            if (-not $latest -or $ts -gt $latest) { $latest = $ts }
        } catch {
            continue
        }
    }
    return $latest
}

function Test-IsGitRepo {
    param([string]$Path)
    $isRepo = $false
    Push-Location $Path
    try {
        $null = git rev-parse --is-inside-work-tree 2>&1
        $isRepo = ($LASTEXITCODE -eq 0)
    } catch {
        $isRepo = $false
    } finally {
        Pop-Location
    }
    return $isRepo
}

$lastEvalTime = Get-LastEvalTimestamp
$isGitRepo = Test-IsGitRepo -Path $PluginRoot

$changedFiles = @()
$detectionMethod = $null

if ($isGitRepo) {
    Push-Location $PluginRoot
    try {
        if ($lastEvalTime) {
            $sinceArg = $lastEvalTime.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
            $detectionMethod = "git diff since last eval run ($sinceArg)"
        } else {
            $sinceArg = '7 days ago'
            $detectionMethod = 'git diff since 7 days ago (no prior results.jsonl entries)'
        }
        $gitOutput = git log "--since=$sinceArg" --name-only --pretty=format: -- agents/ skills/ 2>&1
        $changedFiles = @($gitOutput | Where-Object { $_ -and $_.Trim() -ne '' } | Sort-Object -Unique)
    } finally {
        Pop-Location
    }
} else {
    $cutoff = $lastEvalTime
    if (-not $cutoff) { $cutoff = (Get-Date).AddDays(-7) }
    $detectionMethod = "file LastWriteTime since $($cutoff.ToString('u')) (not a git repo)"

    $agentsPath = Join-Path $PluginRoot 'agents'
    $skillsPath = Join-Path $PluginRoot 'skills'
    $changedFiles = @()
    foreach ($root in @($agentsPath, $skillsPath)) {
        if (Test-Path $root) {
            $changedFiles += Get-ChildItem -Path $root -Recurse -File |
                Where-Object { $_.LastWriteTime -gt $cutoff } |
                ForEach-Object { $_.FullName.Substring($PluginRoot.Length + 1).Replace('\', '/') }
        }
    }
}

Write-Output '=== Weekly Change Check ==='
Write-Output "Detection method: $detectionMethod"
Write-Output ''

if (-not $changedFiles -or $changedFiles.Count -eq 0) {
    Write-Output 'No changes detected in agents/ or skills/. Nothing to run.'
    exit 0
}

Write-Output 'Changed files:'
foreach ($f in $changedFiles) { Write-Output "  - $f" }
Write-Output ''

$affectedEvals = New-Object System.Collections.Generic.HashSet[string]
# Mechanical (non-LLM, zero-token) checks. Tracked separately from $affectedEvals
# because run-evals.ps1 only dispatches 'trigger' and 'contract:*' suites.
$mechanicalChecks = New-Object System.Collections.Generic.HashSet[string]

foreach ($f in $changedFiles) {
    if ($f -match 'agents/rex\.md$') {
        [void]$affectedEvals.Add('contract:rex-requirements-shape')
    }
    if ($f -match 'agents/alex\.md$' -or $f -match 'skills/planning-and-task-breakdown/') {
        # Alex owns TWO plan-time artifacts: plan.md (coverage gate) and
        # acceptance-matrix.md (the feature-scoped walkthrough). Both formats are
        # owned by planning-and-task-breakdown, so a change to either file fires both.
        [void]$affectedEvals.Add('contract:alex-plan-coverage')
        [void]$affectedEvals.Add('contract:alex-acceptance-matrix')
    }
    if ($f -match 'agents/quinn\.md$' -or $f -match 'skills/test-driven-development/' -or $f -match 'skills/debugging-and-error-recovery/' -or $f -match 'skills/runtime-evidence/') {
        [void]$affectedEvals.Add('contract:quinn-test-report-shape')
        [void]$affectedEvals.Add('contract:quinn-runtime-evidence')
    }
    if ($f -match 'skills/runtime-evidence/') {
        # The contract quinn-runtime-evidence exists to regression-test: an
        # in-process observation can fail a wire claim but never pass one. Its
        # SKILL.md description also drives routing, hence trigger.
        [void]$affectedEvals.Add('contract:quinn-runtime-evidence')
        [void]$affectedEvals.Add('trigger')
    }
    if ($f -match 'skills/dotnet-backend-patterns/') {
        # That case encodes this stack's tier rule: the .NET contract mandates
        # zero-mock integration tests against a real DB, which is exactly the
        # in-process tier that stood in for a wire observation in the 2026-08
        # incident. It also names the envelope keys (isSuccess, notifications,
        # statusCode) the case's gate invocation requires.
        [void]$affectedEvals.Add('contract:quinn-runtime-evidence')
    }
    if ($f -match 'agents/mason\.md$' -or $f -match 'skills/debugging-and-error-recovery/' -or $f -match 'skills/runtime-evidence/') {
        # mason-fix-verification-tier3 measures the *which* in
        # debugging-and-error-recovery step 7: VERIFY runs at the tier the failure was
        # reported at. It pairs Mason's fix-round <fix_verification> contract with the
        # tier ladder, so a change to any of the three files can move the answer.
        [void]$affectedEvals.Add('contract:mason-fix-verification-tier3')
    }
    if ($f -match 'skills/bgpdd-build/') {
        # The build pipeline's contract surfaces: the fix-round <fix_verification>
        # precondition (Phase 2 step 3), the Runtime Evidence Gate, and Quinn's
        # ledger/report grammars it briefs. mechanical-pipeline (zero-token,
        # surfaced separately below via pipeline-tools) covers its gate composition.
        [void]$affectedEvals.Add('contract:mason-fix-verification')
        [void]$affectedEvals.Add('contract:mason-fix-verification-tier3')
        [void]$affectedEvals.Add('contract:quinn-runtime-evidence')
        [void]$affectedEvals.Add('contract:quinn-test-report-shape')
    }
    if ($f -match 'skills/bgpdd-verify/') {
        # The verify lane consumes the acceptance-matrix grammar (alex case) and
        # the runtime-evidence capture contract (quinn case); no case invokes the
        # lane's Orchestrator itself.
        [void]$affectedEvals.Add('contract:alex-acceptance-matrix')
        [void]$affectedEvals.Add('contract:quinn-runtime-evidence')
    }
    if ($f -match 'agents/echo\.md$' -or $f -match 'agents/iris\.md$' -or $f -match 'agents/scout\.md$' -or $f -match 'skills/bgpdd-discovery/') {
        [void]$affectedEvals.Add('contract:echo-qa-discovery-shape')
    }
    if ($f -match 'agents/vera\.md$' -or $f -match 'skills/shipping-and-launch/' -or $f -match 'skills/bgpdd-shipping/') {
        [void]$affectedEvals.Add('contract:vera-verification-shape')
    }
    if ($f -match 'agents/dep\.md$' -or $f -match 'agents/cipher\.md$' -or $f -match 'skills/shipping-and-launch/' -or $f -match 'skills/cloud-deploy-patterns/' -or $f -match 'skills/bgpdd-shipping/') {
        [void]$affectedEvals.Add('contract:dep-ship-decision-shape')
    }
    if ($f -match 'agents/aria\.md$' -or $f -match 'skills/blackgoat-research/' -or $f -match 'skills/pipeline-tools/scripts/check_coverage\.py$') {
        # aria-supersession-writeback plants a research finding that falsifies an FR;
        # the graded obligations are the register row + in-place requirements
        # annotation, gated by check_coverage.py design mode.
        [void]$affectedEvals.Add('contract:aria-supersession-writeback')
    }
    if ($f -match 'agents/forge\.md$' -or $f -match 'agents/max\.md$' -or $f -match 'skills/agent-orchestration-improve-agent/' -or $f -match 'CLAUDE\.md$') {
        # forge-blackgoat-carveout plants an approved surgery plan whose second item
        # edits agents/blackgoat.md; the carve-out (repo convention #7) must hold.
        [void]$affectedEvals.Add('contract:forge-blackgoat-carveout')
    }
    if ($f -match 'agents/luna\.md$' -or $f -match 'skills/code-review-and-quality/') {
        # luna-verdict-arithmetic plants an IDOR + a swallowed rejection behind a
        # green suite; graded on finding both and on the verdict being arithmetic
        # over the findings (Request Changes, never approve-with-notes).
        # luna-clean-approve is its mirror: the same fixture genuinely fixed, where
        # the correct verdict is Approve - the pair only means something together
        # (one side alone cannot distinguish judgement from bias).
        [void]$affectedEvals.Add('contract:luna-verdict-arithmetic')
        [void]$affectedEvals.Add('contract:luna-clean-approve')
    }
    if ($f -match 'agents/cipher\.md$' -or $f -match 'skills/security-and-hardening/' -or $f -match 'skills/pipeline-tools/scripts/check_agent_report\.py$') {
        # cipher-security-report plants a hardcoded sk_live signing secret and a
        # wildcard CORS grant behind a clean-looking service; graded on evidenced
        # check lines, both findings, and the verdict being arithmetic (Fail).
        [void]$affectedEvals.Add('contract:cipher-security-report')
    }
    if ($f -match 'agents/max\.md$' -or $f -match 'skills/code-simplification/') {
        # max-behavior-preservation plants a genuine simplification beside a
        # load-bearing 'redundancy'; graded on a runtime value probe, not a grep.
        [void]$affectedEvals.Add('contract:max-behavior-preservation')
    }
    if ($f -match 'agents/nova\.md$' -or $f -match 'agents/mason\.md$' -or $f -match 'agents/luna\.md$') {
        # None of the three builders/reviewers has a dedicated contract eval: no
        # suite here invokes them, because grading produced CODE deterministically
        # is a different problem from grading a produced DOCUMENT's shape, which is
        # all this suite's graders do. Their frontmatter `description` does drive
        # delegation routing, so a change at least re-checks that via trigger.
        # This is a stopgap, not coverage: read a green trigger run as "routing still
        # works", never as "the builder/reviewer still behaves".
        [void]$affectedEvals.Add('trigger')
    }
    if ($f -match 'skills/bgpdd-learn/') {
        [void]$affectedEvals.Add('trigger')
    }
    if ($f -match 'skills/pipeline-tools/scripts/') {
        # pipeline-tools has no LLM contract eval, but it does have a mechanical
        # one: evals/contract/mechanical-pipeline/run.py drives next_milestone,
        # update_state, check_commit_gate and run_quiet end-to-end over a real
        # temp git repo. It is not dispatchable as 'contract:mechanical-pipeline'
        # (run-evals.ps1 discovers contract suites by case.md + grade.ps1, which
        # that dir has neither of), so surface it as a direct command instead.
        # Routing surface is covered separately by the SKILL.md rule below.
        [void]$mechanicalChecks.Add('python evals/contract/mechanical-pipeline/run.py')
        # Every script carrying a --self-test. check_dependency_tables.py is
        # deliberately absent: it has no --self-test flag (it takes a positional
        # dir) and exits 2 if handed one, so it gets its own line below.
        # $LASTEXITCODE, not $? - PS 5.1 sets $? false on any native stderr write,
        # and unittest always reports to stderr even when it passes.
        [void]$mechanicalChecks.Add("@('check_acceptance_suite','check_agent_report','check_blockers','check_commit_gate','check_coverage','check_runtime_evidence','check_ship_decision','next_milestone','update_state','run_quiet') | ForEach-Object { python skills/pipeline-tools/scripts/`$_.py --self-test *> `$null; `"`$_ -> exit `$LASTEXITCODE`" }")
        [void]$mechanicalChecks.Add('python skills/pipeline-tools/scripts/check_dependency_tables.py skills')
    }
    if ($f -match 'SKILL\.md$') {
        # Any SKILL.md's frontmatter `description` is what drives skill routing.
        [void]$affectedEvals.Add('trigger')
    }
}

if ($mechanicalChecks.Count -gt 0) {
    Write-Output 'Mechanical checks (no tokens - run these first):'
    foreach ($m in $mechanicalChecks) { Write-Output "  $m" }
    Write-Output ''
}

if ($affectedEvals.Count -eq 0) {
    if ($mechanicalChecks.Count -gt 0) {
        Write-Output 'No LLM evals flagged - the changes are mechanical only. Run the checks above.'
    } else {
        Write-Output 'Changed files did not match any known eval mapping. No evals flagged - review manually if that seems wrong.'
    }
    exit 0
}

Write-Output 'Affected evals:'
foreach ($e in $affectedEvals) { Write-Output "  - $e" }
Write-Output ''

$contractCount = @($affectedEvals | Where-Object { $_ -like 'contract:*' }).Count
$triggerFlagged = $affectedEvals.Contains('trigger')

$estRuns = ($contractCount * $DefaultRuns)
if ($triggerFlagged) {
    $triggerLinesPath = Join-Path $EvalsRoot 'trigger\cases.jsonl'
    $triggerLineCount = 0
    if (Test-Path $triggerLinesPath) {
        $triggerLineCount = @(Get-Content -Path $triggerLinesPath | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }).Count
    }
    $estRuns += ($triggerLineCount * $DefaultRuns)
}

Write-Output "Estimated runs (at -Runs $DefaultRuns): ~$estRuns"
Write-Output 'Estimated cost: rough only - run-evals.ps1 without -Confirm for a live dry-run estimate.'
Write-Output ''

$suiteArg = 'all'
if ($contractCount -gt 0 -and -not $triggerFlagged) { $suiteArg = 'contract' }
if ($triggerFlagged -and $contractCount -eq 0) { $suiteArg = 'trigger' }

Write-Output 'To actually run these evals (spends tokens), first dry-run:'
Write-Output "  powershell -File `"$EvalsRoot\run-evals.ps1`" -Suite $suiteArg -Runs $DefaultRuns"
Write-Output 'Then, after reviewing the plan, approve with -Confirm:'
Write-Output "  powershell -File `"$EvalsRoot\run-evals.ps1`" -Suite $suiteArg -Runs $DefaultRuns -Confirm"
