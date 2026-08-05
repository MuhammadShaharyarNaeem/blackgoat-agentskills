#!/usr/bin/env python3
"""Deterministic coverage-gate CLI for the bgPDD pipelines.

Verifies every Must-Have FR/NFR in a requirements.md is covered either by
plan.md tasks (plan mode) or by passing tests in test-report.md (test mode).

Usage:
    python check_coverage.py --requirements <path> --plan <path>
    python check_coverage.py --requirements <path> --test-report <path>
    python check_coverage.py --requirements <path> --design <path>
    python check_coverage.py --self-test

Pure standard library. See ../SKILL.md for the full contract (JSON shape,
exit codes, parsing rules).
"""
import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Regex vocabulary
# ---------------------------------------------------------------------------

HEADING_RE = re.compile(r"^(#{1,6})(?:\s|$)")
TIER_HEADING_RE = re.compile(r"^#{2,4}\s*(Must|Should|Could|Won'?t)\s+Have", re.IGNORECASE)
FR_BOLD_RE = re.compile(r"\*\*(FR-\d+)\*\*", re.IGNORECASE)
NFR_BOLD_RE = re.compile(r"\*\*(NFR-\d+)\*\*", re.IGNORECASE)
NFR_TIER_RE = re.compile(r"-\s*\*\*(NFR-\d+)\*\*\s*\((Must|Should|Could)[^)]*\)", re.IGNORECASE)
TASK_HEADING_RE = re.compile(r"^##\s*Task\s*\[?(\d+)\]?\s*:", re.IGNORECASE | re.MULTILINE)
COVERED_FIELD_RE = re.compile(r"\*\*Requirements covered:\*\*", re.IGNORECASE)
ID_TOKEN_RE = re.compile(r"\b(?:FR|NFR)-\d+\b", re.IGNORECASE)
FAIL_TOKEN_RE = re.compile(r"\b(?:FAILED|FAIL)\b|❌", re.IGNORECASE)
PASS_TOKEN_RE = re.compile(r"\b(?:PASSED|PASS)\b|✅", re.IGNORECASE)
STRUCK_ID_RE = re.compile(r"~~[^~]*?\*\*((?:FR|NFR)-\d+)\*\*[^~]*?~~", re.IGNORECASE)

# --- plan-mode lint vocabulary -------------------------------------------
# Inventory nouns only: a count of artifacts that exists in a source table.
# Deliberately excludes unit/threshold nouns ("2 decimal places", "3 attempts",
# "60 seconds") which are legitimate acceptance-criteria values.
LITERAL_COUNT_RE = re.compile(
    r"(?<![\w-])\d+\s+(?:error\s+|status\s+)?"
    r"(?:codes|routes|endpoints|entries|components|screens|tables)\b",
    re.IGNORECASE,
)
BOUNDARY_FIELD_RE = re.compile(r"\*\*Boundary\s+contracts?:\*\*", re.IGNORECASE)
FIELD_START_RE = re.compile(r"^\s*(?:[-*+]\s+)?\*\*[^*]+:\*\*")
CONTRACT_TOKEN_RE = re.compile(
    r"\b(consumes|provides)\s*:\s*((?:(?!\b(?:consumes|provides)\s*:)[^\n;])*)",
    re.IGNORECASE,
)
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9_./-]+")
EMPTY_VALUES = {"none", "n/a", "na", "nothing", "-", "tbd"}

# --- design-mode lint vocabulary -----------------------------------------
REGISTER_HEADING_RE = re.compile(
    r"^#{2,4}\s*(?:[\d.]+\s+)?Divergence\s*(?:&|and)\s*Supersession\s+Register\b",
    re.IGNORECASE,
)
TABLE_ROW_RE = re.compile(r"^\s*\|")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|[\s:|-]*\|?\s*$")
ANY_BOLD_ID_RE = re.compile(r"\*\*((?:FR|NFR)-\d+)\*\*", re.IGNORECASE)
SUPERSESSION_ANNOTATION_RE = re.compile(r"supersed\w*|~~", re.IGNORECASE)
ROW_LABEL_CLEAN_RE = re.compile(r"[*`~]+")
REGISTER_ROW_ID_RE = re.compile(r"\b([A-Z]{2,5}-\d+)\b")
# A register row's subject — what it departs from / supersedes — is declared in
# its first two cells; later cells are justification prose that cites other
# requirements as supporting argument without superseding them.
SUBJECT_CELL_COUNT = 2

