# bgpdd-build — Sub-Contract: The Alex Re-Planning Loop

**This file is a SUB-CONTRACT, not rationale.** `bgpdd-build/SKILL.md` names five call sites where a planning defect routes to Alex mid-run; the executable detail — brief shape, artifact path and re-entry rule — lives here and is binding. Read it in full before delegating to Alex from any of them. Where it and the spine appear to conflict, the spine wins — but nothing here is optional.

Alex is a **conditional re-planning agent only** in this pipeline (SKILL.md §1) — re-engaged when a planning defect surfaces mid-run, never to plan new work. **The Orchestrator makes this delegation itself** — convention #6: subagents never route to Alex on their own, they only surface the defect that makes the Orchestrator do it.

## § When this fires

The five call sites: the umbrella rule (SKILL.md §1, Strict Delegation), a `MIXED`/`UNTAGGED` milestone (Phase 1 step 2), a milestone with no `RUNTIME PROBE:` line (Phase 2 step 1b), and an acceptance matrix expected but absent (Phase 5 step 2.5 — both the SKILL.md stub and `build-phase5-gates.md` § Steps 1, 2 and 2.5, which restates the same gate). Each HALTs at its own point and routes here rather than improvising a fix.

## § The brief (what Alex receives)

  - The current plan in full, not a summary: `.docs/{project-name}/implementation/plan.md`, or the polymorphic `artifacts.plan` path when that field is set (SKILL.md §1).
  - The exact defect that triggered re-planning, quoted from the gate's own output — never paraphrased: `next_milestone.py`'s `MIXED`/`UNTAGGED` verdict, the milestone text that is missing its `RUNTIME PROBE:` line, or the acceptance-matrix path that resolved to nothing.
  - The current coverage picture, so Alex re-plans against what already exists rather than from zero: `python {PLUGIN_ROOT}/pipeline-tools/scripts/check_coverage.py --requirements .docs/{project-name}/requirements.md --test-report .docs/{project-name}/implementation/test-report.md --ledger .docs/{project-name}/implementation/gates.jsonl`'s result.
  - Which milestones already carry `[x]`, read directly off the plan — these are out of scope for the rewrite (§ Re-entry below).

## § The artifact (where the revision lands)

  - Alex revises the same path his brief named — `plan.md` (or the polymorphic `artifacts.plan` path) in place. There is no second "revised-plan" file for `next_milestone.py` to fall out of sync with; his `<changed_files>` names the one path he touched.
  - Every milestone already `[x]` in the plan he was handed reappears verbatim, `[x]` and all — he may add, split or re-tag pending milestones, never rewrite a completed one's heading or tasks.
  - On the acceptance-matrix call site, Alex also authors/repairs `artifacts.acceptance_matrix` (or `.docs/{project-name}/acceptance-matrix.md`) per `planning-and-task-breakdown` § Acceptance Matrix Output — the same format authority the initial plan used.

## § Re-entry rule (what survives the rewrite)

  - **`[x]` milestones stay `[x]`.** A milestone with a PASS commit-gate entry behind it is done; Alex's rewrite is scoped to pending work and never reopens one — a milestone is reopened only through `mark_milestone.py --reopen`, and only by the Orchestrator's own hydration re-entry rule (SKILL.md §1), never as a side effect of a plan edit.
  - **The ledger is append-only and untouched.** `gates.jsonl` records what already happened; a re-plan never edits, truncates or reorders it. Alex does not write to it at all.
  - **The cursor is re-derived, never hand-set.** After Alex returns, run `next_milestone.py` exactly as SKILL.md §1's "Milestone completion" rule already requires on every plan edit — the first milestone without `[x]`, top to bottom, in the *rewritten* plan. Discard whatever `milestone_cursor` held before the rewrite; it is a resume hint, not authority (SKILL.md §1).
  - **The handoff gate still runs on his return**, exactly as every other agent's does (SKILL.md §1, Handoff validation): `check_handoff.py --handoff <file> --persona alex --repo . --since <the sha HEAD held when the re-plan was launched> --ledger .docs/{project-name}/implementation/gates.jsonl`. Exit 1 = back to Alex, counting the round.
  - Resume the phase that HALTed against the re-derived cursor once the handoff passes.
