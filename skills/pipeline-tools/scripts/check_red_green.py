#!/usr/bin/env python3
"""RED-then-GREEN gate for the bgpdd-bugfix lane.

Converts the prose rule that a post-fix green alone cannot show the check
ever failed into an artifact pair that has to exist on disk. A GREEN with no
RED sibling is an unproven test; a RED and a GREEN of DIFFERENT commands are
two unrelated runs dressed as a proof.

Given one RED capture and one or more GREEN captures, all produced by
`run_quiet.py --capture`, it verifies:

  * every capture exists and is structurally a capture (`## Captured output`)
  * every capture carries its `<capture>.meta.json` provenance sidecar, whose
    `capture_sha256` still matches the capture FILE's bytes -- a hand-typed
    capture has no sidecar and an edited one fails the hash
  * every sidecar AGREES with its capture's own header lines: `exit_code`
    equals `- Exit code:` and `finished` equals `- Captured:`. The hash
    protects the capture file and NOTHING protects the sidecar, so editing the
    sidecar alone -- a RED's exit_code 3 -> 0, or a GREEN's `finished` pushed
    past the RED's to manufacture the ordering below -- passed every other
    check here (`sidecar_body_disagrees`; a capture with no header pair at all
    is `capture_header_missing` and must be re-taken)
  * the sidecars record the IDENTICAL child `argv` -- the same command was
    run before and after the fix
  * the RED sidecar's `exit_code` is NON-zero (the failure was observed)
  * every GREEN sidecar's `exit_code` is zero
  * every GREEN was `finished` strictly LATER than the RED (a "green" taken
    before the fix is the pre-existing state, not a proof). The sidecar's
    stamp has one-second resolution and the comparison is strictly `>`:
    EQUAL stamps do not order two runs, so they fail closed. A real RED and
    GREEN are a fix round apart; a pair inside one second is re-taken.
  * with `--green-runs N`, at least N green captures were supplied and all of
    them pass -- for a flaky bug, 4 of 5 green is NOT fixed

The sidecar validation is deliberately the SAME logic
`check_runtime_evidence.py` applies (sidecar present, JSON object, matching
`capture_sha256`, integer `exit_code`), duplicated rather than imported per
this script family's convention (stdlib-only, one file each, no shared
module -- `GateError` and `append_ledger` are duplicated in several files).
It is not weakened here: the only difference is that RED inverts the
exit-code expectation, which is the point of a RED capture.

THIS GATE READS FILES ONLY. It runs nothing and opens no socket.

Pure standard library. Every file is read as utf-8-sig, so a BOM cannot
break parsing.

Usage:
    python check_red_green.py --red <capture> --green <capture> \
        [--green <capture>]... [--green-runs N] [--milestone "<slug>"] \
        [--ledger <path>]
    python check_red_green.py --self-test
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

READ_ENCODING = "utf-8-sig"
SIDECAR_SUFFIX = ".meta.json"
CAPTURED_HEADING_RE = re.compile(
    r"(?im)^##[^\S\n]+Captured[^\S\n]+output[^\S\n]*$")
TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"


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


def ledger_line_hash(raw):
    """sha256 of one ledger LINE's bytes, ignoring its terminator.

    Surrounding whitespace (CR included) is stripped so a ledger written on
    Windows chains identically to the same file read on POSIX. Byte-identical
    in every gate in this family and in check_ledger.py, which verifies the
    chain (family convention: one file each, no shared module).
    """
    return hashlib.sha256(raw.strip()).hexdigest()


def ledger_prev_hash(ledger_path):
    """The `prev` value for the next record: hash of the last line on disk.

    `"genesis"` when the ledger is missing or holds no non-blank line.
    """
    try:
        with open(ledger_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return "genesis"
    last = None
    for raw in data.splitlines():
        if raw.strip():
            last = raw
    return "genesis" if last is None else ledger_line_hash(last)


def ledger_self_hash(record):
    """sha256 of the record serialized canonically WITHOUT its `self` field."""
    body = {k: v for k, v in record.items() if k != "self"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")).hexdigest()


def append_ledger(ledger_path, argv, milestone, inputs, verdict, exit_code,
                  extra=None):
    """Append ONE JSON line recording this run. Best-effort by design."""
    if not ledger_path:
        return
    record = {
        "ts": datetime.now(timezone.utc).strftime(TIMESTAMP_FMT),
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
        record["prev"] = ledger_prev_hash(p)
        record["self"] = ledger_self_hash(record)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# Provenance: the run_quiet.py sidecar (same logic as check_runtime_evidence)
# ---------------------------------------------------------------------------

def sidecar_path_for(capture_path):
    return Path(str(capture_path) + SIDECAR_SUFFIX)


def load_sidecar(path):
    """(meta dict or None, reason-when-None). Malformed reads as absent."""
    p = Path(path)
    if not p.is_file():
        return None, "no sidecar file"
    try:
        meta = json.loads(p.read_text(encoding=READ_ENCODING, errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"sidecar is unreadable or not valid JSON: {exc}"
    if not isinstance(meta, dict):
        return None, "sidecar is not a JSON object"
    return meta, None


def parse_finished(meta):
    """(datetime or None, reason-when-None) from the sidecar's `finished`."""
    raw = meta.get("finished")
    if not isinstance(raw, str) or not raw.strip():
        return None, "the sidecar records no 'finished' timestamp"
    try:
        return datetime.strptime(raw.strip(), TIMESTAMP_FMT), None
    except ValueError:
        return None, (f"the sidecar's 'finished' value {raw.strip()!r} is not "
                      f"an ISO-8601 UTC instant ({TIMESTAMP_FMT})")


