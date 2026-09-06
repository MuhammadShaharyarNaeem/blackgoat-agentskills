#!/usr/bin/env python3
"""Mechanical blockers-ledger gate for orchestrator-state.json.

Exit 0 only when the `blockers` array exists and is empty. Used by
bgpdd-shipping Step 0.5 (and any other pipeline that must refuse to
proceed over standing ledger entries). Pure standard library.

Usage:
    python check_blockers.py --state <path> [--milestone "<title>"] \
        [--severity-floor Critical|Important|Info] [--ledger <path>]
    python check_blockers.py --self-test
"""
import argparse
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

SEVERITIES = ("Critical", "Important", "Info")
SEVERITY_RANK = {"Critical": 3, "Important": 2, "Info": 1}
# Default floor: block on Critical and Important, ignore Info. Chosen so a
# state file with only legacy string entries (normalized to Critical) or
# pre-existing structured Critical/Important entries gates exactly as before
# --severity-floor existed -- Info is a new severity value nothing emitted
# prior to this change, so the default cannot silently unblock old data.
DEFAULT_SEVERITY_FLOOR = "Important"


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def normalize_blocker(entry):
    """A blocker array entry, structured-or-legacy, as one canonical shape.

    Duplicated from update_state.py by family convention (stdlib-only,
    one file each, no shared module). A legacy freeform string reads as
    unscoped (milestone null) and Critical -- the fail-safe reading.
    """
    if isinstance(entry, str):
        return {"id": None, "text": entry, "milestone": None,
                "capability": None, "severity": "Critical",
                "source": None, "added": None, "evidence": None}
    if isinstance(entry, dict):
        severity = entry.get("severity") or "Critical"
        if severity not in SEVERITIES:
            severity = "Critical"
        return {
            "id": entry.get("id"),
            "text": entry.get("text", ""),
            "milestone": entry.get("milestone"),
            "capability": entry.get("capability"),
            "severity": severity,
            "source": entry.get("source"),
            "added": entry.get("added"),
            "evidence": entry.get("evidence"),
        }
    return {"id": None, "text": json.dumps(entry), "milestone": None,
            "capability": None, "severity": "Critical",
            "source": None, "added": None, "evidence": None}


def milestone_equal(a, b):
    """Exact, case/whitespace-insensitive equality on the structured
    `milestone` field.

    Deliberately NOT the word-boundary substring match check_commit_gate.py
    uses to find a review-section heading matching a milestone title (per
    CLAUDE.md convention #8, a labeled divergence, tighter on purpose): that
    match exists because a review heading is free prose with no structured
    field to compare against. A blocker's `milestone` is a value someone
    wrote deliberately (via --blocker-milestone) to name one milestone, so
    exact equality is correct and closes exactly the ambiguity this schema
    was built to remove -- "not obviously this milestone's" is no longer
    indistinguishable from "not this milestone's" once scoping is a field,
    not a guess against freeform text.
    """
    return a.strip().casefold() == b.strip().casefold()


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
        record["prev"] = ledger_prev_hash(p)
        record["self"] = ledger_self_hash(record)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


def read_state(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"state file not found or not readable: {path}")
    try:
        # utf-8-sig: a BOM-prefixed state file is still valid JSON to a human
        # editor but json.loads chokes on the mark.
        state = json.loads(p.read_text(encoding="utf-8-sig", errors="replace"))
    except json.JSONDecodeError as exc:
        raise GateError(f"state file is not valid JSON: {exc}")
    if not isinstance(state, dict):
        raise GateError("state file does not contain a JSON object")
    if "blockers" not in state:
        raise GateError("state file has no 'blockers' field")
    blockers = state["blockers"]
    if not isinstance(blockers, list):
        raise GateError("'blockers' is not an array")
    return state, blockers


