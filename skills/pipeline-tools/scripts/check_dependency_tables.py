#!/usr/bin/env python3
"""Validates the Methodology Dependencies tables in agents/*.md.

Verifies, for every agent persona except blackgoat.md (the author's
psychological profile, exempt by design):

  (a) the "## Methodology Dependencies" section contains the canonical
      "NOT Skill-tool invocables" wording, so a delegated agent cannot
      mistake a dependency-table path for a Skill-tool invocation.
  (b) every `{PLUGIN_ROOT}` path in that section's table resolves to an
      existing file, with {PLUGIN_ROOT} resolved to the skills/ dir
      passed on the command line.

Usage:
    python check_dependency_tables.py <skills_dir>

<skills_dir> is the plugin's skills/ directory (i.e. {PLUGIN_ROOT}).
agents/ is located as the sibling directory of <skills_dir>.

Pure standard library. See ../SKILL.md for usage notes.
"""
import sys
import re
from pathlib import Path

CANONICAL_WORDING = "NOT Skill-tool invocables"
EXCLUDED_AGENTS = {"blackgoat.md"}

SECTION_HEADING_RE = re.compile(r"^##\s*Methodology Dependencies\s*$", re.MULTILINE)
NEXT_HEADING_RE = re.compile(r"^##\s+\S", re.MULTILINE)
PLUGIN_ROOT_PATH_RE = re.compile(r"`\{PLUGIN_ROOT\}(/[^`]+)`")


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
        return violations  # no Methodology Dependencies section to validate

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
    """Return a list of violation strings across every agents/*.md file."""
    agents_dir = skills_dir.parent / "agents"
    violations = []
    for path in sorted(agents_dir.glob("*.md")):
        if path.name in EXCLUDED_AGENTS:
            continue
        violations.extend(check_agent_file(path, skills_dir))
    return violations


def main(argv):
    if len(argv) != 1:
        print("usage: check_dependency_tables.py <skills_dir>", file=sys.stderr)
        return 2

    skills_dir = Path(argv[0])
    if not skills_dir.is_dir():
        print(f"error: {skills_dir} is not a directory", file=sys.stderr)
        return 2

    violations = check_all(skills_dir)
    if not violations:
        print("PASS: all Methodology Dependencies tables are valid")
        return 0

    print(f"FAIL: {len(violations)} violation(s)")
    for violation in violations:
        print(f"  - {violation}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
