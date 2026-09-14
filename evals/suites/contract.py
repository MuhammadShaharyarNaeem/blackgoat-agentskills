#!/usr/bin/env python3
"""`evals/run_suite.py --suite contract` -- start/grade a `evals/contract/<case>/`
working copy on any runtime, replicating `run-evals.ps1`'s `Invoke-ContractRun`
working-copy build and `Get-ContractCaseCommand`/`Get-ContractCaseDocsPath`/
`Get-ContractCaseMinDuration` in Python, then grading with the case's own
(unmodified) `grade.ps1` via `powershell.exe -File`.

The four zero-LLM `contract/*-adversarial/` and `mechanical-pipeline` dirs
have no `grade.ps1` and are excluded from discovery, exactly as
`Get-ContractCases` excludes them -- they already have `python run.py --record`.
"""
import re
from pathlib import Path

from . import common

CONTRACT_ROOT = common.EVALS_ROOT / "contract"

COMMAND_RE = re.compile(r"(?ms)^##\s*Command.*?```(?:powershell)?\s*(.*?)\s*```")
DOCS_PATH_RE = re.compile(r"(?m)^-\s*Copies to:\s*`([^`]+)`")
MIN_DURATION_RE = re.compile(r"(?ms)^##\s*Minimum duration\s*\r?\n+\s*(\d+)")
CLAUDE_P_RE = re.compile(r"\bclaude\s+-p\s+")
DEFAULT_MIN_DURATION = 60

# PowerShell backtick-escape map used inside a double-quoted string literal.
_BACKTICK_ESCAPES = {'"': '"', "n": "\n", "r": "\r", "t": "\t", "`": "`", "0": "\0", "'": "'"}


# --------------------------------------------------------------------------
# case.md parsing -- mirrors Get-ContractCaseCommand / Get-ContractCaseDocsPath /
# Get-ContractCaseMinDuration
# --------------------------------------------------------------------------

def discover_cases():
    """Every dir under `contract/` carrying BOTH `case.md` and `grade.ps1` --
    same filter as `Get-ContractCases`."""
    if not CONTRACT_ROOT.is_dir():
        return []
    out = []
    for child in sorted(CONTRACT_ROOT.iterdir()):
        if child.is_dir() and (child / "case.md").is_file() and (child / "grade.ps1").is_file():
            out.append(child.name)
    return out


def extract_command(text):
    m = COMMAND_RE.search(text)
    if not m:
        raise ValueError("No fenced powershell block found under '## Command'")
    return m.group(1).strip()


def extract_docs_path(text):
    m = DOCS_PATH_RE.search(text)
    if not m:
        raise ValueError("No '- Copies to: `path`' line found")
    return m.group(1).strip()


def extract_min_duration(text):
    m = MIN_DURATION_RE.search(text)
    if not m:
        return DEFAULT_MIN_DURATION
    try:
        value = int(m.group(1))
    except ValueError:
        return DEFAULT_MIN_DURATION
    return value if value > 0 else DEFAULT_MIN_DURATION


def parse_quoted_prompt(remainder):
    """`remainder` starts right after `claude -p `: either a PowerShell
    single-quoted literal (`'...'`, doubled `''` -> one literal apostrophe) or
    a double-quoted one (`"..."`, doubled `""` -> one literal quote, and a
    backtick escape -- `` `" ``, `` `n ``, `` `r ``, `` `t ``, `` `` ` ``,
    `` `0 `` -- for everything else). Returns `(prompt, end_index)` where
    `end_index` is the offset just past the closing quote."""
    if not remainder:
        raise ValueError("empty prompt remainder")
    quote = remainder[0]
    if quote not in ("'", '"'):
        raise ValueError(f"prompt does not start with a quote: {remainder[:40]!r}")
    buf = []
    i = 1
    n = len(remainder)
    while i < n:
        c = remainder[i]
        if quote == "'" and c == "'":
            if i + 1 < n and remainder[i + 1] == "'":
                buf.append("'")
                i += 2
                continue
            return "".join(buf), i + 1
        if quote == '"' and c == "`":
            if i + 1 < n:
                nc = remainder[i + 1]
                buf.append(_BACKTICK_ESCAPES.get(nc, nc))
                i += 2
                continue
            buf.append(c)
            i += 1
            continue
        if quote == '"' and c == '"':
            if i + 1 < n and remainder[i + 1] == '"':
                buf.append('"')
                i += 2
                continue
            return "".join(buf), i + 1
        buf.append(c)
        i += 1
    raise ValueError("unterminated quoted prompt")


