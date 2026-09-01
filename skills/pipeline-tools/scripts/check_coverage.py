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
import bisect
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
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
# BLOCKED: a check whose precondition was absent, so nothing ran. Required by
# agents/quinn.md §6 and base-persona.md's Evidence Integrity section; without
# a machine-visible slot an honest agent must either write FAIL (which asserts
# a test ran and failed — a different fabrication) or omit the line (which
# hides the gap). Status-bearing, and counted as NOT covered.
#
# Deliberate divergence (CLAUDE.md convention #8) from check_agent_report.py's
# four-token grammar: NOT RUN is deliberately absent here. In the coverage
# ledger omission already means "not run" — parse_test_report() already warns
# on a status-less mention and leaves the ID uncovered — so a fourth token
# would add a second spelling for a state the gate already reports.
BLOCKED_TOKEN_RE = re.compile(r"\bBLOCKED\b", re.IGNORECASE)
STRUCK_ID_RE = re.compile(r"~~[^~]*?\*\*((?:FR|NFR)-\d+)\*\*[^~]*?~~", re.IGNORECASE)

# --- test-mode ledger-line grammar ----------------------------------------
# A Coverage Ledger entry is a LIST ITEM (`- FR-3: PASS — evidence`). Bare
# prose that merely happens to contain an id and the word "pass" is not a
# claim anyone wrote as a status, and it used to count as coverage: the
# sentence "FR-1 and FR-2 both pass the smoke test" silently covered two
# Must-Haves. A non-list line is now a status-LESS mention (warned, uncovered).
LEDGER_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
# What a PASS must cite. This is the grammar Quinn already emits (agents/
# quinn.md §6): the executed command with its exit code, a `file::test-name`
# reference, or a runtime-evidence capture. Everything else — "verified",
# "looks good", "I did not run anything" — is prose, and a PASS resting on
# prose is `unevidenced` and counts as NOT covered.
EVIDENCE_EXIT_RE = re.compile(r"\bexit(?:\s+code)?\s+-?\d+\b", re.IGNORECASE)
EVIDENCE_RUNTIME_RE = re.compile(
    r"\*\*Runtime\s+evidence:\*\*|evidence[\\/]runtime[\\/]", re.IGNORECASE)
EVIDENCE_TEST_REF_RE = re.compile(r"\S+::\S+")

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
# A keyword's identifier list ends where prose begins. An internal dot inside
# an identifier (`api.mode.ruling`) is never followed by whitespace, so `. `
# (dot+whitespace) is a safe sentence-break terminator; ` — ` (space-emdash-
# space) is the other observed prose-introduction shape.
SENTENCE_BREAK_RE = re.compile(r"\.\s|\s—\s")

# --- domain-tag lint vocabulary --------------------------------------------
# Contract authority: planning-and-task-breakdown/SKILL.md — every task's
# `**Tags:**` line carries exactly one domain tag, and a milestone heading
# carries its domain tag beside `[vs:<surface>]`. Uppercase by contract: the
# lowercase `[vs:...]` grammar exists specifically so the two never collide.
TAGS_FIELD_RE = re.compile(r"\*\*Tags:\*\*", re.IGNORECASE)
DOMAIN_TAG_RE = re.compile(r"\[(UI|API)\]")

