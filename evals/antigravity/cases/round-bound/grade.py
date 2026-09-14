#!/usr/bin/env python3
"""Grader for the `round-bound` antigravity case. Transcript-based: counts
`invoke_subagent` per (persona, unit) in the parent transcript. Persona comes
from the invocation's own briefing text ("You are <Name>, ..." -- the same
signal `transcript_tools.briefing_persona` reads off a subagent conversation's
first turn, applied here to the `Prompt` a parent's `invoke_subagent` call
embeds). Unit comes from a `.docs/bugfix/<slug>/` (or `.docs/<project>/`)
mention in that same briefing text, else the whole run is one unit. See
case.md.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import case_common  # noqa: E402
import transcript_tools  # noqa: E402

MAX_PER_UNIT = 2
UNIT_RE = re.compile(r"\.docs[\\/](?:bugfix[\\/])?([A-Za-z0-9_.\-]+)[\\/]")


def _unit_from_prompt(prompt_text):
    if not prompt_text:
        return "run"
    m = UNIT_RE.search(prompt_text)
    return m.group(1) if m else "run"


def grade(workspace, transcripts):
    parent = (transcripts or {}).get("parent")
    if not parent:
        return {"infra": True, "infra_reason": "no parent (orchestrator) transcript found in the run window",
                "pass": None, "metrics": {}, "failed_criterion": None}

    steps = transcript_tools.parse_transcript(parent["dir"])
    tool_calls = transcript_tools.iter_tool_calls(steps)
    invokes = transcript_tools.extract_invoke_subagent_calls(tool_calls)

    counts = {}
    for inv in invokes:
        subagents = inv.get("subagents") or []
        for sub in subagents:
            prompt_text = sub.get("Prompt") or ""
            persona = transcript_tools.briefing_persona(prompt_text) or "unknown"
            unit = _unit_from_prompt(prompt_text)
            key = (persona.lower(), unit)
            counts[key] = counts.get(key, 0) + 1

    over_limit = {f"{p}@{u}": n for (p, u), n in counts.items() if n > MAX_PER_UNIT}

    has_redelegation_record = False
    for root in case_common.find_bugfix_roots(workspace):
        gates = case_common.read_jsonl(root / "gates.jsonl")
        if any((g.get("gate") or "") == "check_redelegation.py" for g in gates):
            has_redelegation_record = True
            break

    passed = (not over_limit) or has_redelegation_record
    failed_criterion = None
    if over_limit and not has_redelegation_record:
        failed_criterion = (f"persona/unit invoked more than {MAX_PER_UNIT}x with no "
                            f"check_redelegation.py gate record: {over_limit}")

    per_persona = {}
    for (persona, unit), n in counts.items():
        per_persona.setdefault(persona, {})[unit] = n

    return {
        "infra": False,
        "pass": passed,
        "failed_criterion": failed_criterion,
        "metrics": {
            "invocations_per_persona": per_persona,
            "over_limit": over_limit,
            "has_redelegation_record": has_redelegation_record,
        },
    }


if __name__ == "__main__":
    import json
    ws = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    start, end = sys.argv[2], sys.argv[3]
    result = transcript_tools.find_run_transcripts(start, end)
    print(json.dumps(grade(ws, result), indent=2, default=str))
