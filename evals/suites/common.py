#!/usr/bin/env python3
"""Shared plumbing for `evals/run_suite.py`'s four suite modules.

Replicates, in runtime-neutral Python, the pieces of `run-evals.ps1` and
`run-outcome.ps1` that every suite needs: workspace/manifest bookkeeping,
a `powershell.exe` shim for the PowerShell graders this repo already has
(`grade.ps1`, `outcome.ps1`) and for the one-line `git init ...` preambles
contract/outcome cases declare in their own `case.md`, and the marker
read/write shape shared by `start`/`grade`.

Pure standard library. Python 3.14 on Windows; every timestamp goes through
`datetime.now(timezone.utc)`, never the deprecated `utcnow()`.
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SUITES_DIR = Path(__file__).resolve().parent
EVALS_ROOT = SUITES_DIR.parent
PLUGIN_ROOT = EVALS_ROOT.parent

RUNS_DIR = EVALS_ROOT / "runs"
ANTIGRAVITY_RUNS_DIR = EVALS_ROOT / "antigravity" / "runs"
RESULTS_PATH = EVALS_ROOT / "results" / "results.jsonl"
OUTCOME_RESULTS_PATH = EVALS_ROOT / "outcome" / "results" / "results.jsonl"

sys.path.insert(0, str(EVALS_ROOT))
sys.path.insert(0, str(EVALS_ROOT / "antigravity"))
import eval_record  # noqa: E402
import transcript_tools  # noqa: E402
import case_common  # noqa: E402

ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"
ARTIFACT_WINDOW_BUFFER = timedelta(minutes=2)


# --------------------------------------------------------------------------
# time
# --------------------------------------------------------------------------

def utc_now():
    """Timezone-aware UTC now -- `datetime.utcnow()` is deprecated (3.12+)."""
    return datetime.now(timezone.utc)


def utc_now_iso():
    return utc_now().strftime(ISO_FMT)


def parse_iso(text):
    """Parse an ISO-8601 UTC ("...Z") timestamp into an aware datetime, or None."""
    if not text:
        return None
    t = text.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_iso(dt):
    return dt.astimezone(timezone.utc).strftime(ISO_FMT)


# --------------------------------------------------------------------------
# hashing / manifests
# --------------------------------------------------------------------------

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    path = Path(path)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compute_manifest_sha256(workspace):
    """sha256 over a sorted list of `<relpath>:<sha256 of that file>` lines,
    covering every file under `workspace` except anything under a `.git`
    directory. Used to answer "did anything in this workspace change since
    start" without a real git repo in every suite (trigger has none)."""
    workspace = Path(workspace)
    entries = []
    if workspace.is_dir():
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in files:
                fpath = Path(root) / name
                rel = fpath.relative_to(workspace).as_posix()
                try:
                    filehash = sha256_file(fpath)
                except OSError:
                    filehash = None
                entries.append(f"{rel}:{filehash}")
    entries.sort()
    return sha256_text("\n".join(entries))


def normalize_mtimes(workspace, when=None):
    """Set every file's mtime under `workspace` (excluding `.git`) to `when`
    (a `time.time()`-style float; default: now).

    `shutil.copytree` uses `copy2` by default, which preserves the SOURCE
    file's original mtime -- so a freshly built workspace's files carry
    whatever mtime they had in the plugin repo or the case's `fixture/`,
    not "now". Left alone, `latest_mtime_iso` (and therefore
    `compute_window_end`'s "latest mtime of any changed workspace file")
    would report the plugin's own most-recently-edited source file instead
    of anything the agent-under-test actually touched. Called once, right
    after a suite's `start_one` finishes building the workspace, so any
    later mtime newer than this baseline is a real post-start change."""
    workspace = Path(workspace)
    when = when if when is not None else datetime.now(timezone.utc).timestamp()
    for root, dirs, files in os.walk(workspace):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            fpath = Path(root) / name
            try:
                os.utime(fpath, (when, when))
            except OSError:
                pass


def latest_mtime_iso(workspace):
    """The latest mtime of any file under `workspace` (excluding `.git`), or None."""
    workspace = Path(workspace)
    latest = None
    if workspace.is_dir():
        for root, dirs, files in os.walk(workspace):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in files:
                fpath = Path(root) / name
                try:
                    mtime = fpath.stat().st_mtime
                except OSError:
                    continue
                if latest is None or mtime > latest:
                    latest = mtime
    if latest is None:
        return None
    dt = datetime.fromtimestamp(latest, tz=timezone.utc)
    return format_iso(dt)


