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
        text = "- FR-1: BLOCKED — no harness\n- FR-1: PASS — harness built, retested\n"
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
