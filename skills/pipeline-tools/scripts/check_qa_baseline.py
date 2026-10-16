#!/usr/bin/env python3
"""State-transition coverage gate for a discovery QA baseline.

Echo derives manual test cases from code paths, so two transitions that
share one handler (map a client, and remap it to a different one) collapsed
into one case and the second was never written. The baseline now carries a
`## State Transitions` table -- one row per mutable entity and dimension,
one cell per transition -- and this gate checks every cell names a case the
file defines, or says why none applies. Pure standard library.

Usage:
    python check_qa_baseline.py --file <manual-testing.md> [--ledger <path>]
        [--milestone "<title>"]
    python check_qa_baseline.py --self-test
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

SECTION = "State Transitions"
COLUMNS = ("Entity", "Dimension", "Unset → Set", "Set → Unset",
           "Set → Different")
CASE_ID_RE = re.compile(r"^[A-Z]{2,}-\d{2,}$")
CASE_HEADING_RE = re.compile(r"^#{2,6}\s+([A-Z]{2,}-\d{2,})\b")
NA_RE = re.compile(r"^N/A\s*:\s*(.*)$", re.IGNORECASE)
NONE_RE = re.compile(r"^None\s*:\s*(.*)$", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
MIN_REASON_WORDS = 3


class GateError(Exception):
    """Structural/usage failure -- maps to exit 2."""


def blank_fences(lines):
    """Lines with fenced regions blanked, line count preserved (family rule)."""
    out, fence = [], None
    for line in lines:
        m = FENCE_RE.match(line)
        if fence is None and m:
            fence = m.group(1)[0]
            out.append("")
        elif fence is not None:
            if m and m.group(1)[0] == fence:
                fence = None
            out.append("")
        else:
            out.append(line)
    return out


def split_row(line):
    """Cells of one markdown table row, or None when it is not a row."""
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")) or len(s) < 2:
        return None
    return [c.strip() for c in s[1:-1].split("|")]


def norm_header(cell):
    """Header comparison: whitespace-collapsed, `->` read as the arrow."""
    return " ".join(cell.replace("->", "→").split()).casefold()


def build_report(path):
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise GateError(f"cannot read --file {path}: {exc}")
    lines = blank_fences(text.splitlines())
    defined = {m.group(1) for line in lines
               for m in [CASE_HEADING_RE.match(line)] if m}
    problems = []

    def problem(code, line_no, detail):
        problems.append({"problem": code, "line": line_no, "detail": detail})

    start = next((i for i, line in enumerate(lines)
                  if re.match(r"^##\s+" + re.escape(SECTION) + r"\s*$",
                              line.strip(), re.IGNORECASE)), None)
    report = {"file": str(p).replace("\\", "/"), "cases_defined": len(defined),
              "rows": [], "none_reason": None, "problems": problems}
    if start is None:
        problem("transitions_missing", None,
                f"no `## {SECTION}` section: every mutable entity's "
                "transitions must be enumerated, or the section must say "
                "`None: <reason>`")
        return report
    body = []
    for i in range(start + 1, len(lines)):
        if re.match(r"^#{1,2}\s", lines[i]):
            break
        if lines[i].strip():
            body.append((i + 1, lines[i]))
    rows = [(n, split_row(line)) for n, line in body]
    table = [(n, cells) for n, cells in rows if cells is not None]
    if not table:
        none = next((NONE_RE.match(line.strip()) for _n, line in body
                     if NONE_RE.match(line.strip())), None)
        if none and len(none.group(1).split()) >= MIN_REASON_WORDS:
            report["none_reason"] = none.group(1).strip()
        else:
            problem("transitions_missing", start + 1,
                    f"`## {SECTION}` holds no table and no `None: <reason>` "
                    f"line of at least {MIN_REASON_WORDS} words")
        return report
    header_no, header = table[0]
    if [norm_header(c) for c in header] != [norm_header(c) for c in COLUMNS]:
        problem("transitions_table_malformed", header_no,
                "header must be | " + " | ".join(COLUMNS) + " |")
        return report
    seen = set()
    data_rows = 0
    for n, cells in table[1:]:
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue                        # the |---| separator row
        data_rows += 1
        if len(cells) != len(COLUMNS):
            problem("transitions_table_malformed", n,
                    f"row has {len(cells)} cells, expected {len(COLUMNS)}")
            continue
        entity, dimension = cells[0], cells[1]
        if not entity or not dimension:
            problem("transitions_table_malformed", n,
                    "Entity and Dimension must both be named")
            continue
        key = (entity.casefold(), dimension.casefold())
        if key in seen:
            problem("transition_row_duplicate", n,
                    f"{entity} / {dimension} is listed twice")
        seen.add(key)
        row = {"line": n, "entity": entity, "dimension": dimension,
               "cells": {}}
        for column, cell in zip(COLUMNS[2:], cells[2:]):
            row["cells"][column] = cell
            where = f"{entity} / {dimension} / {column}"
            na = NA_RE.match(cell)
            if not cell:
                problem("transition_cell_empty", n,
                        f"{where}: name a case ID or `N/A: <reason>`")
            elif na:
                if len(na.group(1).split()) < MIN_REASON_WORDS:
                    problem("transition_na_unreasoned", n,
                            f"{where}: `N/A:` needs a reason of at least "
                            f"{MIN_REASON_WORDS} words")
            else:
                ids = [x.strip().strip("`") for x in cell.split(",")]
                for case_id in ids:
                    if not CASE_ID_RE.match(case_id):
                        problem("transitions_table_malformed", n,
                                f"{where}: {case_id!r} is neither a case ID "
                                "nor `N/A: <reason>`")
                    elif case_id not in defined:
                        problem("transition_case_missing", n,
                                f"{where}: {case_id} is not a case heading "
                                "in this file")
        report["rows"].append(row)
    if not data_rows:
        problem("transitions_missing", header_no,
                "the table has a header and no rows; with no mutable state "
                "write `None: <reason>` instead")
    return report


# --- the gate ledger: byte-identical helpers (pipeline-tools/SKILL.md) -----

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


def append_ledger(ledger_path, argv, milestone, inputs, verdict, exit_code):
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
    try:
        p = Path(ledger_path)
        if str(p.parent):
            p.parent.mkdir(parents=True, exist_ok=True)
        ledger_append(p, record)
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


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


PURPOSE = ("Decides whether a discovery QA baseline enumerates every mutable "
           "entity's state transitions, each cell citing a defined case or a "
           "reasoned N/A.")

EPILOG = """\
Reads:
  --file <path>  the feature's .docs/summary/{feature}/QA/manual-testing.md.
  Its `## State Transitions` section holds one table (the arrow is the
  Unicode right arrow or `->`):
    | Entity | Dimension | Unset -> Set | Set -> Unset | Set -> Different |
  one row per mutable entity and independently changeable dimension (a
  client mapping with a target client AND a target box is two rows). Each
  transition cell holds one or more case IDs (`EC-03, EC-04`) whose
  `### <ID> — ...` heading exists in the same file, or `N/A: <reason>`
  (at least 3 words). A feature with no
  mutable state writes `None: <reason>` (3+ words) under the heading
  instead of a table. Fenced blocks are blanked first; the file is read
  as utf-8-sig.

  What this cannot see: an entity the table never lists. It guarantees
  that every listed dimension gets its change case or an explicit,
  reviewable N/A -- not that the list of entities is complete.

