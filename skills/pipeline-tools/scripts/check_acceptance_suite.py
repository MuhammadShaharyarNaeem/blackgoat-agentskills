#!/usr/bin/env python3
"""Mechanical gate for the end-to-end acceptance suite.

Per-milestone gates prove each brick; nothing proves the wall stands. A
feature can pass every milestone commit gate and still fail its own
acceptance walkthrough — most often on an INVERSE operation (unmap,
remove, uninstall), because the milestone that adds mapping has no reason
to unmap. This gate reads Alex's plan-time `acceptance-matrix.md` and
Quinn's end-of-build `acceptance-results.md` and verifies:

  1. every gated scenario's EVERY step has a result;
  2. every gated step's result is PASS (FAIL / BLOCKED / NOT RUN block);
  3. every `Mode: manual` step cites an EXISTING evidence file under an
     `evidence/runtime/` directory — a manual step on an agent's word
     alone reads as NOT RUN and blocks;
  4. every step marked `[inverse of N]` names a real step N in the same
     scenario (blocking, at any priority) and has a result of its own.

It additionally REPORTS (never blocks on) state-changing steps that
declare no inverse — see `undeclared_inverse` in the JSON and the
reasoning note below.

SCOPE LIMIT: this gate verifies the matrix was EXECUTED and EVIDENCED. It
never verifies that a scenario is the RIGHT scenario, that the ASSERT
column asserts the right thing, or that the cited evidence actually shows
what the step claims. Choosing and wording the scenarios is Alex's
authoring judgment and stays reviewable prose; the internal honesty of a
runtime capture is check_runtime_evidence.py's job.

Pure standard library.

Usage:
    python check_acceptance_suite.py --matrix <path> --results <path> \
        [--repo <dir>] [--require-priority P0[,P1]] [--min-scenarios <N>]
    python check_acceptance_suite.py --self-test
"""
import argparse
import json
import re
import sys
from pathlib import Path

SCENARIO_HEADING_RE = re.compile(r"^##\s+(.*)$")
SCENARIO_ID_RE = re.compile(r"\b([A-Za-z]{1,6}-\d+)\b")
PRIORITY_RE = re.compile(r"\bP([0-3])\b")
PAREN_RE = re.compile(r"\(([^)]*)\)")
REQ_ID_RE = re.compile(r"\b[A-Z]{2,6}-\d+\b")
META_PAIR_RE = re.compile(r"^\s*\**\s*([A-Za-z][A-Za-z /_-]{0,30}?)\s*\**\s*:\s*(.*)$")
SEPARATOR_CELL_RE = re.compile(r"^:?-{2,}:?$")
INVERSE_RE = re.compile(r"\[\s*inverse\s+of\s+(\d+)\s*\]", re.IGNORECASE)

# Result lines reuse check_agent_report.py's check-line grammar verbatim, so
# Quinn emits one shape for every durable report she writes.
RESULT_LINE_RE = re.compile(
    r"^\s*-\s*(?P<name>[^:]+?):\s*(?P<status>PASS|FAIL|BLOCKED|NOT RUN)\b(?P<rest>.*)$")
# Canonical step key: `<ScenarioId>.<StepNumber>` — a DOT only. `-` is
# deliberately NOT accepted as the separator: `AS-2-4` is ambiguous with the
# scenario id's own dash, and a forgiving parser would silently bind the wrong
# step. A mis-keyed line lands in `extra_results` (warning) while the step it
# meant to cover lands in `missing_results` (blocking) — the mistake fails loud.
RESULT_KEY_RE = re.compile(r"^([A-Za-z]{1,6}-\d+)\.(\d+)$")

PATH_SHAPE_RE = re.compile(r"^[A-Za-z0-9_./\\-]+$")
PATH_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]+$")

MANUAL_MODES = ("manual",)

# Stores that record no durable state. A step touching only these cannot
# have an inverse, so it is never reported as missing one.
READ_ONLY_STORES = {"", "-", "ui", "none", "n/a", "na", "read", "readonly",
                    "read-only", "view"}

# Verbs whose presence in the DO cell marks a step as state-changing, for the
# NON-BLOCKING undeclared-inverse report only. ALLOWLIST -- therefore
# incomplete: a mutation phrased with a verb absent here is not reported. It is
# advisory precisely because it cannot be complete.
MUTATING_VERB_RE = re.compile(
    r"\b(?:map|unmap|remap|add|remove|create|delete|destroy|connect|disconnect|"
    r"distribute|install|uninstall|reinstall|enable|disable|assign|unassign|"
    r"update|edit|save|submit|post|put|patch|upload|import|export|revoke|grant|"
    r"sync|provision|deprovision|archive|restore|activate|deactivate|attach|"
    r"detach|link|unlink|rename|publish|unpublish|approve|reject|cancel|set|"
    r"clear|reset|purge|migrate|rotate|invite|register|deregister|onboard|"
    r"offboard|apply|schedule|unschedule)\b")


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def read_text(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding="utf-8", errors="replace")