HERE_STRING_VAR_RE = re.compile(r"^\$(\w+)\b")


def extract_here_string_prompt(command_text, varname):
    """`$<varname> = @'...'@` -- a PowerShell single-quoted here-string
    assignment, the shape `alex-domain-tags/case.md` uses so a long
    multi-paragraph prompt survives `Invoke-Expression` without being
    collapsed into one `-p '...'` line. The closing `'@` must open the line
    (no leading whitespace) per PowerShell's own here-string rule."""
    pattern = re.compile(rf"(?ms)^\s*\${re.escape(varname)}\s*=\s*@'\r?\n(.*?)\r?\n'@\s*$")
    m = pattern.search(command_text)
    return m.group(1) if m else None


def split_command(command_text):
    """`(prefix, prompt, handoff_to)` -- split at the `claude -p` token.
    `prefix` is everything before it (the `git init ...;` preamble, or `""`
    when the command opens directly with `claude -p`, as `luna-clean-approve`
    does). `handoff_to` is `"handoff.txt"` when the block ends in
    `Out-File -FilePath handoff.txt`, else `None`. Every other flag
    (`--permission-mode`, `--allowedTools`, ...) is ignored, as the brief
    directs -- a human/Orchestrator run has no headless permission model to
    configure.

    One case (`alex-domain-tags`) passes `-p $promptText`, a bare PowerShell
    variable assigned earlier in the same block from a here-string rather
    than a quoted literal -- handled by resolving the variable out of the
    prefix instead of treating it as a malformed quoted prompt. Running that
    prefix for real (as the caller does) is harmless: it only assigns the
    variable, never mind that this function reads its value directly instead."""
    m = CLAUDE_P_RE.search(command_text)
    if not m:
        raise ValueError("no 'claude -p' token found in Command block")
    prefix = command_text[:m.start()].strip()
    remainder = command_text[m.end():]
    remainder_stripped = remainder.lstrip()
    var_match = HERE_STRING_VAR_RE.match(remainder_stripped) if remainder_stripped[:1] not in ("'", '"') else None
    if var_match:
        varname = var_match.group(1)
        prompt = extract_here_string_prompt(command_text, varname)
        if prompt is None:
            raise ValueError(f"prompt variable ${varname} has no here-string assignment in the Command block")
    else:
        prompt, _end = parse_quoted_prompt(remainder)
    handoff_to = "handoff.txt" if "Out-File -FilePath handoff.txt" in command_text else None
    return prefix, prompt, handoff_to


# --------------------------------------------------------------------------
# start
# --------------------------------------------------------------------------

def build_working_copy(case, workspace):
    """Fixture -> `- Copies to:` path, then the plugin's agents/skills/references
    -- exactly as `Invoke-ContractRun` builds its temp dir. Returns the
    case.md text (already read once, so callers don't re-read it)."""
    case_dir = CONTRACT_ROOT / case
    case_md_path = case_dir / "case.md"
    text = case_md_path.read_text(encoding="utf-8")
    docs_rel = extract_docs_path(text)
    destination = Path(workspace) if docs_rel in (".", "") else Path(workspace) / docs_rel
    destination.mkdir(parents=True, exist_ok=True)
    common.copy_tree_merge(case_dir / "fixture", destination)
    common.copy_plugin_agents_skills_references(workspace)
    return text