FILE_URI_RE = re.compile(r"file:///\S*[^\s`'\"()\[\],;.]")
WINDOWS_ABS_PATH_RE = re.compile(r"(?<![\w:/\\])[A-Za-z]:[\\/][^\s`'\"()\[\],;]*")
UNC_PATH_RE = re.compile(r"(?<!\S)\\\\[^\s`'\"()\[\],;]+")
REL_ESCAPE_RE = re.compile(r"(?<![\w.])\.\.[\\/][^\s`'\"()\[\],;]*")


class GateError(Exception):
    """A structural contract failure in an artifact (exit code 2)."""


def sort_key(req_id):
    """Natural sort key so FR-2 sorts before FR-10."""
    prefix, number = req_id.split("-", 1)
    return (prefix, int(number))


def read_text(path):
    """Read a file as utf-8-sig with replacement on decode errors.

    Returns (text, None) on success or (None, error_message) on failure.
    """
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
            return handle.read(), None
    except OSError as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# requirements.md parsing
# ---------------------------------------------------------------------------


def heading_level(line):
    match = HEADING_RE.match(line)
    return len(match.group(1)) if match else None


def parse_requirements(text):
    """Parse a requirements.md body.

    Returns (tier_by_id, warnings, known_ids):
      tier_by_id  -- {ID: "Must"|"Should"|"Could"} for every non-excluded ID
      warnings    -- list of warning strings
      known_ids   -- every ID that appeared anywhere (including Won't-Have),
                     used to detect "unknown ID cited in plan".
    """
    warnings = []
    events = []  # list of (id, tier) in document order
    struck_ids = set()  # IDs annotated as superseded (strikethrough)

    current_tier = None
    current_level = None

    for line in text.split("\n"):
        for match in STRUCK_ID_RE.finditer(line):
            struck_ids.add(match.group(1).upper())

        level = heading_level(line)
        if level is not None:
            tier_match = TIER_HEADING_RE.match(line)
            if tier_match and 2 <= level <= 4:
                word = tier_match.group(1).lower()
                current_tier = "Wont" if word.startswith("won") else word.capitalize()
                current_level = level
            elif current_tier is not None and level <= current_level:
                current_tier = None
                current_level = None

        if current_tier is not None:
            for match in FR_BOLD_RE.finditer(line):
                events.append((match.group(1).upper(), current_tier))

        tier_tagged_ids = set()
        for match in NFR_TIER_RE.finditer(line):
            req_id = match.group(1).upper()
            tier = match.group(2).lower().capitalize()
            events.append((req_id, tier))
            tier_tagged_ids.add(req_id)

        for match in NFR_BOLD_RE.finditer(line):
            req_id = match.group(1).upper()
            if req_id not in tier_tagged_ids:
                warnings.append(
                    f"{req_id} has a bold ID but no parseable tier tag; defaulting to Must Have"
                )
                events.append((req_id, "Must"))

    by_id = {}
    for req_id, tier in events:
        by_id.setdefault(req_id, []).append(tier)

    tier_by_id = {}
    known_ids = set(by_id.keys())

    for req_id, tiers in by_id.items():
        had_wont = "Wont" in tiers
        others = [t for t in tiers if t != "Wont"]

        if not others:
            # Excluded: only ever appeared in Won't Have.
            continue

        final_tier = others[0]
        if len(set(others)) > 1:
            warnings.append(
                f"Duplicate {req_id} found across tiers; first occurrence "
                f"({final_tier} Have) wins"
            )
        if had_wont:
            warnings.append(
                f"{req_id} appears in both Won't Have and {final_tier} Have; "
                f"using {final_tier} Have"
            )

        tier_by_id[req_id] = final_tier

    # Supersession annotations (strikethrough + "superseded by D-x") never move
    # an ID between tiers — same fail-safe precedence as the rules above.
    for req_id in sorted(struck_ids & set(tier_by_id), key=sort_key):
        warnings.append(
            f"{req_id} is struck through (supersession annotation) but stays "
            f"registered at {tier_by_id[req_id]} Have; annotations never change tiers"
        )

    return tier_by_id, warnings, known_ids


