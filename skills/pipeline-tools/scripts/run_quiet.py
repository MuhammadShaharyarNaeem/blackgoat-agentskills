#!/usr/bin/env python3
"""Quiet build/test runner for agent transcripts.

Runs a child command, writes its FULL merged stdout+stderr to disk, and
prints only what an agent needs to diagnose and fix a failure: the
error-profile lines with surrounding context, the tail, and the log path
for selective grepping. No diagnostic information is lost -- it is moved
off the transcript and onto disk; only noise is dropped from stdout.

Usage:
    python run_quiet.py --log <path> [--context N] [--tail N] \
        [--timeout SECONDS] -- <command and args...>
    python run_quiet.py --capture <path> [--capture-field K=V]... \
        [--log <path>] -- <command and args...>
    python run_quiet.py --self-test

`--capture` additionally writes a conforming runtime-evidence capture
artifact (contract: runtime-evidence/SKILL.md). The tool owns the
load-bearing fields -- probe command, timestamp, exit code, duration and
the captured output -- so an agent cannot author them; `--capture-field`
supplies only the descriptive header (milestone, surface, transport, base
URL, environment). A field name the tool owns is rejected, not overwritten.

`--capture` ALSO writes `<capture path>.meta.json`, a machine-owned sidecar
recording the child argv, cwd, host, pid, start/finish instants, the real
exit code, and two hashes: `body_sha256` over the captured text as embedded
in the artifact, and `capture_sha256` over the finished capture FILE bytes.
The sidecar is what makes a hand-typed capture detectable downstream --
check_runtime_evidence.py requires it, re-hashes the capture file against
`capture_sha256`, and rejects a capture whose probe exited non-zero.

The capture BODY and the sidecar are deliberately redundant: `- Exit code:`
equals the sidecar's `exit_code`, and `- Captured:` equals the sidecar's
`finished` EXACTLY (this file stamps the header line from that same instant --
it used to call `now()` again while rendering, which left the two honestly
but unpredictably a second apart). The redundancy is the point. `capture_sha256`
protects the capture file's bytes and NOTHING protects the sidecar's own
fields, so the body is the witness and the sidecar is the claim: flipping a
sidecar's `exit_code` from 3 to 0, or pushing its `finished` forward to defeat
a downstream freshness check, leaves every hash intact and is invisible until
the two are compared. Every gate that reads a sidecar's `exit_code` or
`finished` now performs that comparison (`sidecar_body_disagrees`), and
`assert_capture_agrees()` below re-checks it here at write time, so this tool
can never be the thing that emits a disagreeing pair.

Pure standard library. Cross-platform (Windows/POSIX).
"""
import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SIDECAR_SUFFIX = ".meta.json"
SIDECAR_SCHEMA = 1

DEFAULT_CONTEXT = 5
DEFAULT_TAIL = 15
DEFAULT_TIMEOUT = 240
EXCERPT_CAP = 200

# One combined, case-insensitive error profile. Word boundaries are chosen
# so summary lines like "0 Failed" or "Tests: 3 failed" still match --
# summaries are wanted, not just the raw error line.
ERROR_PATTERN_SOURCES = [
    r"\berror\s+(CS|MSB|NU|NETSDK)\d+",   # MSBuild/C# diagnostic codes
    r": error ",                          # MSBuild/compiler line shape
    r"\bFailed!",                         # dotnet test summary
    r"\bFAILED\b",                        # generic test-runner summary
    r"\[FAIL\]",                          # tap-style / pytest-style markers
    r"Error Message:",                    # xunit/nunit failure block
    r"Assert\.",                          # assertion frame in a failure
    r"Expected:.*Actual:",                # assertion diff line
    r"\bERR!",                            # npm error prefix
    r"✖",                            # '✖' node/mocha/jest failure mark
    r"FAIL ",                             # jest "FAIL <file>" line
    r"\bexception\b",                     # generic
    r"Traceback \(most recent call last\)",  # Python
    r"\bfatal\b",                         # generic
]
ERROR_PATTERN = re.compile("|".join(ERROR_PATTERN_SOURCES), re.IGNORECASE)


