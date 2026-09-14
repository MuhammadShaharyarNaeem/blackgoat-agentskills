#!/usr/bin/env python3
"""Grader for the `run-log-discipline` antigravity case. Artifact-only: reads
only `run-log.jsonl` under the workspace's `.docs/bugfix/<slug>/` root.
See case.md for the full criterion.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import case_common  # noqa: E402

REQUIRED_AGENTS = {"quinn", "mason", "luna"}


def grade(workspace, transcripts):
    """`workspace`: Path to the graded run's workspace. `transcripts`: unused
    here (artifact-only case) but accepted for a uniform grader signature.
    """
    roots = case_common.find_bugfix_roots(workspace)
    if not roots:
        return {"infra": True, "infra_reason": "no .docs/bugfix/<slug>/bug-report.md found",
                "pass": None, "metrics": {}, "failed_criterion": None}

    # The lane picks its own bug-slug; grade whichever root actually has a
    # run-log.jsonl (there should be exactly one for a single-bug run).
    run_log_path = None
    for root in roots:
        candidate = root / "run-log.jsonl"
        if candidate.is_file():
            run_log_path = candidate
            break
    if run_log_path is None:
        return {"infra": True, "infra_reason": "bug-report.md present but no run-log.jsonl beside it",
                "pass": None, "metrics": {}, "failed_criterion": None}

    records = case_common.read_jsonl(run_log_path)
    delegations = [r for r in records if r.get("event") == "delegation"]

    agents_seen = set()
    missing_fields = []
    for i, rec in enumerate(delegations):
        agent = (rec.get("agent") or "").lower()
        if agent:
            agents_seen.add(agent)
        problems = []
        model = rec.get("model")
        tier = rec.get("tier")
        runtime = rec.get("runtime")
        has_tokens = (
            rec.get("tokens_total") is not None
            or (rec.get("tokens_in") is not None and rec.get("tokens_out") is not None)
            or bool(rec.get("tokens_unavailable"))
        )
        runtime_is_non_claude = bool(runtime) and runtime.lower() not in ("claude", "claude-code", "anthropic")
        if not model:
            problems.append("model missing")
        elif runtime_is_non_claude and model.lower() in case_common.CLAUDE_TIERS:
            problems.append(f"model={model!r} is a Claude tier name under runtime={runtime!r}")
        if not tier:
            problems.append("tier missing")
        if not has_tokens:
            problems.append("no tokens_total/tokens_in+out/tokens_unavailable")
        if not runtime:
            problems.append("runtime missing")
        if problems:
            missing_fields.append({"index": i, "agent": rec.get("agent"), "problems": problems})

    missing_required_agents = sorted(REQUIRED_AGENTS - agents_seen)
    passed = (not missing_required_agents) and (not missing_fields) and bool(delegations)

    failed_criterion = None
    if not delegations:
        failed_criterion = "no delegation records in run-log.jsonl"
    elif missing_required_agents:
        failed_criterion = f"missing delegation record(s) for: {', '.join(missing_required_agents)}"
    elif missing_fields:
        failed_criterion = f"{len(missing_fields)} delegation record(s) missing required fields"

    return {
        "infra": False,
        "pass": passed,
        "failed_criterion": failed_criterion,
        "metrics": {
            "run_log": str(run_log_path),
            "records": len(delegations),
            "agents_seen": sorted(agents_seen),
            "missing_required_agents": missing_required_agents,
            "missing_fields": missing_fields,
        },
    }


if __name__ == "__main__":
    import json
    ws = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    print(json.dumps(grade(ws, {}), indent=2))
