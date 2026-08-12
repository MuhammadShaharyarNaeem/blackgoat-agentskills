#!/usr/bin/env python3
"""Mechanical gate for observed-runtime evidence.

Converts the prose rule that an in-process observation can fail a wire
claim but never pass one (runtime-evidence/SKILL.md) into an artifact that
has to exist on disk. Reads a durable agent report, collects its
`**Runtime evidence:**` citations, and verifies each cited capture:

  * exists, resolved against the report's directory or --repo
  * is cited under an `evidence/runtime/` directory
  * names an OUT-OF-PROCESS transport (an in-process test client is a
    gate failure, not a shortcut -- this is the mechanical twin of the
    "real HTTP" comment that let a missing response envelope ship)
  * probes a runtime surface, not a compile/build/search command
  * postdates every --changed-files entry (freshness)
  * carries the required top-level response keys
  * does not name a forbidden (shared dev/staging) host

Pure standard library.

Usage:
    python check_runtime_evidence.py --report <path> --milestone "<title>" \
        --changed-files <p1> [<p2> ...] [--repo <dir>] \
        [--surface <key>] [--require-key <name>]... [--expect-status <N>] \
        [--forbid-host <pattern>]... [--require-build-marker <value>] \
        [--min-captures <N>]
    python check_runtime_evidence.py --self-test
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

CITATION_RE = re.compile(r"\*\*Runtime evidence:\*\*(.*)", re.IGNORECASE)
FIELD_RE = re.compile(r"^\s*-\s*([^:]{1,60}?):\s*(.*)$")
CAPTURED_HEADING_RE = re.compile(r"(?im)^##\s+Captured\s+output\s*$")
# Horizontal whitespace only ([^\S\n]), never \s: a `\s*` here consumes the
# newline after the opening fence and then matches the NEXT line, silently
# eating the first line of every captured body — which is exactly the HTTP
# status line --expect-status needs.
FENCE_RE = re.compile(r"(?m)^[^\S\n]*(`{3,})[^\n]*$")
STATUS_LINE_RE = re.compile(r"HTTP/\d(?:\.\d)?\s+(\d{3})")
PATH_SHAPE_RE = re.compile(r"^[A-Za-z0-9_./\\-]+$")
PATH_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]+$")

# Transports that never open a socket. A capture naming one of these was
# taken inside the process it claims to have observed from outside.
# BLOCKLIST -- therefore incomplete: a new framework's in-process client
# passes until its name is added here.
IN_PROCESS_TELLS = (
    "webapplicationfactory", "createclient(", "testserver", "testclient",
    "supertest", "mockmvc", "asgitransport", "rack-test", "httptestingcontroller",
    "inmemorytransport", "app.test_client(",
)

# Commands that prove the code was written, never that it runs. Word-boundary
# regexes rather than substrings, so a base URL containing "org " does not read
# as `rg`. Test-RUNNER invocations are the load-bearing entries: `dotnet test`
# executes the in-process suite, which is precisely the tier this gate exists
# to stop standing in for an observation.
NON_RUNTIME_PROBE_RES = (
    re.compile(r"\b(?:dotnet|go|cargo|mvn|gradle)\s+(?:build|restore|compile)\b"),
    re.compile(r"\b(?:dotnet|go|cargo|mvn|gradle)\s+test\b"),
    re.compile(r"\bnpm\s+(?:ci|test|run\s+(?:build|test))\b"),
    re.compile(r"\byarn\s+(?:build|test)\b"),
    re.compile(r"\b(?:pytest|jest|vitest|mocha|karma|nunit|xunit)\b"),
    re.compile(r"\btsc\b|--no-?emit\b|\bmsbuild\b"),
    re.compile(r"\b(?:grep|rg|ripgrep|findstr|ack)\b"),
    re.compile(r"\bmake\s+(?:build|all)\b"),
)

REQUIRED_FIELDS = ("milestone", "transport", "probe command", "captured", "exit code")


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


def collect_citations(report_text):
    """Every path cited on a `**Runtime evidence:**` line, file-wide.

    Collection is file-wide and scoping happens capture-side (on each
    capture's own `- Milestone:` field), because `test-report.md`'s
    `#Task [N]:` headers are documented human-only -- inventing a machine
    header there would break Quinn's append-only format.
    """
    out = []
    for line in report_text.splitlines():
        m = CITATION_RE.search(line)
        if not m:
            continue
        for tok in re.split(r"[,\s]+", m.group(1).strip()):
            tok = tok.strip("`<>()[]")
            if tok and is_path_shaped(tok):
                out.append(tok)
    # de-duplicate, preserving first-seen order
    seen, unique = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def cited_under(candidate, *segments):
    """True if the CITED string names `segments` as consecutive path parts.

    A containment scan, not a prefix anchor: a capture is normally cited
    relative to the report, but the same path may legitimately carry a
    `.docs/{project}/implementation/` prefix.

    Rejects any `..` segment. check_commit_gate.py's older prefix-anchored
    predicate normalizes with `lstrip("./")`, which strips ANY leading run
    of `.` and `/` characters -- so `../evidence/review/x.png` collapsed to
    a passing path. Repo-escaping citations are refused here.
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


def resolve_path(candidate, report_path, repo):
    """Resolve a cited path against the report's dir, then --repo, then as given."""
    for base in (Path(report_path).parent, Path(repo), Path(".")):
        p = base / candidate
        if p.is_file():
            return p
    p = Path(candidate)
    return p if p.is_file() else None


def milestone_tokens(milestone):
    """Full title plus its leading identifier (text before the first ':' / '—')."""
    tokens = [milestone.strip().lower()]
    short = re.split(r"[:—-]", milestone, maxsplit=1)[0].strip().lower()
    if len(short) >= 2 and short != tokens[0]:
        tokens.append(short)
    return tokens


def milestone_token_patterns(milestone):
    """Word-boundary regex per token, so `M1` never matches `M10`."""
    return [re.compile(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])")
            for t in milestone_tokens(milestone)]


