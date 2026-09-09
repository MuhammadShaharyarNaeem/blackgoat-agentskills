#!/usr/bin/env python3
"""Mechanical GO/NO-GO gate for ship-decision.md.

Makes Dep's shipping verdict machine-verifiable the same way
check_agent_report.py gates Vera/Cipher: one unambiguous labeled
GO or NO-GO in the latest verdict-bearing section (last-section-wins,
so an appended fix round can supersede an earlier verdict), plus a
Rollback heading and a post-deploy checklist section.
Matches the dep-ship-decision-shape eval contract on the shape a
single-shot decision must have; the two deliberately differ on
multi-section documents, which that eval never produces (its
grade.ps1 counts verdicts file-wide, this gate scopes to the latest
section so a pipeline fix round can converge). Note that criterion 5
there — and therefore this gate — accepts a heading containing
"Checklist" OR three-plus checkbox items; a checklist heading with
no items under it passes.

Two opt-in flags convert the two assertions a heading match never proved
(convention #9):

  --require-rehearsal  a `/rollback/` heading asserts a PLAN; it does not
        assert that anyone ever reverted anything. The decision must carry a
        `Time to Rollback:` line naming a timed, dated, environment-named
        rehearsal and citing the capture that recorded it, and that capture
        must carry a run_quiet.py provenance sidecar whose probe exited 0 and
        which AGREES with the capture's own header lines (`exit_code` =
        `- Exit code:`, `finished` = `- Captured:`) -- the hash protects the
        capture file and nothing protects the sidecar, so flipping a failed
        rehearsal's exit_code to 0 passed every other check here
        (`sidecar_body_disagrees` / `capture_header_missing`).
  --require-baseline   the rollout threshold table in
        `shipping-and-launch/SKILL.md` is expressed entirely in deltas
        ("within 10% of baseline", ">2x baseline"), so without a captured
        baseline every one of its rows is unevaluable. The decision must
        carry a `## Baseline` section of at least three evidenced metrics.

Both default OFF: `bgpdd-build` Phase 5 and `bgpdd-shipping` Step 0.4 gate a
PREP decision, which legitimately predates any rehearsal or rollout baseline.

Usage:
    python check_ship_decision.py --report <path> [--require-go]
        [--require-rehearsal] [--require-baseline] [--repo <dir>]
        [--max-rehearsal-age-days <N>] [--ledger <path>]
    python check_ship_decision.py --self-test
"""
import argparse
import hashlib
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

VERDICT_LINE_RE = re.compile(
    r"(?im)^[#>\s\-\*]*(?:Ship\s+Decision|Verdict|Recommendation)\b[^\r\n]*?\b(NO[-\s]?GO|GO)\b"
)
ROLLBACK_HEADING_RE = re.compile(r"(?im)^#{1,6}\s*.*\brollback\b")
CHECKLIST_HEADING_RE = re.compile(r"(?im)^#{1,6}\s*.*\bchecklist\b")
CHECKBOX_RE = re.compile(r"(?m)^\s*[-*]\s*\[[ xX]\]")
HEADING_RE = re.compile(r"(?m)^#{1,6}\s+\S")
LEVELLED_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+\S")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")

# --- the rollback rehearsal line -------------------------------------------
# Grammar (ONE line, leading `#`/`>`/`-`/`*` markers tolerated like the
# verdict line; the two separators accept em dash, en dash or hyphen):
#
#   Time to Rollback: <N><unit> — rehearsed <YYYY-MM-DD> on <env> — evidence: <path>
#
# <N> is a positive number, <unit> one of s/sec(s)/second(s)/m/min(s)/minute(s)
# (normalized to `time_s`), <env> free text naming where it was rehearsed,
# <path> a single whitespace-free token. `<env>` backtracks, so a hyphenated
# environment name (`staging-eu`) parses. This gate records <env>; it does not
# judge it — "non-production" is a producer-side rule in
# `shipping-and-launch/SKILL.md`, unenforceable from a name alone.
REHEARSAL_RE = re.compile(
    r"(?im)^[#>\s\-\*]*Time\s+to\s+Rollback\s*:\s*"
    r"(?P<time>\d+(?:\.\d+)?)\s*"
    r"(?P<unit>seconds|second|secs|sec|minutes|minute|mins|min|s|m)\b"
    r"\s*[—–-]\s*rehearsed\s+(?P<date>\d{4}-\d{2}-\d{2})\s+"
    r"on\s+(?P<env>\S.*?)\s*[—–-]\s*"
    r"evidence\s*:\s*(?P<path>\S+)\s*$"
)
UNIT_SECONDS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
                "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60}
CAPTURED_OUTPUT_RE = re.compile(r"(?im)^#{1,6}\s*Captured\s+output\s*$")

# --- the rollout baseline section ------------------------------------------
BASELINE_HEADING_RE = re.compile(r"(?im)^(?P<hashes>#{2,3})\s*Baseline\b[^\r\n]*$")
METRIC_LINE_RE = re.compile(
    r"(?m)^\s*[-*]\s+(?P<name>[^:\r\n]+?)\s*:\s*(?P<value>\S[^\r\n]*?)\s*$")
PATH_TOKEN_RE = re.compile(r"[^\s,;()\[\]<>\"'`]+")

# --- provenance sidecar ----------------------------------------------------
# run_quiet.py writes `<capture>.meta.json` next to every --capture artifact.
# The rules are check_runtime_evidence.py's, duplicated here per this family's
# no-shared-module convention: a capture with no sidecar was never produced by
# a probe, one whose capture_sha256 no longer matches was edited after the
# fact, and one whose exit_code is non-zero observed nothing.
SIDECAR_SUFFIX = ".meta.json"
DEFAULT_MAX_REHEARSAL_AGE_DAYS = 30


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def positive_int(value):
    """argparse type: a strictly positive integer."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}")
    if n < 1:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {value!r}")
    return n


def read_text(path):
    """Read a UTF-8 artifact, tolerating a byte-order mark."""
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    text = p.read_text(encoding="utf-8-sig", errors="replace")
    if not text.strip():
        raise GateError(f"file is empty: {path}")
    return text


def strip_fenced_blocks(text):
    """Blank out every ```/~~~ fenced region, preserving the line count.

    A `Ship Decision: GO` inside a fenced TEMPLATE block is an example of the
    format, not a decision — but it parsed as one and, being in the last
    verdict-bearing section, won outright.

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


def has_segments(candidate, segments):
    """True when `segments` appear consecutively in the path, with one after.

    A containment scan, not a prefix anchor — a capture is legitimately cited
    report-relative (`evidence/rollback/x.md`) or with its
    `.docs/{project}/implementation/` prefix. Any `..` segment is refused:
    `../evidence/rollback/x.md` must not launder its way past the provenance
    check (the lesson check_runtime_evidence.py's reference records).
    """
    parts = [p for p in candidate.replace("\\", "/").split("/") if p and p != "."]
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


# --- body-vs-sidecar agreement (duplicated from check_runtime_evidence.py) --
# `capture_sha256` protects the capture FILE's bytes; NOTHING protects the
# sidecar's own fields. So the hash-checked body is the witness and the sidecar
# is the claim under test: flipping a rehearsal sidecar's `exit_code` from 1 to
# 0 leaves every hash intact, and a rehearsal that FAILED then reads as one
# that proved the rollback works. `- Captured:` is compared against `finished`,
# which is what run_quiet.py now stamps it FROM; the window is one-sided (never
# EARLIER than `finished`) and two seconds wide solely so a capture from the
# pre-2.4 build path, which re-stamped the header while rendering, is not
# accused of forgery.
CAPTURED_SKEW_SECONDS = 2
SIDECAR_TIMESTAMP_FMT = "%Y-%m-%dT%H:%M:%SZ"
BODY_EXIT_CODE_RE = re.compile(
    r"(?im)^[^\S\n]*-[^\S\n]*Exit[^\S\n]+code[^\S\n]*:[^\S\n]*(-?\d+)[^\S\n]*$")
BODY_CAPTURED_RE = re.compile(
    r"(?im)^[^\S\n]*-[^\S\n]*Captured[^\S\n]*:[^\S\n]*(\S+)[^\S\n]*$")


def capture_header(text):
    """The capture's header: before `## Captured output`, fences blanked.

    Both cuts matter. A rehearsal transcript routinely contains a line like
    `- Exit code: 1`, and a preamble may fence an example header block; either
    would otherwise supply the value meant to witness the sidecar.
    """
    m = CAPTURED_OUTPUT_RE.search(text)
    return strip_fenced_blocks(text[:m.start()] if m else text)


def parse_utc_stamp(raw):
    """A `%Y-%m-%dT%H:%M:%SZ` string as a naive UTC datetime, or None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.strptime(raw.strip(), SIDECAR_TIMESTAMP_FMT)
    except ValueError:
        return None


