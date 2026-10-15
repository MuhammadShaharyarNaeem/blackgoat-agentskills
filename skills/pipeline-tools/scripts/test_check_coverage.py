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
        # The PASS now carries an exit code: an unevidenced PASS is
        # UNEVIDENCED rather than PASS (see TestPassEvidence below).
        text = ("- FR-1: FAIL — first run\n"
                "- FR-1: PASS — `npm test` exit 0 — retest\n")
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


class TestBlockedStatusToken(unittest.TestCase):
    """BLOCKED — a check whose precondition was absent — is status-bearing.

    Required by agents/quinn.md §6 and base-persona.md's Evidence Integrity
    section. Without it an honest agent must write FAIL (asserting a test ran)
    or omit the line (hiding the gap).
    """

    def test_blocked_is_status_bearing_and_never_covered(self):
        text = "- FR-1: BLOCKED — the dismiss endpoint is not deployed locally\n"
        status_by_id, warnings = cc.parse_test_report(text)
        self.assertEqual(status_by_id["FR-1"], "BLOCKED")
        # Status-bearing, so it earns no "mentioned without a status" warning.
        self.assertEqual(warnings, [])

    def test_blocked_downgrades_a_stale_pass(self):
        text = "- FR-1: PASS — first run\n- FR-1: BLOCKED — harness removed\n"
        status_by_id, _warnings = cc.parse_test_report(text)
        self.assertEqual(status_by_id["FR-1"], "BLOCKED")

    def test_later_pass_can_still_clear_a_blocked(self):
        text = ("- FR-1: BLOCKED — no harness\n"
                "- FR-1: PASS — harness built, `npm test` exit 0, retested\n")
        status_by_id, _warnings = cc.parse_test_report(text)
        self.assertEqual(status_by_id["FR-1"], "PASS")

    def test_fail_beats_blocked_on_one_line(self):
        text = "- FR-1: BLOCKED for the device check, FAIL for the API check\n"
        status_by_id, _warnings = cc.parse_test_report(text)
        self.assertEqual(status_by_id["FR-1"], "FAIL")

    def test_blocked_beats_pass_on_one_line(self):
        text = "- FR-1: PASS in-process, BLOCKED on the wire (no local estate)\n"
        status_by_id, _warnings = cc.parse_test_report(text)
        self.assertEqual(status_by_id["FR-1"], "BLOCKED")

    def test_not_run_is_deliberately_not_a_status_token(self):
        """Divergence from check_agent_report.py: omission already means not-run.

        A `NOT RUN` line must therefore behave exactly like any other
        status-less mention — warned about, and not covered.
        """
        text = "- FR-1: NOT RUN — deferred to the next milestone\n"
        status_by_id, warnings = cc.parse_test_report(text)
        self.assertNotIn("FR-1", status_by_id)
        self.assertTrue(any("FR-1" in w for w in warnings))

    def test_blocked_must_have_lands_in_uncovered_and_blocked(self):
        report = cc.build_report(
            "test",
            str(FIXTURES / "blocked" / "requirements.md"),
            str(FIXTURES / "blocked" / "test-report.md"),
        )
        self.assertEqual(report["result"], "FAIL")
        self.assertEqual(report["uncovered"], ["FR-2"])
        self.assertEqual(report["blocked"], ["FR-2"])
        self.assertNotIn("FR-2", report["covered"])

    def test_blocked_key_present_and_empty_in_plan_mode(self):
        report = cc.build_report(
            "plan",
            str(FIXTURES / "happy" / "requirements.md"),
            str(FIXTURES / "happy" / "plan.md"),
        )
        self.assertEqual(report["blocked"], [])

    def test_blocked_key_present_and_empty_in_design_mode(self):
        report = cc.build_report(
            "design",
            str(FIXTURES / "design-annotated" / "requirements.md"),
            str(FIXTURES / "design-annotated" / "detailed-design.md"),
        )
        self.assertEqual(report["blocked"], [])

    def test_existing_test_mode_fixtures_report_no_blocked_ids(self):
        """Backward compatibility: no pre-existing report carries the token."""
        for name in ("happy", "uncovered"):
            report = cc.build_report(
                "test",
                str(FIXTURES / name / "requirements.md"),
                str(FIXTURES / name / "test-report.md"),
            )
            self.assertEqual(report["blocked"], [], name)