def compute_window_end(workspace, override_end=None):
    """[started_at, --end | latest mtime of any changed workspace file + 2 min | now]."""
    if override_end:
        return override_end
    latest = latest_mtime_iso(workspace)
    if latest:
        dt = parse_iso(latest) + ARTIFACT_WINDOW_BUFFER
        return format_iso(dt)
    return utc_now_iso()


# --------------------------------------------------------------------------
# filesystem
# --------------------------------------------------------------------------

def copy_tree_merge(src, dst):
    """`shutil.copytree(src, dst, dirs_exist_ok=True)`, skipped if `src` has nothing."""
    import shutil
    src = Path(src)
    dst = Path(dst)
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def ensure_empty_workspace(workspace):
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    if any(workspace.iterdir()):
        raise SystemExit(f"error: workspace {workspace} is not empty; refusing to start into it")
    return workspace


def copy_plugin_agents_skills_references(workspace):
    """Copy the plugin's `agents/`, `skills/`, `references/` into `workspace`,
    exactly as `Invoke-ContractRun` does -- so a case prompt's relative paths
    (`agents/mason.md`, `skills/runtime-evidence/SKILL.md`) resolve for the
    agent-under-test, and the run is isolated from the live plugin tree."""
    for name in ("agents", "skills", "references"):
        copy_tree_merge(PLUGIN_ROOT / name, Path(workspace) / name)


# --------------------------------------------------------------------------
# PowerShell shim
# --------------------------------------------------------------------------

_GIT_INIT_CLAUSE_RE = re.compile(r"^(\s*git\s+init\b[^;]*;)")


def harden_git_prefix_for_long_paths(prefix):
    """Insert `git config core.longpaths true;` right after a leading
    `git init ...;` clause, local to that one repo -- never `--global`.

    Windows git without this refuses any path past ~260 chars with
    "Filename too long", and this plugin's own `skills/` tree (copied into
    every contract/outcome workspace) already has several paths that long
    on their own before a workspace root even enters the equation. Purely
    survives the platform limit; it changes no test semantics. A no-op on
    a prefix that doesn't open with `git init` (e.g. no prefix at all)."""
    m = _GIT_INIT_CLAUSE_RE.match(prefix)
    if not m:
        return prefix
    return prefix[:m.end()] + " git config core.longpaths true;" + prefix[m.end():]


def run_powershell_command(command_text, cwd, timeout=None):
    """Run `command_text` as a `powershell.exe -Command` script inside `cwd`.
    Used for a contract/outcome case's `git init ...` preamble. Returns a
    `subprocess.CompletedProcess` (never raises on a non-zero exit)."""
    if not command_text or not command_text.strip():
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", command_text],
        cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
    )


def run_powershell_grader(script_path, target_dir, timeout=None):
    """Run `<script_path> -TargetDir <target_dir>` (a `grade.ps1`/`outcome.ps1`
    call) via `powershell.exe -File`. Returns a `subprocess.CompletedProcess`."""
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script_path), "-TargetDir", str(target_dir)],
        capture_output=True, text=True, timeout=timeout,
    )


# --------------------------------------------------------------------------
# markers
# --------------------------------------------------------------------------

def marker_path(suite, case, ts):
    return RUNS_DIR / f"{suite}-{case}-{ts}.json"


