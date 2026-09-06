# next_bugfix_route.py — depth

Contract spine: `../SKILL.md`, `## next_bugfix_route.py`. This file carries the
rationale, the route-rule reasoning and the self-test inventory.

## What failure this converts

`/bgpdd-bugfix` needs a fast path — most bugs are one file and a null check, and
pausing for the user five times to fix a typo is the kind of friction that gets
a lane abandoned. But a fast path chosen *by the Orchestrator, at the moment it
wants to proceed*, is convention #9's exact anti-pattern: the fork gets taken
fast for the wrong bug, and the phases the fast route skipped are the ones that
would have caught it.

So the fork is mechanical, and — crucially — **the fork controls only pauses**.
FAST and FULL differ in nothing but user check-ins. There is no route through
the lane that reaches a commit without RED, GREEN, Luna and the commit gate. A
fork that could skip a gate would be a fork worth gaming; this one is not.

## Why it refuses without a ledger-recorded intake PASS

The route reads `bug-report.md`. If it read it directly, the lane would route
off an unlinted report: no reproduction command, no surface enum, and FAST would
be decided on absent fields (`reproduction_mode: null` is not `"command"`, so it
would fall to FULL — but `- Surface:` would be `null` too, and a null surface
routing anywhere is a guess).

Requiring a ledger PASS gives two guarantees the file alone cannot:

1. **The gate actually ran** — a lint nobody invoked is indistinguishable from
   one that failed.
2. **The file has not changed since** — the recorded input sha256 is compared
   against the current bytes. Editing `- Surface: both` to `- Surface: api`
   after intake passed is the cheapest possible way into the FAST lane, and it
   is `intake_unbacked`, exit 2.

Matching is on the **hash**, not the path string: the earlier invocation
recorded the path exactly as it was given (`.docs/bugfix/x/bug-report.md`), and
this one may be handed an absolute path. Path-key equality would reject honest
pairs. A hash collision between two different bug reports is not a threat model
worth code.

**The lookup is scoped by `--milestone`** (fixed 2026-09). It used to take the
globally latest `check_bugfix_intake.py` record, which is right for one bug at a
time and wrong the moment two share a ledger: bug A's report is linted, bug B's
intake lands after it, and A's route then reads B's record, finds a hash that is
not A's, and reports that A's report *was edited after it passed intake* — a
false `intake_unbacked` whose message points at the wrong cause. With
`--milestone`, only records naming that milestone count; the fallback is
deliberately narrow (records carrying **no** milestone, i.e. an unscoped
invocation) and never another bug's. A scoped FAIL still blocks, so scoping
cannot route past one's own failed intake. **Pass the same `--milestone` to the
intake gate and to the route**, or there is nothing to match and the fallback
does the work.

`--ledger` is therefore required, not optional — the only gate in this family
for which the ledger is an *input*.

## Why `--red` is required, and why the match is exact

Phase 1 (RED) runs *before* this gate, so by the time a route is decided a real
capture of the failure already exists. Not comparing it left two holes:

1. **The intake gate's residual.** `` `see chat` `` is backtick-wrapped and two
   tokens, so it clears that text lint. No probe ever ran `see chat`, so the
   comparison here is what refuses it. This is the designed division of labour:
   a text lint bounds the *shape* of the value, and only an artifact can bound
   its *truth*.
2. **A capture of something else.** Quinn probes `/api/health` while the report
   reports `/api/orders`; both artifacts are honest and the pair proves nothing
   about the reported bug. `check_red_green.py` at Phase 4 catches RED/GREEN
   disagreeing with *each other*, but nothing tied either to the report.

### The comparison is on token lists, not strings

The first version compared `" ".join(sidecar["argv"])` against the report's
command string. That was wrong, and wrong in the direction that punishes
careful authors: **it rejected every correctly quoted command.** A report
saying

    - Command: `curl --fail -X POST http://host/orders -d '{}'`

is run verbatim by Quinn, the shell strips the quoting, and the sidecar records
argv `[..., '-d', '{}']` -- whose join is `-d {}`, which never equals the
report's `-d '{}'`. Every `-d '{...}'` body and every
`-H "Content-Type: application/json"` header hit it. The sidecar's `argv` is
the list the *process* received; the report's string is what a *shell* would be
given. Comparing them as strings compares two different things.