def is_path_shaped(token):
    """A bare path-like token: allowed charset plus a dot-extension."""
    return bool(PATH_SHAPE_RE.match(token)) and bool(PATH_EXTENSION_RE.search(token))


def cited_under(candidate, *segments):
    """True if the CITED string names `segments` as consecutive path parts.

    A containment scan, not a prefix anchor: a capture is normally cited
    relative to the results file, but the same path may legitimately carry a
    `.docs/{project}/implementation/` prefix.

    Rejects any `..` segment. check_commit_gate.py's older prefix-anchored
    predicate normalizes with `lstrip("./")`, which strips ANY leading run
    of `.` and `/` characters -- so `../evidence/review/x.png` collapsed to
    a passing path. Repo-escaping citations are refused here.

    Duplicated verbatim from check_runtime_evidence.py: this script family has
    no shared module, and GateError is already duplicated in seven files.
    """
    normalized = candidate.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p and p != "."]
    if ".." in parts:
        return False
    want = [s.lower() for s in segments]
    for i in range(len(parts) - len(want)):
        if [p.lower() for p in parts[i:i + len(want)]] == want:
            return True
    return False


def resolve_path(candidate, results_path, repo):
    """Resolve a cited path against the results file's dir, then --repo, then as given."""
    for base in (Path(results_path).parent, Path(repo), Path(".")):
        p = base / candidate
        if p.is_file():
            return p
    p = Path(candidate)
    return p if p.is_file() else None


def split_row(line):
    """Cells of a markdown table row, or None if the line is not a row."""
    s = line.strip()
    if not s.startswith("|"):
        return None
    s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def is_separator_row(cells):
    return bool(cells) and all(SEPARATOR_CELL_RE.match(c or "-") for c in cells)


def split_stores(value):
    return [s.strip().lower() for s in re.split(r"[,/;+]", value or "") if s.strip()]


# ---------------------------------------------------------------------------
# Matrix parsing
# ---------------------------------------------------------------------------

def new_scenario(heading):
    """Build a scenario dict from a `## ` heading, or None if it names no id."""
    idm = SCENARIO_ID_RE.search(heading)
    if not idm:
        return None
    pm = PRIORITY_RE.search(heading)
    reqs = []
    for group in PAREN_RE.findall(heading):
        reqs.extend(REQ_ID_RE.findall(group))
    return {
        "id": idm.group(1),
        "title": heading,
        "priority": f"P{pm.group(1)}" if pm else None,
        "requirements": sorted(set(reqs)),
        "surface": None,
        "preconditions": None,
        "step_count": 0,
        "gated": False,
        "_steps": [],
    }


def parse_matrix(text):
    """Return (scenarios, warnings).

    Scenario = a `## ` heading naming an id like `AS-2`. Its steps come from the
    first markdown table under it whose header row carries GO, DO and ASSERT
    columns (case-insensitive). `#`, `Stores` and `Mode` columns are read when
    present. A `Surface: ... | Preconditions: ...` line above the table is
    parsed for metadata.
    """
    scenarios, warnings = [], []
    current, header = None, None
    for raw in text.splitlines():
        m = SCENARIO_HEADING_RE.match(raw)
        if m:
            header = None
            current = new_scenario(m.group(1).strip())
            if current:
                scenarios.append(current)
            continue
        if current is None:
            continue

        cells = split_row(raw)
        if cells is None:
            header = None
            if not current["_steps"]:
                for segment in raw.split("|"):
                    pair = META_PAIR_RE.match(segment)
                    if not pair:
                        continue
                    key = pair.group(1).strip().lower()
                    if key in ("surface", "preconditions", "precondition"):
                        field = "surface" if key == "surface" else "preconditions"
                        current[field] = pair.group(2).strip() or None
            continue

        if is_separator_row(cells):
            continue

        low = [c.lower() for c in cells]
        if {"go", "do", "assert"} <= set(low):
            header = {name: i for i, name in enumerate(low)}
            continue
        if header is None:
            continue

        def cell(name):
            idx = header.get(name)
            return cells[idx] if idx is not None and idx < len(cells) else ""

        ordinal = len(current["_steps"]) + 1
        raw_n = cell("#")
        if raw_n.isdigit():
            number = int(raw_n)
        else:
            number = ordinal
            if "#" in header:
                warnings.append(
                    f"{current['id']}: step row {ordinal} has a non-numeric '#' "
                    f"cell ({raw_n!r}); using the row ordinal {ordinal}")
        mode = (cell("mode") or "auto").strip().lower() or "auto"
        do_text = cell("do")
        inv = INVERSE_RE.search(raw)
        stores = split_stores(cell("stores"))
        current["_steps"].append({
            "key": f"{current['id']}.{number}",
            "scenario": current["id"],
            "n": number,
            "go": cell("go"),
            "do": do_text,
            "assert": cell("assert"),
            "stores": stores,
            "mode": mode,
            "inverse_of": int(inv.group(1)) if inv else None,
            "state_changing": bool(MUTATING_VERB_RE.search(do_text.lower()))
                              and any(s not in READ_ONLY_STORES for s in stores),
            "has_mode_column": "mode" in header,
            "has_stores_column": "stores" in header,
        })
        current["step_count"] = len(current["_steps"])
    return scenarios, warnings


