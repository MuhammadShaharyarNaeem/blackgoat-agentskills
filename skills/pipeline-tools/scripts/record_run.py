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

`--model` is MANDATORY on `--event delegation`. Measured finding: model
choice left to prose decays -- 17 dispatches in one audited wave silently
inherited the most expensive tier, and nothing in the run log could tell that
apart from a deliberate choice, because the field was simply null. A null
there is not "not measured": the tier is always known at dispatch time, so
its absence records a decision nobody made (`CLAUDE.md` convention #9 -- a
restraint rule the Orchestrator skips at the moment it wants to proceed
becomes a mechanical gate, not louder prose). `--from-json` may supply it.
Every other event is unchanged: a gate, phase or note record has no model.

An UNRESOLVABLE `--model` is exit 2 (`model_unknown`), not a null tier. The
tier-inversion check below reads the tier out of the model string, and a value
it cannot resolve -- `gpt-4o`, a name that mentions two tiers
(`sonnet-or-opus`), a typo -- used to record cleanly with `tier: null` and
silently DELETE the check for that delegation. A mistyped flag must not be
able to disable a gate. Resolvable means: the value contains exactly one of
`haiku`/`sonnet`/`opus`/`fable`, case-insensitively, so `opus`, `Opus`,
`opus-4.1`, `claude-opus-5` and `claude-fable-5-1` all resolve and `gpt-4o`
does not. Only `--event delegation` is checked -- a gate, phase or note
record has no model.

ONE DELEGATION, ONE RECORD (`duplicate_delegation`)
---------------------------------------------------
Orchestrator Contract §4: "A second completion notification for an agent that
has already returned is a re-wake -- a background task it started finishing
after its handoff -- not a new delegation. Do not append a second record, and
do not take the later notification's cumulative duration as the delegation's
cost: the first completion is the measurement."

That restraint is asked for while a notification is sitting in the transcript
with a bigger, more recent-looking number in it, so convention #9 makes it a
refusal: an `--event delegation` record whose
(`--pipeline`, `--unit`, `--agent`, `--rounds`) tuple already appears in the
log is `duplicate_delegation`, exit 1, and nothing is written. The FIRST
completion stays the measurement.

`--rounds N` is what distinguishes a legitimate second delegation from a
re-wake: a fix round 2 of the same agent on the same unit records
`--rounds 2` and is a different tuple. There is deliberately no `--rewake`
flag -- the lesson is that a re-wake is not recorded at all, so a flag saying
"record this re-wake anyway" would be the thing being prevented. `--phase` is
NOT part of the tuple: a re-wake often arrives while the Orchestrator has
moved on, and letting a re-labelled phase make it a fresh record would leave
the double-count this refuses. The check is skipped when `--agent` is absent
(nothing identifies the delegation to be a duplicate OF) and for every
non-delegation event.

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

# --- the tier-inversion check (convention #9) ------------------------------
# A verifier run BELOW the producer it judges is a review that cannot see what
# the producer saw. The rule was prose ("a verifier never runs below the
# producer it judges", agent-audit heuristic 13) and the run log is where the
# violation is already visible after the fact -- so the log is where it
# becomes a refusal instead of a finding.
# `fable` sits ABOVE `opus`: Claude Fable 5.1 is the current top tier, and its
# ids look like `claude-fable-5-1`. Ordering it correctly is what makes the two
# real pairings resolvable -- a fable verifier over an opus producer is not an
# inversion, and an opus verifier over a fable producer is one. Left out of the
# map, every fable delegation was `model_unknown` and unrecordable.
TIER_ORDER = {"haiku": 1, "sonnet": 2, "opus": 3, "fable": 4}
VERIFIER_AGENTS = ("quinn", "luna", "vera", "cipher")
# `dep` produces the deployment artifacts Vera and Cipher judge at shipping,
# so a verifier running below Dep is the same inversion as one running below
# Mason. Its absence from this tuple made that one pairing unmeasurable.
PRODUCER_AGENTS = ("mason", "nova", "max", "dep")

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


def normalize_agent(name):
    """An agent name as the roster spells it, or None."""
    if not isinstance(name, str):
        return None
    return name.strip().lower() or None


