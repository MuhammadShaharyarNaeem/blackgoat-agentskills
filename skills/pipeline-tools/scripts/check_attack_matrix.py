#!/usr/bin/env python3
"""Deterministic gate for a security attack-matrix table.

Converts security-and-hardening/SKILL.md's Coverage & Provability prose into
an artifact that has to exist: a markdown table with columns

    Category | Surface | Tier | Preconditions | Planned evidence | Verdict

whose Tier column stays machine-parseable and whose Verdict column obeys
base-persona.md's Evidence Integrity rule (a check whose precondition is
absent is BLOCKED, never PASS) rather than resting on an agent's word.

Two modes, matching the two points in the lane where this table is read:

LINT MODE (`--lint-only`, `bgpdd-secure` Phase 1) — the matrix has just been
authored and no probe has run yet, so `Verdict` is genuinely still blank.
Every verdict-dependent rule below is therefore SUPPRESSED, and this mode
enforces only what a row can already state at authoring time:

  L1. Every row carries all six fields (a placeholder token counts as
      present; a truly empty cell does not).
  L2. `Tier` is a bare token: exactly one of `provable`, `partial`,
      `not agent-testable`.
  L3. A `not agent-testable` row's Planned evidence cites no capture-style
      path (`evidence/...`) beyond a closing source-read citation — a
      category an agent cannot test can never plan an actual probe.
  L4. Every Broken-Access-Control-family row (Broken Access Control, IDOR,
      BOLA, BFLA) declares the two-account precondition in Preconditions.
  L5. The document carries the environment preamble's authorization and
      scope-exclusion block.

RESULTS MODE (default, `bgpdd-secure` Phase 3) — keeps the six matrix-only
rules this gate has always enforced:

  1. Tier is a bare token (L2, repeated here against the now-final table).
  2. Every row carries a Verdict, one of `PASS`, `FAIL`, `BLOCKED`.
  3. A `not agent-testable` row's own Verdict cell is never `PASS`.
  4. A `partial` row names what was not covered, in Planned evidence or
     Preconditions.
  5. A `PASS` row cites a capture path in Planned evidence, resolved and
     verified on disk against `--repo`.
  6. A `provable`/`partial` row has a non-empty Preconditions cell.

...and, whenever `--report <path>` is also given, cross-references that
report (Cipher's `security-report.md`, `check_agent_report.py`'s check-line
grammar) against the matrix:

  7. Every matrix row has a corresponding check line in the report.
  8. A `not agent-testable` row's check line in the REPORT was never closed
     `PASS` either — independent of rule 3, which only reads the matrix's
     own (Orchestrator-authored) Verdict cell.
  9. A row whose Preconditions declare the two-account requirement cites two
     distinct identities in its check line's evidence.

...and, whenever `--require-priority {Critical,Critical+Important}` is also
given (requires `--report`), scans the report's Findings
(`- **<Severity>** — <finding> — <file:line>`, the squad's severity
taxonomy) for one at or above that floor. A qualifying finding is reported
as a failure here too, but under its own rule code — Phase 3 step 4 of the
lane routes that failure class to Phase 4 as a confirmed-vulnerability
finding, never as a defect loop, so a caller distinguishes it from a real
gate defect by rule code alone.

Every violation is reported with its row's Category and source line number;
this gate never stops at the first failure. A missing or malformed table,
report, or bad `--require-priority` token is a structural/usage error
(exit 2), never a traceback.

Pure standard library.

Usage:
    python check_attack_matrix.py --lint-only --matrix <path> [--ledger <path>]
    python check_attack_matrix.py --matrix <path> [--repo <dir>] \
        [--report <path>] [--require-priority Critical|Critical+Important] \
        [--ledger <path>]
    python check_attack_matrix.py --self-test
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TIER_TOKENS = ("provable", "partial", "not agent-testable")
VERDICT_TOKENS = ("PASS", "FAIL", "BLOCKED")
CHECK_STATUS_TOKENS = ("PASS", "FAIL", "BLOCKED", "NOT RUN")
NOT_AGENT_TESTABLE = "not agent-testable"
FINDING_SEVERITIES = ("Critical", "Important", "Suggestion", "Nit", "FYI")

# Priority floors this lane's Phase 0 actually offers the user — a fixed
# two-value choice, unlike the acceptance-matrix's open P0-P3 scale, because
# it scopes REPORT FINDING SEVERITY (the squad's Critical/Important/.../FYI
# taxonomy — `cipher.md` § 4, `check_agent_report.py`'s CRITICAL_FINDING_RE),
# not a per-row token the matrix has no column for.
PRIORITY_FLOORS = {
    "critical": ("Critical",),
    "critical+important": ("Critical", "Important"),
}

# Placeholder values that count as "empty" for a prose cell — same intent as
# check_coverage.py's EMPTY_VALUES, case-folded before comparison.
PLACEHOLDER_VALUES = {"-", "—", "tbd", "n/a", "na"}

# Category text naming the Broken-Access-Control family this lane's Phase 1
# names by example (BOLA/BFLA reuse Broken Access Control's tier).
BAC_FAMILY_KEYWORDS = ("broken access control", "idor", "bola", "bfla")

REQUIRED_COLUMNS = (
    "Category", "Surface", "Tier", "Preconditions", "Planned evidence", "Verdict",
)

TABLE_ROW_RE = re.compile(r"^\s*\|")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|[\s:|-]*\|?\s*$")

# A bare path-like token: allowed charset, ending in a dot-extension. Cheap
# and language-neutral, matching the shape check_runtime_evidence.py already
# uses to spot a cited capture inside prose.
PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+")
# Asymmetric on purpose: a leading "." is a real relative-path prefix
# (`.docs/{project-name}/...` is this plugin's own evidence-path convention)
# and must survive; a trailing "." is prose punctuation (a sentence period
# after the citation) and must not.
PATH_STRIP_LEADING = "`'\"()[]{}<>,;"
PATH_STRIP_TRAILING = "`'\"()[]{}<>,;."

FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")

# `- <name>: PASS|FAIL|BLOCKED|NOT RUN <rest>` — byte-identical to
# check_agent_report.py's CHECK_LINE_RE (this family shares no module, so
# the grammar is duplicated per file, per house convention).
CHECK_LINE_RE = re.compile(
    r"^\s*-\s*(?P<name>[^:]+?):\s*(?P<status>PASS|FAIL|BLOCKED|NOT RUN)\b(?P<rest>.*)$")

# `- **<Severity>** — <finding> — <file:line>` (cipher.md § 4's Findings
# grammar; CRITICAL_FINDING_RE in check_agent_report.py checks only the
# Critical case, this needs every severity to apply a floor).
FINDING_LINE_RE = re.compile(
    r"^\s*-\s*\*\*(Critical|Important|Suggestion|Nit|FYI)\*\*\s*[—-]?\s*(.*)$")

# Two-account precondition wording: "two accounts", "2 accounts", and the
# identity/tenant/user variants the Preconditions cell's own prose uses.
TWO_ACCOUNT_RE = re.compile(
    r"\btwo\b[^.\n]{0,60}\b(accounts?|identities|tenants|users)\b"
    r"|\b2\s+(accounts?|identities|tenants|users)\b",
    re.IGNORECASE,
)

# Identity tokens inside a check line's own text: an email address, or a
# word labelled by "account"/"user"/"identity"/"tenant". Heuristic by
# necessity — the report is prose — so it favors precision (a label or an
# email) over recall.
EMAIL_RE = re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+")
LABELED_IDENTITY_RE = re.compile(
    r"\b(?:account|user|identity|tenant)\b\s*[:#]?\s*([A-Za-z0-9_.+-]{1,40})",
    re.IGNORECASE,
)

# The environment preamble's authorization / scope-exclusion block (Phase 1
# step 3, Phase 0 step 2): two labelled lines, bold and punctuation
# optional. Convention this gate assumes since the lane leaves the exact
# preamble grammar as free-form prose — see check_attack_matrix.py's
# `## check_attack_matrix.py` section in pipeline-tools/SKILL.md.
PREAMBLE_AUTH_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?\**authoriz(?:ation|ed)\**\s*:")
PREAMBLE_SCOPE_RE = re.compile(
    r"(?im)^\s*(?:[-*]\s*)?\**scope\s+exclusions?\**\s*:")


class GateError(Exception):
    """A structural or usage contract failure (exit code 2)."""


def read_text(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding="utf-8-sig", errors="replace")


def strip_fenced_blocks(text):
    """Blank out every ```/~~~ fenced region, preserving the line count.

    Duplicated per file (this family shares no module by convention) from
    check_agent_report.py: an example row or check line inside a fence is a
    template, not this round's claim.
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


def is_placeholder(value):
    """True for empty, whitespace-only, or a placeholder token (case-folded)."""
    stripped = (value or "").strip()
    return not stripped or stripped.lower() in PLACEHOLDER_VALUES


def split_row(line):
    """A markdown table row's cells, stripped, from `| a | b |` shape."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_table(text):
    """Return [(line_number, [cells])] for every data row in the table.

    Raises GateError when the header, separator, or a data row's column
    count does not match the required shape.
    """
    lines = text.split("\n")

    header_idx = None
    for index, line in enumerate(lines):
        if not TABLE_ROW_RE.match(line) or TABLE_SEPARATOR_RE.match(line):
            continue
        cells = split_row(line)
        if len(cells) == len(REQUIRED_COLUMNS) and [
            c.lower() for c in cells
        ] == [c.lower() for c in REQUIRED_COLUMNS]:
            header_idx = index
            break
    if header_idx is None:
        raise GateError(
            "no attack-matrix table found: expected a header row 'Category | "
            "Surface | Tier | Preconditions | Planned evidence | Verdict'"
        )

    sep_idx = header_idx + 1
    if sep_idx >= len(lines) or not TABLE_SEPARATOR_RE.match(lines[sep_idx]):
        raise GateError(
            f"malformed attack-matrix table: no separator row after the "
            f"header at line {header_idx + 1}"
        )

    rows = []
    for index in range(sep_idx + 1, len(lines)):
        line = lines[index]
        if not TABLE_ROW_RE.match(line):
            break
        cells = split_row(line)
        if len(cells) != len(REQUIRED_COLUMNS):
            raise GateError(
                f"malformed attack-matrix table row at line {index + 1}: "
                f"expected {len(REQUIRED_COLUMNS)} columns, found {len(cells)}"
            )
        rows.append((index + 1, cells))

    if not rows:
        raise GateError("attack-matrix table has a header but no data rows")

    return rows


def find_path_candidates(cell_text):
    """Every path-shaped token in a cell, punctuation-trimmed."""
    candidates = []
    for match in PATH_TOKEN_RE.finditer(cell_text or ""):
        token = match.group(0).lstrip(PATH_STRIP_LEADING).rstrip(PATH_STRIP_TRAILING)
        if token:
            candidates.append(token)
    return candidates


def is_evidence_path(candidate):
    """True for a path-shaped token that names an evidence/capture directory."""
    normalized = candidate.replace("\\", "/").lower().lstrip("./")
    return normalized.startswith("evidence/") or "/evidence/" in normalized


def resolve_capture(candidate, repo):
    """Resolve a cited path against --repo, then as given. None if absent."""
    p = Path(repo) / candidate
    if p.is_file():
        return p
    p = Path(candidate)
    return p if p.is_file() else None


def is_bac_family(category):
    """True when Category names the Broken-Access-Control family (Phase 1's
    own example set: Broken Access Control, IDOR, BOLA, BFLA)."""
    cat = (category or "").strip().lower()
    return any(keyword in cat for keyword in BAC_FAMILY_KEYWORDS)


def declares_two_account(preconditions_text):
    """True when Preconditions names the two-account/identity requirement."""
    return bool(TWO_ACCOUNT_RE.search(preconditions_text or ""))


def has_environment_preamble(raw_text):
    """True when both the authorization and scope-exclusion labels are present."""
    stripped = strip_fenced_blocks(raw_text)
    return bool(PREAMBLE_AUTH_RE.search(stripped)) and bool(
        PREAMBLE_SCOPE_RE.search(stripped))


# ---------------------------------------------------------------------------
# Results-mode row rules (the six this gate has always enforced)
# ---------------------------------------------------------------------------

def evaluate_row(line_no, cells, repo):
    """Every rule violation for one data row, as {line, category, rule, detail}."""
    category, _surface, tier_raw, preconditions_raw, planned_raw, verdict_raw = cells
    label = category or f"row {line_no}"
    failures = []

    def fail(rule, detail):
        failures.append({"line": line_no, "category": label, "rule": rule, "detail": detail})

    tier = tier_raw.strip()
    tier_valid = tier in TIER_TOKENS
    if not tier_valid:
        fail(
            "tier-token",
            f"Tier {tier_raw!r} is not a bare token — exactly one of "
            f"{', '.join(TIER_TOKENS)} is required; prose appended to the "
            "token breaks machine parsing",
        )

    verdict = verdict_raw.strip()
    verdict_valid = verdict in VERDICT_TOKENS
    if not verdict_valid:
        fail(
            "verdict-missing",
            f"Verdict {verdict_raw!r} is empty or not one of "
            f"{', '.join(VERDICT_TOKENS)}",
        )

    if tier_valid and tier == NOT_AGENT_TESTABLE and verdict_valid and verdict == "PASS":
        fail(
            "not-agent-testable-pass",
            f"tier '{NOT_AGENT_TESTABLE}' can never carry verdict PASS — "
            "absence of a finding in an untestable category is absence of a "
            "test, not a clean bill of health; use BLOCKED or FAIL",
        )

    if tier_valid and tier == "partial":
        if is_placeholder(planned_raw) and is_placeholder(preconditions_raw):
            fail(
                "partial-uncovered",
                "tier 'partial' names nothing left uncovered — its Planned "
                "evidence or Preconditions cell must be non-empty and not a "
                "placeholder",
            )

    if verdict_valid and verdict == "PASS":
        candidates = find_path_candidates(planned_raw)
        if not candidates:
            fail(
                "pass-uncited",
                "verdict PASS cites no capture path in Planned evidence — a "
                "verdict with no artifact behind it is not evidence",
            )
        elif not any(resolve_capture(c, repo) for c in candidates):
            fail(
                "pass-capture-missing",
                f"verdict PASS cites capture path(s) {candidates} but none "
                f"exist on disk under --repo {repo!r}",
            )

    if tier_valid and tier in ("provable", "partial"):
        if is_placeholder(preconditions_raw):
            fail(
                "precondition-missing",
                f"tier '{tier}' requires a non-empty Preconditions cell "
                "(e.g. the two-account requirement for an IDOR check); a "
                "placeholder does not count",
            )

    return failures


# ---------------------------------------------------------------------------
# Lint-mode row rules (Phase 1 — no Verdict exists yet)
# ---------------------------------------------------------------------------

def evaluate_lint_row(line_no, cells):
    """Every lint-time violation for one data row. No verdict-dependent rule
    fires here — the Verdict column is genuinely still blank at Phase 1."""
    category, _surface, tier_raw, preconditions_raw, planned_raw, verdict_raw = cells
    label = category or f"row {line_no}"
    failures = []

    def fail(rule, detail):
        failures.append({"line": line_no, "category": label, "rule": rule, "detail": detail})

    empty_fields = [
        name for name, value in zip(REQUIRED_COLUMNS, cells) if not (value or "").strip()
    ]
    if empty_fields:
        fail(
            "row-incomplete",
            f"missing field(s): {', '.join(empty_fields)} — every row needs "
            "all six fields at authoring time; a placeholder token is fine, "
            "a bare empty cell is not",
        )

    tier = tier_raw.strip()
    tier_valid = tier in TIER_TOKENS
    if not tier_valid:
        fail(
            "tier-token",
            f"Tier {tier_raw!r} is not a bare token — exactly one of "
            f"{', '.join(TIER_TOKENS)} is required; prose appended to the "
            "token breaks machine parsing",
        )

    if tier_valid and tier == NOT_AGENT_TESTABLE:
        evidence_candidates = [
            c for c in find_path_candidates(planned_raw) if is_evidence_path(c)
        ]
        if evidence_candidates:
            fail(
                "not-agent-testable-evidence",
                f"tier '{NOT_AGENT_TESTABLE}' row's Planned evidence cites "
                f"capture path(s) {evidence_candidates} — a category an "
                "agent cannot test closes on a source-read citation only, "
                "never a planned probe artifact",
            )

    if is_bac_family(category) and not declares_two_account(preconditions_raw):
        fail(
            "bac-precondition-lint",
            f"Broken-Access-Control-family category {category!r} does not "
            "declare the two-account precondition in Preconditions — every "
            "Broken Access Control/IDOR/BOLA/BFLA row needs two accounts at "
            "different privilege levels or tenants",
        )

    return failures


def build_lint_report(matrix_path):
    report = {
        "mode": "lint",
        "matrix_file": matrix_path,
        "rows_checked": 0,
        "failures": [],
        "result": "ERROR",
        "error": None,
    }

    try:
        raw = read_text(matrix_path)
        rows = parse_table(raw)
    except GateError as exc:
        report["error"] = str(exc)
        return report

    failures = []
    for line_no, cells in rows:
        failures.extend(evaluate_lint_row(line_no, cells))

    if not has_environment_preamble(raw):
        failures.append({
            "line": None,
            "category": "<environment preamble>",
            "rule": "preamble-missing",
            "detail": "the environment preamble's authorization and/or "
                      "scope-exclusion block is missing — Phase 0 step 2's "
                      "three confirmations must be recorded verbatim in the "
                      "matrix before Phase 2 runs (labelled `Authorization:` "
                      "and `Scope exclusions:`)",
        })

    report["rows_checked"] = len(rows)
    report["failures"] = failures
    report["result"] = "FAIL" if failures else "PASS"
    return report


def build_report(matrix_path, repo):
    """The six matrix-only rules this gate has always enforced."""
    report = {
        "matrix_file": matrix_path,
        "repo": repo,
        "rows_checked": 0,
        "failures": [],
        "result": "ERROR",
        "error": None,
    }

    try:
        text = read_text(matrix_path)
        rows = parse_table(text)
    except GateError as exc:
        report["error"] = str(exc)
        return report

    failures = []
    for line_no, cells in rows:
        failures.extend(evaluate_row(line_no, cells, repo))

    report["rows_checked"] = len(rows)
    report["failures"] = failures
    report["result"] = "FAIL" if failures else "PASS"
    return report


# ---------------------------------------------------------------------------
# Results-mode report cross-reference (Phase 3, when --report is given)
# ---------------------------------------------------------------------------

def parse_check_lines(report_text):
    """[(name, status, rest)] for every check line in the (fence-stripped) report."""
    checks = []
    for line in report_text.split("\n"):
        m = CHECK_LINE_RE.match(line)
        if m:
            checks.append((m.group("name").strip().strip("*").strip(),
                           m.group("status"), m.group("rest")))
    return checks


def parse_findings(report_text):
    """[(severity, detail)] for every Findings line in the (fence-stripped) report."""
    findings = []
    for line in report_text.split("\n"):
        m = FINDING_LINE_RE.match(line)
        if m:
            findings.append((m.group(1), m.group(2).strip()))
    return findings


def find_check_line(category, surface, checks):
    """The first check line whose name+rest mentions this row's Category
    (and Surface, when it is not a placeholder). None if no line matches."""
    cat = (category or "").strip().lower()
    surf = (surface or "").strip().lower()
    surf_required = surf and not is_placeholder(surface)
    for name, status, rest in checks:
        haystack = f"{name} {rest}".lower()
        if cat and cat in haystack and (not surf_required or surf in haystack):
            return (name, status, rest)
    return None


def extract_identities(text):
    """Distinct identity tokens (case-folded) cited in a check line's text."""
    found = set()
    for m in EMAIL_RE.finditer(text or ""):
        found.add(m.group(0).lower())
    for m in LABELED_IDENTITY_RE.finditer(text or ""):
        token = m.group(1).strip("`'\".,;: ").lower()
        if token:
            found.add(token)
    return found