def matches_milestone(patterns, haystack):
    haystack_l = (haystack or "").lower()
    return any(p.search(haystack_l) for p in patterns)


def parse_capture(text):
    """Return (fields dict keyed lowercase, captured_output str or None)."""
    m = CAPTURED_HEADING_RE.search(text)
    head = text[:m.start()] if m else text
    fields = {}
    for line in head.splitlines():
        fm = FIELD_RE.match(line)
        if fm:
            fields.setdefault(fm.group(1).strip().lower(), fm.group(2).strip())
    if not m:
        return fields, None
    body = text[m.end():]
    fence = FENCE_RE.search(body)
    if not fence:
        return fields, body.strip()
    marker = fence.group(1)
    rest = body[fence.end():]
    close = rest.find("\n" + marker)
    return fields, (rest[:close] if close != -1 else rest).strip("\n")


def newest_changed_mtime(changed_files):
    """(newest mtime or None, warnings) over the declared changed files."""
    warnings, newest = [], None
    for f in changed_files:
        p = Path(f)
        if not p.exists():
            warnings.append(f"declared changed file does not exist: {f}")
            continue
        mt = p.stat().st_mtime
        newest = mt if newest is None else max(newest, mt)
    return newest, warnings


def extract_body_json(captured):
    """Parse the LAST balanced JSON object in the captured output.

    Last, not first: a probe's output routinely carries a status line and
    headers before the body, and run_quiet merges stderr into the stream.
    """
    if not captured:
        return None, "no captured output"
    depth, start, best = 0, None, None
    in_str, esc = False, False
    for i, ch in enumerate(captured):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth:
                depth -= 1
                if depth == 0 and start is not None:
                    best = captured[start:i + 1]
    if best is None:
        return None, "no JSON object found in captured output"
    try:
        return json.loads(best), None
    except json.JSONDecodeError as exc:
        return None, f"captured body is not valid JSON: {exc}"


def key_scopes(doc):
    """Scopes a --require-key may be satisfied in: the document, and its `body`.

    Deliberately NOT recursive. A key named `isSuccess` buried inside a
    payload must never pass an envelope check.
    """
    scopes = []
    if isinstance(doc, dict):
        scopes.append(doc)
        if isinstance(doc.get("body"), dict):
            scopes.append(doc["body"])
    return scopes


# ---------------------------------------------------------------------------
# Per-capture evaluation
# ---------------------------------------------------------------------------