def sidecar_body_disagreement(text, meta):
    """(problem-code, detail) when the capture's header and sidecar disagree."""
    head = capture_header(text)
    exit_m = BODY_EXIT_CODE_RE.search(head)
    cap_m = BODY_CAPTURED_RE.search(head)
    if exit_m is None or cap_m is None:
        return ("capture_header_missing",
                "the cited rehearsal capture carries no readable "
                "'- Exit code:' and '- Captured:' header pair, so the "
                "sidecar's exit_code and finished stamp cannot be checked "
                "against anything — a capture predating run_quiet.py's header "
                "contract must be re-taken with `run_quiet.py --capture`")
    body_exit = int(exit_m.group(1))
    side_exit = meta.get("exit_code")
    if isinstance(side_exit, int) and side_exit != body_exit:
        return ("sidecar_body_disagrees",
                f"the sidecar records exit_code {side_exit} but the capture's "
                f"own hash-protected body records '- Exit code: {body_exit}' — "
                "the sidecar was edited after the rehearsal (the capture "
                "file's hash still matches, because only the sidecar was "
                "touched)")
    body_dt = parse_utc_stamp(cap_m.group(1))
    if body_dt is None:
        return ("capture_header_missing",
                f"the capture's '- Captured: {cap_m.group(1)}' is not an "
                f"ISO-8601 UTC instant ({SIDECAR_TIMESTAMP_FMT})")
    side_dt = parse_utc_stamp(meta.get("finished"))
    if side_dt is None:
        return ("sidecar_body_disagrees",
                "the sidecar records no parseable 'finished' instant to check "
                f"against the capture's '- Captured: {cap_m.group(1)}'")
    skew = (body_dt - side_dt).total_seconds()
    if not 0 <= skew <= CAPTURED_SKEW_SECONDS:
        return ("sidecar_body_disagrees",
                f"the sidecar records finished {meta.get('finished')!r} but the "
                f"capture's own hash-protected body records '- Captured: "
                f"{cap_m.group(1)}' ({skew:+.0f}s apart; allowed 0.."
                f"{CAPTURED_SKEW_SECONDS}s) — run_quiet.py stamps "
                "'- Captured:' FROM 'finished', so a pair this far apart was "
                "not written by it: either the sidecar's timestamp was edited "
                "or the capture was authored by hand")
    return None, None


def load_sidecar(path):
    """(meta dict or None, reason-when-None). Malformed reads as absent.

    Duplicated from check_runtime_evidence.py per family convention.
    """
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


def ledger_line_hash(raw):
    """sha256 of one ledger LINE's bytes, ignoring its terminator.

    Surrounding whitespace (CR included) is stripped so a ledger written on
    Windows chains identically to the same file read on POSIX. Byte-identical
    in every gate in this family and in check_ledger.py, which verifies the
    chain (family convention: one file each, no shared module).
    """
    return hashlib.sha256(raw.strip()).hexdigest()


