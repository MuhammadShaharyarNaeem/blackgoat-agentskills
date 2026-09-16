#!/usr/bin/env python3
"""Read-only tools for parsing Google Antigravity's on-disk conversation transcripts.

Antigravity keeps one directory per conversation under the "brain" root
(default `~/.gemini/antigravity/brain/<conversation-id>/`), each holding
`.system_generated/logs/transcript.jsonl` (and a `transcript_full.jsonl` that
adds `thinking` content the trimmed file omits). Every line is one JSON step
record:

    {"step_index": int, "source": str, "type": str, "status": str,
     "created_at": "<ISO-8601 UTC>", "content": str|None,
     "tool_calls": [{"name": str, "args": {...}}, ...]|None,
     "thinking": str|None}

`type` is one of PLANNER_RESPONSE, GENERIC, SYSTEM_MESSAGE, USER_INPUT,
ERROR_MESSAGE, CHECKPOINT. There is NO token-usage field anywhere in a
transcript -- duration and tool-call counts are the only cost proxies this
module can report.

A real quirk this module works around: every `tool_calls[].args` value is a
STRING that is itself JSON-quoted -- e.g. an `AbsolutePath` arg reads as the
Python string `"C:\\\\Users\\\\...\\\\mason.md"` (leading/trailing literal
`"` characters included), not the unwrapped path. `unwrap_arg` strips that.
Path separators are inconsistent across tool calls in the SAME transcript
(backslash in most, forward slash in at least one observed Quinn run) --
`normalize_path` accounts for both before any comparison.

Pure standard library.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_BRAIN_ROOT = Path.home() / ".gemini" / "antigravity" / "brain"

# A subagent's opening line, injected per the retired plugin AGENTS.md's
# recipe ("Take its full body verbatim ... as the subagent's
# system_prompt"), kept here because older transcripts follow it, and the
# briefing pattern observed in real transcripts:
# "You are <Name>, the <Role>.\nRead your persona at ..."). A human typing to
# Antigravity directly does not write in this shape, so it is the mechanical
# signal that a conversation's first turn is a briefing, not a person.
BRIEFING_RE = re.compile(r"You are \w[\w '-]*,\s*the\s+\S", re.I)
PERSONA_NAME_RE = re.compile(r"You are (\w+),", re.I)


# --------------------------------------------------------------------------
# Low-level helpers
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


# --------------------------------------------------------------------------
# Conversation discovery
# --------------------------------------------------------------------------

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
    the parent transcript (see the Part 1 write-up in README.md for the
    real-run evidence this rule was derived from). Each dict carries an added
    `"persona"` key (from `briefing_persona`) when it is a subagent.
    A conversation active in the window that is neither the parent nor a
    briefing is left out of both lists but still appears in `"all"`.
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

    Used by `evals/suites/headless.py` for the Antigravity CLI (`agy`), whose
    headless-run conversation is attributed deterministically via
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


# --------------------------------------------------------------------------
# Transcript parsing
# --------------------------------------------------------------------------

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


def extract_view_file_paths(tool_calls):
    """Deduped, unwrapped `AbsolutePath` values from every `view_file` call, in order."""
    seen = set()
    out = []
    for call in tool_calls:
        if call["name"] != "view_file":
            continue
        path = unwrap_arg(call["args"].get("AbsolutePath"))
        if not path:
            continue
        key = normalize_path(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def extract_run_command_strings(tool_calls):
    """Unwrapped `CommandLine` values from every `run_command` call, in order (not deduped)."""
    out = []
    for call in tool_calls:
        if call["name"] != "run_command":
            continue
        cmd = unwrap_arg(call["args"].get("CommandLine"))
        if cmd:
            out.append(cmd)
    return out


def extract_define_subagent_calls(tool_calls):
    """`{created_at, name, system_prompt_len}` per `define_subagent` call."""
    out = []
    for call in tool_calls:
        if call["name"] != "define_subagent":
            continue
        args = call["args"]
        sp = unwrap_arg(args.get("system_prompt")) or ""
        out.append({
            "created_at": call["created_at"],
            "name": unwrap_arg(args.get("name")),
            "system_prompt_len": len(sp),
        })
    return out


def extract_invoke_subagent_calls(tool_calls):
    """`{created_at, subagents_raw, subagents}` per `invoke_subagent` call.

    `Subagents` is (unlike every other observed arg) stored as a raw,
    un-wrapped JSON array string of `{Model, Prompt, ...}` objects -- no
    extra literal-quote layer, so `unwrap_arg` is not applied here. It is
    parsed with `strict=False` because real transcripts (observed
    2026-09-14) sometimes embed a literal control character straight from a
    persona file's newlines inside `Prompt`, which a strict parse rejects.
    Some real calls go further and embed an un-escaped literal `"` inside
    `Prompt` too, which breaks JSON structure entirely (not just strictness)
    -- `_recover_subagents_prompts` is the fallback for that case, so a
    caller that only needs which personas were briefed and what text
    followed still gets an answer instead of `None`.
    """
    out = []
    for call in tool_calls:
        if call["name"] != "invoke_subagent":
            continue
        raw = call["args"].get("Subagents")
        parsed = None
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw, strict=False)
            except json.JSONDecodeError:
                parsed = _recover_subagents_prompts(raw)
        out.append({
            "created_at": call["created_at"],
            "subagents_raw": raw,
            "subagents": parsed,
        })
    return out


def _recover_subagents_prompts(raw):
    """Best-effort persona/`Prompt`-text recovery when `Subagents` isn't valid JSON.

    Splits the raw text on each `"You are <Name>, the ..."` briefing opener
    found anywhere in it (`BRIEFING_RE`) and keeps everything up to the next
    opener (or the end) as that entry's `"Prompt"` -- a `{"Model": None,
    "Prompt": <text>}` dict per opener, shaped enough for
    `briefing_persona`/a unit-slug regex to read, even though it is not a
    faithful reconstruction of the original JSON. Returns `None` if the text
    contains no briefing opener at all (nothing to recover).
    """
    if not isinstance(raw, str):
        return None
    matches = list(BRIEFING_RE.finditer(raw))
    if not matches:
        return None
    out = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        out.append({"Model": None, "Prompt": raw[start:end]})
    return out


# --------------------------------------------------------------------------
# CLI (read-only inspection, used for Part 1 discovery and for spot checks)
# --------------------------------------------------------------------------

def _cmd_list(args):
    convs = list_conversations(args.brain_root)
    print(f"{len(convs)} conversations under {args.brain_root or DEFAULT_BRAIN_ROOT}")
    for c in convs[:args.limit]:
        print(f"  {c['conversation_id']}  {c['first_ts']} -> {c['last_ts']}  ({c['n_steps']} steps)")


def _cmd_window(args):
    result = find_run_transcripts(args.start, args.end, args.brain_root, workspace=args.workspace)
    parent = result["parent"]
    print("parent:", parent["conversation_id"] if parent else None)
    print(f"subagents ({len(result['subagents'])}):")
    for s in result["subagents"]:
        print(f"  {s['conversation_id']}  persona={s.get('persona')}  {s['first_ts']} -> {s['last_ts']}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brain-root", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list conversations, newest-first-ts window")
    p_list.add_argument("--limit", type=int, default=20)
    p_list.set_defaults(func=_cmd_list)

    p_window = sub.add_parser("window", help="find parent + subagent transcripts for a time window")
    p_window.add_argument("--start", required=True)
    p_window.add_argument("--end", required=True)
    p_window.add_argument("--workspace", default=None, help="attribute conversations to this workspace path only")
    p_window.set_defaults(func=_cmd_window)

    parsed = parser.parse_args(argv)
    parsed.func(parsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