# --- body-vs-sidecar agreement (duplicated from check_runtime_evidence.py) --
# `capture_sha256` protects the capture FILE's bytes; NOTHING protects the
# sidecar's own fields. So the hash-checked body is the witness and the sidecar
# is the claim under test: flipping a RED sidecar's `exit_code` 3 -> 0, or
# pushing a GREEN's `finished` past the RED's to manufacture the ordering this
# gate checks, leaves every hash intact -- and did, until this comparison
# existed. `- Captured:` is compared against `finished`, which is what
# run_quiet.py now stamps it FROM; the window is one-sided (never EARLIER than
# `finished`) and two seconds wide solely so a capture from the pre-2.4 build
# path, which re-stamped the header while rendering, is not accused of forgery.
CAPTURED_SKEW_SECONDS = 2
BODY_EXIT_CODE_RE = re.compile(
    r"(?im)^[^\S\n]*-[^\S\n]*Exit[^\S\n]+code[^\S\n]*:[^\S\n]*(-?\d+)[^\S\n]*$")
BODY_CAPTURED_RE = re.compile(
    r"(?im)^[^\S\n]*-[^\S\n]*Captured[^\S\n]*:[^\S\n]*(\S+)[^\S\n]*$")
FENCE_LINE_RE = re.compile(r"^[^\S\n]*(`{3,}|~{3,})")


def capture_header(text):
    """The capture's header region: before `## Captured output`, fences blanked.

    Both cuts matter. A probe's own output routinely contains a line like
    `- Exit code: 3` (this gate's captures are test-runner transcripts), and a
    capture's prose preamble may fence an example header block; either would
    otherwise supply the value that is supposed to witness the sidecar.
    """
    m = CAPTURED_HEADING_RE.search(text)
    head = text[:m.start()] if m else text
    out, fence = [], None
    for line in head.split("\n"):
        fm = FENCE_LINE_RE.match(line)
        if fence is None:
            if fm:
                fence = fm.group(1)
                out.append("")
                continue
            out.append(line)
        else:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
            out.append("")
    return "\n".join(out)