# --- runtime-criterion lint vocabulary ------------------------------------
# Milestone block extents MUST stay consistent with next_milestone.py's
# parse_milestones(): level-2 OR level-3 `Milestone <n>` headings open a block;
# the block runs to the next milestone heading or the next level-2 heading
# whose text starts with neither "Task" nor "Checkpoint". If that parser's
# extents change, change these with it — a checkpoint that falls outside its
# milestone here loses the `[vs:<surface>]` tag that decides which probe
# fields this lint requires.
MILESTONE_HEADING_RE = re.compile(r"^#{2,3}\s*Milestone\b\s+\d")
LEVEL2_HEADING_RE = re.compile(r"^##(?!#)\s*(.*)$")
# Level-3 `### Checkpoint:` is the canonical writer form. Level-2 is the
# deprecated form next_milestone.py tolerates-with-a-warning inside a block;
# both are linted here so the deprecated spelling is not an escape hatch from
# the probe requirement.
CHECKPOINT_HEADING_RE = re.compile(r"^#{2,3}\s*Checkpoint\b", re.IGNORECASE)
HEADING_TEXT_RE = re.compile(r"^#+\s*")
LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s")
# Verification-surface tag — duplicated verbatim from next_milestone.py's
# VS_TAG_RE. Same heading-line-wins-then-scan-the-block semantics.
VS_TAG_RE = re.compile(r"\[vs:([a-z+]{2,12})\]")
# Surfaces whose evidence is a response, so the probe must declare what to
# assert on it (planning-and-task-breakdown/SKILL.md).
RESPONSE_SURFACES = ("api", "web+api", "fn")
PROBE_MARKER_RE = re.compile(r"RUNTIME\s+PROBE\s*:", re.IGNORECASE)
JUSTIFICATION_RE = re.compile(r"\bjustification\s*:", re.IGNORECASE)
# Same shape as CONTRACT_TOKEN_RE: a keyword's value runs to the next `;`,
# newline, or sibling keyword. Scope limit: a `;` inside a probe command
# therefore truncates the value — the documented cost of a `;`-delimited
# field grammar shared with `Boundary contracts:`.
PROBE_FIELD_RE = re.compile(
    r"\b(start|probe|expect-status|require-keys|justification)\s*:\s*"
    r"((?:(?!\b(?:start|probe|expect-status|require-keys|justification)\s*:)[^\n;])*)",
    re.IGNORECASE,
)
# Transports that never open a socket, and commands that prove the code was
# written rather than that it runs. Both tuples are duplicated VERBATIM from
# check_runtime_evidence.py (IN_PROCESS_TELLS / NON_RUNTIME_PROBE_RES) and must
# stay identical: this lint rejects at plan time exactly what that gate rejects
# at evidence time. Duplicated rather than imported — this script family has no
# shared module by convention (GateError is duplicated in 7 files).
IN_PROCESS_TELLS = (
    "webapplicationfactory", "createclient(", "testserver", "testclient",
    "supertest", "mockmvc", "asgitransport", "rack-test", "httptestingcontroller",
    "inmemorytransport", "app.test_client(",
    # Honest self-descriptions of an in-process probe. A framework name is the
    # strong signal; these catch the author who describes the transport in prose
    # instead ("direct handler call", "in-process HTTP"). They do nothing against
    # someone who misdescribes the transport -- but nothing here does, and the
    # list is documented as a blocklist and therefore incomplete.
    "in-process", "in process", "direct handler", "handler directly",
    "direct invocation", "invoked directly", "same process",
)
NON_RUNTIME_PROBE_RES = (
    re.compile(r"\b(?:dotnet|go|cargo|mvn|gradle)\s+(?:build|restore|compile)\b"),
    re.compile(r"\b(?:dotnet|go|cargo|mvn|gradle)\s+test\b"),
    # `node --test` is flag-shaped rather than subcommand-shaped, so it slipped
    # past every pattern here and a capture declaring it passed the gate with a
    # hand-written envelope body: the same escape this file exists to stop,
    # through a different hole. Found 2026-08-12 by the eval fixture.
    re.compile(r"\bnode\s+--test\b"),
    re.compile(r"\b(?:deno|bun|swift|rails|ctest)\s+test\b"),
    re.compile(r"\b(?:rspec|phpunit|vstest|testcafe|minitest)\b"),
    re.compile(r"\b(?:npm|pnpm)\s+(?:ci|test|run\s+(?:build|test))\b"),
    re.compile(r"\byarn\s+(?:build|test)\b"),
    re.compile(r"\b(?:pytest|jest|vitest|mocha|karma|nunit|xunit)\b"),
    re.compile(r"\btsc\b|--no-?emit\b|\bmsbuild\b"),
    re.compile(r"\b(?:grep|rg|ripgrep|findstr|ack)\b"),
    re.compile(r"\bmake\s+(?:build|all)\b"),
)

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


