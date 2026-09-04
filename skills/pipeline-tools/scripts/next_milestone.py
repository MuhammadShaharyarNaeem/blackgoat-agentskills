#!/usr/bin/env python3
"""Deterministic next-milestone derivation for the bgpdd-build Orchestrator.

Reads plan.md once and emits only what the Orchestrator needs to route the
next build phase: the next pending milestone (title, heading line, domain),
its full block text verbatim, the remaining pending milestone titles, and an
optional staleness check against orchestrator-state.json's milestone_cursor.
This replaces re-reading the entire plan (290K+ chars in real plans) every
time the Orchestrator must decide what to build next.

Usage:
    python next_milestone.py --plan <path> [--state <path>] \
        [--ledger <path>] [--emit-gate-args]
    python next_milestone.py --self-test

Pure standard library. See ../SKILL.md for the full contract (JSON shape,
exit codes, parsing rules).
"""
import argparse
import bisect
import json
import re
import sys
from pathlib import Path

MILESTONE_HEADING_RE = re.compile(r"^#{2,3}\s*Milestone\b\s+\d")
LEVEL2_HEADING_RE = re.compile(r"^##(?!#)\s*(.*)$")
COMPLETE_RE = re.compile(r"\[x\]", re.IGNORECASE)
UI_TAG_RE = re.compile(r"\[UI\]")
API_TAG_RE = re.compile(r"\[API\]")

# Verification-surface tag: a second, ORTHOGONAL axis to the domain tag.
# Lowercase deliberately -- UI_TAG_RE/API_TAG_RE match case-sensitive bracket
# literals, so `[vs:api]` cannot collide with `[API]`.
VS_TAG_RE = re.compile(r"\[vs:([a-z+]{2,12})\]")
VALID_SURFACES = ("api", "ui", "web+api", "rmm", "fn", "none")

EXIT_CODES = {"NEXT": 0, "DONE": 0, "MIXED": 1, "ERROR": 2}

# --- RUNTIME PROBE parsing (for --emit-gate-args) --------------------------
# The probe line the plan already declares carries exactly the arguments
# check_runtime_evidence.py needs. Deriving them mechanically removes the step
# where the Orchestrator retypes them — and a retyped assertion is one that can
# be quietly weakened. The parse is deliberately CONSERVATIVE: anything it is
# unsure of comes back null/empty so the caller supplies it explicitly, never
# a guess that reads as a declaration.
PROBE_MARKER_RE = re.compile(r"RUNTIME\s+PROBE\s*:", re.IGNORECASE)
EXPECT_STATUS_RES = (
    re.compile(r"\bexpect[-_\s]*status\s*[:=]?\s*(\d{3})\b", re.IGNORECASE),
    re.compile(r"\bexpects?\s+(\d{3})\b", re.IGNORECASE),
    re.compile(r"\bstatus\s+(\d{3})\b", re.IGNORECASE),
    re.compile(r"\b(\d{3})\s+(?:OK|Created|Accepted|No\s+Content)\b",
               re.IGNORECASE),
)
# A keys FIELD, whose value runs to the next `;` or newline. Backticked and
# bare identifiers inside the value both parse.
REQUIRE_KEYS_FIELD_RE = re.compile(
    r"\brequire[-_]?keys?\s*[:=]\s*([^;\n]*)|\bkeys\s*[:=]\s*([^;\n]*)",
    re.IGNORECASE)
REQUIRE_KEY_SINGLE_RE = re.compile(
    r"\brequire[-_]?key\s+`?([A-Za-z_][A-Za-z0-9_]*)`?", re.IGNORECASE)
KEY_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
EMPTY_KEY_VALUES = {"none", "n/a", "na", "-", "tbd"}


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_text(path):
    """Read a UTF-8 artifact, tolerating a byte-order mark."""
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding="utf-8-sig", errors="replace")


def milestone_domain(heading_line, block_text):
    """UI / API / MIXED / UNTAGGED for a milestone.

    The heading line's own [UI]/[API] tag is authoritative when present
    (backticks around the tag don't matter — the tag regexes match the
    brackets regardless). Only when the heading carries neither tag do we
    fall back to scanning the whole block, including task prose, for tags.
    """
    heading_ui = bool(UI_TAG_RE.search(heading_line))
    heading_api = bool(API_TAG_RE.search(heading_line))
    if heading_ui or heading_api:
        if heading_ui and heading_api:
            return "MIXED"
        return "UI" if heading_ui else "API"

    has_ui = bool(UI_TAG_RE.search(block_text))
    has_api = bool(API_TAG_RE.search(block_text))
    if has_ui and has_api:
        return "MIXED"
    if has_ui:
        return "UI"
    if has_api:
        return "API"
    return "UNTAGGED"


