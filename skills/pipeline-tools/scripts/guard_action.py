#!/usr/bin/env python3
"""Pre-execution guard: converts four restraint rules from "should not" to "cannot".

Every other script in this family verifies AFTER the fact, and the decision to
run it is the model's. This one runs BEFORE the tool call, decided by the
runtime rather than by the model, and returns a deny that the model cannot
route around. It is the mechanical form of CLAUDE.md convention #9 applied to
the four restraints that bite at the exact moment the model most wants to
proceed: committing, editing the RED, delegating before intake, and hand-
writing the artifacts the gates read.

This file is the DECISION LOGIC and it is runtime-neutral (convention #5).
The per-runtime packaging -- which hook event fires it, and which JSON shape
the host reads -- lives in `hooks/hooks.json` (Claude Code),
`hooks/hooks-cursor.json` (Cursor) and the `--format` flag below. No rule text
is duplicated into either.

THE FOUR RULES
--------------
1. `commit_through_the_gate` -- tool `Bash`, a history-writing `git`
   invocation (`commit|merge|cherry-pick|revert|rebase|am|notes|tag|stash`) or
   `gh pr merge`, while a lane is ACTIVE and NOT yet closed -> DENY, naming
   the gate that commits for that lane. The gates commit from their own
   subprocess, not through the model's Bash tool, so this can never block a
   gate. Outside any lane the call is allowed: `always-on.md` § Outside any
   lane rule 3 makes a hand commit the user's call. Two carve-outs, both read
   from artifacts (see CLOSED LANES and VERIFY below).
2. `frozen_tests_during_a_fix` -- a write targeting an EXISTING test path
   while a BUGFIX lane is active and its ledger holds no
   `check_commit_gate.py` PASS -> DENY. "A write" is a write TOOL (`Edit`,
   `Write`, `MultiEdit`, `NotebookEdit`) or a `Bash` command that mutates the
   path (see BASH WRITES). A path that does not exist yet is allowed: adding
   a new test is not editing the RED.
3. `no_delegation_before_intake` -- a delegation tool while a fresh
   `bug-report.md` exists whose ledger lacks a `check_bugfix_intake.py` PASS
   -> DENY.
4. `gate_artifacts_are_written_by_tools` -- a write targeting `gates.jsonl`,
   `orchestrator-state.json`, `run-log.jsonl` or a `*.meta.json` sidecar ->
   DENY, always, lane or no lane. "A write" again covers write TOOLS and
   `Bash` (see BASH WRITES). These are the evidence the other gates read; a
   hand edit to any of them makes every verdict downstream unfalsifiable.

BASH WRITES (rules 2 and 4)
---------------------------
Until 2.6.1 rules 2 and 4 tested only `tool_name in WRITE_TOOLS`, so the
docstring's "always, lane or no lane" was false for the one guarded tool that
can write anything: `echo '{}' >> gates.jsonl`, `| tee -a`, `Set-Content`,
`python -c "open(...,'a')"`, `sed -i tests/x.test.js`, `mv test.js test.js.old`
and `git checkout -- tests/` were all ALLOW while `Edit` on the same path was
DENY. `bash_write_targets()` now extracts every path a shell command
plausibly WRITES:

  * redirection -- `>` / `>>` (any leading fd digit), per `;`/`&`/`|`/newline
    segment;
  * a write VERB and its operands -- `tee`, `mv`/`move`, `cp`/`copy`,
    `rm`/`del`/`erase`, `ren`/`rename`, `truncate`, and the PowerShell
    cmdlets `Set-Content`, `Add-Content`, `Out-File`, `Clear-Content`,
    `New-Item`, `Move-Item`, `Copy-Item`, `Remove-Item`, `Rename-Item`;
  * `sed` / `perl` ONLY with an in-place flag (`-i`, `-i.bak`, `-pi`) --
    without it they write to stdout and mutate nothing;
  * `python -c` whose code opens a path in a writing mode
    (`open(<path>, 'w'|'a'|'...+')`);
  * `git checkout -- <paths>` and `git restore <paths>`, which overwrite a
    working-tree file from the index.

The extractor deliberately OVER-collects candidates (a `sed` script operand,
a branch name after `git checkout`) and lets the two narrow predicates decide:
`is_gate_artifact()` matches four exact basenames plus the sidecar suffix, and
rule 2 additionally requires the path to EXIST. A candidate that is neither
costs nothing. Matching is case-insensitive and separator-agnostic, so a
Windows path written with backslashes and an upper-case `GATES.JSONL` matches.

ACTIVE-LANE DETECTION, AND WHY IT READS THE TREE
------------------------------------------------
A lane is detected from ARTIFACTS ON DISK, never from prose, a session flag or
a model assertion -- the guard has to be right in a session that never said
which lane it was in. Four detectors, all relative to the hook's `cwd`, all
using a 12-hour freshness window (`--window-hours`):

  (a) FEATURE  `.docs/*/orchestrator-state.json` whose `pipeline` is a
      non-empty string, where that file OR its sibling
      `implementation/gates.jsonl` was modified inside the window.
  (b) BUGFIX (standalone route) `.docs/bugfix/*/bug-report.md` whose
      directory's `gates.jsonl` was modified inside the window.
  (c) BUGFIX (feature route) `.docs/*/implementation/bug-report.md` and
      `.docs/*/implementation/bugs/*/bug-report.md` -- the paths
      `bgpdd-bugfix` § Route detection mandates for a bug found inside an
      in-flight epic -- with a fresh `gates.jsonl` beside the report, or, when
      the report is slug-scoped and has no ledger of its own, the epic's
      `implementation/gates.jsonl`. Detector (a) may report the same epic as a
      FEATURE lane; both stand, and the bugfix lane is what arms rules 2
      and 3. Until this detector existed, a bug fixed on the feature route
      armed rule 1 only: the builder could edit the RED and the Orchestrator
      could delegate before intake.
  (d) QUICK    `.docs/quick/*/note.md` modified inside the window, whose
      directory's `gates.jsonl` holds no `check_quick_close.py` PASS carrying
      `--commit` (i.e. the lane has not closed itself yet).

CLOSED LANES (rule 1's carve-out)
---------------------------------
Rule 1 exists to route the commit through the gate -- not to forbid the close
the pipelines mandate AFTER it. `bgpdd-bugfix` Phase 5 and `bgpdd-lite`
Phase 3 both end in a local `git merge` of the lane's branch, and the guard
denied exactly that. A lane is therefore CLOSED, and stops arming rule 1, once
its own ledger holds a `check_commit_gate.py` PASS whose `argv` carries
`--commit` for the lane's CURRENT milestone:

  * bugfix -- the bug slug (the lane directory's name);
  * feature / lite -- `milestone_cursor` from the lane's state file.

The milestone scope is what keeps this from being a blanket disarm: an epic
that committed M1 still arms rule 1 while the cursor points at M2. When the
milestone cannot be read (a null cursor, or the unscoped feature-route report
whose directory name is `implementation` rather than a slug) the lane is
treated as NOT closed -- fail-closed, and `--explain` says so. Quick keeps its
own, older predicate: a `check_quick_close.py --commit` PASS removes the lane
from detection entirely.

VERIFY LANES DO NOT ARM RULE 1
------------------------------
A state file whose `pipeline` is `bgpdd-verify` is detected as a lane (so
`--explain` shows it) but does not arm rule 1. `bgpdd-verify` has no commit
gate: its only durable output is Quinn's Playwright specs, which are committed
by hand outside the lane, so arming rule 1 there names a gate that does not
exist and leaves the lane with no commit path at all. Rules 2, 3 and 4 are
unaffected -- rule 4 in particular still guards the verify lane's ledger.

Known failure modes, each deliberate rather than overlooked:

  * PHASE-0 BUGFIX WINDOW. Between writing `bug-report.md` and running the
    intake gate, the ledger does not exist, so (b)/(c) report no active lane
    and rule 1 would allow a hand commit. Rule 3 deliberately does NOT depend
    on (b)/(c): it keys off the report's own mtime, so the restraint that
    actually matters in that window -- do not delegate yet -- still fires.
    Accepted: tightening (b) to the report's mtime would make every stale bug
    folder from last week block commits for an unrelated change.
  * STALE LANE. A lane abandoned more than 12 hours ago stops being active and
    the guard stops blocking. This is the intended trade: the alternative is a
    forgotten `.docs/` folder that bricks committing forever. Touching the
    ledger (running any gate) re-arms it -- and, symmetrically, `touch`ing or
    renaming the ledger DISARMS it. Rule 4 now blocks a `Bash` rename or
    delete of the ledger itself, which was the cheapest form of that
    disarm; a `touch` of an unprotected sibling still ages the lane out.
  * CLOCK AND CHECKOUT. Freshness is mtime, so a fresh `git checkout`, a
    `git clone`, or a machine whose clock moved can make an old lane look
    active (over-blocking, recoverable by `--explain` + the named gate) or a
    new one look stale (under-blocking).
  * WRONG CWD. Detection is rooted at the hook's `cwd`. A tool call issued
    with a cwd outside the repo sees no `.docs/` and no lane.
  * NON-NATIVE PATH FORM. The interpreter has to be able to resolve `cwd` as
    given. A Windows python handed an MSYS path (`/c/Users/...`) resolves
    nothing, finds no `.docs/`, and allows -- observed while testing this
    file. Claude Code passes a native path, so this bites hand-built payloads
    and shell wrappers rather than the real hook, but it fails OPEN either
    way, which is the correct direction for a mistake of this kind.
  * QUOTED COMMANDS. Rule 1 matches the command STRING, so
    `echo "git commit"` is denied (over-block) while a commit reached through
    a shell alias (`git cm`), a script file, `Start-Process git -ArgumentList
    commit`, or a `subprocess.run(['git','commit'])` with no whitespace
    between the tokens is not (under-block). The regex does cover global
    options (`git -C <dir> commit`), which is the one bypass common enough to
    matter. `git tag` and `git stash` are in the list even though their
    read-only forms (`git tag -l`, `git stash list`) are then over-blocked:
    an over-block costs one `--explain`, an under-block costs a rewritten
    history.
  * BASH WRITE EXTRACTION IS HEURISTIC. It reads a command string, not a
    shell. A path built by variable expansion (`$LEDGER`), reached through a
    script file, produced by a here-document, or written by an editor spawned
    from the command is invisible; a directory-level `Remove-Item .docs
    -Recurse` names no protected basename and is allowed. Every one of those
    fails OPEN, which is the correct direction: the rule raises the cost of
    the wrong action, it does not make the tree read-only.
  * NON-TOOL PATHS. Anything that does not travel through a guarded tool call
    -- a terminal the user drives, an MCP server that shells out -- is out of
    reach by construction. This guard raises the cost of the wrong action; it
    does not make the repo tamper-proof.

FAIL-OPEN IS A HARD REQUIREMENT
-------------------------------
Any internal error -- unparseable stdin, an unreadable `.docs/` tree, a bug in
this file -- results in ALLOW: exit 0, nothing on stdout, one diagnostic line
on stderr. A guard that bricks a session would be removed within a day, and a
removed guard enforces nothing. Every deny in this file is therefore a
positive identification, never the absence of a reason to allow.

Fail-open is a property of the guard's ERROR handling, not a licence for a
rule to be silently unarmed: the 2.6.0 state of rules 2 and 4 (no `Bash`
branch at all) was not a fail-open, it was a rule that did not exist for the
one tool that mattered. The distinction is why `--explain` prints which rule
is armed for what, and why the self-test asserts a DENY for every mutating
verb rather than only for the write tools.

WHY JSON-ON-STDOUT AND NOT EXIT 2
---------------------------------
The docs sanction both forms for PreToolUse: structured JSON on stdout with
exit 0, or exit 2 with the reason on stderr. This script emits the JSON form,
for two reasons. First, it is the form that carries a structured
`permissionDecision` plus a `permissionDecisionReason` that is fed back to the
model, so a deny reads as an instruction to take the gated path rather than as
a tool crash. Second, and decisively for this plugin: the Windows half of
`hooks/run-hook.cmd` ends every branch with `exit /b 0`, so an exit code from
this script would be swallowed by the launcher and never reach the host. Only
stdout survives that trip.

ALLOW IS SILENCE, NOT `permissionDecision: "allow"`
---------------------------------------------------
An explicit `"allow"` from a PreToolUse hook SHORT-CIRCUITS the user's own
permission prompt. This guard is a restraint, not a permission grant: it must
never turn a call the user would have been asked about into one they were not.
So an allow prints nothing and the host's normal permission flow runs
untouched.

Pure standard library. Every file is read as utf-8-sig, so a BOM cannot break
parsing. All output is ASCII.

Usage:
    guard_action.py [--format claude|cursor] [--window-hours N] < hook.json
    guard_action.py --explain [--cwd DIR] [--window-hours N]
    guard_action.py --self-test
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

READ_ENCODING = "utf-8-sig"
WINDOW_HOURS_DEFAULT = 12

# Tool names, by role. Matched exactly against `tool_name`; the host-side
# matcher in hooks.json is a coarse pre-filter, this is the real check.
BASH_TOOLS = ("Bash",)
WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
DELEGATION_TOOLS = ("Task", "Agent")

# `tool_input` keys that can carry a target path. The published tool schemas
# disagree between doc pages on whether MultiEdit puts `file_path` at the top
# level or inside each `edits[]` entry, so this collects BOTH rather than
# betting on one shape -- guessing wrong would be a silent hole in rules 2
# and 4, which is the one failure this guard cannot afford.
PATH_KEYS = ("file_path", "notebook_path", "path", "filePath", "file")

TEST_DIR_SEGMENTS = ("tests", "test", "__tests__", "spec")
TEST_FILE_PATTERNS = (
    r"^.+\.test\.[^.]+$",
    r"^.+\.spec\.[^.]+$",
    r"^test_.+\.py$",
    r"^.+_test\.go$",
)

GATE_ARTIFACT_NAMES = ("gates.jsonl", "orchestrator-state.json", "run-log.jsonl")
GATE_ARTIFACT_SUFFIX = ".meta.json"

# A pipeline whose lane has no commit gate: it arms every rule EXCEPT rule 1.
NO_COMMIT_GATE_PIPELINES = ("bgpdd-verify",)

# `git`, any number of global options, then a history-writing subcommand.
# `stash` captures its `pop`/`apply` tail so the deny message can name it.
GIT_WRITE_RE = re.compile(
    r"\bgit\b(?:\s+(?:-[cC]\s+\S+|--\S+|-\w))*\s+"
    r"(stash(?:\s+(?:pop|apply))?|cherry-pick|commit|merge|revert|rebase|am|"
    r"notes|tag)\b"
)
# `gh pr merge` writes the same history through a different binary.
GH_WRITE_RE = re.compile(r"\bgh\s+pr\s+merge\b")
HELP_RE = re.compile(r"(?:^|\s)(--help|-h)(?=\s|$)")
COMMAND_SEPARATORS = re.compile(r"[;&|\n]")

# --- Bash write extraction (rules 2 and 4); see BASH WRITES in the docstring.
# One shell token: a double-quoted run, a single-quoted run, or a bare run.
BASH_TOKEN_RE = re.compile(r'"[^"]*"|\'[^\']*\'|\S+')
# `>` or `>>`, optionally preceded by an fd digit, then the target token.
BASH_REDIRECT_RE = re.compile(
    r'\d?>>?\s*("[^"]*"|\'[^\']*\'|[^\s;&|<>"\']+)')
# Commands whose operands are things they WRITE. Matched on the token's
# basename, lower-cased, with a Windows executable suffix stripped.
BASH_WRITE_VERBS = (
    "tee", "sed", "perl",
    "mv", "move", "cp", "copy", "rm", "del", "erase", "ren", "rename",
    "truncate", "shred",
    "set-content", "add-content", "out-file", "clear-content",
    "new-item", "move-item", "copy-item", "remove-item", "rename-item",
)
# `sed`/`perl` mutate a file only in place; without the flag they write stdout.
BASH_INPLACE_VERBS = ("sed", "perl")
INPLACE_FLAG_RE = re.compile(r"^-[A-Za-z]*i")
EXECUTABLE_SUFFIXES = (".exe", ".cmd", ".bat", ".ps1", ".com")
PYTHON_TOKEN_RE = re.compile(r"(?:^|[\s/\\])(?:python\d?(?:\.\d+)?|py)(?:\.exe)?(?=\s|$)",
                             re.IGNORECASE)
PYTHON_DASH_C_RE = re.compile(r"(?:^|\s)-c(?=\s|$)")
PY_OPEN_WRITE_RE = re.compile(
    r"""open\s*\(\s*(?P<q>['"])(?P<p>[^'"]+)(?P=q)\s*,\s*"""
    r"""(?P<mq>['"])(?P<m>[^'"]*)(?P=mq)""")
# `git checkout -- <paths>` / `git restore <paths>` overwrite the working tree.
GIT_RESTORE_RE = re.compile(
    r"\bgit\b(?:\s+(?:-[cC]\s+\S+|--\S+|-\w))*\s+(checkout|restore)\b(?P<rest>[^;&|\n]*)")


class GuardError(Exception):
    """Anything this script could not do. Always resolves to ALLOW."""


# ---------------------------------------------------------------------------
# Filesystem helpers -- every one of them fails soft
# ---------------------------------------------------------------------------

def _mtime(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


def _fresh(path, now, window_hours):
    """True when `path` exists and was modified inside the window."""
    stamp = _mtime(path)
    if stamp is None:
        return False
    return (now - stamp) <= (window_hours * 3600.0)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding=READ_ENCODING))
    except (OSError, ValueError):
        return None


def read_ledger(path):
    """Every parseable record in a gates.jsonl. A bad line is skipped, not fatal."""
    records = []
    try:
        text = Path(path).read_text(encoding=READ_ENCODING, errors="replace")
    except OSError:
        return records
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def ledger_has_pass(path, gate_name, require_flag=None, milestone=None):
    """True when the ledger holds a PASS for `gate_name`.

    `require_flag` additionally demands that flag in the record's `argv`;
    `milestone` demands an exact match on the record's `milestone` field. A
    `milestone` of None means "any", so callers that cannot name the lane's
    milestone must decide for themselves whether that is safe -- the closed-
    lane predicate below refuses to, and fails closed instead.
    """
    for record in read_ledger(path):
        if record.get("gate") != gate_name:
            continue
        if record.get("verdict") != "PASS":
            continue
        if require_flag is not None:
            argv = record.get("argv")
            if not isinstance(argv, list) or require_flag not in argv:
                continue
        if milestone is not None and record.get("milestone") != milestone:
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# Active-lane detection
# ---------------------------------------------------------------------------

class Lane(object):
    """One detected lane: what kind, where, and which gate commits for it."""

    def __init__(self, kind, root, ledger, gate, detail="", milestone=None,
                 arms_commit_rule=True, closed=False):
        self.kind = kind          # "feature" | "bugfix" | "quick"
        self.root = root          # the lane's directory
        self.ledger = ledger      # its gates.jsonl (may not exist)
        self.gate = gate          # the gate that commits for this lane
        self.detail = detail
        self.milestone = milestone            # the lane's current milestone
        self.arms_commit_rule = arms_commit_rule   # False for verify lanes
        self.closed = closed      # its commit gate already committed the close

    def arms_rule_1(self):
        """True when this lane should still deny a hand `git commit`/`merge`."""
        return self.arms_commit_rule and not self.closed

    def __repr__(self):  # pragma: no cover -- diagnostics only
        return "Lane({0}, {1})".format(self.kind, self.root)


def _iter_dirs(parent):
    try:
        return sorted(p for p in Path(parent).iterdir() if p.is_dir())
    except OSError:
        return []


def bug_slug_of(bugdir):
    """The bug slug a bugfix lane's ledger records as its `--milestone`.

    The lane directory's own name, EXCEPT on the unscoped feature route where
    that name is `implementation` (the epic's directory, shared with every
    other artifact). There the slug is unknowable from the path, so this
    returns None and the closed-lane predicate fails closed.
    """
    name = Path(bugdir).name
    return None if name.lower() == "implementation" else name


def bugfix_report_dirs(cwd):
    """Every directory holding a `bug-report.md`, standalone and feature route.

    Detectors (b) and (c) share this walk so the two routes can never drift
    apart -- the 2.6.0 hook scanned `.docs/bugfix/*` only, and a bug fixed
    inside an in-flight epic armed no write rule at all.
    """
    docs = Path(cwd) / ".docs"
    found = []

    def offer(directory):
        if (directory / "bug-report.md").is_file() and directory not in found:
            found.append(directory)

    for bugdir in _iter_dirs(docs / "bugfix"):     # (b) standalone route
        offer(bugdir)
    for project in _iter_dirs(docs):               # (c) feature route
        implementation = project / "implementation"
        if not implementation.is_dir():
            continue
        offer(implementation)
        for slugdir in _iter_dirs(implementation / "bugs"):
            offer(slugdir)
    return found


def bugfix_ledger_for(bugdir):
    """The ledger a bugfix lane's verdicts land in.

    Its own `gates.jsonl` when one exists; otherwise, for a slug-scoped
    feature-route folder, the epic's `implementation/gates.jsonl` one level up
    (`bgpdd-bugfix` shares the epic's ledger on that route). Falls back to the
    folder's own path so a caller always has something to test for freshness.
    """
    own = Path(bugdir) / "gates.jsonl"
    if own.is_file():
        return own
    parent = Path(bugdir).parent
    if parent.name.lower() == "bugs":
        shared = parent.parent / "gates.jsonl"
        if shared.is_file():
            return shared
    return own


def detect_lanes(cwd, now=None, window_hours=WINDOW_HOURS_DEFAULT):
    """Return every ACTIVE lane under `cwd`, read from artifacts on disk.

    Never raises: an unreadable tree yields no lanes, which yields allow.
    """
    if now is None:
        now = time.time()
    lanes = []
    docs = Path(cwd) / ".docs"
    if not docs.is_dir():
        return lanes

    # (a) FEATURE -- .docs/*/orchestrator-state.json with a non-empty pipeline.
    for project in _iter_dirs(docs):
        state_path = project / "orchestrator-state.json"
        if not state_path.is_file():
            continue
        state = _read_json(state_path)
        if not isinstance(state, dict):
            continue
        pipeline = state.get("pipeline")
        if not isinstance(pipeline, str) or not pipeline.strip():
            continue
        ledger = project / "implementation" / "gates.jsonl"
        if not (_fresh(ledger, now, window_hours)
                or _fresh(state_path, now, window_hours)):
            continue
        cursor = state.get("milestone_cursor")
        milestone = cursor if isinstance(cursor, str) and cursor.strip() else None
        arms = pipeline.strip() not in NO_COMMIT_GATE_PIPELINES
        lanes.append(Lane(
            "feature", str(project), str(ledger),
            "check_commit_gate.py",
            "pipeline={0}{1}".format(
                pipeline.strip(),
                "" if arms else "; no commit gate, rule 1 not armed"),
            milestone=milestone,
            arms_commit_rule=arms,
            closed=lane_is_closed(str(ledger), milestone),
        ))

    # (b)+(c) BUGFIX -- standalone and feature route, ledger fresh.
    for bugdir in bugfix_report_dirs(cwd):
        ledger = bugfix_ledger_for(bugdir)
        if not _fresh(ledger, now, window_hours):
            continue
        slug = bug_slug_of(bugdir)
        lanes.append(Lane(
            "bugfix", str(bugdir), str(ledger),
            "check_commit_gate.py",
            detail="" if slug else "unscoped feature route: no readable slug",
            milestone=slug,
            closed=lane_is_closed(str(ledger), slug),
        ))

    # (d) QUICK -- .docs/quick/*/note.md fresh and not yet closed.
    for quickdir in _iter_dirs(docs / "quick"):
        note = quickdir / "note.md"
        if not _fresh(note, now, window_hours):
            continue
        ledger = quickdir / "gates.jsonl"
        if ledger_has_pass(str(ledger), "check_quick_close.py", "--commit"):
            continue
        lanes.append(Lane(
            "quick", str(quickdir), str(ledger),
            "check_quick_close.py",
        ))

    return lanes


def lane_is_closed(ledger, milestone):
    """True when this lane's commit gate already committed its current milestone.

    See CLOSED LANES in the module docstring. `milestone` of None -> False:
    a lane whose milestone cannot be read is never treated as closed, because
    "any commit-gate PASS in this ledger" would disarm rule 1 for a whole epic
    the moment its first milestone landed.
    """
    if not milestone:
        return False
    return ledger_has_pass(ledger, "check_commit_gate.py", "--commit", milestone)


def pending_bugfix_intakes(cwd, now=None, window_hours=WINDOW_HOURS_DEFAULT):
    """Bugfix folders with a fresh report and no intake PASS (rule 3's predicate).

    Deliberately keyed on the REPORT's mtime rather than on `detect_lanes`
    detectors (b)/(c): before the intake gate runs there is no ledger to be
    fresh, and that pre-intake window is exactly when rule 3 has to hold.
    Both routes are covered -- the feature route's Phase 0 gate is the same
    `check_bugfix_intake.py`.
    """
    if now is None:
        now = time.time()
    pending = []
    for bugdir in bugfix_report_dirs(cwd):
        report = bugdir / "bug-report.md"
        if not _fresh(report, now, window_hours):
            continue
        ledger = bugfix_ledger_for(bugdir)
        if ledger_has_pass(str(ledger), "check_bugfix_intake.py"):
            continue
        pending.append(Lane("bugfix", str(bugdir), str(ledger),
                            "check_bugfix_intake.py",
                            milestone=bug_slug_of(bugdir)))
    return pending


def unfixed_bugfix_lanes(lanes):
    """Active bugfix lanes whose ledger holds no commit-gate PASS (rule 2's)."""
    return [lane for lane in lanes
            if lane.kind == "bugfix"
            and not ledger_has_pass(lane.ledger, "check_commit_gate.py")]


# ---------------------------------------------------------------------------
# Payload normalization -- one shape in, whatever the host sent
# ---------------------------------------------------------------------------

def normalize_payload(payload):
    """(tool_name, tool_input, cwd) from a Claude Code or Cursor hook payload."""
    if not isinstance(payload, dict):
        raise GuardError("hook payload is not a JSON object")

    event = payload.get("hook_event_name")
    cwd = payload.get("cwd") or payload.get("workspace_roots") or os.getcwd()
    if isinstance(cwd, list):
        cwd = cwd[0] if cwd else os.getcwd()
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()

    # Cursor's beforeShellExecution is flat: the command sits at the top level.
    if event == "beforeShellExecution":
        return "Bash", {"command": payload.get("command")}, cwd

    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str):
        raise GuardError("hook payload carries no string tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    return tool_name, tool_input, cwd


def command_of(tool_input):
    value = tool_input.get("command")
    return value if isinstance(value, str) else ""


def paths_of(tool_input):
    """Every plausible target path in a write tool's input, both schema shapes."""
    found = []

    def harvest(container):
        if not isinstance(container, dict):
            return
        for key in PATH_KEYS:
            value = container.get(key)
            if isinstance(value, str) and value:
                found.append(value)

    harvest(tool_input)
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            harvest(edit)

    ordered = []
    for path in found:
        if path not in ordered:
            ordered.append(path)
    return ordered


# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------

def _segments(path):
    """Path segments, separator-agnostic (a Windows path arrives with '\\')."""
    return [s for s in path.replace("\\", "/").split("/") if s and s != "."]


def is_test_path(path):
    parts = _segments(path)
    if not parts:
        return False
    for segment in parts[:-1]:
        if segment.lower() in TEST_DIR_SEGMENTS:
            return True
    name = parts[-1].lower()
    for pattern in TEST_FILE_PATTERNS:
        if re.match(pattern, name):
            return True
    return False


def is_frozen_test_target(path):
    """Rule 2's predicate for a BASH target: a test file OR a test DIRECTORY.

    Deliberately wider than `is_test_path` (convention #8): a write tool
    targets one file, so `tests` alone is meaningless there, while
    `git checkout -- tests/` and `rm -rf tests` name the directory and undo
    every RED in it. The existence check in rule 2 still applies.
    """
    if is_test_path(path):
        return True
    parts = _segments(path)
    return bool(parts) and parts[-1].lower() in TEST_DIR_SEGMENTS


def is_gate_artifact(path):
    parts = _segments(path)
    if not parts:
        return False
    name = parts[-1].lower()
    if name in GATE_ARTIFACT_NAMES:
        return True
    return name.endswith(GATE_ARTIFACT_SUFFIX)


def bash_tokens(text):
    """Shell-ish tokens with one layer of quoting removed."""
    return [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t
            for t in BASH_TOKEN_RE.findall(text or "")]


def command_basename(token):
    """A command token's comparable name: basename, lower, no .exe/.cmd/..."""
    parts = _segments(token or "")
    name = (parts[-1] if parts else (token or "")).lower()
    for suffix in EXECUTABLE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def bash_write_targets(command):
    """[(verb, path)] for every path this shell command plausibly WRITES.

    See BASH WRITES in the module docstring for the construct list and for
    why this over-collects candidates on purpose.
    """
    targets = []

    def emit(verb, raw):
        path = (raw or "").strip().strip("\"'").strip()
        if not path or path == "--":
            return
        pair = (verb, path)
        if pair not in targets:
            targets.append(pair)

    command = command or ""
    for segment in COMMAND_SEPARATORS.split(command):
        if not segment.strip():
            continue
        for match in BASH_REDIRECT_RE.finditer(segment):
            emit("redirect", match.group(1))
        tokens = bash_tokens(segment)
        for index, token in enumerate(tokens):
            verb = command_basename(token)
            if verb not in BASH_WRITE_VERBS:
                continue
            operands = tokens[index + 1:]
            if verb in BASH_INPLACE_VERBS and not any(
                    INPLACE_FLAG_RE.match(t) for t in operands):
                break   # sed/perl without -i writes stdout, not the file
            for operand in operands:
                if operand.startswith("-"):
                    continue
                emit(verb, operand)
            break       # the first write verb in a segment owns its operands

    for match in GIT_RESTORE_RE.finditer(command):
        for operand in bash_tokens(match.group("rest")):
            if operand.startswith("-"):
                continue
            emit("git " + match.group(1), operand)

    if PYTHON_TOKEN_RE.search(command) and PYTHON_DASH_C_RE.search(command):
        for match in PY_OPEN_WRITE_RE.finditer(command):
            if set("wa+") & set(match.group("m").lower()):
                emit("python -c", match.group("p"))
    return targets


def write_targets_of(tool_name, tool_input):
    """[(source, path)] for whichever guarded tool is about to write.

    `source` is `"tool"` for a write tool's declared path and the shell verb
    for a Bash construct, so a deny message can name what it matched.
    """
    if tool_name in WRITE_TOOLS:
        return [("tool", path) for path in paths_of(tool_input)]
    if tool_name in BASH_TOOLS:
        return bash_write_targets(command_of(tool_input))
    return []


def path_exists(path, cwd):
    try:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = Path(cwd) / candidate
        return candidate.exists()
    except OSError:
        return False


def git_write_invocation(command):
    """The history-writing invocation in `command`, or None.

    A `--help` / `-h` in the same shell segment is documentation, not a
    commit. `gh pr merge` is matched by its own regex and reported under that
    name -- it writes the same history through a different binary.
    """
    for regex, label in ((GIT_WRITE_RE, None), (GH_WRITE_RE, "gh pr merge")):
        for match in regex.finditer(command):
            tail = COMMAND_SEPARATORS.split(command[match.start():], 1)[0]
            if HELP_RE.search(tail):
                continue
            return label or match.group(1)
    return None


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------

def _plugin_root():
    return (os.environ.get("CLAUDE_PLUGIN_ROOT")
            or os.environ.get("CURSOR_PLUGIN_ROOT")
            or "{PLUGIN_ROOT}")


def _gate_command(gate):
    return "python {0}/skills/pipeline-tools/scripts/{1}".format(_plugin_root(), gate)


def decide(tool_name, tool_input, cwd, now=None, window_hours=WINDOW_HOURS_DEFAULT):
    """Return (decision, rule_id, reason). decision is 'allow' or 'deny'."""
    if now is None:
        now = time.time()

    # Every path this call is about to write, whichever tool it arrived on.
    targets = write_targets_of(tool_name, tool_input)

    # Rule 4 first: it holds with or without a lane, so it needs no detection.
    for source, path in targets:
        if is_gate_artifact(path):
            how = ("" if source == "tool" else
                   " (matched the shell construct `{0}`)".format(source))
            return "deny", "gate_artifacts_are_written_by_tools", (
                "Blocked: `{0}` is a gate artifact, written only by "
                "pipeline-tools scripts{1}. gates.jsonl, "
                "orchestrator-state.json, run-log.jsonl and *.meta.json "
                "sidecars are the evidence every other gate reads; a hand "
                "edit -- or a redirect, a `tee`, a `Set-Content`, a rename or "
                "a delete -- to any of them makes each downstream verdict "
                "unfalsifiable. Record the ledger line by running the gate "
                "with --ledger, change state with update_state.py, and "
                "record runs with record_run.py. If a sidecar disagrees "
                "with its capture, re-run the capture through "
                "run_quiet.py --capture; do not reconcile it by hand."
                .format(path, how)
            )

    lanes = detect_lanes(cwd, now=now, window_hours=window_hours)

    # Rule 1 -- commit through the gate.
    if tool_name in BASH_TOOLS:
        subcommand = git_write_invocation(command_of(tool_input))
        arming = [lane for lane in lanes if lane.arms_rule_1()]
        if subcommand and arming:
            lane = arming[0]
            prefix = "" if subcommand.startswith("gh ") else "git "
            return "deny", "commit_through_the_gate", (
                "Blocked: `{0}{1}` by hand while the {2} lane at `{3}` is "
                "active. In this lane the gate makes the commit -- run\n"
                "  {4} ... --commit --message \"<the commit message>\"\n"
                "which commits from its own subprocess (not through the Bash "
                "tool, so this guard never blocks it) once the verdict, the "
                "clean-tree check and the size bound have actually passed. "
                "Committing here by hand skips all three. The sanctioned "
                "local merge that CLOSES this lane is allowed once that "
                "gate has recorded a --commit PASS for milestone {5}; "
                "`--explain` lists what was detected and which rule is armed."
                .format(prefix, subcommand, lane.kind, lane.root,
                        _gate_command(lane.gate),
                        repr(lane.milestone) if lane.milestone
                        else "(unreadable from this lane's path -- see "
                             "--explain)")
            )

    # Rule 2 -- the builder never edits the RED.
    unfixed = unfixed_bugfix_lanes(lanes)
    if unfixed and targets:
        for source, path in targets:
            frozen = (is_test_path(path) if source == "tool"
                      else is_frozen_test_target(path))
            if not frozen:
                continue
            if not path_exists(path, cwd):
                continue  # a brand-new test file is an addition, not an edit
            how = ("" if source == "tool" else
                   " (matched the shell construct `{0}`)".format(source))
            return "deny", "frozen_tests_during_a_fix", (
                "Blocked: `{0}` is a test path{1} and the bugfix lane at "
                "`{2}` has not reached its commit gate. The builder never "
                "edits the RED -- a failing test is a finding about the "
                "code, not an obstacle in front of it. Quinn owns tests in "
                "this lane (bgpdd-bugfix Phase 3 step 4): fix the code, or "
                "report the test as wrong and say why. Adding a NEW test "
                "file is allowed -- this fired because the path already "
                "exists, so the write is an edit to an existing test."
                .format(path, how, unfixed[0].root)
            )

    # Rule 3 -- no delegation before intake.
    if tool_name in DELEGATION_TOOLS:
        pending = pending_bugfix_intakes(cwd, now=now, window_hours=window_hours)
        if pending:
            lane = pending[0]
            return "deny", "no_delegation_before_intake", (
                "Blocked: `{0}/bug-report.md` exists but its ledger holds no "
                "check_bugfix_intake.py PASS. bgpdd-bugfix Phase 0 step 3: no "
                "delegation until the intake gate exits 0 -- a report that has "
                "not passed intake is missing observed/expected, a "
                "reproduction or a surface, and every agent briefed from it "
                "inherits the gap. Run\n"
                "  {1} --report {0}/bug-report.md --milestone \"<bug-slug>\" "
                "--ledger {2}\n"
                "then delegate."
                .format(lane.root, _gate_command(lane.gate), lane.ledger)
            )

    return "allow", None, ""


# ---------------------------------------------------------------------------
# Output -- per-runtime packaging of one decision
# ---------------------------------------------------------------------------

def emit(decision, reason, fmt):
    """Print the host's deny payload. An ALLOW prints NOTHING, on purpose."""
    if decision != "deny":
        return
    if fmt == "cursor":
        payload = {
            "permission": "deny",
            "agent_message": reason,
            "user_message": "blackgoat guard_action denied this call.",
        }
    else:
        payload = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    sys.stdout.write(json.dumps(payload) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def read_stdin():
    """The hook payload as text, BOM-tolerant.

    Read as BYTES and decoded utf-8-sig, matching this family's file-reading
    convention. Not cosmetic: PowerShell 5.1 prefixes a UTF-8 BOM to anything
    it pipes to a native executable, and a BOM makes `json.loads` raise, which
    fails OPEN -- a deny silently becoming an allow. Caught by
    `test_42_bom_prefixed_stdin_still_denies`.
    """
    try:
        data = sys.stdin.buffer.read()
    except AttributeError:  # a text-only stdin (tests, some embedders)
        return sys.stdin.read().lstrip("﻿")
    return data.decode("utf-8-sig", errors="replace").lstrip("﻿")


def build_parser():
    parser = argparse.ArgumentParser(
        description="Pre-execution guard for the bgPDD lanes.")
    parser.add_argument("--format", choices=("claude", "cursor"), default="claude",
                        help="which host's decision payload to emit")
    parser.add_argument("--window-hours", type=float, default=WINDOW_HOURS_DEFAULT,
                        help="lane freshness window (default 12)")
    parser.add_argument("--cwd", default=None,
                        help="root for lane detection (--explain; else the payload's)")
    parser.add_argument("--explain", action="store_true",
                        help="print the rules and the detected lanes, then exit 0")
    parser.add_argument("--self-test", action="store_true")
    return parser


def run_explain(args):
    cwd = args.cwd or os.getcwd()
    now = time.time()
    lanes = detect_lanes(cwd, now=now, window_hours=args.window_hours)
    pending = pending_bugfix_intakes(cwd, now=now, window_hours=args.window_hours)
    unfixed = unfixed_bugfix_lanes(lanes)

    out = ["guard_action.py -- pre-execution guard", ""]
    out.append("Rules (each reads an artifact; a deny is always a positive")
    out.append("identification, never the absence of a reason to allow):")
    out.append("  1 commit_through_the_gate           Bash + git commit/merge/"
               "cherry-pick/revert/rebase/am/notes/tag/stash or gh pr merge, "
               "any active OPEN lane that has a commit gate")
    out.append("  2 frozen_tests_during_a_fix         write (tool OR Bash "
               "mutation) to an EXISTING test path, active bugfix lane "
               "pre-commit-gate")
    out.append("  3 no_delegation_before_intake       Task/Agent while a fresh "
               "bug-report.md has no intake PASS (both routes)")
    out.append("  4 gate_artifacts_are_written_by_tools  write (tool OR Bash "
               "mutation) to gates.jsonl / orchestrator-state.json / "
               "run-log.jsonl / *.meta.json, always")
    out.append("")
    out.append("cwd            : {0}".format(cwd))
    out.append("window (hours) : {0:g}".format(args.window_hours))
    out.append("")
    if lanes:
        out.append("ACTIVE LANES ({0}):".format(len(lanes)))
        for lane in lanes:
            suffix = " [{0}]".format(lane.detail) if lane.detail else ""
            out.append("  - {0}: {1}{2}".format(lane.kind, lane.root, suffix))
            out.append("      ledger: {0}".format(lane.ledger))
            out.append("      milestone: {0}".format(
                lane.milestone if lane.milestone
                else "(unreadable -- closed-lane check fails closed)"))
            out.append("      commits via: {0} --commit".format(lane.gate))
            if not lane.arms_commit_rule:
                out.append("      rule 1: NOT armed (this pipeline has no "
                           "commit gate)")
            elif lane.closed:
                out.append("      rule 1: NOT armed (closed -- the commit gate "
                           "recorded a --commit PASS for this milestone, so "
                           "the sanctioned local merge is allowed)")
            else:
                out.append("      rule 1: armed")
    else:
        out.append("ACTIVE LANES: none -- rule 1 allows a hand commit "
                   "(the user's call).")
    out.append("")
    arming = [l for l in lanes if l.arms_rule_1()]
    out.append("Rule 1 armed for: {0}".format(
        ", ".join(l.root for l in arming) if arming else "nothing"))
    out.append("Rule 2 armed for: {0}".format(
        ", ".join(l.root for l in unfixed) if unfixed else "nothing"))
    out.append("Rule 3 armed for: {0}".format(
        ", ".join(l.root for l in pending) if pending else "nothing"))
    out.append("Rule 4 is always armed, for write tools AND for Bash "
               "redirection/tee/Set-Content/sed -i/mv/rm/git checkout.")
    print("\n".join(out))
    return 0


def main(argv):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()
    if args.explain:
        try:
            return run_explain(args)
        except Exception as exc:  # pragma: no cover -- diagnostics must not raise
            print("guard_action: --explain failed: {0}".format(exc),
                  file=sys.stderr)
            return 0

    # From here to the end, EVERY failure resolves to allow.
    try:
        raw = read_stdin()
    except Exception as exc:
        print("guard_action: could not read stdin ({0}); allowing.".format(exc),
              file=sys.stderr)
        return 0

    try:
        payload = json.loads(raw) if raw.strip() else None
        if payload is None:
            raise GuardError("empty stdin")
        tool_name, tool_input, cwd = normalize_payload(payload)
        if args.cwd:
            cwd = args.cwd
        decision, _rule, reason = decide(
            tool_name, tool_input, cwd, window_hours=args.window_hours)
        emit(decision, reason, args.format)
    except Exception as exc:
        print("guard_action: {0}; allowing.".format(exc), file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil
    import tempfile
    import unittest

    HOUR = 3600.0

    def touch(path, content="x", age_hours=0.0, now=None):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if age_hours:
            stamp = (now or time.time()) - age_hours * HOUR
            os.utime(str(path), (stamp, stamp))
        return str(path)

    def ledger_line(gate, verdict="PASS", argv=None, milestone=None):
        return json.dumps({"gate": gate, "verdict": verdict,
                           "argv": argv or [], "milestone": milestone,
                           "ts": "2026-09-07T00:00:00Z"}) + "\n"

    class GuardTest(unittest.TestCase):

        def setUp(self):
            self.root = tempfile.mkdtemp(prefix="guard-")
            self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

        # -- fixtures ---------------------------------------------------

        def make_bugfix(self, slug="coupon-500", intake=True, commit=False,
                        age_hours=0.0, commit_milestone=None):
            d = Path(self.root) / ".docs" / "bugfix" / slug
            touch(d / "bug-report.md", "# Bug report", age_hours)
            lines = ""
            if intake:
                lines += ledger_line("check_bugfix_intake.py")
            if commit:
                lines += ledger_line("check_commit_gate.py", argv=["--commit"],
                                     milestone=commit_milestone)
            touch(d / "gates.jsonl", lines or "", age_hours)
            return str(d)

        def make_feature(self, name="demo", pipeline="bgpdd-build", age_hours=0.0,
                         cursor=None, commit_milestone=None):
            d = Path(self.root) / ".docs" / name
            touch(d / "orchestrator-state.json",
                  json.dumps({"pipeline": pipeline,
                              "milestone_cursor": cursor}), age_hours)
            lines = ""
            if commit_milestone is not None:
                lines = ledger_line("check_commit_gate.py", argv=["--commit"],
                                    milestone=commit_milestone)
            touch(d / "implementation" / "gates.jsonl", lines, age_hours)
            return str(d)

        def make_feature_bugfix(self, name="demo", slug=None, intake=True,
                                commit=False, commit_milestone=None,
                                age_hours=0.0):
            """The FEATURE route: a bug-report.md under the epic's tree.

            `slug=None` is the unscoped 2.6.0 shape
            (`implementation/bug-report.md`); a slug is the scoped shape
            (`implementation/bugs/<slug>/bug-report.md`).
            """
            impl = Path(self.root) / ".docs" / name / "implementation"
            d = impl / "bugs" / slug if slug else impl
            touch(d / "bug-report.md", "# Bug report", age_hours)
            lines = ""
            if intake:
                lines += ledger_line("check_bugfix_intake.py")
            if commit:
                lines += ledger_line("check_commit_gate.py", argv=["--commit"],
                                     milestone=commit_milestone)
            touch(d / "gates.jsonl", lines or "", age_hours)
            return str(d)

        def make_quick(self, slug="2026-09-07-rename", closed=False, age_hours=0.0):
            d = Path(self.root) / ".docs" / "quick" / slug
            touch(d / "note.md", "What/Where/How", age_hours)
            line = (ledger_line("check_quick_close.py", argv=["--commit"])
                    if closed else "")
            touch(d / "gates.jsonl", line, age_hours)
            return str(d)

        def decide(self, tool, tool_input):
            return decide(tool, tool_input, self.root)

        # -- rule 1: commit through the gate ----------------------------

        def test_01_commit_denied_in_feature_lane(self):
            self.make_feature()
            d, rule, reason = self.decide("Bash", {"command": "git commit -m x"})
            self.assertEqual((d, rule), ("deny", "commit_through_the_gate"))
            self.assertIn("check_commit_gate.py", reason)

        def test_02_commit_denied_in_bugfix_lane(self):
            self.make_bugfix()
            d, rule, _ = self.decide("Bash", {"command": "git commit -m x"})
            self.assertEqual((d, rule), ("deny", "commit_through_the_gate"))

        def test_03_commit_denied_in_quick_lane_names_quick_gate(self):
            self.make_quick()
            d, rule, reason = self.decide("Bash", {"command": "git commit -m x"})
            self.assertEqual((d, rule), ("deny", "commit_through_the_gate"))
            self.assertIn("check_quick_close.py", reason)

        def test_04_commit_allowed_with_no_lane(self):
            self.assertEqual(self.decide("Bash", {"command": "git commit -m x"})[0],
                             "allow")

        def test_05_commit_allowed_when_lane_is_stale_13h(self):
            self.make_feature(age_hours=13.0)
            self.assertEqual(self.decide("Bash", {"command": "git commit -m x"})[0],
                             "allow")

        def test_06_commit_allowed_when_quick_lane_already_closed(self):
            self.make_quick(closed=True)
            self.assertEqual(self.decide("Bash", {"command": "git commit -m x"})[0],
                             "allow")

        def test_07_git_commit_help_allowed_in_active_lane(self):
            self.make_feature()
            for cmd in ("git commit --help", "git commit -h"):
                self.assertEqual(self.decide("Bash", {"command": cmd})[0], "allow",
                                 cmd)

        def test_08_merge_revert_cherry_pick_denied(self):
            self.make_feature()
            for cmd in ("git merge main", "git revert HEAD",
                        "git cherry-pick abc123"):
                self.assertEqual(self.decide("Bash", {"command": cmd})[0], "deny",
                                 cmd)

        def test_09_global_option_bypass_is_closed(self):
            self.make_feature()
            for cmd in ("git -C /repo commit -m x",
                        "git --no-pager commit -m x",
                        "git -c user.name=x commit -m y"):
                self.assertEqual(self.decide("Bash", {"command": cmd})[0], "deny",
                                 cmd)

        def test_10_read_only_git_allowed_in_active_lane(self):
            self.make_feature()
            for cmd in ("git status", "git log --oneline", "git diff --stat",
                        "git add -A"):
                self.assertEqual(self.decide("Bash", {"command": cmd})[0], "allow",
                                 cmd)

        def test_11_legit_is_not_git(self):
            self.make_feature()
            self.assertEqual(
                self.decide("Bash", {"command": "legit commit -m x"})[0], "allow")

        # -- rule 2: frozen tests ---------------------------------------

        def test_12_existing_test_edit_denied_during_bugfix(self):
            self.make_bugfix()
            path = touch(Path(self.root) / "tests" / "test_api.py", "old")
            d, rule, reason = self.decide("Edit", {"file_path": path})
            self.assertEqual((d, rule), ("deny", "frozen_tests_during_a_fix"))
            self.assertIn("Quinn", reason)

        def test_13_new_test_file_allowed_during_bugfix(self):
            self.make_bugfix()
            path = str(Path(self.root) / "tests" / "test_brand_new.py")
            self.assertEqual(self.decide("Write", {"file_path": path})[0], "allow")

        def test_14_test_edit_allowed_once_commit_gate_passed(self):
            self.make_bugfix(commit=True)
            path = touch(Path(self.root) / "tests" / "test_api.py", "old")
            self.assertEqual(self.decide("Edit", {"file_path": path})[0], "allow")

        def test_15_test_edit_allowed_with_no_bugfix_lane(self):
            self.make_feature()
            path = touch(Path(self.root) / "tests" / "test_api.py", "old")
            self.assertEqual(self.decide("Edit", {"file_path": path})[0], "allow")

        def test_16_source_edit_allowed_during_bugfix(self):
            self.make_bugfix()
            path = touch(Path(self.root) / "src" / "api.py", "old")
            self.assertEqual(self.decide("Edit", {"file_path": path})[0], "allow")

        def test_17_windows_separators_are_recognized(self):
            self.make_bugfix()
            real = touch(Path(self.root) / "tests" / "unit" / "test_api.py", "old")
            windows_style = real.replace("/", "\\")
            d, rule, _ = self.decide("Edit", {"file_path": windows_style})
            self.assertEqual((d, rule), ("deny", "frozen_tests_during_a_fix"))

        def test_18_test_naming_conventions_all_match(self):
            self.make_bugfix()
            for name in ("api.test.ts", "api.spec.js", "test_api.py",
                         "api_test.go"):
                path = touch(Path(self.root) / "src" / name, "old")
                self.assertEqual(self.decide("Edit", {"file_path": path})[0],
                                 "deny", name)

        def test_19_spec_and_dunder_test_dirs_match(self):
            self.make_bugfix()
            for seg in ("spec", "__tests__", "Tests", "test"):
                path = touch(Path(self.root) / seg / "thing.js", "old")
                self.assertEqual(self.decide("Edit", {"file_path": path})[0],
                                 "deny", seg)

        def test_20_multiedit_nested_path_is_seen(self):
            self.make_bugfix()
            path = touch(Path(self.root) / "tests" / "test_api.py", "old")
            d, rule, _ = self.decide("MultiEdit", {"edits": [{"file_path": path}]})
            self.assertEqual((d, rule), ("deny", "frozen_tests_during_a_fix"))

        # -- rule 3: no delegation before intake ------------------------

        def test_21_delegation_denied_before_intake(self):
            self.make_bugfix(intake=False)
            for tool in ("Task", "Agent"):
                d, rule, reason = self.decide(tool, {"prompt": "go"})
                self.assertEqual((d, rule),
                                 ("deny", "no_delegation_before_intake"), tool)
                self.assertIn("check_bugfix_intake.py", reason)

        def test_22_delegation_allowed_after_intake(self):
            self.make_bugfix(intake=True)
            self.assertEqual(self.decide("Task", {"prompt": "go"})[0], "allow")

        def test_23_delegation_allowed_when_report_is_stale(self):
            self.make_bugfix(intake=False, age_hours=13.0)
            self.assertEqual(self.decide("Task", {"prompt": "go"})[0], "allow")

        def test_24_rule3_fires_before_any_ledger_exists(self):
            d = Path(self.root) / ".docs" / "bugfix" / "no-ledger"
            touch(d / "bug-report.md", "# Bug report")
            self.assertEqual(self.decide("Agent", {"prompt": "go"})[0], "deny")

        def test_25_failed_intake_does_not_count_as_pass(self):
            d = Path(self.root) / ".docs" / "bugfix" / "failed"
            touch(d / "bug-report.md", "# Bug report")
            touch(d / "gates.jsonl",
                  ledger_line("check_bugfix_intake.py", verdict="FAIL"))
            self.assertEqual(self.decide("Task", {"prompt": "go"})[0], "deny")

        # -- rule 4: gate artifacts -------------------------------------

        def test_26_gate_artifacts_denied_always(self):
            for name in ("gates.jsonl", "orchestrator-state.json",
                         "run-log.jsonl", "evidence/red/x.md.meta.json"):
                path = str(Path(self.root) / ".docs" / "anything" / name)
                d, rule, reason = self.decide("Write", {"file_path": path})
                self.assertEqual((d, rule),
                                 ("deny", "gate_artifacts_are_written_by_tools"),
                                 name)
                self.assertIn("pipeline-tools", reason)

        def test_27_gate_artifacts_denied_with_no_lane_and_for_every_write_tool(self):
            path = str(Path(self.root) / ".docs" / "x" / "gates.jsonl")
            for tool, key in (("Edit", "file_path"), ("Write", "file_path"),
                              ("MultiEdit", "file_path"),
                              ("NotebookEdit", "notebook_path")):
                self.assertEqual(self.decide(tool, {key: path})[0], "deny", tool)

        def test_28_ordinary_json_is_not_a_gate_artifact(self):
            for name in ("package.json", "state.json", "meta.json"):
                path = str(Path(self.root) / name)
                self.assertEqual(self.decide("Write", {"file_path": path})[0],
                                 "allow", name)

        def test_29_bash_may_not_be_used_to_dodge_rule_4(self):
            # Was the documented LIMIT until 2.6.1: rule 4 tested only write
            # tools, so one `>>` rewrote any ledger. Now the same call denies.
            path = str(Path(self.root) / ".docs" / "x" / "gates.jsonl")
            d, rule, reason = self.decide(
                "Bash", {"command": "echo x >> " + path})
            self.assertEqual((d, rule),
                             ("deny", "gate_artifacts_are_written_by_tools"))
            self.assertIn("redirect", reason)

        # -- fail-open and payload handling -----------------------------

        def test_30_malformed_stdin_allows(self):
            for raw in ("", "   ", "not json", "[]", "null", "{}"):
                try:
                    payload = json.loads(raw) if raw.strip() else None
                    if payload is None:
                        raise GuardError("empty")
                    tool_name, tool_input, cwd = normalize_payload(payload)
                    result = decide(tool_name, tool_input, cwd)[0]
                except Exception:
                    result = "allow"
                self.assertEqual(result, "allow", repr(raw))

        def test_31_unknown_tool_allows(self):
            self.make_bugfix(intake=False)
            self.assertEqual(self.decide("WebFetch", {"url": "https://x"})[0],
                             "allow")

        def test_32_missing_tool_input_allows(self):
            self.make_feature()
            self.assertEqual(self.decide("Bash", {})[0], "allow")

        def test_33_unreadable_docs_tree_yields_no_lanes(self):
            touch(Path(self.root) / ".docs", "not a directory")
            self.assertEqual(detect_lanes(self.root), [])

        def test_34_corrupt_state_and_ledger_do_not_raise(self):
            d = Path(self.root) / ".docs" / "broken"
            touch(d / "orchestrator-state.json", "{not json")
            touch(d / "implementation" / "gates.jsonl", "{bad\n\n{\"gate\":1}\n")
            self.assertEqual(detect_lanes(self.root), [])

        def test_35_empty_pipeline_is_not_an_active_lane(self):
            self.make_feature(pipeline="")
            self.assertEqual(detect_lanes(self.root), [])

        # -- payload normalization and output ---------------------------

        def test_36_claude_payload_normalizes(self):
            payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "tool_input": {"command": "git commit -m x"},
                       "cwd": self.root}
            self.assertEqual(normalize_payload(payload),
                             ("Bash", {"command": "git commit -m x"}, self.root))

        def test_37_cursor_shell_payload_normalizes_to_bash(self):
            payload = {"hook_event_name": "beforeShellExecution",
                       "command": "git commit -m x", "cwd": self.root}
            tool, tin, cwd = normalize_payload(payload)
            self.assertEqual((tool, tin["command"], cwd),
                             ("Bash", "git commit -m x", self.root))

        def test_38_deny_payload_shapes_match_each_host(self):
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                emit("deny", "because", "claude")
            claude = json.loads(buf.getvalue())
            self.assertEqual(
                claude["hookSpecificOutput"]["permissionDecision"], "deny")
            self.assertEqual(
                claude["hookSpecificOutput"]["hookEventName"], "PreToolUse")
            self.assertEqual(
                claude["hookSpecificOutput"]["permissionDecisionReason"], "because")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                emit("deny", "because", "cursor")
            self.assertEqual(json.loads(buf.getvalue())["permission"], "deny")

        def test_39_allow_prints_nothing_in_either_format(self):
            import contextlib
            import io
            for fmt in ("claude", "cursor"):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    emit("allow", "", fmt)
                self.assertEqual(buf.getvalue(), "", fmt)

        def test_40_main_never_exits_nonzero(self):
            import contextlib
            import io
            for raw in ("garbage", json.dumps(
                    {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                     "tool_input": {"command": "git commit -m x"},
                     "cwd": self.root})):
                stdin, sys.stdin = sys.stdin, io.StringIO(raw)
                out, err = io.StringIO(), io.StringIO()
                try:
                    with contextlib.redirect_stdout(out), \
                            contextlib.redirect_stderr(err):
                        code = main([])
                finally:
                    sys.stdin = stdin
                self.assertEqual(code, 0, raw[:20])

        def test_42_bom_prefixed_stdin_still_denies(self):
            # PowerShell 5.1 pipes a UTF-8 BOM ahead of the payload. Before
            # read_stdin() decoded utf-8-sig, that BOM made json.loads raise
            # and the guard fail open -- a deny that silently became an allow.
            import contextlib
            import io
            payload = json.dumps(
                {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "tool_input": {"command": "git commit -m x"},
                 "cwd": self.root})
            self.make_feature()

            class ByteStdin(object):
                def __init__(self, data):
                    self.buffer = io.BytesIO(data)

            stdin, sys.stdin = sys.stdin, ByteStdin(
                b"\xef\xbb\xbf" + payload.encode("utf-8"))
            out = io.StringIO()
            try:
                with contextlib.redirect_stdout(out):
                    code = main([])
            finally:
                sys.stdin = stdin
            self.assertEqual(code, 0)
            emitted = json.loads(out.getvalue())
            self.assertEqual(
                emitted["hookSpecificOutput"]["permissionDecision"], "deny")

        def test_41_explain_runs_and_exits_zero(self):
            import contextlib
            import io
            self.make_bugfix(intake=False)
            self.make_quick()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["--explain", "--cwd", self.root])
            self.assertEqual(code, 0)
            text = buf.getvalue()
            self.assertIn("ACTIVE LANES", text)
            self.assertIn("check_quick_close.py", text)
            self.assertIn("Rule 3 armed for", text)

        # == 2.6.1 ==================================================
        # -- rule 4 through Bash (audit3 F1) ----------------------------

        def ledger_path(self):
            return str(Path(self.root) / ".docs" / "x" / "gates.jsonl")

        def assert_rule4(self, command, needle=None):
            d, rule, reason = self.decide("Bash", {"command": command})
            self.assertEqual((d, rule),
                             ("deny", "gate_artifacts_are_written_by_tools"),
                             command)
            if needle:
                self.assertIn(needle, reason, command)

        def test_43_bash_single_redirect_into_a_ledger_denies(self):
            self.assert_rule4("echo '{}' > " + self.ledger_path())

        def test_44_bash_fd_prefixed_redirect_denies(self):
            self.assert_rule4("cmd 2>> " + self.ledger_path())

        def test_45_bash_piped_tee_denies(self):
            self.assert_rule4("echo '{}' | tee -a " + self.ledger_path(), "tee")

        def test_46_bash_bare_tee_denies(self):
            self.assert_rule4("tee " + self.ledger_path(), "tee")

        def test_47_powershell_content_cmdlets_deny(self):
            for verb in ("Set-Content", "Add-Content", "Out-File",
                         "Clear-Content"):
                self.assert_rule4("{0} {1} '{{}}'".format(
                    verb, self.ledger_path()), verb.lower())

        def test_48_powershell_item_cmdlets_deny(self):
            for verb in ("Remove-Item", "Move-Item", "Copy-Item",
                         "Rename-Item", "New-Item"):
                self.assert_rule4("{0} {1}".format(verb, self.ledger_path()),
                                  verb.lower())

        def test_49_python_dash_c_open_write_denies(self):
            for mode in ("w", "a", "r+", "wb"):
                self.assert_rule4(
                    "python -c \"open('{0}','{1}').write('x')\"".format(
                        self.ledger_path().replace("\\", "/"), mode),
                    "python -c")

        def test_50_python_dash_c_open_read_is_allowed(self):
            path = self.ledger_path().replace("\\", "/")
            self.assertEqual(self.decide("Bash", {
                "command": "python -c \"print(open('{0}').read())\"".format(path)
            })[0], "allow")
            self.assertEqual(self.decide("Bash", {
                "command": "python -c \"open('{0}','r').read()\"".format(path)
            })[0], "allow")

        def test_51_mv_cp_rm_del_of_a_ledger_deny(self):
            for verb in ("mv", "cp", "rm", "del", "erase", "move", "copy",
                         "ren", "rename", "truncate"):
                self.assert_rule4("{0} {1} x".format(verb, self.ledger_path()),
                                  verb)

        def test_52_renaming_the_ledger_away_denies(self):
            # The cheapest way to disarm every lane rule was to rename its
            # ledger out of the way; that is now rule 4's business.
            self.assert_rule4("mv {0} {0}.bak".format(self.ledger_path()))

        def test_53_sidecar_and_state_and_run_log_through_bash_deny(self):
            base = Path(self.root) / ".docs" / "x"
            for name in ("orchestrator-state.json", "run-log.jsonl",
                         "evidence/red/r.md.meta.json"):
                self.assert_rule4("echo x >> " + str(base / name))

        def test_54_bash_paths_match_case_insensitively_and_either_slash(self):
            windows = str(Path(self.root) / ".docs" / "x" / "GATES.JSONL")
            self.assert_rule4("echo x >> " + windows)
            self.assert_rule4("echo x >> " + windows.replace("/", "\\"))

        def test_55_reading_a_gate_artifact_through_bash_is_allowed(self):
            for command in ("cat " + self.ledger_path(),
                            "grep gates.jsonl notes.md",
                            "python check_ledger.py --ledger "
                            + self.ledger_path(),
                            "ls -la .docs/x"):
                self.assertEqual(self.decide("Bash", {"command": command})[0],
                                 "allow", command)

        def test_56_sed_without_in_place_is_not_a_write(self):
            path = self.ledger_path()
            self.assertEqual(self.decide(
                "Bash", {"command": "sed s/a/b/ " + path})[0], "allow")
            self.assert_rule4("sed -i s/a/b/ " + path, "sed")
            self.assert_rule4("sed -i.bak s/a/b/ " + path, "sed")
            self.assert_rule4("perl -pi -e s/a/b/ " + path, "perl")

        def test_57_git_checkout_and_restore_of_a_ledger_deny(self):
            self.assert_rule4("git checkout -- " + self.ledger_path(),
                              "git checkout")
            self.assert_rule4("git restore " + self.ledger_path(),
                              "git restore")

        def test_58_rule_4_through_bash_needs_no_lane(self):
            self.assertEqual(detect_lanes(self.root), [])
            self.assert_rule4("echo x >> " + self.ledger_path())

        # -- rule 2 through Bash (audit3 F1) ----------------------------

        def test_59_bash_mutations_of_an_existing_test_deny(self):
            self.make_bugfix()
            path = touch(Path(self.root) / "tests" / "orders.test.js", "old")
            for command in ("sed -i s/a/b/ " + path,
                            "perl -pi -e s/a/b/ " + path,
                            "mv {0} {0}.old".format(path),
                            "rm " + path,
                            "Remove-Item " + path,
                            "echo x > " + path,
                            "cat new | tee " + path):
                d, rule, _ = self.decide("Bash", {"command": command})
                self.assertEqual((d, rule),
                                 ("deny", "frozen_tests_during_a_fix"), command)

        def test_60_git_checkout_of_the_tests_directory_denies(self):
            self.make_bugfix()
            touch(Path(self.root) / "tests" / "orders.test.js", "old")
            for command in ("git checkout -- tests/", "git restore tests"):
                d, rule, _ = self.decide("Bash", {"command": command})
                self.assertEqual((d, rule),
                                 ("deny", "frozen_tests_during_a_fix"), command)

        def test_61_bash_write_to_a_new_test_path_is_allowed(self):
            self.make_bugfix()
            path = str(Path(self.root) / "tests" / "brand-new.test.js")
            self.assertEqual(self.decide(
                "Bash", {"command": "echo x > " + path})[0], "allow")

        def test_62_bash_write_to_source_is_allowed_during_a_bugfix(self):
            self.make_bugfix()
            path = touch(Path(self.root) / "src" / "api.py", "old")
            self.assertEqual(self.decide(
                "Bash", {"command": "sed -i s/a/b/ " + path})[0], "allow")

        def test_63_bash_test_mutation_allowed_with_no_bugfix_lane(self):
            path = touch(Path(self.root) / "tests" / "orders.test.js", "old")
            self.assertEqual(self.decide(
                "Bash", {"command": "rm " + path})[0], "allow")

        def test_64_bash_test_mutation_allowed_once_the_commit_gate_passed(self):
            self.make_bugfix(commit=True)
            path = touch(Path(self.root) / "tests" / "orders.test.js", "old")
            self.assertEqual(self.decide(
                "Bash", {"command": "rm " + path})[0], "allow")

        def test_65_running_the_test_suite_is_not_a_write(self):
            self.make_bugfix()
            touch(Path(self.root) / "tests" / "orders.test.js", "old")
            for command in ("npm test", "pytest tests/", "dotnet test",
                            "npx playwright test tests/orders.test.js"):
                self.assertEqual(self.decide("Bash", {"command": command})[0],
                                 "allow", command)

        # -- the feature bugfix route (audit3 Metric 20) ----------------

        def test_66_feature_route_bug_report_arms_rule_2(self):
            self.make_feature()
            self.make_feature_bugfix()
            path = touch(Path(self.root) / "tests" / "orders.test.js", "old")
            d, rule, _ = self.decide("Edit", {"file_path": path})
            self.assertEqual((d, rule), ("deny", "frozen_tests_during_a_fix"))

        def test_67_feature_route_bug_report_arms_rule_3(self):
            self.make_feature()
            self.make_feature_bugfix(intake=False)
            d, rule, reason = self.decide("Task", {"prompt": "go"})
            self.assertEqual((d, rule), ("deny", "no_delegation_before_intake"))
            self.assertIn("check_bugfix_intake.py", reason)

        def test_68_slug_scoped_feature_route_arms_rules_2_and_3(self):
            self.make_feature()
            self.make_feature_bugfix(slug="coupon-500", intake=False)
            path = touch(Path(self.root) / "tests" / "orders.test.js", "old")
            self.assertEqual(self.decide("Edit", {"file_path": path})[1],
                             "frozen_tests_during_a_fix")
            self.assertEqual(self.decide("Agent", {"prompt": "go"})[1],
                             "no_delegation_before_intake")

        def test_69_slug_scoped_route_falls_back_to_the_epic_ledger(self):
            self.make_feature()
            impl = Path(self.root) / ".docs" / "demo" / "implementation"
            touch(impl / "bugs" / "coupon-500" / "bug-report.md", "# Bug")
            touch(impl / "gates.jsonl",
                  ledger_line("check_bugfix_intake.py"))
            kinds = sorted(l.kind for l in detect_lanes(self.root))
            self.assertIn("bugfix", kinds)
            self.assertEqual(self.decide("Task", {"prompt": "go"})[0], "allow")

        def test_70_feature_route_still_arms_rule_1(self):
            self.make_feature()
            self.make_feature_bugfix()
            self.assertEqual(self.decide("Bash", {"command": "git commit -m x"})[0],
                             "deny")

        def test_71_the_unscoped_feature_route_reads_no_slug(self):
            self.make_feature()
            self.make_feature_bugfix()
            bugfix = [l for l in detect_lanes(self.root) if l.kind == "bugfix"]
            self.assertEqual(len(bugfix), 1)
            self.assertIsNone(bugfix[0].milestone)
            self.assertFalse(bugfix[0].closed)

        # -- closed lanes: the sanctioned local merge -------------------

        def test_72_bugfix_merge_allowed_after_a_scoped_commit_gate_pass(self):
            self.make_bugfix(slug="coupon-500", commit=True,
                             commit_milestone="coupon-500")
            for command in ("git merge --no-ff bugfix/coupon-500",
                            "git commit -m x"):
                self.assertEqual(self.decide("Bash", {"command": command})[0],
                                 "allow", command)

        def test_73_a_commit_gate_pass_for_another_milestone_does_not_close(self):
            self.make_bugfix(slug="coupon-500", commit=True,
                             commit_milestone="refund-timeout")
            self.assertEqual(self.decide("Bash", {"command": "git merge x"})[0],
                             "deny")

        def test_74_an_unscoped_commit_gate_pass_does_not_close_a_lane(self):
            self.make_bugfix(slug="coupon-500", commit=True,
                             commit_milestone=None)
            self.assertEqual(self.decide("Bash", {"command": "git merge x"})[0],
                             "deny")

        def test_75_a_commit_gate_pass_without_commit_flag_does_not_close(self):
            d = Path(self.root) / ".docs" / "bugfix" / "coupon-500"
            touch(d / "bug-report.md", "# Bug report")
            touch(d / "gates.jsonl",
                  ledger_line("check_bugfix_intake.py")
                  + ledger_line("check_commit_gate.py", argv=["--state", "s"],
                                milestone="coupon-500"))
            self.assertEqual(self.decide("Bash", {"command": "git merge x"})[0],
                             "deny")

        def test_76_lite_merge_allowed_after_the_cursor_milestone_committed(self):
            self.make_feature(pipeline="bgpdd-lite", cursor="M2 - Auth",
                              commit_milestone="M2 - Auth")
            self.assertEqual(self.decide("Bash", {"command": "git merge x"})[0],
                             "allow")

        def test_77_feature_lane_with_a_null_cursor_stays_armed(self):
            self.make_feature(cursor=None, commit_milestone="M1")
            self.assertEqual(self.decide("Bash", {"command": "git merge x"})[0],
                             "deny")

        def test_78_an_earlier_milestone_commit_does_not_close_the_epic(self):
            self.make_feature(cursor="M2 - Auth", commit_milestone="M1 - Setup")
            self.assertEqual(self.decide("Bash", {"command": "git commit -m x"})[0],
                             "deny")

        def test_79_a_closed_lane_still_arms_rule_4(self):
            root = self.make_bugfix(slug="coupon-500", commit=True,
                                    commit_milestone="coupon-500")
            self.assert_rule4("echo x >> " + str(Path(root) / "gates.jsonl"))

        # -- verify lanes have no commit gate (audit3 Metric 20) --------

        def test_80_a_verify_lane_does_not_arm_rule_1(self):
            self.make_feature(pipeline="bgpdd-verify")
            for command in ("git commit -m x", "git merge main"):
                self.assertEqual(self.decide("Bash", {"command": command})[0],
                                 "allow", command)

        def test_81_a_verify_lane_is_still_detected_and_still_arms_rule_4(self):
            root = self.make_feature(pipeline="bgpdd-verify")
            lanes = detect_lanes(self.root)
            self.assertEqual([l.kind for l in lanes], ["feature"])
            self.assertFalse(lanes[0].arms_commit_rule)
            self.assert_rule4("echo x >> " + str(
                Path(root) / "implementation" / "gates.jsonl"))

        def test_82_a_verify_lane_beside_a_build_lane_still_denies(self):
            self.make_feature(name="verify-me", pipeline="bgpdd-verify")
            self.make_feature(name="build-me", pipeline="bgpdd-build")
            self.assertEqual(self.decide("Bash", {"command": "git commit -m x"})[0],
                             "deny")

        # -- the widened git surface (audit3 F12) -----------------------

        def test_83_the_widened_git_subcommands_deny(self):
            self.make_feature()
            for command in ("git am patch.mbox", "git rebase -i HEAD~2",
                            "git rebase --continue", "git stash",
                            "git stash pop", "git stash apply",
                            "git notes add -m x", "git tag -a v1 -m x",
                            "gh pr merge 12 --squash"):
                self.assertEqual(self.decide("Bash", {"command": command})[0],
                                 "deny", command)

        def test_84_gh_pr_merge_is_named_in_its_own_deny(self):
            self.make_feature()
            _d, _rule, reason = self.decide(
                "Bash", {"command": "gh pr merge 12 --squash"})
            self.assertIn("gh pr merge", reason)
            self.assertNotIn("git gh", reason)

        def test_85_read_only_git_and_gh_stay_allowed(self):
            self.make_feature()
            for command in ("git status", "git log --oneline", "git show HEAD",
                            "git rebase --help", "git tag --help",
                            "gh pr view 12", "gh pr list", "gh pr checks"):
                self.assertEqual(self.decide("Bash", {"command": command})[0],
                                 "allow", command)

        def test_86_the_widened_surface_is_still_lane_scoped(self):
            for command in ("git am patch.mbox", "git stash pop",
                            "gh pr merge 12"):
                self.assertEqual(self.decide("Bash", {"command": command})[0],
                                 "allow", command)

        # -- extractor unit cases --------------------------------------

        def test_87_bash_write_targets_handles_quoting_and_segments(self):
            self.assertIn(
                ("redirect", "a b/gates.jsonl"),
                bash_write_targets('echo x >> "a b/gates.jsonl"'))
            self.assertIn(
                ("tee", "one/gates.jsonl"),
                bash_write_targets("true && echo x | tee one/gates.jsonl"))
            self.assertEqual(bash_write_targets(""), [])
            self.assertEqual(bash_write_targets(None), [])

        def test_88_explain_reports_rule_1_arming_per_lane(self):
            import contextlib
            import io
            self.make_feature(pipeline="bgpdd-verify")
            self.make_bugfix(slug="coupon-500", commit=True,
                             commit_milestone="coupon-500")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["--explain", "--cwd", self.root])
            self.assertEqual(code, 0)
            text = buf.getvalue()
            self.assertIn("Rule 1 armed for: nothing", text)
            self.assertIn("no commit gate", text)
            self.assertIn("closed", text)
            self.assertIn("milestone:", text)

    suite = unittest.TestLoader().loadTestsFromTestCase(GuardTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
