#!/usr/bin/env python3
"""`evals/run_suite.py run` -- headless, unattended runs of the antigravity/
contract/trigger suites through a real runtime CLI (`agy` or `claude`),
end to end: start a workspace, invoke the CLI non-interactively, classify
INFRA, grade, optionally record, print one row per run and a SUMMARY table.

Ports (never re-implements) the semantics of `evals/run-evals.ps1`'s
headless `claude -p` harness -- `Invoke-ContractRun`, the trigger run,
`Get-InfraReason`, `Invoke-BatchPreflight` -- to a runtime-neutral Python
driver that also knows how to drive Google Antigravity's headless CLI
(`agy`), per the 2026-09-15 probe of `agy` v1.1.3 (see each builder
function's docstring for the exact CLI shape assumed).

Sequential only, by design: evals run one at a time, never in parallel
(MEMORY.md "Eval running rules"). `--runs` defaults to 1 -- the README's
`runs=5` is the convention a caller opts into, not this module's default.

Pure standard library. Python 3.14 on Windows; every timestamp goes through
`datetime.now(timezone.utc)`.
"""
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import common, contract, trigger, outcome

ANTIGRAVITY_DIR = common.EVALS_ROOT / "antigravity"
if str(ANTIGRAVITY_DIR) not in sys.path:
    sys.path.insert(0, str(ANTIGRAVITY_DIR))
import run as antigravity_run  # noqa: E402  (evals/antigravity/run.py)

# The plugin arm ONLY -- the baseline (plugin-disabled) arm needs the runtime's
# OWN plugin toggled off (`claude plugin disable ...`), which is a decision
# about the user's live install, not something this headless driver may do on
# its own (the user's decision, 2026-09-15). `evals/outcome/run-outcome.ps1`
# remains the only way to run the baseline arm.
RUN_SUITES = ("antigravity", "contract", "trigger", "outcome")
RUNTIMES = ("agy", "claude")

TRANSCRIPTS_DIR = common.EVALS_ROOT / "results" / "transcripts" / "headless"
# Module-level so the self-test can redirect it to a temp dir -- the INFRA
# quarantine file must never be the real evals/results/ during a test run.
RESULTS_DIR = common.EVALS_ROOT / "results"
# The outcome tier's own results/ dir (`evals/outcome/results/`) is a
# DIFFERENT directory from the shared `evals/results/` above -- its
# results.jsonl already lives there (`common.OUTCOME_RESULTS_PATH`), so its
# INFRA quarantine file sits next to it rather than in the shared dir.
OUTCOME_RESULTS_DIR = common.OUTCOME_RESULTS_PATH.parent

DEFAULT_TIMEOUT_S = 2700  # 45 minutes
# Headless workspaces live OUTSIDE the plugin checkout by default. In-place
# `start` puts them under cwd/eval-runs/ for the interactive skill, but a
# headless worker that searches one directory upward from such a workspace
# lands in the checkout itself -- graders included -- and the scope guard
# rightly flags it (bgpdd-bugfix-lane run 1 of the resumed 2026-09-14 batch:
# `find_by_name` on the checkout root). The system temp dir is already an
# allowed root, so a sibling-or-parent peek under it is harmless, exactly as
# run-evals.ps1's temp working copies are.
DEFAULT_RUN_ROOT = Path(tempfile.gettempdir()) / "bg-eval-runs"
HARD_KILL_GRACE_S = 60

AGY_CLI_BRAIN_ROOT = Path.home() / ".gemini" / "antigravity-cli" / "brain"
AGY_LAST_CONVERSATIONS_PATH = Path.home() / ".gemini" / "antigravity-cli" / "cache" / "last_conversations.json"

# The three evals/antigravity/ cases judged off a transcript (invoke_subagent
# counts, skill-read discipline, ...) rather than workspace artifacts alone --
# `run-log-discipline` is the one artifact-only case. `claude` has no
# Antigravity-shaped transcript to judge these from at all.
CLAUDE_ANTIGRAVITY_TRANSCRIPT_CASES = {"quiet-runner-discipline", "round-bound", "skill-load-discipline"}

INSTALLED_PLUGIN_PATHS = {
    "agy": Path.home() / ".gemini" / "config" / "plugins" / "blackgoat-agentskills",
    "claude": Path.home() / ".claude" / "skills" / "blackgoat-agentskills",
}


# --------------------------------------------------------------------------
# process invocation seam
# --------------------------------------------------------------------------

class ProcResult:
    """Uniform result of one CLI invocation -- what `RUNTIME_INVOKER` returns."""

    def __init__(self, stdout="", stderr="", returncode=0, duration_s=0.0, timed_out=False):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.duration_s = duration_s
        self.timed_out = timed_out


# Module-level so a self-test can shrink either for a fast, deterministic
# heartbeat assertion without waiting on a real 30 s interval.
HEARTBEAT_INTERVAL_S = 30
POLL_INTERVAL_S = 0.25