def model_tier(model):
    """The tier rank of a model string, or None when it names no known tier.

    Matches on the tier NAME appearing in the value, so both `opus` and
    `claude-opus-4-20250514` resolve. A value naming two tiers, or none,
    resolves to None -- an unknown tier is never compared, because refusing on
    a guess is worse than not refusing (Evidence Integrity: an unknown
    measurement is not a measurement).
    """
    if not isinstance(model, str):
        return None
    low = model.strip().lower()
    hits = [tier for tier in TIER_ORDER if tier in low]
    if len(hits) != 1:
        return None
    return hits[0]


def read_log(log_path):
    """Every parseable JSON-object line of the run log, in file order."""
    p = Path(log_path)
    if not p.is_file():
        return []
    records = []
    for line in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            records.append(rec)
    return records


def latest_producer(log_path, unit):
    """The most recent producer delegation in this unit whose tier is known.

    Scoped to `unit` EXACTLY (an unscoped record matches only an unscoped
    invocation): the comparison is "this verifier against the producer whose
    work it is judging", and two different milestones' tiers are unrelated.
    """
    latest = None
    for rec in read_log(log_path):
        if rec.get("event") != "delegation":
            continue
        if normalize_agent(rec.get("agent")) not in PRODUCER_AGENTS:
            continue
        if rec.get("unit") != unit:
            continue
        if model_tier(rec.get("model")) is None:
            continue
        latest = rec
    return latest


def delegation_key(rec):
    """The tuple that identifies ONE delegation: pipeline, unit, agent, round.

    `--phase` is deliberately absent -- see ONE DELEGATION, ONE RECORD above.
    `rounds` is coerced the same way on both sides so a record written with
    `--rounds 2` and one read back as the string "2" are the same round.
    """
    return (rec.get("pipeline"), rec.get("unit"),
            normalize_agent(rec.get("agent")), as_int(rec.get("rounds")))


def check_duplicate_delegation(log_path, fields):
    """(problem_code, detail) when this delegation is already in the log.

    (None, None) when there is nothing to refuse: a non-delegation, a record
    with no `--agent` (nothing identifies it), or a tuple the log has not
    seen. The re-wake this refuses is a SECOND completion notification for an
    agent that already returned; the first completion is the measurement.
    """
    if fields.get("event") != "delegation":
        return None, None
    if normalize_agent(fields.get("agent")) is None:
        return None, None
    key = delegation_key(fields)
    for rec in read_log(log_path):
        if rec.get("event") != "delegation":
            continue
        if delegation_key(rec) != key:
            continue
        return "duplicate_delegation", (
            "{0} already has a delegation record in this run log for unit "
            "{1!r} at round {2} (recorded {3}). A second completion "
            "notification for an agent that has already returned is a "
            "RE-WAKE -- a background task finishing after its handoff -- not "
            "a new delegation, and its cumulative duration is not the "
            "delegation's cost: the first completion is the measurement "
            "(Orchestrator Contract section 4). If this really is a new "
            "round, record it with --rounds N; there is no flag that records "
            "a re-wake.".format(
                normalize_agent(fields.get("agent")), fields.get("unit"),
                as_int(fields.get("rounds")), rec.get("ts")))
    return None, None


