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
        [--log <path>] [--full-body] [--ledger <path>] \
        [--milestone "<title>"] -- <command and args...>
    python run_quiet.py --self-test

`--capture` additionally writes a conforming runtime-evidence capture
artifact (contract: runtime-evidence/SKILL.md). The tool owns the
load-bearing fields -- probe command, timestamp, exit code, duration, the
log path/hash and the captured output -- so an agent cannot author them;
`--capture-field` supplies only the descriptive header (milestone, surface,
transport, base URL, environment). A field name the tool owns is rejected,
not overwritten.

By default the capture's `## Captured output` embeds an EXCERPT -- the same
error-profile lines with context, plus a tail, that `--log` prints to the
terminal -- capped at ~200 lines, not the full child output (a 130KB Vite
chunk-list embedded whole in a quick-lane capture is the failure mode this
closes: an Orchestrator reading a check.md should not pay 32k tokens for
build noise). The FULL merged output always goes to a log file on disk:
`--log <path>` if given, else a sibling `<capture path>.log`. Pass
`--full-body` to embed the full output in the capture instead, for the rare
probe whose entire output IS the evidence (a small JSON response, a short
`curl -i`) -- recorded as `full_body: true` in the sidecar.

A `## Summary` section, above `## Captured output`, carries the per-runner
summary line(s) this tool recognises (dotnet test, MSBuild, vitest/jest,
pytest, Playwright), or `Summary: none recognised (exit <code>)` when
nothing matches. The same line(s) print FIRST on stdout, ahead of the
header, in both `--log` and `--capture` runs -- a green test run should not
force the reader to go find the pass/fail count in the tail.

`--capture` ALSO writes `<capture path>.meta.json`, a machine-owned sidecar
recording the child argv, cwd, host, pid, start/finish instants, the real
exit code, and four hash/path fields: `body_sha256` over the captured text
as embedded in the artifact (the excerpt by default, the full output under
`--full-body`), `capture_sha256` over the finished capture FILE bytes, and
`log_sha256`/`log_path` over/naming the FULL log file on disk -- so the
excerpt's omissions are still hash-anchored to something. The sidecar is
what makes a hand-typed capture detectable downstream --
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
can never be the thing that emits a disagreeing pair. `log_sha256` gives the
same file-bytes guarantee to the full log that `capture_sha256` gives the
capture -- an edited log is detectable, even though nothing downstream
requires it yet.

WHAT THE PAIR STILL CANNOT SAY, AND WHAT `--ledger` ADDS
--------------------------------------------------------
Everything above proves the capture and its sidecar are consistent WITH EACH
OTHER. It does not prove a command ever ran: both files are plain text, both
hashes are unkeyed sha256 over content anyone can produce, so a short script
writes a mutually-consistent pair for a run that never happened, and every
reader of the pair alone passes it (SKILL.md § The unkeyed-sidecar limit).

`--ledger <path>` closes the omission half of that gap. After a `--capture`
completes, this tool appends ONE hash-chained record -- `gate:
"run_quiet.py"`, `verdict: "CAPTURED"`, the child's `exit`, the capture and
sidecar paths hashed under `inputs`, plus `command_argv` and `capture_sha256`
-- to the shared gate ledger, using the same chained `append_ledger` every
gate in this family writes. A reader (`check_agent_report.py`,
`check_runtime_evidence.py`, `check_ship_decision.py`) can then look a
capture's current sha256 up in that ledger and tell an OBSERVED capture from
an authored one: a forger must now also append a chained ledger line, in a
file `check_ledger.py` walks and `check_commit_gate.py --require-ledger-gates`
re-hashes. It does not make forgery impossible -- the ledger is unkeyed too --
it makes it a larger written act. `--milestone` scopes the record the way
every other gate's does. Without `--ledger`, behavior is unchanged.

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
SIDECAR_SCHEMA = 2

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

