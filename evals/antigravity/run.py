#!/usr/bin/env python3
"""CLI for the `evals/antigravity/` harness: `start`, `grade`, `list`, `--self-test`.

See `evals/antigravity/README.md` for the full workflow. Short version:

    python run.py start --case run-log-discipline --workspace C:\\tmp\\ws1
    # ... open C:\\tmp\\ws1 in Antigravity, paste cases/run-log-discipline/prompt.md ...
    python run.py grade --run evals/antigravity/runs/run-log-discipline-<ts>.json --record

Pure standard library.
"""
import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ANTIGRAVITY_DIR = Path(__file__).resolve().parent
EVALS_DIR = ANTIGRAVITY_DIR.parent
CASES_DIR = ANTIGRAVITY_DIR / "cases"
RUNS_DIR = ANTIGRAVITY_DIR / "runs"

sys.path.insert(0, str(ANTIGRAVITY_DIR))
sys.path.insert(0, str(EVALS_DIR))
import transcript_tools  # noqa: E402
import case_common  # noqa: E402
import eval_record  # noqa: E402

ARTIFACT_WINDOW_BUFFER = timedelta(minutes=2)


def utc_now_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_grader(case):
    grade_path = CASES_DIR / case / "grade.py"
    if not grade_path.is_file():
        raise SystemExit(f"error: no grader at {grade_path}")
    spec = importlib.util.spec_from_file_location(f"case_{case}_grade", grade_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.grade


# --------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------

def cmd_start(args):
    case_dir = CASES_DIR / args.case
    fixture_dir = case_dir / "fixture"
    if not fixture_dir.is_dir():
        raise SystemExit(f"error: no fixture at {fixture_dir} -- unknown case {args.case!r}?")

    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if any(workspace.iterdir()):
        raise SystemExit(f"error: workspace {workspace} is not empty; use a fresh directory")

    shutil.copytree(fixture_dir, workspace, dirs_exist_ok=True)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    run_path = RUNS_DIR / f"{args.case}-{ts}.json"
    record = {
        "case": args.case,
        "workspace": str(workspace),
        "started_at": utc_now_iso(),
        "graded_at": None,
        "last_result": None,
    }
    run_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    print(f"STARTED: case={args.case} workspace={workspace}")
    print(f"Run marker: {run_path}")
    print(f"Next: open {workspace} in Antigravity with the plugin installed, "
          f"paste cases/{args.case}/prompt.md verbatim, then when it finishes run:")
    print(f"  python run.py grade --run {run_path}")
    return run_path


# --------------------------------------------------------------------------
# grade
# --------------------------------------------------------------------------

def _artifact_window_end(workspace):
    """Latest `ts` seen across every `run-log.jsonl`/`gates.jsonl` under the
    workspace's `.docs/bugfix/*/`, plus a buffer -- or None if there is no
    artifact to read a timestamp from.
    """
    latest = None
    for root in case_common.find_bugfix_roots(workspace):
        for name in ("run-log.jsonl", "gates.jsonl"):
            for rec in case_common.read_jsonl(root / name):
                ts = rec.get("ts")
                if ts and (latest is None or ts > latest):
                    latest = ts
    if latest is None:
        return None
    dt = datetime.strptime(latest, "%Y-%m-%dT%H:%M:%SZ") + ARTIFACT_WINDOW_BUFFER
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def cmd_grade(args):
    run_path = Path(args.run)
    if not run_path.is_file():
        raise SystemExit(f"error: no run marker at {run_path}")
    run_record = json.loads(run_path.read_text(encoding="utf-8"))
    case = run_record["case"]
    workspace = Path(run_record["workspace"])
    window_start = run_record["started_at"]
    window_end = args.end or _artifact_window_end(workspace) or utc_now_iso()

    transcripts = transcript_tools.find_run_transcripts(window_start, window_end, args.brain_root)
    grader = _load_grader(case)
    result = grader(workspace, transcripts)

    is_infra = bool(result.get("infra"))
    outcome = "INFRA" if is_infra else "GRADED"
    passed = None if is_infra else bool(result.get("pass"))

    print(f"CASE: {case}")
    print(f"WORKSPACE: {workspace}")
    print(f"WINDOW: {window_start} -> {window_end}")
    print(f"PARENT: {transcripts['parent']['conversation_id'] if transcripts['parent'] else None}")
    print(f"SUBAGENTS: {[s['conversation_id'] for s in transcripts['subagents']]}")
    if is_infra:
        print(f"OUTCOME: INFRA ({result.get('infra_reason')})")
    else:
        print(f"OUTCOME: {'PASS' if passed else 'FAIL'}")
        if result.get("failed_criterion"):
            print(f"FAILED CRITERION: {result['failed_criterion']}")
    print("METRICS:")
    print(json.dumps(result.get("metrics", {}), indent=2, default=str))

    run_record["graded_at"] = utc_now_iso()
    run_record["last_result"] = {"outcome": outcome, "pass": passed,
                                  "failed_criterion": result.get("failed_criterion")}
    run_path.write_text(json.dumps(run_record, indent=2), encoding="utf-8")

    if args.record:
        run_index = args.run_index or _infer_run_index(case, run_path)
        eval_record.append_antigravity_record(
            case=case, run_index=run_index, passed=passed, outcome=outcome,
            failed_criterion=result.get("failed_criterion"),
            metrics=result.get("metrics", {}),
            triage=("INFRA" if is_infra else None),
        )

    return 0 if (is_infra or passed) else 1


def _infer_run_index(case, this_run_path):
    """1-based ordinal of `this_run_path` among this case's run markers, by `started_at`."""
    markers = sorted(RUNS_DIR.glob(f"{case}-*.json"))
    starts = []
    for m in markers:
        try:
            rec = json.loads(m.read_text(encoding="utf-8"))
            starts.append((rec.get("started_at", ""), m))
        except (OSError, json.JSONDecodeError):
            continue
    starts.sort()
    for i, (_, m) in enumerate(starts, start=1):
        if m == this_run_path:
            return i
    return 1


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------

def cmd_list(args):
    print(f"Cases under {CASES_DIR}:")
    for case_dir in sorted(CASES_DIR.iterdir()):
        if (case_dir / "grade.py").is_file():
            print(f"  {case_dir.name}")
    print()
    print(f"Run markers under {RUNS_DIR}:")
    if not RUNS_DIR.is_dir():
        return
    for run_path in sorted(RUNS_DIR.glob("*.json")):
        try:
            rec = json.loads(run_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        status = "not graded"
        if rec.get("last_result"):
            lr = rec["last_result"]
            status = f"{lr['outcome']}" + (f" pass={lr['pass']}" if lr["outcome"] == "GRADED" else "")
        print(f"  {run_path.name}: case={rec.get('case')} workspace={rec.get('workspace')} [{status}]")


# --------------------------------------------------------------------------
# --self-test
# --------------------------------------------------------------------------

def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _write_transcript(conv_dir, steps):
    logs_dir = Path(conv_dir) / ".system_generated" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    with open(logs_dir / "transcript.jsonl", "w", encoding="utf-8") as fh:
        for step in steps:
            fh.write(json.dumps(step) + "\n")


def _q(s):
    """Wrap a string the way a real Antigravity tool arg is stored (literal quotes)."""
    return f'"{s}"'


def _build_synthetic_brain(root):
    """A parent + 3 subagents (quinn, mason, luna) mimicking the real run shape."""
    root = Path(root)
    parent = root / "parent-conv"
    quinn_conv = root / "quinn-conv"
    mason_conv = root / "mason-conv"
    luna_conv = root / "luna-conv"
    other_conv = root / "unrelated-human-conv"

    invoke_subagents_arg = json.dumps([
        {"Model": "inherit", "Prompt": "You are Quinn, the QA Tester.\nRead your persona at agents/quinn.md"},
    ])
    parent_steps = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": "2026-01-01T00:00:00Z", "content": "fix the bug please"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:01:00Z",
         "tool_calls": [{"name": "define_subagent", "args": {"name": _q("quinn"), "system_prompt": _q("x" * 50)}}]},
        {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:02:00Z",
         # NOTE: `Subagents` is stored RAW (no extra literal-quote wrapping,
         # unlike AbsolutePath/CommandLine/name) -- see transcript_tools.py.
         "tool_calls": [{"name": "invoke_subagent", "args": {"Subagents": invoke_subagents_arg}}]},
        {"step_index": 3, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:03:00Z",
         "tool_calls": [{"name": "invoke_subagent", "args": {"Subagents": json.dumps([
             {"Model": "inherit", "Prompt": "You are Mason, the Backend Builder.\nRead your persona at agents/mason.md .docs/bugfix/bug-1/"}])}}]},
        {"step_index": 4, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:04:00Z",
         "tool_calls": [{"name": "invoke_subagent", "args": {"Subagents": json.dumps([
             {"Model": "inherit", "Prompt": "You are Luna, the Code Reviewer.\nRead your persona at agents/luna.md .docs/bugfix/bug-1/"}])}}]},
        {"step_index": 5, "source": "MODEL", "type": "GENERIC", "status": "DONE",
         "created_at": "2026-01-01T00:05:00Z",
         "tool_calls": [{"name": "run_command", "args": {"CommandLine": _q("npm test"), "Cwd": _q(".")}}]},
        {"step_index": 6, "source": "MODEL", "type": "GENERIC", "status": "DONE",
         "created_at": "2026-01-01T00:10:00Z", "content": "done"},
    ]
    quinn_steps = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": "2026-01-01T00:02:05Z",
         "content": "You are Quinn, the QA Tester.\nRead your persona at agents/quinn.md"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:02:10Z",
         "tool_calls": [
             {"name": "view_file", "args": {"AbsolutePath": _q("C:\\\\plugin\\\\skills\\\\agent-squad\\\\base-persona.md")}},
             {"name": "view_file", "args": {"AbsolutePath": _q("C:\\\\plugin\\\\skills\\\\runtime-evidence\\\\SKILL.md")}},
             {"name": "run_command", "args": {"CommandLine": _q("python C:/plugin/skills/pipeline-tools/scripts/run_quiet.py --capture ev.md -- npm test")}},
         ]},
    ]
    mason_steps = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": "2026-01-01T00:03:05Z",
         "content": "You are Mason, the Backend Builder.\nRead your persona at agents/mason.md"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:03:10Z",
         "tool_calls": [
             {"name": "view_file", "args": {"AbsolutePath": _q("C:\\\\plugin\\\\skills\\\\agent-squad\\\\base-persona.md")}},
             {"name": "view_file", "args": {"AbsolutePath": _q("C:\\\\plugin\\\\skills\\\\test-driven-development\\\\SKILL.md")}},
             {"name": "view_file", "args": {"AbsolutePath": _q("C:\\\\plugin\\\\skills\\\\godot-gdscript-patterns\\\\SKILL.md")}},
             {"name": "run_command", "args": {"CommandLine": _q("dotnet test C:\\\\proj\\\\x.csproj")}},
         ]},
    ]
    luna_steps = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": "2026-01-01T00:04:05Z",
         "content": "You are Luna, the Code Reviewer.\nRead your persona at agents/luna.md"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:04:10Z",
         "tool_calls": [
             {"name": "view_file", "args": {"AbsolutePath": _q("C:\\\\plugin\\\\skills\\\\agent-squad\\\\base-persona.md")}},
             {"name": "view_file", "args": {"AbsolutePath": _q("C:\\\\plugin\\\\skills\\\\code-review-and-quality\\\\SKILL.md")}},
         ]},
    ]
    other_steps = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": "2026-01-01T05:00:00Z", "content": "unrelated later human question"},
    ]

    _write_transcript(parent, parent_steps)
    _write_transcript(quinn_conv, quinn_steps)
    _write_transcript(mason_conv, mason_steps)
    _write_transcript(luna_conv, luna_steps)
    _write_transcript(other_conv, other_steps)
    return {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:10:00Z"}


class SelfTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agv-selftest-"))
        self.brain_root = self.tmp / "brain"
        self.window = _build_synthetic_brain(self.brain_root)
        self.workspace = self.tmp / "workspace"
        self.workspace.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- transcript_tools -------------------------------------------------

    def test_unwrap_arg(self):
        self.assertEqual(transcript_tools.unwrap_arg('"C:\\\\foo\\\\bar.md"'), "C:\\\\foo\\\\bar.md")
        self.assertEqual(transcript_tools.unwrap_arg("false"), "false")

    def test_normalize_path_both_separators(self):
        a = transcript_tools.normalize_path("C:\\\\plugin\\\\skills\\\\x\\\\SKILL.md")
        b = transcript_tools.normalize_path("C:/plugin/skills/x/SKILL.md")
        self.assertEqual(a, b)

    def test_is_briefing_input(self):
        self.assertTrue(transcript_tools.is_briefing_input("You are Quinn, the QA Tester.\nRead your persona"))
        self.assertFalse(transcript_tools.is_briefing_input("can you read .docs/summary/slide"))

    def test_briefing_persona(self):
        self.assertEqual(transcript_tools.briefing_persona("You are Mason, the Backend Builder."), "Mason")

    def test_list_conversations(self):
        convs = transcript_tools.list_conversations(self.brain_root)
        self.assertEqual(len(convs), 5)

    def test_find_run_transcripts(self):
        result = transcript_tools.find_run_transcripts(self.window["start"], self.window["end"], self.brain_root)
        self.assertIsNotNone(result["parent"])
        self.assertEqual(result["parent"]["conversation_id"], "parent-conv")
        personas = sorted(s["persona"] for s in result["subagents"])
        self.assertEqual(personas, ["Luna", "Mason", "Quinn"])
        ids = {s["conversation_id"] for s in result["subagents"]}
        self.assertNotIn("unrelated-human-conv", ids)

    def test_extract_view_file_paths(self):
        steps = transcript_tools.parse_transcript(self.brain_root / "mason-conv")
        calls = transcript_tools.iter_tool_calls(steps)
        paths = transcript_tools.extract_view_file_paths(calls)
        self.assertEqual(len(paths), 3)

    def test_extract_run_command_strings(self):
        steps = transcript_tools.parse_transcript(self.brain_root / "mason-conv")
        calls = transcript_tools.iter_tool_calls(steps)
        cmds = transcript_tools.extract_run_command_strings(calls)
        self.assertIn("dotnet test C:\\\\proj\\\\x.csproj", cmds)

    def test_extract_invoke_subagent_calls(self):
        steps = transcript_tools.parse_transcript(self.brain_root / "parent-conv")
        calls = transcript_tools.iter_tool_calls(steps)
        invokes = transcript_tools.extract_invoke_subagent_calls(calls)
        self.assertEqual(len(invokes), 3)
        self.assertIsNotNone(invokes[0]["subagents"])

    # -- case_common --------------------------------------------------------

    def test_is_raw_runner_invocation(self):
        self.assertTrue(case_common.is_raw_runner_invocation("dotnet test C:\\\\x.csproj"))
        self.assertFalse(case_common.is_raw_runner_invocation(
            "python run_quiet.py --capture x.md -- dotnet test C:\\\\x.csproj"))
        self.assertFalse(case_common.is_raw_runner_invocation("git status"))

    def test_normalize_path_suffix(self):
        self.assertEqual(
            case_common.normalize_path_suffix("C:\\\\plugin\\\\skills\\\\foo\\\\SKILL.md"),
            "skills/foo/skill.md")

    def test_is_skill_read(self):
        self.assertTrue(case_common.is_skill_read("skills/dotnet-backend-patterns/skill.md"))
        self.assertTrue(case_common.is_skill_read("skills/agent-squad/base-persona.md"))
        self.assertFalse(case_common.is_skill_read("agents/mason.md"))

    def test_parse_methodology_table_mason(self):
        rows = case_common.parse_methodology_table("mason")
        self.assertTrue(rows)
        always_skills = {r["skill"] for r in rows if r["when"].strip().lower() == "always"}
        self.assertIn("base-persona", always_skills)
        self.assertIn("test-driven-development", always_skills)

    def test_find_bugfix_roots_empty(self):
        self.assertEqual(case_common.find_bugfix_roots(self.workspace), [])

    # -- graders: run-log-discipline ----------------------------------------

    def _write_bugfix_root(self, slug="bug-1"):
        root = self.workspace / ".docs" / "bugfix" / slug
        root.mkdir(parents=True, exist_ok=True)
        (root / "bug-report.md").write_text("# report", encoding="utf-8")
        return root

    def test_run_log_discipline_infra_no_artifact(self):
        grade = _load_grader("run-log-discipline")
        result = grade(self.workspace, {})
        self.assertTrue(result["infra"])

    def test_run_log_discipline_pass(self):
        grade = _load_grader("run-log-discipline")
        root = self._write_bugfix_root()
        _write_jsonl(root / "run-log.jsonl", [
            {"event": "delegation", "agent": "quinn", "model": "gemini-3.8-flash", "tier": "flash",
             "runtime": "antigravity", "tokens_unavailable": "antigravity: no usage field"},
            {"event": "delegation", "agent": "mason", "model": "gemini-3.8-flash", "tier": "flash",
             "runtime": "antigravity", "tokens_total": 1000},
            {"event": "delegation", "agent": "luna", "model": "gemini-3.8-flash", "tier": "flash",
             "runtime": "antigravity", "tokens_total": 500},
        ])
        result = grade(self.workspace, {})
        self.assertFalse(result["infra"])
        self.assertTrue(result["pass"], result.get("failed_criterion"))

    def test_run_log_discipline_fail_missing_fields(self):
        grade = _load_grader("run-log-discipline")
        root = self._write_bugfix_root()
        _write_jsonl(root / "run-log.jsonl", [
            {"event": "delegation", "agent": "quinn", "model": "sonnet", "tier": None,
             "runtime": "antigravity"},
            {"event": "delegation", "agent": "mason", "model": "gemini-3.8-flash", "tier": "flash",
             "runtime": "antigravity", "tokens_total": 100},
        ])
        result = grade(self.workspace, {})
        self.assertFalse(result["infra"])
        self.assertFalse(result["pass"])
        self.assertIsNotNone(result["failed_criterion"])

    # -- graders: skill-load-discipline --------------------------------------

    def test_skill_load_discipline_infra_no_subagents(self):
        grade = _load_grader("skill-load-discipline")
        result = grade(self.workspace, {"subagents": [], "parent": None, "all": []})
        self.assertTrue(result["infra"])

    def test_skill_load_discipline_pass(self):
        grade = _load_grader("skill-load-discipline")
        transcripts = transcript_tools.find_run_transcripts(self.window["start"], self.window["end"], self.brain_root)
        result = grade(self.workspace, transcripts)
        self.assertFalse(result["infra"])
        # Mason's transcript over-reads godot-gdscript-patterns (1 over-read <= limit 1) -> still PASS
        self.assertTrue(result["pass"], result.get("failed_criterion"))
        mason_key = [k for k in result["metrics"]["per_subagent"] if k.startswith("Mason")][0]
        self.assertEqual(result["metrics"]["per_subagent"][mason_key]["over_reads"],
                          ["skills/godot-gdscript-patterns/skill.md"])

    def test_skill_load_discipline_fail_over_reads(self):
        grade = _load_grader("skill-load-discipline")
        transcripts = transcript_tools.find_run_transcripts(self.window["start"], self.window["end"], self.brain_root)
        # Inject a second bogus over-read into Mason's transcript to push it past the limit of 1.
        mason_dir = self.brain_root / "mason-conv"
        steps = transcript_tools.parse_transcript(mason_dir)
        steps[1]["tool_calls"].append(
            {"name": "view_file", "args": {"AbsolutePath": _q("C:\\\\plugin\\\\skills\\\\jobs-and-messaging-patterns\\\\SKILL.md")}})
        _write_transcript(mason_dir, steps)
        result = grade(self.workspace, transcripts)
        self.assertFalse(result["pass"])

    # -- graders: quiet-runner-discipline -------------------------------------

    def test_quiet_runner_discipline_fail_raw(self):
        grade = _load_grader("quiet-runner-discipline")
        transcripts = transcript_tools.find_run_transcripts(self.window["start"], self.window["end"], self.brain_root)
        result = grade(self.workspace, transcripts)
        self.assertFalse(result["infra"])
        self.assertFalse(result["pass"])  # Mason's raw `dotnet test` and parent's raw `npm test`
        self.assertEqual(result["metrics"]["raw_count"], 2)

    def test_quiet_runner_discipline_pass_when_wrapped(self):
        grade = _load_grader("quiet-runner-discipline")
        # Only Quinn's transcript, whose one runner call is wrapped.
        transcripts = {"all": [{"conversation_id": "quinn-conv", "dir": str(self.brain_root / "quinn-conv")}]}
        result = grade(self.workspace, transcripts)
        self.assertFalse(result["infra"])
        self.assertTrue(result["pass"])
        self.assertEqual(result["metrics"]["raw_count"], 0)

    # -- graders: round-bound -------------------------------------------------

    def test_round_bound_infra_no_parent(self):
        grade = _load_grader("round-bound")
        result = grade(self.workspace, {"parent": None})
        self.assertTrue(result["infra"])

    def test_round_bound_pass_within_limit(self):
        grade = _load_grader("round-bound")
        transcripts = transcript_tools.find_run_transcripts(self.window["start"], self.window["end"], self.brain_root)
        result = grade(self.workspace, transcripts)
        self.assertFalse(result["infra"])
        self.assertTrue(result["pass"], result.get("failed_criterion"))
        self.assertEqual(result["metrics"]["invocations_per_persona"]["quinn"]["run"], 1)

    def test_round_bound_fail_over_limit_without_gate_record(self):
        grade = _load_grader("round-bound")
        parent_dir = self.brain_root / "parent-conv"
        steps = transcript_tools.parse_transcript(parent_dir)
        extra = {"step_index": 6, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                 "created_at": "2026-01-01T00:10:10Z",
                 "tool_calls": [{"name": "invoke_subagent", "args": {"Subagents": json.dumps([
                     {"Model": "inherit", "Prompt": "You are Mason, the Backend Builder. .docs/bugfix/bug-1/"}])}}]}
        steps.append(extra)
        steps.append(dict(extra, step_index=7, created_at="2026-01-01T00:10:20Z"))
        _write_transcript(parent_dir, steps)
        transcripts = transcript_tools.find_run_transcripts(self.window["start"], "2026-01-01T00:10:20Z", self.brain_root)
        result = grade(self.workspace, transcripts)
        self.assertFalse(result["infra"])
        self.assertFalse(result["pass"])

    def test_round_bound_pass_over_limit_with_gate_record(self):
        grade = _load_grader("round-bound")
        parent_dir = self.brain_root / "parent-conv"
        steps = transcript_tools.parse_transcript(parent_dir)
        extra = {"step_index": 6, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                 "created_at": "2026-01-01T00:10:10Z",
                 "tool_calls": [{"name": "invoke_subagent", "args": {"Subagents": json.dumps([
                     {"Model": "inherit", "Prompt": "You are Mason, the Backend Builder. .docs/bugfix/bug-1/"}])}}]}
        steps.append(extra)
        steps.append(dict(extra, step_index=7, created_at="2026-01-01T00:10:20Z"))
        _write_transcript(parent_dir, steps)
        root = self._write_bugfix_root()
        _write_jsonl(root / "gates.jsonl", [{"gate": "check_redelegation.py", "verdict": "PASS"}])
        transcripts = transcript_tools.find_run_transcripts(self.window["start"], "2026-01-01T00:10:20Z", self.brain_root)
        result = grade(self.workspace, transcripts)
        self.assertTrue(result["pass"])

    # -- run.py CLI plumbing --------------------------------------------------

    def test_start_then_grade_cli_roundtrip(self):
        # `cmd_start`/`cmd_grade` write run markers under the module-level
        # RUNS_DIR -- redirect it to this test's temp dir for the duration so
        # a self-test run never leaves a marker behind in the real
        # evals/antigravity/runs/.
        global RUNS_DIR
        original_runs_dir = RUNS_DIR
        RUNS_DIR = self.tmp / "runs"
        try:
            ws = self.tmp / "cli-ws"
            run_path = cmd_start(argparse.Namespace(case="run-log-discipline", workspace=str(ws)))
            self.assertTrue((ws / "package.json").is_file())
            rec = json.loads(run_path.read_text(encoding="utf-8"))
            self.assertEqual(rec["case"], "run-log-discipline")
            # No artifact was ever produced in `ws` -> grade must report INFRA, not raise.
            rc = cmd_grade(argparse.Namespace(run=str(run_path), brain_root=self.tmp / "empty-brain",
                                              end=None, record=False, run_index=None))
            self.assertEqual(rc, 0)
            graded = json.loads(run_path.read_text(encoding="utf-8"))
            self.assertEqual(graded["last_result"]["outcome"], "INFRA")
        finally:
            RUNS_DIR = original_runs_dir

    def test_eval_record_append_antigravity_record(self):
        target = self.tmp / "results.jsonl"
        rec = eval_record.append_antigravity_record(
            case="run-log-discipline", run_index=1, passed=True,
            metrics={"records": 3}, results_path=target,
            case_path=CASES_DIR / "run-log-discipline" / "case.md")
        self.assertIsNotNone(rec)
        self.assertEqual(rec["runtime"], "antigravity")
        self.assertEqual(rec["model"], "gemini-3.8-flash")
        self.assertEqual(rec["judge"], "harness")
        lines = target.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["outcome"], "GRADED")


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


