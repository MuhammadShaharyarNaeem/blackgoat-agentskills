#!/usr/bin/env python3
"""One place that writes a `results.jsonl` record for a zero-LLM eval case.

The two zero-LLM cases (`contract/mechanical-pipeline/run.py`,
`contract/bugfix-gates-adversarial/run.py`) are invisible to `run-evals.ps1`'s case
discovery by design and used to write **no record at all** -- so the only proof
either had ever run was a human remembering it. They are free, so there was never a
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


def utc_timestamp():
    # Matches PowerShell's (Get-Date).ToUniversalTime().ToString('o') closely enough
    # for a reader parsing with a standard ISO-8601 parser.
    return datetime.utcnow().isoformat() + "Z"


def append_script_record(case, passed, failed_criterion=None, duration_s=None,
                         results_path=None):
    """Append one flat record for a deterministic, script-graded eval run.

    `run_index` is always 1 and `judge` is always "script": there is no LLM
    variance here to average over N runs, which is why these two cases are exempt
    from the suite's runs=5 doctrine. A reader computing a pass RATE must therefore
    not pool a `judge: "script"` row with the LLM rows for the same case name --
    there is no such case name overlap today, and this field is how it stays
    detectable if one is ever added.
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