def _truncate_at_sentence_break(text):
    """Cut a keyword's raw identifier-list text at the first sentence break.

    A machine-parseable `provides:`/`consumes:` line is sometimes followed by
    explanatory prose on the same physical line (no `;`, no newline, no next
    keyword). That prose's own commas would otherwise get comma-split into
    fake identifiers. Terminators: `. ` (dot+whitespace) and ` — `
    (space-emdash-space) — see SENTENCE_BREAK_RE.
    """
    match = SENTENCE_BREAK_RE.search(text)
    return text[: match.start()] if match else text


def _contract_identifiers(field_text):
    """Return (consumes, provides) lists of normalized identifiers."""
    result = {"consumes": [], "provides": []}
    for match in CONTRACT_TOKEN_RE.finditer(field_text):
        keyword = match.group(1).lower()
        list_text = _truncate_at_sentence_break(match.group(2))
        for part in list_text.split(","):
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


def split_milestone_blocks(lines):
    """[(title, heading_line, start_index, end_index)] per milestone heading.

    Mirrors next_milestone.py's parse_milestones() block extents exactly — see
    the note on MILESTONE_HEADING_RE; the two must stay consistent. One
    deliberate difference: this returns an empty list rather than raising when
    a plan declares no milestone headings, because the coverage gate also runs
    against plans that predate the milestone convention and next_milestone.py
    already halts the build on a milestone-less plan.
    """
    milestone_idxs = [i for i, line in enumerate(lines) if MILESTONE_HEADING_RE.match(line)]
    if not milestone_idxs:
        return []

    terminator_idxs = set(milestone_idxs)
    for index, line in enumerate(lines):
        match = LEVEL2_HEADING_RE.match(line)
        if not match:
            continue
        heading_text = match.group(1).strip().lower()
        if heading_text.startswith("task") or heading_text.startswith("checkpoint"):
            continue  # stays inside the block
        terminator_idxs.add(index)
    terminator_idxs = sorted(terminator_idxs)

    blocks = []
    for index in milestone_idxs:
        position = bisect.bisect_right(terminator_idxs, index)
        end = terminator_idxs[position] if position < len(terminator_idxs) else len(lines)
        blocks.append((HEADING_TEXT_RE.sub("", lines[index]).rstrip(), lines[index], index, end))
    return blocks


def milestone_surface(heading_line, block_text):
    """The `[vs:<surface>]` key, or None when absent.

    Duplicated semantics from next_milestone.py's milestone_surface(): the
    heading line wins when it carries a tag, otherwise the whole block is
    scanned. The raw key is returned even when invalid so a typo never reads
    as an omission.
    """
    match = VS_TAG_RE.search(heading_line) or VS_TAG_RE.search(block_text)
    return match.group(1).lower() if match else None


def checkpoint_blocks(lines):
    """[(index, label, block_text)] for every checkpoint heading in a plan.

    A checkpoint block runs from its heading to the next heading of ANY level,
    or EOF. Because a milestone block always ends at a heading, this extent is
    identical whether computed plan-wide or within one milestone.
    """
    blocks = []
    for index, line in enumerate(lines):
        if not CHECKPOINT_HEADING_RE.match(line):
            continue
        stop = len(lines)
        for follow in range(index + 1, len(lines)):
            if heading_level(lines[follow]) is not None:
                stop = follow
                break
        blocks.append((index, HEADING_TEXT_RE.sub("", line).rstrip(),
                       "\n".join(lines[index:stop])))
    return blocks


