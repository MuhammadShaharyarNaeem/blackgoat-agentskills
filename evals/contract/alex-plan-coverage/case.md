# Case: alex-plan-coverage

## Purpose
Guards against Alex producing a `plan.md` that fails the Must-Have requirements coverage
gate used at every bgPDD pipeline checkpoint (`bgpdd-plan` Phase 3.5, `bgpdd-lite` Phase
2.5, `bgpdd-build` Phase 5 Step 2): tasks missing the `**Requirements covered:**` field,
non-integer `## Task [N]:` headings that make a whole task block invisible to the gate,
or a genuinely dropped Must-Have FR/NFR. The fixture also targets a subtler failure
mode: a requirement that is deliberately cross-cutting (audit logging touching every
endpoint) getting collapsed into a single task instead of threaded through the tasks it
actually spans.

## Frozen Input
- Fixture dir: `fixture/requirements.md` — a "webhook notification service" spec with 5
  Must-Have FRs (`FR-5` is the cross-cutting audit-logging requirement), 1 Should-Have
  FR, 1 Could-Have FR, and 2 Must-Have NFRs.
- Copies to: `.docs/webhook-notify/`

## Command
Run from the temp working copy's root (the parent of `.docs/`):

```powershell
claude -p "Act as Alex per agents/alex.md. Read .docs/webhook-notify/requirements.md and produce .docs/webhook-notify/plan.md following the planning-and-task-breakdown methodology exactly. Every Must-Have FR and NFR must be covered by at least one task's Requirements covered field before you finalize - cross-check against the Must-Have list yourself." --permission-mode acceptEdits
```

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. `.docs/webhook-notify/requirements.md` is present (fixture sanity check).
2. `.docs/webhook-notify/plan.md` was produced.
3. `python skills/pipeline-tools/scripts/check_coverage.py --requirements <requirements.md> --plan <plan.md>` exits `0` with `"result": "PASS"` and an empty `uncovered` array. **This is the grader shelling out to the real coverage-gate tool — it does not reimplement the parsing rules.**
4. The tool's `warnings` array contains no `"has no 'Requirements covered:' field"`
   entry — every task is explicitly tagged, not merely accidentally covered by another
   task.
5. `FR-5` (the cross-cutting audit-logging requirement) appears in the
   `Requirements covered:` field of **at least two** distinct task blocks — proof it was
   threaded through the plan rather than dumped into one task and called done.

`grade.ps1` exits `0` only if all five pass; otherwise it exits `1` and prints which
criterion failed, including the raw `check_coverage.py` JSON fields where relevant.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

## Future (not implemented)
Whether the task breakdown is well-sequenced (dependencies, vertical slicing per
`planning-and-task-breakdown`) beyond the coverage gate is a judgment call, not a
deterministic check. Not implemented here.
