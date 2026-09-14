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
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


def _utcnow():
    """Timezone-aware UTC now -- `datetime.utcnow()` is deprecated (3.12+)."""
    return datetime.now(timezone.utc)


def utc_now_iso():
    return _utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


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

def _all_case_names():
    """Every case dir under `CASES_DIR` that has both a `fixture/` and a `grade.py`."""
    return sorted(d.name for d in CASES_DIR.iterdir()
                  if d.is_dir() and (d / "grade.py").is_file() and (d / "fixture").is_dir())


def _start_one(case, workspace, ts=None):
    """Copy `case`'s fixture into `workspace` and write its start marker. Returns the marker Path."""
    case_dir = CASES_DIR / case
    fixture_dir = case_dir / "fixture"
    if not fixture_dir.is_dir():
        raise SystemExit(f"error: no fixture at {fixture_dir} -- unknown case {case!r}?")

    workspace = Path(workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    if any(workspace.iterdir()):
        raise SystemExit(f"error: workspace {workspace} is not empty; use a fresh directory")

    shutil.copytree(fixture_dir, workspace, dirs_exist_ok=True)

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = ts or _utcnow().strftime("%Y%m%dT%H%M%SZ")
    run_path = RUNS_DIR / f"{case}-{ts}.json"
    record = {
        "case": case,
        "workspace": str(workspace),
        "started_at": utc_now_iso(),
        "graded_at": None,
        "last_result": None,
    }
    run_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return run_path


def _print_next_steps(case, workspace, run_path):
    print(f"STARTED: case={case} workspace={workspace}")
    print(f"Run marker: {run_path}")
    print(f"Next: open {workspace} in Antigravity with the plugin installed, "
          f"paste cases/{case}/prompt.md verbatim, then when it finishes run:")
    print(f"  python run.py grade --run {run_path}")


def _cmd_start_impl(args):
    """Does the actual work of `start`; returns the marker Path (single-case
    or `--in-place --case`) or a list of marker Paths (`--in-place
    --all-cases`). Kept separate from `cmd_start` because every `cmd_*`
    dispatched from `main()` must return an int (`sys.exit(main())` treats a
    non-empty Path/list as a failure message, not an exit code) -- callers
    that need the actual path(s) (the self-test) call this directly instead.
    """
    in_place = getattr(args, "in_place", False)
    all_cases = getattr(args, "all_cases", False)
    root_arg = getattr(args, "root", None)

    if all_cases and not in_place:
        raise SystemExit("error: --all-cases requires --in-place")

    if in_place:
        if bool(args.case) == bool(all_cases):
            raise SystemExit("error: --in-place requires exactly one of --case or --all-cases")
        if args.workspace:
            raise SystemExit("error: --workspace is not compatible with --in-place -- "
                              "the workspace is derived under <root>/eval-runs/<case>-<ts>/")
        root = Path(root_arg).resolve() if root_arg else Path.cwd()
        cases = [args.case] if args.case else _all_case_names()
        if not cases:
            raise SystemExit(f"error: no cases found under {CASES_DIR}")
        ts = _utcnow().strftime("%Y%m%dT%H%M%SZ")
        rows = []
        for case in cases:
            workspace = root / "eval-runs" / f"{case}-{ts}"
            run_path = _start_one(case, workspace, ts=ts)
            rows.append((case, str(workspace), str(run_path)))
        if all_cases:
            print(f"{'case':30} {'workspace':60} marker")
            for case, workspace, run_path in rows:
                print(f"{case:30} {workspace:60} {run_path}")
        else:
            _print_next_steps(*rows[0])
        return [Path(r[2]) for r in rows]

    if not args.case or not args.workspace:
        raise SystemExit("error: --case and --workspace are required (or use --in-place)")
    workspace = Path(args.workspace).resolve()
    run_path = _start_one(args.case, workspace)
    _print_next_steps(args.case, workspace, run_path)
    return run_path


def cmd_start(args):
    _cmd_start_impl(args)
    return 0


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


# A transcript that VIEWED this harness's own grader/CLI after the marker's
# start time is a self-contamination signal: the graded run inspected the
# very code that will judge it. Matched on the `evals/antigravity/...`
# suffix (see `case_common.normalize_path_suffix`'s rationale -- a real
# transcript's path is on the user's machine, never this repo's absolute
# path byte for byte).
SELF_INSPECT_RE = re.compile(r"evals/antigravity/(cases/[^/]+/grade\.py|run\.py)$", re.I)


def _check_self_inspection(transcripts, window_start):
    """True if any transcript attributed to this run `view_file`-d this
    harness's own `grade.py`/`run.py` strictly after `window_start`."""
    convs = []
    seen = set()
    ordered = ([transcripts.get("parent")] if transcripts.get("parent") else [])
    ordered += (transcripts.get("subagents") or []) + (transcripts.get("all") or [])
    for conv in ordered:
        if not conv or conv["conversation_id"] in seen:
            continue
        seen.add(conv["conversation_id"])
        convs.append(conv)

    for conv in convs:
        for step in transcript_tools.parse_transcript(conv["dir"]):
            if (step.get("created_at") or "") <= window_start:
                continue
            for call in step.get("tool_calls") or []:
                if call.get("name") != "view_file":
                    continue
                path = transcript_tools.unwrap_arg((call.get("args") or {}).get("AbsolutePath"))
                if path and SELF_INSPECT_RE.search(transcript_tools.normalize_path(path)):
                    return True
    return False


def cmd_grade(args):
    if getattr(args, "all_runs", None):
        return cmd_grade_all(args)
    if not args.run:
        raise SystemExit("error: --run is required (or use --all-runs)")

    run_path = Path(args.run)
    if not run_path.is_file():
        raise SystemExit(f"error: no run marker at {run_path}")
    run_record = json.loads(run_path.read_text(encoding="utf-8"))
    case = getattr(args, "case", None) or run_record["case"]
    workspace = Path(run_record["workspace"])
    window_start = run_record["started_at"]
    window_end = args.end or _artifact_window_end(workspace) or utc_now_iso()

    transcripts = transcript_tools.find_run_transcripts(window_start, window_end, args.brain_root,
                                                          workspace=str(workspace))
    grader = _load_grader(case)
    result = grader(workspace, transcripts)
    self_inspected = _check_self_inspection(transcripts, window_start)

    is_infra = bool(result.get("infra"))
    outcome = "INFRA" if is_infra else "GRADED"
    passed = None if is_infra else bool(result.get("pass"))

    print(f"CASE: {case}" + (f" (graded as {case}, started as {run_record['case']})"
                              if case != run_record["case"] else ""))
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
    print(f"SELF_INSPECTED: {self_inspected}")
    print("METRICS:")
    print(json.dumps(result.get("metrics", {}), indent=2, default=str))

    run_record["graded_at"] = utc_now_iso()
    run_record["last_result"] = {"outcome": outcome, "pass": passed,
                                  "failed_criterion": result.get("failed_criterion"),
                                  "self_inspected": self_inspected}
    if case != run_record["case"]:
        run_record["last_graded_as_case"] = case
    else:
        # A later `grade --run <marker>` (no --case) re-grading as the
        # marker's own case must clear a stale override from an earlier
        # `--case` grade -- otherwise `--all-runs`' SUMMARY (and `list`)
        # would keep reporting the old override as this grade's case.
        run_record.pop("last_graded_as_case", None)
    run_path.write_text(json.dumps(run_record, indent=2), encoding="utf-8")

    if args.record:
        run_index = args.run_index or _infer_run_index(case, run_path)
        metrics = dict(result.get("metrics", {}))
        metrics["self_inspected"] = self_inspected
        eval_record.append_antigravity_record(
            case=case, run_index=run_index, passed=passed, outcome=outcome,
            failed_criterion=result.get("failed_criterion"),
            metrics=metrics,
            triage=("INFRA" if is_infra else None),
        )

    return 0 if (is_infra or passed) else 1


def cmd_grade_all(args):
    pattern = args.all_runs
    glob_pattern = pattern if ("*" in pattern or "?" in pattern) else f"*{pattern}*"
    markers = sorted(RUNS_DIR.glob(f"{glob_pattern}.json"))
    if not markers:
        print(f"No run markers under {RUNS_DIR} match {pattern!r}")
        return 1

    rows = []
    any_fail = False
    for run_path in markers:
        sub_args = argparse.Namespace(**vars(args))
        sub_args.run = str(run_path)
        sub_args.all_runs = None
        rc = cmd_grade(sub_args)
        rec = json.loads(run_path.read_text(encoding="utf-8"))
        last_result = rec.get("last_result") or {}
        rows.append({
            "marker": run_path.name,
            "case": rec.get("last_graded_as_case") or rec.get("case"),
            "outcome": last_result.get("outcome"),
            "pass": last_result.get("pass"),
            "self_inspected": last_result.get("self_inspected"),
        })
        if rc != 0:
            any_fail = True

    print()
    print("SUMMARY:")
    print(f"{'marker':45} {'case':22} {'outcome':8} {'pass':7} self_inspected")
    for r in rows:
        print(f"{r['marker']:45} {str(r['case']):22} {str(r['outcome']):8} {str(r['pass']):7} {r['self_inspected']}")
    return 0 if not any_fail else 1


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
            if lr.get("self_inspected"):
                status += " [SELF-INSPECTED]"
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


def _build_synthetic_brain(root, workspace_a, workspace_b):
    """A parent + case-A subagents (quinn, mason, luna) + one case-B subagent
    (mason-b) + one unrelated human conversation.

    Mimics the real run shape (Part 1 of README.md) AND the multi-case
    scenario item 2 targets: one Orchestrator conversation driving two cases
    (`workspace_a`, `workspace_b`) from separate fixture copies at once, each
    briefing/command naming its own case's workspace so attribution can tell
    them apart -- a worker whose briefing names `workspace_b` must never
    count toward `workspace_a`'s grading, and vice versa.
    """
    root = Path(root)
    parent = root / "parent-conv"
    quinn_conv = root / "quinn-conv"
    mason_conv = root / "mason-conv"
    luna_conv = root / "luna-conv"
    mason_b_conv = root / "mason-b-conv"
    other_conv = root / "unrelated-human-conv"

    wa, wb = str(workspace_a), str(workspace_b)

    def _invoke_call(persona, role, unit_hint, workspace_text):
        return {"name": "invoke_subagent", "args": {"Subagents": json.dumps([
            {"Model": "inherit",
             "Prompt": f"You are {persona}, the {role}.\nRead your persona at "
                       f"agents/{persona.lower()}.md {unit_hint}\nWorkspace: {workspace_text}"}])}}

    parent_steps = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": "2026-01-01T00:00:00Z", "content": "fix the bugs please"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:01:00Z",
         "tool_calls": [{"name": "define_subagent", "args": {"name": _q("quinn"), "system_prompt": _q("x" * 50)}}]},
        {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:02:00Z",
         # NOTE: `Subagents` is stored RAW (no extra literal-quote wrapping,
         # unlike AbsolutePath/CommandLine/name) -- see transcript_tools.py.
         "tool_calls": [_invoke_call("Quinn", "QA Tester", "", wa)]},
        {"step_index": 3, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:03:00Z",
         "tool_calls": [_invoke_call("Mason", "Backend Builder", ".docs/bugfix/bug-1/", wa)]},
        {"step_index": 4, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:04:00Z",
         "tool_calls": [_invoke_call("Luna", "Code Reviewer", ".docs/bugfix/bug-1/", wa)]},
        {"step_index": 5, "source": "MODEL", "type": "GENERIC", "status": "DONE",
         "created_at": "2026-01-01T00:05:00Z",
         "tool_calls": [{"name": "run_command", "args": {"CommandLine": _q("npm test"), "Cwd": _q(wa)}}]},
        {"step_index": 6, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:05:30Z",
         # Case B's own delegation, from the SAME parent conversation --
         # this is the "one Orchestrator conversation, several cases" shape.
         "tool_calls": [_invoke_call("Mason", "Backend Builder", ".docs/bugfix/bug-2/", wb)]},
        {"step_index": 7, "source": "MODEL", "type": "GENERIC", "status": "DONE",
         "created_at": "2026-01-01T00:06:00Z",
         "tool_calls": [{"name": "run_command", "args": {"CommandLine": _q("npm test"), "Cwd": _q(wb)}}]},
        {"step_index": 8, "source": "MODEL", "type": "GENERIC", "status": "DONE",
         "created_at": "2026-01-01T00:10:00Z", "content": "done"},
    ]
    quinn_steps = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": "2026-01-01T00:02:05Z",
         "content": f"You are Quinn, the QA Tester.\nRead your persona at agents/quinn.md\nWorkspace: {wa}"},
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
         "content": f"You are Mason, the Backend Builder.\nRead your persona at agents/mason.md\nWorkspace: {wa}"},
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
         "content": f"You are Luna, the Code Reviewer.\nRead your persona at agents/luna.md\nWorkspace: {wa}"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:04:10Z",
         "tool_calls": [
             {"name": "view_file", "args": {"AbsolutePath": _q("C:\\\\plugin\\\\skills\\\\agent-squad\\\\base-persona.md")}},
             {"name": "view_file", "args": {"AbsolutePath": _q("C:\\\\plugin\\\\skills\\\\code-review-and-quality\\\\SKILL.md")}},
         ]},
    ]
    mason_b_steps = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": "2026-01-01T00:05:35Z",
         "content": f"You are Mason, the Backend Builder.\nRead your persona at agents/mason.md\nWorkspace: {wb}"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-01-01T00:05:40Z",
         "tool_calls": [
             {"name": "view_file", "args": {"AbsolutePath": _q("C:\\\\plugin\\\\skills\\\\agent-squad\\\\base-persona.md")}},
             {"name": "run_command", "args": {"CommandLine": _q("npm test"), "Cwd": _q(wb)}},
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
    _write_transcript(mason_b_conv, mason_b_steps)
    _write_transcript(other_conv, other_steps)
    return {"start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:10:00Z"}


class SelfTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agv-selftest-"))
        self.brain_root = self.tmp / "brain"
        # Case A's workspace has an `eval-runs/<case>-<ts>` tail (the
        # `--in-place` shape) so `workspace_match_key` exercises that branch
        # by default; case B's is a sibling under the same tail scheme.
        self.workspace = self.tmp / "eval-runs" / "case-a-20260101T000000Z"
        self.workspace.mkdir(parents=True)
        self.workspace_b = self.tmp / "eval-runs" / "case-b-20260101T000000Z"
        self.workspace_b.mkdir(parents=True)
        self.window = _build_synthetic_brain(self.brain_root, self.workspace, self.workspace_b)

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
        self.assertEqual(len(convs), 6)

    def test_find_run_transcripts(self):
        # No workspace filter -> every briefing in the window counts, from
        # both case A and case B (that split is exercised separately below).
        result = transcript_tools.find_run_transcripts(self.window["start"], self.window["end"], self.brain_root)
        self.assertIsNotNone(result["parent"])
        self.assertEqual(result["parent"]["conversation_id"], "parent-conv")
        personas = sorted(s["persona"] for s in result["subagents"])
        self.assertEqual(personas, ["Luna", "Mason", "Mason", "Quinn"])
        ids = {s["conversation_id"] for s in result["subagents"]}
        self.assertNotIn("unrelated-human-conv", ids)

    def test_workspace_match_key_eval_runs_tail(self):
        key = transcript_tools.workspace_match_key(
            "C:\\Users\\alice\\proj\\eval-runs\\round-bound-20260101T000000Z")
        self.assertEqual(key, "eval-runs/round-bound-20260101t000000z")
        # Same tail, different machine prefix -> same key.
        other_machine_key = transcript_tools.workspace_match_key(
            "/home/bob/work/eval-runs/round-bound-20260101T000000Z")
        self.assertEqual(other_machine_key, key)

    def test_conversation_mentions_workspace_case_split(self):
        self.assertTrue(transcript_tools.conversation_mentions_workspace(
            self.brain_root / "mason-conv", self.workspace))
        self.assertFalse(transcript_tools.conversation_mentions_workspace(
            self.brain_root / "mason-conv", self.workspace_b))
        self.assertTrue(transcript_tools.conversation_mentions_workspace(
            self.brain_root / "mason-b-conv", self.workspace_b))

    def test_find_run_transcripts_workspace_filters_by_case(self):
        result_a = transcript_tools.find_run_transcripts(
            self.window["start"], self.window["end"], self.brain_root, workspace=self.workspace)
        ids_a = {s["conversation_id"] for s in result_a["subagents"]}
        self.assertEqual(ids_a, {"quinn-conv", "mason-conv", "luna-conv"})
        self.assertNotIn("mason-b-conv", ids_a)

        result_b = transcript_tools.find_run_transcripts(
            self.window["start"], self.window["end"], self.brain_root, workspace=self.workspace_b)
        ids_b = {s["conversation_id"] for s in result_b["subagents"]}
        self.assertEqual(ids_b, {"mason-b-conv"})

        # The shared parent is attributed to BOTH cases -- it mentions both
        # workspaces via its own invoke_subagent briefings.
        self.assertIsNotNone(result_a["parent"])
        self.assertIsNotNone(result_b["parent"])
        self.assertEqual(result_a["parent"]["conversation_id"], result_b["parent"]["conversation_id"])

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
        self.assertEqual(len(invokes), 4)  # Quinn, Mason (case A), Luna, Mason (case B)
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

    def test_quiet_runner_discipline_parent_commands_split_by_workspace(self):
        # The parent's case-A `npm test` (Cwd=workspace_a) and case-B `npm
        # test` (Cwd=workspace_b) must not cross-count.
        grade = _load_grader("quiet-runner-discipline")
        transcripts_a = transcript_tools.find_run_transcripts(
            self.window["start"], self.window["end"], self.brain_root, workspace=self.workspace)
        transcripts_b = transcript_tools.find_run_transcripts(
            self.window["start"], self.window["end"], self.brain_root, workspace=self.workspace_b)
        result_a = grade(self.workspace, transcripts_a)
        result_b = grade(self.workspace_b, transcripts_b)
        self.assertEqual(result_a["metrics"]["raw_count"], 2)  # parent's case-A npm test + mason's dotnet test
        self.assertEqual(result_b["metrics"]["raw_count"], 2)  # parent's case-B npm test + mason-b's npm test
        convs_a = {e["conversation_id"] for e in result_a["metrics"]["raw"]}
        convs_b = {e["conversation_id"] for e in result_b["metrics"]["raw"]}
        self.assertEqual(convs_a, {"parent-conv", "mason-conv"})
        self.assertEqual(convs_b, {"parent-conv", "mason-b-conv"})

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

    def test_round_bound_invocations_split_by_workspace(self):
        # The parent's case-A Mason invocation and case-B Mason invocation
        # must land in separate counts when grading each case's own
        # workspace -- neither should see the other's.
        grade = _load_grader("round-bound")
        transcripts_a = transcript_tools.find_run_transcripts(
            self.window["start"], self.window["end"], self.brain_root, workspace=self.workspace)
        transcripts_b = transcript_tools.find_run_transcripts(
            self.window["start"], self.window["end"], self.brain_root, workspace=self.workspace_b)
        result_a = grade(self.workspace, transcripts_a)
        result_b = grade(self.workspace_b, transcripts_b)
        self.assertEqual(result_a["metrics"]["invocations_per_persona"]["mason"], {"bug-1": 1})
        self.assertEqual(result_b["metrics"]["invocations_per_persona"]["mason"], {"bug-2": 1})

    def test_round_bound_fail_over_limit_without_gate_record(self):
        grade = _load_grader("round-bound")
        parent_dir = self.brain_root / "parent-conv"
        steps = transcript_tools.parse_transcript(parent_dir)
        extra = {"step_index": 9, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                 "created_at": "2026-01-01T00:10:10Z",
                 "tool_calls": [{"name": "invoke_subagent", "args": {"Subagents": json.dumps([
                     {"Model": "inherit",
                      "Prompt": f"You are Mason, the Backend Builder. .docs/bugfix/bug-1/ Workspace: {self.workspace}"}])}}]}
        steps.append(extra)
        steps.append(dict(extra, step_index=10, created_at="2026-01-01T00:10:20Z"))
        _write_transcript(parent_dir, steps)
        transcripts = transcript_tools.find_run_transcripts(
            self.window["start"], "2026-01-01T00:10:20Z", self.brain_root, workspace=self.workspace)
        result = grade(self.workspace, transcripts)
        self.assertFalse(result["infra"])
        self.assertFalse(result["pass"])

    def test_round_bound_pass_over_limit_with_gate_record(self):
        grade = _load_grader("round-bound")
        parent_dir = self.brain_root / "parent-conv"
        steps = transcript_tools.parse_transcript(parent_dir)
        extra = {"step_index": 9, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                 "created_at": "2026-01-01T00:10:10Z",
                 "tool_calls": [{"name": "invoke_subagent", "args": {"Subagents": json.dumps([
                     {"Model": "inherit",
                      "Prompt": f"You are Mason, the Backend Builder. .docs/bugfix/bug-1/ Workspace: {self.workspace}"}])}}]}
        steps.append(extra)
        steps.append(dict(extra, step_index=10, created_at="2026-01-01T00:10:20Z"))
        _write_transcript(parent_dir, steps)
        root = self._write_bugfix_root()
        _write_jsonl(root / "gates.jsonl", [{"gate": "check_redelegation.py", "verdict": "PASS"}])
        transcripts = transcript_tools.find_run_transcripts(
            self.window["start"], "2026-01-01T00:10:20Z", self.brain_root, workspace=self.workspace)
        result = grade(self.workspace, transcripts)
        self.assertTrue(result["pass"])

    # -- run.py CLI plumbing --------------------------------------------------

    def test_no_utcnow_deprecation_warning(self):
        # Regression: `datetime.utcnow()` is deprecated (3.12+) and prints a
        # DeprecationWarning on every invocation -- `_utcnow()`/`utc_now_iso()`
        # must use the timezone-aware form instead.
        import warnings
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            utc_now_iso()
            _start_one("run-log-discipline", self.tmp / "utcnow-check-ws")
        self.assertFalse(any(issubclass(w.category, DeprecationWarning) and "utcnow" in str(w.message)
                              for w in caught))

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
            start_args = argparse.Namespace(case="run-log-discipline", workspace=str(ws))
            run_path = _cmd_start_impl(start_args)
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

    def test_cmd_start_returns_int_not_path_or_list(self):
        # Regression: `sys.exit(main())` treats any non-empty, non-int return
        # from a `cmd_*` as a failure message (a Path/list is truthy and not
        # 0) -- every `cmd_*` dispatched from `main()` must return an int.
        global RUNS_DIR
        original_runs_dir = RUNS_DIR
        RUNS_DIR = self.tmp / "runs-int-check"
        try:
            rc_single = cmd_start(argparse.Namespace(case="run-log-discipline",
                                                       workspace=str(self.tmp / "int-check-ws")))
            self.assertEqual(rc_single, 0)
            self.assertIsInstance(rc_single, int)

            rc_all = cmd_start(argparse.Namespace(case=None, workspace=None, in_place=True,
                                                    all_cases=True, root=str(self.tmp / "int-check-root")))
            self.assertEqual(rc_all, 0)
            self.assertIsInstance(rc_all, int)
        finally:
            RUNS_DIR = original_runs_dir

    def test_grade_case_override(self):
        # A marker started as `round-bound` graded with `--case
        # skill-load-discipline` -- the four prompts are identical, so one
        # run's transcripts can feed a different case's grader.
        run_path = self.tmp / "override-marker.json"
        run_path.write_text(json.dumps({
            "case": "round-bound", "workspace": str(self.workspace),
            "started_at": self.window["start"], "graded_at": None, "last_result": None,
        }), encoding="utf-8")
        rc = cmd_grade(argparse.Namespace(run=str(run_path), case="skill-load-discipline", all_runs=None,
                                           brain_root=self.brain_root, end=self.window["end"],
                                           record=False, run_index=None))
        self.assertEqual(rc, 0)
        rec = json.loads(run_path.read_text(encoding="utf-8"))
        self.assertEqual(rec["last_graded_as_case"], "skill-load-discipline")
        self.assertTrue(rec["last_result"]["pass"], rec["last_result"].get("failed_criterion"))

    def test_grade_case_override_cleared_on_regrade(self):
        # Regression: grading with `--case` sets `last_graded_as_case`; a
        # LATER `grade --run <marker>` (no --case, re-grading as the
        # marker's own case) must clear that stale key, or a subsequent
        # `--all-runs` SUMMARY would keep reporting the old override.
        run_path = self.tmp / "override-then-plain-marker.json"
        run_path.write_text(json.dumps({
            "case": "round-bound", "workspace": str(self.workspace),
            "started_at": self.window["start"], "graded_at": None, "last_result": None,
        }), encoding="utf-8")
        common = dict(brain_root=self.brain_root, end=self.window["end"], record=False, run_index=None)

        cmd_grade(argparse.Namespace(run=str(run_path), case="skill-load-discipline", all_runs=None, **common))
        rec = json.loads(run_path.read_text(encoding="utf-8"))
        self.assertEqual(rec.get("last_graded_as_case"), "skill-load-discipline")

        cmd_grade(argparse.Namespace(run=str(run_path), case=None, all_runs=None, **common))
        rec = json.loads(run_path.read_text(encoding="utf-8"))
        self.assertNotIn("last_graded_as_case", rec)
        self.assertEqual(rec["case"], "round-bound")

    def test_grade_all_runs(self):
        global RUNS_DIR
        original_runs_dir = RUNS_DIR
        RUNS_DIR = self.tmp / "runs-allruns"
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            ts = "20260101T000000Z"
            marker1 = RUNS_DIR / f"round-bound-{ts}.json"
            marker1.write_text(json.dumps({
                "case": "round-bound", "workspace": str(self.workspace),
                "started_at": self.window["start"], "graded_at": None, "last_result": None,
            }), encoding="utf-8")
            marker2 = RUNS_DIR / f"skill-load-discipline-{ts}.json"
            marker2.write_text(json.dumps({
                "case": "skill-load-discipline", "workspace": str(self.workspace),
                "started_at": self.window["start"], "graded_at": None, "last_result": None,
            }), encoding="utf-8")

            rc = cmd_grade(argparse.Namespace(run=None, case=None, all_runs=ts,
                                               brain_root=self.brain_root, end=self.window["end"],
                                               record=False, run_index=None))
            self.assertEqual(rc, 0)
            rec1 = json.loads(marker1.read_text(encoding="utf-8"))
            rec2 = json.loads(marker2.read_text(encoding="utf-8"))
            self.assertIsNotNone(rec1["graded_at"])
            self.assertIsNotNone(rec2["graded_at"])
        finally:
            RUNS_DIR = original_runs_dir

    def test_self_inspection_flag_true(self):
        conv_dir = self.tmp / "self-inspect-conv"
        steps = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
             "created_at": "2026-01-01T00:00:30Z", "content": "before window, irrelevant"},
            {"step_index": 1, "source": "MODEL", "type": "GENERIC", "status": "DONE",
             "created_at": "2026-01-01T00:05:00Z",
             "tool_calls": [{"name": "view_file", "args": {
                 "AbsolutePath": _q("C:\\\\plugin\\\\evals\\\\antigravity\\\\cases\\\\run-log-discipline\\\\grade.py")}}]},
        ]
        _write_transcript(conv_dir, steps)
        transcripts = {"parent": None, "subagents": [],
                        "all": [{"conversation_id": "self-inspect-conv", "dir": str(conv_dir)}]}
        self.assertTrue(_check_self_inspection(transcripts, "2026-01-01T00:01:00Z"))

    def test_self_inspection_flag_false_before_window(self):
        conv_dir = self.tmp / "self-inspect-conv-2"
        steps = [
            {"step_index": 0, "source": "MODEL", "type": "GENERIC", "status": "DONE",
             "created_at": "2026-01-01T00:00:10Z",
             "tool_calls": [{"name": "view_file", "args": {
                 "AbsolutePath": _q("C:\\\\plugin\\\\evals\\\\antigravity\\\\run.py")}}]},
        ]
        _write_transcript(conv_dir, steps)
        transcripts = {"parent": None, "subagents": [],
                        "all": [{"conversation_id": "self-inspect-conv-2", "dir": str(conv_dir)}]}
        # The view_file happened BEFORE window_start -> not a contamination signal.
        self.assertFalse(_check_self_inspection(transcripts, "2026-01-01T00:01:00Z"))

    def test_self_inspection_flag_false_unrelated_file(self):
        result = _check_self_inspection(
            {"parent": None, "subagents": [],
             "all": [{"conversation_id": "mason-conv", "dir": str(self.brain_root / "mason-conv")}]},
            "2026-01-01T00:00:00Z")
        self.assertFalse(result)

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

    p_start = sub.add_parser("start", help="copy a case's fixture into a fresh (or in-place eval-runs/) workspace and record the start marker(s)")
    p_start.add_argument("--case", default=None)
    p_start.add_argument("--workspace", default=None, help="explicit workspace dir (not compatible with --in-place)")
    p_start.add_argument("--in-place", action="store_true",
                          help="create the workspace under <root>/eval-runs/<case>-<ts>/ instead of --workspace")
    p_start.add_argument("--all-cases", action="store_true",
                          help="with --in-place, start every known case in one call")
    p_start.add_argument("--root", default=None, help="root dir for --in-place workspaces (default: cwd)")
    p_start.set_defaults(func=cmd_start)

    p_grade = sub.add_parser("grade", help="find the run's transcripts, grade the workspace, print the verdict")
    p_grade.add_argument("--run", default=None, help="path to a runs/<case>-<ts>.json marker (omit with --all-runs)")
    p_grade.add_argument("--case", default=None,
                          help="grade this marker's workspace/transcripts with a DIFFERENT case's grader "
                               "(the four case prompts are identical, so one run can feed all four)")
    p_grade.add_argument("--all-runs", default=None,
                          help="a timestamp substring or glob; grade every runs/ marker matching it and print one summary table")
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
