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


class TestSupersessionAnnotation(unittest.TestCase):
    def test_struck_through_id_keeps_its_tier_and_warns(self):
        text = (
            "### Must Have\n"
            "- [ ] **FR-1** kept as is\n"
            "- [ ] ~~**FR-2** emailed exports~~ — superseded by D-3\n"
        )
        tier_by_id, warnings, known = cc.parse_requirements(text)
        self.assertEqual(tier_by_id["FR-2"], "Must")
        self.assertIn("FR-2", known)
        self.assertTrue(any("FR-2" in w and "struck through" in w for w in warnings))

    def test_annotation_note_does_not_break_sibling_parsing(self):
        text = (
            "### Must Have\n"
            "- [ ] ~~**FR-1** dropped behaviour~~ (superseded by D-1)\n"
            "### Should Have\n"
            "- [ ] **FR-2** still wanted\n"
        )
        tier_by_id, _warnings, _known = cc.parse_requirements(text)
        self.assertEqual(tier_by_id["FR-1"], "Must")
        self.assertEqual(tier_by_id["FR-2"], "Should")


class TestLiteralCountLint(unittest.TestCase):
    def _lint(self, plan_text):
        return cc.lint_literal_counts(cc.split_task_blocks(plan_text))

    def test_inventory_counts_are_flagged(self):
        failures = self._lint(
            "## Task 1: API surface\n"
            "- The handler maps 7 error codes.\n"
            "- The router exposes 4 endpoints.\n"
        )
        self.assertEqual(len(failures), 2)
        self.assertTrue(all(f["check"] == "literal-count" for f in failures))
        self.assertTrue(all(f["task"] == "1" for f in failures))

    def test_units_and_thresholds_are_not_flagged(self):
        failures = self._lint(
            "## Task 1: Retries\n"
            "- Amounts round to 2 decimal places.\n"
            "- Retry up to 3 attempts, backing off 60 seconds.\n"
            "- Covers FR-3 endpoints already specified? no: see FR-3.\n"
        )
        self.assertEqual(failures, [])

    def test_repeated_phrase_reported_once_per_task(self):
        failures = self._lint(
            "## Task 1: Tables\n"
            "- Creates 3 tables.\n"
            "- Verifies 3 tables exist.\n"
        )
        self.assertEqual(len(failures), 1)


class TestBoundaryContractsLint(unittest.TestCase):
    def _lint(self, plan_text):
        return cc.lint_boundary_contracts(cc.split_task_blocks(plan_text))

    def test_consumed_identifier_provided_earlier_passes(self):
        failures = self._lint(
            "## Task 1: Schema\n**Boundary contracts:** provides: db.schema\n\n"
            "## Task 2: API\n**Boundary contracts:** consumes: db.schema; provides: api.routes\n"
        )
        self.assertEqual(failures, [])

    def test_consumed_identifier_provided_later_fails(self):
        failures = self._lint(
            "## Task 1: API\n**Boundary contracts:** consumes: db.schema\n\n"
            "## Task 2: Schema\n**Boundary contracts:** provides: db.schema\n"
        )
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["check"], "consumes-provides")
        self.assertEqual(failures[0]["task"], "1")
        self.assertIn("db.schema", failures[0]["detail"])

    def test_consumed_identifier_with_no_provider_fails(self):
        failures = self._lint(
            "## Task 1: API\n**Boundary contracts:** consumes: queue.topic\n"
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("no task provides it", failures[0]["detail"])

    def test_missing_field_is_not_a_failure(self):
        failures = self._lint("## Task 1: Styling\n\nPure styling, no contracts field.\n")
        self.assertEqual(failures, [])

    def test_comma_lists_and_multiline_field_are_parsed(self):
        failures = self._lint(
            "## Task 1: Foundations\n"
            "**Boundary contracts:**\n"
            "  provides: db.schema, `queue.topic`\n"
            "  consumes: none\n\n"
            "## Task 2: Worker\n"
            "**Boundary contracts:** consumes: db.schema, queue.topic\n"
        )
        self.assertEqual(failures, [])

    def test_identifier_matching_is_case_insensitive(self):
        failures = self._lint(
            "## Task 1: Schema\n**Boundary contracts:** provides: DB.Schema\n\n"
            "## Task 2: API\n**Boundary contracts:** consumes: db.schema\n"
        )
        self.assertEqual(failures, [])


class TestPathHygieneLint(unittest.TestCase):
    def _lint(self, plan_text):
        return cc.lint_path_hygiene(cc.split_task_blocks(plan_text))

    def test_windows_absolute_path_fails(self):
        failures = self._lint("## Task 1: Port logic\n\nSee `D:\\repos\\Other-Repo\\src\\a.ts`.\n")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["check"], "path-hygiene")
        self.assertIn("absolute path", failures[0]["detail"])

    def test_file_uri_fails_once(self):
        failures = self._lint("## Task 1: Notes\n\nSee `file:///D:/repos/Other/docs/x.md`.\n")
        self.assertEqual(len(failures), 1)
        self.assertIn("file:///", failures[0]["detail"])

    def test_repo_escaping_relative_path_fails(self):
        failures = self._lint("## Task 1: Reuse\n\nCopy `../Other-Repo/src/rollback.ts`.\n")
        self.assertEqual(len(failures), 1)
        self.assertIn("repo-escaping", failures[0]["detail"])

    def test_repo_relative_paths_and_routes_pass(self):
        failures = self._lint(
            "## Task 1: Import\n"
            "**Named identifiers:** `src/import/parser.ts`, `tests/import/parser.spec.ts`\n"
            "Implements the `/auth/login` route.\n"
        )
        self.assertEqual(failures, [])


