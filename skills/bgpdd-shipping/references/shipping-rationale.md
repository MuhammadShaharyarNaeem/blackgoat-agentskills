# bgpdd-shipping — Rationale and Observed-Failure Narratives

Loaded on demand. Every rule this file explains lives, in its operative form, in `skills/bgpdd-shipping/SKILL.md`. Nothing here is a contract: if this file and the spine disagree, the spine wins. Read a section when you need to know *why* a rule is shaped the way it is — most often when you are about to argue that it should be relaxed.

---

## Core capabilities, in full

1. **Launch Orchestration**: delegates to a staged Launch Squad — Vera (Stage 1), then Cipher+Dep (Stage 2 in parallel) — against the `shipping-and-launch` checklists.
2. **Strict Gatekeeping**: blocks final deployment until all 3 agents report a fully green checklist, and does not close until the deployed environment has been verified against that checklist (Step 5.5).
3. **Automated Documentation**: compiles the final Changelog, README updates, and Emergency Rollback Plan based on agent reports.

---

## Why the Step 6.4 write to Tier 1 exists

Tier 1 (`.docs/summary/{feature}/`) is produced only by `/bgpdd-discovery` and is read-only everywhere else. Step 6.4 is the one sanctioned write, and the spine labels it a deliberate divergence (convention #8) rather than an exception to be generalized.

Without it, the QA baseline captures only how the system behaved before the *first* feature ever shipped. Every subsequent discovery run re-derives the baseline from scratch, and Alex's Baseline Reconciliation duty compares the plan against a document that is progressively more wrong. The alternative to the write is a baseline that rots after the first feature ships.

The write is narrow by construction — one file, once, after the launch squad is green, recording only behavior that was just verified. That narrowness is what makes it a refinement of the read-only rule rather than a breach of it.

### Why the lite path still writes something

Skipping outright leaves `manual-testing.md` describing a system this epic has since changed, and the next discovery run trusts it — the exact rot the exception exists to prevent. So a lite-originated epic (no acceptance matrix) still records the change, as a dated note listing the FR/NFR IDs that shipped and the evidence lines that proved them.

That note is a **deliberate refinement of step 3's "record only what was proven"** (convention #8): step 3 bars an unverified *scenario* from the baseline, because the next discovery run would execute it as truth. The note asserts no scenario — it records which requirements shipped and where their evidence lives, which is proven material in a form that cannot be mistaken for a test case. The rule's target is a fabricated case, not an honest gap marker.

---

## Why Step 5.5 exists, and why it is numbered 5.5

**Why it exists**: until this step existed the pipeline ended at PR open, and every "after deploying" item in `shipping-and-launch`'s Verification section was owned by nobody. The last thing this pipeline verified was a decision taken *before* the deploy.

**Why the number**: a trailing "Step 8" would either read as running last or force a renumber of 6.4/6.5/6.6, which `README.md` and `agents/echo.md` cite by identifier. Sequence position wins over the number.

**Why a fresh Dep**: the context that wrote `Ship Decision: GO` an hour ago is primed to read every post-deploy dashboard as confirming it. Orchestrator Contract §1's independent-verification exemption applies for the same reason it does to the Step 3 Quinn re-run.

**Why a deferred verification is recorded rather than simulated**: a deferred verification recorded as deferred is honest; one recorded as green is the defect this step exists to prevent.

### Why the two Step 5.5 gates are not redundant

`check_agent_report.py` proves the verdict is backed by evidenced check lines; `check_runtime_evidence.py` proves something was actually probed out-of-process. The same pairing Step 3 applies to Vera, applied here to the deployed environment.

---

## Why the Runtime Smoke section may not be dropped from Vera's paste

`Pre-Merge Local Runtime Smoke` is the only item in Vera's assignment that requires a *started* application, and it is the section that would have caught the 2026-08 response-envelope escape. Omitting it silently returns this pipeline to build-and-lint verification.

"Do not drop it" is a restraint asked of you at the moment you are assembling a long prompt, so the spine verifies the result instead of the intent (convention #9): it searches the delivered report for the section heading. Proceeding to the Runtime Evidence Gate on a report with no smoke section would mean the gate is reading captures nobody was asked to produce.

---

## Why the Step 0.4 entry ticket and the Step 3 exit ticket run the same script with different flags

`ship-decision.md` is a single mutable file read at two different moments in its life.

- At **Step 0.4** it holds a *prep* decision written at `bgpdd-build` Phase 5, which legitimately predates any rollback rehearsal and any rollout baseline. Requiring them there would make the entry ticket unobtainable.
- At **Step 3** it holds a *launch* decision, where both must exist.

Hence the exit ticket is deliberately tighter (convention #8): `--require-rehearsal --require-baseline --repo .` on top of `--require-go`.

The **resume branch** of Step 0.4 drops `--require-go` for a different reason. On a resume, Stage 2 Dep has already rewritten the file, so its content is an *exit* verdict, not an entry one. A standing `NO-GO` is the work the resume exists to finish. Applying `--require-go` there would block re-entry to the only stage that can resolve the NO-GO, and the pipeline could never converge on its own output.

---

## Why the acceptance suite is re-executed rather than re-read

`check_acceptance_suite.py` is documented (`pipeline-tools/SKILL.md`, `planning-and-task-breakdown/SKILL.md`) as running "again at `bgpdd-shipping` Stage 1 as regression". Re-reading build's `acceptance-results.md` is not that run: a results file written at build passes the same gate it passed at build no matter what changed since, so a re-check of it can only ever confirm history. The walkthrough has to be *executed again* against the code that is about to ship.

**Why a fresh Quinn**: Orchestrator Contract §1's independent-verification exemption — a verifier re-examining shipped work, and a context that already recorded these steps green is primed to record them green again.

**Why `--changed-files` is added here** (deliberate divergence from `bgpdd-build` Phase 5 step 2.5, convention #8): same script, same matrix, same priority scope. Build's invocation grades a walkthrough Quinn had just run, so freshness was implicit. Shipping's would otherwise grade a file that is by construction older than the code, so freshness must be asserted.

---

## Why `--surface` and `--expect-status` are deliberately not passed at shipping

Both are per-capture, per-milestone assertions — one declared surface, one expected status code. An epic's captures can legitimately span several milestones with different surfaces and statuses, so no single value passed at the epic level could hold across the whole re-run without being wrong for some capture it claims to cover.

`--require-key` and `--forbid-host` survive the same reasoning because they assert content that is meant to hold uniformly across every capture.

This is the same divergence class as the `--milestone` scope at shipping being the epic rather than a single build milestone.

---

## Why the fix-routing bound counts checklist areas, not artifacts

Deliberately a different unit from Orchestrator Contract §2's "2 rounds per artifact" (convention #8). One agent writes one report covering several checklist areas, so an artifact-scoped count would spend the whole budget on the first failing area and leave a genuinely independent second area with none. Same bound of 2, deliberately coarser scope.

A rehearsal older than `--max-rehearsal-age-days` (default 30) is `rehearsal_stale` and has to be re-run, not re-dated. Pass a smaller value where the deploy pipeline changes faster than 30 days.

---

## Why a shipping finding is recorded as a blocker *before* the re-entry instruction

`bgpdd-build`'s hydration accepts `pipeline: bgpdd-shipping` as a re-entry — it resets the state to `bgpdd-build` and records the shipping finding in the game tape, so the state no longer has to be laundered to get back in.

Without the blocker entry, build's commit gate has nothing standing against the milestone and will happily close it on the same green that shipped the defect. With it, the milestone cannot close until the entry is discharged under Orchestrator Contract §4's evidence rule.

**Why the entry must be scoped**: `--blocker-milestone` is what lets build's commit gate hold exactly the milestone this finding lands in while the rest of the plan stays commitable. An unscoped entry still blocks everything — the fail-safe reading for a finding whose owner is genuinely unknown, not a default to reach for when you know it.

---

## Why the Step 6.5 roll-up is unscoped, and not a duplicate of build's

**No `--unit`**, deliberately, unlike `bgpdd-build` Phase 6 step 1b's per-milestone block (convention #8): a unit filter would drop every phase-level and null-milestone record the epic-wide view exists to show.

**Not a duplicate of build's own epic roll-up** (Phase 6 step 2) either: that one closes the build phase; this one runs after shipping's Step 2, 3 and 5.5 delegations have appended their own records, so it is the first and only roll-up covering the whole epic *including its launch*.

**Why the block is pasted rather than narrated**: a summary you retype is a number Forge cannot check against the log.

**Why the tape cites the ledger rather than re-narrating it**: every Step 0, Step 3, Step 3.5 and Step 5.5 gate invocation appended a record to `gates.jsonl` with its argv, inputs and verdict. Step 7's Forge run reads the ledger for what actually ran and the game tape only for what could not have been recorded mechanically. A gate claimed in the tape with no ledger record is the discrepancy Forge is meant to find — write the tape so it is findable rather than papering over it.

---

## Why Step 7 gates Forge on a populated game tape

If the tape records only this pipeline, the epic's build and plan phases left nothing behind. Delegating anyway produces confident lessons derived from one shipping session and a `git log`, which is worse than no lessons: they are indistinguishable from evidenced ones once they land in a persona.

`bgpdd-build` Phase 6 admits this exact failure — milestones M1–M8 of a real epic ran with zero checkpoints, and the improvement run that followed had a fraction of the evidence it needed. The fix is Phase 6 checkpoints during the *next* epic, not a Forge run now.

**Why the eval bracket is offered rather than run**: running the suite spends the user's tokens, and a bracket they did not ask for is a bill, not evidence. `evals/weekly-check.ps1` is zero-token — it only reads files and git, and never invokes the eval runner.

**Why the write boundary is verified after the apply** (convention #9): Forge's write boundary is prose in his persona, and it is asked of him at the moment he is editing files. So the spine verifies the result — `git diff --name-only` — instead of the intent.

**Why reverting is the user's call**: Forge's `<changed_skills>` pairing of each approved lesson with its destination file is what makes a single bad lesson revertible without unwinding the whole apply. Only the user can decide which lesson to drop.

---

## Why the Step 0.3 prerequisite gate is mechanical

"All milestones are `[x]`" is a counting judgment made while you are already committed to shipping — exactly the class convention #9 converts. `plan.md` is not eyeballed.

---

## Why agents here commit as they go

Agents in this pipeline touch a shipping-ready codebase, so the incremental-persistence instruction passed to them must cover committing code changes to the working branch as they are made, not only writing reports section by section. That is what makes the partial-work expectation achievable rather than aspirational.
