#!/usr/bin/env python3
"""Close gate for the bgpdd-quick daily-driver lane.

The quick lane has no epic, no plan.md, no delegation and no review report --
two artifacts (`note.md`, one `run_quiet.py --capture`) and this one gate. It
therefore has to carry, alone, every restraint the heavier lanes spread across
five gates and a squad: that the change was declared BEFORE it was made, that
the declaration still matches the tree, that a check actually ran and passed
AFTER the edit, that no test was quietly edited into agreement, and that the
change is still small enough for a lane with no plan behind it.

Given the note, the capture and the declared file list, it verifies, in order:

  * `note_missing` / `note_incomplete` -- the note exists and carries three
    labelled, non-placeholder lines: What, Where, How verified
  * `note_where_mismatch` -- the Where line's path set EQUALS the declared
    `--changed-files` set. The note is the pre-change declaration; a Where
    line that drifted from what was actually touched is a note about a
    different change.
  * `capture_missing` / `not_a_capture` -- the How-verified command's run was
    captured to disk by `run_quiet.py --capture`, not narrated
  * `sidecar_missing` / `sidecar_hash_mismatch` -- the capture carries its
    provenance sidecar and still hashes to it (a hand-typed or after-the-fact
    edited capture is authored, not observed)
  * `capture_exit_nonzero` -- the captured command exited 0
  * `capture_stale` -- the capture `finished` no earlier than the newest
    changed file's mtime. A green taken BEFORE the edit proves the old code.
  * `changed_file_missing` -- every declared path exists on disk
  * `undeclared_tree_changes` -- the working tree holds nothing dirty beyond
    the declared files and `.docs/`
  * `frozen_path_modified` -- no `--frozen` path (typically `tests/`) appears
    in the working tree's diff as a MODIFIED tracked file. This is the
    mechanical form of the lane's "never edit an existing test to make it
    pass" rule; a newly ADDED test is not an edit and passes, which is what
    keeps the rule from forbidding the lane's own use case.
  * `size_bound_exceeded` -- the declared count is within
    `--max-changed-files`; the message names the lane to escalate to. There is
    deliberately NO `--waiver` here (convention #8, tighter than
    `check_commit_gate.py --waiver` in the bugfix lane): a quick change that
    outgrew the bound has an escalation lane, and a waiver would make the one
    bound that defines this lane self-certified by the person exceeding it.

On a clean pass, `--commit` commits EXACTLY the declared files (`git add --
<paths>`, never `-A`), so a skipped gate is loud -- no commit exists -- rather
than silent.

Deliberate divergences from sibling gates in this family, both labelled per
CLAUDE.md convention #8:

  * freshness compares at ONE-SECOND resolution with `>=`, where
    `check_red_green.py` orders two captures with a strict `>`. There, RED and
    GREEN are a fix round apart and equal stamps cannot order them. Here the
    two things compared are an edit and the check of that edit, which routinely
    land inside the same second; a strict `>` would reject honest same-second
    work while catching nothing a whole-second comparison misses.
  * `--max-changed-files` DEFAULTS to 3 rather than being opt-in as in
    `check_commit_gate.py`. In that lane the bound is an extra; here it is the
    lane's definition, and a bound that silently does not apply when the flag
    is forgotten is the exact failure this gate exists to prevent.

Helper logic (`sha256_file`, `append_ledger`, sidecar validation, the git
tree helpers, `perform_commit`) is COPIED from `check_commit_gate.py`,
`check_red_green.py` and `check_runtime_evidence.py` rather than imported --
this family's convention is stdlib-only, one self-contained file per script.

THIS GATE READS FILES AND RUNS git. It opens no socket.

Pure standard library. Every file is read as utf-8-sig, so a BOM cannot break
parsing. All output is ASCII.

Usage:
    python check_quick_close.py --note <path> --capture <path> \
        --changed-files <p1> [<p2> ...] [--repo <dir>] \
        [--max-changed-files N] [--frozen <path>]... \
        [--milestone "<slug>"] [--ledger <path>] \
        [--commit --message "<msg>"]
    python check_quick_close.py --self-test
"""
import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

READ_ENCODING = "utf-8-sig"
SIDECAR_SUFFIX = ".meta.json"
TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"
DEFAULT_MAX_CHANGED_FILES = 3

