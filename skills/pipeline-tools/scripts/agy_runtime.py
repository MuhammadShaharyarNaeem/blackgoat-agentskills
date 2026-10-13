#!/usr/bin/env python3
"""Shared Antigravity CLI (`agy`) runtime: invocation, scope preamble,
transcript attribution and the workspace-escape tripwire.

A library module first. `evals/suites/headless.py` (the eval harness) and
`run_agy_builder.py` (the /bgpdd-build-agy lane) both import it; it lives
here, not under `evals/`, because the installed plugin does not ship
`evals/` and a lane script must still import it. The transcript readers
below moved here from `evals/antigravity/transcript_tools.py`, which now
re-exports them, so no logic is duplicated.

Antigravity keeps one directory per conversation under a "brain" root
(`~/.gemini/antigravity/brain/<id>/` for the IDE,
`~/.gemini/antigravity-cli/brain/<id>/` for the headless CLI), each holding
`.system_generated/logs/transcript.jsonl`. Every line is one JSON step:

    {"step_index": int, "source": str, "type": str, "status": str,
     "created_at": "<ISO-8601 UTC>", "content": str|None,
     "tool_calls": [{"name": str, "args": {...}}, ...]|None,
     "thinking": str|None}

Every `tool_calls[].args` value is a STRING that is itself JSON-quoted
(`unwrap_arg` strips that), and path separators vary within one transcript
(`normalize_path` accounts for both).

Pure standard library.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

DEFAULT_BRAIN_ROOT = Path.home() / ".gemini" / "antigravity" / "brain"
AGY_CLI_BRAIN_ROOT = Path.home() / ".gemini" / "antigravity-cli" / "brain"
AGY_LAST_CONVERSATIONS_PATH = Path.home() / ".gemini" / "antigravity-cli" / "cache" / "last_conversations.json"
AGY_INSTALLED_PLUGIN_PATH = Path.home() / ".gemini" / "config" / "plugins" / "blackgoat-agentskills"

DEFAULT_TIMEOUT_S = 2700  # 45 minutes
HARD_KILL_GRACE_S = 60

# A subagent's opening line ("You are <Name>, the <Role>.\nRead your persona
# at ..."). A human typing to Antigravity directly does not write in this
# shape, so it is the mechanical signal that a conversation's first turn is a
# briefing, not a person.
BRIEFING_RE = re.compile(r"You are \w[\w '-]*,\s*the\s+\S", re.I)
PERSONA_NAME_RE = re.compile(r"You are (\w+),", re.I)

# agy's own "a tool needed a permission headless mode cannot prompt for" text.
AGY_INFRA_RE = re.compile(r"(?i)^jetski:|no output produced|auto-denied|headless mode cannot prompt")


# --------------------------------------------------------------------------
# process invocation seam
# --------------------------------------------------------------------------

class ProcResult:
    """Uniform result of one CLI invocation -- what an invoke function returns."""

    def __init__(self, stdout="", stderr="", returncode=0, duration_s=0.0, timed_out=False):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.duration_s = duration_s
        self.timed_out = timed_out


# Module-level so a self-test can shrink either for a fast, deterministic
# heartbeat assertion without waiting on a real 30 s interval. A caller with
# its own seam (headless.py) passes its values in explicitly.
HEARTBEAT_INTERVAL_S = 30
POLL_INTERVAL_S = 0.25


def default_invoke(argv, cwd, timeout_s, heartbeat_interval_s=None, poll_interval_s=None):
    """Run `argv` with stdin closed (an empty file), capturing stdout/stderr.

    Popen + a poll loop, not one blocking `subprocess.run` call: a live
    agy/claude call prints nothing for however long the agent takes, which
    was mistaken for a hang and Ctrl+C'd mid-run on a perfectly healthy
    multi-minute call. This prints one heartbeat line to stderr every
    `heartbeat_interval_s` seconds instead (default `HEARTBEAT_INTERVAL_S`).

    The CLI's OWN timeout flag (`--print-timeout` for agy) should fire well
    before `timeout_s`; a Python-side hard kill fires `HARD_KILL_GRACE_S`
    seconds after it as a backstop for a CLI that ignores its own flag or
    hangs before it starts consuming its budget.
    """
    heartbeat_interval_s = HEARTBEAT_INTERVAL_S if heartbeat_interval_s is None else heartbeat_interval_s
    poll_interval_s = POLL_INTERVAL_S if poll_interval_s is None else poll_interval_s
    started = time.time()
    fd, empty_stdin_path = tempfile.mkstemp(prefix="bg-headless-stdin-")
    os.close(fd)
    runtime_name = argv[0] if argv else "?"
    hard_deadline = started + timeout_s + HARD_KILL_GRACE_S
    next_heartbeat = started + heartbeat_interval_s
    try:
        with open(empty_stdin_path, "rb") as stdin_fh:
            proc = subprocess.Popen(argv, cwd=str(cwd), stdin=stdin_fh,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            timed_out = False
            stdout = stderr = ""
            while True:
                try:
                    stdout, stderr = proc.communicate(timeout=poll_interval_s)
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
                        next_heartbeat = now + heartbeat_interval_s
            returncode = -1 if timed_out else proc.returncode
            return ProcResult(stdout or "", stderr or "", returncode,
                               time.time() - started, timed_out=timed_out)
    finally:
        try:
            Path(empty_stdin_path).unlink()
        except OSError:
            pass


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
# workspace-scope preamble (guard 1 -- the 2026-09-15 incident)
# --------------------------------------------------------------------------

def scope_preamble(workspace):
    """The EVAL harness's preamble: exact text prepended to every prompt
    `evals/suites/headless.py` composes for a headless CLI, naming
    `workspace` as the entire project and forbidding any excursion outside
    it. It names the plugin's evals/ directory because an eval worker must
    never read its own graders; a lane uses `lane_scope_preamble` instead.

    NEVER applied to headless.py's `build_claude_contract_command_text`
    output: that path runs a case's own `## Command` block verbatim, and
    that block IS the measurement."""
    return (f"Your working copy is {workspace}. Treat it as the entire project: every "
            "relative path resolves there. Do not read, search, or modify anything "
            "outside it; do not look for other repositories or projects on this "
            "machine; do not call external services, issue trackers, MCP tools, or "
            "the network. Never open the plugin evals/ directory or any earlier "
            "runs artifacts, results, or transcripts; they are not part of the project. If "
            "something the task needs is not inside the working "
            "copy, stop and say so. Repeat these restrictions, verbatim, at the top of every "
            "briefing you write for a delegated worker; they bind the workers exactly as they "
            "bind you. Delegation is blocking: invoke each worker synchronously, wait for "
            "its return before doing anything else, and never end your turn while a worker "
            "is outstanding; nobody is at the keyboard to resume you. Before you finish, "
            "stop every background process you started "
            "(servers, watchers); a process left running delays the run until its timeout.")


def lane_scope_preamble(workspace):
    """The LANE preamble: `scope_preamble`'s workspace boundary without the
    eval-grading sentence (a lane run has no graders to protect). Package
    managers and build tools a brief needs still run; web search/fetch tools
    and MCP tools do not -- `detect_workspace_escape` flags both."""
    return (f"Your working copy is {workspace}. Treat it as the entire project: every "
            "relative path resolves there. Do not read, search, or modify anything "
            "outside it; do not look for other repositories or projects on this "
            "machine; do not call external services, issue trackers, MCP tools, or "
            "web search or fetch tools. If something the task needs is not inside the "
            "working copy, stop and say so. Repeat these restrictions, verbatim, at the "
            "top of every briefing you write for a delegated worker; they bind the "
            "workers exactly as they bind you.")


def apply_scope_preamble(prompt, workspace, preamble=scope_preamble):
    """`preamble(workspace)` + two newlines + `prompt` verbatim."""
    return f"{preamble(workspace)}\n\n{prompt}"


# --------------------------------------------------------------------------
# argv builder
# --------------------------------------------------------------------------

def build_argv_agy(prompt, model=None, timeout_s=DEFAULT_TIMEOUT_S, skip_permissions=True,
                    mode="accept-edits", agent=None):
    """`agy -p "<prompt>" --mode <mode> --print-timeout <duration>
    [--dangerously-skip-permissions] [--model "<name>"] [--agent <name>]`
    (agy v1.1.3, probed 2026-09-15). `mode` defaults to `"accept-edits"`;
    the eval trigger suite passes `"plan"`. `agent` selects one of the
    installed plugin's personas (`agy agents` lists them)."""
    argv = ["agy", "-p", prompt, "--mode", mode,
            "--print-timeout", to_go_duration(timeout_s)]
    if skip_permissions:
        argv.append("--dangerously-skip-permissions")
    if model:
        argv += ["--model", model]
    if agent:
        argv += ["--agent", agent]
    return argv