So `command_matches()` compares **token lists**, trying three candidates in
order and passing on any match:

1. **`shlex.split(command, posix=True)`** -- the shell's own rule. This is the
   candidate that makes quoted JSON bodies and quoted headers work.
2. **the same, with backslashes doubled first.** In posix mode `shlex` treats
   `\` as an escape, so a backslash-separated Windows path
   (`C:\repro\run.cmd`) would come back with its separators eaten. Doubling
   first makes it survive.
3. **a raw whitespace split** -- the original rule. Kept for two reasons: an
   unquoted command tokenizes identically under it, and it cannot be defeated
   by a `shlex` parse error (an unbalanced quote raises `ValueError`, that
   candidate is skipped, and this one still applies).

**Nothing fuzzier is tried**, and the self-test pins that: reordered tokens
still mismatch, a case difference still mismatches, and a genuinely different
URL still mismatches. Tolerance beyond tokenization would be this gate guessing
at semantics it does not implement, and the spine's remedy for a real mismatch
is trivial -- brief Quinn with the report's command copied verbatim (Phase 1
step 1 says exactly that).

`red_match_strategy` in the JSON names which candidate matched, so a report
that only passes via `whitespace` is visibly less well-formed than one that
passes via `shlex`.

**Corollary, stated in the template and enforced by construction**: a
`- Command:` value must be a single **argv-runnable** command -- no pipes, no
redirects, no `&&`. `run_quiet.py` executes argv directly with no shell, so a
shell-only construct is not re-runnable as written, and no tokenization of it
could ever match a real capture.

Ordering: the RED check runs **before** `rca.md` is read, so a RED that does not
back the report blocks (`BLOCKED`) regardless of whether the RCA is complete.
Reporting `INCOMPLETE` for an RCA whose route was never legitimate would send
the Orchestrator to fix the wrong artifact.

Only `argv` is read from the sidecar. The exit code and the `capture_sha256`
re-hash are `check_red_green.py`'s at Phase 4; duplicating them here would
create two gates that can disagree about which owns them.

## Why the report's fields come from the intake gate

Rather than re-parsing `bug-report.md`, this script runs
`check_bugfix_intake.py --report <path>` as a subprocess and reads its JSON —
the same pattern `check_commit_gate.py` uses for `check_runtime_evidence.py`,
and for the same reason. A second copy of the report parser would drift: the
masking rule, the placeholder set and the enum handling are all subtle, and the
two copies would disagree the first time either is fixed.

A child re-run that *disagrees* with the recorded PASS over the same bytes is
exit 2 with a message saying so. That should be impossible (same file, pure
function), so it is reported as an environment defect — a version skew between
the two scripts — never silently routed around.

## Route rules, term by term

**PLAN outranks everything.** It means *this is not a bugfix*:

- `- New capability: yes` — building something that does not exist is
  `/bgpdd-plan` work, and the bugfix lane has no requirements or design artifact
  to hang it on.
- `- Schema or contract change: yes` — Aria owns contracts; a bugfix that
  changes one has consumers to renegotiate, which is exactly the blast radius
  Phase 5 step 4 HALTs on anyway. Catching it at Phase 2 saves three
  delegations.
- `- Estimated changed files:` above `--max-changed-files` (default 5) — the
  same bound `check_commit_gate.py --max-changed-files` enforces at commit time.
  Declaring it early is cheaper than discovering it at the gate; the commit gate
  remains the enforcement, this is the early warning.

**FAST needs every term.** Each is a reason the lane can proceed unpaused:

- `reproduction_mode == "command"` — a single runnable command means Quinn's RED
  and GREEN are trivially the same thing, and `check_red_green.py`'s
  identical-`argv` check does the work a user check-in would otherwise do.
  Numbered steps mean Quinn *authors* a test to stand in for them, which is a
  judgement worth showing the user.
- exactly one `- Root cause file:` — one file is one fix. Two or more means the
  Orchestrator is asserting a relationship between files that nothing verified.
- surface `api` or `ui`, not `both` — `both` means two builders, concurrent
  write surfaces to partition, and one shared GREEN closing two diffs. Worth a
  pause.
- `- Baseline suite: green` — a suite already red cannot distinguish this fix's
  regression from the standing one, so Phase 4's full-suite floor is degraded
  and the user should know before the fix, not after.

**FULL otherwise**, with the failing terms printed as `reasons`. FULL is not a
punishment; it is the default, and FAST is the narrow exception.

## Why `INCOMPLETE` is exit 1

`next_milestone.py` returns exit 1 with `result: MIXED` for "the plan cannot be
executed as written". This mirrors it deliberately: an RCA missing
`- Baseline suite:` or any `- Root cause file:` cannot be *routed* as written,
and the Orchestrator's action is identical to the MIXED case — fix the artifact,
re-run, do not improvise past it. Making it exit 0 with `route: null` would
invite exactly that improvisation.

A missing `- Estimated changed files:` is the one field that only **warns**: the
commit gate still enforces the bound, so the route is decidable without it.

## rca.md grammar notes

- Fields are read **file-wide**, last mention winning. An appended
  `## Correction` section supersedes an earlier line, which is how an RCA
  revised after a failed fix round stays honest without rewriting history.