def parse_priority_floor(value):
    """`Critical` -> {Critical}; `Critical+Important` -> {Critical, Important}."""
    if value is None:
        return None
    key = re.sub(r"\s+", "", value).lower()
    if key not in PRIORITY_FLOORS:
        raise GateError(
            f"--require-priority value {value!r} is not a recognized floor "
            "(expected 'Critical' or 'Critical+Important')"
        )
    return set(PRIORITY_FLOORS[key])


def evaluate_against_report(rows, report_text, priority_floor):
    """Rules 7-9 (always, once --report is given) plus the priority-floor
    finding scan (only when a floor is given). Returns (failures, keys)."""
    failures = []
    checks = parse_check_lines(report_text)

    for line_no, cells in rows:
        category, surface, tier_raw, preconditions_raw, _planned_raw, _verdict_raw = cells
        label = category or f"row {line_no}"
        tier = tier_raw.strip()
        tier_valid = tier in TIER_TOKENS

        matched = find_check_line(category, surface, checks)
        if matched is None:
            failures.append({
                "line": line_no, "category": label, "rule": "row-uncited-in-report",
                "detail": f"no check line in the report matches Category "
                          f"{category!r} / Surface {surface!r} — every matrix "
                          "row needs its own check line",
            })
            continue

        name, status, rest = matched

        if tier_valid and tier == NOT_AGENT_TESTABLE and status == "PASS":
            failures.append({
                "line": line_no, "category": label,
                "rule": "report-not-agent-testable-pass",
                "detail": f"tier '{NOT_AGENT_TESTABLE}' row's report check "
                          f"line {name!r} closed PASS — absence of a finding "
                          "in an untestable category is absence of a test, "
                          "not a clean bill of health",
            })

        if declares_two_account(preconditions_raw):
            identities = extract_identities(f"{name} {rest}")
            if len(identities) < 2:
                failures.append({
                    "line": line_no, "category": label,
                    "rule": "two-account-evidence-missing",
                    "detail": f"Preconditions declares the two-account "
                              f"requirement but report check line {name!r} "
                              f"cites {len(identities)} distinct identity/"
                              "identities — two are required",
                })

    if priority_floor:
        for severity, detail in parse_findings(report_text):
            if severity in priority_floor:
                failures.append({
                    "line": None, "category": "<finding>",
                    "rule": "finding-at-or-above-floor",
                    "detail": f"{severity} finding at or above the required "
                              f"priority floor: {detail}",
                })

    return failures