# --------------------------------------------------------------------------
# transcript readers (moved from evals/antigravity/transcript_tools.py)
# --------------------------------------------------------------------------

def unwrap_arg(value):
    """Strip the one layer of literal-quote wrapping every tool arg carries.

    `tool_calls[].args["AbsolutePath"]` etc. are stored as the string
    `"C:\\\\...\\\\mason.md"` INCLUDING the leading/trailing `"` characters
    as real content -- not JSON escaping, the characters are actually in the
    Python string after `json.loads`. Booleans/numbers observed as args
    (`"IsDaemon": "false"`, `"WaitMsBeforeAsync": "10000"`) are left as
    strings; callers that need the typed value parse it themselves.
    """
    if not isinstance(value, str):
        return value
    s = value.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def normalize_path(path):
    """Lowercase, forward-slash form of a path string for comparison only.

    Never used to actually open a file -- only to compare two paths that may
    have come from tool calls using different separators (observed: one
    Quinn transcript used `/` throughout while every sibling transcript used
    `\\`).
    """
    if not path:
        return ""
    p = unwrap_arg(path).strip().strip('"').strip("'")
    p = p.replace("\\\\", "\\").replace("\\", "/")
    return p.lower()


def _read_jsonl(path):
    steps = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                steps.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return steps


