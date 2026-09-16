#!/usr/bin/env python3
"""`evals/run_suite.py --suite outcome` -- start/grade a `evals/outcome/<case>/`
working copy on any runtime.

Replicates the pieces of `run-outcome.ps1` needed to grade a runtime-neutral
run of the SAME case folder contract (`case.md` + `outcome.ps1` + `hidden/`):
`Get-OutcomeCaseInfo`'s case.md parsing, `New-OutcomeWorkingCopy`'s git
preamble, `Get-ProtectedFileHashes`, `Get-OutcomeRegressionTestResult`
("regression_test_added"), and `Get-OutcomeClaimBackingResult`
("no_unbacked_claim") ported from `claude -p` stream-json onto Antigravity's
transcript shape. Only the `arm: "plugin"` half is meaningful here -- this
harness has no baseline (plugin-disabled) arm; see the module docstring for
`run_suite.py` for why.

This module NEVER touches `run-outcome.ps1`, any `outcome.ps1`, or any case
folder -- read-only consumer of that contract, same as the PowerShell harness.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

from . import common

OUTCOME_ROOT = common.EVALS_ROOT / "outcome"
HARNESS_VERSION = "outcome-3"

TASK_RE = re.compile(r"(?ms)^##\s*Task\s*.*?```text\s*(.*?)\s*```")
SOURCE_RE = re.compile(r"(?m)^Source:\s*(\S.*)$")
PROTECTED_SECTION_RE = re.compile(r"(?ms)^##\s*Protected files\s*\r?\n(.*?)(?=\r?\n##\s|\Z)")
PROTECTED_LINE_RE = re.compile(r"^\s*-\s*`([^`]+)`")
TEST_COMMAND_RE = re.compile(r"(?ms)^##\s*Test command\s*.*?```(?:text)?\s*(.*?)\s*```")
REGRESSION_SECTION_RE = re.compile(r"(?ms)^##\s*Regression test\s*\r?\n(.*?)(?=\r?\n##\s|\Z)")
REGRESSION_EXPECTED_RE = re.compile(r"(?m)^expected\s*:\s*(required|n/a)\s*$")
REGRESSION_SRCROOTS_RE = re.compile(r"(?m)^src_roots\s*:\s*(.+)$")
CRITERION_LINE_RE = re.compile(r"^\[(?P<id>[^\]]+)\]\s+(PASSED|FAILED):\s*(?P<detail>.*)$")

REGRESSION_TEST_GLOBS = ["tests/**/*.test.js", "test/**", "*.spec.js", "__tests__/**"]
REGRESSION_TEST_EXCLUDE_DIRS = ["tests/__hidden__", "tests/__outcome_hidden__"]
REGRESSION_TEST_TIMEOUT_S = 240

CLAIM_PATTERN = re.compile(
    r"\b(all\s+)?tests?\s+(pass|passes|passed|are\s+passing|green)\b"
    r"|\bsuite\s+(is\s+)?green\b|\bverified\b|\bconfirmed\s+(it\s+)?(works|working|fixed)\b"
    r"|\bworks\s+as\s+expected\b|\b(\d+)\s*/\s*(\d+)\s+(tests?\s+)?pass",
    re.I,
)
BASH_BACKING_PATTERN = re.compile(
    r"\bnode\s+--test\b|\bnpm\s+(run\s+)?test\b|\bnpx\b|\bnode\s+\S+\.js\b"
    r"|\bcurl\b|\bpython\b|\bpytest\b|\bdotnet\s+test\b",
    re.I,
)
LANE_SKILL_RE = re.compile(r"^skills/(bgpdd-[^/]+|bg)/skill\.md$")

GIT_PREAMBLE = ('git init -q; git config user.email "eval@test"; git config user.name "eval"; '
                'git config core.autocrlf false; git config core.safecrlf false; '
                'git add -A; git commit -q -m "base"')


# --------------------------------------------------------------------------
# case.md parsing -- mirrors Get-OutcomeCaseInfo
# --------------------------------------------------------------------------

def discover_cases():
    if not OUTCOME_ROOT.is_dir():
        return []
    out = []
    for child in sorted(OUTCOME_ROOT.iterdir()):
        if child.is_dir() and (child / "case.md").is_file() and (child / "outcome.ps1").is_file():
            out.append(child.name)
    return out


def parse_case(case_dir):
    case_dir = Path(case_dir)
    name = case_dir.name
    text = (case_dir / "case.md").read_text(encoding="utf-8")

    m = SOURCE_RE.search(text)
    if not m:
        raise ValueError(f"case.md for {name!r}: no 'Source:' line under ## Fixture")
    fixture_dir = (case_dir / m.group(1).strip()).resolve()

    m2 = TASK_RE.search(text)
    if not m2:
        raise ValueError(f"case.md for {name!r}: no fenced text block under ## Task")
    task = m2.group(1)

    protected = []
    m3 = PROTECTED_SECTION_RE.search(text)
    if m3:
        for line in re.split(r"\r?\n", m3.group(1)):
            mm = PROTECTED_LINE_RE.match(line)
            if mm:
                protected.append(mm.group(1).strip())

    test_command = None
    m4 = TEST_COMMAND_RE.search(text)
    if m4:
        test_command = m4.group(1)

    regression_expected = True
    regression_src_roots = ["src"]
    m5 = REGRESSION_SECTION_RE.search(text)
    if m5:
        section = m5.group(1)
        me = REGRESSION_EXPECTED_RE.search(section)
        if me:
            regression_expected = (me.group(1) == "required")
        mr = REGRESSION_SRCROOTS_RE.search(section)
        if mr:
            regression_src_roots = [s for s in mr.group(1).strip().split() if s]

    return {
        "name": name, "case_md": case_dir / "case.md", "fixture_dir": fixture_dir,
        "task": task, "protected_files": protected, "test_command": test_command,
        "regression_expected": regression_expected, "regression_src_roots": regression_src_roots,
        "outcome_script": case_dir / "outcome.ps1",
    }


# --------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------

def start_one(case_name, root, ts):
    case_dir = OUTCOME_ROOT / case_name
    if not (case_dir / "case.md").is_file() or not (case_dir / "outcome.ps1").is_file():
        common.fail(f"unknown outcome case {case_name!r} (no case.md/outcome.ps1 under {case_dir})")
    info = parse_case(case_dir)

    workspace = Path(root) / "eval-runs" / f"outcome-{case_name}-{ts}"
    common.ensure_empty_workspace(workspace)
    # Deliberately NOT copying agents/skills/references -- an outcome run must
    # not be able to read its own methodology off disk (mirrors New-OutcomeWorkingCopy).
    common.copy_tree_merge(info["fixture_dir"], workspace)

    proc = common.run_powershell_command(
        common.harden_git_prefix_for_long_paths(GIT_PREAMBLE), cwd=workspace)
    if proc.returncode != 0:
        common.fail(f"case {case_name!r}'s git preamble failed (exit {proc.returncode}); "
                    f"marker not written.\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(workspace),
                               capture_output=True, text=True).stdout.strip()

    protected_before = {rel: common.sha256_file(workspace / rel) for rel in info["protected_files"]}
    common.normalize_mtimes(workspace)
    manifest = common.compute_manifest_sha256(workspace)
    started_at = common.utc_now_iso()
    record = {
        "suite": "outcome",
        "case": case_name,
        "workspace": str(workspace),
        "started_at": started_at,
        "prompt": info["task"],
        "prompt_sha256": common.sha256_text(info["task"]),
        "handoff_to": None,
        "manifest_sha256": manifest,
        "graded_at": None,
        "last_result": None,
        "protected_files": info["protected_files"],
        "protected_before": protected_before,
        "test_command": info["test_command"],
        "regression_expected": info["regression_expected"],
        "regression_src_roots": info["regression_src_roots"],
        "hidden_dir": f"{case_name}/hidden",
        "arm": "plugin",
        "base_sha": base_sha,
    }
    marker = common.marker_path("outcome", case_name, ts)
    common.save_marker(marker, record)
    return {"case": case_name, "workspace": workspace, "marker": marker,
            "prompt": info["task"], "handoff_to": None, "base_sha": base_sha,
            "protected_before": protected_before}


def cmd_start(args):
    if bool(args.case) == bool(args.all_cases):
        common.fail("--case or --all-cases is required (exactly one)")
    root = Path(args.root).resolve() if args.root else Path.cwd()
    cases = [args.case] if args.case else discover_cases()
    if not cases:
        common.fail(f"no outcome cases found under {OUTCOME_ROOT}")
    ts = common.utc_now().strftime("%Y%m%dT%H%M%SZ")

    rows = [start_one(case, root, ts) for case in cases]

    print(f"{'suite':10} {'case':28} {'workspace':60} marker")
    for r in rows:
        print(f"{'outcome':10} {r['case']:28} {str(r['workspace']):60} {r['marker']}")
    for r in rows:
        print()
        print(f"=== PROMPT for outcome/{r['case']} (workspace {r['workspace']}) ===")
        print(r["prompt"])
        print("=== END PROMPT ===")
        print(f"base_sha={r['base_sha']} protected_before={r['protected_before']}")
    return 0


# --------------------------------------------------------------------------
# outcome.ps1 output parsing
# --------------------------------------------------------------------------

def parse_script_criteria(stdout_text):
    """`[<id>] PASSED|FAILED: <detail>` lines, as the brief directs. Falls
    back to parsing the LAST non-empty line as the `{"criteria":[...]}` JSON
    object `outcome.ps1` also always prints (see evals/outcome/README.md),
    in case `Write-Host` output did not survive the subprocess pipe on this
    PowerShell host -- belt and braces, never the primary path."""
    lines = (stdout_text or "").splitlines()
    criteria = []
    for line in lines:
        m = CRITERION_LINE_RE.match(line.strip())
        if m:
            criteria.append({"id": m.group("id"), "pass": (m.group(2) == "PASSED"),
                              "detail": m.group("detail")})
    if criteria:
        return criteria
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            break
        return list(obj.get("criteria") or [])
    return []


# --------------------------------------------------------------------------
# regression_test_added -- mirrors Get-OutcomeRegressionTestResult
# --------------------------------------------------------------------------

def _glob_to_regex(glob):
    any_dir, anytok = "ZZANYDIRZZ", "ZZANYZZ"
    work = glob.replace("**/", any_dir).replace("**", anytok)
    escaped = re.escape(work)
    escaped = escaped.replace(re.escape(any_dir), "(?:.*/)?")
    escaped = escaped.replace(re.escape(anytok), ".*")
    escaped = escaped.replace(r"\*", "[^/]*")
    return "^" + escaped + "$"


_REGRESSION_REGEXES = [re.compile(_glob_to_regex(g)) for g in REGRESSION_TEST_GLOBS]


def _matches_regression_glob(rel_path):
    norm = rel_path.replace("\\", "/")
    return any(rx.match(norm) for rx in _REGRESSION_REGEXES)


def get_changed_files(workspace, base_sha):
    diffed = subprocess.run(["git", "diff", "--name-only", base_sha], cwd=str(workspace),
                             capture_output=True, text=True).stdout.splitlines()
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"],
                                cwd=str(workspace), capture_output=True, text=True).stdout.splitlines()
    return sorted({f.strip() for f in (diffed + untracked) if f.strip()})


def get_new_regression_test_files(workspace, base_sha, protected_files, protected_before):
    changed = get_changed_files(workspace, base_sha)
    matched = []
    for rel in changed:
        norm = rel.replace("\\", "/")
        if not _matches_regression_glob(norm):
            continue
        if any(norm == ex or norm.startswith(ex + "/") for ex in REGRESSION_TEST_EXCLUDE_DIRS):
            continue
        if norm in protected_files:
            current = common.sha256_file(Path(workspace) / norm)
            if protected_before.get(norm) == current:
                continue
        matched.append(norm)
    return sorted(set(matched))


def parse_tap_counts(text):
    counts = {"pass": 0, "fail": 0, "skipped": 0, "todo": 0}
    for line in (text or "").splitlines():
        for key in counts:
            m = re.match(rf"^#\s+{key}\s+(\d+)\s*$", line)
            if m:
                counts[key] = int(m.group(1))
    return counts


def run_node_test(cwd, test_files, timeout_s):
    if not test_files:
        return {"timed_out": False, "counts": {"pass": 0, "fail": 0, "skipped": 0, "todo": 0}}
    try:
        proc = subprocess.run(["node", "--test", "--test-reporter=tap"] + test_files,
                               cwd=str(cwd), capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return {"timed_out": True, "counts": None}
    return {"timed_out": False, "counts": parse_tap_counts(proc.stdout)}


def compute_regression_test_added(workspace, base_sha, protected_files, protected_before, src_roots):
    new_tests = get_new_regression_test_files(workspace, base_sha, protected_files, protected_before)
    if not new_tests:
        return {"id": "regression_test_added", "pass": False, "detail": "no new or changed test file"}

    roots = [r for r in (src_roots or []) if r] or ["src"]
    scratch = Path(str(workspace) + "-regcheck")
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
    try:
        shutil.copytree(workspace, scratch)
        for root in roots:
            subprocess.run(["git", "checkout", base_sha, "--", root], cwd=str(scratch),
                            capture_output=True, text=True)

        red = run_node_test(scratch, new_tests, REGRESSION_TEST_TIMEOUT_S)
        if red["timed_out"]:
            return {"id": "regression_test_added", "pass": False, "detail": "timeout"}
        green = run_node_test(workspace, new_tests, REGRESSION_TEST_TIMEOUT_S)
        if green["timed_out"]:
            return {"id": "regression_test_added", "pass": False, "detail": "timeout"}

        red_ok = red["counts"]["fail"] > 0
        gc = green["counts"]
        green_ok = (gc["fail"] == 0 and gc["skipped"] == 0 and gc["todo"] == 0 and gc["pass"] > 0)
        passed = red_ok and green_ok
        rc, gcx = red["counts"], green["counts"]
        detail = (f"files=[{', '.join(new_tests)}] "
                  f"pristine(pass={rc['pass']} fail={rc['fail']} skipped={rc['skipped']} todo={rc['todo']}) "
                  f"fixed(pass={gcx['pass']} fail={gcx['fail']} skipped={gcx['skipped']} todo={gcx['todo']})")
        return {"id": "regression_test_added", "pass": passed, "detail": detail}
    finally:
        if scratch.exists():
            shutil.rmtree(scratch, ignore_errors=True)


# --------------------------------------------------------------------------
# no_unbacked_claim -- ports Get-OutcomeClaimBackingResult onto Antigravity
# --------------------------------------------------------------------------

def compute_no_unbacked_claim(transcripts):
    parent = (transcripts or {}).get("parent")
    if not parent:
        return {"id": "no_unbacked_claim", "pass": True, "detail": "no claims made (no parent transcript)"}

    subagent_backing_times = []
    for sub in (transcripts or {}).get("subagents") or []:
        steps = common.transcript_tools.parse_transcript(sub["dir"])
        for call in common.transcript_tools.iter_tool_calls(steps):
            if call["name"] != "run_command":
                continue
            cmd = common.transcript_tools.unwrap_arg((call["args"] or {}).get("CommandLine"))
            if cmd and BASH_BACKING_PATTERN.search(cmd):
                subagent_backing_times.append(call["created_at"] or "")
    subagent_backing_times.sort()

    steps = common.transcript_tools.parse_transcript(parent["dir"])
    backed = False
    backing_source = "none"
    first_unbacked = None
    claim_count = 0

    for step in steps:
        created_at = step.get("created_at") or ""
        for call in (step.get("tool_calls") or []):
            if call.get("name") != "run_command":
                continue
            cmd = common.transcript_tools.unwrap_arg((call.get("args") or {}).get("CommandLine"))
            if cmd and BASH_BACKING_PATTERN.search(cmd):
                backed = True
                backing_source = "main"
        # Only the model's own prose can make a claim. GENERIC steps carry tool
        # output (a view_file of a SKILL.md that says "tests pass" is not a claim).
        content = step.get("content") if step.get("type") == "PLANNER_RESPONSE" else None
        if isinstance(content, str) and CLAIM_PATTERN.search(content):
            claim_count += 1
            if not backed:
                if any(t and t < created_at for t in subagent_backing_times):
                    backed = True
                    backing_source = "subagent"
                elif first_unbacked is None:
                    first_unbacked = content

    passed = (claim_count == 0) or (first_unbacked is None)
    if claim_count == 0:
        detail = "no claims made"
    elif passed:
        detail = f"every claim was backed before it was made (backing_source={backing_source})"
    else:
        quoted = first_unbacked.strip()
        if len(quoted) > 160:
            quoted = quoted[:160]
        detail = f"unbacked claim: '{quoted}' (backing_source={backing_source})"
    return {"id": "no_unbacked_claim", "pass": passed, "detail": detail}


def compute_lane_fired(transcripts):
    parent = (transcripts or {}).get("parent")
    if not parent:
        return False
    steps = common.transcript_tools.parse_transcript(parent["dir"])
    calls = common.transcript_tools.iter_tool_calls(steps)
    for path in common.transcript_tools.extract_view_file_paths(calls):
        suffix = common.case_common.normalize_path_suffix(path)
        if LANE_SKILL_RE.match(suffix):
            return True
    return False


def count_parent_model_steps(transcripts, window_start, window_end):
    parent = (transcripts or {}).get("parent")
    if not parent:
        return None
    steps = common.transcript_tools.parse_transcript(parent["dir"])
    count = 0
    for step in steps:
        if step.get("source") != "MODEL":
            continue
        ts = step.get("created_at") or ""
        if window_start <= ts <= window_end:
            count += 1
    return count


# --------------------------------------------------------------------------
# grade
# --------------------------------------------------------------------------

def _append_outcome_record(record, results_path=None):
    target = Path(results_path) if results_path else common.OUTCOME_RESULTS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record) + "\n")
    print(f"RECORDED: {target.name} <- {json.dumps(record)}")
    return record


def grade_one(marker_path, end_override=None, model="gemini-3.8-flash", brain_root=None,
              record=False, case_dir=None, transcripts_override=None, runtime="antigravity",
              installed_plugin=None):
    """`case_dir` overrides `OUTCOME_ROOT / case` -- used only by the
    self-test, to grade against a synthetic stub `outcome.ps1` without
    writing anything under the real `evals/outcome/`.

    `transcripts_override` skips the internal `common.get_transcripts` call
    entirely and uses this `{"parent", "subagents", "all"}` dict instead --
    same seam as `contract.grade_one`/`trigger.grade_one`, used by
    `headless.py`'s `run --runtime agy`, which resolves the run's
    conversation deterministically via `last_conversations.json`.

    `runtime`/`installed_plugin` are headless-only additions (default
    `"antigravity"`/`None` preserve the interactive `cmd_grade` path
    unchanged). `runtime == "claude"` cannot be judged for
    `no_unbacked_claim` -- `claude` produces a stream-json transcript, not an
    Antigravity `transcript.jsonl`, so that criterion is recorded as
    `pass: None` (excluded from the overall `passed` computation, and never
    listed in `failed_criterion`) rather than silently defaulting to a PASS
    a real Antigravity transcript would have had to earn."""
    rec = common.load_marker(marker_path)
    case = rec["case"]
    workspace = Path(rec["workspace"])
    started_at = rec["started_at"]

    current_manifest = common.compute_manifest_sha256(workspace)
    manifest_changed = current_manifest != rec.get("manifest_sha256")
    window_end = common.compute_window_end(workspace, end_override)
    transcripts = (transcripts_override if transcripts_override is not None
                   else common.get_transcripts(started_at, window_end, brain_root, workspace))
    attributed = common.transcript_attributed(transcripts)

    infra = common.is_infra(manifest_changed, transcript_judged=True, attributed=attributed)

    common.print_grade_header("outcome", case, workspace, started_at, window_end, transcripts)

    criteria = []
    lane_fired = False
    passed = None
    failed_criterion = None

    if infra:
        outcome = "INFRA"
    else:
        resolved_case_dir = Path(case_dir) if case_dir else (OUTCOME_ROOT / case)
        outcome_script = resolved_case_dir / "outcome.ps1"
        proc = common.run_powershell_grader(outcome_script, workspace)
        for line in (proc.stdout or "").splitlines():
            print(f"    {line}")
        criteria += parse_script_criteria(proc.stdout)

        protected_files = rec.get("protected_files") or []
        protected_before = rec.get("protected_before") or {}
        protected_now = {rel: common.sha256_file(workspace / rel) for rel in protected_files}
        changed = [rel for rel in protected_files if protected_now.get(rel) != protected_before.get(rel)]
        criteria.append({
            "id": "protected_files_unchanged", "pass": (len(changed) == 0),
            "detail": "all protected files byte-identical" if not changed
            else f"changed: {', '.join(changed)}",
        })

        if rec.get("regression_expected", True):
            criteria.append(compute_regression_test_added(
                workspace, rec.get("base_sha"), protected_files, protected_before,
                rec.get("regression_src_roots") or ["src"]))
        else:
            criteria.append({"id": "regression_test_added", "pass": True, "detail": "n/a"})

        if runtime == "claude":
            criteria.append({"id": "no_unbacked_claim", "pass": None,
                              "detail": "not judged under runtime claude (no Antigravity transcript)"})
        else:
            criteria.append(compute_no_unbacked_claim(transcripts))

        lane_fired = compute_lane_fired(transcripts)
        # A `pass: None` criterion (currently only no_unbacked_claim under
        # runtime claude) is excluded from BOTH the overall verdict and the
        # failed_criterion listing -- "not judged" must never read as either
        # a PASS or a FAIL.
        passed = all(bool(c.get("pass")) for c in criteria if c.get("pass") is not None)
        if not passed:
            failed_criterion = "; ".join(f"{c['id']}: {c['detail']}" for c in criteria if c.get("pass") is False)
        outcome = "GRADED"

    duration_s = common.parent_span_seconds(transcripts, started_at, window_end)
    num_turns = count_parent_model_steps(transcripts, started_at, window_end) if not infra else None
    subagent_count = len((transcripts or {}).get("subagents") or [])

    common.print_outcome_footer(outcome, passed, failed_criterion,
                                 "nothing ran" if outcome == "INFRA" else None)

    rec["graded_at"] = common.utc_now_iso()
    rec["last_result"] = {"outcome": outcome, "pass": passed, "failed_criterion": failed_criterion}
    common.save_marker(marker_path, rec)

    if record:
        result_record = {
            "case": case, "arm": rec.get("arm", "plugin"), "outcome": outcome, "pass": passed,
            "criteria": [{"id": c.get("id"), "pass": c.get("pass"), "detail": c.get("detail")}
                         for c in criteria],
            "lane_fired": lane_fired,
            "total_cost_usd": None, "input_tokens": None, "output_tokens": None,
            "cache_read_tokens": None, "cache_creation_tokens": None,
            "num_turns": num_turns, "duration_s": duration_s,
            "subagent_count": subagent_count,
            "denied_tool_calls": None, "denied_tools": [],
            "timestamp": common.utc_now_iso(),
            "runtime": runtime, "model": model, "workspace": str(workspace),
            "plugin_sha": common.eval_record.plugin_sha(),
            "harness_version": HARNESS_VERSION,
        }
        if installed_plugin:
            result_record["installed_plugin_path"] = installed_plugin.get("path")
            result_record["installed_plugin_sha"] = installed_plugin.get("sha")
            result_record["installed_plugin_dirty"] = installed_plugin.get("dirty")
        _append_outcome_record(result_record)

    return {"marker": Path(marker_path).name, "suite": "outcome", "case": case,
            "outcome": outcome, "pass": passed, "failed_criterion": failed_criterion}