# ---------------------------------------------------------------------------
# plan.md parsing
# ---------------------------------------------------------------------------


def split_task_blocks(text):
    """Split a plan.md body into [(task_number, block_text)] in document order."""
    matches = list(TASK_HEADING_RE.finditer(text))
    blocks = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match.group(1), text[start:end]))
    return blocks


def parse_plan(text):
    """Parse a plan.md body into (covered_ids, warnings).

    Raises GateError if no `## Task N:` blocks are found.
    """
    warnings = []
    blocks = split_task_blocks(text)
    if not blocks:
        raise GateError("no task blocks found in plan")

    covered = set()
    for task_number, block in blocks:
        field_line = None
        for line in block.split("\n"):
            if COVERED_FIELD_RE.search(line):
                field_line = line
                break

        if field_line is None:
            warnings.append(f"Task {task_number} has no 'Requirements covered:' field")
            continue

        covered |= {token.upper() for token in ID_TOKEN_RE.findall(field_line)}

    return covered, warnings


# ---------------------------------------------------------------------------
# plan-mode lints
# ---------------------------------------------------------------------------


def _failure(check, task, detail):
    return {"check": check, "task": task, "detail": detail}


def lint_literal_counts(blocks):
    """Flag transcribed artifact-inventory counts in task text."""
    failures = []
    for task_number, block in blocks:
        seen = set()
        for match in LITERAL_COUNT_RE.finditer(block):
            phrase = " ".join(match.group(0).split()).lower()
            if phrase in seen:
                continue
            seen.add(phrase)
            failures.append(
                _failure(
                    "literal-count",
                    task_number,
                    f"hardcoded count \"{phrase}\": assert set-equality against the "
                    f"source table instead of transcribing a number",
                )
            )
    return failures


def _boundary_contract_text(block):
    """Return the `**Boundary contracts:**` field text, or None if absent.

    The field is the marker line plus any continuation lines up to the first
    blank line, next `**Field:**` line, or next heading.
    """
    collected = []
    capturing = False
    for line in block.split("\n"):
        if not capturing:
            if BOUNDARY_FIELD_RE.search(line):
                capturing = True
                collected.append(line)
            continue
        if not line.strip() or heading_level(line) is not None or FIELD_START_RE.match(line):
            break
        collected.append(line)

    return "\n".join(collected) if capturing else None


def _contract_identifiers(field_text):
    """Return (consumes, provides) lists of normalized identifiers."""
    result = {"consumes": [], "provides": []}
    for match in CONTRACT_TOKEN_RE.finditer(field_text):
        keyword = match.group(1).lower()
        for part in match.group(2).split(","):
            token_match = IDENTIFIER_RE.search(part.replace("`", " "))
            if not token_match:
                continue
            identifier = token_match.group(0).strip("./-").lower()
            if identifier and identifier not in EMPTY_VALUES:
                result[keyword].append(identifier)
    return result["consumes"], result["provides"]


def lint_boundary_contracts(blocks):
    """Every consumed identifier must be provided by a lower-numbered task."""
    providers = {}  # identifier -> sorted task numbers that provide it
    consumers = []  # (task_int, task_number, identifier)

    for task_number, block in blocks:
        field_text = _boundary_contract_text(block)
        if field_text is None:
            continue  # optional field: absence is never a failure
        consumes, provides = _contract_identifiers(field_text)
        task_int = int(task_number)
        for identifier in provides:
            providers.setdefault(identifier, []).append(task_int)
        for identifier in consumes:
            consumers.append((task_int, task_number, identifier))

    failures = []
    reported = set()
    for task_int, task_number, identifier in consumers:
        produced_by = providers.get(identifier, [])
        if any(number < task_int for number in produced_by):
            continue
        if (task_number, identifier) in reported:
            continue
        reported.add((task_number, identifier))
        if produced_by:
            where = ", ".join(f"Task {n}" for n in sorted(set(produced_by)))
            detail = (
                f"consumes '{identifier}' but it is only provided by {where}; "
                f"a consumed identifier must be provided by a lower-numbered task"
            )
        else:
            detail = (
                f"consumes '{identifier}' but no task provides it; add a "
                f"'provides: {identifier}' contract to a lower-numbered task"
            )
        failures.append(_failure("consumes-provides", task_number, detail))
    return failures


