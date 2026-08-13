#!/usr/bin/env python3
"""Deterministic commit-gate CLI for the bgpdd-build pipeline.

Enforces the milestone commit gate mechanically: the latest review for the
milestone must be a machine-readable `**Verdict:** Approve` that postdates
the newest change, and the orchestrator-state blockers ledger must hold no
standing entry. On a pass, `--commit` performs the commit itself, so a
skipped gate is loud (no commit exists) rather than silent.

Usage:
    python check_commit_gate.py --review-report <path> --state <path> \
        --milestone "<title>" --changed-files <p1> [<p2> ...] \
        [--commit --message "<msg>"] [--repo <dir>] [--ignore-unscoped] \
        [--require-rendered-evidence] [--verify-tree]
    python check_commit_gate.py --self-test

Pure standard library. See ../SKILL.md for the full contract (JSON shape,
exit codes, parsing rules).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REVIEW_HEADING_RE = re.compile(r"^##\s*Review:\s*(.*)$")
VERDICT_LINE_RE = re.compile(r"^\s*\*\*Verdict:\*\*(.*)$")
VERDICT_TOKEN_RE = re.compile(r"^\s*(Approve|Request Changes)\s*$")
PATH_SHAPE_RE = re.compile(r"^[A-Za-z0-9_./\\-]+$")
PATH_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]+$")
MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_text(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding="utf-8", errors="replace")


def milestone_tokens(milestone):
    """Full title plus its leading identifier (text before the first ':' / '—')."""
    tokens = [milestone.strip().lower()]
    short = re.split(r"[:—-]", milestone, maxsplit=1)[0].strip().lower()
    if len(short) >= 2 and short != tokens[0]:
        tokens.append(short)
    return tokens


def milestone_token_patterns(milestone):
    """Compile each milestone token into a word-boundary regex.

    A bare substring test (e.g. "m1" `in` "## Review: M10 — ...") false-
    matches: "m1" is a substring of "m10". Requiring the token not be
    preceded/followed by an alphanumeric character makes it match only as a
    whole word, so "M1" no longer matches "M10" (or vice versa).
    """
    return [re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])")
            for t in milestone_tokens(milestone)]


def _matches_milestone(patterns, haystack):
    haystack_l = haystack.lower()
    return any(p.search(haystack_l) for p in patterns)


def parse_review_sections(text):
    """Return every '## Review: ...' section as (title, [body lines])."""
    sections = []
    current = None
    for line in text.splitlines():
        m = REVIEW_HEADING_RE.match(line)
        if m:
            current = (m.group(1).strip(), [])
            sections.append(current)
        elif line.startswith("## "):
            current = None  # a non-review level-2 heading closes the section
        elif current is not None:
            current[1].append(line)
    return sections


def find_matching_section(text, milestone):
    """Return (title, body_lines) for the LAST section matching the milestone."""
    patterns = milestone_token_patterns(milestone)
    matching = [s for s in parse_review_sections(text)
                if _matches_milestone(patterns, s[0])]
    return matching[-1] if matching else None


def find_latest_review(text, milestone):
    """Return (found, verdict_or_None, warnings) for the LAST matching section."""
    warnings = []
    section = find_matching_section(text, milestone)
    if section is None:
        return False, None, warnings
    title, body = section
    verdict_lines = [m.group(1) for m in
                     (VERDICT_LINE_RE.match(l) for l in body) if m]
    if not verdict_lines:
        warnings.append(f"review section '{title}' has no **Verdict:** line")
        return True, None, warnings
    token = VERDICT_TOKEN_RE.match(verdict_lines[-1])
    if not token:
        # Latest expression of intent is unreadable — fail-safe: no verdict.
        warnings.append(
            f"review section '{title}': latest Verdict line is not a "
            f"machine-readable token (got: {verdict_lines[-1].strip()!r}); "
            "required: 'Approve' or 'Request Changes' exactly")
        return True, None, warnings
    return True, token.group(1), warnings


def is_path_shaped(token):
    """A bare path-like token: allowed charset plus a dot-extension."""
    return bool(PATH_SHAPE_RE.match(token)) and bool(PATH_EXTENSION_RE.search(token))


def collect_rendered_evidence(body):
    """Gather evidence-path candidates from a matched review section's body.

    Sources: 'Rendered evidence: <paths>' lines (comma/whitespace-separated,
    path-shaped tokens only) and markdown image refs '![...](path)'.
    """
    candidates = []
    for line in body:
        if "Rendered evidence:" in line:
            after = line.split("Rendered evidence:", 1)[1]
            for tok in re.split(r"[,\s]+", after.strip()):
                if tok and is_path_shaped(tok):
                    candidates.append(tok)
        for m in MD_IMAGE_RE.finditer(line):
            candidates.append(m.group(1).strip())
    return candidates


def _cited_under_evidence_review(candidate):
    """True if the cited path names 'evidence/review/...' as a prefix.

    Tolerates backslash separators (a Windows-style citation) and a leading
    './'. This is a check on the CITED string itself -- the same string
    resolved against the review dir or --repo for existence -- so it applies
    regardless of which of the two bases resolved it.

    Rejects any '..' segment. Fixed 2026-08-12: the previous normalization
    was `lstrip("./")`, which strips ANY leading run of '.' and '/'
    characters rather than a single './' -- so '../evidence/review/x.png'
    collapsed to 'evidence/review/x.png' and satisfied provenance from
    outside the repo. `check_runtime_evidence.py` refuses traversal the same
    way; the two predicates differ only in anchoring (prefix here,
    containment there), deliberately and for documented reasons.
    """
    normalized = candidate.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p and p != "."]
    if ".." in parts:
        return False
    return (len(parts) >= 3 and parts[0].lower() == "evidence"
            and parts[1].lower() == "review")


def check_rendered_evidence(candidates, review_report, repo):
    """True if a candidate both exists (relative to the review dir or
    --repo) AND is cited under an evidence/review/ directory.

    Builder evidence (e.g. evidence/build/...) or any other existing path
    satisfies existence but not provenance -- only reviewer evidence gates.
    """
    review_dir = Path(review_report).parent
    repo_dir = Path(repo)
    for c in candidates:
        exists = (review_dir / c).exists() or (repo_dir / c).exists()
        if exists and _cited_under_evidence_review(c):
            return True
    return False


def check_staleness(review_report, changed_files):
    """Review file must be at least as new as the newest changed file."""
    warnings = []
    review_mtime = Path(review_report).stat().st_mtime
    newest = None
    for f in changed_files:
        p = Path(f)
        if not p.exists():
            warnings.append(f"changed file not found on disk (deleted?): {f}")
            continue
        mt = p.stat().st_mtime
        if newest is None or mt > newest:
            newest = mt
    stale = newest is not None and newest > review_mtime
    return stale, review_mtime, newest, warnings


def check_blockers(state_path, milestone, ignore_unscoped):
    """Split standing ledger entries into milestone-scoped and unscoped."""
    warnings = []
    try:
        state = json.loads(read_text(state_path))
    except json.JSONDecodeError as exc:
        raise GateError(f"state file is not valid JSON: {exc}")
    entries = state.get("blockers")
    if entries is None:
        raise GateError("state file has no 'blockers' field")
    if not isinstance(entries, list):
        raise GateError("'blockers' is not an array")
    patterns = milestone_token_patterns(milestone)
    scoped, unscoped = [], []
    for entry in entries:
        text = entry if isinstance(entry, str) else json.dumps(entry)
        (scoped if _matches_milestone(patterns, text) else unscoped).append(text)
    if unscoped and ignore_unscoped:
        warnings.append(
            f"{len(unscoped)} unscoped blocker entr{'y' if len(unscoped)==1 else 'ies'} "
            "ignored via --ignore-unscoped; verify none belongs to this milestone")
    return scoped, unscoped, warnings


def run_git(args, repo):
    proc = subprocess.run(["git"] + args, cwd=repo, capture_output=True,
                          text=True, timeout=240)
    if proc.returncode != 0:
        raise GateError(f"git {' '.join(args[:1])} failed: "
                        f"{(proc.stderr or proc.stdout).strip()}")
    return proc.stdout


def perform_commit(changed_files, message, repo):
    run_git(["add", "--"] + list(changed_files), repo)
    run_git(["commit", "-m", message], repo)


def parse_porcelain_line(line):
    """Return the path a `git status --porcelain` line refers to.

    Two status chars then a space then the path; rename/copy lines read
    `R  old -> new` (or `C  ...`) — take the new path. Paths git quotes for
    special characters have their surrounding double quotes stripped.
    """
    path = line[3:]
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    return path


def normalize_repo_path(path, repo):
    """Repo-relative, forward-slash, case-folded-on-Windows form for comparison."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(repo) / p
    p = p.resolve()
    try:
        rel = p.relative_to(Path(repo).resolve())
    except ValueError:
        rel = p
    normalized = os.path.normcase(str(rel).replace("\\", "/"))
    return normalized.replace("\\", "/")


