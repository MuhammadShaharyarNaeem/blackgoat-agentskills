"""Status-token regression tests for check_coverage.py (bug coverage-fail-filename).

A ledger line's status token is a standalone word, inside backticks or not;
the same letters inside a cited name (`m3-exit-fail.md`, `test_fail_path.py`)
are part of the name, not a status.

Run directly: python test_check_coverage_status_tokens.py
Or via the CLI: python check_coverage.py --self-test
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_coverage as cc  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"
SCRIPT = Path(__file__).parent / "check_coverage.py"
HAPPY_NFR1_LINE = ("- NFR-1: PASS — `pytest tests/auth` — exit 0 — "
                   "tests/auth/test_login.py::test_login_performance (180ms)")


def status_of(line, req_id="FR-1"):
    status_by_id, _warnings = cc.parse_test_report(line)
    return status_by_id.get(req_id)


class ReproCasesTests(unittest.TestCase):
    """The three cases of .docs/bugfix/coverage-fail-filename/repro.py."""

    def test_pass_citing_backticked_fail_filename_is_pass(self):
        self.assertEqual(status_of(
            "- FR-1: PASS — `pytest tests/auth` — exit 0 — expected-failure leg "
            "captured at `.docs/demo/evidence/runtime/m3-exit-fail.md`"), "PASS")

    def test_pass_citing_bare_fail_filename_is_pass(self):
        self.assertEqual(status_of(
            "- FR-1: PASS — `pytest tests/auth` — exit 0 — expected-failure leg "
            "captured at .docs/demo/evidence/runtime/m3-exit-fail.md"), "PASS")

    def test_real_fail_citing_pass_filename_stays_fail(self):
        self.assertEqual(status_of(
            "- FR-1: FAIL — timed out; see .docs/demo/evidence/runtime/m3-exit-pass.md"),
            "FAIL")


class JoinedNameTests(unittest.TestCase):
    """`fail` joined to a name by -, _, / or \\ is part of the name."""

    NAMES = [
        "tests/test_fail_path.py",
        "logs/fail/run.log",
        "logs\\fail\\run.log",
        "fail_cases.txt",
        "out/run-FAILED",
    ]

    def test_bare_joined_names_do_not_fail_a_pass_line(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                self.assertEqual(status_of(f"- FR-1: PASS — exit 0 — see {name}"), "PASS")

    def test_backticked_joined_names_do_not_fail_a_pass_line(self):
        for name in self.NAMES:
            with self.subTest(name=name):
                self.assertEqual(status_of(f"- FR-1: PASS — exit 0 — see `{name}`"), "PASS")

    def test_token_followed_by_dot_word_is_a_name(self):
        self.assertEqual(status_of("- FR-1: PASS — exit 0 — see fail.md"), "PASS")

    def test_code_span_with_a_standalone_fail_word_fails_a_pass_line(self):
        self.assertEqual(status_of(
            "- FR-1: PASS — `grep -c FAIL out.log` returned 0 — exit 0"), "FAIL")


class RealFailStillFailsTests(unittest.TestCase):
    """The fix must never hide a real FAIL."""

    def test_status_fail_with_sentence_period(self):
        self.assertEqual(status_of("- FR-1: status: FAIL."), "FAIL")

    def test_fail_dash_reason(self):
        self.assertEqual(status_of("- FR-1: FAIL — timed out"), "FAIL")

    def test_failed_lowercase(self):
        self.assertEqual(status_of("- FR-1: failed, exit 1"), "FAIL")

    def test_bold_fail(self):
        self.assertEqual(status_of("- FR-1: **FAIL** — exit 1"), "FAIL")

    def test_fail_beside_pass_still_wins(self):
        self.assertEqual(status_of("- FR-1: PASS then FAIL on rerun — exit 1"), "FAIL")

    def test_backticked_test_summary_failure_is_fail(self):
        self.assertEqual(status_of(
            "- FR-1: PASS — `pytest tests/auth` — exit 0 — `1 failed, 3 passed in 2.1s`"),
            "FAIL")

    def test_backticked_runner_output_failure_is_fail(self):
        self.assertEqual(status_of(
            "- FR-1: PASS — `npm test` → `Tests: 1 failed, 4 passed` — exit 0"), "FAIL")

    def test_backticked_blocked_status_is_blocked(self):
        self.assertEqual(status_of(
            "- FR-1: PASS — exit 0 — `status: BLOCKED (no db)`"), "BLOCKED")

    def test_status_only_code_span_is_still_read(self):
        self.assertEqual(status_of("- FR-1: `FAIL` — exit 1"), "FAIL")
        self.assertEqual(status_of("- FR-1: `PASS` — exit 0"), "PASS")

    def test_emoji_tokens_unchanged(self):
        self.assertEqual(status_of("- FR-1: ❌ — exit 1"), "FAIL")
        self.assertEqual(status_of("- FR-1: ✅ — exit 0 — see m3-exit-fail.md"), "PASS")


class PassInsideNameDoesNotUpgradeTests(unittest.TestCase):

    def test_pass_inside_name_on_fail_line_stays_fail(self):
        self.assertEqual(status_of("- FR-1: FAIL — see `m3-exit-pass.md` exit 1"), "FAIL")

    def test_pass_inside_name_alone_is_no_status(self):
        status_by_id, warnings = cc.parse_test_report(
            "- FR-1: see m3-exit-pass.md and test_pass_path.py — exit 0")
        self.assertNotIn("FR-1", status_by_id)
        self.assertTrue(any("FR-1" in w and "without a status" in w for w in warnings))


class BlockedTokenTests(unittest.TestCase):

    def test_blocked_inside_name_does_not_downgrade_a_pass(self):
        self.assertEqual(status_of(
            "- FR-1: PASS — exit 0 — see `.docs/x/blocked-env.md` and logs/blocked_run.log"),
            "PASS")

    def test_real_blocked_citing_pass_name_stays_blocked(self):
        self.assertEqual(status_of("- FR-1: BLOCKED — see m3-exit-pass.md"), "BLOCKED")

    def test_blocked_with_sentence_period(self):
        self.assertEqual(status_of("- FR-1: BLOCKED."), "BLOCKED")

    def test_blocked_inside_name_alone_is_no_status(self):
        status_by_id, _warnings = cc.parse_test_report(
            "- FR-1: see env-blocked.md — exit 0")
        self.assertNotIn("FR-1", status_by_id)


class CitationStillSeesCodeSpansTests(unittest.TestCase):
    """Backticked citations still count as evidence."""

    def test_backticked_exit_code_is_evidence(self):
        self.assertEqual(cc.citation_status("- FR-1: PASS — `exit 0`"), (True, None))

    def test_backticked_runtime_capture_is_evidence(self):
        self.assertEqual(status_of(
            "- FR-1: PASS — see `.docs/demo/evidence/runtime/m3-exit-fail.md`"), "PASS")

    def test_backticked_test_ref_resolves(self):
        with tempfile.TemporaryDirectory() as repo:
            (Path(repo) / "tests").mkdir()
            (Path(repo) / "tests" / "test_fail_path.py").write_text(
                "def test_rejects_bad_token():\n    pass\n", encoding="utf-8")
            line = "- FR-1: PASS — `tests/test_fail_path.py::test_rejects_bad_token`"
            self.assertEqual(cc.citation_status(line, repo, strict_evidence=True), (True, None))
            status_by_id, _ = cc.parse_test_report(line, repo, strict_evidence=True)
            self.assertEqual(status_by_id.get("FR-1"), "PASS")


class CliReproTests(unittest.TestCase):
    """End to end through the CLI on the happy fixture, as repro.py does."""

    def run_with_nfr1(self, line):
        base = (FIXTURES / "happy" / "test-report.md").read_text(encoding="utf-8")
        self.assertIn(HAPPY_NFR1_LINE, base)
        with tempfile.TemporaryDirectory() as work:
            report = Path(work) / "test-report.md"
            report.write_text(base.replace(HAPPY_NFR1_LINE, line), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(SCRIPT),
                 "--requirements", str(FIXTURES / "happy" / "requirements.md"),
                 "--test-report", str(report)],
                capture_output=True, text=True).returncode

    def test_pass_citing_fail_filename_is_covered(self):
        self.assertEqual(self.run_with_nfr1(
            "- NFR-1: PASS — `pytest tests/auth` — exit 0 — expected-failure leg "
            "captured at `.docs/demo/evidence/runtime/m3-exit-fail.md`"), 0)

    def test_real_fail_citing_pass_filename_is_uncovered(self):
        self.assertEqual(self.run_with_nfr1(
            "- NFR-1: FAIL — timed out; see .docs/demo/evidence/runtime/m3-exit-pass.md"), 1)


if __name__ == "__main__":
    unittest.main()
