#!/usr/bin/env python3
"""Append ONE run-telemetry record to the run log.

The gate ledger (`gates.jsonl`) records which gates fired. This records what
the run COST: which agent ran, under which model, for how long, for how many
tokens, across how many rounds. Together they are the mechanical half of the
evidence Forge reads — the game tape is the narrative half.

The integrity rule this file exists to hold: **an unknown measurement is
recorded as null, never as 0.** A zero token count asserts an observation that
did not happen (`base-persona.md`, Evidence Integrity: "never record a
measurement you did not take"). A runtime that exposes no usage numbers
therefore produces records with duration only, or with nothing but the
delegation's shape — which is honest, and still countable.

Record shape (one JSON object per line):

    {"ts": "<ISO-8601 UTC>", "pipeline": str, "phase": str,
     "unit": str|null, "agent": str|null, "model": str|null,
     "event": "delegation"|"gate"|"phase"|"note",
     "duration_s": float|null, "tokens_in": int|null, "tokens_out": int|null,
     "tokens_total": int|null, "rounds": int|null,
     "status": "COMPLETE"|"PARTIAL"|"BLOCKED"|"PASS"|"FAIL"|"ERROR"|null,
     "note": str|null}

Usage:
    python record_run.py --log <path> --pipeline <name> --phase <name> \
        --event <delegation|gate|phase|note> \
        [--unit "<title>"] [--agent <name>] [--model <tier>] \
        [--duration-s <float>] [--tokens-in <int>] [--tokens-out <int>] \
        [--tokens-total <int>] [--rounds <int>] [--status <STATUS>] \
        [--note "<text>"] [--from-json <file>]
    python record_run.py --self-test

Pure standard library.
"""
import argparse
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

EVENTS = ("delegation", "gate", "phase", "note")
STATUSES = ("COMPLETE", "PARTIAL", "BLOCKED", "PASS", "FAIL", "ERROR")

# --from-json key aliases, searched at the payload's top level and then inside
# a nested "usage" object. Deliberately conservative: only names that mean
# exactly the field they map to. Cache-token fields (cache_read_input_tokens,
# cache_creation_input_tokens) are NOT folded into tokens_in — whether they
# count as input is a judgment this tool has no standing to make, so they stay
# unmapped rather than silently inflating a measurement.
TOKENS_IN_KEYS = ("tokens_in", "input_tokens", "prompt_tokens", "inputTokens")
TOKENS_OUT_KEYS = ("tokens_out", "output_tokens", "completion_tokens",
                   "outputTokens")
TOKENS_TOTAL_KEYS = ("tokens_total", "total_tokens", "subagent_tokens",
                     "totalTokens")
DURATION_S_KEYS = ("duration_s", "duration_seconds", "durationSeconds")
DURATION_MS_KEYS = ("duration_ms", "durationMs", "elapsed_ms",
                    "total_duration_ms")
AGENT_KEYS = ("agent", "agent_name", "subagent_type", "subagentType")
MODEL_KEYS = ("model", "model_id", "modelId")
UNIT_KEYS = ("unit", "milestone")
ROUNDS_KEYS = ("rounds",)
STATUS_KEYS = ("status",)


class RecordError(Exception):
    """Structural/usage failure — maps to exit 2."""


def lookup(payload, keys):
    """First non-null value among `keys`, top level then a nested `usage`."""
    for scope in (payload, payload.get("usage")):
        if not isinstance(scope, dict):
            continue
        for key in keys:
            if key in scope and scope[key] is not None:
                return scope[key]
    return None