def sidecar_body_disagreement(text, meta):
    """(problem-code, detail) when the capture's header and sidecar disagree."""
    head = capture_header(text)
    exit_m = BODY_EXIT_CODE_RE.search(head)
    cap_m = BODY_CAPTURED_RE.search(head)
    if exit_m is None or cap_m is None:
        return ("capture_header_missing",
                "the capture carries no readable '- Exit code:' and "
                "'- Captured:' header pair, so the sidecar's exit_code and "
                "finished stamp cannot be checked against anything -- a "
                "capture predating run_quiet.py's header contract must be "
                "re-taken with `run_quiet.py --capture`")
    body_exit = int(exit_m.group(1))
    side_exit = meta.get("exit_code")
    if isinstance(side_exit, int) and side_exit != body_exit:
        return ("sidecar_body_disagrees",
                f"the sidecar records exit_code {side_exit} but the capture's "
                f"own hash-protected body records '- Exit code: {body_exit}' — "
                "the sidecar was edited after the run (the capture file's hash "
                "still matches, because only the sidecar was touched)")
    try:
        body_dt = datetime.strptime(cap_m.group(1), TIMESTAMP_FMT)
    except ValueError:
        return ("capture_header_missing",
                f"the capture's '- Captured: {cap_m.group(1)}' is not an "
                f"ISO-8601 UTC instant ({TIMESTAMP_FMT})")
    side_dt, reason = parse_finished(meta)
    if side_dt is None:
        return ("sidecar_body_disagrees",
                f"{reason} to check against the capture's '- Captured: "
                f"{cap_m.group(1)}'")
    skew = (body_dt - side_dt).total_seconds()
    if not 0 <= skew <= CAPTURED_SKEW_SECONDS:
        return ("sidecar_body_disagrees",
                f"the sidecar records finished {meta.get('finished')!r} but the "
                f"capture's own hash-protected body records '- Captured: "
                f"{cap_m.group(1)}' ({skew:+.0f}s apart; allowed 0.."
                f"{CAPTURED_SKEW_SECONDS}s) — run_quiet.py stamps "
                "'- Captured:' FROM 'finished', so a pair this far apart was "
                "not written by it: either the sidecar's timestamp was edited "
                "(which is how a GREEN is made to look newer than the RED it "
                "is ordered against) or the capture was authored by hand")
    return None, None


def evaluate_capture(path, role):
    """Per-capture result dict. Empty `problems` => structurally usable.

    `role` is "red" or "green" and selects the exit-code expectation only.
    """
    res = {
        "path": str(path), "role": role, "exists": False,
        "is_capture": None, "sidecar": None, "sidecar_present": None,
        "sidecar_capture_sha256_ok": None, "sidecar_body_agrees": None,
        "exit_code": None,
        "argv": None, "finished": None,
        "problems": [], "problem_codes": [],
    }

    def fail(code, message):
        res["problems"].append(f"{code}: {message}")
        res["problem_codes"].append(code)

    p = Path(path)
    if not p.is_file():
        fail("capture_missing", f"no such capture file: {path}")
        return res
    res["exists"] = True

    text = p.read_text(encoding=READ_ENCODING, errors="replace")
    res["is_capture"] = bool(CAPTURED_HEADING_RE.search(text))
    if not res["is_capture"]:
        fail("not_a_capture",
             "no '## Captured output' section — structurally not a "
             "run_quiet.py capture artifact")

    side = sidecar_path_for(p)
    res["sidecar"] = str(side)
    meta, side_error = load_sidecar(side)
    res["sidecar_present"] = meta is not None
    if meta is None:
        fail("sidecar_missing",
             f"{side_error} at {side.name} — a capture with no run_quiet.py "
             "provenance sidecar is indistinguishable from a hand-typed one; "
             "re-take it with `run_quiet.py --capture`")
        return res

    declared = meta.get("capture_sha256")
    actual = sha256_file(p)
    res["sidecar_capture_sha256_ok"] = bool(
        declared and actual and declared == actual)
    if not res["sidecar_capture_sha256_ok"]:
        fail("sidecar_hash_mismatch",
             f"the capture file's sha256 ({actual}) does not match the "
             f"sidecar's capture_sha256 ({declared}) — the artifact was edited "
             "after it was recorded, so its contents are authored, not observed")

    # The hash above protects the capture file, not the sidecar. Compare the
    # two BEFORE trusting the exit code or the ordering stamp below.
    code, detail = sidecar_body_disagreement(text, meta)
    res["sidecar_body_agrees"] = code is None
    if code:
        fail(code, detail)

    exit_code = meta.get("exit_code")
    if not isinstance(exit_code, int):
        fail("sidecar_no_exit_code",
             "the sidecar records no integer exit_code — the run's outcome was "
             "never observed")
    else:
        res["exit_code"] = exit_code
        if role == "red" and exit_code == 0:
            fail("red_exit_zero",
                 f"the RED capture's command exited {exit_code} — a run that "
                 "succeeded does not reproduce the bug, so nothing downstream "
                 "can tell a real fix from a test that never failed")
        if role == "green" and exit_code != 0:
            fail("green_exit_nonzero",
                 f"the GREEN capture's command exited {exit_code} — the bug is "
                 "not fixed")

    argv = meta.get("argv")
    if not isinstance(argv, list) or not argv:
        fail("sidecar_no_argv",
             "the sidecar records no child argv — the command that ran cannot "
             "be compared against the other capture's")
    else:
        res["argv"] = [str(a) for a in argv]

    finished, reason = parse_finished(meta)
    if finished is None:
        fail("timestamp_unparseable", reason)
    else:
        res["finished"] = meta["finished"].strip()
    res["_finished_dt"] = finished
    return res


