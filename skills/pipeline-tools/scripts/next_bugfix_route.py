#!/usr/bin/env python3
"""Decides the bgpdd-bugfix lane's FAST / FULL / PLAN route mechanically.

The fork used to be a judgement call made at the moment the Orchestrator most
wants to proceed, which is exactly the shape CLAUDE.md convention #9 says must
become a gate. This reads the two durable artifacts the lane has already
produced -- `bug-report.md` (Phase 0) and `rca.md` (Phase 2) -- and prints the
route with its reasons.

It REFUSES to route at all (exit 2) unless the gate ledger holds a PASS for
`check_bugfix_intake.py` whose recorded sha256 still matches the current
`bug-report.md`. Routing off an unlinted or since-edited report is how a bug
with no reproduction command reaches the FAST lane.

It also **ties the RED capture to the report**. Phase 1 (RED) runs before this
gate, so when the report carries a `- Command:` line, `--red` is REQUIRED and
the RED sidecar's recorded child `argv` must EQUAL a legitimate tokenization
of that command string. The comparison is on **token lists, not strings** --
`shlex.split(posix=True)` first, then the same with backslashes doubled (so a
Windows path survives), then a raw whitespace split; any match passes and
nothing fuzzier is tried. A string compare rejected every correctly quoted
command (`-d '{}'`, `-H "Content-Type: application/json"`), because the shell
strips the quoting before the child sees argv.

The Orchestrator briefs Quinn to run the report's command **verbatim**, so a
mismatch is either a paraphrased brief or a capture of something else. This
also closes the intake gate's documented residual hole -- `` `see chat` `` is
backtick-wrapped and two tokens, so it passes that text lint, and no probe
ever ran it. A steps-only report has no command to compare, so `--red` is
optional there and unchecked.

Route rules:

  * **PLAN** when the RCA says the fix needs a new capability, a schema or
    contract change, or more files than the size bound. PLAN outranks
    everything else -- this is not a bugfix.
  * **FAST** when ALL of: the report carries a reproduction COMMAND (not steps
    only); the RED capture ran that exact command; the RCA names EXACTLY ONE
    root-cause file; the surface is `api` or `ui` (not `both`); and the RCA
    records the suite green at baseline.
  * **FULL** otherwise.

FAST and FULL differ ONLY in user check-ins (FAST proceeds phase to phase;
FULL pauses after the RCA and before the commit). **Neither route ever skips
RED, GREEN, Luna, or the commit gate** -- there is no route through this lane
that reaches a commit without all four.

The report's own fields (surface, reproduction mode) are read by DELEGATING to
`check_bugfix_intake.py` and reading its JSON -- the same subprocess-reuse
pattern `check_commit_gate.py` uses for `check_runtime_evidence.py`, and for
the same reason: this family has no shared module by convention, and a second
copy of the report parser would drift.

Pure standard library. Files are read as utf-8-sig.

Usage:
    python next_bugfix_route.py --report <bug-report.md> --rca <rca.md> \
        --ledger <path> [--red <capture>] [--milestone "<slug>"] \
        [--max-changed-files N]
    python next_bugfix_route.py --self-test
"""
import argparse
import hashlib
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

READ_ENCODING = "utf-8-sig"
DEFAULT_MAX_CHANGED_FILES = 5

FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
FIELD_RE = re.compile(r"^\s*[-*]\s*([A-Za-z][A-Za-z /_-]{1,40}?)\s*:\s*(.*)$")
INT_RE = re.compile(r"^\s*(\d{1,4})\b")

BASELINE_VALUES = ("green", "red", "not run")
YES_NO = ("yes", "no")
PLACEHOLDER_VALUE_RE = re.compile(
    r"^(?:<[^>]*>|todo|tbd|fixme|n/?a|none|unknown|\?+|\.{3,}|xxx+)[.:]?$",
    re.IGNORECASE)

INTAKE_GATE = Path(__file__).parent / "check_bugfix_intake.py"
SIDECAR_SUFFIX = ".meta.json"


# ---------------------------------------------------------------------------
# The RED capture's provenance sidecar
# ---------------------------------------------------------------------------
# Minimal reader, duplicated from check_red_green.py / check_runtime_evidence.py
# per family convention (stdlib-only, one file each, no shared module). Only
# `argv` is needed here -- exit code and hash are check_red_green.py's job at
# Phase 4, and duplicating those checks would make two gates disagree about
# which one owns them.

