#!/usr/bin/env python3
"""Emits the ONE next mandatory action for a bgpdd-bugfix or bgpdd-quick lane.

Phase order used to be prose the Orchestrator recalled at the moment it most
wanted to proceed -- exactly the shape CLAUDE.md convention #9 says must become
an artifact that has to be run. This reads the lane root's artifacts and the
gate ledger, derives the current phase from what is actually on disk, and
prints the single next action. The Orchestrator executes; the driver decides.

It REFUSES to advance past a phase whose required gate is not a standing PASS.
The exit codes carry that refusal, and the invariant is
`exit 1 if and only if blocked_by is non-empty`:

  * `required_gate` is set only when running that gate IS the next action --
    the artifact it reads already exists. Whenever it is set and its status is
    not PASS (never run, FAIL, or a PASS whose recorded input hashes no longer
    match disk), the lane is BLOCKED at exit 1: run that gate, never the next
    phase. The driver still prints the command with its exact flags, because
    "blocked" here means "there is exactly one thing to do", not "stop".
  * When the next action is to AUTHOR an artifact or DELEGATE an agent, there
    is no gate to run yet -- `required_gate` is null and the exit is 0.
  * An artifact that is PRESENT and structurally wrong -- a RED capture that
    exited 0, a capture with no run_quiet.py sidecar -- blocks on the same
    terms even where no gate is pending. It is not "not there yet"; someone
    must fix it.

This is a READER, like next_milestone.py and summarize_run.py: it grants no
verdict, so it appends nothing to the ledger. `--ledger` is an input only. The
one subprocess it runs is `detect_stack.py`, a sibling READER, to name a
suggested check command in the quick lane's Phase 0 action; it is best-effort,
and its absence or failure only drops that clause.

Usage:
    python pipeline_driver.py --root <lane root> [--lane bugfix|quick|auto] \
        [--json] [--ledger <path>] [--milestone "<slug>"]
    python pipeline_driver.py --self-test

Exit codes:
    0  a next action was emitted
    1  blocked -- `blocked_by` names what must be fixed or re-run first
    2  root unreadable, no lane detected, or the lane's state is corrupt
    3  lane complete -- the closing gate PASSed with --commit

Pure standard library. Files are read as utf-8-sig. ASCII output.
See ../SKILL.md for the contract and ../references/pipeline_driver.md for
depth (phase tables, the derivation rules, the self-test inventory).
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

READ_ENCODING = "utf-8-sig"
SIDECAR_SUFFIX = ".meta.json"

EXIT_NEXT = 0
EXIT_BLOCKED = 1
EXIT_ERROR = 2
EXIT_COMPLETE = 3

# --- artifact grammars, each a minimal copy of the owning gate's ------------
# One-file convention (pipeline-tools/SKILL.md): no cross-imports. Each regex
# below is the narrowest form of the owning gate's, kept narrow on purpose --
# this tool decides WHERE the lane is, never whether a gate would pass.
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
FIELD_RE = re.compile(r"^\s*[-*]\s*([A-Za-z][A-Za-z /_-]{1,40}?)\s*:\s*(.*)$")
PLACEHOLDER_VALUE_RE = re.compile(
    r"^(?:<[^>]*>|todo|tbd|fixme|n/?a|none|unknown|\?+|\.{3,}|xxx+)[.:]?$",
    re.IGNORECASE)
# check_red_green.py / check_quick_close.py: the capture and its header pair.
CAPTURED_HEADING_RE = re.compile(
    r"(?im)^##[^\S\n]+Captured[^\S\n]+output[^\S\n]*$")
BODY_EXIT_CODE_RE = re.compile(
    r"(?im)^[^\S\n]*-[^\S\n]*Exit[^\S\n]+code[^\S\n]*:[^\S\n]*(-?\d+)[^\S\n]*$")
# check_commit_gate.py: the review section and its verdict line.
REVIEW_HEADING_RE = re.compile(r"^##\s*Review:\s*(.*)$")
ANY_HEADING_RE = re.compile(r"^#{2,6}(?:\s|$)")
VERDICT_LINE_RE = re.compile(r"^\s*\*\*Verdict:\*\*(.*)$")
# `.docs/quick/{YYYY-MM-DD}-{slug}` -- the date prefix is not part of the slug.
DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")

BUILDER_AGENTS = ("mason", "nova")
SCRIPTS_DIR = Path(__file__).resolve().parent


class DriverError(Exception):
    """Structural/usage failure -- maps to exit 2."""


# ---------------------------------------------------------------------------
# Small shared readers
# ---------------------------------------------------------------------------

def rp(path):
    """A path rendered for a command line: forward slashes, Windows-safe."""
    return str(path).replace("\\", "/")


def read_text(path):
    p = Path(path)
    if not p.is_file():
        raise DriverError("file not found or not readable: %s" % rp(path))
    return p.read_text(encoding=READ_ENCODING, errors="replace")


def sha256_file(path):
    """Hex sha256 of a file's bytes, or None when it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def strip_fenced_blocks(text):
    """Blank every fenced region, preserving line count (family rule)."""
    out, fence = [], None
    for line in text.split("\n"):
        m = FENCE_RE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                out.append("")
                continue
            out.append(line)
        else:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            out.append("")
    return out


def clean_value(raw):
    return (raw or "").strip().strip("`").strip('"').strip("'").strip()


def value_present(raw):
    v = clean_value(raw)
    return bool(v) and not PLACEHOLDER_VALUE_RE.match(v)


def parse_fields(path):
    """Every `- Key: value` line outside fences, LAST occurrence winning."""
    fields = {}
    try:
        text = read_text(path)
    except DriverError:
        return fields
    for line in strip_fenced_blocks(text):
        m = FIELD_RE.match(line)
        if m:
            fields[m.group(1).strip().lower()] = m.group(2).strip()
    return fields


# ---------------------------------------------------------------------------
# The gate ledger (read-only -- this tool is not a gate)
# ---------------------------------------------------------------------------

