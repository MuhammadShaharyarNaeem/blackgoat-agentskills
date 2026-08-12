#!/usr/bin/env python3
"""Deterministic read-modify-write CLI for orchestrator-state.json.

Replaces hand-edits of `.docs/{project}/orchestrator-state.json`, which risk
malformed JSON and silent blocker deletion. Every invocation validates the
existing file (if any), applies the requested actions, stamps "updated",
and writes atomically (temp file + os.replace) before printing the
resulting full state as JSON to stdout.

Usage:
    python update_state.py --state <path> \
        [--init --project-name <name>] \
        [--set-cursor <title|null>] [--set-pipeline <name>] \
        [--set-feature <feature|null>] [--set-branch <name>] \
        [--set-artifact <name>=<path>] \
        [--add-blocker "<text>"] \
        [--resolve-blocker "<substring>" --evidence "<text>"]
    python update_state.py --self-test

Pure standard library. See ../SKILL.md for the full contract.
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1"


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_skeleton(project_name):
    return {
        "schema": SCHEMA_VERSION,
        "project_name": project_name,
        "feature": None,
        "pipeline": "",
        "branch": None,
        "milestone_cursor": None,
        "artifacts": {},
        "blockers": [],
    }


def validate_actions(args):
    """Raise GateError for any invalid CLI action combination."""
    has_action = any([
        args.init,
        args.set_cursor is not None,
        args.set_pipeline is not None,
        args.set_branch is not None,
        args.set_feature is not None,
        bool(args.set_artifact),
        bool(args.add_blocker),
        args.resolve_blocker is not None,
    ])
    if not has_action:
        raise GateError("at least one action is required (see --help)")
    if args.resolve_blocker is not None and not (args.evidence and args.evidence.strip()):
        raise GateError(
            "--resolve-blocker requires --evidence: per the ledger doctrine "
            "(orchestrator-contract §4), a blocker entry is removed only "
            "once its fix is verified")
    if args.init and not args.project_name:
        raise GateError("--init requires --project-name")


def coerce_schema(state, warnings):
    """Normalize legacy numeric schema 1 → string \"1\" (plan/README drift)."""
    schema = state.get("schema")
    if schema == 1 or schema == "1":
        if schema != SCHEMA_VERSION:
            warnings.append(
                f'coerced schema {schema!r} → {SCHEMA_VERSION!r} '
                f'(authority: SCHEMA_VERSION string)')
        state["schema"] = SCHEMA_VERSION
    elif schema is None:
        state["schema"] = SCHEMA_VERSION
        warnings.append(f'schema missing; set to {SCHEMA_VERSION!r}')
    elif schema != SCHEMA_VERSION:
        raise GateError(
            f"unsupported schema version {schema!r}; expected {SCHEMA_VERSION!r}")


def load_state(path, init, project_name):
    """Load the existing state file, or build a skeleton for --init.

    Returns (state, warnings). Raises GateError on missing/invalid file.
    """
    warnings = []
    if path.exists():
        text = path.read_text(encoding="utf-8")
        try:
            state = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GateError(f"state file is not valid JSON: {exc}")
        if not isinstance(state, dict):
            raise GateError("state file does not contain a JSON object")
        coerce_schema(state, warnings)
        if init:
            warnings.append("--init is a no-op: state file already exists")
        return state, warnings
    if not init:
        raise GateError(f"state file not found: {path} (use --init to create it)")
    return build_skeleton(project_name), warnings


def parse_artifact_spec(spec):
    if "=" not in spec:
        raise GateError(f"invalid --set-artifact value {spec!r}; expected name=path")
    name, _, value = spec.partition("=")
    if not name:
        raise GateError(f"invalid --set-artifact value {spec!r}; expected name=path")
    return name, value


def resolve_blocker(state, substring, evidence, timestamp):
    """Remove every blocker containing `substring` (case-insensitive).

    Returns log lines (ISO timestamp, removed entry, evidence) to append to
    the sibling blockers-resolved.log, or a warning if nothing matched.
    """
    needle = substring.lower()
    blockers = state.get("blockers", [])
    matched = [b for b in blockers if needle in str(b).lower()]
    if not matched:
        return [], [f"--resolve-blocker matched no entries for {substring!r}; nothing removed"]
    state["blockers"] = [b for b in blockers if needle not in str(b).lower()]
    log_lines = [f"{timestamp}\t{entry}\t{evidence}" for entry in matched]
    return log_lines, []


