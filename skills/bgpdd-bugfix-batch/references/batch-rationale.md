# bgpdd-bugfix-batch — rationale, the worktree/hook interaction, the overlap rule

Depth for `{PLUGIN_ROOT}/bgpdd-bugfix-batch/SKILL.md`, loaded on demand. The spine is the
contract; nothing here adds a rule. Where a term below is mechanical, the script that
enforces it is named.

## 1. Why this lane exists at all

`/bgpdd-bugfix` fixes **one** bug and cannot be run twice in one working tree. Two
independent reasons, both mechanical:

1. **The commit gate's `--verify-tree` fails.** Phase 5's
   `check_commit_gate.py --changed-files <the fix> --verify-tree` refuses a commit when the
   tree holds a change the caller did not declare (`undeclared_tree_changes`). Bug A's fix
   sits uncommitted in the tree until its own gate commits it, so bug B's gate — run while
   A is still open — sees A's edits as undeclared and blocks. The obvious workarounds are
   each worse than the problem: declaring A's files in B's commit gate makes one commit out
   of two fixes (and blows B's `--max-changed-files`), and committing A by hand outside its
   gate is exactly the restraint `guard_action.py` rule 1 and convention #9 exist to stop.
2. **The spine is one linear flow with two interactive stops.** Phase 0's report is written
   turn-by-turn with the user, and Phase 2's FULL route pauses for them again. A single
   session cannot interleave two of those and still have `pipeline_driver.py` answer "where
   am I" — the driver derives one phase from one lane root, and one root per tree means one
   answer.

What already coexists is the **artifacts**: `bgpdd-bugfix` § 1 made both routes
slug-scoped (`references/bugfix-rationale.md` § 8b), so `.docs/bugfix/{slug}/` on the
standalone route and `implementation/bugs/{slug}/` on the feature route already hold N
bugs' reports, RCAs, captures and ledgers side by side without collision. The artifact
model needed nothing; only the **tree** did. That is the whole design: give each bug its
own tree, and the existing contract runs N times unchanged.

## 2. The worktree/hook interaction

`git worktree add <path> -b fix/{slug} <base>` gives each bug its own checkout of the same
repository — its own working tree and index, its own branch, one shared object store. The
`.docs/bugfix/{slug}/` folder for that bug is created **inside** that tree, which is what
makes the hook behave.

`guard_action.py` detects the active lane **from the tree, rooted at the tool call's own
`cwd`** (its module docstring: "Four detectors, all relative to the hook's `cwd`"). The
bugfix detectors share one walk, `bugfix_report_dirs(cwd)`, which offers
`<cwd>/.docs/bugfix/*/bug-report.md` (standalone) and
`<cwd>/.docs/*/implementation[/bugs/*]/bug-report.md` (feature). Consequences, all read off
that code:

- **Each worktree presents exactly one bugfix lane.** A call made with worktree W as its
  `cwd` sees W's single `bug-report.md`. So rule 2 (`frozen_tests_during_a_fix`) and rule 3
  (`no_delegation_before_intake`) arm N times over, once per bug, against the right bug —
  which is the property a single shared tree would destroy: N reports in one tree would
  make every rule's milestone scope ambiguous, and `lane_is_closed` fails closed on an
  unreadable milestone.
- **`{batch-root}` arms nothing.** `.docs/bugfix-batch/` is a sibling of `.docs/bugfix/`,
  not a child, so the standalone walk (`_iter_dirs(docs / "bugfix")`) never reaches it, and
  the feature walk needs a `<project>/implementation/` directory it does not have. The
  batch root is therefore inert to lane detection — deliberately, since the batch layer has
  no commit gate of its own to name.
- **Rule 4 still guards the batch root.** `gate_artifacts_are_written_by_tools` fires on any
  write to `gates.jsonl`, `run-log.jsonl`, `orchestrator-state.json` or a `*.meta.json`
  sidecar, "always, lane or no lane" — so `{batch-root}/gates.jsonl` and
  `{batch-root}/run-log.jsonl` are hand-edit-proof exactly as a lane's are.
- **The merges are unguarded, and that is why the spine binds a gate to them.** Rule 1
  (`commit_through_the_gate`) arms only when an active open lane with a commit gate is
  detected in the call's `cwd`. The merges run in the **main tree**, which holds no
  `bug-report.md` — every report is inside a worktree — so no lane is detected and
  `git merge` is allowed. The hook cannot help here, which is precisely why Phase 3 step 2
  makes the merge's precondition a command that has to be run: `check_ledger.py` on that
  bug's own ledger plus a `check_commit_gate.py` `PASS` record carrying `--commit`
  (convention #9 — a restraint at the moment of merging is an artifact, not prose).

## 3. Why phases run in waves rather than N sequential lanes

Running `/bgpdd-bugfix` five times end to end costs five RED delegations, five builders,
five GREENs and five Lunas **in series**. The waves change only the scheduling: every bug's
RED goes out in one message, then every RCA, and so on. Orchestrator Contract §1 permits
this and states its own precondition — *partition every write surface before you launch* —
which the worktrees satisfy for files by construction.

The surfaces worktrees do **not** partition are the non-file ones §1 also names: ports,
singleton external identities, shared caches, installed artifacts. A wave of Quinn REDs
that each start the same service on the same port is one write surface with five claimants,
and §1's answer is to serialize rather than partition. Each bug's brief therefore names the
port or identity its reproduction uses, and two bugs whose reproductions need the same
singleton run in different waves — the same rule the eval fixture exercises by giving each
bug its own port.

```
Phase 0  intake, one bug at a time, with the user   (interactive: never parallel)
Phase 1  wt/bug-a      wt/bug-b      wt/bug-c        (worktrees created)
Phase 2  RED    ──┐    RED    ──┐    RED    ──┐      wave 1  (parallel, background)
         RCA    ──┤    RCA    ──┤    RCA ── PLAN ──> /bgpdd-plan, dropped
         Fix    ──┤    Fix    ──┤                    wave 3
         GREEN  ──┤    GREEN  ──┤                    wave 4
         Luna   ──┘    Luna   ──┘                    wave 5  (fresh per bug)
Phase 3  gate+commit   gate+commit                   per bug, in its own worktree
         ledger check, evidence commit, merge A ───> base
                       rebase B on base, re-GREEN,
                       evidence commit, merge B ───> base   one at a time, by overlap
Phase 4  batch.md final table, worktrees removed, one game-tape bullet per bug
```

## 4. The overlap rule, and why it is a merge-order rule

Two bugs "overlap" when they can touch the same file. The batch learns this twice, at
different costs:

- **Cheaply, at intake** — the reports' `## Affected surface` sections name the same
  surface. This is a *prediction*, and the spine treats it as one: it decides merge order,
  nothing else.
- **Certainly, at Phase 3** — the two builders' `<changed_files>` sets intersect. These are
  validated per `bgpdd-bugfix` § 1's `check_handoff.py --since --ledger`, which is what
  makes them a fact about the tree rather than a claim in a handoff.

The rule then is: **the second bug merges after the first, rebasing its branch on the merged
base and re-running its GREEN and `check_red_green.py` there.** Two things make that the only
honest option. First, a GREEN capture proves the fix works against the tree it ran in; once
bug A's change lands under bug B, B's GREEN is evidence about a tree that no longer exists,
so re-running it is not ceremony. Second, resolving a merge conflict by hand produces a diff
**no gate has seen** — not Luna's review (whose `check_commit_gate.py --verify-tree` term was
satisfied against the pre-merge tree), not the red/green pair. A conflict is therefore
routed, never resolved in place.

**What the second bug does NOT do is re-enter its commit gate.** Its fix is already committed
by that gate, and `check_commit_gate.py --commit` answers `already_committed` (exit 1) when no
declared path differs from HEAD — by design, so that a commit made outside the gate is loud.
The rebase therefore re-establishes the *evidence* (a fresh GREEN of the same argv, later than
the RED, through `check_red_green.py`), not the commit.

## 4b. Why each bug's evidence gets its own commit

`check_undeclared_tree` in `check_commit_gate.py` exempts everything under `.docs/`: pipeline
artifacts legitimately change during a milestone without being a code change. So a bug's
`bug-report.md`, `rca.md`, captures, sidecars, `gates.jsonl` and `run-log.jsonl` are still
**untracked** when its gate commits the fix — which is exactly how `/bgpdd-bugfix` leaves them
in a normal single-bug run, where nothing later deletes the tree.

A batch does delete the tree. `git worktree remove` refuses a worktree with untracked files,
and `--force` would take the whole evidence set with it — the ledger that is the only record
the fix was gated (`bgpdd-bugfix` Phase 5 step 8). Hence Phase 3 step 2(b): commit that bug's
`.docs/bugfix/{bug-slug}/` on its own branch, just before the branch merges, so the evidence
arrives in the base alongside the fix and the worktree becomes disposable.

That commit is a hand `git commit`, and it is permitted rather than smuggled: `guard_action.py`
rule 1 disarms for a lane whose own ledger holds a `check_commit_gate.py` PASS carrying
`--commit` for its current milestone, which step 2(a) has just verified. The same carve-out is
what lets `bgpdd-bugfix` and `bgpdd-lite` run their closing local merges.

Bugs that genuinely need the *same edit* are not two bugs. That is the `## Limitations`
entry, and the test is the RCA: two `rca.md` files naming the same `- Root cause file:` and
the same mechanism are one bug with two reporters.

## 5. Why `--event note` and not `--event batch`

`record_run.py`'s `EVENTS` tuple is `("delegation", "gate", "phase", "note")`; anything else
is exit 2. A batch-level record is therefore `--event note`, and the batch layer adds no
script and no new event value — a thin lane that changed a shared CLI's enum would make
every existing run log's reader guess at a fifth kind.

The per-bug run log stays the authoritative one for the same reason it exists:
`check_commit_gate.py --require-run-log --require-agents` reads `{bugfix-root}/run-log.jsonl`
and scopes **exactly** on the record's `unit`. A batch-level duplicate would be a second
record no gate reads, and Orchestrator Contract §4's point is that the record is the thing a
later gate can check.

## 6. Example `batch.md`

Written at Phase 0 with the status column empty, updated as waves land, closed at Phase 4.

```markdown
# Bug batch: 2026-09-08-checkout-triage

- Base branch: `main`
- Batch root: `.docs/bugfix-batch/2026-09-08-checkout-triage/`

## Bugs

| # | Slug | Surface | Worktree | Branch | Status |
|---|---|---|---|---|---|
| 1 | `null-coupon-500` | api | `../wt/null-coupon-500` | `fix/null-coupon-500` | MERGED |
| 2 | `tax-rounding-cents` | api | `../wt/tax-rounding-cents` | `fix/tax-rounding-cents` | MERGED |
| 3 | `cart-badge-stale` | ui | `../wt/cart-badge-stale` | `fix/cart-badge-stale` | DROPPED-PLAN |

## Overlap

- 1 and 2 both declare `## Affected surface: api` and their builders both returned
  `src/pricing.js` — serialised: 2 merges after 1, rebased on the merged base, GREEN
  re-run there (spine Phase 3 step 3).
- 3 is independent (ui) and was dropped at its route step: `next_bugfix_route.py` printed
  `PLAN` (new capability), handed to `/bgpdd-plan` with its `bug-report.md`.

## Final

| # | Slug | Commit | Gate record |
|---|---|---|---|
| 1 | `null-coupon-500` | `9f2c1ab` | `check_commit_gate.py` PASS `--commit`, 2026-09-08T11:04:12Z, `.docs/bugfix/null-coupon-500/gates.jsonl` line 7 (`check_ledger.py` exit 0) |
| 2 | `tax-rounding-cents` | `4d7e880` | `check_commit_gate.py` PASS `--commit`, 2026-09-08T11:31:55Z, `.docs/bugfix/tax-rounding-cents/gates.jsonl` line 9 (`check_ledger.py` exit 0) |
| 3 | `cart-badge-stale` | — | dropped to `/bgpdd-plan` before Phase 3 |
```

## Anti-patterns

- **One worktree, N bug roots.** The artifacts survive it; `--verify-tree` does not, and
  every hook rule loses its scope. § 1.
- **One commit for the batch.** It defeats each bug's own `--max-changed-files` bound and
  makes a revert of one bug a revert of all of them.
- **Merging all branches, then running one gate at the end.** The gate's `--verify-tree` and
  Luna's verdict are both about a specific tree; a post-merge gate certifies a tree nobody
  reviewed.
- **Resolving a merge conflict by hand "because it was obvious".** § 4.
- **Batching bugs of an in-flight epic.** The epic is one branch and one worktree, and
  `bgpdd-bugfix` § 1 forbids a private fix branch on that route — so N trees cannot exist.
  Fix them sequentially on the epic's branch, which is what the feature route is for.
- **A batch of one.** That is `/bgpdd-bugfix`, and the batch layer adds only overhead.