def read_ledger(ledger_path):
    """Every parseable JSON-object line of the ledger, in file order."""
    p = Path(ledger_path)
    if not p.is_file():
        return []
    records = []
    for line in p.read_text(encoding=READ_ENCODING,
                            errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def gate_state(records, gate_name, milestone, check_inputs=True):
    """Where a named gate stands for this unit.

    Scoping mirrors check_commit_gate.check_ledger_gates(): the latest entry
    whose milestone is this one or null. Staleness -- a PASS whose recorded
    input hashes no longer match disk -- is reported as FAIL, because a PASS
    that no longer covers the artifact is not a PASS of the artifact.

    Returns {"gate", "status" in PASS|FAIL|MISSING, "argv", "record",
             "stale", "detail"}.
    """
    res = {"gate": gate_name, "status": "MISSING", "argv": [],
           "record": None, "stale": [], "detail": None}
    candidates = [r for r in records
                  if r.get("gate") == gate_name
                  and (r.get("milestone") is None
                       or r.get("milestone") == milestone)]
    if not candidates:
        res["detail"] = ("no %s entry scoped to %r (or unscoped) in the ledger"
                         % (gate_name, milestone))
        return res
    latest = candidates[-1]
    res["record"] = latest
    res["argv"] = [str(a) for a in (latest.get("argv") or [])]
    if latest.get("verdict") != "PASS":
        res["status"] = "FAIL"
        res["detail"] = ("the latest %s ledger entry records verdict %r "
                         "(exit %s)" % (gate_name, latest.get("verdict"),
                                        latest.get("exit")))
        return res
    if check_inputs:
        for path, recorded in (latest.get("inputs") or {}).items():
            if recorded is None:
                continue
            current = sha256_file(path)
            if current is None:
                res["stale"].append("%s (missing now)" % rp(path))
            elif current != recorded:
                res["stale"].append("%s (edited since that run)" % rp(path))
    if res["stale"]:
        res["status"] = "FAIL"
        res["detail"] = ("the latest %s PASS covered inputs that no longer "
                         "match on disk: %s -- re-run it"
                         % (gate_name, ", ".join(res["stale"])))
        return res
    res["status"] = "PASS"
    return res


def block_reason(state):
    """The `blocked_by` line for a required gate that is not a standing PASS."""
    if state["status"] == "MISSING":
        return ("gate_not_run %s: %s -- run it now; the lane does not advance "
                "past this phase without it" % (state["gate"], state["detail"]))
    return "gate_not_passed %s: %s" % (state["gate"], state["detail"])


def gate_committed(state):
    """Did this gate's PASS actually carry --commit? A dry run closes nothing."""
    return state["status"] == "PASS" and "--commit" in state["argv"]


# ---------------------------------------------------------------------------
# The run_quiet.py capture (minimal copy of check_red_green.evaluate_capture)
# ---------------------------------------------------------------------------

def capture_header(text):
    """The region before `## Captured output`, fences blanked."""
    m = CAPTURED_HEADING_RE.search(text)
    head = text[:m.start()] if m else text
    out, fence = [], None
    for line in head.split("\n"):
        fm = FENCE_RE.match(line)
        if fence is None:
            if fm:
                fence = fm.group(1)
                out.append("")
                continue
            out.append(line)
        else:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
            out.append("")
    return "\n".join(out)


def capture_state(path, expect):
    """Is this a usable run_quiet.py capture with the expected outcome?

    `expect` is "zero" or "nonzero". The exit code must agree between the
    sidecar and the capture's own hash-protected body -- the sidecar is the
    claim, the body is the witness (pipeline-tools/SKILL.md).
    """
    res = {"path": rp(path), "exists": False, "exit_code": None,
           "body_exit_code": None, "argv": None, "ok": False, "problems": []}

    def fail(code, message):
        res["problems"].append("%s: %s" % (code, message))

    p = Path(path)
    if not p.is_file():
        fail("capture_missing", "no capture file at %s" % rp(path))
        return res
    res["exists"] = True
    text = p.read_text(encoding=READ_ENCODING, errors="replace")
    if not CAPTURED_HEADING_RE.search(text):
        fail("not_a_capture",
             "%s has no '## Captured output' section, so it is not a "
             "run_quiet.py capture" % rp(path))

    side = Path(str(p) + SIDECAR_SUFFIX)
    if not side.is_file():
        fail("sidecar_missing",
             "%s has no provenance sidecar at %s -- re-take it with "
             "`run_quiet.py --capture`" % (rp(path), side.name))
        return res
    try:
        meta = json.loads(side.read_text(encoding=READ_ENCODING,
                                         errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        fail("sidecar_missing", "the sidecar %s is unreadable or not valid "
                                "JSON: %s" % (side.name, exc))
        return res
    if not isinstance(meta, dict):
        fail("sidecar_missing", "the sidecar %s is not a JSON object"
                                % side.name)
        return res

    declared = meta.get("capture_sha256")
    actual = sha256_file(p)
    if not (declared and actual and declared == actual):
        fail("sidecar_hash_mismatch",
             "%s was edited after it was recorded (sha256 %s, sidecar says "
             "%s)" % (rp(path), actual, declared))

    argv = meta.get("argv")
    if isinstance(argv, list) and argv:
        res["argv"] = [str(a) for a in argv]

    body_m = BODY_EXIT_CODE_RE.search(capture_header(text))
    if body_m is not None:
        res["body_exit_code"] = int(body_m.group(1))
    side_exit = meta.get("exit_code")
    if isinstance(side_exit, int):
        res["exit_code"] = side_exit
    else:
        fail("sidecar_no_exit_code",
             "the sidecar for %s records no integer exit_code" % rp(path))
    if body_m is None:
        fail("capture_header_missing",
             "%s carries no readable '- Exit code:' header line, so the "
             "sidecar's exit_code witnesses nothing" % rp(path))
    elif isinstance(side_exit, int) and side_exit != res["body_exit_code"]:
        fail("sidecar_body_disagrees",
             "the sidecar for %s records exit_code %s but the capture's own "
             "body records '- Exit code: %s'"
             % (rp(path), side_exit, res["body_exit_code"]))

    if not res["problems"]:
        code = res["exit_code"]
        if expect == "nonzero" and code == 0:
            fail("red_exit_zero",
                 "the RED capture %s exited 0 -- a run that succeeded does "
                 "not reproduce the bug; re-take it" % rp(path))
        elif expect == "zero" and code not in (0, None):
            fail("capture_exit_nonzero",
                 "the capture %s exited %s -- the check did not pass; fix "
                 "and re-run it" % (rp(path), code))
    res["ok"] = not res["problems"]
    return res


def first_capture(directory, suffix=".md"):
    """The lexicographically first capture in a directory, or None.

    Sidecars are skipped. A lane produces one capture per role; taking the
    first (rather than guessing at a slug) means a capture named for anything
    still counts as the artifact it is.
    """
    d = Path(directory)
    if not d.is_dir():
        return None
    names = sorted(p for p in d.iterdir()
                   if p.is_file() and p.name.endswith(suffix)
                   and not p.name.endswith(SIDECAR_SUFFIX))
    return names[0] if names else None


# ---------------------------------------------------------------------------
# Lane and route detection
# ---------------------------------------------------------------------------

def detect_lane(root, requested):
    """(lane, warnings). `auto` looks for the lane's own first artifact."""
    warnings = []
    has_note = (root / "note.md").is_file()
    has_report = (root / "bug-report.md").is_file()
    if requested in ("bugfix", "quick"):
        return requested, warnings
    if has_note and has_report:
        warnings.append(
            "both note.md and bug-report.md are present in %s; --lane auto "
            "resolves to quick -- pass --lane bugfix if that is wrong"
            % rp(root))
    if has_note:
        return "quick", warnings
    if has_report:
        return "bugfix", warnings
    raise DriverError(
        "no lane detected in %s: no note.md (bgpdd-quick) and no "
        "bug-report.md (bgpdd-bugfix). Pass --lane explicitly to start one "
        "from Phase 0." % rp(root))


def detect_bugfix_route(root):
    """(route, state_file). Which of the two bugfix workspaces this is.

    bgpdd-bugfix SKILL.md section 1: on the FEATURE route the root is
    `.docs/{project}/implementation/bugs/{bug-slug}/` (2.6.1, slug-scoped)
    and the state file is the epic's own, THREE LEVELS UP; the pre-2.6.1
    unscoped shape -- the root IS the epic's `implementation/` folder, state
    file one level up -- is still recognised so an in-flight 2.6.0 bug keeps
    driving. On the STANDALONE route the root is `.docs/bugfix/{slug}/` and
    the state file is inside it. Phase 0 has not created the standalone state
    yet, so folder shape -- not the file's presence -- decides the route.
    """
    own = root / "orchestrator-state.json"
    if (root.parent.name.lower() == "bugs"
            and root.parent.parent.name.lower() == "implementation"):
        up = root.parent.parent.parent / "orchestrator-state.json"
    elif root.name.lower() == "implementation":
        up = root.parent / "orchestrator-state.json"
    else:
        return "standalone", own
    if not up.is_file():
        raise DriverError(
            "feature-route root %s has no epic orchestrator-state.json at "
            "%s -- a feature route with no epic state is a mis-resolved "
            "root (bgpdd-bugfix Phase 0 step 4 says HALT). Use the "
            "standalone route, or fix the resolution."
            % (rp(root), rp(up)))
    return "feature", up


def derive_slug(root, lane, records, override, gate_name):
    """The unit slug used to scope every ledger lookup and evidence path.

    Order: an explicit --milestone; the ledger's own record for this lane's
    first gate; the RED capture's filename; the root's basename. On the
    2.6.1 feature route the basename IS the bug slug (`bugs/{bug-slug}/`);
    the override exists for the pre-2.6.1 shape, where the basename is
    `implementation` and names the epic, never the bug.
    """
    if override:
        return override, "override"
    for rec in reversed(records):
        if rec.get("gate") == gate_name and isinstance(rec.get("milestone"), str) \
                and rec["milestone"].strip():
            return rec["milestone"].strip(), "ledger"
    if lane == "bugfix":
        red = first_capture(root / "evidence" / "red")
        if red is not None:
            return red.stem, "red-capture"
        if root.name.lower() != "implementation":
            return root.name, "root"
        return None, None
    return DATE_PREFIX_RE.sub("", root.name), "root"


# ---------------------------------------------------------------------------
# bgpdd-bugfix
# ---------------------------------------------------------------------------

BUGFIX_PHASE_NAMES = {
    0: "Intake",
    1: "Reproduce - RED (Quinn)",
    2: "Isolate - RCA and route",
    3: "Fix (Mason and/or Nova)",
    4: "Verify - GREEN (Quinn)",
    5: "Review and Close (Luna, then Orchestrator)",
    6: "Complete",
}

QUICK_PHASE_NAMES = {
    0: "Scope",
    1: "Change and Prove",
    3: "Close (the gate)",
    4: "Complete",
}


def _script(name):
    return "python %s" % rp(SCRIPTS_DIR / name)


def repo_root_for(root):
    """The repository the lane root sits inside, or None.

    A quick lane root is `<repo>/.docs/quick/<date>-<slug>/`, so the repo is
    the nearest ancestor holding a `.git` entry; failing that, the parent of
    the nearest `.docs` ancestor. Both are structural reads of the path, never
    a guess about the caller's cwd.
    """
    try:
        here = Path(root).resolve()
    except OSError:
        return None
    for candidate in [here] + list(here.parents):
        if (candidate / ".git").exists():
            return candidate
    for candidate in [here] + list(here.parents):
        if candidate.name == ".docs" and candidate.parent != candidate:
            return candidate.parent
    return None


_DETECT_CACHE = {}


def detect_report(root):
    """({...}|None, warning) -- detect_stack.py's JSON for the lane's repo.

    Shelled out to rather than imported: this family's convention is one
    self-contained stdlib file per script, and copying the stack table here
    would give the quick lane two tables to keep in step. Best-effort by
    design -- a missing detector, a non-zero exit, unparseable JSON or a repo
    the path walk cannot find all yield None, and the caller simply drops the
    clause it would have added. Only an absent detector is worth a warning:
    that is a broken install, not a repo the table has nothing to say about.
    Cached per repo so one driver run costs at most one tree walk.
    """
    detector = SCRIPTS_DIR / "detect_stack.py"
    if not detector.is_file():
        return None, ("detect_stack.py is not beside this script, so no "
                      "stack defaults could be suggested")
    repo = repo_root_for(root)
    if repo is None:
        return None, None
    key = str(repo)
    if key in _DETECT_CACHE:
        return _DETECT_CACHE[key], None
    data = None
    try:
        proc = subprocess.run(
            [sys.executable, str(detector), "--repo", key, "--json"],
            capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            parsed = json.loads(proc.stdout)
            if isinstance(parsed, dict):
                data = parsed
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        data = None
    _DETECT_CACHE[key] = data
    return data, None


def _string_list(data, key):
    values = (data or {}).get(key)
    if not isinstance(values, list):
        return []
    return [v for v in values if isinstance(v, str) and v.strip()]


def suggested_check_command(root):
    """(command, warning) -- detect_stack.py's FIRST suggested check, or None."""
    data, warning = detect_report(root)
    commands = _string_list(data, "suggested_check_commands")
    return (commands[0] if commands else None), warning


def suggested_frozen_flags(root):
    """The `--frozen` flags for the close command, from the detected stack.

    Falls back to `--frozen tests/` when the detector names nothing -- a
    printed EXAMPLE the caller edits, not a default inside the gate, which
    deliberately has none (`check_quick_close.py`: the gate must not guess
    what is frozen).
    """
    globs = _string_list(detect_report(root)[0], "test_path_globs")
    if not globs:
        return "--frozen tests/"
    return " ".join("--frozen '%s'" % g for g in globs)


def _surface_personas(surface):
    if surface == "ui":
        return "Nova", "nova"
    if surface == "both":
        return "Mason (api) and Nova (ui)", "mason"
    return "Mason", "mason"


def build_bugfix_report(root, ledger, milestone_override):
    records = read_ledger(ledger)
    route, state_file = detect_bugfix_route(root)
    slug, slug_source = derive_slug(root, "bugfix", records, milestone_override,
                                    "check_bugfix_intake.py")
    slug_label = slug or "<bug-slug>"

    report_md = root / "bug-report.md"
    rca_md = root / "rca.md"
    run_log = root / "run-log.jsonl"
    review_md = root / "review-report.md"
    package_md = root / "review-package.md"
    test_report = root / "test-report.md"

    present, missing = {}, []

    def note(name, path):
        if Path(path).exists():
            present[name] = rp(path)
        else:
            missing.append(name)

    note("bug-report.md", report_md)
    note("rca.md", rca_md)
    note("run-log.jsonl", run_log)
    note("test-report.md", test_report)
    note("review-package.md", package_md)
    note("review-report.md", review_md)
    note("orchestrator-state.json", state_file)

    fields = parse_fields(report_md) if report_md.is_file() else {}
    command = clean_value(fields.get("command", ""))
    surface = clean_value(fields.get("surface", "")).lower() or "api"
    runtime_observable = clean_value(
        fields.get("runtime observable", "")).lower() == "yes"
    command_text = command if value_present(command) else \
        "<the reproduction command from bug-report.md's '- Command:' line>"

    out = {
        "root": rp(root),
        "lane": "bugfix",
        "route": route,
        "state_file": rp(state_file),
        "milestone": slug,
        "milestone_source": slug_source,
        "ledger": rp(ledger),
        "phase": 0,
        "phase_name": BUGFIX_PHASE_NAMES[0],
        "next_action": None,
        "required_gate": None,
        "required_gates": [],
        "gate_status": None,
        "blocked_by": [],
        "artifacts_present": present,
        "artifacts_missing": missing,
        "warnings": [],
        "error": None,
    }
    if slug is None:
        out["warnings"].append(
            "no bug slug could be derived on the feature route (the root's "
            "basename names the epic). Pass --milestone \"<bug-slug>\"; the "
            "ledger lookups below fall back to unscoped entries only.")

    def emit(phase, action, gate_st=None, gates=None):
        out["phase"] = phase
        out["phase_name"] = BUGFIX_PHASE_NAMES[phase]
        out["next_action"] = action
        out["required_gate"] = gate_st["gate"] if gate_st else None
        out["required_gates"] = gates if gates is not None else \
            ([gate_st["gate"]] if gate_st else [])
        out["gate_status"] = gate_st["status"] if gate_st else None
        if gate_st and gate_st["status"] != "PASS":
            out["blocked_by"].append(block_reason(gate_st))
        return out

    # --- Phase 0: intake ---------------------------------------------------
    if not report_md.is_file():
        return emit(0,
                    "Write %s with the user from "
                    "bgpdd-bugfix/references/bug-report-template.md -- every "
                    "section, no placeholders, and a '- Command:' line that "
                    "exits non-zero while the bug is present."
                    % rp(report_md))

    intake = gate_state(records, "check_bugfix_intake.py", slug)
    intake_cmd = ('%s --report %s --milestone "%s" --ledger %s'
                  % (_script("check_bugfix_intake.py"), rp(report_md),
                     slug_label, rp(ledger)))
    if intake["status"] != "PASS":
        return emit(0, "Run: %s" % intake_cmd, intake)

    # --- Phase 1: RED ------------------------------------------------------
    red_path = first_capture(root / "evidence" / "red")
    red_cmd = ("Delegate Quinn to capture the pre-fix RED, briefing her with "
               "the reproduction command copied verbatim: %s --capture %s -- %s"
               % (_script("run_quiet.py"),
                  rp(root / "evidence" / "red" / ("%s.md" % slug_label)),
                  command_text))
    if red_path is None:
        missing.append("evidence/red/<capture>.md")
        return emit(1, red_cmd)
    red = capture_state(red_path, "nonzero")
    present["evidence/red"] = red["path"]
    if not red["ok"]:
        out["blocked_by"].extend(red["problems"])
        return emit(1, red_cmd)

    # --- Phase 2: RCA and route -------------------------------------------
    route_cmd = ('%s --report %s --rca %s --red %s --milestone "%s" '
                 "--ledger %s --max-changed-files 5"
                 % (_script("next_bugfix_route.py"), rp(report_md), rp(rca_md),
                    red["path"], slug_label, rp(ledger)))
    if not rca_md.is_file():
        return emit(2,
                    "Write %s yourself in the main session (no delegation) "
                    "from bgpdd-bugfix/references/rca-template.md: the "
                    "hypothesis ledger, one '- Root cause file:' per file, "
                    "and the '## Fix shape' fields the route gate reads."
                    % rp(rca_md))

    route_gate = gate_state(records, "next_bugfix_route.py", slug)
    if route_gate["status"] != "PASS":
        return emit(2, "Run: %s" % route_cmd, route_gate)

    recorded_route = (route_gate["record"] or {}).get("route")
    if isinstance(recorded_route, str) and recorded_route:
        route_note = ("the route gate recorded %s" % recorded_route)
    else:
        route_note = ("the ledger does not record which of FAST/FULL the "
                      "route gate printed -- re-run `%s` to re-read it before "
                      "deciding whether to pause for the user" % route_cmd)
    out["warnings"].append("FAST vs FULL: %s. Neither route skips RED, GREEN, "
                           "Luna or the commit gate." % route_note)

    # --- Phase 3: fix ------------------------------------------------------
    personas, agent = _surface_personas(surface)
    delegated = False
    if run_log.is_file():
        for rec in read_ledger(run_log):
            if rec.get("event") == "delegation" and \
                    str(rec.get("agent") or "").lower() in BUILDER_AGENTS:
                delegated = True
                break
    if not delegated:
        return emit(3,
                    "Delegate %s to make the fix from rca.md's root cause -- "
                    "uncommitted, and neither the RED capture nor its command "
                    "may be edited. On return run: %s --log %s --pipeline "
                    'bgpdd-bugfix --phase "Phase 3: Fix" --event delegation '
                    '--agent %s --model <tier> --unit "%s"'
                    % (personas, _script("record_run.py"), rp(run_log), agent,
                       slug_label))

    # --- Phase 4: GREEN ----------------------------------------------------
    green_path = first_capture(root / "evidence" / "green")
    runtime_green = first_capture(root / "evidence" / "runtime")
    chosen_green = green_path or runtime_green
    green_cmd = ("Delegate Quinn to re-run the SAME command the RED sidecar "
                 "records and capture GREEN: %s --capture %s -- %s"
                 % (_script("run_quiet.py"),
                    rp(root / "evidence" / "green" / ("%s.md" % slug_label)),
                    " ".join(red["argv"]) if red["argv"] else command_text))
    if runtime_observable:
        green_cmd += (" ; the bug is runtime-observable, so she also takes an "
                      "out-of-process capture under %s and appends a "
                      "'**Runtime evidence:**' citation to %s"
                      % (rp(root / "evidence" / "runtime"), rp(test_report)))
    if chosen_green is None:
        missing.append("evidence/green/<capture>.md")
        return emit(4, green_cmd)
    green = capture_state(chosen_green, "zero")
    present["evidence/green"] = green["path"]
    if not green["ok"]:
        out["blocked_by"].extend(green["problems"])
        return emit(4, green_cmd)

    needed = ["check_red_green.py"]
    if runtime_observable:
        needed.append("check_runtime_evidence.py")
    gate_cmds = {
        "check_red_green.py": (
            '%s --red %s --green %s --milestone "%s" --ledger %s'
            % (_script("check_red_green.py"), red["path"], green["path"],
               slug_label, rp(ledger))),
        "check_runtime_evidence.py": (
            '%s --report %s --milestone "%s" --changed-files <the builder\'s '
            "paths> --repo . --surface %s --ledger %s"
            % (_script("check_runtime_evidence.py"), rp(test_report),
               slug_label, surface if surface in ("api", "ui") else "api",
               rp(ledger))),
    }
    for name in needed:
        st = gate_state(records, name, slug)
        if st["status"] != "PASS":
            return emit(4, "Run: %s" % gate_cmds[name], st, gates=needed)

    # --- Phase 5: review and close ----------------------------------------
    commit_gate_cmd = (
        '%s --review-report %s --state %s --milestone "%s" --changed-files '
        "<the builder's paths> --verify-tree --max-changed-files 5 --waiver %s "
        "--require-ledger-gates %s --ledger %s --commit "
        '--message "<the commit message>"'
        % (_script("check_commit_gate.py"), rp(review_md), rp(state_file),
           slug_label, rp(rca_md),
           ",".join(["check_bugfix_intake.py", "check_red_green.py"]
                    + (["check_runtime_evidence.py"] if runtime_observable
                       else [])),
           rp(ledger)))

    if not package_md.is_file():
        return emit(5,
                    "Run: %s --repo . --base HEAD --head WORKTREE "
                    "--changed-files <the builder's paths> --out %s "
                    '--ledger %s --milestone "%s"'
                    % (_script("review_package.py"), rp(package_md),
                       rp(ledger), slug_label))

    if not review_section_verdict(review_md, slug):
        return emit(5,
                    "Delegate a FRESH Luna with %s, the builder's "
                    "<changed_files> and <consumers>, the root cause and the "
                    "RED path she must confirm was not modified; she APPENDS "
                    "a '## Review: %s' section with its '**Verdict:**' line "
                    "to %s."
                    % (rp(package_md), slug_label, rp(review_md)))

    commit = gate_state(records, "check_commit_gate.py", slug,
                        check_inputs=False)
    if not gate_committed(commit):
        if commit["status"] == "PASS":
            out["warnings"].append(
                "check_commit_gate.py PASSed but its argv carries no "
                "--commit, so nothing was committed: that was a dry run.")
        return emit(5, "Run: %s" % commit_gate_cmd, commit)

    # --- complete ----------------------------------------------------------
    close = ("Lane complete: the commit gate PASSed with --commit. Close it -- "
             "(1) Tier-1 write-back: with a .docs/summary/{feature}/ base, "
             "append the reproduced case to "
             ".docs/summary/{feature}/QA/manual-testing.md in Echo's "
             "GO -> DO -> ASSERT shape under Regression Risks (no base: write "
             "nothing and say so); (2) leave %s standing and its `pipeline` "
             "as you found it; (3) name exactly one next command: "
             "/bgpdd-verify {feature}, /bgpdd-shipping or /bgpdd-build."
             % rp(state_file))
    if route == "standalone":
        close += (" (4) Standalone route: close the branch -- offer merge "
                  "locally, publish and open a PR, or keep the branch, and "
                  "after a merge capture the project's test command with "
                  "%s --capture %s -- <the project's test command>."
                  % (_script("run_quiet.py"), rp(root / "evidence"
                                                 / "post-merge.md")))
    else:
        close += (" (4) Feature route: there is NO branch to close -- the fix "
                  "rode the epic's own branch; say so plainly and stop.")
    return emit(6, close, commit)


def review_section_verdict(review_path, slug):
    """Is there a `## Review: <slug>` section carrying a `**Verdict:**` line?

    Minimal copy of check_commit_gate.py's section walk: any level-2..6
    heading closes an open review section, and the slug is matched as a whole
    token in the heading's title so `auth-500` never satisfies `auth-500-b`.
    """
    p = Path(review_path)
    if not p.is_file():
        return False
    token = re.compile(r"(?<![0-9A-Za-z_-])%s(?![0-9A-Za-z_-])"
                       % re.escape(slug or ""), re.IGNORECASE) if slug else None
    in_section = False
    for line in strip_fenced_blocks(p.read_text(encoding=READ_ENCODING,
                                                errors="replace")):
        m = REVIEW_HEADING_RE.match(line)
        if m:
            title = m.group(1).strip()
            in_section = True if token is None else bool(token.search(title))
            continue
        if in_section and ANY_HEADING_RE.match(line):
            in_section = False
            continue
        if in_section and VERDICT_LINE_RE.match(line):
            return True
    return False


# ---------------------------------------------------------------------------
# bgpdd-quick
# ---------------------------------------------------------------------------

QUICK_NOTE_KEYS = ("what", "where", "how verified")


def parse_where(raw):
    """Path tokens from a Where line: comma- and/or whitespace-separated."""
    out = []
    for chunk in re.split(r"[,\s]+", clean_value(raw)):
        tok = chunk.strip().strip("`").strip()
        if tok:
            out.append(tok)
    return out


def build_quick_report(root, ledger, milestone_override):
    records = read_ledger(ledger)
    slug, slug_source = derive_slug(root, "quick", records, milestone_override,
                                    "check_quick_close.py")
    slug_label = slug or "<slug>"

    note_md = root / "note.md"
    check_md = root / "evidence" / "check.md"

    present, missing = {}, []
    for name, path in (("note.md", note_md), ("evidence/check.md", check_md)):
        if path.exists():
            present[name] = rp(path)
        else:
            missing.append(name)

    out = {
        "root": rp(root),
        "lane": "quick",
        "route": None,
        "state_file": None,
        "milestone": slug,
        "milestone_source": slug_source,
        "ledger": rp(ledger),
        "phase": 0,
        "phase_name": QUICK_PHASE_NAMES[0],
        "next_action": None,
        "required_gate": None,
        "required_gates": [],
        "gate_status": None,
        "blocked_by": [],
        "artifacts_present": present,
        "artifacts_missing": missing,
        "warnings": [],
        "error": None,
    }

    def emit(phase, action, gate_st=None):
        out["phase"] = phase
        out["phase_name"] = QUICK_PHASE_NAMES[phase]
        out["next_action"] = action
        out["required_gate"] = gate_st["gate"] if gate_st else None
        out["required_gates"] = [gate_st["gate"]] if gate_st else []
        out["gate_status"] = gate_st["status"] if gate_st else None
        if gate_st and gate_st["status"] != "PASS":
            out["blocked_by"].append(block_reason(gate_st))
        return out

    # --- Phase 0: scope ----------------------------------------------------
    fields = parse_fields(note_md) if note_md.is_file() else {}
    absent = [k for k in QUICK_NOTE_KEYS if not value_present(fields.get(k, ""))]
    if not note_md.is_file() or absent:
        detail = ("Write %s with three labelled, non-placeholder lines: "
                  "'- What:' the one sentence, '- Where:' every file you will "
                  "touch (<= 3, comma-separated), '- How verified:' the exact "
                  "command." % rp(note_md))
        if note_md.is_file():
            detail = ("Complete %s: the line(s) %s are missing or still a "
                      "placeholder." % (rp(note_md),
                                        ", ".join(repr(a) for a in absent)))
        suggested, detect_warning = suggested_check_command(root)
        if detect_warning:
            out["warnings"].append(detect_warning)
        if suggested and (not note_md.is_file() or "how verified" in absent):
            detail += (" Detected stack suggests `%s` for 'How verified' "
                       "(%s --repo . --json for the full set, including the "
                       "test_path_globs Phase 3 passes as --frozen); confirm "
                       "or replace it with the user -- never adopt it "
                       "silently." % (suggested, _script("detect_stack.py")))
        return emit(0, detail)

    where = parse_where(fields.get("where", ""))
    how = clean_value(fields.get("how verified", ""))

    # --- Phases 1 and 2: change, then prove --------------------------------
    # Fused deliberately: an edit leaves no artifact of its own, so the driver
    # cannot see Phase 1 end. The capture is what Phase 2 produces and what
    # Phase 3 reads, so it is the only observable boundary either phase has.
    prove_cmd = ("Edit only the files the note's Where line names (%s), then "
                 "run the check through the capture wrapper: %s --capture %s "
                 "-- %s"
                 % (", ".join(where) or "<the Where line's paths>",
                    _script("run_quiet.py"), rp(check_md), how or "<the "
                    "How verified command>"))
    if not check_md.is_file():
        return emit(1, prove_cmd)
    check = capture_state(check_md, "zero")
    present["evidence/check.md"] = check["path"]
    if not check["ok"]:
        out["blocked_by"].extend(check["problems"])
        return emit(1, prove_cmd)

    # --- Phase 3: close ----------------------------------------------------
    close_cmd = ("%s --note %s --capture %s --changed-files %s --repo . "
                 '--max-changed-files 3 %s --milestone "%s" '
                 '--ledger %s --commit --message "<msg>"'
                 % (_script("check_quick_close.py"), rp(note_md), rp(check_md),
                    " ".join(where) or "<paths>", suggested_frozen_flags(root),
                    slug_label, rp(ledger)))
    close = gate_state(records, "check_quick_close.py", slug,
                       check_inputs=False)
    if not gate_committed(close):
        if close["status"] == "PASS":
            out["warnings"].append(
                "check_quick_close.py PASSed but its argv carries no "
                "--commit, so nothing was committed: that was a dry run.")
        return emit(3, "Run: %s" % close_cmd, close)

    return emit(4,
                "Lane complete: the close gate PASSed with --commit and "
                "committed exactly the declared files. Append the one-bullet "
                "'## Result' game tape to %s -- what the gate said, plus what "
                "surprised you." % rp(note_md), close)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def build_report(args):
    root = Path(args.root)
    if not root.is_dir():
        raise DriverError("lane root is not a readable directory: %s"
                          % rp(args.root))
    lane, warnings = detect_lane(root, args.lane)
    ledger = Path(args.ledger) if args.ledger else root / "gates.jsonl"
    if lane == "bugfix":
        out = build_bugfix_report(root, ledger, args.milestone)
    else:
        out = build_quick_report(root, ledger, args.milestone)
    out["warnings"] = warnings + out["warnings"]
    return out


def exit_code_for(report):
    if report["blocked_by"]:
        return EXIT_BLOCKED
    if report["lane"] == "bugfix" and report["phase"] == 6:
        return EXIT_COMPLETE
    if report["lane"] == "quick" and report["phase"] == 4:
        return EXIT_COMPLETE
    return EXIT_NEXT


def render_human(report, code):
    lines = [
        "lane:   %s%s" % (report["lane"],
                          "" if not report.get("route")
                          else " (%s route)" % report["route"]),
        "phase:  %s - %s" % (report["phase"], report["phase_name"]),
        "gate:   %s [%s]" % (report["required_gate"] or "none",
                             report["gate_status"] or "n/a"),
        "next:   %s" % (report["next_action"] or "(none)"),
    ]
    for b in report["blocked_by"]:
        lines.append("BLOCKED %s" % b)
    for w in report["warnings"]:
        lines.append("warn:   %s" % w)
    lines.append("exit:   %s" % code)
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(prog="pipeline_driver.py")
    parser.add_argument("--root", help="the lane root directory")
    parser.add_argument("--lane", choices=("bugfix", "quick", "auto"),
                        default="auto",
                        help="force a lane; 'auto' (default) detects it from "
                             "the root's first artifact")
    parser.add_argument("--ledger",
                        help="the gate ledger to READ (default "
                             "<root>/gates.jsonl); this tool grants no verdict "
                             "and never writes it")
    parser.add_argument("--milestone",
                        help="the unit slug, overriding derivation -- REQUIRED "
                             "on the bugfix feature route, whose root basename "
                             "names the epic and not the bug")
    parser.add_argument("--json", action="store_true",
                        help="emit the machine-readable report instead of the "
                             "human block")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()
    if not args.root:
        print(json.dumps({"error": "missing required argument: --root",
                          "phase": None, "next_action": None,
                          "blocked_by": []}))
        return EXIT_ERROR
    try:
        report = build_report(args)
    except DriverError as exc:
        payload = {"root": rp(args.root), "lane": None, "phase": None,
                   "phase_name": None, "next_action": None,
                   "required_gate": None, "gate_status": None,
                   "blocked_by": [], "artifacts_present": {},
                   "artifacts_missing": [], "warnings": [],
                   "error": str(exc)}
        print(json.dumps(payload, indent=2) if args.json
              else "error:  %s" % exc)
        return EXIT_ERROR
    code = exit_code_for(report)
    report["exit"] = code
    print(json.dumps(report, indent=2) if args.json
          else render_human(report, code))
    return code


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil
    import tempfile
    import unittest

    CAPTURE_TMPL = ("# Capture\n\n- Command: `%s`\n- Exit code: %d\n"
                    "- Captured: 2026-09-07T10:00:00Z\n\n"
                    "## Captured output\n\n```\nstuff\n```\n")

    REPORT_TMPL = (
        "# Bug report: {slug}\n\n"
        "## Observed behaviour\n\nPOST /api/orders returns 500.\n\n"
        "## Expected behaviour\n\nIt returns 201.\n\n"
        "## Reproduction\n\n- Command: `{command}`\n\n"
        "## Environment\n\n- Surface: {surface}\n"
        "- Runtime observable: {runtime}\n- Regression: no\n")

    class Base(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.root = self.dir / "bug-slug"
            self.root.mkdir(parents=True)
            self.ledger = self.root / "gates.jsonl"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        # -- fixture builders -------------------------------------------
        def write(self, rel, text):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            return p

        def capture(self, rel, exit_code, argv=("pytest", "-q")):
            body = CAPTURE_TMPL % (" ".join(argv), exit_code)
            p = self.write(rel, body)
            side = Path(str(p) + SIDECAR_SUFFIX)
            side.write_text(json.dumps({
                "argv": list(argv), "exit_code": exit_code,
                "finished": "2026-09-07T10:00:00Z",
                "capture_sha256": sha256_file(p)}), encoding="utf-8")
            return p

        def ledger_line(self, gate, verdict="PASS", milestone="bug-slug",
                        inputs=None, argv=None, exit_code=0, **extra):
            rec = {"ts": "2026-09-07T10:00:00Z", "gate": gate,
                   "argv": argv if argv is not None else ["--x"],
                   "milestone": milestone,
                   "inputs": {rp(k): sha256_file(k)
                              for k in (inputs or [])},
                   "verdict": verdict, "exit": exit_code}
            rec.update(extra)
            with open(self.ledger, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")

        def run_driver(self, lane="auto", root=None, milestone=None,
                       ledger=None):
            ns = argparse.Namespace(
                root=str(root or self.root), lane=lane,
                ledger=str(ledger) if ledger else None, milestone=milestone,
                json=True, self_test=False)
            rep = build_report(ns)
            return rep, exit_code_for(rep)

        # -- lane stage helpers ------------------------------------------
        def stage_intake(self, surface="api", runtime="no",
                         command="pytest -q tests/test_orders.py"):
            r = self.write("bug-report.md", REPORT_TMPL.format(
                slug="bug-slug", command=command, surface=surface,
                runtime=runtime))
            self.ledger_line("check_bugfix_intake.py", inputs=[r])
            return r

        def stage_red(self):
            return self.capture("evidence/red/bug-slug.md", 3)

        def stage_rca(self):
            rca = self.write("rca.md", "# RCA\n\n- Root cause file: src/a.py\n")
            self.ledger_line("next_bugfix_route.py", inputs=[rca])
            return rca

        def stage_delegation(self, agent="mason"):
            with open(self.root / "run-log.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"pipeline": "bgpdd-bugfix",
                                     "phase": "Phase 3: Fix", "agent": agent,
                                     "event": "delegation", "model": "sonnet",
                                     "unit": "bug-slug"}) + "\n")

        def stage_green(self, runtime=False):
            g = self.capture("evidence/green/bug-slug.md", 0)
            self.ledger_line("check_red_green.py", inputs=[g])
            if runtime:
                self.write("test-report.md", "# Tests\n")
                self.ledger_line("check_runtime_evidence.py")
            return g

        def stage_review(self, slug="bug-slug"):
            self.write("review-package.md", "# Package\n")
            self.write("review-report.md",
                       "## Review: %s\n\n**Verdict:** Approve\n" % slug)

    # ---------------------------------------------------------------- bugfix
    class BugfixPhaseTests(Base):
        def test_no_lane_detected_exits_2(self):
            with self.assertRaises(DriverError) as ctx:
                self.run_driver()
            self.assertIn("no lane detected", str(ctx.exception))

        def test_root_not_a_directory_exits_2(self):
            with self.assertRaises(DriverError) as ctx:
                self.run_driver(root=self.root / "nope")
            self.assertIn("not a readable directory", str(ctx.exception))

        def test_phase0_no_report_asks_for_the_report(self):
            rep, code = self.run_driver(lane="bugfix")
            self.assertEqual(rep["phase"], 0)
            self.assertEqual(code, EXIT_NEXT)
            self.assertIn("bug-report.md", rep["next_action"])
            self.assertIn("bug-report.md", rep["artifacts_missing"])

        def test_phase0_ledger_absent_gives_the_intake_command(self):
            self.write("bug-report.md", REPORT_TMPL.format(
                slug="s", command="pytest -q", surface="api", runtime="no"))
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (0, EXIT_BLOCKED))
            self.assertEqual(rep["required_gate"], "check_bugfix_intake.py")
            self.assertEqual(rep["gate_status"], "MISSING")
            self.assertIn("check_bugfix_intake.py", rep["next_action"])
            self.assertTrue(any(b.startswith("gate_not_run check_bugfix_"
                                             "intake.py")
                                for b in rep["blocked_by"]))

        def test_intake_fail_record_blocks(self):
            r = self.write("bug-report.md", REPORT_TMPL.format(
                slug="s", command="pytest -q", surface="api", runtime="no"))
            self.ledger_line("check_bugfix_intake.py", verdict="FAIL",
                             inputs=[r], exit_code=1)
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (0, EXIT_BLOCKED))
            self.assertEqual(rep["gate_status"], "FAIL")
            self.assertTrue(any("gate_not_passed check_bugfix_intake.py" in b
                                for b in rep["blocked_by"]))

        def test_report_edited_after_intake_pass_blocks(self):
            r = self.stage_intake()
            r.write_text(r.read_text(encoding="utf-8") + "\nedited later\n",
                         encoding="utf-8")
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (0, EXIT_BLOCKED))
            self.assertTrue(any("edited since that run" in b
                                for b in rep["blocked_by"]))

        def test_phase1_after_intake_pass_asks_quinn_for_red(self):
            self.stage_intake()
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (1, EXIT_NEXT))
            self.assertIn("Quinn", rep["next_action"])
            self.assertIn("run_quiet.py", rep["next_action"])
            self.assertIn("pytest -q tests/test_orders.py",
                          rep["next_action"])
            self.assertIsNone(rep["required_gate"])

        def test_red_that_exited_zero_blocks_at_phase1(self):
            self.stage_intake()
            self.capture("evidence/red/bug-slug.md", 0)
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (1, EXIT_BLOCKED))
            self.assertTrue(any("red_exit_zero" in b
                                for b in rep["blocked_by"]))

        def test_red_without_a_sidecar_blocks_at_phase1(self):
            self.stage_intake()
            self.write("evidence/red/bug-slug.md", CAPTURE_TMPL % ("x", 3))
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (1, EXIT_BLOCKED))
            self.assertTrue(any("sidecar_missing" in b
                                for b in rep["blocked_by"]))

        def test_red_edited_after_capture_blocks_at_phase1(self):
            self.stage_intake()
            p = self.stage_red()
            p.write_text(p.read_text(encoding="utf-8") + "tampered\n",
                         encoding="utf-8")
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (1, EXIT_BLOCKED))
            self.assertTrue(any("sidecar_hash_mismatch" in b
                                for b in rep["blocked_by"]))

        def test_phase2_valid_red_asks_for_the_rca(self):
            self.stage_intake()
            self.stage_red()
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (2, EXIT_NEXT))
            self.assertIn("rca.md", rep["next_action"])
            # Authoring an artifact is not a gate: nothing to run yet.
            self.assertIsNone(rep["required_gate"])
            self.assertEqual(rep["blocked_by"], [])

        def test_phase2_rca_without_route_gate_gives_the_gate_command(self):
            self.stage_intake()
            self.stage_red()
            self.write("rca.md", "# RCA\n\n- Root cause file: src/a.py\n")
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (2, EXIT_BLOCKED))
            self.assertIn("next_bugfix_route.py", rep["next_action"])
            self.assertIn("--max-changed-files 5", rep["next_action"])

        def test_skipping_the_route_gate_does_not_advance_to_phase3(self):
            # The deliberate skip: the fix has already been delegated, but the
            # route gate never ran. The driver refuses to look past Phase 2.
            self.stage_intake()
            self.stage_red()
            self.write("rca.md", "# RCA\n\n- Root cause file: src/a.py\n")
            self.stage_delegation()
            rep, code = self.run_driver()
            self.assertEqual(rep["phase"], 2)
            self.assertEqual(rep["required_gate"], "next_bugfix_route.py")

        def test_route_gate_fail_blocks(self):
            self.stage_intake()
            self.stage_red()
            rca = self.write("rca.md", "# RCA\n")
            self.ledger_line("next_bugfix_route.py", verdict="FAIL",
                             inputs=[rca], exit_code=1)
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (2, EXIT_BLOCKED))
            self.assertTrue(any("gate_not_passed next_bugfix_route.py" in b
                                for b in rep["blocked_by"]))

        def test_phase3_names_mason_for_an_api_surface(self):
            self.stage_intake(surface="api")
            self.stage_red()
            self.stage_rca()
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (3, EXIT_NEXT))
            self.assertIn("Mason", rep["next_action"])
            self.assertIn("record_run.py", rep["next_action"])

        def test_phase3_names_both_builders_for_surface_both(self):
            self.stage_intake(surface="both")
            self.stage_red()
            self.stage_rca()
            rep, _ = self.run_driver()
            self.assertIn("Mason (api) and Nova (ui)", rep["next_action"])

        def test_phase3_route_note_says_rerun_when_unrecorded(self):
            self.stage_intake()
            self.stage_red()
            self.stage_rca()
            rep, _ = self.run_driver()
            self.assertTrue(any("FAST vs FULL" in w for w in rep["warnings"]))
            self.assertTrue(any("re-run" in w for w in rep["warnings"]))

        def test_phase3_route_note_reports_a_recorded_route(self):
            self.stage_intake()
            self.stage_red()
            rca = self.write("rca.md", "# RCA\n")
            self.ledger_line("next_bugfix_route.py", inputs=[rca], route="FAST")
            rep, _ = self.run_driver()
            self.assertTrue(any("recorded FAST" in w for w in rep["warnings"]))

        def test_a_non_builder_delegation_does_not_advance_phase3(self):
            self.stage_intake()
            self.stage_red()
            self.stage_rca()
            self.stage_delegation(agent="quinn")
            rep, _ = self.run_driver()
            self.assertEqual(rep["phase"], 3)

        def test_phase4_missing_green_asks_quinn_for_it(self):
            self.stage_intake()
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (4, EXIT_NEXT))
            self.assertIn("GREEN", rep["next_action"])
            self.assertIn("evidence/green/<capture>.md",
                          rep["artifacts_missing"])

        def test_phase4_green_without_the_gate_gives_check_red_green(self):
            self.stage_intake()
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            self.capture("evidence/green/bug-slug.md", 0)
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (4, EXIT_BLOCKED))
            self.assertEqual(rep["required_gate"], "check_red_green.py")
            self.assertIn("check_red_green.py", rep["next_action"])

        def test_green_that_exited_nonzero_blocks(self):
            self.stage_intake()
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            self.capture("evidence/green/bug-slug.md", 1)
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (4, EXIT_BLOCKED))
            self.assertTrue(any("capture_exit_nonzero" in b
                                for b in rep["blocked_by"]))

        def test_runtime_observable_requires_the_runtime_gate(self):
            self.stage_intake(runtime="yes")
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            g = self.capture("evidence/green/bug-slug.md", 0)
            self.ledger_line("check_red_green.py", inputs=[g])
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (4, EXIT_BLOCKED))
            self.assertEqual(rep["required_gate"], "check_runtime_evidence.py")
            self.assertEqual(rep["required_gates"],
                             ["check_red_green.py", "check_runtime_evidence.py"])

        def test_runtime_not_observable_needs_only_red_green(self):
            self.stage_intake(runtime="no")
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            self.stage_green()
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (5, EXIT_NEXT))
            self.assertIn("review_package.py", rep["next_action"])

        def test_phase5_asks_for_the_review_package_first(self):
            self.stage_intake()
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            self.stage_green()
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (5, EXIT_NEXT))
            self.assertIn("review_package.py", rep["next_action"])

        def test_phase5_then_asks_for_a_fresh_luna(self):
            self.stage_intake()
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            self.stage_green()
            self.write("review-package.md", "# Package\n")
            rep, _ = self.run_driver()
            self.assertEqual(rep["phase"], 5)
            self.assertIn("Luna", rep["next_action"])

        def test_a_review_section_for_another_slug_does_not_count(self):
            self.stage_intake()
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            self.stage_green()
            self.stage_review(slug="some-other-bug")
            rep, _ = self.run_driver()
            self.assertIn("Luna", rep["next_action"])

        def test_phase5_with_a_verdict_gives_the_commit_gate(self):
            self.stage_intake()
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            self.stage_green()
            self.stage_review()
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (5, EXIT_BLOCKED))
            self.assertEqual(rep["required_gate"], "check_commit_gate.py")
            self.assertIn("--require-ledger-gates check_bugfix_intake.py,"
                          "check_red_green.py", rep["next_action"])
            self.assertIn("--commit", rep["next_action"])

        def test_commit_gate_pass_without_commit_is_not_complete(self):
            self.stage_intake()
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            self.stage_green()
            self.stage_review()
            self.ledger_line("check_commit_gate.py", argv=["--verify-tree"])
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (5, EXIT_NEXT))
            self.assertTrue(any("dry run" in w for w in rep["warnings"]))

        def test_commit_gate_fail_blocks(self):
            self.stage_intake()
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            self.stage_green()
            self.stage_review()
            self.ledger_line("check_commit_gate.py", verdict="FAIL",
                             argv=["--commit"], exit_code=1)
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (5, EXIT_BLOCKED))
            self.assertTrue(any("gate_not_passed check_commit_gate.py" in b
                                for b in rep["blocked_by"]))

        def test_complete_lane_exits_3_with_close_steps(self):
            self.stage_intake()
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            self.stage_green()
            self.stage_review()
            self.ledger_line("check_commit_gate.py",
                             argv=["--commit", "--message", "fix"])
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (6, EXIT_COMPLETE))
            self.assertIn("Lane complete", rep["next_action"])
            self.assertIn("manual-testing.md", rep["next_action"])
            self.assertIn("close the branch", rep["next_action"])

        def test_runtime_observable_commit_gate_requires_the_third_gate(self):
            self.stage_intake(runtime="yes")
            self.stage_red()
            self.stage_rca()
            self.stage_delegation()
            self.stage_green(runtime=True)
            self.stage_review()
            rep, _ = self.run_driver()
            self.assertEqual(rep["phase"], 5)
            self.assertIn("check_runtime_evidence.py", rep["next_action"])

    # ------------------------------------------------------- bugfix routing
    class BugfixRouteTests(Base):
        def test_standalone_route_uses_its_own_state_file(self):
            self.stage_intake()
            rep, _ = self.run_driver()
            self.assertEqual(rep["route"], "standalone")
            self.assertTrue(rep["state_file"].endswith(
                "bug-slug/orchestrator-state.json"))

        def test_feature_route_state_file_is_one_level_up(self):
            epic = self.dir / "proj"
            impl = epic / "implementation"
            impl.mkdir(parents=True)
            (epic / "orchestrator-state.json").write_text(
                json.dumps({"branch": "feat/x"}), encoding="utf-8")
            (impl / "bug-report.md").write_text(REPORT_TMPL.format(
                slug="s", command="pytest -q", surface="api", runtime="no"),
                encoding="utf-8")
            rep, code = self.run_driver(root=impl, milestone="auth-500")
            self.assertEqual(rep["route"], "feature")
            self.assertTrue(rep["state_file"].endswith(
                "proj/orchestrator-state.json"))
            self.assertEqual(rep["milestone"], "auth-500")
            # the intake gate has not run for this unit yet
            self.assertEqual(code, EXIT_BLOCKED)

        def test_feature_route_slug_scoped_root_state_file_is_three_levels_up(self):
            """2.6.1 layout: `.docs/{project}/implementation/bugs/{slug}/`.
            The basename is the slug, so no --milestone override is needed."""
            epic = self.dir / "proj"
            root = epic / "implementation" / "bugs" / "auth-500"
            root.mkdir(parents=True)
            (epic / "orchestrator-state.json").write_text(
                json.dumps({"branch": "feat/x"}), encoding="utf-8")
            (root / "bug-report.md").write_text(REPORT_TMPL.format(
                slug="auth-500", command="pytest -q", surface="api",
                runtime="no"), encoding="utf-8")
            rep, code = self.run_driver(root=root)
            self.assertEqual(rep["route"], "feature")
            self.assertTrue(rep["state_file"].endswith(
                "proj/orchestrator-state.json"))
            self.assertEqual(rep["milestone"], "auth-500")
            self.assertEqual(rep["milestone_source"], "root")
            self.assertEqual(code, EXIT_BLOCKED)

        def test_feature_route_slug_scoped_without_epic_state_exits_2(self):
            root = self.dir / "proj" / "implementation" / "bugs" / "auth-500"
            root.mkdir(parents=True)
            (root / "bug-report.md").write_text("# x\n", encoding="utf-8")
            with self.assertRaises(DriverError) as ctx:
                self.run_driver(root=root)
            self.assertIn("mis-resolved", str(ctx.exception))

        def test_feature_route_without_epic_state_exits_2(self):
            impl = self.dir / "proj" / "implementation"
            impl.mkdir(parents=True)
            (impl / "bug-report.md").write_text("# x\n", encoding="utf-8")
            with self.assertRaises(DriverError) as ctx:
                self.run_driver(root=impl)
            self.assertIn("mis-resolved", str(ctx.exception))

        def test_slug_is_derived_from_the_ledger_when_not_overridden(self):
            epic = self.dir / "proj"
            impl = epic / "implementation"
            impl.mkdir(parents=True)
            (epic / "orchestrator-state.json").write_text("{}",
                                                          encoding="utf-8")
            r = impl / "bug-report.md"
            r.write_text(REPORT_TMPL.format(slug="s", command="pytest -q",
                                            surface="api", runtime="no"),
                         encoding="utf-8")
            led = impl / "gates.jsonl"
            led.write_text(json.dumps({
                "gate": "check_bugfix_intake.py", "milestone": "auth-500",
                "argv": [], "inputs": {rp(r): sha256_file(r)},
                "verdict": "PASS", "exit": 0}) + "\n", encoding="utf-8")
            rep, _ = self.run_driver(root=impl)
            self.assertEqual(rep["milestone"], "auth-500")
            self.assertEqual(rep["milestone_source"], "ledger")
            self.assertEqual(rep["phase"], 1)

    # ----------------------------------------------------------------- quick
    class QuickTests(Base):
        def setUp(self):
            super(QuickTests, self).setUp()
            self.root = self.dir / "2026-09-07-rename-thing"
            self.root.mkdir(parents=True)
            self.ledger = self.root / "gates.jsonl"

        def note(self, what="rename A to B", where="src/a.py",
                 how="pytest -q tests/test_a.py"):
            lines = ["# Quick note", ""]
            if what:
                lines.append("- What: %s" % what)
            if where:
                lines.append("- Where: %s" % where)
            if how:
                lines.append("- How verified: `%s`" % how)
            return self.write("note.md", "\n".join(lines) + "\n")

        def test_phase0_no_note_asks_for_the_three_lines(self):
            rep, code = self.run_driver(lane="quick")
            self.assertEqual((rep["phase"], code), (0, EXIT_NEXT))
            self.assertIn("- How verified:", rep["next_action"])

        def test_phase0_incomplete_note_names_the_missing_line(self):
            self.note(how=None)
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (0, EXIT_NEXT))
            self.assertIn("how verified", rep["next_action"])

        # -- detect_stack.py defaults in the emitted actions ---------------

        def _in_repo(self, *files):
            """Re-root this lane under `<repo>/.docs/quick/<slug>/`."""
            repo = self.dir / "repo"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            for rel, text in files:
                p = repo / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
            self.root = repo / ".docs" / "quick" / "2026-09-07-rename-thing"
            self.root.mkdir(parents=True, exist_ok=True)
            self.ledger = self.root / "gates.jsonl"
            _DETECT_CACHE.clear()
            return repo

        def test_phase0_names_the_detected_stacks_check_command(self):
            self._in_repo(("package.json",
                           json.dumps({"dependencies": {"express": "^4.18.0"}})))
            rep, code = self.run_driver(lane="quick")
            self.assertEqual((rep["phase"], code), (0, EXIT_NEXT))
            self.assertIn("`npm test`", rep["next_action"])
            self.assertIn("never adopt it silently", rep["next_action"])

        def test_phase0_says_nothing_when_no_stack_matches(self):
            self._in_repo(("README.md", "# nothing detectable\n"))
            rep, _ = self.run_driver(lane="quick")
            self.assertNotIn("Detected stack suggests", rep["next_action"])
            self.assertEqual(rep["warnings"], [])

        def test_phase0_suggestion_is_absent_once_how_verified_is_written(self):
            self._in_repo(("package.json",
                           json.dumps({"dependencies": {"express": "^4"}})))
            self.note(where=None)
            rep, _ = self.run_driver(lane="quick")
            self.assertEqual(rep["phase"], 0)
            self.assertNotIn("Detected stack suggests", rep["next_action"])

        def test_close_command_carries_the_detected_frozen_globs(self):
            self._in_repo(("package.json",
                           json.dumps({"dependencies": {"express": "^4"}})))
            self.note()
            self.capture("evidence/check.md", 0)
            rep, code = self.run_driver(lane="quick")
            self.assertEqual((rep["phase"], code), (3, EXIT_BLOCKED))
            self.assertIn("--frozen 'tests/**'", rep["next_action"])
            self.assertIn("--frozen '**/*.spec.*'", rep["next_action"])
            self.assertNotIn("--frozen tests/ ", rep["next_action"])

        def test_close_command_falls_back_to_tests_when_undetectable(self):
            self.note()
            self.capture("evidence/check.md", 0)
            rep, _ = self.run_driver(lane="quick")
            self.assertIn("--frozen tests/", rep["next_action"])

        def test_repo_root_for_prefers_the_nearest_git_dir(self):
            repo = self._in_repo(("README.md", "x\n"))
            self.assertEqual(repo_root_for(self.root).resolve(),
                             repo.resolve())
            inner = repo / "sub"
            (inner / ".git").mkdir(parents=True)
            deep = inner / ".docs" / "quick" / "s"
            deep.mkdir(parents=True)
            self.assertEqual(repo_root_for(deep).resolve(), inner.resolve())
            self.assertIsNone(repo_root_for(self.dir / "no" / "such"))

        def test_repo_root_for_falls_back_to_the_docs_parent(self):
            """No .git anywhere above: the .docs parent is the repo."""
            base = self.dir / "nogit"
            deep = base / ".docs" / "quick" / "s"
            deep.mkdir(parents=True)
            if any((p / ".git").exists() for p in [deep] + list(deep.parents)):
                self.skipTest("temp dir sits inside a git repo")
            self.assertEqual(repo_root_for(deep).resolve(), base.resolve())

        def test_placeholder_note_value_counts_as_absent(self):
            self.note(how="TBD")
            rep, _ = self.run_driver()
            self.assertEqual(rep["phase"], 0)

        def test_phase1_asks_for_the_edit_and_the_capture(self):
            self.note()
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (1, EXIT_NEXT))
            self.assertIn("src/a.py", rep["next_action"])
            self.assertIn("run_quiet.py", rep["next_action"])
            self.assertIn("pytest -q tests/test_a.py", rep["next_action"])

        def test_failing_check_capture_blocks_at_phase1(self):
            self.note()
            self.capture("evidence/check.md", 1)
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (1, EXIT_BLOCKED))
            self.assertTrue(any("capture_exit_nonzero" in b
                                for b in rep["blocked_by"]))

        def test_phase3_gives_the_close_gate_with_exact_flags(self):
            self.note()
            self.capture("evidence/check.md", 0)
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (3, EXIT_BLOCKED))
            self.assertEqual(rep["required_gate"], "check_quick_close.py")
            self.assertIn("--max-changed-files 3", rep["next_action"])
            self.assertIn("--frozen tests/", rep["next_action"])
            self.assertIn("--changed-files src/a.py", rep["next_action"])
            self.assertIn('--milestone "rename-thing"', rep["next_action"])

        def test_close_gate_fail_blocks(self):
            self.note()
            self.capture("evidence/check.md", 0)
            self.ledger_line("check_quick_close.py", verdict="FAIL",
                             milestone="rename-thing", argv=["--commit"],
                             exit_code=1)
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (3, EXIT_BLOCKED))

        def test_close_gate_pass_without_commit_is_not_complete(self):
            self.note()
            self.capture("evidence/check.md", 0)
            self.ledger_line("check_quick_close.py", milestone="rename-thing",
                             argv=["--note", "x"])
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (3, EXIT_NEXT))

        def test_complete_quick_lane_exits_3(self):
            self.note()
            self.capture("evidence/check.md", 0)
            self.ledger_line("check_quick_close.py", milestone="rename-thing",
                             argv=["--commit", "--message", "m"])
            rep, code = self.run_driver()
            self.assertEqual((rep["phase"], code), (4, EXIT_COMPLETE))
            self.assertIn("## Result", rep["next_action"])

        def test_auto_detects_quick_from_note_md(self):
            self.note()
            rep, _ = self.run_driver()
            self.assertEqual(rep["lane"], "quick")

        def test_auto_prefers_quick_and_warns_when_both_exist(self):
            self.note()
            self.write("bug-report.md", "# x\n")
            rep, _ = self.run_driver()
            self.assertEqual(rep["lane"], "quick")
            self.assertTrue(any("both note.md and bug-report.md" in w
                                for w in rep["warnings"]))

    # -------------------------------------------------------------- generic
    class OutputTests(Base):
        def test_auto_detects_bugfix_from_bug_report(self):
            self.stage_intake()
            rep, _ = self.run_driver()
            self.assertEqual(rep["lane"], "bugfix")

        def test_report_carries_every_contract_key(self):
            self.stage_intake()
            rep, _ = self.run_driver()
            for key in ("lane", "phase", "phase_name", "next_action",
                        "required_gate", "gate_status", "blocked_by",
                        "artifacts_present", "artifacts_missing"):
                self.assertIn(key, rep)

        def test_human_render_names_the_next_action(self):
            self.stage_intake()
            rep, code = self.run_driver()
            text = render_human(rep, code)
            self.assertIn("phase:  1", text)
            self.assertIn("next:", text)
            self.assertIn("exit:   0", text)

        def test_exit_1_iff_blocked_by_is_non_empty(self):
            self.stage_intake()
            self.capture("evidence/red/bug-slug.md", 0)
            rep, code = self.run_driver()
            self.assertTrue(rep["blocked_by"])
            self.assertEqual(code, EXIT_BLOCKED)

        def test_explicit_ledger_path_is_honoured(self):
            self.stage_intake()
            other = self.dir / "elsewhere.jsonl"
            rep, _ = self.run_driver(ledger=other)
            self.assertEqual(rep["ledger"], rp(other))
            self.assertEqual(rep["phase"], 0)

    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(BugfixPhaseTests),
        loader.loadTestsFromTestCase(BugfixRouteTests),
        loader.loadTestsFromTestCase(QuickTests),
        loader.loadTestsFromTestCase(OutputTests),
    ])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