Problem codes:
  transitions_missing          no section, or a section with neither a table
                               with rows nor a reasoned `None:` line
  transitions_table_malformed  wrong header, wrong cell count, an unnamed
                               entity/dimension, or a cell that is neither
                               case IDs nor `N/A:`
  transition_cell_empty        a transition cell left blank
  transition_na_unreasoned     `N/A:` with fewer than 3 words of reason
  transition_case_missing      a cited ID with no case heading in the file
  transition_row_duplicate     the same entity/dimension listed twice

JSON keys:
  file, cases_defined, rows, none_reason, problems, result, error

Exit codes:
  0  every row's three cells resolve, or a reasoned `None:`
  1  any problem above
  2  usage error, or --file unreadable

Self-test:
  python check_qa_baseline.py --self-test   (12 cases)
"""


def main(argv):
    parser = PurposeFirstParser(
        prog="check_qa_baseline.py", description=PURPOSE, epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", help="the QA baseline (manual-testing.md)")
    parser.add_argument("--milestone",
                        help="recorded in the ledger record; not a scope")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone,
                      [args.file] if args.file else [], verdict, code)
        return code

    if not args.file:
        print(json.dumps({"result": "ERROR",
                          "error": "missing required argument: --file"}))
        return finish(2, "ERROR")
    try:
        report = build_report(args.file)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")
    report["result"] = "FAIL" if report["problems"] else "PASS"
    report["error"] = None
    print(json.dumps(report, indent=2))
    return finish(1, "FAIL") if report["problems"] else finish(0, "PASS")


def run_self_test():
    import shutil

    CASES = ("## Happy Path\n\n### HP-01 — Map a client (P0)\n"
             "### HP-02 — Unmap a client (P0)\n\n## Edge Cases\n\n"
             "### EC-03 — Remap to another box (P0)\n"
             "### EC-04 — Remap to another client (P0)\n")
    HEADER = ("| Entity | Dimension | Unset → Set | Set → Unset | "
              "Set → Different |\n|---|---|---|---|---|\n")

    class QaBaselineTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.file = self.dir / "manual-testing.md"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def codes(self, transitions, cases=CASES):
            self.file.write_text("# QA\n\n" + cases + "\n## State Transitions"
                                 "\n\n" + transitions, encoding="utf-8")
            return sorted(p["problem"] for p in
                          build_report(str(self.file))["problems"])

        def test_full_table_passes(self):
            self.assertEqual(self.codes(
                HEADER + "| Mapping | Slide client | HP-01 | HP-02 | EC-04 |\n"
                "| Mapping | Box | HP-01 | HP-02 | EC-03 |\n"), [])

        def test_the_slide_gap_fails(self):
            """2026-10-16: remap-to-another-client had no case."""
            self.assertEqual(self.codes(
                HEADER + "| Mapping | Slide client | HP-01 | HP-02 | |\n"),
                ["transition_cell_empty"])

        def test_reasoned_na_passes_and_bare_na_fails(self):
            self.assertEqual(self.codes(
                HEADER + "| Flag | Enabled | HP-01 | HP-02 | N/A: boolean, "
                "so different is unset or set |\n"), [])
            self.assertEqual(self.codes(
                HEADER + "| Flag | Enabled | HP-01 | HP-02 | N/A |\n"),
                ["transitions_table_malformed"])
            self.assertEqual(self.codes(
                HEADER + "| Flag | Enabled | HP-01 | HP-02 | N/A: no |\n"),
                ["transition_na_unreasoned"])

        def test_cited_case_must_exist(self):
            self.assertEqual(self.codes(
                HEADER + "| Mapping | Box | HP-01 | HP-02 | EC-03, EC-09 |\n"),
                ["transition_case_missing"])

        def test_a_case_only_inside_a_fence_does_not_exist(self):
            cases = CASES + "```\n### EC-09 — template (P2)\n```\n"
            self.assertEqual(self.codes(
                HEADER + "| Mapping | Box | HP-01 | HP-02 | EC-09 |\n", cases),
                ["transition_case_missing"])

        def test_missing_section_fails(self):
            self.file.write_text("# QA\n\n" + CASES, encoding="utf-8")
            self.assertEqual([p["problem"] for p in build_report(
                str(self.file))["problems"]], ["transitions_missing"])

        def test_reasoned_none_passes_and_empty_section_fails(self):
            self.assertEqual(self.codes(
                "None: a read-only report with no writes\n"), [])
            self.assertEqual(self.codes("None: n/a\n"),
                             ["transitions_missing"])
            self.assertEqual(self.codes(HEADER), ["transitions_missing"])

        def test_wrong_header_or_cell_count_fails(self):
            self.assertEqual(self.codes(
                "| Entity | Dimension | Add | Remove | Change |\n"
                "|---|---|---|---|---|\n| A | B | HP-01 | HP-02 | EC-03 |\n"),
                ["transitions_table_malformed"])
            self.assertEqual(self.codes(
                HEADER + "| A | B | HP-01 | HP-02 |\n"),
                ["transitions_table_malformed"])

        def test_ascii_arrow_header_is_accepted(self):
            header = HEADER.replace("→", "->")
            self.assertEqual(self.codes(
                header + "| A | B | HP-01 | HP-02 | EC-03 |\n"), [])

        def test_duplicate_row_fails(self):
            row = "| A | B | HP-01 | HP-02 | EC-03 |\n"
            self.assertEqual(self.codes(HEADER + row + row),
                             ["transition_row_duplicate"])

        def test_cli_exit_codes_and_ledger(self):
            self.codes(HEADER + "| A | B | HP-01 | HP-02 | EC-03 |\n")
            ledger = self.dir / "gates.jsonl"
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--file", str(self.file),
                                       "--ledger", str(ledger)]), 0)
                self.assertEqual(main(["--file", str(self.dir / "nope.md"),
                                       "--ledger", str(ledger)]), 2)
                self.assertEqual(main([]), 2)
            records = [json.loads(l) for l in
                       ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["verdict"] for r in records],
                             ["PASS", "ERROR"])
            self.assertEqual(records[1]["prev"],
                             ledger_line_hash(ledger.read_bytes()
                                              .splitlines()[0]))

        def test_bom_and_next_section_bound_the_table(self):
            self.file.write_text(
                "﻿# QA\n\n" + CASES + "\n## State Transitions\n\n"
                + HEADER + "| A | B | HP-01 | HP-02 | EC-03 |\n\n"
                "## Notes\n\n| x | y |\n", encoding="utf-8")
            self.assertEqual(build_report(str(self.file))["problems"], [])

    suite = unittest.TestLoader().loadTestsFromTestCase(QaBaselineTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
