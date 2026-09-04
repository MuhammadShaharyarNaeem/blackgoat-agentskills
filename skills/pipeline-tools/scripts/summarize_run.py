#!/usr/bin/env python3
"""Read the run log (and optionally the gate ledger) and summarize the run.

The reader half of `record_run.py`. It answers the two questions the game tape
kept answering in prose, and answering wrong: **what did this cost**, and
**which gates actually caught something**.

The second is the mechanical form of the author's fired-vs-rubber-stamped
metric. A gate is:

- **fired**       — it recorded a `FAIL` at least once. It caught something.
- **rubber_stamped** — every verdict it ever recorded is `PASS`. It has never
  yet been the thing that stopped a bad artifact.
- **inconclusive** — it recorded an `ERROR` (a structural/usage failure) but no
  `FAIL`. Neither claim can be made about it, and it is reported separately
  rather than folded into either bucket.

`rubber_stamped` is a description, not a verdict: a gate can be load-bearing
and never fire. It is the input to the Incident Test, not its answer.

Usage:
    python summarize_run.py --run-log <path> [--ledger <path>] \
        [--unit "<title>"] [--markdown]
    python summarize_run.py --self-test

Exit 0 on a summary; 2 on unreadable input. A missing ledger is NOT an error:
the gates section becomes null and a warning says so. Pure standard library.
"""
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

UNSCOPED = "(unscoped)"


class SummaryError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_jsonl(path, label):
    """Return (records, malformed_count). A malformed LINE is tolerated.

    A file that cannot be opened is exit 2; a single unparseable line inside an
    append-only telemetry log is not, because a truncated last line (a run
    killed mid-write) must not blind the reader to everything before it.
    """
    p = Path(path)
    if not p.is_file():
        raise SummaryError(f"{label} not found or not readable: {path}")
    try:
        text = p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise SummaryError(f"{label} could not be read: {exc}")
    records, malformed = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            malformed += 1
    return records, malformed


def as_number(value):
    """A usable number, or None. Booleans and junk are None, never 0."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def record_tokens(record):
    """The record's token total: as recorded, else in+out, else None."""
    total = as_number(record.get("tokens_total"))
    if total is not None:
        return total
    tin = as_number(record.get("tokens_in"))
    tout = as_number(record.get("tokens_out"))
    if tin is not None and tout is not None:
        return tin + tout
    return None


def blank_bucket():
    return {"records": 0, "delegations": 0, "duration_s_total": 0.0,
            "duration_known_count": 0, "duration_unknown_count": 0,
            "tokens_total": 0, "tokens_unknown_count": 0,
            "rounds_max": None, "rounds_recorded": 0}


def add_to_bucket(bucket, record):
    bucket["records"] += 1
    if record.get("event") == "delegation":
        bucket["delegations"] += 1
    duration = as_number(record.get("duration_s"))
    if duration is None:
        bucket["duration_unknown_count"] += 1
    else:
        bucket["duration_s_total"] = round(bucket["duration_s_total"] + duration, 3)
        bucket["duration_known_count"] += 1
    tokens = record_tokens(record)
    if tokens is None:
        bucket["tokens_unknown_count"] += 1
    else:
        bucket["tokens_total"] += tokens
    rounds = as_number(record.get("rounds"))
    if rounds is not None:
        bucket["rounds_recorded"] += 1
        if bucket["rounds_max"] is None or rounds > bucket["rounds_max"]:
            bucket["rounds_max"] = rounds


def key_of(value):
    return value if isinstance(value, str) and value.strip() else UNSCOPED


def matches_unit(value, wanted):
    if wanted is None:
        return True
    return isinstance(value, str) and value.strip().lower() == wanted.strip().lower()