# ---------------------------------------------------------------------------
# Results parsing
# ---------------------------------------------------------------------------

def parse_results(text):
    """Return {step key lowercased: (name, status, rest)}; latest mention wins.

    Section headings in the results file are informational only. The step key
    on each line is self-describing, so no heading scoping is needed -- which
    removes an entire class of "which section was that under" bugs.
    """
    results, unkeyed = {}, []
    for line in text.splitlines():
        m = RESULT_LINE_RE.match(line)
        if not m:
            continue
        name = m.group("name").strip().strip("*`").strip()
        km = RESULT_KEY_RE.match(name)
        if not km:
            unkeyed.append(name)
            continue
        results[f"{km.group(1)}.{km.group(2)}".lower()] = (
            name, m.group("status"), m.group("rest"))
    return results, unkeyed


def evidence_tokens(rest):
    """Path-shaped tokens cited in a result line's trailing detail.

    Sentence punctuation is stripped with rstrip, never strip: a citation
    legitimately carries a `.docs/{project}/` prefix, and a symmetric
    strip(".") would eat that leading dot and unresolve the path. Looped to a
    fixed point because the two classes interleave -- a citation wrapped in
    backticks AND ending a sentence reads `` `....md`. ``.
    """
    out = []
    for tok in re.split(r"[,\s]+", rest or ""):
        previous = None
        while previous != tok:
            previous = tok
            tok = tok.strip("`<>()[]*—–").rstrip(".:;,")
        if tok and is_path_shaped(tok) and tok not in out:
            out.append(tok)
    return out


# ---------------------------------------------------------------------------
# Priority scoping
# ---------------------------------------------------------------------------

