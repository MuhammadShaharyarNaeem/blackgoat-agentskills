#!/usr/bin/env python3
"""Zero-LLM integration eval: walks a milestone's full lifecycle through the
pipeline-tools mechanical CLI family (next_milestone.py, update_state.py,
check_commit_gate.py, run_quiet.py, check_runtime_evidence.py,
check_acceptance_suite.py) against a disposable temp git repo.

Deliberately needs no `claude -p` -- it exercises only the mechanical layer
(deterministic stdlib Python CLIs), so it is safe to run unconfirmed and is
exempt from the suite's runs=5 doctrine, which exists to average out LLM
variance across repeated persona invocations. This case has none: every step
is a pure function of its inputs, so one run either proves the composition
works or doesn't.

See README.md in this directory for what this proves and when to re-run it.

Usage:
    python run.py               # run, print, record nothing
    python run.py --record      # ... and append one record to results/results.jsonl

Exit 0 only if every step below passes. Prints a PASS/FAIL table and cleans
up its temp directory unconditionally (even on failure).

--record is OFF by default so an iteration loop on this file does not pollute the
run log, and `run-evals.ps1` passes it at the start of every confirmed contract
batch: the case is free, and until that landed it left no history at all.
"""
import argparse
import hashlib
import itertools
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# evals/contract/mechanical-pipeline/run.py -> plugin root is 3 levels up.
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = PLUGIN_ROOT / "skills" / "pipeline-tools" / "scripts"
NEXT_MILESTONE = SCRIPTS / "next_milestone.py"
UPDATE_STATE = SCRIPTS / "update_state.py"
CHECK_COMMIT_GATE = SCRIPTS / "check_commit_gate.py"
RUN_QUIET = SCRIPTS / "run_quiet.py"
CHECK_RUNTIME_EVIDENCE = SCRIPTS / "check_runtime_evidence.py"
CHECK_ACCEPTANCE_SUITE = SCRIPTS / "check_acceptance_suite.py"
CHECK_AGENT_REPORT = SCRIPTS / "check_agent_report.py"
CHECK_HANDOFF = SCRIPTS / "check_handoff.py"
CHECK_ALWAYS_ON = SCRIPTS / "check_always_on.py"
CHECK_TIER1_PROVENANCE = SCRIPTS / "check_tier1_provenance.py"
CHECK_RUNTIME_RECIPE = SCRIPTS / "check_runtime_recipe.py"
MARK_MILESTONE = SCRIPTS / "mark_milestone.py"
RECORD_RUN = SCRIPTS / "record_run.py"
GUARD_ACTION = SCRIPTS / "guard_action.py"

# The shared record writer lives in evals/, two levels up from this file. Shared,
# not copied into each case, because the record shape has to match the one
# run-evals.ps1 appends to the same file.
sys.path.insert(0, str(PLUGIN_ROOT / "evals"))
from eval_record import append_script_record  # noqa: E402

# The TOKEN used for --milestone / --set-cursor: deliberately untagged. Cursor
# and milestone matching are word-boundary token tests, so a cursor written
# before the [vs:] axis existed still matches a now-tagged heading. That
# back-compat property is asserted by steps 1 and 8a passing with these values.
MILESTONE2_TITLE = "Milestone 2 — API Layer"
MILESTONE3_TITLE = "Milestone 3 — UI Layer"
# The full HEADING text, which is what next_milestone reports as `title`.
MILESTONE2_HEADING = f"{MILESTONE2_TITLE} [API] [vs:api]"
MILESTONE3_HEADING = f"{MILESTONE3_TITLE} [UI] [vs:ui]"

PLAN_TEMPLATE = """# Plan: Proj

## Milestone 1 — Bootstrap [API] [vs:api] [x]

## Task 1: Init repo

**Tags:** [API]

Repo initialized.

## Milestone 2 — API Layer [API] [vs:api]

## Task 2: Build endpoint

**Tags:** [API]

**Requirements covered:** None

Implements the contacts endpoint.

## Task 3: Add validation

**Tags:** [API]

**Requirements covered:** None

Adds request validation.

## Milestone 3 — UI Layer [UI] [vs:ui]

## Task 4: Build screen

**Tags:** [UI]

**Requirements covered:** None

Builds the contacts panel.
"""

# --- Steps 10-11 fixtures: the two evidence gates ---------------------------
# The response body the platform's envelope requires, and the bare body the
# 2026-08 incident actually shipped. Only the body differs between the 10a and
# 10b captures: same honest transport, same local host, same runtime probe, same
# 200 -- which is the whole point, because only the body reveals the defect.
ENVELOPE_BODY = ('{"statusCode":200,"isSuccess":true,"notifications":[],'
                 '"data":{"id":1,"total":9}}')
BARE_BODY = '{"id":1,"total":9}'

# The capture header's `- Captured:` and the sidecar's `finished` are ONE fact
# recorded twice, and check_runtime_evidence.py's `sidecar_body_disagrees` term now
# requires them to agree (0 <= captured - finished <= CAPTURED_SKEW_SECONDS). They
# are constants here so the honest fixture cannot drift into looking forged: before
# this, the capture said 2026-08-12 and write_sidecar() said 2026-01-01, 223 days
# apart, and step 10a began failing the moment that term landed. The same pair is
# what an ATTACK moves - see step 10c.
CAPTURE_STARTED = "2026-08-12T09:59:59Z"
CAPTURE_FINISHED = "2026-08-12T10:00:00Z"
CAPTURED_STAMP = CAPTURE_FINISHED

CAPTURE_TEMPLATE = """# Runtime capture: GET /api/contacts

- Milestone: {milestone}
- Requirement IDs: FR-1
- Surface: api
- Transport: out-of-process HTTP (curl)
- Base URL: http://localhost:5142
- Probe command: `curl -sS -i http://localhost:5142/api/contacts`
- Captured: {captured}
- Exit code: 0

## Captured output

```
HTTP/1.1 200 OK
content-type: application/json

{body}
```
"""

RUNTIME_REPORT_TEMPLATE = """# Contacts — Test Report

#Task [2]:

**Runtime evidence:** {capture}

- FR-1: PASS — `curl -sS -i http://localhost:5142/api/contacts` — exit 0
"""

# One scenario, three steps, one of them `manual` -- the manual step is where the
# two gates meet: check_acceptance_suite only checks that its cited evidence
# EXISTS under evidence/runtime/, while check_runtime_evidence is what opens the
# same file and judges whether the observation is honest. Step 11a cites the very
# capture step 10a accepted, so the composition is asserted rather than assumed.
ACCEPTANCE_MATRIX = """# Acceptance Matrix — proj

## AS-1 Contacts endpoint lifecycle — P0 — (FR-1)
Surface: api | Preconditions: none

| # | GO | DO | ASSERT | Stores | Mode |
|---|----|----|--------|--------|------|
| 1 | Contacts API | create a contact | 200 + row stored | api, db | auto |
| 2 | Contacts API | delete the contact [inverse of 1] | 200 + row gone | api, db | auto |
| 3 | Contacts API | read the response off the wire | body carries isSuccess and notifications | api | manual |
"""

ACCEPTANCE_RESULTS_GREEN = """# Acceptance Results — proj

## Execution

- AS-1.1: PASS — exit 0 — 200 + row stored
- AS-1.2: PASS — exit 0 — 200 + row gone
- AS-1.3: PASS — evidence/runtime/m2-contacts-get.md — envelope observed on the wire
"""

ACCEPTANCE_RESULTS_UNEVIDENCED = """# Acceptance Results — proj

## Execution

- AS-1.1: PASS — exit 0 — 200 + row stored
- AS-1.2: PASS — exit 0 — 200 + row gone
- AS-1.3: PASS — checked it by hand, looked right
"""

# Monotonically increasing fake-clock seconds, used with os.utime so mtime
# ordering (staleness checks) is deterministic instead of racing real-clock
# resolution.
_clock = itertools.count(1_700_000_000, 10)


def tick():
    return next(_clock)


def set_mtime(path, t=None):
    t = tick() if t is None else t
    os.utime(path, (t, t))
    return t