def summarize_records(records, unit_filter):
    pipelines, units, agents = {}, {}, {}
    for record in records:
        if not matches_unit(record.get("unit"), unit_filter):
            continue
        add_to_bucket(pipelines.setdefault(key_of(record.get("pipeline")),
                                           blank_bucket()), record)
        add_to_bucket(units.setdefault(key_of(record.get("unit")),
                                       blank_bucket()), record)
        agent = agents.setdefault(key_of(record.get("agent")), blank_bucket())
        add_to_bucket(agent, record)
    for agent in agents.values():
        agent["duration_mean_s"] = (
            round(agent["duration_s_total"] / agent["duration_known_count"], 3)
            if agent["duration_known_count"] else None)
    return pipelines, units, agents


def summarize_gates(entries, unit_filter):
    """Per-gate verdict counts and the fired / rubber-stamped classification."""
    per_gate = {}
    for entry in entries:
        milestone = entry.get("milestone")
        if not matches_unit(milestone, unit_filter):
            continue
        gate = key_of(entry.get("gate"))
        verdict = entry.get("verdict")
        if verdict not in ("PASS", "FAIL", "ERROR"):
            continue
        bucket = per_gate.setdefault(gate, {"runs": 0, "pass": 0, "fail": 0,
                                            "error": 0, "units": {}})
        bucket["runs"] += 1
        bucket[verdict.lower()] += 1
        bucket["units"].setdefault(key_of(milestone), []).append(verdict)
    fired, rubber_stamped, inconclusive = [], [], []
    for gate in sorted(per_gate):
        bucket = per_gate[gate]
        if bucket["fail"] > 0:
            fired.append(gate)
        elif bucket["error"] == 0:
            rubber_stamped.append(gate)
        else:
            inconclusive.append(gate)
    return {"per_gate": per_gate, "fired": fired,
            "rubber_stamped": rubber_stamped, "inconclusive": inconclusive}


def build_summary(run_log, ledger, unit_filter):
    records, malformed = read_jsonl(run_log, "run log")
    warnings = []
    if malformed:
        warnings.append(f"{malformed} unparseable line(s) in the run log were "
                        f"skipped")
    if not records:
        warnings.append("run log holds no records - nothing was recorded for "
                        "this run")
    pipelines, units, agents = summarize_records(records, unit_filter)
    if unit_filter and not any(matches_unit(r.get("unit"), unit_filter)
                               for r in records):
        warnings.append(f"no run-log record carries unit {unit_filter!r}")

    gates = None
    if ledger:
        try:
            entries, ledger_malformed = read_jsonl(ledger, "gate ledger")
        except SummaryError as exc:
            warnings.append(f"gates section is null: {exc}")
        else:
            if ledger_malformed:
                warnings.append(f"{ledger_malformed} unparseable line(s) in the "
                                f"gate ledger were skipped")
            gates = summarize_gates(entries, unit_filter)
            if gates["inconclusive"]:
                warnings.append(
                    "inconclusive gates recorded an ERROR but never a FAIL - "
                    "neither fired nor rubber-stamped")
    else:
        warnings.append("gates section is null: no --ledger given")

    return {
        "run_log": run_log,
        "ledger": ledger,
        "unit_filter": unit_filter,
        "records": len(records),
        "malformed_lines": malformed,
        "pipelines": pipelines,
        "units": units,
        "agents": agents,
        "gates": gates,
        "warnings": warnings,
        "error": None,
    }


def cell(text):
    return str(text).replace("|", "\\|")


def fmt_tokens(bucket):
    if bucket["tokens_total"] == 0 and bucket["tokens_unknown_count"]:
        return f"unknown ({bucket['tokens_unknown_count']}/{bucket['records']} records)"
    suffix = (f" (+{bucket['tokens_unknown_count']} unknown)"
              if bucket["tokens_unknown_count"] else "")
    return f"{bucket['tokens_total']:,}{suffix}"


def fmt_duration(bucket):
    if not bucket["duration_known_count"]:
        return "unknown"
    suffix = (f" (+{bucket['duration_unknown_count']} unknown)"
              if bucket["duration_unknown_count"] else "")
    return f"{bucket['duration_s_total']:.1f}s{suffix}"