def build_results_report(matrix_path, repo, report_path, priority_value):
    """Rules 1-6 (matrix-only) plus 7-9 and the priority-floor scan, when
    `report_path` is given. `priority_value` requires `report_path`."""
    report = build_report(matrix_path, repo)
    report["report_file"] = report_path
    report["require_priority"] = None

    if report["result"] == "ERROR":
        return report

    try:
        priority_floor = parse_priority_floor(priority_value)
    except GateError as exc:
        report["result"] = "ERROR"
        report["error"] = str(exc)
        return report
    report["require_priority"] = sorted(priority_floor) if priority_floor else None

    if report_path is None:
        return report

    try:
        raw_report = read_text(report_path)
    except GateError as exc:
        report["result"] = "ERROR"
        report["error"] = str(exc)
        return report
    report_text = strip_fenced_blocks(raw_report)

    try:
        rows = parse_table(read_text(matrix_path))
    except GateError as exc:
        report["result"] = "ERROR"
        report["error"] = str(exc)
        return report

    extra_failures = evaluate_against_report(rows, report_text, priority_floor)
    report["failures"] = report["failures"] + extra_failures
    report["result"] = "FAIL" if report["failures"] else "PASS"
    return report


# ---------------------------------------------------------------------------
# Gate ledger — byte-identical helper across this family (no shared module)
# ---------------------------------------------------------------------------

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