class RunQuietError(Exception):
    """Structural/usage failure -- maps to exit 2."""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def split_argv(argv):
    """Split argv into (own_flags, child_command) at the first '--'."""
    if "--" not in argv:
        return argv, []
    idx = argv.index("--")
    return argv[:idx], argv[idx + 1:]


def find_matches(lines, pattern=ERROR_PATTERN):
    """Return 0-based indices of lines matching the error profile."""
    return [i for i, line in enumerate(lines) if pattern.search(line)]


def compute_windows(indices, context, n_lines):
    """Merge each match index into a [start, end, matched_indices] window.

    Windows are ±context lines around a match, clipped to the file bounds.
    Overlapping or touching windows are merged into one.
    """
    raw = [[max(0, i - context), min(n_lines - 1, i + context), {i}]
           for i in indices]
    raw.sort(key=lambda w: (w[0], w[1]))
    merged = []
    for start, end, matched in raw:
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
            merged[-1][2] |= matched
        else:
            merged.append([start, end, matched])
    return merged


def format_excerpt(lines, indices, context, log_path, cap=EXCERPT_CAP):
    """Render the ERROR EXCERPT body: merged windows, capped, with a note
    (and the log path repeated) if the cap truncated further matches."""
    windows = compute_windows(indices, context, len(lines))
    total_matches = len(indices)
    out = []
    included_matches = set()
    for idx, (start, end, matched) in enumerate(windows):
        block = [f"{i + 1}: {lines[i]}" for i in range(start, end + 1)]
        if idx > 0 and len(out) + 1 + len(block) > cap:
            break
        if idx > 0:
            out.append("...")
        out.extend(block)
        included_matches |= matched
    omitted = total_matches - len(included_matches)
    if omitted > 0:
        out.append(f"... {omitted} further match(es) omitted (cap ~{cap} "
                    f"excerpt lines) -- see full log: {log_path}")
    return out


def format_tail(lines, tail_n):
    """Render the last tail_n lines, numbered."""
    n = len(lines)
    start = max(0, n - tail_n)
    return [f"{i + 1}: {lines[i]}" for i in range(start, n)]


def format_header(cmd, exit_code, duration, log_path, total_lines,
                   timed_out, timeout):
    lines = [
        f"command: {' '.join(cmd)}",
        f"exit code: {exit_code}",
        f"duration: {duration:.2f}s",
        f"full log: {log_path}",
        f"total lines: {total_lines}",
    ]
    if timed_out:
        lines.append(f"TIMEOUT: exceeded {timeout}s limit; process tree killed")
    return "\n".join(lines)


def ensure_log_parent(log_path):
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RunQuietError(f"cannot create log directory for {log_path}: {exc}")


def write_log(log_path, content):
    try:
        Path(log_path).write_text(content, encoding="utf-8")
    except OSError as exc:
        raise RunQuietError(f"cannot write log file {log_path}: {exc}")


# ---------------------------------------------------------------------------
# Runtime-evidence capture artifact
# ---------------------------------------------------------------------------

# Fields the TOOL owns. An agent may not supply these -- that is the whole
# integrity property of --capture: the fields a gate reads are observed, not
# authored. Compared case-insensitively.
TOOL_OWNED_FIELDS = ("probe command", "captured", "exit code", "duration", "log")


def parse_capture_field(spec):
    """Parse `Name=value`. Rejects tool-owned names and empty names."""
    if "=" not in spec:
        raise RunQuietError(
            f"invalid --capture-field value {spec!r}; expected Name=value")
    name, _, value = spec.partition("=")
    name = name.strip()
    if not name:
        raise RunQuietError(
            f"invalid --capture-field value {spec!r}; expected Name=value")
    if name.lower() in TOOL_OWNED_FIELDS:
        raise RunQuietError(
            f"--capture-field {name!r} is tool-owned and cannot be supplied; "
            "run_quiet.py records it from the actual run")
    return name, value.strip()