# A 1x1 transparent PNG. --require-rendered-evidence demands a NON-EMPTY file
# carrying its format's magic bytes, so a zero-byte placeholder named .png no
# longer satisfies the gate -- an empty file depicts nothing.
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6360000002000100fdff03fa0000000"
    "049454e44ae426082".replace(" ", ""))


def write_sidecar(capture_path, exit_code=0):
    """Mirror `run_quiet.py --capture`'s machine-owned provenance sidecar.

    check_runtime_evidence.py rejects a capture with no sidecar, one whose
    capture_sha256 no longer matches, or one whose probe exited non-zero.
    These fixtures are written directly rather than produced by a real probe,
    so the sidecar is written the same way run_quiet.py writes it -- schema
    and hash included -- and the composition being asserted stays honest.
    """
    capture_path = Path(capture_path)
    meta = {
        "argv": ["curl", "-sS", "-i", "http://localhost:5142/api/contacts"],
        "cwd": str(capture_path.parent),
        "host": "eval-fixture",
        "pid": 0,
        "started": CAPTURE_STARTED,
        "finished": CAPTURE_FINISHED,
        "exit_code": int(exit_code),
        "body_sha256": hashlib.sha256(b"").hexdigest(),
        "capture_sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
        "tool": "run_quiet.py",
        "schema": 1,
    }
    side = capture_path.with_name(capture_path.name + ".meta.json")
    side.write_text(json.dumps(meta, indent=2) + chr(10), encoding="utf-8")
    return side


results = []


def record(name, ok, detail=""):
    results.append((name, ok))
    status = "PASS" if ok else "FAIL"
    line = f"[{status}] {name}"
    if detail:
        line += f"\n         {detail}"
    print(line)


def run_py(script, args):
    proc = subprocess.run([sys.executable, str(script)] + [str(a) for a in args],
                           capture_output=True, text=True)
    return proc


def run_git(args, repo):
    proc = subprocess.run(["git"] + args, cwd=str(repo), capture_output=True, text=True)
    return proc


def parse_json(proc, step_name):
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        record(step_name, False,
               f"could not parse JSON stdout: {exc}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}")
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true",
                        help="append one flat record to evals/results/results.jsonl")
    args = parser.parse_args()

    started = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="eval-mechanical-pipeline-"))
    try:
        run_lifecycle(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    duration = round(time.time() - started, 2)

    print()
    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"RESULT: FAIL ({len(failed)}/{len(results)} steps failed)")
    else:
        print(f"RESULT: PASS ({len(results)}/{len(results)} steps passed)")

    if args.record:
        detail = None
        if failed:
            detail = " | ".join(f"[FAIL] {name}" for name in failed)
        append_script_record(case="mechanical-pipeline", passed=(not failed),
                             failed_criterion=detail, duration_s=duration)

    if failed:
        return 1
    return 0


