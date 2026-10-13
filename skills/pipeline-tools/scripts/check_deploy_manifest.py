#!/usr/bin/env python3
"""Deployment-manifest gate for .docs/{project}/deploy/manifest.md.

Dep writes the manifest at the end of planning (--phase plan) and completes
it at build Phase 5 (--phase build), so a production deploy has one ordered
bundle of SQL / Azure / config scripts, each with a rollback and each traced
to a plan task. Pure standard library.

Usage:
    python check_deploy_manifest.py --manifest <path> --plan <path> --phase plan|build [--ledger <gates.jsonl>]
    python check_deploy_manifest.py --self-test
"""
import argparse
import hashlib
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_coverage import split_task_blocks  # noqa: E402 - one task parser, not two

HEADER = ("#", "Type", "Step", "Script", "Rollback", "Traces", "Status")
TYPES = ("sql", "azure", "appsetting", "secret", "flag", "backfill", "other")
STATUSES = ("drafted", "pending-build", "final")
PHASES = ("plan", "build")
ARRAYS = ("bad_rows", "missing_rollback", "untraced", "missing_files",
          "premature_sql", "pending", "empty_manifest", "manifest_missing")

FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
SEPARATOR_RE = re.compile(r"^\s*\|[\s:|-]*\|?\s*$")
EXEMPTION_RE = re.compile(r"^\s*No production changes:\s*\S", re.MULTILINE)
NO_ROLLBACK_RE = re.compile(r"^\[no rollback:\s*(.*?)\s*\]$", re.IGNORECASE)
NOT_A_PATH = ("", "-", "n/a", "na", "none", "tbd")


class GateError(Exception):
    """Structural/usage failure -- maps to exit 2."""


def blank_fences(text):
    """Blank fenced regions, preserving line count (family parsing rule)."""
    out, fence = [], None
    for line in text.split("\n"):
        match = FENCE_RE.match(line)
        if fence is None:
            if match:
                fence = match.group(1)[0] * 3
                out.append("")
                continue
            out.append(line)
        else:
            if match and match.group(1).startswith(fence):
                fence = None
            out.append("")
    return "\n".join(out)


def read_text(path, label):
    p = Path(path)
    if not p.is_file():
        raise GateError("%s not found or not readable: %s" % (label, path))
    return p.read_text(encoding="utf-8-sig", errors="replace")


def cells(line):
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in body.split("|")]


def parse_manifest(text):
    """Return (rows, exempt). rows = [(lineno, [7 cells])]. Raises GateError."""
    lines = blank_fences(text).split("\n")
    start = None
    for index, line in enumerate(lines):
        if line.strip().startswith("|") and tuple(cells(line)) == HEADER:
            start = index
            break
    if start is None:
        raise GateError("no manifest table: no line carries the header "
                        "| # | Type | Step | Script | Rollback | Traces | Status |")
    if start + 1 >= len(lines) or not SEPARATOR_RE.match(lines[start + 1]):
        raise GateError("manifest header at line %d has no separator row"
                        % (start + 1))
    rows = []
    for index in range(start + 2, len(lines)):
        line = lines[index]
        if not line.strip().startswith("|"):
            break
        row = cells(line)
        if len(row) != len(HEADER):
            raise GateError("manifest line %d has %d cells, expected %d"
                            % (index + 1, len(row), len(HEADER)))
        rows.append((index + 1, row))
    return rows, bool(EXEMPTION_RE.search("\n".join(lines)))


def rollback_kind(value):
    """'path', 'exempt', or None (missing or an invalid exemption)."""
    match = NO_ROLLBACK_RE.match(value)
    if match:
        return "exempt" if match.group(1) else None
    if value.lower() in NOT_A_PATH or value.startswith("["):
        return None
    return "path"


def empty_report(phase, manifest, plan):
    report = {"ok": False, "phase": phase, "manifest": manifest, "plan": plan,
              "rows": 0, "exempt": False, "legacy": False, "error": None}
    for name in ARRAYS:
        report[name] = []
    return report