def _probe_text(block):
    """The `RUNTIME PROBE:` field text, or None when the line is absent.

    Continuation lines fold in until a blank line, a heading, or a new list
    item — the same field-extent rule as _boundary_contract_text.
    """
    lines = block.split("\n")
    for index, line in enumerate(lines):
        match = PROBE_MARKER_RE.search(line)
        if not match:
            continue
        collected = [line[match.end():]]
        for follow in lines[index + 1:]:
            if (not follow.strip()
                    or heading_level(follow) is not None
                    or LIST_ITEM_RE.match(follow)):
                break
            collected.append(follow)
        return "\n".join(collected)
    return None


def _probe_fields(probe_text):
    """{keyword: value} for the probe line; first occurrence of a keyword wins."""
    fields = {}
    for match in PROBE_FIELD_RE.finditer(probe_text):
        fields.setdefault(match.group(1).lower(), match.group(2).strip().strip("`").strip())
    return fields


def _field_absent(fields, name):
    value = fields.get(name, "")
    return not value or value.lower() in EMPTY_VALUES


def _checkpoint_failures(task_label, checkpoint, surface, block):
    """Every runtime-criterion failure for one checkpoint block."""
    probe_text = _probe_text(block)
    if probe_text is None:
        # Single root cause: with no probe line at all, every field is missing.
        return [
            _failure(
                "runtime-criterion",
                task_label,
                f"checkpoint \"{checkpoint}\" carries no 'RUNTIME PROBE:' line; add "
                f"'RUNTIME PROBE: start: <start command>; probe: <probe command>; "
                f"expect-status: <N>; require-keys: <k1, k2>' so the exit criterion "
                f"is executable by someone other than its author",
            )
        ]

    fields = _probe_fields(probe_text)
    probe_missing = _field_absent(fields, "probe")
    failures = []

    if surface == "none":
        # `[vs:none]` replaces the probe fields with a justification sentence.
        # Presence only: no gate can check whether a sentence is true.
        if "justification" not in fields and not JUSTIFICATION_RE.search(block):
            failures.append(
                _failure(
                    "runtime-criterion",
                    task_label,
                    f"checkpoint \"{checkpoint}\" is on a [vs:none] milestone but "
                    f"carries no 'justification:' field; [vs:none] is an explicit, "
                    f"reviewable claim that nothing is observable, not an exemption "
                    f"from declaring one",
                )
            )
    elif probe_missing:
        failures.append(
            _failure(
                "runtime-criterion",
                task_label,
                f"checkpoint \"{checkpoint}\" declares no 'probe:' command; an exit "
                f"criterion that names no command is satisfied by opinion",
            )
        )

    if not probe_missing:
        probe = fields["probe"].lower()
        for tell in IN_PROCESS_TELLS:
            if tell in probe:
                failures.append(
                    _failure(
                        "runtime-criterion",
                        task_label,
                        f"checkpoint \"{checkpoint}\" probe names an IN-PROCESS test "
                        f"client ({tell!r}); an in-process observation can fail a wire "
                        f"claim but never pass one — probe the running system over its "
                        f"real transport",
                    )
                )
                break
        for pattern in NON_RUNTIME_PROBE_RES:
            match = pattern.search(probe)
            if match:
                failures.append(
                    _failure(
                        "runtime-criterion",
                        task_label,
                        f"checkpoint \"{checkpoint}\" probe is a build/typecheck/search/"
                        f"test-runner command ({match.group(0)!r}), not a runtime probe; "
                        f"it proves the code was written or that a suite is green, never "
                        f"that the running system emits this",
                    )
                )
                break

    if surface in RESPONSE_SURFACES:
        missing = [name for name in ("expect-status", "require-keys")
                   if _field_absent(fields, name)]
        if missing:
            failures.append(
                _failure(
                    "runtime-criterion",
                    task_label,
                    f"checkpoint \"{checkpoint}\" is on a [vs:{surface}] milestone but "
                    f"its probe declares no " + " and no ".join(f"'{n}:'" for n in missing)
                    + "; these become check_runtime_evidence.py's --expect-status / "
                    "--require-key arguments verbatim, so a surface whose evidence is a "
                    "response must say what to assert on it",
                )
            )

    return failures


