#!/usr/bin/env python3
"""Frontmatter integrity gate for agents/*.md and skills/*/SKILL.md.

A hand-rolled YAML frontmatter block is easy to break silently: an unquoted
scalar value that happens to contain ": " reads as a nested mapping to a real
YAML parser and the ENTIRE frontmatter block fails to parse, so the runtime
sees neither the agent's persona nor the skill's trigger. This has already
happened twice in this repo (agents/scout.md's `phase:` line, doubt-driven-
development's `description:` line) and gone unnoticed because nothing checked
frontmatter validity on its own -- only downstream symptoms (missing skill,
missing description) surfaced, long after the cause.

Checks, per agents/*.md and skills/*/SKILL.md file:
  (a) the leading `---` block exists and closes;
  (b) every non-blank, non-comment line inside it is a `key: value` pair;
  (c) a plain (unquoted) scalar value never contains ': ' -- that sequence is
      a real YAML parse failure (a quoted value may contain it freely);
  (d) a value that opens with a quote (" or ') closes with a matching one;
  (e) every required key is present -- agents: name, description, model,
      role, phase, squad, reports-to; skills: name, description
      (agents/blackgoat.md is EXEMPT from (b)-(e): CLAUDE.md convention #7
      makes it the author's psychological profile, not a normal persona --
      checked only for existence);
  (f) `model:`, where present, is one of opus/sonnet/haiku;
  (g) `description:` is <= 1024 chars (warning only);
  (h) every skills/bgpdd-*/SKILL.md carries `trigger: /bgpdd-<name>` matching
      its own folder name.

A plain scalar containing ' #' (space-hash) is valid YAML -- it is parsed as
an inline comment, silently truncating the value -- so it is deliberately
NOT flagged here; agents/alex.md's `depends-on: rex, aria # ...` line relies
on exactly this and must keep parsing clean.

Usage:
    python check_frontmatter.py <root_dir>
    python check_frontmatter.py --self-test

<root_dir> is the plugin root: it must contain the sibling `agents/` and/or
`skills/` directories. Pure standard library.
"""
import argparse
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

EXEMPT_AGENT = "blackgoat.md"
VALID_MODELS = {"opus", "sonnet", "haiku"}
MAX_DESCRIPTION_LEN = 1024
AGENT_REQUIRED_KEYS = ("name", "description", "model", "role", "phase", "squad", "reports-to")
SKILL_REQUIRED_KEYS = ("name", "description")

KEY_LINE_RE = re.compile(r"^([A-Za-z0-9_.-]+):(?:\s(.*))?$")


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def read_text(path):
    p = Path(path)
    if not p.is_file():
        raise GateError(f"file not found or not readable: {path}")
    return p.read_text(encoding="utf-8-sig", errors="replace")


