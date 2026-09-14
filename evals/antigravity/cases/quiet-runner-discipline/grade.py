#!/usr/bin/env python3
"""Grader for the `quiet-runner-discipline` antigravity case. Transcript-based:
every `run_command` across the parent AND every subagent transcript whose
leading tokens are a build/test runner must contain `run_quiet.py`. See
case.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import case_common  # noqa: E402
import transcript_tools  # noqa: E402


def grade(workspace, transcripts):
    all_convs = (transcripts or {}).get("all") or []
    if workspace:
        # Defense in depth, same rationale as skill-load-discipline: a
        # transcript belongs to this case only if it mentions this case's
        # workspace (`run.py` already scopes `transcripts` this way via
        # `find_run_transcripts(..., workspace=...)`).
        all_convs = [c for c in all_convs
                     if transcript_tools.conversation_mentions_workspace(c["dir"], workspace)]
    if not all_convs:
        return {"infra": True, "infra_reason": "no transcripts found in the run window",
                "pass": None, "metrics": {}, "failed_criterion": None}

    parent = (transcripts or {}).get("parent")
    parent_id = parent["conversation_id"] if parent else None

    raw = []
    wrapped = []
    for conv in all_convs:
        is_parent = parent_id is not None and conv["conversation_id"] == parent_id
        steps = transcript_tools.parse_transcript(conv["dir"])
        tool_calls = transcript_tools.iter_tool_calls(steps)
        for call in tool_calls:
            if call["name"] != "run_command":
                continue
            cmd = transcript_tools.unwrap_arg(call["args"].get("CommandLine"))
            if not cmd:
                continue
            if is_parent and workspace:
                # The parent conversation can drive several cases at once,
                # so a single conversation-level attribution isn't enough --
                # only count a PARENT command whose own Cwd or command text
                # names this case's workspace. A subagent conversation
                # needs no such per-call check: attribution already scoped
                # `all_convs` to conversations dedicated to this case.
                cwd = transcript_tools.unwrap_arg(call["args"].get("Cwd")) or ""
                if not (transcript_tools.text_mentions_workspace(cwd, workspace)
                        or transcript_tools.text_mentions_workspace(cmd, workspace)):
                    continue
            entry = {"conversation_id": conv["conversation_id"], "command": cmd}
            if case_common.matches_any_runner(cmd):
                # Leading tokens ARE the runner -- raw unless `run_quiet.py`
                # appears somewhere in the same string too.
                if case_common.is_raw_runner_invocation(cmd):
                    raw.append(entry)
                else:
                    wrapped.append(entry)
                continue
            # Leading tokens are NOT the runner (e.g. `python ...
            # run_quiet.py --capture ... -- dotnet test ...`) -- the
            # sanctioned wrapped form. Recognized separately so `wrapped` is
            # a real count instead of always 0.
            inner = case_common.command_after_run_quiet(cmd)
            if inner and case_common.matches_any_runner(inner):
                wrapped.append(entry)

    passed = len(raw) == 0
    failed_criterion = None if passed else f"{len(raw)} raw runner invocation(s) with no run_quiet.py"

    return {
        "infra": False,
        "pass": passed,
        "failed_criterion": failed_criterion,
        "metrics": {"raw": raw, "wrapped_count": len(wrapped), "raw_count": len(raw)},
    }


if __name__ == "__main__":
    import json
    ws = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    start, end = sys.argv[2], sys.argv[3]
    result = transcript_tools.find_run_transcripts(start, end)
    print(json.dumps(grade(ws, result), indent=2, default=str))
