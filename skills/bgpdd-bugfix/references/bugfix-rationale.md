# bgpdd-bugfix — rationale, anti-patterns, worked example

Loaded on demand. The operational spine is `../SKILL.md`; nothing here is a rule
the spine does not already state. This file explains *why* the six phases are
shaped as they are, and what each shape is a reaction to.

---

## 1. Why intake is a gate, not a habit

Every other lane in this plugin has an entry ticket that can refuse:
`/bgpdd-verify` demands `.docs/summary/{feature}/QA/manual-testing.md`;
`/bgpdd-build` demands `plan.md`. The bugfix lane's ticket used to be the
Orchestrator's memory of the conversation. Three failures followed from that:

- **The reproduction evaporated.** Quinn was briefed with a paraphrase of a
  command the user had typed twenty messages earlier, so her run and the reported
  bug were not provably the same thing.
- **The surface was decided by impression.** "This looks like a UI bug" routed
  Nova at a defect whose fix landed in an API handler; the builder returned it as
  the routing defect its persona requires, one delegation later.
- **The environment was never recorded.** "It works on my machine" arrived in
  Phase 4, with nothing written down to compare against.

Phase 0 writes `bug-report.md` and `check_bugfix_intake.py` refuses to let the
lane start on a report that is missing a section, still holding template text, or
carrying an unanswered enum. The report is also the durable input two later gates
read: `next_bugfix_route.py` refuses to route without a ledger-recorded intake
PASS whose hash still matches, and Phase 4 reads `- Runtime observable:` to
decide whether `check_runtime_evidence.py` runs.

Depth on the gate itself: `{PLUGIN_ROOT}/pipeline-tools/references/check_bugfix_intake.md`.

## 2. Why Quinn owns RED, and why that is structural

