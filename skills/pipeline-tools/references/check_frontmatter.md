# check_frontmatter.py — reference

Depth for the `check_frontmatter.py` section of `../SKILL.md`.

## The observed failure

A hand-rolled YAML frontmatter block is easy to break silently: an unquoted scalar value that happens to contain `": "` reads as a nested mapping to a real YAML parser, and the ENTIRE frontmatter block fails to parse — so the runtime sees neither the agent's persona nor the skill's trigger. This has already happened three times in this repo (`agents/scout.md`'s `phase:` line, `skills/doubt-driven-development/SKILL.md`'s `description:`, `skills/bgpdd-verify/SKILL.md`'s `description:`) and went unnoticed because nothing checked frontmatter validity on its own — only downstream symptoms surfaced (a skill that never triggers, an agent with no description), long after the cause. Two of the three predate the distillation wave by months.

## What it does not flag, on purpose

A plain scalar containing ` #` (space-hash) is valid YAML — it parses as an inline comment, silently truncating the value — so it is deliberately NOT flagged. `agents/alex.md`'s `depends-on: rex, aria # ...` line relies on exactly this and must keep parsing clean. Flagging it would convert a working idiom into noise, and the check that matters (does a real parser accept the block) already passes.

The description-length check is a **warning**, not an error: an over-long description degrades trigger quality rather than breaking registration, and failing a lint on it would block a commit for a soft problem. CLAUDE.md convention #7 exempts `agents/blackgoat.md` from every content check — it is verified to exist and nothing more.

`python scripts/check_frontmatter.py --self-test` runs 9 in-process cases over synthetic trees: a clean agent and skill, the unquoted-colon break, the same colon quoted and accepted, a missing required key, a bad `model:` value, a `bgpdd-*` skill with and without its `trigger:`, the blackgoat exemption, and a root carrying neither `agents/` nor `skills/`.
