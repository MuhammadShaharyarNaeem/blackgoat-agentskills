# check_dependency_tables.py — reference

Depth for the `check_dependency_tables.py` section of `../SKILL.md`.

## What it enforces, and why it fails closed

CLAUDE.md convention #3 says every Methodology-Dependency path must resolve to a real file, and that a dangling reference is a Blocker. This is that rule's mechanical half. It also checks for the canonical "NOT Skill-tool invocables" wording — the guard against a delegated agent invoking a dependency path through the Skill tool instead of reading it as a file, which silently loads a different contract than the table names.

**It fails closed.** A missing or empty `agents/` directory is exit **2**, not a vacuous pass: a lint that reports green when it found nothing to check is worse than no lint, because it is quoted as evidence. An agent file with no Methodology Dependencies section at all is a **violation**, not a skip — the absence is the defect the convention exists to prevent.

`{PLUGIN_ROOT}` paths are matched **with or without surrounding backticks**, because both spellings occur across the personas and a backtick-sensitive matcher silently skipped half the table it claimed to be checking.

`agents/blackgoat.md` is excluded by design (repo CLAUDE.md convention #7 — the author's psychological profile, not a persona).

`python scripts/check_dependency_tables.py --self-test` runs 9 in-process cases over synthetic trees: the happy path, a missing and an empty `agents/` directory, an agent with no dependency section, the blackgoat exemption, a backtick-wrapped path resolving, a bare path matched, a bare path that is missing reported as a violation, and a missing canonical guard sentence.