def build_report(manifest_path, plan_path, phase):
    report = empty_report(phase, manifest_path, plan_path)
    rows, exempt = parse_manifest(read_text(manifest_path, "manifest"))
    tasks = {number for number, _ in
             split_task_blocks(read_text(plan_path, "plan"))}
    if not tasks:
        raise GateError("no task blocks (## Task N:) found in plan: %s" % plan_path)
    base = Path(manifest_path).resolve().parent
    report["rows"] = len(rows)

    if not rows:
        report["exempt"] = exempt
        if not exempt:
            report["empty_manifest"].append(
                "header-only table with no `No production changes: <reason>` line")
        report["ok"] = exempt
        return report

    def bad(row_no, field, value, detail):
        report["bad_rows"].append({"row": row_no, "field": field,
                                   "value": value, "detail": detail})

    for position, (lineno, row) in enumerate(rows, 1):
        number, kind, step, script, rollback, traces, status = row
        ref = {"row": position, "line": lineno}
        if number != str(position):
            bad(position, "#", number,
                "expected %d: # must run 1..N contiguous, in order" % position)
        if kind not in TYPES:
            bad(position, "Type", kind, "not one of " + ", ".join(TYPES))
        if status not in STATUSES:
            bad(position, "Status", status, "not one of " + ", ".join(STATUSES))
        if not step:
            bad(position, "Step", step, "empty")
        if not script or script.lower() in NOT_A_PATH:
            bad(position, "Script", script, "empty")
        rb = rollback_kind(rollback)
        if rb is None:
            report["missing_rollback"].append(dict(ref, value=rollback))
        tokens = [t.strip() for t in traces.split(",")] if traces else []
        if not tokens or any(not t for t in tokens):
            report["untraced"].append(dict(ref, value=traces,
                                           detail="no plan task number"))
        else:
            malformed = [t for t in tokens if not t.isdigit()]
            if malformed:
                bad(position, "Traces", traces,
                    "not comma-separated task numbers")
            unknown = [t for t in tokens if t.isdigit() and t not in tasks]
            if unknown:
                report["untraced"].append(dict(
                    ref, value=traces,
                    detail="task(s) not in plan: " + ", ".join(unknown)))

        if phase == "plan" and kind == "sql" and status != "pending-build":
            report["premature_sql"].append(dict(ref, status=status))
        if phase == "build" and status == "pending-build":
            report["pending"].append(dict(ref, step=step))

        must_exist = phase == "build" or status in ("drafted", "final")
        if must_exist:
            paths = [("Script", script)] if script and script.lower() not in NOT_A_PATH else []
            if rb == "path":
                paths.append(("Rollback", rollback))
            for field, rel in paths:
                if not (base / rel).is_file():
                    report["missing_files"].append(dict(ref, field=field, path=rel))

    report["ok"] = not any(report[name] for name in ARRAYS)
    return report


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


