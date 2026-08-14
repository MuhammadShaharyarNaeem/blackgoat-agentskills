#!/usr/bin/env python3
"""Deterministic agent-report gate for the PDD pipelines.

Verifies that a durable agent report (Cipher's security-report.md, Vera's
verification-report.md) actually backs its verdict: the report exists and
is non-empty, its latest verdict-bearing section carries a machine-readable
`**Verdict:** Pass`, every check line cites executed-command evidence (an
exit code) or an explicit NOT RUN / BLOCKED reason, and no Critical finding
stands. Fail-closed: a verdict the evidence does not support never passes.

Usage:
    python check_agent_report.py --report <path>
    python check_agent_report.py --self-test

Pure standard library. See ../SKILL.md for the full contract (JSON shape,
exit codes, parsing rules).
"""
import argparse
import json
import re
import sys
from pathlib import Path

SECTION_HEADING_RE = re.compile(r"^##\s+(.*)$")
VERDICT_LINE_RE = re.compile(r"^\s*\*\*Verdict:\*\*(.*)$")
VERDICT_TOKEN_RE = re.compile(r"^\s*(Pass|Fail)\s*$")
CHECK_LINE_RE = re.compile(
    r"^\s*-\s*(?P<name>[^:]+?):\s*(?P<status>PASS|FAIL|BLOCKED|NOT RUN)\b(?P<rest>.*)$")
CRITICAL_FINDING_RE = re.compile(r"^\s*-\s*\*\*Critical\*\*")
EXIT_CODE_RE = re.compile(r"\bexit(?:\s+code)?\s+-?\d+\b", re.IGNORECASE)


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_text(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding="utf-8", errors="replace")


def parse_sections(text):
    """Return every level-2 ('## ') section as (title, [body lines]).

    Text before the first level-2 heading (a document title, preamble) belongs
    to no section and is never gated.
    """
    sections = []
    current = None
    for line in text.splitlines():
        m = SECTION_HEADING_RE.match(line)
        if m:
            current = (m.group(1).strip(), [])
            sections.append(current)
        elif current is not None:
            current[1].append(line)
    return sections


def find_gated_section(text):
    """Return (title, body) of the LAST section containing a Verdict line.

    Each audit/verification round appends a fresh section, so the last
    verdict-bearing section is the current round — the same last-matching-
    section rule check_commit_gate.py uses for review sections.
    """
    gated = None
    for title, body in parse_sections(text):
        if any(VERDICT_LINE_RE.match(l) for l in body):
            gated = (title, body)
    return gated


def parse_checks(body):
    """Return the section's check lines, deduplicated by name (latest wins).

    A check line is `- <name>: <STATUS> <rest>` where <name> contains no
    colon and <STATUS> is exactly PASS, FAIL, BLOCKED, or NOT RUN (uppercase)
    immediately after the first colon. Anything else is prose and ignored.
    Latest mention per name wins, mirroring the coverage-ledger convention.
    """
    checks = {}
    order = []
    for line in body:
        m = CHECK_LINE_RE.match(line)
        if not m:
            continue
        name = m.group("name").strip().strip("*").strip()
        key = name.lower()
        if key not in checks:
            order.append(key)
        checks[key] = (name, m.group("status"), m.group("rest"))
    return [checks[k] for k in order]


def build_report(args):
    report = {
        "report": args.report,
        "section": None,
        "verdict": None,
        "checks": 0,
        "passed": 0,
        "failed": [],
        "blocked": [],
        "not_run": [],
        "unevidenced": [],
        "critical_findings": 0,
        "warnings": [],
        "result": "FAIL",
        "error": None,
    }
    text = read_text(args.report)
    if not text.strip():
        raise GateError(f"report file is empty: {args.report}")

    gated = find_gated_section(text)
    if gated is None:
        raise GateError("no '## ' section containing a '**Verdict:**' line "
                        "found — not a conforming agent report")
    title, body = gated
    report["section"] = title

    verdict_values = [m.group(1) for m in
                      (VERDICT_LINE_RE.match(l) for l in body) if m]
    token = VERDICT_TOKEN_RE.match(verdict_values[-1])
    if not token:
        # Latest expression of intent is unreadable — fail-safe: no verdict.
        report["warnings"].append(
            f"section '{title}': latest Verdict line is not a machine-"
            f"readable token (got: {verdict_values[-1].strip()!r}); "
            "required: 'Pass' or 'Fail' exactly")
    else:
        report["verdict"] = token.group(1)

    for name, status, rest in parse_checks(body):
        if status == "PASS":
            report["passed"] += 1
        elif status == "FAIL":
            report["failed"].append(name)
        elif status == "BLOCKED":
            report["blocked"].append(name)
        else:  # NOT RUN
            report["not_run"].append(name)
        if status in ("PASS", "FAIL"):
            # An executed check cites the command's exit code — the terse
            # proof an execution happened. No exit code = unevidenced.
            if not EXIT_CODE_RE.search(rest):
                report["unevidenced"].append(name)
        elif not re.search(r"\w", rest):
            # An unexecuted check carries its reason. No reason = unevidenced.
            report["unevidenced"].append(name)
    report["checks"] = (report["passed"] + len(report["failed"])
                        + len(report["blocked"]) + len(report["not_run"]))

    report["critical_findings"] = sum(
        1 for line in body if CRITICAL_FINDING_RE.match(line))

    if report["checks"] == 0:
        report["warnings"].append(
            "no check lines found in the gated section — a report that "
            "proves nothing cannot pass")
    if report["unevidenced"]:
        report["warnings"].append(
            "check line(s) without an exit code (executed checks) or a "
            "reason (NOT RUN/BLOCKED): " + ", ".join(report["unevidenced"]))
    non_green = report["failed"] + report["blocked"] + report["not_run"]
    if report["verdict"] == "Pass" and non_green:
        report["warnings"].append(
            "verdict 'Pass' contradicts non-passing check line(s) — the "
            "verdict is arithmetic over the lines above it: "
            + ", ".join(non_green))
    if report["verdict"] == "Pass" and report["critical_findings"]:
        report["warnings"].append(
            f"verdict 'Pass' stands over {report['critical_findings']} "
            "Critical finding(s) — 'Pass' is unavailable while a Critical "
            "finding stands")

    gate_ok = (report["verdict"] == "Pass"
               and report["checks"] > 0
               and not non_green
               and not report["unevidenced"]
               and report["critical_findings"] == 0)
    report["result"] = "PASS" if gate_ok else "FAIL"
    return report


