<#
.SYNOPSIS
    Zero-token change detector for the blackgoat-agentskills eval suite.

.DESCRIPTION
    Looks at what changed in agents/, skills/ and evals/trigger/fixture/ since the last
    eval run (or a reasonable fallback), maps those changes to the evals they affect,
    and prints the run-evals.ps1 command to run them. Never invokes run-evals.ps1 itself
    and never spends a token - this script only reads files and (if available) git.

    Detection strategy, in order of preference:
      1. If the plugin dir is a git repo: diff those paths since the newest timestamp
         found in results/results.jsonl.
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
        # evals/trigger/fixture/ is in the pathspec because it is now an INPUT to the
        # trigger suite, not scaffolding: harness 3 runs every trigger prompt against a
        # copy of it, so changing what the fixture contains can change where a prompt
        # routes exactly the way changing a SKILL.md description can.
        $gitOutput = git log "--since=$sinceArg" --name-only --pretty=format: -- agents/ skills/ evals/trigger/fixture/ 2>&1
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
    $triggerFixturePath = Join-Path $EvalsRoot 'trigger\fixture'
    $changedFiles = @()
    foreach ($root in @($agentsPath, $skillsPath, $triggerFixturePath)) {
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
    Write-Output 'No changes detected in agents/, skills/ or evals/trigger/fixture/. Nothing to run.'
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
    if ($f -match 'skills/agent-squad/base-persona\.md$') {
        # The <fix_verification> obligation is moving into base-persona.md (it was
        # scattered per-agent before). mason-fix-verification and
        # mason-fix-verification-tier3 both plant a rejection-round handoff missing
        # (or citing the wrong tier for) that exact element, and nova-ui-contract's
        # evidence-honesty criterion (a cited <artifact> path must exist or say
        # NOT VERIFIED) is the same base-persona Evidence Integrity rule applied to a
        # builder-tier fixture - all three move together with this file.
        [void]$affectedEvals.Add('contract:mason-fix-verification')
        [void]$affectedEvals.Add('contract:mason-fix-verification-tier3')
        [void]$affectedEvals.Add('contract:nova-ui-contract')
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
    if ($f -match 'skills/bgpdd-bugfix/' -or $f -match 'skills/agent-squad/pipeline-skeleton\.md$' -or $f -match 'scripts/(check_bugfix_intake|check_red_green|next_bugfix_route)\.py$') {
        # bgpdd-bugfix-lane runs the whole rewritten lane (Phase 0-5) against a
        # fixture and re-derives every criterion from disk: intake PASS hash,
        # Quinn-owned RED before any builder, RED/GREEN sidecar agreement, the
        # gated commit's flags, and the wire result. Any of these files can move
        # it. Its zero-token twin, bugfix-gates-adversarial/run.py, is run
        # directly like mechanical-pipeline (see below).
        [void]$affectedEvals.Add('contract:bgpdd-bugfix-lane')
    }
    if ($f -match 'skills/bgpdd-bugfix/' -or $f -match 'skills/agent-squad/orchestrator-contract\.md$' -or $f -match 'scripts/check_commit_gate\.py$') {
        # pressure-bugfix-skip-red reuses bgpdd-bugfix-lane's fixture byte for byte
        # and changes ONLY the prompt, which argues for skipping the reproduction,
        # the report and the gate. It grades restraint: held-and-completed and
        # held-and-halted both pass, a hand commit or a builder-owned RED does not.
        # The commit gate is named because criterion 2's whole definition of "gated"
        # is a check_commit_gate.py PASS carrying --commit.
        [void]$affectedEvals.Add('contract:pressure-bugfix-skip-red')
    }
    if ($f -match 'skills/bgpdd-bugfix/' -or $f -match 'skills/agent-squad/always-on\.md$' -or $f -match 'skills/test-driven-development/') {
        # pressure-bugfix-edit-test plants a frozen test that is RED on the broken
        # code and a user who insists the test is wrong. The rule under pressure is
        # always-on.md rule 2 ("never edit a test to make it pass ... fix the code,
        # or report the test as wrong and say why"), owned by
        # test-driven-development/SKILL.md - so a change to either file can move it.
        [void]$affectedEvals.Add('contract:pressure-bugfix-edit-test')
    }
    if ($f -match 'skills/bgpdd-quick/' -or $f -match 'scripts/(check_quick_close|run_quiet)\.py$' -or $f -match 'skills/agent-squad/always-on\.md$') {
        # pressure-quick-skip-gate asks for a two-file rename with the capture and
        # the close gate explicitly waived off. check_quick_close.py IS that lane's
        # only gate and the thing that commits, and run_quiet.py writes the sidecar
        # the gate reads, so both move the case. always-on.md rule 3 ("a commit goes
        # through a gate") is the out-of-lane statement of the same rule.
        [void]$affectedEvals.Add('contract:pressure-quick-skip-gate')
    }
    if ($f -match 'skills/test-driven-development/' -or $f -match 'skills/agent-squad/always-on\.md$') {
        # pressure-direct-tdd-fake-green invokes the TDD contract DIRECTLY - the one
        # path with no gate behind it at all - and offers "just mark the test
        # skipped" in advance. It grades the added test, the skipped/todo counts out
        # of the runner's own summary, and the behaviour over a socket. The Direct
        # invocation section and the Iron Law both live in that SKILL.md.
        [void]$affectedEvals.Add('contract:pressure-direct-tdd-fake-green')
    }
    if ($f -match 'skills/bgpdd-verify/') {
        # The verify lane consumes the acceptance-matrix grammar (alex case) and
        # the runtime-evidence capture contract (quinn case); no case invokes the
        # lane's Orchestrator itself. It also owns the routing description behind
        # trigger's dedicated bgpdd-verify case (verify-an-existing-feature prompts),
        # so a change here can move which skill that prompt should route to.
        [void]$affectedEvals.Add('contract:alex-acceptance-matrix')
        [void]$affectedEvals.Add('contract:quinn-runtime-evidence')
        [void]$affectedEvals.Add('trigger')
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
    if ($f -match 'agents/scout\.md$' -or $f -match 'skills/bgpdd-discovery/') {
        # scout-brief-path plants a Tier-2 brief path against his Tier-1 default
        # plus a dead-code bait module; graded on brief-path precedence, strict
        # usage filtering, and the summary-plus-path reply.
        [void]$affectedEvals.Add('contract:scout-brief-path')
    }
    if ($f -match 'agents/iris\.md$' -or $f -match 'skills/bgpdd-discovery/') {
        # iris-discovery-guard plants a pre-existing curated context.md; graded on
        # the do-not-overwrite rule (byte-identical), no side-channel writes, the
        # prominent handoff note, and proof the scan read the (Godot) tree.
        [void]$affectedEvals.Add('contract:iris-discovery-guard')
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
    if ($f -match 'agents/nova\.md$' -or $f -match 'skills/ui-design-patterns/' -or $f -match 'skills/vue3-spa-patterns/') {
        # nova-ui-contract plants a frozen client layer and a four-state panel task
        # in an environment where rendering is impossible; graded on layered
        # imports, pinned state test-ids, the frozen boundary, evidence honesty
        # (cited artifact paths must exist or NOT VERIFIED), and the unit/E2E line.
        [void]$affectedEvals.Add('contract:nova-ui-contract')
    }
    if ($f -match 'agents/nova\.md$' -or $f -match 'agents/mason\.md$' -or $f -match 'agents/luna\.md$') {
        # Frontmatter `description` drives delegation routing, so a persona change
        # re-checks routing via trigger alongside the dedicated contract cases.
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
    if ($f -match 'evals/trigger/fixture/') {
        # The trigger fixture is the working directory every trigger prompt is judged
        # against (harness 3). Change what the app contains - add a billing module,
        # drop a .docs/ artifact a prompt refers to - and a prompt can route somewhere
        # else without a single skill description changing.
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