def _transcript_path(conversation_dir, full=False):
    name = "transcript_full.jsonl" if full else "transcript.jsonl"
    return Path(conversation_dir) / ".system_generated" / "logs" / name


def list_conversations(brain_root=None):
    """List every conversation dir with its first/last step timestamp.

    Reads only the transcript's first and last non-blank line (not the whole
    file) so this stays cheap across the hundreds of conversation dirs a real
    Antigravity install accumulates. Returns a list of dicts:
    `{conversation_id, dir, first_ts, last_ts, n_steps}`, sorted by
    `first_ts` (conversations with an unreadable/missing transcript are
    skipped, not raised on).
    """
    root = Path(brain_root) if brain_root else DEFAULT_BRAIN_ROOT
    out = []
    if not root.is_dir():
        return out
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        tpath = _transcript_path(entry)
        if not tpath.is_file():
            continue
        first_ts = last_ts = None
        n_steps = 0
        try:
            with open(tpath, "r", encoding="utf-8", errors="replace") as fh:
                lines = [ln for ln in fh if ln.strip()]
            n_steps = len(lines)
            if lines:
                try:
                    first_ts = json.loads(lines[0]).get("created_at")
                except json.JSONDecodeError:
                    pass
                try:
                    last_ts = json.loads(lines[-1]).get("created_at")
                except json.JSONDecodeError:
                    pass
        except OSError:
            continue
        out.append({
            "conversation_id": entry.name,
            "dir": str(entry),
            "first_ts": first_ts,
            "last_ts": last_ts,
            "n_steps": n_steps,
        })
    out.sort(key=lambda c: c["first_ts"] or "")
    return out


def _in_window(ts, start, end):
    if not ts:
        return False
    return start <= ts <= end


def find_active_in_window(window_start, window_end, brain_root=None):
    """Conversations whose [first_ts, last_ts] overlaps [window_start, window_end].

    All three are ISO-8601 UTC strings ("...Z"); plain string comparison is
    valid because every timestamp in this corpus is zero-padded UTC.
    """
    active = []
    for conv in list_conversations(brain_root):
        first_ts, last_ts = conv["first_ts"], conv["last_ts"]
        if not first_ts or not last_ts:
            continue
        if last_ts < window_start or first_ts > window_end:
            continue
        active.append(conv)
    return active


def first_user_input(steps):
    """The first USER_INPUT step's content, or None."""
    for step in steps:
        if step.get("type") == "USER_INPUT":
            return step.get("content")
    return None


def is_briefing_input(text):
    """True if a USER_INPUT's content reads as a subagent briefing, not a person.

    Matches the observed real shape: "You are Quinn, the QA Tester.\\nRead
    your persona at ...". A human's own first message to Antigravity does not
    open this way.
    """
    if not text:
        return False
    return bool(BRIEFING_RE.search(text))


def briefing_persona(text):
    """The persona name out of a briefing's "You are <Name>, ..." opener, or None."""
    if not text:
        return None
    m = PERSONA_NAME_RE.search(text)
    return m.group(1) if m else None


def workspace_match_key(workspace):
    """Normalize `workspace` (any path-like value) to the substring used to
    match it against transcript text.

    Prefers the `eval-runs/<case>-<ts>` tail when present -- the piece that
    survives a machine-prefix difference between where `run.py` ran and
    where Antigravity recorded the path in a `view_file`/`run_command` arg or
    a briefing's `Prompt` text. Falls back to the full normalized path
    (`normalize_path`, so already lowercase/forward-slash) for a classic
    external `--workspace <dir>` that has no `eval-runs/` segment. Empty
    input yields `""`, which callers treat as "no filter".
    """
    if not workspace:
        return ""
    norm = normalize_path(str(workspace))
    parts = [p for p in norm.split("/") if p]
    for i, part in enumerate(parts):
        if part == "eval-runs":
            return "/".join(parts[i:])
    return norm


def text_mentions_workspace(text, workspace):
    """True if `text` (content, a tool-call arg, a raw `Subagents` JSON blob --
    anything stringy) contains `workspace`'s `workspace_match_key` once both
    sides are normalized (lowercase, forward-slash)."""
    key = workspace_match_key(workspace)
    if not key or not text:
        return False
    return key in normalize_path(text)


def _step_mentions_key(step, key):
    content = step.get("content")
    if isinstance(content, str) and key in normalize_path(content):
        return True
    for call in step.get("tool_calls") or []:
        for value in (call.get("args") or {}).values():
            if isinstance(value, str) and key in normalize_path(value):
                return True
    return False