def fence_for(text):
    """A backtick fence longer than any run of backticks inside text."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def build_capture(fields, cmd, exit_code, duration, output, log_path, timed_out,
                   captured_at):
    """Render the capture artifact. `fields` is an ordered list of (name, value).

    `captured_at` is the sidecar's `finished` instant, not a fresh `now()`:
    the two records must be comparable downstream, and re-stamping here made
    them differ by however long the write took.
    """
    title = next((v for n, v in fields if n.lower() == "title"), None)
    body = [f"# Runtime capture: {title}" if title else "# Runtime capture", ""]
    for name, value in fields:
        if name.lower() == "title":
            continue
        body.append(f"- {name}: {value}")
    body.append(f"- Probe command: `{' '.join(cmd)}`")
    body.append(f"- Captured: {captured_at}")
    body.append(f"- Exit code: {exit_code}")
    body.append(f"- Duration: {duration:.2f}s")
    if log_path:
        body.append(f"- Log: {log_path}")
    if timed_out:
        body.append("- NOTE: probe TIMED OUT; process tree killed. This capture "
                     "records an incomplete observation.")
    fence = fence_for(output)
    body += ["", "## Captured output", "", fence, output.rstrip("\n"), fence, ""]
    return "\n".join(body)


def write_capture(capture_path, content):
    try:
        Path(capture_path).parent.mkdir(parents=True, exist_ok=True)
        Path(capture_path).write_text(content, encoding="utf-8")
    except OSError as exc:
        raise RunQuietError(f"cannot write capture file {capture_path}: {exc}")


def sidecar_path_for(capture_path):
    """`<capture filename>.meta.json`, in the capture's own directory."""
    return str(capture_path) + SIDECAR_SUFFIX


def sha256_text(text):
    """sha256 over the LF-form text (what the artifact embeds)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    """sha256 over a file's raw bytes, exactly as they landed on disk."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_sidecar(capture_path, cmd, exit_code, output, started, finished, pid):
    """The machine-owned provenance record for a capture.

    `capture_sha256` is computed from the finished file on disk, so it is
    invalidated by ANY later edit of the artifact -- including a plausible
    one. That, plus `exit_code`, is what a downstream gate can check without
    trusting a word of the capture's prose.
    """
    body = output.rstrip("\n")
    return {
        "argv": list(cmd),
        "cwd": os.getcwd(),
        "host": platform.node(),
        "pid": pid,
        "started": started,
        "finished": finished,
        "exit_code": int(exit_code),
        "body_sha256": sha256_text(body),
        "capture_sha256": sha256_file(capture_path),
        "tool": "run_quiet.py",
        "schema": SIDECAR_SCHEMA,
    }


# The header lines the downstream agreement check reads. Searched in the
# capture's HEAD only (everything before `## Captured output`), so a probe
# whose own output contains `- Exit code: 3` cannot supply either value.
CAPTURED_HEADING_RE = re.compile(
    r"(?im)^##[^\S\n]+Captured[^\S\n]+output[^\S\n]*$")
BODY_EXIT_CODE_RE = re.compile(
    r"(?im)^[^\S\n]*-[^\S\n]*Exit[^\S\n]+code[^\S\n]*:[^\S\n]*(-?\d+)[^\S\n]*$")
BODY_CAPTURED_RE = re.compile(
    r"(?im)^[^\S\n]*-[^\S\n]*Captured[^\S\n]*:[^\S\n]*(\S+)[^\S\n]*$")