def render_markdown(summary):
    scope = summary["unit_filter"] or "whole run"
    # ASCII only in the rendered table: this is printed to a console whose
    # encoding the tool does not control, and a paste-ready block that raises
    # UnicodeEncodeError on a cp1252 terminal is not paste-ready.
    out = [f"**Run telemetry - {cell(scope)}** "
           f"({summary['records']} record(s))", ""]
    out.append("| scope | delegations | tokens | duration | rounds |")
    out.append("| --- | --- | --- | --- | --- |")
    rows = ([(f"pipeline {name}", b) for name, b in sorted(summary["pipelines"].items())]
            + [(f"unit {name}", b) for name, b in sorted(summary["units"].items())])
    for label, bucket in rows:
        rounds = "n/a" if bucket["rounds_max"] is None else bucket["rounds_max"]
        out.append(f"| {cell(label)} | {bucket['delegations']} | "
                   f"{fmt_tokens(bucket)} | {fmt_duration(bucket)} | {rounds} |")
    if not rows:
        out.append("| _no records_ | n/a | n/a | n/a | n/a |")

    out += ["", "| agent | delegations | tokens | mean duration |",
            "| --- | --- | --- | --- |"]
    for name, bucket in sorted(summary["agents"].items()):
        mean = ("unknown" if bucket["duration_mean_s"] is None
                else f"{bucket['duration_mean_s']:.1f}s")
        out.append(f"| {cell(name)} | {bucket['delegations']} | "
                   f"{fmt_tokens(bucket)} | {mean} |")
    if not summary["agents"]:
        out.append("| _no records_ | n/a | n/a | n/a |")

    out.append("")
    gates = summary["gates"]
    if gates is None:
        out.append("_Gates: no ledger read._")
    elif not gates["per_gate"]:
        out.append("_Gates: ledger holds no entries for this scope._")
    else:
        out += ["| gate | runs | PASS | FAIL | ERROR | classification |",
                "| --- | --- | --- | --- | --- | --- |"]
        label = {}
        for name in gates["fired"]:
            label[name] = "fired"
        for name in gates["rubber_stamped"]:
            label[name] = "rubber-stamped"
        for name in gates["inconclusive"]:
            label[name] = "inconclusive"
        for name in sorted(gates["per_gate"]):
            b = gates["per_gate"][name]
            out.append(f"| {cell(name)} | {b['runs']} | {b['pass']} | "
                       f"{b['fail']} | {b['error']} | {label[name]} |")
    for warning in summary["warnings"]:
        out.append(f"> Warning: {cell(warning)}")
    return "\n".join(out)


def main(argv):
    parser = argparse.ArgumentParser(prog="summarize_run.py")
    parser.add_argument("--run-log", dest="run_log")
    parser.add_argument("--ledger")
    parser.add_argument("--unit", help="scope to one milestone title / bug slug")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.run_log:
        print(json.dumps({"error": "missing required argument: --run-log"}))
        return 2
    try:
        summary = build_summary(args.run_log, args.ledger, args.unit)
    except SummaryError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2

    print(render_markdown(summary) if args.markdown
          else json.dumps(summary, indent=2))
    return 0