def lint_runtime_criterion(text):
    """Every checkpoint's `RUNTIME PROBE:` line must be executable and complete.

    Scope limits (deliberate): a plan with no `### Checkpoint:` block yields no
    failures — the presence of checkpoints is Step 5's own review item, and
    making absence a failure here would retroactively fail every plan written
    before the convention. A checkpoint outside every milestone block has no
    surface, so only the surface-independent rules apply. The probe itself is
    never executed: this lint checks the SHAPE of the declared command, and
    check_runtime_evidence.py gates the capture it later produces.
    """
    lines = text.split("\n")
    milestones = split_milestone_blocks(lines)

    failures = []
    for index, label, block in checkpoint_blocks(lines):
        owner = next((m for m in milestones if m[2] <= index < m[3]), None)
        if owner is None:
            task_label, surface = label, None
        else:
            title, heading_line, start, end = owner
            task_label = title
            surface = milestone_surface(heading_line, "\n".join(lines[start:end]))
        failures.extend(_checkpoint_failures(task_label, label, surface, block))
    return failures


def _tags_field_text(block):
    """The `**Tags:**` field text, or None if the field is absent.

    Same extent rule as _boundary_contract_text: the marker line plus any
    continuation lines up to the first blank line, next `**Field:**` line, or
    next heading.
    """
    collected = []
    capturing = False
    for line in block.split("\n"):
        if not capturing:
            if TAGS_FIELD_RE.search(line):
                capturing = True
                collected.append(line)
            continue
        if not line.strip() or heading_level(line) is not None or FIELD_START_RE.match(line):
            break
        collected.append(line)

    return "\n".join(collected) if capturing else None