class TestDesignRegisterParsing(unittest.TestCase):
    def test_numbered_heading_opens_section_and_subsections_are_included(self):
        text = (
            "## 17. Divergence & Supersession Register\n"
            "### 17.1 Divergences\n"
            "| # | Departs from |\n"
            "|---|---|\n"
            "| **DIV-01** | **FR-1** something |\n"
            "### 17.2 Supersessions\n"
            "| **SUP-01** | **NFR-2** something else |\n"
            "## 18. Risks\n"
            "| **X** | **FR-9** outside the register |\n"
        )
        rows, warnings = cc.parse_design_register(text)
        self.assertEqual(rows, [("DIV-01", ["FR-1"]), ("SUP-01", ["NFR-2"])])
        self.assertEqual(warnings, [])

    def test_missing_section_warns_and_yields_no_rows(self):
        rows, warnings = cc.parse_design_register("# Design\n\n## 4. Data Model\n")
        self.assertEqual(rows, [])
        self.assertTrue(any("no 'Divergence & Supersession Register'" in w for w in warnings))

    def test_separator_and_idless_rows_are_skipped(self):
        text = (
            "## Divergence & Supersession Register\n"
            "| # | Requirement |\n"
            "|:---|---:|\n"
            "| **DIV-01** | no ids in this row |\n"
        )
        rows, warnings = cc.parse_design_register(text)
        self.assertEqual(rows, [])
        self.assertTrue(any("no table row citing an FR/NFR id" in w for w in warnings))

    def test_subject_cells_are_read_and_justification_prose_is_not(self):
        text = (
            "## Divergence & Supersession Register\n"
            "| **SUP-01** | **FR-16**, **FR-24** | re-resolves FR-16 at the new price |\n"
            "| **DIV-04** | the error-envelope playbook | consumes the FR-1 retry budget |\n"
        )
        rows, _warnings = cc.parse_design_register(text)
        # FR-16 deduplicated; DIV-04 cites FR-1 only in justification prose.
        self.assertEqual(rows, [("SUP-01", ["FR-16", "FR-24"])])