# --------------------------------------------------------------------------
# argparse wiring
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-test", action="store_true", help="run the offline synthetic-fixture self-test")
    sub = parser.add_subparsers(dest="cmd")

    p_start = sub.add_parser("start", help="copy a case's fixture into a fresh workspace and record the start marker")
    p_start.add_argument("--case", required=True)
    p_start.add_argument("--workspace", required=True)
    p_start.set_defaults(func=cmd_start)

    p_grade = sub.add_parser("grade", help="find the run's transcripts, grade the workspace, print the verdict")
    p_grade.add_argument("--run", required=True, help="path to a runs/<case>-<ts>.json marker")
    p_grade.add_argument("--brain-root", default=None, help="override the Antigravity brain root (default: ~/.gemini/antigravity/brain)")
    p_grade.add_argument("--end", default=None, help="override the window end (ISO-8601 UTC); default: derived from workspace artifacts, else now")
    p_grade.add_argument("--run-index", type=int, default=None, help="override the inferred run_index (1..5) for --record")
    p_grade.add_argument("--record", action="store_true", help="append a results record via eval_record.append_antigravity_record")
    p_grade.set_defaults(func=cmd_grade)

    p_list = sub.add_parser("list", help="list known cases and run markers")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()
    if not args.cmd:
        parser.print_help()
        return 2
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