def lint_path_hygiene(blocks):
    """Absolute paths, UNC paths, file:/// URIs and repo-escaping relative paths."""
    checks = (
        ("file:/// URI", FILE_URI_RE),
        ("absolute path", WINDOWS_ABS_PATH_RE),
        ("UNC path", UNC_PATH_RE),
        ("repo-escaping relative path", REL_ESCAPE_RE),
    )

    failures = []
    for task_number, block in blocks:
        claimed = []  # spans already reported, so file:///C:/x counts once
        reported = set()
        for label, pattern in checks:
            for match in pattern.finditer(block):
                if any(match.start() < end and start < match.end() for start, end in claimed):
                    continue
                claimed.append((match.start(), match.end()))
                text = match.group(0)
                if (label, text) in reported:
                    continue
                reported.add((label, text))
                failures.append(
                    _failure(
                        "path-hygiene",
                        task_number,
                        f"{label} \"{text}\": reference files by repo-relative path "
                        f"inside this plan's own repository",
                    )
                )
    return failures


def run_plan_lints(text):
    """Run every plan-mode lint over a plan.md body."""
    blocks = split_task_blocks(text)
    return (
        lint_literal_counts(blocks)
        + lint_boundary_contracts(blocks)
        + lint_path_hygiene(blocks)
    )


# ---------------------------------------------------------------------------
# detailed-design.md parsing + design-mode lint
# ---------------------------------------------------------------------------


def extract_register_section(text):
    """Return the register section's lines, or None if the section is absent.

    The section opens at a `## Divergence & Supersession Register` heading
    (leading section numbering tolerated) and closes at the next heading of the
    same-or-higher level, so its `###` subsections are included.
    """
    collected = None
    open_level = None
    for line in text.split("\n"):
        level = heading_level(line)
        if collected is None:
            if level is not None and REGISTER_HEADING_RE.match(line):
                collected = []
                open_level = level
            continue
        if level is not None and level <= open_level:
            break
        collected.append(line)
    return collected


def parse_design_register(text):
    """Parse a detailed-design.md body into (rows, warnings).

    `rows` is [(row_label, [ids])] in document order for every register table
    row whose subject cells cite at least one FR/NFR id. An absent register
    section is a warning, never a failure: a greenfield design may have zero
    divergences.
    """
    warnings = []
    section = extract_register_section(text)
    if section is None:
        warnings.append(
            "design has no 'Divergence & Supersession Register' section; "
            "no supersession rows to check"
        )
        return [], warnings

    rows = []
    for index, line in enumerate(section, start=1):
        if not TABLE_ROW_RE.match(line) or TABLE_SEPARATOR_RE.match(line):
            continue

        cells = line.strip().strip("|").split("|")
        subject = "|".join(cells[:SUBJECT_CELL_COUNT])

        ids = []
        for token in ID_TOKEN_RE.findall(subject):
            token = token.upper()
            if token not in ids:
                ids.append(token)
        if not ids:
            continue

        label = " ".join(ROW_LABEL_CLEAN_RE.sub(" ", cells[0]).split())
        rows.append((label or f"row {index}", ids))

    if not rows:
        warnings.append(
            "register section has no table row citing an FR/NFR id; "
            "no supersession annotations to check"
        )

    return rows, warnings