def append_ledger(ledger_path, argv, milestone, inputs, verdict, exit_code):
    """Append ONE JSON line recording this run. Best-effort by design.

    A ledger that cannot be written must never change this gate's verdict —
    the ledger is an audit trail for LATER gates, not a term in this one.
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
        record["prev"] = ledger_prev_hash(p)
        record["self"] = ledger_self_hash(record)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


class PurposeFirstParser(argparse.ArgumentParser):
    """`--help` whose FIRST line is the one-line purpose, then usage/args/epilog.

    argparse prints usage before the description; the registry's
    `description` must equal help line 1 verbatim, so the description is
    lifted out and re-emitted ahead of the standard body.
    """

    def format_help(self):
        purpose = (self.description or "").strip()
        saved, self.description = self.description, None
        try:
            body = super().format_help()
        finally:
            self.description = saved
        return purpose + "\n\n" + body if purpose else body


PURPOSE = ("Decides whether a security attack matrix is well-formed, or "
           "whether its rows were probed and evidenced, for the secure lane.")

EPILOG = """\
Reads:
  --matrix <path>  the attack-matrix markdown file. Its table:
      | Category | Surface | Tier | Preconditions | Planned evidence | Verdict |
    Tier is a bare token: provable | partial | not agent-testable.
    Verdict is PASS | FAIL | BLOCKED (blank at lint time).
    The document also carries an environment preamble naming
    `Authorization:` and `Scope exclusions:`.
  --report <path>  (results mode only) Cipher's security-report.md, read
    under check_agent_report.py's check-line grammar:
      - <name>: PASS|FAIL|BLOCKED|NOT RUN -- `<command>` -- exit <N> -- <counts> -- capture: evidence/<dir>/<file>.md
    and its finding lines, for --require-priority's severity floor.
  --repo <dir>     a Planned-evidence capture path resolves against it
    first, then as given (default '.'; replaces the old --root).

  Modes: --lint-only (Phase 1, before any probe runs, so no verdict-
  dependent rule fires) and results mode (Phase 3, default).

Problem codes:
  Emitted in failures[].rule.
  Lint mode:
  row-incomplete               a row is missing one of the six fields
  tier-token                   Tier is not one bare recognized token
  not-agent-testable-evidence  such a row plans an actual capture probe
  bac-precondition-lint        a BAC/IDOR/BOLA/BFLA row lacks two accounts
  preamble-missing             no Authorization / Scope exclusions block
  Results mode (tier-token repeats against the final table):
  verdict-missing              a row carries no PASS/FAIL/BLOCKED verdict
  not-agent-testable-pass      such a row's own Verdict cell says PASS
  partial-uncovered            a partial row names no gap
  pass-uncited                 a PASS row cites no capture path
  pass-capture-missing         the cited capture is not on disk
  precondition-missing         a provable/partial row has empty Preconditions
  With --report:
  row-uncited-in-report        no check line corresponds to the row
  report-not-agent-testable-pass  its report check line was closed PASS
  two-account-evidence-missing    its check line cites one identity only
  With --require-priority:
  finding-at-or-above-floor    a Finding at or above the given floor stands

