#!/usr/bin/env python3
"""Zero-LLM adversarial eval: walks the /bgpdd-bugfix lane's own gate chain
(check_bugfix_intake.py -> RED capture -> next_bugfix_route.py -> fix -> GREEN
capture -> check_red_green.py -> check_commit_gate.py) against a disposable
temp git repo, and asserts the exit code AND the naming JSON field on each of
the fabricated inputs the lane is supposed to refuse.

Each gate ships its own `--self-test`, which proves the predicate in-process
against synthetic fixtures. Nothing previously proved that the four bugfix
gates refuse a fabricated run when they are COMPOSED in the order the lane
invokes them, against real run_quiet.py captures and a real on-disk git repo:
that a route will not run without a recorded intake PASS, that editing the
report after that PASS invalidates it, that a GREEN of a different command is
not a proof, that 4-of-5 green is not fixed, and that the shipped rca-template's
own placeholder waiver does not waive anything.

Deliberately needs no `claude -p` -- every step is a subprocess call to a
deterministic stdlib-Python CLI against fixture files this script writes, so it
is safe to run unconfirmed and is exempt from the suite's runs=5 doctrine,
which exists to average out LLM variance. There is none here.

See README.md in this directory for what this proves and when to re-run it.

Usage:
    python run.py

Exit 0 only if every step passes. Prints a PASS/FAIL line per step and a final
RESULT: line; on failure the detail line shows the raw JSON the tool produced.
The script builds its own temp directory and removes it unconditionally.
"""
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# evals/contract/bugfix-gates-adversarial/run.py -> plugin root is 3 levels up.
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = PLUGIN_ROOT / "skills" / "pipeline-tools" / "scripts"
REFERENCES = PLUGIN_ROOT / "skills" / "bgpdd-bugfix" / "references"

CHECK_INTAKE = SCRIPTS / "check_bugfix_intake.py"
NEXT_ROUTE = SCRIPTS / "next_bugfix_route.py"
CHECK_RED_GREEN = SCRIPTS / "check_red_green.py"
CHECK_COMMIT_GATE = SCRIPTS / "check_commit_gate.py"
RUN_QUIET = SCRIPTS / "run_quiet.py"

BUG_REPORT_TEMPLATE = REFERENCES / "bug-report-template.md"
RCA_TEMPLATE = REFERENCES / "rca-template.md"

SLUG = "probe-exit-code"

# The reproduction command. Quoted on purpose: `-H "Content-Type: ..."` is the
# shape a string compare rejected and a token compare accepts, so the route
# gate's `red_match_strategy` is exercised rather than assumed. `python` is
# invoked by bare name so the report's `- Command:` line stays a plain,
# argv-runnable string (run_quiet.py execs argv with no shell).
PROBE_ARGV = ["python", "probe.py", "-H", "Content-Type: application/json"]
PROBE_COMMAND = 'python probe.py -H "Content-Type: application/json"'

# The probe's exit code is a pure function of state.txt, which is what lets one
# IDENTICAL argv be a RED before the fix and a GREEN after it -- exactly the
# property check_red_green.py exists to verify.
PROBE_PY = """import pathlib, sys
state = pathlib.Path(__file__).with_name("state.txt").read_text().strip()
print("probe: state=" + state)
sys.exit(22 if state == "broken" else 0)
"""

VALID_REPORT = """# Bug report: the probe exits 22 while the service is broken

## Observed behaviour

The probe command exits 22 and prints `probe: state=broken`.

## Expected behaviour

The probe exits 0 once the service answers correctly, which is what the
deployment checklist asserts before a release is cut.

## Exact error text or log excerpt

```
probe: state=broken
exit 22
```

## Reproduction

- Command: `%s`

## Environment

- Repository / branch: bugfix-gates-adversarial - fix/probe-exit-code
- Version or commit: the scaffold commit
- Runtime / OS: Python 3 on this host
- How it was run: directly, from the repository root

## Regression

- Regression: no
- Last known good: not applicable - never worked

## Affected surface

- Surface: api
- Runtime observable: yes
""" % PROBE_COMMAND

# The documented residual the intake lint cannot close: `see chat` is backticked
# and two tokens, so it passes the text lint. UNQUOTED it does not -- and with no
# numbered steps beside it there is no fallback reproduction either.
SEE_CHAT_REPORT = VALID_REPORT.replace(
    "- Command: `%s`" % PROBE_COMMAND, "- Command: see chat")

