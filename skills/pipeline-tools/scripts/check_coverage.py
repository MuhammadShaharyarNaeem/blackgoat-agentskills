#!/usr/bin/env python3
"""Deterministic coverage-gate CLI for the bgPDD pipelines.

Verifies every Must-Have FR/NFR in a requirements.md is covered either by
plan.md tasks (plan mode) or by passing tests in test-report.md (test mode).

Usage:
    python check_coverage.py --requirements <path> --plan <path>
    python check_coverage.py --requirements <path> --test-report <path>
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

    current_tier = None
    current_level = None

    for line in text.split("\n"):
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

    return tier_by_id, warnings, known_ids


# ---------------------------------------------------------------------------
# plan.md parsing
# ---------------------------------------------------------------------------


def parse_plan(text):
    """Parse a plan.md body into (covered_ids, warnings).

    Raises GateError if no `## Task N:` blocks are found.
    """
    warnings = []
    matches = list(TASK_HEADING_RE.finditer(text))
    if not matches:
        raise GateError("no task blocks found in plan")

    covered = set()
    for index, match in enumerate(matches):
        task_number = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[start:end]

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
        kind = "plan" if mode == "plan" else "test report"
        report["error"] = f"cannot read {kind} file '{target_path}': {read_error}"
        return report

    try:
        if mode == "plan":
            covered_ids, target_warnings = parse_plan(target_text)
            unknown_ids = sorted(covered_ids - known_ids, key=sort_key)
            for unknown_id in unknown_ids:
                target_warnings.append(f"unknown requirement ID {unknown_id} cited in plan")
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
    report["result"] = "FAIL" if report["uncovered"] else "PASS"

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


def _print_usage_error(args, message):
    target = args.plan if args.plan is not None else args.test_report
    mode = "plan" if args.plan is not None else ("test" if args.test_report is not None else None)
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
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if (args.plan is None) == (args.test_report is None):
        _print_usage_error(args, "exactly one of --plan or --test-report is required")
        return 2

    if args.requirements is None:
        _print_usage_error(args, "--requirements is required")
        return 2

    mode = "plan" if args.plan is not None else "test"
    target = args.plan if mode == "plan" else args.test_report

    report = build_report(mode, args.requirements, target)
    print(json.dumps(report))

    if report["result"] == "ERROR":
        return 2
    if report["result"] == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