def run_lifecycle(repo):
    # --- Setup: disposable git repo + fixtures -----------------------------
    init = run_git(["init", "-q"], repo)
    run_git(["config", "user.email", "eval@test"], repo)
    run_git(["config", "user.name", "eval"], repo)
    if init.returncode != 0:
        record("0. setup: git init", False, init.stderr)
        return
    record("0. setup: git init + user config", True)

    docs_dir = repo / ".docs" / "proj"
    impl_dir = docs_dir / "implementation"
    impl_dir.mkdir(parents=True, exist_ok=True)

    plan_path = impl_dir / "plan.md"
    plan_path.write_text(PLAN_TEMPLATE, encoding="utf-8")

    state_path = docs_dir / "orchestrator-state.json"
    state_path.write_text(json.dumps({
        "schema": "1",
        "project_name": "proj",
        "feature": None,
        "pipeline": "",
        "branch": None,
        "milestone_cursor": MILESTONE3_TITLE,
        "artifacts": {},
        "blockers": [],
    }, indent=2), encoding="utf-8")

    review_path = impl_dir / "review-report.md"

    # KNOWN TOOL DEFECT WORKAROUND (documented, not patched -- see README.md
    # "Tool defect found"): `git status --porcelain` in its default mode
    # collapses a directory that has NEVER been tracked before into a single
    # "?? <dir>/" line instead of listing the files inside it.
    # check_commit_gate.py's normalize_repo_path() strips that trailing
    # slash, so (a) the ".docs/" carve-out no longer matches (".docs" does
    # not start with ".docs/") and (b) a declared file's own directory, if
    # untracked, is reported as the whole dir rather than the file, so it
    # never matches the declared set either -- both make --verify-tree
    # misreport legitimate changes as undeclared the FIRST time a directory
    # appears. Real bgpdd-build runs build on an already-established repo
    # (per bgpdd-build/SKILL.md's Git Workflow), so .docs/ and src/ are
    # already tracked by the time a milestone gate runs --verify-tree; we
    # reproduce that precondition here with a scaffold commit so steps 6-7
    # exercise the tool's intended per-file declared/undeclared logic
    # instead of this orthogonal git-porcelain collapsing behavior.
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "src" / ".gitkeep").write_text("", encoding="utf-8")
    run_git(["add", "-A"], repo)
    scaffold_commit = run_git(["commit", "-m", "scaffold: initial project structure"], repo)
    record("0b. setup: scaffold commit (.docs/ + src/ tracked before verify-tree steps)",
           scaffold_commit.returncode == 0, "" if scaffold_commit.returncode == 0 else scaffold_commit.stderr)

    # --- Step 1: next_milestone.py derives milestone 2, cursor is stale ----
    proc = run_py(NEXT_MILESTONE, ["--plan", plan_path, "--state", state_path])
    data = parse_json(proc, "1. next_milestone: NEXT / milestone 2 / API / cursor stale")
    if data is not None:
        ok = (proc.returncode == 0 and data.get("result") == "NEXT"
              and data.get("next_milestone", {}).get("title") == MILESTONE2_HEADING
              and data.get("next_milestone", {}).get("domain") == "API"
              and data.get("next_milestone", {}).get("surface") == "api"
              and data.get("cursor", {}).get("stale") is True)
        record("1. next_milestone: NEXT / milestone 2 / API / cursor stale", ok,
               "" if ok else json.dumps(data))

    # --- Step 2: update_state.py sets cursor + pipeline ---------------------
    proc = run_py(UPDATE_STATE, ["--state", state_path,
                                  "--set-cursor", MILESTONE2_TITLE,
                                  "--set-pipeline", "bgpdd-build"])
    record("2. update_state: --set-cursor milestone2 --set-pipeline bgpdd-build",
           proc.returncode == 0, "" if proc.returncode == 0 else proc.stderr)

    # --- Step 3: builder diff + Request Changes review -> gate fails -------
    api_cs = repo / "src" / "api.cs"
    api_cs.parent.mkdir(parents=True, exist_ok=True)
    api_cs.write_text("// builder diff placeholder for milestone 2\n", encoding="utf-8")
    set_mtime(api_cs)

    review_path.write_text(
        f"## Review: {MILESTONE2_TITLE}\n\n"
        "Validation is missing on the create endpoint.\n\n"
        "**Verdict:** Request Changes\n",
        encoding="utf-8")
    set_mtime(review_path)

    gate_common = ["--review-report", review_path, "--state", state_path,
                   "--milestone", MILESTONE2_TITLE, "--changed-files", api_cs,
                   "--repo", repo]

    proc = run_py(CHECK_COMMIT_GATE, gate_common)
    data = parse_json(proc, "3. check_commit_gate: Request Changes -> exit 1")
    if data is not None:
        ok = proc.returncode == 1 and data.get("verdict") == "Request Changes"
        record("3. check_commit_gate: Request Changes -> exit 1", ok,
               "" if ok else json.dumps(data))

    # --- Step 4: blocker added, review flips to Approve, blocker still gates
    # Scoped via --blocker-milestone so it lands in check_commit_gate's
    # `blocking` (structured milestone-field match), not `unscoped_blockers`
    # -- the blockers-ledger schema moved scoping from a substring guess
    # against freeform text to an explicit field (see update_state.py /
    # check_commit_gate.py blocker-schema work).
    blocker_text = "validation finding open"
    proc = run_py(UPDATE_STATE, ["--state", state_path, "--add-blocker", blocker_text,
                                  "--blocker-milestone", MILESTONE2_TITLE])
    add_blocker_ok = proc.returncode == 0

    with review_path.open("a", encoding="utf-8") as f:
        f.write(f"\n## Review: {MILESTONE2_TITLE}\n\n"
                "Re-reviewed after the validation fix.\n\n"
                "**Verdict:** Approve\n")
    set_mtime(review_path)

    proc = run_py(CHECK_COMMIT_GATE, gate_common)
    data = parse_json(proc, "4. check_commit_gate: blocker stands -> exit 1")
    if data is not None:
        ok = (add_blocker_ok and proc.returncode == 1
              and data.get("verdict") == "Approve"
              and len(data.get("blocking", [])) >= 1)
        record("4. check_commit_gate: blocker stands -> exit 1", ok,
               "" if ok else json.dumps(data))

    # --- Step 5: resolve-blocker requires --evidence ------------------------
    proc_no_ev = run_py(UPDATE_STATE, ["--state", state_path,
                                        "--resolve-blocker", "validation finding"])
    proc_ev = run_py(UPDATE_STATE, ["--state", state_path,
                                     "--resolve-blocker", "validation finding",
                                     "--evidence", "re-test passed, re-review Approve"])
    log_path = state_path.parent / "blockers-resolved.log"
    ok = proc_no_ev.returncode == 2 and proc_ev.returncode == 0 and log_path.exists()
    record("5. update_state: --resolve-blocker without/with --evidence (exit 2 / exit 0, log written)",
           ok, "" if ok else
           f"no-evidence rc={proc_no_ev.returncode}, with-evidence rc={proc_ev.returncode}, "
           f"log exists={log_path.exists()}")

    # --- Step 6: --verify-tree catches an undeclared file -------------------
    rogue = repo / "src" / "rogue.cs"
    rogue.write_text("// undeclared file, not part of the milestone 2 diff\n", encoding="utf-8")

    proc = run_py(CHECK_COMMIT_GATE, gate_common + ["--verify-tree"])
    data = parse_json(proc, "6. check_commit_gate --verify-tree: undeclared rogue.cs -> exit 1")
    if data is not None:
        undeclared = data.get("undeclared_changes", [])
        ok = proc.returncode == 1 and undeclared == ["src/rogue.cs"]
        record("6. check_commit_gate --verify-tree: undeclared rogue.cs -> exit 1", ok,
               "" if ok else json.dumps(data))
    rogue.unlink()

    # --- Step 7: clean tree, --verify-tree --commit succeeds and commits ---
    proc = run_py(CHECK_COMMIT_GATE, gate_common + [
        "--verify-tree", "--commit", "--message", "M2: api (FR-1)"])
    data = parse_json(proc, "7. check_commit_gate --verify-tree --commit: exit 0, committed")
    if data is not None:
        log = run_git(["log", "--oneline"], repo).stdout
        ok = (proc.returncode == 0 and data.get("committed") is True
              and "M2: api (FR-1)" in log)
        record("7. check_commit_gate --verify-tree --commit: exit 0, committed", ok,
               "" if ok else f"data={json.dumps(data)} git_log={log!r}")

    # --- Step 8a: mark milestone 2 complete, next_milestone advances to M3 -
    plan_text = plan_path.read_text(encoding="utf-8")
    # Append [x] to the FULL heading (tags included) -- completion is recorded on
    # the heading line, which now carries both the domain and [vs:] tags.
    marked = plan_text.replace(f"## {MILESTONE2_HEADING}\n",
                                f"## {MILESTONE2_HEADING} [x]\n")
    ok_marked = marked != plan_text
    plan_path.write_text(marked, encoding="utf-8")

    proc = run_py(NEXT_MILESTONE, ["--plan", plan_path, "--state", state_path])
    data = parse_json(proc, "8a. next_milestone: advances to milestone 3 / UI")
    if data is not None:
        ok = (ok_marked and proc.returncode == 0 and data.get("result") == "NEXT"
              and data.get("next_milestone", {}).get("title") == MILESTONE3_HEADING
              and data.get("next_milestone", {}).get("domain") == "UI"
              and data.get("next_milestone", {}).get("surface") == "ui")
        record("8a. next_milestone: advances to milestone 3 / UI", ok,
               "" if ok else json.dumps(data))

    # --- Step 8b: --require-rendered-evidence fails with no evidence cited -
    ui_tsx = repo / "src" / "ui.tsx"
    ui_tsx.write_text("// milestone 3 UI diff placeholder\n", encoding="utf-8")
    set_mtime(ui_tsx)

    with review_path.open("a", encoding="utf-8") as f:
        f.write(f"\n## Review: {MILESTONE3_TITLE}\n\nLooks good.\n\n**Verdict:** Approve\n")
    set_mtime(review_path)

    gate_m3 = ["--review-report", review_path, "--state", state_path,
               "--milestone", MILESTONE3_TITLE, "--changed-files", ui_tsx,
               "--repo", repo, "--require-rendered-evidence"]

    proc = run_py(CHECK_COMMIT_GATE, gate_m3)
    data = parse_json(proc, "8b. check_commit_gate --require-rendered-evidence: no evidence -> exit 1")
    if data is not None:
        ok = proc.returncode == 1 and data.get("rendered_evidence_ok") is False
        record("8b. check_commit_gate --require-rendered-evidence: no evidence -> exit 1", ok,
               "" if ok else json.dumps(data))

    # --- Step 8c: add rendered-evidence line + file, refresh mtime -> pass -
    # Path is under evidence/review/ -- reviewer-produced evidence, per the
    # provenance rule (evidence/build/ or any other path would not satisfy
    # --require-rendered-evidence even if the file exists on disk).
    evidence_file = repo / "evidence" / "review" / "m3.png"
    evidence_file.parent.mkdir(parents=True, exist_ok=True)
    evidence_file.write_bytes(PNG_1PX)
    set_mtime(evidence_file)  # must be no older than the newest changed file

    with review_path.open("a", encoding="utf-8") as f:
        f.write("\nRendered evidence: evidence\\review\\m3.png\n")
    set_mtime(review_path)  # refresh so staleness still passes vs ui_tsx

    proc = run_py(CHECK_COMMIT_GATE, gate_m3)
    data = parse_json(proc, "8c. check_commit_gate --require-rendered-evidence: evidence cited -> exit 0")
    if data is not None:
        ok = (proc.returncode == 0 and data.get("result") == "PASS"
              and data.get("rendered_evidence_ok") is True)
        record("8c. check_commit_gate --require-rendered-evidence: evidence cited -> exit 0", ok,
               "" if ok else json.dumps(data))

    # --- Step 9: run_quiet.py surfaces the error, keeps stdout short, -------
    #             full log holds everything.
    build_log = repo / "build.log"
    noise_script = (
        "for i in range(80):\n"
        "    print('noise line %d' % i)\n"
        "print('error CS1002: ; expected')\n"
        "import sys\n"
        "sys.exit(1)\n"
    )
    proc = subprocess.run(
        [sys.executable, str(RUN_QUIET), "--log", str(build_log), "--",
         sys.executable, "-c", noise_script],
        capture_output=True, text=True)
    stdout_lines = proc.stdout.splitlines()
    log_lines = build_log.read_text(encoding="utf-8").splitlines() if build_log.exists() else []
    ok = (proc.returncode == 1
          and "error CS1002" in proc.stdout
          and len(stdout_lines) <= 40
          and len(log_lines) == 81)
    record("9. run_quiet: exit 1, error surfaced, stdout <=40 lines, log holds all 81", ok,
           "" if ok else
           f"rc={proc.returncode}, stdout_lines={len(stdout_lines)}, log_lines={len(log_lines)}, "
           f"error_in_stdout={'error CS1002' in proc.stdout}")

    # --- Step 10a: check_runtime_evidence accepts an honest capture ----------
    # Scoped to milestone 2 ([vs:api]) because an envelope is a response claim.
    # The capture's mtime comes from the synthetic clock AFTER api_cs's (step 3),
    # so the freshness check resolves deterministically instead of racing
    # real-clock resolution -- the same reason every other mtime here is faked.
    runtime_dir = impl_dir / "evidence" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    good_capture = runtime_dir / "m2-contacts-get.md"
    good_capture.write_text(
        CAPTURE_TEMPLATE.format(milestone=MILESTONE2_HEADING, body=ENVELOPE_BODY,
                                captured=CAPTURED_STAMP),
        encoding="utf-8")
    set_mtime(good_capture)
    set_mtime(write_sidecar(good_capture))

    good_report = impl_dir / "test-report.md"
    good_report.write_text(
        RUNTIME_REPORT_TEMPLATE.format(capture="evidence/runtime/m2-contacts-get.md"),
        encoding="utf-8")

    evidence_common = ["--milestone", MILESTONE2_TITLE, "--repo", repo,
                       "--changed-files", api_cs,
                       "--require-key", "isSuccess", "--require-key", "notifications",
                       "--expect-status", 200]

    proc = run_py(CHECK_RUNTIME_EVIDENCE, ["--report", good_report] + evidence_common)
    data = parse_json(proc, "10a. check_runtime_evidence: honest out-of-process capture -> exit 0")
    if data is not None:
        captures = data.get("captures", [])
        ok = (proc.returncode == 0 and data.get("result") == "PASS"
              and data.get("accepted") == ["evidence/runtime/m2-contacts-get.md"]
              and data.get("missing_keys") == []
              and len(captures) == 1
              and captures[0].get("fresh") is True
              and captures[0].get("status") == 200)
        record("10a. check_runtime_evidence: honest out-of-process capture -> exit 0", ok,
               "" if ok else json.dumps(data))

    # --- Step 10b: same capture minus the envelope -> exit 1 -----------------
    # The 2026-08 incident, mechanically: everything honest except the body.
    bare_capture = runtime_dir / "m2-contacts-get-bare.md"
    bare_capture.write_text(
        CAPTURE_TEMPLATE.format(milestone=MILESTONE2_HEADING, body=BARE_BODY,
                                captured=CAPTURED_STAMP),
        encoding="utf-8")
    set_mtime(bare_capture)
    set_mtime(write_sidecar(bare_capture))

    bare_report = impl_dir / "test-report-bare.md"
    bare_report.write_text(
        RUNTIME_REPORT_TEMPLATE.format(capture="evidence/runtime/m2-contacts-get-bare.md"),
        encoding="utf-8")

    proc = run_py(CHECK_RUNTIME_EVIDENCE, ["--report", bare_report] + evidence_common)
    data = parse_json(proc, "10b. check_runtime_evidence: envelope keys absent -> exit 1")
    if data is not None:
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and data.get("missing_keys") == ["isSuccess", "notifications"]
              and data.get("accepted") == []
              and data.get("rejected") == ["evidence/runtime/m2-contacts-get-bare.md"]
              and data.get("in_process_transport") == []
              and data.get("stale") == [])
        record("10b. check_runtime_evidence: envelope keys absent -> exit 1", ok,
               "" if ok else json.dumps(data))

    # --- Step 10c: ONLY the sidecar is edited -> sidecar_body_disagrees ------
    # The forgery the `capture_sha256` term alone cannot see. The hash protects
    # the capture FILE; nothing protects the sidecar. So: take an honest capture
    # of a probe that FAILED (its body records `- Exit code: 3`), then edit the
    # sidecar's `exit_code` to 0. Every older term stays green -- the file exists,
    # is under evidence/runtime/, is fresh, hashes to the sidecar, and the sidecar
    # now claims a clean exit. Only the capture's own hash-protected header
    # contradicts it, which is what this term reads.
    forged_capture = runtime_dir / "m2-contacts-get-forged.md"
    forged_capture.write_text(
        CAPTURE_TEMPLATE.format(milestone=MILESTONE2_HEADING, body=ENVELOPE_BODY,
                                captured=CAPTURED_STAMP)
        .replace("- Exit code: 0", "- Exit code: 3"),
        encoding="utf-8")
    set_mtime(forged_capture)
    # exit_code=0 over a body that says 3. The hash is computed AFTER the body is
    # written, so it still matches: the capture was never touched.
    set_mtime(write_sidecar(forged_capture, exit_code=0))

    forged_report = impl_dir / "test-report-forged.md"
    forged_report.write_text(
        RUNTIME_REPORT_TEMPLATE.format(
            capture="evidence/runtime/m2-contacts-get-forged.md"),
        encoding="utf-8")

    proc = run_py(CHECK_RUNTIME_EVIDENCE, ["--report", forged_report] + evidence_common)
    data = parse_json(proc, "10c. check_runtime_evidence: sidecar exit_code edited to 0 -> exit 1")
    if data is not None:
        captures = data.get("captures", [])
        codes = []
        if captures:
            codes = list(captures[0].get("problem_codes") or [])
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and data.get("sidecar_body_disagrees")
                  == ["evidence/runtime/m2-contacts-get-forged.md"]
              and "sidecar_body_disagrees" in codes
              # The older terms must NOT be what caught it, or this step would
              # pass for a reason that predates the check being asserted.
              and data.get("sidecar_missing") == []
              and data.get("sidecar_hash_mismatch") == []
              and data.get("stale") == [])
        record("10c. check_runtime_evidence: sidecar exit_code edited to 0 -> exit 1", ok,
               "" if ok else json.dumps(data))

    # --- Step 11a: check_acceptance_suite, green walkthrough -> exit 0 -------
    # The manual step cites the capture 10a just accepted: the acceptance gate
    # only proves the file EXISTS under evidence/runtime/, the runtime gate is
    # what proves the observation inside it is honest. Running both is the point.
    matrix_path = docs_dir / "acceptance-matrix.md"
    matrix_path.write_text(ACCEPTANCE_MATRIX, encoding="utf-8")

    green_results = impl_dir / "acceptance-results.md"
    green_results.write_text(ACCEPTANCE_RESULTS_GREEN, encoding="utf-8")

    proc = run_py(CHECK_ACCEPTANCE_SUITE, ["--matrix", matrix_path,
                                           "--results", green_results,
                                           "--repo", repo])
    data = parse_json(proc, "11a. check_acceptance_suite: green walkthrough -> exit 0")
    if data is not None:
        ok = (proc.returncode == 0 and data.get("result") == "PASS"
              and data.get("gated_scenarios") == ["AS-1"]
              and data.get("steps_gated") == 3 and data.get("passed") == 3
              and data.get("unevidenced_manual") == []
              and data.get("dangling_inverse") == []
              and data.get("missing_results") == [])
        record("11a. check_acceptance_suite: green walkthrough -> exit 0", ok,
               "" if ok else json.dumps(data))

    # --- Step 11b: unevidenced manual PASS reads as NOT RUN -> exit 1 -------
    unevidenced_results = impl_dir / "acceptance-results-unevidenced.md"
    unevidenced_results.write_text(ACCEPTANCE_RESULTS_UNEVIDENCED, encoding="utf-8")

    proc = run_py(CHECK_ACCEPTANCE_SUITE, ["--matrix", matrix_path,
                                           "--results", unevidenced_results,
                                           "--repo", repo])
    data = parse_json(proc, "11b. check_acceptance_suite: unevidenced manual PASS -> exit 1")
    if data is not None:
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and data.get("unevidenced_manual") == ["AS-1.3"]
              and "AS-1.3" in data.get("not_run", [])
              and data.get("failed") == []
              and data.get("missing_results") == [])
        record("11b. check_acceptance_suite: unevidenced manual PASS -> exit 1", ok,
               "" if ok else json.dumps(data))

    # --- Step 12: check_agent_report's capture term -------------------------
    # The gate that used to read NOTHING unforgeable. Every term it checked was
    # text an agent types, so a wholly invented security report whose check lines
    # carried plausible exit codes passed. 12a is that report; 12b is the same
    # report with the same two checks actually run through run_quiet.py --capture,
    # so the step proves the term fires on a typed report AND clears on an
    # executed one -- a gate proven only against failure is a gate that fails
    # closed on everything.
    security_dir = impl_dir / "evidence" / "security"
    security_dir.mkdir(parents=True, exist_ok=True)

    TYPED_REPORT = (
        "# Security Report\n\n"
        "## Security Audit: proj — 2026-08-12\n\n"
        "- Dependency audit: PASS — `npm audit --audit-level=high` — exit 0 — 0 high, 0 critical\n"
        "- Secrets scan: PASS — `git grep -nE \"(api_key|secret)\"` — exit 1 — 0 matches\n\n"
        "**Verdict:** Pass\n")
    typed_report_path = impl_dir / "security-report-typed.md"
    typed_report_path.write_text(TYPED_REPORT, encoding="utf-8")

    proc = run_py(CHECK_AGENT_REPORT, ["--report", typed_report_path,
                                       "--milestone", MILESTONE2_TITLE,
                                       "--repo", repo])
    data = parse_json(proc, "12a. check_agent_report: a wholly TYPED report -> exit 1 (check_uncaptured)")
    if data is not None:
        problems = [p.get("problem") for p in (data.get("capture_problems") or [])]
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              # The verdict token and the exit codes are all correct: the report
              # is refused for citing nothing, not for a grammar slip.
              and data.get("verdict") == "Pass"
              and data.get("unevidenced") == []
              and sorted(data.get("uncaptured") or [])
                  == ["Dependency audit", "Secrets scan"]
              and set(problems) == {"check_uncaptured"})
        record("12a. check_agent_report: a wholly TYPED report -> exit 1 (check_uncaptured)", ok,
               "" if ok else json.dumps(data))

    # 12b: the SAME two checks, actually executed through run_quiet.py --capture,
    # each line citing its own artifact, claiming the exit code the sidecar
    # recorded AND naming the command the sidecar recorded. The `exit 1` line is
    # deliberate: a clean `git grep` for secrets exits 1 (no matches), so the
    # gate must tie a line to its capture by exit-code EQUALITY rather than by
    # "was it zero" -- and, since 2.6.1, by the command as well.
    #
    # The lines name the real argv (shlex-joined) rather than a plausible
    # `npm audit` string. That is the point of `capture_command_mismatch`: a
    # line may only claim the command its capture recorded, and this eval is not
    # allowed to model a report that lies about it.
    audit_capture = security_dir / "npm-audit.md"
    secrets_capture = security_dir / "secrets-scan.md"
    audit_argv = [sys.executable, "-c", "print('0 high, 0 critical')"]
    secrets_argv = [sys.executable, "-c",
                    "import sys; print('no matches'); sys.exit(1)"]
    run_py(RUN_QUIET, ["--capture", audit_capture, "--"] + audit_argv)
    run_py(RUN_QUIET, ["--capture", secrets_capture, "--"] + secrets_argv)

    EXECUTED_REPORT = (
        "# Security Report\n\n"
        "## Security Audit: proj — 2026-08-12\n\n"
        "- Dependency audit: PASS — `" + shlex.join(audit_argv) + "` — exit 0"
        " — 0 high, 0 critical — capture: evidence/security/npm-audit.md\n"
        "- Secrets scan: PASS — `" + shlex.join(secrets_argv) + "` — exit 1"
        " — 0 matches — capture: evidence/security/secrets-scan.md\n\n"
        "**Verdict:** Pass\n")
    executed_report_path = impl_dir / "security-report-executed.md"
    executed_report_path.write_text(EXECUTED_REPORT, encoding="utf-8")

    proc = run_py(CHECK_AGENT_REPORT, ["--report", executed_report_path,
                                       "--milestone", MILESTONE2_TITLE,
                                       "--repo", repo])
    data = parse_json(proc, "12b. check_agent_report: the same checks, really captured -> exit 0")
    if data is not None:
        ok = (proc.returncode == 0 and data.get("result") == "PASS"
              and data.get("verdict") == "Pass"
              and data.get("uncaptured") == []
              and data.get("capture_disagrees") == []
              and data.get("capture_command_mismatches") == []
              and data.get("capture_problems") == []
              and data.get("allow_uncaptured") is False)
        record("12b. check_agent_report: the same checks, really captured -> exit 0", ok,
               "" if ok else json.dumps(data))

    # 12c (2.6.1): ONE real capture cited by three unrelated check lines, each
    # claiming the exit code that capture recorded. Exit-code equality alone
    # cleared all three -- every clean scan claims 0 or 1 -- and the report
    # passed with verdict Pass. The command tie is what refuses it now, and the
    # first line (which DOES name the captured command) must still clear, so the
    # step proves the term is per-line rather than a blanket refusal.
    REUSED_REPORT = (
        "# Security Report\n\n"
        "## Security Audit: proj — 2026-09-07\n\n"
        "- Secrets scan: PASS — `" + shlex.join(secrets_argv) + "` — exit 1"
        " — 0 matches — capture: evidence/security/secrets-scan.md\n"
        "- Dependency audit: PASS — `npm audit --production` — exit 1"
        " — 0 high — capture: evidence/security/secrets-scan.md\n"
        "- Auth boundary review: PASS — `dotnet test Auth.Tests` — exit 1"
        " — 12 passed — capture: evidence/security/secrets-scan.md\n\n"
        "**Verdict:** Pass\n")
    reused_report_path = impl_dir / "security-report-reused.md"
    reused_report_path.write_text(REUSED_REPORT, encoding="utf-8")

    proc = run_py(CHECK_AGENT_REPORT, ["--report", reused_report_path,
                                       "--milestone", MILESTONE2_TITLE,
                                       "--repo", repo])
    data = parse_json(
        proc,
        "12c. check_agent_report: ONE capture cited by three unrelated lines "
        "-> exit 1 (capture_command_mismatch)")
    if data is not None:
        problems = [p.get("problem") for p in (data.get("capture_problems") or [])]
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and data.get("verdict") == "Pass"
              and data.get("uncaptured") == []
              and data.get("capture_disagrees") == []
              and sorted(data.get("capture_command_mismatches") or [])
                  == ["Auth boundary review", "Dependency audit"]
              and set(problems) == {"capture_command_mismatch"})
        record("12c. check_agent_report: ONE capture cited by three unrelated "
               "lines -> exit 1 (capture_command_mismatch)", ok,
               "" if ok else json.dumps(data))

    # 12d (2.6.1): --allow-uncaptured waives the CITATION, never the command
    # tie. A flag for grading a pre-contract archive must not become a way to
    # cite somebody else's capture.
    proc = run_py(CHECK_AGENT_REPORT, ["--report", reused_report_path,
                                       "--milestone", MILESTONE2_TITLE,
                                       "--repo", repo, "--allow-uncaptured"])
    data = parse_json(
        proc,
        "12d. check_agent_report: --allow-uncaptured does not waive the "
        "command tie -> exit 1")
    if data is not None:
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and data.get("allow_uncaptured") is True
              and sorted(data.get("capture_command_mismatches") or [])
                  == ["Auth boundary review", "Dependency audit"])
        record("12d. check_agent_report: --allow-uncaptured does not waive the "
               "command tie -> exit 1", ok, "" if ok else json.dumps(data))

    # --- Steps 13-16: the H3 interface gates, composed against this repo ----
    # Each ships its own --self-test against synthetic fixtures. What is new
    # here is the composition: the same real git repo the milestone lifecycle
    # above built, the same on-disk artifacts, and the exit code AND naming
    # JSON field asserted on both an honest and a fabricated input.

    # 13: check_handoff.py against a real diff. `src/pristine.py` is committed
    # FIRST and never touched again, so it exists on disk while being provably
    # outside the `--since head` window; `src/contacts.py` is written after,
    # so the window is non-empty and precisely known.
    pristine = repo / "src" / "pristine.py"
    pristine.parent.mkdir(parents=True, exist_ok=True)
    pristine.write_text("# committed, then never touched\n", encoding="utf-8")
    run_git(["add", "src/pristine.py"], repo)
    run_git(["commit", "-qm", "handoff-step baseline"], repo)
    head = run_git(["rev-parse", "HEAD"], repo).stdout.strip()
    touched = repo / "src" / "contacts.py"
    touched.write_text("# added after HEAD\n", encoding="utf-8")

    handoff_dir = impl_dir / "handoffs"
    handoff_dir.mkdir(parents=True, exist_ok=True)

    honest_handoff = handoff_dir / "mason-m2.md"
    honest_handoff.write_text(
        "<handoff><status>COMPLETE</status>"
        "<changed_files>src/contacts.py</changed_files>"
        "<blockers>None</blockers></handoff>\n", encoding="utf-8")
    proc = run_py(CHECK_HANDOFF, ["--handoff", honest_handoff, "--persona", "mason",
                                  "--repo", repo, "--since", head])
    data = parse_json(proc, "13a. check_handoff: builder handoff matching the real diff -> exit 0")
    if data is not None:
        ok = (proc.returncode == 0 and data.get("result") == "PASS"
              and data.get("findings") == []
              and data.get("changed_files") == ["src/contacts.py"])
        record("13a. check_handoff: builder handoff matching the real diff -> exit 0", ok,
               "" if ok else json.dumps(data))

    # 13b: the same handoff, plus a path that exists on disk but that git does
    # NOT report as changed since `head`. Existence alone must not satisfy the
    # subset check -- that is the whole difference between "a file is there"
    # and "this agent changed it".
    inflated = handoff_dir / "mason-m2-inflated.md"
    inflated.write_text(
        "<handoff><status>COMPLETE</status>"
        "<changed_files>src/contacts.py, src/pristine.py"
        "</changed_files><blockers>None</blockers></handoff>\n", encoding="utf-8")
    proc = run_py(CHECK_HANDOFF, ["--handoff", inflated, "--persona", "mason",
                                  "--repo", repo, "--since", head])
    data = parse_json(proc, "13b. check_handoff: a changed_files entry git never saw -> exit 1")
    if data is not None:
        codes = sorted({f.get("code") for f in (data.get("findings") or [])})
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and codes == ["changed_files_not_in_diff"])
        record("13b. check_handoff: a changed_files entry git never saw -> exit 1", ok,
               "" if ok else json.dumps(data))

    # 13c: a handoff that exists ONLY inside a fence. The adversarial case the
    # gate was written for: a template shown in prose reads as a report.
    fenced = handoff_dir / "mason-fenced.md"
    fenced.write_text(
        "I will report like this when I am done:\n\n```\n"
        "<handoff><status>COMPLETE</status>"
        "<changed_files>src/contacts.py</changed_files>"
        "<blockers>None</blockers></handoff>\n```\n", encoding="utf-8")
    proc = run_py(CHECK_HANDOFF, ["--handoff", fenced, "--persona", "mason",
                                  "--repo", repo])
    data = parse_json(proc, "13c. check_handoff: a fenced template is not a handoff -> exit 1")
    if data is not None:
        codes = sorted({f.get("code") for f in (data.get("findings") or [])})
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and codes == ["handoff_missing"])
        record("13c. check_handoff: a fenced template is not a handoff -> exit 1", ok,
               "" if ok else json.dumps(data))

    # 14: check_always_on.py against the REAL plugin tree, not a fixture --
    # the shipped index has to be true of the shipped lanes.
    proc = run_py(CHECK_ALWAYS_ON, [])
    data = parse_json(proc, "14. check_always_on: the shipped index matches the shipped lanes -> exit 0")
    if data is not None:
        ok = (proc.returncode == 0 and data.get("result") == "PASS"
              and data.get("findings") == []
              and sorted(data.get("lanes_in_table") or [])
                  == sorted(data.get("lanes_on_disk") or []))
        record("14. check_always_on: the shipped index matches the shipped lanes -> exit 0", ok,
               "" if ok else json.dumps(data))

    # 15: check_tier1_provenance.py against a Tier-1 tree in this same repo,
    # stamped with a sha this repo really contains -- and then with one it
    # does not, which is the fabricated-stamp case.
    summary = repo / ".docs" / "summary"
    (summary / "contacts").mkdir(parents=True, exist_ok=True)
    stamp = f"# Context\n\n> Provenance — 2026-08-12\n> `{head}`\n\n## Stacks (detected)\n\nnone\n"
    (summary / "context.md").write_text(stamp, encoding="utf-8")
    (summary / "contacts" / "overview.md").write_text(
        f"# Contacts — overview\n\n> Provenance — 2026-08-12\n> `{head}`\n\n"
        "## Owning services\n\napi\n", encoding="utf-8")
    proc = run_py(CHECK_TIER1_PROVENANCE, ["--summary-root", summary,
                                           "--feature", "contacts",
                                           "--repo", f"proj={repo}"])
    data = parse_json(proc, "15a. check_tier1_provenance: both artifacts stamped with a real sha -> exit 0")
    if data is not None:
        ok = (proc.returncode == 0 and data.get("result") == "PASS"
              and data.get("findings") == [] and data.get("drift") == [])
        record("15a. check_tier1_provenance: both artifacts stamped with a real sha -> exit 0", ok,
               "" if ok else json.dumps(data))

    (summary / "contacts" / "overview.md").write_text(
        "# Contacts — overview\n\n> Provenance — 2026-08-12\n> `"
        + "0" * 40 + "`\n\n## Owning services\n\napi\n", encoding="utf-8")
    proc = run_py(CHECK_TIER1_PROVENANCE, ["--summary-root", summary,
                                           "--feature", "contacts",
                                           "--repo", f"proj={repo}"])
    data = parse_json(proc, "15b. check_tier1_provenance: a sha this repo never had -> exit 1")
    if data is not None:
        codes = sorted({f.get("code") for f in (data.get("findings") or [])})
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and codes == ["sha_unknown"])
        record("15b. check_tier1_provenance: a sha this repo never had -> exit 1", ok,
               "" if ok else json.dumps(data))

    # 16: check_runtime_recipe.py -- a filled manifest, then the same file with
    # its only start command and readiness check replaced by placeholders. The
    # blocks are identical in both; only the facts differ.
    qa_dir = summary / "contacts" / "QA"
    qa_dir.mkdir(parents=True, exist_ok=True)
    recipe = qa_dir / "runtime-environment.md"
    FILLED_RECIPE = (
        "# Runtime Environment — contacts\n\n"
        "## Bring-up sequence\n\n1. Start the API. Needed for: api.\n\n"
        "## Services\n\n"
        "| Service | Start command | Local base URL | Readiness check |\n"
        "|---|---|---|---|\n"
        "| api | `dotnet run --project src/Api` | http://localhost:5142 | "
        "`curl -sS http://localhost:5142/health` |\n\n"
        "## Repointing map\n\n| Key | Service | Ships as | Local |\n|---|---|---|---|\n"
        "| Api:BaseUrl | web | https://dev.example | http://localhost:5142 |\n\n"
        "## Forbidden hosts\n\n- `dev.example`\n\n"
        "## Test identities & fixtures\n\n- login `qa@example.test`, password from the vault\n\n"
        "## Capabilities\n\n- out-of-process HTTP client\n")
    recipe.write_text(FILLED_RECIPE, encoding="utf-8")
    proc = run_py(CHECK_RUNTIME_RECIPE, ["--recipe", recipe])
    data = parse_json(proc, "16a. check_runtime_recipe: a filled manifest -> exit 0")
    if data is not None:
        ok = (proc.returncode == 0 and data.get("result") == "PASS"
              and data.get("blocks_missing") == []
              and len(data.get("start_commands") or []) == 1
              and len(data.get("readiness_checks") or []) == 1)
        record("16a. check_runtime_recipe: a filled manifest -> exit 0", ok,
               "" if ok else json.dumps(data))

    hollow = FILLED_RECIPE.replace("`dotnet run --project src/Api`", "TBD")
    hollow = hollow.replace("`curl -sS http://localhost:5142/health`", "TODO")
    recipe.write_text(hollow, encoding="utf-8")
    proc = run_py(CHECK_RUNTIME_RECIPE, ["--recipe", recipe])
    data = parse_json(proc, "16b. check_runtime_recipe: every block present, both facts TBD -> exit 1")
    if data is not None:
        codes = sorted({f.get("code") for f in (data.get("findings") or [])})
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and data.get("blocks_missing") == []
              and codes == ["readiness_check_missing", "start_command_missing"])
        record("16b. check_runtime_recipe: every block present, both facts TBD -> exit 1", ok,
               "" if ok else json.dumps(data))

    # --- Step 17 (2.6.1): check_handoff --advisory --------------------------
    # bgpdd-learn's Forge propose handoff and bgpdd-build's Aria Mode 2 advisory
    # both return a RECOMMENDATION and no artifact, and both failed this gate
    # exit 1 -- so the Orchestrator's mandatory validation was contradicted by
    # the pipelines twice per epic. The pair below is the point: the SAME
    # handoff, refused without the flag and accepted with it, and the flag
    # recorded in the chained ledger line so the waiver is attributable.
    advisory_handoff = handoff_dir / "forge-propose.md"
    advisory_handoff.write_text(
        "<handoff><status>COMPLETE</status>"
        "<blockers>None</blockers></handoff>\n", encoding="utf-8")
    proc = run_py(CHECK_HANDOFF, ["--handoff", advisory_handoff,
                                  "--persona", "forge", "--repo", repo])
    data = parse_json(proc, "17a. check_handoff: Forge's propose handoff without --advisory -> exit 1")
    if data is not None:
        elements = [f.get("element") for f in (data.get("findings") or [])]
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and elements == ["changed_skills"])
        record("17a. check_handoff: Forge's propose handoff without --advisory -> exit 1",
               ok, "" if ok else json.dumps(data))

    handoff_ledger = impl_dir / "handoff-gates.jsonl"
    proc = run_py(CHECK_HANDOFF, ["--handoff", advisory_handoff,
                                  "--persona", "forge", "--repo", repo,
                                  "--advisory", "--ledger", handoff_ledger])
    data = parse_json(proc, "17b. check_handoff --advisory: the same handoff -> exit 0, advisory recorded")
    if data is not None:
        records = [json.loads(l) for l in
                   handoff_ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
        ok = (proc.returncode == 0 and data.get("result") == "PASS"
              and data.get("advisory") is True
              and data.get("advisory_waived_elements") == ["changed_skills"]
              and bool(records) and records[-1].get("advisory") is True
              and records[-1].get("verdict") == "PASS")
        record("17b. check_handoff --advisory: the same handoff -> exit 0, advisory recorded",
               ok, "" if ok else json.dumps(data))

    # 17c: the flag waives the ARTIFACT and nothing else. A builder handoff with
    # no <changed_files> is still refused with --advisory, because an agent that
    # wrote code has an artifact whether or not the brief asked for one.
    proc = run_py(CHECK_HANDOFF, ["--handoff", advisory_handoff,
                                  "--persona", "mason", "--repo", repo,
                                  "--advisory"])
    data = parse_json(proc, "17c. check_handoff --advisory does not waive <changed_files> -> exit 1")
    if data is not None:
        elements = [f.get("element") for f in (data.get("findings") or [])]
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and elements == ["changed_files"])
        record("17c. check_handoff --advisory does not waive <changed_files> -> exit 1",
               ok, "" if ok else json.dumps(data))

    # --- Step 18 (2.6.1): mark_milestone --reopen ---------------------------
    # Completion was a one-way door: a shipping finding against a milestone
    # whose [x] was written had nowhere to go. This runs the real round trip on
    # the plan this suite has been building -- reopen M2, then read it back out
    # of the real next_milestone.py.
    finding = impl_dir / "shipping-finding.md"
    finding.write_text("p95 regressed 40% under the canary\n", encoding="utf-8")
    reopen_ledger = impl_dir / "reopen-gates.jsonl"
    proc = run_py(MARK_MILESTONE, ["--plan", plan_path, "--reopen",
                                   MILESTONE2_HEADING, "--evidence", finding,
                                   "--reason", "shipping found a p95 regression",
                                   "--ledger", reopen_ledger])
    data = parse_json(proc, "18a. mark_milestone --reopen: removes the [x] -> exit 0")
    if data is not None:
        text = plan_path.read_text(encoding="utf-8")
        records = [json.loads(l) for l in
                   reopen_ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
        ok = (proc.returncode == 0 and data.get("result") == "PASS"
              and data.get("reopened") is True
              and f"## {MILESTONE2_HEADING}\n" in text
              and f"{MILESTONE2_HEADING} [x]" not in text
              and "[ ]" not in text
              and bool(records) and records[-1].get("action") == "reopen"
              and records[-1].get("reason") == "shipping found a p95 regression")
        record("18a. mark_milestone --reopen: removes the [x] -> exit 0", ok,
               "" if ok else json.dumps(data))

    proc = run_py(NEXT_MILESTONE, ["--plan", plan_path, "--state", state_path])
    data = parse_json(proc, "18b. next_milestone returns the reopened milestone as NEXT")
    if data is not None:
        ok = (proc.returncode == 0 and data.get("result") == "NEXT"
              and data.get("next_milestone", {}).get("title") == MILESTONE2_HEADING)
        record("18b. next_milestone returns the reopened milestone as NEXT", ok,
               "" if ok else json.dumps(data))

    # 18c: the three mandatory flags. A reopen is the one write here that
    # destroys a recorded verdict, so an unevidenced, unreasoned or unrecorded
    # one is a usage error and the plan is left alone.
    reopen_refusals = [
        ("no --evidence", ["--plan", plan_path, "--reopen", MILESTONE3_HEADING,
                           "--reason", "x", "--ledger", reopen_ledger]),
        ("empty --reason", ["--plan", plan_path, "--reopen", MILESTONE3_HEADING,
                            "--evidence", finding, "--reason", "   ",
                            "--ledger", reopen_ledger]),
        ("no --ledger", ["--plan", plan_path, "--reopen", MILESTONE3_HEADING,
                         "--evidence", finding, "--reason", "x"]),
        ("--evidence that does not exist",
         ["--plan", plan_path, "--reopen", MILESTONE3_HEADING, "--evidence",
          impl_dir / "nope.md", "--reason", "x", "--ledger", reopen_ledger]),
    ]
    codes = [run_py(MARK_MILESTONE, argv).returncode for _n, argv in reopen_refusals]
    ok = codes == [2, 2, 2, 2]
    record("18c. mark_milestone --reopen without evidence/reason/ledger -> exit 2 (x4)",
           ok, "" if ok else f"exit codes {codes} for "
                             f"{[n for n, _a in reopen_refusals]}")

    # --- Step 19 (2.6.1): the Tier-1 consumer end ---------------------------
    # 15a/15b prove the producer half. These two are the consumer half the
    # audit found had no consumers at all: a stamp dated in the future, and
    # --verify-current against a repo whose HEAD has moved on.
    (summary / "contacts" / "overview.md").write_text(
        f"# Contacts — overview\n\n> Provenance — 2031-01-01\n> `{head}`\n\n"
        "## Owning services\n\napi\n", encoding="utf-8")
    proc = run_py(CHECK_TIER1_PROVENANCE, ["--summary-root", summary,
                                           "--feature", "contacts",
                                           "--repo", f"proj={repo}"])
    data = parse_json(proc, "19a. check_tier1_provenance: a stamp dated in the future -> exit 1")
    if data is not None:
        codes = sorted({f.get("code") for f in (data.get("findings") or [])})
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and codes == ["stamp_date_future"])
        record("19a. check_tier1_provenance: a stamp dated in the future -> exit 1",
               ok, "" if ok else json.dumps(data))

    # Restore an honest stamp, then move HEAD on. Drift is still a warning by
    # default (bgpdd-discovery section 1) and a finding under --verify-current.
    (summary / "contacts" / "overview.md").write_text(
        f"# Contacts — overview\n\n> Provenance — 2026-08-12\n> `{head}`\n\n"
        "## Owning services\n\napi\n", encoding="utf-8")
    (repo / "src" / "drifted.py").write_text("# moves HEAD\n", encoding="utf-8")
    run_git(["add", "src/drifted.py"], repo)
    run_git(["commit", "-qm", "tier1 drift step"], repo)
    t1_common = ["--summary-root", summary, "--feature", "contacts",
                 "--repo", f"proj={repo}"]

    proc = run_py(CHECK_TIER1_PROVENANCE, t1_common)
    data = parse_json(proc, "19b. check_tier1_provenance: drift alone is still exit 0")
    if data is not None:
        ok = (proc.returncode == 0 and data.get("result") == "PASS"
              and len(data.get("drift") or []) >= 1
              and data.get("findings") == [])
        record("19b. check_tier1_provenance: drift alone is still exit 0", ok,
               "" if ok else json.dumps(data))

    proc = run_py(CHECK_TIER1_PROVENANCE, t1_common + ["--verify-current"])
    data = parse_json(proc, "19c. check_tier1_provenance --verify-current: drift -> exit 1 (tier1_drift)")
    if data is not None:
        codes = sorted({f.get("code") for f in (data.get("findings") or [])})
        drifted = [f for f in (data.get("findings") or [])
                   if f.get("code") == "tier1_drift"]
        ok = (proc.returncode == 1 and data.get("result") == "FAIL"
              and codes == ["tier1_drift"]
              and bool(drifted) and drifted[0].get("stamped") == head
              and drifted[0].get("head") != head)
        record("19c. check_tier1_provenance --verify-current: drift -> exit 1 (tier1_drift)",
               ok, "" if ok else json.dumps(data))

    t1_ledger = impl_dir / "tier1-gates.jsonl"
    proc = run_py(CHECK_TIER1_PROVENANCE, t1_common + [
        "--verify-current", "--allow-drift", "the commit touched only CI",
        "--ledger", t1_ledger])
    data = parse_json(proc, "19d. --allow-drift: exit 0 and the reason in the ledger")
    if data is not None:
        records = [json.loads(l) for l in
                   t1_ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
        ok = (proc.returncode == 0 and data.get("result") == "PASS"
              and data.get("allow_drift") == "the commit touched only CI"
              and bool(records)
              and records[-1].get("allow_drift_reason") == "the commit touched only CI")
        record("19d. --allow-drift: exit 0 and the reason in the ledger", ok,
               "" if ok else json.dumps(data))

    empty = run_py(CHECK_TIER1_PROVENANCE,
                   t1_common + ["--verify-current", "--allow-drift", "   "])
    orphan = run_py(CHECK_TIER1_PROVENANCE,
                    t1_common + ["--allow-drift", "no --verify-current"])
    ok = empty.returncode == 2 and orphan.returncode == 2
    record("19e. --allow-drift empty, or without --verify-current -> exit 2", ok,
           "" if ok else f"empty={empty.returncode} orphan={orphan.returncode}")

    # --- Step 20 (2.6.1): record_run refuses an unresolvable tier -----------
    # An unrecognised --model recorded cleanly with tier: null and silently
    # deleted the verifier-below-producer check for that delegation. A mistyped
    # flag must not be able to disable a gate.
    run_log = impl_dir / "run-log-2611.jsonl"
    log_common = ["--log", run_log, "--pipeline", "bgpdd-build",
                  "--phase", "Phase 2", "--event", "delegation",
                  "--unit", MILESTONE2_TITLE]
    producer = run_py(RECORD_RUN, log_common + ["--agent", "mason",
                                                "--model", "claude-opus-4-1"])
    typo = run_py(RECORD_RUN, log_common + ["--agent", "luna",
                                            "--model", "gpt-4o"])
    inversion = run_py(RECORD_RUN, log_common + ["--agent", "luna",
                                                 "--model", "haiku"])
    typo_data = None
    try:
        typo_data = json.loads(typo.stdout)
    except ValueError:
        pass
    lines = [json.loads(l) for l in
             run_log.read_text(encoding="utf-8").splitlines() if l.strip()]
    ok = (producer.returncode == 0 and typo.returncode == 2
          and typo_data is not None
          and typo_data.get("problem") == "model_unknown"
          and inversion.returncode == 1
          # The producer record is the only one written: the typo wrote
          # nothing, and the inversion was refused before the write.
          and [r.get("agent") for r in lines] == ["mason"])
    record("20. record_run: an unresolvable --model is exit 2 (model_unknown), "
           "and the inversion check still fires after it", ok,
           "" if ok else f"producer={producer.returncode} typo={typo.returncode} "
                         f"inversion={inversion.returncode} log={lines!r}")

    # 20b: dep is a producer, so a verifier below Dep is the same inversion.
    dep_log = impl_dir / "run-log-dep.jsonl"
    dep_common = ["--log", dep_log, "--pipeline", "bgpdd-shipping",
                  "--phase", "Step 2", "--event", "delegation",
                  "--unit", "Launch"]
    dep = run_py(RECORD_RUN, dep_common + ["--agent", "dep", "--model", "opus"])
    below = run_py(RECORD_RUN, dep_common + ["--agent", "vera", "--model", "haiku"])
    ok = dep.returncode == 0 and below.returncode == 1
    record("20b. record_run: a verifier below `dep` is an inversion -> exit 1",
           ok, "" if ok else f"dep={dep.returncode} vera={below.returncode}")

    # --- Step 21 (2.6.1): the guard hook sees Bash ---------------------------
    # Rules 2 and 4 tested `tool_name in WRITE_TOOLS`, so one `>>` rewrote any
    # ledger while Edit on the same path was denied. Driven through real stdin,
    # the way the runtime drives it, so the payload shape is exercised too.
    guard_root = impl_dir / "guard-scratch"
    (guard_root / ".docs" / "bugfix" / "login-500").mkdir(parents=True, exist_ok=True)
    (guard_root / ".docs" / "bugfix" / "login-500" / "bug-report.md").write_text(
        "# Bug\n", encoding="utf-8")
    (guard_root / ".docs" / "bugfix" / "login-500" / "gates.jsonl").write_text(
        json.dumps({"gate": "check_bugfix_intake.py", "verdict": "PASS",
                    "argv": [], "milestone": "login-500"}) + "\n",
        encoding="utf-8")
    (guard_root / "tests").mkdir(parents=True, exist_ok=True)
    (guard_root / "tests" / "orders.test.js").write_text("t\n", encoding="utf-8")

    def guard(tool, tool_input):
        payload = json.dumps({"hook_event_name": "PreToolUse",
                              "tool_name": tool, "tool_input": tool_input,
                              "cwd": str(guard_root)})
        proc = subprocess.run([sys.executable, str(GUARD_ACTION)],
                              input=payload, capture_output=True, text=True,
                              timeout=120)
        if not proc.stdout.strip():
            return None
        return (json.loads(proc.stdout)["hookSpecificOutput"]
                ["permissionDecisionReason"])

    ledger_rel = ".docs/bugfix/login-500/gates.jsonl"
    denied_writes = [
        "echo '{}' >> " + ledger_rel,
        "echo '{}' | tee -a " + ledger_rel,
        "Set-Content " + ledger_rel + " '{}'",
        "rm " + ledger_rel,
        "python -c \"open('" + ledger_rel + "','a').write('{}')\"",
    ]
    denied_tests = [
        "sed -i s/a/b/ tests/orders.test.js",
        "mv tests/orders.test.js tests/orders.test.js.old",
        "git checkout -- tests/",
    ]
    allowed = ["cat " + ledger_rel, "npm test", "git status"]
    write_reasons = [guard("Bash", {"command": c}) for c in denied_writes]
    test_reasons = [guard("Bash", {"command": c}) for c in denied_tests]
    allow_reasons = [guard("Bash", {"command": c}) for c in allowed]
    ok = (all(r and "gate artifact" in r for r in write_reasons)
          and all(r and "test path" in r for r in test_reasons)
          and all(r is None for r in allow_reasons))
    record("21. guard_action: Bash redirection/tee/cmdlet/rm/python -c into a "
           "ledger, and sed/mv/git-checkout of a frozen test, all DENY", ok,
           "" if ok else f"writes={write_reasons} tests={test_reasons} "
                         f"allowed={allow_reasons}")

    # 21b: the sanctioned close. bgpdd-bugfix Phase 5 ends in a local merge,
    # which rule 1 denied. A commit-gate --commit PASS for this lane's own
    # milestone un-arms it; one for a DIFFERENT milestone does not.
    lane_ledger = guard_root / ".docs" / "bugfix" / "login-500" / "gates.jsonl"
    before = guard("Bash", {"command": "git merge --no-ff bugfix/login-500"})
    with lane_ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"gate": "check_commit_gate.py", "verdict": "PASS",
                             "argv": ["--commit"], "milestone": "other-bug"}) + "\n")
    wrong = guard("Bash", {"command": "git merge --no-ff bugfix/login-500"})
    with lane_ledger.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"gate": "check_commit_gate.py", "verdict": "PASS",
                             "argv": ["--commit"], "milestone": "login-500"}) + "\n")
    after = guard("Bash", {"command": "git merge --no-ff bugfix/login-500"})
    ok = (before is not None and wrong is not None and after is None)
    record("21b. guard_action: the lane's own --commit PASS un-arms rule 1; "
           "another milestone's does not", ok,
           "" if ok else f"before={bool(before)} wrong={bool(wrong)} "
                         f"after={bool(after)}")


if __name__ == "__main__":
    sys.exit(main())