# Per-runner summary-line patterns. Each is checked independently; matches
# from every pattern are merged and ordered by where they appear in the
# output, so a run that mixes runners (rare, but MSBuild-then-tests is not)
# still reads top to bottom. A summary line is printed FIRST, ahead of the
# header, so "N passed, M failed" never requires hunting through the tail.
SUMMARY_LINE_PATTERNS = [
    re.compile(r"(?m)^[ \t]*(?:Passed|Failed)!.*$"),          # dotnet test result
    re.compile(r"(?m)^[ \t]*Total tests:.*$"),                # dotnet test (older) totals block
    re.compile(r"(?m)^[ \t]*\d+\s+Warning\(s\)[ \t]*$"),      # MSBuild
    re.compile(r"(?m)^[ \t]*\d+\s+Error\(s\)[ \t]*$"),        # MSBuild
    re.compile(r"(?m)^[ \t]*Build (?:succeeded|FAILED)\.[ \t]*$"),  # MSBuild
    re.compile(r"(?m)^[ \t]*Tests:.*$"),                      # vitest
    re.compile(r"(?m)^[ \t]*Test Files.*$"),                  # vitest
    re.compile(r"(?m)^[ \t]*Test Suites:.*$"),                # jest
    re.compile(r"(?m)^[ \t]*=+[ \t].*\b\d+\s+(?:passed|failed|error|skipped)\b.*=+[ \t]*$",
               re.IGNORECASE),                                # pytest
    re.compile(r"(?m)^[ \t]*\d+\s+(?:passed|failed|flaky)\b.*$"),  # Playwright
]


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


def extract_summary_lines(text):
    """Every per-runner summary line found in `text`, in file order, deduped.

    Each SUMMARY_LINE_PATTERNS entry is matched independently; hits are
    merged and sorted by position so a run that touches more than one
    runner still reads top to bottom.
    """
    hits = []
    for pattern in SUMMARY_LINE_PATTERNS:
        for m in pattern.finditer(text):
            hits.append((m.start(), m.group(0).strip()))
    hits.sort(key=lambda h: h[0])
    seen, out = set(), []
    for _, line in hits:
        if line not in seen:
            seen.add(line)
            out.append(line)
    return out


def build_summary_lines(output, exit_code):
    """The lines to print/embed under `Summary:` -- recognised runner
    summaries, or a single explicit "none recognised" line."""
    lines = extract_summary_lines(output)
    if lines:
        return lines
    return [f"none recognised (exit {exit_code})"]


def build_output_section(lines, indices, context, tail_n, log_path, exit_code,
                          cap=EXCERPT_CAP):
    """The ERROR EXCERPT (or 'no errors detected') + TAIL block.

    Shared by the terminal report (both --log and --capture runs) and the
    default (excerpt) --capture body, so the two are always the same text.
    """
    section = []
    if indices:
        section.append(f"ERROR EXCERPT (context +/-{context} lines):")
        section.extend(format_excerpt(lines, indices, context, log_path, cap))
    elif exit_code == 0:
        section.append("no errors detected")
    section.append("")
    section.append(f"TAIL (last {tail_n} lines):")
    section.extend(format_tail(lines, tail_n))
    return section


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
TOOL_OWNED_FIELDS = ("probe command", "captured", "exit code", "duration", "log",
                     "log sha256")


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