class TestPassEvidence(unittest.TestCase):
    """A PASS must cite something a reader could go and check.

    The gate was deterministic about the STATUS token and completely trusting
    about the EVIDENCE beside it, so `- FR-1: PASS — I did not run anything`
    counted as coverage. Accepted forms mirror agents/quinn.md §6: an
    evidence/runtime/ capture, a `file::test-name` reference RESOLVED against
    --repo, or (unless --strict-evidence) a bare exit code.
    """

    def test_prose_only_pass_is_unevidenced_and_uncovered(self):
        text = "- FR-1: PASS — I did not run anything\n"
        status_by_id, warnings = cc.parse_test_report(text)
        self.assertEqual(status_by_id["FR-1"], "UNEVIDENCED")
        self.assertTrue(any("no checkable evidence" in w for w in warnings))

    def test_exit_code_evidence_is_accepted(self):
        status_by_id, warnings = cc.parse_test_report(
            "- FR-1: PASS — `npm test` — exit 0 — 42 passed\n")
        self.assertEqual(status_by_id["FR-1"], "PASS")
        self.assertEqual(warnings, [])

    def test_file_test_name_reference_resolves_against_repo(self):
        """The file half must exist and the name half must appear in it."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            test_file = Path(tmp) / "tests" / "reset.test.js"
            test_file.parent.mkdir(parents=True)
            test_file.write_text(
                "test('token expires after TTL', () => {});\n", encoding="utf-8")
            status_by_id, warnings = cc.parse_test_report(
                "- FR-1: PASS — tests/reset.test.js::token expires after TTL\n",
                repo_root=tmp)
            self.assertEqual(status_by_id["FR-1"], "PASS")
            self.assertEqual(warnings, [])

    def test_file_test_name_citation_to_a_nonexistent_file_is_unevidenced(self):
        """The audited fabrication (Metric 19.2): a citation to a file that
        does not exist in the repo must not certify coverage."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            status_by_id, warnings = cc.parse_test_report(
                "- FR-1: PASS — tests/LoginTests.cs::CanLogIn\n", repo_root=tmp)
            self.assertEqual(status_by_id["FR-1"], "UNEVIDENCED")
            self.assertTrue(any("cited_test_file_missing" in w for w in warnings))

    def test_file_test_name_citation_with_absent_test_name_is_unevidenced(self):
        """The file exists but never mentions the cited test — still fabricated."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            test_file = Path(tmp) / "tests" / "reset.test.js"
            test_file.parent.mkdir(parents=True)
            test_file.write_text("test('unrelated case', () => {});\n", encoding="utf-8")
            status_by_id, warnings = cc.parse_test_report(
                "- FR-1: PASS — tests/reset.test.js::token expires after TTL\n",
                repo_root=tmp)
            self.assertEqual(status_by_id["FR-1"], "UNEVIDENCED")
            self.assertTrue(any("cited_test_not_found_in_file" in w for w in warnings))

    def test_co_cited_exit_code_still_covers_an_unresolvable_test_ref(self):
        """Backward compatibility: every pre-existing fixture pairs `exit 0`
        with a `file::test-name` citing a path from the TARGET project the
        gate checks, not this plugin repo, so it never resolves here either.
        The bare exit code stays sufficient on its own unless
        --strict-evidence is set (see next class)."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            status_by_id, warnings = cc.parse_test_report(
                "- FR-1: PASS — `pytest` — exit 0 — tests/no_such.py::test_x\n",
                repo_root=tmp)
            self.assertEqual(status_by_id["FR-1"], "PASS")
            self.assertEqual(warnings, [])

    def test_runtime_capture_citation_is_accepted(self):
        for line in ("- FR-1: PASS — evidence/runtime/m3-auth.md\n",
                     "- FR-1: PASS — **Runtime evidence:** m3-auth.md\n"):
            status_by_id, _ = cc.parse_test_report(line)
            self.assertEqual(status_by_id["FR-1"], "PASS", line)

    def test_evidence_before_the_status_token_does_not_count(self):
        """`exit 0` must be the PASS's evidence, not an earlier line fragment."""
        self.assertFalse(cc.pass_is_evidenced(
            "- FR-1: exit 0 was yesterday's run; today it is PASS"))

    def test_strict_evidence_rejects_a_bare_exit_code(self):
        status_by_id, warnings = cc.parse_test_report(
            "- FR-1: PASS — `npm test` — exit 0 — 42 passed\n",
            strict_evidence=True)
        self.assertEqual(status_by_id["FR-1"], "UNEVIDENCED")
        self.assertTrue(any("strict-evidence" in w for w in warnings))

    def test_strict_evidence_still_accepts_a_resolved_file_test_name(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            test_file = Path(tmp) / "a.test.js"
            test_file.write_text("test('x', () => {});\n", encoding="utf-8")
            status_by_id, _ = cc.parse_test_report(
                "- FR-1: PASS — a.test.js::x\n", repo_root=tmp, strict_evidence=True)
            self.assertEqual(status_by_id["FR-1"], "PASS")

    def test_strict_evidence_still_accepts_runtime_capture(self):
        status_by_id, _ = cc.parse_test_report(
            "- FR-1: PASS — evidence/runtime/m3-auth.md\n", strict_evidence=True)
        self.assertEqual(status_by_id["FR-1"], "PASS")

    def test_unevidenced_must_have_lands_in_uncovered_and_unevidenced(self):
        report = cc.build_report(
            "test",
            str(FIXTURES / "happy" / "requirements.md"),
            str(FIXTURES / "unevidenced" / "test-report.md"),
        )
        self.assertEqual(report["result"], "FAIL")
        self.assertIn("FR-1", report["uncovered"])
        self.assertIn("FR-1", report["unevidenced"])
        self.assertNotIn("FR-1", report["covered"])

    def test_unevidenced_key_present_and_empty_outside_test_mode(self):
        for mode, name, target in (
                ("plan", "happy", "plan.md"),
                ("design", "design-annotated", "detailed-design.md")):
            report = cc.build_report(mode,
                                     str(FIXTURES / name / "requirements.md"),
                                     str(FIXTURES / name / target))
            self.assertEqual(report["unevidenced"], [], mode)

    def test_bare_prose_without_a_list_marker_never_counts(self):
        """`FR-1 and FR-2 both pass the smoke test` covered two Must-Haves."""
        text = "FR-1 and FR-2 both pass the smoke test — exit 0\n"
        status_by_id, warnings = cc.parse_test_report(text)
        self.assertEqual(status_by_id, {})
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all("without a status token" in w for w in warnings))

    def test_numbered_list_item_is_still_a_ledger_line(self):
        status_by_id, _ = cc.parse_test_report(
            "1. FR-1: PASS — `npm test` exit 0\n")
        self.assertEqual(status_by_id["FR-1"], "PASS")


class TestFenceStripping(unittest.TestCase):
    """A status token inside a fence is a transcript, not a claim."""

    def test_fenced_pass_does_not_overwrite_a_real_fail(self):
        report = cc.build_report(
            "test",
            str(FIXTURES / "happy" / "requirements.md"),
            str(FIXTURES / "fenced" / "test-report.md"),
        )
        self.assertEqual(report["result"], "FAIL")
        self.assertIn("FR-2", report["uncovered"])

    def test_strip_fenced_blocks_preserves_line_count(self):
        text = "a\n```\nb\nc\n```\nd\n"
        stripped = cc.strip_fenced_blocks(text)
        self.assertEqual(len(stripped.split("\n")), len(text.split("\n")))
        self.assertNotIn("b", stripped)

    def test_tilde_fences_are_stripped_too(self):
        self.assertNotIn("hidden", cc.strip_fenced_blocks("~~~\nhidden\n~~~\n"))

    def test_plan_mode_is_not_fence_stripped(self):
        """Plan probes legitimately live in fenced blocks — strip nothing."""
        report = cc.build_report(
            "plan",
            str(FIXTURES / "lint-runtime-criterion" / "requirements.md"),
            str(FIXTURES / "lint-runtime-criterion" / "plan.md"),
        )
        self.assertEqual(
            len([f for f in report["lint_failures"]
                 if f["check"] == "runtime-criterion"]), 2)


