#!/usr/bin/env python3
"""Mechanical blockers-ledger gate for orchestrator-state.json.

Exit 0 only when the `blockers` array exists and is empty. Used by
bgpdd-shipping Step 0.5 (and any other pipeline that must refuse to
proceed over standing ledger entries). Pure standard library.

Usage:
    python check_blockers.py --state <path> [--ledger <path>]
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


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


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


def build_report(state_path):
    state, blockers = read_state(state_path)
    return {
        "state_file": state_path,
        "pass": len(blockers) == 0,
        "blocker_count": len(blockers),
        "blockers": blockers,
        "pipeline": state.get("pipeline"),
        "error": None,
    }


def main(argv):
    parser = argparse.ArgumentParser(prog="check_blockers.py")
    parser.add_argument("--state")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, None,
                      [args.state] if args.state else [], verdict, code)
        return code

    if not args.state:
        print(json.dumps({"pass": False, "error": "missing required argument: --state"}))
        return finish(2, "ERROR")

    try:
        report = build_report(args.state)
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