def write_atomic(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".update_state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
        os.replace(tmp_name, str(path))
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def apply_updates(args):
    """Validate, load, mutate, write, and return (state, warnings)."""
    validate_actions(args)
    path = Path(args.state)
    state, warnings = load_state(path, args.init, args.project_name)

    if args.set_cursor is not None:
        state["milestone_cursor"] = None if args.set_cursor == "null" else args.set_cursor
    if args.set_pipeline is not None:
        state["pipeline"] = args.set_pipeline
    if args.set_branch is not None:
        state["branch"] = args.set_branch
    if args.set_feature is not None:
        state["feature"] = None if args.set_feature == "null" else args.set_feature
    for spec in args.set_artifact:
        name, value = parse_artifact_spec(spec)
        state.setdefault("artifacts", {})[name] = value
    for text in args.add_blocker:
        state.setdefault("blockers", []).append(text)

    timestamp = now_iso()
    log_lines = []
    if args.resolve_blocker is not None:
        log_lines, resolve_warnings = resolve_blocker(state, args.resolve_blocker,
                                                       args.evidence, timestamp)
        warnings += resolve_warnings

    state["updated"] = timestamp
    write_atomic(path, state)
    if log_lines:
        log_path = path.parent / "blockers-resolved.log"
        with open(log_path, "a", encoding="utf-8") as f:
            for line in log_lines:
                f.write(line + "\n")

    return state, warnings


def build_parser():
    parser = argparse.ArgumentParser(prog="update_state.py")
    parser.add_argument("--state")
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--project-name")
    parser.add_argument("--set-cursor")
    parser.add_argument("--set-pipeline")
    parser.add_argument("--set-branch")
    parser.add_argument(
        "--set-feature",
        help='Tier-1 durable feature id, or the literal "null" for greenfield',
    )
    parser.add_argument("--set-artifact", action="append", default=[])
    parser.add_argument("--add-blocker", action="append", default=[])
    parser.add_argument("--resolve-blocker")
    parser.add_argument("--evidence")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.state:
        print(json.dumps({"error": "--state is required"}))
        return 2

    try:
        state, warnings = apply_updates(args)
    except GateError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2

    for w in warnings:
        print(f"Warning: {w}", file=sys.stderr)
    print(json.dumps(state, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil
    import unittest

    def ns(state_path, **overrides):
        base = dict(state=str(state_path), init=False, project_name=None,
                    set_cursor=None, set_pipeline=None, set_branch=None,
                    set_feature=None, set_artifact=[], add_blocker=[],
                    resolve_blocker=None, evidence=None)
        base.update(overrides)
        return argparse.Namespace(**base)

    class UpdateStateTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.state_path = self.dir / "orchestrator-state.json"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def test_init_creates_skeleton(self):
            state, warnings = apply_updates(ns(self.state_path, init=True,
                                              project_name="demo"))
            self.assertEqual(warnings, [])
            self.assertEqual(state["schema"], "1")
            self.assertEqual(state["project_name"], "demo")
            self.assertIsNone(state["feature"])
            self.assertEqual(state["pipeline"], "")
            self.assertIsNone(state["branch"])
            self.assertIsNone(state["milestone_cursor"])
            self.assertEqual(state["artifacts"], {})
            self.assertEqual(state["blockers"], [])
            self.assertIn("updated", state)
            on_disk = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk, state)

        def test_init_on_existing_file_is_noop_warning(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            state, warnings = apply_updates(ns(self.state_path, init=True,
                                              project_name="other",
                                              set_pipeline="bgpdd-build"))
            self.assertTrue(any("no-op" in w for w in warnings))
            self.assertEqual(state["project_name"], "demo")  # untouched
            self.assertEqual(state["pipeline"], "bgpdd-build")

        def test_combined_cursor_pipeline_branch_in_one_call(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            self.state_path.write_text(
                json.dumps({**json.loads(self.state_path.read_text()),
                           "updated": "SENTINEL"}))
            state, _ = apply_updates(ns(
                self.state_path, set_cursor="M2 - Auth",
                set_pipeline="bgpdd-build", set_branch="feature/auth"))
            self.assertEqual(state["milestone_cursor"], "M2 - Auth")
            self.assertEqual(state["pipeline"], "bgpdd-build")
            self.assertEqual(state["branch"], "feature/auth")
            self.assertNotEqual(state["updated"], "SENTINEL")

        def test_set_cursor_null_sets_json_null(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             set_cursor="M1"))
            state, _ = apply_updates(ns(self.state_path, set_cursor="null"))
            self.assertIsNone(state["milestone_cursor"])

        def test_set_feature_and_null(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             set_feature="slide"))
            state, _ = apply_updates(ns(self.state_path, set_feature="null"))
            self.assertIsNone(state["feature"])

        def test_coerces_numeric_schema_1(self):
            self.state_path.write_text(json.dumps({
                "schema": 1, "project_name": "demo", "feature": None,
                "pipeline": "", "branch": None, "milestone_cursor": None,
                "artifacts": {}, "blockers": [],
            }), encoding="utf-8")
            state, warnings = apply_updates(ns(self.state_path,
                                               set_pipeline="bgpdd-plan"))
            self.assertEqual(state["schema"], "1")
            self.assertTrue(any("coerced schema" in w for w in warnings))

        def test_add_blocker_appends_preserving_existing(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["first blocker"]))
            state, _ = apply_updates(ns(self.state_path,
                                       add_blocker=["second blocker"]))
            self.assertEqual(state["blockers"], ["first blocker", "second blocker"])

        def test_resolve_blocker_with_evidence_removes_and_logs(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open",
                                         "unrelated blocker"]))
            state, warnings = apply_updates(ns(
                self.state_path, resolve_blocker="placeholder route",
                evidence="verified via test-report.md M3 section"))
            self.assertEqual(warnings, [])
            self.assertEqual(state["blockers"], ["unrelated blocker"])
            log_path = self.dir / "blockers-resolved.log"
            self.assertTrue(log_path.exists())
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("M3: placeholder route open", log_text)
            self.assertIn("verified via test-report.md M3 section", log_text)

        def test_resolve_blocker_without_evidence_fails_and_leaves_file(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open"]))
            before = self.state_path.read_text(encoding="utf-8")
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path,
                                 resolve_blocker="placeholder route"))
            after = self.state_path.read_text(encoding="utf-8")
            self.assertEqual(before, after)
            self.assertFalse((self.dir / "blockers-resolved.log").exists())

        def test_resolve_blocker_matching_nothing_warns(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["unrelated blocker"]))
            state, warnings = apply_updates(ns(
                self.state_path, resolve_blocker="no such substring",
                evidence="n/a"))
            self.assertTrue(any("nothing removed" in w for w in warnings))
            self.assertEqual(state["blockers"], ["unrelated blocker"])

        def test_invalid_json_file_raises(self):
            self.state_path.write_text("{not valid json")
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path, set_pipeline="bgpdd-build"))

        def test_missing_file_without_init_raises(self):
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path, set_pipeline="bgpdd-build"))

        def test_init_without_project_name_raises(self):
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path, init=True))

        def test_no_action_raises(self):
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path))

        def test_set_artifact(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo"))
            state, _ = apply_updates(ns(
                self.state_path,
                set_artifact=["plan=.docs/demo/plan.md", "design=.docs/demo/design.md"]))
            self.assertEqual(state["artifacts"], {
                "plan": ".docs/demo/plan.md", "design": ".docs/demo/design.md"})

        def test_main_exit_codes(self):
            import contextlib
            import io

            argv_missing_file = ["--state", str(self.state_path),
                                 "--set-pipeline", "x"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(argv_missing_file)
            self.assertEqual(rc, 2)

            argv_init = ["--state", str(self.state_path), "--init",
                        "--project-name", "demo"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(argv_init)
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(buf.getvalue())["project_name"], "demo")

            argv_no_evidence = ["--state", str(self.state_path),
                                "--add-blocker", "b1"]
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(argv_no_evidence)
            self.assertEqual(rc, 0)

            argv_resolve_no_evidence = ["--state", str(self.state_path),
                                        "--resolve-blocker", "b1"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = main(argv_resolve_no_evidence)
            self.assertEqual(rc, 2)
            self.assertIn("error", json.loads(buf.getvalue()))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(UpdateStateTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
