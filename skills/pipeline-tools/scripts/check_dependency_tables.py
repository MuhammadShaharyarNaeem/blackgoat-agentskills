#!/usr/bin/env python3
"""Validates the Methodology Dependencies tables in agents/*.md.

Verifies, for every agent persona except blackgoat.md (the author's
psychological profile, exempt by design):

  (a) a "## Methodology Dependencies" section exists at all;
  (b) that section contains the canonical "NOT Skill-tool invocables"
      wording, so a delegated agent cannot mistake a dependency-table path
      for a Skill-tool invocation.
  (c) every `{PLUGIN_ROOT}` path in that section's table resolves to an
      existing file, with {PLUGIN_ROOT} resolved to the skills/ dir passed
      on the command line. A path is matched whether or not it is wrapped
      in backticks.

Fails closed: a missing or empty agents/ directory is a usage error (exit
2), not a vacuous PASS, and an agent with no dependency section at all is a
violation (exit 1) rather than something silently skipped.

Usage:
    python check_dependency_tables.py <skills_dir>
    python check_dependency_tables.py --self-test

<skills_dir> is the plugin's skills/ directory (i.e. {PLUGIN_ROOT}).
agents/ is located as the sibling directory of <skills_dir>.

Pure standard library. See ../SKILL.md for usage notes.
"""
import sys
import re
import tempfile
import unittest
from pathlib import Path

CANONICAL_WORDING = "NOT Skill-tool invocables"
EXCLUDED_AGENTS = {"blackgoat.md"}

