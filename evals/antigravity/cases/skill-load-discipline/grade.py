#!/usr/bin/env python3
"""Grader for the `skill-load-discipline` antigravity case. Transcript-based:
for each subagent transcript, the set of `skills/*/SKILL.md` paths (plus
`base-persona.md`) read via `view_file`, compared against the persona's
`## Methodology Dependencies` table (Always rows + stack-triggered rows
`detect_stack.py` reports for the workspace). See case.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import case_common  # noqa: E402
import transcript_tools  # noqa: E402

OVER_READ_LIMIT = 1


def grade(workspace, transcripts):
    subagents = (transcripts or {}).get("subagents") or []
    if workspace:
        # Defense in depth: a worker transcript belongs to the case whose
        # workspace its briefing names. `run.py` already scopes `transcripts`
        # to this workspace via `find_run_transcripts(..., workspace=...)`,
        # but re-check here too so a caller that hands this grader an
        # unfiltered `transcripts` dict (e.g. a different case's siblings
        # from one shared parent conversation) can't leak a sibling case's
        # worker into this case's over-read count.
        subagents = [c for c in subagents
                     if transcript_tools.conversation_mentions_workspace(c["dir"], workspace)]
    if not subagents:
        return {"infra": True, "infra_reason": "no subagent transcripts found in the run window",
                "pass": None, "metrics": {}, "failed_criterion": None}

    per_persona = {}
    any_over_limit = []

    for conv in subagents:
        persona = conv.get("persona") or "unknown"
        steps = transcript_tools.parse_transcript(conv["dir"])
        tool_calls = transcript_tools.iter_tool_calls(steps)
        read_paths_raw = transcript_tools.extract_view_file_paths(tool_calls)
        reads = set()
        for p in read_paths_raw:
            suffix = case_common.normalize_path_suffix(p)
            if case_common.is_skill_read(suffix):
                reads.add(suffix)

        expected, always = case_common.expected_skill_reads(persona, workspace)
        over_reads = reads - expected
        misses = always - reads

        key = f"{persona}:{conv['conversation_id']}"
        per_persona[key] = {
            "persona": persona,
            "conversation_id": conv["conversation_id"],
            "reads": sorted(reads),
            "expected": sorted(expected),
            "over_reads": sorted(over_reads),
            "misses": sorted(misses),
        }
        if len(over_reads) > OVER_READ_LIMIT:
            any_over_limit.append(key)

    passed = not any_over_limit
    failed_criterion = None
    if any_over_limit:
        failed_criterion = f"over-reads > {OVER_READ_LIMIT} for: {', '.join(any_over_limit)}"

    return {
        "infra": False,
        "pass": passed,
        "failed_criterion": failed_criterion,
        "metrics": {"per_subagent": per_persona},
    }


if __name__ == "__main__":
    import json
    ws = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    start, end = sys.argv[2], sys.argv[3]
    result = transcript_tools.find_run_transcripts(start, end)
    print(json.dumps(grade(ws, result), indent=2, default=str))