def milestone_surface(heading_line, block_text):
    """The `[vs:<surface>]` verification surface, or None when absent.

    Same authority rule as the domain tag: the heading line wins when it
    carries one; otherwise the whole block is scanned. Returns the raw key
    even when invalid, so the caller can distinguish "missing" (None) from
    "misspelled" (a key not in VALID_SURFACES) -- a typo must not read as an
    omission and vice versa.
    """
    m = VS_TAG_RE.search(heading_line) or VS_TAG_RE.search(block_text)
    return m.group(1).lower() if m else None


def parse_milestones(text):
    """Split plan.md into milestone blocks on '## Milestone <n>' / '### Milestone <n>' headings.

    A block runs from its heading to the FIRST of: the next milestone
    heading (level 2 or 3), the next level-2 heading whose text starts with
    neither "Task" nor "Checkpoint" (this is what ends the task list at a
    trailing section like "## Risks and Mitigations" or "## Open Questions"
    while keeping a checkpoint block inside its milestone), or
    EOF. Any other heading in between — "## Task N:" headings, "### Checkpoint:"
    blocks, non-numbered "Milestone ..." prose — stays inside the block.
    """
    lines = text.splitlines()
    milestone_idxs = [i for i, line in enumerate(lines) if MILESTONE_HEADING_RE.match(line)]
    if not milestone_idxs:
        raise GateError(
            "plan has no '## Milestone <n>' or '### Milestone <n>' headings")

    terminator_idxs = set(milestone_idxs)
    checkpoint_idxs = []
    for i, line in enumerate(lines):
        m = LEVEL2_HEADING_RE.match(line)
        if not m:
            continue
        heading_text = m.group(1).strip().lower()
        if heading_text.startswith("task"):
            continue  # stays inside the block
        if heading_text.startswith("checkpoint"):
            # Deprecated level-2 checkpoint form: tolerated inside the block
            # (like a "### Checkpoint:" heading) rather than terminating it,
            # but flagged -- the canonical writer form is level-3.
            checkpoint_idxs.append(i)
            continue
        terminator_idxs.add(i)
    terminator_idxs = sorted(terminator_idxs)

    milestones = []
    for idx in milestone_idxs:
        pos = bisect.bisect_right(terminator_idxs, idx)
        end = terminator_idxs[pos] if pos < len(terminator_idxs) else len(lines)
        heading_line = lines[idx]
        block_text = "\n".join(lines[idx:end])
        title = re.sub(r"^#+\s*", "", heading_line).rstrip()
        warnings = []
        if any(idx <= c < end for c in checkpoint_idxs):
            warnings.append(
                f"milestone {title!r} contains a deprecated level-2 "
                "'## Checkpoint:' heading; use the canonical level-3 "
                "'### Checkpoint:' form instead")
        milestones.append({
            "title": title,
            "line": idx + 1,
            "complete": bool(COMPLETE_RE.search(title)),
            "text": block_text,
            "domain": milestone_domain(heading_line, block_text),
            "surface": milestone_surface(heading_line, block_text),
            "warnings": warnings,
        })
    return milestones


def derive_next(milestones):
    """Pick the first pending milestone and describe the pending set."""
    warnings = []
    pending = [m for m in milestones if not m["complete"]]
    completed_count = len(milestones) - len(pending)
    total_count = len(milestones)

    if not pending:
        return {
            "result": "DONE",
            "next_milestone": None,
            "milestone_text": None,
            "remaining": [],
            "completed_count": completed_count,
            "total_count": total_count,
            "warnings": warnings,
        }

    next_m = pending[0]
    # Three distinct planning defects, one verdict. `MIXED` is the family name
    # for "the plan cannot be executed as written" — the Orchestrator's action
    # is identical in every case (halt, route back through Alex), so they share
    # an exit code and are told apart by the warning, not the verdict.
    defect = False
    if next_m["domain"] in ("MIXED", "UNTAGGED"):
        defect = True
        if next_m["domain"] == "UNTAGGED":
            warnings.append(
                f"milestone {next_m['title']!r} has no [UI]/[API] task tags "
                f"— treat as planning defect (halt for re-tag), same as MIXED")
    if next_m["surface"] is None:
        defect = True
        warnings.append(
            f"milestone {next_m['title']!r} carries no [vs:<surface>] "
            f"verification-surface tag — planning defect (halt for re-tag). "
            f"Valid: {', '.join(VALID_SURFACES)}. A milestone whose surface is "
            f"undeclared cannot have its evidence requirement checked, which is "
            f"exactly how an unverified claim reaches a commit")
    elif next_m["surface"] not in VALID_SURFACES:
        defect = True
        warnings.append(
            f"milestone {next_m['title']!r} declares unknown verification "
            f"surface [vs:{next_m['surface']}] — planning defect (halt for "
            f"re-tag). Valid: {', '.join(VALID_SURFACES)}")
    result = "MIXED" if defect else "NEXT"
    warnings += next_m.get("warnings", [])

    return {
        "result": result,
        "next_milestone": {"title": next_m["title"], "line": next_m["line"],
                           "domain": next_m["domain"],
                           "surface": next_m["surface"]},
        "milestone_text": next_m["text"],
        "remaining": [m["title"] for m in pending],
        "completed_count": completed_count,
        "total_count": total_count,
        "warnings": warnings,
    }


