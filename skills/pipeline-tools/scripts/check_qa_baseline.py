#!/usr/bin/env python3
"""State-transition coverage gate for a discovery QA baseline.

Echo derives manual test cases from code paths, so two transitions that
share one handler (map a client, and remap it to a different one) collapsed
into one case and the second was never written. The baseline now carries a
`## State Transitions` table -- one row per mutable entity and dimension,
one cell per transition -- and this gate checks every cell names a case the
file defines, or says why none applies. Pure standard library.

Usage:
    python check_qa_baseline.py --file <manual-testing.md> [--ledger <path>]
        [--milestone "<title>"]
    python check_qa_baseline.py --self-test
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

SECTION = "State Transitions"
COLUMNS = ("Entity", "Dimension", "Unset → Set", "Set → Unset",
           "Set → Different")
CASE_ID_RE = re.compile(r"^[A-Z]{2,}-\d{2,}$")
CASE_HEADING_RE = re.compile(r"^#{2,6}\s+([A-Z]{2,}-\d{2,})\b")
NA_RE = re.compile(r"^N/A\s*:\s*(.*)$", re.IGNORECASE)
NONE_RE = re.compile(r"^None\s*:\s*(.*)$", re.IGNORECASE)
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
MIN_REASON_WORDS = 3

DOMAIN_SECTIONS = ("Rules", "Glossary", "Roles", "Entity States",
                   "Known Bugs", "Risk Weights", "Open Questions")
RULE_COLUMNS = ("ID", "Rule", "Source")
RULE_ID_RE = re.compile(r"^D-[1-9]\d*$")
QUESTION_RE = re.compile(r"^[-*]\s+\**(Q-[1-9]\d*)\b")
ANSWERED_RE = re.compile(r"\bAnswered:\s*(DS?-[1-9]\d*)\b")
DEFERRED_RE = re.compile(r"\bDeferred:\s*(.*)$")
QUESTIONS_NONE_RE = re.compile(r"^None\.?$|^None\s*:", re.IGNORECASE)
OPEN_QUESTION_CAP = 10
OVER_CAP_REASON = "over the 10-question cap"
DOMAIN_PREFIX = "domain.md:"

COVERAGE_SECTION = "Domain Coverage"
COVERAGE_COLUMNS = ("Rule", "Cases")
ORACLE_RE = re.compile(r"^\*\*Oracle:\*\*\s*(.*)$")
DEFECT_RE = re.compile(r"^\*\*Suspected defect:\*\*\s*(\S.*)$")
SHARED_RULE_ID_RE = re.compile(r"^DS-[1-9]\d*$")
SUSPECT_PREFIX = "SD-"
FIXED_BY_RE = re.compile(r"^\*\*Fixed by:\*\*(.*)$")
FIXED_BY_LOOSE_RE = re.compile(   # any case, emphasis, prefix or spacing
    r"^(?:[\s>|*+_-]|[0-9]+[.)])*fixed[\s_​-]+by"
    r"(?:[\s*_]*[:：]|\s*[*_]+)", re.IGNORECASE)
FIXED_BY_VALUE_RE = re.compile(
    r"^(?:`([A-Z]{2,}-\d{2,})`|([A-Z]{2,}-\d{2,}))\s+"
    r"\((\d{4}-\d{2}-\d{2})\)$", re.ASCII)
ORACLE_CODE = "code"
HEADING_RE = re.compile(r"^#{1,6}\s")
SECTION_END_RE = re.compile(r"^#{1,2}\s")
SEPARATOR_RE = re.compile(r":?-{3,}:?")
CLOSING_HASHES_RE = re.compile(r"\s+#+\s*$")     # CommonMark `## X ##`


class GateError(Exception):
    """Structural/usage failure -- maps to exit 2."""


def blank_fences(lines):
    """Lines with fenced regions blanked, line count preserved (family rule)."""
    out, fence = [], None
    for line in lines:
        m = FENCE_RE.match(line)
        if fence is None and m:
            fence = m.group(1)[0]
            out.append("")
        elif fence is not None:
            if m and m.group(1)[0] == fence:
                fence = None
            out.append("")
        else:
            out.append(line)
    return out


def split_row(line):
    """Cells of one markdown table row, or None when it is not a row."""
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")) or len(s) < 2:
        return None
    return [c.strip() for c in s[1:-1].split("|")]


def norm_header(cell):
    """Header comparison: whitespace-collapsed, `->` read as the arrow."""
    return " ".join(cell.replace("->", "→").split()).casefold()


def read_lines(path, flag):
    """The file's lines, fences blanked; unreadable is a GateError (exit 2)."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise GateError(f"cannot read {flag} {path}: {exc}")
    return blank_fences(text.splitlines())


def case_ids(lines):
    """Every case ID with a heading in these lines."""
    return {m.group(1) for line in lines
            for m in [CASE_HEADING_RE.match(line)] if m}


def build_report(path):
    p = Path(path)
    lines = read_lines(path, "--file")
    defined = case_ids(lines)
    problems = []

    def problem(code, line_no, detail):
        problems.append({"problem": code, "line": line_no, "detail": detail})

    start = next((i for i, line in enumerate(lines)
                  if re.match(r"^##\s+" + re.escape(SECTION) + r"\s*$",
                              line.strip(), re.IGNORECASE)), None)
    report = {"file": str(p).replace("\\", "/"), "cases_defined": len(defined),
              "rows": [], "none_reason": None, "problems": problems}
    if start is None:
        problem("transitions_missing", None,
                f"no `## {SECTION}` section: every mutable entity's "
                "transitions must be enumerated, or the section must say "
                "`None: <reason>`")
        return report
    body = []
    for i in range(start + 1, len(lines)):
        if re.match(r"^#{1,2}\s", lines[i]):
            break
        if lines[i].strip():
            body.append((i + 1, lines[i]))
    rows = [(n, split_row(line)) for n, line in body]
    table = [(n, cells) for n, cells in rows if cells is not None]
    if not table:
        none = next((NONE_RE.match(line.strip()) for _n, line in body
                     if NONE_RE.match(line.strip())), None)
        if none and len(none.group(1).split()) >= MIN_REASON_WORDS:
            report["none_reason"] = none.group(1).strip()
        else:
            problem("transitions_missing", start + 1,
                    f"`## {SECTION}` holds no table and no `None: <reason>` "
                    f"line of at least {MIN_REASON_WORDS} words")
        return report
    header_no, header = table[0]
    if [norm_header(c) for c in header] != [norm_header(c) for c in COLUMNS]:
        problem("transitions_table_malformed", header_no,
                "header must be | " + " | ".join(COLUMNS) + " |")
        return report
    seen = set()
    data_rows = 0
    for n, cells in table[1:]:
        if all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
            continue                        # the |---| separator row
        data_rows += 1
        if len(cells) != len(COLUMNS):
            problem("transitions_table_malformed", n,
                    f"row has {len(cells)} cells, expected {len(COLUMNS)}")
            continue
        entity, dimension = cells[0], cells[1]
        if not entity or not dimension:
            problem("transitions_table_malformed", n,
                    "Entity and Dimension must both be named")
            continue
        key = (entity.casefold(), dimension.casefold())
        if key in seen:
            problem("transition_row_duplicate", n,
                    f"{entity} / {dimension} is listed twice")
        seen.add(key)
        row = {"line": n, "entity": entity, "dimension": dimension,
               "cells": {}}
        for column, cell in zip(COLUMNS[2:], cells[2:]):
            row["cells"][column] = cell
            where = f"{entity} / {dimension} / {column}"
            na = NA_RE.match(cell)
            if not cell:
                problem("transition_cell_empty", n,
                        f"{where}: name a case ID or `N/A: <reason>`")
            elif na:
                if len(na.group(1).split()) < MIN_REASON_WORDS:
                    problem("transition_na_unreasoned", n,
                            f"{where}: `N/A:` needs a reason of at least "
                            f"{MIN_REASON_WORDS} words")
            else:
                ids = [x.strip().strip("`") for x in cell.split(",")]
                for case_id in ids:
                    if not CASE_ID_RE.match(case_id):
                        problem("transitions_table_malformed", n,
                                f"{where}: {case_id!r} is neither a case ID "
                                "nor `N/A: <reason>`")
                    elif case_id not in defined:
                        problem("transition_case_missing", n,
                                f"{where}: {case_id} is not a case heading "
                                "in this file")
        report["rows"].append(row)
    if not data_rows:
        problem("transitions_missing", header_no,
                "the table has a header and no rows; with no mutable state "
                "write `None: <reason>` instead")
    return report