def check_undeclared_tree(changed_files, repo):
    """Return repo-relative paths dirty in the working tree but not declared.

    Anything under `.docs/` is allowed regardless of declaration — pipeline
    artifacts (test reports, review reports, state, evidence) legitimately
    change during a milestone without being a builder code change.

    `git status --porcelain` collapses an entirely-untracked directory into a
    single `?? <dir>/` line rather than listing the files inside it. A
    porcelain path ending in `/` is therefore a DIRECTORY entry, not a file,
    and is normalized/compared as one: it is allowed iff its normalized form
    (trailing slash restored) is `.docs/` or begins with `.docs/`, or at
    least one declared `--changed-files` path lies under that directory
    prefix (a declared file's own never-before-tracked directory collapses
    the same way). Otherwise it is undeclared, reported WITH its trailing
    slash so the report is honest about it naming a directory, not a file.
    """
    output = run_git(["status", "--porcelain"], repo)
    declared = {normalize_repo_path(f, repo) for f in changed_files}
    undeclared = []
    for line in output.splitlines():
        if not line:
            continue
        raw_path = parse_porcelain_line(line)
        if raw_path.endswith("/"):
            norm_dir = normalize_repo_path(raw_path, repo) + "/"
            if norm_dir.startswith(".docs/"):
                continue
            if any(d == norm_dir or d.startswith(norm_dir) for d in declared):
                continue
            undeclared.append(norm_dir)
            continue
        norm = normalize_repo_path(raw_path, repo)
        if norm in declared or norm.startswith(".docs/"):
            continue
        undeclared.append(norm)
    return undeclared


