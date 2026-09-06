#!/usr/bin/env python3
"""Mechanical lint for `skills/agent-squad/always-on.md`, the session-start index.

The index is injected into every session, including ones that never type a lane
command, so it is the plugin's first and sometimes only self-description. It
claims to be "an index, not a contract": every entry names a file that owns the
rule. Two failure modes make that claim false and nothing caught either one --
a lane added under `skills/` with no row (invisible to every ordinary chat) and
a row or owner pointer whose file was renamed out from under it (a pointer to
nothing, read as authority).

CLAUDE.md convention #9: an index nobody re-reads drifts silently, so the check
is a command in CI rather than a line asking a reader to look.

Usage:
    python check_always_on.py [--index <path>] [--plugin-root <dir>] \
        [--max-words N] [--ledger <path>] [--milestone "<title>"]
    python check_always_on.py --self-test

Exit 0 PASS, 1 FAIL (findings), 2 ERROR (usage, unreadable index/root).
Pure standard library.
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

# scripts/ -> pipeline-tools/ -> skills/ -> plugin root
DEFAULT_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INDEX_REL = Path("skills") / "agent-squad" / "always-on.md"

LANES_HEADING = "## The lanes"
RULES_HEADING = "## Outside any lane"
EXPECTED_RULE_COUNT = 4
DEFAULT_MAX_WORDS = 20

BACKTICK_RE = re.compile(r"`([^`\n]+)`")
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
SEPARATOR_ROW_RE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
NUMBERED_ITEM_RE = re.compile(r"^\s*(\d+)\.\s+(.*)$")
SCRIPT_TOKEN_RE = re.compile(r"^[\w.-]+\.py$")
SCRIPTS_REL = Path("skills") / "pipeline-tools" / "scripts"


class GateError(Exception):
    """Structural/usage failure -- maps to exit 2."""


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
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"Warning: could not append to ledger {ledger_path}: {exc}",
              file=sys.stderr)


def lanes_on_disk(plugin_root):
    """Every `/bg*` lane that exists as a skill folder with a SKILL.md."""
    skills = Path(plugin_root) / "skills"
    if not skills.is_dir():
        raise GateError(f"no skills/ directory under --plugin-root: {plugin_root}")
    found = set()
    for child in sorted(skills.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if name != "bg" and not name.startswith("bgpdd-"):
            continue
        if (child / "SKILL.md").is_file():
            found.add("/" + name)
    return found


def section_lines(lines, heading):
    """The lines between `heading` and the next `## ` heading."""
    out = []
    inside = False
    for line in lines:
        if line.strip() == heading:
            inside = True
            continue
        if inside and line.startswith("## "):
            break
        if inside:
            out.append(line)
    return out


def parse_table(lines):
    """Body rows of the first markdown table in `lines`, as cell lists."""
    rows = []
    seen_header = False
    for line in lines:
        match = TABLE_ROW_RE.match(line)
        if not match:
            if rows or seen_header:
                # The table ended; a second table in the same section is not
                # the lane table.
                if rows:
                    break
            continue
        if SEPARATOR_ROW_RE.match(line):
            seen_header = True
            continue
        cells = [c.strip() for c in match.group(1).split("|")]
        if not seen_header:
            continue
        rows.append(cells)
    return rows


def word_count(cell):
    """Words in a table cell, ignoring markdown punctuation-only tokens."""
    return len([t for t in cell.split() if t.strip("`*_|")])


def resolve_citation(plugin_root, token):
    """(kind, resolved_or_None) for one backticked token.

    Only two kinds of token are treated as a citation this gate can check: a
    slash-bearing relative path, and a bare `*.py` script name (the index cites
    `check_commit_gate.py` and `check_quick_close.py` that way). A lane command
    (`/bg...`), a prose token and a bare filename of any other kind are not
    claims about the tree, so they are not findings.
    """
    root = Path(plugin_root)
    item = token.strip()
    if not item or item.startswith("/"):
        return "not-a-path", None
    if SCRIPT_TOKEN_RE.match(item):
        candidate = root / SCRIPTS_REL / item
        return "script", candidate if candidate.is_file() else None
    if "/" not in item:
        return "not-a-path", None
    if any(ch in item for ch in " <>{}"):
        # A template placeholder such as `.docs/{project-name}/` names no one
        # file on disk.
        return "not-a-path", None
    candidate = root / item
    return "path", candidate if candidate.exists() else None


def build_report(index_path, plugin_root, max_words=DEFAULT_MAX_WORDS):
    index = Path(index_path)
    if not index.is_file():
        raise GateError(f"index file not found: {index_path}")
    root = Path(plugin_root)
    if not root.is_dir():
        raise GateError(f"--plugin-root is not a directory: {plugin_root}")
    text = index.read_text(encoding="utf-8-sig", errors="replace")
    lines = text.splitlines()

    report = {
        "result": None,
        "index": str(index_path),
        "plugin_root": str(plugin_root),
        "max_words": max_words,
        "lanes_on_disk": sorted(lanes_on_disk(root)),
        "lanes_in_table": [],
        "rule_count": 0,
        "findings": [],
        "warnings": [],
        "error": None,
    }

    def finding(code, detail, **extra):
        entry = {"code": code, "detail": detail}
        entry.update(extra)
        report["findings"].append(entry)

    # --- the lane table ------------------------------------------------
    lane_lines = section_lines(lines, LANES_HEADING)
    if not lane_lines:
        finding("section_missing", f"no '{LANES_HEADING}' section in the index")
        rows = []
    else:
        rows = parse_table(lane_lines)
        if not rows:
            finding("section_missing",
                    f"'{LANES_HEADING}' section has no table body rows")

    table_lanes = []
    for cells in rows:
        first = cells[0].strip().strip("`").strip()
        if not first.startswith("/"):
            finding("lane_row_orphan",
                    f"table row does not name a lane command: {cells[0]!r}",
                    row=cells[0])
            continue
        table_lanes.append(first)
        for index_of, cell in enumerate(cells):
            count = word_count(cell)
            if count > max_words:
                finding("cell_too_long",
                        f"row {first} column {index_of + 1}: {count} words "
                        f"(max {max_words})",
                        lane=first, column=index_of + 1, words=count)
    report["lanes_in_table"] = table_lanes

    for lane in sorted(set(table_lanes)):
        if lane not in report["lanes_on_disk"]:
            finding("lane_row_orphan",
                    f"row for {lane} but skills/{lane.lstrip('/')}/SKILL.md "
                    "does not exist", lane=lane)
    for lane in report["lanes_on_disk"]:
        if lane not in table_lanes:
            finding("lane_missing_row",
                    f"{lane} exists on disk with no row in '{LANES_HEADING}'",
                    lane=lane)
    duplicates = sorted({l for l in table_lanes if table_lanes.count(l) > 1})
    for lane in duplicates:
        finding("lane_row_orphan", f"{lane} has more than one row", lane=lane)

    # --- every cited path resolves --------------------------------------
    for line_no, line in enumerate(lines, start=1):
        for token in BACKTICK_RE.findall(line):
            kind, resolved = resolve_citation(root, token)
            if kind == "not-a-path":
                continue
            if resolved is None:
                finding("path_missing",
                        f"line {line_no}: cited {kind} `{token}` does not "
                        "resolve under the plugin root",
                        line=line_no, token=token)

    # --- the four outside-any-lane rules --------------------------------
    rule_lines = section_lines(lines, RULES_HEADING)
    if not rule_lines:
        finding("section_missing", f"no '{RULES_HEADING}' section in the index")
    else:
        items = [m.group(2) for m in
                 (NUMBERED_ITEM_RE.match(l) for l in rule_lines) if m]
        report["rule_count"] = len(items)
        if len(items) != EXPECTED_RULE_COUNT:
            finding("rule_count",
                    f"'{RULES_HEADING}' has {len(items)} numbered rules; "
                    f"the section's own prose says {EXPECTED_RULE_COUNT}",
                    found=len(items), expected=EXPECTED_RULE_COUNT)
        for position, item in enumerate(items, start=1):
            if "Owner:" not in item:
                finding("rule_owner_missing",
                        f"rule {position} names no `Owner:`", rule=position)
                continue
            owner_text = item.split("Owner:", 1)[1]
            owners = [t for t in BACKTICK_RE.findall(owner_text)
                      if resolve_citation(root, t)[0] != "not-a-path"]
            if not owners:
                finding("rule_owner_missing",
                        f"rule {position} says Owner: but cites no file path",
                        rule=position)
                continue
            for token in owners:
                kind, resolved = resolve_citation(root, token)
                if resolved is None:
                    finding("rule_owner_missing",
                            f"rule {position} names owner `{token}`, which does "
                            "not exist", rule=position, token=token)

    report["result"] = "FAIL" if report["findings"] else "PASS"
    return report


def main(argv):
    parser = argparse.ArgumentParser(prog="check_always_on.py")
    parser.add_argument("--plugin-root", default=str(DEFAULT_PLUGIN_ROOT),
                        help="plugin root (default: derived from this script's path)")
    parser.add_argument("--index",
                        help=f"index file (default: <plugin-root>/{DEFAULT_INDEX_REL.as_posix()})")
    parser.add_argument("--max-words", type=int, default=DEFAULT_MAX_WORDS,
                        help=f"maximum words per table cell (default {DEFAULT_MAX_WORDS})")
    parser.add_argument("--milestone", help="recorded in the ledger line")
    parser.add_argument("--ledger", help="append one JSON record per run to this path")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    index = args.index or str(Path(args.plugin_root) / DEFAULT_INDEX_REL)

    def finish(code, verdict):
        """One exit point: EVERY return path records a ledger line."""
        append_ledger(args.ledger, argv, args.milestone, [index], verdict, code)
        return code

    try:
        report = build_report(index, args.plugin_root, args.max_words)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return finish(2, "ERROR")

    print(json.dumps(report, indent=2))
    return finish(0, "PASS") if report["result"] == "PASS" else finish(1, "FAIL")


def run_self_test():
    import shutil

    HEADER = "# Index\n\nPreamble.\n\n"

    class AlwaysOnTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            self.skills = self.dir / "skills"
            for lane in ("bg", "bgpdd-quick"):
                (self.skills / lane).mkdir(parents=True)
                (self.skills / lane / "SKILL.md").write_text("x", encoding="utf-8")
            (self.skills / "agent-squad").mkdir(parents=True)
            (self.skills / "agent-squad" / "base-persona.md").write_text(
                "x", encoding="utf-8")
            (self.skills / "test-driven-development").mkdir(parents=True)
            (self.skills / "test-driven-development" / "SKILL.md").write_text(
                "x", encoding="utf-8")
            (self.skills / "pipeline-tools" / "scripts").mkdir(parents=True)
            (self.skills / "pipeline-tools" / "SKILL.md").write_text(
                "x", encoding="utf-8")
            (self.skills / "pipeline-tools" / "scripts"
             / "check_commit_gate.py").write_text("x", encoding="utf-8")
            (self.skills / "agent-squad" / "orchestrator-contract.md").write_text(
                "x", encoding="utf-8")
            self.index = self.dir / "always-on.md"

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def codes(self, report):
            return sorted({f["code"] for f in report["findings"]})

        def write(self, lanes_rows, rules=None):
            table = ("| Lane | What it is for |\n|---|---|\n" + lanes_rows)
            if rules is None:
                rules = "\n".join([
                    "1. **Evidence.** Owner: `skills/agent-squad/base-persona.md`.",
                    "2. **Tests.** Owner: `skills/test-driven-development/SKILL.md`.",
                    "3. **Commits.** Owner: `skills/pipeline-tools/SKILL.md`.",
                    "4. **Ask first.** Owner: "
                    "`skills/agent-squad/orchestrator-contract.md`.",
                ])
            self.index.write_text(
                HEADER + LANES_HEADING + "\n\n" + table + "\n\n"
                + RULES_HEADING + "\n\n" + rules + "\n",
                encoding="utf-8")

        def report(self, **kw):
            return build_report(self.index, self.dir, **kw)

        # --- happy path -------------------------------------------------
        def test_complete_index_passes(self):
            self.write("| `/bg` | Front door. |\n| `/bgpdd-quick` | One change. |\n")
            r = self.report()
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertEqual(r["lanes_on_disk"], ["/bg", "/bgpdd-quick"])
            self.assertEqual(r["rule_count"], 4)

        # --- lane coverage ----------------------------------------------
        def test_lane_on_disk_with_no_row_fails(self):
            self.write("| `/bg` | Front door. |\n")
            r = self.report()
            self.assertEqual(self.codes(r), ["lane_missing_row"])
            self.assertEqual(r["findings"][0]["lane"], "/bgpdd-quick")

        def test_row_for_a_lane_that_does_not_exist_fails(self):
            self.write("| `/bg` | Front door. |\n| `/bgpdd-quick` | One. |\n"
                       "| `/bgpdd-ghost` | Nothing. |\n")
            self.assertEqual(self.codes(self.report()), ["lane_row_orphan"])

        def test_a_lane_folder_without_skill_md_is_not_a_lane(self):
            (self.skills / "bgpdd-draft").mkdir()
            self.write("| `/bg` | Front door. |\n| `/bgpdd-quick` | One. |\n")
            r = self.report()
            self.assertEqual(r["result"], "PASS", r["findings"])
            self.assertNotIn("/bgpdd-draft", r["lanes_on_disk"])

        def test_duplicate_row_fails(self):
            self.write("| `/bg` | Front door. |\n| `/bgpdd-quick` | One. |\n"
                       "| `/bg` | Front door again. |\n")
            self.assertEqual(self.codes(self.report()), ["lane_row_orphan"])

        # --- cell budget ------------------------------------------------
        def test_cell_over_the_word_budget_fails(self):
            long_cell = " ".join(["word"] * 21)
            self.write(f"| `/bg` | {long_cell} |\n| `/bgpdd-quick` | One. |\n")
            r = self.report()
            self.assertEqual(self.codes(r), ["cell_too_long"])
            self.assertEqual(r["findings"][0]["words"], 21)

        def test_cell_exactly_at_the_budget_passes(self):
            cell = " ".join(["word"] * 20)
            self.write(f"| `/bg` | {cell} |\n| `/bgpdd-quick` | One. |\n")
            self.assertEqual(self.report()["result"], "PASS")

        def test_max_words_is_configurable(self):
            cell = " ".join(["word"] * 12)
            self.write(f"| `/bg` | {cell} |\n| `/bgpdd-quick` | One. |\n")
            self.assertEqual(self.report(max_words=10)["result"], "FAIL")

        # --- citations --------------------------------------------------
        def test_unresolvable_cited_path_fails(self):
            self.write("| `/bg` | Front door. |\n| `/bgpdd-quick` | One. |\n")
            self.index.write_text(
                self.index.read_text(encoding="utf-8")
                + "\nSee `skills/agent-squad/gone.md` for more.\n", encoding="utf-8")
            r = self.report()
            self.assertEqual(self.codes(r), ["path_missing"])
            self.assertEqual(r["findings"][0]["token"], "skills/agent-squad/gone.md")

        def test_bare_script_name_is_resolved_against_the_scripts_dir(self):
            self.write("| `/bg` | Front door. |\n| `/bgpdd-quick` | One. |\n")
            base = self.index.read_text(encoding="utf-8")
            self.index.write_text(base + "\nThe gate is `check_commit_gate.py`.\n",
                                  encoding="utf-8")
            self.assertEqual(self.report()["result"], "PASS")
            self.index.write_text(base + "\nThe gate is `check_gone.py`.\n",
                                  encoding="utf-8")
            self.assertEqual(self.codes(self.report()), ["path_missing"])

        def test_lane_commands_and_placeholders_are_not_path_claims(self):
            self.write("| `/bg` | Front door. |\n| `/bgpdd-quick` | One. |\n")
            self.index.write_text(
                self.index.read_text(encoding="utf-8")
                + "\nArtifacts land under `.docs/{project-name}/`.\n",
                encoding="utf-8")
            self.assertEqual(self.report()["result"], "PASS")

        # --- outside-any-lane rules -------------------------------------
        def test_rule_with_no_owner_fails(self):
            self.write("| `/bg` | Front door. |\n| `/bgpdd-quick` | One. |\n",
                       rules="\n".join([
                           "1. **Evidence.** Owner: "
                           "`skills/agent-squad/base-persona.md`.",
                           "2. **Tests.** No owner named here.",
                           "3. **Commits.** Owner: `skills/pipeline-tools/SKILL.md`.",
                           "4. **Ask.** Owner: "
                           "`skills/agent-squad/orchestrator-contract.md`.",
                       ]))
            self.assertEqual(self.codes(self.report()), ["rule_owner_missing"])

        def test_rule_owner_that_does_not_exist_fails(self):
            self.write("| `/bg` | Front door. |\n| `/bgpdd-quick` | One. |\n",
                       rules="\n".join([
                           "1. **Evidence.** Owner: `skills/agent-squad/gone.md`.",
                           "2. **Tests.** Owner: "
                           "`skills/test-driven-development/SKILL.md`.",
                           "3. **Commits.** Owner: `skills/pipeline-tools/SKILL.md`.",
                           "4. **Ask.** Owner: "
                           "`skills/agent-squad/orchestrator-contract.md`.",
                       ]))
            codes = self.codes(self.report())
            self.assertIn("rule_owner_missing", codes)

        def test_wrong_rule_count_fails(self):
            self.write("| `/bg` | Front door. |\n| `/bgpdd-quick` | One. |\n",
                       rules="1. **Evidence.** Owner: "
                             "`skills/agent-squad/base-persona.md`.")
            r = self.report()
            self.assertIn("rule_count", self.codes(r))
            self.assertEqual(r["rule_count"], 1)

        def test_missing_sections_fail(self):
            self.index.write_text(HEADER, encoding="utf-8")
            self.assertEqual(self.codes(self.report()),
                             ["lane_missing_row", "section_missing"])

        # --- plumbing ---------------------------------------------------
        def test_missing_index_or_root_is_an_error(self):
            with self.assertRaises(GateError):
                build_report(self.dir / "nope.md", self.dir)
            self.write("| `/bg` | Front door. |\n| `/bgpdd-quick` | One. |\n")
            with self.assertRaises(GateError):
                build_report(self.index, self.dir / "nope")

        def test_ledger_records_every_exit_path(self):
            ledger = self.dir / "logs" / "gates.jsonl"
            self.write("| `/bg` | Front door. |\n| `/bgpdd-quick` | One. |\n")
            self.assertEqual(main(["--index", str(self.index), "--plugin-root",
                                   str(self.dir), "--ledger", str(ledger)]), 0)
            self.write("| `/bg` | Front door. |\n")
            self.assertEqual(main(["--index", str(self.index), "--plugin-root",
                                   str(self.dir), "--ledger", str(ledger)]), 1)
            self.assertEqual(main(["--index", str(self.dir / "nope.md"),
                                   "--plugin-root", str(self.dir),
                                   "--ledger", str(ledger)]), 2)
            records = [json.loads(l) for l in
                       ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual([r["verdict"] for r in records],
                             ["PASS", "FAIL", "ERROR"])
            self.assertTrue(all(r["gate"] == "check_always_on.py" for r in records))

        def test_the_shipped_index_passes(self):
            """The gate must be true of the file it was written for."""
            index = DEFAULT_PLUGIN_ROOT / DEFAULT_INDEX_REL
            if not index.is_file():
                self.skipTest("always-on.md not resolvable from this checkout")
            r = build_report(index, DEFAULT_PLUGIN_ROOT)
            self.assertEqual(r["result"], "PASS", json.dumps(r["findings"], indent=2))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AlwaysOnTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