def parse_priority_filter(value):
    """`P0` -> {P0}; `P0,P1` -> {P0,P1}; `P1` -> {P0,P1} ("at or above P1")."""
    if value is None:
        return None
    levels = []
    for tok in value.split(","):
        tok = tok.strip().upper()
        if not tok:
            continue
        if not re.fullmatch(r"P[0-3]", tok):
            raise GateError(
                f"--require-priority value {tok!r} is not a priority token "
                "(expected P0, P1, P2 or P3, comma-separated)")
        levels.append(int(tok[1]))
    if not levels:
        raise GateError("--require-priority was given no priority token")
    return {f"P{n}" for n in range(0, max(levels) + 1)}


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_report(args):
    report = {
        "matrix": args.matrix,
        "results": args.results,
        "require_priority": None,
        "min_scenarios": args.min_scenarios,
        "scenarios": [],
        "gated_scenarios": [],
        "steps": [],
        "steps_gated": 0,
        "passed": 0,
        "failed": [],
        "blocked": [],
        "not_run": [],
        "missing_results": [],
        "unevidenced_manual": [],
        "dangling_inverse": [],
        "undeclared_inverse": [],
        "extra_results": [],
        "warnings": [],
        "result": "FAIL",
        "error": None,
    }

    wanted = parse_priority_filter(args.require_priority)
    report["require_priority"] = sorted(wanted) if wanted else None

    matrix_text = read_text(args.matrix)
    scenarios, parse_warnings = parse_matrix(matrix_text)
    report["warnings"].extend(parse_warnings)
    if not scenarios:
        raise GateError(
            f"no parseable scenario in {args.matrix} — a scenario is a '## ' "
            "heading naming an id like 'AS-2'; not a conforming acceptance matrix")

    results_text = read_text(args.results)
    if not results_text.strip():
        raise GateError(f"results file is empty: {args.results}")
    results, unkeyed = parse_results(results_text)
    if not results:
        raise GateError(
            f"no parseable result line in {args.results} — expected lines of the "
            "form '- AS-2.3: PASS — detail'; results file shape unreadable")
    for name in unkeyed:
        report["extra_results"].append(name)

    # ---- scope each scenario ----
    for sc in scenarios:
        if wanted is None:
            sc["gated"] = True
        elif sc["priority"] is None:
            # Fail-closed: an unprioritized scenario cannot be filtered
            # honestly, so it is gated rather than silently skipped.
            sc["gated"] = True
            report["warnings"].append(
                f"{sc['id']}: heading declares no priority token; gated anyway "
                "(fail-closed) — add P0/P1/P2 to the heading to scope it")
        else:
            sc["gated"] = sc["priority"] in wanted
        if not sc["_steps"]:
            report["warnings"].append(
                f"{sc['id']}: no step table found (need a header row carrying "
                "GO, DO and ASSERT columns) — this scenario proves nothing")

    report["gated_scenarios"] = [sc["id"] for sc in scenarios if sc["gated"]]

    # ---- per-step evaluation ----
    seen_keys = set()
    for sc in scenarios:
        numbers = {st["n"] for st in sc["_steps"]}
        inverse_targets = {st["inverse_of"] for st in sc["_steps"]
                           if st["inverse_of"] is not None}
        for st in sc["_steps"]:
            entry = {k: st[k] for k in
                     ("key", "scenario", "n", "mode", "stores", "inverse_of",
                      "state_changing")}
            entry.update({"gated": sc["gated"], "priority": sc["priority"],
                          "status": None, "detail": None, "evidence": [],
                          "evidence_ok": None, "problems": []})
            seen_keys.add(st["key"].lower())

            # Dangling inverse reference: a matrix-authoring defect. Blocking at
            # ANY priority — priority scopes EXECUTION, not authoring validity,
            # and a reference to a step that does not exist means the matrix is
            # lying about its own coverage.
            if st["inverse_of"] is not None and st["inverse_of"] not in numbers:
                entry["problems"].append(
                    f"declares '[inverse of {st['inverse_of']}]' but scenario "
                    f"{sc['id']} has no step {st['inverse_of']}")
                report["dangling_inverse"].append(st["key"])

            # Non-blocking advisory: a state-changing step with no inverse
            # anywhere in its scenario.
            if (st["state_changing"] and st["inverse_of"] is None
                    and st["n"] not in inverse_targets):
                report["undeclared_inverse"].append(st["key"])

            found = results.get(st["key"].lower())
            if found is None:
                if sc["gated"]:
                    report["missing_results"].append(st["key"])
                    entry["problems"].append("no result line for this step")
                elif st["inverse_of"] is not None:
                    report["warnings"].append(
                        f"{st['key']}: inverse step in a non-gated scenario has "
                        "no result — not blocking at this priority scope")
                report["steps"].append(entry)
                continue

            _, status, rest = found
            entry["status"] = status
            entry["detail"] = rest.strip() or None

            if entry["mode"] in MANUAL_MODES:
                entry["evidence"] = evidence_tokens(rest)
                accepted = [t for t in entry["evidence"]
                            if cited_under(t, "evidence", "runtime")
                            and resolve_path(t, args.results, args.repo) is not None]
                entry["evidence_ok"] = bool(accepted)
                entry["evidence"] = accepted or entry["evidence"]

            if not sc["gated"]:
                report["steps"].append(entry)
                continue

            report["steps_gated"] += 1
            if status == "FAIL":
                report["failed"].append(st["key"])
                entry["problems"].append("result is FAIL")
            elif status == "BLOCKED":
                report["blocked"].append(st["key"])
                entry["problems"].append("result is BLOCKED")
            elif status == "NOT RUN":
                report["not_run"].append(st["key"])
                entry["problems"].append("result is NOT RUN")
            elif entry["mode"] in MANUAL_MODES and not entry["evidence_ok"]:
                # The crux. Manual steps are first-class (a device check
                # genuinely cannot be automated) but never trusted on an
                # agent's word: an unevidenced manual PASS reads as NOT RUN.
                report["unevidenced_manual"].append(st["key"])
                report["not_run"].append(st["key"])
                entry["problems"].append(
                    "manual step reports PASS but cites no existing evidence "
                    "file under an 'evidence/runtime/' directory (a '..' segment "
                    "is also refused) — reads as NOT RUN")
            elif entry["problems"]:
                pass  # dangling inverse already recorded; result itself is green
            else:
                report["passed"] += 1
            report["steps"].append(entry)

    for key in sorted(results):
        if key not in seen_keys:
            report["extra_results"].append(results[key][0])

    # ---- report-level warnings ----
    if report["extra_results"]:
        report["warnings"].append(
            "result line(s) whose key matches no matrix step (canonical key is "
            "'<ScenarioId>.<StepNumber>', dot-separated): "
            + ", ".join(report["extra_results"]))
    if report["undeclared_inverse"]:
        report["warnings"].append(
            "ADVISORY (non-blocking): state-changing step(s) with no inverse "
            "declared anywhere in their scenario — the inverse operation is the "
            "one that escapes: " + ", ".join(report["undeclared_inverse"]))
    if any(not st["has_mode_column"] for sc in scenarios for st in sc["_steps"]):
        report["warnings"].append(
            "step table(s) have no 'Mode' column — every step there defaults to "
            "'auto' and no manual-evidence check applies to it")
    if any(not st["has_stores_column"] for sc in scenarios for st in sc["_steps"]):
        report["warnings"].append(
            "step table(s) have no 'Stores' column — the undeclared-inverse "
            "advisory cannot run on them")
    if len(report["gated_scenarios"]) < args.min_scenarios:
        report["warnings"].append(
            f"{len(report['gated_scenarios'])} scenario(s) in gate scope, "
            f"below --min-scenarios {args.min_scenarios}")
    if report["steps_gated"] == 0:
        report["warnings"].append(
            "zero steps in gate scope — a suite that executes nothing cannot pass")

    report["scenarios"] = [{k: v for k, v in sc.items() if not k.startswith("_")}
                           for sc in scenarios]

    gate_ok = (len(report["gated_scenarios"]) >= args.min_scenarios
               and report["steps_gated"] > 0
               and not report["missing_results"]
               and not report["failed"]
               and not report["blocked"]
               and not report["not_run"]
               and not report["unevidenced_manual"]
               and not report["dangling_inverse"])
    report["result"] = "PASS" if gate_ok else "FAIL"
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="check_acceptance_suite.py")
    p.add_argument("--matrix")
    p.add_argument("--results")
    p.add_argument("--repo", default=".")
    p.add_argument("--require-priority")
    p.add_argument("--min-scenarios", type=int, default=1)
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    missing = [n for n, v in (("--matrix", args.matrix),
                              ("--results", args.results)) if not v]
    if missing:
        print(json.dumps({"result": "ERROR",
                          "error": f"missing required argument(s): {', '.join(missing)}"}))
        return 2

    try:
        report = build_report(args)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return 2

    print(json.dumps(report, indent=2))
    return 0 if report["result"] == "PASS" else 1


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil
    import tempfile
    import unittest

    MATRIX = """# Acceptance Matrix — slide-integration

## AS-1 Integration connect — P0 — (FR-1)
Surface: api | Preconditions: none

| # | GO | DO | ASSERT | Stores | Mode |
|---|----|----|--------|--------|------|
| 1 | Integrations | connect Slide | 200 + token stored | api, db | auto |
| 2 | Integrations | disconnect Slide [inverse of 1] | 200 + token gone | api, db | auto |

## AS-2 Client mapping lifecycle — P0 — (FR-3, FR-4, EC-2)
Surface: web+api | Preconditions: integration connected (AS-1)

| # | GO | DO | ASSERT | Stores | Mode |
|---|----|----|--------|--------|------|
| 1 | Clients list | map client A | 200 + mapping row | api, db | auto |
| 2 | Clients list | reload | green tick on A | ui | auto |
| 3 | Clients list | unmap A [inverse of 1] | 200 + row gone | api, db | auto |
| 4 | Asset policies | distribute | Slide installed on device | device | manual |
"""

    def results(lines):
        return ("# Acceptance Results — slide-integration\n\n"
                "## Execution — 2026-08-12\n\n" + "\n".join(lines) + "\n")

    GREEN = [
        "- AS-1.1: PASS — exit 0 — 200, token persisted",
        "- AS-1.2: PASS — exit 0 — 200, token removed",
        "- AS-2.1: PASS — exit 0 — 200 + mapping row",
        "- AS-2.2: PASS — exit 0 — green tick rendered",
        "- AS-2.3: PASS — exit 0 — 200 + row gone",
        "- AS-2.4: PASS — evidence/runtime/as2-4-device-install.md — agent 1.4.2 on device",
    ]

    class Tests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.impl = self.dir / ".docs" / "slide" / "implementation"
            (self.impl / "evidence" / "runtime").mkdir(parents=True)
            self.matrix = self.impl / "acceptance-matrix.md"
            self.results = self.impl / "acceptance-results.md"
            self.matrix.write_text(MATRIX, encoding="utf-8")
            (self.impl / "evidence" / "runtime" / "as2-4-device-install.md"
             ).write_text("# device capture\n", encoding="utf-8")

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _args(self, **kw):
            base = dict(matrix=str(self.matrix), results=str(self.results),
                        repo=str(self.dir), require_priority=None,
                        min_scenarios=1, self_test=False)
            base.update(kw)
            return argparse.Namespace(**base)

        def _run(self, lines=None, matrix=None, **kw):
            self.results.write_text(results(lines if lines is not None else GREEN),
                                    encoding="utf-8")
            if matrix is not None:
                self.matrix.write_text(matrix, encoding="utf-8")
            return build_report(self._args(**kw))

        # ---- happy path ----

        def test_happy_suite_passes(self):
            r = self._run()
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["passed"], 6)
            self.assertEqual(r["steps_gated"], 6)
            self.assertEqual(r["gated_scenarios"], ["AS-1", "AS-2"])

        def test_matrix_parsing_shape(self):
            r = self._run()
            as2 = [s for s in r["scenarios"] if s["id"] == "AS-2"][0]
            self.assertEqual(as2["priority"], "P0")
            self.assertEqual(as2["requirements"], ["EC-2", "FR-3", "FR-4"])
            self.assertEqual(as2["surface"], "web+api")
            self.assertEqual(as2["preconditions"], "integration connected (AS-1)")
            self.assertEqual(as2["step_count"], 4)
            step3 = [s for s in r["steps"] if s["key"] == "AS-2.3"][0]
            self.assertEqual(step3["inverse_of"], 1)
            self.assertEqual(step3["stores"], ["api", "db"])
            self.assertEqual(step3["mode"], "auto")

        # ---- condition 1: every step has a result ----

        def test_missing_step_result_blocks(self):
            r = self._run([l for l in GREEN if not l.startswith("- AS-2.3")])
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["missing_results"], ["AS-2.3"])

        def test_missing_inverse_step_result_blocks(self):
            """The driver: the unmap step is the one that escapes."""
            r = self._run([l for l in GREEN if not l.startswith("- AS-1.2")])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("AS-1.2", r["missing_results"])

        def test_empty_results_file_is_exit_2(self):
            self.results.write_text("   \n", encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(self._args())

        def test_unreadable_results_shape_is_exit_2(self):
            self.results.write_text("# Results\n\nall good, shipped it\n",
                                    encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(self._args())

        # ---- condition 2: every result is PASS ----

        def test_fail_result_blocks(self):
            r = self._run(GREEN[:-1] + ["- AS-2.4: FAIL — agent never installed"])
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["failed"], ["AS-2.4"])

        def test_not_run_result_blocks(self):
            r = self._run(GREEN[:2] + ["- AS-2.1: NOT RUN — no sandbox tenant"]
                          + GREEN[3:])
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["not_run"], ["AS-2.1"])

        def test_blocked_result_blocks(self):
            r = self._run(GREEN[:1] + ["- AS-1.2: BLOCKED — disconnect endpoint 500s"]
                          + GREEN[2:])
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["blocked"], ["AS-1.2"])

        def test_lowercase_status_is_not_a_result(self):
            r = self._run(GREEN[:-1] + ["- AS-2.4: pass — looked fine"])
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["missing_results"], ["AS-2.4"])

        def test_duplicate_key_latest_wins(self):
            r = self._run(["- AS-2.3: FAIL — row still there"] + GREEN)
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["failed"], [])

        # ---- condition 3: manual steps must cite existing runtime evidence ----

        def test_unevidenced_manual_pass_reads_as_not_run(self):
            r = self._run(GREEN[:-1]
                          + ["- AS-2.4: PASS — confirmed the agent installed"])
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["unevidenced_manual"], ["AS-2.4"])
            self.assertEqual(r["not_run"], ["AS-2.4"])

        def test_manual_evidence_file_must_exist(self):
            r = self._run(GREEN[:-1]
                          + ["- AS-2.4: PASS — evidence/runtime/absent.md"])
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["unevidenced_manual"], ["AS-2.4"])

        def test_manual_evidence_outside_evidence_runtime_rejected(self):
            p = self.impl / "evidence" / "build"
            p.mkdir(parents=True, exist_ok=True)
            (p / "device.md").write_text("x", encoding="utf-8")
            r = self._run(GREEN[:-1]
                          + ["- AS-2.4: PASS — evidence/build/device.md"])
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["unevidenced_manual"], ["AS-2.4"])

        def test_manual_evidence_parent_traversal_refused(self):
            (self.dir / "escape.md").write_text("x", encoding="utf-8")
            r = self._run(GREEN[:-1] + [
                "- AS-2.4: PASS — ../evidence/runtime/as2-4-device-install.md"])
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["unevidenced_manual"], ["AS-2.4"])
            self.assertFalse(cited_under("../evidence/runtime/x.md",
                                         "evidence", "runtime"))
            self.assertTrue(cited_under("evidence\\runtime\\x.md",
                                        "evidence", "runtime"))
            self.assertTrue(cited_under(
                ".docs/slide/implementation/evidence/runtime/x.md",
                "evidence", "runtime"))

        def test_docs_prefixed_citation_keeps_its_leading_dot(self):
            """A symmetric strip('.') would eat `.docs/`'s leading dot."""
            self.assertEqual(
                evidence_tokens("— `.docs/slide/implementation/evidence/runtime/x.md`."),
                [".docs/slide/implementation/evidence/runtime/x.md"])
            r = self._run(GREEN[:-1] + [
                "- AS-2.4: PASS — .docs/slide/implementation/evidence/runtime/"
                "as2-4-device-install.md."], repo=str(self.dir))
            self.assertEqual(r["result"], "PASS", r)

        def test_manual_evidence_resolved_against_repo(self):
            (self.dir / "evidence" / "runtime").mkdir(parents=True)
            (self.dir / "evidence" / "runtime" / "dev.md").write_text(
                "x", encoding="utf-8")
            r = self._run(GREEN[:-1] + ["- AS-2.4: PASS — evidence/runtime/dev.md"])
            self.assertEqual(r["result"], "PASS", r)

        def test_auto_step_needs_no_evidence_file(self):
            r = self._run()
            step1 = [s for s in r["steps"] if s["key"] == "AS-2.1"][0]
            self.assertIsNone(step1["evidence_ok"])

        def test_missing_mode_column_defaults_auto_and_warns(self):
            m = MATRIX.replace(" | Mode |", " |").replace("|--------|------|",
                                                          "|--------|")
            m = re.sub(r"\| (auto|manual) \|$", "|", m, flags=re.M)
            r = self._run(GREEN, matrix=m)
            self.assertEqual(r["result"], "PASS", r)
            self.assertTrue(any("no 'Mode' column" in w for w in r["warnings"]))

        # ---- condition 4: inverse coverage ----

        def test_dangling_inverse_reference_blocks(self):
            m = MATRIX.replace("[inverse of 1]", "[inverse of 9]", 1)
            r = self._run(GREEN, matrix=m)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["dangling_inverse"], ["AS-1.2"])

        def test_dangling_inverse_blocks_even_out_of_priority_scope(self):
            m = MATRIX.replace("## AS-1 Integration connect — P0",
                               "## AS-1 Integration connect — P2")
            m = m.replace("[inverse of 1]", "[inverse of 9]", 1)
            r = self._run(GREEN, matrix=m, require_priority="P0")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["dangling_inverse"], ["AS-1.2"])

        def test_inverse_in_another_scenario_does_not_resolve(self):
            """`[inverse of N]` is scenario-local by design."""
            m = MATRIX.replace("| 2 | Integrations | disconnect Slide [inverse of 1] "
                               "| 200 + token gone | api, db | auto |",
                               "| 2 | Integrations | disconnect Slide [inverse of 4] "
                               "| 200 + token gone | api, db | auto |")
            r = self._run(GREEN, matrix=m)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["dangling_inverse"], ["AS-1.2"])

        def test_undeclared_inverse_is_advisory_not_blocking(self):
            r = self._run()
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["undeclared_inverse"], ["AS-2.4"])
            self.assertTrue(any("ADVISORY" in w for w in r["warnings"]))

        def test_read_only_step_is_not_state_changing(self):
            r = self._run()
            reload_step = [s for s in r["steps"] if s["key"] == "AS-2.2"][0]
            self.assertFalse(reload_step["state_changing"])
            self.assertNotIn("AS-2.2", r["undeclared_inverse"])

        def test_inversed_step_is_not_reported_as_undeclared(self):
            r = self._run()
            self.assertNotIn("AS-2.1", r["undeclared_inverse"])
            self.assertNotIn("AS-1.1", r["undeclared_inverse"])
            self.assertNotIn("AS-1.2", r["undeclared_inverse"])

        # ---- priority scoping ----

        def test_priority_filter_excludes_lower_scenarios(self):
            m = MATRIX.replace("## AS-2 Client mapping lifecycle — P0",
                               "## AS-2 Client mapping lifecycle — P2")
            r = self._run(GREEN[:2], matrix=m, require_priority="P0")
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["gated_scenarios"], ["AS-1"])
            self.assertEqual(r["steps_gated"], 2)

        def test_priority_filter_is_at_or_above(self):
            m = MATRIX.replace("## AS-2 Client mapping lifecycle — P0",
                               "## AS-2 Client mapping lifecycle — P1")
            r = self._run(GREEN, matrix=m, require_priority="P1")
            self.assertEqual(sorted(r["gated_scenarios"]), ["AS-1", "AS-2"])
            self.assertEqual(r["require_priority"], ["P0", "P1"])

        def test_unprioritized_scenario_is_gated_fail_closed(self):
            m = MATRIX.replace("## AS-2 Client mapping lifecycle — P0 —",
                               "## AS-2 Client mapping lifecycle —")
            r = self._run(GREEN[:2], matrix=m, require_priority="P0")
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("AS-2", r["gated_scenarios"])
            self.assertTrue(any("declares no priority" in w for w in r["warnings"]))

        def test_no_priority_filter_gates_everything(self):
            r = self._run()
            self.assertIsNone(r["require_priority"])
            self.assertEqual(len(r["gated_scenarios"]), 2)

        def test_bad_priority_token_is_exit_2(self):
            with self.assertRaises(GateError):
                build_report(self._args(require_priority="P9"))
            with self.assertRaises(GateError):
                build_report(self._args(require_priority="high"))

        def test_no_scenario_in_scope_fails(self):
            r = self._run(GREEN, require_priority="P0",
                          matrix=MATRIX.replace("— P0 —", "— P3 —"))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["gated_scenarios"], [])

        # ---- --min-scenarios ----

        def test_min_scenarios_enforced(self):
            r = self._run(min_scenarios=3)
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(any("--min-scenarios" in w for w in r["warnings"]))

        # ---- structural ----

        def test_missing_matrix_is_exit_2(self):
            with self.assertRaises(GateError):
                build_report(self._args(matrix=str(self.dir / "nope.md")))

        def test_matrix_with_no_scenario_is_exit_2(self):
            self.matrix.write_text("# Acceptance Matrix\n\n## Overview\n\nprose\n",
                                   encoding="utf-8")
            self.results.write_text(results(GREEN), encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(self._args())

        def test_scenario_with_no_step_table_warns_and_cannot_pass(self):
            self.matrix.write_text(
                "## AS-1 Connect — P0 — (FR-1)\n\nsurface: api\n", encoding="utf-8")
            r = self._run(GREEN)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["steps_gated"], 0)
            self.assertTrue(any("no step table" in w for w in r["warnings"]))

        def test_extra_result_key_is_a_warning_and_the_real_step_blocks(self):
            r = self._run([l for l in GREEN if not l.startswith("- AS-2.3")]
                          + ["- AS-2-3: PASS — exit 0 — row gone"])
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("AS-2.3", r["missing_results"])
            self.assertIn("AS-2-3", r["extra_results"])

        def test_json_keys_present_on_every_run(self):
            expected = {
                "matrix", "results", "require_priority", "min_scenarios",
                "scenarios", "gated_scenarios", "steps", "steps_gated", "passed",
                "failed", "blocked", "not_run", "missing_results",
                "unevidenced_manual", "dangling_inverse", "undeclared_inverse",
                "extra_results", "warnings", "result", "error"}
            self.assertEqual(set(self._run().keys()), expected)
            self.assertEqual(set(self._run(GREEN[:1]).keys()), expected)

        # ---- CLI ----

        def test_usage_error_exits_2(self):
            self.assertEqual(main(["--matrix", str(self.matrix)]), 2)
            self.assertEqual(main(["--results", str(self.results)]), 2)
            self.assertEqual(main([]), 2)

        def test_cli_exit_codes(self):
            self.results.write_text(results(GREEN), encoding="utf-8")
            argv = ["--matrix", str(self.matrix), "--results", str(self.results),
                    "--repo", str(self.dir)]
            self.assertEqual(main(argv), 0)
            self.results.write_text(
                results(GREEN[:-1] + ["- AS-2.4: PASS — trust me"]),
                encoding="utf-8")
            self.assertEqual(main(argv), 1)
            self.assertEqual(main(["--matrix", str(self.dir / "nope.md"),
                                   "--results", str(self.results)]), 2)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