- `- Root cause file:` (and `- Root cause files:`) is the only repeatable key;
  every occurrence with a non-placeholder value is kept.
- Fences are **blanked** (the family's normal rule — unlike
  `check_bugfix_intake.py`, which masks; see that file's reference for why the
  divergence is scoped to the report and not here). A `## Fix shape` block
  pasted as a template asserts nothing and lands as `INCOMPLETE`.

## Self-test inventory (52 cases)

- **FAST (2)** — the happy path and its exit 0, including the assertion that the
  printed reasons say the routes differ only in check-ins.
- **`--red` (12)** — the FAST reasons name the RED tie; `--red` omitted with a
  command report is exit 2 (`red_required`); a mismatched command blocks and
  exits 1; backticked `` `see chat` `` is refused *here*; a missing sidecar, a
  missing capture file, and an argv-less sidecar each block; whitespace is
  collapsed before comparing; a steps-only report neither requires nor checks
  `--red` (and warns when one is passed anyway); the RED block precedes the RCA
  read.
- **Quoting / tokenization (8)** — a single-quoted `'{}'` body matches via
  `shlex`; a single-quoted JSON object with fields matches; a double-quoted
  header containing a space matches via `shlex`; a backslash-separated Windows
  path matches via `shlex-escaped` or `whitespace`; a genuinely different URL
  still mismatches; **reordered** tokens still mismatch; a **case** difference
  still mismatches; an unbalanced quote falls back to the whitespace candidate
  instead of raising.
- **FULL (5)** — steps-only reproduction; two root-cause files; `Surface: both`;
  baseline red; baseline `not run`.
- **PLAN (6)** — new capability; schema/contract change; over the bound; exactly
  at the bound is *not* PLAN; `--max-changed-files` override moves the boundary
  both ways; PLAN outranks a would-be FAST.
- **INCOMPLETE (4)** — missing `- Baseline suite:`; no `- Root cause file:`;
  missing `## Fix shape` flags; the exit-1 mapping.
- **Intake backing, adversarial (8)** — no intake entry; an intake FAIL entry;
  a PASS whose hash no longer matches an edited report; a later FAIL superseding
  an earlier PASS; a PASS recorded under a different path string is accepted;
  two interleaved bugs in one ledger (unscoped reads the wrong record and
  refuses, `--milestone` finds its own); a scoped FAIL for this bug still
  blocks; a milestone-less PASS still backs a scoped route.
- **Parsing (3)** — fenced RCA fields route nothing; last mention wins; a
  missing estimate warns but still routes.
- **Usage + ledger (4)** — missing `--rca` file is exit 2; missing `--ledger` is
  exit 2; the ledger records the route run with the RCA's hash; the ledger
  records the refusal as ERROR.

## Scope limits

- It reads what the RCA **declares**. An RCA that understates the fix
  understates the route — stated in the lane's own Limitations section.
- It does not verify the root-cause file exists or that it is the actual cause.
  `check_commit_gate.py --changed-files` and Luna cover the first; the
  hypothesis ledger and Contract §3a cover the second.