def assert_capture_agrees(capture_text, meta):
    """Raise RunQuietError unless the body's header agrees with the sidecar.

    A self-check, not a gate: every downstream gate makes this comparison, so
    this tool must never be the source of a pair that fails it.
    """
    head = capture_text
    m = CAPTURED_HEADING_RE.search(capture_text)
    if m:
        head = capture_text[:m.start()]
    exit_m = BODY_EXIT_CODE_RE.search(head)
    cap_m = BODY_CAPTURED_RE.search(head)
    if exit_m is None or cap_m is None:
        raise RunQuietError(
            "internal: the rendered capture is missing a '- Exit code:' or "
            "'- Captured:' header line")
    if int(exit_m.group(1)) != int(meta["exit_code"]):
        raise RunQuietError(
            f"internal: capture body records exit code {exit_m.group(1)} but "
            f"the sidecar records {meta['exit_code']}")
    if cap_m.group(1) != meta["finished"]:
        raise RunQuietError(
            f"internal: capture body records 'Captured: {cap_m.group(1)}' but "
            f"the sidecar records 'finished': {meta['finished']}")


def write_sidecar(capture_path, meta):
    path = sidecar_path_for(capture_path)
    try:
        Path(path).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise RunQuietError(f"cannot write capture sidecar {path}: {exc}")
    return path


# ---------------------------------------------------------------------------
# Child process execution
# ---------------------------------------------------------------------------