def _probe_lines(block_text):
    """Every `RUNTIME PROBE:` line in a milestone block, in file order."""
    return [line for line in block_text.split("\n")
            if PROBE_MARKER_RE.search(line)]


def _parse_expect_status(line):
    for pattern in EXPECT_STATUS_RES:
        m = pattern.search(line)
        if m:
            return int(m.group(1))
    return None


def _parse_require_keys(line):
    """Identifier list from a keys FIELD only — never from the whole line.

    Harvesting backticked tokens line-wide would read the probe COMMAND
    (`` `npm run start` ``) as required response keys. A key is only a key
    where the author declared one.
    """
    values = []
    for m in REQUIRE_KEYS_FIELD_RE.finditer(line):
        values.append(m.group(1) if m.group(1) is not None else m.group(2))
    keys = []
    for value in values:
        for part in (value or "").split(","):
            part = part.strip().strip("`").strip()
            if not part or part.lower() in EMPTY_KEY_VALUES:
                continue
            token = KEY_TOKEN_RE.match(part)
            if token and token.group(0) not in keys:
                keys.append(token.group(0))
    for m in REQUIRE_KEY_SINGLE_RE.finditer(line):
        if m.group(1) not in keys:
            keys.append(m.group(1))
    return keys


def derive_gate_args(milestone):
    """Parse a milestone's probe declarations into gate arguments.

    Returns ({surface, expect_status, require_keys, forbid_hosts}, warnings).

    When a milestone declares SEVERAL probe lines that disagree, the
    disagreement is reported and the field comes back null/empty: a gate
    argument invented from an ambiguous plan is worse than an absent one,
    because it reads to every later consumer as a declaration.

    `forbid_hosts` is ALWAYS empty. Forbidden hosts are project-declared by
    the caller (check_runtime_evidence.py's contract) and nothing in a plan
    can supply them; the key exists so the object's shape is stable.
    """
    warnings = []
    lines = _probe_lines(milestone["text"])
    statuses = [s for s in (_parse_expect_status(l) for l in lines)
                if s is not None]
    key_sets = [_parse_require_keys(l) for l in lines]
    key_sets = [k for k in key_sets if k]

    expect_status = None
    if len({*statuses}) == 1:
        expect_status = statuses[0]
    elif len({*statuses}) > 1:
        warnings.append(
            f"milestone {milestone['title']!r} declares conflicting probe "
            f"statuses ({', '.join(str(s) for s in sorted({*statuses}))}); "
            "gate_args.expect_status left null — pass --expect-status "
            "explicitly")

    require_keys = []
    distinct = {tuple(k) for k in key_sets}
    if len(distinct) == 1:
        require_keys = list(key_sets[0])
    elif len(distinct) > 1:
        warnings.append(
            f"milestone {milestone['title']!r} declares conflicting probe key "
            "sets; gate_args.require_keys left empty — pass --require-key "
            "explicitly")

    if not lines:
        warnings.append(
            f"milestone {milestone['title']!r} declares no 'RUNTIME PROBE:' "
            "line, so gate_args carries only the surface")

    return {
        "surface": milestone["surface"],
        "expect_status": expect_status,
        "require_keys": require_keys,
        "forbid_hosts": [],
    }, warnings


def check_unbacked_complete(ledger_path, milestones):
    """Milestones marked `[x]` with no PASS commit-gate record behind them.

    ADVISORY ONLY — exit codes are unchanged. Completion is recorded by
    hand-appending `[x]` to a heading, which nothing tied to a commit or a
    gate: a milestone could be marked done by editing one character. This
    cannot refuse the edit, but it can refuse to stay quiet about it.

    Matching mirrors the cursor check: a case-insensitive substring test in
    either direction between the ledger entry's milestone and the title.
    """
    warnings = []
    p = Path(ledger_path)
    if not p.is_file():
        return [], [f"ledger {ledger_path} does not exist; the "
                    "unbacked-completion check reports nothing"]
    passed = []
    for line in p.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (isinstance(rec, dict) and rec.get("gate") == "check_commit_gate.py"
                and rec.get("verdict") == "PASS"
                and isinstance(rec.get("milestone"), str)):
            passed.append(rec["milestone"].lower())

    unbacked = []
    for m in milestones:
        if not m["complete"]:
            continue
        title = m["title"].lower()
        if not any(entry in title or title in entry for entry in passed):
            unbacked.append(m["title"])
    if unbacked:
        warnings.append(
            "unbacked_complete (ADVISORY): milestone(s) marked '[x]' with no "
            "PASS check_commit_gate.py ledger entry behind them — completion "
            "was asserted, not gated: " + ", ".join(unbacked))
    return unbacked, warnings


