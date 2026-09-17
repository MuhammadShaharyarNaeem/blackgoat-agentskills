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
  (d) every table row carrying such a path has a non-empty last ("When")
      cell. An empty cell is ambiguous between "Always" and "never
      loaded" -- a reader resolves it either way, and a split that moves
      the file leaves a silently unloaded skill behind.

Fails closed: a missing or empty agents/ directory is a usage error (exit
2), not a vacuous PASS, and an agent with no dependency section at all is a
violation (exit 1) rather than something silently skipped.

Usage:
    python check_dependency_tables.py <skills_dir>
    python check_dependency_tables.py --self-test
    python check_dependency_tables.py --help

<skills_dir> is the plugin's skills/ directory (i.e. {PLUGIN_ROOT}).
agents/ is located as the sibling directory of <skills_dir>.

Pure standard library. See ../SKILL.md for usage notes.
"""
import argparse
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
EMPTY_WHEN_FIX = ("write `Always`, or the condition under which this file is "
                  "read")


class GateError(Exception):
    """Structural/usage failure — maps to exit 2."""


def find_section(text):
    """Return (body, first_line_no) for "## Methodology Dependencies".

    Returns (None, None) when the section is absent. The body runs from
    just after the heading to the next "## " heading (or end of file);
    first_line_no is the 1-based file line the body's first character
    sits on (the heading's own line), so row line numbers can be reported.
    """
    match = SECTION_HEADING_RE.search(text)
    if match is None:
        return None, None
    start = match.end()
    next_heading = NEXT_HEADING_RE.search(text, start)
    end = next_heading.start() if next_heading else len(text)
    return text[start:end], text.count("\n", 0, start) + 1


def check_when_cells(path, section, first_line_no):
    """Return violations for dependency rows with an empty "When" cell.

    Only markdown table rows are considered -- a line starting with "|"
    that carries a {PLUGIN_ROOT} path. Prose in the section that mentions
    a path is not a row and is not checked. The "When" cell is the row's
    last cell; a row with no cell after the path has no "When" cell at
    all, which is the same violation.
    """
    violations = []
    for offset, line in enumerate(section.split("\n")):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        match = PLUGIN_ROOT_PATH_RE.search(stripped)
        if match is None:
            continue
        # A row is delimited by a leading and (usually) a trailing pipe.
        # Drop only those two, never a run of them -- `strip("|")` would
        # eat the trailing empty cell this check exists to catch.
        parts = stripped.split("|")[1:]
        if stripped.endswith("|"):
            parts = parts[:-1]
        cells = [cell.strip() for cell in parts]
        when = cells[-1] if len(cells) >= 2 else ""
        if when:
            continue
        violations.append(
            f"{path.name}:{first_line_no + offset}: "
            f"{{PLUGIN_ROOT}}{match.group(1)} has an empty \"When\" cell -- "
            f"ambiguous between \"Always\" and \"never loaded\"; "
            f"fix: {EMPTY_WHEN_FIX}"
        )
    return violations


def check_agent_file(path, skills_dir):
    """Return a list of violation strings for a single agents/<name>.md file."""
    violations = []
    text = path.read_text(encoding="utf-8-sig", errors="replace")

    section, first_line_no = find_section(text)
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

    violations.extend(check_when_cells(path, section, first_line_no))

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


PURPOSE = ("Validates every agent's Methodology Dependencies table: guard "
           "wording, resolvable {PLUGIN_ROOT} paths, non-empty When cells.")

EPILOG = """\
Reads:
  <skills_dir>/../agents/*.md -- each persona's "## Methodology Dependencies"
    section, which must contain the guard wording "NOT Skill-tool invocables".
    Inside it, every `{PLUGIN_ROOT}<rel/path>` token (backticks optional) must
    resolve to a file under <skills_dir>. On a markdown table row, the LAST
    cell is the "When" cell and must be non-empty:
      | `{PLUGIN_ROOT}/<skill>/SKILL.md` | <what> | <When> |
    Prose mentions of a path carry no When cell and are path-checked only.
    agents/blackgoat.md is excluded (CLAUDE.md convention #7).

Exit codes:
  0  every dependency table valid.
  1  at least one violation, reported one per line on stdout: a dangling
     {PLUGIN_ROOT} path, a missing guard sentence, an empty "When" cell, or
     an agent with no Methodology Dependencies section at all.
  2  usage error, or a missing/empty agents/ directory (fails closed rather
     than reporting a vacuous pass).

Self-test:
  python check_dependency_tables.py --self-test   (20 cases)
"""


def build_parser():
    """Real argparse, so `-h`/`--help` works like every sibling script.

    Before 2.6.1 this was the one script in the family with a hand-rolled
    argv walk: `--help` was treated as the positional and died with
    "error: --help is not a directory". Behaviour and exit codes are
    unchanged -- only the parsing and the help text are new.
    """
    parser = PurposeFirstParser(
        prog="check_dependency_tables.py",
        description=PURPOSE,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "skills_dir", nargs="?",
        help="the plugin's skills/ directory (i.e. {PLUGIN_ROOT}); agents/ is "
             "located as its sibling directory")
    parser.add_argument("--self-test", action="store_true",
                        help="run the built-in test suite and exit")
    return parser


def main(argv):
    parser = build_parser()
    # argparse exits 2 on an unknown flag -- already this script's usage code.
    args = parser.parse_args(argv)

    if args.self_test:
        return run_self_test()

    if args.skills_dir is None:
        parser.print_usage(sys.stderr)
        print("error: skills_dir is required (or pass --self-test)",
              file=sys.stderr)
        return 2

    skills_dir = Path(args.skills_dir)
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

        def _agent_with_when(self, when):
            """Write rex.md with one dependency row whose When cell is `when`."""
            body = (
                "# Rex\n\n## Methodology Dependencies\n\n"
                "READ these as file paths under {PLUGIN_ROOT} "
                "(NOT Skill-tool invocables).\n\n"
                "| Skill | Path | When |\n"
                "|---|---|---|\n"
                "| base-persona | `{PLUGIN_ROOT}/agent-squad/base-persona.md` "
                f"|{when}|\n"
            )
            self._write_agent("rex.md", body)

        def test_empty_when_cell_is_a_violation(self):
            self._agent_with_when("")
            violations = check_all(self.skills_dir)
            self.assertEqual(len(violations), 1)
            # Names the agent file, the row's line, the path, and the fix.
            self.assertIn("rex.md:9:", violations[0])
            self.assertIn("{PLUGIN_ROOT}/agent-squad/base-persona.md", violations[0])
            self.assertIn(EMPTY_WHEN_FIX, violations[0])

        def test_empty_when_cell_exits_1(self):
            import contextlib
            import io
            self._agent_with_when("")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main([str(self.skills_dir)]), 1)
            self.assertIn("empty \"When\" cell", out.getvalue())

        def test_whitespace_only_when_cell_is_a_violation(self):
            self._agent_with_when("   ")
            violations = check_all(self.skills_dir)
            self.assertEqual(len(violations), 1)
            self.assertIn("empty \"When\" cell", violations[0])

        def test_always_when_cell_passes(self):
            self._agent_with_when(" Always ")
            self.assertEqual(check_all(self.skills_dir), [])

        def test_condition_when_cell_passes(self):
            self._agent_with_when(" When the diff contains a migration ")
            self.assertEqual(check_all(self.skills_dir), [])

        def test_prose_path_in_section_is_not_a_row(self):
            """A non-table line carrying a path has no When cell to check."""
            body = (
                "# Rex\n\n## Methodology Dependencies\n\n"
                "READ these as file paths under {PLUGIN_ROOT} "
                "(NOT Skill-tool invocables).\n\n"
                "Always read {PLUGIN_ROOT}/agent-squad/base-persona.md first.\n"
            )
            self._write_agent("rex.md", body)
            self.assertEqual(check_all(self.skills_dir), [])

        def test_happy_path(self):
            self._write_agent(
                "rex.md",
                "# Rex\n\n## Methodology Dependencies\n" + VALID_SECTION,
            )
            self._write_agent("blackgoat.md", "# Blackgoat\n\nNothing here.\n")
            violations = check_all(self.skills_dir)
            self.assertEqual(violations, [])

    class CliTests(unittest.TestCase):
        """The CLI surface itself: `--help` works, exit codes unchanged."""

        def test_help_exits_zero_and_prints_usage(self):
            import contextlib
            import io
            out = io.StringIO()
            with self.assertRaises(SystemExit) as ctx, \
                    contextlib.redirect_stdout(out):
                main(["--help"])
            self.assertEqual(ctx.exception.code, 0)
            text = out.getvalue()
            self.assertIn("check_dependency_tables.py", text)
            self.assertIn("skills_dir", text)
            self.assertIn("--self-test", text)

        def test_short_help_flag_also_works(self):
            import contextlib
            import io
            out = io.StringIO()
            with self.assertRaises(SystemExit) as ctx, \
                    contextlib.redirect_stdout(out):
                main(["-h"])
            self.assertEqual(ctx.exception.code, 0)
            self.assertIn("usage:", out.getvalue())

        def test_no_argument_is_exit_2(self):
            import contextlib
            import io
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(main([]), 2)
            self.assertIn("skills_dir is required", err.getvalue())

        def test_nonexistent_directory_is_exit_2(self):
            import contextlib
            import io
            root = Path(tempfile.mkdtemp())
            err = io.StringIO()
            try:
                with contextlib.redirect_stderr(err):
                    self.assertEqual(main([str(root / "nope")]), 2)
                self.assertIn("is not a directory", err.getvalue())
            finally:
                shutil.rmtree(root, ignore_errors=True)

        def test_unknown_flag_is_exit_2(self):
            import contextlib
            import io
            err = io.StringIO()
            with self.assertRaises(SystemExit) as ctx, \
                    contextlib.redirect_stderr(err):
                main(["--no-such-flag"])
            self.assertEqual(ctx.exception.code, 2)

    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite([
        loader.loadTestsFromTestCase(DependencyTableTests),
        loader.loadTestsFromTestCase(CliTests),
    ])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