def build_report(state_path, milestone=None, severity_floor=DEFAULT_SEVERITY_FLOOR):
    state, raw_blockers = read_state(state_path)
    normalized = [normalize_blocker(b) for b in raw_blockers]
    floor_rank = SEVERITY_RANK[severity_floor]

    counted = [n for n in normalized if SEVERITY_RANK[n["severity"]] >= floor_rank]
    other_milestone = []
    if milestone is not None:
        blocking = [n for n in counted
                    if n["milestone"] is None or milestone_equal(n["milestone"], milestone)]
        other_milestone = [n for n in counted
                           if n["milestone"] is not None and not milestone_equal(n["milestone"], milestone)]
    else:
        # No milestone context to scope against -- every counted entry blocks,
        # matching the pre-existing "any entry blocks" behavior exactly.
        blocking = counted

    return {
        "state_file": state_path,
        "milestone": milestone,
        "severity_floor": severity_floor,
        "pass": len(blocking) == 0,
        "blocker_count": len(blocking),
        "blockers": normalized,
        "blocking": blocking,
        "other_milestone_blockers": other_milestone,
        "pipeline": state.get("pipeline"),
        "error": None,
    }


def main(argv):
    parser = argparse.ArgumentParser(prog="check_blockers.py")
    parser.add_argument("--state")
    parser.add_argument("--milestone",
                        help="scope: an entry blocks only if its milestone "
                             "matches this title exactly, or is null "
                             "(unscoped entries still block -- fail-safe)")
    parser.add_argument("--severity-floor", choices=list(SEVERITIES),
                        default=DEFAULT_SEVERITY_FLOOR,
                        help=f"minimum severity that blocks (default "
                             f"{DEFAULT_SEVERITY_FLOOR}: Critical and "
                             "Important block, Info is ignored)")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone,
                      [args.state] if args.state else [], verdict, code)
        return code

    if not args.state:
        print(json.dumps({"pass": False, "error": "missing required argument: --state"}))
        return finish(2, "ERROR")

    try:
        report = build_report(args.state, args.milestone, args.severity_floor)
    except GateError as exc:
        print(json.dumps({"pass": False, "error": str(exc)}))
        return finish(2, "ERROR")

    print(json.dumps(report, indent=2))
    return finish(0, "PASS") if report["pass"] else finish(1, "FAIL")