def requirement_blocks(text):
    """Map each bold-declared FR/NFR id to its block text in requirements.md.

    A block runs from a line carrying a `**FR-n**`/`**NFR-n**` bold id to the
    next such line. An id declared more than once owns all of its blocks.
    """
    blocks = {}
    current_ids = []
    current_lines = []

    def flush():
        if not current_ids:
            return
        block = "\n".join(current_lines)
        for req_id in current_ids:
            blocks.setdefault(req_id, []).append(block)

    for line in text.split("\n"):
        ids = []
        for match in ANY_BOLD_ID_RE.finditer(line):
            req_id = match.group(1).upper()
            if req_id not in ids:
                ids.append(req_id)
        if ids:
            flush()
            current_ids = ids
            current_lines = [line]
        elif current_ids:
            current_lines.append(line)
    flush()

    return {req_id: "\n".join(parts) for req_id, parts in blocks.items()}


def lint_supersession_annotations(requirements_text, rows, known_ids):
    """Every register row's subject requirement must be annotated in requirements.md.

    An annotation is any of: strikethrough (`~~`), a "supersed*" word, or a
    citation of the register row's own id (`SUP-01`, `DIV-07`, ...). The row-id
    citation is the real routing link and the only marker every observed
    annotation carries — real annotations say "REINTERPRETED by SUP-05",
    "SCOPE PINNED by SUP-06", "SUPERSEDED IN PART by SUP-02", so a verb
    whitelist would reject correctly-annotated requirements.

    Scope limit (deliberate): this verifies rows-that-exist route back to an
    annotation. It cannot see a divergence that was never filed in the register
    at all — that stays with the Phase 2.5 review gate.
    """
    blocks = requirement_blocks(requirements_text)
    failures = []
    reported = set()

    for label, ids in rows:
        row_id_match = REGISTER_ROW_ID_RE.search(label.upper())
        row_id = row_id_match.group(1) if row_id_match else None
        for req_id in ids:
            if req_id not in known_ids:
                continue  # unknown id: handled by the warning path
            if (label, req_id) in reported:
                continue
            block = blocks.get(req_id, "")
            if SUPERSESSION_ANNOTATION_RE.search(block):
                continue
            if row_id and re.search(rf"\b{re.escape(row_id)}\b", block, re.IGNORECASE):
                continue
            reported.add((label, req_id))
            failures.append(
                _failure(
                    "supersession-annotation",
                    label,
                    f"register row names {req_id} but requirements.md carries no "
                    f"supersession annotation on it; annotate {req_id} in place "
                    f"(strikethrough and/or a note citing {row_id or 'the row'}) "
                    f"or drop it from the register row's subject",
                )
            )
    return failures


# ---------------------------------------------------------------------------
# test-report.md parsing
# ---------------------------------------------------------------------------


def parse_test_report(text):
    """Parse a test-report.md body into (status_by_id, warnings).

    Latest status-bearing mention of an ID wins. IDs whose only mentions
    lack a status token get a warning and are not considered covered.
    """
    warnings = []
    status_by_id = {}
    mentioned_ids = set()
    status_bearing_ids = set()

    for line in text.split("\n"):
        ids_in_line = {token.upper() for token in ID_TOKEN_RE.findall(line)}
        if not ids_in_line:
            continue

        mentioned_ids |= ids_in_line
        has_fail = bool(FAIL_TOKEN_RE.search(line))
        has_pass = bool(PASS_TOKEN_RE.search(line))

        if has_fail or has_pass:
            status = "FAIL" if has_fail else "PASS"  # both present => conservative FAIL
            for req_id in ids_in_line:
                status_by_id[req_id] = status
                status_bearing_ids.add(req_id)

    for req_id in sorted(mentioned_ids - status_bearing_ids, key=sort_key):
        warnings.append(f"{req_id} is only ever mentioned without a status token")

    return status_by_id, warnings


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _base_report(mode, requirements_path, target_path):
    return {
        "mode": mode,
        "requirements_file": requirements_path,
        "target_file": target_path,
        "must_have": [],
        "should_have": [],
        "covered": [],
        "uncovered": [],
        "uncovered_should": [],
        "warnings": [],
        "lint_failures": [],
        "result": "ERROR",
        "error": None,
    }