def evaluate_capture(candidate, args, patterns, newest_mtime):
    """Return a per-capture result dict. `problems` empty => accepted."""
    res = {
        "path": candidate, "exists": False, "cited_under_evidence_runtime": False,
        "milestone_match": False, "fresh": None, "surface": None,
        "transport": None, "probe_command": None, "status": None,
        "body_parsed": False, "body_keys": [], "missing_keys": [],
        "build_marker": None, "problems": [],
    }

    res["cited_under_evidence_runtime"] = cited_under(candidate, "evidence", "runtime")
    if not res["cited_under_evidence_runtime"]:
        res["problems"].append(
            "not cited under an 'evidence/runtime/' directory (a '..' segment is "
            "also refused); builder captures under evidence/build/ do not gate")

    resolved = resolve_path(candidate, args.report, args.repo)
    if resolved is None:
        res["problems"].append("cited capture file does not exist")
        return res
    res["exists"] = True

    text = resolved.read_text(encoding="utf-8", errors="replace")
    fields, captured = parse_capture(text)
    if captured is None:
        raise GateError(
            f"cited capture {candidate} has no '## Captured output' section — "
            "structurally not a capture artifact")

    res["milestone_match"] = matches_milestone(patterns, fields.get("milestone", ""))
    if not res["milestone_match"]:
        # Not this milestone's capture — caller filters it out, not a problem.
        res["problems"].append("capture's Milestone field does not name this milestone")
        return res

    for required in REQUIRED_FIELDS:
        if not fields.get(required):
            res["problems"].append(f"capture is missing the '{required}' field")

    res["surface"] = fields.get("surface")
    res["transport"] = fields.get("transport")
    res["probe_command"] = fields.get("probe command")
    res["build_marker"] = fields.get("build marker")

    haystack = f"{res['transport'] or ''} {res['probe_command'] or ''}".lower()
    for tell in IN_PROCESS_TELLS:
        if tell in haystack:
            res["problems"].append(
                f"declares an IN-PROCESS transport ({tell!r}) — an in-process "
                "observation can fail a wire claim but never pass one")
            break
    for pattern in NON_RUNTIME_PROBE_RES:
        m = pattern.search(haystack)
        if m:
            res["problems"].append(
                f"probe is a build/test-runner/search command ({m.group(0)!r}), not a "
                "runtime probe — it proves the code was written or that a suite is "
                "green, never that the running system emits this")
            break

    if args.surface and res["surface"] and args.surface.lower() != res["surface"].lower():
        res["problems"].append(
            f"surface {res['surface']!r} does not match the required {args.surface!r}")

    # Forbidden hosts: a capture taken against shared dev/staging proves
    # nothing about local. Scanned across the location-bearing fields.
    location = " ".join(filter(None, (
        fields.get("base url"), fields.get("environment"),
        fields.get("device"), fields.get("openapi"))))
    for pattern in args.forbid_host:
        if pattern.lower() in location.lower():
            res["problems"].append(
                f"names forbidden host {pattern!r} — this capture did not "
                "observe the local environment")

    if args.require_build_marker:
        if not res["build_marker"]:
            res["problems"].append(
                "--require-build-marker set but the capture records no 'Build marker'")
        elif args.require_build_marker not in res["build_marker"]:
            res["problems"].append(
                f"build marker {res['build_marker']!r} does not contain the "
                f"expected {args.require_build_marker!r} — the process that "
                "answered may not be running the built code")

    if not captured.strip():
        res["problems"].append("captured output is empty")

    if args.expect_status is not None:
        m = STATUS_LINE_RE.search(captured)
        res["status"] = int(m.group(1)) if m else None
        if res["status"] is None:
            res["problems"].append(
                f"--expect-status {args.expect_status} set but no HTTP status "
                "line found in the captured output")
        elif res["status"] != args.expect_status:
            res["problems"].append(
                f"observed status {res['status']} != expected {args.expect_status}")

    if args.require_key:
        doc, err = extract_body_json(captured)
        if err:
            res["problems"].append(err)
        else:
            res["body_parsed"] = True
            scopes = key_scopes(doc)
            res["body_keys"] = sorted(scopes[0].keys()) if scopes else []
            missing = None
            for scope in scopes:
                gaps = [k for k in args.require_key if k not in scope]
                if not gaps:
                    missing = []
                    break
                if missing is None or len(gaps) < len(missing):
                    missing = gaps
            res["missing_keys"] = missing or []
            if res["missing_keys"]:
                res["problems"].append(
                    "required response keys absent from the captured body: "
                    + ", ".join(res["missing_keys"]))

    if newest_mtime is not None:
        res["fresh"] = resolved.stat().st_mtime >= newest_mtime
        if not res["fresh"]:
            res["problems"].append(
                "capture predates the newest declared changed file — it observed "
                "the system before this change (mtime proxy)")

    return res


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_report(args):
    report = {
        "report": args.report, "milestone": args.milestone,
        "citations": [], "captures": [], "accepted": [], "rejected": [],
        "missing_keys": [], "stale": [], "in_process_transport": [],
        "min_captures": args.min_captures, "warnings": [],
        "result": "ERROR", "error": None,
    }

    report_text = read_text(args.report)
    report["citations"] = collect_citations(report_text)
    newest, warnings = newest_changed_mtime(args.changed_files)
    report["warnings"].extend(warnings)

    if not report["citations"]:
        report["result"] = "FAIL"
        report["warnings"].append(
            "no '**Runtime evidence:**' citation found in the report — a wire, "
            "device or rendered claim with no capture is unproven, not proven")
        return report

    patterns = milestone_token_patterns(args.milestone)
    for candidate in report["citations"]:
        res = evaluate_capture(candidate, args, patterns, newest)
        report["captures"].append(res)
        if not res["milestone_match"]:
            continue  # another milestone's capture; not this gate's business
        if res["problems"]:
            report["rejected"].append(res["path"])
            if res["missing_keys"]:
                report["missing_keys"].extend(res["missing_keys"])
            if res["fresh"] is False:
                report["stale"].append(res["path"])
            if any("IN-PROCESS" in p for p in res["problems"]):
                report["in_process_transport"].append(res["path"])
        else:
            report["accepted"].append(res["path"])

    scoped = [c for c in report["captures"] if c["milestone_match"]]
    if not scoped:
        report["warnings"].append(
            f"{len(report['citations'])} capture(s) cited, none naming milestone "
            f"{args.milestone!r} in its 'Milestone' field")
    report["missing_keys"] = sorted(set(report["missing_keys"]))
    report["result"] = ("PASS" if len(report["accepted"]) >= args.min_captures
                        else "FAIL")
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="check_runtime_evidence.py")
    p.add_argument("--report")
    p.add_argument("--milestone")
    p.add_argument("--changed-files", nargs="*", default=[])
    p.add_argument("--repo", default=".")
    p.add_argument("--surface")
    p.add_argument("--require-key", action="append", default=[])
    p.add_argument("--expect-status", type=int)
    p.add_argument("--forbid-host", action="append", default=[])
    p.add_argument("--require-build-marker")
    p.add_argument("--min-captures", type=int, default=1)
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    missing = [n for n, v in (("--report", args.report),
                              ("--milestone", args.milestone)) if not v]
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

    ENVELOPE = '{"statusCode":200,"isSuccess":true,"data":{"id":1},' \
               '"dataContext":null,"notifications":[]}'
    BARE = '{"id":1,"total":9}'

    def capture(milestone="M3 — Order envelope", transport="out-of-process HTTP",
                probe="curl -sS -i http://localhost:5142/api/orders",
                body=ENVELOPE, status="200 OK", base_url="http://localhost:5142",
                surface="api", extra=(), captured_section=True):
        head = [
            "# Runtime capture: POST /api/orders", "",
            f"- Milestone: {milestone}",
            f"- Surface: {surface}",
            f"- Transport: {transport}",
            f"- Base URL: {base_url}",
            f"- Probe command: `{probe}`",
            "- Captured: 2026-08-12T14:03:11Z",
            "- Exit code: 0",
        ]
        head += list(extra)
        if not captured_section:
            return "\n".join(head) + "\n"
        payload = f"HTTP/1.1 {status}\ncontent-type: application/json\n\n{body}" \
            if status else body
        return "\n".join(head + ["", "## Captured output", "", "```",
                                  payload, "```", ""])

    class Tests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.impl = self.dir / ".docs" / "proj" / "implementation"
            (self.impl / "evidence" / "runtime").mkdir(parents=True)
            self.report = self.impl / "test-report.md"
            self.changed = self.dir / "src" / "Api.cs"
            self.changed.parent.mkdir(parents=True, exist_ok=True)
            self.changed.write_text("// code", encoding="utf-8")

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _write(self, name="m3-orders.md", **kw):
            p = self.impl / "evidence" / "runtime" / name
            p.write_text(capture(**kw), encoding="utf-8")
            self._order(self.changed, p)
            return f"evidence/runtime/{name}"

        def _order(self, older, newer):
            """Synthetic mtimes — never the real clock."""
            os.utime(older, (1000, 1000))
            os.utime(newer, (2000, 2000))

        def _report(self, *cited):
            body = "#Task [1]:\n\n"
            if cited:
                body += "**Runtime evidence:** " + ", ".join(cited) + "\n"
            body += "- FR-4: PASS — EnvelopeTests.cs\n"
            self.report.write_text(body, encoding="utf-8")

        def _args(self, **kw):
            base = dict(report=str(self.report), milestone="M3 — Order envelope",
                        changed_files=[str(self.changed)], repo=str(self.dir),
                        surface=None, require_key=[], expect_status=None,
                        forbid_host=[], require_build_marker=None,
                        min_captures=1, self_test=False)
            base.update(kw)
            return argparse.Namespace(**base)

        # ---- happy path ----

        def test_happy_capture_passes(self):
            self._report(self._write())
            r = build_report(self._args(require_key=["isSuccess", "notifications"],
                                        expect_status=200))
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(len(r["accepted"]), 1)

        # ---- the original bug ----

        def test_missing_envelope_key_fails(self):
            self._report(self._write(body=BARE))
            r = build_report(self._args(require_key=["isSuccess", "notifications"]))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["missing_keys"], ["isSuccess", "notifications"])

        def test_key_nested_one_level_deeper_does_not_pass(self):
            self._report(self._write(body='{"data":{"isSuccess":true,"notifications":[]}}'))
            r = build_report(self._args(require_key=["isSuccess", "notifications"]))
            self.assertEqual(r["result"], "FAIL")

        def test_key_inside_body_scope_passes(self):
            self._report(self._write(body='{"body":{"isSuccess":true,"notifications":[]}}'))
            r = build_report(self._args(require_key=["isSuccess", "notifications"]))
            self.assertEqual(r["result"], "PASS", r)

        # ---- transport honesty ----

        def test_in_process_transport_rejected(self):
            for tell in ("WebApplicationFactory<Program>", "factory.CreateClient()",
                          "TestServer", "supertest(app)", "MockMvc"):
                self._report(self._write(transport=tell))
                r = build_report(self._args())
                self.assertEqual(r["result"], "FAIL", tell)
                self.assertEqual(len(r["in_process_transport"]), 1, tell)

        def test_test_runner_is_not_a_runtime_probe(self):
            """The whole point: a green suite is not an observation."""
            for bad in ("dotnet test --filter Envelope", "npm test", "pytest -k envelope",
                         "go test ./...", "npx jest orders"):
                self._report(self._write(probe=bad))
                r = build_report(self._args())
                self.assertEqual(r["result"], "FAIL", bad)

        def test_build_command_probe_rejected(self):
            for bad in ("dotnet build", "npm run build", "tsc --noEmit",
                         "grep -r isSuccess src/", "msbuild /t:Rebuild"):
                self._report(self._write(probe=bad))
                r = build_report(self._args())
                self.assertEqual(r["result"], "FAIL", bad)

        def test_url_containing_rg_is_not_a_search_command(self):
            """Word boundaries: 'myorg' must not read as ripgrep."""
            self._report(self._write(
                probe="curl -sS -i http://myorg.localhost:5142/api/orders"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS", r)

        def test_status_line_survives_fence_parsing(self):
            """Regression: a `\\s*` fence regex ate the body's first line."""
            self._report(self._write())
            r = build_report(self._args(expect_status=200))
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["captures"][0]["status"], 200)

        # ---- environment honesty ----

        def test_forbidden_host_rejected(self):
            self._report(self._write(base_url="https://api.dev.internal"))
            r = build_report(self._args(forbid_host=["dev.internal"]))
            self.assertEqual(r["result"], "FAIL")

        def test_forbidden_host_in_environment_field_rejected(self):
            self._report(self._write(
                extra=["- Environment: web=http://localhost:5173, crm=https://crm.dev.internal"]))
            r = build_report(self._args(forbid_host=["dev.internal"]))
            self.assertEqual(r["result"], "FAIL")

        def test_build_marker_mismatch_rejected(self):
            self._report(self._write(extra=["- Build marker: 1.4.1+sha.deadbee"]))
            r = build_report(self._args(require_build_marker="sha.9f2c1ab"))
            self.assertEqual(r["result"], "FAIL")

        def test_build_marker_required_but_absent_rejected(self):
            self._report(self._write())
            r = build_report(self._args(require_build_marker="sha.9f2c1ab"))
            self.assertEqual(r["result"], "FAIL")

        # ---- freshness ----

        def test_stale_capture_rejected(self):
            cited = self._write()
            p = self.impl / "evidence" / "runtime" / "m3-orders.md"
            self._order(p, self.changed)   # capture older than the diff
            self._report(cited)
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["stale"], [cited])

        # ---- provenance ----

        def test_evidence_build_dir_does_not_gate(self):
            p = self.impl / "evidence" / "build"
            p.mkdir(parents=True, exist_ok=True)
            (p / "m3.md").write_text(capture(), encoding="utf-8")
            self._order(self.changed, p / "m3.md")
            self._report("evidence/build/m3.md")
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")

        def test_parent_traversal_citation_refused(self):
            self.assertFalse(cited_under("../evidence/runtime/x.md", "evidence", "runtime"))
            self.assertTrue(cited_under("evidence/runtime/x.md", "evidence", "runtime"))
            self.assertTrue(cited_under(
                ".docs/proj/implementation/evidence/runtime/x.md", "evidence", "runtime"))
            self.assertTrue(cited_under("evidence\\runtime\\x.md", "evidence", "runtime"))

        def test_missing_file_fails(self):
            self._report("evidence/runtime/nope.md")
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")

        # ---- milestone scoping ----

        def test_other_milestone_capture_is_not_this_gates_business(self):
            self._report(self._write(name="m10.md", milestone="M10 — Something else"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")   # nothing accepted for M3
            self.assertEqual(r["rejected"], [])     # but not rejected either
            self.assertTrue(any("none naming milestone" in w for w in r["warnings"]))

        def test_m1_does_not_match_m10(self):
            self._report(self._write(name="m10.md", milestone="M10 — Other"))
            r = build_report(self._args(milestone="M1"))
            self.assertEqual(r["accepted"], [])

        # ---- report-level ----

        def test_no_citation_fails(self):
            self._report()
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(any("no '**Runtime evidence:**'" in w for w in r["warnings"]))

        def test_capture_without_output_section_is_exit_2(self):
            name = "broken.md"
            p = self.impl / "evidence" / "runtime" / name
            p.write_text(capture(captured_section=False), encoding="utf-8")
            self._order(self.changed, p)
            self._report(f"evidence/runtime/{name}")
            with self.assertRaises(GateError):
                build_report(self._args())

        def test_empty_captured_output_fails(self):
            self._report(self._write(body="", status=None))
            r = build_report(self._args())
            self.assertEqual(r["result"], "FAIL")

        def test_status_mismatch_fails(self):
            self._report(self._write(status="500 Internal Server Error"))
            r = build_report(self._args(expect_status=200))
            self.assertEqual(r["result"], "FAIL")

        def test_min_captures_enforced(self):
            self._report(self._write())
            r = build_report(self._args(min_captures=2))
            self.assertEqual(r["result"], "FAIL")

        def test_missing_report_is_exit_2(self):
            with self.assertRaises(GateError):
                build_report(self._args(report=str(self.dir / "nope.md")))

        # ---- CLI ----

        def test_usage_error_exits_2(self):
            self.assertEqual(main(["--milestone", "M3"]), 2)
            self.assertEqual(main(["--report", str(self.report)]), 2)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