def main(argv):
    parser = argparse.ArgumentParser(prog="check_agent_report.py")
    parser.add_argument("--report")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.report:
        print(json.dumps({"result": "ERROR",
                          "error": "missing required argument: --report"}))
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
    import shutil
    import tempfile
    import unittest

    HAPPY = (
        "# Security Report\n\n"
        "## Security Audit: Shipping — 2026-08-11\n\n"
        "- Dependency audit: PASS — `npm audit --audit-level=high` — exit 0 — 0 high, 0 critical\n"
        "- Secrets scan: PASS — `git grep -nE \"(api_key|secret)\"` — exit 1 — 0 matches\n\n"
        "**Verdict:** Pass\n")
    FAIL_VERDICT = (
        "## Security Audit: Shipping\n\n"
        "- Dependency audit: FAIL — `npm audit` — exit 1 — 2 high, 5 moderate\n\n"
        "**Verdict:** Fail\n")

    class GateTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.path = self.dir / "security-report.md"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _run(self, text):
            self.path.write_text(text, encoding="utf-8")
            return build_report(argparse.Namespace(report=str(self.path)))

        def test_happy_path_passes(self):
            r = self._run(HAPPY)
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(r["verdict"], "Pass")
            self.assertEqual(r["checks"], 2)
            self.assertEqual(r["passed"], 2)

        def test_fail_verdict_fails(self):
            r = self._run(FAIL_VERDICT)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["verdict"], "Fail")
            self.assertEqual(r["failed"], ["Dependency audit"])

        def test_pass_verdict_over_critical_finding_fails(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 matches\n\n"
                "- **Critical** — hardcoded JWT secret — src/auth/token.js:14\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["critical_findings"], 1)

        def test_pass_verdict_over_failing_check_fails(self):
            r = self._run(
                "## Verification: Shipping\n\n"
                "- All tests pass: FAIL — `npm test` — exit 1 — 2 failed, 40 passed\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["failed"], ["All tests pass"])

        def test_not_run_check_blocks_pass(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 matches\n"
                "- Rate limiting: NOT RUN — no staging environment reachable\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["not_run"], ["Rate limiting"])
            self.assertNotIn("Rate limiting", r["unevidenced"])

        def test_blocked_check_blocks_pass(self):
            r = self._run(
                "## Verification: Shipping\n\n"
                "- Accessibility scan: BLOCKED — axe-core not installed and no network\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["blocked"], ["Accessibility scan"])

        def test_executed_check_without_exit_code_is_unevidenced(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — repo looked clean\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["unevidenced"], ["Secrets scan"])

        def test_not_run_without_reason_is_unevidenced(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 matches\n"
                "- Rate limiting: NOT RUN\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["unevidenced"], ["Rate limiting"])

        def test_zero_check_lines_fails(self):
            r = self._run("## Security Audit: Shipping\n\nAll clear.\n\n"
                          "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["checks"], 0)

        def test_last_verdict_bearing_section_wins(self):
            r = self._run(FAIL_VERDICT + "\n" + HAPPY[HAPPY.index("## "):])
            self.assertEqual(r["result"], "PASS")
            self.assertIn("2026-08-11", r["section"])

        def test_nonstandard_verdict_token_fails(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 matches\n\n"
                "**Verdict:** Secure\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertIsNone(r["verdict"])

        def test_latest_verdict_line_in_section_wins(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 matches\n\n"
                "**Verdict:** Pass\n"
                "**Verdict:** LGTM\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertIsNone(r["verdict"])

        def test_duplicate_check_name_latest_wins(self):
            r = self._run(
                "## Verification: Shipping\n\n"
                "- All tests pass: FAIL — `npm test` — exit 1 — 2 failed\n"
                "- All tests pass: PASS — `npm test` — exit 0 — 42 passed\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(r["checks"], 1)
            self.assertEqual(r["failed"], [])

        def test_lowercase_status_is_prose(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: pass — `git grep -n secret` — exit 1 — 0 matches\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")  # zero parseable checks
            self.assertEqual(r["checks"], 0)

        def test_missing_file_raises(self):
            with self.assertRaises(GateError):
                build_report(argparse.Namespace(
                    report=str(self.dir / "absent.md")))

        def test_empty_file_raises(self):
            self.path.write_text("  \n\n", encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(argparse.Namespace(report=str(self.path)))

        def test_no_verdict_section_raises(self):
            self.path.write_text("# Report\n\n## Notes\n\nprose only\n",
                                 encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(argparse.Namespace(report=str(self.path)))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(GateTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