# --- --domain: the domain pack and the rule-coverage table ------------------

def level2_headings(lines):
    """Level-2 heading text (whitespace-collapsed, casefolded) -> indexes."""
    found = {}
    for i, line in enumerate(lines):
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            text = CLOSING_HASHES_RE.sub("", " " + m.group(1))
            found.setdefault(" ".join(text.split()).casefold(),
                             []).append(i)
    return found


def section_body(lines, start):
    """Non-blank (line_no, text) after heading `start`, to the next #/##."""
    body = []
    for i in range(start + 1, len(lines)):
        if SECTION_END_RE.match(lines[i]):
            break
        if lines[i].strip():
            body.append((i + 1, lines[i]))
    return body


def table_of(body):
    """(line_no, cells) for every table row in a section body."""
    return [(n, cells) for n, line in body
            for cells in [split_row(line)] if cells is not None]


def is_separator(cells):
    return all(SEPARATOR_RE.fullmatch(c) for c in cells)


def has_reason(text):
    return len(text.split()) >= MIN_REASON_WORDS


def parse_rules(lines, start, problem):
    """`## Rules`: {D-<n>: line_no}; empty for a reasoned `None:`."""
    body = section_body(lines, start)
    table = table_of(body)
    rules = {}
    if not table:
        none = next((m for _n, line in body
                     for m in [NONE_RE.match(line.strip())] if m), None)
        if not (none and has_reason(none.group(1))):
            problem("domain_pack_malformed", start + 1,
                    "`## Rules` holds no `| ID | Rule | Source |` table and "
                    f"no `None: <reason>` line of at least {MIN_REASON_WORDS} "
                    "words")
        return rules
    header_no, header = table[0]
    if [norm_header(c) for c in header] != [norm_header(c)
                                            for c in RULE_COLUMNS]:
        problem("domain_pack_malformed", header_no,
                "`## Rules` header must be | " + " | ".join(RULE_COLUMNS)
                + " |")
        return rules
    data_rows = 0
    for n, cells in table[1:]:
        if is_separator(cells):
            continue
        data_rows += 1
        if len(cells) != len(RULE_COLUMNS):
            problem("domain_pack_malformed", n, f"Rules row has {len(cells)} "
                    f"cells, expected {len(RULE_COLUMNS)}")
            continue
        rule_id = cells[0].strip("`")
        if not RULE_ID_RE.match(rule_id):
            problem("domain_pack_malformed", n,
                    f"Rules row, ID cell: {rule_id!r} is not D-<n>")
            continue
        if rule_id in rules:
            problem("domain_pack_malformed", n, f"Rules row, ID cell: "
                    f"{rule_id} repeats line {rules[rule_id]}")
            continue
        rules[rule_id] = n
        for column, cell in zip(RULE_COLUMNS[1:], cells[1:]):
            if not cell:
                problem("domain_pack_malformed", n,
                        f"Rules row {rule_id}, {column} cell: empty")
    if not data_rows:
        problem("domain_pack_malformed", header_no,
                "`## Rules` has a header and no rows; with no rules write "
                "`None: <reason>` instead")
    return rules


def check_open_questions(lines, start, rules, problem):
    """`## Open Questions`: every entry answered or deferred, cap held."""
    body = section_body(lines, start)
    if len(body) == 1 and QUESTIONS_NONE_RE.match(body[0][1].strip()):
        return
    if not body:
        problem("domain_pack_malformed", start + 1,
                "`## Open Questions` holds neither `None` nor "
                "`- Q-<n>` entries")
        return
    entries = []
    for n, line in body:
        m = QUESTION_RE.match(line.strip())
        if m:
            entries.append((n, line.strip(), m.group(1)))
        else:
            problem("domain_pack_malformed", n, "every `## Open Questions` "
                    "line is one `- Q-<n> — ...` entry (Q-1, Q-2, ...), or "
                    "the section is a lone `None`")
    counted = 0
    for n, text, question_id in entries:
        answered = ANSWERED_RE.search(text)
        deferred = DEFERRED_RE.search(text)
        reason = deferred.group(1).strip() if deferred else ""
        if reason != OVER_CAP_REASON:
            counted += 1
        if answered:
            if (RULE_ID_RE.match(answered.group(1))
                    and answered.group(1) not in rules):
                problem("domain_rule_unknown", n,
                        f"{question_id} is Answered: {answered.group(1)}, "
                        "which `## Rules` does not define")
        elif not (deferred and has_reason(reason)):
            problem("open_question_unresolved", n,
                    f"{question_id} carries neither `Answered: D-<n>`/"
                    "`DS-<n>` nor "
                    f"`Deferred: <reason>` of at least {MIN_REASON_WORDS} "
                    "words")
    if counted > OPEN_QUESTION_CAP:
        problem("open_questions_over_cap", start + 1,
                f"{counted} open questions; keep at most {OPEN_QUESTION_CAP} "
                f"and mark the rest `Deferred: {OVER_CAP_REASON}`")


def build_domain_report(domain_path, problems):
    """Gate the domain pack; return its rules {D-<n>: line_no}."""
    lines = read_lines(domain_path, "--domain")

    def problem(code, line_no, detail):
        where = DOMAIN_PREFIX + (f"{line_no}:" if line_no else "")
        problems.append({"problem": code, "line": line_no,
                         "detail": f"{where} {detail}"})

    headings = level2_headings(lines)
    for name in DOMAIN_SECTIONS:
        found = headings.get(name.casefold(), [])
        if not found:
            problem("domain_pack_malformed", None, f"no `## {name}` section")
        for repeat in found[1:]:
            problem("domain_pack_malformed", repeat + 1, f"`## {name}` "
                    f"repeats line {found[0] + 1}; write one section")
    rules = {}
    if "rules" in headings:
        rules = parse_rules(lines, headings["rules"][0], problem)
    if "open questions" in headings:
        check_open_questions(lines, headings["open questions"][0], rules,
                             problem)
    return rules