def check_cursor(state_path, milestones, next_milestone):
    """Compare orchestrator-state.json's milestone_cursor against plan order.

    stale: the cursor names a milestone that appears LATER in plan order
    than the derived next pending one (resuming from it would skip pending
    work). matches_next: the cursor names the derived next milestone itself.
    Matching is a case-insensitive substring test, either direction.
    """
    warnings = []
    try:
        state = json.loads(read_text(state_path))
    except json.JSONDecodeError as exc:
        raise GateError(f"state file is not valid JSON: {exc}")
    if not isinstance(state, dict) or "milestone_cursor" not in state:
        raise GateError("state file has no 'milestone_cursor' field")

    cursor = state["milestone_cursor"]
    if cursor is not None and not isinstance(cursor, str):
        raise GateError("'milestone_cursor' is not a string or null")

    if cursor is None or next_milestone is None:
        return {"stored": cursor, "matches_next": False, "stale": False}, warnings

    cursor_l = cursor.lower()
    matches = [i for i, m in enumerate(milestones)
               if cursor_l in m["title"].lower() or m["title"].lower() in cursor_l]
    if not matches:
        warnings.append(f"cursor {cursor!r} does not match any milestone title")
        return {"stored": cursor, "matches_next": False, "stale": False}, warnings

    next_idx = next((i for i, m in enumerate(milestones)
                     if m["line"] == next_milestone["line"]), None)
    matches_next = next_idx is not None and next_idx in matches
    stale = next_idx is not None and any(i > next_idx for i in matches)
    return {"stored": cursor, "matches_next": matches_next, "stale": stale}, warnings


def build_report(args):
    report = {
        "plan_file": args.plan,
        "result": "ERROR",
        "next_milestone": None,
        "milestone_text": None,
        "remaining": [],
        "completed_count": 0,
        "total_count": 0,
        "cursor": None,
        "gate_args": None,
        "unbacked_complete": [],
        "warnings": [],
        "error": None,
    }
    milestones = parse_milestones(read_text(args.plan))
    derived = derive_next(milestones)
    report.update({k: derived[k] for k in
                   ("result", "next_milestone", "milestone_text", "remaining",
                    "completed_count", "total_count")})
    report["warnings"] += derived["warnings"]

    if args.state:
        cursor_info, warnings = check_cursor(args.state, milestones,
                                             derived["next_milestone"])
        report["cursor"] = cursor_info
        report["warnings"] += warnings

    if getattr(args, "ledger", None):
        unbacked, warnings = check_unbacked_complete(args.ledger, milestones)
        report["unbacked_complete"] = unbacked
        report["warnings"] += warnings

    if getattr(args, "emit_gate_args", False) and derived["result"] == "NEXT":
        next_m = next(m for m in milestones
                      if m["line"] == derived["next_milestone"]["line"])
        gate_args, warnings = derive_gate_args(next_m)
        report["gate_args"] = gate_args
        report["warnings"] += warnings

    return report