def run_self_test():
    import shutil

    class BlockersTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.state = self.dir / "orchestrator-state.json"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _write(self, obj):
            self.state.write_text(json.dumps(obj), encoding="utf-8")

        def test_empty_blockers_passes(self):
            self._write({"schema": "1", "blockers": [], "pipeline": "bgpdd-build"})
            report = build_report(str(self.state))
            self.assertTrue(report["pass"])
            self.assertEqual(report["blocker_count"], 0)

        def test_nonempty_blockers_fails(self):
            self._write({"schema": "1", "blockers": ["M1: open finding"]})
            report = build_report(str(self.state))
            self.assertFalse(report["pass"])
            self.assertEqual(report["blocker_count"], 1)

        def test_missing_blockers_field_raises(self):
            self._write({"schema": "1"})
            with self.assertRaises(GateError):
                build_report(str(self.state))

        def test_missing_file_raises(self):
            with self.assertRaises(GateError):
                build_report(str(self.dir / "missing.json"))

        def test_bom_prefixed_state_still_parses(self):
            """utf-8 (not -sig) made json.loads choke on the byte-order mark."""
            self.state.write_bytes(
                b"\xef\xbb\xbf" + json.dumps({"blockers": []}).encode("utf-8"))
            self.assertTrue(build_report(str(self.state))["pass"])

        def test_reports_normalized_objects(self):
            self._write({"schema": "1", "blockers": [
                "legacy freeform",
                {"id": "B-1", "text": "structured", "milestone": "M3",
                 "severity": "Important"},
            ]})
            report = build_report(str(self.state))
            self.assertEqual(report["blockers"][0],
                             {"id": None, "text": "legacy freeform", "milestone": None,
                              "capability": None, "severity": "Critical",
                              "source": None, "added": None, "evidence": None})
            self.assertEqual(report["blockers"][1]["id"], "B-1")
            self.assertEqual(report["blockers"][1]["severity"], "Important")

        def test_milestone_scoping_same_milestone_blocks(self):
            self._write({"schema": "1", "blockers": [
                {"id": "B-1", "text": "x", "milestone": "M3 — Auth"}]})
            report = build_report(str(self.state), milestone="M3 — Auth")
            self.assertFalse(report["pass"])
            self.assertEqual(len(report["blocking"]), 1)
            self.assertEqual(report["other_milestone_blockers"], [])

        def test_milestone_scoping_is_case_and_whitespace_insensitive(self):
            self._write({"schema": "1", "blockers": [
                {"id": "B-1", "text": "x", "milestone": " m3 — auth "}]})
            report = build_report(str(self.state), milestone="M3 — Auth")
            self.assertFalse(report["pass"])

        def test_milestone_scoping_null_milestone_still_blocks(self):
            """Fail-safe refinement of the old 'gate on all' rule (CLAUDE.md
            convention #8): an entry with no recorded milestone still blocks
            any milestone's gate run."""
            self._write({"schema": "1", "blockers": [
                {"id": "B-1", "text": "x", "milestone": None}]})
            report = build_report(str(self.state), milestone="M3 — Auth")
            self.assertFalse(report["pass"])
            self.assertEqual(len(report["blocking"]), 1)

        def test_milestone_scoping_different_milestone_does_not_block(self):
            self._write({"schema": "1", "blockers": [
                {"id": "B-1", "text": "x", "milestone": "M10 — Other"}]})
            report = build_report(str(self.state), milestone="M3 — Auth")
            self.assertTrue(report["pass"])
            self.assertEqual(report["blocking"], [])
            self.assertEqual(len(report["other_milestone_blockers"]), 1)
            self.assertEqual(report["other_milestone_blockers"][0]["id"], "B-1")

        def test_severity_floor_default_ignores_info(self):
            self._write({"schema": "1", "blockers": [
                {"id": "B-1", "text": "cosmetic", "severity": "Info"}]})
            report = build_report(str(self.state))
            self.assertTrue(report["pass"])
            self.assertEqual(report["blocker_count"], 0)

        def test_severity_floor_default_still_blocks_important(self):
            self._write({"schema": "1", "blockers": [
                {"id": "B-1", "text": "x", "severity": "Important"}]})
            report = build_report(str(self.state))
            self.assertFalse(report["pass"])

        def test_severity_floor_critical_ignores_important(self):
            self._write({"schema": "1", "blockers": [
                {"id": "B-1", "text": "x", "severity": "Important"}]})
            report = build_report(str(self.state), severity_floor="Critical")
            self.assertTrue(report["pass"])

        def test_severity_floor_info_blocks_everything(self):
            self._write({"schema": "1", "blockers": [
                {"id": "B-1", "text": "x", "severity": "Info"}]})
            report = build_report(str(self.state), severity_floor="Info")
            self.assertFalse(report["pass"])

        def test_without_milestone_any_entry_blocks_unchanged(self):
            """Legacy-data backward compatibility: with no --milestone, a
            structured entry scoped to some OTHER milestone still blocks --
            there is no milestone context to exempt it against."""
            self._write({"schema": "1", "blockers": [
                {"id": "B-1", "text": "x", "milestone": "M10 — Other"}]})
            report = build_report(str(self.state))
            self.assertFalse(report["pass"])
            self.assertEqual(report["other_milestone_blockers"], [])

        def test_ledger_records_every_exit_path(self):
            ledger = self.dir / "logs" / "gates.jsonl"
            self._write({"schema": "1", "blockers": []})
            self.assertEqual(main(["--state", str(self.state),
                                   "--ledger", str(ledger)]), 0)
            self._write({"schema": "1", "blockers": ["M1: open finding"]})
            self.assertEqual(main(["--state", str(self.state),
                                   "--ledger", str(ledger)]), 1)
            self.assertEqual(main(["--ledger", str(ledger)]), 2)
            records = [json.loads(l) for l in
                       ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual([r["verdict"] for r in records],
                             ["PASS", "FAIL", "ERROR"])
            self.assertTrue(all(r["gate"] == "check_blockers.py" for r in records))
            self.assertEqual(records[1]["inputs"][str(self.state)],
                             sha256_file(self.state))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BlockersTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
