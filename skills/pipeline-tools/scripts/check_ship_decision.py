#!/usr/bin/env python3
"""Mechanical GO/NO-GO gate for ship-decision.md.

Makes Dep's shipping verdict machine-verifiable the same way
check_agent_report.py gates Vera/Cipher: one unambiguous labeled
GO or NO-GO, plus a Rollback heading and a post-deploy checklist.
Matches the dep-ship-decision-shape eval contract.

Usage:
    python check_ship_decision.py --report <path> [--require-go]
    python check_ship_decision.py --self-test
"""
import argparse
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

VERDICT_LINE_RE = re.compile(
    r"(?im)^[#>\s\-\*]*(?:Ship\s+Decision|Verdict|Recommendation)\b[^\r\n]*?\b(NO[-\s]?GO|GO)\b"
)
ROLLBACK_HEADING_RE = re.compile(r"(?im)^#{1,6}\s*.*\brollback\b")
CHECKLIST_HEADING_RE = re.compile(r"(?im)^#{1,6}\s*.*\bchecklist\b")
CHECKBOX_RE = re.compile(r"(?m)^\s*[-*]\s*\[[ xX]\]")


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_text(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    text = p.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise GateError(f"file is empty: {path}")
    return text


def normalize_verdict(token):
    return re.sub(r"\s+", "-", token.upper())


def parse_verdicts(text):
    return [normalize_verdict(m.group(1)) for m in VERDICT_LINE_RE.finditer(text)]


def build_report(path, require_go):
    text = read_text(path)
    verdicts = parse_verdicts(text)
    distinct = sorted(set(verdicts))
    has_rollback = bool(ROLLBACK_HEADING_RE.search(text))
    checkbox_count = len(CHECKBOX_RE.findall(text))
    has_checklist = bool(CHECKLIST_HEADING_RE.search(text)) or checkbox_count >= 3

    failures = []
    if not verdicts:
        failures.append("no labeled GO/NO-GO verdict line found")
    elif len(distinct) > 1:
        failures.append(f"ambiguous verdict - both {' and '.join(distinct)} present")

    verdict = distinct[0] if len(distinct) == 1 else None
    if require_go and verdict == "NO-GO":
        failures.append("require-go: latest unambiguous verdict is NO-GO")
    if require_go and verdict is None and verdicts:
        failures.append("require-go: no unambiguous GO verdict")
    if not has_rollback:
        failures.append("no Rollback section heading found")
    if not has_checklist:
        failures.append(
            f"no checklist heading and fewer than 3 checkbox items (found {checkbox_count})"
        )

    return {
        "report_file": path,
        "pass": len(failures) == 0,
        "verdict": verdict,
        "require_go": require_go,
        "has_rollback": has_rollback,
        "has_checklist": has_checklist,
        "checkbox_count": checkbox_count,
        "failures": failures,
        "error": None,
    }


def main(argv):
    parser = argparse.ArgumentParser(prog="check_ship_decision.py")
    parser.add_argument("--report")
    parser.add_argument(
        "--require-go",
        action="store_true",
        help="fail unless the unambiguous verdict is GO",
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.report:
        print(json.dumps({"pass": False, "error": "missing required argument: --report"}))
        return 2

    try:
        report = build_report(args.report, args.require_go)
    except GateError as exc:
        print(json.dumps({"pass": False, "error": str(exc)}))
        return 2

    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


def run_self_test():
    import shutil

    HAPPY = """# Ship Decision

## Rollback Strategy
Revert the feature flag.

## Launch Checklist
- [ ] Health endpoint 200
- [ ] Auth flow works
- [ ] Logs shipping

Ship Decision: GO
"""

    NO_GO = """# Ship Decision

## Rollback Strategy
Revert.

## Post-deploy Checklist
- [ ] a
- [ ] b
- [ ] c

**Verdict:** NO-GO
"""

    AMBIGUOUS = """# Ship Decision

## Rollback Strategy
x

## Checklist
- [ ] a
- [ ] b
- [ ] c

Ship Decision: GO
Recommendation: NO-GO
"""

    class ShipDecisionTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.path = self.dir / "ship-decision.md"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def test_happy_go_passes(self):
            self.path.write_text(HAPPY, encoding="utf-8")
            report = build_report(str(self.path), require_go=True)
            self.assertTrue(report["pass"])
            self.assertEqual(report["verdict"], "GO")

        def test_no_go_passes_without_require_go(self):
            self.path.write_text(NO_GO, encoding="utf-8")
            report = build_report(str(self.path), require_go=False)
            self.assertTrue(report["pass"])
            self.assertEqual(report["verdict"], "NO-GO")

        def test_no_go_fails_require_go(self):
            self.path.write_text(NO_GO, encoding="utf-8")
            report = build_report(str(self.path), require_go=True)
            self.assertFalse(report["pass"])

        def test_ambiguous_fails(self):
            self.path.write_text(AMBIGUOUS, encoding="utf-8")
            report = build_report(str(self.path), require_go=False)
            self.assertFalse(report["pass"])
            self.assertTrue(any("ambiguous" in f for f in report["failures"]))

        def test_missing_rollback_fails(self):
            self.path.write_text(
                "## Checklist\n- [ ] a\n- [ ] b\n- [ ] c\n\nShip Decision: GO\n",
                encoding="utf-8",
            )
            report = build_report(str(self.path), require_go=True)
            self.assertFalse(report["pass"])
            self.assertTrue(any("Rollback" in f for f in report["failures"]))

        def test_empty_file_raises(self):
            self.path.write_text("   \n", encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(str(self.path), require_go=False)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ShipDecisionTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