def kill_process_tree(proc):
    """Best-effort kill of the child and any of its descendants."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), 9)  # SIGKILL
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        proc.kill()
    except OSError:
        pass


def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_child(cmd, timeout):
    """Run cmd with merged stdout+stderr. Returns (output, exit_code,
    duration_seconds, timed_out, pid, started_iso, finished_iso)."""
    kwargs = {}
    if os.name != "nt":
        kwargs["start_new_session"] = True

    started = utc_now_iso()
    start = time.monotonic()
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True,
                                 errors="replace", **kwargs)
    except (FileNotFoundError, PermissionError) as exc:
        raise RunQuietError(f"cannot run command {cmd!r}: {exc}")

    timed_out = False
    try:
        output, _ = proc.communicate(timeout=timeout)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_process_tree(proc)
        try:
            output, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            output, _ = proc.communicate()
        exit_code = 124

    duration = time.monotonic() - start
    return (output or "", exit_code, duration, timed_out, proc.pid,
            started, utc_now_iso())


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def execute(log_path, context, tail_n, timeout, cmd,
            capture_path=None, capture_fields=()):
    """Run cmd, write the full log and/or capture, build the plain-text report.

    Returns (report_text, exit_code).
    """
    if log_path:
        ensure_log_parent(log_path)
    (output, exit_code, duration, timed_out,
     pid, started, finished) = run_child(cmd, timeout)
    if log_path:
        write_log(log_path, output)
    sidecar = None
    if capture_path:
        # ONE exit code feeds both records (run_child already reports 124 for
        # a timeout), and ONE instant -- `finished` -- feeds both timestamps.
        capture_text = build_capture(
            capture_fields, cmd, exit_code, duration, output, log_path,
            timed_out, finished)
        write_capture(capture_path, capture_text)
        # Sidecar LAST: capture_sha256 is over the finished file's bytes, so
        # it can only be computed once the capture is fully written and closed.
        meta = build_sidecar(capture_path, cmd, exit_code, output,
                              started, finished, pid)
        # The pair this tool emits must satisfy the same agreement every gate
        # downstream checks; a disagreement written here would be
        # indistinguishable from a tampered sidecar.
        assert_capture_agrees(capture_text, meta)
        sidecar = write_sidecar(capture_path, meta)

    lines = output.splitlines()
    report = [format_header(cmd, exit_code, duration, log_path or capture_path,
                             len(lines), timed_out, timeout)]
    if capture_path:
        report.append(f"capture:     {capture_path}")
        report.append(f"sidecar:     {sidecar}")

    indices = find_matches(lines)
    if indices:
        report.append("")
        report.append(f"ERROR EXCERPT (context +/-{context} lines):")
        report.extend(format_excerpt(lines, indices, context, log_path))
    elif exit_code == 0:
        report.append("")
        report.append("no errors detected")

    report.append("")
    report.append(f"TAIL (last {tail_n} lines):")
    report.extend(format_tail(lines, tail_n))

    return "\n".join(report), (124 if timed_out else exit_code)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="run_quiet.py",
        description="Run a command, log the full output, print only "
                     "errors-with-context + tail.")
    parser.add_argument("--log", help="path to write the full merged log to")
    parser.add_argument("--context", type=int, default=DEFAULT_CONTEXT,
                         help=f"context lines around each match (default {DEFAULT_CONTEXT})")
    parser.add_argument("--tail", type=int, default=DEFAULT_TAIL,
                         help=f"lines in the tail section (default {DEFAULT_TAIL})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                         help=f"child timeout in seconds (default {DEFAULT_TIMEOUT})")
    parser.add_argument("--capture",
                         help="also write a runtime-evidence capture artifact here")
    parser.add_argument("--capture-field", action="append", default=[],
                         metavar="Name=value",
                         help="descriptive header field for --capture (repeatable)")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    flags_argv, cmd = split_argv(argv)
    args = build_parser().parse_args(flags_argv)

    if args.self_test:
        return run_self_test()

    try:
        if not args.log and not args.capture:
            raise RunQuietError("one of --log or --capture is required")
        if args.capture_field and not args.capture:
            raise RunQuietError("--capture-field requires --capture")
        if not cmd:
            raise RunQuietError("no command given after '--'")
        capture_fields = [parse_capture_field(s) for s in args.capture_field]
        report_text, exit_code = execute(args.log, args.context, args.tail,
                                          args.timeout, cmd,
                                          args.capture, capture_fields)
    except RunQuietError as exc:
        print(f"run_quiet: {exc}", file=sys.stderr)
        return 2

    print(report_text)
    return exit_code


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import contextlib
    import io
    import shutil
    import tempfile
    import unittest

    class RunQuietTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.log = self.dir / "sub" / "run.log"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _run(self, extra_flags, cmd):
            argv = ["--log", str(self.log)] + extra_flags + ["--"] + cmd
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(argv)
            return code, buf.getvalue()

        def _run_raw(self, argv):
            """main() with a fully-explicit argv (no implicit --log)."""
            buf, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
                code = main(argv)
            return code, buf.getvalue() + err.getvalue()

        def test_passing_command_reports_no_errors(self):
            cmd = [sys.executable, "-c", "print('all good')"]
            code, out = self._run([], cmd)
            self.assertEqual(code, 0)
            self.assertIn("no errors detected", out)
            self.assertTrue(self.log.is_file())
            self.assertIn("all good", self.log.read_text(encoding="utf-8"))

        def test_failing_command_excerpt_has_context_not_far_noise(self):
            script = (
                "for i in range(50):\n"
                "    print('noise %d' % i)\n"
                "print('error CS1002: unexpected token')\n"
                "for i in range(50, 100):\n"
                "    print('noise %d' % i)\n"
                "raise SystemExit(1)\n"
            )
            cmd = [sys.executable, "-c", script]
            code, out = self._run(["--context", "5"], cmd)
            self.assertEqual(code, 1)
            self.assertIn("error CS1002", out)
            # +/-5 context around the match (0-based index 50) must be present
            for n in (45, 46, 47, 48, 49, 50, 51, 52, 53, 54):
                self.assertIn(f"noise {n}", out)
            # noise well outside both the context window and the tail
            # (indices 0..44 minus the last `--tail` lines) must be absent
            # from stdout...
            self.assertNotIn("noise 0\n", out)
            self.assertNotIn("noise 20", out)
            # ...but must still be in the full log on disk
            log_text = self.log.read_text(encoding="utf-8")
            self.assertIn("noise 0", log_text)
            self.assertIn("noise 20", log_text)
            self.assertIn("noise 99", log_text)

        def test_tail_is_last_n_lines(self):
            script = "\n".join(f"print('line {i}')" for i in range(30))
            cmd = [sys.executable, "-c", script]
            code, out = self._run(["--tail", "3"], cmd)
            self.assertEqual(code, 0)
            tail_section = out.split("TAIL (last 3 lines):", 1)[1]
            self.assertIn("line 27", tail_section)
            self.assertIn("line 28", tail_section)
            self.assertIn("line 29", tail_section)
            self.assertNotIn("line 26", tail_section)

        def test_timeout_kills_and_exits_124(self):
            cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
            start = time.monotonic()
            code, out = self._run(["--timeout", "2"], cmd)
            elapsed = time.monotonic() - start
            self.assertEqual(code, 124)
            self.assertIn("TIMEOUT", out)
            self.assertLess(elapsed, 20)  # killed well before the 30s sleep

        # ---- --capture (runtime-evidence artifact) ----

        def test_capture_writes_artifact_with_observed_fields(self):
            cap = self.dir / "evidence" / "runtime" / "m1-probe.md"
            cmd = [sys.executable, "-c", "print('{\"isSuccess\": true}')"]
            code, out = self._run_raw([
                "--capture", str(cap),
                "--capture-field", "Title=GET /api/orders",
                "--capture-field", "Milestone=M1 — Orders [API] [vs:api]",
                "--capture-field", "Transport=out-of-process HTTP",
                "--", *cmd])
            self.assertEqual(code, 0)
            self.assertTrue(cap.is_file())
            text = cap.read_text(encoding="utf-8")
            self.assertIn("# Runtime capture: GET /api/orders", text)
            self.assertIn("- Milestone: M1 — Orders [API] [vs:api]", text)
            self.assertIn("- Transport: out-of-process HTTP", text)
            self.assertIn("- Exit code: 0", text)
            self.assertIn("## Captured output", text)
            self.assertIn('{"isSuccess": true}', text)
            # the tool stamps the timestamp itself
            self.assertRegex(text, r"- Captured: \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
            self.assertIn(str(cap), out)

        # ---- sidecar (machine-owned provenance) ----

        def _sidecar(self, cap):
            return json.loads(
                Path(sidecar_path_for(cap)).read_text(encoding="utf-8"))

        def test_sidecar_written_beside_capture_with_full_schema(self):
            cap = self.dir / "evidence" / "runtime" / "m1-probe.md"
            code, out = self._run_raw([
                "--capture", str(cap), "--",
                sys.executable, "-c", "print('{\"isSuccess\": true}')"])
            self.assertEqual(code, 0)
            side = Path(sidecar_path_for(cap))
            self.assertTrue(side.is_file())
            self.assertEqual(side.name, cap.name + ".meta.json")
            meta = self._sidecar(cap)
            for key in ("argv", "cwd", "host", "pid", "started", "finished",
                         "exit_code", "body_sha256", "capture_sha256",
                         "tool", "schema"):
                self.assertIn(key, meta)
            self.assertEqual(meta["tool"], "run_quiet.py")
            self.assertEqual(meta["schema"], 1)
            self.assertEqual(meta["exit_code"], 0)
            self.assertEqual(meta["argv"][0], sys.executable)
            self.assertIsInstance(meta["pid"], int)
            for stamp in (meta["started"], meta["finished"]):
                self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertIn(str(side), out)   # surfaced in the stdout summary

        def test_sidecar_hashes_match_the_written_artifacts(self):
            cap = self.dir / "c.md"
            self._run_raw(["--capture", str(cap), "--",
                            sys.executable, "-c", "print('hello body')"])
            meta = self._sidecar(cap)
            self.assertEqual(meta["capture_sha256"], sha256_file(cap))
            self.assertEqual(meta["body_sha256"], sha256_text("hello body"))

        def test_editing_the_capture_invalidates_capture_sha256(self):
            """The point of the hash: a plausible later edit is still detectable."""
            cap = self.dir / "c.md"
            self._run_raw(["--capture", str(cap), "--",
                            sys.executable, "-c", "print('x')"])
            meta = self._sidecar(cap)
            cap.write_text(cap.read_text(encoding="utf-8").replace(
                "- Exit code: 0", "- Exit code: 0 "), encoding="utf-8")
            self.assertNotEqual(meta["capture_sha256"], sha256_file(cap))

        # ---- body/sidecar agreement (the flipped-sidecar attack) ----

        def test_body_captured_equals_the_sidecar_finished_exactly(self):
            """The header line is stamped FROM `finished`, not re-stamped."""
            cap = self.dir / "c.md"
            self._run_raw(["--capture", str(cap), "--",
                            sys.executable, "-c", "print('x')"])
            meta = self._sidecar(cap)
            self.assertIn(f"- Captured: {meta['finished']}",
                          cap.read_text(encoding="utf-8"))

        def test_body_exit_code_equals_the_sidecar_exit_code(self):
            cap = self.dir / "c.md"
            self._run_raw(["--capture", str(cap), "--",
                            sys.executable, "-c", "raise SystemExit(3)"])
            meta = self._sidecar(cap)
            self.assertEqual(meta["exit_code"], 3)
            self.assertIn("- Exit code: 3", cap.read_text(encoding="utf-8"))

        def test_timeout_pair_still_agrees(self):
            cap = self.dir / "c.md"
            self._run_raw(["--capture", str(cap), "--timeout", "2", "--",
                            sys.executable, "-c", "import time; time.sleep(30)"])
            meta = self._sidecar(cap)
            text = cap.read_text(encoding="utf-8")
            self.assertIn("- Exit code: 124", text)
            self.assertIn(f"- Captured: {meta['finished']}", text)
            assert_capture_agrees(text, meta)   # raises if it does not

        def test_assert_capture_agrees_rejects_a_flipped_exit_code(self):
            """The attack the downstream gates gained a code for."""
            cap = self.dir / "c.md"
            self._run_raw(["--capture", str(cap), "--",
                            sys.executable, "-c", "raise SystemExit(3)"])
            meta = self._sidecar(cap)
            meta["exit_code"] = 0
            with self.assertRaises(RunQuietError):
                assert_capture_agrees(cap.read_text(encoding="utf-8"), meta)

        def test_assert_capture_agrees_rejects_an_edited_timestamp(self):
            cap = self.dir / "c.md"
            self._run_raw(["--capture", str(cap), "--",
                            sys.executable, "-c", "print('x')"])
            meta = self._sidecar(cap)
            meta["finished"] = "2099-01-01T00:00:00Z"
            with self.assertRaises(RunQuietError):
                assert_capture_agrees(cap.read_text(encoding="utf-8"), meta)

        def test_assert_capture_agrees_ignores_header_lines_in_the_output(self):
            """A probe that PRINTS `- Exit code: 3` supplies nothing."""
            cap = self.dir / "c.md"
            self._run_raw(["--capture", str(cap), "--", sys.executable, "-c",
                            "print('- Exit code: 3'); print('- Captured: 1999-01-01T00:00:00Z')"])
            meta = self._sidecar(cap)
            assert_capture_agrees(cap.read_text(encoding="utf-8"), meta)

        def test_assert_capture_agrees_rejects_a_headerless_capture(self):
            with self.assertRaises(RunQuietError):
                assert_capture_agrees(
                    "# Runtime capture\n\n## Captured output\n\n```\nok\n```\n",
                    {"exit_code": 0, "finished": "2026-09-04T00:00:00Z"})

        def test_sidecar_records_real_nonzero_exit(self):
            cap = self.dir / "c.md"
            code, _ = self._run_raw(["--capture", str(cap), "--",
                                      sys.executable, "-c", "raise SystemExit(7)"])
            self.assertEqual(code, 7)
            self.assertEqual(self._sidecar(cap)["exit_code"], 7)

        def test_sidecar_records_124_on_timeout(self):
            cap = self.dir / "c.md"
            code, _ = self._run_raw([
                "--capture", str(cap), "--timeout", "2", "--",
                sys.executable, "-c", "import time; time.sleep(30)"])
            self.assertEqual(code, 124)
            self.assertEqual(self._sidecar(cap)["exit_code"], 124)

        def test_no_sidecar_when_only_log_requested(self):
            code, _ = self._run([], [sys.executable, "-c", "print('x')"])
            self.assertEqual(code, 0)
            self.assertFalse(Path(sidecar_path_for(self.log)).exists())

        def test_capture_records_real_nonzero_exit(self):
            cap = self.dir / "evidence" / "runtime" / "m1-fail.md"
            cmd = [sys.executable, "-c", "raise SystemExit(7)"]
            code, _ = self._run_raw(["--capture", str(cap), "--", *cmd])
            self.assertEqual(code, 7)
            self.assertIn("- Exit code: 7", cap.read_text(encoding="utf-8"))

        def test_capture_field_cannot_forge_a_tool_owned_field(self):
            cap = self.dir / "c.md"
            for forged in ("Exit code=0", "Captured=1999-01-01T00:00:00Z",
                            "Probe command=`curl real-thing`", "exit CODE=0"):
                code, out = self._run_raw([
                    "--capture", str(cap), "--capture-field", forged,
                    "--", sys.executable, "-c", "pass"])
                self.assertEqual(code, 2, forged)
                self.assertIn("tool-owned", out)
                self.assertFalse(cap.exists(), forged)

        def test_capture_field_without_capture_exits_2(self):
            code, out = self._run_raw([
                "--log", str(self.log), "--capture-field", "Surface=api",
                "--", sys.executable, "-c", "pass"])
            self.assertEqual(code, 2)
            self.assertIn("--capture-field requires --capture", out)

        def test_malformed_capture_field_exits_2(self):
            code, out = self._run_raw([
                "--capture", str(self.dir / "c.md"), "--capture-field", "nokey",
                "--", sys.executable, "-c", "pass"])
            self.assertEqual(code, 2)
            self.assertIn("expected Name=value", out)

        def test_fence_survives_backticks_in_output(self):
            cap = self.dir / "c.md"
            cmd = [sys.executable, "-c", "print('a ``` b ```` c')"]
            code, _ = self._run_raw(["--capture", str(cap), "--", *cmd])
            self.assertEqual(code, 0)
            text = cap.read_text(encoding="utf-8")
            # fence must be longer than the longest backtick run in the body
            self.assertIn("`````", text)
            self.assertIn("a ``` b ```` c", text)

        def test_neither_log_nor_capture_exits_2(self):
            code, out = self._run_raw(["--", sys.executable, "-c", "pass"])
            self.assertEqual(code, 2)
            self.assertIn("one of --log or --capture", out)

        def test_capture_and_log_together_record_log_path(self):
            cap = self.dir / "c.md"
            code, _ = self._run_raw([
                "--log", str(self.log), "--capture", str(cap),
                "--", sys.executable, "-c", "print('x')"])
            self.assertEqual(code, 0)
            self.assertTrue(self.log.is_file())
            self.assertIn(f"- Log: {self.log}", cap.read_text(encoding="utf-8"))

        def test_missing_command_exits_2(self):
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                code = main(["--log", str(self.log)])
            self.assertEqual(code, 2)

        def test_unwritable_log_path_exits_2(self):
            # A path through a file (not a directory) can never be created.
            blocker = self.dir / "blocker"
            blocker.write_text("x")
            bad_log = blocker / "run.log"
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                code = main(["--log", str(bad_log), "--",
                             sys.executable, "-c", "print('hi')"])
            self.assertEqual(code, 2)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RunQuietTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
