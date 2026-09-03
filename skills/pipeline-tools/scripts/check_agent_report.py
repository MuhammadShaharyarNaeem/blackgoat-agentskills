#!/usr/bin/env python3
"""Deterministic agent-report gate for the PDD pipelines.

Verifies that a durable agent report (Cipher's security-report.md, Vera's
verification-report.md) actually backs its verdict: the report exists and
is non-empty, its latest verdict-bearing section carries a machine-readable
`**Verdict:** Pass`, every check line cites executed-command evidence (an
exit code) or an explicit NOT RUN / BLOCKED reason, and no Critical finding
stands. Fail-closed: a verdict the evidence does not support never passes.

Usage:
    python check_agent_report.py --report <path> [--milestone "<title>"] \
        [--ledger <path>]
    python check_agent_report.py --self-test

Pure standard library. See ../SKILL.md for the full contract (JSON shape,
exit codes, parsing rules).
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SECTION_HEADING_RE = re.compile(r"^##\s+(.*)$")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
VERDICT_LINE_RE = re.compile(r"^\s*\*\*Verdict:\*\*(.*)$")
VERDICT_TOKEN_RE = re.compile(r"^\s*(Pass|Fail)\s*$")
CHECK_LINE_RE = re.compile(
    r"^\s*-\s*(?P<name>[^:]+?):\s*(?P<status>PASS|FAIL|BLOCKED|NOT RUN)\b(?P<rest>.*)$")
CRITICAL_FINDING_RE = re.compile(r"^\s*-\s*\*\*Critical\*\*")
EXIT_CODE_RE = re.compile(r"\bexit(?:\s+code)?\s+-?\d+\b", re.IGNORECASE)


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_text(path):
    """Read a UTF-8 artifact, tolerating a byte-order mark.

    `utf-8` (not `-sig`) glued a BOM to the first character, so a conforming
    report whose first line was a heading exited 2 ("not a conforming agent
    report") purely because of how its editor saved it.
    """
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding="utf-8-sig", errors="replace")


def strip_fenced_blocks(text):
    """Blank out every ```/~~~ fenced region, preserving the line count.

    A `**Verdict:** Pass` or a `- Secrets scan: PASS — exit 0` inside a fence
    is a TEMPLATE or a pasted transcript, not this round's claim — and because
    the last verdict line in the gated section wins, a pasted example silently
    became the verdict.

    Duplicated per file: this script family has no shared module by convention.
    """
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
    return "\n".join(out)


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


def append_ledger(ledger_path, argv, milestone, inputs, verdict, exit_code):
    """Append ONE JSON line recording this run. Best-effort by design.

    A ledger that cannot be written must never change this gate's verdict —
    the ledger is an audit trail for LATER gates (check_commit_gate.py's
    --require-ledger-gates), not a term in this one.
    """
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
    try:
        p = Path(ledger_path)
        if str(p.parent):
            p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


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
    raw = read_text(args.report)
    if not raw.strip():
        raise GateError(f"report file is empty: {args.report}")
    # Fences are stripped ONCE, here: section splitting, verdict lines, check
    # lines and Critical findings all then read a document with no example
    # blocks in it.
    text = strip_fenced_blocks(raw)

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


def build_parser():
    parser = argparse.ArgumentParser(prog="check_agent_report.py")
    parser.add_argument("--report")
    parser.add_argument("--milestone",
                        help="scope this run's ledger record to a milestone")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone,
                      [args.report] if args.report else [], verdict, code)
        return code

    if not args.report:
        print(json.dumps({"result": "ERROR",
                          "error": "missing required argument: --report"}))
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

        # ---- fences and encoding ----

        def test_fenced_pass_verdict_does_not_count(self):
            """A pasted TEMPLATE cannot become this round's verdict."""
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 matches\n\n"
                "**Verdict:** Fail\n\n"
                "Next round, use:\n\n"
                "```markdown\n**Verdict:** Pass\n```\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["verdict"], "Fail")

        def test_fenced_check_line_does_not_count(self):
            """A check line inside a transcript fence is not an executed check."""
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "Example of the format:\n\n"
                "~~~\n- Secrets scan: PASS — exit 0 — 0 matches\n~~~\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["checks"], 0)

        def test_fenced_critical_finding_does_not_count(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 matches\n\n"
                "```\n- **Critical** — example finding from the template\n```\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(r["critical_findings"], 0)

        def test_strip_fenced_blocks_preserves_line_count(self):
            text = "a\n```\nb\n```\nc\n"
            self.assertEqual(len(strip_fenced_blocks(text).split("\n")),
                             len(text.split("\n")))

        def test_bom_prefixed_report_still_passes(self):
            """utf-8 (not -sig) made a valid BOM-prefixed report exit 2."""
            self.path.write_bytes(b"\xef\xbb\xbf" + HAPPY.encode("utf-8"))
            r = build_report(argparse.Namespace(report=str(self.path)))
            self.assertEqual(r["result"], "PASS")

        # ---- the shared gate ledger ----

        def _ledger_records(self, path):
            return [json.loads(l) for l in
                    Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

        def test_ledger_records_a_pass_run(self):
            self.path.write_text(HAPPY, encoding="utf-8")
            ledger = self.dir / "logs" / "gates.jsonl"
            rc = main(["--report", str(self.path), "--milestone", "M3",
                       "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["gate"], "check_agent_report.py")
            self.assertEqual(rec["verdict"], "PASS")
            self.assertEqual(rec["exit"], 0)
            self.assertEqual(rec["milestone"], "M3")
            self.assertEqual(rec["inputs"][str(self.path)],
                             sha256_file(self.path))

        def test_ledger_records_fail_and_error_runs(self):
            ledger = self.dir / "gates.jsonl"
            self.path.write_text(FAIL_VERDICT, encoding="utf-8")
            self.assertEqual(main(["--report", str(self.path),
                                   "--ledger", str(ledger)]), 1)
            self.assertEqual(main(["--report", str(self.dir / "absent.md"),
                                   "--ledger", str(ledger)]), 2)
            self.assertEqual(main(["--ledger", str(ledger)]), 2)
            verdicts = [r["verdict"] for r in self._ledger_records(ledger)]
            self.assertEqual(verdicts, ["FAIL", "ERROR", "ERROR"])
            self.assertIsNone(self._ledger_records(ledger)[0]["milestone"])

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