RUNTIME_GATE = Path(__file__).parent / "check_runtime_evidence.py"


def run_runtime_gate(args):
    """Delegate to check_runtime_evidence.py. Returns (ok, its JSON payload).

    Subprocess rather than import: this family has no shared module by
    convention, and duplicating existence/provenance/freshness/content logic
    into a second file is the worse cost. `sys.executable` keeps the child on
    the same interpreter, and the file already shells out for git.
    """
    if not RUNTIME_GATE.is_file():
        raise GateError(f"runtime-evidence gate not found at {RUNTIME_GATE}")
    cmd = [sys.executable, str(RUNTIME_GATE),
           "--report", args.runtime_report,
           "--milestone", args.milestone,
           "--repo", args.repo]
    if args.changed_files:
        cmd += ["--changed-files"] + [str(p) for p in args.changed_files]
    if args.surface:
        cmd += ["--surface", args.surface]
    for key in args.require_key:
        cmd += ["--require-key", key]
    for host in args.forbid_host:
        cmd += ["--forbid-host", host]
    if args.expect_status is not None:
        cmd += ["--expect-status", str(args.expect_status)]
    if args.require_build_marker:
        cmd += ["--require-build-marker", args.require_build_marker]
    # The OpenAPI assertions must forward too, or the commit-time re-run is
    # strictly weaker than the earlier build-phase run — and this gate is the
    # one that owns the commit, so it is the one where the restraint has to
    # bind. Same reasoning as --verify-tree running here rather than only
    # earlier.
    if args.require_openapi_reachable:
        cmd += ["--require-openapi-reachable"]
    if args.openapi_doc:
        cmd += ["--openapi-doc", args.openapi_doc,
                "--openapi-route", args.openapi_route]
        if args.openapi_method:
            cmd += ["--openapi-method", args.openapi_method]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f"cannot run the runtime-evidence gate: {exc}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise GateError(
            f"runtime-evidence gate emitted unparseable output "
            f"(exit {proc.returncode}): {proc.stdout[:400]!r}")
    if proc.returncode == 2:
        # Its structural failure is our structural failure -- an artifact or
        # environment defect, never a silently-passed gate.
        raise GateError(
            f"runtime-evidence gate structural failure: {payload.get('error')}")
    return proc.returncode == 0, payload


def build_report(args):
    report = {
        "milestone": args.milestone,
        "review_report": args.review_report,
        "state_file": args.state,
        "review_found": False,
        "verdict": None,
        "stale": False,
        "blocking": [],
        "unscoped_blockers": [],
        "rendered_evidence": [],
        "rendered_evidence_ok": not args.require_rendered_evidence,
        "runtime_evidence": None,
        "runtime_evidence_ok": not args.require_runtime_evidence,
        "undeclared_changes": [],
        "tree_verified": True,
        "warnings": [],
        "committed": False,
        "result": "FAIL",
        "error": None,
    }
    text = read_text(args.review_report)
    found, verdict, w = find_latest_review(text, args.milestone)
    report["review_found"] = found
    report["verdict"] = verdict
    report["warnings"] += w
    if not found:
        report["warnings"].append(
            f"no '## Review:' section matching milestone {args.milestone!r}")

    stale, _, _, w = check_staleness(args.review_report, args.changed_files)
    report["stale"] = stale
    report["warnings"] += w
    if stale:
        report["warnings"].append(
            "a changed file is newer than the review report — the latest "
            "review predates the current diff and does not count")

    scoped, unscoped, w = check_blockers(args.state, args.milestone,
                                         args.ignore_unscoped)
    report["blocking"] = scoped
    report["unscoped_blockers"] = unscoped
    report["warnings"] += w

    section = find_matching_section(text, args.milestone)
    candidates = collect_rendered_evidence(section[1] if section else [])
    report["rendered_evidence"] = candidates
    if args.require_rendered_evidence:
        evidence_ok = check_rendered_evidence(candidates, args.review_report,
                                              args.repo)
        report["rendered_evidence_ok"] = evidence_ok
        if not evidence_ok:
            report["warnings"].append(
                "--require-rendered-evidence set but the matched review "
                "section cites no existing evidence file under an "
                "'evidence/review/' directory; expected a "
                "'Rendered evidence: <path>' line or a markdown image ref "
                "'![...](path)' naming a path under evidence/review/ that "
                "resolves under the review report's directory or --repo "
                f"({args.repo}) — evidence under evidence/build/ or "
                "elsewhere does not satisfy this gate")

    if args.require_runtime_evidence:
        runtime_ok, payload = run_runtime_gate(args)
        report["runtime_evidence_ok"] = runtime_ok
        report["runtime_evidence"] = payload
        if not runtime_ok:
            accepted = payload.get("accepted") or []
            report["warnings"].append(
                "--require-runtime-evidence set but the runtime-evidence gate "
                f"failed for this milestone ({len(accepted)} accepted "
                "capture(s)); see the 'runtime_evidence' object for the "
                "per-capture cause. An in-process suite cannot pass a claim "
                "about observed behavior")

    if args.verify_tree:
        undeclared = check_undeclared_tree(args.changed_files, args.repo)
        report["undeclared_changes"] = undeclared
        report["tree_verified"] = not undeclared
        for path in undeclared:
            report["warnings"].append(
                f"--verify-tree set but the working tree has an undeclared "
                f"change outside --changed-files and .docs/: {path}")

    gate_ok = (found and verdict == "Approve" and not stale and not scoped
               and (args.ignore_unscoped or not unscoped)
               and report["rendered_evidence_ok"]
               and report["runtime_evidence_ok"]
               and report["tree_verified"])
    report["result"] = "PASS" if gate_ok else "FAIL"

    if gate_ok and args.commit:
        perform_commit(args.changed_files, args.message, args.repo)
        report["committed"] = True
    return report