RCA = """# RCA: probe-exit-code

## Hypothesis ledger

| Hypothesis | Disproof attempt (the read or command run) | Result |
|---|---|---|
| the probe reads the wrong file | read `probe.py` | disproved - it reads `state.txt` beside itself |
| `state.txt` holds the broken sentinel | ran `python probe.py` and read `state.txt` | survived - it holds `broken` |

## Root cause

`state.txt` holds the broken sentinel, so `probe.py` takes its non-zero exit
branch.

- Root cause file: `state.txt`

## Fix shape

- Baseline suite: green
- New capability: no
- Schema or contract change: no
- Estimated changed files: 1
"""

REVIEW_REPORT = """# Review report: probe-exit-code

## Review: probe-exit-code

**Verdict:** Approve

No Critical or Important findings.
"""

REAL_WAIVER = """# RCA: probe-exit-code (oversized fix)

## Root cause

Six call sites read the sentinel directly instead of going through the probe.

- Root cause file: `state.txt`

## Fix shape

- Baseline suite: green
- New capability: no
- Schema or contract change: no
- Estimated changed files: 6

## Size waiver

Six files, not five: the sentinel is read directly at six call sites and
collapsing them into one reader is a refactor this bugfix must not take on.
The user approved proceeding at six files on 2026-09-03.
"""

results = []
_clock = itertools.count(1_700_000_000, 10)


def tick():
    return next(_clock)


def set_mtime(path, t=None):
    t = tick() if t is None else t
    os.utime(path, (t, t))
    return t


def record(name, ok, detail=""):
    results.append((name, ok))
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f"\n         {detail}"
    print(line)


def run_py(script, args, cwd):
    return subprocess.run([sys.executable, str(script)] + [str(a) for a in args],
                          cwd=str(cwd), capture_output=True, text=True)


def run_git(args, repo):
    return subprocess.run(["git"] + args, cwd=str(repo), capture_output=True, text=True)


def parse_json(proc, step_name):
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        record(step_name, False,
               f"could not parse JSON stdout: {exc}\nstdout={proc.stdout!r}\n"
               f"stderr={proc.stderr!r}")
        return None


def expect(step_name, proc, exit_code, predicate=None, why=""):
    """Assert the exit code, then a naming JSON field. An exit code alone can be
    right for the wrong reason -- these gates have three of them."""
    data = parse_json(proc, step_name)
    if data is None:
        return None
    ok = proc.returncode == exit_code
    detail = ""
    if not ok:
        detail = f"expected exit {exit_code}, got {proc.returncode}: {json.dumps(data)}"
    elif predicate is not None and not predicate(data):
        ok = False
        detail = f"exit {exit_code} as expected, but {why}: {json.dumps(data)}"
    record(step_name, ok, detail)
    return data


def codes(data):
    return list(data.get("problem_codes") or [])


def write_capture(cwd, path, extra_fields=()):
    """Take a REAL run_quiet.py capture of the probe, sidecar and all."""
    args = ["--capture", path]
    for field in extra_fields:
        args += ["--capture-field", field]
    args += ["--"] + PROBE_ARGV
    return run_py(RUN_QUIET, args, cwd)


def main():
    if shutil.which("python") is None:
        print("RESULT: ERROR - `python` is not on PATH, and the reproduction "
              "command this case asserts on is invoked by bare name.")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="eval-bugfix-gates-adversarial-"))
    try:
        run_suite(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"RESULT: FAIL ({len(failed)}/{len(results)} steps failed)")
        return 1
    print(f"RESULT: PASS ({len(results)}/{len(results)} steps passed)")
    return 0