JSON keys:
  Always printed on stdout (there is no --json flag):
  mode (lint report only), matrix_file, repo, report_file,
  require_priority (sorted list or null), rows_checked,
  failures ([{line, category, rule, detail}]), result, error

Exit codes:
  0  no rule violation.
  1  any row or finding fails a rule.
  2  missing --matrix, an unreadable matrix or report, no table found, a
     malformed row, --require-priority without --report, or an
     unrecognized --require-priority token.

Self-test:
  python check_attack_matrix.py --self-test   (57 cases)
"""


def build_parser():
    parser = PurposeFirstParser(
        prog="check_attack_matrix.py",
        description=PURPOSE,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--matrix", help="path to the attack-matrix markdown file")
    parser.add_argument(
        "--repo", default=".",
        help="repo root a Planned-evidence capture path resolves against "
             "(default: '.') -- replaces the old --root",
    )
    parser.add_argument(
        "--lint-only", action="store_true",
        help="Phase 1 mode: structural/authoring rules only, no verdict-"
             "dependent rule fires (Verdict is still blank at this point)",
    )
    parser.add_argument(
        "--report",
        help="Cipher's security-report.md -- when given in results mode, "
             "cross-references the matrix's rows against its check lines",
    )
    parser.add_argument(
        "--require-priority",
        help="severity floor, 'Critical' or 'Critical+Important' (results "
             "mode, requires --report): scans the report's Findings for one "
             "at or above this floor",
    )
    parser.add_argument("--ledger", help="append a chained record here (best-effort)")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    def finish(code, verdict, inputs):
        append_ledger(args.ledger, argv, None, inputs, verdict, code)
        return code

    if not args.matrix:
        print(json.dumps({"result": "ERROR", "error": "missing required argument: --matrix"}))
        return finish(2, "ERROR", [])

    if args.lint_only:
        report = build_lint_report(args.matrix)
        inputs = [args.matrix]
    else:
        if args.require_priority and not args.report:
            print(json.dumps({
                "result": "ERROR",
                "error": "--require-priority requires --report (there is no "
                         "Findings section to scan otherwise)",
            }))
            return finish(2, "ERROR", [args.matrix])
        report = build_results_report(args.matrix, args.repo, args.report,
                                      args.require_priority)
        inputs = [args.matrix] + ([args.report] if args.report else [])

    print(json.dumps(report, indent=2))

    if report["result"] == "ERROR":
        return finish(2, "ERROR", inputs)
    if report["result"] == "FAIL":
        return finish(1, "FAIL", inputs)
    return finish(0, "PASS", inputs)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil
    import tempfile
    import unittest

    HEADER = "| Category | Surface | Tier | Preconditions | Planned evidence | Verdict |"
    SEP = "|---|---|---|---|---|---|"

    PREAMBLE = (
        "# Attack matrix\n\n"
        "## Environment preamble\n\n"
        "- Authorization: user confirmed this target is theirs to test\n"
        "- Non-production: staging only, https://staging.example.test\n"
        "- Scope exclusions: /admin/billing, the ops account\n\n"
    )

    def row(category="IDOR", surface="api", tier="provable",
            preconditions="two accounts, different tenants", planned="",
            verdict="BLOCKED"):
        return f"| {category} | {surface} | {tier} | {preconditions} | {planned} | {verdict} |"

    def matrix(*rows, preamble=PREAMBLE):
        return preamble + "\n".join([HEADER, SEP, *rows]) + "\n"

    class Tests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.matrix_path = self.dir / "attack-matrix.md"
            self.report_path = self.dir / "security-report.md"
            evidence_dir = self.dir / "evidence" / "security"
            evidence_dir.mkdir(parents=True)
            self.capture = evidence_dir / "probe-capture.md"
            self.capture.write_text("# capture\n", encoding="utf-8")
            self.capture_rel = "evidence/security/probe-capture.md"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _run(self, *rows, preamble=PREAMBLE):
            self.matrix_path.write_text(matrix(*rows, preamble=preamble), encoding="utf-8")
            return build_report(str(self.matrix_path), str(self.dir))

        def _lint(self, *rows, preamble=PREAMBLE):
            self.matrix_path.write_text(matrix(*rows, preamble=preamble), encoding="utf-8")
            return build_lint_report(str(self.matrix_path))

        def _results(self, *rows, report_text=None, priority=None, preamble=PREAMBLE):
            self.matrix_path.write_text(matrix(*rows, preamble=preamble), encoding="utf-8")
            if report_text is not None:
                self.report_path.write_text(report_text, encoding="utf-8")
            return build_results_report(
                str(self.matrix_path), str(self.dir),
                str(self.report_path) if report_text is not None else None,
                priority)

        def _codes(self, report):
            return [f["rule"] for f in report["failures"]]

        # ---- Rule 1: tier is a bare token ----

        def test_valid_tier_token_passes(self):
            r = self._run(row(tier="provable", verdict="BLOCKED"))
            self.assertNotIn("tier-token", self._codes(r))

        def test_tier_with_appended_prose_fails(self):
            r = self._run(row(tier="provable (mostly)", verdict="BLOCKED"))
            self.assertIn("tier-token", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        def test_tier_unknown_value_fails(self):
            r = self._run(row(tier="maybe", verdict="BLOCKED"))
            self.assertIn("tier-token", self._codes(r))

        # ---- Rule 2: every row carries a Verdict ----

        def test_valid_verdict_passes(self):
            r = self._run(row(verdict="FAIL"))
            self.assertNotIn("verdict-missing", self._codes(r))

        def test_empty_verdict_fails(self):
            r = self._run(row(verdict=""))
            self.assertIn("verdict-missing", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        def test_nonstandard_verdict_fails(self):
            r = self._run(row(verdict="Passed"))
            self.assertIn("verdict-missing", self._codes(r))

        # ---- Rule 3: not agent-testable is never PASS (matrix's own Verdict) ----

        def test_not_agent_testable_blocked_passes(self):
            r = self._run(row(tier="not agent-testable", preconditions="-",
                              planned="-", verdict="BLOCKED"))
            self.assertNotIn("not-agent-testable-pass", self._codes(r))

        def test_not_agent_testable_fail_passes(self):
            r = self._run(row(tier="not agent-testable", preconditions="-",
                              planned="-", verdict="FAIL"))
            self.assertNotIn("not-agent-testable-pass", self._codes(r))

        def test_not_agent_testable_pass_fails(self):
            r = self._run(row(tier="not agent-testable", preconditions="-",
                              planned=self.capture_rel, verdict="PASS"))
            self.assertIn("not-agent-testable-pass", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        # ---- Rule 4: a partial row names what was not covered ----

        def test_partial_row_naming_gap_in_planned_evidence_passes(self):
            r = self._run(row(tier="partial",
                              preconditions="two accounts, different tenants",
                              planned="ownership check exercised; rate limiting not covered",
                              verdict="BLOCKED"))
            self.assertNotIn("partial-uncovered", self._codes(r))

        def test_partial_row_naming_gap_in_preconditions_passes(self):
            r = self._run(row(tier="partial",
                              preconditions="requires a second tenant account not available in this env",
                              planned="-", verdict="BLOCKED"))
            self.assertNotIn("partial-uncovered", self._codes(r))

        def test_partial_row_with_both_cells_placeholder_fails(self):
            r = self._run(row(tier="partial", preconditions="-", planned="-",
                              verdict="BLOCKED"))
            self.assertIn("partial-uncovered", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        # ---- Rule 5: a PASS row cites an existing capture path ----

        def test_pass_row_citing_existing_capture_passes(self):
            r = self._run(row(tier="provable",
                              preconditions="two accounts, different tenants",
                              planned=f"capture: {self.capture_rel}", verdict="PASS"))
            self.assertNotIn("pass-uncited", self._codes(r))
            self.assertNotIn("pass-capture-missing", self._codes(r))
            self.assertEqual(r["result"], "PASS")

        def test_pass_row_citing_dot_relative_path_passes(self):
            # `.docs/{project-name}/...` is this plugin's own evidence-path
            # convention (a leading-dot relative path) — the punctuation
            # trim must never eat that leading dot.
            docs_capture = self.dir / ".docs" / "demo" / "evidence.md"
            docs_capture.parent.mkdir(parents=True)
            docs_capture.write_text("# capture\n", encoding="utf-8")
            r = self._run(row(tier="provable",
                              preconditions="two accounts, different tenants",
                              planned="capture: .docs/demo/evidence.md, done.",
                              verdict="PASS"))
            self.assertNotIn("pass-capture-missing", self._codes(r))
            self.assertEqual(r["result"], "PASS")

        def test_pass_row_with_no_cited_path_fails(self):
            r = self._run(row(tier="provable",
                              preconditions="two accounts, different tenants",
                              planned="looked fine", verdict="PASS"))
            self.assertIn("pass-uncited", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        def test_pass_row_citing_missing_capture_fails(self):
            r = self._run(row(tier="provable",
                              preconditions="two accounts, different tenants",
                              planned="capture: evidence/security/does-not-exist.md",
                              verdict="PASS"))
            self.assertIn("pass-capture-missing", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        def test_non_pass_verdict_is_never_checked_for_a_citation(self):
            r = self._run(row(tier="provable",
                              preconditions="two accounts, different tenants",
                              planned="-", verdict="BLOCKED"))
            self.assertNotIn("pass-uncited", self._codes(r))
            self.assertNotIn("pass-capture-missing", self._codes(r))

        # ---- Rule 6: provable/partial requires non-empty Preconditions ----

        def test_provable_with_preconditions_passes(self):
            r = self._run(row(tier="provable",
                              preconditions="authenticated session required",
                              planned=f"capture: {self.capture_rel}", verdict="PASS"))
            self.assertNotIn("precondition-missing", self._codes(r))

        def test_provable_with_placeholder_preconditions_fails(self):
            for placeholder in ("-", "—", "TBD", "N/A", ""):
                r = self._run(row(tier="provable", preconditions=placeholder,
                                  planned=f"capture: {self.capture_rel}", verdict="PASS"))
                self.assertIn("precondition-missing", self._codes(r), placeholder)

        def test_partial_with_placeholder_preconditions_fails(self):
            r = self._run(row(tier="partial", preconditions="-",
                              planned="named the gap here", verdict="BLOCKED"))
            self.assertIn("precondition-missing", self._codes(r))

        def test_not_agent_testable_never_needs_preconditions(self):
            r = self._run(row(tier="not agent-testable", preconditions="-",
                              planned="-", verdict="BLOCKED"))
            self.assertNotIn("precondition-missing", self._codes(r))

        # ---- structural / malformed table ----

        def test_missing_table_is_a_clear_error_not_a_traceback(self):
            self.matrix_path.write_text("# Attack surface\n\nNo table here.\n",
                                        encoding="utf-8")
            r = build_report(str(self.matrix_path), str(self.dir))
            self.assertEqual(r["result"], "ERROR")
            self.assertIn("no attack-matrix table found", r["error"])

        def test_missing_file_is_a_clear_error_not_a_traceback(self):
            r = build_report(str(self.dir / "does-not-exist.md"), str(self.dir))
            self.assertEqual(r["result"], "ERROR")
            self.assertIn("file not found", r["error"])

        def test_malformed_row_column_count_is_a_clear_error(self):
            self.matrix_path.write_text(
                HEADER + "\n" + SEP + "\n| IDOR | api | provable |\n",
                encoding="utf-8")
            r = build_report(str(self.matrix_path), str(self.dir))
            self.assertEqual(r["result"], "ERROR")
            self.assertIn("malformed attack-matrix table row", r["error"])

        # ---- does not stop at the first failure ----

        def test_every_violation_is_reported_not_just_the_first(self):
            r = self._run(
                row(category="IDOR", tier="maybe", preconditions="-", planned="-",
                    verdict=""),
                row(category="SSRF", tier="not agent-testable", preconditions="-",
                    planned=self.capture_rel, verdict="PASS"),
            )
            self.assertEqual(r["result"], "FAIL")
            categories = {f["category"] for f in r["failures"]}
            self.assertIn("IDOR", categories)
            self.assertIn("SSRF", categories)
            self.assertGreaterEqual(len(r["failures"]), 3)

        # ---- CLI exit codes (--repo, the --root replacement) ----

        def test_main_exit_codes(self):
            self.matrix_path.write_text(matrix(
                row(tier="provable", preconditions="authenticated session required",
                    planned=f"capture: {self.capture_rel}", verdict="PASS")),
                encoding="utf-8")
            self.assertEqual(
                main(["--matrix", str(self.matrix_path), "--repo", str(self.dir)]), 0)

            self.matrix_path.write_text(matrix(row(verdict="")), encoding="utf-8")
            self.assertEqual(
                main(["--matrix", str(self.matrix_path), "--repo", str(self.dir)]), 1)

            self.assertEqual(
                main(["--matrix", str(self.dir / "gone.md"), "--repo", str(self.dir)]), 2)
            self.assertEqual(main([]), 2)

        # ============================================================
        # LINT MODE
        # ============================================================

        # ---- L1: every row has all six fields ----

        def test_lint_row_with_all_placeholder_fields_passes_l1(self):
            r = self._lint(row(preconditions="-", planned="-", verdict="-"))
            self.assertNotIn("row-incomplete", self._codes(r))

        def test_lint_row_with_a_truly_empty_field_fails(self):
            r = self._lint(row(preconditions=""))
            self.assertIn("row-incomplete", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        # ---- L2: tier bare token, reused at lint time ----

        def test_lint_bad_tier_fails(self):
            r = self._lint(row(tier="mostly provable"))
            self.assertIn("tier-token", self._codes(r))

        # ---- L3: not-agent-testable cites no capture-style evidence ----

        def test_lint_not_agent_testable_with_source_citation_passes(self):
            r = self._lint(row(category="Business Logic Flaws", tier="not agent-testable",
                              preconditions="-",
                              planned="source-read: security-and-hardening/SKILL.md § Coverage",
                              verdict="-"))
            self.assertNotIn("not-agent-testable-evidence", self._codes(r))

        def test_lint_not_agent_testable_with_capture_path_fails(self):
            r = self._lint(row(category="Business Logic Flaws", tier="not agent-testable",
                              preconditions="-",
                              planned=f"capture: {self.capture_rel}", verdict="-"))
            self.assertIn("not-agent-testable-evidence", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        # ---- L4: Broken-Access-Control-family two-account precondition ----

        def test_lint_bac_family_with_two_account_precondition_passes(self):
            for category in ("Broken Access Control", "IDOR", "BOLA", "BFLA"):
                r = self._lint(row(category=category, tier="partial",
                                  preconditions="two accounts, different tenants",
                                  planned="-", verdict="-"))
                self.assertNotIn("bac-precondition-lint", self._codes(r), category)

        def test_lint_bac_family_without_two_account_precondition_fails(self):
            r = self._lint(row(category="IDOR", tier="partial",
                              preconditions="authenticated session required",
                              planned="-", verdict="-"))
            self.assertIn("bac-precondition-lint", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        def test_lint_non_bac_category_never_needs_two_account_wording(self):
            r = self._lint(row(category="SSRF", tier="provable",
                              preconditions="outbound allowlist configured",
                              planned="-", verdict="-"))
            self.assertNotIn("bac-precondition-lint", self._codes(r))

        # ---- L5: environment preamble present ----

        def test_lint_preamble_present_passes(self):
            r = self._lint(row())
            self.assertNotIn("preamble-missing", self._codes(r))

        def test_lint_preamble_missing_fails(self):
            r = self._lint(row(), preamble="# Attack matrix\n\n")
            self.assertIn("preamble-missing", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        # ---- verdict-dependent rules must NOT fire in lint mode ----

        def test_lint_mode_never_fires_verdict_missing(self):
            r = self._lint(row(verdict=""))
            self.assertNotIn("verdict-missing", self._codes(r))

        def test_lint_mode_never_fires_not_agent_testable_pass(self):
            # Would fail under results mode (rule 3); lint mode is silent —
            # Verdict is not a judged column yet.
            r = self._lint(row(tier="not agent-testable", preconditions="-",
                              planned="-", verdict="PASS"))
            self.assertNotIn("not-agent-testable-pass", self._codes(r))

        def test_lint_mode_never_fires_pass_uncited(self):
            r = self._lint(row(tier="provable",
                              preconditions="two accounts, different tenants",
                              planned="looked fine", verdict="PASS"))
            self.assertNotIn("pass-uncited", self._codes(r))
            self.assertNotIn("pass-capture-missing", self._codes(r))

        def test_lint_mode_never_fires_precondition_missing(self):
            r = self._lint(row(category="SSRF", tier="provable", preconditions="-",
                              planned="-", verdict="-"))
            self.assertNotIn("precondition-missing", self._codes(r))

        def test_lint_mode_never_fires_partial_uncovered(self):
            r = self._lint(row(tier="partial", preconditions="-", planned="-",
                              verdict="-"))
            self.assertNotIn("partial-uncovered", self._codes(r))

        # ---- lint CLI wiring ----

        def test_main_lint_only_flag(self):
            self.matrix_path.write_text(matrix(row(planned="-", verdict="-")),
                                        encoding="utf-8")
            self.assertEqual(main(["--lint-only", "--matrix", str(self.matrix_path)]), 0)

            self.matrix_path.write_text(
                matrix(row(tier="maybe", planned="-", verdict="-")), encoding="utf-8")
            self.assertEqual(main(["--lint-only", "--matrix", str(self.matrix_path)]), 1)

        # ============================================================
        # RESULTS MODE — report cross-reference (rules 7-9)
        # ============================================================

        def test_report_row_with_matching_check_line_passes(self):
            report_text = (
                "## Security Audit: demo — 2026-09-16\n\n"
                "- IDOR (api): PASS — `probe.py` — exit 0 — capture: "
                f"{self.capture_rel}\n\n**Verdict:** Pass\n"
            )
            r = self._results(
                row(category="IDOR", surface="api", tier="provable",
                    preconditions="two accounts: alice@test.com, bob@test.com",
                    planned=f"capture: {self.capture_rel}", verdict="PASS"),
                report_text=report_text, priority="Critical")
            self.assertNotIn("row-uncited-in-report", self._codes(r))

        def test_report_row_with_no_matching_check_line_fails(self):
            report_text = (
                "## Security Audit: demo\n\n"
                "- SSRF (api): PASS — `probe.py` — exit 0 — capture: "
                f"{self.capture_rel}\n\n**Verdict:** Pass\n"
            )
            r = self._results(
                row(category="IDOR", surface="api", tier="provable",
                    preconditions="two accounts", planned=f"capture: {self.capture_rel}",
                    verdict="PASS"),
                report_text=report_text, priority="Critical")
            self.assertIn("row-uncited-in-report", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        def test_report_not_agent_testable_pass_fails_even_when_matrix_verdict_is_blocked(self):
            report_text = (
                "## Security Audit: demo\n\n"
                "- Business Logic Flaws (checkout): PASS — reviewed\n\n"
                "**Verdict:** Pass\n"
            )
            r = self._results(
                row(category="Business Logic Flaws", surface="checkout",
                    tier="not agent-testable", preconditions="-", planned="-",
                    verdict="BLOCKED"),
                report_text=report_text, priority="Critical")
            self.assertIn("report-not-agent-testable-pass", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        def test_two_account_row_with_two_identities_passes(self):
            report_text = (
                "## Security Audit: demo\n\n"
                "- IDOR (api): PASS — checked as account alice@test.com and "
                f"account bob@test.com — capture: {self.capture_rel}\n\n"
                "**Verdict:** Pass\n"
            )
            r = self._results(
                row(category="IDOR", surface="api", tier="provable",
                    preconditions="two accounts, different tenants",
                    planned=f"capture: {self.capture_rel}", verdict="PASS"),
                report_text=report_text, priority="Critical")
            self.assertNotIn("two-account-evidence-missing", self._codes(r))

        def test_two_account_row_with_one_identity_fails(self):
            report_text = (
                "## Security Audit: demo\n\n"
                "- IDOR (api): PASS — checked as alice@test.com only — "
                f"capture: {self.capture_rel}\n\n**Verdict:** Pass\n"
            )
            r = self._results(
                row(category="IDOR", surface="api", tier="provable",
                    preconditions="two accounts, different tenants",
                    planned=f"capture: {self.capture_rel}", verdict="PASS"),
                report_text=report_text, priority="Critical")
            self.assertIn("two-account-evidence-missing", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        def test_row_without_two_account_precondition_is_never_checked_for_identities(self):
            report_text = (
                "## Security Audit: demo\n\n"
                "- SSRF (api): PASS — allowlist rejected out-of-scope target — "
                f"capture: {self.capture_rel}\n\n**Verdict:** Pass\n"
            )
            r = self._results(
                row(category="SSRF", surface="api", tier="provable",
                    preconditions="outbound allowlist configured",
                    planned=f"capture: {self.capture_rel}", verdict="PASS"),
                report_text=report_text, priority="Critical")
            self.assertNotIn("two-account-evidence-missing", self._codes(r))

        # ---- priority floor ----

        def test_priority_floor_critical_ignores_important_finding(self):
            report_text = (
                "## Security Audit: demo\n\n"
                "- IDOR (api): PASS — `probe.py` — exit 0 — capture: "
                f"{self.capture_rel}\n\n"
                "- **Important** — missing rate limiting — api/login.py:12\n\n"
                "**Verdict:** Pass\n"
            )
            r = self._results(
                row(category="IDOR", surface="api", tier="provable",
                    preconditions="two accounts: alice@test.com, bob@test.com",
                    planned=f"capture: {self.capture_rel}", verdict="PASS"),
                report_text=report_text, priority="Critical")
            self.assertNotIn("finding-at-or-above-floor", self._codes(r))

        def test_priority_floor_critical_plus_important_catches_important_finding(self):
            report_text = (
                "## Security Audit: demo\n\n"
                "- IDOR (api): PASS — `probe.py` — exit 0 — capture: "
                f"{self.capture_rel}\n\n"
                "- **Important** — missing rate limiting — api/login.py:12\n\n"
                "**Verdict:** Pass\n"
            )
            r = self._results(
                row(category="IDOR", surface="api", tier="provable",
                    preconditions="two accounts: alice@test.com, bob@test.com",
                    planned=f"capture: {self.capture_rel}", verdict="PASS"),
                report_text=report_text, priority="Critical+Important")
            self.assertIn("finding-at-or-above-floor", self._codes(r))
            self.assertEqual(r["result"], "FAIL")

        def test_priority_floor_never_flags_suggestion(self):
            report_text = (
                "## Security Audit: demo\n\n"
                "- IDOR (api): PASS — `probe.py` — exit 0 — capture: "
                f"{self.capture_rel}\n\n"
                "- **Suggestion** — add a comment — api/login.py:9\n\n"
                "**Verdict:** Pass\n"
            )
            r = self._results(
                row(category="IDOR", surface="api", tier="provable",
                    preconditions="two accounts: alice@test.com, bob@test.com",
                    planned=f"capture: {self.capture_rel}", verdict="PASS"),
                report_text=report_text, priority="Critical+Important")
            self.assertNotIn("finding-at-or-above-floor", self._codes(r))

        def test_finding_inside_a_fence_is_not_counted(self):
            report_text = (
                "## Security Audit: demo\n\n"
                "- IDOR (api): PASS — `probe.py` — exit 0 — capture: "
                f"{self.capture_rel}\n\n"
                "```\n- **Critical** — example finding from the template\n```\n\n"
                "**Verdict:** Pass\n"
            )
            r = self._results(
                row(category="IDOR", surface="api", tier="provable",
                    preconditions="two accounts: alice@test.com, bob@test.com",
                    planned=f"capture: {self.capture_rel}", verdict="PASS"),
                report_text=report_text, priority="Critical")
            self.assertNotIn("finding-at-or-above-floor", self._codes(r))

        def test_bad_priority_token_is_an_error(self):
            r = self._results(
                row(category="IDOR", surface="api"),
                report_text="## Security Audit: demo\n\n**Verdict:** Pass\n",
                priority="High")
            self.assertEqual(r["result"], "ERROR")

        def test_require_priority_without_report_is_a_usage_error(self):
            self.matrix_path.write_text(matrix(row()), encoding="utf-8")
            self.assertEqual(
                main(["--matrix", str(self.matrix_path), "--repo", str(self.dir),
                      "--require-priority", "Critical"]), 2)

        def test_results_mode_without_report_runs_only_the_six_matrix_rules(self):
            # No report/priority given: behaves exactly like build_report.
            self.matrix_path.write_text(matrix(row(verdict="")), encoding="utf-8")
            r = build_results_report(str(self.matrix_path), str(self.dir), None, None)
            self.assertIn("verdict-missing", self._codes(r))
            self.assertIsNone(r["report_file"])
            self.assertIsNone(r["require_priority"])

        def test_main_results_mode_with_report_flag(self):
            self.matrix_path.write_text(matrix(
                row(category="IDOR", surface="api", tier="provable",
                    preconditions="two accounts: alice@test.com, bob@test.com",
                    planned=f"capture: {self.capture_rel}", verdict="PASS")),
                encoding="utf-8")
            self.report_path.write_text(
                "## Security Audit: demo\n\n"
                "- IDOR (api): PASS — checked as account alice@test.com and "
                f"account bob@test.com — `probe.py` — exit 0 — capture: "
                f"{self.capture_rel}\n\n**Verdict:** Pass\n", encoding="utf-8")
            self.assertEqual(main([
                "--matrix", str(self.matrix_path), "--report", str(self.report_path),
                "--repo", str(self.dir), "--require-priority", "Critical",
            ]), 0)

        # ---- ledger ----

        def test_ledger_records_a_chained_line(self):
            ledger = self.dir / "gates.jsonl"
            self.matrix_path.write_text(matrix(row(verdict="")), encoding="utf-8")
            main(["--lint-only", "--matrix", str(self.matrix_path), "--ledger", str(ledger)])
            lines = ledger.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["gate"], "check_attack_matrix.py")
            self.assertEqual(record["prev"], "genesis")
            self.assertIn("self", record)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