def build_parser():
    """Single source of truth for the CLI surface.

    Extracted from main() so the self-test parses real argv instead of
    hand-building argparse.Namespace objects -- every hand-built namespace is
    a place a newly-added flag raises AttributeError instead of being tested.
    """
    parser = argparse.ArgumentParser(prog="check_commit_gate.py")
    parser.add_argument("--review-report")
    parser.add_argument("--state")
    parser.add_argument("--milestone")
    parser.add_argument("--changed-files", nargs="+", default=[])
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--message")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--ignore-unscoped", action="store_true")
    parser.add_argument("--require-rendered-evidence", action="store_true")
    parser.add_argument("--verify-tree", action="store_true")
    # Runtime-evidence delegation. This gate owns the commit, so the restraint
    # has to live here -- but the checking logic lives once, in
    # check_runtime_evidence.py, rather than being duplicated across two files.
    parser.add_argument("--require-runtime-evidence", action="store_true")
    parser.add_argument("--runtime-report")
    parser.add_argument("--surface")
    parser.add_argument("--require-key", action="append", default=[])
    parser.add_argument("--expect-status", type=int)
    parser.add_argument("--forbid-host", action="append", default=[])
    parser.add_argument("--require-build-marker")
    parser.add_argument("--require-openapi-reachable", action="store_true")
    parser.add_argument("--openapi-doc")
    parser.add_argument("--openapi-route")
    parser.add_argument("--openapi-method")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    missing = [n for n, v in (("--review-report", args.review_report),
                              ("--state", args.state),
                              ("--milestone", args.milestone)) if not v]
    if missing:
        print(json.dumps({"result": "ERROR",
                          "error": f"missing required argument(s): {', '.join(missing)}"}))
        return 2
    if args.commit and not args.message:
        print(json.dumps({"result": "ERROR",
                          "error": "--commit requires --message"}))
        return 2
    if not args.changed_files:
        print(json.dumps({"result": "ERROR",
                          "error": "--changed-files requires at least one path"}))
        return 2
    if args.require_runtime_evidence and not args.runtime_report:
        print(json.dumps({"result": "ERROR",
                          "error": "--require-runtime-evidence requires --runtime-report "
                                    "(the test or verification report carrying the "
                                    "**Runtime evidence:** citations)"}))
        return 2
    forwarded = [n for n, v in (("--runtime-report", args.runtime_report),
                                 ("--surface", args.surface),
                                 ("--require-key", args.require_key),
                                 ("--expect-status", args.expect_status),
                                 ("--forbid-host", args.forbid_host),
                                 ("--require-build-marker", args.require_build_marker),
                                 ("--require-openapi-reachable",
                                  args.require_openapi_reachable),
                                 ("--openapi-doc", args.openapi_doc),
                                 ("--openapi-route", args.openapi_route),
                                 ("--openapi-method", args.openapi_method))
                 if v and not args.require_runtime_evidence]
    if forwarded:
        print(json.dumps({"result": "ERROR",
                          "error": f"{', '.join(forwarded)} given without "
                                    "--require-runtime-evidence"}))
        return 2

    try:
        report = build_report(args)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["result"] == "PASS" else 1


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import os
    import shutil
    import tempfile
    import unittest

    REVIEW_OK = ("## Review: M3 — Auth endpoints\n\nfindings...\n\n"
                 "**Verdict:** Approve\n")
    REVIEW_RC = ("## Review: M3 — Auth endpoints\n\n"
                 "**Verdict:** Request Changes\n")
    REVIEW_EVIDENCE_LINE = ("## Review: M3 — Auth endpoints\n\nfindings...\n\n"
                            "Rendered evidence: evidence/review/m3-table.png\n\n"
                            "**Verdict:** Approve\n")
    REVIEW_EVIDENCE_IMAGE = ("## Review: M3 — Auth endpoints\n\nfindings...\n\n"
                             "![screenshot](evidence/review/m3-shot.png)\n\n"
                             "**Verdict:** Approve\n")
    REVIEW_EVIDENCE_BUILD_ONLY = ("## Review: M3 — Auth endpoints\n\nfindings...\n\n"
                                  "Rendered evidence: evidence/build/m3-table.png\n\n"
                                  "**Verdict:** Approve\n")

    class GateTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.changed = self.dir / "src_file.py"
            self.changed.write_text("code\n")
            self.review = self.dir / "review-report.md"
            self.state = self.dir / "orchestrator-state.json"
            self.state.write_text(json.dumps({"blockers": []}))

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _order(self, older, newer):
            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))

        def _ns(self, milestone="M3", changed=None, repo=None, extra=None,
                commit=False, message=None):
            """Parse real argv -- never hand-build a Namespace.

            A hand-built Namespace silently lacks any newly-added flag and
            raises AttributeError instead of exercising it, which is how a new
            gate term can ship untested.
            """
            argv = ["--review-report", str(self.review),
                    "--state", str(self.state),
                    "--milestone", milestone,
                    "--changed-files"] + (changed or [str(self.changed)]) + [
                    "--repo", repo or str(self.dir)]
            if commit:
                argv += ["--commit", "--message", message or "m"]
            return build_parser().parse_args(argv + (extra or []))

        def _run(self, extra=None):
            return build_report(self._ns(extra=extra))

        def test_happy_path_passes(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self.assertEqual(self._run()["result"], "PASS")

        def test_request_changes_fails(self):
            self.review.write_text(REVIEW_RC)
            self._order(self.changed, self.review)
            r = self._run()
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["verdict"], "Request Changes")

        def test_stale_review_fails(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.review, self.changed)  # change is newer
            r = self._run()
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(r["stale"])

        def test_scoped_blocker_fails(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": ["M3: placeholder route finding open"]}))
            r = self._run()
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(len(r["blocking"]), 1)

        def test_unscoped_blocker_fails_by_default(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": ["proxy substitution in test env"]}))
            self.assertEqual(self._run()["result"], "FAIL")

        def test_unscoped_blocker_ignorable(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": ["proxy substitution in test env"]}))
            r = self._run(["--ignore-unscoped"])
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(len(r["unscoped_blockers"]), 1)

        def test_missing_review_section_fails(self):
            self.review.write_text("## Review: M7 — other milestone\n"
                                   "**Verdict:** Approve\n")
            self._order(self.changed, self.review)
            r = self._run()
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["review_found"])

        def test_latest_matching_section_wins(self):
            self.review.write_text(REVIEW_RC + "\n" + REVIEW_OK)
            self._order(self.changed, self.review)
            self.assertEqual(self._run()["result"], "PASS")

        def test_word_boundary_m1_does_not_match_m10_section(self):
            # Gating M1 must NOT match a report whose only section is "M10".
            self.review.write_text(
                "## Review: M10 — Unrelated milestone\n\n**Verdict:** Approve\n")
            self._order(self.changed, self.review)
            ns = self._ns(milestone="M1")
            r = build_report(ns)
            self.assertFalse(r["review_found"])
            self.assertEqual(r["result"], "FAIL")

        def test_word_boundary_m1_matches_m1_section(self):
            # Existing behavior preserved: M1 matches a section titled M1.
            self.review.write_text(
                "## Review: M1 — Setup\n\n**Verdict:** Approve\n")
            changed = self.dir / "m1_file.py"
            changed.write_text("code\n")
            self._order(changed, self.review)
            ns = self._ns(milestone="M1", changed=[str(changed)])
            r = build_report(ns)
            self.assertTrue(r["review_found"])
            self.assertEqual(r["result"], "PASS")

        def test_word_boundary_m10_scoped_blocker_does_not_gate_m1(self):
            # An M10-scoped blocker must land in unscoped, not blocking, for
            # an M1 gate run -- proving "m1" no longer substring-matches
            # "m10". (It still gates by default via the unscoped policy;
            # --ignore-unscoped is the documented override, which then
            # passes -- demonstrating it was never truly M1-scoped.)
            self.review.write_text(
                "## Review: M1 — Setup\n\n**Verdict:** Approve\n")
            self._order(self.changed, self.review)
            self.state.write_text(json.dumps(
                {"blockers": ["M10: unrelated finding open"]}))
            ns = self._ns(milestone="M1")
            r = build_report(ns)
            self.assertEqual(r["blocking"], [])
            self.assertEqual(len(r["unscoped_blockers"]), 1)
            self.assertEqual(r["result"], "FAIL")  # unscoped gates by default

            ns.ignore_unscoped = True
            r2 = build_report(ns)
            self.assertEqual(r2["result"], "PASS")

        # ---- --require-runtime-evidence (delegates to check_runtime_evidence) ----

        def _runtime_fixtures(self, body, openapi=None):
            """A test-report citing one capture with the given response body."""
            impl = self.dir / ".docs" / "p" / "implementation"
            (impl / "evidence" / "runtime").mkdir(parents=True, exist_ok=True)
            cap = impl / "evidence" / "runtime" / "m3.md"
            cap.write_text(
                "# Runtime capture\n\n"
                "- Milestone: M3 — auth endpoints [API] [vs:api]\n"
                "- Surface: api\n"
                "- Transport: out-of-process HTTP\n"
                + (f"- OpenAPI: {openapi}\n" if openapi else "")
                + "- Base URL: http://localhost:5142\n"
                "- Probe command: `curl -sS -i http://localhost:5142/api/auth`\n"
                "- Captured: 2026-08-12T14:03:11Z\n"
                "- Exit code: 0\n\n"
                "## Captured output\n\n```\nHTTP/1.1 200 OK\n\n" + body + "\n```\n",
                encoding="utf-8")
            report = impl / "test-report.md"
            report.write_text(
                "#Task [1]:\n\n**Runtime evidence:** evidence/runtime/m3.md\n"
                "- FR-1: PASS — AuthTests.cs\n", encoding="utf-8")
            # capture must postdate the diff
            os.utime(self.changed, (1000, 1000))
            os.utime(cap, (3000, 3000))
            os.utime(report, (3000, 3000))
            return str(report)

        def test_runtime_evidence_envelope_present_passes(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            rep = self._runtime_fixtures('{"isSuccess":true,"notifications":[]}')
            r = build_report(self._ns(extra=[
                "--require-runtime-evidence", "--runtime-report", rep,
                "--require-key", "isSuccess", "--require-key", "notifications"]))
            self.assertTrue(r["runtime_evidence_ok"], r["runtime_evidence"])
            self.assertEqual(r["result"], "PASS")

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_runtime_evidence_missing_envelope_blocks_the_commit(self):
            """The load-bearing case: everything else green, no commit exists."""
            run_git(["init", "-q"], str(self.dir))
            run_git(["config", "user.email", "gate@test"], str(self.dir))
            run_git(["config", "user.name", "gate"], str(self.dir))
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            rep = self._runtime_fixtures('{"id":1,"total":9}')   # bare payload
            r = build_report(self._ns(
                milestone="M3", commit=True, message="M3: auth endpoints",
                extra=["--require-runtime-evidence", "--runtime-report", rep,
                       "--require-key", "isSuccess", "--require-key", "notifications"]))
            self.assertFalse(r["runtime_evidence_ok"])
            self.assertEqual(r["verdict"], "Approve")      # review was fine
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["committed"])
            # `git log` ERRORS on a repo with no commits, so count instead --
            # zero commits is the proof the gate blocked rather than reported.
            self.assertEqual(
                run_git(["rev-list", "--all", "--count"], str(self.dir)).strip(), "0")

        def test_openapi_flag_forwards_to_the_child_gate(self):
            """A commit-time re-run must not be weaker than the earlier run.

            The flag has to reach the child process, so the assertion is that
            the SAME capture passes without it and fails with it.
            """
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            rep = self._runtime_fixtures('{"isSuccess":true,"notifications":[]}')
            base = ["--require-runtime-evidence", "--runtime-report", rep]
            r = build_report(self._ns(extra=base))
            self.assertTrue(r["runtime_evidence_ok"], r["runtime_evidence"])
            r2 = build_report(self._ns(extra=base + ["--require-openapi-reachable"]))
            self.assertFalse(r2["runtime_evidence_ok"])
            self.assertEqual(r2["result"], "FAIL")

        def test_openapi_flag_passes_when_the_capture_records_it(self):
            """The forwarded assertion is satisfiable, not a dead end."""
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            rep = self._runtime_fixtures(
                '{"isSuccess":true,"notifications":[]}',
                openapi="http://localhost:5142/swagger/v1/swagger.json — 200")
            r = build_report(self._ns(extra=[
                "--require-runtime-evidence", "--runtime-report", rep,
                "--require-openapi-reachable"]))
            self.assertTrue(r["runtime_evidence_ok"], r["runtime_evidence"])
            self.assertEqual(r["result"], "PASS")

        def test_runtime_evidence_flag_unset_is_backcompat(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            r = self._run()
            self.assertTrue(r["runtime_evidence_ok"])
            self.assertIsNone(r["runtime_evidence"])
            self.assertEqual(r["result"], "PASS")

        def test_runtime_report_missing_is_exit_2_not_a_pass(self):
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            with self.assertRaises(GateError):
                build_report(self._ns(extra=[
                    "--require-runtime-evidence",
                    "--runtime-report", str(self.dir / "nope.md")]))

        def test_usage_errors_for_the_delegating_flags(self):
            base = ["--review-report", str(self.review), "--state", str(self.state),
                    "--milestone", "M3", "--changed-files", str(self.changed)]
            # --require-runtime-evidence without --runtime-report
            self.assertEqual(main(base + ["--require-runtime-evidence"]), 2)
            # forwarded flags without the gate flag
            self.assertEqual(main(base + ["--require-key", "isSuccess"]), 2)
            self.assertEqual(main(base + ["--expect-status", "200"]), 2)
            self.assertEqual(main(base + ["--require-openapi-reachable"]), 2)
            self.assertEqual(main(base + ["--openapi-doc", "x.json",
                                          "--openapi-route", "/a"]), 2)
            self.assertEqual(main(base + ["--openapi-method", "post"]), 2)

        def test_nonstandard_verdict_token_fails(self):
            self.review.write_text("## Review: M3\n\n**Verdict:** Approved\n")
            self._order(self.changed, self.review)
            r = self._run()
            self.assertEqual(r["result"], "FAIL")
            self.assertIsNone(r["verdict"])

        def test_verdict_after_earlier_valid_wins(self):
            self.review.write_text("## Review: M3\n\n**Verdict:** Approve\n"
                                   "**Verdict:** LGTM\n")
            self._order(self.changed, self.review)
            self.assertEqual(self._run()["result"], "FAIL")

        def test_missing_state_raises(self):
            self.review.write_text(REVIEW_OK)
            self.state.unlink()
            with self.assertRaises(GateError):
                self._run()

        def test_rendered_evidence_line_present_passes(self):
            self.review.write_text(REVIEW_EVIDENCE_LINE)
            self._order(self.changed, self.review)
            evidence_dir = self.dir / "evidence" / "review"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "m3-table.png").write_bytes(b"")
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["rendered_evidence_ok"])
            self.assertIn("evidence/review/m3-table.png", r["rendered_evidence"])

        def test_rendered_evidence_missing_fails(self):
            self.review.write_text(REVIEW_EVIDENCE_LINE)  # path cited, not on disk
            self._order(self.changed, self.review)
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["rendered_evidence_ok"])

        def test_rendered_evidence_markdown_image_passes(self):
            self.review.write_text(REVIEW_EVIDENCE_IMAGE)
            self._order(self.changed, self.review)
            evidence_dir = self.dir / "evidence" / "review"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "m3-shot.png").write_bytes(b"")
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["rendered_evidence_ok"])

        def test_rendered_evidence_flag_unset_is_backcompat(self):
            self.review.write_text(REVIEW_OK)  # no evidence cited anywhere
            self._order(self.changed, self.review)
            r = self._run()
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["rendered_evidence_ok"])

        def test_rendered_evidence_build_dir_only_fails(self):
            # Existing evidence file, but cited under evidence/build/ (a
            # builder-produced artifact) rather than evidence/review/ (a
            # reviewer-produced one) -- must not satisfy the gate.
            self.review.write_text(REVIEW_EVIDENCE_BUILD_ONLY)
            self._order(self.changed, self.review)
            evidence_dir = self.dir / "evidence" / "build"
            evidence_dir.mkdir(parents=True)
            (evidence_dir / "m3-table.png").write_bytes(b"")
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["rendered_evidence_ok"])
            self.assertIn("evidence/build/m3-table.png", r["rendered_evidence"])

        def test_rendered_evidence_none_cited_fails(self):
            self.review.write_text(REVIEW_OK)  # no evidence citation at all
            self._order(self.changed, self.review)
            r = self._run(["--require-rendered-evidence"])
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["rendered_evidence_ok"])
            self.assertEqual(r["rendered_evidence"], [])

        def test_provenance_refuses_parent_traversal(self):
            """`lstrip("./")` collapsed '../evidence/review/x' to a passing path."""
            self.assertFalse(_cited_under_evidence_review("../evidence/review/x.png"))
            self.assertFalse(_cited_under_evidence_review("../../evidence/review/x.png"))
            # unchanged acceptances
            self.assertTrue(_cited_under_evidence_review("evidence/review/x.png"))
            self.assertTrue(_cited_under_evidence_review("./evidence/review/x.png"))
            self.assertTrue(_cited_under_evidence_review("/evidence/review/x.png"))
            self.assertTrue(_cited_under_evidence_review("evidence\\review\\x.png"))
            # still prefix-anchored: a nested prefix does NOT satisfy this
            # predicate (deliberate; check_runtime_evidence.py scans instead)
            self.assertFalse(_cited_under_evidence_review(
                ".docs/p/implementation/evidence/review/x.png"))

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_commit_on_pass(self):
            run_git(["init", "-q"], str(self.dir))
            run_git(["config", "user.email", "gate@test"], str(self.dir))
            run_git(["config", "user.name", "gate"], str(self.dir))
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            ns = self._ns(milestone="M3", commit=True,
                           message="M3: auth endpoints (FR-1, FR-2)")
            r = build_report(ns)
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["committed"])
            log = run_git(["log", "--oneline"], str(self.dir))
            self.assertIn("M3: auth endpoints", log)

        def _init_repo_for_tree_check(self):
            run_git(["init", "-q"], str(self.dir))
            run_git(["config", "user.email", "gate@test"], str(self.dir))
            run_git(["config", "user.name", "gate"], str(self.dir))
            (self.dir / ".gitignore").write_text(
                "review-report.md\norchestrator-state.json\n")
            docs_dir = self.dir / ".docs"
            docs_dir.mkdir()
            self.docs_file = docs_dir / "state.md"
            self.docs_file.write_text("initial\n")
            run_git(["add", "-A"], str(self.dir))
            run_git(["commit", "-m", "init"], str(self.dir))

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_verify_tree_declared_and_docs_change_passes(self):
            self._init_repo_for_tree_check()
            self.changed.write_text("code changed\n")
            self.docs_file.write_text("updated\n")
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            r = self._run(["--verify-tree"])
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["tree_verified"])
            self.assertEqual(r["undeclared_changes"], [])

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_verify_tree_undeclared_tracked_change_fails(self):
            self._init_repo_for_tree_check()
            other = self.dir / "other_file.py"
            other.write_text("v1\n")
            run_git(["add", "-A"], str(self.dir))
            run_git(["commit", "-m", "add other"], str(self.dir))
            other.write_text("v2\n")
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            r = self._run(["--verify-tree"])
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["tree_verified"])
            self.assertIn("other_file.py", r["undeclared_changes"])

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_verify_tree_undeclared_untracked_file_fails(self):
            self._init_repo_for_tree_check()
            stray = self.dir / "stray.py"
            stray.write_text("surprise\n")
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            r = self._run(["--verify-tree"])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("stray.py", r["undeclared_changes"])

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_verify_tree_flag_unset_is_backcompat(self):
            self._init_repo_for_tree_check()
            stray = self.dir / "stray.py"
            stray.write_text("surprise\n")
            self.review.write_text(REVIEW_OK)
            self._order(self.changed, self.review)
            r = self._run()
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["tree_verified"])
            self.assertEqual(r["undeclared_changes"], [])

        # -- Directory-entry porcelain lines (no scaffold commit at all) -----
        # `git status --porcelain` collapses an entirely-untracked directory
        # into one `?? <dir>/` line. These run against a FRESH `git init`
        # repo with zero commits (everything untracked), which is exactly
        # when that collapse happens -- unlike _init_repo_for_tree_check's
        # repos, which pre-track `.docs/` and `src/` via a scaffold commit.
        # review-report.md/orchestrator-state.json live outside the repo dir
        # so they never pollute `git status` for it.

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_verify_tree_fresh_repo_declared_file_in_untracked_dir_and_docs_pass(self):
            repo_dir = Path(tempfile.mkdtemp())
            try:
                run_git(["init", "-q"], str(repo_dir))
                run_git(["config", "user.email", "gate@test"], str(repo_dir))
                run_git(["config", "user.name", "gate"], str(repo_dir))
                src_dir = repo_dir / "src"
                src_dir.mkdir()
                declared_file = src_dir / "api.cs"
                declared_file.write_text("code\n")
                docs_dir = repo_dir / ".docs"
                docs_dir.mkdir()
                (docs_dir / "state.md").write_text("state\n")
                self.review.write_text(REVIEW_OK)
                self._order(self.changed, declared_file)
                self._order(declared_file, self.review)
                ns = self._ns(milestone="M3",
                              changed=[str(self.changed), str(declared_file)],
                              repo=str(repo_dir), extra=["--verify-tree"])
                r = build_report(ns)
                self.assertEqual(r["result"], "PASS")
                self.assertTrue(r["tree_verified"])
                self.assertEqual(r["undeclared_changes"], [])
            finally:
                shutil.rmtree(repo_dir, ignore_errors=True)

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_verify_tree_fresh_repo_untracked_dir_with_only_undeclared_files_fails(self):
            repo_dir = Path(tempfile.mkdtemp())
            try:
                run_git(["init", "-q"], str(repo_dir))
                run_git(["config", "user.email", "gate@test"], str(repo_dir))
                run_git(["config", "user.name", "gate"], str(repo_dir))
                stray_dir = repo_dir / "stray"
                stray_dir.mkdir()
                (stray_dir / "file.py").write_text("surprise\n")
                self.review.write_text(REVIEW_OK)
                self._order(self.changed, self.review)
                ns = self._ns(milestone="M3",
                              changed=[str(self.changed)],
                              repo=str(repo_dir), extra=["--verify-tree"])
                r = build_report(ns)
                self.assertEqual(r["result"], "FAIL")
                self.assertFalse(r["tree_verified"])
                self.assertIn("stray/", r["undeclared_changes"])
            finally:
                shutil.rmtree(repo_dir, ignore_errors=True)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(GateTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