SECTION_HEADING_RE = re.compile(r"^##\s*Methodology Dependencies\s*$", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^##\s+\S", re.MULTILINE)
# Matches `{PLUGIN_ROOT}/some/path` whether or not it is wrapped in
# backticks. The path runs to the first character that can't plausibly be
# part of one: whitespace, a closing backtick, a markdown table pipe, a
# comma, or a closing paren/bracket (all observed as the next character
# after a path in a dependency table cell or parenthetical aside).
PLUGIN_ROOT_PATH_RE = re.compile(r"\{PLUGIN_ROOT\}(/[^\s`|,)\]]+)")


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def find_section(text):
    """Return the "## Methodology Dependencies" section body, or None.

    The body runs from just after the heading to the next "## " heading
    (or end of file).
    """
    match = SECTION_HEADING_RE.search(text)
    if match is None:
        return None
    start = match.end()
    next_heading = NEXT_HEADING_RE.search(text, start)
    end = next_heading.start() if next_heading else len(text)
    return text[start:end]


def check_agent_file(path, skills_dir):
    """Return a list of violation strings for a single agents/<name>.md file."""
    violations = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")

    section = find_section(text)
    if section is None:
        violations.append(
            f"{path.name}: no \"## Methodology Dependencies\" section found"
        )
        return violations

    if CANONICAL_WORDING not in section:
        violations.append(
            f"{path.name}: Methodology Dependencies header is missing the "
            f"canonical \"{CANONICAL_WORDING}\" wording"
        )

    for match in PLUGIN_ROOT_PATH_RE.finditer(section):
        rel_path = match.group(1)
        resolved = skills_dir / rel_path.lstrip("/")
        if not resolved.is_file():
            violations.append(
                f"{path.name}: {{PLUGIN_ROOT}}{rel_path} does not resolve to "
                f"an existing file ({resolved})"
            )

    return violations


def check_all(skills_dir):
    """Return a list of violation strings across every agents/*.md file.

    Raises GateError (usage-class, exit 2) when the sibling agents/
    directory is missing or contains no *.md files at all -- an empty
    input must never read as a vacuous PASS.
    """
    agents_dir = skills_dir.parent / "agents"
    if not agents_dir.is_dir():
        raise GateError(f"agents directory does not exist: {agents_dir}")

    agent_paths = sorted(agents_dir.glob("*.md"))
    if not agent_paths:
        raise GateError(f"agents directory is empty (no *.md files found): {agents_dir}")

    violations = []
    for path in agent_paths:
        if path.name in EXCLUDED_AGENTS:
            continue
        violations.extend(check_agent_file(path, skills_dir))
    return violations


def main(argv):
    if len(argv) == 1 and argv[0] == "--self-test":
        return run_self_test()

    if len(argv) != 1:
        print("usage: check_dependency_tables.py <skills_dir>", file=sys.stderr)
        return 2

    skills_dir = Path(argv[0])
    if not skills_dir.is_dir():
        print(f"error: {skills_dir} is not a directory", file=sys.stderr)
        return 2

    try:
        violations = check_all(skills_dir)
    except GateError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not violations:
        print("PASS: all Methodology Dependencies tables are valid")
        return 0

    print(f"FAIL: {len(violations)} violation(s)")
    for violation in violations:
        print(f"  - {violation}")
    return 1


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------


VALID_SECTION = (
    "\n\nREAD these as file paths under {PLUGIN_ROOT} "
    "(NOT Skill-tool invocables). Read every \"Always\" file BEFORE "
    "starting.\n\n"
    "| Skill | When |\n"
    "|---|---|\n"
    "| `{PLUGIN_ROOT}/agent-squad/base-persona.md` | Always |\n"
)


def run_self_test():
    import shutil

    class DependencyTableTests(unittest.TestCase):
        def setUp(self):
            self.root = Path(tempfile.mkdtemp())
            self.skills_dir = self.root / "skills"
            self.agents_dir = self.root / "agents"
            self.skills_dir.mkdir()
            self.agents_dir.mkdir()
            (self.skills_dir / "agent-squad").mkdir()
            (self.skills_dir / "agent-squad" / "base-persona.md").write_text(
                "base persona", encoding="utf-8"
            )

        def tearDown(self):
            shutil.rmtree(self.root, ignore_errors=True)

        def _write_agent(self, name, body):
            (self.agents_dir / name).write_text(body, encoding="utf-8")

        def test_missing_agents_dir_raises_gate_error(self):
            shutil.rmtree(self.agents_dir)
            with self.assertRaises(GateError):
                check_all(self.skills_dir)

        def test_empty_agents_dir_raises_gate_error(self):
            with self.assertRaises(GateError):
                check_all(self.skills_dir)

        def test_agent_with_no_dependency_section_is_a_violation(self):
            self._write_agent("rex.md", "# Rex\n\nNo dependency section here.\n")
            violations = check_all(self.skills_dir)
            self.assertEqual(len(violations), 1)
            self.assertIn("no \"## Methodology Dependencies\" section found", violations[0])

        def test_blackgoat_with_no_dependency_section_is_exempt(self):
            self._write_agent("blackgoat.md", "# Blackgoat\n\nNo dependency section here.\n")
            violations = check_all(self.skills_dir)
            self.assertEqual(violations, [])

        def test_backtick_wrapped_path_resolves(self):
            self._write_agent(
                "rex.md",
                "# Rex\n\n## Methodology Dependencies\n" + VALID_SECTION,
            )
            violations = check_all(self.skills_dir)
            self.assertEqual(violations, [])

        def test_bare_path_without_backticks_is_matched(self):
            body = (
                "# Rex\n\n## Methodology Dependencies\n\n"
                "READ these as file paths under {PLUGIN_ROOT} "
                "(NOT Skill-tool invocables).\n\n"
                "Always read {PLUGIN_ROOT}/agent-squad/base-persona.md before starting.\n"
            )
            self._write_agent("rex.md", body)
            violations = check_all(self.skills_dir)
            self.assertEqual(violations, [])

        def test_bare_path_without_backticks_that_is_missing_is_a_violation(self):
            body = (
                "# Rex\n\n## Methodology Dependencies\n\n"
                "READ these as file paths under {PLUGIN_ROOT} "
                "(NOT Skill-tool invocables).\n\n"
                "Always read {PLUGIN_ROOT}/agent-squad/does-not-exist.md before starting.\n"
            )
            self._write_agent("rex.md", body)
            violations = check_all(self.skills_dir)
            self.assertEqual(len(violations), 1)
            self.assertIn("does-not-exist.md", violations[0])

        def test_missing_canonical_wording_is_a_violation(self):
            body = (
                "# Rex\n\n## Methodology Dependencies\n\n"
                "Read `{PLUGIN_ROOT}/agent-squad/base-persona.md` before starting.\n"
            )
            self._write_agent("rex.md", body)
            violations = check_all(self.skills_dir)
            self.assertEqual(len(violations), 1)
            self.assertIn(CANONICAL_WORDING, violations[0])

        def test_happy_path(self):
            self._write_agent(
                "rex.md",
                "# Rex\n\n## Methodology Dependencies\n" + VALID_SECTION,
            )
            self._write_agent("blackgoat.md", "# Blackgoat\n\nNothing here.\n")
            violations = check_all(self.skills_dir)
            self.assertEqual(violations, [])

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(DependencyTableTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