def conversation_mentions_workspace(conversation_dir, workspace):
    """True if any step's USER_INPUT content, tool-call arg, or `content`
    field anywhere in the conversation at `conversation_dir` mentions
    `workspace` (see `workspace_match_key`). `workspace` falsy -> always
    False (an empty key matches nothing, deliberately -- callers that want
    "no filter" check `workspace` truthiness themselves)."""
    key = workspace_match_key(workspace)
    if not key:
        return False
    steps = parse_transcript(conversation_dir)
    return any(_step_mentions_key(s, key) for s in steps)


def find_run_transcripts(window_start, window_end, brain_root=None, workspace=None):
    """Locate the parent conversation and any subagent conversations for one run.

    A "run" is one invocation of a bgpdd-* lane, bounded by [window_start,
    window_end] (e.g. a workspace's run-log.jsonl or gates.jsonl first/last
    `ts`). Returns:

        {"parent": {...} | None, "subagents": [{...}, ...], "all": [{...}, ...]}

    When `workspace` is given, a conversation active in the window is kept
    only if it mentions that workspace (`conversation_mentions_workspace`)
    somewhere in a `USER_INPUT`, a `tool_calls` arg, or a `content` field --
    this is what lets several cases run from one Antigravity conversation (the
    eval orchestrator driving multiple parallel fixture copies) without one
    case's worker transcripts leaking into another's grading: the parent's
    `invoke_subagent`/`define_subagent` calls (or their briefing text) name
    the workspace a subagent was launched against, so the same parent
    conversation is kept -- and re-attributed -- for each case's own
    `workspace` filter in turn, while a worker whose OWN briefing names a
    different case's workspace is dropped. `workspace=None` (the default)
    keeps the old unfiltered behavior.

    `parent` is the conversation whose OWN span [first_ts, last_ts] contains
    the whole window (the human-driven conversation the Orchestrator ran in).
    `subagents` is every OTHER conversation active in the window whose first
    USER_INPUT is a briefing (`is_briefing_input`) -- this is what
    `define_subagent`/`invoke_subagent` produce under Antigravity: a fresh,
    separate conversation dir per subagent invocation, not inline turns in
    the parent transcript (see the Part 1 write-up in evals/antigravity/
    README.md for the real-run evidence this rule was derived from). Each
    dict carries an added `"persona"` key (from `briefing_persona`) when it
    is a subagent. A conversation active in the window that is neither the
    parent nor a briefing is left out of both lists but still appears in
    `"all"`.
    """
    candidates = find_active_in_window(window_start, window_end, brain_root)
    parent = None
    subagents = []
    all_active = []
    for conv in candidates:
        if workspace and not conversation_mentions_workspace(conv["dir"], workspace):
            continue
        tpath = _transcript_path(conv["dir"])
        steps = _read_jsonl(tpath) if tpath.is_file() else []
        fu = first_user_input(steps)
        record = dict(conv)
        record["first_user_input"] = fu
        all_active.append(record)
        if is_briefing_input(fu):
            record["persona"] = briefing_persona(fu)
            subagents.append(record)
        elif (conv["first_ts"] or "") <= window_start and (conv["last_ts"] or "") >= window_start:
            # Overlaps the window's START and isn't itself a briefing -> the
            # human-driven parent. Deliberately NOT "spans the whole window"
            # (first_ts <= window_start AND last_ts >= window_end): grade's
            # window_end is "last artifact write + 2 min", so a conversation
            # that ended within that buffer of its own last gate write would
            # otherwise lose its parent to a false INFRA. If several qualify,
            # keep the tightest (latest first_ts) as parent and leave the
            # rest in "all" only.
            if parent is None or conv["first_ts"] > parent["first_ts"]:
                parent = record
    return {"parent": parent, "subagents": subagents, "all": all_active}