def main(argv):
    parser = argparse.ArgumentParser(prog="next_milestone.py")
    parser.add_argument("--plan")
    parser.add_argument("--state")
    parser.add_argument(
        "--ledger",
        help="the shared gate ledger; enables the ADVISORY unbacked_complete "
             "check (exit codes are unchanged)")
    parser.add_argument(
        "--emit-gate-args", action="store_true",
        help="parse the next milestone's RUNTIME PROBE line into gate_args")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.plan:
        print(json.dumps({"result": "ERROR",
                          "error": "missing required argument: --plan"}))
        return 2

    try:
        report = build_report(args)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return 2

    print(json.dumps(report, indent=2))
    return EXIT_CODES[report["result"]]


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    import shutil
    import tempfile
    import unittest

    HAPPY_PLAN = """# Demo Plan

## Milestone ordering — a stated deviation from the usual sequence

Prose only, not a milestone heading: no digit-leading identifier follows
"Milestone" here.

## Milestone 1 — Setup [API] [vs:api] [x]

## Task 1: Init repo

**Tags:** [API]

Done already.

## Milestone 2 — Persistence [API] [vs:api]

## Task 2: Add DB layer

**Tags:** [API]

## Task 3: Add migrations

**Tags:** [API]

### Checkpoint: schema review

## Milestone 3 — Reporting [API] [vs:api]

## Task 4: Add report UI

**Tags:** [UI]
"""

    DONE_PLAN = """# Demo Plan

## Milestone 1 — Setup [API] [vs:api] [x]

## Task 1: Init repo

**Tags:** [API]

## Milestone 2 — Persistence [API] [vs:api] [X]

## Task 2: Add DB layer

**Tags:** [API]
"""

    NO_MILESTONES_PLAN = """# Demo Plan

## Task 1: Init repo

**Tags:** [API]
"""

    MIXED_PLAN = """# Demo Plan

## Milestone 1 — Onboarding [vs:web+api]

## Task 1: Build screen

**Tags:** [UI]

## Task 2: Build endpoint

**Tags:** [API]
"""

    UNTAGGED_PLAN = """# Demo Plan

## Milestone 1 — Onboarding [vs:api]

## Task 1: Do something

No tags on this task at all.
"""

    # Domain-tagged and routable, but its verification surface is undeclared.
    NO_SURFACE_PLAN = """# Demo Plan

## Milestone 1 — Onboarding [API]

## Task 1: Add endpoint

**Tags:** [API]
"""

    BAD_SURFACE_PLAN = """# Demo Plan

## Milestone 1 — Onboarding [API] [vs:apo]

## Task 1: Add endpoint

**Tags:** [API]
"""

    LEVEL3_PLAN = """# Demo Plan

### Milestone 1 — Backend: contacts schema, list endpoint, create endpoint [API] [vs:api]

## Task 1: Create contacts schema

**Tags:** [API]

## Task 2: Add list endpoint

**Tags:** [API]

### Checkpoint: schema review

### Milestone 2 — Frontend: contacts list view [UI] [vs:ui]

## Task 3: Build contacts list UI

**Tags:** [UI]

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Data loss | High | Backups |
"""

    HEADING_TAG_AUTHORITY_PLAN = """# Demo Plan

### Milestone 1 — Backend only [API] [vs:api]

## Task 1: Do backend work

**Tags:** [API]

Note: the UI team will later consume this via a [UI] component, but that
is out of scope for this milestone.
"""

    BACKTICK_TAG_PLAN = """# Demo Plan

### Milestone 1 — Backend only `[API]` [vs:api]

## Task 1: Do backend work

**Tags:** [API]
"""

    LEVEL2_CHECKPOINT_PLAN = """# Demo Plan

## Milestone 1 — Setup [API] [vs:api]

## Task 1: Init repo

**Tags:** [API]

## Checkpoint: schema review

Notes about the checkpoint.

## Milestone 2 — Persistence [API] [vs:api]

## Task 2: Add DB layer

**Tags:** [API]
"""

    class NextMilestoneTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _plan(self, text, name="plan.md"):
            p = self.dir / name
            p.write_text(text, encoding="utf-8")
            return p

        def _state(self, cursor, name="orchestrator-state.json"):
            p = self.dir / name
            p.write_text(json.dumps({"milestone_cursor": cursor}))
            return p

        def _run(self, plan_path, state_path=None, **kw):
            base = dict(plan=str(plan_path),
                        state=str(state_path) if state_path else None,
                        ledger=None, emit_gate_args=False)
            base.update(kw)
            return build_report(argparse.Namespace(**base))

        def test_happy_path_derives_next(self):
            r = self._run(self._plan(HAPPY_PLAN))
            self.assertEqual(r["result"], "NEXT")
            self.assertEqual(r["next_milestone"]["title"], "Milestone 2 — Persistence [API] [vs:api]")
            self.assertEqual(r["next_milestone"]["domain"], "API")
            self.assertEqual(r["remaining"],
                             ["Milestone 2 — Persistence [API] [vs:api]", "Milestone 3 — Reporting [API] [vs:api]"])
            self.assertEqual(r["completed_count"], 1)
            self.assertEqual(r["total_count"], 3)
            self.assertIn("Task 2", r["milestone_text"])
            self.assertIn("Task 3", r["milestone_text"])
            self.assertNotIn("Task 4", r["milestone_text"])
            self.assertEqual(EXIT_CODES[r["result"]], 0)

        def test_prose_milestone_heading_not_counted(self):
            r = self._run(self._plan(HAPPY_PLAN))
            titles = [r["next_milestone"]["title"]] + r["remaining"]
            self.assertTrue(all("ordering" not in t for t in titles))
            self.assertEqual(r["total_count"], 3)

        def test_all_complete_is_done(self):
            r = self._run(self._plan(DONE_PLAN))
            self.assertEqual(r["result"], "DONE")
            self.assertIsNone(r["next_milestone"])
            self.assertIsNone(r["milestone_text"])
            self.assertEqual(r["remaining"], [])
            self.assertEqual(r["completed_count"], 2)
            self.assertEqual(EXIT_CODES[r["result"]], 0)

        def test_no_milestone_headings_raises(self):
            with self.assertRaises(GateError) as ctx:
                self._run(self._plan(NO_MILESTONES_PLAN))
            self.assertIn("## Milestone", str(ctx.exception))

        def test_mixed_tags(self):
            r = self._run(self._plan(MIXED_PLAN))
            self.assertEqual(r["result"], "MIXED")
            self.assertEqual(r["next_milestone"]["domain"], "MIXED")
            self.assertEqual(EXIT_CODES[r["result"]], 1)

        def test_untagged_is_planning_defect_like_mixed(self):
            r = self._run(self._plan(UNTAGGED_PLAN))
            self.assertEqual(r["result"], "MIXED")
            self.assertEqual(r["next_milestone"]["domain"], "UNTAGGED")
            self.assertTrue(any("UI" in w and "API" in w for w in r["warnings"]))
            self.assertEqual(EXIT_CODES[r["result"]], 1)

        # ---- verification-surface tag (the non-omissible axis) ----

        def test_missing_surface_tag_is_a_planning_defect(self):
            r = self._run(self._plan(NO_SURFACE_PLAN))
            self.assertEqual(r["result"], "MIXED")
            self.assertEqual(EXIT_CODES[r["result"]], 1)
            self.assertIsNone(r["next_milestone"]["surface"])
            self.assertEqual(r["next_milestone"]["domain"], "API")  # routable...
            self.assertTrue(any("[vs:<surface>]" in w for w in r["warnings"]))

        def test_unknown_surface_tag_is_a_planning_defect(self):
            r = self._run(self._plan(BAD_SURFACE_PLAN))
            self.assertEqual(r["result"], "MIXED")
            self.assertEqual(r["next_milestone"]["surface"], "apo")
            self.assertTrue(any("unknown verification" in w for w in r["warnings"]))

        def test_surface_reported_on_the_happy_path(self):
            r = self._run(self._plan(HAPPY_PLAN))
            self.assertEqual(r["result"], "NEXT")
            self.assertEqual(r["next_milestone"]["surface"], "api")

        def test_every_valid_surface_is_accepted(self):
            for surface in VALID_SURFACES:
                plan = f"# P\n\n## Milestone 1 — X [API] [vs:{surface}]\n\n## Task 1: t\n"
                r = self._run(self._plan(plan))
                self.assertEqual(r["result"], "NEXT", surface)
                self.assertEqual(r["next_milestone"]["surface"], surface)

        def test_heading_surface_wins_over_block_mention(self):
            plan = ("# P\n\n## Milestone 1 — X [API] [vs:api]\n\n"
                    "## Task 1: t\n\nprose mentioning [vs:rmm] in passing\n")
            r = self._run(self._plan(plan))
            self.assertEqual(r["next_milestone"]["surface"], "api")

        def test_surface_from_block_when_heading_has_none(self):
            plan = ("# P\n\n## Milestone 1 — X [API]\n\n"
                    "## Task 1: t\n\n**Verification surface:** [vs:fn]\n")
            r = self._run(self._plan(plan))
            self.assertEqual(r["result"], "NEXT")
            self.assertEqual(r["next_milestone"]["surface"], "fn")

        def test_vs_tag_does_not_collide_with_domain_tag(self):
            """`[vs:api]` must not read as `[API]` — the axes are orthogonal."""
            self.assertEqual(milestone_domain("## M 1 — X [vs:api]", ""), "UNTAGGED")
            self.assertEqual(milestone_surface("## M 1 — X [API]", ""), None)

        def test_stale_cursor(self):
            plan = self._plan(HAPPY_PLAN)
            state = self._state("Milestone 3 — Reporting")
            r = self._run(plan, state)
            self.assertEqual(r["next_milestone"]["title"], "Milestone 2 — Persistence [API] [vs:api]")
            self.assertTrue(r["cursor"]["stale"])
            self.assertFalse(r["cursor"]["matches_next"])
            self.assertEqual(EXIT_CODES[r["result"]], 0)

        def test_matching_cursor(self):
            plan = self._plan(HAPPY_PLAN)
            state = self._state("Milestone 2 — Persistence")
            r = self._run(plan, state)
            self.assertTrue(r["cursor"]["matches_next"])
            self.assertFalse(r["cursor"]["stale"])

        def test_null_cursor(self):
            plan = self._plan(HAPPY_PLAN)
            state = self._state(None)
            r = self._run(plan, state)
            self.assertIsNone(r["cursor"]["stored"])
            self.assertFalse(r["cursor"]["matches_next"])
            self.assertFalse(r["cursor"]["stale"])

        def test_unmatchable_cursor_warns(self):
            plan = self._plan(HAPPY_PLAN)
            state = self._state("Milestone 99 — Nonexistent")
            r = self._run(plan, state)
            self.assertFalse(r["cursor"]["matches_next"])
            self.assertFalse(r["cursor"]["stale"])
            self.assertTrue(any("does not match" in w for w in r["warnings"]))

        def test_missing_plan_raises(self):
            with self.assertRaises(GateError):
                self._run(self.dir / "nope.md")

        def test_invalid_state_json_raises(self):
            plan = self._plan(HAPPY_PLAN)
            state = self.dir / "orchestrator-state.json"
            state.write_text("not json")
            with self.assertRaises(GateError):
                self._run(plan, state)

        def test_missing_state_file_raises(self):
            plan = self._plan(HAPPY_PLAN)
            with self.assertRaises(GateError):
                self._run(plan, self.dir / "missing-state.json")

        def test_level3_headings_with_trailing_risks_section(self):
            milestones = parse_milestones(LEVEL3_PLAN)
            self.assertEqual(len(milestones), 2)
            m1, m2 = milestones
            self.assertTrue(m1["title"].startswith("Milestone 1"))
            self.assertEqual(m1["domain"], "API")
            self.assertIn("Task 1", m1["text"])
            self.assertIn("Task 2", m1["text"])
            self.assertIn("Checkpoint", m1["text"])
            self.assertNotIn("Milestone 2", m1["text"])
            self.assertTrue(m2["title"].startswith("Milestone 2"))
            self.assertEqual(m2["domain"], "UI")
            self.assertIn("Task 3", m2["text"])
            self.assertNotIn("Risks and Mitigations", m2["text"])

        def test_level3_plan_end_to_end(self):
            r = self._run(self._plan(LEVEL3_PLAN))
            self.assertEqual(r["result"], "NEXT")
            self.assertEqual(r["total_count"], 2)
            self.assertEqual(r["next_milestone"]["domain"], "API")
            self.assertEqual(EXIT_CODES[r["result"]], 0)

        def test_heading_tag_is_authoritative_over_prose_tag(self):
            milestones = parse_milestones(HEADING_TAG_AUTHORITY_PLAN)
            self.assertEqual(len(milestones), 1)
            self.assertEqual(milestones[0]["domain"], "API")
            r = self._run(self._plan(HEADING_TAG_AUTHORITY_PLAN))
            self.assertEqual(r["result"], "NEXT")
            self.assertEqual(r["next_milestone"]["domain"], "API")

        def test_heading_tag_with_backticks(self):
            milestones = parse_milestones(BACKTICK_TAG_PLAN)
            self.assertEqual(milestones[0]["domain"], "API")

        def test_level2_checkpoint_tolerated_with_warning(self):
            milestones = parse_milestones(LEVEL2_CHECKPOINT_PLAN)
            m1 = milestones[0]
            self.assertIn("Checkpoint: schema review", m1["text"])
            self.assertNotIn("Milestone 2", m1["text"])
            self.assertTrue(any("Checkpoint" in w for w in m1["warnings"]))

            r = self._run(self._plan(LEVEL2_CHECKPOINT_PLAN))
            self.assertEqual(r["result"], "NEXT")
            self.assertIn("Checkpoint: schema review", r["milestone_text"])
            self.assertTrue(any("Checkpoint" in w for w in r["warnings"]))

        # ---- --emit-gate-args ----

        def _probe_plan(self, checkpoint):
            return ("# P\n\n## Milestone 1 — Orders [API] [vs:api]\n\n"
                    "## Task 1: t\n\n**Tags:** [API]\n\n"
                    "### Checkpoint: Milestone 1\n" + checkpoint)

        def test_gate_args_parsed_from_the_canonical_probe_line(self):
            plan = self._probe_plan(
                "- [ ] RUNTIME PROBE: start: `npm run start`; probe: "
                "`curl -sS -i http://localhost:5142/api/orders`; "
                "expect-status: 200; require-keys: isSuccess, data\n")
            r = self._run(self._plan(plan), emit_gate_args=True)
            self.assertEqual(r["gate_args"], {
                "surface": "api", "expect_status": 200,
                "require_keys": ["isSuccess", "data"], "forbid_hosts": []})

        def test_gate_args_parses_loose_status_spellings(self):
            for probe, expected in (
                    ("- [ ] RUNTIME PROBE: probe: `curl /a`; expect 201\n", 201),
                    ("- [ ] RUNTIME PROBE: probe: `curl /a`; status 204\n", 204),
                    ("- [ ] RUNTIME PROBE: probe: `curl /a` returns 200 OK\n", 200)):
                r = self._run(self._plan(self._probe_plan(probe)),
                              emit_gate_args=True)
                self.assertEqual(r["gate_args"]["expect_status"], expected, probe)

        def test_gate_args_parses_loose_key_spellings(self):
            for probe in ("- [ ] RUNTIME PROBE: probe: `curl /a`; keys: a, b\n",
                          "- [ ] RUNTIME PROBE: probe: `curl /a`; "
                          "require-keys: `a`, `b`\n"):
                r = self._run(self._plan(self._probe_plan(probe)),
                              emit_gate_args=True)
                self.assertEqual(r["gate_args"]["require_keys"], ["a", "b"], probe)
            r = self._run(self._plan(self._probe_plan(
                "- [ ] RUNTIME PROBE: probe: `curl /a`; require-key isSuccess\n")),
                emit_gate_args=True)
            self.assertEqual(r["gate_args"]["require_keys"], ["isSuccess"])

        def test_gate_args_never_harvests_keys_from_the_probe_command(self):
            """Line-wide backtick harvesting would read `npm run start` as keys."""
            r = self._run(self._plan(self._probe_plan(
                "- [ ] RUNTIME PROBE: start: `npm run start`; probe: "
                "`curl -sS -i http://localhost:5142/api/orders`\n")),
                emit_gate_args=True)
            self.assertEqual(r["gate_args"]["require_keys"], [])
            self.assertIsNone(r["gate_args"]["expect_status"])

        def test_gate_args_are_null_when_probes_disagree(self):
            plan = self._probe_plan(
                "- [ ] RUNTIME PROBE: probe: `curl /a`; expect-status: 200; "
                "require-keys: a\n"
                "- [ ] RUNTIME PROBE: probe: `curl /b`; expect-status: 404; "
                "require-keys: b\n")
            r = self._run(self._plan(plan), emit_gate_args=True)
            self.assertIsNone(r["gate_args"]["expect_status"])
            self.assertEqual(r["gate_args"]["require_keys"], [])
            self.assertTrue(any("conflicting probe statuses" in w
                                for w in r["warnings"]))

        def test_gate_args_absent_probe_warns_and_carries_only_the_surface(self):
            r = self._run(self._plan(self._probe_plan("- [ ] All tests pass\n")),
                          emit_gate_args=True)
            self.assertEqual(r["gate_args"], {
                "surface": "api", "expect_status": None,
                "require_keys": [], "forbid_hosts": []})
            self.assertTrue(any("no 'RUNTIME PROBE:'" in w for w in r["warnings"]))

        def test_gate_args_null_without_the_flag_and_on_a_defect(self):
            r = self._run(self._plan(HAPPY_PLAN))
            self.assertIsNone(r["gate_args"])
            r = self._run(self._plan(MIXED_PLAN), emit_gate_args=True)
            self.assertEqual(r["result"], "MIXED")
            self.assertIsNone(r["gate_args"])

        # ---- --ledger: the ADVISORY unbacked-completion check ----

        def _ledger(self, *milestones, name="gates.jsonl"):
            p = self.dir / name
            with open(p, "w", encoding="utf-8") as fh:
                for m in milestones:
                    fh.write(json.dumps({
                        "ts": "2026-09-02T00:00:00Z",
                        "gate": "check_commit_gate.py", "argv": [],
                        "milestone": m, "inputs": {}, "verdict": "PASS",
                        "exit": 0}) + "\n")
            return p

        def test_hand_marked_complete_milestone_is_reported_as_unbacked(self):
            """`[x]` is a hand edit; nothing tied it to a commit or a gate."""
            ledger = self._ledger()
            r = self._run(self._plan(HAPPY_PLAN), ledger=str(ledger))
            self.assertEqual(r["unbacked_complete"],
                             ["Milestone 1 — Setup [API] [vs:api] [x]"])
            self.assertTrue(any("unbacked_complete" in w for w in r["warnings"]))
            self.assertEqual(r["result"], "NEXT")
            self.assertEqual(EXIT_CODES[r["result"]], 0)   # advisory only

        def test_backed_complete_milestone_is_not_reported(self):
            ledger = self._ledger("Milestone 1 — Setup")
            r = self._run(self._plan(HAPPY_PLAN), ledger=str(ledger))
            self.assertEqual(r["unbacked_complete"], [])

        def test_failing_ledger_entry_does_not_back_a_completion(self):
            ledger = self.dir / "gates.jsonl"
            ledger.write_text(json.dumps({
                "ts": "2026-09-02T00:00:00Z", "gate": "check_commit_gate.py",
                "argv": [], "milestone": "Milestone 1 — Setup", "inputs": {},
                "verdict": "FAIL", "exit": 1}) + "\n", encoding="utf-8")
            r = self._run(self._plan(HAPPY_PLAN), ledger=str(ledger))
            self.assertEqual(len(r["unbacked_complete"]), 1)

        def test_missing_ledger_warns_and_does_not_raise(self):
            r = self._run(self._plan(HAPPY_PLAN),
                          ledger=str(self.dir / "absent.jsonl"))
            self.assertEqual(r["unbacked_complete"], [])
            self.assertTrue(any("does not exist" in w for w in r["warnings"]))
            self.assertEqual(r["result"], "NEXT")

        def test_ledger_key_absent_without_the_flag(self):
            r = self._run(self._plan(HAPPY_PLAN))
            self.assertEqual(r["unbacked_complete"], [])

        def test_bom_prefixed_plan_still_parses(self):
            p = self.dir / "bom-plan.md"
            p.write_bytes(b"\xef\xbb\xbf" + HAPPY_PLAN.encode("utf-8"))
            r = self._run(p)
            self.assertEqual(r["result"], "NEXT")
            self.assertEqual(r["total_count"], 3)

        def test_level3_checkpoint_form_has_no_warning(self):
            # Canonical '### Checkpoint:' form is unchanged: included, no warning.
            milestones = parse_milestones(LEVEL3_PLAN)
            self.assertIn("Checkpoint", milestones[0]["text"])
            self.assertEqual(milestones[0]["warnings"], [])

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(NextMilestoneTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