def lint_domain_tags(text):
    """Every task declares exactly one domain tag; every milestone is
    domain-homogeneous under a domain-tagged heading.

    Contract authority: planning-and-task-breakdown/SKILL.md. Installed per
    CLAUDE.md convention #9 after the alex-domain-tags eval showed the prose
    rule violated in 10 of 10 runs across two wordings — untagged tasks are
    unroutable (next_milestone.py's [UI]/[API] routing) and a mixed milestone
    is rejected as MIXED at build time, so both defects must die at plan time.
    Scope limit (mirrors lint_runtime_criterion): a plan with no milestone
    headings skips the homogeneity half — the per-task rule applies always.
    """
    lines = text.split("\n")
    failures = []

    domain_by_task = {}
    for task_number, block in split_task_blocks(text):
        field_text = _tags_field_text(block)
        if field_text is None:
            failures.append(
                _failure(
                    "domain-tag",
                    task_number,
                    "no **Tags:** line: every task declares exactly one domain "
                    "tag ([UI] or [API])",
                )
            )
            continue
        domains = set(DOMAIN_TAG_RE.findall(field_text))
        if len(domains) == 1:
            domain_by_task[task_number] = next(iter(domains))
        elif not domains:
            failures.append(
                _failure(
                    "domain-tag",
                    task_number,
                    "**Tags:** line carries no domain tag: exactly one of "
                    "[UI]/[API] is required (overlays [SEC]/[EXT]/[BLOCKED] "
                    "combine freely with either)",
                )
            )
        else:
            failures.append(
                _failure(
                    "domain-tag",
                    task_number,
                    "**Tags:** line carries both [UI] and [API]: a task has "
                    "exactly one domain — split the task",
                )
            )

    task_number_by_line = {}
    for index, line in enumerate(lines):
        match = TASK_HEADING_RE.match(line)
        if match:
            task_number_by_line[index] = match.group(1)

    for title, heading_line, start, end in split_milestone_blocks(lines):
        heading_domains = set(DOMAIN_TAG_RE.findall(heading_line))
        if len(heading_domains) != 1:
            failures.append(
                _failure(
                    "domain-tag",
                    title,
                    "milestone heading must carry exactly one domain tag "
                    "([UI] or [API]) beside its [vs:<surface>] tag",
                )
            )
            continue
        milestone_domain = next(iter(heading_domains))
        for index in range(start, end):
            task_number = task_number_by_line.get(index)
            if task_number is None:
                continue
            task_domain = domain_by_task.get(task_number)
            if task_domain is not None and task_domain != milestone_domain:
                failures.append(
                    _failure(
                        "domain-tag",
                        title,
                        f"mixed-domain milestone: Task {task_number} is "
                        f"[{task_domain}] inside a [{milestone_domain}] "
                        f"milestone — milestones are domain-homogeneous "
                        f"(next_milestone.py rejects MIXED at build time)",
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
        + lint_runtime_criterion(text)
        + lint_domain_tags(text)
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


def lint_fr_citations(design_text, must_have):
    """Every Must-Have FR/NFR ID must appear at least once in the design body.

    Deliberately distinct from supersession-annotation lint: this only
    proves citation presence, not that the design covers the requirement.

    Matching is whole-token (`ID_TOKEN_RE`), never substring — a design that
    cites only `FR-10` does not thereby cite `FR-1`. The naive `in` test this
    replaced silently passed every single-digit Must-Have on any requirements
    set with ten or more requirements.
    """
    cited = {token.upper() for token in ID_TOKEN_RE.findall(design_text)}
    failures = []
    for req_id in must_have:
        if req_id.upper() not in cited:
            failures.append({
                "check": "fr-citation",
                "task": req_id,
                "detail": (
                    f"Must-Have {req_id} is never cited in detailed-design.md"
                ),
            })
    return failures


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


def strip_fenced_blocks(text):
    """Blank out every ```/~~~ fenced region, preserving the line count.

    A `- FR-1: PASS — exit 0` inside a fence is a pasted transcript or a
    format example, not this round's claim — and since latest mention wins, a
    fenced example could overwrite a genuine FAIL. Applied in TEST MODE ONLY:
    plan-mode probes and design-mode register rows legitimately live inside
    fenced blocks, so stripping there would delete the lints' own inputs.

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


def pass_is_evidenced(line):
    """True when a PASS line cites something a reader could go and check.

    The gate is deterministic about the STATUS token and was completely
    trusting about the EVIDENCE beside it, so `- FR-1: PASS — I did not run
    anything` counted as coverage. Three accepted forms, matching what
    agents/quinn.md §6 already requires: an exit code, a runtime-evidence
    capture citation, or a `file::test-name` reference.

    SCOPE LIMIT: this checks the SHAPE of the citation, never its truth. A
    fabricated `exit 0` still passes here — check_runtime_evidence.py and the
    ledger are what make a citation costly to fake.
    """
    m = PASS_TOKEN_RE.search(line)
    rest = line[m.end():] if m else line
    return bool(EVIDENCE_EXIT_RE.search(rest)
                or EVIDENCE_RUNTIME_RE.search(rest)
                or EVIDENCE_TEST_REF_RE.search(rest))


def parse_test_report(text):
    """Parse a test-report.md body into (status_by_id, warnings).

    Latest status-bearing mention of an ID wins, so a BLOCKED line written
    after a stale PASS downgrades it. IDs whose only mentions lack a status
    token get a warning and are not considered covered.

    Precedence when one line carries several tokens: FAIL > BLOCKED > PASS.
    This extends the original "both PASS and FAIL on one line counts as FAIL"
    rule with the same conservative logic — the worst status on the line wins,
    and only PASS ever counts as covered.

    Two further conditions, both fail-safe:

    - a status is read only from a LIST ITEM (the ledger's own grammar);
      prose that merely contains an id and the word "pass" is a status-less
      mention, warned about and uncovered.
    - a PASS whose evidence text cites nothing checkable is recorded as
      `UNEVIDENCED`, which — like BLOCKED — is status-bearing and NOT covered.
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
        if not LEDGER_ITEM_RE.match(line):
            # Prose, not a ledger line. Falls through to the status-less
            # mention warning below.
            continue
        has_fail = bool(FAIL_TOKEN_RE.search(line))
        has_blocked = bool(BLOCKED_TOKEN_RE.search(line))
        has_pass = bool(PASS_TOKEN_RE.search(line))

        if has_fail or has_blocked or has_pass:
            # Worst status on the line wins: FAIL > BLOCKED > PASS.
            status = "FAIL" if has_fail else "BLOCKED" if has_blocked else "PASS"
            if status == "PASS" and not pass_is_evidenced(line):
                status = "UNEVIDENCED"
            for req_id in ids_in_line:
                status_by_id[req_id] = status
                status_bearing_ids.add(req_id)

    for req_id in sorted(mentioned_ids - status_bearing_ids, key=sort_key):
        warnings.append(f"{req_id} is only ever mentioned without a status token")
    for req_id in sorted((i for i, s in status_by_id.items()
                          if s == "UNEVIDENCED"), key=sort_key):
        warnings.append(
            f"{req_id}: latest PASS cites no checkable evidence — required is "
            "an exit code ('exit 0'), a 'file::test-name' reference, or an "
            "evidence/runtime/ capture citation; counted as NOT covered")

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
        "blocked": [],
        "unevidenced": [],
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
        report["lint_failures"] = (
            lint_supersession_annotations(requirements_text, rows, known_ids)
            + lint_fr_citations(target_text, must_have)
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
            status_by_id, target_warnings = parse_test_report(
                strip_fenced_blocks(target_text))
            covered_ids = {i for i, status in status_by_id.items() if status == "PASS"}
            # Reported the same way as `blocked`: unfiltered, so an id the
            # requirements never declared still surfaces. An UNEVIDENCED
            # Must-Have lands in `uncovered` and fails the gate.
            report["unevidenced"] = sorted(
                (i for i, status in status_by_id.items()
                 if status == "UNEVIDENCED"),
                key=sort_key,
            )
            # BLOCKED is reported verbatim — unfiltered by tier or known-ness,
            # so an ID the requirements never declared still surfaces here
            # rather than vanishing. Only PASS ever lands in `covered`, so a
            # Must-Have marked BLOCKED lands in `uncovered` and fails the gate:
            # honesty routes the work, it never passes it.
            report["blocked"] = sorted(
                (i for i, status in status_by_id.items() if status == "BLOCKED"),
                key=sort_key,
            )
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


def main(argv):
    parser = argparse.ArgumentParser(
        prog="check_coverage.py",
        description="Deterministic requirements coverage gate for bgPDD pipelines.",
    )
    parser.add_argument("--requirements")
    parser.add_argument("--plan")
    parser.add_argument("--test-report")
    parser.add_argument("--design")
    parser.add_argument("--ledger",
                        help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    _mode, _target = _selected_mode(args)

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, None,
                      [p for p in (args.requirements, _target) if p],
                      verdict, code)
        return code

    given = [t for t in (args.plan, args.test_report, args.design) if t is not None]
    if len(given) != 1:
        _print_usage_error(
            args, "exactly one of --plan, --test-report or --design is required"
        )
        return finish(2, "ERROR")

    if args.requirements is None:
        _print_usage_error(args, "--requirements is required")
        return finish(2, "ERROR")

    mode, target = _selected_mode(args)

    report = build_report(mode, args.requirements, target)
    print(json.dumps(report))

    if report["result"] == "ERROR":
        return finish(2, "ERROR")
    if report["result"] == "FAIL":
        return finish(1, "FAIL")
    return finish(0, "PASS")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
