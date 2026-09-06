#!/usr/bin/env python3
"""Deterministic agent-report gate for the PDD pipelines.

Verifies that a durable agent report (Cipher's security-report.md, Vera's
verification-report.md) actually backs its verdict: the report exists and
is non-empty, its latest verdict-bearing section carries a machine-readable
`**Verdict:** Pass`, every check line cites executed-command evidence (an
exit code AND the capture that recorded the run) or an explicit NOT RUN /
BLOCKED reason, and no Critical finding stands. Fail-closed: a verdict the
evidence does not support never passes.

UNTIL THE CAPTURE TERM EXISTED, THIS GATE READ NOTHING UNFORGEABLE. Every
term above was text an agent types: a wholly invented report whose check
lines carried plausible exit codes passed, and `- Secrets scan: PASS —
`git grep -n secret` — exit 1 — 0 matches` cost exactly as little to write as
to run. So an EXECUTED line (`PASS`/`FAIL`, which must carry an exit code)
must additionally cite a `run_quiet.py --capture` artifact under `evidence/`:

    - <name>: PASS — `<command>` — exit <N> — <counts> — capture: evidence/<dir>/<file>.md

The cited capture must exist, carry its `<capture>.meta.json` provenance
sidecar, still hash to that sidecar's `capture_sha256`, agree with its own
header lines, and record an `exit_code` EQUAL to the one the line claims
(`check_uncaptured` / `check_capture_disagrees`). `NOT RUN` and `BLOCKED`
lines are exempt -- there is no run to capture, and their evidence is the
reason they already carry.

MIGRATION: a report authored under 2.3.0 or earlier fails with
`check_uncaptured`. The fix is to re-run each check through
`run_quiet.py --capture` and cite the artifact; `--allow-uncaptured` waives
the CITATION only (never a cited capture that disagrees) and exists for
grading an archived report from before this contract.

Usage:
    python check_agent_report.py --report <path> [--milestone "<title>"] \
        [--repo <dir>] [--allow-uncaptured] [--ledger <path>]
    python check_agent_report.py --self-test

Pure standard library. See ../SKILL.md for the full contract (JSON shape,
exit codes, parsing rules).
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SECTION_HEADING_RE = re.compile(r"^##\s+(.*)$")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
VERDICT_LINE_RE = re.compile(r"^\s*\*\*Verdict:\*\*(.*)$")
VERDICT_TOKEN_RE = re.compile(r"^\s*(Pass|Fail)\s*$")
CHECK_LINE_RE = re.compile(
    r"^\s*-\s*(?P<name>[^:]+?):\s*(?P<status>PASS|FAIL|BLOCKED|NOT RUN)\b(?P<rest>.*)$")
CRITICAL_FINDING_RE = re.compile(r"^\s*-\s*\*\*Critical\*\*")
EXIT_CODE_RE = re.compile(r"\bexit(?:\s+code)?\s+(-?\d+)\b", re.IGNORECASE)

# --- the check line's capture citation --------------------------------------
# `capture: <path>` appended to an executed check line. The path is bare (no
# backticks required, but tolerated) and ends the token at whitespace or a
# separator, so `— capture: evidence/security/npm-audit.md — 0 high` parses.
CHECK_CAPTURE_RE = re.compile(r"\bcapture:\s*`?([^\s`,;]+)`?", re.IGNORECASE)
SIDECAR_SUFFIX = ".meta.json"

# Body-vs-sidecar agreement, duplicated from check_runtime_evidence.py per
# this family's one-file convention. `capture_sha256` protects the capture
# FILE's bytes and NOTHING protects the sidecar's own fields, so the
# hash-checked body is the witness and the sidecar is the claim under test.
CAPTURED_SKEW_SECONDS = 2
SIDECAR_TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"
CAPTURED_HEADING_RE = re.compile(
    r"(?im)^##[^\S\n]+Captured[^\S\n]+output[^\S\n]*$")
BODY_EXIT_CODE_RE = re.compile(
    r"(?im)^[^\S\n]*-[^\S\n]*Exit[^\S\n]+code[^\S\n]*:[^\S\n]*(-?\d+)[^\S\n]*$")
BODY_CAPTURED_RE = re.compile(
    r"(?im)^[^\S\n]*-[^\S\n]*Captured[^\S\n]*:[^\S\n]*(\S+)[^\S\n]*$")


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_text(path):
    """Read a UTF-8 artifact, tolerating a byte-order mark.

    `utf-8` (not `-sig`) glued a BOM to the first character, so a conforming
    report whose first line was a heading exited 2 ("not a conforming agent
    report") purely because of how its editor saved it.
    """
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding="utf-8-sig", errors="replace")


def strip_fenced_blocks(text):
    """Blank out every ```/~~~ fenced region, preserving the line count.

    A `**Verdict:** Pass` or a `- Secrets scan: PASS — exit 0` inside a fence
    is a TEMPLATE or a pasted transcript, not this round's claim — and because
    the last verdict line in the gated section wins, a pasted example silently
    became the verdict.

    Duplicated per file: this script family has no shared module by convention.
    """
    out, fence = [], None
    for line in text.split("\n"):
        m = FENCE_RE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
                out.append("")
                continue
            out.append(line)
        else:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            out.append("")
    return "\n".join(out)


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
    """Append ONE JSON line recording this run. Best-effort by design.

    A ledger that cannot be written must never change this gate's verdict —
    the ledger is an audit trail for LATER gates (check_commit_gate.py's
    --require-ledger-gates), not a term in this one.
    """
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


# ---------------------------------------------------------------------------
# The capture a check line cites
# ---------------------------------------------------------------------------

def has_segments(candidate, segments):
    """True when `segments` appear consecutively in the path, with one after.

    A containment scan, not a prefix anchor — a capture is legitimately cited
    report-relative (`evidence/security/x.md`) or with its
    `.docs/{project}/implementation/` prefix. Any `..` segment is refused, so
    `../../elsewhere/evidence/security/x.md` cannot launder its way in.
    """
    parts = [p for p in candidate.replace("\\", "/").split("/")
             if p and p != "."]
    if ".." in parts:
        return False
    want = [s.lower() for s in segments]
    for i in range(len(parts) - len(want)):
        if [p.lower() for p in parts[i:i + len(want)]] == want:
            return True
    return False


def resolve_capture(candidate, report_path, repo):
    """Resolve a cited path against the report's dir, then --repo, then cwd."""
    bases = [Path(report_path).parent]
    if repo:
        bases.append(Path(repo))
    bases.append(Path("."))
    for base in bases:
        p = base / candidate
        if p.is_file():
            return p
    p = Path(candidate)
    return p if p.is_file() else None


def load_sidecar(path):
    """(meta dict or None, reason-when-None). Malformed reads as absent."""
    p = Path(path)
    if not p.is_file():
        return None, "no sidecar file"
    try:
        meta = json.loads(p.read_text(encoding="utf-8-sig", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"sidecar is unreadable or not valid JSON: {exc}"
    if not isinstance(meta, dict):
        return None, "sidecar is not a JSON object"
    return meta, None


def parse_utc_stamp(raw):
    """A `%Y-%m-%dT%H:%M:%SZ` string as a naive UTC datetime, or None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.strptime(raw.strip(), SIDECAR_TIMESTAMP_FMT)
    except ValueError:
        return None


def body_disagreement(text, meta):
    """(detail or None) when a capture's header and its sidecar disagree.

    The header is read from the region BEFORE `## Captured output`, with
    fences blanked: a scanner transcript routinely prints `- Exit code: 0`,
    and that must not supply the value meant to witness the sidecar.
    """
    m = CAPTURED_HEADING_RE.search(text)
    head = strip_fenced_blocks(text[:m.start()] if m else text)
    exit_m = BODY_EXIT_CODE_RE.search(head)
    cap_m = BODY_CAPTURED_RE.search(head)
    if exit_m is None or cap_m is None:
        return ("the capture carries no readable '- Exit code:' and "
                "'- Captured:' header pair, so its sidecar is unwitnessed; "
                "re-take the check with `run_quiet.py --capture`")
    side_exit = meta.get("exit_code")
    if isinstance(side_exit, int) and side_exit != int(exit_m.group(1)):
        return (f"the sidecar records exit_code {side_exit} but the capture's "
                f"own hash-protected body records '- Exit code: "
                f"{exit_m.group(1)}' — the sidecar was edited after the run")
    body_dt = parse_utc_stamp(cap_m.group(1))
    side_dt = parse_utc_stamp(meta.get("finished"))
    if body_dt is None:
        return (f"the capture's '- Captured: {cap_m.group(1)}' is not an "
                f"ISO-8601 UTC instant ({SIDECAR_TIMESTAMP_FMT})")
    if side_dt is None:
        return ("the sidecar records no parseable 'finished' instant to check "
                f"against the capture's '- Captured: {cap_m.group(1)}'")
    skew = (body_dt - side_dt).total_seconds()
    if not 0 <= skew <= CAPTURED_SKEW_SECONDS:
        return (f"the sidecar records finished {meta.get('finished')!r} but "
                f"the capture's own body records '- Captured: "
                f"{cap_m.group(1)}' ({skew:+.0f}s apart; allowed 0.."
                f"{CAPTURED_SKEW_SECONDS}s) — run_quiet.py stamps "
                "'- Captured:' FROM 'finished', so a pair this far apart was "
                "not written by it")
    return None


def check_capture_problem(rest, claimed_exit, report_path, repo, seen=None):
    """(code, detail) for one executed check line's capture citation.

    `seen` collects every capture path (and sidecar) this gate actually READ,
    so the ledger record can hash them and a later
    `check_commit_gate.py --require-ledger-gates check_agent_report.py`
    catches one edited after this gate passed.

    Returns (None, None) when the line cites a capture that exists, carries a
    sidecar it still hashes to, agrees with its own header, and records the
    SAME exit code the line claims. The exit-code equality is the term that
    ties this capture to THIS line: without it one green capture backs every
    line in the report.
    """
    m = CHECK_CAPTURE_RE.search(rest or "")
    if not m:
        return ("check_uncaptured",
                "no `capture: evidence/<dir>/<file>.md` citation — an executed "
                "check line is otherwise entirely typed, so re-run the check "
                "through `run_quiet.py --capture` and cite the artifact")
    cited = m.group(1)
    if not has_segments(cited, ("evidence",)):
        return ("check_uncaptured",
                f"cited capture `{cited}` is not under an `evidence/` directory "
                "(a `..` segment is refused outright)")
    resolved = resolve_capture(cited, report_path, repo)
    if resolved is None:
        return ("check_uncaptured",
                f"cited capture `{cited}` does not exist relative to the "
                "report's directory, --repo, or the working directory")
    if seen is not None:
        for path in (str(resolved), str(resolved) + SIDECAR_SUFFIX):
            if path not in seen:
                seen.append(path)
    try:
        text = resolved.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        return ("check_uncaptured", f"cited capture `{cited}` is unreadable: {exc}")
    if not CAPTURED_HEADING_RE.search(text):
        return ("check_uncaptured",
                f"cited capture `{cited}` has no `## Captured output` section — "
                "it was not written by `run_quiet.py --capture`, so it is prose "
                "about a run rather than a recording of one")

    side_path = Path(str(resolved) + SIDECAR_SUFFIX)
    meta, side_error = load_sidecar(side_path)
    if meta is None:
        return ("check_capture_disagrees",
                f"{side_error} at {side_path.name} — a capture with no "
                "run_quiet.py provenance sidecar is indistinguishable from a "
                "hand-typed one")
    declared, actual = meta.get("capture_sha256"), sha256_file(resolved)
    if not (declared and actual and declared == actual):
        return ("check_capture_disagrees",
                f"the capture's sha256 ({actual}) does not match its sidecar's "
                f"capture_sha256 ({declared}) — the artifact was edited after "
                "it was recorded")
    disagreement = body_disagreement(text, meta)
    if disagreement:
        return "check_capture_disagrees", disagreement
    side_exit = meta.get("exit_code")
    if not isinstance(side_exit, int):
        return ("check_capture_disagrees",
                "the sidecar records no integer exit_code — the check's "
                "outcome was never observed")
    if claimed_exit is None:
        return ("check_capture_disagrees",
                "the line claims no readable exit code to compare against the "
                f"capture's recorded exit_code {side_exit}")
    if side_exit != claimed_exit:
        return ("check_capture_disagrees",
                f"the line claims exit {claimed_exit} but the cited capture "
                f"recorded exit_code {side_exit} — the citation points at a "
                "different run than the one the line reports")
    return None, None


def parse_sections(text):
    """Return every level-2 ('## ') section as (title, [body lines]).

    Text before the first level-2 heading (a document title, preamble) belongs
    to no section and is never gated.
    """
    sections = []
    current = None
    for line in text.splitlines():
        m = SECTION_HEADING_RE.match(line)
        if m:
            current = (m.group(1).strip(), [])
            sections.append(current)
        elif current is not None:
            current[1].append(line)
    return sections


def find_gated_section(text):
    """Return (title, body) of the LAST section containing a Verdict line.

    Each audit/verification round appends a fresh section, so the last
    verdict-bearing section is the current round — the same last-matching-
    section rule check_commit_gate.py uses for review sections.
    """
    gated = None
    for title, body in parse_sections(text):
        if any(VERDICT_LINE_RE.match(l) for l in body):
            gated = (title, body)
    return gated


def parse_checks(body):
    """Return the section's check lines, deduplicated by name (latest wins).

    A check line is `- <name>: <STATUS> <rest>` where <name> contains no
    colon and <STATUS> is exactly PASS, FAIL, BLOCKED, or NOT RUN (uppercase)
    immediately after the first colon. Anything else is prose and ignored.
    Latest mention per name wins, mirroring the coverage-ledger convention.
    """
    checks = {}
    order = []
    for line in body:
        m = CHECK_LINE_RE.match(line)
        if not m:
            continue
        name = m.group("name").strip().strip("*").strip()
        key = name.lower()
        if key not in checks:
            order.append(key)
        checks[key] = (name, m.group("status"), m.group("rest"))
    return [checks[k] for k in order]


def build_report(args):
    report = {
        "report": args.report,
        "section": None,
        "verdict": None,
        "checks": 0,
        "passed": 0,
        "failed": [],
        "blocked": [],
        "not_run": [],
        "unevidenced": [],
        "uncaptured": [],
        "capture_disagrees": [],
        "capture_problems": [],
        "capture_inputs": [],
        "allow_uncaptured": bool(getattr(args, "allow_uncaptured", False)),
        "critical_findings": 0,
        "warnings": [],
        "result": "FAIL",
        "error": None,
    }
    repo = getattr(args, "repo", None)
    raw = read_text(args.report)
    if not raw.strip():
        raise GateError(f"report file is empty: {args.report}")
    # Fences are stripped ONCE, here: section splitting, verdict lines, check
    # lines and Critical findings all then read a document with no example
    # blocks in it.
    text = strip_fenced_blocks(raw)

    gated = find_gated_section(text)
    if gated is None:
        raise GateError("no '## ' section containing a '**Verdict:**' line "
                        "found — not a conforming agent report")
    title, body = gated
    report["section"] = title

    verdict_values = [m.group(1) for m in
                      (VERDICT_LINE_RE.match(l) for l in body) if m]
    token = VERDICT_TOKEN_RE.match(verdict_values[-1])
    if not token:
        # Latest expression of intent is unreadable — fail-safe: no verdict.
        report["warnings"].append(
            f"section '{title}': latest Verdict line is not a machine-"
            f"readable token (got: {verdict_values[-1].strip()!r}); "
            "required: 'Pass' or 'Fail' exactly")
    else:
        report["verdict"] = token.group(1)

    for name, status, rest in parse_checks(body):
        if status == "PASS":
            report["passed"] += 1
        elif status == "FAIL":
            report["failed"].append(name)
        elif status == "BLOCKED":
            report["blocked"].append(name)
        else:  # NOT RUN
            report["not_run"].append(name)
        if status in ("PASS", "FAIL"):
            # An executed check cites the command's exit code — the terse
            # proof an execution happened. No exit code = unevidenced.
            exit_m = EXIT_CODE_RE.search(rest)
            if not exit_m:
                report["unevidenced"].append(name)
            # ...and the capture that recorded that run, which is the only
            # term in this gate an agent cannot type.
            code, detail = check_capture_problem(
                rest, int(exit_m.group(1)) if exit_m else None,
                args.report, repo, report["capture_inputs"])
            if code:
                report["capture_problems"].append(
                    {"check": name, "problem": code, "detail": detail})
                if code == "check_uncaptured":
                    report["uncaptured"].append(name)
                else:
                    report["capture_disagrees"].append(name)
        elif not re.search(r"\w", rest):
            # An unexecuted check carries its reason. No reason = unevidenced.
            report["unevidenced"].append(name)
    report["checks"] = (report["passed"] + len(report["failed"])
                        + len(report["blocked"]) + len(report["not_run"]))

    report["critical_findings"] = sum(
        1 for line in body if CRITICAL_FINDING_RE.match(line))

    if report["checks"] == 0:
        report["warnings"].append(
            "no check lines found in the gated section — a report that "
            "proves nothing cannot pass")
    if report["unevidenced"]:
        report["warnings"].append(
            "check line(s) without an exit code (executed checks) or a "
            "reason (NOT RUN/BLOCKED): " + ", ".join(report["unevidenced"]))
    if report["uncaptured"] and report["allow_uncaptured"]:
        report["warnings"].append(
            "CAPTURE CITATIONS WAIVED by --allow-uncaptured for: "
            + ", ".join(report["uncaptured"])
            + " — these lines are entirely typed and nothing here verifies "
              "that the commands ever ran")
    elif report["uncaptured"]:
        report["warnings"].append(
            "executed check line(s) citing no `capture: evidence/<dir>/"
            "<file>.md` artifact: " + ", ".join(report["uncaptured"])
            + " — re-run each through `run_quiet.py --capture` (reports "
              "authored before this contract fail here by design)")
    if report["capture_disagrees"]:
        report["warnings"].append(
            "executed check line(s) whose cited capture does not back them: "
            + ", ".join(report["capture_disagrees"]))
    non_green = report["failed"] + report["blocked"] + report["not_run"]
    if report["verdict"] == "Pass" and non_green:
        report["warnings"].append(
            "verdict 'Pass' contradicts non-passing check line(s) — the "
            "verdict is arithmetic over the lines above it: "
            + ", ".join(non_green))
    if report["verdict"] == "Pass" and report["critical_findings"]:
        report["warnings"].append(
            f"verdict 'Pass' stands over {report['critical_findings']} "
            "Critical finding(s) — 'Pass' is unavailable while a Critical "
            "finding stands")

    gate_ok = (report["verdict"] == "Pass"
               and report["checks"] > 0
               and not non_green
               and not report["unevidenced"]
               # --allow-uncaptured waives the CITATION only; a cited capture
               # that disagrees is never waived (the same split
               # check_runtime_evidence.py's --allow-missing-sidecar applies).
               and not (report["uncaptured"] and not report["allow_uncaptured"])
               and not report["capture_disagrees"]
               and report["critical_findings"] == 0)
    report["result"] = "PASS" if gate_ok else "FAIL"
    return report


def build_parser():
    parser = argparse.ArgumentParser(prog="check_agent_report.py")
    parser.add_argument("--report")
    parser.add_argument("--milestone",
                        help="scope this run's ledger record to a milestone")
    parser.add_argument("--repo", default=".",
                        help="repo root, used to resolve a cited capture path "
                             "that is not relative to the report's directory")
    parser.add_argument(
        "--allow-uncaptured", action="store_true",
        help="waive the `capture:` citation on executed check lines. For "
             "grading a report authored before this contract existed; it "
             "never waives a cited capture that disagrees with its sidecar.")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    if args.allow_uncaptured:
        print("check_agent_report: WARNING — --allow-uncaptured is set. "
              "Executed check lines are accepted with no capture backing "
              "them, so nothing here verifies that any command ran.",
              file=sys.stderr)

    def finish(code, verdict, extra_inputs=()):
        """One exit point: EVERY return path records a ledger line.

        `extra_inputs` are the captures this run actually read, hashed
        alongside the report so a later re-hash catches one edited after
        this gate passed.
        """
        inputs = ([args.report] if args.report else []) + list(extra_inputs)
        append_ledger(args.ledger, argv, args.milestone, inputs, verdict, code)
        return code

    if not args.report:
        print(json.dumps({"result": "ERROR",
                          "error": "missing required argument: --report"}))
        return finish(2, "ERROR")

    try:
        report = build_report(args)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")
    cited = report["capture_inputs"]
    print(json.dumps(report, indent=2))
    passed = report["result"] == "PASS"
    return finish(0 if passed else 1, "PASS" if passed else "FAIL", cited)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil
    import tempfile
    import unittest

    # Every executed check line cites a capture, because that is now the
    # contract. `{c0}` / `{c1}` are filled with paths the fixture writes.
    HAPPY_T = (
        "# Security Report\n\n"
        "## Security Audit: Shipping — 2026-08-11\n\n"
        "- Dependency audit: PASS — `npm audit --audit-level=high` — exit 0 — 0 high, 0 critical — capture: {c0}\n"
        "- Secrets scan: PASS — `git grep -nE \"(api_key|secret)\"` — exit 1 — 0 matches — capture: {c1}\n\n"
        "**Verdict:** Pass\n")
    FAIL_VERDICT_T = (
        "## Security Audit: Shipping\n\n"
        "- Dependency audit: FAIL — `npm audit` — exit 1 — 2 high, 5 moderate — capture: {c1}\n\n"
        "**Verdict:** Fail\n")

    def capture_text(cmd, exit_code, body, captured):
        """run_quiet.py's shape: the header records the SAME exit code and
        instant the sidecar does, so a fixture pair agrees by construction."""
        return (
            "# Runtime capture\n\n"
            f"- Probe command: `{cmd}`\n"
            f"- Captured: {captured}\n"
            f"- Exit code: {exit_code}\n\n"
            f"## Captured output\n\n```\n{body}\n```\n")

    class GateTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.path = self.dir / "security-report.md"
            # exit 0 and exit 1 captures: several fixture lines claim each.
            self.c0 = self._capture("audit.md", 0)
            self.c1 = self._capture("grep.md", 1)
            self.HAPPY = HAPPY_T.format(c0=self.c0, c1=self.c1)
            self.FAIL_VERDICT = FAIL_VERDICT_T.format(c1=self.c1)

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _capture(self, name, exit_code, sidecar=True, hash_ok=True,
                     body_exit=None, body_captured=None, sub="security",
                     header=True):
            """A run_quiet.py-shaped capture + sidecar, cited report-relative.

            `body_*` / `header` override ONLY the capture's header lines,
            which is how a fixture forges a sidecar whose hash still matches.
            """
            rel = f"evidence/{sub}/{name}"
            p = self.dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            finished = "2026-08-11T09:00:00Z"
            if header:
                p.write_text(capture_text(
                    "npm audit --audit-level=high",
                    exit_code if body_exit is None else body_exit,
                    "0 vulnerabilities",
                    finished if body_captured is None else body_captured),
                    encoding="utf-8")
            else:
                p.write_text("# Runtime capture\n\n## Captured output\n\n"
                             "```\n0 vulnerabilities\n```\n", encoding="utf-8")
            if sidecar:
                p.with_name(p.name + SIDECAR_SUFFIX).write_text(json.dumps({
                    "argv": ["npm", "audit"], "cwd": str(self.dir),
                    "started": finished, "finished": finished,
                    "exit_code": exit_code, "body_sha256": "0" * 64,
                    "capture_sha256": (sha256_file(p) if hash_ok
                                       else "f" * 64),
                    "tool": "run_quiet.py", "schema": 1}), encoding="utf-8")
            return rel

        def _args(self, **kw):
            base = dict(report=str(self.path), milestone=None, repo=str(self.dir),
                        allow_uncaptured=False, ledger=None, self_test=False)
            base.update(kw)
            return argparse.Namespace(**base)

        def _run(self, text, **kw):
            self.path.write_text(text, encoding="utf-8")
            return build_report(self._args(**kw))

        def test_happy_path_passes(self):
            r = self._run(self.HAPPY)
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(r["verdict"], "Pass")
            self.assertEqual(r["checks"], 2)
            self.assertEqual(r["passed"], 2)

        def test_fail_verdict_fails(self):
            r = self._run(self.FAIL_VERDICT)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["verdict"], "Fail")
            self.assertEqual(r["failed"], ["Dependency audit"])

        def test_pass_verdict_over_critical_finding_fails(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 "
                f"matches — capture: {self.c1}\n\n"
                "- **Critical** — hardcoded JWT secret — src/auth/token.js:14\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["critical_findings"], 1)

        def test_pass_verdict_over_failing_check_fails(self):
            r = self._run(
                "## Verification: Shipping\n\n"
                "- All tests pass: FAIL — `npm test` — exit 1 — 2 failed, 40 "
                f"passed — capture: {self.c1}\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["failed"], ["All tests pass"])

        def test_not_run_check_blocks_pass(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 "
                f"matches — capture: {self.c1}\n"
                "- Rate limiting: NOT RUN — no staging environment reachable\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["not_run"], ["Rate limiting"])
            self.assertNotIn("Rate limiting", r["unevidenced"])

        def test_blocked_check_blocks_pass(self):
            r = self._run(
                "## Verification: Shipping\n\n"
                "- Accessibility scan: BLOCKED — axe-core not installed and no network\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["blocked"], ["Accessibility scan"])

        def test_executed_check_without_exit_code_is_unevidenced(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — repo looked clean\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["unevidenced"], ["Secrets scan"])

        def test_not_run_without_reason_is_unevidenced(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 "
                f"matches — capture: {self.c1}\n"
                "- Rate limiting: NOT RUN\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["unevidenced"], ["Rate limiting"])

        def test_zero_check_lines_fails(self):
            r = self._run("## Security Audit: Shipping\n\nAll clear.\n\n"
                          "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["checks"], 0)

        def test_last_verdict_bearing_section_wins(self):
            r = self._run(self.FAIL_VERDICT + "\n"
                          + self.HAPPY[self.HAPPY.index("## "):])
            self.assertEqual(r["result"], "PASS")
            self.assertIn("2026-08-11", r["section"])

        def test_nonstandard_verdict_token_fails(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 "
                f"matches — capture: {self.c1}\n\n"
                "**Verdict:** Secure\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertIsNone(r["verdict"])

        def test_latest_verdict_line_in_section_wins(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 "
                f"matches — capture: {self.c1}\n\n"
                "**Verdict:** Pass\n"
                "**Verdict:** LGTM\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertIsNone(r["verdict"])

        def test_duplicate_check_name_latest_wins(self):
            r = self._run(
                "## Verification: Shipping\n\n"
                f"- All tests pass: FAIL — `npm test` — exit 1 — capture: {self.c1}\n"
                f"- All tests pass: PASS — `npm test` — exit 0 — capture: {self.c0}\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(r["checks"], 1)
            self.assertEqual(r["failed"], [])

        def test_lowercase_status_is_prose(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: pass — `git grep -n secret` — exit 1 — 0 "
                f"matches — capture: {self.c1}\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")  # zero parseable checks
            self.assertEqual(r["checks"], 0)

        # ---- fences and encoding ----

        def test_fenced_pass_verdict_does_not_count(self):
            """A pasted TEMPLATE cannot become this round's verdict."""
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 "
                f"matches — capture: {self.c1}\n\n"
                "**Verdict:** Fail\n\n"
                "Next round, use:\n\n"
                "```markdown\n**Verdict:** Pass\n```\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["verdict"], "Fail")

        def test_fenced_check_line_does_not_count(self):
            """A check line inside a transcript fence is not an executed check."""
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "Example of the format:\n\n"
                "~~~\n- Secrets scan: PASS — exit 0 — 0 matches\n~~~\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["checks"], 0)

        def test_fenced_critical_finding_does_not_count(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 "
                f"matches — capture: {self.c1}\n\n"
                "```\n- **Critical** — example finding from the template\n```\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "PASS")
            self.assertEqual(r["critical_findings"], 0)

        def test_strip_fenced_blocks_preserves_line_count(self):
            text = "a\n```\nb\n```\nc\n"
            self.assertEqual(len(strip_fenced_blocks(text).split("\n")),
                             len(text.split("\n")))

        def test_bom_prefixed_report_still_passes(self):
            """utf-8 (not -sig) made a valid BOM-prefixed report exit 2."""
            self.path.write_bytes(b"\xef\xbb\xbf" + self.HAPPY.encode("utf-8"))
            r = build_report(self._args())
            self.assertEqual(r["result"], "PASS")

        # ---- the shared gate ledger ----

        def _ledger_records(self, path):
            return [json.loads(l) for l in
                    Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

        def test_ledger_records_a_pass_run(self):
            self.path.write_text(self.HAPPY, encoding="utf-8")
            ledger = self.dir / "logs" / "gates.jsonl"
            rc = main(["--report", str(self.path), "--milestone", "M3",
                       "--repo", str(self.dir), "--ledger", str(ledger)])
            self.assertEqual(rc, 0)
            rec = self._ledger_records(ledger)[-1]
            self.assertEqual(rec["gate"], "check_agent_report.py")
            self.assertEqual(rec["verdict"], "PASS")
            self.assertEqual(rec["exit"], 0)
            self.assertEqual(rec["milestone"], "M3")
            self.assertEqual(rec["inputs"][str(self.path)],
                             sha256_file(self.path))

        def test_ledger_inputs_carry_every_cited_capture_and_sidecar(self):
            """So --require-ledger-gates re-hashes them at commit time."""
            self.path.write_text(self.HAPPY, encoding="utf-8")
            ledger = self.dir / "gates.jsonl"
            self.assertEqual(main(["--report", str(self.path), "--repo",
                                   str(self.dir), "--ledger", str(ledger)]), 0)
            inputs = self._ledger_records(ledger)[-1]["inputs"]
            for rel in (self.c0, self.c1):
                cap = self.dir / rel
                self.assertEqual(inputs[str(cap)], sha256_file(cap))
                side = Path(str(cap) + SIDECAR_SUFFIX)
                self.assertEqual(inputs[str(side)], sha256_file(side))

        def test_ledger_records_fail_and_error_runs(self):
            ledger = self.dir / "gates.jsonl"
            self.path.write_text(self.FAIL_VERDICT, encoding="utf-8")
            self.assertEqual(main(["--report", str(self.path),
                                   "--ledger", str(ledger)]), 1)
            self.assertEqual(main(["--report", str(self.dir / "absent.md"),
                                   "--ledger", str(ledger)]), 2)
            self.assertEqual(main(["--ledger", str(ledger)]), 2)
            verdicts = [r["verdict"] for r in self._ledger_records(ledger)]
            self.assertEqual(verdicts, ["FAIL", "ERROR", "ERROR"])
            self.assertIsNone(self._ledger_records(ledger)[0]["milestone"])

        def test_missing_file_raises(self):
            with self.assertRaises(GateError):
                build_report(self._args(report=str(self.dir / "absent.md")))

        def test_empty_file_raises(self):
            self.path.write_text("  \n\n", encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(self._args())

        def test_no_verdict_section_raises(self):
            self.path.write_text("# Report\n\n## Notes\n\nprose only\n",
                                 encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(self._args())

        # ---- the capture citation: the one term an agent cannot type ----

        def test_typed_report_with_no_captures_fails_closed(self):
            """The 2.3.0 shape: plausible exit codes, nothing behind them."""
            r = self._run(
                "## Security Audit: Shipping — 2026-08-11\n\n"
                "- Dependency audit: PASS — `npm audit` — exit 0 — 0 high\n"
                "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 matches\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["uncaptured"],
                             ["Dependency audit", "Secrets scan"])
            self.assertEqual(r["unevidenced"], [])   # the exit codes ARE there
            self.assertTrue(all(p["problem"] == "check_uncaptured"
                                for p in r["capture_problems"]))

        def test_allow_uncaptured_waives_the_citation_only(self):
            typed = ("## Security Audit: Shipping\n\n"
                     "- Secrets scan: PASS — `git grep -n secret` — exit 1 — 0 matches\n\n"
                     "**Verdict:** Pass\n")
            r = self._run(typed, allow_uncaptured=True)
            self.assertEqual(r["result"], "PASS")
            self.assertTrue(any("WAIVED" in w for w in r["warnings"]))
            # ...but a cited capture that disagrees is never waived.
            bad = self._capture("flipped.md", 0, body_exit=1)
            r2 = self._run(
                "## Security Audit: Shipping\n\n"
                f"- Secrets scan: PASS — exit 0 — capture: {bad}\n\n"
                "**Verdict:** Pass\n", allow_uncaptured=True)
            self.assertEqual(r2["result"], "FAIL")
            self.assertEqual(r2["capture_disagrees"], ["Secrets scan"])

        def test_not_run_and_blocked_lines_need_no_capture(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                f"- Secrets scan: PASS — exit 1 — capture: {self.c1}\n"
                "- Rate limiting: NOT RUN — no staging environment reachable\n"
                "- Image scan: BLOCKED — trivy not installed, no network\n\n"
                "**Verdict:** Fail\n")
            self.assertEqual(r["uncaptured"], [])
            self.assertEqual(r["capture_problems"], [])

        def test_cited_capture_that_does_not_exist_fails(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — exit 1 — capture: evidence/security/gone.md\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["uncaptured"], ["Secrets scan"])

        def test_citation_outside_evidence_fails(self):
            p = self.dir / "notes" / "scan.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("## Captured output\n\n```\nok\n```\n", encoding="utf-8")
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — exit 1 — capture: notes/scan.md\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["uncaptured"], ["Secrets scan"])

        def test_dot_dot_citation_is_refused(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — exit 1 — capture: "
                "../elsewhere/evidence/security/x.md\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["uncaptured"], ["Secrets scan"])

        def test_cited_capture_without_sidecar_fails(self):
            rel = self._capture("nosidecar.md", 0, sidecar=False)
            r = self._run(
                "## Security Audit: Shipping\n\n"
                f"- Secrets scan: PASS — exit 0 — capture: {rel}\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["capture_disagrees"], ["Secrets scan"])

        def test_cited_capture_edited_after_recording_fails(self):
            rel = self._capture("edited.md", 0, hash_ok=False)
            r = self._run(
                "## Security Audit: Shipping\n\n"
                f"- Secrets scan: PASS — exit 0 — capture: {rel}\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["capture_disagrees"], ["Secrets scan"])

        def test_cited_capture_of_a_different_run_fails(self):
            """One green capture must not back a line claiming another code."""
            r = self._run(
                "## Security Audit: Shipping\n\n"
                f"- Secrets scan: PASS — exit 1 — capture: {self.c0}\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["capture_disagrees"], ["Secrets scan"])
            self.assertIn("different run",
                          r["capture_problems"][0]["detail"])

        def test_cited_capture_with_a_flipped_sidecar_fails(self):
            rel = self._capture("flip.md", 0, body_exit=1)
            r = self._run(
                "## Security Audit: Shipping\n\n"
                f"- Secrets scan: PASS — exit 0 — capture: {rel}\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["capture_disagrees"], ["Secrets scan"])

        def test_cited_capture_without_header_lines_fails(self):
            rel = self._capture("legacy.md", 0, header=False)
            r = self._run(
                "## Security Audit: Shipping\n\n"
                f"- Secrets scan: PASS — exit 0 — capture: {rel}\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["capture_disagrees"], ["Secrets scan"])

        def test_cited_file_that_is_not_a_capture_fails(self):
            p = self.dir / "evidence" / "security" / "prose.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("I ran the scan and it was clean.\n", encoding="utf-8")
            r = self._run(
                "## Security Audit: Shipping\n\n"
                "- Secrets scan: PASS — exit 0 — capture: evidence/security/prose.md\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["uncaptured"], ["Secrets scan"])

        def test_backticked_citation_parses(self):
            r = self._run(
                "## Security Audit: Shipping\n\n"
                f"- Secrets scan: PASS — exit 1 — capture: `{self.c1}`\n\n"
                "**Verdict:** Pass\n")
            self.assertEqual(r["result"], "PASS", r["capture_problems"])

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(GateTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
