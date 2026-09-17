# check_dependency_tables.py — reference

Depth for the `check_dependency_tables.py` section of `../SKILL.md`.

## What it enforces, and why it fails closed

CLAUDE.md convention #3 says every Methodology-Dependency path must resolve to a real file, and that a dangling reference is a Blocker. This is that rule's mechanical half. It also checks for the canonical "NOT Skill-tool invocables" wording — the guard against a delegated agent invoking a dependency path through the Skill tool instead of reading it as a file, which silently loads a different contract than the table names.

It also checks that every dependency **row** carrying a `{PLUGIN_ROOT}` path has a non-empty `When` cell. A blank cell is not a small omission: it is ambiguous between "Always" and "never loaded", two readers resolve it two ways, and a skill split that moves the file leaves a dependency nobody loads and nobody notices. Only markdown table rows are checked — prose inside the section that mentions a path has no `When` cell to carry, and flagging it would push authors to drop the explanation rather than fill the cell.

**It fails closed.** A missing or empty `agents/` directory is exit **2**, not a vacuous pass: a lint that reports green when it found nothing to check is worse than no lint, because it is quoted as evidence. An agent file with no Methodology Dependencies section at all is a **violation**, not a skip — the absence is the defect the convention exists to prevent.

`{PLUGIN_ROOT}` paths are matched **with or without surrounding backticks**, because both spellings occur across the personas and a backtick-sensitive matcher silently skipped half the table it claimed to be checking.

`agents/blackgoat.md` is excluded by design (repo CLAUDE.md convention #7 — the author's psychological profile, not a persona).

`python scripts/check_dependency_tables.py --self-test` runs 20 in-process cases over synthetic trees: the happy path, a missing and an empty `agents/` directory, an agent with no dependency section, the blackgoat exemption, a backtick-wrapped path resolving, a bare path matched, a bare path that is missing reported as a violation, a missing canonical guard sentence, the `When`-cell cases (empty cell a violation, empty cell exits 1, whitespace-only cell a violation, `Always` and a conditional cell passing, a prose path that is not a row), and the CLI surface (`--help` and `-h` exit 0 with usage, no argument, a nonexistent directory, and an unknown flag each exit 2).