def build_report(args):
    report = {
        "red": args.red,
        "green": list(args.green),
        "green_runs": args.green_runs,
        "red_result": None,
        "green_results": [],
        "command": None,
        "problems": [],
        "problem_codes": [],
        "warnings": [],
        "result": "FAIL",
        "error": None,
    }

    def fail(code, message):
        report["problems"].append(f"{code}: {message}")
        report["problem_codes"].append(code)

    red = evaluate_capture(args.red, "red")
    greens = [evaluate_capture(g, "green") for g in args.green]

    if len(args.green) < args.green_runs:
        fail("green_runs_short",
             f"--green-runs {args.green_runs} requires {args.green_runs} GREEN "
             f"capture(s) but {len(args.green)} were given — an under-supplied "
             "flake check proves nothing about the runs that were not taken")

    red_dt = red.pop("_finished_dt", None)
    report["red_result"] = red
    report["problems"] += [f"red: {p}" for p in red["problems"]]
    report["problem_codes"] += red["problem_codes"]

    if red["argv"]:
        report["command"] = " ".join(red["argv"])

    for i, g in enumerate(greens, start=1):
        g_dt = g.pop("_finished_dt", None)
        if red["argv"] and g["argv"] and g["argv"] != red["argv"]:
            g["problems"].append(
                "command_mismatch: this GREEN capture's command "
                f"{g['argv']!r} is not the RED capture's {red['argv']!r} — a "
                "different command's green says nothing about the reproduction")
            g["problem_codes"].append("command_mismatch")
        if red_dt is not None and g_dt is not None and g_dt <= red_dt:
            g["problems"].append(
                f"green_not_newer: this GREEN capture finished {g['finished']}, "
                f"which is not later than the RED's {red['finished']} — a green "
                "taken before the fix records the pre-fix state")
            g["problem_codes"].append("green_not_newer")
        report["green_results"].append(g)
        report["problems"] += [f"green[{i}]: {p}" for p in g["problems"]]
        report["problem_codes"] += g["problem_codes"]

    report["result"] = "PASS" if not report["problems"] else "FAIL"
    return report