def transcripts_for_conversation(conversation_id, window_start, window_end, brain_root=None):
    """Like `find_run_transcripts`, but the PARENT conversation is pinned to
    `conversation_id` instead of inferred from which conversation's own span
    overlaps `window_start`.

    Used for the Antigravity CLI (`agy`), whose headless-run conversation is
    attributed deterministically via
    `~/.gemini/antigravity-cli/cache/last_conversations.json` (cwd -> conversation
    id) rather than by which conversation happens to overlap the window's start --
    a fresh headless run's OWN conversation may start well after `window_start`
    (workspace setup, preflight, etc. all happen before the CLI is even invoked).

    Subagents are every OTHER conversation active in the window whose first
    USER_INPUT is a briefing (`is_briefing_input`) -- the same rule
    `find_run_transcripts` uses. Returns the same `{"parent", "subagents",
    "all"}` shape, where "all" is exactly the parent plus those subagents --
    a non-briefing neighbour conversation in the window is NOT included
    (it is another run's parent). `parent` is `None` if `conversation_id`'s transcript is
    missing or empty (the caller should fall back to `find_run_transcripts`
    in that case).
    """
    root = Path(brain_root) if brain_root else DEFAULT_BRAIN_ROOT
    conv_dir = root / conversation_id
    tpath = _transcript_path(conv_dir)
    parent = None
    all_active = []
    if tpath.is_file():
        steps = _read_jsonl(tpath)
        if steps:
            fu = first_user_input(steps)
            parent = {
                "conversation_id": conversation_id,
                "dir": str(conv_dir),
                "first_ts": steps[0].get("created_at"),
                "last_ts": steps[-1].get("created_at"),
                "n_steps": len(steps),
                "first_user_input": fu,
            }
            all_active.append(parent)

    subagents = []
    for conv in find_active_in_window(window_start, window_end, root):
        if conv["conversation_id"] == conversation_id:
            continue
        tpath2 = _transcript_path(conv["dir"])
        steps2 = _read_jsonl(tpath2) if tpath2.is_file() else []
        fu2 = first_user_input(steps2)
        record = dict(conv)
        record["first_user_input"] = fu2
        # Only briefing conversations (this run's own subagents) join the
        # set. A non-briefing neighbour active in the same window is another
        # headless run's parent, and letting it into "all" would leak its
        # tool calls into this run's trigger judge and escape tripwire.
        if is_briefing_input(fu2):
            record["persona"] = briefing_persona(fu2)
            subagents.append(record)
            all_active.append(record)

    return {"parent": parent, "subagents": subagents, "all": all_active}


def parse_transcript(conversation_dir, full=False):
    """Return the flat list of raw step dicts for one conversation."""
    tpath = _transcript_path(conversation_dir, full=full)
    if not tpath.is_file():
        return []
    return _read_jsonl(tpath)


def iter_tool_calls(steps):
    """Flatten every step's `tool_calls` into `{step_index, created_at, name, args}`."""
    out = []
    for step in steps:
        calls = step.get("tool_calls") or []
        for call in calls:
            out.append({
                "step_index": step.get("step_index"),
                "created_at": step.get("created_at"),
                "name": call.get("name"),
                "args": call.get("args") or {},
            })
    return out


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
    target = normalize_path(str(workspace))
    for cwd_key, conversation_id in (mapping or {}).items():
        if normalize_path(cwd_key) == target:
            return conversation_id
    return None


def resolve_agy_transcripts(workspace, window_start, window_end, brain_root=None, cache_path=None):
    """Attribute a headless `agy` run's conversation deterministically via
    `last_conversations.json`; fall back to the window/workspace-mention
    heuristic (`find_run_transcripts`) when the mapping has no entry."""
    brain_root = brain_root or AGY_CLI_BRAIN_ROOT
    conversation_id = resolve_agy_conversation_id(workspace, cache_path=cache_path)
    if conversation_id:
        transcripts = transcripts_for_conversation(
            conversation_id, window_start, window_end, brain_root)
        if transcripts.get("parent"):
            return transcripts
    return find_run_transcripts(
        window_start, window_end, brain_root, workspace=str(workspace))


# --------------------------------------------------------------------------
# workspace-scope tripwire (guard 3 -- the 2026-09-15 incident)
# --------------------------------------------------------------------------

# Antigravity/agy tool names whose path-like argument must resolve inside an
# allowed root. Checked in this order against each call's own `args` dict --
# whichever key is present wins (a call carries exactly one of these).
_SCOPE_GUARD_PATH_TOOLS = ("view_file", "list_dir", "find_by_name", "grep_search",
                           "write_to_file", "replace_file_content", "multi_replace_file_content")
_SCOPE_GUARD_PATH_ARG_KEYS = ("AbsolutePath", "DirectoryPath", "SearchDirectory", "SearchPath", "TargetFile", "Path")

# Any call to one of these is a flag regardless of its arguments -- the
# incident's four `call_mcp_tool` calls to `linear` had no in-workspace
# reading at all; the point is that a headless run must never reach an
# external service, full stop.
_SCOPE_GUARD_NETWORK_TOOLS = ("read_url_content", "search_web", "call_mcp_tool")

_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
# A drive-letter token must not be preceded by a letter or digit: `http://` ends in
# `p:/` and matched the unanchored form, flagging every `curl http://localhost:...`
# reproduction command as an escape (bgpdd-bugfix-lane run 1, 2026-09-14 22:56Z).
_ESCAPE_SEQ_RE = re.compile(r"\\[ntr]")  # a literal backslash-n/-t/-r left by double-encoded args
_WINDOWS_ABS_PATH_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']*")


def _is_absolute_windows_path(path):
    if not path:
        return False
    return bool(_WINDOWS_ABS_PATH_RE.match(path.strip().strip('"').strip("'")))


