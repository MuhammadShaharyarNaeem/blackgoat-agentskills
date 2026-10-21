"""Plan-mode exit-criterion lint tests for check_coverage.py.

A RUNTIME EXIT CRITERION line whose `run `<cmd>`` cannot be parsed fails the
plan gate, because mark_milestone.py --require-exit-capture would refuse it
as exit_criterion_unparseable at milestone close.

Run directly: python test_check_coverage_exit_criterion.py
Or via the CLI: python check_coverage.py --self-test
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import check_coverage as cc  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures"
SCRIPT = Path(__file__).parent / "check_coverage.py"

MALFORMED = ("- [ ] RUNTIME EXIT CRITERION — copy `fixture.md` into `scratch/`, "
             "then run `python --version`; expect exit 0")
WELL_FORMED = "- [ ] RUNTIME EXIT CRITERION — run `python --version`; expect exit 0"
UNBACKTICKED_SETUP = ("- [ ] RUNTIME EXIT CRITERION — copy the fixture into scratch/, "
                      "then run `python --version`; expect exit 0")
PROBE_MENTION = ("- [ ] RUNTIME PROBE: justification: a stdlib CLI; its "
                 "RUNTIME EXIT CRITERION is read directly, out of process.")
PROBE_LINE = ("- [ ] RUNTIME PROBE: justification: a stdlib CLI with no service; "
              "its exit code is read directly, out of process.")
MILESTONE_TITLE = "Milestone 1 — Styling [UI] [vs:none]"


def milestone_plan(*criterion_lines):
    return "\n".join([
        f"### {MILESTONE_TITLE}",
        "",
        "### Checkpoint: Milestone 1",
        "",
        "- [ ] All tests pass",
        *criterion_lines,
        PROBE_LINE,
        "- [ ] Review with human before proceeding",
        "",
    ])


def exit_criterion_failures(plan_text):
    return [f for f in cc.lint_runtime_criterion(plan_text)
            if "exit_criterion_unparseable" in f["detail"]]


class ExitCriterionLintTest(unittest.TestCase):
    def test_malformed_criterion_fails_naming_the_line(self):
        failures = exit_criterion_failures(milestone_plan(MALFORMED))
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["check"], "runtime-criterion")
        self.assertEqual(failures[0]["task"], MILESTONE_TITLE)
        self.assertIn(MALFORMED, failures[0]["detail"])
        self.assertIn("--require-exit-capture", failures[0]["detail"])

    def test_well_formed_criterion_passes(self):
        self.assertEqual(exit_criterion_failures(milestone_plan(WELL_FORMED)), [])

    def test_unbackticked_setup_before_run_parses(self):
        self.assertEqual(
            exit_criterion_failures(milestone_plan(UNBACKTICKED_SETUP)), [])

    def test_probe_line_mentioning_the_phrase_is_not_a_criterion(self):
        self.assertEqual(
            exit_criterion_failures(milestone_plan(PROBE_MENTION)), [])

    def test_fenced_criterion_is_not_read(self):
        self.assertEqual(
            exit_criterion_failures(milestone_plan(
                "```", "- [ ] RUNTIME EXIT CRITERION: tbd", "```")), [])

    def test_quoted_commandless_criterion_fails(self):
        failures = exit_criterion_failures(
            milestone_plan("> RUNTIME EXIT CRITERION: tbd"))
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["check"], "runtime-criterion")

    def test_checked_criterion_with_command_passes(self):
        self.assertEqual(
            exit_criterion_failures(
                milestone_plan("- [x] RUNTIME EXIT CRITERION — run `a b`")), [])


class ExitCriterionCliTest(unittest.TestCase):
    """End to end on the happy fixture, the same shape as the bug's repro."""

    def _plan_with(self, criterion):
        body = (FIXTURES / "happy" / "plan.md").read_text(encoding="utf-8")
        body = body.replace(
            "## Task 3:", f"### {MILESTONE_TITLE}\n\n## Task 3:", 1)
        return body.rstrip("\n") + (
            "\n\n### Checkpoint: Milestone 1\n\n"
            "- [ ] All tests pass\n"
            f"{criterion}\n"
            f"{PROBE_LINE}\n"
            "- [ ] Review with human before proceeding\n")

    def _run(self, criterion):
        with tempfile.TemporaryDirectory() as work:
            plan = Path(work) / "plan.md"
            plan.write_text(self._plan_with(criterion), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT),
                 "--requirements", str(FIXTURES / "happy" / "requirements.md"),
                 "--plan", str(plan)],
                capture_output=True, text=True, encoding="utf-8")
        return result.returncode, json.loads(result.stdout)

    def test_cli_well_formed_passes_and_malformed_fails(self):
        good_code, good = self._run(WELL_FORMED)
        self.assertEqual(good_code, 0, good["lint_failures"])
        bad_code, bad = self._run(MALFORMED)
        self.assertEqual(bad_code, 1)
        self.assertEqual(
            [f["check"] for f in bad["lint_failures"]
             if "exit_criterion_unparseable" in f["detail"]],
            ["runtime-criterion"])


if __name__ == "__main__":
    unittest.main()