def save_marker(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def load_marker(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_markers(pattern):
    """Every `evals/runs/*.json` and `evals/antigravity/runs/*.json` marker
    matching `pattern` (bare timestamp substring -> `*<pattern>*`, or a glob
    pattern used verbatim) -- the antigravity suite's own markers live in a
    different directory, and `--all-runs`/`list` must cover both."""
    glob_pattern = pattern if ("*" in pattern or "?" in pattern) else f"*{pattern}*"
    out = []
    if RUNS_DIR.is_dir():
        out += sorted(RUNS_DIR.glob(f"{glob_pattern}.json"))
    if ANTIGRAVITY_RUNS_DIR.is_dir():
        out += sorted(ANTIGRAVITY_RUNS_DIR.glob(f"{glob_pattern}.json"))
    return out


def infer_run_index(suite, case, this_marker_path):
    """1-based ordinal of `this_marker_path` among `<suite>-<case>-*.json`
    markers, by `started_at` -- mirrors `evals/antigravity/run.py`'s
    `_infer_run_index`."""
    this_marker_path = Path(this_marker_path)
    markers = sorted(RUNS_DIR.glob(f"{suite}-{case}-*.json"))
    starts = []
    for m in markers:
        try:
            rec = load_marker(m)
        except (OSError, json.JSONDecodeError):
            continue
        starts.append((rec.get("started_at", ""), m))
    starts.sort()
    for i, (_, m) in enumerate(starts, start=1):
        if Path(m) == this_marker_path:
            return i
    return 1


def fail(message, code=2):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def all_own_markers():
    """Every marker this module's own suites (contract/trigger/outcome) wrote,
    i.e. everything under `evals/runs/` -- excludes antigravity's own dir."""
    if not RUNS_DIR.is_dir():
        return []
    return sorted(RUNS_DIR.glob("*.json"))


# --------------------------------------------------------------------------
# transcript attribution
# --------------------------------------------------------------------------

def get_transcripts(window_start, window_end, brain_root, workspace):
    return transcript_tools.find_run_transcripts(window_start, window_end, brain_root,
                                                  workspace=str(workspace))


def transcript_attributed(transcripts):
    if not transcripts:
        return False
    if transcripts.get("parent"):
        return True
    if transcripts.get("subagents"):
        return True
    return False


def is_infra(manifest_changed, transcript_judged, attributed):
    """Common rule: INFRA when the manifest is unchanged AND, for a suite that
    judges off transcripts (trigger/outcome), no transcript was attributed
    either -- "nothing ran". A suite that is not transcript-judged (contract)
    needs only the manifest check: it is graded off workspace state, and a
    transcript existing with no workspace change still proves nothing to
    grade there."""
    if manifest_changed:
        return False
    if transcript_judged:
        return not attributed
    return True


def parent_span_seconds(transcripts, window_start, window_end):
    """Seconds between the parent conversation's first/last step, clipped to
    the grading window, or None if there is no attributed parent."""
    parent = (transcripts or {}).get("parent")
    if not parent:
        return None
    first = parse_iso(parent.get("first_ts"))
    last = parse_iso(parent.get("last_ts"))
    if not first or not last:
        return None
    ws = parse_iso(window_start)
    we = parse_iso(window_end)
    if ws and first < ws:
        first = ws
    if we and last > we:
        last = we
    if last < first:
        return 0.0
    return round((last - first).total_seconds(), 2)


def ordered_conversations(transcripts):
    """Parent first (if any), then subagents ordered by `first_ts` -- the
    order `skills_invoked`/`no_unbacked_claim` walk conversations in."""
    out = []
    parent = (transcripts or {}).get("parent")
    if parent:
        out.append(parent)
    subs = sorted((transcripts or {}).get("subagents") or [], key=lambda s: s.get("first_ts") or "")
    out += subs
    return out


# --------------------------------------------------------------------------
# console output
# --------------------------------------------------------------------------

def print_grade_header(suite, case, workspace, window_start, window_end, transcripts):
    print(f"CASE: {suite}/{case}")
    print(f"WORKSPACE: {workspace}")
    print(f"WINDOW: {window_start} -> {window_end}")
    parent = (transcripts or {}).get("parent")
    print(f"PARENT: {parent['conversation_id'] if parent else None}")
    print(f"SUBAGENTS: {[s['conversation_id'] for s in (transcripts or {}).get('subagents') or []]}")


def print_outcome_footer(outcome, passed, failed_criterion=None, infra_reason=None):
    if outcome == "INFRA":
        print(f"OUTCOME: INFRA ({infra_reason})")
    else:
        print(f"OUTCOME: {'PASS' if passed else 'FAIL'}")
        if failed_criterion:
            print(f"FAILED CRITERION: {failed_criterion}")


def print_summary_table(rows):
    """rows: list of dicts with marker, suite, case, outcome, pass, failed_criterion."""
    print()
    print("SUMMARY:")
    print(f"{'marker':45} {'suite':10} {'case':28} {'outcome':8} {'pass':7} failed_criterion")
    for r in rows:
        fc = (r.get("failed_criterion") or "")[:60]
        print(f"{r['marker']:45} {r['suite']:10} {r['case']:28} "
              f"{str(r['outcome']):8} {str(r['pass']):7} {fc}")