class LedgerLock:
    """Exclusive cross-process lock held around ONE ledger append.

    Without it two concurrent appenders read the same last line and both
    write the same `prev`: a chain break nobody forged (and, on Windows, a
    record overwritten). The lock is taken on the ledger file itself, so
    there is no sidecar file and no stale lock to clean up -- the OS drops
    it if the holder dies: `fcntl.flock` on POSIX; on Windows a
    `msvcrt.locking` byte far past EOF (mandatory there, so it sits where
    no read or append ever reaches). Best-effort: a wait longer than
    WAIT_SECONDS, or any lock error, warns on stderr and the append goes
    ahead unlocked: it never raises, never skips its own append and never
    changes an exit code, though an unlocked append may still collide
    with a concurrent one.
    """

    WAIT_SECONDS = 10.0
    POLL_SECONDS = 0.005
    WINDOWS_LOCK_OFFSET = 1 << 62

    def __init__(self, ledger_path):
        self.ledger_path = ledger_path
        self.fh = None

    def _lock_call(self, unlock):
        """One non-blocking lock (or unlock) attempt; OSError when busy."""
        if sys.platform == "win32":
            import msvcrt
            import os
            os.lseek(self.fh.fileno(), self.WINDOWS_LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(self.fh.fileno(),
                           msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN if unlock
                        else fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _acquired(self):
        """True once locked, False while another holder has it."""
        import errno
        try:
            self._lock_call(unlock=False)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                return False
            raise

    def __enter__(self):
        import time
        deadline = time.monotonic() + self.WAIT_SECONDS
        try:
            self.fh = open(self.ledger_path, "ab")
            while not self._acquired():
                if time.monotonic() >= deadline:
                    raise OSError("lock still held after {0}s".format(
                        self.WAIT_SECONDS))
                time.sleep(self.POLL_SECONDS)
        except (OSError, ImportError, ValueError) as exc:
            if self.fh is not None:
                self.fh.close()
                self.fh = None
            print("Warning: appending to ledger {0} without a lock: "
                  "{1}".format(self.ledger_path, exc), file=sys.stderr)
        return self

    def __exit__(self, *exc_info):
        if self.fh is not None:
            try:
                self._lock_call(unlock=True)
            except OSError as exc:
                print("Warning: could not release the lock on ledger "
                      "{0}: {1}".format(self.ledger_path, exc),
                      file=sys.stderr)
            self.fh.close()
            self.fh = None
        return False


def ledger_append(p, record):
    """Chain `record` onto ledger `p` and append it as one line, locked.

    `prev` is read and the line written, closed and so flushed, inside one
    LedgerLock. An OSError from the write itself propagates: each caller
    keeps its own best-effort handling of a failed append.
    """
    with LedgerLock(p):
        record["prev"] = ledger_prev_hash(p)
        record["self"] = ledger_self_hash(record)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


def ledger_self_hash(record):
    """sha256 of the record serialized canonically WITHOUT its `self` field."""
    body = {k: v for k, v in record.items() if k != "self"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")).hexdigest()


def append_ledger(ledger_path, argv, inputs, verdict, exit_code, phase, legacy):
    """Append ONE chained JSON line recording this run. Best-effort by design.

    `phase` is recorded so a later --phase build run can tell an epic whose
    plan phase ran this gate from one planned before the gate existed.
    """
    if not ledger_path:
        return
    record = {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gate": Path(__file__).name,
        "argv": list(argv),
        "milestone": None,
        "inputs": {str(p): sha256_file(p) for p in inputs if p},
        "verdict": verdict,
        "exit": exit_code,
        "phase": phase,
    }
    if legacy:
        record["legacy"] = True
    try:
        p = Path(ledger_path)
        if str(p.parent):
            p.parent.mkdir(parents=True, exist_ok=True)
        ledger_append(p, record)
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


def scan_ledger(ledger_path):
    """(plan_recorded, coverage_recorded) for the legacy path at --phase build.

    plan_recorded: an earlier --phase plan run of this gate, any verdict -- a
    plan-phase run at all means the epic was planned after the manifest
    phase existed. coverage_recorded: any check_coverage.py record, which
    every real epic ledger holds by build (bgpdd-plan Phase 3.5 and
    bgpdd-lite Phase 2.5 run it with --ledger). Unparseable lines are
    skipped -- chain integrity is check_ledger.py's job. Raises GateError
    when the ledger is missing or unreadable: a mistyped --ledger must not
    read as "no plan-phase record".
    """
    p = Path(ledger_path)
    if not p.is_file():
        raise GateError("ledger not found: %s -- likely a wrong --ledger path; "
                        "the legacy path needs the epic's real gates.jsonl"
                        % ledger_path)
    try:
        lines = p.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError as exc:
        raise GateError("ledger not readable: %s (%s)" % (ledger_path, exc))
    plan_recorded = coverage_recorded = False
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if (record.get("gate") == Path(__file__).name
                and record.get("phase") == "plan"):
            plan_recorded = True
        elif record.get("gate") == "check_coverage.py":
            coverage_recorded = True
    return plan_recorded, coverage_recorded


class PurposeFirstParser(argparse.ArgumentParser):
    """`--help` whose FIRST line is the one-line purpose, then usage/args/epilog.

    argparse prints usage before the description; the registry's
    `description` must equal help line 1 verbatim, so the description is
    lifted out and re-emitted ahead of the standard body.
    """

    def format_help(self):
        purpose = (self.description or "").strip()
        saved, self.description = self.description, None
        try:
            body = super().format_help()
        finally:
            self.description = saved
        return purpose + "\n\n" + body if purpose else body


PURPOSE = ("Decides whether a deployment manifest is an ordered, rolled-back, "
           "plan-traced bundle ready for its phase: plan or build.")

EPILOG = """\
Reads:
  --manifest  .docs/{project}/deploy/manifest.md. The FIRST table whose
  header is exactly
      | # | Type | Step | Script | Rollback | Traces | Status |
  is the manifest (fenced blocks are blanked first; utf-8-sig). Per row:
    #         1..N, contiguous, in order -- the execution order.
    Type      sql | azure | appsetting | secret | flag | backfill | other
    Step      non-empty description.
    Script    path relative to the manifest's directory.
    Rollback  a path relative to the manifest's directory, or
              [no rollback: <non-empty reason>].
    Traces    plan task numbers, comma-separated ("5, 6").
    Status    drafted | pending-build | final
  A header-only table passes only when the file carries a line
  `No production changes: <reason>` (JSON `exempt: true`).
  --plan  .docs/{project}/implementation/plan.md; task numbers come from its
  `## Task N:` headings via check_coverage.py's split_task_blocks.
  Script/Rollback files, checked on disk per phase.
  --ledger  .docs/{project}/implementation/gates.jsonl: one chained record
  is appended per run, on every exit path (pipeline-tools SKILL.md, "Gate
  ledger"), carrying the extra field `phase` (and `legacy: true` on a
  legacy pass). At --phase build with no manifest file it is also READ.

Epic planned before the manifest phase (--phase build, no manifest file):
  A ledger record of this gate with phase `plan` (any verdict) -> exit 1,
  `manifest_missing`. Otherwise the ledger must hold a check_coverage.py
  record (the plan lanes' coverage gate writes one) -> exit 0,
  `legacy: true`. A missing or unreadable ledger, or one with no
  check_coverage.py record, -> exit 2 (likely a wrong --ledger path).
  Without --ledger, or at --phase plan, a missing manifest stays exit 2.

Phase rules:
  both   the row checks above (bad_rows, missing_rollback, untraced).
  plan   pending-build allowed; drafted/final rows need their Script and
         path Rollback on disk; a sql row must be pending-build (SQL is
         generated from the real migrations at build).
  build  no row may be pending-build; every Script and path Rollback must
         exist on disk.

Problem codes:
  Each is a JSON array; any non-empty array is exit 1.
  bad_rows          {row, field, value, detail}: # out of order, Type or
                    Status outside its enum, empty Step/Script, Traces not
                    comma-separated numbers
  missing_rollback  {row, line, value}: empty, n/a, or an exemption with no
                    reason
  untraced          {row, line, value, detail}: no trace, or a task number
                    plan.md does not have
  missing_files     {row, line, field, path}: a required file is absent
  premature_sql     {row, line, status}: a sql row not pending-build at plan
  pending           {row, line, step}: a pending-build row at build
  empty_manifest    header-only table without the exemption line
  manifest_missing  {path, detail}: no manifest at build, but the ledger
                    records a plan-phase run of this gate
  error             prose naming the exit-2 failure

JSON keys:
  Always printed on stdout (there is no --json flag):
  ok, phase, manifest, plan, rows, exempt, legacy, bad_rows,
  missing_rollback, untraced, missing_files, premature_sql, pending,
  empty_manifest, manifest_missing, error

Exit codes:
  0  ok: every array empty (or an exempt empty manifest, or a legacy pass).
  1  at least one array is non-empty.
  2  usage error, a missing/unreadable manifest or plan (outside the legacy
     path), a missing, unreadable or coverage-less ledger on the legacy
     path, no manifest table,
     no separator row, a row with the wrong cell count, or a plan with no
     `## Task N:` headings.

Self-test:
  python check_deploy_manifest.py --self-test   (22 cases)
"""


def main(argv):
    parser = PurposeFirstParser(
        prog="check_deploy_manifest.py",
        description=PURPOSE,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--manifest", help="path to deploy/manifest.md")
    parser.add_argument("--plan", help="path to implementation/plan.md")
    parser.add_argument("--phase", help="plan or build")
    parser.add_argument("--ledger",
                        help="append one chained JSON record per run to this "
                             "path; read for the legacy path at --phase build")
    parser.add_argument("--self-test", action="store_true",
                        help="run the built-in tests and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(report, code):
        """One exit point: EVERY return path prints and records a ledger line."""
        print(json.dumps(report, indent=2))
        append_ledger(args.ledger, argv, [args.manifest, args.plan],
                      ("PASS", "FAIL", "ERROR")[code], code, args.phase,
                      report["legacy"])
        return code

    report = empty_report(args.phase, args.manifest, args.plan)
    missing = [flag for flag, value in (("--manifest", args.manifest),
                                         ("--plan", args.plan),
                                         ("--phase", args.phase)) if not value]
    if missing:
        report["error"] = "missing required argument(s): " + ", ".join(missing)
    elif args.phase not in PHASES:
        report["error"] = "--phase must be plan or build, not %r" % args.phase
    if report["error"]:
        return finish(report, 2)
    try:
        if (args.phase == "build" and args.ledger
                and not Path(args.manifest).is_file()):
            plan_recorded, coverage_recorded = scan_ledger(args.ledger)
            if plan_recorded:
                report["manifest_missing"].append({
                    "path": args.manifest,
                    "detail": "the ledger records a plan-phase run of this "
                              "gate, so this epic owes a manifest"})
                return finish(report, 1)
            if not coverage_recorded:
                raise GateError(
                    "ledger %s holds no check_coverage.py record, so it is not "
                    "this epic's plan-lane ledger -- likely a wrong --ledger "
                    "path" % args.ledger)
            report["legacy"] = report["ok"] = True
            return finish(report, 0)
        report = build_report(args.manifest, args.plan, args.phase)
    except GateError as exc:
        report["error"] = str(exc)
        return finish(report, 2)
    return finish(report, 0 if report["ok"] else 1)


def run_self_test():
    import io
    import shutil
    from contextlib import redirect_stdout

    PLAN = "# Plan\n\n## Task 3: schema\n\nx\n\n## Task 5: queue\n\ny\n\n## Task 6: z\n"
    HEAD = ("| # | Type | Step | Script | Rollback | Traces | Status |\n"
            "|---|------|------|--------|----------|--------|--------|\n")
    SQL_PENDING = "| 1 | sql | Add column | scripts/01.sql | rollback/01.sql | 3 | pending-build |\n"
    AZURE = "| 2 | azure | Queue | scripts/02.ps1 | rollback/02.ps1 | 5, 6 | drafted |\n"
    SETTING = ("| 3 | appsetting | Key | scripts/03.json | "
               "[no rollback: additive key] | 5 | drafted |\n")

    class ManifestTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.plan = self.dir / "plan.md"
            self.plan.write_text(PLAN, encoding="utf-8")
            self.manifest = self.dir / "deploy" / "manifest.md"
            self.manifest.parent.mkdir()
            for rel in ("scripts/02.ps1", "rollback/02.ps1", "scripts/03.json"):
                self.touch(rel)

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def touch(self, rel):
            p = self.manifest.parent / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")

        def run_gate(self, body, phase):
            self.manifest.write_text(body, encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--manifest", str(self.manifest),
                             "--plan", str(self.plan), "--phase", phase])
            report = json.loads(out.getvalue())
            self.assertEqual(report["ok"], code == 0)
            for key in ("phase", "rows") + ARRAYS:
                self.assertIn(key, report)
            return code, report

        def test_plan_pass(self):
            code, r = self.run_gate(HEAD + SQL_PENDING + AZURE + SETTING, "plan")
            self.assertEqual(code, 0, r)
            self.assertEqual(r["rows"], 3)

        def test_build_pass_once_sql_final(self):
            self.touch("scripts/01.sql")
            self.touch("rollback/01.sql")
            body = HEAD + SQL_PENDING.replace("pending-build", "final") + AZURE + SETTING
            code, r = self.run_gate(body, "build")
            self.assertEqual(code, 0, r)

        def test_bad_rows_order_and_enums(self):
            body = HEAD + SQL_PENDING + AZURE.replace("| 2 | azure", "| 4 | cloud") \
                + SETTING.replace("drafted", "done")
            code, r = self.run_gate(body, "plan")
            self.assertEqual(code, 1)
            fields = sorted(b["field"] for b in r["bad_rows"])
            self.assertEqual(fields, ["#", "Status", "Type"])

        def test_missing_rollback(self):
            body = HEAD + SQL_PENDING.replace("rollback/01.sql", "n/a") \
                + SETTING.replace("| 3 |", "| 2 |").replace("additive key", "")
            code, r = self.run_gate(body, "plan")
            self.assertEqual(code, 1)
            self.assertEqual(len(r["missing_rollback"]), 2)

        def test_untraced_unknown_and_empty(self):
            body = HEAD + SQL_PENDING.replace("| 3 |", "| 9 |") \
                + AZURE.replace("5, 6", "")
            code, r = self.run_gate(body, "plan")
            self.assertEqual(code, 1)
            self.assertEqual(len(r["untraced"]), 2)
            self.assertIn("9", r["untraced"][0]["detail"])

        def test_plan_missing_files_for_drafted(self):
            (self.manifest.parent / "rollback/02.ps1").unlink()
            code, r = self.run_gate(HEAD + SQL_PENDING + AZURE, "plan")
            self.assertEqual(code, 1)
            self.assertEqual([(m["field"], m["path"]) for m in r["missing_files"]],
                             [("Rollback", "rollback/02.ps1")])

        def test_plan_pending_build_needs_no_files(self):
            code, r = self.run_gate(HEAD + SQL_PENDING, "plan")
            self.assertEqual(code, 0, r)

        def test_premature_sql_at_plan(self):
            self.touch("scripts/01.sql")
            self.touch("rollback/01.sql")
            body = HEAD + SQL_PENDING.replace("pending-build", "drafted")
            code, r = self.run_gate(body, "plan")
            self.assertEqual(code, 1)
            self.assertEqual(len(r["premature_sql"]), 1)

        def test_build_pending_and_missing_files(self):
            code, r = self.run_gate(HEAD + SQL_PENDING + AZURE, "build")
            self.assertEqual(code, 1)
            self.assertEqual(len(r["pending"]), 1)
            self.assertEqual(sorted(m["path"] for m in r["missing_files"]),
                             ["rollback/01.sql", "scripts/01.sql"])

        def test_no_changes_exemption_passes_both_phases(self):
            body = "No production changes: docs-only feature\n\n" + HEAD
            for phase in PHASES:
                code, r = self.run_gate(body, phase)
                self.assertEqual(code, 0, r)
                self.assertTrue(r["exempt"])

        def test_empty_without_exemption_blocks(self):
            code, r = self.run_gate(HEAD, "plan")
            self.assertEqual(code, 1)
            self.assertEqual(len(r["empty_manifest"]), 1)

        def test_exemption_inside_fence_does_not_count(self):
            code, r = self.run_gate("```\nNo production changes: x\n```\n" + HEAD, "build")
            self.assertEqual(code, 1)

        def test_no_table_is_exit_2(self):
            code, r = self.run_gate("# Manifest\n\nnothing here\n", "plan")
            self.assertEqual(code, 2)
            self.assertIn("no manifest table", r["error"])

        def test_wrong_cell_count_is_exit_2(self):
            code, r = self.run_gate(HEAD + "| 1 | sql | x | a.sql | 3 | final |\n", "plan")
            self.assertEqual(code, 2)

        def test_missing_plan_and_bad_phase_are_exit_2(self):
            self.plan.unlink()
            code, r = self.run_gate(HEAD + SQL_PENDING, "plan")
            self.assertEqual(code, 2)
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(main(["--manifest", "m", "--plan", "p",
                                       "--phase", "ship"]), 2)
            self.assertIn("--phase", json.loads(out.getvalue())["error"])

        def test_bom_manifest_parses(self):
            self.manifest.write_bytes(b"\xef\xbb\xbf" + (HEAD + SQL_PENDING).encode("utf-8"))
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--manifest", str(self.manifest),
                             "--plan", str(self.plan), "--phase", "plan"])
            self.assertEqual(code, 0, out.getvalue())

        # --- ledger and the pre-manifest-epic (legacy) path ---------------
        def run_ledgered(self, phase, *extra):
            self.ledger = self.dir / "implementation" / "gates.jsonl"
            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--manifest", str(self.manifest),
                             "--plan", str(self.plan), "--phase", phase,
                             *extra])
            report = json.loads(out.getvalue())
            self.assertEqual(report["ok"], code == 0)
            return code, report

        def records(self):
            return [json.loads(line) for line in
                    self.ledger.read_text(encoding="utf-8").splitlines()]

        def test_every_exit_appends_one_chained_record(self):
            self.manifest.write_text(HEAD + SQL_PENDING, encoding="utf-8")
            ledger = str(self.dir / "implementation" / "gates.jsonl")
            self.run_ledgered("plan", "--ledger", ledger)
            self.run_ledgered("ship", "--ledger", ledger)
            recs = self.records()
            self.assertEqual([(r["verdict"], r["exit"], r["phase"]) for r in recs],
                             [("PASS", 0, "plan"), ("ERROR", 2, "ship")])
            self.assertEqual(recs[0]["gate"], "check_deploy_manifest.py")
            self.assertEqual(recs[0]["prev"], "genesis")
            self.assertEqual(recs[1]["prev"], ledger_line_hash(
                self.ledger.read_bytes().splitlines()[0]))
            self.assertEqual(recs[0]["self"], ledger_self_hash(recs[0]))

        def test_build_no_manifest_no_plan_record_is_legacy_pass(self):
            ledger = self.dir / "implementation" / "gates.jsonl"
            ledger.parent.mkdir()
            ledger.write_text(json.dumps({"gate": "check_coverage.py",
                                          "phase": "plan"}) + "\n",
                              encoding="utf-8")
            code, r = self.run_ledgered("build", "--ledger", str(ledger))
            self.assertEqual(code, 0, r)
            self.assertTrue(r["legacy"])
            self.assertTrue(self.records()[-1]["legacy"])

        def test_build_no_manifest_absent_ledger_is_exit_2(self):
            code, r = self.run_ledgered(
                "build", "--ledger", str(self.dir / "implementation" / "gates.jsonl"))
            self.assertEqual(code, 2, r)
            self.assertFalse(r["legacy"])
            self.assertIn("wrong --ledger path", r["error"])

        def test_build_no_manifest_ledger_without_coverage_is_exit_2(self):
            ledger = self.dir / "implementation" / "gates.jsonl"
            ledger.parent.mkdir()
            ledger.write_text(json.dumps({"gate": "check_handoff.py"}) + "\n",
                              encoding="utf-8")
            code, r = self.run_ledgered("build", "--ledger", str(ledger))
            self.assertEqual(code, 2, r)
            self.assertIn("no check_coverage.py record", r["error"])

        def test_build_no_manifest_after_plan_record_blocks(self):
            ledger = str(self.dir / "implementation" / "gates.jsonl")
            # The plan-phase run itself failed (no manifest yet): any verdict counts.
            self.assertEqual(self.run_ledgered("plan", "--ledger", ledger)[0], 2)
            code, r = self.run_ledgered("build", "--ledger", ledger)
            self.assertEqual(code, 1, r)
            self.assertFalse(r["legacy"])
            self.assertEqual(len(r["manifest_missing"]), 1)

        def test_missing_manifest_without_ledger_or_at_plan_is_exit_2(self):
            code, r = self.run_ledgered("build")
            self.assertEqual(code, 2)
            self.assertIn("manifest not found", r["error"])
            ledger = str(self.dir / "implementation" / "gates.jsonl")
            code, r = self.run_ledgered("plan", "--ledger", ledger)
            self.assertEqual(code, 2)
            self.assertFalse(r["legacy"])
            unreadable = self.dir / "a-directory"
            unreadable.mkdir()
            code, r = self.run_ledgered("build", "--ledger", str(unreadable))
            self.assertEqual(code, 2)

    suite =unittest.defaultTestLoader.loadTestsFromTestCase(ManifestTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