def start_one(case, root, ts):
    workspace = Path(root) / "eval-runs" / f"contract-{case}-{ts}"
    common.ensure_empty_workspace(workspace)
    case_dir = CONTRACT_ROOT / case
    if not (case_dir / "case.md").is_file() or not (case_dir / "grade.ps1").is_file():
        common.fail(f"unknown contract case {case!r} (no case.md/grade.ps1 under {case_dir})")

    text = build_working_copy(case, workspace)
    command_text = extract_command(text)
    min_duration = extract_min_duration(text)
    prefix, prompt, handoff_to = split_command(command_text)

    if prefix:
        proc = common.run_powershell_command(
            common.harden_git_prefix_for_long_paths(prefix), cwd=workspace)
        if proc.returncode != 0:
            common.fail(
                f"case {case!r}'s Command prefix failed (exit {proc.returncode}); marker not written.\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )

    common.normalize_mtimes(workspace)
    manifest = common.compute_manifest_sha256(workspace)
    started_at = common.utc_now_iso()
    record = {
        "suite": "contract",
        "case": case,
        "workspace": str(workspace),
        "started_at": started_at,
        "prompt": prompt,
        "prompt_sha256": common.sha256_text(prompt),
        "handoff_to": handoff_to,
        "manifest_sha256": manifest,
        "graded_at": None,
        "last_result": None,
        "min_duration_s": min_duration,
    }
    marker = common.marker_path("contract", case, ts)
    common.save_marker(marker, record)
    return {"case": case, "workspace": workspace, "marker": marker,
            "prompt": prompt, "handoff_to": handoff_to}


def cmd_start(args):
    if bool(args.case) == bool(args.all_cases):
        common.fail("--case or --all-cases is required (exactly one)")
    root = Path(args.root).resolve() if args.root else Path.cwd()
    cases = [args.case] if args.case else discover_cases()
    if not cases:
        common.fail(f"no contract cases found under {CONTRACT_ROOT}")
    ts = common.utc_now().strftime("%Y%m%dT%H%M%SZ")

    rows = []
    for case in cases:
        rows.append(start_one(case, root, ts))

    print(f"{'suite':10} {'case':28} {'workspace':60} marker")
    for r in rows:
        print(f"{'contract':10} {r['case']:28} {str(r['workspace']):60} {r['marker']}")
    for r in rows:
        print()
        print(f"=== PROMPT for contract/{r['case']} (workspace {r['workspace']}) ===")
        print(r["prompt"])
        print("=== END PROMPT ===")
        if r["handoff_to"]:
            print(f"Reply capture: write the worker's final reply verbatim to "
                  f"{Path(r['workspace']) / r['handoff_to']}")
    return 0


# --------------------------------------------------------------------------
# grade
# --------------------------------------------------------------------------

def grade_one(marker_path, end_override=None, model="gemini-3.8-flash", brain_root=None,
              record=False, case_dir=None):
    """`case_dir` overrides `CONTRACT_ROOT / case` -- used only by the
    self-test, to grade against a synthetic stub `grade.ps1` without writing
    anything under the real `evals/contract/`."""
    rec = common.load_marker(marker_path)
    case = rec["case"]
    workspace = Path(rec["workspace"])
    started_at = rec["started_at"]

    current_manifest = common.compute_manifest_sha256(workspace)
    manifest_changed = current_manifest != rec.get("manifest_sha256")
    window_end = common.compute_window_end(workspace, end_override)
    transcripts = common.get_transcripts(started_at, window_end, brain_root, workspace)
    attributed = common.transcript_attributed(transcripts)

    infra = common.is_infra(manifest_changed, transcript_judged=False, attributed=attributed)
    infra_reason = "nothing ran" if infra else None
    passed = None
    failed_criterion = None
    outcome = "GRADED"

    if not infra and rec.get("handoff_to"):
        handoff_path = workspace / rec["handoff_to"]
        if not handoff_path.is_file() or not handoff_path.read_text(
                encoding="utf-8", errors="replace").strip():
            infra = True
            infra_reason = "handoff.txt not written"

    common.print_grade_header("contract", case, workspace, started_at, window_end, transcripts)

    resolved_case_dir = Path(case_dir) if case_dir else (CONTRACT_ROOT / case)

    if infra:
        outcome = "INFRA"
        passed = None
    else:
        grade_script = resolved_case_dir / "grade.ps1"
        proc = common.run_powershell_grader(grade_script, workspace)
        stdout_lines = (proc.stdout or "").splitlines()
        for line in stdout_lines:
            print(f"    {line}")
        passed = (proc.returncode == 0)
        if not passed:
            failed_lines = [l for l in stdout_lines if "FAILED:" in l]
            if failed_lines:
                failed_criterion = " | ".join(failed_lines)
            elif stdout_lines:
                failed_criterion = stdout_lines[-1]
            else:
                failed_criterion = f"grade.ps1 exited {proc.returncode}"

    duration_s = common.parent_span_seconds(transcripts, started_at, window_end)
    common.print_outcome_footer(outcome, passed, failed_criterion, infra_reason)

    rec["graded_at"] = common.utc_now_iso()
    rec["last_result"] = {"outcome": outcome, "pass": passed, "failed_criterion": failed_criterion}
    common.save_marker(marker_path, rec)

    if record:
        run_index = common.infer_run_index("contract", case, marker_path)
        common.eval_record.append_runtime_contract_record(
            case=case, run_index=run_index, passed=passed, outcome=outcome,
            failed_criterion=failed_criterion, duration_s=duration_s,
            runtime="antigravity", model=model, workspace=workspace,
            case_path=resolved_case_dir / "case.md",
        )

    return {"marker": Path(marker_path).name, "suite": "contract", "case": case,
            "outcome": outcome, "pass": passed, "failed_criterion": failed_criterion}