def case_blocks(lines):
    """Each case heading's block: its Oracle lines and defect presence."""
    blocks, current = [], None
    for i, line in enumerate(lines):
        m = CASE_HEADING_RE.match(line)
        if m:
            current = {"id": m.group(1), "line": i + 1, "oracles": [],
                       "defect": False}
            blocks.append(current)
        elif HEADING_RE.match(line):
            current = None
        elif current is not None:
            text = line.strip()
            oracle = ORACLE_RE.match(text)
            if oracle:
                current["oracles"].append((i + 1, oracle.group(1).strip()))
            elif DEFECT_RE.match(text):
                current["defect"] = True
    return blocks


def check_case_oracle(block, rules, named, problem):
    """One case's Oracle line; adds the D-<n> it names to `named`."""
    case_id = block["id"]
    if not block["oracles"]:
        problem("oracle_missing", block["line"], f"{case_id} has no "
                "`**Oracle:**` line: `code`, or the D-<n>/DS-<n> it checks")
        return
    if len(block["oracles"]) > 1:
        problem("oracle_malformed", block["oracles"][1][0],
                f"{case_id} has {len(block['oracles'])} `**Oracle:**` "
                "lines; exactly one")
        return
    n, value = block["oracles"][0]
    if value != ORACLE_CODE:
        ids = [x.strip().strip("`") for x in value.split(",")]
        if not all(RULE_ID_RE.match(x) or SHARED_RULE_ID_RE.match(x)
                   for x in ids):
            problem("oracle_malformed", n, f"{case_id}: {value!r} is "
                    "neither `code` nor a comma list of D-<n>/DS-<n> IDs")
            return
        for rule_id in ids:
            if not RULE_ID_RE.match(rule_id):
                continue                    # DS-<n>: no lookup (FR-10)
            named.add(rule_id)
            if rule_id not in rules:
                problem("domain_rule_unknown", n, f"{case_id}: Oracle "
                        f"names {rule_id}, which domain.md does not define")
    if case_id.startswith(SUSPECT_PREFIX) and (
            value == ORACLE_CODE or not block["defect"]):
        problem("suspected_defect_malformed", block["line"],
                f"{case_id} needs an Oracle naming the rule it contradicts "
                "and a `**Suspected defect:** <text>` line")


def is_calendar_date(text):
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def check_fixed_by_value(n, current, text, defined, problem):
    """An exact-label marker's value: a real date and a defined non-SD case."""
    value = FIXED_BY_VALUE_RE.match(text)
    if not value or not is_calendar_date(value.group(3)):
        problem("fixed_by_malformed", n, f"{current}: {text!r} is not "
                "`<case ID> (<YYYY-MM-DD>)` with a real date")
        return
    cited = value.group(1) or value.group(2)
    if cited.startswith(SUSPECT_PREFIX):
        problem("fixed_by_cites_sd", n, f"{current}: {cited} is a suspected "
                "defect, not the regression case that fixed it")
    elif cited not in defined:
        problem("fixed_by_case_missing", n, f"{current}: "
                f"{cited} is not a case heading in this file")


def check_fixed_by(lines, defined, problem):
    """`**Fixed by:** <ID> (<date>)`: once per SD case, citing a real case.

    Inside an SD case the label is detected loosely (any case, emphasis,
    prefix or spacing), so a near-miss a reader would take for a marker is
    malformed rather than invisible. Elsewhere only the exact label counts,
    so ordinary "Fixed by:" prose in other cases stays legal. A marker in
    a table row is misplaced.
    """
    current, marked = None, set()
    for i, line in enumerate(lines):
        heading = CASE_HEADING_RE.match(line)
        if heading or HEADING_RE.match(line):
            current = heading.group(1) if heading else None
            continue
        in_sd = current is not None and current.startswith(SUSPECT_PREFIX)
        label = FIXED_BY_LOOSE_RE if in_sd else FIXED_BY_RE
        cells = split_row(line)
        if cells is not None:
            if any(label.match(cell) for cell in cells):
                problem("fixed_by_misplaced", i + 1, "a `**Fixed by:**` "
                        "marker sits in a table row; it is its own line "
                        "inside an SD-NN case")
            continue
        text = line.strip()
        if not label.match(text):
            continue
        if current is None or not current.startswith(SUSPECT_PREFIX):
            problem("fixed_by_misplaced", i + 1, "a `**Fixed by:**` line "
                    f"sits in {current or 'no case'}; only an SD-NN case "
                    "carries one")
        elif current in marked:
            problem("fixed_by_duplicate", i + 1, f"{current} has a second "
                    "`**Fixed by:**` line; one fix closes one SD")
        else:
            marked.add(current)
            exact = FIXED_BY_RE.match(text)
            if exact:
                check_fixed_by_value(i + 1, current, exact.group(1).strip(),
                                     defined, problem)
            else:
                problem("fixed_by_malformed", i + 1, f"{current}: {text!r} "
                        "is not spelled `**Fixed by:**`")


def check_coverage_cell(n, rule_id, cell, defined, oracles, problem):
    """One Cases cell: case IDs whose Oracle names the rule, or `N/A:`."""
    na = NA_RE.match(cell)
    if na:
        if not has_reason(na.group(1)):
            problem("domain_coverage_malformed", n, f"{rule_id}: `N/A:` "
                    f"needs a reason of at least {MIN_REASON_WORDS} words")
        return
    if not cell:
        problem("domain_coverage_malformed", n,
                f"{rule_id}: name a case ID or `N/A: <reason>`")
        return
    for case_id in [x.strip().strip("`") for x in cell.split(",")]:
        if not CASE_ID_RE.match(case_id):
            problem("domain_coverage_malformed", n, f"{rule_id}: "
                    f"{case_id!r} is neither a case ID nor `N/A: <reason>`")
        elif case_id not in defined:
            problem("domain_case_missing", n,
                    f"{rule_id}: {case_id} is not a case heading in this file")
        elif rule_id not in oracles.get(case_id, ()):
            problem("oracle_mismatch", n, f"{rule_id}: {case_id}'s "
                    f"`**Oracle:**` line does not name {rule_id}")


