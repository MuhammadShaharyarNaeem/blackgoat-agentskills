#!/usr/bin/env python3
"""Deterministic milestone-completion writer for plan.md.

`next_milestone.py` reads completion from a `[x]` appended to a milestone
heading — and until this file existed, that `[x]` was a hand edit tied to
nothing. A milestone could be marked done by typing three characters: no
commit, no gate, no evidence. This is the write side of that convention, and
it refuses to append the marker unless the completion is backed:

  * `--require-commit` — HEAD's history must carry a commit naming the
    milestone (`git log --fixed-strings --grep`);
  * `--require-gates` (with `--ledger`) — the LATEST ledger entry for each
    named gate, scoped to this milestone, must record `PASS`.

Both are opt-in, because a plan may legitimately be marked up before a repo
exists (a docs-only milestone, a spike). What is NOT optional is that the
marker is written by a tool that leaves a ledger record, so a completion is
always attributable afterwards.

Usage:
    python mark_milestone.py --plan <path> --milestone "<title>" \
        [--repo <dir>] [--require-commit] \
        [--ledger <path>] [--require-gates <name>[,<name>...]]
    python mark_milestone.py --self-test

Pure standard library. See ../SKILL.md for the full contract.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Duplicated VERBATIM from next_milestone.py: the write side must recognize
# exactly the headings the read side does, or a marked milestone would be
# invisible to the router. This script family has no shared module by
# convention (GateError is duplicated in seven files).
MILESTONE_HEADING_RE = re.compile(r"^#{2,3}\s*Milestone\b\s+\d")
COMPLETE_RE = re.compile(r"\[x\]", re.IGNORECASE)
HEADING_PREFIX_RE = re.compile(r"^#+\s*")
LINE_SPLIT_RE = re.compile(r"(\r\n|\r|\n)")

DEFAULT_REQUIRE_GATES = ("check_commit_gate.py",)


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_text(path):
    """Read a UTF-8 artifact with its line endings intact, tolerating a BOM.

    `newline=""` keeps CRLF as CRLF: this file REWRITES the plan, so
    normalizing line endings would rewrite every line of a Windows-authored
    plan and bury the one-character change in a whole-file diff.
    """
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    with open(p, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        return fh.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


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
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
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
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


def read_ledger(ledger_path):
    """Every parseable JSON-object line of the ledger, in file order."""
    p = Path(ledger_path)
    if not p.is_file():
        return []
    records = []
    for line in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
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


def split_lines(text):
    """[(content, line_ending)] — the split that lets one line be rewritten."""
    parts = LINE_SPLIT_RE.split(text)
    lines = []
    for i in range(0, len(parts), 2):
        content = parts[i]
        ending = parts[i + 1] if i + 1 < len(parts) else ""
        if content == "" and ending == "":
            continue
        lines.append([content, ending])
    return lines


def find_milestone(lines, milestone):
    """Return (index, problems) for the ONE heading matching `milestone`.

    Matching is a case-insensitive WHOLE-TOKEN test: the given title must
    appear in the heading with no alphanumeric character glued to either end,
    so `M1` never matches `M10` — the same word-boundary rule
    check_commit_gate.py uses to scope a review section.

    Zero matches and several matches are both refusals, not guesses: marking
    the wrong milestone complete is exactly as bad as marking one that does
    not exist, and there is no safe way to pick.
    """
    needle = milestone.strip()
    if not needle:
        raise GateError("--milestone is empty")
    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(needle.lower())}(?![a-z0-9])")
    matches = [i for i, (content, _e) in enumerate(lines)
               if MILESTONE_HEADING_RE.match(content)
               and pattern.search(content.lower())]
    if not matches:
        return None, [{
            "problem": "milestone_not_found",
            "detail": f"no '## Milestone <n>' heading matching {milestone!r}"}]
    if len(matches) > 1:
        titles = [HEADING_PREFIX_RE.sub("", lines[i][0]).rstrip()
                  for i in matches]
        return None, [{
            "problem": "ambiguous_milestone",
            "detail": f"{len(matches)} headings match {milestone!r} "
                      f"({'; '.join(titles)}) — name one exactly"}]
    return matches[0], []


def check_commit_exists(repo, milestone):
    """True when HEAD's history carries a commit naming the milestone.

    `--fixed-strings` deliberately: a milestone title carries em dashes and
    brackets, and treating it as a regex would either error or match
    something else.
    """
    try:
        proc = subprocess.run(
            ["git", "log", "--fixed-strings", f"--grep={milestone}",
             "--format=%H"],
            cwd=repo, capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f"cannot run git in {repo}: {exc}")
    if proc.returncode != 0:
        raise GateError(
            "git log failed (is --repo a git repository with at least one "
            f"commit?): {(proc.stderr or proc.stdout).strip()}")
    return bool(proc.stdout.strip())


def check_ledger_gates(ledger_path, gate_names, milestone):
    """Refuse unless each named gate's LATEST entry for this milestone PASSed.

    SCOPE LIMIT, and a deliberate divergence (CLAUDE.md convention #8) from
    check_commit_gate.py's `--require-ledger-gates`, which additionally
    re-hashes each recorded input: this checks the VERDICT only. Input
    freshness is the commit gate's own term, and re-asserting it here would
    refuse a legitimate mark whenever a later milestone touched a shared file.
    """
    records = read_ledger(ledger_path)
    problems = []
    for name in gate_names:
        candidates = [r for r in records
                      if r.get("gate") == name
                      and r.get("milestone") == milestone]
        if not candidates:
            problems.append({
                "problem": "ledger_missing",
                "detail": f"no {name} ledger entry for milestone "
                          f"{milestone!r} in {ledger_path}"})
            continue
        latest = candidates[-1]
        if latest.get("verdict") != "PASS":
            problems.append({
                "problem": "ledger_failed",
                "detail": f"the latest {name} entry for {milestone!r} records "
                          f"verdict {latest.get('verdict')!r}"})
    return problems


def build_report(args):
    report = {
        "plan_file": args.plan,
        "milestone": args.milestone,
        "matched_heading": None,
        "require_commit": bool(args.require_commit),
        "commit_found": None,
        "ledger": args.ledger,
        "require_gates": list(args.require_gates or []),
        "problems": [],
        "marked": False,
        "result": "FAIL",
        "error": None,
    }
    text = read_text(args.plan)
    lines = split_lines(text)
    if not any(MILESTONE_HEADING_RE.match(c) for c, _e in lines):
        raise GateError(
            "plan has no '## Milestone <n>' or '### Milestone <n>' headings")

    index, problems = find_milestone(lines, args.milestone)
    report["problems"] += problems
    if index is None:
        return report

    heading = lines[index][0]
    report["matched_heading"] = HEADING_PREFIX_RE.sub("", heading).rstrip()

    if COMPLETE_RE.search(heading):
        report["problems"].append({
            "problem": "already_complete",
            "detail": f"heading {report['matched_heading']!r} already carries "
                      "'[x]' — completion is recorded once"})
        return report

    if args.require_commit:
        report["commit_found"] = check_commit_exists(args.repo, args.milestone)
        if not report["commit_found"]:
            report["problems"].append({
                "problem": "no_commit",
                "detail": f"no commit in HEAD's history names "
                          f"{args.milestone!r} (git log --fixed-strings "
                          f"--grep) in {args.repo}"})

    if args.require_gates:
        report["problems"] += check_ledger_gates(
            args.ledger, args.require_gates, args.milestone)

    if report["problems"]:
        return report

    content, ending = lines[index]
    lines[index][0] = content.rstrip() + " [x]"
    write_text(args.plan, "".join(c + e for c, e in lines))
    report["marked"] = True
    report["result"] = "PASS"
    return report


def parse_gate_names(values):
    """Flatten repeated and/or comma-separated --require-gates values."""
    names = []
    for value in values or []:
        for token in value.split(","):
            token = token.strip()
            if token and token not in names:
                names.append(token)
    return names


def build_parser():
    parser = argparse.ArgumentParser(prog="mark_milestone.py")
    parser.add_argument("--plan")
    parser.add_argument("--milestone")
    parser.add_argument("--repo", default=".")
    parser.add_argument(
        "--require-commit", action="store_true",
        help="refuse unless HEAD's history carries a commit naming the "
             "milestone")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument(
        "--require-gates", action="append", default=None,
        help="comma-separated gate script names whose LATEST ledger entry for "
             "this milestone must be PASS (default: check_commit_gate.py)")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    # `--require-gates` with no value list means the default gate set. Given
    # without `--ledger` it is a usage error rather than a silent no-op: a
    # typo'd invocation must not quietly drop the requirement.
    if args.require_gates is not None:
        args.require_gates = (parse_gate_names(args.require_gates)
                              or list(DEFAULT_REQUIRE_GATES))
    else:
        args.require_gates = []

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone,
                      [args.plan] if args.plan else [], verdict, code)
        return code

    missing = [n for n, v in (("--plan", args.plan),
                              ("--milestone", args.milestone)) if not v]
    if missing:
        print(json.dumps({"result": "ERROR",
                          "error": f"missing required argument(s): "
                                   f"{', '.join(missing)}"}))
        return finish(2, "ERROR")
    if args.require_gates and not args.ledger:
        print(json.dumps({"result": "ERROR",
                          "error": "--require-gates requires --ledger (there "
                                   "is no ledger to read otherwise)"}))
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
    import shutil
    import tempfile
    import unittest

    PLAN = """# Demo Plan

## Milestone 1 — Setup [API] [vs:api] [x]

## Task 1: Init repo

## Milestone 2 — Persistence [API] [vs:api]

## Task 2: Add DB layer

## Milestone 10 — Reporting [API] [vs:api]

## Task 3: Add report
"""

    def git(args, repo):
        proc = subprocess.run(["git"] + args, cwd=repo, capture_output=True,
                              text=True, timeout=240)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout)
        return proc.stdout

    class MarkMilestoneTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.plan = self.dir / "plan.md"
            self.plan.write_text(PLAN, encoding="utf-8")
            self.ledger = self.dir / "gates.jsonl"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _args(self, milestone="Milestone 2", **kw):
            base = dict(plan=str(self.plan), milestone=milestone,
                        repo=str(self.dir), require_commit=False,
                        ledger=None, require_gates=[], self_test=False)
            base.update(kw)
            return argparse.Namespace(**base)

        def _init_repo(self):
            git(["init", "-q"], str(self.dir))
            git(["config", "user.email", "gate@test"], str(self.dir))
            git(["config", "user.name", "gate"], str(self.dir))
            (self.dir / "src.py").write_text("code\n", encoding="utf-8")
            git(["add", "-A"], str(self.dir))

        def _write_ledger(self, **over):
            rec = {"ts": "2026-09-02T00:00:00Z", "gate": "check_commit_gate.py",
                   "argv": [], "milestone": "Milestone 2", "inputs": {},
                   "verdict": "PASS", "exit": 0}
            rec.update(over)
            with open(self.ledger, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")

        def _ledger_records(self, path=None):
            p = Path(path or self.ledger)
            return [json.loads(l) for l in
                    p.read_text(encoding="utf-8").splitlines() if l.strip()]

        # ---- happy path ----

        def test_marks_the_matching_heading(self):
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["marked"])
            text = self.plan.read_text(encoding="utf-8")
            self.assertIn("## Milestone 2 — Persistence [API] [vs:api] [x]", text)
            # Nothing else moved.
            self.assertIn("## Milestone 10 — Reporting [API] [vs:api]\n", text)
            self.assertEqual(text.count("[x]"), 2)

        def test_next_milestone_agrees_the_mark_took(self):
            """The write side must be visible to the read side."""
            build_report(self._args())
            sys.path.insert(0, str(Path(__file__).parent))
            import next_milestone as nm

            report = nm.build_report(argparse.Namespace(
                plan=str(self.plan), state=None, ledger=None,
                emit_gate_args=False))
            self.assertEqual(report["completed_count"], 2)
            self.assertTrue(
                report["next_milestone"]["title"].startswith("Milestone 10"))

        def test_crlf_plan_keeps_its_line_endings(self):
            self.plan.write_bytes(PLAN.replace("\n", "\r\n").encode("utf-8"))
            build_report(self._args())
            raw = self.plan.read_bytes()
            # Every newline is still a CRLF — no bare LF was introduced.
            self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"))
            self.assertIn("Persistence [API] [vs:api] [x]\r\n",
                          raw.decode("utf-8"))

        def test_bom_prefixed_plan_still_marks(self):
            self.plan.write_bytes(b"\xef\xbb\xbf" + PLAN.encode("utf-8"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS")

        # ---- refusals ----

        def test_already_complete_is_refused(self):
            r = build_report(self._args(milestone="Milestone 1"))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["problems"][0]["problem"], "already_complete")
            self.assertFalse(r["marked"])

        def test_unknown_milestone_is_refused(self):
            r = build_report(self._args(milestone="Milestone 42"))
            self.assertEqual(r["problems"][0]["problem"], "milestone_not_found")

        def test_ambiguous_milestone_is_refused(self):
            self.plan.write_text(
                "## Milestone 2 — Persistence [API] [vs:api]\n\n"
                "## Milestone 2 — Persistence (continued) [API] [vs:api]\n",
                encoding="utf-8")
            r = build_report(self._args())
            self.assertEqual(r["problems"][0]["problem"], "ambiguous_milestone")
            self.assertNotIn("[x]", self.plan.read_text(encoding="utf-8"))

        def test_word_boundary_m1_does_not_match_m10(self):
            self.plan.write_text(
                "## Milestone 1 — Setup [API] [vs:api]\n\n"
                "## Milestone 10 — Reporting [API] [vs:api]\n",
                encoding="utf-8")
            r = build_report(self._args(milestone="Milestone 1"))
            self.assertEqual(r["result"], "PASS")
            text = self.plan.read_text(encoding="utf-8")
            self.assertIn("Setup [API] [vs:api] [x]", text)
            self.assertNotIn("Reporting [API] [vs:api] [x]", text)

        def test_plan_without_milestone_headings_is_structural(self):
            self.plan.write_text("# Plan\n\n## Task 1: t\n", encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(self._args())

        def test_missing_plan_is_structural(self):
            with self.assertRaises(GateError):
                build_report(self._args(plan=str(self.dir / "absent.md")))

        # ---- --require-commit ----

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_require_commit_refuses_without_a_commit(self):
            self._init_repo()
            git(["commit", "-m", "unrelated work"], str(self.dir))
            r = build_report(self._args(require_commit=True))
            self.assertEqual(r["result"], "FAIL")
            self.assertFalse(r["commit_found"])
            self.assertEqual(r["problems"][0]["problem"], "no_commit")
            self.assertNotIn("Persistence [API] [vs:api] [x]",
                             self.plan.read_text(encoding="utf-8"))

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_require_commit_passes_with_a_naming_commit(self):
            self._init_repo()
            git(["commit", "-m", "Milestone 2 — Persistence: add DB layer"],
                str(self.dir))
            r = build_report(self._args(require_commit=True))
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(r["commit_found"])

        @unittest.skipUnless(shutil.which("git"), "git not on PATH")
        def test_require_commit_on_a_repoless_dir_is_structural(self):
            with self.assertRaises(GateError):
                build_report(self._args(require_commit=True))

        # ---- --require-gates ----

        def test_require_gates_passes_on_a_backed_milestone(self):
            self._write_ledger()
            r = build_report(self._args(
                ledger=str(self.ledger),
                require_gates=["check_commit_gate.py"]))
            self.assertEqual(r["result"], "PASS")

        def test_require_gates_refuses_a_missing_entry(self):
            self._write_ledger(milestone="Milestone 9")
            r = build_report(self._args(
                ledger=str(self.ledger),
                require_gates=["check_commit_gate.py"]))
            self.assertEqual(r["problems"][0]["problem"], "ledger_missing")
            self.assertFalse(r["marked"])

        def test_require_gates_refuses_a_failed_latest_entry(self):
            self._write_ledger()
            self._write_ledger(verdict="FAIL", exit=1)   # latest wins
            r = build_report(self._args(
                ledger=str(self.ledger),
                require_gates=["check_commit_gate.py"]))
            self.assertEqual(r["problems"][0]["problem"], "ledger_failed")

        def test_require_gates_defaults_to_the_commit_gate(self):
            self._write_ledger()
            rc = main(["--plan", str(self.plan), "--milestone", "Milestone 2",
                       "--ledger", str(self.ledger), "--require-gates", ""])
            self.assertEqual(rc, 0)

        def test_require_gates_without_ledger_is_usage_error(self):
            self.assertEqual(main([
                "--plan", str(self.plan), "--milestone", "Milestone 2",
                "--require-gates", "check_commit_gate.py"]), 2)

        def test_parse_gate_names_splits_a_comma_list(self):
            self.assertEqual(parse_gate_names(["a.py,b.py", "c.py"]),
                             ["a.py", "b.py", "c.py"])

        # ---- the shared gate ledger ----

        def test_ledger_records_every_exit_path(self):
            ledger = self.dir / "logs" / "gates.jsonl"
            base = ["--plan", str(self.plan), "--ledger", str(ledger)]
            self.assertEqual(main(base + ["--milestone", "Milestone 2"]), 0)
            self.assertEqual(main(base + ["--milestone", "Milestone 2"]), 1)
            self.assertEqual(main(base), 2)
            records = self._ledger_records(ledger)
            self.assertEqual([r["verdict"] for r in records],
                             ["PASS", "FAIL", "ERROR"])
            self.assertEqual([r["exit"] for r in records], [0, 1, 2])
            self.assertTrue(all(r["gate"] == "mark_milestone.py"
                                for r in records))
            self.assertEqual(records[0]["milestone"], "Milestone 2")
            self.assertEqual(records[1]["inputs"][str(self.plan)],
                             sha256_file(self.plan))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(MarkMilestoneTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