def _is_evals_self_inspection(path, workspace):
    """True when `path` points anywhere under an `evals/` directory that is
    not the run's own workspace -- the harness's cases, graders, results and
    archived transcripts, wherever they live (the checkout, the installed
    plugin clone). Reading them is self-inspection, so it is an escape even
    inside an otherwise allowed root: on 2026-09-15 00:03Z a Quinn worker
    grep-searched the installed clone for its bug slug, found a committed
    outcome-run transcript of the same case under
    `evals/outcome/results/artifacts/`, and read it.

    Kept here, not in the eval harness, because a lane run shares the
    hazard: the installed plugin path is an allowed root, and that clone
    carries evals/ with archived transcripts of the same personas' work."""
    norm = normalize_path(path)
    ws = normalize_path(str(workspace)).rstrip("/") + "/"
    return "/evals/" in norm and not norm.startswith(ws)


def _path_within_roots(path, normalized_roots):
    """True if `path`'s normalized segments start with one allowed root's
    segments -- a prefix match on path SEGMENTS (`C:/Gorelo` must not match
    an allowed root `C:/Go`), never a bare string prefix."""
    norm = normalize_path(path)
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
    return [normalize_path(r) for r in roots if r]


def _scope_guard_path_arg(call):
    args = call.get("args") or {}
    for key in _SCOPE_GUARD_PATH_ARG_KEYS:
        if key in args:
            return unwrap_arg(args.get(key))
    return None


def _scope_guard_mcp_argument(call):
    """Best-effort human-readable label for a `call_mcp_tool` call -- the
    exact arg-key names an installed MCP client uses aren't part of this
    repo's documented transcript shape, so this reads whichever of the
    plausible keys is present rather than assuming one."""
    args = call.get("args") or {}
    server = unwrap_arg(
        args.get("ServerName") or args.get("Server") or args.get("server"))
    tool = unwrap_arg(
        args.get("ToolName") or args.get("Tool") or args.get("tool"))
    if server or tool:
        return " ".join(p for p in (server, tool) if p)
    return "call_mcp_tool"


def detect_workspace_escape(transcripts, workspace, installed_plugin_path, brain_root=None):
    """Post-run tripwire for the 2026-09-15 incident: a headless run that
    wanders outside its workspace while permissions are skipped -- searching
    the machine for a "real" repository, grepping another project, calling
    an issue tracker over MCP. Meaningful only for `agy`'s own
    Antigravity-shaped transcripts (`view_file`/`run_command`/`call_mcp_tool`
    are agy's tool vocabulary, not `claude`'s).

    Walks every attributed conversation (`transcripts["all"]`, chronological
    by `first_ts`), and within each, its steps/tool calls in file order.
    Flags:

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
        steps = parse_transcript(conv["dir"])
        for call in iter_tool_calls(steps):
            name = call.get("name")
            argument = None
            if name in _SCOPE_GUARD_PATH_TOOLS:
                path = _scope_guard_path_arg(call)
                if path and _is_absolute_windows_path(path) and (
                        _is_evals_self_inspection(path, workspace) or not _path_within_roots(path, roots)):
                    argument = path
            elif name == "run_command":
                args = call.get("args") or {}
                cwd = unwrap_arg(args.get("Cwd"))
                cmdline = unwrap_arg(args.get("CommandLine")) or ""
                if cwd and _is_absolute_windows_path(cwd) and (
                        _is_evals_self_inspection(cwd, workspace) or not _path_within_roots(cwd, roots)):
                    argument = cmdline or cwd
                else:
                    # Transcript CommandLine values keep JSON escapes as two-char
                    # sequences, so a multi-line python -c reads 'as f:' + backslash-n
                    # as drive f: (nova-ui-contract, 2026-09-15 04:30Z, a false
                    # left_workspace). Blank those escapes before scanning.
                    for token in _WINDOWS_ABS_PATH_TOKEN_RE.findall(_ESCAPE_SEQ_RE.sub(" ", cmdline)):
                        if _is_evals_self_inspection(token, workspace) or not _path_within_roots(token, roots):
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


# --------------------------------------------------------------------------
# preflight
# --------------------------------------------------------------------------

def preflight_agy(probe=False, invoker=None, required_agents=("luna", "mason"), run=None,
                  exact=False):
    """`(ok, reason)`: `agy agents` runs and lists every `required_agents`
    name; with `probe`, one tiny `agy -p` call must reply READY. `invoker`
    (default `default_invoke`) and `run` (default `subprocess.run`) are the
    seams a self-test replaces so no real `agy` is ever started.

    `exact=True` (the lane) matches whole stripped lines -- `agy agents`
    prints one bare name per line -- so "maximus" never satisfies "max".
    The default substring test is the eval harness's original behaviour,
    kept unchanged."""
    invoker = invoker or default_invoke
    run = run or subprocess.run
    try:
        proc = run(["agy", "agents"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not run `agy agents`: {exc}"
    out = proc.stdout or ""
    if exact:
        listed_names = {line.strip() for line in out.splitlines()}
        missing = [name for name in required_agents if name not in listed_names]
    else:
        missing = [name for name in required_agents if name not in out]
    if proc.returncode != 0 or missing:
        names = list(required_agents)
        listed = ("both " + " and ".join(names)) if len(names) == 2 else " and ".join(names)
        return False, (f"`agy agents` did not list {listed} -- is the plugin loaded "
                        f"from {AGY_INSTALLED_PLUGIN_PATH}?")
    if probe:
        result = invoker(["agy", "-p", "reply with the word READY", "--print-timeout", "2m"],
                         Path.cwd(), 120)
        if "READY" not in (result.stdout or ""):
            return False, "agy preflight probe did not reply READY"
    return True, None


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

class PurposeFirstParser(argparse.ArgumentParser):
    """`--help` whose FIRST line is the one-line purpose, then usage/args/epilog.

    argparse prints usage before the description; the registry's
    `description` must equal help line 1 verbatim, so the description is
    lifted out and re-emitted ahead of the standard body.
    """

    def format_help(self):
        purpose = (self.description or "").strip()
        saved, self.description = self.description, None
        try:
            body = super().format_help()
        finally:
            self.description = saved
        return purpose + "\n\n" + body if purpose else body


PURPOSE = ("Library shared by the eval harness and run_agy_builder.py: agy invocation, scope "
           "preambles, transcript attribution and the workspace-escape tripwire.")

EPILOG = """\
Reads:
  Nothing from the command line. Imported, it reads agy's own files:
  ~/.gemini/antigravity-cli/cache/last_conversations.json (cwd -> id) and
  <brain root>/<id>/.system_generated/logs/transcript.jsonl.

