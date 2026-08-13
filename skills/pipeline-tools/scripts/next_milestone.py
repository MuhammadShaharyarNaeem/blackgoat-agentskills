#!/usr/bin/env python3
"""Deterministic next-milestone derivation for the bgpdd-build Orchestrator.

Reads plan.md once and emits only what the Orchestrator needs to route the
next build phase: the next pending milestone (title, heading line, domain),
its full block text verbatim, the remaining pending milestone titles, and an
optional staleness check against orchestrator-state.json's milestone_cursor.
This replaces re-reading the entire plan (290K+ chars in real plans) every
time the Orchestrator must decide what to build next.

Usage:
    python next_milestone.py --plan <path> [--state <path>]
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


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_text(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding="utf-8", errors="replace")


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
    heading (level 2 or 3), the next level-2 heading whose text does not
    start with "Task" (this is what ends the task list at a trailing
    section like "## Risks and Mitigations" or "## Open Questions"), or
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

    return report


def main(argv):
    parser = argparse.ArgumentParser(prog="next_milestone.py")
    parser.add_argument("--plan")
    parser.add_argument("--state")
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

        def _run(self, plan_path, state_path=None):
            ns = argparse.Namespace(plan=str(plan_path),
                                    state=str(state_path) if state_path else None)
            return build_report(ns)

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
