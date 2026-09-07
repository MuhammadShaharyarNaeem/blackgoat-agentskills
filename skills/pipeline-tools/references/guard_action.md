# guard_action.py — depth

Contract spine: `../SKILL.md`, `## guard_action.py`. This file carries the
rationale, the active-lane heuristic in full, the failure modes, the per-runtime
packaging and the self-test inventory.

## What failure this converts

Every other script in this family is a **verifier**: it reads artifacts after
the work and returns a verdict. That leaves one hole the family cannot close
from inside, because the hole is upstream of every gate — **the decision to run
the gate is the model's**. `check_commit_gate.py` cannot stop a commit it was
never invoked for. `bgpdd-bugfix` Phase 3's "the builder never edits the RED"
holds only as long as the builder chooses to be bound by it. Convention #9 says
a rule that asks an agent to restrain itself at the moment it most wants to
proceed must be enforced by an artifact that has to be run — but until now the
*running* was still voluntary.

`guard_action.py` is the first artifact in this plugin that the model does not
choose to invoke. The runtime invokes it, before the tool call, and the tool
call does not happen if it says no. That is the whole point: it moves four
restraints from "the model should not" to "the model cannot".

It is deliberately narrow. Four rules, each reading a real artifact, each with
a documented allow path. It is not a sandbox and not a permission system.

## The four rules

| # | id | Fires on | Reads |
|---|---|---|---|
| 1 | `commit_through_the_gate` | `Bash` + a history-writing `git` subcommand, any active lane | the lane's detection artifacts |
| 2 | `frozen_tests_during_a_fix` | a write tool + an **existing** test path, active bugfix lane pre-commit-gate | `gates.jsonl` |
| 3 | `no_delegation_before_intake` | `Task`/`Agent` + a fresh `bug-report.md` with no intake PASS | `bug-report.md` mtime, `gates.jsonl` |
| 4 | `gate_artifacts_are_written_by_tools` | a write tool + a gate artifact path | nothing — unconditional |

Rule 4 is evaluated **first and without lane detection**, because it is the only
one that holds unconditionally: `gates.jsonl`, `orchestrator-state.json`,
`run-log.jsonl` and `*.meta.json` sidecars are the evidence every other gate
reads. A hand edit to any of them does not just break one verdict, it makes
every downstream verdict unfalsifiable — the ledger stops being a record of what
ran and becomes a record of what someone typed.

Rule 1's allow-outside-a-lane is not a gap. `always-on.md` § *Outside any lane*
rule 3 already says a hand commit with no lane running is the user's call, made
knowingly; the guard enforces the lane half of that sentence and leaves the
other half alone.

Rule 2's new-file exception is what keeps the rule from forbidding the lane's
own use case. Quinn's job in a bugfix is to **add** the reproducing test; the
defect the rule catches is editing a test that already exists into agreement.
The mechanical form of that distinction is `path_exists()` — the same shape
`check_quick_close.py` uses for `frozen_path_modified`, where a newly ADDED test
passes and a MODIFIED tracked one does not.

## The active-lane heuristic

A lane is detected from **artifacts on disk**, never from a session flag, a
prose declaration or a model assertion. The guard has to be right in a session
that never announced which lane it was in — including a session that has
forgotten, or one that would rather not say.

Three detectors, all rooted at the hook's `cwd`, all using a 12-hour freshness
window (`--window-hours`):

- **(a) FEATURE** — `.docs/*/orchestrator-state.json` whose `pipeline` is a
  non-empty string, where that file **or** its sibling
  `implementation/gates.jsonl` was modified inside the window. Two mtimes
  rather than one because the two lanes that write this state disagree about
  which file moves: `/bgpdd-build` writes ledger lines continuously, while a
  lane sitting between milestones may only have touched state.
- **(b) BUGFIX** — `.docs/bugfix/*/bug-report.md` whose directory's
  `gates.jsonl` was modified inside the window.
- **(c) QUICK** — `.docs/quick/*/note.md` modified inside the window whose
  directory's `gates.jsonl` holds **no** `check_quick_close.py` PASS carrying
  `--commit`. The quick lane closes itself by committing, so its own close
  record is the signal that it is over — a cleaner end condition than mtime,
  and the reason this detector reads the ledger's `argv` and not just a verdict.

Freshness is `mtime`, not content. That is a deliberate trade: content-hashing
the tree on every tool call would put the guard in the latency path of the whole
session, and a 12-hour window is long enough to cover a working day and short
enough that a folder from last month does not haunt an unrelated change.