def check_domain_coverage(lines, defined, rules, problems):
    """Oracle lines and `## Domain Coverage`; return the uncovered rules."""
    def problem(code, line_no, detail):
        problems.append({"problem": code, "line": line_no, "detail": detail})

    oracles = {}
    for block in case_blocks(lines):
        check_case_oracle(block, rules,
                          oracles.setdefault(block["id"], set()), problem)
    check_fixed_by(lines, defined, problem)
    start = next((i for i, line in enumerate(lines)
                  if re.match(r"^##\s+" + re.escape(COVERAGE_SECTION)
                              + r"\s*$", line.strip(), re.IGNORECASE)), None)
    covered, seen = set(), set()
    table = table_of(section_body(lines, start)) if start is not None else []
    if table and [norm_header(c) for c in table[0][1]] != [
            norm_header(c) for c in COVERAGE_COLUMNS]:
        problem("domain_coverage_malformed", table[0][0],
                "header must be | " + " | ".join(COVERAGE_COLUMNS) + " |")
        table = []
    for n, cells in table[1:]:
        if is_separator(cells):
            continue
        if len(cells) != len(COVERAGE_COLUMNS):
            problem("domain_coverage_malformed", n, f"row has {len(cells)} "
                    f"cells, expected {len(COVERAGE_COLUMNS)}")
            continue
        rule_id = cells[0].strip("`")
        if not RULE_ID_RE.match(rule_id):
            problem("domain_coverage_malformed", n,
                    f"Rule cell {rule_id!r} is not D-<n>")
            continue
        if rule_id in seen:
            problem("domain_coverage_malformed", n,
                    f"{rule_id} is listed twice")
            continue
        seen.add(rule_id)
        if rule_id not in rules:
            problem("domain_rule_unknown", n,
                    f"{rule_id} is not defined in domain.md's `## Rules`")
            continue
        covered.add(rule_id)
        check_coverage_cell(n, rule_id, cells[1], defined, oracles, problem)
    uncovered = [rule_id for rule_id in rules if rule_id not in covered]
    for rule_id in uncovered:
        problem("domain_rule_uncovered",
                None if start is None else start + 1,
                f"{rule_id} has no `## {COVERAGE_SECTION}` row: cite a case "
                "whose Oracle names it, or `N/A: <reason>`")
    return uncovered


# --- the gate ledger: byte-identical helpers (pipeline-tools/SKILL.md) -----

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


