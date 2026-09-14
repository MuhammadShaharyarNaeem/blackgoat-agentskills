#!/usr/bin/env python3
"""Runtime-neutral eval runner for the blackgoat-agentskills plugin.

Today `evals/antigravity/` is the only suite that can be started and graded
against a Google Antigravity (Gemini) run: `evals/contract/`, `evals/trigger/`
and `evals/outcome/` are driven by `claude -p` from PowerShell harnesses
(`evals/run-evals.ps1`, `evals/outcome/run-outcome.ps1`). Their GRADERS
(`contract/<case>/grade.ps1`, `outcome/<case>/outcome.ps1`) are already
runtime-neutral PowerShell scripts taking `-TargetDir <workspace>` --
what was missing was a way to START a case's working copy on any runtime,
hand the prompt to a human-driven Orchestrator session (Antigravity or
Claude Code), and then GRADE the result with those same unmodified graders.

This script is that missing piece. It never modifies `run-evals.ps1`,
`run-outcome.ps1`, any `grade.ps1`/`outcome.ps1`, any case, or
`evals/antigravity/cases/*` -- see each suite module's own docstring in
`evals/suites/` for exactly which PowerShell function it replicates and why.

    python run_suite.py start --suite {contract,trigger,outcome,antigravity} (--case <case> | --all-cases) --in-place [--root <dir>]
    python run_suite.py grade (--run <marker> | --all-runs <ts-or-glob>) [--record] [--brain-root <dir>] [--end <iso>] [--model <name>]
    python run_suite.py list
    python run_suite.py --self-test

Pure standard library. Python 3.14 on Windows.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "antigravity"))

from suites import common, contract, trigger, outcome, headless  # noqa: E402
import run as antigravity_run  # noqa: E402  (evals/antigravity/run.py)

SUITE_NAMES = ("contract", "trigger", "outcome", "antigravity")
RUN_SUITE_NAMES = headless.RUN_SUITES
RUN_RUNTIME_NAMES = headless.RUNTIMES


# --------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------

def cmd_start(args):
    if not args.in_place:
        common.fail("start requires --in-place (the only workspace scheme this runner supports)")

    if args.suite == "antigravity":
        ns = argparse.Namespace(case=args.case, workspace=None, in_place=True,
                                 all_cases=args.all_cases, root=args.root)
        antigravity_run._cmd_start_impl(ns)
        return 0
    if args.suite == "contract":
        return contract.cmd_start(args)
    if args.suite == "trigger":
        return trigger.cmd_start(args)
    if args.suite == "outcome":
        return outcome.cmd_start(args)
    common.fail(f"unknown --suite {args.suite!r} (expected one of {SUITE_NAMES})")


# --------------------------------------------------------------------------
# grade
# --------------------------------------------------------------------------

def determine_marker_suite(marker_path):
    """`"suite"` field on a contract/trigger/outcome marker; a marker under
    `evals/antigravity/runs/` (its own shape has no `"suite"` key) is always
    the antigravity suite."""
    marker_path = Path(marker_path)
    try:
        rec = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        rec = {}
    if "suite" in rec:
        return rec["suite"]
    return "antigravity"


def grade_dispatch(marker_path, args):
    suite = determine_marker_suite(marker_path)
    if suite == "contract":
        row = contract.grade_one(marker_path, end_override=args.end, model=args.model,
                                  brain_root=args.brain_root, record=args.record)
    elif suite == "trigger":
        row = trigger.grade_one(marker_path, end_override=args.end, model=args.model,
                                 brain_root=args.brain_root, record=args.record)
    elif suite == "outcome":
        row = outcome.grade_one(marker_path, end_override=args.end, model=args.model,
                                 brain_root=args.brain_root, record=args.record)
    elif suite == "antigravity":
        ns = argparse.Namespace(run=str(marker_path), case=None, all_runs=None,
                                 brain_root=args.brain_root, end=args.end,
                                 run_index=None, record=args.record)
        antigravity_run.cmd_grade(ns)
        rec = json.loads(Path(marker_path).read_text(encoding="utf-8"))
        last_result = rec.get("last_result") or {}
        row = {"marker": Path(marker_path).name, "suite": "antigravity",
               "case": rec.get("last_graded_as_case") or rec.get("case"),
               "outcome": last_result.get("outcome"), "pass": last_result.get("pass"),
               "failed_criterion": last_result.get("failed_criterion")}
    else:
        common.fail(f"marker {marker_path} names an unknown suite {suite!r}")
    return row


def cmd_grade(args):
    if args.all_runs:
        markers = common.find_markers(args.all_runs)
        if not markers:
            print(f"No run markers under evals/runs/ or evals/antigravity/runs/ match {args.all_runs!r}")
            return 1
        rows = [grade_dispatch(m, args) for m in markers]
        common.print_summary_table(rows)
        any_fail = any(r["outcome"] == "GRADED" and r["pass"] is False for r in rows)
        return 1 if any_fail else 0

    if not args.run:
        common.fail("--run is required (or use --all-runs)")
    row = grade_dispatch(Path(args.run), args)
    if row["outcome"] == "INFRA":
        return 0
    return 0 if row["pass"] else 1


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------

def cmd_list(args):
    print("Cases:")
    for c in contract.discover_cases():
        print(f"  contract/{c}")
    for c in trigger.discover_cases():
        print(f"  trigger/{c}")
    for c in outcome.discover_cases():
        print(f"  outcome/{c}")
    for c in antigravity_run._all_case_names():
        print(f"  antigravity/{c}")

    print()
    print("Run markers:")
    markers = common.all_own_markers()
    if common.ANTIGRAVITY_RUNS_DIR.is_dir():
        markers += sorted(common.ANTIGRAVITY_RUNS_DIR.glob("*.json"))
    for marker in markers:
        try:
            rec = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        suite = rec.get("suite", "antigravity")
        status = "not graded"
        if rec.get("last_result"):
            lr = rec["last_result"]
            status = str(lr.get("outcome"))
            if lr.get("outcome") == "GRADED":
                status += f" pass={lr.get('pass')}"
        print(f"  {marker.name}: suite={suite} case={rec.get('case')} "
              f"workspace={rec.get('workspace')} [{status}]")
    return 0


# --------------------------------------------------------------------------
# --self-test
# --------------------------------------------------------------------------

def cmd_self_test():
    from suites import selftest
    rc_own = selftest.run_self_test()
    print()
    print("=== evals/antigravity/run.py --self-test (unchanged surface, must stay green) ===")
    rc_antigravity = antigravity_run.run_self_test()
    if rc_own == 0 and rc_antigravity == 0:
        return 0
    return 1


# --------------------------------------------------------------------------
# argparse wiring
# --------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--self-test", action="store_true",
                         help="run the offline self-test for contract/trigger/outcome, "
                              "then evals/antigravity/run.py's own --self-test")
    sub = parser.add_subparsers(dest="cmd")

    p_start = sub.add_parser("start", help="build a case's working copy on any runtime and print its prompt")
    p_start.add_argument("--suite", choices=SUITE_NAMES, required=True)
    p_start.add_argument("--case", default=None, help="one case name (contract/outcome: the dir name; "
                                                        "trigger: trigger-<N>; antigravity: the case dir name)")
    p_start.add_argument("--all-cases", action="store_true", help="start every case in --suite")
    p_start.add_argument("--in-place", action="store_true",
                          help="required: workspace is <root>/eval-runs/<suite>-<case>-<ts>/")
    p_start.add_argument("--root", default=None, help="root dir for eval-runs/ (default: cwd)")
    p_start.set_defaults(func=cmd_start)

    p_grade = sub.add_parser("grade", help="grade a started workspace against its attributed transcript(s)")
    p_grade.add_argument("--run", default=None, help="path to a run marker (omit with --all-runs)")
    p_grade.add_argument("--all-runs", default=None,
                          help="a timestamp substring or glob; grade every marker matching it "
                               "under evals/runs/ and evals/antigravity/runs/, print one SUMMARY table")
    p_grade.add_argument("--record", action="store_true",
                          help="append a results.jsonl record for this grade")
    p_grade.add_argument("--brain-root", default=None,
                          help="override the Antigravity brain root (default: ~/.gemini/antigravity/brain)")
    p_grade.add_argument("--end", default=None,
                          help="override the grading window end (ISO-8601 UTC); default: derived "
                               "from the workspace's latest file mtime + 2 min, else now")
    p_grade.add_argument("--model", default="gemini-3.8-flash", help="recorded as the record's `model` field")
    p_grade.set_defaults(func=cmd_grade)

    p_list = sub.add_parser("list", help="list known cases (all four suites) and run markers")
    p_list.set_defaults(func=lambda a: cmd_list(a))

    p_run = sub.add_parser("run", help="headless: start, invoke a real runtime CLI, classify INFRA, "
                                        "grade and (optionally) record every run, unattended")
    p_run.add_argument("--runtime", choices=RUN_RUNTIME_NAMES, required=True)
    p_run.add_argument("--suite", choices=RUN_SUITE_NAMES, required=True)
    p_run.add_argument("--case", default=None)
    p_run.add_argument("--all-cases", action="store_true")
    p_run.add_argument("--runs", type=int, default=1)
    p_run.add_argument("--model", default=None, help="passed through verbatim to the runtime CLI; "
                                                       "default: omit the flag, record '<runtime>-default'")
    p_run.add_argument("--timeout", type=int, default=None,
                        help=f"seconds before a hard kill (default: {headless.DEFAULT_TIMEOUT_S})")
    p_run.add_argument("--root", default=None, help="root dir for eval-runs/ (default: cwd)")
    p_run.add_argument("--record", action="store_true", help="append results.jsonl / antigravity records")
    p_run.add_argument("--no-skip-permissions", action="store_true",
                        help="agy only: omit --dangerously-skip-permissions")
    p_run.add_argument("--preflight-probe", action="store_true",
                        help="add a live 'reply with the word READY' probe to preflight (spends tokens)")
    p_run.add_argument("--keep-workspaces", action="store_true",
                        help="never delete a run's workspace, even on PASS")
    p_run.add_argument("--brain-root", default=None,
                        help="agy only: override the antigravity-cli brain root "
                             "(default: ~/.gemini/antigravity-cli/brain)")
    p_run.add_argument("--installed-plugin-path", default=None,
                        help="override the installed-plugin path used for provenance "
                             "(default: agy -> ~/.gemini/config/plugins/blackgoat-agentskills, "
                             "claude -> ~/.claude/skills/blackgoat-agentskills)")
    p_run.set_defaults(func=headless.cmd_run)

    args = parser.parse_args(argv)

    if args.self_test:
        return cmd_self_test()
    if not args.cmd:
        parser.print_help()
        return 2
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