### Failure modes

Each of these is accepted, not overlooked. Every one of them fails **open**.

- **Phase-0 bugfix window.** Between writing `bug-report.md` and running the
  intake gate there is no ledger, so (b) reports no active lane and rule 1
  would allow a hand commit. Rule 3 deliberately does **not** depend on (b) —
  it keys off the report's own mtime — so the restraint that actually matters
  in that window still fires. Tightening (b) to the report's mtime instead
  would make every stale bug folder from last week block commits on unrelated
  work.
- **Stale lane.** A lane untouched for more than 12 hours stops being active
  and the guard stops blocking it. The alternative is a forgotten `.docs/`
  folder that bricks committing forever. Running any gate re-arms it.
- **Clock and checkout.** A fresh `clone`/`checkout`, or a machine whose clock
  moved, can make an old lane look active (over-block — recoverable via
  `--explain` and the named gate) or a new one look stale (under-block).
- **Wrong cwd.** Detection is rooted at the hook's `cwd`; a call issued from
  outside the repo sees no `.docs/`.
- **Non-native path form.** The interpreter must be able to resolve `cwd` as
  given. A Windows python handed an MSYS path (`/c/Users/...`) resolves
  nothing and allows — observed while building this file. Claude Code passes a
  native path, so this bites hand-built payloads, not the real hook.
- **Quoted commands.** Rule 1 matches the command **string**, so
  `echo "git commit"` is denied (over-block) while a commit reached through a
  shell alias, a script file or a heredoc is not (under-block). The regex does
  cover global options (`git -C <dir> commit`, `git -c user.name=x commit`),
  which is the one bypass common enough to matter.
- **Non-tool paths.** Anything not travelling through a guarded tool call — the
  user's own terminal, an MCP server that shells out, `Bash` redirecting into
  `gates.jsonl` (asserted in `test_29`) — is out of reach by construction.

The last one is worth stating plainly: **this guard raises the cost of the
wrong action; it does not make the repo tamper-proof.** A determined bypass is
always available. What it removes is the *accidental* bypass — the commit made
because finishing felt close, the test edited because it was in the way.

## Fail-open is a hard requirement

Any internal error — unparseable stdin, an unreadable `.docs/` tree, a bug in
the file — resolves to **allow**: exit 0, nothing on stdout, one diagnostic on
stderr. A guard that bricks a session gets removed within a day, and a removed
guard enforces nothing.

The design consequence is that **every deny is a positive identification**,
never the absence of a reason to allow. There is no code path where "I could
not tell" produces a block.

One bug found while testing this deserves recording, because it is the exact
shape the requirement exists to catch and it failed in the *dangerous*
direction. PowerShell 5.1 prefixes a UTF-8 BOM to anything it pipes to a native
executable. `json.loads` raises on a BOM. The raise was caught by the fail-open
handler — and so a deny silently became an allow, with the guard reporting
success. `read_stdin()` now reads **bytes** and decodes `utf-8-sig`, matching
this family's file-reading convention; `test_42` pins it.

## Why JSON on stdout, not exit code 2

The docs sanction both forms for `PreToolUse`: structured JSON on stdout with
exit 0, or exit 2 with the reason on stderr. This script emits JSON, for two
reasons.

1. It is the form that carries a structured `permissionDecision` alongside a
   `permissionDecisionReason` that is **fed back to the model**, so a deny
   reads as an instruction to take the gated path rather than as a tool crash.
   The end-to-end proof shows the model receiving the reason and restating it.
2. Decisively for this plugin: the Windows half of `hooks/run-hook.cmd` ends
   **every** branch with `exit /b 0`. An exit code from this script would be
   swallowed by the launcher and never reach the host. Only stdout survives the
   trip, so on Windows the exit-2 form would silently enforce nothing.

### Allow is silence, not `permissionDecision: "allow"`

An explicit `"allow"` from a `PreToolUse` hook **short-circuits the user's own
permission prompt**. This guard is a restraint, not a permission grant: it must
never convert a call the user would have been asked about into one they were
not. So an allow prints nothing and the host's normal permission flow runs
untouched. `test_39` pins this in both output formats.

## Per-runtime packaging (convention #5)

The decision logic lives **once**, here, runtime-neutral. What differs per host
is which event fires it and which JSON shape it reads:

| Runtime | Event | Wiring | Output |
|---|---|---|---|
| Claude Code | `PreToolUse` × 3 matchers | `hooks/hooks.json` → `run-hook.cmd guard-action` | `hookSpecificOutput.permissionDecision` |
| Cursor | `beforeShellExecution` | `hooks/hooks-cursor.json` (template → `.cursor/hooks.json`) | `permission` / `agent_message` |

Cursor's documented pre-execution hooks cover shell, MCP and file reads — not
file writes, and not subagent spawning. So **only rule 1 is mechanically
enforceable under Cursor**; rules 2–4 hold there as prose contract
(`rules/cursor-runtime.mdc`). `normalize_payload()` absorbs Cursor's flat
`beforeShellExecution` shape into the same `(tool_name, tool_input, cwd)` triple
the rest of the file works in, so no rule is written twice.

`hooks/guard-action` is the bash launcher: it resolves the plugin root and a
python, pipes stdin through, and passes stdout back. It holds **no rule text**.

## Tool-input path extraction

The published tool schemas disagree between doc pages on whether `MultiEdit`
puts `file_path` at the top level or inside each `edits[]` entry. Rather than
bet on one shape, `paths_of()` harvests `file_path`, `notebook_path`, `path`,
`filePath` and `file` from **both** the top level and every `edits[]` entry, and
denies if any of them matches. Guessing wrong here would be a silent hole in
rules 2 and 4 — the one failure this guard cannot afford, since a hole in a
guard is indistinguishable from the guard working.

Test-path matching is **case-insensitive on directory segments** (`tests`,
`test`, `__tests__`, `spec`), because `Tests/` is idiomatic in the .NET stack
this plugin supports, and separator-agnostic, because a Windows payload arrives
with backslashes (`test_17`).

## What 2.6.1 changed

Four findings from the 2026-09-07 gate-adversarial audit, all in this file.

