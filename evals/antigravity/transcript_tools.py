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

The conversation discovery and parsing readers (`unwrap_arg`,
`normalize_path`, `list_conversations`, `find_run_transcripts`,
`transcripts_for_conversation`, `parse_transcript`, `iter_tool_calls`, ...)
live in `skills/pipeline-tools/scripts/agy_runtime.py`, because the
/bgpdd-build-agy lane needs them and the installed plugin does not ship
evals/. They are re-exported here unchanged, so every grader's
`transcript_tools.<name>` keeps working. The extractors and the CLI below
are eval-only and stay here.

Pure standard library.
"""
import argparse
import json
import sys
from pathlib import Path

_PIPELINE_TOOLS_SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "pipeline-tools" / "scripts"
if str(_PIPELINE_TOOLS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_PIPELINE_TOOLS_SCRIPTS))
from agy_runtime import (  # noqa: E402,F401  (re-exported for the graders)
    BRIEFING_RE,
    DEFAULT_BRAIN_ROOT,
    PERSONA_NAME_RE,
    _in_window,
    _read_jsonl,
    _step_mentions_key,
    _transcript_path,
    briefing_persona,
    conversation_mentions_workspace,
    find_active_in_window,
    find_run_transcripts,
    first_user_input,
    is_briefing_input,
    iter_tool_calls,
    list_conversations,
    normalize_path,
    parse_transcript,
    text_mentions_workspace,
    transcripts_for_conversation,
    unwrap_arg,
    workspace_match_key,
)


# --------------------------------------------------------------------------
# Extractors (eval-only)
# --------------------------------------------------------------------------

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