def build_capture(fields, cmd, exit_code, duration, log_path, log_sha256,
                   embedded_body, summary_lines, timed_out, captured_at):
    """Render the capture artifact. `fields` is an ordered list of (name, value).

    `captured_at` is the sidecar's `finished` instant, not a fresh `now()`:
    the two records must be comparable downstream, and re-stamping here made
    them differ by however long the write took.

    `embedded_body` is what lands under `## Captured output` -- the excerpt
    block by default, or the full raw output under `--full-body`. `log_path`
    (the FULL log on disk) and `log_sha256` are unconditional: --capture
    always determines a log path, explicit or a sibling `<capture>.log`.
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
    body.append(f"- Log: {log_path}")
    body.append(f"- Log sha256: {log_sha256}")
    if timed_out:
        body.append("- NOTE: probe TIMED OUT; process tree killed. This capture "
                     "records an incomplete observation.")
    body += ["", "## Summary", ""]
    for line in summary_lines:
        body.append(f"Summary: {line}")
    fence = fence_for(embedded_body)
    body += ["", "## Captured output", "", fence, embedded_body.rstrip("\n"), fence, ""]
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


LOG_SUFFIX = ".log"


def log_path_for_capture(capture_path):
    """`<capture filename>.log`, the sibling log used when --log is omitted."""
    return str(capture_path) + LOG_SUFFIX


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


def build_sidecar(capture_path, cmd, exit_code, embedded_body, started, finished,
                   pid, log_sha256, log_path, full_body):
    """The machine-owned provenance record for a capture.

    `capture_sha256` is computed from the finished file on disk, so it is
    invalidated by ANY later edit of the artifact -- including a plausible
    one. That, plus `exit_code`, is what a downstream gate can check without
    trusting a word of the capture's prose. `body_sha256` is over
    `embedded_body` -- the excerpt by default, the full output under
    `--full-body` (`full_body` records which) -- not the full child output.
    `log_sha256` gives the same file-bytes guarantee to the FULL log on disk
    that `capture_sha256` gives the capture.
    """
    body = embedded_body.rstrip("\n")
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
        "log_sha256": log_sha256,
        "log_path": log_path,
        "full_body": bool(full_body),
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


# ---------------------------------------------------------------------------
# Gate ledger (the chained record that says this capture was TAKEN, not typed)
#
# Copied byte-identical from check_handoff.py per this family's one-file
# convention -- check_ledger.py's drift guard compares the three helpers below
# across every script that carries them.
# ---------------------------------------------------------------------------

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
    """Append ONE JSON line recording this run. Best-effort by design.

    `extra` merges into the record BEFORE `prev`/`self` are computed, so the
    chain covers it: a capture records `command_argv` and `capture_sha256`,
    which is the field a reader looks a capture up by.
    """
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
        record["prev"] = ledger_prev_hash(p)
        record["self"] = ledger_self_hash(record)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


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
            capture_path=None, capture_fields=(), full_body=False,
            ledger=None, milestone=None, own_argv=()):
    """Run cmd, write the full log and/or capture, build the plain-text report.

    The FULL merged output always lands on disk: at `log_path` if given, else
    (when only `capture_path` is given) at a sibling `<capture_path>.log`.
    The capture body embeds an excerpt of that output by default, or the
    full output when `full_body` is set.

    With `ledger`, ONE chained record is appended after the capture and its
    sidecar are on disk -- last, so `inputs` hashes both files as they finally
    landed.

    Returns (report_text, exit_code).
    """
    effective_log = log_path or (
        log_path_for_capture(capture_path) if capture_path else None)
    if effective_log:
        ensure_log_parent(effective_log)
    (output, exit_code, duration, timed_out,
     pid, started, finished) = run_child(cmd, timeout)
    if effective_log:
        write_log(effective_log, output)
    log_sha256 = sha256_file(effective_log) if effective_log else None

    lines = output.splitlines()
    indices = find_matches(lines)
    summary_lines = build_summary_lines(output, exit_code)

    sidecar = None
    if capture_path:
        embedded_body = output if full_body else "\n".join(
            build_output_section(lines, indices, context, tail_n,
                                  effective_log, exit_code))
        # ONE exit code feeds both records (run_child already reports 124 for
        # a timeout), and ONE instant -- `finished` -- feeds both timestamps.
        capture_text = build_capture(
            capture_fields, cmd, exit_code, duration, effective_log,
            log_sha256, embedded_body, summary_lines, timed_out, finished)
        write_capture(capture_path, capture_text)
        # Sidecar LAST: capture_sha256 is over the finished file's bytes, so
        # it can only be computed once the capture is fully written and closed.
        meta = build_sidecar(capture_path, cmd, exit_code, embedded_body,
                              started, finished, pid, log_sha256,
                              effective_log, full_body)
        # The pair this tool emits must satisfy the same agreement every gate
        # downstream checks; a disagreement written here would be
        # indistinguishable from a tampered sidecar.
        assert_capture_agrees(capture_text, meta)
        sidecar = write_sidecar(capture_path, meta)
        # LAST, and only for a capture: the record says this artifact was
        # observed, so it must hash the artifact exactly as it now stands.
        append_ledger(ledger, own_argv, milestone,
                      [capture_path, sidecar], "CAPTURED", exit_code,
                      extra={"command_argv": list(cmd),
                             "capture_sha256": meta["capture_sha256"]})

    report = [f"Summary: {line}" for line in summary_lines]
    report.append("")
    report.append(format_header(cmd, exit_code, duration, effective_log,
                                 len(lines), timed_out, timeout))
    if capture_path:
        report.append(f"capture:     {capture_path}")
        report.append(f"sidecar:     {sidecar}")

    report.append("")
    report.extend(build_output_section(lines, indices, context, tail_n,
                                        effective_log, exit_code))

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
    parser.add_argument("--full-body", action="store_true",
                         help="embed the full raw output in --capture instead of "
                              "the default error-excerpt + tail")
    parser.add_argument("--ledger",
                         help="append ONE chained record for this --capture to "
                              "the shared gate ledger, so a reader can tell an "
                              "OBSERVED capture from an authored one (requires "
                              "--capture)")
    parser.add_argument("--milestone",
                         help="scope this capture's ledger record to a milestone "
                              "(requires --capture)")
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
        if args.full_body and not args.capture:
            raise RunQuietError("--full-body requires --capture")
        if args.ledger and not args.capture:
            raise RunQuietError("--ledger requires --capture (the record is "
                                 "about a capture; a --log-only run writes none)")
        if args.milestone and not args.capture:
            raise RunQuietError("--milestone requires --capture")
        if not cmd:
            raise RunQuietError("no command given after '--'")
        capture_fields = [parse_capture_field(s) for s in args.capture_field]
        report_text, exit_code = execute(args.log, args.context, args.tail,
                                          args.timeout, cmd,
                                          args.capture, capture_fields,
                                          args.full_body,
                                          args.ledger, args.milestone, argv)
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

    # Pulls the text between the capture's fence markers, whatever their
    # exact backtick count (fence_for varies it with the content).
    CAPTURE_BODY_RE = re.compile(r"## Captured output\n\n`{3,}\n(.*?)\n`{3,}\n", re.S)

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
                         "log_sha256", "log_path", "full_body",
                         "tool", "schema"):
                self.assertIn(key, meta)
            self.assertEqual(meta["tool"], "run_quiet.py")
            self.assertEqual(meta["schema"], 2)
            self.assertEqual(meta["exit_code"], 0)
            self.assertEqual(meta["argv"][0], sys.executable)
            self.assertIsInstance(meta["pid"], int)
            self.assertFalse(meta["full_body"])
            for stamp in (meta["started"], meta["finished"]):
                self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertIn(str(side), out)   # surfaced in the stdout summary

        def test_sidecar_hashes_match_the_written_artifacts(self):
            """`--full-body` restores the old contract: body_sha256 over the
            raw output verbatim -- the rare probe whose whole output IS the
            evidence."""
            cap = self.dir / "c.md"
            self._run_raw(["--capture", str(cap), "--full-body", "--",
                            sys.executable, "-c", "print('hello body')"])
            meta = self._sidecar(cap)
            self.assertEqual(meta["capture_sha256"], sha256_file(cap))
            self.assertEqual(meta["body_sha256"], sha256_text("hello body"))
            self.assertTrue(meta["full_body"])

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

        # ---- excerpt body (default) vs --full-body ----

        def _noisy_script(self):
            return (
                "for i in range(50):\n"
                "    print('noise %d' % i)\n"
                "print('error CS1002: unexpected token')\n"
                "for i in range(50, 100):\n"
                "    print('noise %d' % i)\n"
                "raise SystemExit(1)\n"
            )

        def test_default_capture_body_is_excerpt_not_full_output(self):
            cap = self.dir / "c.md"
            cmd = [sys.executable, "-c", self._noisy_script()]
            code, _ = self._run_raw(["--capture", str(cap), "--", *cmd])
            self.assertEqual(code, 1)
            text = cap.read_text(encoding="utf-8")
            self.assertIn("ERROR EXCERPT", text)
            self.assertIn("error CS1002", text)
            self.assertNotIn("noise 0\n", text)     # far outside excerpt+tail
            self.assertNotIn("noise 20", text)
            meta = self._sidecar(cap)
            self.assertFalse(meta["full_body"])
            body = CAPTURE_BODY_RE.search(text).group(1)
            self.assertEqual(meta["body_sha256"], sha256_text(body))
            # the full output is still on disk, uncut
            log_text = Path(meta["log_path"]).read_text(encoding="utf-8")
            self.assertIn("noise 0", log_text)
            self.assertIn("noise 20", log_text)

        def test_full_body_flag_restores_full_output(self):
            cap = self.dir / "c.md"
            cmd = [sys.executable, "-c", self._noisy_script()]
            code, _ = self._run_raw(
                ["--capture", str(cap), "--full-body", "--", *cmd])
            self.assertEqual(code, 1)
            text = cap.read_text(encoding="utf-8")
            self.assertIn("noise 0", text)
            self.assertIn("noise 20", text)
            self.assertIn("noise 99", text)
            meta = self._sidecar(cap)
            self.assertTrue(meta["full_body"])
            body = CAPTURE_BODY_RE.search(text).group(1)
            self.assertEqual(meta["body_sha256"], sha256_text(body))

        # ---- log: always written, always hashed ----

        def test_capture_without_log_writes_sibling_log_file(self):
            cap = self.dir / "evidence" / "runtime" / "c.md"
            cmd = [sys.executable, "-c", self._noisy_script()]
            code, _ = self._run_raw(["--capture", str(cap), "--", *cmd])
            self.assertEqual(code, 1)
            sibling = Path(log_path_for_capture(cap))
            self.assertTrue(sibling.is_file())
            log_text = sibling.read_text(encoding="utf-8")
            self.assertIn("noise 0", log_text)     # full output, unlike the excerpt
            self.assertIn(f"- Log: {sibling}", cap.read_text(encoding="utf-8"))

        def test_log_sha256_matches_the_full_log_file(self):
            cap = self.dir / "c.md"
            code, _ = self._run_raw([
                "--log", str(self.log), "--capture", str(cap), "--",
                sys.executable, "-c", "print('hello')"])
            self.assertEqual(code, 0)
            meta = self._sidecar(cap)
            self.assertEqual(meta["log_sha256"], sha256_file(self.log))
            self.assertEqual(meta["log_path"], str(self.log))
            self.assertIn(f"- Log sha256: {meta['log_sha256']}",
                          cap.read_text(encoding="utf-8"))

        # ---- --ledger: the record that says this capture was TAKEN ----

        def _ledger(self, path):
            return [json.loads(l) for l in
                    Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

        def test_ledger_record_appended_for_a_capture(self):
            cap = self.dir / "evidence" / "runtime" / "c.md"
            led = self.dir / "logs" / "gates.jsonl"
            code, _ = self._run_raw([
                "--capture", str(cap), "--ledger", str(led),
                "--milestone", "M1 — Orders [API]",
                "--", sys.executable, "-c", "print('x')"])
            self.assertEqual(code, 0)
            records = self._ledger(led)
            self.assertEqual(len(records), 1)
            rec = records[0]
            self.assertEqual(rec["gate"], "run_quiet.py")
            self.assertEqual(rec["verdict"], "CAPTURED")
            self.assertEqual(rec["exit"], 0)
            self.assertEqual(rec["milestone"], "M1 — Orders [API]")
            self.assertEqual(rec["command_argv"][0], sys.executable)
            self.assertRegex(rec["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

        def test_ledger_record_pins_the_capture_and_its_sidecar(self):
            """The lookup key downstream: capture_sha256 as it landed on disk."""
            cap = self.dir / "c.md"
            led = self.dir / "gates.jsonl"
            self._run_raw(["--capture", str(cap), "--ledger", str(led), "--",
                            sys.executable, "-c", "print('x')"])
            rec = self._ledger(led)[0]
            meta = self._sidecar(cap)
            self.assertEqual(rec["capture_sha256"], meta["capture_sha256"])
            self.assertEqual(rec["capture_sha256"], sha256_file(cap))
            self.assertEqual(rec["inputs"][str(cap)], sha256_file(cap))
            side = sidecar_path_for(cap)
            self.assertEqual(rec["inputs"][side], sha256_file(side))

        def test_ledger_record_is_chained(self):
            cap = self.dir / "c.md"
            led = self.dir / "gates.jsonl"
            for _ in range(2):
                self._run_raw(["--capture", str(cap), "--ledger", str(led), "--",
                                sys.executable, "-c", "print('x')"])
            lines = [l for l in Path(led).read_text(encoding="utf-8").splitlines()
                      if l.strip()]
            first, second = json.loads(lines[0]), json.loads(lines[1])
            self.assertEqual(first["prev"], "genesis")
            self.assertEqual(second["prev"], ledger_line_hash(lines[0].encode()))
            for rec in (first, second):
                self.assertEqual(rec["self"], ledger_self_hash(rec))

        def test_ledger_records_the_childs_real_nonzero_exit(self):
            cap = self.dir / "c.md"
            led = self.dir / "gates.jsonl"
            code, _ = self._run_raw([
                "--capture", str(cap), "--ledger", str(led), "--",
                sys.executable, "-c", "raise SystemExit(3)"])
            self.assertEqual(code, 3)
            self.assertEqual(self._ledger(led)[0]["exit"], 3)

        def test_no_ledger_file_when_the_flag_is_absent(self):
            """Without --ledger, behavior is unchanged."""
            cap = self.dir / "c.md"
            self._run_raw(["--capture", str(cap), "--",
                            sys.executable, "-c", "print('x')"])
            self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                             ["c.md", "c.md.log", "c.md.meta.json"])

        def test_ledger_without_capture_exits_2(self):
            code, out = self._run_raw([
                "--log", str(self.log), "--ledger", str(self.dir / "g.jsonl"),
                "--", sys.executable, "-c", "pass"])
            self.assertEqual(code, 2)
            self.assertIn("--ledger requires --capture", out)
            self.assertFalse((self.dir / "g.jsonl").exists())

        def test_milestone_without_capture_exits_2(self):
            code, out = self._run_raw([
                "--log", str(self.log), "--milestone", "M1",
                "--", sys.executable, "-c", "pass"])
            self.assertEqual(code, 2)
            self.assertIn("--milestone requires --capture", out)

        # ---- per-runner summary extraction (fixture text, not real runners) ----

        def test_extract_summary_lines_dotnet_test(self):
            text = ("Starting test execution, please wait...\n"
                    "Passed!  - Failed:     0, Passed:    12, Skipped:     0, "
                    "Total:    12, Duration: 45 ms\n"
                    "\n"
                    "Total tests: 12. Passed: 12. Failed: 0. Skipped: 0.\n")
            lines = extract_summary_lines(text)
            self.assertTrue(any(l.startswith("Passed!") for l in lines))
            self.assertTrue(any(l.startswith("Total tests:") for l in lines))

        def test_extract_summary_lines_msbuild(self):
            text = ("Build started...\n"
                    "    2 Warning(s)\n"
                    "    1 Error(s)\n"
                    "Build FAILED.\n")
            lines = extract_summary_lines(text)
            self.assertIn("2 Warning(s)", lines)
            self.assertIn("1 Error(s)", lines)
            self.assertIn("Build FAILED.", lines)

        def test_extract_summary_lines_vitest(self):
            text = (" Test Files  3 passed (3)\n"
                    "      Tests:  20 passed, 2 failed (22)\n")
            lines = extract_summary_lines(text)
            self.assertTrue(any(l.startswith("Test Files") for l in lines))
            self.assertTrue(any(l.startswith("Tests:") for l in lines))

        def test_extract_summary_lines_jest(self):
            text = ("Test Suites: 1 failed, 4 passed, 5 total\n"
                    "Tests:       2 failed, 30 passed, 32 total\n")
            lines = extract_summary_lines(text)
            self.assertTrue(any(l.startswith("Test Suites:") for l in lines))

        def test_extract_summary_lines_pytest(self):
            text = ("============ 2 passed, 1 failed in 0.53s ============\n")
            lines = extract_summary_lines(text)
            self.assertTrue(any("2 passed, 1 failed" in l for l in lines))

        def test_extract_summary_lines_playwright(self):
            text = ("  5 passed (12.3s)\n"
                    "  2 failed\n"
                    "  1 flaky\n")
            lines = extract_summary_lines(text)
            self.assertIn("5 passed (12.3s)", lines)
            self.assertIn("2 failed", lines)
            self.assertIn("1 flaky", lines)

        def test_summary_none_recognised_when_no_pattern_matches(self):
            self.assertEqual(
                build_summary_lines("just some ordinary output\n", 0),
                ["none recognised (exit 0)"])
            self.assertEqual(
                build_summary_lines("", 3),
                ["none recognised (exit 3)"])

        def test_summary_printed_first_in_log_report(self):
            script = "print('Passed!  - Failed: 0, Passed: 1, Total: 1')"
            code, out = self._run([], [sys.executable, "-c", script])
            self.assertEqual(code, 0)
            first_line = out.splitlines()[0]
            self.assertTrue(first_line.startswith("Summary: Passed!"))
            self.assertLess(out.index("Summary:"), out.index("command:"))

        def test_capture_summary_section_above_captured_output(self):
            cap = self.dir / "c.md"
            script = "print('Passed!  - Failed: 0, Passed: 1, Total: 1')"
            code, _ = self._run_raw(
                ["--capture", str(cap), "--", sys.executable, "-c", script])
            self.assertEqual(code, 0)
            text = cap.read_text(encoding="utf-8")
            self.assertIn("Summary: Passed!", text)
            self.assertLess(text.index("## Summary"), text.index("## Captured output"))
            self.assertLess(text.index("Summary: Passed!"), text.index("## Captured output"))

        def test_full_body_without_capture_exits_2(self):
            code, out = self._run_raw([
                "--log", str(self.log), "--full-body",
                "--", sys.executable, "-c", "pass"])
            self.assertEqual(code, 2)
            self.assertIn("--full-body requires --capture", out)

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