**Rules 2 and 4 now see `Bash`.** Both were gated on `tool_name in
WRITE_TOOLS`, so the docstring's "always, lane or no lane" was false for the
one guarded tool that can write anything. Confirmed ALLOW with an active
bugfix lane, against `Edit`'s DENY on the same paths: `echo '{}' >>
gates.jsonl`, `| tee -a`, `python -c "open(...,'a').write(...)"`,
`Set-Content`, `sed -i tests/orders.test.js`, `perl -pi`, `mv test.js
test.js.old`, `git checkout -- tests/`, and `rm gates.jsonl` -- which also
ended the lane and re-enabled hand commits. `bash_write_targets()` now
extracts every path a shell command plausibly writes (the construct list is in
the module docstring under BASH WRITES). It OVER-collects candidates by
design: `is_gate_artifact()` matches four exact basenames plus the sidecar
suffix, and rule 2 additionally requires the path to exist, so a `sed` script
operand or a branch name after `git checkout` costs nothing. For rule 2 a test
DIRECTORY counts as well as a test file -- a deliberate widening (convention
#8) over the write-tool branch, which targets one file and for which `tests`
alone would be meaningless.

**The feature bugfix route is detected.** The 2.6.0 detector scanned
`.docs/bugfix/*` only, so a bug fixed inside an in-flight epic -- the route
`bgpdd-bugfix` mandates for exactly that case -- armed rule 1 and nothing
else: the builder could edit the RED and the Orchestrator could delegate
before intake. `bugfix_report_dirs()` now walks both routes and both feature
shapes (`implementation/bug-report.md` and
`implementation/bugs/<slug>/bug-report.md`), and `bugfix_ledger_for()` falls
back to the epic's `implementation/gates.jsonl` for a slug folder that has no
ledger of its own. Rule 3's predicate shares that walk, so the two routes
cannot drift apart again.

**Closed lanes stop arming rule 1.** The guard denied the local `git merge`
that `bgpdd-bugfix` Phase 5 and `bgpdd-lite` Phase 3 *instruct*, which is a
rule teaching people to work around it. A lane is closed once its ledger holds
a `check_commit_gate.py` PASS carrying `--commit` for the lane's current
milestone -- the bug slug, or `milestone_cursor`. Scoping it to the milestone
is what stops it becoming a blanket disarm; an unreadable milestone (a null
cursor, or the unscoped feature-route folder named `implementation`) is
treated as NOT closed, and `--explain` prints which lanes are armed and why.

**Verify lanes never armed rule 1 to begin with.** `bgpdd-verify` has no
commit gate -- Quinn's specs are committed by hand outside the lane -- so
arming rule 1 named a gate that does not exist and left the lane with no
commit path. The lane is still detected and rules 2-4 still apply.

Plus `GIT_WRITE_RE` widened to `am|rebase|stash [pop|apply]|notes|tag` beside
the original four, and a separate match for `gh pr merge`. `git push` and
`git replace` are deliberately outside it: neither writes local history that a
gate was supposed to author. `git tag` and `git stash` are in it even though
their read-only forms (`git tag -l`, `git stash list`) are then over-blocked
-- an over-block costs one `--explain`, an under-block costs a rewritten
history.

## Self-test inventory

**88** cases, `python guard_action.py --self-test`. The 2.6.0 forty-two below,
plus forty-six for the changes above:

- **Rule 4 through Bash (16)** — single and `>>` redirection, an fd-prefixed
  redirect, piped and bare `tee`, the four content cmdlets, the five item
  cmdlets, `python -c` opening in `w`/`a`/`r+`/`wb` (and ALLOW for a read),
  ten mutating verbs, renaming the ledger away, all four artifact kinds,
  case-insensitive and backslashed paths, `sed`/`perl` only with `-i`,
  `git checkout --` and `git restore`, no lane required — and four ALLOW cases
  (`cat`, `grep`, running `check_ledger.py`, `ls`) so the branch cannot be a
  blanket deny on any command that mentions a filename.
- **Rule 2 through Bash (7)** — seven mutating forms of an existing test path
  denied; `git checkout -- tests/` and `git restore tests` denied on the
  directory; a NEW test path allowed; a source path allowed; allowed with no
  bugfix lane and after the commit gate; four test-RUNNER commands allowed
  (`npm test`, `pytest tests/`, `dotnet test`, a Playwright run naming the
  spec) — running a test is not writing one.
- **The feature route (6)** — rules 2 and 3 armed by
  `implementation/bug-report.md` and by the slug-scoped shape; the epic-ledger
  fallback; rule 1 unaffected; the unscoped route reads no slug and is not
  closed.
- **Closed lanes (8)** — merge and commit allowed after a slug-scoped
  `--commit` PASS; a PASS for another milestone, an unscoped PASS, and a PASS
  without `--commit` all still deny; lite's cursor case; a null cursor still
  denies; an earlier milestone's commit does not close the epic; a closed lane
  still arms rule 4.
- **Verify lanes (3)** — rule 1 not armed; the lane is still detected and rule
  4 still fires on its ledger; a verify lane beside a build lane still denies.
- **The widened git surface (4)** — nine denied forms; `gh pr merge` named in
  its own message; eight read-only `git`/`gh` forms still allowed; the whole
  surface still lane-scoped.
- **Extractor and explain (2)** — quoting and segment handling, empty and
  `None` input; `--explain` reports per-lane arming.

The 2.6.0 forty-two:

- **Rule 1 (11)** — deny in each of the three lane kinds, the quick-lane reason
  naming `check_quick_close.py`; allow with no lane, with a 13-hour-stale lane,
  and with a quick lane already closed; `git commit --help` and `-h` allowed;
  `merge`/`revert`/`cherry-pick` denied; the global-option bypass closed;
  read-only git allowed; `legit commit` not matched.
- **Rule 2 (9)** — existing test edit denied; new test path allowed; allowed
  once the commit gate passed; allowed with no bugfix lane; source edit allowed;
  Windows separators; all four filename conventions; all four directory
  segments; a `MultiEdit` nested path seen.
- **Rule 3 (5)** — denied for `Task` and `Agent` before intake; allowed after;
  allowed when the report is stale; fires before any ledger exists; a `FAIL`
  intake record does not count as a PASS.
- **Rule 4 (4)** — all four artifact kinds denied; denied with no lane and for
  every write tool; ordinary `.json` files untouched; and
  `test_29_bash_may_not_be_used_to_dodge_rule_4`, which asserted the
  documented `Bash` redirection LIMIT in 2.6.0 and now asserts the DENY that
  replaced it.
- **Fail-open (6)** — malformed stdin (six shapes) allows; unknown tool allows;
  missing `tool_input` allows; a `.docs` that is a file yields no lanes; corrupt
  state and ledger do not raise; an empty `pipeline` is not a lane.
- **Contract (7)** — both payload shapes normalize; both deny payload shapes
  match their host; allow prints nothing in either format; `main` never exits
  non-zero; `--explain` runs; **BOM-prefixed stdin still denies**.