class TestBomTolerance(unittest.TestCase):
    def test_bom_prefixed_test_report_parses(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test-report.md"
            path.write_bytes(
                b"\xef\xbb\xbf"
                + "- FR-1: PASS — `npm test` exit 0 — tests/a.js::b\n".encode(
                    "utf-8"))
            report = cc.build_report(
                "test", str(FIXTURES / "happy" / "requirements.md"), str(path))
            self.assertIn("FR-1", report["covered"])


class TestLedger(unittest.TestCase):
    def test_ledger_records_every_exit_path(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "logs" / "gates.jsonl"
            code, _out, _err = run_cli(
                "--requirements", str(FIXTURES / "happy" / "requirements.md"),
                "--test-report", str(FIXTURES / "happy" / "test-report.md"),
                "--ledger", str(ledger))
            self.assertEqual(code, 0)
            code, _out, _err = run_cli(
                "--requirements", str(FIXTURES / "uncovered" / "requirements.md"),
                "--test-report", str(FIXTURES / "uncovered" / "test-report.md"),
                "--ledger", str(ledger))
            self.assertEqual(code, 1)
            code, _out, _err = run_cli("--ledger", str(ledger))
            self.assertEqual(code, 2)
            records = [json.loads(l) for l in
                       ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual([r["verdict"] for r in records],
                             ["PASS", "FAIL", "ERROR"])
            self.assertTrue(all(r["gate"] == "check_coverage.py"
                                for r in records))
            self.assertIsNone(records[0]["milestone"])
            self.assertEqual(
                records[0]["inputs"][
                    str(FIXTURES / "happy" / "test-report.md")],
                cc.sha256_file(FIXTURES / "happy" / "test-report.md"))


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


class TestConsumesProvidesSentenceBreakTruncation(unittest.TestCase):
    """Reproduces the observed prose-after-machine-line false positives.

    A real Alex plan wrote a machine-parseable `provides:`/`consumes:` line
    with explanatory prose trailing it on the same physical line (no `;`, no
    newline separating list from prose). Comma-splitting the raw text turned
    that prose's commas into fake identifiers (`4`, `5`, `not`, ...).
    """

    def test_consumes_none_with_trailing_sentence_yields_zero_identifiers(self):
        # Observed line: "provides: api.mode.ruling; consumes: none. The
        # ruling is a single string token read by Tasks 3, 4, 5."
        field_text = (
            "**Boundary contracts:** provides: api.mode.ruling; "
            "consumes: none. The ruling is a single string token read by "
            "Tasks 3, 4, 5.\n"
        )
        consumes, provides = cc._contract_identifiers(field_text)
        self.assertEqual(consumes, [])
        self.assertEqual(provides, ["api.mode.ruling"])
        self.assertNotIn("4", consumes)
        self.assertNotIn("5", consumes)

    def test_provides_list_with_trailing_prose_and_emdash_yields_only_real_identifiers(self):
        # Observed shape: a provides: list followed by prose containing its
        # own comma and an em-dash aside ("not the SQL file — the seed...");
        # the prose's "not" must never be comma-split into a fake identifier.
        field_text = (
            "**Boundary contracts:** provides: db.fixtures.customera, "
            "db.fixtures.customerb, api.mode.ruling. The two fixture "
            "identifiers name **live rows in the Dev DB**, not the SQL "
            "file — the seed script only inserts them.\n"
        )
        consumes, provides = cc._contract_identifiers(field_text)
        self.assertEqual(consumes, [])
        self.assertEqual(
            provides,
            ["db.fixtures.customera", "db.fixtures.customerb", "api.mode.ruling"],
        )
        self.assertNotIn("not", provides)

    def test_lint_boundary_contracts_ignores_trailing_prose_end_to_end(self):
        # Integration path: the trailing-prose line must not manufacture a
        # consumed identifier that then fails the consumes-provides lint.
        failures = cc.lint_boundary_contracts(
            cc.split_task_blocks(
                "## Task 1: Ruling\n"
                "**Boundary contracts:** provides: api.mode.ruling; "
                "consumes: none. The ruling is a single string token read "
                "by Tasks 3, 4, 5.\n\n"
                "## Task 3: Consumer\n"
                "**Boundary contracts:** consumes: api.mode.ruling\n"
            )
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


class TestRuntimeCriterionLint(unittest.TestCase):
    """The plan-mode `runtime-criterion` lint over `### Checkpoint:` blocks."""

    GOOD_PROBE = (
        "RUNTIME PROBE: start: `npm run start`; "
        "probe: `curl -sS -i http://localhost:5142/api/orders`; "
        "expect-status: 200; require-keys: isSuccess, data"
    )

    def _plan(self, surface="api", probe_line=GOOD_PROBE, extra_checkpoint_lines=()):
        lines = [
            "# P",
            "",
            f"### Milestone 1 — Orders [API] [vs:{surface}]",
            "",
            "## Task 1: Endpoint",
            "",
            "**Requirements covered:** FR-1",
            "",
            "### Checkpoint: Milestone 1",
            "- [ ] All tests pass",
        ]
        if probe_line is not None:
            lines.append(f"- [ ] {probe_line}")
        lines.extend(f"- [ ] {line}" for line in extra_checkpoint_lines)
        lines.append("- [ ] Review with human before proceeding")
        return "\n".join(lines) + "\n"

    def _lint(self, *args, **kwargs):
        return cc.lint_runtime_criterion(self._plan(*args, **kwargs))

    # ---- condition 1: no RUNTIME PROBE line ----

    def test_checkpoint_without_a_probe_line_fails(self):
        failures = self._lint(probe_line=None)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["check"], "runtime-criterion")
        self.assertIn("carries no 'RUNTIME PROBE:' line", failures[0]["detail"])

    def test_missing_probe_line_reports_one_root_cause_only(self):
        """A [vs:api] checkpoint with no probe line must not also report the
        missing expect-status/require-keys — one root cause, one failure."""
        self.assertEqual(len(self._lint(surface="api", probe_line=None)), 1)

    # ---- condition 2: empty probe field ----

    def test_empty_probe_field_fails(self):
        failures = self._lint(probe_line=(
            "RUNTIME PROBE: start: `npm run start`; probe: ; "
            "expect-status: 200; require-keys: isSuccess"))
        self.assertEqual(len(failures), 1)
        self.assertIn("declares no 'probe:' command", failures[0]["detail"])

    def test_probe_field_set_to_none_counts_as_empty(self):
        failures = self._lint(probe_line=(
            "RUNTIME PROBE: start: `npm run start`; probe: none; "
            "expect-status: 200; require-keys: isSuccess"))
        self.assertEqual(len(failures), 1)
        self.assertIn("declares no 'probe:' command", failures[0]["detail"])

    def test_probe_keyword_entirely_absent_counts_as_empty(self):
        failures = self._lint(probe_line=(
            "RUNTIME PROBE: start: `npm run start`; "
            "expect-status: 200; require-keys: isSuccess"))
        self.assertEqual(len(failures), 1)
        self.assertIn("declares no 'probe:' command", failures[0]["detail"])

    # ---- condition 3: in-process test client ----

    def test_in_process_probe_fails_for_every_tell(self):
        for tell in ("WebApplicationFactory<Program>", "factory.CreateClient()",
                     "TestServer", "supertest(app)", "MockMvc",
                     "app.test_client()", "ASGITransport"):
            failures = self._lint(probe_line=(
                f"RUNTIME PROBE: start: `run`; probe: `{tell}`; "
                "expect-status: 200; require-keys: isSuccess"))
            self.assertTrue(any("IN-PROCESS" in f["detail"] for f in failures), tell)

    # ---- condition 4: build / typecheck / search / test-runner ----

    def test_test_runner_probe_fails(self):
        """The load-bearing case: a green suite is not an observation."""
        for bad in ("dotnet test --filter Orders", "npm test", "pytest -k orders",
                    "go test ./...", "npx jest orders", "vitest run"):
            failures = self._lint(probe_line=(
                f"RUNTIME PROBE: start: `run`; probe: `{bad}`; "
                "expect-status: 200; require-keys: isSuccess"))
            self.assertTrue(
                any("test-runner command" in f["detail"] for f in failures), bad)

    def test_build_typecheck_and_search_probes_fail(self):
        for bad in ("dotnet build", "npm run build", "tsc --noEmit",
                    "grep -r isSuccess src/", "msbuild /t:Rebuild", "make build"):
            failures = self._lint(probe_line=(
                f"RUNTIME PROBE: start: `run`; probe: `{bad}`; "
                "expect-status: 200; require-keys: isSuccess"))
            self.assertEqual(len(failures), 1, bad)

    def test_url_containing_rg_is_not_a_search_command(self):
        """Word boundaries, as in check_runtime_evidence.py: 'myorg' != ripgrep."""
        failures = self._lint(probe_line=(
            "RUNTIME PROBE: start: `run`; "
            "probe: `curl -sS -i http://myorg.localhost:5142/api/orders`; "
            "expect-status: 200; require-keys: isSuccess"))
        self.assertEqual(failures, [])

    # ---- condition 5: response surfaces need assertion fields ----

    def test_response_surfaces_require_expect_status_and_require_keys(self):
        for surface in ("api", "web+api", "fn"):
            failures = self._lint(surface=surface, probe_line=(
                "RUNTIME PROBE: start: `run`; "
                "probe: `curl -sS -i http://localhost:5142/api/orders`"))
            self.assertEqual(len(failures), 1, surface)
            self.assertIn("'expect-status:'", failures[0]["detail"])
            self.assertIn("'require-keys:'", failures[0]["detail"])
            self.assertIn(f"[vs:{surface}]", failures[0]["detail"])

    def test_only_the_absent_response_field_is_named(self):
        failures = self._lint(probe_line=(
            "RUNTIME PROBE: start: `run`; "
            "probe: `curl -sS -i http://localhost:5142/api/orders`; "
            "expect-status: 200"))
        self.assertEqual(len(failures), 1)
        self.assertIn("'require-keys:'", failures[0]["detail"])
        self.assertNotIn("'expect-status:'", failures[0]["detail"])

    def test_non_response_surfaces_do_not_require_those_fields(self):
        for surface in ("ui", "rmm"):
            failures = self._lint(surface=surface, probe_line=(
                "RUNTIME PROBE: start: `npm run dev`; "
                "probe: `open /orders and read the accessibility tree`"))
            self.assertEqual(failures, [], surface)

    # ---- condition 6: [vs:none] needs a justification ----

    def test_vs_none_without_a_justification_fails(self):
        failures = self._lint(surface="none", probe_line=(
            "RUNTIME PROBE: start: `npm run start`"))
        self.assertEqual(len(failures), 1)
        self.assertIn("'justification:'", failures[0]["detail"])

    def test_vs_none_with_a_justification_passes_without_a_probe(self):
        failures = self._lint(surface="none", probe_line=(
            "RUNTIME PROBE: justification: the change renames an internal "
            "helper; no client, person or device can observe it"))
        self.assertEqual(failures, [])

    def test_vs_none_justification_elsewhere_in_the_block_is_accepted(self):
        failures = self._lint(
            surface="none",
            probe_line="RUNTIME PROBE: start: `npm run start`",
            extra_checkpoint_lines=("justification: nothing crosses a boundary",))
        self.assertEqual(failures, [])

    # ---- happy path and scope limits ----

    def test_conforming_probe_passes(self):
        self.assertEqual(self._lint(), [])

    def test_plan_with_no_checkpoints_yields_no_failures(self):
        """Backward compatibility: absence of checkpoints is Step 5's own
        review item, never this lint's failure."""
        self.assertEqual(cc.lint_runtime_criterion(
            "# P\n\n### Milestone 1 — X [API] [vs:api]\n\n## Task 1: t\n"), [])

    def test_plan_with_no_milestones_still_lints_its_checkpoints(self):
        """No milestone means no surface, so only the surface-independent
        rules apply — the probe must still exist and be a runtime probe."""
        failures = cc.lint_runtime_criterion(
            "# P\n\n## Task 1: t\n\n### Checkpoint: after task 1\n"
            "- [ ] All tests pass\n")
        self.assertEqual(len(failures), 1)
        self.assertIn("carries no 'RUNTIME PROBE:' line", failures[0]["detail"])
        self.assertEqual(failures[0]["task"], "Checkpoint: after task 1")

    def test_task_field_names_the_owning_milestone(self):
        failures = self._lint(probe_line=None)
        self.assertEqual(failures[0]["task"], "Milestone 1 — Orders [API] [vs:api]")

    def test_deprecated_level2_checkpoint_is_also_linted(self):
        """The level-2 form next_milestone.py tolerates is not an escape hatch."""
        failures = cc.lint_runtime_criterion(
            "# P\n\n### Milestone 1 — X [API] [vs:api]\n\n## Task 1: t\n\n"
            "## Checkpoint: Milestone 1\n- [ ] All tests pass\n")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["task"], "Milestone 1 — X [API] [vs:api]")

    def test_checkpoint_is_attributed_to_its_own_milestone(self):
        plan = (
            "# P\n\n"
            "### Milestone 1 — API [API] [vs:api]\n\n## Task 1: t\n\n"
            "### Checkpoint: Milestone 1\n"
            "- [ ] RUNTIME PROBE: start: `run`; probe: `curl -sS -i http://localhost:1/a`\n\n"
            "### Milestone 2 — UI [UI] [vs:ui]\n\n## Task 2: t\n\n"
            "### Checkpoint: Milestone 2\n"
            "- [ ] RUNTIME PROBE: start: `run`; probe: `open /orders, read the tree`\n"
        )
        failures = cc.lint_runtime_criterion(plan)
        # Only the [vs:api] milestone's checkpoint needs the response fields.
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["task"], "Milestone 1 — API [API] [vs:api]")
        self.assertIn("Checkpoint: Milestone 1", failures[0]["detail"])

    def test_heading_surface_wins_over_a_block_mention(self):
        """Mirrors next_milestone.py's milestone_surface() authority rule."""
        plan = (
            "# P\n\n### Milestone 1 — X [API] [vs:ui]\n\n## Task 1: t\n\n"
            "Prose mentioning [vs:api] in passing.\n\n"
            "### Checkpoint: Milestone 1\n"
            "- [ ] RUNTIME PROBE: start: `run`; probe: `open /x and read the tree`\n"
        )
        self.assertEqual(cc.lint_runtime_criterion(plan), [])
        self.assertEqual(cc.milestone_surface("### M 1 — X [API] [vs:ui]", "[vs:api]"), "ui")

    def test_surface_read_from_the_block_when_the_heading_has_none(self):
        plan = (
            "# P\n\n### Milestone 1 — X [API]\n\n## Task 1: t\n\n"
            "**Verification surface:** [vs:api]\n\n"
            "### Checkpoint: Milestone 1\n"
            "- [ ] RUNTIME PROBE: start: `run`; probe: `curl -sS -i http://localhost:1/a`\n"
        )
        failures = cc.lint_runtime_criterion(plan)
        self.assertEqual(len(failures), 1)
        self.assertIn("[vs:api]", failures[0]["detail"])

    def test_multiline_probe_field_is_folded_in(self):
        plan = (
            "# P\n\n### Milestone 1 — X [API] [vs:api]\n\n## Task 1: t\n\n"
            "### Checkpoint: Milestone 1\n"
            "- [ ] RUNTIME PROBE: start: `npm run start`;\n"
            "      probe: `curl -sS -i http://localhost:5142/api/orders`;\n"
            "      expect-status: 200; require-keys: isSuccess, data\n"
        )
        self.assertEqual(cc.lint_runtime_criterion(plan), [])

    def test_milestone_block_extents_match_next_milestone(self):
        """A trailing non-Task level-2 heading ends the milestone block, so a
        checkpoint after it is an orphan with no surface — the same extent
        next_milestone.py's parse_milestones() computes."""
        plan = (
            "# P\n\n### Milestone 1 — X [API] [vs:api]\n\n## Task 1: t\n\n"
            "## Risks and Mitigations\n\n"
            "### Checkpoint: stray\n"
            "- [ ] RUNTIME PROBE: start: `run`; probe: `curl -sS -i http://localhost:1/a`\n"
        )
        failures = cc.lint_runtime_criterion(plan)
        # Orphan: no surface, so the response-field rule does not apply.
        self.assertEqual(failures, [])
        blocks = cc.split_milestone_blocks(plan.split("\n"))
        self.assertEqual(len(blocks), 1)
        self.assertNotIn("Checkpoint: stray", "\n".join(
            plan.split("\n")[blocks[0][2]:blocks[0][3]]))

    def test_in_process_tells_match_check_runtime_evidence_verbatim(self):
        """Both lists gate the same claim; a drift is a hole in one of them."""
        import check_runtime_evidence as cre  # noqa: E402
        self.assertEqual(cc.IN_PROCESS_TELLS, cre.IN_PROCESS_TELLS)
        self.assertEqual([p.pattern for p in cc.NON_RUNTIME_PROBE_RES],
                         [p.pattern for p in cre.NON_RUNTIME_PROBE_RES])


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


class TestFrCitationLint(unittest.TestCase):
    MUST_HAVE = ["FR-1", "FR-10", "NFR-1", "NFR-10"]

    def _lint(self, design_text):
        return cc.lint_fr_citations(design_text, self.MUST_HAVE)

    def test_all_cited_passes(self):
        design = "Covers FR-1, FR-10, NFR-1 and NFR-10."
        self.assertEqual(self._lint(design), [])

    def test_uncited_id_fails(self):
        failures = self._lint("Covers FR-1, FR-10 and NFR-10.")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["check"], "fr-citation")
        self.assertEqual(failures[0]["task"], "NFR-1")

    def test_longer_id_does_not_cite_its_prefix(self):
        """FR-10 must not satisfy FR-1 — whole-token match, never substring."""
        failures = self._lint("Audit rows are written per FR-10, meeting NFR-10.")
        self.assertEqual([f["task"] for f in failures], ["FR-1", "NFR-1"])

    def test_nfr_does_not_cite_the_fr_of_the_same_number(self):
        failures = self._lint("Only NFR-1 and NFR-10 are named here.")
        self.assertEqual([f["task"] for f in failures], ["FR-1", "FR-10"])


