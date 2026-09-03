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
        [--resolve-blocker "<substring>" --evidence "<text>"] \
        [--ledger <path>]
    python update_state.py --self-test

Pure standard library. See ../SKILL.md for the full contract.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1"
SEVERITIES = ("Critical", "Important", "Info")
BLOCKER_ID_RE = re.compile(r"^B-(\d+)$")


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""

    def __init__(self, message, candidates=None):
        super().__init__(message)
        # Populated only for an ambiguous --resolve-blocker substring match,
        # so the caller can print the candidate entries alongside the error.
        self.candidates = candidates


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def append_ledger(ledger_path, argv, milestone, inputs, verdict, exit_code,
                  extra=None):
    """Append ONE JSON line recording this run. Best-effort by design.

    The state file's hash is taken AFTER the write, so the record describes
    the state a later gate will actually read.

    `--resolve-blocker` additionally records the action and the evidence
    string, which is the load-bearing part: the CLI cannot judge whether
    "trust me" is real evidence, but with a ledger the claim is durable,
    attributable and reviewable rather than gone the moment the array shrinks.
    """
    if not ledger_path:
        return
    record = {
        "ts": now_iso(),
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
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


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
    blocker_companions_given = any([
        args.blocker_milestone is not None,
        args.blocker_capability is not None,
        args.blocker_severity is not None,
        args.blocker_source is not None,
        args.blocker_evidence is not None,
    ])
    if blocker_companions_given and not args.add_blocker:
        raise GateError(
            "--blocker-milestone/--blocker-capability/--blocker-severity/"
            "--blocker-source/--blocker-evidence require --add-blocker in "
            "the same invocation")


def normalize_blocker(entry):
    """A blocker array entry, structured-or-legacy, as one canonical shape.

    A legacy freeform string is read as `{id: null, text: <string>,
    milestone: null, capability: null, severity: "Critical", source: null,
    added: null, evidence: null}` -- unscoped and Critical, the fail-safe
    reading. This function never mutates the stored entry; callers that
    write back to `state["blockers"]` keep untouched entries in their
    original raw form (string or dict).
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
    # Defensive: an entry that is neither -- stringify rather than crash.
    return {"id": None, "text": json.dumps(entry), "milestone": None,
            "capability": None, "severity": "Critical",
            "source": None, "added": None, "evidence": None}


def next_blocker_id(blockers):
    """The next `B-<n>` id: one past the highest structured id currently
    present in the array. Legacy string entries (id null) don't count.

    Scoped to entries currently in the array, not the file's full history --
    resolving away the highest-numbered entry and then adding a new one can
    reuse its number. Documented limitation, not prevented: see
    references/update_state.md.
    """
    max_n = 0
    for entry in blockers:
        m = BLOCKER_ID_RE.match(normalize_blocker(entry)["id"] or "")
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


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
        # utf-8-sig: a BOM-prefixed state file is valid to an editor but
        # json.loads chokes on the mark.
        text = path.read_text(encoding="utf-8-sig")
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
    """Parse `name=path`. The literal value `null` stores JSON null.

    Matches --set-cursor / --set-feature. Without this, `design=null` (what
    bgpdd-lite emits when no stack contract governs) stored the truthy STRING
    "null", and bgpdd-build's "when non-null, inject artifacts.design as the
    architecture reference" rule injected it as a path.
    """
    if "=" not in spec:
        raise GateError(f"invalid --set-artifact value {spec!r}; expected name=path")
    name, _, value = spec.partition("=")
    if not name:
        raise GateError(f"invalid --set-artifact value {spec!r}; expected name=path")
    return name, (None if value == "null" else value)


def resolve_blocker(state, target, evidence, timestamp):
    """Resolve one or more blockers matching `target`, in priority order:

    1. exact `id` match ("B-3")
    2. exact `text` match (case-insensitive) -- removes every entry sharing
       that exact text, the same "resolve all duplicates" behavior this
       replaces
    3. substring match (case-insensitive) against `text` -- must be UNIQUE,
       or the call is refused (GateError, ambiguous) rather than silently
       removing more than the caller meant to name

    Returns (log_lines, warnings, removed_entries). `log_lines` are ISO
    timestamp / id / full JSON entry / evidence, appended to the sibling
    blockers-resolved.log. A target matching nothing warns and changes
    nothing.
    """
    blockers = state.get("blockers", [])
    normalized = [normalize_blocker(b) for b in blockers]

    id_idxs = [i for i, n in enumerate(normalized)
               if n["id"] is not None and n["id"] == target]
    if id_idxs:
        idxs = id_idxs
    else:
        needle = target.strip().lower()
        text_idxs = [i for i, n in enumerate(normalized)
                     if n["text"].lower() == needle]
        if text_idxs:
            idxs = text_idxs
        else:
            sub_idxs = [i for i, n in enumerate(normalized)
                        if needle in n["text"].lower()]
            if not sub_idxs:
                return [], [f"--resolve-blocker matched no entries for {target!r}; nothing removed"], []
            if len(sub_idxs) > 1:
                candidates = [normalized[i] for i in sub_idxs]
                raise GateError(
                    f"--resolve-blocker {target!r} matches {len(sub_idxs)} entries "
                    "ambiguously; be more specific (an id, or the exact text) -- "
                    f"candidates: {json.dumps(candidates)}",
                    candidates=candidates)
            idxs = sub_idxs

    idxset = set(idxs)
    removed = [normalized[i] for i in idxs]
    state["blockers"] = [b for i, b in enumerate(blockers) if i not in idxset]
    log_lines = [f"{timestamp}\t{entry['id'] or ''}\t"
                 f"{json.dumps(entry, ensure_ascii=False)}\t{evidence}"
                 for entry in removed]
    return log_lines, [], removed


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
    timestamp = now_iso()

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
    if args.add_blocker:
        blockers = state.setdefault("blockers", [])
        next_n = next_blocker_id(blockers)
        severity = args.blocker_severity or "Critical"
        for text in args.add_blocker:
            blockers.append({
                "id": f"B-{next_n}",
                "text": text,
                "milestone": args.blocker_milestone,
                "capability": args.blocker_capability,
                "severity": severity,
                "source": args.blocker_source,
                "added": timestamp,
                "evidence": args.blocker_evidence,
            })
            next_n += 1

    log_lines = []
    removed_entries = []
    if args.resolve_blocker is not None:
        log_lines, resolve_warnings, removed_entries = resolve_blocker(
            state, args.resolve_blocker, args.evidence, timestamp)
        warnings += resolve_warnings
    # Stashed on the Namespace (not returned) so main()'s ledger closure can
    # cite the resolved entries without widening this function's return
    # shape -- every existing call site unpacks (state, warnings).
    args.resolved_entries = removed_entries

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
    parser.add_argument("--blocker-milestone",
                        help="applies to every --add-blocker in this invocation")
    parser.add_argument("--blocker-capability",
                        help='e.g. "browser", "docker", "device"; applies to '
                             "every --add-blocker in this invocation")
    parser.add_argument("--blocker-severity", choices=list(SEVERITIES),
                        help="default Critical; applies to every --add-blocker "
                             "in this invocation")
    parser.add_argument("--blocker-source",
                        help="agent or gate that raised it; applies to every "
                             "--add-blocker in this invocation")
    parser.add_argument("--blocker-evidence",
                        help="applies to every --add-blocker in this invocation "
                             "(distinct from --evidence, which is --resolve-blocker's)")
    parser.add_argument("--resolve-blocker",
                        help="an id (\"B-3\"), exact text, or a substring that "
                             "must match exactly one entry's text")
    parser.add_argument("--evidence")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        extra = None
        if args.resolve_blocker is not None:
            extra = {"action": "resolve-blocker",
                     "evidence": args.evidence}
            resolved = getattr(args, "resolved_entries", None)
            if resolved:
                extra["resolved_ids"] = [e.get("id") for e in resolved]
                extra["resolved_entries"] = resolved
        # The cursor names the milestone this run is about, when it names one;
        # the literal "null" clears it and is recorded as JSON null.
        milestone = (None if args.set_cursor in (None, "null")
                     else args.set_cursor)
        append_ledger(args.ledger, argv, milestone,
                      [args.state] if args.state else [], verdict, code, extra)
        return code

    if not args.state:
        print(json.dumps({"error": "--state is required"}))
        return finish(2, "ERROR")

    try:
        state, warnings = apply_updates(args)
    except GateError as exc:
        payload = {"error": str(exc)}
        if exc.candidates is not None:
            payload["candidates"] = exc.candidates
        print(json.dumps(payload))
        return finish(2, "ERROR")

    for w in warnings:
        print(f"Warning: {w}", file=sys.stderr)
    print(json.dumps(state, indent=2))
    return finish(0, "PASS")


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
                    blocker_milestone=None, blocker_capability=None,
                    blocker_severity=None, blocker_source=None,
                    blocker_evidence=None,
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

        def test_set_artifact_null_sets_json_null(self):
            """bgpdd-lite emits design=null when no stack contract governs."""
            state, _ = apply_updates(ns(
                self.state_path, init=True, project_name="demo",
                set_artifact=["requirements=.docs/demo/requirements.md",
                              "design=null"]))
            self.assertIsNone(state["artifacts"]["design"])
            self.assertEqual(state["artifacts"]["requirements"],
                             ".docs/demo/requirements.md")

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
            self.assertEqual([b["text"] for b in state["blockers"]],
                             ["first blocker", "second blocker"])

        def test_add_blocker_creates_structured_entry_with_defaults(self):
            """`--add-blocker` alone: auto id, Critical severity, null milestone."""
            state, warnings = apply_updates(ns(self.state_path, init=True,
                                              project_name="demo",
                                              add_blocker=["route missing auth"]))
            self.assertEqual(warnings, [])
            entry = state["blockers"][0]
            self.assertEqual(entry["id"], "B-1")
            self.assertEqual(entry["text"], "route missing auth")
            self.assertIsNone(entry["milestone"])
            self.assertIsNone(entry["capability"])
            self.assertEqual(entry["severity"], "Critical")
            self.assertIsNone(entry["source"])
            self.assertIn("added", entry)
            self.assertIsNone(entry["evidence"])

        def test_add_blocker_companions_apply_to_every_text_in_the_call(self):
            state, _ = apply_updates(ns(
                self.state_path, init=True, project_name="demo",
                add_blocker=["no docker in CI", "no docker on staging"],
                blocker_milestone="M4 — Deploy", blocker_capability="docker",
                blocker_severity="Important", blocker_source="dep",
                blocker_evidence="observed in CI log"))
            for entry in state["blockers"]:
                self.assertEqual(entry["milestone"], "M4 — Deploy")
                self.assertEqual(entry["capability"], "docker")
                self.assertEqual(entry["severity"], "Important")
                self.assertEqual(entry["source"], "dep")
                self.assertEqual(entry["evidence"], "observed in CI log")
            self.assertEqual([e["id"] for e in state["blockers"]], ["B-1", "B-2"])

        def test_blocker_companion_without_add_blocker_is_usage_error(self):
            with self.assertRaises(GateError):
                apply_updates(ns(self.state_path, init=True, project_name="demo",
                                 blocker_milestone="M1"))

        def test_add_blocker_id_increments_across_calls(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["a"]))
            apply_updates(ns(self.state_path, add_blocker=["b", "c"]))
            state, _ = apply_updates(ns(self.state_path, add_blocker=["d"]))
            self.assertEqual([e["id"] for e in state["blockers"]],
                             ["B-1", "B-2", "B-3", "B-4"])

        def test_add_blocker_preserves_legacy_string_entries_untouched(self):
            """Mixed array: a pre-existing legacy string is never rewritten."""
            self.state_path.write_text(json.dumps({
                "schema": "1", "project_name": "demo", "feature": None,
                "pipeline": "", "branch": None, "milestone_cursor": None,
                "artifacts": {}, "blockers": ["legacy freeform blocker"],
            }), encoding="utf-8")
            state, _ = apply_updates(ns(self.state_path,
                                        add_blocker=["new structured one"]))
            self.assertEqual(state["blockers"][0], "legacy freeform blocker")
            self.assertIsInstance(state["blockers"][1], dict)
            self.assertEqual(state["blockers"][1]["id"], "B-1")

        def test_resolve_blocker_with_evidence_removes_and_logs(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open",
                                         "unrelated blocker"]))
            state, warnings = apply_updates(ns(
                self.state_path, resolve_blocker="placeholder route",
                evidence="verified via test-report.md M3 section"))
            self.assertEqual(warnings, [])
            self.assertEqual(len(state["blockers"]), 1)
            self.assertEqual(state["blockers"][0]["text"], "unrelated blocker")
            log_path = self.dir / "blockers-resolved.log"
            self.assertTrue(log_path.exists())
            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("M3: placeholder route open", log_text)
            self.assertIn("verified via test-report.md M3 section", log_text)
            self.assertIn("B-1", log_text)

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
            self.assertEqual(len(state["blockers"]), 1)
            self.assertEqual(state["blockers"][0]["text"], "unrelated blocker")

        def test_resolve_blocker_by_exact_id(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["first", "second"]))
            state, _ = apply_updates(ns(self.state_path, resolve_blocker="B-1",
                                        evidence="fixed"))
            self.assertEqual(len(state["blockers"]), 1)
            self.assertEqual(state["blockers"][0]["id"], "B-2")

        def test_resolve_blocker_by_exact_text(self):
            """Exact text match wins over a broader substring reading, and
            removes every entry sharing that exact text."""
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["route open", "route open extended"]))
            state, _ = apply_updates(ns(self.state_path, resolve_blocker="route open",
                                        evidence="fixed"))
            self.assertEqual(len(state["blockers"]), 1)
            self.assertEqual(state["blockers"][0]["text"], "route open extended")

        def test_resolve_blocker_ambiguous_substring_exits_2_with_candidates(self):
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["auth route missing check",
                                         "billing route missing check"]))
            with self.assertRaises(GateError) as ctx:
                apply_updates(ns(self.state_path, resolve_blocker="route missing",
                                 evidence="fixed"))
            self.assertEqual(len(ctx.exception.candidates), 2)
            # Nothing removed on the refusal.
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            self.assertEqual(len(state["blockers"]), 2)

        def test_ledger_resolve_blocker_records_id_and_full_entry(self):
            import contextlib
            import io

            ledger = self.dir / "gates.jsonl"
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open"],
                             blocker_milestone="M3"))
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path),
                           "--resolve-blocker", "B-1",
                           "--evidence", "retested, passes",
                           "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["resolved_ids"], ["B-1"])
            self.assertEqual(rec["resolved_entries"][0]["milestone"], "M3")
            self.assertEqual(rec["resolved_entries"][0]["text"],
                             "M3: placeholder route open")

        def test_bom_prefixed_state_still_loads(self):
            """utf-8 (not -sig) made json.loads choke on the byte-order mark."""
            self.state_path.write_bytes(b"\xef\xbb\xbf" + json.dumps({
                "schema": "1", "project_name": "demo", "feature": None,
                "pipeline": "", "branch": None, "milestone_cursor": None,
                "artifacts": {}, "blockers": [],
            }).encode("utf-8"))
            state, _ = apply_updates(ns(self.state_path,
                                        set_pipeline="bgpdd-build"))
            self.assertEqual(state["pipeline"], "bgpdd-build")

        # ---- the shared gate ledger ----

        def _ledger_records(self, path):
            return [json.loads(l) for l in
                    Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

        def test_ledger_records_success_and_usage_error(self):
            import contextlib
            import io

            ledger = self.dir / "logs" / "gates.jsonl"
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path), "--init",
                           "--project-name", "demo", "--set-cursor", "M2 — Auth",
                           "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--ledger", str(ledger)])
            self.assertEqual(rc, 2)
            records = self._ledger_records(ledger)
            self.assertEqual([r["verdict"] for r in records], ["PASS", "ERROR"])
            self.assertEqual(records[0]["gate"], "update_state.py")
            self.assertEqual(records[0]["milestone"], "M2 — Auth")
            self.assertEqual(records[0]["inputs"][str(self.state_path)],
                             sha256_file(self.state_path))
            self.assertNotIn("action", records[0])

        def test_ledger_records_the_resolve_blocker_evidence(self):
            """The evidence string is unjudgeable — so it must be durable."""
            import contextlib
            import io

            ledger = self.dir / "gates.jsonl"
            apply_updates(ns(self.state_path, init=True, project_name="demo",
                             add_blocker=["M3: placeholder route open"]))
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--state", str(self.state_path),
                           "--resolve-blocker", "placeholder route",
                           "--evidence", "trust me",
                           "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["action"], "resolve-blocker")
            self.assertEqual(rec["evidence"], "trust me")
            self.assertEqual(rec["verdict"], "PASS")

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
