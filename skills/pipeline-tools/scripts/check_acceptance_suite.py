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
  3. every `Mode: manual` step — and every step whose Mode cell is
     present but UNRECOGNIZED, which fails closed to manual — cites an
     EXISTING evidence file under an `evidence/runtime/` directory; such
     a step on an agent's word alone reads as NOT RUN and blocks;
  4. every step marked `[inverse of N]` names a real step N in the same
     scenario (blocking, at any priority) and has a result of its own.

It additionally REPORTS (never blocks on) state-changing steps that
declare no inverse — see `undeclared_inverse` in the JSON and the
reasoning note below.

`--lint-only` is a SECOND MODE that gates matrix STRUCTURE at plan time,
before any code exists. It takes --matrix alone (--results is a usage
error) and runs only the checks the matrix can support by itself. Given
--requirements it additionally gates the FR->scenario LINK: every
Must-Have FR/NFR in requirements.md must be cited by at least one
scenario heading.

DELIBERATE MODE DIVERGENCE (CLAUDE.md convention #8 — this refines the
"undeclared_inverse is advisory, non-blocking" rule stated above rather
than contradicting it): in --lint-only mode `undeclared_inverse` BLOCKS.
Same signal, opposite posture, because both the COST of the fix and the
MEANING of green differ by phase. At build time the code is already
written, so blocking would ask Quinn to author a scenario Alex owed weeks
earlier, and a verb-allowlist heuristic must not block when green means
only "the heuristic found nothing". At plan time the matrix is the
artifact under authorship, the fix is a one-line edit, and there is
nothing else green could mean. The escape hatch is the same in both
modes: `[no inverse: <reason>]` on the row.

SCOPE LIMIT: in execution mode this gate verifies the matrix was EXECUTED
and EVIDENCED. It never verifies that a scenario is the RIGHT scenario,
that the ASSERT column asserts the right thing, or that the cited
evidence actually shows what the step claims. Choosing and wording the
scenarios is Alex's authoring judgment and stays reviewable prose; the
internal honesty of a runtime capture is check_runtime_evidence.py's job.

SCOPE LIMIT (--lint-only): structure only. It never judges whether a
scenario is worth running, whether its ASSERT column asserts the right
thing, or whether an exemption reason is TRUE. Exemption presence is
checkable; exemption truth is not. With --requirements it checks that a
Must-Have is CITED by a scenario — never that the scenario actually
exercises it; that judgment stays with the human reading the matrix.

Pure standard library.

Usage:
    python check_acceptance_suite.py --matrix <path> --results <path> \
        [--repo <dir>] [--require-priority P0[,P1]] [--min-scenarios <N>]
    python check_acceptance_suite.py --lint-only --matrix <path> \
        [--requirements <path>] [--min-scenarios <N>]
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
# Escape hatch for legitimately one-way steps: nothing un-queues a distributed
# job, nothing un-reinstalls. The reason text is REQUIRED — presence is
# checkable, truth is not, so the marker buys an author nothing but a place to
# be wrong in writing.
NO_INVERSE_RE = re.compile(r"\[\s*no\s+inverse\s*:\s*([^\]]*)\]", re.IGNORECASE)
LETTER_RE = re.compile(r"[A-Za-z]")

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
# The whole recognized Mode vocabulary. A typo like "Manual!" or an invented
# "semi" matches neither entry, so it must not be read as "auto" — see
# needs_manual_evidence() for how execution mode fails closed on it.
# --lint-only additionally BLOCKS on it, at the only time the fix is a
# one-character edit.
RECOGNIZED_MODES = ("auto", "manual")

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

# --- requirements.md tier vocabulary --------------------------------------
# Duplicated VERBATIM from check_coverage.py, together with heading_level(),
# sort_key() and parse_requirements() below, so the two gates recognize the
# SAME Must-Have document convention rather than two dialects of it. Duplicated
# rather than imported: this script family has no shared module by convention
# (GateError is already duplicated in seven files). If that parser's grammar
# changes, change this with it.
HEADING_RE = re.compile(r"^(#{1,6})(?:\s|$)")
TIER_HEADING_RE = re.compile(r"^#{2,4}\s*(Must|Should|Could|Won'?t)\s+Have", re.IGNORECASE)
FR_BOLD_RE = re.compile(r"\*\*(FR-\d+)\*\*", re.IGNORECASE)
NFR_BOLD_RE = re.compile(r"\*\*(NFR-\d+)\*\*", re.IGNORECASE)
NFR_TIER_RE = re.compile(r"-\s*\*\*(NFR-\d+)\*\*\s*\((Must|Should|Could)[^)]*\)", re.IGNORECASE)
STRUCK_ID_RE = re.compile(r"~~[^~]*?\*\*((?:FR|NFR)-\d+)\*\*[^~]*?~~", re.IGNORECASE)
ID_TOKEN_RE = re.compile(r"\b(?:FR|NFR)-\d+\b", re.IGNORECASE)


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
# requirements.md parsing (duplicated from check_coverage.py — see the note on
# HEADING_RE above; keep the two in step)
# ---------------------------------------------------------------------------

def sort_key(req_id):
    """Natural sort key so FR-2 sorts before FR-10."""
    prefix, number = req_id.split("-", 1)
    return (prefix, int(number))


def heading_level(line):
    match = HEADING_RE.match(line)
    return len(match.group(1)) if match else None