class TestRequirementBlocks(unittest.TestCase):
    def test_block_runs_to_the_next_bold_id_line(self):
        text = (
            "### Must Have\n"
            "- [ ] **FR-1** first requirement\n"
            "  > **SUPERSEDED by SUP-01** — see design §17.2\n"
            "- [ ] **FR-2** second requirement\n"
            "  - Given a thing, Then another thing.\n"
        )
        blocks = cc.requirement_blocks(text)
        self.assertIn("SUPERSEDED by SUP-01", blocks["FR-1"])
        self.assertNotIn("SUPERSEDED", blocks["FR-2"])

    def test_repeated_declarations_are_concatenated(self):
        text = "- **NFR-1** first mention\n- **NFR-1** later mention ~~struck~~\n"
        blocks = cc.requirement_blocks(text)
        self.assertIn("~~struck~~", blocks["NFR-1"])


class TestSupersessionAnnotationLint(unittest.TestCase):
    REQUIREMENTS = (
        "### Must Have\n"
        "- [ ] **FR-1** plain requirement, no annotation\n"
        "- [ ] ~~**FR-2** struck requirement~~\n"
        "- [ ] **FR-3** annotated by note only\n"
        "  > superseded by SUP-02\n"
        "- [ ] **FR-4** annotated with a non-supersession verb\n"
        "  > **SCOPE PINNED by SUP-06** (design §17.2)\n"
    )

    def _lint(self, rows):
        return cc.lint_supersession_annotations(
            self.REQUIREMENTS, rows, {"FR-1", "FR-2", "FR-3", "FR-4"}
        )

    def test_strikethrough_annotation_satisfies_the_check(self):
        self.assertEqual(self._lint([("SUP-01", ["FR-2"])]), [])

    def test_superseded_by_note_satisfies_the_check(self):
        self.assertEqual(self._lint([("SUP-02", ["FR-3"])]), [])

    def test_row_id_citation_satisfies_the_check_without_a_supersession_verb(self):
        self.assertEqual(self._lint([("SUP-06", ["FR-4"])]), [])

    def test_annotation_citing_a_different_row_does_not_satisfy_the_check(self):
        failures = self._lint([("DIV-11", ["FR-4"])])
        self.assertEqual(len(failures), 1)
        self.assertIn("FR-4", failures[0]["detail"])

    def test_unannotated_citation_fails(self):
        failures = self._lint([("DIV-01", ["FR-1"])])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["check"], "supersession-annotation")
        self.assertEqual(failures[0]["task"], "DIV-01")
        self.assertIn("FR-1", failures[0]["detail"])

    def test_unknown_id_is_not_a_lint_failure(self):
        self.assertEqual(self._lint([("DIV-02", ["FR-9"])]), [])

    def test_same_row_and_id_reported_once(self):
        failures = self._lint([("DIV-01", ["FR-1"]), ("DIV-01", ["FR-1"])])
        self.assertEqual(len(failures), 1)


class TestLintsArePlanModeOnly(unittest.TestCase):
    def test_test_mode_report_has_empty_lint_failures(self):
        report = cc.build_report(
            "test",
            str(FIXTURES / "happy" / "requirements.md"),
            str(FIXTURES / "happy" / "test-report.md"),
        )
        self.assertEqual(report["lint_failures"], [])
        self.assertEqual(report["result"], "PASS")


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