def red_command(capture_path):
    """(the sidecar's argv joined by single spaces, problem-code, detail)."""
    p = Path(capture_path)
    if not p.is_file():
        return None, "red_sidecar_missing", (
            f"no RED capture at {capture_path}")
    side = Path(str(p) + SIDECAR_SUFFIX)
    if not side.is_file():
        return None, "red_sidecar_missing", (
            f"the RED capture has no provenance sidecar at {side.name} — a "
            "capture with no run_quiet.py sidecar records no command, so "
            "nothing can tie it to the report")
    try:
        meta = json.loads(side.read_text(encoding=READ_ENCODING,
                                         errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, "red_sidecar_missing", (
            f"the RED sidecar is unreadable or not valid JSON: {exc}")
    if not isinstance(meta, dict):
        return None, "red_sidecar_missing", "the RED sidecar is not an object"
    argv = meta.get("argv")
    if not isinstance(argv, list) or not argv:
        return None, "red_sidecar_missing", (
            "the RED sidecar records no child argv")
    return [str(a) for a in argv], None, None


def normalize_command(text):
    """The report's `- Command:` value: backticks and outer space stripped."""
    return (text or "").strip().strip("`").strip()


def command_token_candidates(command):
    """Every legitimate tokenization of the report's command string.

    The comparison against the sidecar is on TOKEN LISTS, never on strings,
    because the recorded `argv` is what the process actually received -- the
    shell has already removed the quoting. A string compare rejected every
    correctly quoted command: a report saying

        - Command: `curl --fail -X POST http://host/orders -d '{}'`

    produces argv [..., '-d', '{}'], whose join is `-d {}` and never equals
    the report's `-d '{}'`. Any `-d '{...}'` or `-H "Content-Type: ..."` hit
    it, so the check refused precisely the careful reports.

    Three candidates, tried in order; ANY match passes. Nothing fuzzier than
    this -- no case-folding, no reordering, no dropped tokens:

      1. `shlex.split(posix=True)` -- the shell's own rule, and the one that
         makes quoted JSON bodies and quoted headers work.
      2. the same with backslashes doubled first, so a backslash-separated
         Windows path survives posix mode, which would otherwise consume the
         separators as escapes.
      3. a raw whitespace split -- the original rule, kept because an
         unquoted command tokenizes identically under it and this candidate
         cannot be defeated by a shlex parse error.

    A `- Command:` value must be a single **argv-runnable** command: no
    pipes, redirects or `&&`. `run_quiet.py` executes argv directly with no
    shell, so a shell-only construct is not re-runnable as written and its
    tokens could never match a real capture.
    """
    candidates = []
    for label, text in (("shlex", command),
                        ("shlex-escaped", command.replace("\\", "\\\\"))):
        try:
            tokens = shlex.split(text, posix=True)
        except ValueError:
            continue    # unbalanced quotes: that candidate does not apply
        if tokens:
            candidates.append((label, tokens))
    raw = command.split()
    if raw:
        candidates.append(("whitespace", raw))
    return candidates


def command_matches(command, argv):
    """(matched?, the strategy name that matched, or None)."""
    for label, tokens in command_token_candidates(command):
        if tokens == argv:
            return True, label
    return False, None


class GateError(Exception):
    """Structural/usage failure -- maps to exit 2."""


# ---------------------------------------------------------------------------
# Shared gate ledger (see ../SKILL.md, "Gate ledger")
# ---------------------------------------------------------------------------

def sha256_file(path):
    """Hex sha256 of a file's bytes, or None when it cannot be read."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def append_ledger(ledger_path, argv, milestone, inputs, verdict, exit_code,
                  extra=None):
    """Append ONE JSON line recording this run. Best-effort by design."""
    if not ledger_path:
        return
    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gate": Path(__file__).name,
        "argv": list(argv),
        "milestone": milestone,
        "inputs": {str(p): sha256_file(p) for p in inputs if p},
        "verdict": verdict,
        "exit": exit_code,
    }
    if extra:
        record.update(extra)
    try:
        p = Path(ledger_path)
        if str(p.parent):
            p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


def read_ledger(ledger_path):
    """Every parseable JSON-object line of the ledger, in file order."""
    p = Path(ledger_path)
    if not p.is_file():
        return []
    records = []
    for line in p.read_text(encoding=READ_ENCODING,
                            errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def intake_backing(ledger_path, report_path):
    """(ok, detail) — does the ledger hold a PASS over THIS report's bytes?

    Matches on the recorded input HASH rather than on the path string: the
    ledger records the path exactly as the earlier invocation gave it, which
    is legitimately a different string (relative vs absolute) from the one
    handed to this script.
    """
    current = sha256_file(report_path)
    if current is None:
        return False, f"cannot hash {report_path}"
    records = [r for r in read_ledger(ledger_path)
               if r.get("gate") == INTAKE_GATE.name]
    if not records:
        return False, (f"no {INTAKE_GATE.name} entry in {ledger_path} — run the "
                       "intake gate before routing; a route decided off an "
                       "unlinted report is a guess")
    latest = records[-1]
    if latest.get("verdict") != "PASS":
        return False, (f"the latest {INTAKE_GATE.name} ledger entry records "
                       f"verdict {latest.get('verdict')!r} (exit "
                       f"{latest.get('exit')}) — the bug report has not passed "
                       "intake")
    hashes = [v for v in (latest.get("inputs") or {}).values() if v]
    if current not in hashes:
        return False, (f"the latest {INTAKE_GATE.name} PASS hashed inputs "
                       f"{hashes!r}, none of which is the current "
                       f"{report_path} ({current}) — the report was edited "
                       "after it passed intake; re-run the intake gate")
    return True, None


# ---------------------------------------------------------------------------
# Delegation: the report's own fields come from the intake gate
# ---------------------------------------------------------------------------

def run_intake_gate(report_path):
    """Return check_bugfix_intake.py's JSON payload for this report."""
    if not INTAKE_GATE.is_file():
        raise GateError(f"intake gate not found at {INTAKE_GATE}")
    cmd = [sys.executable, str(INTAKE_GATE), "--report", str(report_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f"cannot run the intake gate: {exc}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise GateError(f"intake gate emitted unparseable output "
                        f"(exit {proc.returncode}): {proc.stdout[:400]!r}")
    if proc.returncode != 0:
        # The ledger said this report passed over these exact bytes. If a
        # re-run disagrees, the artifact and the record no longer describe the
        # same world -- an environment defect, never a route.
        raise GateError(
            "the intake gate now reports "
            f"{payload.get('result')} for a report the ledger recorded as PASS "
            f"over the same bytes: {payload.get('problems') or payload.get('error')}")
    return payload


# ---------------------------------------------------------------------------
# rca.md
# ---------------------------------------------------------------------------

def read_text(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding=READ_ENCODING, errors="replace")


def strip_fenced_blocks(text):
    """Blank every fenced region, preserving line count.

    A `- New capability: yes` inside a fence is a TEMPLATE, never an
    assertion. Same rule as the rest of the family
    (pipeline-tools/SKILL.md, "Fenced blocks and encoding").
    """
    out, fence = [], None
    for line in text.split("\n"):
        m = FENCE_RE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                out.append("")
                continue
            out.append(line)
        else:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            out.append("")
    return out


def clean_value(raw):
    return (raw or "").strip().strip("`").strip('"').strip("'").strip()


def value_present(raw):
    v = clean_value(raw)
    return bool(v) and not PLACEHOLDER_VALUE_RE.match(v)


def parse_rca(path):
    """Return the routing-relevant fields of rca.md.

    Every field is a `- Key: value` line read file-wide, LAST occurrence
    winning -- the same latest-mention-wins convention the family's other
    parsers use, so an appended correction supersedes an earlier line.
    `Root cause file` is the one repeatable key: every occurrence is kept.
    """
    fields, root_cause_files = {}, []
    for line in strip_fenced_blocks(read_text(path)):
        m = FIELD_RE.match(line)
        if not m:
            continue
        key = m.group(1).strip().lower()
        value = m.group(2).strip()
        if key in ("root cause file", "root cause files"):
            if value_present(value):
                root_cause_files.append(clean_value(value))
        else:
            fields[key] = value
    return fields, root_cause_files


def build_report(args):
    report = {
        "report": args.report,
        "rca": args.rca,
        "ledger": args.ledger,
        "max_changed_files": args.max_changed_files,
        "intake_backed": False,
        "surface": None,
        "runtime_observable": None,
        "reproduction_mode": None,
        "reproduction_command": None,
        "red": args.red,
        "red_argv": None,
        "red_command": None,
        "red_match_strategy": None,
        "red_matches_report": None,
        "problems": [],
        "problem_codes": [],
        "root_cause_files": [],
        "baseline_suite": None,
        "new_capability": None,
        "schema_or_contract_change": None,
        "estimated_changed_files": None,
        "missing_fields": [],
        "route": None,
        "reasons": [],
        "warnings": [],
        "result": "ERROR",
        "error": None,
    }

    ok, detail = intake_backing(args.ledger, args.report)
    report["intake_backed"] = ok
    if not ok:
        raise GateError(f"intake_unbacked: {detail}")

    intake = run_intake_gate(args.report)
    report["surface"] = intake.get("surface")
    report["runtime_observable"] = intake.get("runtime_observable")
    report["reproduction_mode"] = intake.get("reproduction_mode")
    report["reproduction_command"] = intake.get("reproduction_command")

    # --- tie the RED capture to the report's command ---
    # Only meaningful in command mode: a steps-only report has no command
    # string to compare, so --red is optional and unchecked there.
    if report["reproduction_mode"] == "command":
        if not args.red:
            raise GateError(
                "red_required: the report carries a '- Command:' line, so "
                "--red <the Phase 1 RED capture> is required — the route "
                "cannot certify that the captured failure is the reported one "
                "without it")
        expected = normalize_command(report["reproduction_command"])
        argv, code, detail = red_command(args.red)
        report["red_argv"] = argv
        report["red_command"] = " ".join(argv) if argv else None
        if code:
            report["problems"].append(f"{code}: {detail}")
            report["problem_codes"].append(code)
            report["red_matches_report"] = False
        else:
            matched, strategy = command_matches(expected, argv)
            report["red_match_strategy"] = strategy
            report["red_matches_report"] = matched
            if not matched:
                tried = [toks for _, toks in command_token_candidates(expected)]
                report["problems"].append(
                    "red_command_mismatch: the RED sidecar recorded argv "
                    f"{argv!r}, which matches none of the tokenizations of "
                    f"the report's '- Command:' {expected!r} ({tried!r}). "
                    "Comparison is on token lists, not strings — brief Quinn "
                    "to run the report's command verbatim, or correct the "
                    "report and re-run Phase 0's gate")
                report["problem_codes"].append("red_command_mismatch")
    elif args.red:
        report["warnings"].append(
            "--red was given but the report is steps-only, so there is no "
            "command string to compare; the capture is not checked here "
            "(check_red_green.py gates it at Phase 4)")

    if report["problems"]:
        report["route"] = None
        report["result"] = "BLOCKED"
        report["reasons"] = list(report["problems"])
        return report

    fields, root_cause_files = parse_rca(args.rca)
    report["root_cause_files"] = root_cause_files

    baseline = clean_value(fields.get("baseline suite", "")).lower()
    if baseline in BASELINE_VALUES:
        report["baseline_suite"] = baseline
    else:
        report["missing_fields"].append("- Baseline suite: green | red | not run")

    for key, out_key in (("new capability", "new_capability"),
                         ("schema or contract change",
                          "schema_or_contract_change")):
        raw = clean_value(fields.get(key, "")).lower()
        if raw in YES_NO:
            report[out_key] = raw == "yes"
        else:
            report["missing_fields"].append(
                f"- {key.capitalize()}: yes | no")

    est_raw = clean_value(fields.get("estimated changed files", ""))
    est_match = INT_RE.match(est_raw)
    if est_match:
        report["estimated_changed_files"] = int(est_match.group(1))
    else:
        report["warnings"].append(
            "rca.md records no '- Estimated changed files: <N>' line, so the "
            "size bound cannot contribute to the route; "
            "check_commit_gate.py --max-changed-files still enforces it at "
            "commit time")

    if not root_cause_files:
        report["missing_fields"].append("- Root cause file: <path>")

    if report["missing_fields"]:
        report["route"] = None
        report["result"] = "INCOMPLETE"
        report["reasons"].append(
            "rca.md is missing routing field(s): "
            + "; ".join(report["missing_fields"]))
        return report

    # --- PLAN outranks everything: this is not a bugfix ---
    plan_reasons = []
    if report["new_capability"]:
        plan_reasons.append("the RCA says the fix needs a NEW CAPABILITY")
    if report["schema_or_contract_change"]:
        plan_reasons.append(
            "the RCA says the fix needs a SCHEMA or CONTRACT change")
    est = report["estimated_changed_files"]
    if est is not None and est > args.max_changed_files:
        plan_reasons.append(
            f"the RCA estimates {est} changed files, over the lane's size "
            f"bound of {args.max_changed_files}")
    if plan_reasons:
        report["route"] = "PLAN"
        report["result"] = "PLAN"
        report["reasons"] = plan_reasons + [
            "PLAN means route the user to /bgpdd-plan or /bgpdd-build — this "
            "lane fixes a localized defect and does not build capability"]
        return report

    # --- FAST needs every term; any miss is FULL ---
    fast_terms = [
        ("a reproduction COMMAND is present (not steps only)",
         report["reproduction_mode"] == "command",
         f"reproduction_mode is {report['reproduction_mode']!r}"),
        ("the RED capture ran the report's command",
         report["red_matches_report"] is True,
         "the RED capture's command was not compared (steps-only report)"),
        ("the RCA names exactly one root-cause file",
         len(root_cause_files) == 1,
         f"the RCA names {len(root_cause_files)} root-cause file(s)"),
        ("the surface is api or ui, not both",
         report["surface"] in ("api", "ui"),
         f"surface is {report['surface']!r}"),
        ("the RCA records the suite green at baseline",
         report["baseline_suite"] == "green",
         f"baseline suite is {report['baseline_suite']!r}"),
    ]
    failed = [why for _, ok_, why in fast_terms if not ok_]
    if failed:
        report["route"] = "FULL"
        report["result"] = "FULL"
        report["reasons"] = failed + [
            "FULL differs from FAST ONLY in user check-ins: pause after the "
            "RCA and before the commit. RED, GREEN, Luna and the commit gate "
            "run on both routes"]
    else:
        report["route"] = "FAST"
        report["result"] = "FAST"
        report["reasons"] = [term for term, _, _ in fast_terms] + [
            "FAST differs from FULL ONLY in user check-ins: proceed phase to "
            "phase without pausing. RED, GREEN, Luna and the commit gate run "
            "on both routes"]
    return report


def build_parser():
    parser = argparse.ArgumentParser(prog="next_bugfix_route.py")
    parser.add_argument("--report", help="path to bug-report.md")
    parser.add_argument("--rca", help="path to rca.md")
    parser.add_argument("--red",
                        help="the Phase 1 RED capture; REQUIRED when the "
                             "report carries a '- Command:' line, and its "
                             "sidecar's argv must equal that command exactly")
    parser.add_argument("--ledger",
                        help="the gate ledger; REQUIRED — the intake PASS is "
                             "read from it and this run is appended to it")
    parser.add_argument("--milestone",
                        help="bug slug, to scope this run's ledger record")
    parser.add_argument("--max-changed-files", type=int,
                        default=DEFAULT_MAX_CHANGED_FILES,
                        help="the lane's fix-size bound (default "
                             f"{DEFAULT_MAX_CHANGED_FILES}); an RCA estimating "
                             "more than this routes to PLAN")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone,
                      [p for p in (args.report, args.rca, args.red) if p],
                      verdict, code)
        return code

    missing = [n for n, v in (("--report", args.report), ("--rca", args.rca),
                              ("--ledger", args.ledger)) if not v]
    if missing:
        print(json.dumps({
            "result": "ERROR",
            "error": f"missing required argument(s): {', '.join(missing)}"}))
        return finish(2, "ERROR")
    if args.max_changed_files < 1:
        print(json.dumps({"result": "ERROR",
                          "error": "--max-changed-files must be >= 1"}))
        return finish(2, "ERROR")

    try:
        report = build_report(args)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")
    print(json.dumps(report, indent=2))
    # Two exit-1 results, told apart by `result`: INCOMPLETE = the RCA cannot
    # be routed as written; BLOCKED = the RED capture does not back the report.
    # Both mean "fix the artifact and re-run", never "improvise past it".
    if report["result"] in ("INCOMPLETE", "BLOCKED"):
        return finish(1, "FAIL")
    return finish(0, "PASS")


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import contextlib
    import io
    import shutil
    import tempfile
    import unittest

    REPORT_OK = (
        "# Bug report: coupon 500\n\n"
        "## Observed behaviour\n\nPOST /api/orders returns 500.\n\n"
        "## Expected behaviour\n\nIt returns 400 with the error envelope.\n\n"
        "## Exact error text or log excerpt\n\n```\nNullReferenceException\n```\n\n"
        "## Reproduction\n\n- Command: `curl -sS -i http://localhost:5142/api/orders`\n\n"
        "## Environment\n\n- Branch: main\n- Version: 2.1.0\n\n"
        "## Regression\n\n- Regression: no\n\n"
        "## Affected surface\n\n- Surface: api\n- Runtime observable: yes\n")
    REPORT_STEPS = REPORT_OK.replace(
        "- Command: `curl -sS -i http://localhost:5142/api/orders`",
        "1. Sign in as a standard user.\n2. Apply an empty coupon at checkout.")
    REPORT_BOTH = REPORT_OK.replace("- Surface: api", "- Surface: both")

    def rca_text(root_cause_files=("src/Api/Coupons/ApplyCoupon.cs",),
                 baseline="green", new_capability="no",
                 schema="no", estimated=2, extra=""):
        body = ["# RCA: coupon-500\n",
                "## Hypothesis ledger\n",
                "| Hypothesis | Disproof attempt | Result |",
                "|---|---|---|",
                "| Coupon code is null-checked upstream | read the handler | "
                "disproved — no check |\n",
                "## Root cause\n"]
        for f in root_cause_files:
            body.append(f"- Root cause file: `{f}`")
        body.append("")
        body.append("## Fix shape\n")
        body.append(f"- Baseline suite: {baseline}")
        body.append(f"- New capability: {new_capability}")
        body.append(f"- Schema or contract change: {schema}")
        if estimated is not None:
            body.append(f"- Estimated changed files: {estimated}")
        if extra:
            body.append(extra)
        return "\n".join(body) + "\n"

    class RouteTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.report = self.dir / "bug-report.md"
            self.rca = self.dir / "rca.md"
            self.ledger = self.dir / "gates.jsonl"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _back_intake(self, verdict="PASS", path=None, hash_override=None):
            """Append the intake PASS the route gate demands."""
            target = path or self.report
            rec = {"ts": "2026-09-03T09:00:00Z",
                   "gate": "check_bugfix_intake.py",
                   "argv": ["--report", str(target)],
                   "milestone": "coupon-500",
                   "inputs": {str(target): hash_override
                              or sha256_file(target)},
                   "verdict": verdict,
                   "exit": 0 if verdict == "PASS" else 1}
            with open(self.ledger, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")

        # The command REPORT_OK carries, as the argv run_quiet would record.
        RED_ARGV = ["curl", "-sS", "-i", "http://localhost:5142/api/orders"]

        def _write_red(self, argv=None, sidecar=True, name="red.md"):
            """A RED capture + the machine-owned sidecar run_quiet writes."""
            cap = self.dir / "evidence" / "red" / name
            cap.parent.mkdir(parents=True, exist_ok=True)
            cap.write_text("# Runtime capture\n\n- Exit code: 22\n\n"
                            "## Captured output\n\n```\n404\n```\n",
                            encoding="utf-8")
            if sidecar:
                Path(str(cap) + SIDECAR_SUFFIX).write_text(json.dumps({
                    "argv": self.RED_ARGV if argv is None else argv,
                    "exit_code": 22, "finished": "2026-09-03T10:00:00Z",
                    "capture_sha256": sha256_file(cap),
                    "tool": "run_quiet.py", "schema": 1}, indent=2),
                    encoding="utf-8")
            return str(cap)

        def _setup(self, report=REPORT_OK, rca=None, back=True,
                   red_argv=None, red_sidecar=True, **rca_kw):
            self.report.write_text(report, encoding="utf-8")
            self.rca.write_text(rca if rca is not None else rca_text(**rca_kw),
                                encoding="utf-8")
            self.red = self._write_red(argv=red_argv, sidecar=red_sidecar)
            if back:
                self._back_intake()

        def _run(self, extra=None, red=True):
            argv = ["--report", str(self.report), "--rca", str(self.rca),
                    "--ledger", str(self.ledger)]
            if red and getattr(self, "red", None):
                argv += ["--red", self.red]
            args = build_parser().parse_args(argv + (extra or []))
            return build_report(args)

        def _main(self, extra=None, red=True):
            argv = ["--report", str(self.report), "--rca", str(self.rca),
                    "--ledger", str(self.ledger)]
            if red and getattr(self, "red", None):
                argv += ["--red", self.red]
            argv += (extra or [])
            buf, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                code = main(argv)
            return code, buf.getvalue() + err.getvalue()

        # ---- FAST ----

        def test_fast_route(self):
            self._setup()
            r = self._run()
            self.assertEqual(r["route"], "FAST", r["reasons"])
            self.assertEqual(r["surface"], "api")
            self.assertEqual(r["reproduction_mode"], "command")
            self.assertTrue(r["intake_backed"])
            self.assertTrue(any("ONLY in user check-ins" in x
                                for x in r["reasons"]))

        def test_fast_exits_zero(self):
            self._setup()
            self.assertEqual(self._main()[0], 0)

        # ---- FULL ----

        def test_full_when_reproduction_is_steps_only(self):
            self._setup(report=REPORT_STEPS)
            r = self._run()
            self.assertEqual(r["route"], "FULL")
            self.assertTrue(any("reproduction_mode" in x for x in r["reasons"]))

        def test_full_when_two_root_cause_files(self):
            self._setup(root_cause_files=("src/a.cs", "src/b.cs"))
            r = self._run()
            self.assertEqual(r["route"], "FULL")
            self.assertEqual(len(r["root_cause_files"]), 2)

        def test_full_when_surface_is_both(self):
            self._setup(report=REPORT_BOTH)
            r = self._run()
            self.assertEqual(r["route"], "FULL")
            self.assertEqual(r["surface"], "both")

        def test_full_when_baseline_suite_not_green(self):
            self._setup(baseline="red")
            r = self._run()
            self.assertEqual(r["route"], "FULL")
            self.assertEqual(r["baseline_suite"], "red")

        def test_full_when_baseline_suite_not_run(self):
            self._setup(baseline="not run")
            self.assertEqual(self._run()["route"], "FULL")

        # ---- PLAN ----

        def test_plan_when_new_capability(self):
            self._setup(new_capability="yes")
            r = self._run()
            self.assertEqual(r["route"], "PLAN")
            self.assertTrue(any("NEW CAPABILITY" in x for x in r["reasons"]))

        def test_plan_when_schema_or_contract_change(self):
            self._setup(schema="yes")
            self.assertEqual(self._run()["route"], "PLAN")

        def test_plan_when_over_the_size_bound(self):
            self._setup(estimated=9)
            r = self._run()
            self.assertEqual(r["route"], "PLAN")
            self.assertEqual(r["estimated_changed_files"], 9)

        def test_at_the_size_bound_is_not_plan(self):
            self._setup(estimated=5)
            self.assertEqual(self._run()["route"], "FAST")

        def test_max_changed_files_override_moves_the_boundary(self):
            self._setup(estimated=6)
            self.assertEqual(self._run()["route"], "PLAN")
            self.assertEqual(
                self._run(["--max-changed-files", "8"])["route"], "FAST")

        def test_plan_outranks_a_would_be_fast(self):
            """Every FAST term met, but the fix needs a schema change."""
            self._setup(schema="yes")
            r = self._run()
            self.assertEqual(r["route"], "PLAN")
            self.assertEqual(r["reproduction_mode"], "command")

        # ---- INCOMPLETE ----

        def test_incomplete_when_baseline_field_missing(self):
            self._setup(rca=rca_text().replace("- Baseline suite: green\n", ""))
            r = self._run()
            self.assertEqual(r["result"], "INCOMPLETE")
            self.assertIsNone(r["route"])
            self.assertTrue(any("Baseline suite" in x
                                for x in r["missing_fields"]))

        def test_incomplete_when_no_root_cause_file(self):
            self._setup(root_cause_files=())
            r = self._run()
            self.assertEqual(r["result"], "INCOMPLETE")

        def test_incomplete_when_fix_shape_flags_missing(self):
            self._setup(rca=rca_text().replace("- New capability: no\n", ""))
            self.assertEqual(self._run()["result"], "INCOMPLETE")

        def test_incomplete_exits_one(self):
            self._setup(root_cause_files=())
            self.assertEqual(self._main()[0], 1)

        # ---- --red: the RED capture must have run the report's command ----

        def test_fast_reasons_name_the_red_tie(self):
            self._setup()
            r = self._run()
            self.assertEqual(r["route"], "FAST", r["reasons"])
            self.assertTrue(r["red_matches_report"])
            self.assertEqual(r["red_command"],
                             "curl -sS -i http://localhost:5142/api/orders")
            self.assertTrue(any("the RED capture ran the report's command" in x
                                for x in r["reasons"]))

        def test_red_required_when_the_report_carries_a_command(self):
            self._setup()
            code, out = self._main(red=False)
            self.assertEqual(code, 2)
            self.assertIn("red_required", out)

        def test_red_command_mismatch_blocks(self):
            """The load-bearing case: a capture of something else."""
            self._setup(red_argv=["curl", "-sS", "-i",
                                   "http://localhost:5142/api/health"])
            r = self._run()
            self.assertEqual(r["result"], "BLOCKED")
            self.assertIsNone(r["route"])
            self.assertFalse(r["red_matches_report"])
            self.assertIn("red_command_mismatch", r["problem_codes"])

        def test_red_command_mismatch_exits_one(self):
            self._setup(red_argv=["pytest"])
            self.assertEqual(self._main()[0], 1)

        def test_backticked_see_chat_is_closed_here(self):
            """Intake passes `see chat`; this gate is what refuses it."""
            self._setup(report=REPORT_OK.replace(
                "- Command: `curl -sS -i http://localhost:5142/api/orders`",
                "- Command: `see chat`"))
            r = self._run()
            self.assertEqual(r["result"], "BLOCKED")
            self.assertIn("red_command_mismatch", r["problem_codes"])

        def test_red_sidecar_missing_blocks(self):
            self._setup(red_sidecar=False)
            r = self._run()
            self.assertEqual(r["result"], "BLOCKED")
            self.assertIn("red_sidecar_missing", r["problem_codes"])

        def test_red_capture_file_missing_blocks(self):
            self._setup()
            args = build_parser().parse_args(
                ["--report", str(self.report), "--rca", str(self.rca),
                 "--ledger", str(self.ledger),
                 "--red", str(self.dir / "evidence" / "red" / "gone.md")])
            r = build_report(args)
            self.assertEqual(r["result"], "BLOCKED")
            self.assertIn("red_sidecar_missing", r["problem_codes"])

        def test_red_sidecar_without_argv_blocks(self):
            self._setup(red_argv=[])
            r = self._run()
            self.assertEqual(r["result"], "BLOCKED")
            self.assertIn("red_sidecar_missing", r["problem_codes"])

        # -- quoting: the comparison is on TOKEN LISTS, not strings ---------
        # A string compare rejected every correctly quoted command, because
        # the shell strips the quoting before the child sees argv.

        def _quoted(self, command, argv):
            """Report carrying `command`; RED capture recording `argv`."""
            self._setup(report=REPORT_OK.replace(
                "- Command: `curl -sS -i http://localhost:5142/api/orders`",
                f"- Command: `{command}`"), red_argv=argv)
            return self._run()

        def test_single_quoted_json_body_matches(self):
            r = self._quoted(
                "curl --fail -X POST http://localhost:5000/orders -d '{}'",
                ["curl", "--fail", "-X", "POST",
                 "http://localhost:5000/orders", "-d", "{}"])
            self.assertEqual(r["route"], "FAST", r["reasons"])
            self.assertTrue(r["red_matches_report"])
            self.assertEqual(r["red_match_strategy"], "shlex")

        def test_single_quoted_json_body_with_fields_matches(self):
            r = self._quoted(
                "curl -X POST http://h/o -d '{\"coupon\":null}'",
                ["curl", "-X", "POST", "http://h/o", "-d",
                 '{"coupon":null}'])
            self.assertTrue(r["red_matches_report"], r["problems"])

        def test_double_quoted_header_with_spaces_matches(self):
            r = self._quoted(
                'curl --fail -H "Content-Type: application/json" http://h/o',
                ["curl", "--fail", "-H", "Content-Type: application/json",
                 "http://h/o"])
            self.assertEqual(r["route"], "FAST", r["reasons"])
            self.assertEqual(r["red_match_strategy"], "shlex")

        def test_windows_path_with_backslashes_matches(self):
            r = self._quoted(
                r"C:\repro\run.cmd --case coupon-null",
                [r"C:\repro\run.cmd", "--case", "coupon-null"])
            self.assertTrue(r["red_matches_report"], r["problems"])
            # posix shlex would eat the separators; the escaped candidate or
            # the whitespace candidate is what carries this one.
            self.assertIn(r["red_match_strategy"],
                          ("shlex-escaped", "whitespace"))

        def test_a_genuinely_different_command_still_mismatches(self):
            """The fix must not have made the check permissive."""
            r = self._quoted(
                "curl --fail -X POST http://localhost:5000/orders -d '{}'",
                ["curl", "--fail", "-X", "POST",
                 "http://localhost:5000/health", "-d", "{}"])
            self.assertEqual(r["result"], "BLOCKED")
            self.assertIn("red_command_mismatch", r["problem_codes"])

        def test_reordered_tokens_still_mismatch(self):
            """No reordering tolerance -- argv order is meaning."""
            r = self._quoted(
                "curl --fail -X POST http://h/o",
                ["curl", "-X", "POST", "--fail", "http://h/o"])
            self.assertEqual(r["result"], "BLOCKED")
            self.assertIn("red_command_mismatch", r["problem_codes"])

        def test_case_differences_still_mismatch(self):
            r = self._quoted("curl --fail http://h/Orders",
                             ["curl", "--fail", "http://h/orders"])
            self.assertEqual(r["result"], "BLOCKED")

        def test_unbalanced_quotes_fall_back_to_whitespace(self):
            """A shlex ValueError must not crash the gate."""
            self.assertEqual(
                command_token_candidates("curl -d 'oops"),
                [("whitespace", ["curl", "-d", "'oops"])])

        def test_whitespace_is_collapsed_before_comparing(self):
            self._setup(report=REPORT_OK.replace(
                "- Command: `curl -sS -i http://localhost:5142/api/orders`",
                "- Command: `curl  -sS   -i  http://localhost:5142/api/orders`"))
            r = self._run()
            self.assertEqual(r["route"], "FAST", r["reasons"])
            self.assertTrue(r["red_matches_report"])

        def test_steps_only_report_does_not_require_red(self):
            self._setup(report=REPORT_STEPS)
            args = build_parser().parse_args(
                ["--report", str(self.report), "--rca", str(self.rca),
                 "--ledger", str(self.ledger)])
            r = build_report(args)
            self.assertEqual(r["route"], "FULL")
            self.assertIsNone(r["red_matches_report"])
            self.assertEqual(r["problem_codes"], [])

        def test_steps_only_report_with_red_warns_and_does_not_check(self):
            self._setup(report=REPORT_STEPS,
                        red_argv=["something", "entirely", "different"])
            r = self._run()
            self.assertEqual(r["route"], "FULL")
            self.assertEqual(r["problem_codes"], [])
            self.assertTrue(any("steps-only" in w for w in r["warnings"]))

        def test_red_block_precedes_the_rca_read(self):
            """A mismatched RED blocks even when the RCA is unroutable."""
            self._setup(red_argv=["pytest", "-x"], root_cause_files=())
            r = self._run()
            self.assertEqual(r["result"], "BLOCKED")
            self.assertIn("red_command_mismatch", r["problem_codes"])

        # ---- adversarial: the intake backing ----

        def test_no_intake_entry_is_exit_2(self):
            self._setup(back=False)
            code, out = self._main()
            self.assertEqual(code, 2)
            self.assertIn("intake_unbacked", out)

        def test_intake_fail_entry_is_exit_2(self):
            self.report.write_text(REPORT_OK, encoding="utf-8")
            self.red = self._write_red()
            self.rca.write_text(rca_text(), encoding="utf-8")
            self._back_intake(verdict="FAIL")
            code, out = self._main()
            self.assertEqual(code, 2)
            self.assertIn("has not passed intake", out)

        def test_intake_pass_whose_hash_no_longer_matches_is_exit_2(self):
            """The load-bearing case: the report was edited after it passed."""
            self._setup()
            self.report.write_text(
                REPORT_OK.replace("- Surface: api", "- Surface: both"),
                encoding="utf-8")
            code, out = self._main()
            self.assertEqual(code, 2)
            self.assertIn("edited after it passed intake", out)

        def test_latest_intake_entry_wins(self):
            """A later FAIL supersedes an earlier PASS."""
            self._setup()
            self._back_intake(verdict="FAIL")
            self.assertEqual(self._main()[0], 2)

        def test_intake_pass_recorded_with_a_different_path_string_is_accepted(self):
            """The ledger records the path as GIVEN; matching is on the hash."""
            self.report.write_text(REPORT_OK, encoding="utf-8")
            self.red = self._write_red()
            self.rca.write_text(rca_text(), encoding="utf-8")
            rec = {"ts": "2026-09-03T09:00:00Z",
                   "gate": "check_bugfix_intake.py", "argv": [],
                   "milestone": None,
                   "inputs": {"./bug-report.md": sha256_file(self.report)},
                   "verdict": "PASS", "exit": 0}
            with open(self.ledger, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
            self.assertEqual(self._main()[0], 0)

        def test_fenced_rca_fields_do_not_route(self):
            """A template block in rca.md asserts nothing."""
            fenced = ("# RCA\n\n## Root cause\n\n"
                      "- Root cause file: `src/a.cs`\n\n"
                      "## Fix shape\n\nUse this shape:\n\n```markdown\n"
                      "- Baseline suite: green\n- New capability: no\n"
                      "- Schema or contract change: no\n```\n")
            self._setup(rca=fenced)
            r = self._run()
            self.assertEqual(r["result"], "INCOMPLETE")

        def test_missing_rca_file_is_exit_2(self):
            self.report.write_text(REPORT_OK, encoding="utf-8")
            self.red = self._write_red()
            self._back_intake()
            code, out = self._main()
            self.assertEqual(code, 2)
            self.assertIn("not found", out)

        def test_missing_flags_are_exit_2(self):
            self._setup()
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(main(["--report", str(self.report),
                                       "--rca", str(self.rca)]), 2)
            self.assertIn("--ledger", buf.getvalue())

        def test_no_estimate_line_warns_but_still_routes(self):
            self._setup(estimated=None)
            r = self._run()
            self.assertEqual(r["route"], "FAST")
            self.assertTrue(any("Estimated changed files" in w
                                for w in r["warnings"]))

        def test_latest_rca_field_mention_wins(self):
            self._setup(rca=rca_text() + "\n## Correction\n\n"
                        "- Baseline suite: red\n")
            self.assertEqual(self._run()["baseline_suite"], "red")

        # ---- ledger ----

        def _records(self):
            return [json.loads(l) for l in
                    self.ledger.read_text(encoding="utf-8").splitlines()
                    if l.strip()]

        def test_ledger_records_the_route_run(self):
            self._setup()
            code, _ = self._main(["--milestone", "coupon-500"])
            self.assertEqual(code, 0)
            rec = self._records()[-1]
            self.assertEqual(rec["gate"], "next_bugfix_route.py")
            self.assertEqual(rec["verdict"], "PASS")
            self.assertEqual(rec["milestone"], "coupon-500")
            self.assertEqual(rec["inputs"][str(self.rca)],
                             sha256_file(self.rca))

        def test_ledger_records_the_refusal_too(self):
            self._setup(back=False)
            self.assertEqual(self._main()[0], 2)
            self.assertEqual(self._records()[-1]["verdict"], "ERROR")

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RouteTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
