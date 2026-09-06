# bgpdd-quick — rationale, escalation cases, worked examples

Spine: `../SKILL.md`. This file carries the reasoning the spine only labels,
the escalation cases in detail, and two worked runs. Loaded on demand.

## What gap this lane fills

Before this lane the plugin's cheapest entry point was `/bgpdd-bugfix`: six
phases, four delegations, five gates, a state file, a run log and a game tape —
for a bug. `/bgpdd-lite` is heavier still. Every one of them assumes an *epic*:
a `.docs/{project-name}/` tree, a plan, milestones, a squad.

None of that fits the change the user actually makes most days. A rename. A
config value. One added test. A guard clause. Faced with a lane whose overhead
exceeds the change by an order of magnitude, the user does the only rational
thing: skips the lane entirely and edits the file. Which means the plugin's
evidence discipline — declared scope, a check that actually ran, a bounded diff,
a commit that is gated rather than assumed — covers the 20% of work that is
already careful and none of the 80% that is not.

This lane is a deliberate bet: at this size, **one gate that cannot be skipped
buys more than five gates that get skipped along with the lane.**

## Why this lane reads two contract sections, not the whole contract

Every other pipeline's MANDATORY FIRST READ pulls `orchestrator-contract.md`
entire. This one reads `## Runtime Neutrality` and `## 3. Role Boundaries` and
stops — a labelled convention-#8 refinement of that rule, for a reason specific
to what the file contains.

Of its five numbered sections, §1 governs delegation discipline, §2 the error
recovery and circuit breaker around delegated work, §4 state hydration and the
inter-pipeline hand-off, §5 where orchestrator lessons land. This lane delegates
nothing, hydrates no state and hands off to nobody; §3 is the only section whose
subject it actually performs — and it performs it by divergence, which the spine
labels. Runtime Neutrality is universal and cheap.

The cost of reading the rest is not abstract. 3,700 words is several times the
lane's own spine, loaded before a change that touches at most three files: the
same overhead-exceeds-the-change arithmetic that made this lane necessary in the
first place, reappearing inside it. A daily driver that charges a heavy read for
every use gets skipped, and a skipped lane enforces nothing.

What the trim must not do is let an escalation inherit it. **A lane escalated to
reads the contract in full** — it is the lane that will delegate, persist state
and hand off. The spine states that in the same block, so the two rules are
never read apart.

## Why the Orchestrator is the worker here

Orchestrator Contract §3 forbids the Orchestrator writing application code, for
two reasons that are worth separating:

1. **Context collapse.** Roleplaying a builder inside the main session floods
   the window that holds the epic, the plan, the milestone cursor and every
   prior handoff. This is the real reason, and it is *proportional to what the
   session is holding*. A quick-lane session holds a slug, three file paths and
   a command. There is nothing to collapse.
2. **Separation of duties.** The author of a fix should not also be the sole
   judge of it. Real, and this lane does not pretend otherwise — it replaces
   the human judge with a mechanical one. Phase 3's gate is not persuadable: it
   re-hashes the capture, re-reads the tree, and re-counts the files. What it
   cannot do is have an opinion about design, which is exactly why any change
   with a design question in it escalates instead.

A delegation round would cost a persona load, a brief, a handoff and a
verification read — more context than the change itself, spent to obtain a
separation the size of the change does not earn. That trade is the labelled
divergence in the spine.

## Why no state file and no run log

`orchestrator-state.json` exists so `/bgpdd-plan` can hand a cursor to
`/bgpdd-build` and `/bgpdd-build` can hand one to `/bgpdd-shipping`, across
sessions. This lane has no successor and no cursor: it opens and closes inside
one session, and its whole output is one commit.

`run-log.jsonl` records what *delegations* cost — agent, model, duration,
tokens, rounds. Contract §4's obligation is per delegation completion and per
state persistence. This lane has neither. Writing a run log with no delegation
records in it would be an empty file asserting that nothing ran, which is worse
than its absence.

What remains is `gates.jsonl`, and it is not optional: it is the only durable
proof the gate fired, with which flags, against which artifact hashes. A quick
change whose gate left no ledger line is indistinguishable from a quick change
whose gate was never run.

## The escalation table, case by case

| The change | Route | Why not here |
|---|---|---|
| Alters behaviour something else depends on | `/bgpdd-lite` | Something downstream has to be checked, and this lane has no traceability to check it with — no FR/NFR ids, no coverage gate. |
| Fixes a defect that has a reproduction | `/bgpdd-bugfix` | A reproduction means a RED capture is *available*, and a fix proven only by a post-fix green is exactly what `check_red_green.py` exists to reject. Taking it here would launder that. |
| Adds a capability, or changes a schema or contract | `/bgpdd-plan` | There is a design decision, and no lane where the author is the only reader may make one. |

**The case the table used to leave ambiguous** is the test that goes red *while*
you are making the change. Read literally, "fixes a defect that has a
reproduction" catches it: there is a red test, and a red test is a reproduction.
That reading routes every ordinary debugging loop out of the lane and empties
it. The line is *when the defect started existing*: red produced by the edit in
front of you is your own work misbehaving, and
`debugging-and-error-recovery` is the card for it; red that predates the session
and has a reproduction is `/bgpdd-bugfix`. The router (`bg/SKILL.md`) states the
same split, because the question arrives there first.

