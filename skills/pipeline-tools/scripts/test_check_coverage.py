"""Unit and CLI tests for check_coverage.py.

Run directly: python test_check_coverage.py
Or via the CLI: python check_coverage.py --self-test
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_coverage as cc  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"
SCRIPT = Path(__file__).parent / "check_coverage.py"


def run_cli(*args):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# (a) Unit tests against the module's parse functions
# ---------------------------------------------------------------------------


class TestParseRequirementsTiers(unittest.TestCase):
    def test_assigns_must_should_could_tiers(self):
        text = (
            "### Must Have\n"
            "- [ ] **FR-1** do a thing\n"
            "### Should Have\n"
            "- [ ] **FR-2** do another thing\n"
            "### Could Have\n"
            "- [ ] **FR-3** maybe do a thing\n"
        )
        tier_by_id, warnings, known = cc.parse_requirements(text)
        self.assertEqual(tier_by_id["FR-1"], "Must")
        self.assertEqual(tier_by_id["FR-2"], "Should")
        self.assertEqual(tier_by_id["FR-3"], "Could")
        self.assertEqual(known, {"FR-1", "FR-2", "FR-3"})

    def test_tier_closes_at_same_or_higher_heading_level(self):
        text = (
            "### Must Have\n"
            "- [ ] **FR-1** covered here\n"
            "## Non-Functional Requirements\n"
            "- [ ] **FR-2** should not be Must\n"
        )
        tier_by_id, _warnings, _known = cc.parse_requirements(text)
        self.assertEqual(tier_by_id.get("FR-1"), "Must")
        self.assertNotIn("FR-2", tier_by_id)


class TestNfrFailSafeDefault(unittest.TestCase):
    def test_nfr_without_tier_tag_defaults_to_must_with_warning(self):
        text = "- **NFR-1** Untagged non-functional requirement.\n"
        tier_by_id, warnings, _known = cc.parse_requirements(text)
        self.assertEqual(tier_by_id["NFR-1"], "Must")
        self.assertTrue(any("NFR-1" in w for w in warnings))

    def test_nfr_with_tier_tag_uses_tag_no_warning(self):
        text = "- **NFR-1** (Should) Tagged non-functional requirement.\n"
        tier_by_id, warnings, _known = cc.parse_requirements(text)
        self.assertEqual(tier_by_id["NFR-1"], "Should")
        self.assertEqual(warnings, [])


class TestDuplicateHandling(unittest.TestCase):
    def test_duplicate_id_across_tiers_first_occurrence_wins(self):
        text = (
            "### Must Have\n"
            "- [ ] **FR-1** first seen here\n"
            "### Should Have\n"
            "- [ ] **FR-1** re-declared here\n"
        )
        tier_by_id, warnings, _known = cc.parse_requirements(text)
        self.assertEqual(tier_by_id["FR-1"], "Must")
        self.assertTrue(any("FR-1" in w for w in warnings))


class TestWontHaveExclusion(unittest.TestCase):
    def test_id_only_in_wont_have_is_excluded(self):
        text = "### Won't Have (this version)\n- [ ] **FR-1** dropped feature\n"
        tier_by_id, _warnings, known = cc.parse_requirements(text)
        self.assertNotIn("FR-1", tier_by_id)
        # Still tracked as a "known" id so cross-referencing plan citations
        # against it doesn't spuriously look unknown.
        self.assertIn("FR-1", known)

    def test_id_in_wont_and_another_tier_uses_other_tier_with_warning(self):
        text = (
            "### Must Have\n"
            "- [ ] **FR-1** kept feature\n"
            "### Won't Have (this version)\n"
            "- [ ] **FR-1** duplicate mention\n"
        )
        tier_by_id, warnings, _known = cc.parse_requirements(text)
        self.assertEqual(tier_by_id["FR-1"], "Must")
        self.assertTrue(any("FR-1" in w and "Won't" in w for w in warnings))


class TestLatestWins(unittest.TestCase):
    def test_last_status_bearing_mention_determines_status(self):
        text = "- FR-1: FAIL — first run\n- FR-1: PASS — retest\n"
        status_by_id, warnings = cc.parse_test_report(text)
        self.assertEqual(status_by_id["FR-1"], "PASS")
        self.assertEqual(warnings, [])

    def test_last_status_bearing_mention_can_flip_to_fail(self):
        text = "- FR-1: PASS — first run\n- FR-1: FAIL — regression\n"
        status_by_id, _warnings = cc.parse_test_report(text)
        self.assertEqual(status_by_id["FR-1"], "FAIL")

    def test_line_with_both_markers_counts_as_fail(self):
        text = "- FR-1: PASS then FAIL on rerun\n"
        status_by_id, _warnings = cc.parse_test_report(text)
        self.assertEqual(status_by_id["FR-1"], "FAIL")

    def test_status_less_mention_only_warns_and_is_not_covered(self):
        text = "- FR-1: see ticket ABC-1 for manual verification\n"
        status_by_id, warnings = cc.parse_test_report(text)
        self.assertNotIn("FR-1", status_by_id)
        self.assertTrue(any("FR-1" in w for w in warnings))


# ---------------------------------------------------------------------------
# (b) CLI tests against fixture pairs
# ---------------------------------------------------------------------------


class TestCliHappyFixture(unittest.TestCase):
    def test_plan_mode_passes(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "happy" / "requirements.md"),
            "--plan", str(FIXTURES / "happy" / "plan.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["result"], "PASS")
        self.assertEqual(data["uncovered"], [])
        self.assertIn("NFR-2", data["uncovered_should"])

    def test_test_report_mode_passes(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "happy" / "requirements.md"),
            "--test-report", str(FIXTURES / "happy" / "test-report.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["result"], "PASS")
        self.assertEqual(data["uncovered"], [])


class TestCliUncoveredFixture(unittest.TestCase):
    def test_plan_mode_fails_with_expected_gaps(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "uncovered" / "requirements.md"),
            "--plan", str(FIXTURES / "uncovered" / "plan.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["result"], "FAIL")
        self.assertEqual(data["uncovered"], ["FR-3", "NFR-1"])
        self.assertTrue(any("Task 3" in w for w in data["warnings"]))
        self.assertTrue(any("FR-9" in w for w in data["warnings"]))

    def test_test_report_mode_fails_with_expected_gaps(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "uncovered" / "requirements.md"),
            "--test-report", str(FIXTURES / "uncovered" / "test-report.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["result"], "FAIL")
        self.assertEqual(data["uncovered"], ["FR-2", "FR-3", "NFR-1"])
        self.assertTrue(any("NFR-1" in w for w in data["warnings"]))


class TestCliMalformedFixture(unittest.TestCase):
    def test_malformed_requirements_exits_2(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "malformed" / "requirements.md"),
            "--plan", str(FIXTURES / "happy" / "plan.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(data["result"], "ERROR")
        self.assertIsNotNone(data["error"])

    def test_malformed_plan_exits_2(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "happy" / "requirements.md"),
            "--plan", str(FIXTURES / "malformed" / "plan.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(data["result"], "ERROR")
        self.assertIsNotNone(data["error"])


class TestCliUsageErrors(unittest.TestCase):
    def test_both_plan_and_test_report_exits_2(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "happy" / "requirements.md"),
            "--plan", str(FIXTURES / "happy" / "plan.md"),
            "--test-report", str(FIXTURES / "happy" / "test-report.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(data["result"], "ERROR")

    def test_neither_plan_nor_test_report_exits_2(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "happy" / "requirements.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(data["result"], "ERROR")

    def test_missing_requirements_file_exits_2_with_valid_json(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "happy" / "does-not-exist.md"),
            "--plan", str(FIXTURES / "happy" / "plan.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(data["result"], "ERROR")
        self.assertIsNotNone(data["error"])


if __name__ == "__main__":
    unittest.main()