Public names:
  ProcResult, default_invoke, to_go_duration, scope_preamble (eval),
  lane_scope_preamble (lane), apply_scope_preamble, build_argv_agy,
  resolve_agy_conversation_id, resolve_agy_transcripts,
  scope_guard_allowed_roots, detect_workspace_escape, preflight_agy, the
  transcript readers (unwrap_arg, normalize_path, parse_transcript,
  iter_tool_calls, find_run_transcripts, transcripts_for_conversation),
  AGY_CLI_BRAIN_ROOT, AGY_INSTALLED_PLUGIN_PATH, AGY_INFRA_RE.

Exit codes:
  0  --help, or a passing --self-test
  1  a failing --self-test
  2  usage error (no flag given)

Self-test:
  python agy_runtime.py --self-test   (15 cases; never starts agy)
"""


def _write_transcript(brain, conv_id, steps):
    d = Path(brain) / conv_id / ".system_generated" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "transcript.jsonl", "w", encoding="utf-8") as fh:
        for i, step in enumerate(steps):
            rec = {"step_index": i, "created_at": step.get("created_at", "2026-10-12T10:00:0%dZ" % i)}
            rec.update(step)
            fh.write(json.dumps(rec) + "\n")


def _q(value):
    return json.dumps(value)


def run_self_test():

    class AgyRuntimeTests(unittest.TestCase):
        def setUp(self):
            self.tmp = Path(tempfile.mkdtemp(prefix="agy_runtime_selftest_"))
            self.brain = self.tmp / "brain"
            self.ws = "C:/work/proj"

        def tearDown(self):
            shutil.rmtree(self.tmp, ignore_errors=True)

        def _tr(self, calls):
            _write_transcript(self.brain, "c1", [
                {"type": "USER_INPUT", "content": "go"},
                {"type": "PLANNER_RESPONSE", "tool_calls": calls}])
            return {"all": [{"conversation_id": "c1", "dir": str(self.brain / "c1"), "first_ts": "a"}]}

        def test_go_duration(self):
            self.assertEqual([to_go_duration(s) for s in (2700, 90, 45, 3661, 0)],
                             ["45m", "1m30s", "45s", "1h1m1s", "0s"])

        def test_argv_with_agent(self):
            argv = build_argv_agy("p", model="m", timeout_s=90, agent="mason")
            self.assertEqual(argv, ["agy", "-p", "p", "--mode", "accept-edits", "--print-timeout", "1m30s",
                                    "--dangerously-skip-permissions", "--model", "m", "--agent", "mason"])

        def test_argv_without_agent_unchanged(self):
            self.assertNotIn("--agent", build_argv_agy("p"))

        def test_lane_preamble_has_no_eval_text(self):
            text = lane_scope_preamble(self.ws)
            self.assertIn(self.ws, text)
            self.assertNotIn("evals/", text)
            self.assertIn("evals/", scope_preamble(self.ws))

        def test_apply_preamble_choice(self):
            self.assertTrue(apply_scope_preamble("X", self.ws, preamble=lane_scope_preamble)
                            .startswith(lane_scope_preamble(self.ws) + "\n\n"))
            self.assertTrue(apply_scope_preamble("X", self.ws).endswith("\n\nX"))

        def test_escape_external_view_file(self):
            r = detect_workspace_escape(self._tr([{"name": "view_file", "args": {
                "AbsolutePath": _q("C:\\Gorelo\\x.cs")}}]), self.ws, None, None)
            self.assertTrue(r["escaped"])
            self.assertEqual(r["first"]["tool"], "view_file")

        def test_escape_mcp(self):
            r = detect_workspace_escape(self._tr([{"name": "call_mcp_tool", "args": {
                "ServerName": _q("linear")}}]), self.ws, None, None)
            self.assertTrue(r["escaped"])

        def test_in_workspace_not_flagged(self):
            r = detect_workspace_escape(self._tr([
                {"name": "view_file", "args": {"AbsolutePath": _q("c:\\work\\PROJ\\src\\a.cs")}},
                {"name": "run_command", "args": {"CommandLine": _q("curl http://localhost:5000/x"),
                                                  "Cwd": _q("C:/work/proj")}}]), self.ws, None, None)
            self.assertFalse(r["escaped"], r)

        def test_installed_plugin_root_allowed_but_evals_flagged(self):
            inst = "C:/plug/bg"
            ok = detect_workspace_escape(self._tr([{"name": "view_file", "args": {
                "AbsolutePath": _q(inst + "/skills/x/SKILL.md")}}]), self.ws, inst, None)
            self.assertFalse(ok["escaped"])
            bad = detect_workspace_escape(self._tr([{"name": "view_file", "args": {
                "AbsolutePath": _q(inst + "/evals/outcome/results/t.jsonl")}}]), self.ws, inst, None)
            self.assertTrue(bad["escaped"])

        def test_segment_prefix_not_string_prefix(self):
            self.assertFalse(_path_within_roots("C:/Gorelo/x", [normalize_path("C:/Go")]))
            self.assertTrue(_path_within_roots("C:/Go/x", [normalize_path("C:/Go")]))

        def test_resolve_prefers_mapping(self):
            _write_transcript(self.brain, "conv-9", [{"type": "USER_INPUT", "content": "hi",
                                                      "created_at": "2026-10-12T10:00:05Z"}])
            cache = self.tmp / "last.json"
            cache.write_text(json.dumps({"C:\\Work\\Proj": "conv-9"}), encoding="utf-8")
            tr = resolve_agy_transcripts(self.ws, "2026-10-12T10:00:00Z", "2026-10-12T11:00:00Z",
                                         brain_root=self.brain, cache_path=cache)
            self.assertEqual(tr["parent"]["conversation_id"], "conv-9")

        def test_resolve_no_mapping_falls_back(self):
            tr = resolve_agy_transcripts(self.ws, "2026-10-12T10:00:00Z", "2026-10-12T11:00:00Z",
                                         brain_root=self.brain, cache_path=self.tmp / "missing.json")
            self.assertEqual(tr, {"parent": None, "subagents": [], "all": []})

        def test_preflight_uses_injected_run(self):
            class P:
                returncode, stdout = 0, "luna\nmason\nnova\n"
            ok, why = preflight_agy(run=lambda *a, **k: P())
            self.assertTrue(ok, why)
            ok, why = preflight_agy(run=lambda *a, **k: P(), required_agents=("max",))
            self.assertFalse(ok)
            self.assertIn("did not list max", why)

        def test_preflight_exact_line_match(self):
            class P:
                returncode, stdout = 0, "  alex\nmaximus\nmason \n"
            ok, _ = preflight_agy(run=lambda *a, **k: P(), required_agents=("max",), exact=True)
            self.assertFalse(ok)
            ok, why = preflight_agy(run=lambda *a, **k: P(), required_agents=("mason",), exact=True)
            self.assertTrue(ok, why)
            ok, _ = preflight_agy(run=lambda *a, **k: P(), required_agents=("max",))
            self.assertTrue(ok)  # default substring test: the eval path, unchanged

        def test_preflight_missing_binary(self):
            def boom(*a, **k):
                raise OSError("not found")
            ok, why = preflight_agy(run=boom)
            self.assertFalse(ok)
            self.assertIn("could not run", why)

    suite = unittest.TestLoader().loadTestsFromTestCase(AgyRuntimeTests)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=1).run(suite)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    print(f"SELF-TEST: {total - failed}/{total} passed. {'OK' if failed == 0 else 'FAIL'}")
    return 0 if failed == 0 else 1


def main(argv=None):
    parser = PurposeFirstParser(
        prog="agy_runtime.py",
        description=PURPOSE,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--self-test", action="store_true",
                        help="run the offline self-test (no agy process is started)")
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_test()
    parser.print_usage(sys.stderr)
    print("agy_runtime.py: error: nothing to do; it is a library (use --help or --self-test)",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