class TestAdrCitationLint(unittest.TestCase):
    KNOWN_IDS = {"FR-1", "FR-2"}

    def _lint(self, design_text, known_ids=None):
        return cc.lint_adr_citation(design_text, known_ids or self.KNOWN_IDS)

    def test_row_with_adr_token_passes(self):
        design = (
            "## Divergence & Supersession Register\n"
            "| **SUP-01** | **FR-2** | link replaces email | see ADR-0007 |\n"
        )
        self.assertEqual(self._lint(design), [])

    def test_row_with_adr_path_passes(self):
        design = (
            "## Divergence & Supersession Register\n"
            "| **SUP-01** | **FR-2** | link replaces email | "
            "design/adr/0007-signed-link.md |\n"
        )
        self.assertEqual(self._lint(design), [])

    def test_row_without_adr_citation_fails(self):
        design = (
            "## Divergence & Supersession Register\n"
            "| **SUP-01** | **FR-2** | link replaces email | no relay provisioned |\n"
        )
        failures = self._lint(design)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["check"], "adr-citation")
        self.assertEqual(failures[0]["task"], "SUP-01")
        self.assertIn("FR-2", failures[0]["detail"])
        self.assertIn("supersession_without_adr", failures[0]["detail"])

    def test_no_register_section_passes(self):
        self.assertEqual(self._lint("# Design\n\n## 4. Data Model\n"), [])

    def test_row_with_no_known_id_is_not_a_supersession_row(self):
        design = (
            "## Divergence & Supersession Register\n"
            "| **DIV-01** | the error-envelope playbook | consumes FR-9 budget |\n"
        )
        # FR-9 is not in KNOWN_IDS, so this row is not linted at all.
        self.assertEqual(self._lint(design), [])

    def test_same_row_reported_once(self):
        design = (
            "## Divergence & Supersession Register\n"
            "| **SUP-01** | **FR-2** | no ADR here, cited **FR-1** too |\n"
        )
        failures = self._lint(design)
        self.assertEqual(len(failures), 1)