class LedgerLock:
    """Exclusive cross-process lock held around ONE ledger append.

    Without it two concurrent appenders read the same last line and both
    write the same `prev`: a chain break nobody forged (and, on Windows, a
    record overwritten). The lock is taken on the ledger file itself, so
    there is no sidecar file and no stale lock to clean up -- the OS drops
    it if the holder dies: `fcntl.flock` on POSIX; on Windows a
    `msvcrt.locking` byte far past EOF (mandatory there, so it sits where
    no read or append ever reaches). Best-effort: a wait longer than
    WAIT_SECONDS, or any lock error, warns on stderr and the append goes
    ahead unlocked: it never raises, never skips its own append and never
    changes an exit code, though an unlocked append may still collide
    with a concurrent one.
    """

    WAIT_SECONDS = 10.0
    POLL_SECONDS = 0.005
    WINDOWS_LOCK_OFFSET = 1 << 62

    def __init__(self, ledger_path):
        self.ledger_path = ledger_path
        self.fh = None

    def _lock_call(self, unlock):
        """One non-blocking lock (or unlock) attempt; OSError when busy."""
        if sys.platform == "win32":
            import msvcrt
            import os
            os.lseek(self.fh.fileno(), self.WINDOWS_LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(self.fh.fileno(),
                           msvcrt.LK_UNLCK if unlock else msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN if unlock
                        else fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _acquired(self):
        """True once locked, False while another holder has it."""
        import errno
        try:
            self._lock_call(unlock=False)
            return True
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                return False
            raise

    def __enter__(self):
        import time
        deadline = time.monotonic() + self.WAIT_SECONDS
        try:
            self.fh = open(self.ledger_path, "ab")
            while not self._acquired():
                if time.monotonic() >= deadline:
                    raise OSError("lock still held after {0}s".format(
                        self.WAIT_SECONDS))
                time.sleep(self.POLL_SECONDS)
        except (OSError, ImportError, ValueError) as exc:
            if self.fh is not None:
                self.fh.close()
                self.fh = None
            print("Warning: appending to ledger {0} without a lock: "
                  "{1}".format(self.ledger_path, exc), file=sys.stderr)
        return self

    def __exit__(self, *exc_info):
        if self.fh is not None:
            try:
                self._lock_call(unlock=True)
            except OSError as exc:
                print("Warning: could not release the lock on ledger "
                      "{0}: {1}".format(self.ledger_path, exc),
                      file=sys.stderr)
            self.fh.close()
            self.fh = None
        return False


def ledger_append(p, record):
    """Chain `record` onto ledger `p` and append it as one line, locked.

    `prev` is read and the line written, closed and so flushed, inside one
    LedgerLock. An OSError from the write itself propagates: each caller
    keeps its own best-effort handling of a failed append.
    """
    with LedgerLock(p):
        record["prev"] = ledger_prev_hash(p)
        record["self"] = ledger_self_hash(record)
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


def ledger_self_hash(record):
    """sha256 of the record serialized canonically WITHOUT its `self` field."""
    body = {k: v for k, v in record.items() if k != "self"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")).hexdigest()


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
        ledger_append(p, record)
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


PURPOSE = ("Decides whether a discovery QA baseline covers every entity's "
           "state transitions and, with --domain, every domain rule, each "
           "through a defined case or reasoned N/A.")

EPILOG = """\
Reads:
  --file <path>  the feature's .docs/summary/{feature}/QA/manual-testing.md.
  Its `## State Transitions` section holds one table (the arrow is the
  Unicode right arrow or `->`):
    | Entity | Dimension | Unset -> Set | Set -> Unset | Set -> Different |
  one row per mutable entity and independently changeable dimension (a
  client mapping with a target client AND a target box is two rows). Each
  transition cell holds one or more case IDs (`EC-03, EC-04`) whose
  `### <ID> — ...` heading exists in the same file, or `N/A: <reason>`
  (at least 3 words). A feature with no
  mutable state writes `None: <reason>` (3+ words) under the heading
  instead of a table. Fenced blocks are blanked first; the file is read
  as utf-8-sig.

  What this cannot see: an entity the table never lists.

  --domain <path>  the feature's .docs/summary/{feature}/domain.md. Needs
  the level-2 sections Rules, Glossary, Roles, Entity States, Known Bugs,
  Risk Weights, Open Questions, each once. `## Rules` is a `| ID | Rule |
  Source |` table (IDs D-1, D-2, ...; no blank cell) or `None: <reason>`.
  `## Open Questions` is a lone `None`, or only `- Q-<n>` lines (Q-1,
  not Q-01), each saying `Answered: D-<n>`, `Answered: DS-<n>` (a shared
  rule, never looked up) or `Deferred: <reason>` (3+ words); any
  other line is malformed. At most 10 are not
  `Deferred: over the 10-question cap`. With --domain, every case in
  --file has one `**Oracle:** code` or `**Oracle:** D-3, DS-1` line; an
  SD-NN case names its rule and has a `**Suspected defect:**` line. Its
  `## Domain Coverage` table `| Rule | Cases |` gives every D-<n> case IDs
  whose Oracle names it, or `N/A: <reason>`. DS-<n> is never looked up.
  One `**Fixed by:** <ID> (<YYYY-MM-DD>)` line may close an SD case
  (<ID> a non-SD case here, a real date); it still covers its rule.
  Domain-pack details start `domain.md:`. Without --domain, none of this
  runs and output is unchanged.

Problem codes:
  transitions_missing          no section, or a section with neither a table
                               with rows nor a reasoned `None:` line
  transitions_table_malformed  wrong header, wrong cell count, an unnamed
                               entity/dimension, or a cell that is neither
                               case IDs nor `N/A:`
  transition_cell_empty        a transition cell left blank
  transition_na_unreasoned     `N/A:` with fewer than 3 words of reason
  transition_case_missing      a cited ID with no case heading in the file
  transition_row_duplicate     the same entity/dimension listed twice
  domain_pack_malformed        a missing or repeated section, a bad Rules
                               table or row, or an Open Questions line
                               that is neither a Q entry nor a lone None
  open_question_unresolved     a question neither answered nor deferred
  open_questions_over_cap      more than 10 questions not over-cap-deferred
  domain_rule_unknown          an Answered:, Oracle or coverage row naming
                               a D-<n> that Rules does not define
  oracle_missing               a case with no `**Oracle:**` line
  oracle_malformed             two Oracle lines, or a value that is neither
                               `code` nor D-<n>/DS-<n> IDs
  suspected_defect_malformed   an SD- case with Oracle `code` or no
                               `**Suspected defect:**` text
  domain_coverage_malformed    wrong header or cell count, a bad or repeated
                               Rule, or a cell neither case IDs nor `N/A:`
  domain_case_missing          a cited ID with no case heading in the file
  oracle_mismatch              a cited case whose Oracle omits the rule
  domain_rule_uncovered        a D-<n> with no Domain Coverage row
  fixed_by_misplaced           Fixed by outside SD- cases, or in a table
  fixed_by_duplicate           Fixed by repeated in one case
  fixed_by_malformed           a near-miss label (any case, emphasis,
                               prefix), or a value not `<ID> (<date>)`
  fixed_by_case_missing        Fixed by citing no case heading
  fixed_by_cites_sd            Fixed by citing an SD- case

JSON keys:
  file, cases_defined, rows, none_reason, problems, result, error;
  with --domain also domain, rules_defined, rules_uncovered

Exit codes:
  0  every row's three cells resolve, or a reasoned `None:`; with
     --domain, every rule covered and the pack well formed
  1  any problem above
  2  usage error, or --file / --domain unreadable

Self-test:
  python check_qa_baseline.py --self-test
"""


def main(argv):
    parser = PurposeFirstParser(
        prog="check_qa_baseline.py", description=PURPOSE, epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", help="the QA baseline (manual-testing.md)")
    parser.add_argument("--domain", dest="domain",
                        help="the feature's domain pack (domain.md)")
    parser.add_argument("--milestone",
                        help="recorded in the ledger record; not a scope")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return run_self_test()

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone,
                      [args.file, args.domain], verdict, code)
        return code

    if not args.file:
        print(json.dumps({"result": "ERROR",
                          "error": "missing required argument: --file"}))
        return finish(2, "ERROR")
    try:
        report = build_report(args.file)
        if args.domain is not None:
            rules = build_domain_report(args.domain, report["problems"])
            lines = read_lines(args.file, "--file")
            report["domain"] = str(Path(args.domain)).replace("\\", "/")
            report["rules_defined"] = len(rules)
            report["rules_uncovered"] = check_domain_coverage(
                lines, case_ids(lines), rules, report["problems"])
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")
    report["result"] = "FAIL" if report["problems"] else "PASS"
    report["error"] = None
    print(json.dumps(report, indent=2))
    return finish(1, "FAIL") if report["problems"] else finish(0, "PASS")


def run_self_test():
    import shutil

    CASES = ("## Happy Path\n\n### HP-01 — Map a client (P0)\n"
             "### HP-02 — Unmap a client (P0)\n\n## Edge Cases\n\n"
             "### EC-03 — Remap to another box (P0)\n"
             "### EC-04 — Remap to another client (P0)\n")
    HEADER = ("| Entity | Dimension | Unset → Set | Set → Unset | "
              "Set → Different |\n|---|---|---|---|---|\n")

    class QaBaselineTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.file = self.dir / "manual-testing.md"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def codes(self, transitions, cases=CASES):
            self.file.write_text("# QA\n\n" + cases + "\n## State Transitions"
                                 "\n\n" + transitions, encoding="utf-8")
            return sorted(p["problem"] for p in
                          build_report(str(self.file))["problems"])

        def test_full_table_passes(self):
            self.assertEqual(self.codes(
                HEADER + "| Mapping | Slide client | HP-01 | HP-02 | EC-04 |\n"
                "| Mapping | Box | HP-01 | HP-02 | EC-03 |\n"), [])

        def test_the_slide_gap_fails(self):
            """2026-10-16: remap-to-another-client had no case."""
            self.assertEqual(self.codes(
                HEADER + "| Mapping | Slide client | HP-01 | HP-02 | |\n"),
                ["transition_cell_empty"])

        def test_reasoned_na_passes_and_bare_na_fails(self):
            self.assertEqual(self.codes(
                HEADER + "| Flag | Enabled | HP-01 | HP-02 | N/A: boolean, "
                "so different is unset or set |\n"), [])
            self.assertEqual(self.codes(
                HEADER + "| Flag | Enabled | HP-01 | HP-02 | N/A |\n"),
                ["transitions_table_malformed"])
            self.assertEqual(self.codes(
                HEADER + "| Flag | Enabled | HP-01 | HP-02 | N/A: no |\n"),
                ["transition_na_unreasoned"])

        def test_cited_case_must_exist(self):
            self.assertEqual(self.codes(
                HEADER + "| Mapping | Box | HP-01 | HP-02 | EC-03, EC-09 |\n"),
                ["transition_case_missing"])

        def test_a_case_only_inside_a_fence_does_not_exist(self):
            cases = CASES + "```\n### EC-09 — template (P2)\n```\n"
            self.assertEqual(self.codes(
                HEADER + "| Mapping | Box | HP-01 | HP-02 | EC-09 |\n", cases),
                ["transition_case_missing"])

        def test_missing_section_fails(self):
            self.file.write_text("# QA\n\n" + CASES, encoding="utf-8")
            self.assertEqual([p["problem"] for p in build_report(
                str(self.file))["problems"]], ["transitions_missing"])

        def test_reasoned_none_passes_and_empty_section_fails(self):
            self.assertEqual(self.codes(
                "None: a read-only report with no writes\n"), [])
            self.assertEqual(self.codes("None: n/a\n"),
                             ["transitions_missing"])
            self.assertEqual(self.codes(HEADER), ["transitions_missing"])

        def test_wrong_header_or_cell_count_fails(self):
            self.assertEqual(self.codes(
                "| Entity | Dimension | Add | Remove | Change |\n"
                "|---|---|---|---|---|\n| A | B | HP-01 | HP-02 | EC-03 |\n"),
                ["transitions_table_malformed"])
            self.assertEqual(self.codes(
                HEADER + "| A | B | HP-01 | HP-02 |\n"),
                ["transitions_table_malformed"])

        def test_ascii_arrow_header_is_accepted(self):
            header = HEADER.replace("→", "->")
            self.assertEqual(self.codes(
                header + "| A | B | HP-01 | HP-02 | EC-03 |\n"), [])

        def test_duplicate_row_fails(self):
            row = "| A | B | HP-01 | HP-02 | EC-03 |\n"
            self.assertEqual(self.codes(HEADER + row + row),
                             ["transition_row_duplicate"])

        def test_cli_exit_codes_and_ledger(self):
            self.codes(HEADER + "| A | B | HP-01 | HP-02 | EC-03 |\n")
            ledger = self.dir / "gates.jsonl"
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--file", str(self.file),
                                       "--ledger", str(ledger)]), 0)
                self.assertEqual(main(["--file", str(self.dir / "nope.md"),
                                       "--ledger", str(ledger)]), 2)
                self.assertEqual(main([]), 2)
            records = [json.loads(l) for l in
                       ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["verdict"] for r in records],
                             ["PASS", "ERROR"])
            self.assertEqual(records[1]["prev"],
                             ledger_line_hash(ledger.read_bytes()
                                              .splitlines()[0]))

        def test_bom_and_next_section_bound_the_table(self):
            self.file.write_text(
                "﻿# QA\n\n" + CASES + "\n## State Transitions\n\n"
                + HEADER + "| A | B | HP-01 | HP-02 | EC-03 |\n\n"
                "## Notes\n\n| x | y |\n", encoding="utf-8")
            self.assertEqual(build_report(str(self.file))["problems"], [])

    RULES = ("| ID | Rule | Source |\n|---|---|---|\n"
             "| D-1 | A mapped client can be remapped | user, 2026-10-20 |\n"
             "| D-2 | Unmapping keeps the history row | user, 2026-10-20 |\n")
    QUESTION = "- Q-1 — Remap or reject? Answered: D-1\n"
    D_CASES = ("## Happy Path\n\n### HP-01 — Remap a client (P0)\n"
               "**Oracle:** D-1\n\n### HP-02 — Unmap a client (P0)\n"
               "**Oracle:** D-2\n")
    COVER_HEAD = "## Domain Coverage\n\n| Rule | Cases |\n|---|---|\n"
    COVERAGE = COVER_HEAD + "| D-1 | HP-01 |\n| D-2 | HP-02 |\n"
    LEGACY_KEYS = ["file", "cases_defined", "rows", "none_reason", "problems",
                   "result", "error"]

    class DomainTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.file = self.dir / "manual-testing.md"
            self.domain = self.dir / "domain.md"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def write(self, rules=RULES, questions=QUESTION, drop=None,
                  cases=D_CASES, coverage=COVERAGE):
            body = {"Rules": rules, "Glossary": "None.\n",
                    "Roles": "None.\n", "Entity States": "None.\n",
                    "Known Bugs": "None.\n", "Risk Weights": "None.\n",
                    "Open Questions": questions}
            self.domain.write_text("# Domain pack\n\n" + "".join(
                f"## {name}\n{text}\n" for name, text in body.items()
                if name != drop), encoding="utf-8")
            self.file.write_text(
                "# QA\n\n" + cases + "\n## State Transitions\n\nNone: a "
                "fixture with no mutable state\n\n" + coverage,
                encoding="utf-8")

        def run_main(self, extra=()):
            import contextlib
            import io
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--file", str(self.file), "--domain",
                             str(self.domain), *extra])
            return code, json.loads(out.getvalue())

        def codes(self, **kw):
            self.write(**kw)
            code, report = self.run_main()
            codes = sorted(p["problem"] for p in report["problems"])
            self.assertEqual(code, 1 if codes else 0)
            return codes

        def test_full_pack_and_coverage_pass(self):
            self.write()
            code, report = self.run_main()
            self.assertEqual((code, report["problems"]), (0, []))
            self.assertEqual((report["rules_defined"],
                              report["rules_uncovered"]), (2, []))
            self.assertEqual(report["domain"],
                             str(self.domain).replace("\\", "/"))

        def test_missing_domain_section_fails(self):
            self.write(drop="Risk Weights")
            _code, report = self.run_main()
            self.assertEqual([p["problem"] for p in report["problems"]],
                             ["domain_pack_malformed"])
            self.assertTrue(report["problems"][0]["detail"]
                            .startswith("domain.md:"))

        def test_bad_rules_rows_fail(self):
            for row in ("| D-2 | Unmapping keeps the history row | |\n",
                        "| D-2 |  | user |\n",
                        "| D-02 | Unmapping keeps history | user |\n",
                        "| D-1 | Unmapping keeps history | user |\n"):
                with self.subTest(row=row):
                    self.assertIn("domain_pack_malformed", self.codes(
                        rules=RULES.rsplit("| D-2", 1)[0] + row))

        def test_rules_none_passes_without_coverage(self):
            self.assertEqual(self.codes(
                rules="None: no rules found here\n", questions="None\n",
                cases=D_CASES.replace("D-1", "code").replace("D-2", "code"),
                coverage=""), [])
            self.assertEqual(self.codes(
                rules="None: no rules found here\n", questions="None\n",
                cases=D_CASES.replace("D-1", "code").replace("D-2", "code"),
                coverage="## Domain Coverage\n\nNone: no rules in the pack\n"),
                [])
            self.assertEqual(self.codes(rules="None: none\n"),
                             sorted(["domain_pack_malformed",
                                     "domain_rule_unknown",
                                     "domain_rule_unknown",
                                     "domain_rule_unknown",
                                     "domain_rule_unknown",
                                     "domain_rule_unknown"]))

        def test_open_question_dispositions(self):
            self.assertEqual(self.codes(questions="- Q-1 — Remap?\n"),
                             ["open_question_unresolved"])
            self.assertEqual(self.codes(
                questions="- Q-1 — Remap? Deferred: user not sure yet\n"), [])
            self.assertEqual(self.codes(
                questions="- Q-1 — Remap? Deferred: later\n"),
                ["open_question_unresolved"])
            self.assertEqual(self.codes(
                questions="- Q-1 — Remap? Answered: D-9\n"),
                ["domain_rule_unknown"])
            self.assertEqual(self.codes(
                questions="- Q-1 — Remap? Answered: DS-1\n"), [])
            self.assertEqual(self.codes(
                questions="- Q-1 — Remap? Answered: DS-01\n"),
                ["open_question_unresolved"])
            self.assertIn("domain_pack_malformed", self.codes(
                rules=RULES + "| DS-1 | Roles are shared | user |\n"))

        def test_no_open_questions_ec2(self):
            for text in ("None\n", "None.\n", "None: nothing was ambiguous\n"):
                with self.subTest(text=text):
                    self.assertEqual(self.codes(questions=text), [])
            self.assertEqual(self.codes(questions="\n"),
                             ["domain_pack_malformed"])

        def test_every_open_questions_line_is_gated(self):
            """2026-10-20 red team: these shapes were silently ignored."""
            for text in ("- Q-02 — Remap? Deferred: user not sure yet\n",
                         "- Should remap be allowed at all?\n",
                         "1. Q-2 — Remap? Deferred: user not sure yet\n",
                         QUESTION + "- Q-02 — Remap? Deferred: not sure\n",
                         QUESTION + "- Should remap be allowed at all?\n",
                         QUESTION + "1. Q-2 — Remap? Deferred: not sure\n",
                         "None\n- Q-1 — Remap or reject?\n",
                         QUESTION + "None\n",
                         QUESTION + "  more prose about Q-1\n"):
                with self.subTest(text=text):
                    self.assertIn("domain_pack_malformed",
                                  self.codes(questions=text))

        def test_zero_padded_ids_cannot_escape_the_cap(self):
            entries = "".join(f"- Q-{n} — ? Deferred: user not sure yet\n"
                              for n in range(1, 11)) + "".join(
                f"- Q-0{n} — ? Deferred: user not sure yet\n"
                for n in range(1, 6))
            self.assertIn("domain_pack_malformed",
                          self.codes(questions=entries))

        def test_repeated_domain_section_fails(self):
            self.assertIn("domain_pack_malformed", self.codes(
                rules=RULES + "\n## Rules\n| ID | Rule | Source |\n"
                "|---|---|---|\n| D-3 | Hidden rule | user |\n"))

        def test_closing_hash_heading_is_the_same_section(self):
            """Round 2 red team: `## X ##` is CommonMark for `## X`."""
            self.assertIn("domain_pack_malformed", self.codes(
                questions=QUESTION + "\n## Open Questions ##\n"
                "- Q-2 — x?\n"))
            self.assertIn("domain_pack_malformed", self.codes(
                rules="None: no rules found here\n\n## Rules ##\n" + RULES))
            self.write()
            self.domain.write_text(self.domain.read_text(encoding="utf-8")
                                   .replace("## Risk Weights\n",
                                            "## Risk Weights ##\n"),
                                   encoding="utf-8")
            self.assertEqual(self.run_main()[1]["problems"], [])

        def test_suspected_defect_cited_for_another_rule_mismatches(self):
            sd = ("\n### SD-01 — History row dropped (P0)\n**Oracle:** D-2\n"
                  "**Suspected defect:** unmap deletes the row; contradicts "
                  "D-2: unmapping keeps the history row\n")
            self.assertEqual(self.codes(
                cases=D_CASES + sd,
                coverage=COVER_HEAD + "| D-1 | HP-01, SD-01 |\n"
                "| D-2 | SD-01 |\n"), ["oracle_mismatch"])

        def test_open_questions_cap(self):
            entries = "".join(f"- **Q-{n}** — ? Deferred: user not sure yet\n"
                              for n in range(1, 12))
            self.assertEqual(self.codes(questions=entries),
                             ["open_questions_over_cap"])
            capped = entries.rsplit("Deferred:", 1)[0] + (
                "Deferred: " + OVER_CAP_REASON + "\n")
            self.assertEqual(self.codes(questions=capped), [])

        def test_report_keys_without_and_with_domain(self):
            import contextlib
            import io
            self.write()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main(["--file", str(self.file)])
            self.assertEqual(list(json.loads(out.getvalue())), LEGACY_KEYS)
            _code, report = self.run_main()
            self.assertEqual(list(report), LEGACY_KEYS[:5] + [
                "domain", "rules_defined", "rules_uncovered"]
                + LEGACY_KEYS[5:])

        def test_unreadable_domain_and_ledger_inputs(self):
            self.write()
            ledger = self.dir / "gates.jsonl"
            self.assertEqual(self.run_main(["--ledger", str(ledger)])[0], 0)
            self.domain.unlink()
            self.assertEqual(self.run_main(["--ledger", str(ledger)])[0], 2)
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                main(["--file", str(self.file), "--ledger", str(ledger)])
            records = [json.loads(l) for l in
                       ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([len(r["inputs"]) for r in records], [2, 2, 1])
            self.assertEqual(records[1]["verdict"], "ERROR")

        def test_empty_domain_path_is_an_error(self):
            """--domain "" is a flag given, not absent: exit 2, never PASS."""
            self.write()
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                code = main(["--file", str(self.file), "--domain", ""])
            self.assertEqual(code, 2)

        def test_uncovered_rule_then_na(self):
            self.write(coverage=COVER_HEAD + "| D-1 | HP-01 |\n")
            code, report = self.run_main()
            self.assertEqual(code, 1)
            self.assertEqual([(p["problem"], "D-2" in p["detail"])
                              for p in report["problems"]],
                             [("domain_rule_uncovered", True)])
            self.assertEqual(report["rules_uncovered"], ["D-2"])
            self.assertEqual(self.codes(
                coverage=COVER_HEAD + "| D-1 | HP-01 |\n"
                "| D-2 | N/A: covered by another feature |\n"), [])
            self.assertEqual(self.codes(
                coverage=COVER_HEAD + "| D-1 | HP-01 |\n| D-2 | N/A: no |\n"),
                ["domain_coverage_malformed"])
            self.assertEqual(self.codes(coverage=""),
                             ["domain_rule_uncovered", "domain_rule_uncovered"])

        def test_suspected_defect_covers_its_rule_ec3(self):
            sd = ("\n### SD-01 — History row dropped on unmap (P0)\n"
                  "**Oracle:** D-2\n**Suspected defect:** unmap deletes the "
                  "row; contradicts D-2: unmapping keeps the history row\n")
            self.assertEqual(self.codes(
                cases=D_CASES + sd,
                coverage=COVER_HEAD + "| D-1 | HP-01 |\n| D-2 | SD-01 |\n"),
                [])

        def test_suspected_defect_malformed(self):
            for sd in ("**Oracle:** code\n**Suspected defect:** it breaks\n",
                       "**Oracle:** D-2\n",
                       "**Oracle:** D-2\n**Suspected defect:**\n"):
                with self.subTest(sd=sd):
                    self.assertEqual(self.codes(
                        cases=D_CASES + "\n### SD-01 — Dropped (P1)\n" + sd),
                        ["suspected_defect_malformed"])

        def test_oracle_lines(self):
            self.assertEqual(self.codes(
                cases=D_CASES + "\n### EC-03 — No oracle (P2)\n"),
                ["oracle_missing"])
            for oracle in ("**Oracle:** D-1\n**Oracle:** D-2\n",
                           "**Oracle:** maybe\n", "**Oracle:**\n",
                           "**Oracle:** D-1; D-2\n"):
                with self.subTest(oracle=oracle):
                    self.assertEqual(self.codes(
                        cases=D_CASES + "\n### EC-03 — X (P2)\n" + oracle),
                        ["oracle_malformed"])
            self.assertEqual(self.codes(
                cases=D_CASES + "\n### EC-03 — X (P2)\n**Oracle:** D-9\n"),
                ["domain_rule_unknown"])
            self.assertEqual(self.codes(
                cases=D_CASES + "\n### EC-03 — X (P2)\n**Oracle:** DS-4\n"),
                [])
            self.assertEqual(self.codes(
                cases=D_CASES + "\n### EC-03 — X (P2)\n"
                "**Oracle:** code, D-1\n"), ["oracle_malformed"])

        def test_coverage_row_must_match_the_oracle(self):
            self.assertEqual(self.codes(
                cases=D_CASES.replace("**Oracle:** D-1", "**Oracle:** code")),
                ["oracle_mismatch"])
            self.assertEqual(self.codes(
                coverage=COVERAGE + "| D-9 | HP-01 |\n"),
                ["domain_rule_unknown"])
            self.assertEqual(self.codes(
                coverage=COVER_HEAD + "| D-1 | HP-01 |\n| D-2 | HP-09 |\n"),
                ["domain_case_missing"])

        def fixed(self, marker, sd_tail="", extra=""):
            """Codes for an SD-01 carrying `marker`, beside RR-01 (FR-4)."""
            sd = ("\n## Suspected Defects\n\n### SD-01 — History row dropped "
                  "(P0)\n**Oracle:** D-2\n**Suspected defect:** unmap deletes "
                  "the row; contradicts D-2: unmapping keeps the history row\n"
                  + marker + sd_tail + "\n## Regression Risks\n\n### RR-01 — "
                  "Unmap keeps history (P0)\n**Oracle:** D-2\n" + extra)
            return self.codes(cases=D_CASES + sd, coverage=COVER_HEAD
                              + "| D-1 | HP-01 |\n| D-2 | HP-02, SD-01 |\n")

        def test_fixed_by_marker_passes_and_still_covers(self):
            self.assertEqual(self.fixed(
                "**Fixed by:** RR-01 (2026-10-21)\n"), [])
            self.assertEqual(self.fixed(
                "**Fixed by:** `RR-01` (2026-10-21)\n"), [])

        def test_fixed_by_near_miss_label_is_malformed(self):
            """Review I-1: a near-miss spelling verify would read as closed."""
            for marker in ("**fixed by:**", "**Fixed By:**", "**Fixed by**:",
                           "Fixed by:", "- **Fixed by:**", "> **Fixed by:**",
                           "__Fixed by:__", "**Fixed by:**",
                           "**Fixed  by:**", "**Fixed by**",
                           "**Fixed-by:**", "Fixed-by:", "1. **Fixed by:**",
                           "**Fixed by：**", "**Fixed​by:**"):
                with self.subTest(marker=marker):
                    self.assertEqual(self.fixed(
                        marker + " RR-01 (2026-10-21)\n"),
                        ["fixed_by_malformed"])

        def test_fixed_by_prose_outside_an_sd_passes(self):
            """Re-review I-4: loose matching runs only inside SD cases."""
            for prose in ("Fixed by: upgrading the vendor SDK in 4.2.\n",
                          "Fixed by _accident_ in 4.1, then regressed.\n",
                          "| GO | DO | ASSERT |\n|---|---|---|\n"
                          "| Orders | Fixed by: PR 412 | ok |\n"):
                with self.subTest(prose=prose):
                    self.assertEqual(self.fixed(
                        "**Fixed by:** RR-01 (2026-10-21)\n", extra=prose),
                        [])

        def test_fixed_by_in_the_step_table_is_misplaced(self):
            """Review I-1: a marker in a GO/DO/ASSERT row or cell."""
            table = "| GO | DO | ASSERT |\n|---|---|---|\n"
            for row in ("| **Fixed by:** RR-01 (2026-10-21) | | |\n",
                        "| Clients | unmap A | **fixed by:** RR-01 "
                        "(2026-10-21) |\n"):
                with self.subTest(row=row):
                    self.assertEqual(self.fixed(table + row),
                                     ["fixed_by_misplaced"])

        def test_fixed_by_citing_an_sd_fails(self):
            """Review I-2: an SD retired by itself or another SD."""
            sd2 = ("\n### SD-02 — Remap drops audit (P1)\n**Oracle:** D-2\n"
                   "**Suspected defect:** remap drops audit; contradicts "
                   "D-2\n")
            for cited in ("SD-01", "SD-02"):
                with self.subTest(cited=cited):
                    self.assertEqual(self.fixed(
                        f"**Fixed by:** {cited} (2026-10-21)\n", extra=sd2),
                        ["fixed_by_cites_sd"])

        def test_fixed_by_case_missing(self):
            self.assertEqual(self.fixed("**Fixed by:** RR-99 (2026-10-21)\n"),
                             ["fixed_by_case_missing"])

        def test_fixed_by_misplaced(self):
            self.assertEqual(self.fixed(
                "", extra="**Fixed by:** RR-01 (2026-10-21)\n"),
                ["fixed_by_misplaced"])
            self.assertEqual(self.codes(cases=D_CASES.replace(
                "## Happy Path\n", "## Happy Path\n**Fixed by:** HP-01 "
                "(2026-10-21)\n")), ["fixed_by_misplaced"])

        def test_fixed_by_duplicate_fr7(self):
            self.assertEqual(self.fixed(
                "**Fixed by:** RR-01 (2026-10-21)\n",
                sd_tail="**Fixed by:** RR-01 (2026-10-22)\n"),
                ["fixed_by_duplicate"])

        def test_fixed_by_malformed(self):
            for marker in ("**Fixed by:** RR-01\n", "**Fixed by:** soon\n",
                           "**Fixed by:**\n",
                           "**Fixed by:** RR-01 (21-10-2026)\n",
                           "**Fixed by:** RR-01 (2026-13-45)\n",
                           "**Fixed by:** RR-01 (2026-02-30)\n",
                           "**Fixed by:** `RR-01 (2026-10-21)\n",
                           "**Fixed by:** RR-01` (2026-10-21)\n",
                           "**Fixed by:** RR-01 (٢026-10-21)\n"):
                with self.subTest(marker=marker):
                    self.assertEqual(self.fixed(marker),
                                     ["fixed_by_malformed"])

        def test_fixed_by_inside_a_fence_is_ignored_ec2(self):
            self.assertEqual(self.fixed(
                "```\n**Fixed by:** RR-99 (2026-10-21)\n```\n"), [])

        def test_coverage_table_malformed(self):
            for coverage in (
                    "## Domain Coverage\n\n| Rule | Case |\n|---|---|\n"
                    "| D-1 | HP-01 |\n| D-2 | HP-02 |\n",
                    COVERAGE + "| D-x | HP-01 |\n",
                    COVERAGE + "| D-1 | HP-01 |\n",
                    COVERAGE.replace("| D-2 | HP-02 |", "| D-2 | |"),
                    COVERAGE.replace("| D-2 | HP-02 |", "| D-2 | HP 2 |"),
                    COVERAGE.replace("| D-2 | HP-02 |", "| D-2 | HP-02 | x |")):
                with self.subTest(coverage=coverage):
                    self.assertIn("domain_coverage_malformed",
                                  self.codes(coverage=coverage))

    suite = unittest.TestSuite()
    for case in (QaBaselineTests, DomainTests):
        suite.addTests(unittest.TestLoader().loadTestsFromTestCase(case))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