def run_self_test():
    import shutil

    class SummarizeRunTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.run_log = self.dir / "run-log.jsonl"
            self.ledger = self.dir / "gates.jsonl"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _write(self, path, objs):
            path.write_text("".join(json.dumps(o) + "\n" for o in objs),
                            encoding="utf-8")

        def _rec(self, **kw):
            base = {"ts": "2026-09-02T00:00:00Z", "pipeline": "bgpdd-build",
                    "phase": "Phase 1", "unit": None, "agent": None,
                    "model": None, "event": "delegation", "duration_s": None,
                    "tokens_in": None, "tokens_out": None,
                    "tokens_total": None, "rounds": None, "status": None,
                    "note": None}
            base.update(kw)
            return base

        def _gate(self, gate, verdict, milestone=None):
            return {"ts": "2026-09-02T00:00:00Z", "gate": gate, "argv": [],
                    "milestone": milestone, "inputs": {}, "verdict": verdict,
                    "exit": 0}

        def test_per_pipeline_and_per_unit_aggregation(self):
            self._write(self.run_log, [
                self._rec(unit="M1", agent="mason", tokens_total=1000,
                          duration_s=10.0, rounds=1),
                self._rec(unit="M1", agent="quinn", tokens_in=400,
                          tokens_out=100, duration_s=5.0, rounds=2),
                self._rec(unit="M2", agent="mason", tokens_total=700),
            ])
            s = build_summary(str(self.run_log), None, None)
            pipe = s["pipelines"]["bgpdd-build"]
            self.assertEqual(pipe["delegations"], 3)
            self.assertEqual(pipe["tokens_total"], 2200)
            self.assertEqual(pipe["duration_s_total"], 15.0)
            self.assertEqual(pipe["duration_unknown_count"], 1)
            self.assertEqual(pipe["rounds_max"], 2)
            self.assertEqual(s["units"]["M1"]["tokens_total"], 1500)
            self.assertEqual(s["units"]["M2"]["delegations"], 1)

        def test_unknown_tokens_counted_not_treated_as_zero(self):
            self._write(self.run_log, [
                self._rec(unit="M1", agent="mason", tokens_total=1000),
                self._rec(unit="M1", agent="nova"),
            ])
            s = build_summary(str(self.run_log), None, None)
            self.assertEqual(s["units"]["M1"]["tokens_total"], 1000)
            self.assertEqual(s["units"]["M1"]["tokens_unknown_count"], 1)
            self.assertEqual(s["agents"]["nova"]["tokens_total"], 0)
            self.assertEqual(s["agents"]["nova"]["tokens_unknown_count"], 1)
            self.assertIsNone(s["agents"]["nova"]["duration_mean_s"])

        def test_per_agent_mean_duration(self):
            self._write(self.run_log, [
                self._rec(agent="mason", duration_s=10.0),
                self._rec(agent="mason", duration_s=20.0),
                self._rec(agent="mason"),
            ])
            s = build_summary(str(self.run_log), None, None)
            self.assertEqual(s["agents"]["mason"]["duration_mean_s"], 15.0)
            self.assertEqual(s["agents"]["mason"]["duration_known_count"], 2)

        def test_gates_fired_vs_rubber_stamped(self):
            self._write(self.run_log, [self._rec(unit="M1")])
            self._write(self.ledger, [
                self._gate("check_commit_gate.py", "FAIL", "M1"),
                self._gate("check_commit_gate.py", "PASS", "M1"),
                self._gate("check_blockers.py", "PASS", "M1"),
                self._gate("check_blockers.py", "PASS", "M2"),
            ])
            s = build_summary(str(self.run_log), str(self.ledger), None)
            self.assertEqual(s["gates"]["fired"], ["check_commit_gate.py"])
            self.assertEqual(s["gates"]["rubber_stamped"], ["check_blockers.py"])
            self.assertEqual(s["gates"]["inconclusive"], [])
            cg = s["gates"]["per_gate"]["check_commit_gate.py"]
            self.assertEqual((cg["runs"], cg["pass"], cg["fail"]), (2, 1, 1))
            self.assertEqual(cg["units"]["M1"], ["FAIL", "PASS"])

        def test_error_only_gate_is_inconclusive_not_rubber_stamped(self):
            """An ERROR is a structural defect, not a caught defect."""
            self._write(self.run_log, [self._rec()])
            self._write(self.ledger, [
                self._gate("check_coverage.py", "ERROR", "M1"),
                self._gate("check_coverage.py", "PASS", "M1"),
            ])
            s = build_summary(str(self.run_log), str(self.ledger), None)
            self.assertEqual(s["gates"]["inconclusive"], ["check_coverage.py"])
            self.assertEqual(s["gates"]["rubber_stamped"], [])
            self.assertTrue(any("inconclusive" in w for w in s["warnings"]))

        def test_missing_ledger_yields_null_gates_and_warning(self):
            self._write(self.run_log, [self._rec()])
            s = build_summary(str(self.run_log), str(self.dir / "nope.jsonl"),
                              None)
            self.assertIsNone(s["gates"])
            self.assertTrue(any("gates section is null" in w
                                for w in s["warnings"]))
            self.assertEqual(main(["--run-log", str(self.run_log), "--ledger",
                                   str(self.dir / "nope.jsonl")]), 0)

        def test_no_ledger_flag_yields_null_gates(self):
            self._write(self.run_log, [self._rec()])
            s = build_summary(str(self.run_log), None, None)
            self.assertIsNone(s["gates"])

        def test_unit_filter_scopes_records_and_gates(self):
            self._write(self.run_log, [
                self._rec(unit="M1", agent="mason", tokens_total=1000),
                self._rec(unit="M2", agent="nova", tokens_total=2000),
            ])
            self._write(self.ledger, [
                self._gate("check_commit_gate.py", "FAIL", "M1"),
                self._gate("check_commit_gate.py", "PASS", "M2"),
            ])
            s = build_summary(str(self.run_log), str(self.ledger), "m1")
            self.assertEqual(list(s["units"]), ["M1"])
            self.assertEqual(list(s["agents"]), ["mason"])
            self.assertEqual(s["gates"]["fired"], ["check_commit_gate.py"])
            self.assertEqual(s["gates"]["per_gate"]["check_commit_gate.py"]["runs"], 1)

        def test_unreadable_run_log_is_exit_2(self):
            self.assertEqual(main(["--run-log", str(self.dir / "nope.jsonl")]), 2)
            self.assertEqual(main([]), 2)

        def test_malformed_line_is_skipped_not_fatal(self):
            self.run_log.write_text(
                json.dumps(self._rec(unit="M1", tokens_total=5)) + "\n"
                + "{truncated\n", encoding="utf-8")
            s = build_summary(str(self.run_log), None, None)
            self.assertEqual(s["records"], 1)
            self.assertEqual(s["malformed_lines"], 1)
            self.assertEqual(main(["--run-log", str(self.run_log)]), 0)

        def test_empty_run_log_summarizes_with_warning(self):
            self.run_log.write_text("", encoding="utf-8")
            s = build_summary(str(self.run_log), None, None)
            self.assertEqual(s["records"], 0)
            self.assertTrue(any("no records" in w for w in s["warnings"]))
            self.assertEqual(main(["--run-log", str(self.run_log)]), 0)

        def test_markdown_renders_tables_and_escapes_pipes(self):
            self._write(self.run_log, [
                self._rec(unit="M1: a|b", agent="mason", tokens_total=1000,
                          duration_s=12.0, rounds=3),
            ])
            self._write(self.ledger, [
                self._gate("check_commit_gate.py", "FAIL", "M1: a|b")])
            md = render_markdown(build_summary(str(self.run_log),
                                               str(self.ledger), None))
            self.assertIn("| scope | delegations | tokens | duration | rounds |", md)
            self.assertIn("M1: a\\|b", md)
            self.assertIn("1,000", md)
            self.assertIn("12.0s", md)
            self.assertIn("fired", md)
            self.assertEqual(main(["--run-log", str(self.run_log),
                                   "--ledger", str(self.ledger),
                                   "--markdown"]), 0)

        def test_null_unit_and_agent_bucket_as_unscoped(self):
            self._write(self.run_log, [self._rec(tokens_total=10)])
            s = build_summary(str(self.run_log), None, None)
            self.assertIn(UNSCOPED, s["units"])
            self.assertIn(UNSCOPED, s["agents"])

        def test_non_delegation_events_counted_as_records_only(self):
            self._write(self.run_log, [
                self._rec(unit="M1", event="delegation", agent="mason"),
                self._rec(unit="M1", event="gate", agent=None),
                self._rec(unit="M1", event="phase"),
            ])
            s = build_summary(str(self.run_log), None, None)
            self.assertEqual(s["units"]["M1"]["records"], 3)
            self.assertEqual(s["units"]["M1"]["delegations"], 1)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SummarizeRunTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
