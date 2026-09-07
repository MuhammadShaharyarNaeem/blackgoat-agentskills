#!/usr/bin/env python3
"""Verify the gate ledger's hash chain.

Every gate in this family appends one JSON line per run carrying two chain
fields (`../SKILL.md`, "Gate ledger"):

  * `prev` — sha256 of the PREVIOUS line's bytes, or `"genesis"` for the
    first record in the file;
  * `self` — sha256 of this record serialized canonically WITHOUT `self`
    (`json.dumps(sort_keys=True, separators=(',', ':'))`).

This script walks the chain and reports the FIRST broken link. What it buys:
a single record that was edited, inserted or removed after the fact is now
visible, where before the ledger was an append-only text file anybody could
retype. What it does NOT buy, and the limit is accepted deliberately: a
forger who rewrites the ENTIRE tail consistently — recomputing every `prev`
and `self` from the edit point onward — produces an intact chain. There is no
external anchor (no signature, no notary), so the chain detects tampering
that is local, not tampering that is thorough. Truncating trailing records is
likewise undetectable by construction.

Legacy records (neither `prev` nor `self`) are tolerated ONLY before the
first chained record: a ledger written by the pre-chain build migrates
forward by simply being appended to. Once a chained record exists, an
unchained one after it is a refusal — reverting to unchained is exactly what
deleting the chain looks like.

`--ledger` here is the SUBJECT under test, not an append target: unlike every
other gate in the family this script writes nothing (convention #8, a
deliberate divergence from the "every gate carries `--ledger`" rule).
Appending its own record would extend the chain it is reporting on.

Usage:
    python check_ledger.py --ledger <path>
    python check_ledger.py --self-test

Pure standard library. See ../SKILL.md for the full contract.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path


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


def verify_ledger_chain(ledger_path):
    """(ok, problem|None) — walk the chain and stop at the FIRST broken link.

    `problem` is `{"line", "reason", "detail"}` with reason one of
    `unparseable`, `legacy-after-chained`, `incomplete-chain-fields`,
    `self-mismatch`, `prev-mismatch`, `unreadable`. A missing ledger file is
    NOT a break here (there is no chain to break); callers that require the
    ledger to exist say so themselves.

    Byte-identical in check_ledger.py, check_commit_gate.py and
    mark_milestone.py (family convention: one file each, no shared module).
    """
    p = Path(ledger_path)
    if not p.is_file():
        return True, None
    try:
        data = p.read_bytes()
    except OSError as exc:
        return False, {"line": 0, "reason": "unreadable",
                       "detail": "cannot read {0}: {1}".format(ledger_path, exc)}
    chained_seen = False
    prev_hash = "genesis"
    for lineno, raw in enumerate(data.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw.decode("utf-8-sig", errors="replace"))
        except ValueError:
            return False, {"line": lineno, "reason": "unparseable",
                           "detail": "line is not parseable JSON"}
        if not isinstance(rec, dict):
            return False, {"line": lineno, "reason": "unparseable",
                           "detail": "line is not a JSON object"}
        has_prev, has_self = "prev" in rec, "self" in rec
        if not has_prev and not has_self:
            if chained_seen:
                return False, {
                    "line": lineno, "reason": "legacy-after-chained",
                    "detail": "an unchained record follows a chained one; a "
                              "ledger that has started chaining cannot revert "
                              "to unchained"}
            prev_hash = ledger_line_hash(raw)
            continue
        if not (has_prev and has_self):
            return False, {
                "line": lineno, "reason": "incomplete-chain-fields",
                "detail": "record carries only one of `prev`/`self`; a chained "
                          "record carries both"}
        if rec.get("self") != ledger_self_hash(rec):
            return False, {
                "line": lineno, "reason": "self-mismatch",
                "detail": "`self` does not hash this record's own content — "
                          "the line was edited after it was written"}
        if rec.get("prev") != prev_hash:
            return False, {
                "line": lineno, "reason": "prev-mismatch",
                "detail": "`prev` is {0} but the preceding record hashes to "
                          "{1} — a record was inserted, removed or edited "
                          "before this line".format(
                              str(rec.get("prev"))[:16], prev_hash[:16])}
        chained_seen = True
        prev_hash = ledger_line_hash(raw)
    return True, None


def build_report(ledger_path):
    """The full JSON report: chain verdict plus the record census."""
    report = {"ledger": ledger_path, "pass": False, "records": 0,
              "chained_records": 0, "legacy_records": 0,
              "problem": None, "error": None}
    p = Path(ledger_path)
    if not p.is_file():
        report["error"] = "ledger not found: {0}".format(ledger_path)
        return report
    try:
        data = p.read_bytes()
    except OSError as exc:
        report["error"] = "ledger is unreadable: {0}".format(exc)
        return report
    for raw in data.splitlines():
        if not raw.strip():
            continue
        report["records"] += 1
        try:
            rec = json.loads(raw.decode("utf-8-sig", errors="replace"))
        except ValueError:
            continue
        if isinstance(rec, dict) and ("prev" in rec or "self" in rec):
            report["chained_records"] += 1
        else:
            report["legacy_records"] += 1
    ok, problem = verify_ledger_chain(ledger_path)
    report["pass"] = ok
    if not ok:
        report["problem"] = dict(problem, problem="chain_broken")
    return report


def main(argv):
    parser = argparse.ArgumentParser(prog="check_ledger.py")
    parser.add_argument("--ledger",
                        help="the gate ledger whose hash chain to verify "
                             "(read only; this script never writes)")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.ledger:
        print(json.dumps({"pass": False, "problem": {"problem": "ledger_missing"},
                          "error": "missing required argument: --ledger"}))
        return 2

    report = build_report(args.ledger)
    print(json.dumps(report, indent=2))
    if report["error"]:
        return 2
    return 0 if report["pass"] else 1


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil
    import tempfile
    import unittest

    def chained(ledger, gate, verdict="PASS", exit_code=0, milestone="M1"):
        """Append one record exactly as the gates' append_ledger() does."""
        record = {"ts": "2026-09-07T00:00:00Z", "gate": gate, "argv": [],
                  "milestone": milestone, "inputs": {}, "verdict": verdict,
                  "exit": exit_code}
        record["prev"] = ledger_prev_hash(ledger)
        record["self"] = ledger_self_hash(record)
        with open(ledger, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return record

    def legacy(ledger, gate, verdict="PASS"):
        record = {"ts": "2026-09-01T00:00:00Z", "gate": gate, "argv": [],
                  "milestone": "M1", "inputs": {}, "verdict": verdict,
                  "exit": 0}
        with open(ledger, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        return record

    class CheckLedgerTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.ledger = self.dir / "gates.jsonl"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _lines(self):
            return self.ledger.read_text(encoding="utf-8").splitlines()

        def _write(self, lines):
            self.ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # ---- the five cases the contract names -------------------------

        def test_intact_chain_passes(self):
            for gate in ("check_coverage.py", "check_agent_report.py",
                         "check_commit_gate.py"):
                chained(self.ledger, gate)
            r = build_report(str(self.ledger))
            self.assertTrue(r["pass"], r)
            self.assertEqual((r["records"], r["chained_records"],
                              r["legacy_records"]), (3, 3, 0))
            self.assertEqual(main(["--ledger", str(self.ledger)]), 0)

        def test_edited_middle_record_fails_at_that_line(self):
            for gate in ("a.py", "b.py", "c.py"):
                chained(self.ledger, gate)
            lines = self._lines()
            rec = json.loads(lines[1])
            rec["verdict"] = "PASS" if rec["verdict"] != "PASS" else "FAIL"
            lines[1] = json.dumps(rec)          # `self` deliberately untouched
            self._write(lines)
            r = build_report(str(self.ledger))
            self.assertFalse(r["pass"])
            self.assertEqual(r["problem"]["line"], 2)
            self.assertEqual(r["problem"]["reason"], "self-mismatch")
            self.assertEqual(r["problem"]["problem"], "chain_broken")
            self.assertEqual(main(["--ledger", str(self.ledger)]), 1)

        def test_edited_record_with_recomputed_self_still_fails(self):
            """A forger who fixes `self` still breaks the NEXT record's prev."""
            for gate in ("a.py", "b.py", "c.py"):
                chained(self.ledger, gate)
            lines = self._lines()
            rec = json.loads(lines[1])
            rec["verdict"] = "FAIL"
            rec.pop("self")
            rec["self"] = ledger_self_hash(rec)
            lines[1] = json.dumps(rec)
            self._write(lines)
            r = build_report(str(self.ledger))
            self.assertFalse(r["pass"])
            self.assertEqual(r["problem"]["line"], 3)
            self.assertEqual(r["problem"]["reason"], "prev-mismatch")

        def test_inserted_record_fails(self):
            for gate in ("a.py", "b.py", "c.py"):
                chained(self.ledger, gate)
            lines = self._lines()
            lines.insert(2, lines[1])           # a verbatim replay of line 2
            self._write(lines)
            r = build_report(str(self.ledger))
            self.assertFalse(r["pass"])
            self.assertEqual(r["problem"]["line"], 3)
            self.assertEqual(r["problem"]["reason"], "prev-mismatch")

        def test_removed_middle_record_fails(self):
            for gate in ("a.py", "b.py", "c.py"):
                chained(self.ledger, gate)
            lines = self._lines()
            del lines[1]
            self._write(lines)
            r = build_report(str(self.ledger))
            self.assertFalse(r["pass"])
            self.assertEqual(r["problem"]["reason"], "prev-mismatch")

        def test_legacy_then_chained_passes(self):
            legacy(self.ledger, "old_gate.py")
            legacy(self.ledger, "older_gate.py")
            chained(self.ledger, "check_commit_gate.py")
            chained(self.ledger, "mark_milestone.py")
            r = build_report(str(self.ledger))
            self.assertTrue(r["pass"], r)
            self.assertEqual((r["legacy_records"], r["chained_records"]), (2, 2))

        def test_chained_then_legacy_fails(self):
            chained(self.ledger, "check_commit_gate.py")
            legacy(self.ledger, "unchained_gate.py")
            r = build_report(str(self.ledger))
            self.assertFalse(r["pass"])
            self.assertEqual(r["problem"]["line"], 2)
            self.assertEqual(r["problem"]["reason"], "legacy-after-chained")

        # ---- the rest of the surface -----------------------------------

        def test_all_legacy_passes(self):
            legacy(self.ledger, "a.py")
            legacy(self.ledger, "b.py")
            self.assertTrue(build_report(str(self.ledger))["pass"])

        def test_empty_ledger_passes_with_zero_records(self):
            self.ledger.write_text("", encoding="utf-8")
            r = build_report(str(self.ledger))
            self.assertTrue(r["pass"])
            self.assertEqual(r["records"], 0)
            self.assertEqual(main(["--ledger", str(self.ledger)]), 0)

        def test_missing_ledger_is_exit_2(self):
            r = build_report(str(self.dir / "nope.jsonl"))
            self.assertFalse(r["pass"])
            self.assertIn("not found", r["error"])
            self.assertEqual(main(["--ledger", str(self.dir / "nope.jsonl")]), 2)

        def test_missing_flag_is_exit_2(self):
            self.assertEqual(main([]), 2)

        def test_blank_lines_are_ignored(self):
            chained(self.ledger, "a.py")
            with open(self.ledger, "a", encoding="utf-8") as fh:
                fh.write("\n   \n")
            chained(self.ledger, "b.py")
            r = build_report(str(self.ledger))
            self.assertTrue(r["pass"], r)
            self.assertEqual(r["records"], 2)

        def test_crlf_ledger_verifies(self):
            """Chaining hashes the line, not its terminator (Windows-safe)."""
            for gate in ("a.py", "b.py"):
                chained(self.ledger, gate)
            body = self.ledger.read_text(encoding="utf-8")
            self.ledger.write_bytes(body.replace("\n", "\r\n").encode("utf-8"))
            self.assertTrue(build_report(str(self.ledger))["pass"])

        def test_wrong_genesis_fails_on_line_1(self):
            chained(self.ledger, "a.py")
            lines = self._lines()
            rec = json.loads(lines[0])
            rec["prev"] = "0" * 64
            rec.pop("self")
            rec["self"] = ledger_self_hash(rec)
            self._write([json.dumps(rec)])
            r = build_report(str(self.ledger))
            self.assertFalse(r["pass"])
            self.assertEqual(r["problem"]["line"], 1)
            self.assertEqual(r["problem"]["reason"], "prev-mismatch")

        def test_incomplete_chain_fields_fail(self):
            chained(self.ledger, "a.py")
            lines = self._lines()
            rec = json.loads(lines[0])
            rec.pop("self")
            self._write([json.dumps(rec)])
            r = build_report(str(self.ledger))
            self.assertFalse(r["pass"])
            self.assertEqual(r["problem"]["reason"], "incomplete-chain-fields")

        def test_unparseable_line_fails(self):
            chained(self.ledger, "a.py")
            with open(self.ledger, "a", encoding="utf-8") as fh:
                fh.write("{not json\n")
            r = build_report(str(self.ledger))
            self.assertFalse(r["pass"])
            self.assertEqual(r["problem"]["line"], 2)
            self.assertEqual(r["problem"]["reason"], "unparseable")

        def test_field_reorder_alone_does_not_break_the_chain(self):
            """`self` is canonical (sort_keys), so key ORDER is not content.

            The line's own bytes still feed the NEXT record's `prev`, so a
            reordered line breaks the chain one line later — which is the
            honest answer: the file changed.
            """
            chained(self.ledger, "a.py")
            lines = self._lines()
            rec = json.loads(lines[0])
            self._write([json.dumps(dict(reversed(list(rec.items()))))])
            self.assertTrue(build_report(str(self.ledger))["pass"])

        def test_truncating_the_tail_is_undetectable_by_design(self):
            """The accepted limit, asserted so it cannot regress silently."""
            for gate in ("a.py", "b.py", "c.py"):
                chained(self.ledger, gate)
            lines = self._lines()
            self._write(lines[:2])
            self.assertTrue(build_report(str(self.ledger))["pass"])

        def test_unicode_record_round_trips(self):
            chained(self.ledger, "a.py", milestone="M3: Café — ünïcode")
            self.assertTrue(build_report(str(self.ledger))["pass"])

        # ---- drift guard across the family's nineteen copies -----------

        # Every gate that appends to a shared gates.jsonl. A missing comma
        # here is not a typo with no effect: `"update_state.py"` and
        # `"check_openapi_diff.py"` sat on adjacent lines with no comma
        # between them, so Python concatenated them into one name matching no
        # file, and BOTH gates dropped out of the guard below (which skips a
        # name whose file does not exist). Keep the trailing commas; the two
        # tests after this list are what make a recurrence loud.
        CHAINED_GATES = (
            "check_acceptance_suite.py",
            "check_agent_report.py",
            "check_always_on.py",
            "check_blockers.py",
            "check_bugfix_intake.py",
            "check_commit_gate.py",
            "check_coverage.py",
            "check_handoff.py",
            "check_openapi_diff.py",
            "check_quick_close.py",
            "check_red_green.py",
            "check_runtime_evidence.py",
            "check_runtime_recipe.py",
            "check_ship_decision.py",
            "check_tier1_provenance.py",
            "mark_milestone.py",
            "next_bugfix_route.py",
            "review_package.py",
            "update_state.py",
        )

        def test_the_chained_gate_list_names_only_real_files(self):
            """The missing-comma class, asserted rather than re-read."""
            here = Path(__file__).resolve().parent
            missing = [n for n in self.CHAINED_GATES
                       if not (here / n).is_file()]
            self.assertEqual(missing, [],
                             "CHAINED_GATES names files that do not exist "
                             "(a missing comma concatenates two entries)")
            self.assertEqual(len(set(self.CHAINED_GATES)),
                             len(self.CHAINED_GATES))

        def test_every_script_that_appends_a_ledger_is_listed(self):
            """The other direction: a new gate must join the guard."""
            here = Path(__file__).resolve().parent
            appending = []
            for script in sorted(here.glob("*.py")):
                if script.name == "check_ledger.py":
                    continue
                src = script.read_text(encoding="utf-8", errors="replace")
                if ("def append_ledger(" in src
                        and 'with open(p, "a", encoding="utf-8") as fh:' in src):
                    appending.append(script.name)
            self.assertEqual(
                sorted(set(appending) - set(self.CHAINED_GATES)), [],
                "these scripts append to a ledger but are not in "
                "CHAINED_GATES, so nothing checks that they chain")

        def test_the_chain_helper_is_byte_identical_everywhere(self):
            """One file each, no shared module -- so drift is what to test.

            A gate whose copy of the helper diverges writes a `prev` or `self`
            nobody else can verify, which reads as tampering.
            """
            here = Path(__file__).resolve().parent
            blocks = {}
            for script in sorted(here.glob("*.py")):
                src = script.read_text(encoding="utf-8", errors="replace")
                if "def ledger_line_hash(" not in src:
                    continue
                start = src.index("def ledger_line_hash(")
                end = src.index("def ledger_self_hash(")
                end = src.index(chr(10) * 3, end) + 1
                blocks.setdefault(src[start:end], []).append(script.name)
            self.assertGreaterEqual(len(blocks), 1)
            self.assertEqual(len(blocks), 1,
                             "the chain helper has drifted: " + repr(
                                 [v for v in blocks.values()]))

        def test_every_chained_gate_actually_chains_its_append(self):
            """The insertion, not just the helper: prev/self set before write."""
            here = Path(__file__).resolve().parent
            unchained = []
            for name in self.CHAINED_GATES:
                script = here / name
                if not script.is_file():
                    continue
                src = script.read_text(encoding="utf-8", errors="replace")
                if ('record["prev"] = ledger_prev_hash(p)' not in src
                        or 'record["self"] = ledger_self_hash(record)' not in src):
                    unchained.append(name)
            self.assertEqual(unchained, [],
                             "these gates append to the shared ledger without "
                             "chaining; every record they write after a chained "
                             "one is `legacy-after-chained`")

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CheckLedgerTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
