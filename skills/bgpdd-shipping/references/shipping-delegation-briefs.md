# bgpdd-shipping — Launch Squad Delegation Briefs (verbatim)

The prompt text for each Step 2 delegation, held verbatim. `SKILL.md` Step 2 mandates pasting the relevant block; the bulleted must-haves in the spine are the enforceable contract, and this file is the wording that satisfies them. Where the spine and this file disagree, the spine wins.

Every block below assumes you have already done what Step 1 requires: read `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md` in full and extracted the exact text of the checklist sections named in the agent's Assignment. `[Paste the exact checklist section text here.]` is an instruction to you, not text to send.

---

## Vera

*Stage 1.*

> "Execute the Code Quality, **Pre-Merge Local Runtime Smoke**, Performance, and Accessibility sections of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`) against the current codebase. [Paste the exact checklist section text here.] Run all tests, linters, and accessibility checks — and **start the application and probe it**, per the Runtime Smoke section and your `runtime-evidence` dependency: a built codebase is not a running one, and every claim about behavior a client, person, or device can observe needs an out-of-process capture cited by path. Start it from the environment manifest at `artifacts.environment_manifest` (inject the resolved path; `bgpdd-build` Phase 0 wrote it) — start commands, local base URLs, the repointing map and the forbidden hosts all come from there and none of them is yours to infer. If that artifact is `null` or absent, say so and report the affected checks `BLOCKED` rather than reconstructing the estate from the repo. Write your per-item report to `.docs/{project-name}/implementation/verification-report.md` per your persona's Verification Report contract, ending in the machine-read `**Verdict:**` line. Scope your report section and every capture's `Milestone:` field to exactly: `<the epic or feature name — inject the verbatim string, which is the same token Step 3 passes to check_runtime_evidence.py --milestone>`. Report back with a final pass/fail."

Plus the CRITICAL CIRCUIT BREAKER rule verbatim as worded in the Orchestrator Contract §2.

---

## Cipher

*Stage 2.*

> "Execute the Security section of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`) against the current codebase. [Paste the exact checklist section text here.] Scan for vulnerabilities, check CORS and headers, and verify auth routes. Append your audit round to `.docs/{project-name}/implementation/security-report.md` per your persona's Security Report contract, ending in the machine-read `**Verdict:**` line. Report back with a final pass/fail."

Plus the CRITICAL CIRCUIT BREAKER rule verbatim as worded in the Orchestrator Contract §2.

---

## Dep

*Stage 2.*

> "Execute the Infrastructure, Feature Flag Strategy, **Baseline Capture**, Staged Rollout, **Rollback Rehearsal**, and Monitoring and Observability sections of the `shipping-and-launch` skill (`{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`). [Paste the exact checklist section text here.] Verify production environment variables and define the Staged Rollout sequence. **Capture the rollout baseline** per Baseline Capture — three metrics read from the project's monitoring source into `.docs/{project-name}/implementation/evidence/baseline/`, listed under a `## Baseline` heading in the ship decision — and **rehearse the rollback** per Rollback Rehearsal: perform the timed revert-plus-health-check on a non-production environment, capture it with `run_quiet.py --capture` under `.docs/{project-name}/implementation/evidence/rollback/`, and record the `Time to Rollback:` line in the grammar that section defines. Neither is optional and neither is satisfiable by prose: Step 3's exit ticket reads both mechanically. **Refresh/re-verify** `.docs/{project-name}/implementation/ship-decision.md` for final launch — build Phase 5 wrote the prep GO that was this pipeline's Step 0.4 entry ticket; your refreshed GO is the Step 3 exit ticket. Either rewrite the file or append a new dated verdict section; the gate reads the LAST verdict-bearing section, so both converge. What it rejects is one section stating both GO and NO-GO. Compile the Emergency Rollback Plan and your final `GO`/`NO-GO` verdict into that same path. Report back with your findings."

Plus the CRITICAL CIRCUIT BREAKER rule verbatim as worded in the Orchestrator Contract §2.

---

## Fresh Quinn

*Step 3 acceptance re-execution.*

Not a continuation of any build-phase Quinn. Her brief carries:

- the resolved `artifacts.acceptance_matrix` path;
- the results path `.docs/{project-name}/implementation/acceptance-results.md`, and that she **appends** a new `## bgpdd-shipping — [date]` section rather than overwriting — build's section is the baseline a regression is read against;
- the resolved `artifacts.environment_manifest` — the bring-up facts are not hers to infer, the same rule as Vera's brief;
- that every step's evidence is a fresh capture written via `{PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture` under `.docs/{project-name}/implementation/evidence/runtime/`, cited inline in the result line's detail field per `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`;
- the CRITICAL CIRCUIT BREAKER rule verbatim.

---

## Fresh Dep

*Step 5.5 post-deploy verification.*

Not the Stage 2 Dep. His brief carries:

- the environment the user just named, and that every check runs **against that deployed environment**, never a local checkout;
- the exact text of the `Post-Launch Verification` block from `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md`, pasted, plus its **Owner and artifact** paragraph — that paragraph carries the report path, the check-line grammar and the capture rule, and is the contract, not a summary of one;
- the `## Baseline` lines from `.docs/{project-name}/implementation/ship-decision.md`, verbatim, so item 6 compares against the recorded readings rather than against a fresh impression of normal;
- the report destination `.docs/{project-name}/implementation/post-deploy-report.md`, and the milestone token `post-deploy`, which every capture's `Milestone:` field must carry;
- the CRITICAL CIRCUIT BREAKER rule verbatim, as worded in the Orchestrator Contract §2.

---

## Forge

*Step 7 improvement run.*

Brief him as the SINGLE end-of-epic improvement run — the per-phase pipelines no longer invoke Forge; their evidence has accumulated for him. Instruct him to read, in this order:

- (a) the **mechanical records FIRST** — the run-log summary (`summarize_run.py --run-log .docs/{project-name}/implementation/run-log.jsonl --ledger .docs/{project-name}/implementation/gates.jsonl`) and the gate ledger itself, because they record what actually ran and what it cost without passing through anyone's memory;
- (b) then `.docs/{project-name}/implementation/game-tape.md` — the per-phase evidence checkpoints from `bgpdd-plan`, `bgpdd-build`, and this shipping run, which is where the material the records cannot hold lives;
- (c) the durable reports — `.docs/{project-name}/implementation/review-report.md` and `test-report.md`;
- (d) optionally, the session transcripts listed in the game tape, under the `/bgpdd-learn` filtered-read rule: he must NEVER full-read a transcript file (transcripts embed every tool result) — grep targeted slices only (user messages, correction phrases, `<handoff>` blocks, error/circuit-breaker patterns, skill invocations), then read just those line ranges.

Then: using those same session transcript paths and the filtered-read rule, he spot-checks that delegated agents actually READ their Always-tier Methodology Dependencies files — grep each subagent's transcript for file-reading tool calls against the exact dependency file paths listed in its `agents/<name>.md` table, and report any agent that skipped one as a finding. Instruct him to hunt cross-phase patterns specifically (e.g. build-phase failures that trace back to plan-phase gaps), and to write proposed updates to `.docs/{project-name}/implementation/agent-improvements.md`.