def default_invoke(argv, cwd, timeout_s):
    """Run `argv` with stdin closed (an empty file), capturing stdout/stderr.

    Popen + a poll loop, not one blocking `subprocess.run` call: a live
    `run --runtime agy/claude` prints nothing for however long the agent
    takes, which was mistaken for a hang and Ctrl+C'd mid-run on a perfectly
    healthy multi-minute call. This prints one heartbeat line to stderr
    every `HEARTBEAT_INTERVAL_S` seconds instead, and still returns the same
    `ProcResult` shape the rest of this module expects.

    The CLI's OWN timeout flag (`--print-timeout` for agy) should fire well
    before `timeout_s`; a Python-side hard kill fires `HARD_KILL_GRACE_S`
    seconds after it as a backstop for a CLI that ignores its own flag or
    hangs before it starts consuming its budget.
    """
    started = time.time()
    fd, empty_stdin_path = tempfile.mkstemp(prefix="bg-headless-stdin-")
    import os
    os.close(fd)
    runtime_name = argv[0] if argv else "?"
    hard_deadline = started + timeout_s + HARD_KILL_GRACE_S
    next_heartbeat = started + HEARTBEAT_INTERVAL_S
    try:
        with open(empty_stdin_path, "rb") as stdin_fh:
            proc = subprocess.Popen(argv, cwd=str(cwd), stdin=stdin_fh,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            timed_out = False
            stdout = stderr = ""
            while True:
                try:
                    stdout, stderr = proc.communicate(timeout=POLL_INTERVAL_S)
                    break
                except subprocess.TimeoutExpired:
                    # Safe to retry communicate() after this -- it never
                    # loses output already buffered (see the stdlib docs for
                    # Popen.communicate's timeout parameter).
                    now = time.time()
                    if now >= hard_deadline:
                        proc.kill()
                        try:
                            stdout, stderr = proc.communicate(timeout=HARD_KILL_GRACE_S)
                        except subprocess.TimeoutExpired:
                            stdout, stderr = stdout or "", stderr or ""
                        timed_out = True
                        break
                    if now >= next_heartbeat:
                        elapsed = int(now - started)
                        print(f"  ... waiting on {runtime_name} (elapsed {elapsed}s, timeout {timeout_s}s)",
                              file=sys.stderr)
                        next_heartbeat = now + HEARTBEAT_INTERVAL_S
            returncode = -1 if timed_out else proc.returncode
            return ProcResult(stdout or "", stderr or "", returncode,
                               time.time() - started, timed_out=timed_out)
    finally:
        try:
            Path(empty_stdin_path).unlink()
        except OSError:
            pass


# Module-level seam -- the self-test replaces this with a fake so it never
# invokes a real `agy`/`claude` process. Every code path below that needs to
# run a CLI goes through this name (never `subprocess` directly), so a test
# double sees every invocation this module makes.
RUNTIME_INVOKER = default_invoke


# --------------------------------------------------------------------------
# Go-duration formatting (agy's `--print-timeout`)
# --------------------------------------------------------------------------

def to_go_duration(total_seconds):
    """`2700` -> `"45m"`, `90` -> `"1m30s"` -- the flag format `agy
    --print-timeout` takes (a Go `time.Duration` literal)."""
    total_seconds = int(round(total_seconds))
    if total_seconds <= 0:
        return "0s"
    hours, rem = divmod(total_seconds, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return "".join(parts)


# --------------------------------------------------------------------------
# installed-plugin provenance (which tree the runtime actually loads)
# --------------------------------------------------------------------------

def _git_output(args, cwd):
    try:
        proc = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def git_head(path):
    out = _git_output(["rev-parse", "HEAD"], path)
    return out.strip() if out else None


def git_dirty(path):
    out = _git_output(["status", "--porcelain"], path)
    return bool(out and out.strip())


def installed_plugin_info(runtime, override_path=None):
    """`{"path", "sha", "dirty"}` for the plugin tree the RUNTIME actually
    loads -- not necessarily the checkout `run_suite.py` lives in. `agy`
    auto-loads its installed clone at `~/.gemini/config/plugins/
    blackgoat-agentskills` (slash commands, always-on index, personas);
    `claude` loads `~/.claude/skills/blackgoat-agentskills`. `override_path`
    (the `--installed-plugin-path` CLI flag) is for a worktree checkout or
    the self-test, where neither default applies."""
    path = Path(override_path) if override_path else INSTALLED_PLUGIN_PATHS.get(runtime)
    if not path or not Path(path).is_dir():
        return {"path": str(path) if path else None, "sha": None, "dirty": False}
    return {"path": str(path), "sha": git_head(path), "dirty": git_dirty(path)}


def print_installed_plugin_provenance(info):
    status = "dirty" if info["dirty"] else "clean"
    # Factual line only. The installed tree may deliberately differ from the
    # harness checkout (the Antigravity clone carries its own record_run
    # shape and explicit agent tools), so no comparison or warning is made
    # here -- the record's installed_plugin_* fields carry the facts.
    print(f"installed plugin: {info['path']} @ {info['sha']} ({status})")


# --------------------------------------------------------------------------
# INFRA classification
# --------------------------------------------------------------------------

AGY_INFRA_RE = re.compile(r"(?i)^jetski:|no output produced|auto-denied|headless mode cannot prompt")

# Ported verbatim from run-evals.ps1's $InfraOutputPatterns.
CLAUDE_INFRA_PATTERNS = [
    (re.compile(r"(?m)^\s*API Error"), "the CLI reported an API error"),
    (re.compile(r"(?i)requires approval"), "the run hit a permission prompt (requires approval)"),
    (re.compile(r"(?is)(?:api error|(?:^|[^a-z])error\s*[:\-]|\b429\b|\bclaude\b)[^\r\n]{0,60}?(usage limit|rate limit)"),
     "the run hit a usage or rate limit"),
    (re.compile(r"(?i)(usage limit|rate limit)[^\r\n]{0,60}?(exceeded|reached|hit|will reset|resets? at|try again)"),
     "the run hit a usage or rate limit"),
]


def classify_infra(runtime, text, timed_out, timeout_s=None, duration_s=None, min_duration_s=None):
    """`None` (not INFRA), or a short reason string. `text` is the effective
    output to judge -- see `effective_output_for_infra` for the Out-File
    exception (runtime claude, suite contract)."""
    if timed_out:
        return f"the run did not finish within its {timeout_s}s timeout" if timeout_s else "the run timed out"
    if not text or not text.strip():
        return "the agent produced no output at all (empty or whitespace stdout)"
    if runtime == "agy" and AGY_INFRA_RE.search(text):
        return ("permission_denied: a tool required a permission headless mode cannot prompt "
                "for, and it was auto-denied")
    if runtime == "claude":
        for pattern, reason in CLAUDE_INFRA_PATTERNS:
            if pattern.search(text):
                return reason
    if min_duration_s and duration_s is not None and duration_s < min_duration_s:
        return (f"the run finished in {duration_s}s, under this case's "
                f"{min_duration_s}s minimum expected duration")
    return None


def effective_output_for_infra(runtime, suite, handoff_to, workspace, stdout):
    """The Out-File exception: `runtime claude, suite contract` with a
    `handoff_to` pipes the agent's whole reply to `handoff.txt` INSIDE the
    Command block itself (`| Out-File -FilePath handoff.txt`), so the
    driving process's own captured stdout is empty by construction -- read
    the handoff file instead, exactly as `run-evals.ps1`'s
    `Resolve-AgentOutputText` does."""
    if runtime == "claude" and suite == "contract" and handoff_to:
        handoff_path = Path(workspace) / handoff_to
        if handoff_path.is_file():
            text = handoff_path.read_text(encoding="utf-8", errors="replace")
            if text.strip():
                return text
    return stdout


# --------------------------------------------------------------------------
# workspace-scope preamble (guard 1 -- the 2026-09-15 incident)
# --------------------------------------------------------------------------

def scope_preamble(workspace):
    """Exact text prepended to every prompt this runner composes for a
    headless CLI, naming `workspace` as the entire project and forbidding
    any excursion outside it. Mirrors what the interactive path already does
    (`skills/bg-eval/SKILL.md` Phase 2: "Your working copy is <workspace>.")
    -- headless now says the same thing, just more explicitly, since there is
    no human in the loop to notice a runaway.

    NEVER applied to `build_claude_contract_command_text`'s output: that path
    runs a case's own `## Command` block verbatim for parity with
    `run-evals.ps1`, and that block IS the measurement -- altering it would
    change what is being graded, not just what is being guarded."""
    return (f"Your working copy is {workspace}. Treat it as the entire project: every "
            "relative path resolves there. Do not read, search, or modify anything "
            "outside it; do not look for other repositories or projects on this "
            "machine; do not call external services, issue trackers, MCP tools, or "
            "the network. If something the task needs is not inside the working "
            "copy, stop and say so.")


def apply_scope_preamble(prompt, workspace):
    """`scope_preamble(workspace)` + two newlines + `prompt` verbatim."""
    return f"{scope_preamble(workspace)}\n\n{prompt}"


def _record_prompt_scope(marker_path, prompt_scoped, prompt_sent_sha256):
    """Adds `prompt_scoped`/`prompt_sent_sha256` to a start marker already on
    disk. Safe for any suite's marker (`common.save_marker`/`load_marker` are
    generic JSON read/write) -- including antigravity's, whose marker has no
    `prompt` field of its own at all. Written before the CLI is invoked, so a
    later fresh `load_marker` (`grade_one`, `_update_marker_result`) carries
    these two fields through untouched, exactly as it already carries every
    other pre-existing key."""
    rec = common.load_marker(marker_path)
    rec["prompt_scoped"] = prompt_scoped
    rec["prompt_sent_sha256"] = prompt_sent_sha256
    common.save_marker(marker_path, rec)


# --------------------------------------------------------------------------
# argv builders
# --------------------------------------------------------------------------

def build_argv_agy(prompt, model=None, timeout_s=DEFAULT_TIMEOUT_S, skip_permissions=True,
                    mode="accept-edits"):
    """`agy -p "<prompt>" --mode <mode> [--model "<name>"]
    --print-timeout <duration> [--dangerously-skip-permissions]` -- see the
    module docstring for the source probe. `mode` defaults to
    `"accept-edits"` for every suite except trigger under agy, which passes
    `"plan"` (guard 2 -- parity with the claude trigger run's own
    `--permission-mode plan`: a trigger case only needs to observe which
    skill gets read, never to let the model actually edit or run anything)."""
    argv = ["agy", "-p", prompt, "--mode", mode,
            "--print-timeout", to_go_duration(timeout_s)]
    if skip_permissions:
        argv.append("--dangerously-skip-permissions")
    if model:
        argv += ["--model", model]
    return argv


def build_argv_claude_trigger(prompt, model=None):
    argv = ["claude", "-p", prompt, "--permission-mode", "plan",
            "--output-format", "stream-json", "--verbose"]
    if model:
        argv = [argv[0], "--model", model] + argv[1:]
    return argv


def build_argv_claude_antigravity(prompt, model=None):
    argv = ["claude", "-p", prompt, "--permission-mode", "acceptEdits", "--allowedTools",
            "Bash,PowerShell,Read,Write,Edit,MultiEdit,Glob,Grep,Agent,Task,TodoWrite,Skill"]
    if model:
        argv = [argv[0], "--model", model] + argv[1:]
    return argv


# Verbatim from evals/outcome/run-outcome.ps1's $AllowedToolsArg -- both arms
# of the interactive outcome harness get this identical list (fairness), and
# the headless plugin-arm run below reuses it unchanged rather than drifting
# its own subset.
OUTCOME_ALLOWED_TOOLS_ARG = ("Bash,PowerShell,Read,Write,Edit,MultiEdit,NotebookEdit,Glob,Grep,"
                             "Agent,Task,TaskOutput,TaskStop,KillShell,BashOutput,TodoWrite,Skill,"
                             "ToolSearch,SendMessage,ListAgents,WebFetch,WebSearch")


def build_argv_claude_outcome(prompt, model=None):
    """Ports `Invoke-OutcomeClaudeRun`'s argv (run-outcome.ps1) onto
    headless's argv-list convention: `claude [--model M] -p <prompt>
    --permission-mode acceptEdits --allowedTools "<OUTCOME_ALLOWED_TOOLS_ARG>"
    --output-format stream-json --verbose`. stdin is the same empty file
    every headless argv gets (`default_invoke`)."""
    argv = ["claude", "-p", prompt, "--permission-mode", "acceptEdits",
            "--allowedTools", OUTCOME_ALLOWED_TOOLS_ARG,
            "--output-format", "stream-json", "--verbose"]
    if model:
        argv = [argv[0], "--model", model] + argv[1:]
    return argv


def build_claude_contract_command_text(command_text, model=None):
    """Insert `--model "<name>"` right after the literal `claude` token that
    precedes `-p`, when given -- otherwise the case's own Command block runs
    verbatim (prefix, `claude -p ...`, any trailing `| Out-File -FilePath
    handoff.txt`, all intact). PARITY with `run-evals.ps1`'s
    `Invoke-ContractRun`, which runs this same block through
    `Invoke-Expression`.

    Also hardens a leading `git init ...;` clause for Windows long paths
    (`common.harden_git_prefix_for_long_paths`) -- `contract.start_one`
    applies this when IT runs a case's prefix (the agy path), and this
    block's own `git init ...` needs the identical fix now that headless
    runs it here instead (a no-op on a block with no such prefix)."""
    text = command_text
    if model:
        m = contract.CLAUDE_P_RE.search(text)
        if m:
            quoted_model = model.replace('"', '`"')
            text = text[:m.start()] + f'claude --model "{quoted_model}" -p ' + text[m.end():]
    return common.harden_git_prefix_for_long_paths(text)


def build_argv_powershell(command_text):
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-Command", command_text]


# --------------------------------------------------------------------------
# claude stream-json trigger judging (port of run-evals.ps1's Invoke-TriggerJudge
# read path -- the Skill tool_use signal, not the Antigravity skill-read signal
# trigger.py's own extract_skills_invoked uses)
# --------------------------------------------------------------------------

def parse_claude_stream(text):
    msgs = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line[0] not in "{[":
            continue
        try:
            msgs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return msgs


def claude_skill_invocations(stream_text):
    """Every `Skill` tool_use in stream order, plugin namespace stripped
    (`'blackgoat-agentskills:bgpdd-plan'` -> `'bgpdd-plan'`)."""
    out = []
    for msg in parse_claude_stream(stream_text):
        if not isinstance(msg, dict):
            continue
        content = None
        message = msg.get("message")
        if isinstance(message, dict) and "content" in message:
            content = message["content"]
        elif "content" in msg:
            content = msg["content"]
        if not content:
            continue
        blocks = content if isinstance(content, list) else [content]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use" or block.get("name") != "Skill":
                continue
            inp = block.get("input") or {}
            raw = inp.get("skill") or inp.get("name")
            if not raw:
                continue
            out.append(re.sub(r"^.*:", "", str(raw)).strip())
    return out


def claude_stream_result_text(stream_text):
    text = None
    for msg in parse_claude_stream(stream_text):
        if isinstance(msg, dict) and msg.get("type") == "result" and "result" in msg:
            text = str(msg["result"])
    return text


def claude_mentioned_only(stream_text, expected_skill, acceptable_alternatives):
    """Diagnostic only -- mirrors `trigger.compute_mentioned_only`, sourced
    from the stream's final result text instead of an Antigravity transcript."""
    text = claude_stream_result_text(stream_text) or ""
    lowered = text.lower()
    for skill in [expected_skill] + list(acceptable_alternatives or []):
        if not skill:
            continue
        needle = skill.lower()
        start = 0
        while True:
            idx = lowered.find(needle, start)
            if idx == -1:
                break
            window = lowered[max(0, idx - 40):idx]
            if not any(neg in window for neg in trigger.NEGATION_WORDS):
                return True
            start = idx + len(needle)
    return False


# --------------------------------------------------------------------------
# agy conversation attribution
# --------------------------------------------------------------------------

def resolve_agy_conversation_id(workspace, cache_path=None):
    """The `agy` conversation id for `workspace`'s cwd, read from
    `~/.gemini/antigravity-cli/cache/last_conversations.json` (absolute cwd
    -> conversation id), or `None` if the CLI never ran there / the mapping
    file is missing. Compared via `normalize_path` on both sides."""
    cache_path = Path(cache_path) if cache_path else AGY_LAST_CONVERSATIONS_PATH
    if not cache_path.is_file():
        return None
    try:
        mapping = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    target = common.transcript_tools.normalize_path(str(workspace))
    for cwd_key, conversation_id in (mapping or {}).items():
        if common.transcript_tools.normalize_path(cwd_key) == target:
            return conversation_id
    return None


def resolve_agy_transcripts(workspace, window_start, window_end, brain_root=None, cache_path=None):
    """Attribute a headless `agy` run's conversation deterministically via
    `last_conversations.json`; fall back to the window/workspace-mention
    heuristic (`find_run_transcripts`) when the mapping has no entry."""
    brain_root = brain_root or AGY_CLI_BRAIN_ROOT
    conversation_id = resolve_agy_conversation_id(workspace, cache_path=cache_path)
    if conversation_id:
        transcripts = common.transcript_tools.transcripts_for_conversation(
            conversation_id, window_start, window_end, brain_root)
        if transcripts.get("parent"):
            return transcripts
    return common.transcript_tools.find_run_transcripts(
        window_start, window_end, brain_root, workspace=str(workspace))


# --------------------------------------------------------------------------
# workspace-scope tripwire (guard 3 -- the 2026-09-15 incident)
# --------------------------------------------------------------------------

# Antigravity/agy tool names whose path-like argument must resolve inside an
# allowed root. Checked in this order against each call's own `args` dict --
# whichever key is present wins (a call carries exactly one of these).
_SCOPE_GUARD_PATH_TOOLS = ("view_file", "list_dir", "find_by_name", "grep_search",
                           "write_to_file", "replace_file_content", "multi_replace_file_content")
_SCOPE_GUARD_PATH_ARG_KEYS = ("AbsolutePath", "DirectoryPath", "SearchDirectory", "TargetFile", "Path")

# Any call to one of these is a flag regardless of its arguments -- the
# incident's four `call_mcp_tool` calls to `linear` had no in-workspace
# reading at all; the point is that a headless run must never reach an
# external service, full stop.
_SCOPE_GUARD_NETWORK_TOOLS = ("read_url_content", "search_web", "call_mcp_tool")

_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
# A drive-letter token must not be preceded by a letter or digit: `http://` ends in
# `p:/` and matched the unanchored form, flagging every `curl http://localhost:...`
# reproduction command as an escape (bgpdd-bugfix-lane run 1, 2026-09-14 22:56Z).
_WINDOWS_ABS_PATH_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']*")


def _is_absolute_windows_path(path):
    if not path:
        return False
    return bool(_WINDOWS_ABS_PATH_RE.match(path.strip().strip('"').strip("'")))


def _path_within_roots(path, normalized_roots):
    """True if `path`'s normalized segments start with one allowed root's
    segments -- a prefix match on path SEGMENTS (`C:/Gorelo` must not match
    an allowed root `C:/Go`), never a bare string prefix."""
    norm = common.transcript_tools.normalize_path(path)
    segs = [p for p in norm.split("/") if p]
    for root in normalized_roots:
        root_segs = [p for p in root.split("/") if p]
        if root_segs and segs[:len(root_segs)] == root_segs:
            return True
    return False


def scope_guard_allowed_roots(workspace, installed_plugin_path, brain_root=None):
    """Every root a headless run's own tool calls may legitimately touch:
    the workspace itself, the installed plugin tree, the Antigravity CLI's
    own scratch/brain dirs (`~/.gemini/antigravity-cli/`, `~/.gemini/
    antigravity/`), the resolved `brain_root` (when it differs), the system
    temp dir, and the running interpreter's own installation dir(s) -- a
    headless run legitimately shells out to `python`/`pip` from its
    workspace, but `python`/its stdlib living outside the workspace is not
    itself an escape."""
    roots = [str(workspace)]
    if installed_plugin_path:
        roots.append(str(installed_plugin_path))
    roots.append(str(Path.home() / ".gemini" / "antigravity-cli"))
    roots.append(str(Path.home() / ".gemini" / "antigravity"))
    if brain_root:
        roots.append(str(brain_root))
    roots.append(str(Path(tempfile.gettempdir())))
    roots.append(str(Path(sys.exec_prefix)))
    if sys.prefix != sys.exec_prefix:
        roots.append(str(Path(sys.prefix)))
    return [common.transcript_tools.normalize_path(r) for r in roots if r]


def _scope_guard_path_arg(call):
    args = call.get("args") or {}
    for key in _SCOPE_GUARD_PATH_ARG_KEYS:
        if key in args:
            return common.transcript_tools.unwrap_arg(args.get(key))
    return None


def _scope_guard_mcp_argument(call):
    """Best-effort human-readable label for a `call_mcp_tool` call -- the
    exact arg-key names an installed MCP client uses aren't part of this
    repo's documented transcript shape, so this reads whichever of the
    plausible keys is present rather than assuming one."""
    args = call.get("args") or {}
    server = common.transcript_tools.unwrap_arg(
        args.get("ServerName") or args.get("Server") or args.get("server"))
    tool = common.transcript_tools.unwrap_arg(
        args.get("ToolName") or args.get("Tool") or args.get("tool"))
    if server or tool:
        return " ".join(p for p in (server, tool) if p)
    return "call_mcp_tool"


def detect_workspace_escape(transcripts, workspace, installed_plugin_path, brain_root=None):
    """Post-run tripwire for the 2026-09-15 incident: a headless run that
    wanders outside its fixture workspace while permissions are skipped --
    searching the machine for a "real" repository, grepping another project,
    calling an issue tracker over MCP. Meaningful only for `agy`'s own
    Antigravity-shaped transcripts (`view_file`/`run_command`/`call_mcp_tool`
    are agy's tool vocabulary, not `claude`'s); a caller with no such
    transcript should not call this at all -- see each `_run_*`'s
    `left_workspace: null` handling for `runtime == "claude"`.

    Walks every attributed conversation (`transcripts["all"]`, chronological
    by `first_ts` -- the same "lives only in transcripts['all']" case
    `trigger.py`'s module docstring rule 2 documents: a bare-prompt headless
    run has no `"You are <Name>, the ..."` briefing opener, so it is neither
    `parent` nor a `subagent`), and within each, its steps/tool calls in file
    order. Flags:

      - a path-arg tool (`view_file`, `list_dir`, `find_by_name`,
        `grep_search`, `write_to_file`, `replace_file_content`,
        `multi_replace_file_content`) whose path argument is an absolute
        Windows path outside every allowed root;
      - a `run_command` whose `Cwd` is an absolute path outside every
        allowed root, OR whose `CommandLine` contains an absolute-path
        token (`[A-Za-z]:\\` / `[A-Za-z]:/`) outside every allowed root --
        `git -C C:\\Gorelo\\X grep ...` run from inside the workspace is
        still an escape;
      - any `call_mcp_tool` at all;
      - any `read_url_content`/`search_web` call, or a tool whose name
        contains "browser".

    Returns `{"escaped": bool, "first": {"tool", "argument", "created_at",
    "conversation_id"} | None, "count": int}` -- `first` is always the FIRST
    escaping call encountered in the walk order above, never the worst or
    the last."""
    roots = scope_guard_allowed_roots(workspace, installed_plugin_path, brain_root)
    convs = sorted((transcripts or {}).get("all") or [], key=lambda c: c.get("first_ts") or "")
    first = None
    count = 0
    for conv in convs:
        steps = common.transcript_tools.parse_transcript(conv["dir"])
        for call in common.transcript_tools.iter_tool_calls(steps):
            name = call.get("name")
            argument = None
            if name in _SCOPE_GUARD_PATH_TOOLS:
                path = _scope_guard_path_arg(call)
                if path and _is_absolute_windows_path(path) and not _path_within_roots(path, roots):
                    argument = path
            elif name == "run_command":
                args = call.get("args") or {}
                cwd = common.transcript_tools.unwrap_arg(args.get("Cwd"))
                cmdline = common.transcript_tools.unwrap_arg(args.get("CommandLine")) or ""
                if cwd and _is_absolute_windows_path(cwd) and not _path_within_roots(cwd, roots):
                    argument = cmdline or cwd
                else:
                    for token in _WINDOWS_ABS_PATH_TOKEN_RE.findall(cmdline):
                        if not _path_within_roots(token, roots):
                            argument = cmdline
                            break
            elif name == "call_mcp_tool":
                argument = _scope_guard_mcp_argument(call)
            elif name in ("read_url_content", "search_web") or (name and "browser" in name.lower()):
                argument = name
            if argument is not None:
                count += 1
                if first is None:
                    first = {"tool": name, "argument": argument,
                             "created_at": call.get("created_at"),
                             "conversation_id": conv.get("conversation_id")}
    return {"escaped": first is not None, "first": first, "count": count}


def _report_workspace_escape(escape_result):
    first = escape_result["first"]
    print(f"LEFT WORKSPACE: {first['tool']} {first['argument']} at {first['created_at']} "
          f"({escape_result['count']} call(s) outside the workspace)")


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------

def preflight_agy(probe=False):
    try:
        proc = subprocess.run(["agy", "agents"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not run `agy agents`: {exc}"
    out = proc.stdout or ""
    if proc.returncode != 0 or "luna" not in out or "mason" not in out:
        return False, (f"`agy agents` did not list both luna and mason -- is the plugin loaded "
                        f"from {INSTALLED_PLUGIN_PATHS['agy']}?")
    if probe:
        result = RUNTIME_INVOKER(["agy", "-p", "reply with the word READY", "--print-timeout", "2m"],
                                  Path.cwd(), 120)
        if "READY" not in (result.stdout or ""):
            return False, "agy preflight probe did not reply READY"
    return True, None


def preflight_claude(probe=False):
    try:
        proc = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not run `claude --version`: {exc}"
    if proc.returncode != 0:
        return False, "`claude --version` failed"
    if probe:
        result = RUNTIME_INVOKER(["claude", "-p", "reply with the word READY", "--output-format", "json"],
                                  Path.cwd(), 120)
        if "READY" not in (result.stdout or ""):
            return False, "claude preflight probe did not reply READY"
    return True, None


# --------------------------------------------------------------------------
# execution + archiving + INFRA retry
# --------------------------------------------------------------------------

def _execute_with_retry(argv_builder, cwd, timeout_s, runtime, suite, handoff_to, min_duration_s=None,
                         transcripts_resolver=None, installed_plugin_path=None, brain_root=None):
    """Runs `argv_builder()` via `RUNTIME_INVOKER`, classifies INFRA, and
    retries ONCE on INFRA only -- a graded FAIL is a measurement and is
    never re-rolled (`run-evals.ps1`'s rule).

    Guard 3 extension: when `transcripts_resolver` is given (every `_run_*`
    passes one only for `runtime == "agy"` -- `claude` has no
    Antigravity-shaped transcript to check), a text-clean attempt is ALSO
    run through `detect_workspace_escape` before being accepted; an escape
    is classified INFRA with reason `"left_workspace"` and retried exactly
    like any other INFRA reason (one retry total, not one retry per cause).
    `transcripts_resolver` is called only after the CLI has actually run
    (it needs a live conversation to attribute).

    Returns `(argv, proc, infra_reason_or_None, transcripts_or_None,
    escape_result_or_None)` -- the last two are `None` whenever
    `transcripts_resolver` was not given or was never reached."""
    argv = proc = reason = None
    transcripts = escape_result = None
    for attempt in (1, 2):
        argv = argv_builder()
        proc = RUNTIME_INVOKER(argv, cwd, timeout_s)
        text = effective_output_for_infra(runtime, suite, handoff_to, cwd, proc.stdout)
        reason = classify_infra(runtime, text, proc.timed_out, timeout_s=timeout_s,
                                 duration_s=proc.duration_s, min_duration_s=min_duration_s)
        transcripts = escape_result = None
        if not reason and transcripts_resolver is not None:
            transcripts = transcripts_resolver()
            escape_result = detect_workspace_escape(transcripts, cwd, installed_plugin_path, brain_root)
            if escape_result["escaped"]:
                _report_workspace_escape(escape_result)
                reason = "left_workspace"
        if not reason:
            return argv, proc, None, transcripts, escape_result
        print(f"    run classified INFRA ({reason})"
              + (" -- retrying once" if attempt == 1 else " after retry"))
    return argv, proc, reason, transcripts, escape_result


def _quote_for_display(token):
    return token if (token and " " not in token and "\n" not in token) else json.dumps(token)


def archive_run(suite, case, ts, argv, proc, extra_files=None):
    d = TRANSCRIPTS_DIR / f"{suite}-{case}-{ts}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "command.txt").write_text(" ".join(_quote_for_display(a) for a in argv), encoding="utf-8")
    (d / "stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
    (d / "stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
    for name, content in (extra_files or {}).items():
        (d / name).write_text(content or "", encoding="utf-8")
    return d


def invalid_infra_path():
    return RESULTS_DIR / f"results-invalid-infra-{common.utc_now().strftime('%Y-%m-%d')}.jsonl"


def outcome_invalid_infra_path():
    """Next to the outcome tier's OWN results.jsonl (`evals/outcome/results/`),
    not the shared `evals/results/` `invalid_infra_path()` above uses -- the
    outcome tier's results file already lives in a different directory."""
    return OUTCOME_RESULTS_DIR / f"results-invalid-infra-{common.utc_now().strftime('%Y-%m-%d')}.jsonl"


def write_handoff_if_needed(runtime, handoff_to, workspace, stdout):
    """Writes `<workspace>/<handoff_to>` from the CLI's captured stdout --
    only when the marker names a handoff file AND the runtime didn't already
    write it itself. `claude`+contract's own Command block pipes its reply
    to `handoff.txt` via `| Out-File` as part of the block that ran; `agy`
    has no such redirection and always prints its final reply to stdout, so
    headless must create the file itself. Returns whether it wrote anything."""
    if not handoff_to or runtime == "claude":
        return False
    (Path(workspace) / handoff_to).write_text(stdout or "", encoding="utf-8")
    return True


def _write_invalid_infra(suite, case, run_index, runtime, model, workspace, reason, duration_s, installed,
                          expected_chain=None, left_workspace=None, left_workspace_first=None):
    if suite == "outcome":
        # The outcome tier has no `common.eval_record.append_*` writer of its
        # own (its results.jsonl shape is `outcome.py`'s, not eval_record's)
        # -- build that shape directly and quarantine it next to the
        # outcome tier's own results dir, never the shared evals/results/.
        outcome_record = {
            "case": case, "arm": "plugin", "outcome": "INFRA", "pass": None,
            "criteria": [], "lane_fired": False,
            "total_cost_usd": None, "input_tokens": None, "output_tokens": None,
            "cache_read_tokens": None, "cache_creation_tokens": None,
            "num_turns": None, "duration_s": duration_s, "subagent_count": None,
            "denied_tool_calls": None, "denied_tools": [],
            "timestamp": common.utc_now_iso(),
            "runtime": runtime, "model": model, "workspace": str(workspace),
            "plugin_sha": common.eval_record.plugin_sha(),
            "harness_version": outcome.HARNESS_VERSION,
            "failed_criterion": f"INFRA: {reason}",
            "triage": "INFRA",
            "installed_plugin_path": installed["path"], "installed_plugin_sha": installed["sha"],
            "installed_plugin_dirty": installed["dirty"],
            "left_workspace": left_workspace, "left_workspace_first": left_workspace_first,
        }
        outcome._append_outcome_record(outcome_record, results_path=outcome_invalid_infra_path())
        return

    path = invalid_infra_path()
    common_kwargs = dict(
        failed_criterion=f"INFRA: {reason}", duration_s=duration_s, runtime=runtime,
        model=model, triage="INFRA", results_path=path,
        installed_plugin_path=installed["path"], installed_plugin_sha=installed["sha"],
        installed_plugin_dirty=installed["dirty"],
        left_workspace=left_workspace, left_workspace_first=left_workspace_first,
    )
    if suite == "contract":
        common.eval_record.append_runtime_contract_record(
            case=case, run_index=run_index, passed=None, outcome="INFRA",
            workspace=workspace, **common_kwargs)
    elif suite == "trigger":
        common.eval_record.append_runtime_trigger_record(
            case=case, run_index=run_index, outcome="INFRA", first_skill=None, skills_invoked=[],
            expected_chain=expected_chain or [], mentioned_only=False, workspace=workspace,
            **common_kwargs)
    else:
        common.eval_record.append_antigravity_record(
            case=case, run_index=run_index, passed=None, outcome="INFRA", **common_kwargs)


def _row(suite, case, run_index, runtime, outcome, passed, duration_s, failed_criterion, workspace):
    return {"suite": suite, "case": case, "run": run_index, "runtime": runtime,
            "outcome": outcome, "pass": passed, "duration_s": round(duration_s or 0.0, 2),
            "failed_criterion": failed_criterion, "workspace": str(workspace)}


def _update_marker_result(marker_path, outcome, passed, failed_criterion, left_workspace=None):
    rec = common.load_marker(marker_path)
    rec["graded_at"] = common.utc_now_iso()
    rec["last_result"] = {"outcome": outcome, "pass": passed, "failed_criterion": failed_criterion,
                          "left_workspace": left_workspace}
    common.save_marker(marker_path, rec)
    return rec


def _maybe_delete_workspace(workspace, outcome, passed, keep_workspaces):
    """Deletes on a PASS, keeps otherwise -- keyed off `passed` alone (`True`),
    not `outcome`: contract/antigravity's graded outcome is `"GRADED"`, but
    trigger's is one of `ROUTED_OK`/`ROUTED_WRONG`/`NO_ROUTE` -- `outcome ==
    "GRADED"` would (and, before this fix, did) never match a trigger PASS."""
    if keep_workspaces:
        print(f"    workspace kept: {workspace}")
        return
    if passed is True:
        import shutil
        shutil.rmtree(workspace, ignore_errors=True)
    else:
        print(f"    workspace kept ({outcome}, pass={passed}): {workspace}")


# --------------------------------------------------------------------------
# per-suite run implementations
# --------------------------------------------------------------------------

def _run_contract(runtime, case, run_index, root, ts, timeout_s, model, record, skip_permissions,
                   keep_workspaces, brain_root, installed):
    run_prefix = (runtime != "claude")
    start_info = contract.start_one(case, root, ts, run_prefix=run_prefix)
    workspace = start_info["workspace"]
    marker = start_info["marker"]
    handoff_to = start_info["handoff_to"]
    marker_rec = common.load_marker(marker)
    min_duration_s = marker_rec.get("min_duration_s")

    if runtime == "agy":
        scoped_prompt = apply_scope_preamble(start_info["prompt"], workspace)
        prompt_scoped, prompt_sent_sha256 = True, common.sha256_text(scoped_prompt)
        argv_builder = lambda: build_argv_agy(scoped_prompt, model=model, timeout_s=timeout_s,
                                               skip_permissions=skip_permissions)

        def _resolve_transcripts():
            window_end = common.compute_window_end(workspace, None)
            return resolve_agy_transcripts(workspace, marker_rec["started_at"], window_end,
                                            brain_root=brain_root or AGY_CLI_BRAIN_ROOT)
    else:
        # NOT scoped -- build_claude_contract_command_text runs the case's own
        # `## Command` block verbatim for parity with run-evals.ps1 (guard 1's
        # docstring explains why).
        command_text = build_claude_contract_command_text(start_info["command_text"], model=model)
        prompt_scoped, prompt_sent_sha256 = False, common.sha256_text(command_text)
        argv_builder = lambda: build_argv_powershell(command_text)
        _resolve_transcripts = None

    _record_prompt_scope(marker, prompt_scoped, prompt_sent_sha256)

    argv, proc, infra_reason, transcripts, escape_result = _execute_with_retry(
        argv_builder, workspace, timeout_s, runtime, "contract", handoff_to,
        min_duration_s=min_duration_s, transcripts_resolver=_resolve_transcripts,
        installed_plugin_path=installed["path"],
        brain_root=(brain_root or AGY_CLI_BRAIN_ROOT) if runtime == "agy" else None)
    archive_run("contract", case, ts, argv, proc)
    left_workspace = escape_result["escaped"] if escape_result is not None else None
    left_workspace_first = escape_result["first"] if escape_result else None

    if infra_reason:
        if record:
            _write_invalid_infra("contract", case, run_index, runtime, model or f"{runtime}-default",
                                  workspace, infra_reason, proc.duration_s, installed,
                                  left_workspace=left_workspace, left_workspace_first=left_workspace_first)
        row = _row("contract", case, run_index, runtime, "INFRA", None, proc.duration_s, f"INFRA: {infra_reason}", workspace)
        row.update(prompt_scoped=prompt_scoped, prompt_sent_sha256=prompt_sent_sha256,
                   left_workspace=left_workspace, left_workspace_first=left_workspace_first)
        _maybe_delete_workspace(workspace, "INFRA", None, keep_workspaces)
        return row, True

    write_handoff_if_needed(runtime, handoff_to, workspace, proc.stdout)

    grade_brain_root = (brain_root or AGY_CLI_BRAIN_ROOT) if runtime == "agy" else brain_root
    result_row = contract.grade_one(marker, model=model or f"{runtime}-default", brain_root=grade_brain_root,
                                     record=record, transcripts_override=transcripts)
    passed = result_row["pass"]
    outcome = result_row["outcome"]
    row = _row("contract", case, run_index, runtime, outcome, passed, proc.duration_s,
               result_row.get("failed_criterion"), workspace)
    row.update(prompt_scoped=prompt_scoped, prompt_sent_sha256=prompt_sent_sha256,
               left_workspace=left_workspace)
    _maybe_delete_workspace(workspace, outcome, passed, keep_workspaces)
    return row, (outcome == "INFRA")


def _run_trigger(runtime, case, run_index, root, ts, timeout_s, model, record, skip_permissions,
                  keep_workspaces, brain_root, installed):
    start_info = trigger.start_one(case, root, ts)
    workspace = start_info["workspace"]
    marker = start_info["marker"]
    marker_rec = common.load_marker(marker)
    prompt = start_info["prompt"]

    scoped_prompt = apply_scope_preamble(prompt, workspace)
    prompt_sent_sha256 = common.sha256_text(scoped_prompt)
    _record_prompt_scope(marker, True, prompt_sent_sha256)

    if runtime == "agy":
        # Guard 2: a trigger run only needs to observe which skill gets read,
        # never to let the model actually edit or run anything -- `--mode
        # plan`, parity with the claude trigger run's own `--permission-mode
        # plan` below.
        argv_builder = lambda: build_argv_agy(scoped_prompt, model=model, timeout_s=timeout_s,
                                               skip_permissions=skip_permissions, mode="plan")

        def _resolve_transcripts():
            window_end = common.compute_window_end(workspace, None)
            return resolve_agy_transcripts(workspace, marker_rec["started_at"], window_end,
                                            brain_root=brain_root or AGY_CLI_BRAIN_ROOT)
    else:
        argv_builder = lambda: build_argv_claude_trigger(scoped_prompt, model=model)
        _resolve_transcripts = None

    argv, proc, infra_reason, transcripts, escape_result = _execute_with_retry(
        argv_builder, workspace, timeout_s, runtime, "trigger", None,
        transcripts_resolver=_resolve_transcripts, installed_plugin_path=installed["path"],
        brain_root=(brain_root or AGY_CLI_BRAIN_ROOT) if runtime == "agy" else None)
    archive_run("trigger", case, ts, argv, proc,
                extra_files=({"stream.jsonl": proc.stdout} if runtime == "claude" else None))
    left_workspace = escape_result["escaped"] if escape_result is not None else None
    left_workspace_first = escape_result["first"] if escape_result else None

    if infra_reason:
        if record:
            _write_invalid_infra("trigger", case, run_index, runtime, model or f"{runtime}-default",
                                  workspace, infra_reason, proc.duration_s, installed,
                                  expected_chain=marker_rec.get("expected_chain"),
                                  left_workspace=left_workspace, left_workspace_first=left_workspace_first)
        row = _row("trigger", case, run_index, runtime, "INFRA", None, proc.duration_s, f"INFRA: {infra_reason}", workspace)
        row.update(prompt_scoped=True, prompt_sent_sha256=prompt_sent_sha256,
                   left_workspace=left_workspace, left_workspace_first=left_workspace_first)
        _maybe_delete_workspace(workspace, "INFRA", None, keep_workspaces)
        return row, True

    if runtime == "agy":
        result_row = trigger.grade_one(marker, model=model or "agy-default",
                                        brain_root=brain_root or AGY_CLI_BRAIN_ROOT,
                                        record=record, transcripts_override=transcripts)
        passed = result_row["pass"]
        outcome = result_row["outcome"]
        failed_criterion = result_row.get("failed_criterion")
    else:
        skills_invoked = claude_skill_invocations(proc.stdout)
        first_skill = skills_invoked[0] if skills_invoked else None
        expected_skill = marker_rec.get("expected_skill")
        acceptable_alternatives = marker_rec.get("acceptable_alternatives") or []
        expected_chain = marker_rec.get("expected_chain") or []
        outcome = trigger.judge_outcome(skills_invoked, expected_chain, expected_skill, acceptable_alternatives)
        mentioned_only = claude_mentioned_only(proc.stdout, expected_skill, acceptable_alternatives)
        passed = (outcome == "ROUTED_OK")
        failed_criterion = None if passed else f"{outcome}: first_skill={first_skill} skills_invoked={skills_invoked}"
        _update_marker_result(marker, outcome, passed, failed_criterion, left_workspace=left_workspace)
        if record:
            run_idx = common.infer_run_index("trigger", case, marker)
            common.eval_record.append_runtime_trigger_record(
                case=case, run_index=run_idx, outcome=outcome, first_skill=first_skill,
                skills_invoked=skills_invoked, expected_chain=expected_chain, mentioned_only=mentioned_only,
                failed_criterion=failed_criterion, duration_s=proc.duration_s, runtime="claude",
                model=model or "claude-default", workspace=workspace, raw_line=marker_rec.get("raw_line"),
                judge="tool_use", installed_plugin_path=installed["path"], installed_plugin_sha=installed["sha"],
                installed_plugin_dirty=installed["dirty"])

    row = _row("trigger", case, run_index, runtime, outcome, passed, proc.duration_s, failed_criterion, workspace)
    row.update(prompt_scoped=True, prompt_sent_sha256=prompt_sent_sha256, left_workspace=left_workspace)
    _maybe_delete_workspace(workspace, outcome, passed, keep_workspaces)
    return row, (outcome == "INFRA")


def _run_outcome(runtime, case, run_index, root, ts, timeout_s, model, record, skip_permissions,
                  keep_workspaces, brain_root, installed):
    """The plugin arm ONLY -- `outcome.start_one` always writes `arm:
    "plugin"` (see `RUN_SUITES`'s comment above for why there is no
    `--arm`/baseline here). Mirrors `_run_trigger`'s shape."""
    start_info = outcome.start_one(case, root, ts)
    workspace = start_info["workspace"]
    marker = start_info["marker"]
    marker_rec = common.load_marker(marker)
    prompt = start_info["prompt"]

    scoped_prompt = apply_scope_preamble(prompt, workspace)
    prompt_sent_sha256 = common.sha256_text(scoped_prompt)
    _record_prompt_scope(marker, True, prompt_sent_sha256)

    if runtime == "agy":
        argv_builder = lambda: build_argv_agy(scoped_prompt, model=model, timeout_s=timeout_s,
                                               skip_permissions=skip_permissions)

        def _resolve_transcripts():
            window_end = common.compute_window_end(workspace, None)
            return resolve_agy_transcripts(workspace, marker_rec["started_at"], window_end,
                                            brain_root=brain_root or AGY_CLI_BRAIN_ROOT)
    else:
        argv_builder = lambda: build_argv_claude_outcome(scoped_prompt, model=model)
        _resolve_transcripts = None

    argv, proc, infra_reason, transcripts, escape_result = _execute_with_retry(
        argv_builder, workspace, timeout_s, runtime, "outcome", None,
        transcripts_resolver=_resolve_transcripts, installed_plugin_path=installed["path"],
        brain_root=(brain_root or AGY_CLI_BRAIN_ROOT) if runtime == "agy" else None)
    archive_run("outcome", case, ts, argv, proc,
                extra_files=({"stream.jsonl": proc.stdout} if runtime == "claude" else None))
    left_workspace = escape_result["escaped"] if escape_result is not None else None
    left_workspace_first = escape_result["first"] if escape_result else None

    if infra_reason:
        if record:
            _write_invalid_infra("outcome", case, run_index, runtime, model or f"{runtime}-default",
                                  workspace, infra_reason, proc.duration_s, installed,
                                  left_workspace=left_workspace, left_workspace_first=left_workspace_first)
        row = _row("outcome", case, run_index, runtime, "INFRA", None, proc.duration_s, f"INFRA: {infra_reason}", workspace)
        row.update(prompt_scoped=True, prompt_sent_sha256=prompt_sent_sha256,
                   left_workspace=left_workspace, left_workspace_first=left_workspace_first)
        _maybe_delete_workspace(workspace, "INFRA", None, keep_workspaces)
        return row, True

    if runtime == "agy":
        grade_brain_root = brain_root or AGY_CLI_BRAIN_ROOT
    else:
        # claude produces a stream-json transcript, not an Antigravity
        # transcript.jsonl -- there is nothing for compute_no_unbacked_claim/
        # compute_lane_fired to read, so hand grade_one an explicitly empty
        # attribution rather than letting it fall back to a window/workspace
        # search that could never find anything real.
        transcripts = {"parent": None, "subagents": [], "all": []}
        grade_brain_root = brain_root

    result_row = outcome.grade_one(marker, model=model or f"{runtime}-default", brain_root=grade_brain_root,
                                    record=record, transcripts_override=transcripts, runtime=runtime,
                                    installed_plugin=installed)
    passed = result_row["pass"]
    outcome_result = result_row["outcome"]
    row = _row("outcome", case, run_index, runtime, outcome_result, passed, proc.duration_s,
               result_row.get("failed_criterion"), workspace)
    row.update(prompt_scoped=True, prompt_sent_sha256=prompt_sent_sha256, left_workspace=left_workspace)
    _maybe_delete_workspace(workspace, outcome_result, passed, keep_workspaces)
    return row, (outcome_result == "INFRA")


def _run_antigravity(runtime, case, run_index, root, ts, timeout_s, model, record, skip_permissions,
                      keep_workspaces, brain_root, installed):
    workspace = Path(root) / "eval-runs" / f"{case}-{ts}"
    marker = antigravity_run._start_one(case, workspace, ts=ts)
    marker_rec = common.load_marker(marker)
    prompt = (antigravity_run.CASES_DIR / case / "prompt.md").read_text(encoding="utf-8")

    scoped_prompt = apply_scope_preamble(prompt, workspace)
    prompt_sent_sha256 = common.sha256_text(scoped_prompt)
    _record_prompt_scope(marker, True, prompt_sent_sha256)

    if runtime == "agy":
        argv_builder = lambda: build_argv_agy(scoped_prompt, model=model, timeout_s=timeout_s,
                                               skip_permissions=skip_permissions)

        def _resolve_transcripts():
            window_end = antigravity_run._artifact_window_end(workspace) or common.utc_now_iso()
            return resolve_agy_transcripts(workspace, marker_rec["started_at"], window_end,
                                            brain_root=brain_root or AGY_CLI_BRAIN_ROOT)
    else:
        argv_builder = lambda: build_argv_claude_antigravity(scoped_prompt, model=model)
        _resolve_transcripts = None

    argv, proc, infra_reason, transcripts, escape_result = _execute_with_retry(
        argv_builder, workspace, timeout_s, runtime, "antigravity", None,
        transcripts_resolver=_resolve_transcripts, installed_plugin_path=installed["path"],
        brain_root=(brain_root or AGY_CLI_BRAIN_ROOT) if runtime == "agy" else None)
    archive_run("antigravity", case, ts, argv, proc)
    left_workspace = escape_result["escaped"] if escape_result is not None else None
    left_workspace_first = escape_result["first"] if escape_result else None

    if not infra_reason and runtime == "claude" and case in CLAUDE_ANTIGRAVITY_TRANSCRIPT_CASES:
        infra_reason = "no Antigravity transcript under runtime claude"

    if infra_reason:
        if record:
            _write_invalid_infra("antigravity", case, run_index, runtime, model or f"{runtime}-default",
                                  workspace, infra_reason, proc.duration_s, installed,
                                  left_workspace=left_workspace, left_workspace_first=left_workspace_first)
        row = _row("antigravity", case, run_index, runtime, "INFRA", None, proc.duration_s, f"INFRA: {infra_reason}", workspace)
        row.update(prompt_scoped=True, prompt_sent_sha256=prompt_sent_sha256,
                   left_workspace=left_workspace, left_workspace_first=left_workspace_first)
        _maybe_delete_workspace(workspace, "INFRA", None, keep_workspaces)
        return row, True

    if runtime != "agy":
        # run-log-discipline is artifact-only -- its grader ignores transcripts.
        transcripts = {"parent": None, "subagents": [], "all": []}

    grader = antigravity_run._load_grader(case)
    result = grader(workspace, transcripts)
    is_infra = bool(result.get("infra"))
    outcome = "INFRA" if is_infra else "GRADED"
    passed = None if is_infra else bool(result.get("pass"))
    failed_criterion = result.get("failed_criterion")

    _update_marker_result(marker, outcome, passed, failed_criterion, left_workspace=left_workspace)

    if is_infra:
        if record:
            _write_invalid_infra("antigravity", case, run_index, runtime, model or f"{runtime}-default",
                                  workspace, result.get("infra_reason") or "grader reported INFRA",
                                  proc.duration_s, installed,
                                  left_workspace=left_workspace, left_workspace_first=left_workspace_first)
    elif record:
        run_idx = antigravity_run._infer_run_index(case, marker)
        common.eval_record.append_antigravity_record(
            case=case, run_index=run_idx, passed=passed, outcome=outcome, failed_criterion=failed_criterion,
            metrics=result.get("metrics", {}), duration_s=proc.duration_s, runtime=runtime,
            model=model or f"{runtime}-default", installed_plugin_path=installed["path"],
            installed_plugin_sha=installed["sha"], installed_plugin_dirty=installed["dirty"])

    row = _row("antigravity", case, run_index, runtime, outcome, passed, proc.duration_s, failed_criterion, workspace)
    row.update(prompt_scoped=True, prompt_sent_sha256=prompt_sent_sha256, left_workspace=left_workspace)
    _maybe_delete_workspace(workspace, outcome, passed, keep_workspaces)
    return row, (outcome == "INFRA")


def discover_cases(suite):
    if suite == "contract":
        return contract.discover_cases()
    if suite == "trigger":
        return trigger.discover_cases()
    if suite == "outcome":
        return outcome.discover_cases()
    if suite == "antigravity":
        return antigravity_run._all_case_names()
    return []


def run_one(runtime, suite, case, run_index, root, timeout_s, model, record, skip_permissions,
            keep_workspaces, brain_root, installed):
    ts = common.utc_now().strftime("%Y%m%dT%H%M%SZ")
    fn = {"contract": _run_contract, "trigger": _run_trigger, "outcome": _run_outcome,
          "antigravity": _run_antigravity}[suite]
    return fn(runtime, case, run_index, root, ts, timeout_s, model, record, skip_permissions,
              keep_workspaces, brain_root, installed)


# --------------------------------------------------------------------------
# cmd_run
# --------------------------------------------------------------------------

def cmd_run(args):
    if args.runtime not in RUNTIMES:
        common.fail(f"unknown --runtime {args.runtime!r} (expected one of {RUNTIMES})")
    if args.suite not in RUN_SUITES:
        common.fail(f"unknown --suite {args.suite!r} for run (expected one of {RUN_SUITES})")
    if bool(args.case) == bool(args.all_cases):
        common.fail("--case or --all-cases is required (exactly one)")

    root = Path(args.root).resolve() if args.root else DEFAULT_RUN_ROOT
    runs = args.runs or 1
    timeout_s = args.timeout or DEFAULT_TIMEOUT_S
    skip_permissions = not args.no_skip_permissions

    if args.runtime == "agy":
        ok, reason = preflight_agy(probe=args.preflight_probe)
    else:
        ok, reason = preflight_claude(probe=args.preflight_probe)
    if not ok:
        print(f"error: preflight failed: {reason}", file=sys.stderr)
        return 2

    installed = installed_plugin_info(args.runtime, override_path=args.installed_plugin_path)
    print_installed_plugin_provenance(installed)

    cases = [args.case] if args.case else discover_cases(args.suite)
    if not cases:
        common.fail(f"no {args.suite} cases found")

    rows = []
    infra_count = 0
    for case in cases:
        for run_index in range(1, runs + 1):
            print(f"--- {args.suite}/{case} run {run_index}/{runs} ({args.runtime}) ---")
            row, was_infra = run_one(args.runtime, args.suite, case, run_index, root, timeout_s,
                                      args.model, args.record, skip_permissions, args.keep_workspaces,
                                      args.brain_root, installed)
            rows.append(row)
            if was_infra:
                infra_count += 1
            print(f"    -> outcome={row['outcome']} pass={row['pass']} duration_s={row['duration_s']}")

    print_summary(rows)
    print()
    print(f"INFRA: {infra_count} run(s) not counted toward any case's N "
          f"(quarantined in {invalid_infra_path().name}).")
    print("INFRA runs are not one of the N -- re-run the case to get a real data point.")

    any_fail = any(r["outcome"] == "GRADED" and r["pass"] is False for r in rows)
    return 1 if any_fail else 0


def print_summary(rows):
    print()
    print("SUMMARY:")
    print(f"{'suite':10} {'case':26} {'run':4} {'runtime':8} {'outcome':8} {'pass':7} "
          f"{'duration_s':11} failed_criterion")
    for r in rows:
        fc = (r.get("failed_criterion") or "")[:60]
        print(f"{r['suite']:10} {r['case']:26} {r['run']:<4} {r['runtime']:8} "
              f"{str(r['outcome']):8} {str(r['pass']):7} {str(r['duration_s']):11} {fc}")