The prior design had the builder write the reproducing test, see it fail, then
fix it — plain TDD, and defensible: the builder's own always-loaded
`test-driven-development` contract requires RED before the fix, so splitting the
test off looked like a collision. The spine even labelled the choice
(convention #8).

It was the wrong trade for one reason: **"make it green" and "make it not
assert" are the same edit** when the same agent owns both the check and the fix.
No prose rule closes that, because the rule has to bind the agent at the moment
the fix is nearly done.

The new split makes it mechanical rather than procedural:

- Quinn produces the RED capture in Phase 1. It is `run_quiet.py --capture`
  output with a machine-owned `.meta.json` sidecar recording the child `argv`,
  the real exit code, and a hash of the finished file.
- The builder is told, in the brief, not to modify the RED test or the
  reproduction command — and the reason that instruction has teeth is that
  Phase 4 replays **the command the RED sidecar records**. An edited check
  produces `command_mismatch` or a GREEN of a different command, which is a
  gate failure, not a pass.
- Luna is briefed with the RED path and checks `<changed_files>` against it.

There is no persona conflict. `quinn.md` §1's narrowing says RED-before-
implementation "does not bind her" — an *exemption*, not a prohibition — and the
code under test already exists, so a pre-fix capture is not
RED-before-implementation at all.

The corollary the spine states in Phase 1 step 3: the reproduction command must
**exit non-zero while the bug is present**. For HTTP that means `curl --fail`
(`-f`), which exits 22 on 4xx/5xx. A bare `curl` exits 0 against a 500 and
produces a capture the gate rejects (`red_exit_zero`) — the single most likely
authoring mistake in this lane.

Depth: `{PLUGIN_ROOT}/pipeline-tools/references/check_red_green.md`.

## 3. Why RED and GREEN are one gate rather than two claims

The old spine said, in prose: *"A GREEN with no RED sibling is an unproven test,
and she reports it as such rather than passing it."* Correct, and unenforceable —
it asks an agent for restraint at the moment the work looks finished, which is
what convention #9 exists to convert.

`check_red_green.py` closes three escapes prose could not:

1. **A green with no red at all** — a test that never failed, run after the fix.
2. **A red and a green of different commands** — both captures real, both exit
   codes honest, the pair proving nothing. A human reviewer misses this one most
   reliably; the identical-`argv` check is why it exists.
3. **A green that predates the fix** — hence the strict `finished` ordering.
   Equal second-resolution stamps fail closed: the gate never says "ordered"
   when it cannot tell.

For a flaky bug, `--green-runs 5` with five green captures. **Four of five is
not fixed** — a bug that reproduces intermittently is not disproved by a run
that happened to pass, and accepting 4/5 would make the lane's own evidence
weaker than the bug's own reproduction rate.

## 4. Why in-process and out-of-process are both required, for one bug class

`runtime-evidence` owns the rule: *an in-process observation can fail a wire
claim but never pass one.* When `bug-report.md` says
`- Runtime observable: yes`, the bug is visible at a boundary a client, person or
device reaches, and Phase 4 runs both:

- **`check_red_green.py`** proves the same command went from failing to passing.
- **`check_runtime_evidence.py`** proves the GREEN capture is an out-of-process
  observation of a running system by an allowlisted client, fresh against the
  diff — the thing the previous spine *named* but never invoked.

Neither substitutes for the other, so the GREEN capture is written under
`evidence/runtime/` with the `Milestone` / `Surface` / `Transport` capture fields
that gate needs, and cited on a `**Runtime evidence:**` line in
`test-report.md`.

The RED capture is deliberately **not** put through the runtime gate: its exit
code is non-zero by design, which that gate treats as `probe_failed_exit` — a
probe that never connected observed nothing. That is the right rule for a
post-fix claim and the wrong one for a pre-fix failure, so the two gates read
different halves of the pair. This also removes the old spine's
`[probe-exempt: test runner, RED capture]` marker requirement: nothing reads a
RED capture's probe line any more.

## 5. Why FAST/FULL/PLAN is mechanical, and why the fork controls only pauses

Most bugs are one file and a null check. Pausing for the user five times to fix a
typo is the friction that gets a lane abandoned, so a fast path is worth having.
But a fast path chosen by the Orchestrator at the moment it wants to proceed
gets taken for the wrong bug, and the phases it skipped are exactly the ones
that would have caught it.

Two design constraints follow:

1. **The fork is derived, not decided.** `next_bugfix_route.py` reads
   `bug-report.md` (via the intake gate) and `rca.md` and prints the route with
   its reasons.
2. **The fork controls nothing but user check-ins.** FAST proceeds phase to
   phase; FULL pauses after the RCA and before the commit. RED, GREEN, Luna and
   the commit gate run on both. A fork that could skip a gate would be a fork
   worth gaming.

PLAN is the third value and outranks the other two: it means *this is not a
bugfix*. A new capability, a schema or contract change, or a fix over the file
bound is `/bgpdd-plan` work, and catching that at Phase 2 saves three
delegations against discovering it at Phase 5 step 4's blast-radius HALT.

Depth: `{PLUGIN_ROOT}/pipeline-tools/references/next_bugfix_route.md`.

## 6. Why the fix-size bound is a gate, and why its waiver is hand-typed

"Use this skill only for localized bug fixes" was a Limitations sentence. A
seven-file "localized" fix passed the commit gate every time, because nothing
counted.

`check_commit_gate.py --max-changed-files 5` counts the declared
`--changed-files` paths — the same list the staleness check already validates
exist, which is why the lane pairs it with `--verify-tree`: that flag is what
makes the declared list equal the real diff.

The waiver is the one place in this family where **author-written text
satisfies a gate**, and that is deliberate (a labelled divergence in
`pipeline-tools/SKILL.md`). Exceeding the bound is a judgement call, and a
judgement call is precisely what no script can verify. What the gate buys is not
verification but **durability and attribution**: the decision is written into
`rca.md` under `## Size waiver`, hashed into the ledger record, and readable six
months later — instead of spoken once in chat and gone. The gate checks that the
section exists and is neither empty nor a placeholder, and nothing more.

## 7. Why API+UI bugs are now delegated instead of refused

The prior spine HALTed on a fix spanning both surfaces and told the user to split
it into two runs or route it to `/bgpdd-build`. The reasoning was Mason's and
Nova's own routing-defect rule: each returns the other's surface unbuilt.

That reasoning survives — neither builder does the other's surface — but the
conclusion does not. Two builders, each on its own surface, against **one shared
RED**, is a well-defined delegation:

- One reproduction means one thing is being fixed, verified once by one GREEN.
- Splitting into two runs produces two bug reports, two RCAs and two RED
  captures for a single defect, and neither run can prove the *whole* bug fixed.
- Routing to `/bgpdd-build` demands a plan and requirements for a null check.

What the Orchestrator must do instead is partition the write surfaces before
launching them concurrently, or serialize — Contract §1's rule, unchanged. The
lane refines this skill's own prior HALT and says so (convention #8).

## 8. Why the close writes back to Tier 1

Quinn's Phase 4 run proved the fix once, in this session. Nothing else records
that the bug ever existed, so the next `/bgpdd-verify` run derives its matrix
from a baseline that never knew about it — and the regression that reintroduces
the bug passes.

So the close appends the reproduced case to
`.docs/summary/{feature}/QA/manual-testing.md` in Echo's `GO → DO → ASSERT`
shape, under Regression Risks.

**This is the second of that file's two sanctioned exceptions, and it is
labelled as one in all three places.** `agents/echo.md` names both writers
(shipping Step 6.4 post-launch; this prevent step, one appended case) and
`bgpdd-shipping`'s Path Model acknowledges this one explicitly. The bugfix
write-back is the narrower of the two: a single case, appended, only after the
commit gate exited 0, recording behaviour just proven by a gated GREEN. It never
rewrites or removes an existing case — that remains shipping's job, which
reconciles against Alex's invalidated/superseded findings.

The permanent version of the same prevention is `/bgpdd-verify {feature}`, which
turns the case into an executed spec. The close names it as the next command
whenever a Tier-1 base exists.

## 9. Why there is one state file per tree, and why this lane leaves `pipeline` alone

The first design gave the feature route its own `orchestrator-state.json` inside
`implementation/`, on the reasoning that a bugfix must never overwrite a live
epic's cursor. That reasoning was right about the cursor and wrong about the
file. Two state files in one tree produced three failures:

1. **The epic's blockers ledger never saw the fix.** A BLOCKED verification
   raised during the bugfix landed in a file `/bgpdd-build` and
   `/bgpdd-shipping` do not read, so the epic's own gates reported a clean
   ledger over a standing blocker in its own code.
2. **The onward route was unreachable.** A re-entry whitelist keyed on
   `pipeline: bgpdd-bugfix` can only fire if something writes that value into
   *the epic's* state — and nothing ever did. The lane closed correctly and the
   fix could not move.
3. **`update_state.py --init` is a documented no-op-with-a-warning on an
   existing file**, so "initialize state" silently did nothing useful on the
   second bugfix against the same feature.

The current design: `{bugfix-root}` still holds every artifact, but
**`{state-file}` is the epic's own `.docs/{project-name}/orchestrator-state.json`
one level up** on the feature route, and
`.docs/bugfix/{bug-slug}/orchestrator-state.json` only on the standalone route,
where there is no epic to share.

**And the feature route does not run `--init` at all.** The first version of
this design ran it anyway and leaned on failure 3 above being benign -- the
no-op warning -- which made the lane depend on a *warning* staying harmless.
If `--init` on an existing file ever hardened to exit 2, the feature route
would break at Phase 0 with nothing in this package testing it. So the epic's
`orchestrator-state.json` is now a **precondition**: read it first, and HALT if
it is absent, because a feature route with no epic state is not a missing file
-- it is a mis-resolved `{bugfix-root}`, and the honest answers are the
standalone route or a corrected resolution. `--init` survives only on the
standalone route, where creating the file is the whole point.

**And `--set-branch` does not survive on the feature route at all.** The design
above once ran it, on the reading that a bugfix gets its own branch like every
other unit of work. On a *shared* state file that is destructive in two places
downstream, both mechanical:

- `bgpdd-shipping` Step 3's Runtime Evidence Gate derives `--changed-files`
  from `git diff <the default branch>...<branch>`, reading `branch` straight
  off this file. Pointed at a small fix branch, that diff is the fix and
  nothing else — the epic's entire body of work stops being under
  verification, and the gate passes on a set it was never meant to grade.
- `bgpdd-shipping` Step 4.5 pushes `branch` and opens the pull request on it.
  Pointed at the fix branch, shipping publishes the fix and leaves the epic
  unshipped, with a green launch report over it.

So on the feature route **the fix is made on the epic's existing branch**: read
`branch`, check it out, write the field never. The epic keeps one branch for its
whole life, which is what makes both downstream derivations correct by
construction rather than by a reader remembering this section. The `{bug-slug}`
scoping in `gates.jsonl` and the blockers ledger is what separates the fix from
the milestones around it — a separate branch was never carrying that, and a
separate `## Review:` and `test-report.md` section carry the rest.

Two consequences worth stating, because both used to read as gaps:

1. **The route rule is now an in-flight test, not a folder test.** A feature
   route requires the epic's state to exist *and* its `branch` to exist
   unmerged. `implementation/` outlives the epic — shipping Step 6.6 deletes
   only `orchestrator-state.json` — so folder presence alone would route a bug
   in long-shipped code onto a branch that no longer exists. Such a bug is
   standalone work and takes the standalone route.
2. **The feature route has no branch to close.** Phase 5 step 9's three offers
   (merge, publish-and-PR, keep) apply to a branch this lane created, which on
   the feature route it did not. Offering them there offers to close the
   *epic*; shipping Step 4.5 owns that. The commit is the close.

**And on the feature route the lane never touches `pipeline`.** A deliberate
divergence (convention #8) from the each-pipeline-stamps-its-own-value pattern
of Contract §4 that every other lane follows — and it is what makes sharing the
file safe:

- `/bgpdd-build` and `/bgpdd-shipping` re-hydrate the epic **exactly as they
  would have if the bugfix had never run**. No re-entry clause, no widened
  whitelist, no value for a downstream lane to reject. `bgpdd-shipping`
  Step 0.2 accepts only `bgpdd-build`/`bgpdd-shipping`, so stamping
  `bgpdd-bugfix` there would have locked the epic out of its own shipping lane.
- `check_commit_gate.py` never reads `pipeline`, so nothing this lane needs
  depends on it. That was a snapshot of one script's behaviour stated as a
  durable property, which is the shape convention #9 says to convert: it is
  now guarded by that script's own
  `test_pipeline_value_never_changes_the_verdict`, which asserts
  **byte-identical** verdict JSON across `bgpdd-build` / `bgpdd-bugfix` /
  `bgpdd-shipping` / `bgpdd-plan` / `bgpdd-lite` / `""` / a junk value / the
  field absent entirely, and that the report never echoes the field. A future
  term that read `pipeline` -- or merely reported it -- fails that test rather
  than silently breaking this lane.
- What records that the fix was gated is **`gates.jsonl`** — every entry scoped
  `milestone: {bug-slug}` — **plus the commit**. Both are durable,
  attributable, and re-readable by a later audit. A `pipeline` string was never
  the evidence; it was a routing hint, and this lane does not need routing.

**Blockers therefore always carry `--blocker-milestone "{bug-slug}"`**, on both
routes. On a shared epic file, scoping is precisely what stops a bugfix blocker
from freezing unrelated milestones — the opposite of the earlier design's "one
unit, so scoping asserts nothing", which was true of a private file and false of
this one. The reverse direction is real too, and worth knowing before the gate
says it: the epic's own **unscoped** blockers *do* block the bugfix commit, by
`check_commit_gate.py`'s fail-safe rule. `--ignore-unscoped` is the sanctioned
override; using it means reading those entries first and naming in the game tape
which ones you skipped.

**The file still survives the close** (deliberately unlike `bgpdd-shipping`
Step 6.6, convention #8): on the standalone route it and `gates.jsonl` are the
only record that the fix was gated, and on the feature route it is the epic's,
not this lane's to delete.

---

## Anti-patterns

- **Narrating the RED.** "The test fails as expected" in a handoff is a claim
  about a moment that no longer exists once the fix lands. Only a capture with
  its sidecar survives.
- **A bare `curl` as the reproduction command.** Exits 0 against a 500;
  `red_exit_zero`. Use `curl --fail`.
- **Re-taking the RED after the fix.** It will pass, and the pair will fail the
  ordering or exit-code check. Re-take only when the *reproduction itself* was
  wrong — and then re-take both, in order.
- **Widening the fix to "clean up while we're here".** The bound is five files;
  the waiver is for a fix that genuinely cannot fit, not for opportunistic
  refactoring. Route the cleanup separately.
- **Editing the RED test to make it pass.** Fails Phase 4's gate rather than
  passing it. If the RED test is wrong, that is a Phase 1 defect: say so and go
  back, do not fix it forward.
- **Scoping Quinn's suite to the fix.** A bugfix's characteristic escape is a
  correct local fix that breaks a distant caller, and a suite scoped to the
  changed files is structurally incapable of seeing it.
- **Inventing FR/NFR IDs.** There is no `requirements.md` here. `check_coverage.py`
  is not run, and a fabricated `FR-1` in the test report is a fabrication with a
  gate-shaped surface.
- **Filling `- Runtime observable:` by reflex.** `yes` for a pure logic defect
  buys a capture that proves nothing extra; `no` for a wire-visible defect skips
  the only gate that could prove the fix. Answer it from the observed symptom.

---

## Worked example — a .NET API returning 500 on a null coupon code

`{bug-slug}` = `coupon-500`; no `.docs/coupons/` folder exists, so
`{bugfix-root}` = `.docs/bugfix/coupon-500/`.

**Phase 0.** The Orchestrator writes `bug-report.md` with the user:
observed = `POST /api/orders` returns 500; expected = 400 with the error
envelope; error text = the pasted `NullReferenceException` frames;
`- Command: `curl --fail -sS -i http://localhost:5142/api/orders`` (backtick-wrapped,
four tokens — the intake gate rejects an unquoted value);
environment = `main`, `2.1.0`, .NET 8 on Windows; `- Regression: no`;
`- Surface: api`; `- Runtime observable: yes`.
`check_bugfix_intake.py … --ledger .docs/bugfix/coupon-500/gates.jsonl` → exit 0.
Standalone route, so `{state-file}` = `.docs/bugfix/coupon-500/orchestrator-state.json`
and the init carries the pipeline value: `update_state.py --state {state-file}
--init --project-name coupon-500 --set-pipeline bgpdd-bugfix --set-branch
fix/coupon-500`. (On a feature route Phase 0 writes no state at all: the epic's
own state file one level above `implementation/` must already exist -- HALT if
it does not -- and the run rides the `branch` that file already names, so there
is no `--init`, no `--set-pipeline` and no `--set-branch`.)

**Phase 1.** Quinn runs the reproduction through
`run_quiet.py --capture .docs/bugfix/coupon-500/evidence/red/coupon-500.md -- curl --fail …`.
`curl --fail` exits 22; the sidecar records `exit_code: 22` and the argv. She
reports the baseline suite green.

**Phase 2.** The Orchestrator traces `ApplyCoupon`, writes `rca.md` with one
hypothesis row (disproved: no upstream null guard), `- Root cause file:
src/Api/Coupons/ApplyCoupon.cs`, `- Baseline suite: green`,
`- New capability: no`, `- Schema or contract change: no`,
`- Estimated changed files: 2`. `next_bugfix_route.py --red
.docs/bugfix/coupon-500/evidence/red/coupon-500.md` → `FAST` (command
reproduction, **the RED sidecar's argv equals the report's command**, one
root-cause file, surface `api`, baseline green).

**Phase 3.** Mason is briefed with the root cause, `rca.md`, the RED capture's
path, `{bugfix-root}`, and the no-editing-the-RED rule. He returns
`<changed_files>` (2 files) and `<consumers>` (the three callers of
`ApplyCoupon`).

**Phase 4.** Quinn re-runs the identical `curl --fail` command, captured to
`evidence/runtime/coupon-500-green.md` with the Milestone/Surface/Transport
fields; exit 0. She runs the full suite through `run_quiet.py` and writes
`test-report.md` citing the capture. `check_red_green.py` → exit 0.
`check_runtime_evidence.py --surface api` → exit 0.

**Phase 5.** A fresh Luna reviews the 2-file diff against the `<consumers>` list
and writes `## Review: coupon-500` / `**Verdict:** Approve`. The commit gate runs
with `--verify-tree --max-changed-files 5 --waiver rca.md --require-ledger-gates
check_bugfix_intake.py,check_red_green.py,check_runtime_evidence.py` and commits
(2 files ≤ 5, so the waiver is never consulted). The Orchestrator states the fix,
finds no `.docs/summary/coupons/` base, so writes nothing to Tier 1 and says so,
and names `/bgpdd-shipping` as the re-entry.