def as_int(value):
    """Coerce to int, or None when the value is not an honest integer.

    Booleans are rejected outright: True would coerce to 1, manufacturing a
    token count out of a flag.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == int(value) else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def as_float(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def as_str(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        return value.strip() or None
    return None


def load_payload(path):
    """Read a runtime completion payload. Anything unreadable is exit 2."""
    p = Path(path)
    if not p.is_file():
        raise RecordError(f"--from-json file not found: {path}")
    try:
        text = p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise RecordError(f"--from-json file could not be read: {exc}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RecordError(f"--from-json file is not valid JSON: {exc}")
    if not isinstance(payload, dict):
        raise RecordError("--from-json payload is not a JSON object")
    return payload


def map_payload(payload):
    """Map a runtime completion payload onto record fields. Unmapped -> None.

    Nothing here infers: a field that is absent, un-coercible, or carries a
    value outside its allowed set stays None, which the record renders as a
    null — the recorded shape of "not measured".
    """
    mapped = {
        "unit": as_str(lookup(payload, UNIT_KEYS)),
        "agent": as_str(lookup(payload, AGENT_KEYS)),
        "model": as_str(lookup(payload, MODEL_KEYS)),
        "tokens_in": as_int(lookup(payload, TOKENS_IN_KEYS)),
        "tokens_out": as_int(lookup(payload, TOKENS_OUT_KEYS)),
        "tokens_total": as_int(lookup(payload, TOKENS_TOTAL_KEYS)),
        "rounds": as_int(lookup(payload, ROUNDS_KEYS)),
        "duration_s": as_float(lookup(payload, DURATION_S_KEYS)),
        "status": None,
    }
    if mapped["duration_s"] is None:
        ms = as_float(lookup(payload, DURATION_MS_KEYS))
        if ms is not None:
            mapped["duration_s"] = round(ms / 1000.0, 3)
    status = as_str(lookup(payload, STATUS_KEYS))
    if status and status.upper() in STATUSES:
        mapped["status"] = status.upper()
    return mapped


def build_record(fields):
    """Assemble the record, deriving tokens_total only from two known halves."""
    tokens_in = fields.get("tokens_in")
    tokens_out = fields.get("tokens_out")
    tokens_total = fields.get("tokens_total")
    if tokens_total is None and tokens_in is not None and tokens_out is not None:
        tokens_total = tokens_in + tokens_out
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pipeline": fields["pipeline"],
        "phase": fields["phase"],
        "unit": fields.get("unit"),
        "agent": fields.get("agent"),
        "model": fields.get("model"),
        "event": fields["event"],
        "duration_s": fields.get("duration_s"),
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_total": tokens_total,
        "rounds": fields.get("rounds"),
        "status": fields.get("status"),
        "note": fields.get("note"),
    }


def append_record(log_path, record):
    """Append one JSON line, creating parent directories. Failure is exit 2.

    Unlike the gate ledger's best-effort write, this IS the artifact: a record
    that silently failed to land is a measurement that never happened.
    """
    try:
        p = Path(log_path)
        if str(p.parent):
            p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise RecordError(f"could not append to run log {log_path}: {exc}")


def main(argv):
    parser = argparse.ArgumentParser(prog="record_run.py", add_help=True)
    parser.add_argument("--log")
    parser.add_argument("--pipeline")
    parser.add_argument("--phase")
    parser.add_argument("--event")
    parser.add_argument("--unit")
    parser.add_argument("--agent")
    parser.add_argument("--model")
    parser.add_argument("--duration-s", dest="duration_s")
    parser.add_argument("--tokens-in", dest="tokens_in")
    parser.add_argument("--tokens-out", dest="tokens_out")
    parser.add_argument("--tokens-total", dest="tokens_total")
    parser.add_argument("--rounds")
    parser.add_argument("--status")
    parser.add_argument("--note")
    parser.add_argument("--from-json", dest="from_json",
                        help="a runtime completion payload; explicit flags win")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    def fail(message):
        print(json.dumps({"recorded": False, "error": message}))
        return 2

    for name, value in (("--log", args.log), ("--pipeline", args.pipeline),
                        ("--phase", args.phase), ("--event", args.event)):
        if not value:
            return fail(f"missing required argument: {name}")
    if args.event not in EVENTS:
        return fail(f"--event must be one of {'|'.join(EVENTS)}")
    if args.status is not None and args.status not in STATUSES:
        return fail(f"--status must be one of {'|'.join(STATUSES)}")

    fields = {"unit": None, "agent": None, "model": None, "tokens_in": None,
              "tokens_out": None, "tokens_total": None, "rounds": None,
              "duration_s": None, "status": None}
    if args.from_json:
        try:
            fields.update(map_payload(load_payload(args.from_json)))
        except RecordError as exc:
            return fail(str(exc))

    # Explicit flags override the payload: the operator saw the number, the
    # mapper only guessed at a field name.
    numeric = (("duration_s", as_float), ("tokens_in", as_int),
               ("tokens_out", as_int), ("tokens_total", as_int),
               ("rounds", as_int))
    for name, coerce in numeric:
        raw = getattr(args, name)
        if raw is not None:
            coerced = coerce(raw)
            if coerced is None:
                return fail(f"--{name.replace('_', '-')} is not a number: {raw}")
            fields[name] = coerced
    for name in ("unit", "agent", "model", "status"):
        if getattr(args, name) is not None:
            fields[name] = getattr(args, name)

    fields["pipeline"] = args.pipeline
    fields["phase"] = args.phase
    fields["event"] = args.event
    fields["note"] = args.note

    record = build_record(fields)
    try:
        append_record(args.log, record)
    except RecordError as exc:
        return fail(str(exc))

    # stdout stays ASCII-escaped (still valid JSON) — a cp1252 console cannot
    # encode a non-ASCII unit title, and the tool must not fail on its own
    # success report. The FILE write above is real utf-8.
    print(json.dumps({"recorded": True, "log": args.log, "record": record},
                     indent=2))
    return 0


def run_self_test():
    import shutil

    class RecordRunTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.log = self.dir / "implementation" / "run-log.jsonl"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _lines(self):
            return [json.loads(l) for l in
                    self.log.read_text(encoding="utf-8").splitlines() if l.strip()]

        def _base(self, *extra):
            return ["--log", str(self.log), "--pipeline", "bgpdd-build",
                    "--phase", "Phase 1", "--event", "delegation"] + list(extra)

        def test_append_creates_parents_and_one_line(self):
            self.assertFalse(self.log.parent.exists())
            self.assertEqual(main(self._base("--agent", "mason")), 0)
            self.assertTrue(self.log.is_file())
            records = self._lines()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["agent"], "mason")
            self.assertEqual(records[0]["pipeline"], "bgpdd-build")
            self.assertEqual(records[0]["event"], "delegation")

        def test_unknown_tokens_are_null_never_zero(self):
            """The integrity property: absence records as null, not as 0."""
            self.assertEqual(main(self._base()), 0)
            rec = self._lines()[0]
            for key in ("tokens_in", "tokens_out", "tokens_total",
                        "duration_s", "rounds", "status", "unit", "note"):
                self.assertIsNone(rec[key], key)

        def test_explicit_zero_is_preserved_as_zero(self):
            """A measured 0 is a measurement; only ABSENCE becomes null."""
            self.assertEqual(main(self._base("--tokens-out", "0")), 0)
            self.assertEqual(self._lines()[0]["tokens_out"], 0)

        def test_tokens_total_derived_only_from_two_known_halves(self):
            self.assertEqual(
                main(self._base("--tokens-in", "100", "--tokens-out", "25")), 0)
            self.assertEqual(self._lines()[0]["tokens_total"], 125)
            self.assertEqual(main(self._base("--tokens-in", "100")), 0)
            self.assertIsNone(self._lines()[1]["tokens_total"])

        def test_multiple_appends_accumulate(self):
            for phase in ("Phase 1", "Phase 2", "Phase 3"):
                self.assertEqual(
                    main(["--log", str(self.log), "--pipeline", "bgpdd-build",
                          "--phase", phase, "--event", "delegation"]), 0)
            self.assertEqual([r["phase"] for r in self._lines()],
                             ["Phase 1", "Phase 2", "Phase 3"])

        def test_from_json_maps_common_field_names(self):
            payload = self.dir / "completion.json"
            payload.write_text(json.dumps({
                "duration_ms": 4200, "subagent_tokens": 51234,
                "model": "sonnet", "agent": "quinn", "status": "COMPLETE",
            }), encoding="utf-8")
            self.assertEqual(
                main(["--log", str(self.log), "--pipeline", "bgpdd-build",
                      "--phase", "Phase 2", "--event", "delegation",
                      "--from-json", str(payload)]), 0)
            rec = self._lines()[0]
            self.assertEqual(rec["duration_s"], 4.2)
            self.assertEqual(rec["tokens_total"], 51234)
            self.assertEqual(rec["model"], "sonnet")
            self.assertEqual(rec["agent"], "quinn")
            self.assertEqual(rec["status"], "COMPLETE")
            self.assertIsNone(rec["tokens_in"])

        def test_from_json_reads_nested_usage(self):
            payload = self.dir / "completion.json"
            payload.write_text(json.dumps({
                "usage": {"input_tokens": 900, "output_tokens": 100,
                          "cache_read_input_tokens": 40000},
            }), encoding="utf-8")
            self.assertEqual(
                main(["--log", str(self.log), "--pipeline", "bgpdd-build",
                      "--phase", "Phase 2", "--event", "delegation",
                      "--from-json", str(payload)]), 0)
            rec = self._lines()[0]
            self.assertEqual((rec["tokens_in"], rec["tokens_out"]), (900, 100))
            # cache tokens are deliberately unmapped, not folded into tokens_in
            self.assertEqual(rec["tokens_total"], 1000)

        def test_from_json_unmapped_and_unusable_fields_stay_null(self):
            payload = self.dir / "completion.json"
            payload.write_text(json.dumps({
                "cost_usd": 0.42, "is_error": True, "status": "weird",
                "input_tokens": "not-a-number",
            }), encoding="utf-8")
            self.assertEqual(
                main(["--log", str(self.log), "--pipeline", "bgpdd-build",
                      "--phase", "Phase 2", "--event", "note",
                      "--from-json", str(payload)]), 0)
            rec = self._lines()[0]
            self.assertIsNone(rec["tokens_in"])
            self.assertIsNone(rec["status"])

        def test_explicit_flag_overrides_from_json(self):
            payload = self.dir / "completion.json"
            payload.write_text(json.dumps({"model": "haiku", "duration_ms": 1000}),
                               encoding="utf-8")
            self.assertEqual(
                main(["--log", str(self.log), "--pipeline", "bgpdd-build",
                      "--phase", "Phase 1", "--event", "delegation",
                      "--from-json", str(payload), "--model", "opus"]), 0)
            rec = self._lines()[0]
            self.assertEqual(rec["model"], "opus")
            self.assertEqual(rec["duration_s"], 1.0)

        def test_bad_json_payload_is_exit_2_and_writes_nothing(self):
            payload = self.dir / "completion.json"
            payload.write_text("{not json", encoding="utf-8")
            self.assertEqual(main(self._base("--from-json", str(payload))), 2)
            self.assertFalse(self.log.exists())

        def test_missing_payload_file_is_exit_2(self):
            self.assertEqual(
                main(self._base("--from-json", str(self.dir / "nope.json"))), 2)

        def test_missing_required_flag_is_exit_2(self):
            self.assertEqual(main(["--log", str(self.log),
                                   "--pipeline", "bgpdd-build",
                                   "--event", "delegation"]), 2)
            self.assertEqual(main(["--pipeline", "bgpdd-build",
                                   "--phase", "Phase 1",
                                   "--event", "delegation"]), 2)
            self.assertFalse(self.log.exists())

        def test_bad_event_and_status_are_exit_2(self):
            self.assertEqual(main(["--log", str(self.log),
                                   "--pipeline", "bgpdd-build",
                                   "--phase", "Phase 1",
                                   "--event", "handoff"]), 2)
            self.assertEqual(main(self._base("--status", "OK")), 2)
            self.assertEqual(main(self._base("--tokens-in", "lots")), 2)
            self.assertFalse(self.log.exists())

        def test_utf8_note_and_unit_round_trip(self):
            self.assertEqual(main(self._base(
                "--unit", "M3: Café résumé — ünïcode",
                "--note", "builder ↔ Quinn round 2")), 0)
            raw = self.log.read_bytes().decode("utf-8")
            self.assertIn("Café résumé", raw)
            rec = self._lines()[0]
            self.assertEqual(rec["unit"], "M3: Café résumé — ünïcode")
            self.assertEqual(rec["note"], "builder ↔ Quinn round 2")

        def test_unwritable_log_path_is_exit_2(self):
            blocker = self.dir / "blocker"
            blocker.write_text("not a directory", encoding="utf-8")
            self.assertEqual(
                main(["--log", str(blocker / "run-log.jsonl"),
                      "--pipeline", "bgpdd-build", "--phase", "Phase 1",
                      "--event", "delegation"]), 2)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RecordRunTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