def build_report(mode, requirements_path, target_path):
    report = _base_report(mode, requirements_path, target_path)

    requirements_text, read_error = read_text(requirements_path)
    if requirements_text is None:
        report["error"] = f"cannot read requirements file '{requirements_path}': {read_error}"
        return report

    tier_by_id, requirement_warnings, known_ids = parse_requirements(requirements_text)
    report["warnings"].extend(requirement_warnings)

    must_have = sorted((i for i, t in tier_by_id.items() if t == "Must"), key=sort_key)
    should_have = sorted((i for i, t in tier_by_id.items() if t == "Should"), key=sort_key)
    report["must_have"] = must_have
    report["should_have"] = should_have

    if not must_have:
        report["error"] = "no Must-Have requirements found"
        return report

    target_text, read_error = read_text(target_path)
    if target_text is None:
        kind = {"plan": "plan", "design": "design"}.get(mode, "test report")
        report["error"] = f"cannot read {kind} file '{target_path}': {read_error}"
        return report

    if mode == "design":
        rows, design_warnings = parse_design_register(target_text)
        cited_ids = {req_id for _label, ids in rows for req_id in ids}
        for unknown_id in sorted(cited_ids - known_ids, key=sort_key):
            design_warnings.append(
                f"unknown requirement ID {unknown_id} cited in design register"
            )
        report["warnings"].extend(design_warnings)
        report["lint_failures"] = lint_supersession_annotations(
            requirements_text, rows, known_ids
        )
        report["result"] = "FAIL" if report["lint_failures"] else "PASS"
        return report

    try:
        if mode == "plan":
            covered_ids, target_warnings = parse_plan(target_text)
            unknown_ids = sorted(covered_ids - known_ids, key=sort_key)
            for unknown_id in unknown_ids:
                target_warnings.append(f"unknown requirement ID {unknown_id} cited in plan")
            report["lint_failures"] = run_plan_lints(target_text)
        else:
            status_by_id, target_warnings = parse_test_report(target_text)
            covered_ids = {i for i, status in status_by_id.items() if status == "PASS"}
    except GateError as exc:
        report["error"] = str(exc)
        return report

    report["warnings"].extend(target_warnings)

    covered_known = covered_ids & known_ids
    report["covered"] = sorted(covered_known, key=sort_key)
    report["uncovered"] = sorted(set(must_have) - covered_known, key=sort_key)
    report["uncovered_should"] = sorted(set(should_have) - covered_known, key=sort_key)
    report["result"] = "FAIL" if (report["uncovered"] or report["lint_failures"]) else "PASS"

    return report


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def run_self_test():
    import unittest

    scripts_dir = str(Path(__file__).parent)
    loader = unittest.TestLoader()
    suite = loader.discover(scripts_dir, pattern="test_check_coverage.py", top_level_dir=scripts_dir)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _selected_mode(args):
    """Return (mode, target) for whichever target flag was given, else (None, None)."""
    for mode, target in (("plan", args.plan), ("test", args.test_report), ("design", args.design)):
        if target is not None:
            return mode, target
    return None, None


def _print_usage_error(args, message):
    mode, target = _selected_mode(args)
    report = _base_report(mode, args.requirements, target)
    report["error"] = message
    print(json.dumps(report))


def main(argv):
    parser = argparse.ArgumentParser(
        prog="check_coverage.py",
        description="Deterministic requirements coverage gate for bgPDD pipelines.",
    )
    parser.add_argument("--requirements")
    parser.add_argument("--plan")
    parser.add_argument("--test-report")
    parser.add_argument("--design")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    given = [t for t in (args.plan, args.test_report, args.design) if t is not None]
    if len(given) != 1:
        _print_usage_error(
            args, "exactly one of --plan, --test-report or --design is required"
        )
        return 2

    if args.requirements is None:
        _print_usage_error(args, "--requirements is required")
        return 2

    mode, target = _selected_mode(args)

    report = build_report(mode, args.requirements, target)
    print(json.dumps(report))

    if report["result"] == "ERROR":
        return 2
    if report["result"] == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