When the escalation does fire, the note is not thrown away. Its `What` line is
already an observed-behaviour sentence and its `How verified` line is already a
single argv-runnable command — exactly the two hardest fields of
`bug-report.md` to write from a standing start. They cross over as **drafts**,
`check_bugfix_intake.py` lints them like any other typed text, and nothing else
carries. This is a convenience, not a shortcut: the gate's judgement is
unchanged, and a `How verified` that was a build rather than a reproduction
fails there just as it would have.

Two rules of thumb for the cases the table does not name:

- **If you want to explain the change to someone before making it, it is not a
  quick change.** The note's three lines are a declaration, not an argument.
- **Duration is not the test.** A two-minute schema tweak is still a schema
  change. Route by what the change *is*.

The bound is mechanical for a reason (CLAUDE.md convention #9): "keep it small"
is a restraint asked of you at the moment the change is nearly done and one
more file would finish it. `--max-changed-files` makes that moment a gate
verdict instead of a judgement call, and gives it no waiver — see
`{PLUGIN_ROOT}/pipeline-tools/references/check_quick_close.md`.

## Worked example — a passing run

Intent: *"`Coupon.pct` reads badly; rename it to `Coupon.percent`."*

`.docs/quick/2026-09-04-rename-coupon-pct/note.md`:

```markdown
# rename-coupon-pct

- What: rename Coupon.pct to Coupon.percent for readability
- Where: src/domain/coupon.py, src/api/coupon_routes.py
- How verified: `python -m pytest tests/test_coupon.py -q`
```

The test file is the *oracle*, not part of the change — it is named on the
`How verified` line and absent from `Where`. That is the shape this lane is
built for, and `--frozen tests/` passes untouched.

Phase 2:

```bash
python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py \
    --capture .docs/quick/2026-09-04-rename-coupon-pct/evidence/check.md \
    -- python -m pytest tests/test_coupon.py -q
```

Phase 3 exits 0, commits both declared files, and the note gains:

```markdown
## Result

- Gate PASS (2 files, capture exit 0, `--frozen tests/` clean). No surprises.
```

## What `--frozen` actually forbids

It forbids **editing an existing tracked file** under a frozen path. Three
consequences worth stating plainly, because the flag is the lane's only defence
against the oldest way to make a check pass:

- **Adding a new test file passes.** `git status` reports it as untracked (or
  `A`), not modified, and the gate treats new and modified differently on
  purpose — "add a test" is one of this lane's stated use cases, and a rule that
  forbade its own use case would simply be dropped by whoever hit it.
- **Staging the edit first does not help.** Both index and worktree status
  letters are read.
- **A `--frozen` value with `*`, `?` or `[` in it is a glob**, matched against
  the repo-relative forward-slash path with `**` support; anything else is
  still a directory prefix. This is what lets the lane freeze a stack whose
  tests sit beside the code they cover — `**/*.spec.ts`, `**/*.Tests/**`,
  `**/*.test.*` — where `tests/` would have frozen nothing at all. Phase 0's
  `detect_stack.py` run supplies the right set per stack; the gate holds no
  default of its own, deliberately, because a freeze it guessed and got wrong
  passes exactly like a change with no test to protect.
- **A rename whose call sites include a test is genuinely blocked.** That is the
  hard case, and the block is correct as a default: the gate cannot distinguish
  a mechanical symbol rename inside a test from a weakened assertion. Narrow
  `--frozen` to the test trees the change does not touch, or drop it and say so
  in `## Result`. Every flag set is recorded in `gates.jsonl` under `argv`, so
  the narrowing is attributable rather than invisible — which is the same trade
  `check_commit_gate.py --waiver` makes in the bugfix lane, taken here at the
  flag rather than in an artifact because it is a scoping decision, not a
  judgement about size.

## Worked example — a blocked run

Same intent, but the rename turned out to need a call-site fix in two more
modules. Four declared files, `--max-changed-files 3`:

```json
{
  "problem_codes": ["size_bound_exceeded"],
  "problems": ["size_bound_exceeded: 4 declared files exceeds this lane's bound of 3. There is no waiver here: escalate instead -- a defect with a reproduction to /bgpdd-bugfix, otherwise /bgpdd-lite."]
}
```

The correct response is not to raise the bound. It is to notice that a rename
reaching four modules is a change to a shared symbol — the blast-radius case
that `/bgpdd-lite` has traceability for and this lane does not.

## Anti-patterns

- **Writing `note.md` after the edit.** The note is a declaration; written
  afterwards it is a summary, and it will always match, which makes the Where
  check vacuous. The gate cannot detect this. You can.
- **`- How verified: manually`.** Not a command; the note fails
  `note_incomplete` and should. If a change genuinely has no runnable check,
  that is a signal about the change, not about the lane.
- **Re-running the gate until it passes by changing the flags.** Dropping
  `--frozen`, raising `--max-changed-files`, or re-pointing `--changed-files` at
  a subset are all ways of passing a gate without satisfying it. Every flag set
  is recorded in `gates.jsonl` under `argv`, which is what makes this visible
  later rather than merely forbidden now.
- **Using this lane for the third quick change in a row on the same subject.**
  Three quick changes to one area is a feature arriving one edit at a time
  without a plan. Stop and run `/bgpdd-lite`.