class TestCliAnnotatedFixture(unittest.TestCase):
    def test_annotated_requirements_still_pass(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "annotated" / "requirements.md"),
            "--plan", str(FIXTURES / "annotated" / "plan.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["result"], "PASS")
        self.assertEqual(data["must_have"], ["FR-1", "FR-2", "NFR-1"])
        self.assertEqual(data["uncovered"], [])
        self.assertEqual(data["lint_failures"], [])
        self.assertTrue(any("FR-2" in w and "struck through" in w for w in data["warnings"]))


class TestCliLintLiteralCountFixture(unittest.TestCase):
    def test_literal_counts_fail_the_gate_with_no_coverage_gap(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "lint-literal-count" / "requirements.md"),
            "--plan", str(FIXTURES / "lint-literal-count" / "plan.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["result"], "FAIL")
        self.assertEqual(data["uncovered"], [])
        checks = {f["check"] for f in data["lint_failures"]}
        self.assertEqual(checks, {"literal-count"})
        details = " ".join(f["detail"] for f in data["lint_failures"])
        self.assertIn("7 error codes", details)
        self.assertIn("4 endpoints", details)
        self.assertNotIn("decimal", details)
        self.assertNotIn("attempts", details)
        self.assertNotIn("seconds", details)


class TestCliLintBoundaryContractsFixture(unittest.TestCase):
    def test_out_of_order_and_unprovided_identifiers_fail_the_gate(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "lint-boundary-contracts" / "requirements.md"),
            "--plan", str(FIXTURES / "lint-boundary-contracts" / "plan.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["result"], "FAIL")
        self.assertEqual(data["uncovered"], [])
        failures = data["lint_failures"]
        self.assertEqual({f["check"] for f in failures}, {"consumes-provides"})
        self.assertEqual({f["task"] for f in failures}, {"1"})
        details = " ".join(f["detail"] for f in failures)
        self.assertIn("db.schema", details)
        self.assertIn("queue.topic", details)
        # Task 2 consumes an identifier provided by Task 1, and Task 4 has no
        # Boundary contracts field at all — neither is a failure.
        self.assertNotIn("notify.worker", details)


class TestCliLintPathsFixture(unittest.TestCase):
    def test_absolute_paths_and_file_uris_fail_the_gate(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "lint-paths" / "requirements.md"),
            "--plan", str(FIXTURES / "lint-paths" / "plan.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["result"], "FAIL")
        self.assertEqual(data["uncovered"], [])
        failures = data["lint_failures"]
        self.assertEqual({f["check"] for f in failures}, {"path-hygiene"})
        details = " ".join(f["detail"] for f in failures)
        self.assertIn("file:///", details)
        self.assertIn("legacy.ts", details)
        self.assertIn("../Travel-Goat-v5/src/import/rollback.ts", details)
        # Sanctioned repo-relative identifiers are untouched.
        self.assertNotIn("src/import/itinerary-parser.ts", details)


class TestCliDesignAnnotatedFixture(unittest.TestCase):
    def test_every_register_row_routes_to_an_annotation(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "design-annotated" / "requirements.md"),
            "--design", str(FIXTURES / "design-annotated" / "detailed-design.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["mode"], "design")
        self.assertEqual(data["result"], "PASS")
        self.assertEqual(data["lint_failures"], [])
        # Design mode never computes coverage.
        self.assertEqual(data["covered"], [])
        self.assertEqual(data["uncovered"], [])


class TestCliDesignUnannotatedFixture(unittest.TestCase):
    def test_unannotated_register_citation_fails_the_gate(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "design-unannotated" / "requirements.md"),
            "--design", str(FIXTURES / "design-unannotated" / "detailed-design.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["result"], "FAIL")
        failures = data["lint_failures"]
        self.assertEqual({f["check"] for f in failures}, {"supersession-annotation"})
        self.assertEqual([f["task"] for f in failures], ["DIV-01"])
        self.assertIn("FR-3", failures[0]["detail"])
        # FR-2 is annotated and FR-9 is undefined: neither is a failure.
        details = " ".join(f["detail"] for f in failures)
        self.assertNotIn("FR-2", details)
        self.assertNotIn("FR-9", details)
        self.assertTrue(any("FR-9" in w for w in data["warnings"]))
        # Coverage is never gated in design mode.
        self.assertEqual(data["uncovered"], [])


class TestCliUsageErrors(unittest.TestCase):
    def test_design_without_requirements_exits_2(self):
        code, out, _err = run_cli(
            "--design", str(FIXTURES / "design-annotated" / "detailed-design.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(data["result"], "ERROR")
        self.assertEqual(data["mode"], "design")

    def test_design_with_plan_exits_2(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "happy" / "requirements.md"),
            "--plan", str(FIXTURES / "happy" / "plan.md"),
            "--design", str(FIXTURES / "design-annotated" / "detailed-design.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 2)
        self.assertEqual(data["result"], "ERROR")

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