def ledger_prev_hash(ledger_path):
    """The `prev` value for the next record: hash of the last line on disk.

    `"genesis"` when the ledger is missing or holds no non-blank line.
    """
    try:
        with open(ledger_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return "genesis"
    last = None
    for raw in data.splitlines():
        if raw.strip():
            last = raw
    return "genesis" if last is None else ledger_line_hash(last)


def ledger_self_hash(record):
    """sha256 of the record serialized canonically WITHOUT its `self` field."""
    body = {k: v for k, v in record.items() if k != "self"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")).hexdigest()


def verify_ledger_chain(ledger_path):
    """(ok, problem|None) — walk the chain and stop at the FIRST broken link.

    `problem` is `{"line", "reason", "detail"}` with reason one of
    `unparseable`, `legacy-after-chained`, `incomplete-chain-fields`,
    `self-mismatch`, `prev-mismatch`, `unreadable`. A missing ledger file is
    NOT a break here (there is no chain to break); callers that require the
    ledger to exist say so themselves.

    Byte-identical in check_ledger.py, check_commit_gate.py and
    mark_milestone.py (family convention: one file each, no shared module).
    """
    p = Path(ledger_path)
    if not p.is_file():
        return True, None
    try:
        data = p.read_bytes()
    except OSError as exc:
        return False, {"line": 0, "reason": "unreadable",
                       "detail": "cannot read {0}: {1}".format(ledger_path, exc)}
    chained_seen = False
    prev_hash = "genesis"
    for lineno, raw in enumerate(data.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            rec = json.loads(raw.decode("utf-8-sig", errors="replace"))
        except ValueError:
            return False, {"line": lineno, "reason": "unparseable",
                           "detail": "line is not parseable JSON"}
        if not isinstance(rec, dict):
            return False, {"line": lineno, "reason": "unparseable",
                           "detail": "line is not a JSON object"}
        has_prev, has_self = "prev" in rec, "self" in rec
        if not has_prev and not has_self:
            if chained_seen:
                return False, {
                    "line": lineno, "reason": "legacy-after-chained",
                    "detail": "an unchained record follows a chained one; a "
                              "ledger that has started chaining cannot revert "
                              "to unchained"}
            prev_hash = ledger_line_hash(raw)
            continue
        if not (has_prev and has_self):
            return False, {
                "line": lineno, "reason": "incomplete-chain-fields",
                "detail": "record carries only one of `prev`/`self`; a chained "
                          "record carries both"}
        if rec.get("self") != ledger_self_hash(rec):
            return False, {
                "line": lineno, "reason": "self-mismatch",
                "detail": "`self` does not hash this record's own content — "
                          "the line was edited after it was written"}
        if rec.get("prev") != prev_hash:
            return False, {
                "line": lineno, "reason": "prev-mismatch",
                "detail": "`prev` is {0} but the preceding record hashes to "
                          "{1} — a record was inserted, removed or edited "
                          "before this line".format(
                              str(rec.get("prev"))[:16], prev_hash[:16])}
        chained_seen = True
        prev_hash = ledger_line_hash(raw)
    return True, None


def read_ledger(ledger_path):
    """Every parseable JSON-object line of the ledger, in file order.

    Duplicated from check_commit_gate.py by family convention (stdlib-only,
    one file each, no shared module).
    """
    p = Path(ledger_path)
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


def check_ledger_gates(ledger_path, gate_names, milestone):
    """Verify each named gate LAST recorded a PASS still standing on its inputs.

    Same three checks as check_commit_gate.py's `--require-ledger-gates` --
    intact chain, latest entry PASS, every recorded input still hashing -- with
    ONE deliberate divergence (CLAUDE.md convention #8), looser on purpose:

      * the commit gate is per-milestone, so it accepts only entries scoped to
        that milestone or unscoped. The ship decision is EPIC-scoped. With no
        `--milestone`, EVERY entry for the named gate is a candidate, whatever
        milestone it carries. That is the point of the flag: `check_coverage.py`
        and `check_acceptance_suite.py` run once for the epic, and binding an
        epic verdict to a per-milestone lookup is the deadlock the audit found.
      * with `--milestone M`, it narrows to the commit gate's rule (M or
        unscoped), for a shipping run that legitimately scopes to one unit.

    Returns [{"gate", "problem", "detail"}]. Codes: `ledger_chain_broken`,
    `ledger_missing`, `ledger_failed`, `ledger_stale`.
    """
    chain_ok, chain = verify_ledger_chain(ledger_path)
    if not chain_ok:
        return [{
            "gate": ledger_path, "problem": "ledger_chain_broken",
            "detail": "the gate ledger's hash chain is broken at line "
                      "{0} ({1}): {2}. Every verdict it records is "
                      "unverifiable until the break is explained; run "
                      "check_ledger.py --ledger {3}".format(
                          chain["line"], chain["reason"], chain["detail"],
                          ledger_path)}]
    records = read_ledger(ledger_path)
    problems = []
    for name in gate_names:
        candidates = [r for r in records
                      if r.get("gate") == name
                      and (milestone is None
                           or r.get("milestone") is None
                           or r.get("milestone") == milestone)]
        if not candidates:
            scope = ("(any milestone)" if milestone is None
                     else "scoped to {0!r} (or unscoped)".format(milestone))
            problems.append({
                "gate": name, "problem": "ledger_missing",
                "detail": "no ledger entry for {0} {1} in {2}".format(
                    name, scope, ledger_path)})
            continue
        latest = candidates[-1]
        if latest.get("verdict") != "PASS":
            problems.append({
                "gate": name, "problem": "ledger_failed",
                "detail": "the latest {0} ledger entry records verdict {1!r} "
                          "(exit {2})".format(name, latest.get("verdict"),
                                              latest.get("exit"))})
            continue
        stale = []
        for path, recorded in (latest.get("inputs") or {}).items():
            if recorded is None:
                continue  # nothing was hashed; there is nothing to compare
            current = sha256_file(path)
            if current is None:
                stale.append("{0} (missing now)".format(path))
            elif current != recorded:
                stale.append("{0} (content changed since that run)".format(path))
        if stale:
            problems.append({
                "gate": name, "problem": "ledger_stale",
                "detail": "the latest {0} ledger entry passed over inputs that "
                          "no longer match on disk: {1}".format(
                              name, ", ".join(stale))})
    return problems


def parse_gate_names(values):
    """Flatten repeated and/or comma-separated --require-ledger-gates values."""
    names = []
    for value in values or []:
        for token in value.split(","):
            token = token.strip()
            if token and token not in names:
                names.append(token)
    return names


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
        record["prev"] = ledger_prev_hash(p)
        record["self"] = ledger_self_hash(record)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


def normalize_verdict(token):
    return re.sub(r"\s+", "-", token.upper())


def split_sections(text):
    """Split on markdown headings; a preamble before the first heading is its own section."""
    starts = [m.start() for m in HEADING_RE.finditer(text)]
    if not starts or starts[0] != 0:
        starts = [0] + starts
    return [text[s:e] for s, e in zip(starts, starts[1:] + [len(text)])]


def parse_verdicts(text):
    """Verdicts from the LAST verdict-bearing section only — last-section-wins.

    Mirrors check_agent_report.py's rule for the same reason: `bgpdd-shipping`
    Step 3 instructs the re-verifying agent to APPEND a fresh section after a
    fix round, so a Round-2 GO must be able to supersede a Round-1 NO-GO.
    Judging ambiguity across the whole file made that document permanently
    unpassable — the only escape was rewriting history.

    Ambiguity is still caught WITHIN the winning section: a decision that says
    both GO and NO-GO in one breath is exactly what this gate exists to reject
    (and what the dep-ship-decision-shape eval's criterion 3 demands).
    """
    bearing = [s for s in split_sections(text) if VERDICT_LINE_RE.search(s)]
    if not bearing:
        return []
    return [normalize_verdict(m.group(1)) for m in VERDICT_LINE_RE.finditer(bearing[-1])]


# ---------------------------------------------------------------------------
# --require-rehearsal: was the rollback ever actually performed?
# ---------------------------------------------------------------------------

def parse_rehearsal(text):
    """The LAST grammar-conforming `Time to Rollback:` line, or None.

    Last-wins for the same reason parse_verdicts is last-section-wins: a fix
    round APPENDS to this document, and a re-run rehearsal after a rollback
    script changed must be able to supersede the earlier one.
    """
    matches = list(REHEARSAL_RE.finditer(text))
    if not matches:
        return None
    m = matches[-1]
    return {"time": float(m.group("time")), "unit": m.group("unit").lower(),
            "date": m.group("date"), "env": m.group("env").strip(),
            "path": m.group("path").strip().strip("`<>\"'")}


def check_rehearsal(text, report_path, repo, max_age_days, today):
    """(rehearsal dict, [(code, detail), ...]) for the --require-rehearsal half."""
    res = {"present": False, "time_s": None, "rehearsed_on": None, "env": None,
           "evidence": None, "sidecar_ok": None, "body_agrees": None,
           "age_days": None}
    parsed = parse_rehearsal(text)
    if parsed is None:
        return res, [("rehearsal_missing",
                      "no `Time to Rollback: <N><unit> — rehearsed <YYYY-MM-DD> "
                      "on <env> — evidence: <path>` line — a Rollback heading "
                      "asserts a plan, not that the revert was ever performed")]
    try:
        rehearsed = datetime.strptime(parsed["date"], "%Y-%m-%d").date()
    except ValueError:
        return res, [("rehearsal_missing",
                      f"`rehearsed {parsed['date']}` is not a real calendar "
                      "date, so the rehearsal line does not satisfy the grammar")]

    res["present"] = True
    res["time_s"] = parsed["time"] * UNIT_SECONDS[parsed["unit"]]
    res["rehearsed_on"] = parsed["date"]
    res["env"] = parsed["env"]
    res["evidence"] = parsed["path"]
    res["age_days"] = (today - rehearsed).days

    problems = []
    if res["age_days"] > max_age_days:
        problems.append((
            "rehearsal_stale",
            f"the rollback was rehearsed {res['age_days']} days ago "
            f"({parsed['date']}), older than the {max_age_days}-day bound — a "
            "revert path drifts with the deploy pipeline it runs against"))

    cited = parsed["path"]
    if not has_segments(cited, ("evidence", "rollback")):
        problems.append((
            "rehearsal_unevidenced",
            f"cited evidence `{cited}` does not resolve under `evidence/rollback/` "
            "(a `..` segment is refused outright)"))
        return res, problems

    resolved = resolve_path(cited, report_path, repo)
    if resolved is None:
        problems.append(("rehearsal_unevidenced",
                         f"cited evidence `{cited}` does not exist relative to "
                         f"the report's directory, --repo, or the working directory"))
        return res, problems

    try:
        capture = resolved.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        problems.append(("rehearsal_unevidenced",
                         f"cited evidence `{cited}` is unreadable: {exc}"))
        return res, problems

    if not capture.strip():
        problems.append(("rehearsal_unevidenced",
                         f"cited evidence `{cited}` is empty"))
    elif not CAPTURED_OUTPUT_RE.search(capture):
        problems.append((
            "rehearsal_unevidenced",
            f"cited evidence `{cited}` has no `## Captured output` section — it "
            "was not written by `run_quiet.py --capture`, so it is prose about a "
            "rehearsal rather than a recording of one"))

    side_path = Path(str(resolved) + SIDECAR_SUFFIX)
    meta, side_error = load_sidecar(side_path)
    if meta is None:
        res["sidecar_ok"] = False
        problems.append((
            "rehearsal_unevidenced",
            f"{side_error} at {side_path.name} — a capture with no run_quiet.py "
            "provenance sidecar is indistinguishable from a hand-typed one"))
        return res, problems

    declared = meta.get("capture_sha256")
    actual = sha256_file(resolved)
    if not (declared and actual and declared == actual):
        res["sidecar_ok"] = False
        problems.append((
            "rehearsal_unevidenced",
            f"the capture's sha256 ({actual}) does not match the sidecar's "
            f"capture_sha256 ({declared}) — the artifact was edited after it was "
            "recorded, so its contents are authored, not observed"))
        return res, problems

    # The hash above protects the capture file, not the sidecar. Compare the
    # two BEFORE trusting the exit code below.
    code, detail = sidecar_body_disagreement(capture, meta)
    res["body_agrees"] = code is None
    if code:
        res["sidecar_ok"] = False
        problems.append((code, detail))
        return res, problems

    exit_code = meta.get("exit_code")
    if not isinstance(exit_code, int):
        res["sidecar_ok"] = False
        problems.append(("rehearsal_failed_exit",
                         "the sidecar records no integer exit_code — the "
                         "rehearsal's outcome was never observed"))
    elif exit_code != 0:
        res["sidecar_ok"] = False
        problems.append((
            "rehearsal_failed_exit",
            f"the rehearsal command exited {exit_code} — a revert-plus-health-check "
            "that failed is a rehearsal that proved the rollback does NOT work, "
            "no matter what its recorded time says"))
    else:
        res["sidecar_ok"] = True
    return res, problems


# ---------------------------------------------------------------------------
# --require-baseline: is the rollout threshold table evaluable at all?
# ---------------------------------------------------------------------------

def baseline_section(text):
    """The body under the first `## Baseline`/`### Baseline` heading, or None."""
    m = BASELINE_HEADING_RE.search(text)
    if not m:
        return None
    level = len(m.group("hashes"))
    for h in LEVELLED_HEADING_RE.finditer(text, m.end()):
        if len(h.group(1)) <= level:
            return text[m.end():h.start()]
    return text[m.end():]


def check_baseline(text, report_path, repo):
    """(baseline dict, [(code, detail), ...]) for the --require-baseline half."""
    res = {"present": False, "metrics": [], "evidenced_count": 0}
    section = baseline_section(text)
    if section is None:
        return res, [("baseline_missing",
                      "no `## Baseline` (or `### Baseline`) section — every row "
                      "of the rollout threshold table is expressed as a delta "
                      "against a baseline, so without one none of them can be "
                      "evaluated at canary time")]
    res["present"] = True

    problems = []
    for m in METRIC_LINE_RE.finditer(section):
        value = m.group("value")
        cited = next((t for t in PATH_TOKEN_RE.findall(value)
                      if has_segments(t, ("evidence", "baseline"))), None)
        entry = {"name": m.group("name").strip(), "value": value,
                 "evidence": cited, "resolved": None}
        if cited is None:
            problems.append((
                "baseline_unevidenced",
                f"baseline metric `{entry['name']}` cites no path under "
                "`evidence/baseline/` — an unevidenced baseline number is the "
                "author's recollection of the dashboard, not a reading of it"))
        else:
            resolved = resolve_path(cited, report_path, repo)
            entry["resolved"] = str(resolved) if resolved else None
            if resolved is None:
                problems.append((
                    "baseline_unevidenced",
                    f"baseline metric `{entry['name']}` cites `{cited}`, which "
                    "does not exist relative to the report's directory, --repo, "
                    "or the working directory"))
            else:
                res["evidenced_count"] += 1
        res["metrics"].append(entry)

    if len(res["metrics"]) < 3:
        problems.append((
            "baseline_missing",
            f"the Baseline section holds {len(res['metrics'])} `- <metric>: "
            "<value>` line(s); at least 3 are required (error rate, p95 latency "
            "and one business metric — the three the threshold table grades)"))
    return res, problems


def build_report(path, require_go, require_rehearsal=False,
                 require_baseline=False, repo=".",
                 max_rehearsal_age_days=DEFAULT_MAX_REHEARSAL_AGE_DAYS,
                 today=None, ledger=None, require_ledger_gates=None,
                 milestone=None):
    # Fences are stripped ONCE, here: the verdict scan, the Rollback heading,
    # the checklist, the rehearsal line and the Baseline section all read a
    # document with no example blocks in it. A `Time to Rollback:` line inside
    # a fenced TEMPLATE is an example of the format, not a rehearsal — the same
    # escape the fenced `Ship Decision: GO` used to take.
    text = strip_fenced_blocks(read_text(path))
    verdicts = parse_verdicts(text)
    distinct = sorted(set(verdicts))
    has_rollback = bool(ROLLBACK_HEADING_RE.search(text))
    checkbox_count = len(CHECKBOX_RE.findall(text))
    has_checklist = bool(CHECKLIST_HEADING_RE.search(text)) or checkbox_count >= 3

    failures = []
    if not verdicts:
        failures.append("no labeled GO/NO-GO verdict line found")
    elif len(distinct) > 1:
        failures.append(
            f"ambiguous verdict - the latest verdict-bearing section states "
            f"both {' and '.join(distinct)}"
        )

    verdict = distinct[0] if len(distinct) == 1 else None
    if require_go and verdict == "NO-GO":
        failures.append("require-go: latest unambiguous verdict is NO-GO")
    if require_go and verdict is None and verdicts:
        failures.append("require-go: no unambiguous GO verdict")
    if not has_rollback:
        failures.append("no Rollback section heading found")
    if not has_checklist:
        failures.append(
            f"no checklist heading and fewer than 3 checkbox items (found {checkbox_count})"
        )

    # The opt-in halves. `problems` carries a machine-readable CODE per finding;
    # `failures` keeps the human string for every finding, old and new, so an
    # existing consumer of this JSON sees the new checks without being changed.
    problems = {}

    def record(code, detail):
        problems.setdefault(code, []).append(detail)
        failures.append(f"{code}: {detail}")

    rehearsal = None
    if require_rehearsal:
        rehearsal, found = check_rehearsal(
            text, path, repo, max_rehearsal_age_days,
            today or datetime.now(timezone.utc).date())
        for code, detail in found:
            record(code, detail)

    baseline = None
    if require_baseline:
        baseline, found = check_baseline(text, path, repo)
        for code, detail in found:
            record(code, detail)

    # The sibling-gate binding. `check_coverage.py` and
    # `check_acceptance_suite.py` are epic-scoped and record `milestone: null`,
    # so this is the gate their PASS binds to -- the per-milestone commit gate
    # cannot hold an epic verdict.
    ledger_gate_problems = []
    if require_ledger_gates:
        ledger_gate_problems = check_ledger_gates(
            ledger, require_ledger_gates, milestone)
        for problem in ledger_gate_problems:
            record(problem["problem"], problem["detail"])

    return {
        "report_file": path,
        "milestone": milestone,
        "ledger": ledger,
        "require_ledger_gates": list(require_ledger_gates or []),
        "ledger_gate_problems": ledger_gate_problems,
        "ledger_gates_ok": not ledger_gate_problems,
        "pass": len(failures) == 0,
        "verdict": verdict,
        "require_go": require_go,
        "has_rollback": has_rollback,
        "has_checklist": has_checklist,
        "checkbox_count": checkbox_count,
        "require_rehearsal": require_rehearsal,
        "rehearsal": rehearsal,
        "require_baseline": require_baseline,
        "baseline": baseline,
        "max_rehearsal_age_days": max_rehearsal_age_days,
        "problems": problems,
        "failures": failures,
        "error": None,
    }


def main(argv):
    parser = argparse.ArgumentParser(prog="check_ship_decision.py")
    parser.add_argument("--report")
    parser.add_argument(
        "--require-go",
        action="store_true",
        help="fail unless the unambiguous verdict is GO",
    )
    parser.add_argument(
        "--require-rehearsal",
        action="store_true",
        help="fail unless a grammar-conforming `Time to Rollback:` line cites a "
             "sidecar-backed rehearsal capture under evidence/rollback/",
    )
    parser.add_argument(
        "--require-baseline",
        action="store_true",
        help="fail unless a `## Baseline` section holds 3+ metric lines, each "
             "citing an existing path under evidence/baseline/",
    )
    parser.add_argument("--repo", default=".",
                        help="root the cited evidence paths resolve against "
                             "(default: the working directory)")
    parser.add_argument("--max-rehearsal-age-days", type=positive_int,
                        default=DEFAULT_MAX_REHEARSAL_AGE_DAYS,
                        help="reject a rehearsal older than this (default 30)")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path; "
                             "also the ledger --require-ledger-gates reads")
    parser.add_argument(
        "--require-ledger-gates", action="append", default=[],
        help="comma-separated gate script names whose LATEST ledger entry "
             "must be PASS over unchanged inputs. EPIC-scoped by default "
             "(any milestone); narrowed to '--milestone or unscoped' when "
             "--milestone is given")
    parser.add_argument(
        "--milestone",
        help="narrow --require-ledger-gates to this milestone (or unscoped) "
             "and record it in this run's ledger line; the ship decision is "
             "epic-scoped, so this is normally omitted")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    args.require_ledger_gates = parse_gate_names(args.require_ledger_gates)

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone,
                      [args.report] if args.report else [], verdict, code)
        return code

    if args.require_ledger_gates and not args.ledger:
        print(json.dumps({"pass": False,
                          "error": "--require-ledger-gates requires --ledger "
                                   "(there is no ledger to read otherwise)"}))
        return finish(2, "ERROR")

    if not args.report:
        print(json.dumps({"pass": False, "error": "missing required argument: --report"}))
        return finish(2, "ERROR")

    try:
        report = build_report(args.report, args.require_go,
                              require_rehearsal=args.require_rehearsal,
                              require_baseline=args.require_baseline,
                              repo=args.repo,
                              max_rehearsal_age_days=args.max_rehearsal_age_days,
                              ledger=args.ledger,
                              require_ledger_gates=args.require_ledger_gates,
                              milestone=args.milestone)
    except GateError as exc:
        print(json.dumps({"pass": False, "error": str(exc)}))
        return finish(2, "ERROR")

    print(json.dumps(report, indent=2))
    return finish(0, "PASS") if report["pass"] else finish(1, "FAIL")


def run_self_test():
    import shutil
    from datetime import date, timedelta

    HAPPY = """# Ship Decision

## Rollback Strategy
Revert the feature flag.

## Launch Checklist
- [ ] Health endpoint 200
- [ ] Auth flow works
- [ ] Logs shipping

Ship Decision: GO
"""

    NO_GO = """# Ship Decision

## Rollback Strategy
Revert.

## Post-deploy Checklist
- [ ] a
- [ ] b
- [ ] c

**Verdict:** NO-GO
"""

    AMBIGUOUS = """# Ship Decision

## Rollback Strategy
x

## Checklist
- [ ] a
- [ ] b
- [ ] c

Ship Decision: GO
Recommendation: NO-GO
"""

    # The bgpdd-shipping Step 3 append pattern: a fix round adds a fresh
    # section rather than rewriting the file.
    APPENDED_FIX = """# Ship Decision

## Rollback Strategy
Revert the feature flag.

## Launch Checklist
- [x] Health endpoint 200
- [x] Auth flow works
- [x] Logs shipping

## Round 1
Ship Decision: NO-GO — production DB_URL was unset.

## Round 2 (after fix)
Ship Decision: GO
"""

    APPENDED_REGRESSION = """# Ship Decision

## Rollback Strategy
Revert.

## Checklist
- [x] a
- [x] b
- [x] c

## Round 1
Verdict: GO

## Round 2 (re-verified after Cipher finding)
Verdict: NO-GO
"""

    TODAY = date(2026, 9, 2)

    def rehearsal_line(when=TODAY, time="4 min", env="staging",
                       path="evidence/rollback/2026-09-02-rehearsal.md",
                       dash="—"):
        return (f"Time to Rollback: {time} {dash} rehearsed {when.isoformat()} "
                f"on {env} {dash} evidence: {path}\n")

    BASELINE = """## Baseline

- Error rate: 0.42% over 24h — evidence: evidence/baseline/error-rate.md
- P95 latency: 184ms — evidence: evidence/baseline/latency.md
- Checkout conversion: 3.1% — evidence: evidence/baseline/conversion.md
"""

    class ShipDecisionTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.path = self.dir / "ship-decision.md"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        # ---- helpers for the rehearsal / baseline halves ----

        def _capture(self, rel="evidence/rollback/2026-09-02-rehearsal.md",
                     body="## Captured output\n\n```\nreverted; health 200\n```\n",
                     sidecar=True, exit_code=0, sidecar_hash=None,
                     finished="2026-09-02T09:00:00Z", body_exit=None,
                     body_captured=None, header=True):
            """A run_quiet.py-shaped capture plus its provenance sidecar.

            The header lines are part of that shape: run_quiet writes the same
            exit code and instant into both records. `body_exit` /
            `body_captured` / `header` override ONLY the capture's header,
            which is how a fixture forges a sidecar whose hash still matches.
            """
            p = self.dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            head = "# Rollback rehearsal\n\n"
            if header:
                head += (
                    "- Probe command: `git revert --no-edit HEAD`\n"
                    "- Captured: {0}\n- Exit code: {1}\n\n".format(
                        body_captured if body_captured is not None else finished,
                        exit_code if body_exit is None else body_exit))
            p.write_text(head + body, encoding="utf-8")
            if sidecar:
                meta = {"argv": ["git", "revert", "--no-edit", "HEAD"],
                        "started": finished, "finished": finished,
                        "exit_code": exit_code, "tool": "run_quiet.py",
                        "capture_sha256": sidecar_hash or sha256_file(p)}
                Path(str(p) + SIDECAR_SUFFIX).write_text(
                    json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            return p

        def _baseline_evidence(self):
            for name in ("error-rate.md", "latency.md", "conversion.md"):
                p = self.dir / "evidence" / "baseline" / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(f"# {name}\n\nread from the monitoring source\n",
                             encoding="utf-8")

        def _write(self, *extra):
            self.path.write_text(HAPPY + "\n" + "\n".join(extra), encoding="utf-8")

        def _run(self, **kw):
            kw.setdefault("today", TODAY)
            kw.setdefault("repo", str(self.dir))
            return build_report(str(self.path), require_go=True, **kw)

        def test_happy_go_passes(self):
            self.path.write_text(HAPPY, encoding="utf-8")
            report = build_report(str(self.path), require_go=True)
            self.assertTrue(report["pass"])
            self.assertEqual(report["verdict"], "GO")

        def test_no_go_passes_without_require_go(self):
            self.path.write_text(NO_GO, encoding="utf-8")
            report = build_report(str(self.path), require_go=False)
            self.assertTrue(report["pass"])
            self.assertEqual(report["verdict"], "NO-GO")

        def test_no_go_fails_require_go(self):
            self.path.write_text(NO_GO, encoding="utf-8")
            report = build_report(str(self.path), require_go=True)
            self.assertFalse(report["pass"])

        def test_ambiguous_within_one_section_fails(self):
            self.path.write_text(AMBIGUOUS, encoding="utf-8")
            report = build_report(str(self.path), require_go=False)
            self.assertFalse(report["pass"])
            self.assertTrue(any("ambiguous" in f for f in report["failures"]))

        def test_appended_fix_round_supersedes_earlier_no_go(self):
            self.path.write_text(APPENDED_FIX, encoding="utf-8")
            report = build_report(str(self.path), require_go=True)
            self.assertTrue(report["pass"], report["failures"])
            self.assertEqual(report["verdict"], "GO")

        def test_appended_regression_supersedes_earlier_go(self):
            self.path.write_text(APPENDED_REGRESSION, encoding="utf-8")
            report = build_report(str(self.path), require_go=True)
            self.assertFalse(report["pass"])
            self.assertEqual(report["verdict"], "NO-GO")

        def test_missing_rollback_fails(self):
            self.path.write_text(
                "## Checklist\n- [ ] a\n- [ ] b\n- [ ] c\n\nShip Decision: GO\n",
                encoding="utf-8",
            )
            report = build_report(str(self.path), require_go=True)
            self.assertFalse(report["pass"])
            self.assertTrue(any("Rollback" in f for f in report["failures"]))

        def test_empty_file_raises(self):
            self.path.write_text("   \n", encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(str(self.path), require_go=False)

        # ---- fences and encoding ----

        def test_fenced_go_template_does_not_win(self):
            """A `GO` inside a fenced format example is not a decision."""
            self.path.write_text(
                NO_GO + "\nFor the next round, write:\n\n"
                "```markdown\nShip Decision: GO\n```\n", encoding="utf-8")
            report = build_report(str(self.path), require_go=True)
            self.assertEqual(report["verdict"], "NO-GO")
            self.assertFalse(report["pass"])

        def test_fenced_go_only_leaves_no_verdict(self):
            self.path.write_text(
                "# Ship Decision\n\n## Rollback\nx\n\n## Checklist\n"
                "- [ ] a\n- [ ] b\n- [ ] c\n\n"
                "~~~\nShip Decision: GO\n~~~\n", encoding="utf-8")
            report = build_report(str(self.path), require_go=False)
            self.assertIsNone(report["verdict"])
            self.assertFalse(report["pass"])

        def test_strip_fenced_blocks_preserves_line_count(self):
            text = "a\n```\nb\n```\nc\n"
            self.assertEqual(len(strip_fenced_blocks(text).split("\n")),
                             len(text.split("\n")))

        def test_bom_prefixed_decision_still_parses(self):
            self.path.write_bytes(b"\xef\xbb\xbf" + HAPPY.encode("utf-8"))
            report = build_report(str(self.path), require_go=True)
            self.assertTrue(report["pass"])
            self.assertEqual(report["verdict"], "GO")

        # ---- --require-rehearsal ----

        def test_rehearsal_happy_passes(self):
            self._capture()
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertTrue(report["pass"], report["failures"])
            self.assertEqual(report["rehearsal"]["time_s"], 240.0)
            self.assertEqual(report["rehearsal"]["env"], "staging")
            self.assertEqual(report["rehearsal"]["age_days"], 0)
            self.assertTrue(report["rehearsal"]["sidecar_ok"])
            self.assertEqual(report["problems"], {})

        def test_rehearsal_not_checked_when_flag_is_off(self):
            """The prep decision at build Phase 5 has no rehearsal, and must pass."""
            self._write()
            report = self._run()
            self.assertTrue(report["pass"], report["failures"])
            self.assertIsNone(report["rehearsal"])
            self.assertFalse(report["require_rehearsal"])

        def test_rehearsal_missing_line_fails(self):
            self._write()
            report = self._run(require_rehearsal=True)
            self.assertFalse(report["pass"])
            self.assertIn("rehearsal_missing", report["problems"])
            self.assertFalse(report["rehearsal"]["present"])

        def test_rollback_heading_alone_does_not_satisfy_rehearsal(self):
            """HAPPY already has `## Rollback Strategy` — a plan, not a rehearsal."""
            self._write()
            report = self._run(require_rehearsal=True)
            self.assertTrue(report["has_rollback"])
            self.assertIn("rehearsal_missing", report["problems"])

        def test_rehearsal_evidence_outside_rollback_dir_fails(self):
            self._capture(rel="evidence/runtime/x.md")
            self._write(rehearsal_line(path="evidence/runtime/x.md"))
            report = self._run(require_rehearsal=True)
            self.assertFalse(report["pass"])
            self.assertIn("rehearsal_unevidenced", report["problems"])

        def test_rehearsal_evidence_with_dotdot_segment_is_refused(self):
            self._capture()
            self._write(rehearsal_line(
                path="../evidence/rollback/2026-09-02-rehearsal.md"))
            report = self._run(require_rehearsal=True)
            self.assertIn("rehearsal_unevidenced", report["problems"])

        def test_rehearsal_evidence_file_absent_fails(self):
            self._write(rehearsal_line(path="evidence/rollback/nope.md"))
            report = self._run(require_rehearsal=True)
            self.assertIn("rehearsal_unevidenced", report["problems"])

        def test_rehearsal_evidence_empty_file_fails(self):
            p = self.dir / "evidence" / "rollback" / "2026-09-02-rehearsal.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("   \n", encoding="utf-8")
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertIn("rehearsal_unevidenced", report["problems"])

        def test_rehearsal_capture_without_captured_output_fails(self):
            self._capture(body="I reverted it and it took four minutes.\n")
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertFalse(report["pass"])
            self.assertTrue(any("Captured output" in d for d
                                in report["problems"]["rehearsal_unevidenced"]))

        def test_rehearsal_capture_without_sidecar_fails(self):
            self._capture(sidecar=False)
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertIn("rehearsal_unevidenced", report["problems"])
            self.assertFalse(report["rehearsal"]["sidecar_ok"])

        def test_rehearsal_capture_edited_after_recording_fails(self):
            self._capture(sidecar_hash="0" * 64)
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertTrue(any("capture_sha256" in d for d
                                in report["problems"]["rehearsal_unevidenced"]))

        def test_rehearsal_nonzero_exit_fails(self):
            self._capture(exit_code=1)
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertFalse(report["pass"])
            self.assertIn("rehearsal_failed_exit", report["problems"])
            self.assertFalse(report["rehearsal"]["sidecar_ok"])

        # ---- the sidecar is the mutable half: it must agree with the body ----

        def test_flipped_sidecar_exit_code_is_caught_by_the_body(self):
            """The attack: a rehearsal that FAILED, sidecar flipped to 0."""
            self._capture(exit_code=0, body_exit=1)
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertFalse(report["pass"])
            self.assertIn("sidecar_body_disagrees", report["problems"])
            self.assertNotIn("rehearsal_unevidenced", report["problems"])
            self.assertFalse(report["rehearsal"]["body_agrees"])

        def test_edited_sidecar_timestamp_is_caught_by_the_body(self):
            self._capture(body_captured="2026-09-02T08:00:00Z")
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertFalse(report["pass"])
            self.assertIn("sidecar_body_disagrees", report["problems"])

        def test_agreeing_pair_records_agreement(self):
            self._capture()
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertTrue(report["rehearsal"]["body_agrees"])
            self.assertTrue(report["rehearsal"]["sidecar_ok"])

        def test_one_second_render_skew_still_passes(self):
            """The pre-2.4 build path stamped `Captured` just after `finished`."""
            self._capture(body_captured="2026-09-02T09:00:01Z")
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertTrue(report["rehearsal"]["body_agrees"])

        def test_capture_without_header_lines_fails_closed(self):
            self._capture(header=False)
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertFalse(report["pass"])
            self.assertIn("capture_header_missing", report["problems"])

        def test_header_lines_inside_the_captured_output_supply_nothing(self):
            """A rehearsal transcript that PRINTS `- Exit code: 1` is not a header."""
            self._capture(body="## Captured output\n\n```\n- Exit code: 1\n"
                                "- Captured: 1999-01-01T00:00:00Z\n```\n")
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertTrue(report["rehearsal"]["body_agrees"], report["problems"])

        def test_rehearsal_non_integer_exit_fails(self):
            self._capture(exit_code="0")
            self._write(rehearsal_line())
            report = self._run(require_rehearsal=True)
            self.assertIn("rehearsal_failed_exit", report["problems"])

        def test_rehearsal_stale_fails(self):
            self._capture()
            self._write(rehearsal_line(when=TODAY - timedelta(days=31)))
            report = self._run(require_rehearsal=True)
            self.assertFalse(report["pass"])
            self.assertIn("rehearsal_stale", report["problems"])
            self.assertEqual(report["rehearsal"]["age_days"], 31)

        def test_rehearsal_exactly_at_the_age_bound_passes(self):
            self._capture()
            self._write(rehearsal_line(when=TODAY - timedelta(days=30)))
            report = self._run(require_rehearsal=True)
            self.assertTrue(report["pass"], report["failures"])

        def test_rehearsal_age_bound_is_configurable(self):
            self._capture()
            self._write(rehearsal_line(when=TODAY - timedelta(days=10)))
            self.assertIn("rehearsal_stale",
                          self._run(require_rehearsal=True,
                                    max_rehearsal_age_days=7)["problems"])

        def test_rehearsal_accepts_hyphen_and_endash_separators(self):
            for dash in ("-", "–", "—"):
                with self.subTest(dash=dash):
                    self._capture()
                    self._write(rehearsal_line(dash=dash))
                    self.assertTrue(self._run(require_rehearsal=True)["pass"])

        def test_rehearsal_units_normalize_to_seconds(self):
            self._capture()
            for text, want in (("90 sec", 90.0), ("90s", 90.0),
                               ("2 minutes", 120.0), ("2m", 120.0),
                               ("1.5 min", 90.0)):
                with self.subTest(text=text):
                    self._write(rehearsal_line(time=text))
                    self.assertEqual(
                        self._run(require_rehearsal=True)["rehearsal"]["time_s"],
                        want)

        def test_rehearsal_hyphenated_environment_parses(self):
            self._capture()
            self._write(rehearsal_line(env="staging-eu-west-1"))
            report = self._run(require_rehearsal=True)
            self.assertTrue(report["pass"], report["failures"])
            self.assertEqual(report["rehearsal"]["env"], "staging-eu-west-1")

        def test_last_rehearsal_line_supersedes_an_earlier_one(self):
            self._capture()
            self._write(rehearsal_line(when=TODAY - timedelta(days=200)),
                        rehearsal_line())
            self.assertTrue(self._run(require_rehearsal=True)["pass"])

        def test_fenced_rehearsal_template_does_not_count(self):
            self._capture()
            self._write("```markdown", rehearsal_line().rstrip("\n"), "```")
            report = self._run(require_rehearsal=True)
            self.assertIn("rehearsal_missing", report["problems"])

        def test_rehearsal_with_impossible_calendar_date_is_not_a_rehearsal(self):
            self._capture()
            self._write(rehearsal_line(time="4 min").replace(
                TODAY.isoformat(), "2026-02-30"))
            report = self._run(require_rehearsal=True)
            self.assertIn("rehearsal_missing", report["problems"])

        def test_require_rehearsal_on_unreadable_report_exits_2(self):
            self.assertEqual(main(["--report", str(self.dir / "gone.md"),
                                   "--require-rehearsal"]), 2)

        # ---- --require-baseline ----

        def test_baseline_happy_passes(self):
            self._baseline_evidence()
            self._write(BASELINE)
            report = self._run(require_baseline=True)
            self.assertTrue(report["pass"], report["failures"])
            self.assertEqual(report["baseline"]["evidenced_count"], 3)
            self.assertEqual(report["problems"], {})

        def test_baseline_not_checked_when_flag_is_off(self):
            self._write()
            report = self._run()
            self.assertTrue(report["pass"], report["failures"])
            self.assertIsNone(report["baseline"])

        def test_baseline_missing_section_fails(self):
            self._write()
            report = self._run(require_baseline=True)
            self.assertFalse(report["pass"])
            self.assertIn("baseline_missing", report["problems"])
            self.assertFalse(report["baseline"]["present"])

        def test_baseline_with_two_metrics_fails(self):
            self._baseline_evidence()
            self._write("## Baseline\n\n"
                        "- Error rate: 0.42% — evidence: evidence/baseline/error-rate.md\n"
                        "- P95 latency: 184ms — evidence: evidence/baseline/latency.md\n")
            report = self._run(require_baseline=True)
            self.assertIn("baseline_missing", report["problems"])
            self.assertEqual(len(report["baseline"]["metrics"]), 2)

        def test_baseline_metric_without_a_citation_fails(self):
            self._baseline_evidence()
            self._write(BASELINE.replace(
                " — evidence: evidence/baseline/conversion.md", ""))
            report = self._run(require_baseline=True)
            self.assertFalse(report["pass"])
            self.assertIn("baseline_unevidenced", report["problems"])
            self.assertEqual(report["baseline"]["evidenced_count"], 2)

        def test_baseline_citation_to_a_missing_file_fails(self):
            self._baseline_evidence()
            self._write(BASELINE.replace("conversion.md", "gone.md"))
            report = self._run(require_baseline=True)
            self.assertIn("baseline_unevidenced", report["problems"])

        def test_baseline_section_ends_at_the_next_same_level_heading(self):
            """Metrics belonging to a later section must not be counted here."""
            self._baseline_evidence()
            self._write("## Baseline\n\n"
                        "- Error rate: 0.42% — evidence: evidence/baseline/error-rate.md\n"
                        "\n## Monitoring\n\n"
                        "- P95 latency: 184ms — evidence: evidence/baseline/latency.md\n"
                        "- Conversion: 3.1% — evidence: evidence/baseline/conversion.md\n")
            report = self._run(require_baseline=True)
            self.assertEqual(len(report["baseline"]["metrics"]), 1)
            self.assertIn("baseline_missing", report["problems"])

        def test_h3_baseline_heading_is_accepted(self):
            self._baseline_evidence()
            self._write(BASELINE.replace("## Baseline", "### Baseline (pre-rollout)"))
            self.assertTrue(self._run(require_baseline=True)["pass"])

        def test_fenced_baseline_template_does_not_count(self):
            self._baseline_evidence()
            self._write("```markdown", BASELINE.rstrip("\n"), "```")
            report = self._run(require_baseline=True)
            self.assertIn("baseline_missing", report["problems"])

        def test_both_flags_together_pass_on_a_complete_decision(self):
            self._capture()
            self._baseline_evidence()
            self._write(BASELINE, rehearsal_line())
            report = self._run(require_rehearsal=True, require_baseline=True)
            self.assertTrue(report["pass"], report["failures"])
            self.assertEqual(report["verdict"], "GO")

        def test_both_flags_exit_1_through_main(self):
            self._write()
            self.assertEqual(main(["--report", str(self.path), "--require-go",
                                   "--require-rehearsal", "--require-baseline",
                                   "--repo", str(self.dir)]), 1)

        # ---- the shared gate ledger ----

        def _ledger_records(self, path):
            return [json.loads(l) for l in
                    Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]

        def test_ledger_records_every_exit_path(self):
            ledger = self.dir / "logs" / "gates.jsonl"
            self.path.write_text(HAPPY, encoding="utf-8")
            self.assertEqual(main(["--report", str(self.path), "--require-go",
                                   "--ledger", str(ledger)]), 0)
            self.path.write_text(NO_GO, encoding="utf-8")
            self.assertEqual(main(["--report", str(self.path), "--require-go",
                                   "--ledger", str(ledger)]), 1)
            self.assertEqual(main(["--report", str(self.dir / "gone.md"),
                                   "--ledger", str(ledger)]), 2)
            records = self._ledger_records(ledger)
            self.assertEqual([r["verdict"] for r in records],
                             ["PASS", "FAIL", "ERROR"])
            self.assertEqual([r["exit"] for r in records], [0, 1, 2])
            self.assertTrue(all(r["gate"] == "check_ship_decision.py"
                                for r in records))
            self.assertIsNone(records[0]["milestone"])
            # The NO-GO run's recorded hash is the file's CURRENT content —
            # the PASS run's is the earlier revision, which is the point.
            self.assertEqual(records[1]["inputs"][str(self.path)],
                             sha256_file(self.path))
            self.assertNotEqual(records[0]["inputs"][str(self.path)],
                                records[1]["inputs"][str(self.path)])

        # ---- --require-ledger-gates (the epic-scoped sibling binding) ----

        def _gate_record(self, ledger, gate, verdict="PASS", milestone=None,
                         inputs=None, exit_code=0, chained=True):
            """One ledger line, chained exactly as a real gate writes it."""
            rec = {"ts": "2026-09-05T00:00:00Z", "gate": gate, "argv": [],
                   "milestone": milestone,
                   "inputs": inputs if inputs is not None else {},
                   "verdict": verdict, "exit": exit_code}
            if chained:
                rec["prev"] = ledger_prev_hash(ledger)
                rec["self"] = ledger_self_hash(rec)
            ledger.parent.mkdir(parents=True, exist_ok=True)
            with open(ledger, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + chr(10))
            return rec

        def test_require_ledger_gates_passes_on_epic_scoped_records(self):
            """The deadlock the flag exists for: both records are unscoped."""
            ledger = self.dir / "gates.jsonl"
            self._gate_record(ledger, "check_coverage.py")
            self._gate_record(ledger, "check_acceptance_suite.py")
            self.path.write_text(HAPPY, encoding="utf-8")
            r = build_report(str(self.path), require_go=True,
                             ledger=str(ledger),
                             require_ledger_gates=["check_coverage.py",
                                                   "check_acceptance_suite.py"])
            self.assertTrue(r["pass"], r["failures"])
            self.assertEqual(r["ledger_gate_problems"], [])

        def test_require_ledger_gates_accepts_a_record_scoped_to_any_milestone(self):
            """Epic scope: without --milestone, M2's record still counts."""
            ledger = self.dir / "gates.jsonl"
            self._gate_record(ledger, "check_coverage.py", milestone="M2")
            self.path.write_text(HAPPY, encoding="utf-8")
            r = build_report(str(self.path), require_go=True,
                             ledger=str(ledger),
                             require_ledger_gates=["check_coverage.py"])
            self.assertTrue(r["pass"], r["failures"])

        def test_milestone_narrows_to_that_milestone_or_unscoped(self):
            ledger = self.dir / "gates.jsonl"
            self._gate_record(ledger, "check_coverage.py", milestone="M2")
            self.path.write_text(HAPPY, encoding="utf-8")
            r = build_report(str(self.path), require_go=True,
                             ledger=str(ledger), milestone="M7",
                             require_ledger_gates=["check_coverage.py"])
            self.assertFalse(r["pass"])
            self.assertEqual(r["ledger_gate_problems"][0]["problem"],
                             "ledger_missing")
            self.assertIn("ledger_missing", r["problems"])

        def test_require_ledger_gates_missing_entry_blocks(self):
            ledger = self.dir / "gates.jsonl"
            self._gate_record(ledger, "check_coverage.py")
            self.path.write_text(HAPPY, encoding="utf-8")
            r = build_report(str(self.path), require_go=True,
                             ledger=str(ledger),
                             require_ledger_gates=["check_acceptance_suite.py"])
            self.assertFalse(r["pass"])
            self.assertEqual(r["ledger_gate_problems"][0]["problem"],
                             "ledger_missing")

        def test_require_ledger_gates_failed_latest_entry_blocks(self):
            ledger = self.dir / "gates.jsonl"
            self._gate_record(ledger, "check_coverage.py")
            self._gate_record(ledger, "check_coverage.py", verdict="FAIL",
                              exit_code=1)
            self.path.write_text(HAPPY, encoding="utf-8")
            r = build_report(str(self.path), require_go=True,
                             ledger=str(ledger),
                             require_ledger_gates=["check_coverage.py"])
            self.assertFalse(r["pass"])
            self.assertEqual(r["ledger_gate_problems"][0]["problem"],
                             "ledger_failed")

        def test_require_ledger_gates_stale_inputs_block(self):
            """A PASS is evidence only while the file it read is unchanged."""
            ledger = self.dir / "gates.jsonl"
            req = self.dir / "requirements.md"
            req.write_text("FR-1 Must-Have" + chr(10), encoding="utf-8")
            self._gate_record(ledger, "check_coverage.py",
                              inputs={str(req): sha256_file(req)})
            req.write_text("FR-1 Must-Have (edited after that gate ran)" + chr(10),
                           encoding="utf-8")
            self.path.write_text(HAPPY, encoding="utf-8")
            r = build_report(str(self.path), require_go=True,
                             ledger=str(ledger),
                             require_ledger_gates=["check_coverage.py"])
            self.assertFalse(r["pass"])
            self.assertEqual(r["ledger_gate_problems"][0]["problem"],
                             "ledger_stale")

        def test_require_ledger_gates_refuses_a_broken_chain(self):
            ledger = self.dir / "gates.jsonl"
            self._gate_record(ledger, "check_coverage.py")
            self._gate_record(ledger, "check_acceptance_suite.py")
            lines = ledger.read_text(encoding="utf-8").splitlines()
            rec = json.loads(lines[0])
            rec["argv"] = ["tampered"]
            lines[0] = json.dumps(rec)
            ledger.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
            self.path.write_text(HAPPY, encoding="utf-8")
            r = build_report(str(self.path), require_go=True,
                             ledger=str(ledger),
                             require_ledger_gates=["check_coverage.py"])
            self.assertFalse(r["pass"])
            self.assertEqual(r["ledger_gate_problems"][0]["problem"],
                             "ledger_chain_broken")

        def test_require_ledger_gates_without_ledger_is_usage_error(self):
            self.path.write_text(HAPPY, encoding="utf-8")
            self.assertEqual(main(["--report", str(self.path),
                                   "--require-ledger-gates",
                                   "check_coverage.py"]), 2)

        def test_require_ledger_gates_end_to_end_via_main(self):
            ledger = self.dir / "gates.jsonl"
            self._gate_record(ledger, "check_coverage.py")
            self.path.write_text(HAPPY, encoding="utf-8")
            names = "check_coverage.py,check_acceptance_suite.py"
            self.assertEqual(main(["--report", str(self.path), "--require-go",
                                   "--ledger", str(ledger),
                                   "--require-ledger-gates", names]), 1)
            self._gate_record(ledger, "check_acceptance_suite.py")
            self.assertEqual(main(["--report", str(self.path), "--require-go",
                                   "--ledger", str(ledger),
                                   "--require-ledger-gates", names]), 0)

        def test_milestone_is_recorded_in_this_runs_ledger_line(self):
            ledger = self.dir / "gates.jsonl"
            self.path.write_text(HAPPY, encoding="utf-8")
            main(["--report", str(self.path), "--ledger", str(ledger),
                  "--milestone", "M4"])
            self.assertEqual(self._ledger_records(ledger)[-1]["milestone"], "M4")

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ShipDecisionTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