class TestDomainTagLint(unittest.TestCase):
    def _lint(self, plan_text):
        return cc.lint_domain_tags(plan_text)

    def test_tagged_homogeneous_plan_passes(self):
        failures = self._lint(
            "### Milestone 1 — Orders API [API] [vs:api]\n"
            "## Task 1: List endpoint\n\n"
            "**Tags:** [API]\n\n"
            "### Milestone 2 — Orders UI [UI] [vs:web+api]\n"
            "## Task 2: Orders table\n\n"
            "**Tags:** [UI] [SEC]\n"
        )
        self.assertEqual(failures, [])

    def test_missing_tags_line_fails(self):
        failures = self._lint("## Task 1: List endpoint\n\n- some body\n")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["check"], "domain-tag")
        self.assertEqual(failures[0]["task"], "1")
        self.assertIn("no **Tags:** line", failures[0]["detail"])

    def test_tags_line_without_domain_fails(self):
        failures = self._lint("## Task 1: Hardening\n\n**Tags:** [SEC]\n")
        self.assertEqual(len(failures), 1)
        self.assertIn("no domain tag", failures[0]["detail"])

    def test_tags_line_with_both_domains_fails(self):
        failures = self._lint("## Task 1: Full slice\n\n**Tags:** [UI] [API]\n")
        self.assertEqual(len(failures), 1)
        self.assertIn("both [UI] and [API]", failures[0]["detail"])

    def test_mixed_domain_milestone_fails(self):
        failures = self._lint(
            "### Milestone 1 — Orders [API] [vs:api]\n"
            "## Task 1: List endpoint\n\n"
            "**Tags:** [API]\n\n"
            "## Task 2: Orders table\n\n"
            "**Tags:** [UI]\n"
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("mixed-domain milestone", failures[0]["detail"])
        self.assertIn("Task 2", failures[0]["detail"])

    def test_untagged_milestone_heading_fails_once(self):
        failures = self._lint(
            "### Milestone 1 — Orders [vs:api]\n"
            "## Task 1: List endpoint\n\n"
            "**Tags:** [API]\n"
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("milestone heading must carry exactly one domain tag",
                      failures[0]["detail"])

    def test_plan_without_milestones_skips_homogeneity_half(self):
        failures = self._lint(
            "## Task 1: List endpoint\n\n**Tags:** [API]\n\n"
            "## Task 2: Orders table\n\n**Tags:** [UI]\n"
        )
        self.assertEqual(failures, [])

    def test_lowercase_vs_tag_never_reads_as_domain(self):
        failures = self._lint(
            "## Task 1: Probe-only task\n\n**Tags:** [vs:api]\n"
        )
        self.assertEqual(len(failures), 1)
        self.assertIn("no domain tag", failures[0]["detail"])


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


class TestCliLintDomainTagsFixture(unittest.TestCase):
    def test_overlay_only_tags_line_fails_the_gate(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "lint-domain-tags" / "requirements.md"),
            "--plan", str(FIXTURES / "lint-domain-tags" / "plan.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["result"], "FAIL")
        self.assertEqual(data["uncovered"], [])
        failures = data["lint_failures"]
        self.assertEqual({f["check"] for f in failures}, {"domain-tag"})
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["task"], "1")
        self.assertIn("no domain tag", failures[0]["detail"])


class TestCliLintRuntimeCriterionFixture(unittest.TestCase):
    def test_non_runtime_probe_and_missing_response_fields_fail_the_gate(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "lint-runtime-criterion" / "requirements.md"),
            "--plan", str(FIXTURES / "lint-runtime-criterion" / "plan.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["result"], "FAIL")
        # This fixture isolates ONE lint: no coverage gap, no sibling lint.
        self.assertEqual(data["uncovered"], [])
        failures = data["lint_failures"]
        self.assertEqual({f["check"] for f in failures}, {"runtime-criterion"})
        self.assertEqual(len(failures), 2)
        details = " ".join(f["detail"] for f in failures)
        self.assertIn("test-runner command", details)
        self.assertIn("'npm test'", details)
        self.assertIn("'expect-status:'", details)
        self.assertIn("'require-keys:'", details)
        self.assertEqual([f["task"] for f in failures],
                         ["Milestone 1 — Orders: list endpoint [API] [vs:api]",
                          "Milestone 2 — Orders: create endpoint [API] [vs:api]"])


class TestCliBlockedFixture(unittest.TestCase):
    def test_blocked_ledger_line_fails_the_gate_and_is_reported(self):
        code, out, _err = run_cli(
            "--requirements", str(FIXTURES / "blocked" / "requirements.md"),
            "--test-report", str(FIXTURES / "blocked" / "test-report.md"),
        )
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(data["result"], "FAIL")
        self.assertEqual(data["blocked"], ["FR-2"])
        self.assertEqual(data["uncovered"], ["FR-2"])
        self.assertEqual(data["covered"], ["FR-1", "NFR-1"])
        # BLOCKED is status-bearing, so it earns no status-less warning.
        self.assertEqual(data["warnings"], [])


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


BUDGET_REQS = """# Requirements

## Must Have
- **FR-1**: receive webhooks
- **FR-2**: store events
- **NFR-1** (Must Have) -- p95 under 200ms

## Complexity Budget
- **Simple version:** one receiver writing one table.
- **Max tables:** 1
- **Mechanisms:** webhook-receiver
- **Waivers:** {waivers}
"""

BUDGET_DESIGN = """# Design

Covers FR-1, FR-2 and NFR-1.

## Data Model

### webhook_events
fields...

## Mechanism Register

| Mechanism | Kind | Traces to | Cost | Status |
|---|---|---|---|---|
| `webhook_events` | table | FR-2 | 1 table | Kept |
| webhook-receiver | mechanism | **FR-1** | 1 endpoint | Kept |
{extra}
"""


class TestComplexityBudget(unittest.TestCase):
    """--budget mode and design mode's --require-budget (plan-simplicity gate)."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def design(self, extra="", waivers=(), design=None, reqs_text=None):
        """The real flow: --budget records the block, --add-waiver records
        each waiver, then --require-budget gates the design. Returns the
        last run's (code, report)."""
        reqs = self.write("requirements.md",
                          reqs_text or BUDGET_REQS.format(waivers="none"))
        ledger = str(self.dir / "gates.jsonl")
        run_cli("--requirements", reqs, "--budget", "--ledger", ledger)
        for waiver in waivers:
            code, out, _err = run_cli("--requirements", reqs, "--add-waiver",
                                      waiver, "--ledger", ledger)
            self.assertEqual(code, 0, out)
        des = self.write("detailed-design.md",
                         design if design is not None else BUDGET_DESIGN.format(extra=extra))
        code, out, _err = run_cli("--requirements", reqs, "--design", des,
                                  "--require-budget", "--ledger", ledger)
        return code, json.loads(out)

    def checks(self, data):
        return sorted({f["check"] for f in data["lint_failures"]})

    # --- budget mode -----------------------------------------------------
    def test_budget_mode_clean_pass(self):
        reqs = self.write("requirements.md", BUDGET_REQS.format(waivers="none"))
        code, out, _err = run_cli("--requirements", reqs, "--budget")
        data = json.loads(out)
        self.assertEqual(code, 0, data)
        self.assertEqual(data["mode"], "budget")
        self.assertEqual(data["budget"], {
            "max_tables": 1, "mechanisms": ["webhook-receiver"], "waivers": [],
            "kept_tables": None, "kept_mechanisms": None})

    def test_budget_missing(self):
        reqs = self.write("requirements.md", "## Must Have\n- **FR-1**: x\n")
        code, out, _err = run_cli("--requirements", reqs, "--budget")
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(self.checks(data), ["budget-missing"])
        self.assertEqual(data["lint_failures"][0]["task"], "budget")
        self.assertIsNone(data["budget"])

    def test_budget_malformed_cases(self):
        good = BUDGET_REQS.format(waivers="none")
        cases = {
            "out of order": good.replace(
                "- **Max tables:** 1\n- **Mechanisms:** webhook-receiver\n",
                "- **Mechanisms:** webhook-receiver\n- **Max tables:** 1\n"),
            "label missing": good.replace("- **Waivers:** none\n", ""),
            "non-integer max": good.replace("**Max tables:** 1", "**Max tables:** four"),
            "bad mechanism name": good.replace("webhook-receiver", "Webhook_Receiver"),
            "malformed waiver": good.replace("**Waivers:** none",
                                             "**Waivers:** tables+1 because we must"),
            "bad waiver date": good.replace(
                "**Waivers:** none",
                "**Waivers:** tables+1 — audit trail (approved 2026-13-40)"),
        }
        for name, text in cases.items():
            reqs = self.write("requirements.md", text)
            code, out, _err = run_cli("--requirements", reqs, "--budget")
            data = json.loads(out)
            self.assertEqual(code, 1, name)
            self.assertEqual(self.checks(data), ["budget-malformed"], name)
            self.assertIsNone(data["budget"], name)

    def test_budget_mode_parses_waivers(self):
        text = BUDGET_REQS.format(waivers=(
            "tables+2 — audit tables (approved 2026-10-15); "
            "mechanism:outbox — payment crash window (approved 2026-10-15)"))
        code, out, _err = run_cli("--requirements", self.write("r.md", text), "--budget")
        data = json.loads(out)
        self.assertEqual(code, 0, data)
        self.assertEqual([w["target"] for w in data["budget"]["waivers"]],
                         ["tables+2", "mechanism:outbox"])
        self.assertEqual(data["budget"]["waivers"][0]["approved"], "2026-10-15")

    def test_require_budget_outside_design_mode_exits_2(self):
        reqs = self.write("requirements.md", BUDGET_REQS.format(waivers="none"))
        for extra in (["--budget"], ["--plan", str(FIXTURES / "happy" / "plan.md")]):
            code, out, _err = run_cli("--requirements", reqs, *extra, "--require-budget")
            self.assertEqual(code, 2, extra)
            self.assertEqual(json.loads(out)["result"], "ERROR", extra)

    def test_budget_with_another_target_exits_2(self):
        reqs = self.write("requirements.md", BUDGET_REQS.format(waivers="none"))
        code, _out, _err = run_cli("--requirements", reqs, "--budget",
                                   "--design", reqs)
        self.assertEqual(code, 2)

    # --- design mode -----------------------------------------------------
    def test_design_without_require_budget_is_unchanged(self):
        reqs = self.write("requirements.md", "## Must Have\n- **FR-1**: x\n")
        des = self.write("detailed-design.md", "# Design\nCovers FR-1.\n")
        code, out, _err = run_cli("--requirements", reqs, "--design", des)
        data = json.loads(out)
        self.assertEqual(code, 0, data)
        self.assertEqual(data["lint_failures"], [])
        self.assertIsNone(data["budget"])

    def test_require_budget_clean_pass(self):
        code, data = self.design()
        self.assertEqual(code, 0, data)
        self.assertEqual(data["budget"]["kept_tables"], ["webhook_events"])
        self.assertEqual(data["budget"]["kept_mechanisms"], ["webhook-receiver"])

    def test_require_budget_reports_budget_missing(self):
        reqs = self.write("requirements.md", "## Must Have\n- **FR-1**: x\n- **FR-2**: y\n"
                          "- **NFR-1** (Must Have) -- z\n")
        des = self.write("detailed-design.md", BUDGET_DESIGN.format(extra=""))
        code, out, _err = run_cli("--requirements", reqs, "--design", des, "--require-budget",
                                  "--ledger", str(self.dir / "gates.jsonl"))
        data = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(self.checks(data), ["budget-missing"])

    def test_register_missing_section(self):
        design = BUDGET_DESIGN.format(extra="").split("## Mechanism Register")[0]
        code, data = self.design(design=design)
        self.assertEqual(code, 1)
        self.assertIn("register-missing", self.checks(data))
        self.assertIn("unregistered-table", self.checks(data))

    def test_register_missing_bad_row(self):
        code, data = self.design(extra="| cache | service | FR-1 |  | Maybe |")
        self.assertEqual(code, 1)
        self.assertEqual(self.checks(data), ["register-missing"])
        failure = data["lint_failures"][0]
        self.assertEqual(failure["task"], "cache")
        for part in ("Kind", "Status", "Cost"):
            self.assertIn(part, failure["detail"])

    def test_untraced_mechanism(self):
        code, data = self.design(extra="| poller | mechanism | nice to have | 1 job | Kept |")
        self.assertEqual(code, 1)
        self.assertIn("untraced-mechanism", self.checks(data))
        self.assertIn("poller", [f["task"] for f in data["lint_failures"]
                                 if f["check"] == "untraced-mechanism"])

    def test_nonexistent_fr_id_is_untraced(self):
        code, data = self.design(
            extra="| poller | mechanism | FR-99 | 1 job | Kept |",
            waivers=("mechanism:poller — polling fallback",))
        self.assertEqual(code, 1)
        self.assertEqual(self.checks(data), ["untraced-mechanism"])
        self.assertIn("FR-99", data["lint_failures"][0]["detail"])

    def test_risk_trace_is_traced(self):
        code, data = self.design(
            extra="| poller | mechanism | risk: vendor drops 2% of webhooks | 1 job | Kept |",
            waivers=("mechanism:poller — webhook loss",))
        self.assertEqual(code, 0, data)

    def test_empty_risk_trace_is_untraced(self):
        code, data = self.design(
            extra="| poller | mechanism | risk: | 1 job | Kept |",
            waivers=("mechanism:poller — webhook loss",))
        self.assertEqual(self.checks(data), ["untraced-mechanism"])

    def test_unregistered_table(self):
        design = BUDGET_DESIGN.format(extra="").replace(
            "## Mechanism Register", "### `Accounts`\nfields...\n\n## Mechanism Register")
        code, data = self.design(design=design)
        self.assertEqual(code, 1)
        self.assertEqual(self.checks(data), ["unregistered-table"])
        self.assertEqual(data["lint_failures"][0]["task"], "Accounts")

    def test_over_budget_tables(self):
        code, data = self.design(extra="| audit_log | table | NFR-1 | 1 table | Kept |")
        self.assertEqual(code, 1)
        self.assertEqual(self.checks(data), ["over-budget-tables"])
        self.assertEqual(data["lint_failures"][0]["task"], "budget")
        self.assertEqual(data["budget"]["kept_tables"], ["webhook_events", "audit_log"])

    def test_tables_waiver_lifts_the_ceiling(self):
        code, data = self.design(
            extra="| audit_log | table | NFR-1 | 1 table | Kept |",
            waivers=("tables+1 — audit trail",))
        self.assertEqual(code, 0, data)

    def test_mechanism_not_in_budget(self):
        code, data = self.design(extra="| outbox | mechanism | NFR-1 | +1 table | Kept |")
        self.assertEqual(code, 1)
        self.assertEqual(self.checks(data), ["mechanism-not-in-budget"])
        self.assertEqual(data["lint_failures"][0]["task"], "outbox")

    def test_mechanism_waiver_admits_it(self):
        code, data = self.design(
            extra="| outbox | mechanism | NFR-1 | +1 table | Kept |",
            waivers=("mechanism:outbox — crash window",))
        self.assertEqual(code, 0, data)

    def test_deferred_rows_count_against_nothing(self):
        code, data = self.design(extra=(
            "| audit_log | table | nice to have | 1 table | Deferred |\n"
            "| outbox | mechanism | | +1 table | Deferred |"))
        self.assertEqual(code, 0, data)
        self.assertEqual(data["budget"]["kept_tables"], ["webhook_events"])


RT_REQ = """## Must Have
- **FR-1** -- users can log in
- ~~**FR-2**~~ -- superseded
## Won't Have
- **FR-9** -- billing
{fence}## Complexity Budget
- **Simple version:** {simple}
- **Max tables:** {max_tables}
- **Mechanisms:** none
- **Waivers:** {waivers}
"""

RT_HEAD = """Covers FR-1 and FR-2.
## Data Model
### users
### audit_log
## Mechanism Register
| Mechanism | Kind | Traces to | Cost | Status |
|---|---|---|---|---|
"""


def rt_req(simple="one users table.", max_tables=1, waivers="none", fence=""):
    return RT_REQ.format(simple=simple, max_tables=max_tables, waivers=waivers,
                         fence=fence)


class TestBudgetRedTeam(unittest.TestCase):
    """The audit's red-team bypasses of 0b8e4c7, each now a named failure."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.reqs = str(self.dir / "requirements.md")
        self.ledger = str(self.dir / "gates.jsonl")

    def tearDown(self):
        self._tmp.cleanup()

    def set_reqs(self, text):
        Path(self.reqs).write_text(text, encoding="utf-8")

    def budget(self):
        code, out, _err = run_cli("--requirements", self.reqs, "--budget",
                                  "--ledger", self.ledger)
        return code, json.loads(out)

    def gate(self, design):
        path = self.dir / "detailed-design.md"
        path.write_text(design, encoding="utf-8")
        code, out, _err = run_cli("--requirements", self.reqs, "--design", str(path),
                                  "--require-budget", "--ledger", self.ledger)
        return code, json.loads(out)

    def add(self, waiver, ledger=True):
        args = ["--requirements", self.reqs, "--add-waiver", waiver]
        if ledger:
            args += ["--ledger", self.ledger]
        code, out, _err = run_cli(*args)
        return code, json.loads(out)

    def checks(self, data):
        return sorted({f["check"] for f in data["lint_failures"]})

    def records(self):
        return [json.loads(line) for line in
                Path(self.ledger).read_text(encoding="utf-8").splitlines()]

    # --- B1: provenance ---------------------------------------------------
    def test_end_to_end_budget_add_waiver_require_budget(self):
        from datetime import datetime
        self.set_reqs(rt_req())
        self.assertEqual(self.budget()[0], 0)
        record = self.records()[-1]
        self.assertTrue(record["budget_hash"])
        self.assertEqual(record["requirements_file"], str(Path(self.reqs).resolve()))
        over = RT_HEAD + ("| users | table | FR-1 | 1 table | Kept |\n"
                          "| audit_log | table | FR-1 | 1 table | Kept |\n"
                          "| outbox | mechanism | FR-1 | worker | Kept |\n")
        code, data = self.gate(over)
        self.assertEqual(code, 1)
        self.assertEqual(self.checks(data), ["mechanism-not-in-budget",
                                             "over-budget-tables"])
        for waiver in ("tables+1 — audit trail", "mechanism:outbox — crash window"):
            code, data = self.add(waiver)
            self.assertEqual(code, 0, data)
        today = datetime.now().date().isoformat()
        text = Path(self.reqs).read_text(encoding="utf-8")
        self.assertIn(f"- **Waivers:** tables+1 — audit trail (approved {today}); "
                      f"mechanism:outbox — crash window (approved {today})", text)
        self.assertEqual(self.records()[-1]["waiver"],
                         f"mechanism:outbox — crash window (approved {today})")
        code, data = self.gate(over)
        self.assertEqual(code, 0, data)
        self.assertEqual(len(data["budget"]["waivers"]), 2)

    def test_require_budget_needs_a_ledger(self):
        self.set_reqs(rt_req())
        path = self.dir / "d.md"
        path.write_text(RT_HEAD, encoding="utf-8")
        code, _out, _err = run_cli("--requirements", self.reqs, "--design", str(path),
                                   "--require-budget")
        self.assertEqual(code, 2)

    def test_budget_unrecorded(self):
        self.set_reqs(rt_req())
        code, data = self.gate(RT_HEAD + "| users | table | FR-1 | 1 | Kept |\n"
                               "| audit_log | table | FR-1 | 1 | Deferred |\n")
        self.assertIn("budget-unrecorded", self.checks(data))

    def test_budget_changed_r_999(self):
        self.set_reqs(rt_req())
        self.budget()
        self.set_reqs(rt_req(max_tables=999))
        code, data = self.gate(RT_HEAD + "| users | table | FR-1 | 1 | Kept |\n"
                               "| audit_log | table | FR-1 | 1 | Kept |\n")
        self.assertEqual(code, 1)
        self.assertEqual(self.checks(data), ["budget-changed"])

    def test_waiver_unrecorded_self_future_ancient(self):
        design = (RT_HEAD + "| users | table | FR-1 | 1 | Kept |\n"
                  "| audit_log | table | FR-1 | 1 | Kept |\n")
        for waiver in ("tables+5 — aria says fine (approved 2026-10-15)",
                       "tables+5 — needed (approved 2099-01-01)",
                       "tables+5 — x (approved 1900-01-01)"):
            self.set_reqs(rt_req())
            self.budget()
            self.set_reqs(rt_req(waivers=waiver))
            code, data = self.gate(design)
            self.assertEqual(code, 1, waiver)
            # Waivers sit outside the hash, and an unrecorded one never
            # lifts the ceiling.
            self.assertEqual(self.checks(data),
                             ["over-budget-tables", "waiver-unrecorded"], waiver)

    def test_add_waiver_rejects_bad_grammar(self):
        self.set_reqs(rt_req())
        for waiver in ("tables+x — more", "mechanism:Outbox — y",
                       "tables+1 — a; b", "tables+1 - plain hyphen", "tables+1 — "):
            code, data = self.add(waiver)
            self.assertEqual(code, 1, waiver)
            self.assertEqual(self.checks(data), ["budget-malformed"], waiver)
        self.assertIn("**Waivers:** none", Path(self.reqs).read_text(encoding="utf-8"))

    def test_add_waiver_usage_and_missing_budget(self):
        self.set_reqs(rt_req())
        self.assertEqual(self.add("tables+1 — x", ledger=False)[0], 2)
        code, _out, _err = run_cli("--requirements", self.reqs, "--add-waiver",
                                   "tables+1 — x", "--budget", "--ledger", self.ledger)
        self.assertEqual(code, 2)
        self.set_reqs("## Must Have\n- **FR-1** -- x\n")
        code, data = self.add("tables+1 — x")
        self.assertEqual((code, self.checks(data)), (1, ["budget-missing"]))

    # --- hidden, duplicate and placeholder budgets -----------------------
    def test_budget_block_hiding_places(self):
        fenced = ("```md\n## Complexity Budget\n- **Simple version:** x\n"
                  "- **Max tables:** 99\n- **Mechanisms:** none\n"
                  "- **Waivers:** none\n```\n")
        commented = fenced.replace("```md\n", "<!--\n").replace("```\n", "-->\n")
        cases = {
            "r_fenced_only": ("## Must Have\n- **FR-1** -- x\n" + fenced,
                              1, ["budget-missing"]),
            "r_comment_only": ("## Must Have\n- **FR-1** -- x\n" + commented,
                               1, ["budget-missing"]),
            "r_dup": (rt_req(max_tables=99) + "## Complexity Budget\n"
                      "- **Simple version:** x\n- **Max tables:** 1\n"
                      "- **Mechanisms:** none\n- **Waivers:** none\n",
                      1, ["budget-malformed"]),
            "r_tbd": (rt_req(simple="TBD"), 1, ["budget-malformed"]),
            "punctuation simple": (rt_req(simple="..."), 1, ["budget-malformed"]),
            "r_fence_first": (rt_req(fence=fenced), 0, []),
        }
        for name, (text, want_code, want_checks) in cases.items():
            self.set_reqs(text)
            code, data = self.budget()
            self.assertEqual((code, self.checks(data)), (want_code, want_checks), name)
        self.assertEqual(data["budget"]["max_tables"], 1)

    # --- register and Data Model -----------------------------------------
    def recorded(self, **kwargs):
        self.set_reqs(rt_req(**kwargs))
        self.assertEqual(self.budget()[0], 0)

    def test_fenced_register_is_not_the_register(self):
        self.recorded()
        decoy = ("```\n## Mechanism Register\n| Mechanism | Kind | Traces to | Cost | Status |\n"
                 "|---|---|---|---|---|\n| users | table | FR-1 | 1 | Kept |\n"
                 "| audit_log | table | FR-1 | 1 | Deferred |\n```\n")
        real = RT_HEAD.replace("## Mechanism Register", decoy + "## Mechanism Register")
        code, data = self.gate(real + "| users | table | FR-1 | 1 | Kept |\n"
                               "| audit_log | table | FR-1 | 1 | Kept |\n")
        self.assertEqual(self.checks(data), ["over-budget-tables"])

    def test_duplicate_register(self):
        self.recorded(max_tables=5)
        rows = "| users | table | FR-1 | 1 | Kept |\n| audit_log | table | FR-1 | 1 | Kept |\n"
        code, data = self.gate(RT_HEAD + rows + RT_HEAD.split("### audit_log\n")[1] + rows)
        self.assertEqual(self.checks(data), ["register-missing"])
        self.assertIn("duplicate", data["lint_failures"][0]["detail"])

    def test_deferred_table_in_design(self):
        self.recorded()
        designs = {
            "d_defer_hide": "| users | table | FR-1 | 1 | Kept |\n"
                            "| audit_log | table | FR-1 | 1 | Deferred |\n",
            "d_dup_defer": "| users | table | FR-1 | 1 | Kept |\n"
                           "| audit_log | table | FR-1 | 1 | Deferred |\n"
                           "| audit_log | mechanism | FR-1 | 1 | Deferred |\n",
            "d_case": "| users | Table | FR-1 | 1 | KEPT |\n"
                      "| AUDIT_LOG | TABLE | fr-1 | 1 | deferred |\n",
        }
        for name, rows in designs.items():
            code, data = self.gate(RT_HEAD + rows)
            self.assertEqual((code, self.checks(data)),
                             (1, ["deferred-table-in-design"]), name)
            self.assertEqual(data["lint_failures"][0]["task"].lower(), "audit_log", name)

    def test_data_model_unstructured(self):
        self.recorded()
        code, data = self.gate("Covers FR-1 and FR-2.\n## Data Model\n| Table | cols |\n|---|---|\n| users | id |\n"
                               "| audit_log | id |\n" + RT_HEAD.split("### audit_log\n")[1]
                               + "| users | table | FR-1 | 1 | Kept |\n")
        self.assertEqual((code, self.checks(data)), (1, ["data-model-unstructured"]))

    def test_placeholder_risk_and_cost(self):
        self.recorded(max_tables=2)
        rows = ("| users | table | FR-1 | 1 | Kept |\n| audit_log | table | FR-1 | 1 | Kept |\n"
                "| outbox | mechanism | risk: | 1 | Kept |\n"
                "| cache | mechanism | risk:   . | 1 | Kept |\n"
                "| queue | mechanism | risk: TBD | 1 | Kept |\n"
                "| poller | mechanism | FR-1 | n/a | Kept |\n")
        code, data = self.gate(RT_HEAD + rows)
        untraced = sorted(f["task"] for f in data["lint_failures"]
                          if f["check"] == "untraced-mechanism")
        self.assertEqual(untraced, ["cache", "outbox", "queue"])
        self.assertEqual([f["task"] for f in data["lint_failures"]
                          if f["check"] == "register-missing"], ["poller"])

    def test_struck_and_wont_have_ids_do_not_trace(self):
        self.recorded(max_tables=5)
        rows = ("| users | table | FR-1 | 1 | Kept |\n| audit_log | table | FR-1 | 1 | Kept |\n"
                "| audit | table | ~~FR-2~~ | 1 | Deferred |\n"
                "| sessions | table | FR-9 | 1 | Kept |\n"
                "| x | table | ~~**FR-2**~~ | 1 | Kept |\n"
                "| y | table | ~~FR-1~~ | 1 | Kept |\n")
        code, data = self.gate(RT_HEAD + rows)
        self.assertEqual(code, 1)
        self.assertEqual(sorted(f["task"] for f in data["lint_failures"]),
                         ["sessions", "x", "y"])
        self.assertEqual(self.checks(data), ["untraced-mechanism"])


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
