#!/usr/bin/env python3
"""Mechanical blockers-ledger gate for orchestrator-state.json.

Exit 0 only when the `blockers` array exists and is empty. Used by
bgpdd-shipping Step 0.5 (and any other pipeline that must refuse to
proceed over standing ledger entries). Pure standard library.

Usage:
    python check_blockers.py --state <path>
    python check_blockers.py --self-test
"""
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_state(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"state file not found or not readable: {path}")
    try:
        state = json.loads(p.read_text(encoding="utf-8", errors="replace"))
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
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.state:
        print(json.dumps({"pass": False, "error": "missing required argument: --state"}))
        return 2

    try:
        report = build_report(args.state)
    except GateError as exc:
        print(json.dumps({"pass": False, "error": str(exc)}))
        return 2

    print(json.dumps(report, indent=2))
    return 0 if report["pass"] else 1


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

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BlockersTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