def split_frontmatter(text):
    """Return (body_lines, status).

    status is one of:
      "ok"             -- body_lines are the lines strictly between the two
                          '---' markers (1-indexed line 2 is body_lines[0])
      "no-frontmatter" -- the file does not open with a '---' line
      "unclosed"       -- an opening '---' was found but never closes
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return [], "no-frontmatter"
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "ok"
    return [], "unclosed"


def unquote(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse_frontmatter(body_lines, start_line_no=2):
    """Parse frontmatter body lines into (fields, parse_errors).

    fields is {key: raw_value_string} for every line that structurally reads
    as `key: value` (or bare `key:`) -- a key is recorded even when its own
    value is separately flagged as a parse error below, so one broken value
    never hides an otherwise-present required key.

    parse_errors is [(line_no, problem), ...] for lines that break YAML
    frontmatter parsing: a line that is not blank, a full-line comment, or
    `key: value`; a plain scalar containing ': '; or a value opening with a
    quote that never closes.
    """
    fields = {}
    parse_errors = []
    for offset, line in enumerate(body_lines):
        line_no = start_line_no + offset
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = KEY_LINE_RE.match(stripped)
        if not match:
            parse_errors.append((line_no, f"key line is not `key: value`: {stripped!r}"))
            continue
        key, value = match.group(1), (match.group(2) or "").strip()
        fields[key] = value
        if not value:
            continue
        if value[0] in "\"'":
            quote = value[0]
            if len(value) < 2 or value[-1] != quote:
                parse_errors.append(
                    (line_no, f"value for '{key}' opens with {quote} that never closes: {value!r}")
                )
        elif ": " in value:
            parse_errors.append(
                (line_no,
                 f"unquoted scalar for '{key}' contains ': ' -- a real YAML parser reads this "
                 f"as a nested mapping and the whole frontmatter block fails to parse: {value!r}")
            )
    return fields, parse_errors


def _issue(rel, line, problem):
    return {"file": rel, "line": line, "problem": problem}


def check_agent_file(path, rel):
    """Return (errors, warnings) for one agents/<name>.md file."""
    if path.name == EXEMPT_AGENT:
        return [], []  # CLAUDE.md convention #7: existence-only exemption

    errors, warnings = [], []
    text = read_text(path)
    body, status = split_frontmatter(text)

    if status == "no-frontmatter":
        return [_issue(rel, 1, "no frontmatter block found (file must open with '---')")], []
    if status == "unclosed":
        return [_issue(rel, 1, "frontmatter block never closes (no second '---' found)")], []

    fields, parse_errors = parse_frontmatter(body)
    errors.extend(_issue(rel, line, problem) for line, problem in parse_errors)

    for key in AGENT_REQUIRED_KEYS:
        if key not in fields:
            errors.append(_issue(rel, 1, f"missing required key: {key}"))

    model = fields.get("model")
    if model is not None and unquote(model) not in VALID_MODELS:
        errors.append(
            _issue(rel, 1, f"invalid model '{unquote(model)}': must be one of {sorted(VALID_MODELS)}")
        )

    description = fields.get("description")
    if description is not None and len(unquote(description)) > MAX_DESCRIPTION_LEN:
        warnings.append(
            _issue(rel, 1, f"description is {len(unquote(description))} chars, exceeds {MAX_DESCRIPTION_LEN}")
        )

    return errors, warnings


def check_skill_file(path, rel, skill_dir_name):
    """Return (errors, warnings) for one skills/<name>/SKILL.md file."""
    errors, warnings = [], []
    text = read_text(path)
    body, status = split_frontmatter(text)

    if status == "no-frontmatter":
        return [_issue(rel, 1, "no frontmatter block found (file must open with '---')")], []
    if status == "unclosed":
        return [_issue(rel, 1, "frontmatter block never closes (no second '---' found)")], []

    fields, parse_errors = parse_frontmatter(body)
    errors.extend(_issue(rel, line, problem) for line, problem in parse_errors)

    for key in SKILL_REQUIRED_KEYS:
        if key not in fields:
            errors.append(_issue(rel, 1, f"missing required key: {key}"))

    description = fields.get("description")
    if description is not None and len(unquote(description)) > MAX_DESCRIPTION_LEN:
        warnings.append(
            _issue(rel, 1, f"description is {len(unquote(description))} chars, exceeds {MAX_DESCRIPTION_LEN}")
        )

    if skill_dir_name.startswith("bgpdd-"):
        expected_trigger = f"/{skill_dir_name}"
        trigger = fields.get("trigger")
        if trigger is None:
            errors.append(
                _issue(rel, 1,
                       f"missing required key: trigger (every bgpdd-* skill must declare "
                       f"trigger: {expected_trigger})")
            )
        elif unquote(trigger) != expected_trigger:
            errors.append(
                _issue(rel, 1, f"trigger '{unquote(trigger)}' does not match expected '{expected_trigger}'")
            )

    return errors, warnings


def check_all(root):
    """Return (files_checked, errors, warnings) across the whole plugin root."""
    root = Path(root)
    agents_dir = root / "agents"
    skills_dir = root / "skills"

    if not agents_dir.is_dir() and not skills_dir.is_dir():
        raise GateError(f"neither {agents_dir} nor {skills_dir} exist under {root}")

    files_checked = []
    errors = []
    warnings = []

    if agents_dir.is_dir():
        for path in sorted(agents_dir.glob("*.md")):
            rel = path.relative_to(root).as_posix()
            files_checked.append(rel)
            file_errors, file_warnings = check_agent_file(path, rel)
            errors.extend(file_errors)
            warnings.extend(file_warnings)

    if skills_dir.is_dir():
        for path in sorted(skills_dir.glob("*/SKILL.md")):
            rel = path.relative_to(root).as_posix()
            files_checked.append(rel)
            file_errors, file_warnings = check_skill_file(path, rel, path.parent.name)
            errors.extend(file_errors)
            warnings.extend(file_warnings)

    return files_checked, errors, warnings


def build_report(root):
    files_checked, errors, warnings = check_all(root)
    return {
        "result": "PASS" if not errors else "FAIL",
        "files_checked": files_checked,
        "errors": errors,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


def run_self_test():
    import shutil

    class FrontmatterTests(unittest.TestCase):
        def setUp(self):
            self.dir = Path(tempfile.mkdtemp())
            (self.dir / "agents").mkdir()
            (self.dir / "skills").mkdir()

        def tearDown(self):
            shutil.rmtree(self.dir, ignore_errors=True)

        def _write_agent(self, name, frontmatter_lines, body="\n## Methodology Dependencies\n"):
            text = "---\n" + "\n".join(frontmatter_lines) + "\n---\n" + body
            (self.dir / "agents" / name).write_text(text, encoding="utf-8")

        def _write_skill(self, dirname, frontmatter_lines, body="\n# Skill\n"):
            skill_dir = self.dir / "skills" / dirname
            skill_dir.mkdir()
            text = "---\n" + "\n".join(frontmatter_lines) + "\n---\n" + body
            (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")

        VALID_AGENT_LINES = [
            "model: sonnet",
            "name: rex",
            'description: "Translates user intent into requirements."',
            "role: Requirements Analyst",
            "phase: Plan 1 — Requirements",
            "squad: agent-squad",
            "reports-to: agent-squad",
        ]

        def test_unquoted_colon_is_error(self):
            lines = list(self.VALID_AGENT_LINES)
            lines[4] = "phase: Cross-pipeline — Research Worker (primary: bgpdd-discovery)"
            self._write_agent("rex.md", lines)
            files_checked, errors, warnings = check_all(self.dir)
            self.assertTrue(any("phase" in e["problem"] and "': '" in e["problem"] for e in errors))

        def test_quoted_colon_is_ok(self):
            lines = list(self.VALID_AGENT_LINES)
            lines[4] = 'phase: "Cross-pipeline — Research Worker (primary: bgpdd-discovery)"'
            self._write_agent("rex.md", lines)
            files_checked, errors, warnings = check_all(self.dir)
            self.assertEqual(errors, [])

        def test_missing_key_is_error(self):
            lines = [l for l in self.VALID_AGENT_LINES if not l.startswith("role:")]
            self._write_agent("rex.md", lines)
            files_checked, errors, warnings = check_all(self.dir)
            self.assertTrue(any(e["problem"] == "missing required key: role" for e in errors))

        def test_bad_model_is_error(self):
            lines = list(self.VALID_AGENT_LINES)
            lines[0] = "model: gpt-5"
            self._write_agent("rex.md", lines)
            files_checked, errors, warnings = check_all(self.dir)
            self.assertTrue(any("invalid model" in e["problem"] for e in errors))

        def test_missing_trigger_on_bgpdd_skill_is_error(self):
            self._write_skill("bgpdd-lite", [
                "name: bgpdd-lite",
                'description: "The mid-weight PDD pipeline for well-specified work."',
            ])
            files_checked, errors, warnings = check_all(self.dir)
            self.assertTrue(any("trigger" in e["problem"] for e in errors))

        def test_present_trigger_on_bgpdd_skill_is_ok(self):
            self._write_skill("bgpdd-lite", [
                "name: bgpdd-lite",
                'description: "The mid-weight PDD pipeline for well-specified work."',
                "trigger: /bgpdd-lite",
            ])
            files_checked, errors, warnings = check_all(self.dir)
            self.assertEqual(errors, [])

        def test_blackgoat_is_exempt(self):
            # Deliberately broken/incomplete frontmatter: no model, no phase,
            # no closing quote -- none of it should be flagged, per CLAUDE.md
            # convention #7 (existence-only exemption).
            self._write_agent("blackgoat.md", [
                "name: blackgoat",
                'description: "unterminated',
            ])
            files_checked, errors, warnings = check_all(self.dir)
            self.assertIn("agents/blackgoat.md", files_checked)
            self.assertEqual(errors, [])

        def test_happy_path_agent_and_skill(self):
            self._write_agent("rex.md", self.VALID_AGENT_LINES)
            self._write_skill("bgpdd-lite", [
                "name: bgpdd-lite",
                'description: "The mid-weight PDD pipeline for well-specified work."',
                "trigger: /bgpdd-lite",
            ])
            files_checked, errors, warnings = check_all(self.dir)
            self.assertEqual(errors, [])
            self.assertEqual(len(files_checked), 2)

        def test_missing_agents_and_skills_dirs_raises(self):
            empty_root = Path(tempfile.mkdtemp())
            try:
                with self.assertRaises(GateError):
                    check_all(empty_root)
            finally:
                shutil.rmtree(empty_root, ignore_errors=True)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FrontmatterTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv):
    parser = argparse.ArgumentParser(prog="check_frontmatter.py")
    parser.add_argument("root", nargs="?", help="plugin root dir (contains agents/, skills/)")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if not args.root:
        print(json.dumps({"result": "ERROR", "error": "missing required argument: root"}))
        return 2

    root = Path(args.root)
    if not root.is_dir():
        print(json.dumps({"result": "ERROR", "error": f"{root} is not a directory"}))
        return 2

    try:
        report = build_report(root)
    except GateError as exc:
        print(json.dumps({"result": "ERROR", "error": str(exc)}))
        return 2

    print(json.dumps(report, indent=2))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