def parse_requirements(text):
    """Parse a requirements.md body.

    Returns (tier_by_id, warnings, known_ids):
      tier_by_id  -- {ID: "Must"|"Should"|"Could"} for every non-excluded ID
      warnings    -- list of warning strings
      known_ids   -- every ID that appeared anywhere (including Won't-Have),
                     used to detect "unknown ID cited in the matrix".
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
            events.append((req_id, match.group(2).lower().capitalize()))
            tier_tagged_ids.add(req_id)

        for match in NFR_BOLD_RE.finditer(line):
            req_id = match.group(1).upper()
            if req_id not in tier_tagged_ids:
                warnings.append(
                    f"{req_id} has a bold ID but no parseable tier tag; "
                    "defaulting to Must Have")
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
            continue  # Excluded: only ever appeared in Won't Have.
        final_tier = others[0]
        if len(set(others)) > 1:
            warnings.append(
                f"Duplicate {req_id} found across tiers; first occurrence "
                f"({final_tier} Have) wins")
        if had_wont:
            warnings.append(
                f"{req_id} appears in both Won't Have and {final_tier} Have; "
                f"using {final_tier} Have")
        tier_by_id[req_id] = final_tier

    for req_id in sorted(struck_ids & set(tier_by_id), key=sort_key):
        warnings.append(
            f"{req_id} is struck through (supersession annotation) but stays "
            f"registered at {tier_by_id[req_id]} Have; annotations never change tiers")

    return tier_by_id, warnings, known_ids


# ---------------------------------------------------------------------------
# Matrix parsing
# ---------------------------------------------------------------------------

def new_scenario(heading):
    """Build a scenario dict from a `## ` heading, or None if it names no id.

    The id is searched for OUTSIDE the parentheses. Requirement ids already live
    inside them by contract, so scanning the raw heading let a scenario with no
    id of its own silently adopt one: `## Mapping lifecycle — P0 — (FR-1)`
    parsed as `id: "FR-1"` and its result keys became `FR-1.1`. Failing to parse
    is the honest outcome — it lands in the prose-heading warning and, under
    --lint-only, in the too-few-scenarios block. Found 2026-08-12.
    """
    idm = SCENARIO_ID_RE.search(PAREN_RE.sub(" ", heading))
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
        "linted": False,
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
        # The raw declared value is captured BEFORE the "auto" default, because
        # "absent" and "present but unreadable" must not collapse into the same
        # token: the default is safe, an unreadable declaration is not.
        raw_mode = (cell("mode") or "").strip()
        mode = raw_mode.lower() or "auto"
        # SCOPE BOUNDARY: only a NON-EMPTY-after-strip cell can be flagged. An
        # empty cell — and every step in a table with no `Mode` column at all,
        # which predates the column — keeps defaulting to "auto" and is never
        # flagged. Retroactively making every step of a pre-column matrix
        # evidence-bearing would be a back-compat break, and --lint-only already
        # blocks the missing column at plan time.
        mode_unrecognized = bool(raw_mode) and mode not in RECOGNIZED_MODES
        do_text = cell("do")
        inv = INVERSE_RE.search(raw)
        stores = split_stores(cell("stores"))
        mutating = bool(MUTATING_VERB_RE.search(do_text.lower()))

        # `[no inverse: <reason>]` exemption. Validated identically in both
        # modes so the two reports stay diffable; only the POSTURE differs
        # (execution mode warns, --lint-only blocks).
        nom = NO_INVERSE_RE.search(raw)
        exempt_reason = nom.group(1).strip() if nom else None
        exempt, exempt_error = False, None
        if nom:
            if not exempt_reason or not LETTER_RE.search(exempt_reason):
                exempt_error = (
                    "'[no inverse: <reason>]' carries no reason text — the "
                    "reason is required and must contain at least one letter")
            elif inv is not None:
                exempt_error = (
                    f"declares both '[inverse of {inv.group(1)}]' and "
                    "'[no inverse: ...]' — a step cannot both have and lack "
                    "an inverse")
            else:
                exempt = True

        current["_steps"].append({
            "key": f"{current['id']}.{number}",
            "scenario": current["id"],
            "n": number,
            "go": cell("go"),
            "do": do_text,
            "assert": cell("assert"),
            "stores": stores,
            "mode": mode,
            "mode_unrecognized": mode_unrecognized,
            "inverse_of": int(inv.group(1)) if inv else None,
            "mutating_verb": mutating,
            "state_changing": mutating
                              and any(s not in READ_ONLY_STORES for s in stores),
            "exempt": exempt,
            "no_inverse_reason": exempt_reason,
            "exempt_error": exempt_error,
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

def is_undeclared_inverse(st, inverse_targets):
    """ONE predicate, two postures. A state-changing step that neither declares
    an inverse, nor is the target of one, nor is validly exempt. Execution mode
    reports it; --lint-only blocks on it (see the module docstring's labelled
    divergence)."""
    return (st["state_changing"]
            and not st["exempt"]
            and st["inverse_of"] is None
            and st["n"] not in inverse_targets)


def needs_manual_evidence(entry):
    """ONE predicate for "this step owes a runtime evidence citation".

    DELIBERATE DIVERGENCE (CLAUDE.md convention #8 — this refines the
    `MANUAL_MODES` evidence rule, which demanded evidence of `Mode: manual`
    alone): execution mode is now STRICTER. A present-but-unrecognized Mode
    also owes evidence.

    Fail-closed doctrine (base-persona.md, Evidence Integrity — "a gate you
    author fails closed"): of the two readings available
    for an unreadable Mode cell, `manual` is the one that DEMANDS evidence, so
    it must be the one an unrecognized value falls back to. Reading `semi` or
    `Manual!` as `auto` made a one-character typo the cheapest way to buy a
    device step out of the evidence gate, silently. `--lint-only` blocks such a
    matrix at plan time, but a matrix can be hand-edited between plan and
    build, so execution mode must fail closed on its own.

    Used at BOTH evidence sites — collection and the blocking check — so the
    two can never disagree about which steps are evidence-bearing.
    """
    return entry["mode"] in MANUAL_MODES or entry["mode_unrecognized"]


def new_report(args):
    """Pre-initialized report. EVERY key is present in BOTH modes so that the
    two modes' JSON can be diffed key-for-key; the arrays a mode cannot fill
    stay `[]`/`0`/`None`."""
    return {
        "matrix": args.matrix,
        "results": args.results,
        "requirements": args.requirements,
        "lint_only": bool(args.lint_only),
        "require_priority": None,
        "min_scenarios": args.min_scenarios,
        "scenarios": [],
        "gated_scenarios": [],
        "linted_scenarios": [],
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
        "exempt_steps": [],
        "invalid_exemption": [],
        "missing_priority": [],
        "missing_step_table": [],
        "missing_columns": [],
        "unrecognized_mode": [],
        "missing_stores": [],
        "duplicate_keys": [],
        "malformed_steps": [],
        "must_have": [],
        "should_have": [],
        "uncovered_should": [],
        "lint_failures": [],
        "extra_results": [],
        "warnings": [],
        "result": "FAIL",
        "error": None,
    }


def step_entry(st, **overrides):
    """A `steps` entry with an identical key set in both modes."""
    entry = {k: st[k] for k in
             ("key", "scenario", "n", "mode", "mode_unrecognized", "stores",
              "inverse_of", "state_changing", "exempt", "no_inverse_reason")}
    entry.update({"gated": False, "priority": None, "status": None,
                  "detail": None, "evidence": [], "evidence_ok": None,
                  "problems": []})
    entry.update(overrides)
    return entry


def build_report(args):
    report = new_report(args)

    wanted = parse_priority_filter(args.require_priority)
    report["require_priority"] = sorted(wanted) if wanted else None

    matrix_text = read_text(args.matrix)
    scenarios, parse_warnings = parse_matrix(matrix_text)
    report["warnings"].extend(parse_warnings)
    if not scenarios:
        raise GateError(
            f"no parseable scenario in {args.matrix} — a scenario is a '## ' "
            "heading naming an id like 'AS-2'; not a conforming acceptance matrix")

    if args.lint_only:
        return lint_report(report, scenarios, matrix_text, args)

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
            # Fail closed on a GATED scenario with no parsed steps. Deliberate
            # divergence (CLAUDE.md #8) refining this file's build-time-advisory
            # posture, which exists because the `state_changing` verb allowlist
            # is an incomplete heuristic. This is not a heuristic: a header cell
            # reading `Asserts` instead of `ASSERT` silently drops the whole
            # table, so its steps never enter `_steps` and therefore can never
            # land in `missing_results`, `not_run` or `unevidenced_manual`. An
            # unevidenced manual device step passed green on nothing but a
            # spelling, which is the exact escape this gate exists to close.
            # Same class as `dangling_inverse`, which already blocks in both
            # modes: the artifact misrepresenting its own coverage, not a
            # coverage judgment. Scoped to gated scenarios so priority
            # filtering keeps its meaning.
            if sc["gated"]:
                report["missing_step_table"].append(sc["id"])

    report["gated_scenarios"] = [sc["id"] for sc in scenarios if sc["gated"]]

    # ---- per-step evaluation ----
    seen_keys = set()
    for sc in scenarios:
        numbers = {st["n"] for st in sc["_steps"]}
        inverse_targets = {st["inverse_of"] for st in sc["_steps"]
                           if st["inverse_of"] is not None}
        for st in sc["_steps"]:
            entry = step_entry(st, gated=sc["gated"], priority=sc["priority"])
            seen_keys.add(st["key"].lower())

            # Exemption bookkeeping. Recorded in BOTH modes; non-blocking here,
            # matching this mode's advisory posture on the whole inverse signal.
            if st["exempt"]:
                report["exempt_steps"].append(st["key"])
            elif st["exempt_error"]:
                report["invalid_exemption"].append(
                    f"{st['key']}: {st['exempt_error']}")

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
            # anywhere in its scenario. Same predicate --lint-only blocks on.
            if is_undeclared_inverse(st, inverse_targets):
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

            if needs_manual_evidence(entry):
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
            elif needs_manual_evidence(entry) and not entry["evidence_ok"]:
                # The crux. Manual steps are first-class (a device check
                # genuinely cannot be automated) but never trusted on an
                # agent's word: an unevidenced manual PASS reads as NOT RUN.
                report["unevidenced_manual"].append(st["key"])
                report["not_run"].append(st["key"])
                # An unrecognized Mode says WHY the gate applied, so an author
                # who typed "semi" is not left wondering why an "auto" step
                # suddenly demanded evidence.
                because = (
                    f"Mode {entry['mode']!r} is not recognized (expected "
                    f"{' or '.join(RECOGNIZED_MODES)}), so this step was gated "
                    "as manual (fail-closed); it "
                    if entry["mode_unrecognized"] else "manual step ")
                entry["problems"].append(
                    because + "reports PASS but cites no existing evidence "
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
    if report["invalid_exemption"]:
        report["warnings"].append(
            "ADVISORY (non-blocking here; BLOCKS under --lint-only): malformed "
            "'[no inverse: <reason>]' marker(s): "
            + "; ".join(report["invalid_exemption"]))
    # Warn, never hide: the fail-closed gate is invisible otherwise, and an
    # author reading only `unevidenced_manual` would not learn that the entry is
    # there because of a Mode typo. Recorded as a warning rather than in
    # `unrecognized_mode` (which BLOCKS in --lint-only) so that execution mode's
    # posture stays "gate the step, do not block on the spelling".
    unrecognized = [f"{e['key']} ({e['mode']})" for e in report["steps"]
                    if e["mode_unrecognized"]]
    if unrecognized:
        report["warnings"].append(
            "step(s) whose 'Mode' cell is present but not recognized (expected "
            f"{' or '.join(RECOGNIZED_MODES)}) — each was gated as MANUAL "
            "(evidence required) BECAUSE the mode was unrecognized, not because "
            "it declares manual; fix the Mode cell or cite an "
            "'evidence/runtime/' capture: " + ", ".join(unrecognized))
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
               and not report["dangling_inverse"]
               and not report["missing_step_table"])
    report["result"] = "PASS" if gate_ok else "FAIL"
    return report


# ---------------------------------------------------------------------------
# --lint-only: plan-time structural gate
# ---------------------------------------------------------------------------

def lint_fr_scenario_coverage(report, scenarios, requirements_path):
    """Every Must-Have FR/NFR must be cited by at least one scenario heading.

    The FR->scenario link was a prose self-check
    (planning-and-task-breakdown/SKILL.md) until this: the heading requirement
    ids were already parsed, but nothing read requirements.md, so "every
    Must-Have appears in at least one scenario" was enforced only by the
    planner remembering to look. Convention #9 — a rule that asks an agent to
    restrain itself at the moment it wants to proceed becomes a gate.

    Must-Have only. A Should-Have with no scenario lands in `uncovered_should`
    and never blocks — the same tier posture check_coverage.py already applies,
    and the reason the two report the same two arrays.

    An id cited by a heading but absent from requirements.md WARNS rather than
    blocks, matching check_coverage.py's unknown-id path; only FR/NFR-shaped
    tokens are considered, so a matrix citing `EC-2` is not accused of naming
    an unknown requirement.
    """
    # BOM stripped explicitly: this file's read_text() is utf-8 where
    # check_coverage.py's is utf-8-sig, and a leading BOM would stop
    # HEADING_RE matching the document's first heading.
    tier_by_id, warnings, known_ids = parse_requirements(
        read_text(requirements_path).lstrip(chr(0xFEFF)))
    report["warnings"].extend(warnings)

    must_have = sorted((i for i, t in tier_by_id.items() if t == "Must"), key=sort_key)
    should_have = sorted((i for i, t in tier_by_id.items() if t == "Should"), key=sort_key)
    if not must_have:
        raise GateError(
            f"no Must-Have requirements found in {requirements_path} — an "
            "acceptance matrix cannot be linked to a requirements set that "
            "declares nothing mandatory")
    report["must_have"] = must_have
    report["should_have"] = should_have

    cited = {r.upper() for sc in scenarios for r in sc["requirements"]}
    for unknown in sorted({i for i in cited if ID_TOKEN_RE.fullmatch(i)} - known_ids,
                          key=sort_key):
        report["warnings"].append(
            f"unknown requirement ID {unknown} cited in an acceptance scenario "
            "heading")

    report["uncovered_should"] = [i for i in should_have if i not in cited]
    if report["uncovered_should"]:
        report["warnings"].append(
            "ADVISORY (non-blocking): Should-Have requirement(s) cited by no "
            "scenario heading: " + ", ".join(report["uncovered_should"]))

    report["lint_failures"].extend(
        {"check": "fr-scenario-coverage", "task": req_id,
         "detail": (f"Must-Have {req_id} is cited by no acceptance scenario "
                    "heading — add it to the parenthesized requirement list of "
                    "the scenario that walks it through, or the feature can "
                    "ship with nothing agreeing on what 'works' means for it")}
        for req_id in must_have if req_id not in cited)


def lint_report(report, scenarios, matrix_text, args):
    """Structure-only gate over the matrix ALONE. No results file exists yet.

    Every check here is answerable from the matrix. Priority does NOT scope
    linting: priority scopes EXECUTION, and a structurally broken scenario is
    broken at every priority — the same reasoning execution mode already
    applies to `dangling_inverse`.
    """
    # A `## ` heading naming no id is not a scenario. Warning only, never
    # blocking: `## Overview` is legitimate prose in a matrix document, and
    # there is no way to tell a prose heading from a typo'd scenario id.
    for raw in matrix_text.splitlines():
        m = SCENARIO_HEADING_RE.match(raw)
        # Same paren-stripped scan `new_scenario` uses, so this warning fires on
        # exactly the headings that failed to parse -- never on a different set.
        if m and not SCENARIO_ID_RE.search(PAREN_RE.sub(" ", m.group(1))):
            report["warnings"].append(
                f"heading '## {m.group(1).strip()}' names no scenario id "
                "(expected something like 'AS-2') — read as prose, not linted")

    if args.require_priority:
        report["warnings"].append(
            "--require-priority does not scope --lint-only: structural validity "
            "is priority-blind, so every scenario in the matrix was linted")

    if args.requirements:
        lint_fr_scenario_coverage(report, scenarios, args.requirements)

    seen_scenarios = set()
    for sc in scenarios:
        sc["linted"] = True
        if sc["id"] in seen_scenarios:
            report["duplicate_keys"].append(
                f"scenario id {sc['id']} is declared by more than one '## ' "
                "heading — step keys like '{0}.1' would be ambiguous in "
                "acceptance-results.md".format(sc["id"]))
        seen_scenarios.add(sc["id"])

        if sc["priority"] is None:
            report["missing_priority"].append(sc["id"])

        if not sc["_steps"]:
            report["missing_step_table"].append(sc["id"])
            continue

        first = sc["_steps"][0]
        absent = [name for name, present in
                  (("Stores", first["has_stores_column"]),
                   ("Mode", first["has_mode_column"])) if not present]
        if absent:
            # Blocking, and deliberately stricter than execution mode (which
            # only warns) — CLAUDE.md #8. Without these columns the Mode,
            # Stores and inverse checks below silently no-op, so a green lint
            # would mean "nothing was checkable", the exact failure mode the
            # advisory posture of `undeclared_inverse` exists to avoid.
            report["missing_columns"].append(
                f"{sc['id']}: step table has no {' or '.join(absent)} column")

        numbers, seen_numbers = set(), set()
        for st in sc["_steps"]:
            if st["n"] in seen_numbers:
                report["duplicate_keys"].append(
                    f"{sc['id']}: step number {st['n']} appears more than once "
                    f"— '[inverse of {st['n']}]' and result key {st['key']} "
                    "would both be ambiguous")
            seen_numbers.add(st["n"])
            numbers.add(st["n"])
        inverse_targets = {st["inverse_of"] for st in sc["_steps"]
                           if st["inverse_of"] is not None}

        for st in sc["_steps"]:
            entry = step_entry(st, priority=sc["priority"])

            if not (st["go"] or st["do"] or st["assert"]):
                report["malformed_steps"].append(st["key"])
                entry["problems"].append(
                    "GO, DO and ASSERT are all empty — phantom step row")

            if st["inverse_of"] is not None and st["inverse_of"] not in numbers:
                report["dangling_inverse"].append(st["key"])
                entry["problems"].append(
                    f"declares '[inverse of {st['inverse_of']}]' but scenario "
                    f"{sc['id']} has no step {st['inverse_of']}")

            if st["has_mode_column"] and st["mode"] not in RECOGNIZED_MODES:
                report["unrecognized_mode"].append(f"{st['key']} ({st['mode']})")
                entry["problems"].append(
                    f"Mode {st['mode']!r} is not recognized (expected "
                    f"{' or '.join(RECOGNIZED_MODES)})")

            if st["has_stores_column"] and st["mutating_verb"] and not st["stores"]:
                report["missing_stores"].append(st["key"])
                entry["problems"].append(
                    "DO reads as state-changing but Stores is empty — record "
                    "where the state lands, or the inverse check cannot run")

            if st["exempt"]:
                report["exempt_steps"].append(st["key"])
                if not st["state_changing"]:
                    report["warnings"].append(
                        f"{st['key']}: carries '[no inverse: ...]' but reads as "
                        "read-only anyway — the exemption is a no-op")
            elif st["exempt_error"]:
                report["invalid_exemption"].append(
                    f"{st['key']}: {st['exempt_error']}")
                entry["problems"].append(st["exempt_error"])

            if is_undeclared_inverse(st, inverse_targets):
                report["undeclared_inverse"].append(st["key"])
                entry["problems"].append(
                    "state-changing step declares no inverse and is not the "
                    "target of one — add '[inverse of N]' on the undoing step, "
                    "or '[no inverse: <reason>]' here if the step is genuinely "
                    "one-way")

            report["steps"].append(entry)

    report["linted_scenarios"] = [sc["id"] for sc in scenarios]

    # ---- report-level messages ----
    if report["missing_priority"]:
        report["warnings"].append(
            "scenario(s) whose '## ' heading declares no P0-P3 priority token — "
            "an unprioritized scenario cannot be execution-scoped honestly: "
            + ", ".join(report["missing_priority"]))
    if report["missing_step_table"]:
        report["warnings"].append(
            "scenario(s) with no step table (need a header row carrying GO, DO "
            "and ASSERT columns) — these prove nothing: "
            + ", ".join(report["missing_step_table"]))
    if report["undeclared_inverse"]:
        report["warnings"].append(
            "BLOCKING in --lint-only (advisory in execution mode — deliberate "
            "mode divergence): state-changing step(s) with no inverse declared "
            "anywhere in their scenario: "
            + ", ".join(report["undeclared_inverse"]))
    if len(report["linted_scenarios"]) < args.min_scenarios:
        report["warnings"].append(
            f"{len(report['linted_scenarios'])} scenario(s) in the matrix, "
            f"below --min-scenarios {args.min_scenarios}")

    report["scenarios"] = [{k: v for k, v in sc.items() if not k.startswith("_")}
                           for sc in scenarios]

    lint_ok = (len(report["linted_scenarios"]) >= args.min_scenarios
               and not report["missing_priority"]
               and not report["missing_step_table"]
               and not report["missing_columns"]
               and not report["unrecognized_mode"]
               and not report["missing_stores"]
               and not report["duplicate_keys"]
               and not report["malformed_steps"]
               and not report["invalid_exemption"]
               and not report["dangling_inverse"]
               and not report["undeclared_inverse"]
               and not report["lint_failures"])
    report["result"] = "PASS" if lint_ok else "FAIL"
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(prog="check_acceptance_suite.py")
    p.add_argument("--matrix")
    p.add_argument("--results")
    p.add_argument("--requirements")
    p.add_argument("--repo", default=".")
    p.add_argument("--require-priority")
    p.add_argument("--min-scenarios", type=int, default=1)
    p.add_argument("--lint-only", action="store_true")
    p.add_argument("--self-test", action="store_true")
    return p


def main(argv):
    args = build_parser().parse_args(argv)

    if args.self_test:
        return run_self_test()

    if args.lint_only:
        if args.results:
            print(json.dumps({"result": "ERROR", "error":
                              "--results is not accepted with --lint-only: lint "
                              "mode gates matrix STRUCTURE, not execution. Drop "
                              "--results to lint, or drop --lint-only to gate "
                              "execution."}))
            return 2
        if not args.matrix:
            print(json.dumps({"result": "ERROR",
                              "error": "missing required argument(s): --matrix"}))
            return 2
    else:
        # Same mode-separation rule --results-with---lint-only enforces, read
        # from the other end: the FR->scenario link is a PLAN-time question
        # about the matrix, and answering it says nothing about whether the
        # matrix was run. A caller passing both has misunderstood which one
        # they wanted.
        if args.requirements:
            print(json.dumps({"result": "ERROR", "error":
                              "--requirements is only accepted with --lint-only: "
                              "the FR->scenario link gates matrix STRUCTURE at "
                              "plan time, not execution. Add --lint-only (and "
                              "drop --results), or drop --requirements."}))
            return 2
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

    # MATRIX itself is NOT lint-clean: AS-2.4 `distribute` is a state-changing
    # step with no inverse. That is the whole point of the mode divergence —
    # execution mode passes it, --lint-only blocks it. LINT_CLEAN is MATRIX plus
    # the one-line exemption that resolves it.
    LINT_CLEAN = MATRIX.replace(
        "| distribute |",
        "| distribute [no inverse: a queued job cannot be un-queued] |")

    # Must-Haves FR-1, FR-3 and FR-4 are exactly what MATRIX's two scenario
    # headings cite; FR-7 and NFR-2 are Should-Haves nothing cites.
    REQUIREMENTS = """# Requirements — slide-integration

## Must Have

- **FR-1** — the tenant can connect the Slide integration.
- **FR-3** — the tenant can map a client to a Slide client.
- **FR-4** — a mapped client renders a green tick.

## Should Have

- **FR-7** — the mapping list is searchable.
- **NFR-2** (Should Have) — the mapping list renders within 500ms.
"""

    EXPECTED_KEYS = {
        "matrix", "results", "requirements", "lint_only", "require_priority",
        "min_scenarios", "scenarios", "gated_scenarios", "linted_scenarios",
        "steps", "steps_gated", "passed", "failed", "blocked", "not_run",
        "missing_results", "unevidenced_manual", "dangling_inverse",
        "undeclared_inverse", "exempt_steps", "invalid_exemption",
        "missing_priority", "missing_step_table", "missing_columns",
        "unrecognized_mode", "missing_stores", "duplicate_keys",
        "malformed_steps", "must_have", "should_have", "uncovered_should",
        "lint_failures", "extra_results", "warnings", "result", "error"}

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
                        requirements=None, repo=str(self.dir),
                        require_priority=None, min_scenarios=1,
                        lint_only=False, self_test=False)
            base.update(kw)
            return argparse.Namespace(**base)

        def _requirements(self, text=None):
            path = self.impl / "requirements.md"
            path.write_text(REQUIREMENTS if text is None else text,
                            encoding="utf-8")
            return str(path)

        def _lint(self, matrix=None, **kw):
            if matrix is not None:
                self.matrix.write_text(matrix, encoding="utf-8")
            return build_report(self._args(lint_only=True, results=None, **kw))

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

        def test_heading_without_an_id_does_not_adopt_a_requirement_id(self):
            """A missing scenario id must not become the cited requirement id."""
            table = ("| # | GO | DO | ASSERT | Stores | Mode |\n"
                     "|---|----|----|--------|--------|------|\n"
                     "| 1 | list | read the list | rows render | ui | auto |\n")
            matrix = ("## AS-1 Listing — P0 — (FR-9)\n\n" + table
                      + "\n## Mapping lifecycle — P0 — (FR-1)\n\n" + table)
            r = self._lint(matrix=matrix)
            # AS-1 only. Before the fix the second heading parsed as `FR-1`.
            self.assertEqual(r["linted_scenarios"], ["AS-1"])
            self.assertTrue(any("names no scenario id" in w for w in r["warnings"]),
                            r["warnings"])

        def test_unparsed_step_table_blocks_in_execution_mode(self):
            """A misspelled header cell must not buy a scenario out of the gate.

            `Asserts` instead of `ASSERT` drops the whole table, so the manual
            device step never enters `_steps` and cannot land in
            `unevidenced_manual`. Before this blocked, the run exited 0/PASS on
            nothing but a spelling.
            """
            broken = MATRIX + (
                "\n## AS-9 Device install — P0 — (FR-9)\n"
                "Surface: rmm | Preconditions: AS-2 step 1\n\n"
                "| # | GO | DO | Asserts | Stores | Mode |\n"
                "|---|----|----|---------|--------|------|\n"
                "| 1 | agent console | verify agent installed | present | device | manual |\n")
            r = self._run(matrix=broken)
            self.assertEqual(r["result"], "FAIL", r)
            self.assertEqual(r["missing_step_table"], ["AS-9"])
            self.assertEqual(r["unevidenced_manual"], [])

        def test_unparsed_step_table_outside_priority_scope_only_warns(self):
            """Priority scoping keeps its meaning: an ungated scenario warns."""
            broken = MATRIX + (
                "\n## AS-9 Device install — P2 — (FR-9)\n\n"
                "| # | GO | DO | Asserts | Stores | Mode |\n"
                "|---|----|----|---------|--------|------|\n"
                "| 1 | agent console | verify agent installed | present | device | manual |\n")
            r = self._run(matrix=broken, require_priority="P0")
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["missing_step_table"], [])
            self.assertTrue(any("AS-9" in w and "no step table" in w
                                for w in r["warnings"]))

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

        # ---- condition 3, fail-closed half: an unrecognized Mode owes evidence ----

        def test_unrecognized_mode_without_evidence_blocks(self):
            """The bug this closed: `semi` used to read as auto and pass green."""
            m = MATRIX.replace("| manual |", "| semi |")
            r = self._run(GREEN[:-1]
                          + ["- AS-2.4: PASS — confirmed the agent installed"],
                          matrix=m)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["unevidenced_manual"], ["AS-2.4"])
            self.assertEqual(r["not_run"], ["AS-2.4"])
            step4 = [s for s in r["steps"] if s["key"] == "AS-2.4"][0]
            self.assertTrue(step4["mode_unrecognized"])
            self.assertTrue(any("not recognized" in p
                                for p in step4["problems"]), step4)
            self.assertTrue(any("BECAUSE the mode was unrecognized" in w
                                for w in r["warnings"]), r["warnings"])

        def test_unrecognized_mode_with_evidence_passes(self):
            """The fail-closed path is satisfiable, not a dead end."""
            r = self._run(GREEN, matrix=MATRIX.replace("| manual |", "| semi |"))
            self.assertEqual(r["result"], "PASS", r)
            step4 = [s for s in r["steps"] if s["key"] == "AS-2.4"][0]
            self.assertTrue(step4["mode_unrecognized"])
            self.assertTrue(step4["evidence_ok"])

        def test_empty_mode_cell_stays_auto_and_is_not_flagged(self):
            """Scope boundary: absent is not unrecognized."""
            m = MATRIX.replace("| device | manual |", "| device |  |")
            r = self._run(GREEN[:-1]
                          + ["- AS-2.4: PASS — confirmed the agent installed"],
                          matrix=m)
            self.assertEqual(r["result"], "PASS", r)
            step4 = [s for s in r["steps"] if s["key"] == "AS-2.4"][0]
            self.assertEqual(step4["mode"], "auto")
            self.assertFalse(step4["mode_unrecognized"])
            self.assertEqual(r["unevidenced_manual"], [])

        def test_mode_unrecognized_is_a_step_key_in_both_modes(self):
            self.assertIn("mode_unrecognized", self._run()["steps"][0])
            self.assertIn("mode_unrecognized", self._lint(LINT_CLEAN)["steps"][0])

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
            self.assertEqual(set(self._run().keys()), EXPECTED_KEYS)
            self.assertEqual(set(self._run(GREEN[:1]).keys()), EXPECTED_KEYS)

        # ---- --lint-only: mode divergence ----

        def test_lint_clean_matrix_passes(self):
            r = self._lint(LINT_CLEAN)
            self.assertEqual(r["result"], "PASS", r)
            self.assertTrue(r["lint_only"])
            self.assertEqual(r["linted_scenarios"], ["AS-1", "AS-2"])
            self.assertEqual(r["undeclared_inverse"], [])
            self.assertEqual(r["exempt_steps"], ["AS-2.4"])

        def test_lint_only_leaves_execution_arrays_empty(self):
            r = self._lint(LINT_CLEAN)
            self.assertIsNone(r["results"])
            self.assertEqual(r["gated_scenarios"], [])
            self.assertEqual(r["steps_gated"], 0)
            self.assertEqual(r["passed"], 0)
            for k in ("failed", "blocked", "not_run", "missing_results",
                      "unevidenced_manual", "extra_results"):
                self.assertEqual(r[k], [], k)

        def test_lint_only_json_keys_match_execution_mode(self):
            """Same key set both modes, so the two reports diff key-for-key."""
            self.assertEqual(set(self._lint(LINT_CLEAN).keys()), EXPECTED_KEYS)
            self.matrix.write_text(MATRIX, encoding="utf-8")
            exec_r, lint_r = self._run(), self._lint(MATRIX)
            self.assertEqual(set(exec_r.keys()), set(lint_r.keys()))
            self.assertEqual(set(exec_r["steps"][0]), set(lint_r["steps"][0]))

        def test_undeclared_inverse_blocks_under_lint_only(self):
            """THE divergence: one matrix, exit 0 executing, exit 1 linting."""
            self.matrix.write_text(MATRIX, encoding="utf-8")
            self.assertEqual(self._run()["result"], "PASS")
            r = self._lint(MATRIX)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["undeclared_inverse"], ["AS-2.4"])
            self.assertTrue(any("BLOCKING in --lint-only" in w
                                for w in r["warnings"]))

        # ---- --lint-only: structural conditions ----

        def test_lint_missing_priority_blocks(self):
            m = LINT_CLEAN.replace("## AS-2 Client mapping lifecycle — P0 —",
                                   "## AS-2 Client mapping lifecycle —")
            r = self._lint(m)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["missing_priority"], ["AS-2"])

        def test_lint_missing_step_table_blocks(self):
            r = self._lint("## AS-1 Connect — P0 — (FR-1)\n\nSurface: api\n")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["missing_step_table"], ["AS-1"])

        def test_lint_missing_stores_or_mode_column_blocks(self):
            m = LINT_CLEAN.replace(" | Stores | Mode |", " |")
            m = m.replace("|--------|--------|------|", "|--------|")
            m = re.sub(r"\| [a-z, ]+ \| (auto|manual) \|$", "|", m, flags=re.M)
            r = self._lint(m)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(len(r["missing_columns"]), 2)
            self.assertIn("no Stores or Mode column", r["missing_columns"][0])

        def test_lint_unrecognized_mode_blocks(self):
            r = self._lint(LINT_CLEAN.replace("| manual |", "| semi |"))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["unrecognized_mode"], ["AS-2.4 (semi)"])

        def test_lint_state_changing_step_with_empty_stores_blocks(self):
            m = LINT_CLEAN.replace(
                "| 1 | Clients list | map client A | 200 + mapping row | api, db "
                "| auto |",
                "| 1 | Clients list | map client A | 200 + mapping row |  | auto |")
            r = self._lint(m)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["missing_stores"], ["AS-2.1"])

        def test_lint_dangling_inverse_blocks(self):
            r = self._lint(LINT_CLEAN.replace("[inverse of 1]",
                                              "[inverse of 9]", 1))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["dangling_inverse"], ["AS-1.2"])

        def test_lint_duplicate_step_number_blocks(self):
            m = LINT_CLEAN.replace(
                "| 2 | Clients list | reload | green tick on A | ui | auto |",
                "| 1 | Clients list | reload | green tick on A | ui | auto |")
            r = self._lint(m)
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(any("step number 1 appears more than once" in d
                                for d in r["duplicate_keys"]), r["duplicate_keys"])

        def test_lint_duplicate_scenario_id_blocks(self):
            r = self._lint(LINT_CLEAN.replace(
                "## AS-2 Client mapping lifecycle",
                "## AS-1 Client mapping lifecycle"))
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(any("scenario id AS-1 is declared" in d
                                for d in r["duplicate_keys"]), r["duplicate_keys"])

        def test_lint_phantom_step_row_blocks(self):
            m = LINT_CLEAN.replace(
                "| 2 | Clients list | reload | green tick on A | ui | auto |",
                "| 2 |  |  |  | ui | auto |")
            r = self._lint(m)
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["malformed_steps"], ["AS-2.2"])

        def test_lint_min_scenarios_enforced(self):
            r = self._lint(LINT_CLEAN, min_scenarios=3)
            self.assertEqual(r["result"], "FAIL")
            self.assertTrue(any("--min-scenarios" in w for w in r["warnings"]))

        def test_lint_priority_does_not_scope_structure(self):
            """P2 does not buy a scenario out of structural linting."""
            m = LINT_CLEAN.replace("## AS-2 Client mapping lifecycle — P0",
                                   "## AS-2 Client mapping lifecycle — P2")
            m = m.replace("[no inverse: a queued job cannot be un-queued]", "")
            r = self._lint(m, require_priority="P0")
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual(r["undeclared_inverse"], ["AS-2.4"])
            self.assertEqual(r["linted_scenarios"], ["AS-1", "AS-2"])
            self.assertTrue(any("does not scope --lint-only" in w
                                for w in r["warnings"]))

        def test_lint_non_scenario_heading_warns_but_does_not_block(self):
            r = self._lint("## Overview\n\nprose about the journey\n\n"
                           + LINT_CLEAN)
            self.assertEqual(r["result"], "PASS", r)
            self.assertTrue(any("names no scenario id" in w
                                for w in r["warnings"]))

        def test_lint_unparseable_matrix_is_exit_2(self):
            self.matrix.write_text("# Matrix\n\n## Overview\n\nprose\n",
                                   encoding="utf-8")
            with self.assertRaises(GateError):
                build_report(self._args(lint_only=True, results=None))

        # ---- --lint-only: the exemption escape hatch ----

        def test_exemption_reason_is_required(self):
            for bad in ("[no inverse:]", "[no inverse: ]", "[no inverse: -]"):
                r = self._lint(LINT_CLEAN.replace(
                    "[no inverse: a queued job cannot be un-queued]", bad))
                self.assertEqual(r["result"], "FAIL", bad)
                self.assertEqual(len(r["invalid_exemption"]), 1, bad)
                self.assertIn("carries no reason text",
                              r["invalid_exemption"][0])
                self.assertEqual(r["exempt_steps"], [], bad)

        def test_exemption_conflicting_with_inverse_of_blocks(self):
            r = self._lint(LINT_CLEAN.replace(
                "[no inverse: a queued job cannot be un-queued]",
                "[inverse of 2] [no inverse: cannot be un-queued]"))
            self.assertEqual(r["result"], "FAIL")
            self.assertIn("cannot both have and lack an inverse",
                          r["invalid_exemption"][0])

        def test_exemption_is_case_insensitive_and_reason_is_captured(self):
            r = self._lint(LINT_CLEAN.replace(
                "[no inverse: a queued job cannot be un-queued]",
                "[NO INVERSE: a queued job cannot be un-queued]"))
            self.assertEqual(r["result"], "PASS", r)
            step4 = [s for s in r["steps"] if s["key"] == "AS-2.4"][0]
            self.assertTrue(step4["exempt"])
            self.assertEqual(step4["no_inverse_reason"],
                             "a queued job cannot be un-queued")

        def test_exemption_on_read_only_step_is_a_no_op_warning(self):
            r = self._lint(LINT_CLEAN.replace(
                "| reload |", "| reload [no inverse: a reload changes nothing] |"))
            self.assertEqual(r["result"], "PASS", r)
            self.assertTrue(any("the exemption is a no-op" in w
                                for w in r["warnings"]))

        def test_exemption_suppresses_the_advisory_in_execution_mode_too(self):
            """One predicate, two postures — the arrays must agree."""
            r = self._run(matrix=LINT_CLEAN)
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["undeclared_inverse"], [])
            self.assertEqual(r["exempt_steps"], ["AS-2.4"])

        def test_malformed_exemption_is_non_blocking_in_execution_mode(self):
            r = self._run(matrix=LINT_CLEAN.replace(
                "[no inverse: a queued job cannot be un-queued]",
                "[no inverse:]"))
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(len(r["invalid_exemption"]), 1)
            self.assertTrue(any("BLOCKS under --lint-only" in w
                                for w in r["warnings"]))

        # ---- --lint-only: the FR -> scenario link (--requirements) ----

        def test_lint_every_must_have_cited_passes(self):
            r = self._lint(LINT_CLEAN, requirements=self._requirements())
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["must_have"], ["FR-1", "FR-3", "FR-4"])
            self.assertEqual(r["lint_failures"], [])

        def test_lint_uncited_must_have_blocks(self):
            """The escape this closed: an FR nothing walks through."""
            r = self._lint(LINT_CLEAN, requirements=self._requirements(
                REQUIREMENTS.replace(
                    "- **FR-4**",
                    "- **FR-9** — the tenant can unmap a client.\n- **FR-4**")))
            self.assertEqual(r["result"], "FAIL")
            self.assertEqual([f["check"] for f in r["lint_failures"]],
                             ["fr-scenario-coverage"])
            self.assertEqual(r["lint_failures"][0]["task"], "FR-9")

        def test_lint_uncited_should_have_never_blocks(self):
            r = self._lint(LINT_CLEAN, requirements=self._requirements())
            self.assertEqual(r["result"], "PASS", r)
            self.assertEqual(r["uncovered_should"], ["FR-7", "NFR-2"])
            self.assertTrue(any("ADVISORY" in w and "Should-Have" in w
                                for w in r["warnings"]), r["warnings"])

        def test_lint_unknown_cited_requirement_only_warns(self):
            r = self._lint(LINT_CLEAN.replace("(FR-1)", "(FR-1, FR-99)"),
                           requirements=self._requirements())
            self.assertEqual(r["result"], "PASS", r)
            self.assertTrue(any("unknown requirement ID FR-99" in w
                                for w in r["warnings"]), r["warnings"])

        def test_non_fr_scenario_citation_is_not_an_unknown_id(self):
            """`EC-2` in AS-2's heading is not a requirement id."""
            r = self._lint(LINT_CLEAN, requirements=self._requirements())
            self.assertFalse(any("EC-2" in w for w in r["warnings"]),
                             r["warnings"])

        def test_requirements_without_lint_only_is_exit_2(self):
            self.results.write_text(results(GREEN), encoding="utf-8")
            self.assertEqual(
                main(["--matrix", str(self.matrix), "--results",
                      str(self.results), "--requirements",
                      self._requirements()]), 2)

        def test_unreadable_or_must_have_less_requirements_is_exit_2(self):
            with self.assertRaises(GateError):
                build_report(self._args(lint_only=True, results=None,
                                        requirements=str(self.dir / "nope.md")))
            with self.assertRaises(GateError):
                build_report(self._args(
                    lint_only=True, results=None,
                    requirements=self._requirements(
                        "# Requirements\n\n## Should Have\n\n"
                        "- **FR-7** — the mapping list is searchable.\n")))

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

        def test_lint_only_rejects_results_with_exit_2(self):
            self.assertEqual(main(["--lint-only", "--matrix", str(self.matrix),
                                   "--results", str(self.results)]), 2)
            self.assertEqual(main(["--lint-only"]), 2)

        def test_lint_only_cli_exit_codes(self):
            self.matrix.write_text(LINT_CLEAN, encoding="utf-8")
            self.assertEqual(main(["--lint-only", "--matrix",
                                   str(self.matrix)]), 0)
            self.matrix.write_text(MATRIX, encoding="utf-8")
            self.assertEqual(main(["--lint-only", "--matrix",
                                   str(self.matrix)]), 1)
            self.assertEqual(main(["--lint-only", "--matrix",
                                   str(self.dir / "nope.md")]), 2)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