def check_tier_inversion(log_path, fields):
    """(problem_code, detail) when this verifier runs below its producer.

    (None, None) when there is nothing to refuse: a non-delegation, a
    non-verifier agent, an unknown tier on either side, or no producer record
    in this unit yet (the verifier may legitimately run first -- Quinn's
    pre-fix RED capture in the bugfix lane is exactly that).
    """
    if fields.get("event") != "delegation":
        return None, None
    agent = normalize_agent(fields.get("agent"))
    if agent not in VERIFIER_AGENTS:
        return None, None
    verifier_tier = model_tier(fields.get("model"))
    if verifier_tier is None:
        return None, None
    producer = latest_producer(log_path, fields.get("unit"))
    if producer is None:
        return None, None
    producer_tier = model_tier(producer.get("model"))
    if TIER_ORDER[verifier_tier] >= TIER_ORDER[producer_tier]:
        return None, None
    return "verifier_below_producer", (
        "{0} is a verifier running on {1}, below {2}, which produced this "
        "unit's work on {3} ({4} < {5}). A review that runs below what it "
        "judges cannot see what the producer saw. Re-run the verifier at "
        "{3} or above, or record the deliberate exception with "
        "--allow-tier-inversion \"<reason>\"".format(
            agent, verifier_tier, normalize_agent(producer.get("agent")),
            producer_tier, TIER_ORDER[verifier_tier],
            TIER_ORDER[producer_tier]))


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
    parser.add_argument("--model",
                        help="the tier the delegation ran at; REQUIRED for "
                             "--event delegation (may come via --from-json)")
    parser.add_argument("--duration-s", dest="duration_s")
    parser.add_argument("--tokens-in", dest="tokens_in")
    parser.add_argument("--tokens-out", dest="tokens_out")
    parser.add_argument("--tokens-total", dest="tokens_total")
    parser.add_argument("--rounds")
    parser.add_argument("--status")
    parser.add_argument("--note")
    parser.add_argument("--from-json", dest="from_json",
                        help="a runtime completion payload; explicit flags win")
    parser.add_argument("--allow-tier-inversion", dest="allow_tier_inversion",
                        help="a written reason for running a verifier below "
                             "the producer it judges; recorded on the record "
                             "as tier_inversion_reason")
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

    # Checked AFTER --from-json is merged: the payload is a legitimate source
    # for the tier. Only `delegation` is gated -- a gate/phase/note record has
    # no model to report, and demanding one there would invite a fabrication.
    if fields["event"] == "delegation" and not fields.get("model"):
        return fail("--model is required for --event delegation: record the "
                    "tier the delegation actually ran at (supply --model, or "
                    "a --from-json payload carrying it)")

    # ...and it must NAME a tier. An unresolvable string recorded cleanly with
    # tier: null and silently deleted the inversion check for that record.
    if fields["event"] == "delegation" and model_tier(fields.get("model")) is None:
        print(json.dumps({
            "recorded": False, "problem": "model_unknown",
            "error": "--model {0!r} resolves to no tier: it must contain "
                     "exactly one of {1} (case-insensitive), e.g. `opus`, "
                     "`claude-opus-5` or `claude-fable-5-1`. An unresolved "
                     "tier is not a "
                     "measured one, and recording it as null would disable "
                     "the verifier-below-producer check for this delegation "
                     "without saying so.".format(
                         fields.get("model"),
                         "/".join(sorted(TIER_ORDER, key=TIER_ORDER.get)))}))
        return 2

    # Duplicate is checked FIRST, and before the write: it decides whether
    # this record should exist at all, where the inversion check below judges
    # the content of a record that should. A re-wake writes nothing.
    duplicate, detail = check_duplicate_delegation(args.log, fields)
    if duplicate:
        print(json.dumps({"recorded": False, "problem": duplicate,
                          "error": detail}))
        return 1

    # Tier inversion is checked BEFORE the write, against the log this record
    # is about to join: a refused delegation records nothing.
    problem, detail = check_tier_inversion(args.log, fields)
    if problem and not args.allow_tier_inversion:
        print(json.dumps({"recorded": False, "problem": problem,
                          "error": detail}))
        return 1
    if problem and not args.allow_tier_inversion.strip():
        print(json.dumps({"recorded": False, "problem": problem,
                          "error": "--allow-tier-inversion requires a "
                                   "non-empty reason: an inversion nobody "
                                   "justified in writing is the one this "
                                   "check exists to stop"}))
        return 2

    record = build_record(fields)
    if problem:
        record["tier_inversion_reason"] = args.allow_tier_inversion.strip()
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
            # --model is mandatory for a delegation record, so it belongs in
            # the shared base: a test about tokens must not fail on the tier.
            return ["--log", str(self.log), "--pipeline", "bgpdd-build",
                    "--phase", "Phase 1", "--event", "delegation",
                    "--model", "sonnet"] + list(extra)

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
                          "--phase", phase, "--event", "delegation",
                          "--model", "sonnet"]), 0)
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
                "model": "haiku",
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
                                   "--event", "delegation",
                                   "--model", "sonnet"]), 2)
            self.assertEqual(main(["--pipeline", "bgpdd-build",
                                   "--phase", "Phase 1",
                                   "--event", "delegation",
                                   "--model", "sonnet"]), 2)
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
                      "--event", "delegation", "--model", "sonnet"]), 2)

        # ---- --model is mandatory for a delegation record ----------------
        def test_delegation_without_model_is_exit_2_and_writes_nothing(self):
            """The measured decay: a null tier is a decision nobody made."""
            self.assertEqual(
                main(["--log", str(self.log), "--pipeline", "bgpdd-build",
                      "--phase", "Phase 1", "--event", "delegation",
                      "--agent", "mason"]), 2)
            self.assertFalse(self.log.exists())

        def test_delegation_with_model_is_exit_0(self):
            self.assertEqual(
                main(["--log", str(self.log), "--pipeline", "bgpdd-build",
                      "--phase", "Phase 1", "--event", "delegation",
                      "--agent", "mason", "--model", "opus"]), 0)
            self.assertEqual(self._lines()[0]["model"], "opus")

        def test_non_delegation_without_model_is_exit_0(self):
            """Only delegations are gated -- a gate/phase/note has no tier."""
            for event in ("gate", "phase", "note"):
                self.assertEqual(
                    main(["--log", str(self.log), "--pipeline", "bgpdd-build",
                          "--phase", "Phase 1", "--event", event]), 0)
            records = self._lines()
            self.assertEqual([r["event"] for r in records],
                             ["gate", "phase", "note"])
            self.assertTrue(all(r["model"] is None for r in records))

        def test_from_json_may_supply_the_model(self):
            payload = self.dir / "completion.json"
            payload.write_text(json.dumps({"model": "haiku"}), encoding="utf-8")
            self.assertEqual(
                main(["--log", str(self.log), "--pipeline", "bgpdd-build",
                      "--phase", "Phase 1", "--event", "delegation",
                      "--from-json", str(payload)]), 0)
            self.assertEqual(self._lines()[0]["model"], "haiku")

        # ---- a verifier never runs below the producer it judges ----------

        def _delegate(self, agent, model, unit="M1", extra=None):
            argv = ["--log", str(self.log), "--pipeline", "bgpdd-build",
                    "--phase", "Phase 1", "--event", "delegation",
                    "--agent", agent, "--model", model, "--unit", unit]
            return main(argv + list(extra or []))

        def test_verifier_below_producer_is_refused_and_writes_nothing(self):
            self.assertEqual(self._delegate("mason", "opus"), 0)
            self.assertEqual(self._delegate("luna", "sonnet"), 1)
            self.assertEqual([r["agent"] for r in self._lines()], ["mason"])

        def test_verifier_at_or_above_the_producer_is_fine(self):
            self.assertEqual(self._delegate("mason", "sonnet"), 0)
            self.assertEqual(self._delegate("quinn", "sonnet"), 0)
            self.assertEqual(self._delegate("luna", "opus"), 0)
            self.assertEqual(len(self._lines()), 3)

        def test_allow_tier_inversion_records_the_reason(self):
            self.assertEqual(self._delegate("mason", "opus"), 0)
            self.assertEqual(self._delegate(
                "vera", "haiku",
                extra=["--allow-tier-inversion",
                       "checklist re-read only; no judgement call"]), 0)
            rec = self._lines()[-1]
            self.assertEqual(rec["agent"], "vera")
            self.assertEqual(rec["tier_inversion_reason"],
                             "checklist re-read only; no judgement call")

        def test_allow_tier_inversion_with_an_empty_reason_is_exit_2(self):
            self.assertEqual(self._delegate("mason", "opus"), 0)
            self.assertEqual(self._delegate(
                "cipher", "haiku", extra=["--allow-tier-inversion", "   "]), 2)
            self.assertEqual(len(self._lines()), 1)

        def test_a_clean_record_carries_no_inversion_key(self):
            self.assertEqual(self._delegate("mason", "sonnet"), 0)
            self.assertEqual(self._delegate(
                "luna", "opus",
                extra=["--allow-tier-inversion", "not needed"]), 0)
            self.assertNotIn("tier_inversion_reason", self._lines()[-1])

        def test_inversion_is_scoped_to_the_unit(self):
            """M2's cheap verifier is not judged against M1's opus builder."""
            self.assertEqual(self._delegate("mason", "opus", unit="M1"), 0)
            self.assertEqual(self._delegate("quinn", "haiku", unit="M2"), 0)
            self.assertEqual(self._delegate("quinn", "haiku", unit="M1"), 1)

        def test_verifier_running_first_is_allowed(self):
            """The bugfix lane's pre-fix RED capture has no producer yet."""
            self.assertEqual(self._delegate("quinn", "haiku"), 0)
            self.assertEqual(len(self._lines()), 1)

        def test_latest_producer_wins_not_the_first(self):
            self.assertEqual(self._delegate("mason", "opus"), 0)
            self.assertEqual(self._delegate("nova", "haiku"), 0)
            self.assertEqual(self._delegate("luna", "sonnet"), 0)

        # ---- model_unknown (audit3 F8) --------------------------------

        def test_an_unresolvable_model_is_exit_2_and_records_nothing(self):
            """A typo used to record tier: null and delete the check."""
            for model in ("gpt-4o", "o3-mini", "sonnet-or-opus",
                          "some-unnamed-model", "  "):
                self.assertEqual(self._delegate("mason", model), 2, model)
            self.assertFalse(self.log.exists(),
                             "a refused delegation wrote a record")

        def test_the_model_unknown_error_names_the_problem_and_the_tiers(self):
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["--log", str(self.log), "--pipeline",
                             "bgpdd-build", "--phase", "Phase 1", "--event",
                             "delegation", "--agent", "mason", "--model",
                             "gpt-4o", "--unit", "M1"])
            self.assertEqual(code, 2)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["problem"], "model_unknown")
            self.assertIs(data["recorded"], False)
            for tier in ("haiku", "sonnet", "opus"):
                self.assertIn(tier, data["error"])

        def test_a_typo_can_no_longer_disable_the_inversion_check(self):
            """audit3 F8, end to end: opus producer, then a mistyped verifier.

            The later Luna calls carry --rounds so each is its own delegation
            rather than a duplicate of the first (see ONE DELEGATION, ONE
            RECORD); the point under test is the tier, not the tuple.
            """
            self.assertEqual(self._delegate("mason", "claude-opus-4-1"), 0)
            self.assertEqual(self._delegate("luna", "opus-4.1"), 0)  # resolves
            self.assertEqual(self._delegate("luna", "gpt-4o",
                                            extra=["--rounds", "2"]), 2)
            self.assertEqual(self._delegate("luna", "haiku",
                                            extra=["--rounds", "2"]), 1)

        def test_a_gate_or_note_record_needs_no_resolvable_model(self):
            self.assertEqual(main(["--log", str(self.log), "--pipeline",
                                   "bgpdd-build", "--phase", "Phase 1",
                                   "--event", "note", "--note", "x"]), 0)

        def test_dep_is_a_producer(self):
            """audit3 Metric 14: a verifier below Dep is an inversion too."""
            self.assertIn("dep", PRODUCER_AGENTS)
            self.assertEqual(self._delegate("dep", "opus"), 0)
            self.assertEqual(self._delegate("vera", "haiku"), 1)
            self.assertEqual(self._delegate("cipher", "opus"), 0)

        def test_full_model_ids_resolve_to_their_tier(self):
            self.assertEqual(self._delegate("mason", "claude-opus-4-1"), 0)
            self.assertEqual(self._delegate("luna", "claude-haiku-4-5"), 1)

        def test_non_verifier_and_non_delegation_records_are_never_gated(self):
            self.assertEqual(self._delegate("mason", "opus"), 0)
            self.assertEqual(self._delegate("dep", "haiku"), 0)
            self.assertEqual(main(["--log", str(self.log),
                                   "--pipeline", "bgpdd-build",
                                   "--phase", "Phase 1", "--event", "gate",
                                   "--agent", "luna", "--unit", "M1"]), 0)

        def test_model_tier_helper(self):
            self.assertEqual(model_tier("Opus"), "opus")
            self.assertEqual(model_tier("claude-sonnet-4-5"), "sonnet")
            self.assertIsNone(model_tier("sonnet-or-opus"))
            self.assertIsNone(model_tier(None))
            self.assertIsNone(model_tier("gpt-4"))

        # ---- the fable family is the current top tier --------------------

        def test_current_model_ids_all_normalise(self):
            for model, tier in (("claude-fable-5-1", "fable"),
                                ("claude-opus-5", "opus"),
                                ("claude-sonnet-5", "sonnet"),
                                ("claude-haiku-4-5-20251001", "haiku"),
                                ("Fable", "fable")):
                self.assertEqual(model_tier(model), tier, model)

        def test_fable_ranks_above_opus(self):
            self.assertGreater(TIER_ORDER["fable"], TIER_ORDER["opus"])

        def test_a_fable_verifier_over_an_opus_producer_is_not_an_inversion(self):
            self.assertEqual(self._delegate("mason", "claude-opus-5"), 0)
            self.assertEqual(self._delegate("luna", "claude-fable-5-1"), 0)
            self.assertEqual(len(self._lines()), 2)

        def test_an_opus_verifier_over_a_fable_producer_is_an_inversion(self):
            self.assertEqual(self._delegate("mason", "claude-fable-5-1"), 0)
            self.assertEqual(self._delegate("luna", "claude-opus-5"), 1)
            self.assertEqual([r["agent"] for r in self._lines()], ["mason"])

        def test_a_fable_delegation_records_cleanly(self):
            self.assertEqual(self._delegate("mason", "claude-fable-5-1"), 0)
            self.assertEqual(self._lines()[0]["model"], "claude-fable-5-1")

        # ---- one delegation, one record ----------------------------------

        def test_a_re_wake_is_refused_and_writes_nothing(self):
            """The second completion notification for an agent that already
            returned. The FIRST completion is the measurement."""
            self.assertEqual(self._delegate("mason", "opus",
                                            extra=["--duration-s", "42"]), 0)
            self.assertEqual(self._delegate("mason", "opus",
                                            extra=["--duration-s", "310"]), 1)
            records = self._lines()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["duration_s"], 42.0)

        def test_the_duplicate_error_names_the_problem_and_the_way_out(self):
            import contextlib
            import io
            self.assertEqual(self._delegate("mason", "opus"), 0)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = self._delegate("mason", "opus")
            self.assertEqual(code, 1)
            data = json.loads(buf.getvalue())
            self.assertEqual(data["problem"], "duplicate_delegation")
            self.assertIs(data["recorded"], False)
            self.assertIn("--rounds", data["error"])
            self.assertIn("re-wake", data["error"].lower())

        def test_a_genuine_second_round_is_a_different_record(self):
            self.assertEqual(self._delegate("mason", "opus",
                                            extra=["--rounds", "1"]), 0)
            self.assertEqual(self._delegate("mason", "opus",
                                            extra=["--rounds", "1"]), 1)
            self.assertEqual(self._delegate("mason", "opus",
                                            extra=["--rounds", "2"]), 0)
            self.assertEqual([r["rounds"] for r in self._lines()], [1, 2])

        def test_a_different_unit_or_pipeline_is_not_a_duplicate(self):
            self.assertEqual(self._delegate("mason", "opus", unit="M1"), 0)
            self.assertEqual(self._delegate("mason", "opus", unit="M2"), 0)
            self.assertEqual(
                main(["--log", str(self.log), "--pipeline", "bgpdd-bugfix",
                      "--phase", "Phase 1", "--event", "delegation",
                      "--agent", "mason", "--model", "opus",
                      "--unit", "M1"]), 0)
            self.assertEqual(len(self._lines()), 3)

        def test_a_relabelled_phase_does_not_make_a_re_wake_a_new_record(self):
            """--phase is deliberately outside the tuple: a re-wake often
            lands after the Orchestrator has moved on."""
            base = ["--log", str(self.log), "--pipeline", "bgpdd-build",
                    "--event", "delegation", "--agent", "quinn",
                    "--model", "sonnet", "--unit", "M1"]
            self.assertEqual(main(base + ["--phase", "Phase 4"]), 0)
            self.assertEqual(main(base + ["--phase", "Phase 5"]), 1)
            self.assertEqual(len(self._lines()), 1)

        def test_a_delegation_with_no_agent_is_not_duplicate_gated(self):
            """Nothing identifies it to be a duplicate OF."""
            for _ in range(3):
                self.assertEqual(main(self._base()), 0)
            self.assertEqual(len(self._lines()), 3)

        def test_non_delegation_events_are_never_duplicate_gated(self):
            for _ in range(2):
                for event in ("gate", "phase", "note"):
                    self.assertEqual(
                        main(["--log", str(self.log), "--pipeline",
                              "bgpdd-build", "--phase", "Phase 1",
                              "--event", event, "--agent", "luna"]), 0)
            self.assertEqual(len(self._lines()), 6)

        def test_duplicate_is_refused_before_the_inversion_check(self):
            """A record that is BOTH a duplicate and an inversion is refused
            as the duplicate: the tuple decides whether the record should
            EXIST at all, the tier only judges one that should."""
            import contextlib
            import io
            self.assertEqual(self._delegate("mason", "sonnet",
                                            extra=["--rounds", "1"]), 0)
            self.assertEqual(self._delegate("luna", "sonnet",
                                            extra=["--rounds", "1"]), 0)
            # The producer is re-run at a higher tier, so re-sending Luna's
            # first completion is now an inversion too.
            self.assertEqual(self._delegate("mason", "opus",
                                            extra=["--rounds", "2"]), 0)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = self._delegate("luna", "sonnet",
                                      extra=["--rounds", "1"])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(buf.getvalue())["problem"],
                             "duplicate_delegation")
            self.assertEqual([r["agent"] for r in self._lines()],
                             ["mason", "luna", "mason"])

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(RecordRunTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
