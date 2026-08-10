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
    python run_quiet.py --self-test

Pure standard library. Cross-platform (Windows/POSIX).
"""
import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

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


def run_child(cmd, timeout):
    """Run cmd with merged stdout+stderr. Returns (output, exit_code,
    duration_seconds, timed_out)."""
    kwargs = {}
    if os.name != "nt":
        kwargs["start_new_session"] = True

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
    return output or "", exit_code, duration, timed_out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def execute(log_path, context, tail_n, timeout, cmd):
    """Run cmd, write the full log, build the plain-text report.

    Returns (report_text, exit_code).
    """
    ensure_log_parent(log_path)
    output, exit_code, duration, timed_out = run_child(cmd, timeout)
    write_log(log_path, output)

    lines = output.splitlines()
    report = [format_header(cmd, exit_code, duration, log_path, len(lines),
                             timed_out, timeout)]

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
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    flags_argv, cmd = split_argv(argv)
    args = build_parser().parse_args(flags_argv)

    if args.self_test:
        return run_self_test()

    try:
        if not args.log:
            raise RunQuietError("--log is required")
        if not cmd:
            raise RunQuietError("no command given after '--'")
        report_text, exit_code = execute(args.log, args.context, args.tail,
                                          args.timeout, cmd)
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
