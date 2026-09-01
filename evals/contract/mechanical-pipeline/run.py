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
    python run.py

Exit 0 only if every step below passes. Prints a PASS/FAIL table and cleans
up its temp directory unconditionally (even on failure).
"""
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
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

CAPTURE_TEMPLATE = """# Runtime capture: GET /api/contacts

- Milestone: {milestone}
- Requirement IDs: FR-1
- Surface: api
- Transport: out-of-process HTTP (curl)
- Base URL: http://localhost:5142
- Probe command: `curl -sS -i http://localhost:5142/api/contacts`
- Captured: 2026-08-12T10:00:00Z
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
        "started": "2026-01-01T00:00:00Z",
        "finished": "2026-01-01T00:00:01Z",
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
    tmp = Path(tempfile.mkdtemp(prefix="eval-mechanical-pipeline-"))
    try:
        run_lifecycle(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    failed = [n for n, ok in results if not ok]
    if failed:
        print(f"RESULT: FAIL ({len(failed)}/{len(results)} steps failed)")
        return 1
    print(f"RESULT: PASS ({len(results)}/{len(results)} steps passed)")
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
    blocker_text = f"{MILESTONE2_TITLE}: validation finding open"
    proc = run_py(UPDATE_STATE, ["--state", state_path, "--add-blocker", blocker_text])
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
        CAPTURE_TEMPLATE.format(milestone=MILESTONE2_HEADING, body=ENVELOPE_BODY),
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
        CAPTURE_TEMPLATE.format(milestone=MILESTONE2_HEADING, body=BARE_BODY),
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


if __name__ == "__main__":
    sys.exit(main())