CAPTURED_HEADING_RE = re.compile(
    r"(?im)^##[^\S\n]+Captured[^\S\n]+output[^\S\n]*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
# A field VALUE stand-in. Same vocabulary as check_bugfix_intake.py's
# PLACEHOLDER_VALUE_RE (duplicated, not imported, per family convention).
PLACEHOLDER_VALUE_RE = re.compile(
    r"^(?:<[^>]*>|todo|tbd|fixme|n/?a|none|unknown|\?+|\.{3,}|xxx+)[.:]?$",
    re.IGNORECASE)

# The three note lines, matched as list items or bare lines, case-insensitively.
NOTE_LABELS = ("what", "where", "how verified")
NOTE_LINE_RE = re.compile(
    r"(?im)^[^\S\n]*(?:[-*+][^\S\n]+|\d+\.[^\S\n]+)?"
    r"(?:\*\*)?(what|where|how[^\S\n]+verified)(?:\*\*)?[^\S\n]*:[^\S\n]*(.*)$")


class GateError(Exception):
    """Structural/usage/environment failure -- maps to exit 2."""


# ---------------------------------------------------------------------------
# Shared gate ledger (see ../SKILL.md, "Gate ledger")
# ---------------------------------------------------------------------------

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


def append_ledger(ledger_path, argv, milestone, inputs, verdict, exit_code,
                  extra=None):
    """Append ONE JSON line recording this run. Best-effort by design."""
    if not ledger_path:
        return
    record = {
        "ts": datetime.now(timezone.utc).strftime(TIMESTAMP_FMT),
        "gate": Path(__file__).name,
        "argv": list(argv),
        "milestone": milestone,
        "inputs": {str(p): sha256_file(p) for p in inputs if p},
        "verdict": verdict,
        "exit": exit_code,
    }
    if extra:
        record.update(extra)
    try:
        p = Path(ledger_path)
        if str(p.parent):
            p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print("Warning: could not append to ledger "
              "{0}: {1}".format(ledger_path, exc), file=sys.stderr)


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def read_text(path):
    try:
        return Path(path).read_text(encoding=READ_ENCODING, errors="replace")
    except OSError as exc:
        raise GateError("cannot read {0}: {1}".format(path, exc))


def strip_fenced_blocks(text):
    """Blank fenced regions, preserving line count (family convention).

    A `- Where: ...` line inside a fence is a TEMPLATE or a pasted transcript,
    never this note's declaration.
    """
    out = []
    fence = None
    for line in text.splitlines():
        m = FENCE_RE.match(line)
        if fence is None and m:
            fence = m.group(1)
            out.append("")
            continue
        if fence is not None:
            out.append("")
            if line.strip().startswith(fence):
                fence = None
            continue
        out.append(line)
    return "\n".join(out)


def is_real_value(value):
    v = (value or "").strip().strip("`").strip()
    return bool(v) and not PLACEHOLDER_VALUE_RE.match(v)


def split_paths(value):
    """Path tokens from a Where line: comma- and/or whitespace-separated."""
    cleaned = (value or "").replace("`", " ")
    cleaned = re.sub(r"[,;]", " ", cleaned)
    return [t for t in cleaned.split() if t and t not in ("and", "+")]


# ---------------------------------------------------------------------------
# Provenance: the run_quiet.py sidecar (same logic as check_red_green.py)
# ---------------------------------------------------------------------------

def sidecar_path_for(capture_path):
    return Path(str(capture_path) + SIDECAR_SUFFIX)


def load_sidecar(path):
    """(meta dict or None, reason-when-None). Malformed reads as absent."""
    p = Path(path)
    if not p.is_file():
        return None, "no sidecar file"
    try:
        meta = json.loads(p.read_text(encoding=READ_ENCODING, errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, "sidecar is unreadable or not valid JSON: {0}".format(exc)
    if not isinstance(meta, dict):
        return None, "sidecar is not a JSON object"
    return meta, None


def parse_finished(meta):
    """(epoch seconds or None, reason-when-None) from the sidecar `finished`."""
    raw = meta.get("finished")
    if not isinstance(raw, str) or not raw.strip():
        return None, "the sidecar records no 'finished' timestamp"
    try:
        dt = datetime.strptime(raw.strip(), TIMESTAMP_FMT)
    except ValueError:
        return None, ("the sidecar's 'finished' value {0!r} is not an ISO-8601 "
                      "UTC instant ({1})".format(raw.strip(), TIMESTAMP_FMT))
    return dt.replace(tzinfo=timezone.utc).timestamp(), None


# ---------------------------------------------------------------------------
# git helpers (copied from check_commit_gate.py)
# ---------------------------------------------------------------------------

def run_git(args, repo):
    try:
        proc = subprocess.run(["git"] + args, cwd=repo, capture_output=True,
                              text=True, timeout=240)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GateError("git could not be run in {0}: {1}".format(repo, exc))
    if proc.returncode != 0:
        raise GateError("git {0} failed: {1}".format(
            args[0], (proc.stderr or proc.stdout).strip()))
    return proc.stdout


def perform_commit(changed_files, message, repo):
    """Commit EXACTLY the declared files. Never `git add -A`."""
    run_git(["add", "--"] + list(changed_files), repo)
    run_git(["commit", "-m", message], repo)


def parse_porcelain_line(line):
    """The path a `git status --porcelain` line refers to."""
    path = line[3:]
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    return path


def normalize_repo_path(path, repo):
    """Repo-relative, forward-slash, case-folded-on-Windows comparison form."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(repo) / p
    try:
        p = p.resolve()
    except OSError:
        p = Path(os.path.abspath(str(p)))
    try:
        rel = p.relative_to(Path(repo).resolve())
    except ValueError:
        rel = p
    normalized = os.path.normcase(str(rel).replace("\\", "/"))
    return normalized.replace("\\", "/")


def is_tracked_change(status):
    """True when a porcelain status means an EXISTING tracked file changed.

    `??` (untracked) and `A` (newly added to the index, including `AM`) are
    NEW files, not edits of existing ones. The distinction is what lets the
    frozen check forbid editing an existing test while still allowing this
    lane's stated use case of ADDING one.
    """
    x, y = (status + "  ")[0], (status + "  ")[1]
    if x in "?!A":
        return False
    return x in "MDRCU" or y in "MDRCU"


def dirty_paths(repo):
    """(status, normalized repo-relative path) for everything dirty.

    A porcelain path ending in `/` is a collapsed untracked DIRECTORY entry,
    not a file; it keeps its trailing slash so callers can tell.
    """
    output = run_git(["status", "--porcelain"], repo)
    entries = []
    for line in output.splitlines():
        if not line:
            continue
        status = line[:2]
        raw = parse_porcelain_line(line)
        if raw.endswith("/"):
            entries.append((status, normalize_repo_path(raw, repo) + "/"))
        else:
            entries.append((status, normalize_repo_path(raw, repo)))
    return entries


def check_undeclared_tree(entries, declared):
    """Dirty paths neither declared nor under `.docs/`.

    `.docs/` is allowed regardless of declaration: the lane's own note,
    capture and ledger live there and are not the change under review.
    """
    undeclared = []
    for _status, norm in entries:
        if norm.endswith("/"):
            if norm.startswith(".docs/"):
                continue
            if any(d == norm or d.startswith(norm) for d in declared):
                continue
            undeclared.append(norm)
            continue
        if norm in declared or norm.startswith(".docs/"):
            continue
        undeclared.append(norm)
    return undeclared


def check_frozen(entries, frozen, repo):
    """Frozen paths (or paths under a frozen directory) that were EDITED.

    Only tracked modifications count (`is_tracked_change`): the rule this
    enforces is "never edit an existing test to make it pass", and a brand new
    test file is the opposite of that. Staged and unstaged edits both count --
    staging a frozen edit is not a way around the rule.
    """
    hits = []
    for raw in frozen:
        norm = normalize_repo_path(raw, repo).rstrip("/")
        prefix = norm + "/"
        for status, candidate in entries:
            if not is_tracked_change(status):
                continue
            cand = candidate.rstrip("/")
            if cand == norm or cand.startswith(prefix):
                if candidate not in hits:
                    hits.append(candidate)
    return hits


# ---------------------------------------------------------------------------
# The note
# ---------------------------------------------------------------------------

def parse_note(path):
    """(fields dict, problems list). Missing/placeholder values read as absent."""
    fields = {label: None for label in NOTE_LABELS}
    p = Path(path)
    if not p.is_file():
        return fields, [("note_missing",
                         "no such note file: {0} -- the quick lane's Phase 0 "
                         "artifact is what declares the change before it is "
                         "made".format(path))]
    text = strip_fenced_blocks(read_text(p))
    for match in NOTE_LINE_RE.finditer(text):
        label = re.sub(r"\s+", " ", match.group(1).strip().lower())
        value = match.group(2).strip()
        if label in fields and fields[label] is None and is_real_value(value):
            fields[label] = value.strip()
    missing = [label for label in NOTE_LABELS if fields[label] is None]
    problems = []
    if missing:
        problems.append((
            "note_incomplete",
            "the note is missing a usable line for: {0} -- each of "
            "'What', 'Where', 'How verified' must carry a real, "
            "non-placeholder value".format(
                ", ".join(m.title() if m != "how verified" else "How verified"
                          for m in missing))))
    return fields, problems


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(args):
    repo = args.repo or "."
    report = {
        "note": args.note,
        "capture": args.capture,
        "repo": repo,
        "milestone": args.milestone,
        "note_fields": None,
        "note_where_paths": [],
        "changed_files": list(args.changed_files),
        "changed_file_count": len(args.changed_files),
        "max_changed_files": args.max_changed_files,
        "size_ok": None,
        "capture_sidecar": None,
        "capture_exit_code": None,
        "capture_finished": None,
        "newest_changed_file": None,
        "fresh": None,
        "undeclared_changes": [],
        "frozen": list(args.frozen),
        "frozen_modified": [],
        "problems": [],
        "problem_codes": [],
        "warnings": [],
        "committed": False,
        "result": "FAIL",
        "error": None,
    }

    def fail(code, message):
        report["problems"].append("{0}: {1}".format(code, message))
        report["problem_codes"].append(code)

    declared = [normalize_repo_path(f, repo) for f in args.changed_files]

    # --- 1/2. the note -----------------------------------------------------
    fields, note_problems = parse_note(args.note)
    report["note_fields"] = dict(fields)
    for code, message in note_problems:
        fail(code, message)

    # --- 3. the Where line matches the declared set ------------------------
    if fields["where"]:
        where_paths = split_paths(fields["where"])
        report["note_where_paths"] = where_paths
        where_norm = sorted({normalize_repo_path(w, repo) for w in where_paths})
        if where_norm != sorted(set(declared)):
            fail("note_where_mismatch",
                 "the note's Where line names {0!r} but --changed-files "
                 "declares {1!r} -- the note is the declaration this gate "
                 "checks the change against, so a drifted Where line is a "
                 "note about a different change".format(
                     where_norm, sorted(set(declared))))

    # --- 4/5/6/7. the capture ---------------------------------------------
    cap = Path(args.capture)
    meta = None
    if not cap.is_file():
        fail("capture_missing",
             "no such capture file: {0} -- the How-verified command's run must "
             "be recorded by `run_quiet.py --capture`, not narrated".format(
                 args.capture))
    else:
        text = read_text(cap)
        if not CAPTURED_HEADING_RE.search(text):
            fail("not_a_capture",
                 "no '## Captured output' section in {0} -- structurally not a "
                 "run_quiet.py capture artifact".format(args.capture))
        side = sidecar_path_for(cap)
        report["capture_sidecar"] = str(side)
        meta, side_error = load_sidecar(side)
        if meta is None:
            fail("sidecar_missing",
                 "{0} at {1} -- a capture with no run_quiet.py provenance "
                 "sidecar is indistinguishable from a hand-typed one; re-take "
                 "it with `run_quiet.py --capture`".format(
                     side_error, side.name))
        else:
            declared_hash = meta.get("capture_sha256")
            actual_hash = sha256_file(cap)
            if not (declared_hash and actual_hash
                    and declared_hash == actual_hash):
                fail("sidecar_hash_mismatch",
                     "the capture file's sha256 ({0}) does not match the "
                     "sidecar's capture_sha256 ({1}) -- the artifact was edited "
                     "after it was recorded, so its contents are authored, not "
                     "observed".format(actual_hash, declared_hash))
            exit_code = meta.get("exit_code")
            if not isinstance(exit_code, int):
                fail("capture_exit_nonzero",
                     "the sidecar records no integer exit_code -- the check's "
                     "outcome was never observed")
            else:
                report["capture_exit_code"] = exit_code
                if exit_code != 0:
                    fail("capture_exit_nonzero",
                         "the How-verified command exited {0} -- the change is "
                         "not proven".format(exit_code))
            if isinstance(meta.get("finished"), str):
                report["capture_finished"] = meta["finished"].strip()

    # --- 8. every declared file exists ------------------------------------
    missing_files = [f for f in args.changed_files if not Path(f).exists()]
    if missing_files:
        fail("changed_file_missing",
             "--changed-files names path(s) that do not exist on disk, which "
             "would silently disable the freshness and tree checks: {0}".format(
                 ", ".join(str(m) for m in missing_files)))

    # --- 7 (cont). freshness: the capture is newer than the edit -----------
    newest = None
    for f in args.changed_files:
        try:
            mt = Path(f).stat().st_mtime
        except OSError:
            continue
        if newest is None or mt > newest:
            newest = mt
    if newest is not None:
        report["newest_changed_file"] = datetime.fromtimestamp(
            newest, timezone.utc).strftime(TIMESTAMP_FMT)
    if meta is not None and newest is not None:
        finished_ts, reason = parse_finished(meta)
        if finished_ts is None:
            fail("capture_stale", reason)
        else:
            # One-second resolution on BOTH sides (the sidecar stamp is whole
            # seconds), then `>=`. See the module docstring for why this is a
            # labelled divergence from check_red_green.py's strict `>`.
            report["fresh"] = finished_ts >= math.floor(newest)
            if not report["fresh"]:
                fail("capture_stale",
                     "the capture finished {0} but a declared file was "
                     "modified at {1} -- a check that ran BEFORE the edit "
                     "proves the old code".format(
                         report["capture_finished"],
                         report["newest_changed_file"]))

    # --- 9/10. the working tree -------------------------------------------
    dirty = dirty_paths(repo)
    report["undeclared_changes"] = check_undeclared_tree(dirty, declared)
    if report["undeclared_changes"]:
        fail("undeclared_tree_changes",
             "the working tree holds change(s) this note never declared: {0} "
             "-- either declare them (and re-check the size bound) or revert "
             "them; an undeclared edit ships unreviewed and unproven".format(
                 ", ".join(report["undeclared_changes"])))

    report["frozen_modified"] = check_frozen(dirty, args.frozen, repo)
    if report["frozen_modified"]:
        fail("frozen_path_modified",
             "frozen path(s) were edited: {0} -- this lane never edits an "
             "existing test to make it pass (adding a NEW test is fine). Fix "
             "the code, or state why the test itself was wrong and take the "
             "change to /bgpdd-bugfix where a RED capture proves it.".format(
                 ", ".join(report["frozen_modified"])))

    # --- 11. the size bound ------------------------------------------------
    report["size_ok"] = len(args.changed_files) <= args.max_changed_files
    if not report["size_ok"]:
        fail("size_bound_exceeded",
             "{0} declared files exceeds this lane's bound of {1}. There is no "
             "waiver here: escalate instead -- a defect with a reproduction to "
             "/bgpdd-bugfix, otherwise /bgpdd-lite.".format(
                 len(args.changed_files), args.max_changed_files))

    report["result"] = "PASS" if not report["problems"] else "FAIL"

    if report["result"] == "PASS" and args.commit:
        perform_commit(args.changed_files, args.message, repo)
        report["committed"] = True
    return report


def build_parser():
    parser = argparse.ArgumentParser(prog="check_quick_close.py")
    parser.add_argument("--note", help="the quick lane's note.md")
    parser.add_argument("--capture",
                        help="the run_quiet.py --capture of the How-verified "
                             "command")
    parser.add_argument("--changed-files", nargs="*", default=[],
                        help="every file this change touched")
    parser.add_argument("--repo", default=".", help="repo root (default .)")
    parser.add_argument("--max-changed-files", type=int,
                        default=DEFAULT_MAX_CHANGED_FILES,
                        help="lane size bound (default {0}; no waiver "
                             "exists)".format(DEFAULT_MAX_CHANGED_FILES))
    parser.add_argument("--frozen", action="append", default=[],
                        help="a path or directory that must NOT appear in the "
                             "diff (typically tests/); repeatable")
    parser.add_argument("--milestone", help="the slug, scoping ledger records")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--commit", action="store_true",
                        help="on a pass, commit exactly the declared files")
    parser.add_argument("--message", help="commit message (requires --commit)")
    parser.add_argument("--self-test", action="store_true")
    return parser


def ledger_inputs(args):
    """Every file this gate READ: note, capture, sidecar, declared files."""
    paths = []
    if args.note:
        paths.append(args.note)
    if args.capture:
        paths.append(args.capture)
        paths.append(str(sidecar_path_for(args.capture)))
    paths += [str(f) for f in args.changed_files]
    return paths


def main(argv):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone, ledger_inputs(args),
                      verdict, code)
        return code

    missing = [n for n, v in (("--note", args.note),
                              ("--capture", args.capture)) if not v]
    if missing:
        print(json.dumps({"result": "ERROR",
                          "error": "missing required argument(s): {0}".format(
                              ", ".join(missing))}))
        return finish(2, "ERROR")
    if not args.changed_files:
        print(json.dumps({"result": "ERROR",
                          "error": "--changed-files requires at least one "
                                   "path"}))
        return finish(2, "ERROR")
    if args.max_changed_files < 1:
        print(json.dumps({"result": "ERROR",
                          "error": "--max-changed-files must be >= 1 (a bound "
                                   "of 0 can never be satisfied)"}))
        return finish(2, "ERROR")
    if args.commit and not args.message:
        print(json.dumps({"result": "ERROR",
                          "error": "--commit requires --message"}))
        return finish(2, "ERROR")
    if args.message and not args.commit:
        print(json.dumps({"result": "ERROR",
                          "error": "--message given without --commit -- there "
                                   "is nothing for it to label"}))
        return finish(2, "ERROR")

    try:
        report = build_report(args)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")
    print(json.dumps(report, indent=2))
    passed = report["result"] == "PASS"
    return finish(0 if passed else 1, "PASS" if passed else "FAIL")


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import contextlib
    import io
    import shutil
    import tempfile
    import time
    import unittest

    def capture_text(cmd, exit_code, body):
        return (
            "# Runtime capture\n\n"
            "- Title: quick check\n"
            "- Probe command: `{0}` [probe-exempt: test runner]\n"
            "- Captured: 2026-09-04T10:00:00Z\n"
            "- Exit code: {1}\n\n"
            "## Captured output\n\n```\n{2}\n```\n".format(
                " ".join(cmd), exit_code, body))

    class QuickCloseTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.repo = self.dir / "repo"
            self.repo.mkdir()
            self._git("init", "-q")
            self._git("config", "user.email", "gate@example.test")
            self._git("config", "user.name", "Gate Self Test")
            self._git("config", "commit.gpgsign", "false")
            (self.repo / "src").mkdir()
            (self.repo / "tests").mkdir()
            (self.repo / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
            (self.repo / "tests" / "test_a.py").write_text(
                "def test_a():\n    assert True\n", encoding="utf-8")
            self._git("add", "-A")
            self._git("commit", "-q", "-m", "base")
            self.cmd = ["python", "-c", "import sys; sys.exit(0)"]

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _git(self, *args):
            proc = subprocess.run(["git"] + list(args), cwd=str(self.repo),
                                  capture_output=True, text=True, timeout=240)
            if proc.returncode != 0:
                raise AssertionError("git {0}: {1}".format(
                    args, proc.stderr or proc.stdout))
            return proc.stdout

        # -- fixture builders ------------------------------------------

        def _edit(self, rel="src/a.py", text="A = 2\n"):
            p = self.repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            return rel

        def _note(self, what="rename A to B", where="src/a.py",
                  how="python -c \"import sys; sys.exit(0)\"", lines=None):
            path = self.repo / ".docs" / "quick" / "note.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            if lines is None:
                lines = ["# Quick note", "",
                         "- What: {0}".format(what),
                         "- Where: {0}".format(where),
                         "- How verified: `{0}`".format(how), ""]
            path.write_text("\n".join(lines), encoding="utf-8")
            return str(path)

        def _capture(self, exit_code=0, finished=None, cmd=None,
                     sidecar=True, hash_ok=True, name="check.md",
                     body_ok=True, extra_meta=None):
            cmd = cmd or self.cmd
            cap = self.repo / ".docs" / "quick" / "evidence" / name
            cap.parent.mkdir(parents=True, exist_ok=True)
            if body_ok:
                cap.write_text(capture_text(cmd, exit_code,
                                            "OK" if not exit_code else "FAILED"),
                               encoding="utf-8")
            else:
                cap.write_text("the check passed, trust me\n",
                               encoding="utf-8")
            if finished is None:
                finished = datetime.now(timezone.utc).strftime(TIMESTAMP_FMT)
            if sidecar:
                meta = {
                    "argv": list(cmd), "cwd": str(self.repo),
                    "host": "test-host", "pid": 4242,
                    "started": finished, "finished": finished,
                    "exit_code": exit_code, "body_sha256": "0" * 64,
                    "capture_sha256": (sha256_file(cap) if hash_ok
                                       else "f" * 64),
                    "tool": "run_quiet.py", "schema": 1,
                }
                if extra_meta:
                    meta.update(extra_meta)
                sidecar_path_for(cap).write_text(
                    json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            return str(cap)

        def _args(self, note, capture, changed, extra=None):
            argv = ["--note", note, "--capture", capture,
                    "--repo", str(self.repo), "--changed-files"] + list(changed)
            return build_parser().parse_args(argv + (extra or []))

        def _run(self, note, capture, changed, extra=None):
            return build_report(self._args(note, capture, changed, extra))

        def _main(self, argv):
            buf, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf), \
                    contextlib.redirect_stderr(err):
                code = main(argv)
            return code, buf.getvalue() + err.getvalue()

        def _happy(self):
            rel = self._edit()
            time.sleep(0.01)
            note = self._note()
            capture = self._capture()
            return note, capture, [str(self.repo / rel)]

        # -- happy path -------------------------------------------------

        def test_a_clean_quick_change_passes(self):
            note, capture, changed = self._happy()
            r = self._run(note, capture, changed)
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["changed_file_count"], 1)
            self.assertTrue(r["size_ok"])
            self.assertTrue(r["fresh"])

        def test_docs_artifacts_are_never_undeclared(self):
            """The note, capture and ledger live under .docs/ by design."""
            note, capture, changed = self._happy()
            r = self._run(note, capture, changed)
            self.assertEqual(r["undeclared_changes"], [], r["problems"])

        # -- the note ---------------------------------------------------

        def test_missing_note_fails(self):
            _, capture, changed = self._happy()
            r = self._run(str(self.repo / ".docs" / "quick" / "gone.md"),
                          capture, changed)
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("note_missing", r["problem_codes"])

        def test_note_missing_the_how_verified_line_fails(self):
            rel = self._edit()
            note = self._note(lines=["- What: rename A to B",
                                     "- Where: src/a.py"])
            capture = self._capture()
            r = self._run(note, capture, [str(self.repo / rel)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("note_incomplete", r["problem_codes"])
            self.assertIn("How verified", r["problems"][0])

        def test_note_with_placeholder_text_fails(self):
            rel = self._edit()
            note = self._note(what="<one sentence of intent>")
            capture = self._capture()
            r = self._run(note, capture, [str(self.repo / rel)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("note_incomplete", r["problem_codes"])

        def test_note_lines_inside_a_fence_do_not_count(self):
            """A pasted template in a fence is an example, not a declaration."""
            rel = self._edit()
            note = self._note(lines=[
                "# Quick note", "", "```", "- What: <intent>",
                "- Where: <files>", "- How verified: <command>", "```", ""])
            capture = self._capture()
            r = self._run(note, capture, [str(self.repo / rel)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("note_incomplete", r["problem_codes"])

        def test_where_list_not_matching_declared_files_fails(self):
            rel = self._edit()
            note = self._note(where="src/other.py")
            capture = self._capture()
            r = self._run(note, capture, [str(self.repo / rel)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("note_where_mismatch", r["problem_codes"])

        def test_where_list_short_of_the_declared_files_fails(self):
            rel = self._edit()
            rel2 = self._edit("src/b.py", "B = 1\n")
            note = self._note(where="src/a.py")
            capture = self._capture()
            r = self._run(note, capture,
                          [str(self.repo / rel), str(self.repo / rel2)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("note_where_mismatch", r["problem_codes"])

        def test_where_list_accepts_comma_and_backtick_forms(self):
            rel = self._edit()
            rel2 = self._edit("src/b.py", "B = 1\n")
            time.sleep(0.01)
            note = self._note(where="`src/a.py`, `src/b.py`")
            capture = self._capture()
            r = self._run(note, capture,
                          [str(self.repo / rel), str(self.repo / rel2)])
            self.assertEqual(r["result"], "PASS", r["problems"])

        # -- the capture ------------------------------------------------

        def test_missing_capture_fails(self):
            note, _, changed = self._happy()
            r = self._run(note,
                          str(self.repo / ".docs" / "quick" / "gone.md"),
                          changed)
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("capture_missing", r["problem_codes"])

        def test_hand_typed_capture_without_sidecar_fails(self):
            rel = self._edit()
            note = self._note()
            capture = self._capture(sidecar=False)
            r = self._run(note, capture, [str(self.repo / rel)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("sidecar_missing", r["problem_codes"])

        def test_a_file_that_is_not_a_capture_fails(self):
            rel = self._edit()
            note = self._note()
            capture = self._capture(body_ok=False)
            r = self._run(note, capture, [str(self.repo / rel)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("not_a_capture", r["problem_codes"])

        def test_capture_edited_after_recording_fails(self):
            rel = self._edit()
            note = self._note()
            capture = self._capture()
            Path(capture).write_text(
                Path(capture).read_text(encoding="utf-8").replace(
                    "- Exit code: 0", "- Exit code: 0 "), encoding="utf-8")
            r = self._run(note, capture, [str(self.repo / rel)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("sidecar_hash_mismatch", r["problem_codes"])

        def test_capture_whose_command_failed_fails(self):
            rel = self._edit()
            note = self._note()
            capture = self._capture(exit_code=1)
            r = self._run(note, capture, [str(self.repo / rel)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("capture_exit_nonzero", r["problem_codes"])

        def test_sidecar_without_an_integer_exit_code_fails(self):
            rel = self._edit()
            note = self._note()
            capture = self._capture(extra_meta={"exit_code": "0"})
            r = self._run(note, capture, [str(self.repo / rel)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("capture_exit_nonzero", r["problem_codes"])

        def test_capture_older_than_the_edit_is_stale(self):
            """A check that ran BEFORE the edit proves the old code."""
            rel = self._edit()
            note = self._note()
            capture = self._capture(finished="2001-01-01T00:00:00Z")
            r = self._run(note, capture, [str(self.repo / rel)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("capture_stale", r["problem_codes"])

        def test_capture_in_the_same_second_as_the_edit_is_fresh(self):
            """Deliberate divergence from check_red_green.py's strict `>`."""
            rel = self._edit()
            stamp = datetime.fromtimestamp(
                (self.repo / rel).stat().st_mtime,
                timezone.utc).strftime(TIMESTAMP_FMT)
            note = self._note()
            capture = self._capture(finished=stamp)
            r = self._run(note, capture, [str(self.repo / rel)])
            self.assertEqual(r["result"], "PASS", r["problems"])

        def test_unparseable_finished_timestamp_is_stale(self):
            rel = self._edit()
            note = self._note()
            capture = self._capture(finished="yesterday afternoon")
            r = self._run(note, capture, [str(self.repo / rel)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("capture_stale", r["problem_codes"])

        def test_bom_prefixed_note_still_parses(self):
            note, capture, changed = self._happy()
            p = Path(note)
            p.write_bytes(b"\xef\xbb\xbf" + p.read_bytes())
            r = self._run(note, capture, changed)
            self.assertEqual(r["result"], "PASS", r["problems"])

        # -- the tree ---------------------------------------------------

        def test_missing_declared_file_fails(self):
            note, capture, _ = self._happy()
            r = self._run(note, capture, [str(self.repo / "src" / "gone.py")])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("changed_file_missing", r["problem_codes"])

        def test_a_fourth_file_slipped_into_the_tree_fails(self):
            note, capture, changed = self._happy()
            (self.repo / "src" / "sneaky.py").write_text("X = 1\n",
                                                         encoding="utf-8")
            r = self._run(note, capture, changed)
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("undeclared_tree_changes", r["problem_codes"])
            self.assertIn("src/sneaky.py", " ".join(r["undeclared_changes"]))

        def test_an_edited_test_file_fails_the_frozen_check(self):
            rel = self._edit()
            (self.repo / "tests" / "test_a.py").write_text(
                "def test_a():\n    assert False or True\n", encoding="utf-8")
            time.sleep(0.01)
            note = self._note()
            capture = self._capture()
            r = self._run(note, capture, [str(self.repo / rel)],
                          ["--frozen", "tests"])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("frozen_path_modified", r["problem_codes"])
            self.assertIn("/bgpdd-bugfix", " ".join(r["problems"]))

        def test_a_declared_test_edit_also_fails_the_frozen_check(self):
            """Declaring the test edit is not a way around the rule."""
            rel = "tests/test_a.py"
            self._edit(rel, "def test_a():\n    assert 1\n")
            time.sleep(0.01)
            note = self._note(where=rel)
            capture = self._capture()
            r = self._run(note, capture, [str(self.repo / rel)],
                          ["--frozen", "tests/"])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("frozen_path_modified", r["problem_codes"])

        def test_staging_a_frozen_edit_is_not_a_way_around_it(self):
            self._edit("tests/test_a.py", "def test_a():\n    assert 1\n")
            self._git("add", "tests/test_a.py")
            rel = self._edit()
            time.sleep(0.01)
            note = self._note(where="src/a.py, tests/test_a.py")
            capture = self._capture()
            r = self._run(note, capture,
                          [str(self.repo / rel),
                           str(self.repo / "tests" / "test_a.py")],
                          ["--frozen", "tests"])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("frozen_path_modified", r["problem_codes"])

        def test_a_newly_added_test_passes_the_frozen_check(self):
            """Adding a test is this lane's use case; editing one is not."""
            rel = "tests/test_new.py"
            self._edit(rel, "def test_new():\n    assert True\n")
            time.sleep(0.01)
            note = self._note(what="add a regression test for coupon math",
                              where=rel)
            capture = self._capture()
            r = self._run(note, capture, [str(self.repo / rel)],
                          ["--frozen", "tests"])
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["frozen_modified"], [])

        def test_frozen_check_is_silent_when_no_test_was_touched(self):
            note, capture, changed = self._happy()
            r = self._run(note, capture, changed, ["--frozen", "tests"])
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["frozen_modified"], [])

        # -- the size bound ---------------------------------------------

        def test_size_bound_exceeded_names_the_escalation_lanes(self):
            rels = [self._edit("src/f{0}.py".format(i),
                               "F = {0}\n".format(i)) for i in range(4)]
            time.sleep(0.01)
            note = self._note(where=", ".join(rels))
            capture = self._capture()
            r = self._run(note, capture, [str(self.repo / x) for x in rels])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("size_bound_exceeded", r["problem_codes"])
            joined = " ".join(r["problems"])
            self.assertIn("/bgpdd-bugfix", joined)
            self.assertIn("/bgpdd-lite", joined)

        def test_the_size_bound_applies_without_the_flag(self):
            """Deliberate divergence: the bound is this lane's definition."""
            args = build_parser().parse_args(
                ["--note", "n", "--capture", "c", "--changed-files", "x"])
            self.assertEqual(args.max_changed_files,
                             DEFAULT_MAX_CHANGED_FILES)

        # -- the commit -------------------------------------------------

        def test_commit_commits_exactly_the_declared_files(self):
            note, capture, changed = self._happy()
            (self.repo / "src" / "unrelated.py").write_text(
                "U = 1\n", encoding="utf-8")
            args = self._args(note, capture, changed,
                              ["--commit", "--message", "quick: rename A"])
            # The stray file makes the gate FAIL, so nothing is committed.
            r = build_report(args)
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["committed"])
            (self.repo / "src" / "unrelated.py").unlink()
            r = build_report(self._args(
                note, capture, changed,
                ["--commit", "--message", "quick: rename A"]))
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertTrue(r["committed"])
            committed = self._git("show", "--name-only", "--pretty=format:",
                                  "HEAD").split()
            self.assertEqual(committed, ["src/a.py"])

        # -- usage + ledger ---------------------------------------------

        def test_usage_errors_are_exit_2(self):
            note, capture, changed = self._happy()
            self.assertEqual(self._main(["--capture", capture])[0], 2)
            self.assertEqual(self._main(["--note", note])[0], 2)
            self.assertEqual(self._main(
                ["--note", note, "--capture", capture])[0], 2)
            self.assertEqual(self._main(
                ["--note", note, "--capture", capture,
                 "--changed-files"] + changed +
                ["--max-changed-files", "0"])[0], 2)
            self.assertEqual(self._main(
                ["--note", note, "--capture", capture,
                 "--changed-files"] + changed + ["--commit"])[0], 2)
            self.assertEqual(self._main(
                ["--note", note, "--capture", capture,
                 "--changed-files"] + changed + ["--message", "x"])[0], 2)

        def _records(self, ledger):
            return [json.loads(l) for l in
                    Path(ledger).read_text(encoding="utf-8").splitlines()
                    if l.strip()]

        def test_ledger_records_the_pass_with_input_hashes(self):
            note, capture, changed = self._happy()
            ledger = self.repo / ".docs" / "quick" / "gates.jsonl"
            argv = ["--note", note, "--capture", capture,
                    "--repo", str(self.repo), "--milestone", "rename-a",
                    "--ledger", str(ledger), "--changed-files"] + changed
            code, _ = self._main(argv)
            self.assertEqual(code, 0)
            rec = self._records(ledger)[-1]
            self.assertEqual(rec["gate"], "check_quick_close.py")
            self.assertEqual(rec["verdict"], "PASS")
            self.assertEqual(rec["exit"], 0)
            self.assertEqual(rec["milestone"], "rename-a")
            self.assertEqual(rec["argv"], argv)
            self.assertEqual(rec["inputs"][note], sha256_file(note))
            self.assertEqual(rec["inputs"][str(sidecar_path_for(capture))],
                             sha256_file(sidecar_path_for(capture)))
            self.assertTrue(rec["ts"].endswith("Z"))

        def test_ledger_records_a_fail_and_a_usage_error(self):
            rel = self._edit()
            note = self._note()
            capture = self._capture(exit_code=1)
            ledger = self.repo / ".docs" / "gates.jsonl"
            self.assertEqual(self._main(
                ["--note", note, "--capture", capture, "--repo",
                 str(self.repo), "--ledger", str(ledger), "--changed-files",
                 str(self.repo / rel)])[0], 1)
            self.assertEqual(self._records(ledger)[-1]["verdict"], "FAIL")
            self.assertEqual(self._main(["--ledger", str(ledger)])[0], 2)
            self.assertEqual(self._records(ledger)[-1]["verdict"], "ERROR")

        # -- end-to-end against the real run_quiet.py -------------------

        def test_real_run_quiet_capture_passes(self):
            """The composition, not the fixture: run_quiet writes both."""
            run_quiet = Path(__file__).resolve().parent / "run_quiet.py"
            if not run_quiet.is_file():
                self.skipTest("run_quiet.py not found beside this script")
            rel = self._edit()
            cap = self.repo / ".docs" / "quick" / "evidence" / "rq.md"
            subprocess.run([sys.executable, str(run_quiet), "--capture",
                            str(cap), "--", sys.executable, "-c",
                            "import sys; sys.exit(0)"],
                           capture_output=True, timeout=120)
            self.assertTrue(sidecar_path_for(cap).is_file())
            note = self._note()
            r = self._run(note, str(cap), [str(self.repo / rel)])
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["capture_exit_code"], 0)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(QuickCloseTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