def build_parser():
    parser = argparse.ArgumentParser(prog="check_red_green.py")
    parser.add_argument("--red", help="the pre-fix (failing) capture")
    parser.add_argument("--green", action="append", default=[],
                        help="a post-fix (passing) capture; repeatable")
    parser.add_argument("--green-runs", type=int, default=1,
                        help="how many GREEN captures must be supplied and "
                             "pass (default 1; use 5 for a flaky bug)")
    parser.add_argument("--milestone",
                        help="bug slug, to scope this run's ledger record")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    return parser


def ledger_inputs(args):
    """Every file this gate READ: each capture and its sidecar.

    The sidecars are included deliberately: `check_commit_gate.py
    --require-ledger-gates` re-hashes exactly these paths, so recording them
    is what makes a later edit of a sidecar's exit_code detectable at commit
    time rather than only at this gate's own run.
    """
    paths = []
    for cap in [args.red] + list(args.green):
        if not cap:
            continue
        paths.append(cap)
        paths.append(str(sidecar_path_for(cap)))
    return paths


def main(argv):
    args = build_parser().parse_args(argv)
    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone, ledger_inputs(args),
                      verdict, code)
        return code

    missing = [n for n, v in (("--red", args.red), ("--green", args.green))
               if not v]
    if missing:
        print(json.dumps({"result": "ERROR",
                          "error": f"missing required argument(s): "
                                   f"{', '.join(missing)}"}))
        return finish(2, "ERROR")
    if args.green_runs < 1:
        print(json.dumps({"result": "ERROR",
                          "error": "--green-runs must be >= 1 (a gate that "
                                   "passes with zero green runs asserts "
                                   "nothing)"}))
        return finish(2, "ERROR")

    try:
        report = build_report(args)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")
    print(json.dumps(report, indent=2))
    passed = report["result"] == "PASS"
    return finish(0 if passed else 1, "PASS" if passed else "FAIL")


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import contextlib
    import io
    import os
    import shutil
    import tempfile
    import unittest

    def capture_text(cmd, exit_code, body, captured):
        """run_quiet.py's shape: the header records the SAME exit code and
        instant the sidecar does, so a fixture pair agrees by construction."""
        return (
            "# Runtime capture\n\n"
            "- Milestone: coupon-500\n"
            "- Transport: test runner\n"
            f"- Probe command: `{' '.join(cmd)}` [probe-exempt: test runner]\n"
            f"- Captured: {captured}\n"
            f"- Exit code: {exit_code}\n\n"
            "## Captured output\n\n```\n" + body + "\n```\n")

    class RedGreenTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.cmd = ["dotnet", "test", "--filter", "CouponTests"]

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _write(self, name, exit_code, finished, cmd=None, body=None,
                   sidecar=True, argv=None, hash_ok=True, extra_meta=None,
                   body_exit=None, body_captured=None):
            """Write a capture (+ its machine-owned sidecar) like run_quiet.

            `body_exit` / `body_captured` override ONLY the header lines, which
            is how a fixture forges a sidecar whose hash still matches.
            """
            cmd = cmd or self.cmd
            cap = self.dir / "evidence" / name
            cap.parent.mkdir(parents=True, exist_ok=True)
            cap.write_text(capture_text(
                cmd, exit_code if body_exit is None else body_exit,
                body if body is not None else ("FAILED" if exit_code else "OK"),
                finished if body_captured is None else body_captured),
                encoding="utf-8")
            if sidecar:
                meta = {
                    "argv": argv if argv is not None else list(cmd),
                    "cwd": str(self.dir), "host": "test-host", "pid": 4242,
                    "started": finished, "finished": finished,
                    "exit_code": exit_code,
                    "body_sha256": "0" * 64,
                    "capture_sha256": (sha256_file(cap) if hash_ok
                                       else "f" * 64),
                    "tool": "run_quiet.py", "schema": 1,
                }
                if extra_meta:
                    meta.update(extra_meta)
                sidecar_path_for(cap).write_text(
                    json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            return str(cap)

        def _run(self, red, greens, extra=None):
            argv = ["--red", red]
            for g in greens:
                argv += ["--green", g]
            args = build_parser().parse_args(argv + (extra or []))
            return build_report(args)

        def _main(self, argv):
            buf, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                code = main(argv)
            return code, buf.getvalue() + err.getvalue()

        def _pair(self):
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z")
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z")
            return red, green

        # ---- happy paths ----

        def test_red_then_green_passes(self):
            red, green = self._pair()
            r = self._run(red, [green])
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["command"], "dotnet test --filter CouponTests")
            self.assertEqual(r["red_result"]["exit_code"], 1)
            self.assertEqual(r["green_results"][0]["exit_code"], 0)

        def test_five_green_runs_all_pass(self):
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z")
            greens = [self._write(f"green{i}.md", 0,
                                  f"2026-09-03T1{i}:00:00Z")
                      for i in range(1, 6)]
            r = self._run(red, greens, ["--green-runs", "5"])
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(len(r["green_results"]), 5)

        # ---- adversarial ----

        def test_hand_typed_capture_without_sidecar_fails(self):
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z")
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z",
                                sidecar=False)
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("sidecar_missing", r["problem_codes"])

        def test_red_without_sidecar_fails(self):
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z",
                              sidecar=False)
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("sidecar_missing", r["problem_codes"])

        def test_edited_capture_fails_the_hash(self):
            red, green = self._pair()
            Path(green).write_text(
                Path(green).read_text(encoding="utf-8").replace(
                    "- Exit code: 0", "- Exit code: 0 "), encoding="utf-8")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("sidecar_hash_mismatch", r["problem_codes"])

        # ---- the sidecar is the mutable half: it must agree with the body ----

        def test_flipped_red_sidecar_exit_code_is_caught_by_the_body(self):
            """The attack: a RED that actually passed, sidecar flipped to 1."""
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z", body_exit=0)
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("sidecar_body_disagrees", r["problem_codes"])
            self.assertNotIn("sidecar_hash_mismatch", r["problem_codes"])
            self.assertFalse(r["red_result"]["sidecar_body_agrees"])

        def test_flipped_green_sidecar_exit_code_is_caught_by_the_body(self):
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z")
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z",
                                 body_exit=1)
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("sidecar_body_disagrees", r["problem_codes"])

        def test_edited_green_timestamp_is_caught_by_the_body(self):
            """Pushing `finished` past the RED's is how ordering is forged."""
            red = self._write("red.md", 1, "2026-09-03T12:00:00Z")
            green = self._write("green.md", 0, "2026-09-03T13:00:00Z",
                                 body_captured="2026-09-03T09:00:00Z")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("sidecar_body_disagrees", r["problem_codes"])
            self.assertNotIn("green_not_newer", r["problem_codes"])

        def test_agreeing_pair_passes_and_records_agreement(self):
            red, green = self._pair()
            r = self._run(red, [green])
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertTrue(r["red_result"]["sidecar_body_agrees"])
            self.assertTrue(r["green_results"][0]["sidecar_body_agrees"])

        def test_one_second_render_skew_still_passes(self):
            """The pre-2.4 build path stamped `Captured` just after `finished`."""
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z",
                               body_captured="2026-09-03T10:00:01Z")
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z",
                                 body_captured="2026-09-03T11:00:02Z")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "PASS", r["problems"])

        def test_capture_without_header_lines_fails_closed(self):
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z")
            green = self.dir / "evidence" / "legacy-green.md"
            green.write_text(
                "# Runtime capture\n\n- Milestone: coupon-500\n\n"
                "## Captured output\n\n```\nOK\n```\n", encoding="utf-8")
            sidecar_path_for(green).write_text(json.dumps({
                "argv": self.cmd, "exit_code": 0,
                "started": "2026-09-03T11:00:00Z",
                "finished": "2026-09-03T11:00:00Z",
                "capture_sha256": sha256_file(green),
                "tool": "run_quiet.py", "schema": 1}), encoding="utf-8")
            r = self._run(red, [str(green)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("capture_header_missing", r["problem_codes"])

        def test_header_lines_inside_the_captured_output_supply_nothing(self):
            """A test transcript that PRINTS `- Exit code: 0` is not a header."""
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z",
                               body="- Exit code: 0\n- Captured: 1999-01-01T00:00:00Z")
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "PASS", r["problems"])

        def test_mismatched_commands_fail(self):
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z")
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z",
                                cmd=["dotnet", "test", "--filter", "OtherTests"])
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("command_mismatch", r["problem_codes"])

        def test_green_older_than_red_fails(self):
            red = self._write("red.md", 1, "2026-09-03T12:00:00Z")
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("green_not_newer", r["problem_codes"])

        def test_green_at_the_same_instant_as_red_fails(self):
            """Equal timestamps do not order the two runs — fail closed."""
            red = self._write("red.md", 1, "2026-09-03T11:00:00Z")
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("green_not_newer", r["problem_codes"])

        def test_red_that_actually_passed_fails(self):
            """A RED whose command exited 0 never reproduced the bug."""
            red = self._write("red.md", 0, "2026-09-03T10:00:00Z")
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("red_exit_zero", r["problem_codes"])

        def test_green_that_still_fails_is_not_fixed(self):
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z")
            green = self._write("green.md", 1, "2026-09-03T11:00:00Z")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("green_exit_nonzero", r["problem_codes"])

        def test_four_of_five_green_is_not_fixed(self):
            """The flake case: one red run among five means not fixed."""
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z")
            greens = [self._write(f"green{i}.md", 0 if i != 4 else 1,
                                  f"2026-09-03T1{i}:00:00Z")
                      for i in range(1, 6)]
            r = self._run(red, greens, ["--green-runs", "5"])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("green_exit_nonzero", r["problem_codes"])

        def test_green_runs_short_fails(self):
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z")
            greens = [self._write(f"green{i}.md", 0,
                                  f"2026-09-03T1{i}:00:00Z")
                      for i in range(1, 4)]
            r = self._run(red, greens, ["--green-runs", "5"])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("green_runs_short", r["problem_codes"])

        def test_missing_capture_file_fails(self):
            red, green = self._pair()
            r = self._run(red, [str(self.dir / "evidence" / "gone.md")])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("capture_missing", r["problem_codes"])

        def test_not_a_capture_artifact_fails(self):
            red, green = self._pair()
            plain = self.dir / "evidence" / "notes.md"
            plain.write_text("the test failed, trust me\n", encoding="utf-8")
            sidecar_path_for(plain).write_text(json.dumps({
                "argv": self.cmd, "exit_code": 0,
                "finished": "2026-09-03T12:00:00Z",
                "capture_sha256": sha256_file(plain),
                "tool": "run_quiet.py", "schema": 1}), encoding="utf-8")
            r = self._run(red, [str(plain)])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("not_a_capture", r["problem_codes"])

        def test_sidecar_that_is_not_an_object_reads_as_absent(self):
            red, green = self._pair()
            sidecar_path_for(Path(green)).write_text("[1, 2, 3]",
                                                     encoding="utf-8")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("sidecar_missing", r["problem_codes"])

        def test_sidecar_without_integer_exit_code_fails(self):
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z")
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z",
                                extra_meta={"exit_code": "0"})
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("sidecar_no_exit_code", r["problem_codes"])

        def test_sidecar_without_argv_fails(self):
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z", argv=[])
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("sidecar_no_argv", r["problem_codes"])

        def test_unparseable_finished_timestamp_fails(self):
            red = self._write("red.md", 1, "2026-09-03T10:00:00Z")
            green = self._write("green.md", 0, "yesterday afternoon")
            r = self._run(red, [green])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("timestamp_unparseable", r["problem_codes"])

        def test_bom_prefixed_sidecar_still_parses(self):
            red, green = self._pair()
            side = sidecar_path_for(Path(green))
            side.write_bytes(b"\xef\xbb\xbf" + side.read_bytes())
            r = self._run(red, [green])
            self.assertEqual(r["result"], "PASS", r["problems"])

        # ---- usage + ledger ----

        def test_missing_flags_are_exit_2(self):
            red, green = self._pair()
            self.assertEqual(self._main(["--green", green])[0], 2)
            self.assertEqual(self._main(["--red", red])[0], 2)

        def test_green_runs_zero_is_exit_2(self):
            red, green = self._pair()
            code, out = self._main(["--red", red, "--green", green,
                                    "--green-runs", "0"])
            self.assertEqual(code, 2)
            self.assertIn(">= 1", out)

        def _records(self, ledger):
            return [json.loads(l) for l in
                    Path(ledger).read_text(encoding="utf-8").splitlines()
                    if l.strip()]

        def test_ledger_records_the_pass_with_capture_and_sidecar_hashes(self):
            red, green = self._pair()
            ledger = self.dir / "logs" / "gates.jsonl"
            argv = ["--red", red, "--green", green,
                    "--milestone", "coupon-500", "--ledger", str(ledger)]
            code, _ = self._main(argv)
            self.assertEqual(code, 0)
            rec = self._records(ledger)[-1]
            self.assertEqual(rec["gate"], "check_red_green.py")
            self.assertEqual(rec["verdict"], "PASS")
            self.assertEqual(rec["exit"], 0)
            self.assertEqual(rec["milestone"], "coupon-500")
            self.assertEqual(rec["argv"], argv)
            self.assertEqual(rec["inputs"][red], sha256_file(red))
            self.assertEqual(rec["inputs"][str(sidecar_path_for(red))],
                             sha256_file(sidecar_path_for(red)))
            self.assertTrue(rec["ts"].endswith("Z"))

        def test_ledger_records_a_fail_and_a_usage_error(self):
            red = self._write("red.md", 0, "2026-09-03T10:00:00Z")
            green = self._write("green.md", 0, "2026-09-03T11:00:00Z")
            ledger = self.dir / "gates.jsonl"
            self.assertEqual(self._main(
                ["--red", red, "--green", green, "--ledger", str(ledger)])[0], 1)
            self.assertEqual(self._records(ledger)[-1]["verdict"], "FAIL")
            self.assertEqual(self._main(["--ledger", str(ledger)])[0], 2)
            self.assertEqual(self._records(ledger)[-1]["verdict"], "ERROR")

        # ---- end-to-end against the real run_quiet.py ----

        def test_real_run_quiet_pair_passes(self):
            """The composition, not the fixture: run_quiet writes both."""
            run_quiet = Path(__file__).resolve().parent / "run_quiet.py"
            if not run_quiet.is_file():
                self.skipTest("run_quiet.py not found beside this script")
            import subprocess
            import time
            red = self.dir / "evidence" / "rq-red.md"
            green = self.dir / "evidence" / "rq-green.md"
            script = ("import os,sys;"
                      "sys.exit(0 if os.environ.get('FIXED') else 3)")
            env = dict(os.environ)
            env.pop("FIXED", None)
            subprocess.run([sys.executable, str(run_quiet),
                            "--capture", str(red), "--",
                            sys.executable, "-c", script],
                           capture_output=True, env=env, timeout=120)
            # The sidecar's `finished` stamp has ONE-SECOND resolution, and the
            # ordering check is strictly `>` (fail-closed: equal stamps do not
            # order two runs). A real RED and GREEN are a fix round apart; this
            # fixture has to cross a second boundary on purpose.
            time.sleep(1.1)
            env["FIXED"] = "1"
            subprocess.run([sys.executable, str(run_quiet),
                            "--capture", str(green), "--",
                            sys.executable, "-c", script],
                           capture_output=True, env=env, timeout=120)
            self.assertTrue(sidecar_path_for(red).is_file())
            r = self._run(str(red), [str(green)])
            self.assertEqual(r["result"], "PASS", r["problems"])
            self.assertEqual(r["red_result"]["exit_code"], 3)
            self.assertEqual(r["green_results"][0]["exit_code"], 0)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RedGreenTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
