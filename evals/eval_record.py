#!/usr/bin/env python3
"""One place that writes a `results.jsonl` record for a zero-LLM eval case.

The four zero-LLM cases (`contract/mechanical-pipeline/run.py`,
`contract/bugfix-gates-adversarial/run.py`,
`contract/openapi-diff-adversarial/run.py`,
`contract/test-authenticity-adversarial/run.py`) are invisible to `run-evals.ps1`'s case
discovery by design and used to write **no record at all** -- so the only proof
any had ever run was a human remembering it. They are free, so there was never a
cost reason not to keep history; there was just no writer.

This module is that writer, and it is shared rather than copy-pasted into both
scripts for one reason: the record shape has to match the one `run-evals.ps1`
appends to the same file. Two independent copies of a shape that must agree is how
`judge: "substring"` outlived the judge that produced it.

Usage from a case's run.py:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from eval_record import append_script_record

    append_script_record(case="mechanical-pipeline", passed=ok,
                         failed_criterion=detail, duration_s=elapsed)

Nothing here raises on failure: a broken record write must not turn a green eval
red. It warns on stderr and returns None.
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# evals/eval_record.py -> evals/ is parents[0], the plugin root is parents[1].
EVALS_ROOT = Path(__file__).resolve().parent
PLUGIN_ROOT = EVALS_ROOT.parent
RESULTS_PATH = EVALS_ROOT / "results" / "results.jsonl"
RUN_EVALS_PS1 = EVALS_ROOT / "run-evals.ps1"

# Fallback only. The live value is read out of run-evals.ps1 so these records can
# never claim a harness version the harness itself has moved past.
HARNESS_VERSION_FALLBACK = "4"


def harness_version():
    """The `$HarnessVersion` constant in run-evals.ps1, or the fallback."""
    try:
        text = RUN_EVALS_PS1.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^\$HarnessVersion\s*=\s*'([^']+)'", text, re.M)
        if match:
            return match.group(1)
    except OSError:
        pass
    print(f"warning: could not read $HarnessVersion from {RUN_EVALS_PS1}; "
          f"recording harness_version={HARNESS_VERSION_FALLBACK}", file=sys.stderr)
    return HARNESS_VERSION_FALLBACK


def _git(args):
    try:
        proc = subprocess.run(["git"] + args, cwd=str(PLUGIN_ROOT),
                              capture_output=True, text=True)
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def plugin_sha():
    return _git(["rev-parse", "HEAD"]) or None


def plugin_dirty():
    status = _git(["status", "--porcelain"])
    if status is None:
        return False
    return bool(status.strip())


def case_sha256(case, case_path=None):
    """Hex sha256 of the case's `run.py`, or None when it cannot be read.

    The LLM-graded rows carry a `case_sha256` of their `case.md`; these three
    zero-LLM cases carried none, so "did the case change since this red was
    recorded?" could only be answered by hashing `run.py` by hand (2026-09-07
    audit, Metric 21b). A zero-LLM case's `run.py` IS its case definition --
    fixtures, assertions and grader in one file -- so it is the right subject.

    Resolved from the case name by convention (`contract/<case>/run.py`) so the
    three existing callers need no change; pass `case_path` to override.
    """
    path = Path(case_path) if case_path else EVALS_ROOT / "contract" / case / "run.py"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        print(f"warning: could not hash the case script {path}; "
              "recording case_sha256=null", file=sys.stderr)
        return None


def utc_timestamp():
    # Matches PowerShell's (Get-Date).ToUniversalTime().ToString('o') closely enough
    # for a reader parsing with a standard ISO-8601 parser.
    return datetime.utcnow().isoformat() + "Z"


def append_script_record(case, passed, failed_criterion=None, duration_s=None,
                         results_path=None, case_path=None):
    """Append one flat record for a deterministic, script-graded eval run.

    `run_index` is always 1 and `judge` is always "script": there is no LLM
    variance here to average over N runs, which is why these two cases are exempt
    from the suite's runs=5 doctrine. A reader computing a pass RATE must therefore
    not pool a `judge: "script"` row with the LLM rows for the same case name --
    there is no such case name overlap today, and this field is how it stays
    detectable if one is ever added.

    `case_sha256` is computed here rather than passed in, so the three existing
    callers keep working unchanged; `case_path` overrides the convention.
    """
    record = {
        "timestamp": utc_timestamp(),
        "case": case,
        "run_index": 1,
        "pass": bool(passed),
        "outcome": "GRADED",
        "failed_criterion": failed_criterion,
        "duration_s": duration_s,
        "plugin_sha": plugin_sha(),
        "plugin_dirty": plugin_dirty(),
        "case_sha256": case_sha256(case, case_path),
        "judge": "script",
        "harness_version": harness_version(),
    }
    target = Path(results_path) if results_path else RESULTS_PATH
    try:
        os.makedirs(str(target.parent), exist_ok=True)
        with io.open(str(target), "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"warning: could not append the run record to {target}: {exc}",
              file=sys.stderr)
        return None
    print(f"RECORDED: {target.name} <- {json.dumps(record)}")
    return record


def append_antigravity_record(case, run_index, passed, runtime="antigravity",
                              model="gemini-3.8-flash", failed_criterion=None,
                              metrics=None, outcome=None, triage=None,
                              duration_s=None, results_path=None, case_path=None):
    """Append one flat `evals/antigravity/` run record, sibling to `append_script_record`.

    Additive only: every field `append_script_record` writes is written here
    too (`case_sha256` hashes `evals/antigravity/cases/<case>/case.md` by
    convention instead of a `run.py`, since an antigravity case has no
    zero-LLM `run.py` -- pass `case_path` to override), plus two fields no
    existing reader looks for: `runtime` and `model`. `judge` is always
    `"harness"` (distinct from the existing `"tool_use"`/`"script"` values --
    an antigravity grade is neither a `claude -p` tool-use judge nor a
    zero-LLM script case; it is a Python grader reading transcripts + a
    workspace). `run-evals.ps1` never reads this file's `runtime`/`judge`
    values, so its own pass-rate pooling for contract/trigger cases is
    unaffected -- see evals/antigravity/README.md for how a reader is
    expected to pool these records (never mixed with `judge: "tool_use"` or
    `judge: "script"` rows for a same-named case; no name collision exists
    today because every antigravity case name is new).

    `outcome` should be `"GRADED"` or `"INFRA"` (INFRA when the window had no
    transcript or the workspace had no artifact at all -- same rule as the
    rest of the suite; `pass` must be `None` on an INFRA record). `metrics` is
    an arbitrary JSON-safe dict the case's grader produced; stored verbatim.
    """
    record = {
        "timestamp": utc_timestamp(),
        "case": case,
        "run_index": run_index,
        "pass": (bool(passed) if outcome != "INFRA" else None),
        "outcome": outcome or ("GRADED" if passed is not None else "INFRA"),
        "failed_criterion": failed_criterion,
        "duration_s": duration_s,
        "metrics": metrics or {},
        "runtime": runtime,
        "model": model,
        "plugin_sha": plugin_sha(),
        "plugin_dirty": plugin_dirty(),
        "case_sha256": _antigravity_case_sha256(case, case_path),
        "judge": "harness",
        "harness_version": harness_version(),
    }
    if triage:
        record["triage"] = triage
    target = Path(results_path) if results_path else RESULTS_PATH
    try:
        os.makedirs(str(target.parent), exist_ok=True)
        with io.open(str(target), "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"warning: could not append the run record to {target}: {exc}",
              file=sys.stderr)
        return None
    print(f"RECORDED: {target.name} <- {json.dumps(record)}")
    return record


def append_runtime_contract_record(case, run_index, passed, outcome, failed_criterion=None,
                                    duration_s=None, runtime="antigravity", model="gemini-3.8-flash",
                                    workspace=None, results_path=None, case_path=None):
    """Append one flat `evals/run_suite.py --suite contract` record, sibling to
    `append_antigravity_record`. Written by `evals/suites/contract.py` for a
    runtime-neutral contract grade (a `claude -p` invocation replaced by a
    human/Orchestrator-performed prompt on any runtime -- Antigravity by
    default). Carries the harness-4 contract fields from evals/README.md's
    "Result record shape" (this file's own docstring section) verbatim --
    `transcript` and `claude_version` are always `None` here because this
    writer has no archived per-run transcript file and no `claude --version`
    to read (the agent-under-test is not necessarily `claude` at all) -- plus
    the three additive fields `run_suite.py` needs that no existing writer
    carries: `runtime`, `model`, `workspace`.

    `judge` is always `"grade.ps1"` -- distinct from `run-evals.ps1`'s own
    `judge` values ("tool_use"/"script") and from `append_antigravity_record`'s
    `"harness"`, so a reader pooling `results.jsonl` can always tell which
    tool produced the verdict.
    """
    record = {
        "timestamp": utc_timestamp(),
        "case": case,
        "run_index": run_index,
        "pass": (bool(passed) if outcome != "INFRA" else None),
        "failed_criterion": failed_criterion,
        "duration_s": duration_s,
        "outcome": outcome,
        "transcript": None,
        "judge": "grade.ps1",
        "plugin_sha": plugin_sha(),
        "plugin_dirty": plugin_dirty(),
        "claude_version": None,
        "case_sha256": case_sha256(case, case_path),
        "harness_version": harness_version(),
        "runtime": runtime,
        "model": model,
        "workspace": str(workspace) if workspace else None,
    }
    target = Path(results_path) if results_path else RESULTS_PATH
    try:
        os.makedirs(str(target.parent), exist_ok=True)
        with io.open(str(target), "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"warning: could not append the run record to {target}: {exc}",
              file=sys.stderr)
        return None
    print(f"RECORDED: {target.name} <- {json.dumps(record)}")
    return record


def append_runtime_trigger_record(case, run_index, outcome, first_skill, skills_invoked,
                                   expected_chain, mentioned_only, failed_criterion=None,
                                   duration_s=None, runtime="antigravity", model="gemini-3.8-flash",
                                   workspace=None, raw_line=None, results_path=None):
    """Append one flat `evals/run_suite.py --suite trigger` record, sibling to
    `append_runtime_contract_record`. `pass` is derived from `outcome` exactly
    as evals/README.md's "Trigger judging" table defines it (`True` only for
    `"ROUTED_OK"`). `case_sha256` hashes the case's raw `cases.jsonl` line
    (there is no `case.md` for a trigger case), matching `run-evals.ps1`'s own
    trigger records. `judge` is always `"skill_read"` -- distinct from
    `run-evals.ps1`'s `"tool_use"`, since this judge reads `skills/<name>/
    SKILL.md` file-view events off a transcript rather than a `Skill`
    tool_use block (no runtime this suite targets necessarily has one).
    """
    record = {
        "timestamp": utc_timestamp(),
        "case": case,
        "run_index": run_index,
        "pass": (outcome == "ROUTED_OK"),
        "failed_criterion": failed_criterion,
        "duration_s": duration_s,
        "outcome": outcome,
        "first_skill": first_skill,
        "skills_invoked": list(skills_invoked or []),
        "expected_chain": list(expected_chain or []),
        "mentioned_only": mentioned_only,
        "transcript": None,
        "judge": "skill_read",
        "plugin_sha": plugin_sha(),
        "plugin_dirty": plugin_dirty(),
        "claude_version": None,
        "case_sha256": (hashlib.sha256(raw_line.encode("utf-8")).hexdigest()
                        if raw_line else None),
        "harness_version": harness_version(),
        "runtime": runtime,
        "model": model,
        "workspace": str(workspace) if workspace else None,
    }
    target = Path(results_path) if results_path else RESULTS_PATH
    try:
        os.makedirs(str(target.parent), exist_ok=True)
        with io.open(str(target), "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"warning: could not append the run record to {target}: {exc}",
              file=sys.stderr)
        return None
    print(f"RECORDED: {target.name} <- {json.dumps(record)}")
    return record


def _antigravity_case_sha256(case, case_path=None):
    """Hex sha256 of an antigravity case's `case.md`, or None if unreadable."""
    path = Path(case_path) if case_path else EVALS_ROOT / "antigravity" / "cases" / case / "case.md"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        print(f"warning: could not hash the case definition {path}; "
              "recording case_sha256=null", file=sys.stderr)
        return None