def run_suite(repo):
    # --- Setup ---------------------------------------------------------------
    init = run_git(["init", "-q"], repo)
    run_git(["config", "user.email", "eval@test"], repo)
    run_git(["config", "user.name", "eval"], repo)
    if init.returncode != 0:
        record("0. setup: git init", False, init.stderr)
        return

    (repo / "probe.py").write_text(PROBE_PY, encoding="utf-8")
    (repo / "state.txt").write_text("broken\n", encoding="utf-8")
    root = repo / ".docs" / "bugfix" / SLUG
    (root / "evidence" / "red").mkdir(parents=True)
    (root / "evidence" / "green").mkdir(parents=True)
    state_path = root / "orchestrator-state.json"
    state_path.write_text(json.dumps({
        "schema": "1", "project_name": SLUG, "feature": None,
        "pipeline": "bgpdd-bugfix", "branch": "fix/probe-exit-code",
        "milestone_cursor": None, "artifacts": {}, "blockers": [],
    }, indent=2), encoding="utf-8")
    run_git(["add", "-A"], repo)
    scaffold = run_git(["commit", "-q", "-m", "scaffold"], repo)
    record("0. setup: git init + probe + scaffold commit",
           scaffold.returncode == 0,
           "" if scaffold.returncode == 0 else scaffold.stderr)

    ledger = f".docs/bugfix/{SLUG}/gates.jsonl"
    report_rel = f".docs/bugfix/{SLUG}/bug-report.md"
    rca_rel = f".docs/bugfix/{SLUG}/rca.md"
    red_rel = f".docs/bugfix/{SLUG}/evidence/red/{SLUG}.md"
    green_rel = f".docs/bugfix/{SLUG}/evidence/green/{SLUG}.md"

    # --- 1. the SHIPPED bug-report template must FAIL the intake gate --------
    # A template that passes is a bypass: copy it, run the gate, delegate.
    proc = run_py(CHECK_INTAKE, ["--report", BUG_REPORT_TEMPLATE,
                                 "--milestone", SLUG], repo)
    expect("1. intake: the SHIPPED bug-report template -> exit 1", proc, 1,
           lambda d: len(codes(d)) > 0,
           "it named no problem code")

    # --- 2. a real report passes, and the PASS lands in the ledger -----------
    (root / "bug-report.md").write_text(VALID_REPORT, encoding="utf-8")
    proc = run_py(CHECK_INTAKE, ["--report", report_rel, "--milestone", SLUG,
                                 "--ledger", ledger], repo)
    # NOTE on types: `runtime_observable` and `regression` come back as JSON
    # BOOLEANS, not the strings `yes`/`no` the report writes. pipeline-tools/
    # SKILL.md lists the keys without their types, so this asserts the observed
    # contract rather than the one a reader would guess from the field rules.
    expect("2. intake: a conforming report -> exit 0, reproduction_mode=command",
           proc, 0,
           lambda d: d.get("reproduction_mode") == "command"
           and d.get("reproduction_command") == PROBE_COMMAND
           and d.get("surface") == "api"
           and d.get("runtime_observable") is True
           and d.get("regression") is False,
           "the parsed fields are not the report's")

    # --- 3. `- Command: see chat` UNQUOTED, with no steps -> exit 1 ----------
    unquoted = root / "bug-report-see-chat.md"
    unquoted.write_text(SEE_CHAT_REPORT, encoding="utf-8")
    proc = run_py(CHECK_INTAKE, ["--report", f".docs/bugfix/{SLUG}/bug-report-see-chat.md",
                                 "--milestone", SLUG], repo)
    expect("3. intake: `- Command: see chat` unquoted, no steps -> exit 1", proc, 1,
           lambda d: "reproduction_missing" in codes(d),
           "it did not name reproduction_missing")

    # --- RED: a real run_quiet capture of the broken probe -------------------
    proc = write_capture(repo, red_rel)
    record("4. run_quiet: RED capture of the broken probe -> exit 22",
           proc.returncode == 22,
           "" if proc.returncode == 22 else f"exit {proc.returncode}: {proc.stdout}")
    (root / "rca.md").write_text(RCA, encoding="utf-8")

    # --- 5. the route refuses to run without a recorded intake PASS ----------
    empty_ledger = f".docs/bugfix/{SLUG}/gates-empty.jsonl"
    (root / "gates-empty.jsonl").write_text("", encoding="utf-8")
    proc = run_py(NEXT_ROUTE, ["--report", report_rel, "--rca", rca_rel,
                               "--red", red_rel, "--milestone", SLUG,
                               "--ledger", empty_ledger,
                               "--max-changed-files", "5"], repo)
    expect("5. route: no intake PASS in the ledger -> exit 2 (intake_unbacked)",
           proc, 2,
           lambda d: "intake_unbacked" in codes(d) or "intake_unbacked" in str(d.get("error")),
           "it did not name intake_unbacked")

    # --- 6. the route refuses a report EDITED after its intake PASS ----------
    # The ledger's recorded input hash no longer matches the bytes on disk, which
    # is the whole reason the route reads the ledger rather than re-linting.
    original = (root / "bug-report.md").read_text(encoding="utf-8")
    (root / "bug-report.md").write_text(
        original.replace("## Observed behaviour",
                         "## Observed behaviour\n\n(edited after the gate passed)"),
        encoding="utf-8")
    proc = run_py(NEXT_ROUTE, ["--report", report_rel, "--rca", rca_rel,
                               "--red", red_rel, "--milestone", SLUG,
                               "--ledger", ledger,
                               "--max-changed-files", "5"], repo)
    expect("6. route: report edited after its intake PASS -> exit 2 (intake_unbacked)",
           proc, 2,
           lambda d: "intake_unbacked" in codes(d) or "intake_unbacked" in str(d.get("error")),
           "it did not name intake_unbacked")
    (root / "bug-report.md").write_text(original, encoding="utf-8")

    # --- 7. the route with a matching --red on a QUOTED command -> FAST ------
    proc = run_py(NEXT_ROUTE, ["--report", report_rel, "--rca", rca_rel,
                               "--red", red_rel, "--milestone", SLUG,
                               "--ledger", ledger,
                               "--max-changed-files", "5"], repo)
    expect("7. route: matching --red on a quoted command -> exit 0, FAST", proc, 0,
           lambda d: d.get("result") == "FAST" and d.get("red_matches_report") is True
           and d.get("red_match_strategy"),
           "it did not route FAST off a matched RED")

    # --- 8. the route refuses a --red that ran a DIFFERENT command ----------
    other_red = f".docs/bugfix/{SLUG}/evidence/red/{SLUG}-other.md"
    proc = run_py(RUN_QUIET, ["--capture", other_red, "--",
                              "python", "probe.py", "-H", "X-Other: nope"], repo)
    proc = run_py(NEXT_ROUTE, ["--report", report_rel, "--rca", rca_rel,
                               "--red", other_red, "--milestone", SLUG,
                               "--ledger", ledger,
                               "--max-changed-files", "5"], repo)
    expect("8. route: --red recorded a DIFFERENT argv -> exit 1 (red_command_mismatch)",
           proc, 1,
           lambda d: "red_command_mismatch" in codes(d) and d.get("result") == "BLOCKED",
           "it did not BLOCK on red_command_mismatch")

    # --- The fix, then a real GREEN capture of the SAME argv ----------------
    (repo / "state.txt").write_text("fixed\n", encoding="utf-8")
    proc = write_capture(repo, green_rel,
                         extra_fields=[f"Milestone={SLUG}", "Surface=api",
                                       "Transport=out-of-process HTTP"])
    record("9. run_quiet: GREEN capture of the fixed probe, same argv -> exit 0",
           proc.returncode == 0,
           "" if proc.returncode == 0 else f"exit {proc.returncode}: {proc.stdout}")

    # --- 10. a hand-typed GREEN with no sidecar is not evidence -------------
    typed = root / "evidence" / "green" / "typed-by-hand.md"
    typed.write_text("# Runtime capture\n\n- Exit code: 0\n\n"
                     "## Captured output\n\n```\nprobe: state=fixed\n```\n",
                     encoding="utf-8")
    proc = run_py(CHECK_RED_GREEN, ["--red", red_rel, "--green",
                                    f".docs/bugfix/{SLUG}/evidence/green/typed-by-hand.md",
                                    "--milestone", SLUG, "--ledger", ledger], repo)
    expect("10. red/green: a hand-typed GREEN with no sidecar -> exit 1 (sidecar_missing)",
           proc, 1,
           lambda d: "sidecar_missing" in codes(d),
           "it did not name sidecar_missing")

    # --- 11. a GREEN of a DIFFERENT argv is two unrelated runs -------------
    other_green = f".docs/bugfix/{SLUG}/evidence/green/{SLUG}-other.md"
    run_py(RUN_QUIET, ["--capture", other_green, "--",
                       "python", "probe.py", "-H", "X-Other: nope"], repo)
    proc = run_py(CHECK_RED_GREEN, ["--red", red_rel, "--green", other_green,
                                    "--milestone", SLUG, "--ledger", ledger], repo)
    expect("11. red/green: GREEN of a different argv -> exit 1 (command_mismatch)",
           proc, 1,
           lambda d: "command_mismatch" in codes(d),
           "it did not name command_mismatch")

    # --- 12. the honest pair passes -----------------------------------------
    proc = run_py(CHECK_RED_GREEN, ["--red", red_rel, "--green", green_rel,
                                    "--milestone", SLUG, "--ledger", ledger], repo)
    expect("12. red/green: the honest RED/GREEN pair -> exit 0", proc, 0,
           lambda d: d.get("result") == "PASS",
           "the result field is not PASS")

    # --- 13. 4 of 5 green is not fixed -------------------------------------
    flaky = []
    for index in range(1, 5):
        path = f".docs/bugfix/{SLUG}/evidence/green/{SLUG}-run{index}.md"
        write_capture(repo, path)
        flaky.append(path)
    args = ["--red", red_rel]
    for path in flaky:
        args += ["--green", path]
    args += ["--green-runs", "5", "--milestone", SLUG, "--ledger", ledger]
    proc = run_py(CHECK_RED_GREEN, args, repo)
    expect("13. red/green: 4 green captures under --green-runs 5 -> exit 1 (green_runs_short)",
           proc, 1,
           lambda d: "green_runs_short" in codes(d),
           "it did not name green_runs_short")

    # --- Commit-gate fixtures: 6 declared files, all real ------------------
    declared = []
    for index in range(1, 7):
        path = repo / f"src-{index}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"changed file {index}\n", encoding="utf-8")
        set_mtime(path)
        declared.append(f"src-{index}.txt")
    review_path = root / "review-report.md"
    review_path.write_text(REVIEW_REPORT, encoding="utf-8")
    set_mtime(review_path)  # newer than every declared file, so not stale
    set_mtime(state_path)

    gate_common = ["--review-report", f".docs/bugfix/{SLUG}/review-report.md",
                   "--state", f".docs/bugfix/{SLUG}/orchestrator-state.json",
                   "--milestone", SLUG, "--repo", ".",
                   "--ledger", ledger, "--changed-files"] + declared

    # --- 14. six declared files against a bound of five, no waiver ---------
    proc = run_py(CHECK_COMMIT_GATE, gate_common + ["--max-changed-files", "5"], repo)
    expect("14. commit gate: 6 changed files, bound 5, no waiver -> exit 1 (size_ok false)",
           proc, 1,
           lambda d: d.get("size_ok") is False and d.get("changed_file_count") == 6
           and d.get("verdict") == "Approve",
           "it failed for a reason other than the size bound")

    # --- 15. the SHIPPED rca-template's placeholder waiver waives nothing --
    # The template writes its waiver as one `<...>` span wrapped across several
    # lines; a naive non-empty-body check accepts it, which would make "copy the
    # template" a size bypass.
    proc = run_py(CHECK_COMMIT_GATE, gate_common +
                  ["--max-changed-files", "5", "--waiver", str(RCA_TEMPLATE)], repo)
    expect("15. commit gate: the SHIPPED rca-template as --waiver -> exit 1", proc, 1,
           lambda d: d.get("size_ok") is False
           and (d.get("size_waiver") or {}).get("satisfied") is False,
           "the template's placeholder waiver was accepted")

    # --- 16. a hand-typed waiver clears the size term ----------------------
    waiver_path = root / "rca-oversized.md"
    waiver_path.write_text(REAL_WAIVER, encoding="utf-8")
    proc = run_py(CHECK_COMMIT_GATE, gate_common +
                  ["--max-changed-files", "5",
                   "--waiver", f".docs/bugfix/{SLUG}/rca-oversized.md"], repo)
    expect("16. commit gate: a hand-typed `## Size waiver` -> exit 0 (size term cleared)",
           proc, 0,
           lambda d: d.get("size_ok") is True
           and (d.get("size_waiver") or {}).get("satisfied") is True
           and d.get("committed") is not True,
           "the size term did not clear, or the gate committed without --commit")


if __name__ == "__main__":
    sys.exit(main())
