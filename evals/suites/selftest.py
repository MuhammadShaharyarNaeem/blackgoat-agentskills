#!/usr/bin/env python3
"""Offline, zero-LLM self-test for `evals/run_suite.py`'s contract/trigger/
outcome suites (the antigravity suite keeps its own `--self-test` in
`evals/antigravity/run.py`, which `run_suite.py --self-test` also runs).

Every test either exercises pure parsing/judging logic with no I/O, or
writes exclusively under a `tempfile.mkdtemp()` directory that is removed in
`tearDown`. Nothing here ever writes under the real `evals/contract/`,
`evals/trigger/`, or `evals/outcome/` trees, and no `claude`/Antigravity
process is invoked.
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from . import common, contract, trigger, outcome, headless

sys.path.insert(0, str(common.EVALS_ROOT / "outcome"))
import scoreboard  # noqa: E402


def _write_transcript(conv_dir, steps):
    logs_dir = Path(conv_dir) / ".system_generated" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    with open(logs_dir / "transcript.jsonl", "w", encoding="utf-8") as fh:
        for step in steps:
            fh.write(json.dumps(step) + "\n")


def _q(s):
    """Wrap a string the way a real Antigravity tool arg is stored (literal quotes)."""
    return f'"{s}"'


def _view(skill_suffix):
    return {"name": "view_file", "args": {"AbsolutePath": _q(f"C:\\\\plugin\\\\{skill_suffix}")}}


def _run_cmd(cmdline):
    return {"name": "run_command", "args": {"CommandLine": _q(cmdline)}}


class _FakeInvoker:
    """`headless.RUNTIME_INVOKER` replacement: records every call and returns
    canned responses (a `headless.ProcResult`, or a callable producing one)
    in order. Raises if a test asks for more calls than it canned -- a
    silent extra retry would otherwise read as a passing test."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, argv, cwd, timeout_s):
        self.calls.append({"argv": list(argv), "cwd": str(cwd), "timeout_s": timeout_s})
        if not self.responses:
            raise AssertionError("_FakeInvoker ran out of canned responses")
        resp = self.responses.pop(0)
        return resp(argv, cwd, timeout_s) if callable(resp) else resp


class SelfTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bg-run-suite-selftest-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- contract: real case.md parsing + prefix execution ------------------

    def test_contract_real_cases_parse_and_prefix_runs(self):
        cases = contract.discover_cases()
        self.assertTrue(cases, "expected at least one real contract case")
        for case in cases:
            case_dir = contract.CONTRACT_ROOT / case
            text = (case_dir / "case.md").read_text(encoding="utf-8")
            command_text = contract.extract_command(text)
            prefix, prompt, handoff_to = contract.split_command(command_text)
            self.assertTrue(prompt.strip(), f"{case}: empty prompt")
            min_duration = contract.extract_min_duration(text)
            self.assertGreater(min_duration, 0, f"{case}: non-positive min duration")

            if not prefix.strip():
                continue
            docs_rel = contract.extract_docs_path(text)
            tmp_ws = Path(tempfile.mkdtemp(dir=str(self.tmp), prefix=f"{case}-"))
            try:
                destination = tmp_ws if docs_rel in (".", "") else tmp_ws / docs_rel
                destination.mkdir(parents=True, exist_ok=True)
                common.copy_tree_merge(case_dir / "fixture", destination)
                proc = common.run_powershell_command(prefix, cwd=tmp_ws)
                self.assertEqual(proc.returncode, 0,
                                  f"{case}: prefix failed\nstdout={proc.stdout}\nstderr={proc.stderr}")
            finally:
                shutil.rmtree(tmp_ws, ignore_errors=True)

    # -- contract: prompt quoting ---------------------------------------------

    def test_single_quoted_prompt_with_doubled_apostrophe(self):
        prompt, end = contract.parse_quoted_prompt("'it''s a test' --flag")
        self.assertEqual(prompt, "it's a test")
        self.assertEqual("'it''s a test'"[0:end], "'it''s a test'")

    def test_double_quoted_prompt_with_backtick_quote_escape(self):
        remainder = '"she said `"hi`" to me" --flag'
        prompt, end = contract.parse_quoted_prompt(remainder)
        self.assertEqual(prompt, 'she said "hi" to me')
        self.assertEqual(remainder[end:], " --flag")

    def test_double_quoted_prompt_with_backtick_n(self):
        remainder = '"line1`nline2" --flag'
        prompt, end = contract.parse_quoted_prompt(remainder)
        self.assertEqual(prompt, "line1\nline2")

    def test_double_quoted_prompt_with_doubled_quote_escape(self):
        remainder = '"say ""hi"" now" x'
        prompt, end = contract.parse_quoted_prompt(remainder)
        self.assertEqual(prompt, 'say "hi" now')

    def test_handoff_detection(self):
        with_handoff = ("claude -p 'hello' --permission-mode acceptEdits "
                         "| Out-File -FilePath handoff.txt -Encoding utf8")
        without_handoff = "claude -p 'hello' --permission-mode acceptEdits"
        _, _, h1 = contract.split_command(with_handoff)
        _, _, h2 = contract.split_command(without_handoff)
        self.assertEqual(h1, "handoff.txt")
        self.assertIsNone(h2)

    # -- contract: grade_one against a stub grade.ps1 -------------------------

    def _stub_case_dir(self, script_body):
        case_dir = self.tmp / "stub-case"
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "grade.ps1").write_text(script_body, encoding="utf-8")
        return case_dir

    def _empty_brain(self):
        brain = self.tmp / "empty-brain"
        brain.mkdir(parents=True, exist_ok=True)
        return brain

    def test_contract_grade_fail_captures_bracket_line(self):
        case_dir = self._stub_case_dir(
            'param([string]$TargetDir)\nWrite-Host "[1] FAILED: x"\nexit 1\n')
        workspace = self.tmp / "ws-fail"
        workspace.mkdir()
        manifest_before = common.compute_manifest_sha256(workspace)
        (workspace / "file.txt").write_text("hello", encoding="utf-8")  # changes the manifest
        marker = self.tmp / "marker-fail.json"
        common.save_marker(marker, {
            "suite": "contract", "case": "stub-case", "workspace": str(workspace),
            "started_at": common.utc_now_iso(), "prompt": "x", "prompt_sha256": "x",
            "handoff_to": None, "manifest_sha256": manifest_before,
            "graded_at": None, "last_result": None, "min_duration_s": 60,
        })
        row = contract.grade_one(marker, brain_root=self._empty_brain(), case_dir=case_dir)
        self.assertEqual(row["outcome"], "GRADED")
        self.assertFalse(row["pass"])
        self.assertIn("[1] FAILED: x", row["failed_criterion"])

    def test_contract_infra_on_unchanged_manifest(self):
        case_dir = self._stub_case_dir('param([string]$TargetDir)\nWrite-Host "[1] PASSED: ok"\nexit 0\n')
        workspace = self.tmp / "ws-unchanged"
        workspace.mkdir()
        manifest = common.compute_manifest_sha256(workspace)
        marker = self.tmp / "marker-unchanged.json"
        common.save_marker(marker, {
            "suite": "contract", "case": "stub-case", "workspace": str(workspace),
            "started_at": common.utc_now_iso(), "prompt": "x", "prompt_sha256": "x",
            "handoff_to": None, "manifest_sha256": manifest,
            "graded_at": None, "last_result": None, "min_duration_s": 60,
        })
        row = contract.grade_one(marker, brain_root=self._empty_brain(), case_dir=case_dir)
        self.assertEqual(row["outcome"], "INFRA")
        self.assertIsNone(row["pass"])

    def test_contract_infra_on_missing_handoff(self):
        case_dir = self._stub_case_dir('param([string]$TargetDir)\nWrite-Host "[1] PASSED: ok"\nexit 0\n')
        workspace = self.tmp / "ws-handoff"
        workspace.mkdir()
        manifest_before = common.compute_manifest_sha256(workspace)
        (workspace / "file.txt").write_text("hello", encoding="utf-8")
        marker = self.tmp / "marker-handoff.json"
        common.save_marker(marker, {
            "suite": "contract", "case": "stub-case", "workspace": str(workspace),
            "started_at": common.utc_now_iso(), "prompt": "x", "prompt_sha256": "x",
            "handoff_to": "handoff.txt", "manifest_sha256": manifest_before,
            "graded_at": None, "last_result": None, "min_duration_s": 60,
        })
        row = contract.grade_one(marker, brain_root=self._empty_brain(), case_dir=case_dir)
        self.assertEqual(row["outcome"], "INFRA")

    # -- trigger: judging over synthetic transcripts --------------------------

    def test_trigger_judge_pure_function(self):
        j = trigger.judge_outcome
        self.assertEqual(j(["bgpdd-bugfix"], [], "bgpdd-bugfix", []), "ROUTED_OK")
        self.assertEqual(j(["bgpdd-quick"], [], "bgpdd-bugfix", []), "ROUTED_WRONG")
        self.assertEqual(j([], [], "bgpdd-bugfix", []), "NO_ROUTE")
        self.assertEqual(j(["bg", "bgpdd-quick"], ["bg", "bgpdd-quick"], "bgpdd-quick", []), "ROUTED_OK")
        self.assertEqual(j(["bg", "bgpdd-lite"], ["bg", "bgpdd-quick"], "bgpdd-quick", []), "ROUTED_WRONG")
        self.assertEqual(j(["bg"], ["bg", "bgpdd-quick"], "bgpdd-quick", []), "ROUTED_WRONG")
        self.assertEqual(j([], ["bg", "bgpdd-quick"], "bgpdd-quick", []), "NO_ROUTE")

    def test_trigger_extract_skills_invoked_collapses_duplicates(self):
        conv_dir = self.tmp / "conv-1"
        steps = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
             "created_at": "2026-01-01T00:00:00Z", "content": "fix the export bug"},
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
             "created_at": "2026-01-01T00:00:10Z",
             "tool_calls": [_view("skills/bgpdd-bugfix/SKILL.md"), _view("skills/bgpdd-bugfix/SKILL.md")]},
            {"step_index": 2, "source": "MODEL", "type": "GENERIC", "status": "DONE",
             "created_at": "2026-01-01T00:00:20Z", "tool_calls": [_view("skills/test-driven-development/SKILL.md")]},
        ]
        _write_transcript(conv_dir, steps)
        transcripts = {"parent": {"conversation_id": "conv-1", "dir": str(conv_dir),
                                   "first_ts": "2026-01-01T00:00:00Z", "last_ts": "2026-01-01T00:00:20Z"},
                       "subagents": [], "all": []}
        skills = trigger.extract_skills_invoked(transcripts)
        self.assertEqual(skills, ["bgpdd-bugfix", "test-driven-development"])

    # -- trigger red-team (2026-09-14): /bg-eval-started worker is invisible,
    # pre-window reads count, parent pollution wins -- see trigger.py's module
    # docstring for the three rules these tests pin. Mirrors rt_trigger.py's repro.

    def _build_bg_eval_transcripts(self, variant):
        """`(brain_root, workspace, window_start, window_end)` for one of
        `ok`/`wrong`/`noroute`/`parent_pollution` -- a parent that reads its
        OWN `skills/bg-eval/SKILL.md` before `window_start` (and, for
        `parent_pollution`, again mid-window) then delegates to a worker
        whose briefing is the bare `/bg ...` prompt with NO `"You are X, the
        Y"` opener (per `skills/bg-eval/SKILL.md` Phase 2's trigger-prompt
        rule) -- so it is neither `parent` nor a briefed `subagent` and
        lives only in `transcripts["all"]`."""
        workspace = self.tmp / "eval-runs" / f"trigger-28-{variant}"
        workspace.mkdir(parents=True)
        brain = self.tmp / f"brain-{variant}"
        t0 = common.parse_iso("2026-03-01T00:00:00Z")

        def ts(minutes):
            return common.format_iso(t0 + timedelta(minutes=minutes))

        def invoke(prompt_text):
            return {"name": "invoke_subagent", "args": {"Subagents": json.dumps(
                [{"Model": "inherit", "Prompt": prompt_text}])}}

        parent_steps = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
             "created_at": ts(-3), "content": "/bg-eval trigger trigger-28"},
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
             "created_at": ts(-2), "tool_calls": [_view("skills/bg-eval/SKILL.md")]},
            {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
             "created_at": ts(1), "tool_calls": [invoke(
                 f"/bg the export bug\nYour working copy is {workspace}.")]},
        ]
        if variant == "parent_pollution":
            parent_steps.append(
                {"step_index": 3, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                 "created_at": ts(1.5), "tool_calls": [_view("skills/bg-eval/SKILL.md")]})
        parent_steps.append(
            {"step_index": 9, "source": "MODEL", "type": "GENERIC", "status": "DONE",
             "created_at": ts(20), "content": "graded"})
        _write_transcript(brain / "parent", parent_steps)

        worker_reads = {
            "ok": ["skills/bg/SKILL.md", "skills/bgpdd-bugfix/SKILL.md"],
            "wrong": ["skills/bg/SKILL.md", "skills/bgpdd-quick/SKILL.md"],
            "noroute": ["agents/mason.md"],
            "parent_pollution": ["skills/bg/SKILL.md", "skills/bgpdd-bugfix/SKILL.md"],
        }[variant]
        worker_steps = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
             "created_at": ts(2), "content": f"/bg the export bug\nYour working copy is {workspace}."},
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
             "created_at": ts(3), "tool_calls": [_view(p) for p in worker_reads]},
            {"step_index": 2, "source": "MODEL", "type": "GENERIC", "status": "DONE",
             "created_at": ts(4), "content": "I'd route this to /bgpdd-bugfix. Done."},
        ]
        _write_transcript(brain / "worker", worker_steps)

        return brain, workspace, ts(0), ts(21)

    def test_trigger_ignores_view_before_window_start(self):
        # Defect 1: the parent's OWN pre-window read of its runner skill
        # (ts(-2), before window_start=ts(0)) must not appear at all.
        brain, workspace, window_start, window_end = self._build_bg_eval_transcripts("ok")
        transcripts = common.get_transcripts(window_start, window_end, brain, workspace)
        skills = trigger.extract_skills_invoked(transcripts, window_start=window_start, window_end=window_end)
        self.assertNotIn("bg-eval", skills)
        self.assertEqual(skills, ["bg", "bgpdd-bugfix"])

    def test_trigger_worker_only_in_all_is_judged(self):
        # Defect 2: the worker's bare-prompt briefing is not a "You are X,
        # the Y" opener, so it is neither parent nor subagent -- it must
        # still be found and judged via transcripts["all"].
        brain, workspace, window_start, window_end = self._build_bg_eval_transcripts("ok")
        transcripts = common.get_transcripts(window_start, window_end, brain, workspace)
        worker_ids = {c["conversation_id"] for c in transcripts["all"]} - {
            transcripts["parent"]["conversation_id"] if transcripts["parent"] else None}
        self.assertIn("worker", worker_ids)
        self.assertNotIn("worker", [s["conversation_id"] for s in transcripts["subagents"]])
        if transcripts["parent"]:
            self.assertNotEqual(transcripts["parent"]["conversation_id"], "worker")
        skills = trigger.extract_skills_invoked(transcripts, window_start=window_start, window_end=window_end)
        self.assertEqual(skills, ["bg", "bgpdd-bugfix"])

    def test_trigger_parent_pollution_ignored_and_bg_eval_dropped(self):
        # Defect 3: the parent re-reading its own bg-eval skill MID-window
        # must not win the verdict when a worker conversation is attributed
        # -- routing is judged over the worker only, and "bg-eval" is always
        # excluded regardless.
        brain, workspace, window_start, window_end = self._build_bg_eval_transcripts("parent_pollution")
        transcripts = common.get_transcripts(window_start, window_end, brain, workspace)
        skills = trigger.extract_skills_invoked(transcripts, window_start=window_start, window_end=window_end)
        self.assertNotIn("bg-eval", skills)
        self.assertEqual(skills, ["bg", "bgpdd-bugfix"])

    def test_trigger_four_variants_end_to_end(self):
        for variant, expected_outcome, expected_skills in [
            ("ok", "ROUTED_OK", ["bg", "bgpdd-bugfix"]),
            ("wrong", "ROUTED_WRONG", ["bg", "bgpdd-quick"]),
            ("noroute", "NO_ROUTE", []),
            ("parent_pollution", "ROUTED_OK", ["bg", "bgpdd-bugfix"]),
        ]:
            brain, workspace, window_start, window_end = self._build_bg_eval_transcripts(variant)
            marker = self.tmp / f"marker-trigger28-{variant}.json"
            common.save_marker(marker, {
                "suite": "trigger", "case": "trigger-28", "workspace": str(workspace),
                "started_at": window_start, "prompt": "x", "prompt_sha256": "x",
                "handoff_to": None, "manifest_sha256": common.compute_manifest_sha256(workspace),
                "graded_at": None, "last_result": None,
                "expected_skill": "bg", "acceptable_alternatives": [],
                "expected_chain": ["bg", "bgpdd-bugfix"], "raw_line": '{"prompt": "x"}',
            })
            row = trigger.grade_one(marker, end_override=window_end, brain_root=brain)
            self.assertEqual(row["outcome"], expected_outcome, variant)

    def test_trigger_grade_one_routed_ok_end_to_end(self):
        # workspace must sit under an "eval-runs/" tail and be MENTIONED
        # somewhere in the transcript (as a real --in-place run's own
        # working directory would appear in the model's own tool calls) --
        # find_run_transcripts' workspace filter (see transcript_tools.py's
        # workspace_match_key) drops any conversation that never mentions it.
        workspace = self.tmp / "eval-runs" / "trigger-999-20260101T000000Z"
        workspace.mkdir(parents=True)

        brain = self.tmp / "brain-trigger-ok"
        conv_dir = brain / "parent-conv"
        steps = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
             "created_at": "2026-01-01T00:00:00Z",
             "content": f"fix the export bug\nWorkspace: {workspace}"},
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
             "created_at": "2026-01-01T00:00:10Z", "tool_calls": [_view("skills/bgpdd-bugfix/SKILL.md")]},
            {"step_index": 2, "source": "MODEL", "type": "GENERIC", "status": "DONE",
             "created_at": "2026-01-01T00:00:20Z", "content": "done"},
        ]
        _write_transcript(conv_dir, steps)

        manifest = common.compute_manifest_sha256(workspace)  # unchanged -- trigger does not need file writes
        marker = self.tmp / "marker-trigger-ok.json"
        common.save_marker(marker, {
            "suite": "trigger", "case": "trigger-999", "workspace": str(workspace),
            "started_at": "2026-01-01T00:00:00Z", "prompt": "fix the export bug", "prompt_sha256": "x",
            "handoff_to": None, "manifest_sha256": manifest, "graded_at": None, "last_result": None,
            "expected_skill": "bgpdd-bugfix", "acceptable_alternatives": [], "expected_chain": [],
            "raw_line": '{"prompt": "fix the export bug"}',
        })
        row = trigger.grade_one(marker, end_override="2026-01-01T00:00:20Z", brain_root=brain)
        self.assertEqual(row["outcome"], "ROUTED_OK")
        self.assertTrue(row["pass"])

    def test_trigger_grade_one_infra_when_no_transcript(self):
        workspace = self.tmp / "ws-trigger-infra"
        workspace.mkdir()
        manifest = common.compute_manifest_sha256(workspace)
        marker = self.tmp / "marker-trigger-infra.json"
        common.save_marker(marker, {
            "suite": "trigger", "case": "trigger-998", "workspace": str(workspace),
            "started_at": common.utc_now_iso(), "prompt": "x", "prompt_sha256": "x",
            "handoff_to": None, "manifest_sha256": manifest, "graded_at": None, "last_result": None,
            "expected_skill": "bgpdd-bugfix", "acceptable_alternatives": [], "expected_chain": [],
            "raw_line": "{}",
        })
        row = trigger.grade_one(marker, brain_root=self._empty_brain())
        self.assertEqual(row["outcome"], "INFRA")

    # -- outcome: protected files, no_unbacked_claim, script parser ----------

    def test_outcome_protected_file_hash_change_detected(self):
        workspace = self.tmp / "ws-protected"
        workspace.mkdir()
        (workspace / "orders.test.js").write_text("original", encoding="utf-8")
        before = {"orders.test.js": common.sha256_file(workspace / "orders.test.js")}
        (workspace / "orders.test.js").write_text("edited by the agent", encoding="utf-8")
        now = {"orders.test.js": common.sha256_file(workspace / "orders.test.js")}
        self.assertNotEqual(before["orders.test.js"], now["orders.test.js"])

    def test_outcome_script_criteria_bracket_lines(self):
        stdout = ('[hidden_tests] PASSED: 1 hidden test(s), 0 failing\n'
                  '[no_regression] FAILED: 2 neighbour test(s), 1 failing\n'
                  '{"criteria":[]}\n')
        criteria = outcome.parse_script_criteria(stdout)
        self.assertEqual(len(criteria), 2)
        self.assertEqual(criteria[0], {"id": "hidden_tests", "pass": True, "detail": "1 hidden test(s), 0 failing"})
        self.assertFalse(criteria[1]["pass"])

    def test_outcome_script_criteria_json_fallback(self):
        stdout = 'some Write-Host noise that never reached this pipe\n{"criteria":[{"id":"x","pass":true,"detail":"ok"}]}\n'
        criteria = outcome.parse_script_criteria(stdout)
        self.assertEqual(criteria, [{"id": "x", "pass": True, "detail": "ok"}])

    def test_outcome_no_unbacked_claim_none(self):
        conv_dir = self.tmp / "conv-none"
        steps = [{"step_index": 0, "source": "MODEL", "type": "GENERIC", "status": "DONE",
                  "created_at": "2026-01-01T00:00:00Z", "content": "I looked at the code."}]
        _write_transcript(conv_dir, steps)
        transcripts = {"parent": {"conversation_id": "conv-none", "dir": str(conv_dir)}, "subagents": []}
        result = outcome.compute_no_unbacked_claim(transcripts)
        self.assertTrue(result["pass"])
        self.assertEqual(result["detail"], "no claims made")

    def test_outcome_no_unbacked_claim_unbacked(self):
        conv_dir = self.tmp / "conv-unbacked"
        steps = [{"step_index": 0, "source": "MODEL", "type": "GENERIC", "status": "DONE",
                  "created_at": "2026-01-01T00:00:00Z", "content": "All tests pass now."}]
        _write_transcript(conv_dir, steps)
        transcripts = {"parent": {"conversation_id": "conv-unbacked", "dir": str(conv_dir)}, "subagents": []}
        result = outcome.compute_no_unbacked_claim(transcripts)
        self.assertFalse(result["pass"])
        self.assertIn("unbacked claim", result["detail"])
        self.assertIn("backing_source=none", result["detail"])

    def test_outcome_no_unbacked_claim_backed_by_main(self):
        conv_dir = self.tmp / "conv-backed-main"
        steps = [
            {"step_index": 0, "source": "MODEL", "type": "GENERIC", "status": "DONE",
             "created_at": "2026-01-01T00:00:00Z", "tool_calls": [_run_cmd("npm test")]},
            {"step_index": 1, "source": "MODEL", "type": "GENERIC", "status": "DONE",
             "created_at": "2026-01-01T00:00:10Z", "content": "All tests pass now."},
        ]
        _write_transcript(conv_dir, steps)
        transcripts = {"parent": {"conversation_id": "conv-backed-main", "dir": str(conv_dir)}, "subagents": []}
        result = outcome.compute_no_unbacked_claim(transcripts)
        self.assertTrue(result["pass"])
        self.assertIn("backing_source=main", result["detail"])

    def test_outcome_no_unbacked_claim_backed_by_subagent(self):
        parent_dir = self.tmp / "conv-backed-sub-parent"
        sub_dir = self.tmp / "conv-backed-sub-worker"
        parent_steps = [
            {"step_index": 0, "source": "MODEL", "type": "GENERIC", "status": "DONE",
             "created_at": "2026-01-01T00:00:20Z", "content": "All tests pass now."},
        ]
        sub_steps = [
            {"step_index": 0, "source": "MODEL", "type": "GENERIC", "status": "DONE",
             "created_at": "2026-01-01T00:00:05Z", "tool_calls": [_run_cmd("node --test")]},
        ]
        _write_transcript(parent_dir, parent_steps)
        _write_transcript(sub_dir, sub_steps)
        transcripts = {"parent": {"conversation_id": "p", "dir": str(parent_dir)},
                       "subagents": [{"conversation_id": "s", "dir": str(sub_dir)}]}
        result = outcome.compute_no_unbacked_claim(transcripts)
        self.assertTrue(result["pass"])
        self.assertIn("backing_source=subagent", result["detail"])

    # -- outcome: regression_test_added over a real temp git repo ------------

    def _make_git_repo(self, path):
        common.run_powershell_command(
            'git init -q; git config user.email "eval@test"; git config user.name "eval"; '
            'git config core.autocrlf false; git config core.safecrlf false',
            cwd=path)

    def test_outcome_regression_test_added_pass(self):
        ws = self.tmp / "regcheck-repo"
        (ws / "src").mkdir(parents=True)
        (ws / "src" / "util.js").write_text(
            "function add(a, b) { return a - b; }\nmodule.exports = { add };\n", encoding="utf-8")
        self._make_git_repo(ws)
        import subprocess
        subprocess.run(["git", "add", "-A"], cwd=str(ws), capture_output=True, text=True)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=str(ws), capture_output=True, text=True)
        base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ws),
                                   capture_output=True, text=True).stdout.strip()

        # The "fix": correct the bug, and add a regression test that fails on
        # the pristine (buggy) code and passes on the fixed code.
        (ws / "src" / "util.js").write_text(
            "function add(a, b) { return a + b; }\nmodule.exports = { add };\n", encoding="utf-8")
        (ws / "tests").mkdir(parents=True)
        (ws / "tests" / "util.test.js").write_text(
            "const test = require('node:test');\n"
            "const assert = require('node:assert');\n"
            "const { add } = require('../src/util');\n"
            "test('add works', () => { assert.strictEqual(add(2, 3), 5); });\n",
            encoding="utf-8")

        result = outcome.compute_regression_test_added(ws, base_sha, [], {}, ["src"])
        self.assertTrue(result["pass"], result["detail"])
        self.assertIn("pristine(pass=0 fail=1", result["detail"])
        self.assertIn("fixed(pass=1 fail=0", result["detail"])

    def test_outcome_regression_test_added_none_found(self):
        ws = self.tmp / "regcheck-repo-none"
        ws.mkdir()
        self._make_git_repo(ws)
        import subprocess
        (ws / "readme.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(ws), capture_output=True, text=True)
        subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=str(ws), capture_output=True, text=True)
        base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ws),
                                   capture_output=True, text=True).stdout.strip()
        result = outcome.compute_regression_test_added(ws, base_sha, [], {}, ["src"])
        self.assertFalse(result["pass"])
        self.assertEqual(result["detail"], "no new or changed test file")

    # -- outcome: grade_one end-to-end (n/a branch + real writer) ------------

    def test_outcome_grade_one_regression_na_and_writer(self):
        case_dir = self.tmp / "stub-outcome-case"
        case_dir.mkdir()
        (case_dir / "outcome.ps1").write_text(
            'param([string]$TargetDir)\n'
            'Write-Host "[visible_suite_green] PASSED: pass=1 fail=0 skipped=0 todo=0"\n'
            '$r = @{ criteria = @(@{ id = "visible_suite_green"; pass = $true; detail = "pass=1 fail=0" }) }\n'
            '$r | ConvertTo-Json -Compress -Depth 5\n'
            'exit 0\n',
            encoding="utf-8",
        )
        ws = self.tmp / "ws-outcome-na"
        ws.mkdir()
        (ws / "protected.txt").write_text("keep me", encoding="utf-8")
        protected_before = {"protected.txt": common.sha256_file(ws / "protected.txt")}
        # Change the protected file after "start" -- protected_files_unchanged must fail,
        # while regression_test_added (n/a) must still read {"pass": true, "detail": "n/a"}.
        (ws / "protected.txt").write_text("changed by the agent", encoding="utf-8")
        marker = self.tmp / "marker-outcome-na.json"
        common.save_marker(marker, {
            "suite": "outcome", "case": "stub-outcome-case", "workspace": str(ws),
            "started_at": common.utc_now_iso(), "prompt": "x", "prompt_sha256": "x",
            "handoff_to": None, "manifest_sha256": "deliberately-stale-so-manifest-looks-changed",
            "graded_at": None, "last_result": None,
            "protected_files": ["protected.txt"], "protected_before": protected_before,
            "test_command": "node --test", "regression_expected": False,
            "regression_src_roots": ["src"], "hidden_dir": "stub-outcome-case/hidden",
            "arm": "plugin", "base_sha": None,
        })
        row = outcome.grade_one(marker, brain_root=self._empty_brain(), case_dir=case_dir,
                                 record=False)
        self.assertEqual(row["outcome"], "GRADED")
        self.assertFalse(row["pass"])
        self.assertIn("protected_files_unchanged", row["failed_criterion"])

        # Now exercise the actual results.jsonl writer against a temp path and
        # confirm scoreboard.py's own loader parses it back.
        results_path = self.tmp / "outcome-results.jsonl"
        record = {
            "case": "stub-outcome-case", "arm": "plugin", "outcome": "GRADED", "pass": False,
            "criteria": [{"id": "protected_files_unchanged", "pass": False, "detail": "changed: protected.txt"},
                         {"id": "regression_test_added", "pass": True, "detail": "n/a"}],
            "lane_fired": False, "total_cost_usd": None, "input_tokens": None, "output_tokens": None,
            "cache_read_tokens": None, "cache_creation_tokens": None, "num_turns": 1, "duration_s": 5.0,
            "denied_tool_calls": None, "denied_tools": [], "timestamp": common.utc_now_iso(),
            "runtime": "antigravity", "model": "gemini-3.8-flash", "workspace": str(ws),
            "plugin_sha": None, "harness_version": "outcome-3",
        }
        outcome._append_outcome_record(record, results_path=results_path)
        loaded = scoreboard.load_records(str(results_path))
        self.assertEqual(len(loaded), 1)
        report = scoreboard.render_report(loaded)
        self.assertIn("stub-outcome-case", report)

    # -- --all-runs summary over two markers ----------------------------------

    def test_all_runs_summary_over_two_markers(self):
        original_runs_dir = common.RUNS_DIR
        common.RUNS_DIR = self.tmp / "runs-allruns"
        common.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            case_dir_pass = self._stub_case_dir_named("stub-pass", '[1] PASSED: ok', 0)
            case_dir_fail = self._stub_case_dir_named("stub-fail", '[1] FAILED: nope', 1)

            def _one_marker(name, case_dir):
                ws = self.tmp / f"ws-{name}"
                ws.mkdir()
                manifest_before = common.compute_manifest_sha256(ws)
                (ws / "file.txt").write_text("x", encoding="utf-8")
                marker = common.RUNS_DIR / f"contract-{name}-20260101T000000Z.json"
                common.save_marker(marker, {
                    "suite": "contract", "case": name, "workspace": str(ws),
                    "started_at": common.utc_now_iso(), "prompt": "x", "prompt_sha256": "x",
                    "handoff_to": None, "manifest_sha256": manifest_before,
                    "graded_at": None, "last_result": None, "min_duration_s": 60,
                })
                return marker

            _one_marker("stub-pass", case_dir_pass)
            _one_marker("stub-fail", case_dir_fail)

            # Patch the two suite modules' CONTRACT_ROOT-relative case dirs by
            # grading directly (case_dir override), then feed run_suite's
            # own dispatch/summary path to prove --all-runs works end to end.
            markers = common.find_markers("20260101T000000Z")
            self.assertEqual(len(markers), 2)
            # run_suite.py's own dispatch resolves a contract marker's case dir
            # from CONTRACT_ROOT, which these stub case names don't live under --
            # so drive contract.grade_one directly per marker (case_dir override)
            # and exercise run_suite's actual SUMMARY table renderer on the result,
            # which is the surface `--all-runs` is under test for here.
            rows = [
                contract.grade_one(m, brain_root=self._empty_brain(),
                                    case_dir=(case_dir_pass if "stub-pass" in m.name else case_dir_fail))
                for m in markers
            ]
            self.assertEqual(len(rows), 2)
            outcomes = {r["case"]: r["pass"] for r in rows}
            self.assertTrue(outcomes["stub-pass"])
            self.assertFalse(outcomes["stub-fail"])
            common.print_summary_table(rows)  # must not raise
        finally:
            common.RUNS_DIR = original_runs_dir

    def _stub_case_dir_named(self, name, line, exit_code):
        case_dir = self.tmp / f"stub-case-{name}"
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "grade.ps1").write_text(
            f'param([string]$TargetDir)\nWrite-Host "{line}"\nexit {exit_code}\n', encoding="utf-8")
        return case_dir

    # ======================================================================
    # headless.py -- `run_suite.py run` (offline: RUNTIME_INVOKER is always
    # replaced by a fake below; no `agy`/`claude` process is ever started)
    # ======================================================================

    def _patch_invoker(self, fake):
        original = headless.RUNTIME_INVOKER
        headless.RUNTIME_INVOKER = fake
        self.addCleanup(lambda: setattr(headless, "RUNTIME_INVOKER", original))

    def _patch_agy_cache_path(self, path):
        original = headless.AGY_LAST_CONVERSATIONS_PATH
        headless.AGY_LAST_CONVERSATIONS_PATH = path
        self.addCleanup(lambda: setattr(headless, "AGY_LAST_CONVERSATIONS_PATH", original))

    def _patch_headless_dirs(self):
        """Redirects the two directories `headless.py` writes archives/quarantine
        records to, so no self-test call ever touches the real `evals/results/`."""
        orig_results, orig_transcripts = headless.RESULTS_DIR, headless.TRANSCRIPTS_DIR
        headless.RESULTS_DIR = self.tmp / "headless-results"
        headless.TRANSCRIPTS_DIR = self.tmp / "headless-transcripts"
        self.addCleanup(lambda: setattr(headless, "RESULTS_DIR", orig_results))
        self.addCleanup(lambda: setattr(headless, "TRANSCRIPTS_DIR", orig_transcripts))

    # -- Go-duration formatting -----------------------------------------------

    def test_headless_go_duration_formatting(self):
        self.assertEqual(headless.to_go_duration(2700), "45m")
        self.assertEqual(headless.to_go_duration(90), "1m30s")
        self.assertEqual(headless.to_go_duration(45), "45s")
        self.assertEqual(headless.to_go_duration(3661), "1h1m1s")
        self.assertEqual(headless.to_go_duration(0), "0s")

    # -- INFRA classification --------------------------------------------------

    def test_headless_classify_infra_agy_permission_denied(self):
        reason = headless.classify_infra(
            "agy", 'jetski: no output produced -- a tool required the "command" permission '
                   'that headless mode cannot prompt for, so it was auto-denied.', timed_out=False)
        self.assertIn("permission_denied", reason)

    def test_headless_classify_infra_empty_stdout(self):
        self.assertIn("no output", headless.classify_infra("agy", "", timed_out=False))
        self.assertIn("no output", headless.classify_infra("claude", "   ", timed_out=False))

    def test_headless_classify_infra_timeout(self):
        reason = headless.classify_infra("agy", "some real text", timed_out=True, timeout_s=60)
        self.assertIn("60s timeout", reason)

    def test_headless_classify_infra_claude_patterns(self):
        self.assertIsNotNone(headless.classify_infra("claude", "API Error: Connection closed", timed_out=False))
        self.assertIsNotNone(headless.classify_infra("claude", "This requires approval to run.", timed_out=False))
        self.assertIsNone(headless.classify_infra("claude", "Here is the plan I made.", timed_out=False))

    # -- handoff.txt / workspace lifecycle --------------------------------------

    def test_headless_write_handoff_if_needed(self):
        ws = self.tmp / "handoff-ws"
        ws.mkdir()
        self.assertFalse(headless.write_handoff_if_needed("claude", "handoff.txt", ws, "reply"))
        self.assertFalse((ws / "handoff.txt").exists())
        self.assertTrue(headless.write_handoff_if_needed("agy", "handoff.txt", ws, "reply text"))
        self.assertEqual((ws / "handoff.txt").read_text(encoding="utf-8"), "reply text")
        self.assertFalse(headless.write_handoff_if_needed("agy", None, ws, "reply text"))

    def test_headless_maybe_delete_workspace(self):
        ws_pass = self.tmp / "ws-pass"
        ws_pass.mkdir()
        headless._maybe_delete_workspace(ws_pass, "GRADED", True, keep_workspaces=False)
        self.assertFalse(ws_pass.exists())

        ws_fail = self.tmp / "ws-fail"
        ws_fail.mkdir()
        headless._maybe_delete_workspace(ws_fail, "GRADED", False, keep_workspaces=False)
        self.assertTrue(ws_fail.exists())

        ws_infra = self.tmp / "ws-infra"
        ws_infra.mkdir()
        headless._maybe_delete_workspace(ws_infra, "INFRA", None, keep_workspaces=False)
        self.assertTrue(ws_infra.exists())

        ws_keep = self.tmp / "ws-keep"
        ws_keep.mkdir()
        headless._maybe_delete_workspace(ws_keep, "GRADED", True, keep_workspaces=True)
        self.assertTrue(ws_keep.exists())

    # -- SUMMARY table -----------------------------------------------------------

    def test_headless_print_summary_table(self):
        rows = [
            {"suite": "trigger", "case": "trigger-1", "run": 1, "runtime": "agy",
             "outcome": "ROUTED_OK", "pass": True, "duration_s": 12.3, "failed_criterion": None},
            {"suite": "contract", "case": "stub", "run": 1, "runtime": "claude",
             "outcome": "GRADED", "pass": False, "duration_s": 45.0, "failed_criterion": "nope"},
        ]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            headless.print_summary(rows)
        out = buf.getvalue()
        self.assertIn("SUMMARY:", out)
        self.assertIn("trigger-1", out)
        self.assertIn("nope", out)

    # -- claude stream-json trigger judging (port of Invoke-TriggerJudge's read path) --

    @staticmethod
    def _claude_skill_line(skill_name):
        return json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": skill_name}}]}})

    def test_headless_claude_stream_trigger_judge_variants(self):
        result_line = json.dumps({"type": "result", "result": "I would route this to bgpdd-bugfix."})

        stream = "\n".join([self._claude_skill_line("bgpdd-bugfix"), result_line])
        skills = headless.claude_skill_invocations(stream)
        self.assertEqual(skills, ["bgpdd-bugfix"])
        self.assertEqual(trigger.judge_outcome(skills, [], "bgpdd-bugfix", []), "ROUTED_OK")

        stream = "\n".join([self._claude_skill_line("bgpdd-quick"), result_line])
        skills = headless.claude_skill_invocations(stream)
        self.assertEqual(trigger.judge_outcome(skills, [], "bgpdd-bugfix", []), "ROUTED_WRONG")
        self.assertTrue(headless.claude_mentioned_only(stream, "bgpdd-bugfix", []))

        stream = result_line
        skills = headless.claude_skill_invocations(stream)
        self.assertEqual(skills, [])
        self.assertEqual(trigger.judge_outcome(skills, [], "bgpdd-bugfix", []), "NO_ROUTE")

        stream = "\n".join([self._claude_skill_line("bg"), self._claude_skill_line("bgpdd-bugfix"), result_line])
        skills = headless.claude_skill_invocations(stream)
        self.assertEqual(trigger.judge_outcome(skills, ["bg", "bgpdd-bugfix"], "bg", []), "ROUTED_OK")

        stream = "\n".join([self._claude_skill_line("bg"), self._claude_skill_line("bgpdd-quick"), result_line])
        skills = headless.claude_skill_invocations(stream)
        self.assertEqual(trigger.judge_outcome(skills, ["bg", "bgpdd-bugfix"], "bg", []), "ROUTED_WRONG")

        stream = "\n".join([self._claude_skill_line("blackgoat-agentskills:bgpdd-plan"), result_line])
        skills = headless.claude_skill_invocations(stream)
        self.assertEqual(skills, ["bgpdd-plan"])

    # -- installed-plugin provenance ------------------------------------------

    def test_headless_installed_plugin_provenance_warns_on_mismatch(self):
        fake_installed = self.tmp / "installed-plugin"
        fake_installed.mkdir()
        self._make_git_repo(fake_installed)
        (fake_installed / "f.txt").write_text("x", encoding="utf-8")
        import subprocess
        subprocess.run(["git", "add", "-A"], cwd=str(fake_installed), capture_output=True, text=True)
        subprocess.run(["git", "commit", "-q", "-m", "other"], cwd=str(fake_installed),
                        capture_output=True, text=True)

        info = headless.installed_plugin_info("agy", override_path=fake_installed)
        self.assertIsNotNone(info["sha"])
        harness_sha = common.eval_record.plugin_sha()
        self.assertNotEqual(info["sha"], harness_sha)

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            headless.print_installed_plugin_provenance(info)
        out = buf.getvalue()
        self.assertIn("installed plugin:", out)
        self.assertIn(info["sha"], out)
        # Deliberately NO warning on a sha mismatch: the installed tree may
        # differ from the harness checkout on purpose.
        self.assertNotIn("WARNING", out)

    def test_headless_records_carry_installed_plugin_fields(self):
        results_path = self.tmp / "results-installed-plugin-test.jsonl"
        common.eval_record.append_runtime_trigger_record(
            case="trigger-1", run_index=1, outcome="ROUTED_OK", first_skill="bgpdd-plan",
            skills_invoked=["bgpdd-plan"], expected_chain=[], mentioned_only=False,
            runtime="claude", model="claude-default", results_path=results_path,
            installed_plugin_path="/x", installed_plugin_sha="deadbeef", installed_plugin_dirty=True,
            judge="tool_use",
        )
        rec = json.loads(results_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(rec["installed_plugin_sha"], "deadbeef")
        self.assertTrue(rec["installed_plugin_dirty"])
        self.assertEqual(rec["judge"], "tool_use")

    # -- agy conversation attribution via last_conversations.json ----------------

    def test_headless_resolve_agy_transcripts_prefers_mapping(self):
        brain = self.tmp / "agy-brain"
        workspace = self.tmp / "eval-runs" / "trigger-case-x-20260101T000000Z"
        workspace.mkdir(parents=True)
        t0 = common.parse_iso("2026-01-01T00:00:00Z")
        window_start = common.format_iso(t0)
        window_end = common.format_iso(t0 + timedelta(minutes=10))

        # This conversation starts AFTER window_start, so find_run_transcripts'
        # own "overlaps window_start" parent-inference rule would never pick
        # it, and it never mentions the workspace either.
        conv_id = "agy-conv-mapped"
        steps = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
             "created_at": common.format_iso(t0 + timedelta(minutes=1)), "content": "do the thing"},
            {"step_index": 1, "source": "MODEL", "type": "GENERIC", "status": "DONE",
             "created_at": common.format_iso(t0 + timedelta(minutes=2)), "content": "done"},
        ]
        _write_transcript(brain / conv_id, steps)

        cache_path = self.tmp / "last_conversations.json"
        cache_path.write_text(json.dumps({str(workspace): conv_id}), encoding="utf-8")

        baseline = common.transcript_tools.find_run_transcripts(window_start, window_end, brain,
                                                                  workspace=str(workspace))
        self.assertIsNone(baseline["parent"])

        resolved = headless.resolve_agy_transcripts(workspace, window_start, window_end, brain_root=brain,
                                                      cache_path=cache_path)
        self.assertIsNotNone(resolved["parent"])
        self.assertEqual(resolved["parent"]["conversation_id"], conv_id)

    def test_headless_run_one_agy_trigger_routed_ok_via_mapping(self):
        self._patch_headless_dirs()
        root = self.tmp / "agy-trigger-root"
        root.mkdir()
        brain = self.tmp / "agy-trigger-brain"
        cache_path = self.tmp / "agy-trigger-cache" / "last_conversations.json"
        conv_id = "agy-trigger-conv"
        self._patch_agy_cache_path(cache_path)

        def fake_invoke(argv, cwd, timeout_s):
            now = common.utc_now_iso()
            steps = [
                {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
                 "created_at": now, "content": "prompt"},
                {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                 "created_at": now, "tool_calls": [_view("skills/bgpdd-plan/SKILL.md")]},
            ]
            _write_transcript(brain / conv_id, steps)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({str(cwd): conv_id}), encoding="utf-8")
            return headless.ProcResult(stdout="I'll use bgpdd-plan.", stderr="", returncode=0,
                                        duration_s=3.0, timed_out=False)

        self._patch_invoker(fake_invoke)
        installed = {"path": None, "sha": None, "dirty": False}
        row, was_infra = headless.run_one("agy", "trigger", "trigger-1", 1, root, 60, None, False,
                                           True, False, brain, installed)
        self.assertFalse(was_infra)
        self.assertEqual(row["outcome"], "ROUTED_OK")
        self.assertTrue(row["pass"])
        self.assertFalse(Path(row["workspace"]).exists())  # PASS, not kept -> deleted

    def test_headless_run_one_agy_permission_denied_retried_and_quarantined(self):
        self._patch_headless_dirs()
        root = self.tmp / "agy-infra-root"
        root.mkdir()
        jetski_text = ('jetski: no output produced -- a tool required the "command" permission '
                       'that headless mode cannot prompt for, so it was auto-denied.')
        invoker = _FakeInvoker([
            lambda argv, cwd, t: headless.ProcResult(jetski_text, "", 0, 2.0, False),
            lambda argv, cwd, t: headless.ProcResult(jetski_text, "", 0, 2.0, False),
        ])
        self._patch_invoker(invoker)
        installed = {"path": None, "sha": None, "dirty": False}

        row, was_infra = headless.run_one("agy", "trigger", "trigger-1", 1, root, 60, None, True,
                                           True, True, self.tmp / "unused-brain", installed)
        self.assertTrue(was_infra)
        self.assertEqual(row["outcome"], "INFRA")
        self.assertIsNone(row["pass"])
        self.assertEqual(len(invoker.calls), 2)  # retried exactly once, never a third try
        self.assertTrue(Path(row["workspace"]).exists())  # INFRA -> kept

        invalid_path = headless.invalid_infra_path()
        self.assertTrue(invalid_path.is_file())
        lines = invalid_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        rec = json.loads(lines[0])
        self.assertEqual(rec["outcome"], "INFRA")
        self.assertIsNone(rec["pass"])
        self.assertEqual(rec["triage"], "INFRA")
        self.assertTrue(rec["failed_criterion"].startswith("INFRA: permission_denied"))
        self.assertFalse((headless.RESULTS_DIR / "results.jsonl").exists())

    def test_headless_run_one_agy_empty_stdout_is_infra(self):
        self._patch_headless_dirs()
        root = self.tmp / "agy-empty-root"
        root.mkdir()
        invoker = _FakeInvoker([
            lambda argv, cwd, t: headless.ProcResult("", "", 0, 1.0, False),
            lambda argv, cwd, t: headless.ProcResult("", "", 0, 1.0, False),
        ])
        self._patch_invoker(invoker)
        installed = {"path": None, "sha": None, "dirty": False}
        row, was_infra = headless.run_one("agy", "trigger", "trigger-1", 1, root, 60, None, False,
                                           True, True, self.tmp / "unused-brain-2", installed)
        self.assertTrue(was_infra)
        self.assertEqual(row["outcome"], "INFRA")
        self.assertIn("no output", row["failed_criterion"])

    def test_headless_run_one_agy_timeout_is_infra(self):
        self._patch_headless_dirs()
        root = self.tmp / "agy-timeout-root"
        root.mkdir()
        invoker = _FakeInvoker([
            lambda argv, cwd, t: headless.ProcResult("", "", -1, float(t) + 60, True),
            lambda argv, cwd, t: headless.ProcResult("", "", -1, float(t) + 60, True),
        ])
        self._patch_invoker(invoker)
        installed = {"path": None, "sha": None, "dirty": False}
        row, was_infra = headless.run_one("agy", "trigger", "trigger-1", 1, root, 30, None, False,
                                           True, True, self.tmp / "unused-brain-3", installed)
        self.assertTrue(was_infra)
        self.assertEqual(row["outcome"], "INFRA")
        self.assertIn("timeout", row["failed_criterion"])

    # -- claude+contract parity: the prefix runs exactly once, never twice -------

    def test_headless_claude_contract_parity_no_double_prefix(self):
        self._patch_headless_dirs()
        case = "bgpdd-bugfix-lane"  # has a git-init prefix and an Out-File handoff
        root = self.tmp / "claude-contract-root"
        root.mkdir()
        calls = []

        def fake_invoke(argv, cwd, timeout_s):
            calls.append({"argv": list(argv), "cwd": Path(cwd)})
            self.assertEqual(argv[0], "powershell.exe")
            command_text = argv[-1]
            self.assertIn("claude -p", command_text)
            self.assertIn("bgpdd-bugfix", command_text)  # the case's own prompt text, verbatim
            prefix, _prompt, handoff_to = contract.split_command(command_text)
            # Runs ONLY the prefix for real (git setup -- no tokens spent);
            # a double-run bug would make the second `git commit` here fail
            # with "nothing to commit" (non-zero exit), which the assertion
            # below catches.
            proc = common.run_powershell_command(prefix, cwd=cwd)
            self.assertEqual(proc.returncode, 0, f"stdout={proc.stdout}\nstderr={proc.stderr}")
            if handoff_to:
                (Path(cwd) / handoff_to).write_text("Fixed the bug.", encoding="utf-8")
            # Above this case's 60s default minimum duration (contract.DEFAULT_MIN_DURATION)
            # -- a faster "run" would classify INFRA and retry, running the prefix twice.
            return headless.ProcResult("", "", 0, 65.0, False)

        self._patch_invoker(fake_invoke)
        installed = {"path": None, "sha": None, "dirty": False}
        row, _was_infra = headless.run_one("claude", "contract", case, 1, root, 120, None, False,
                                            True, True, None, installed)
        self.assertEqual(len(calls), 1)
        self.assertTrue((Path(row["workspace"]) / ".git").is_dir())

    # -- antigravity: the three transcript-judged cases are INFRA under claude ---

    def test_headless_run_one_claude_antigravity_transcript_cases_are_infra(self):
        self._patch_headless_dirs()
        root = self.tmp / "claude-antigravity-root"
        root.mkdir()
        installed = {"path": None, "sha": None, "dirty": False}

        def fake_invoke(argv, cwd, timeout_s):
            return headless.ProcResult("I did the work as instructed.", "", 0, 5.0, False)

        self._patch_invoker(fake_invoke)
        for case in sorted(headless.CLAUDE_ANTIGRAVITY_TRANSCRIPT_CASES):
            row, was_infra = headless.run_one("claude", "antigravity", case, 1, root, 60, None, False,
                                               True, True, None, installed)
            self.assertTrue(was_infra, case)
            self.assertEqual(row["outcome"], "INFRA", case)
            self.assertEqual(row["failed_criterion"],
                              "INFRA: no Antigravity transcript under runtime claude", case)
            self.assertTrue(Path(row["workspace"]).exists(), case)  # INFRA -> kept


def run_self_test():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(SelfTest)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    if failed:
        print(f"SELF-TEST: {total - failed}/{total} passed, {failed} FAILED")
        return 1
    print(f"SELF-TEST: {total}/{total} passed. OK")
    return 0


if __name__ == "__main__":
    sys.exit(run_self_test())
