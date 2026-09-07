# Authoring a new agent or methodology skill

## Adding a New Agent

1. Create `agents/<name>.md` with frontmatter: `name`, `description`, `model`, `role`, `phase`, `squad: agent-squad`, `reports-to: agent-squad`, `depends-on` (every agent whose output a pipeline routes into this one), `source`, and `date_added`.
2. Add a **Methodology Dependencies** table listing only the skills it truly needs; mark heavy ones on-demand (`When ...`, a condition the Orchestrator can decide at delegation time from the milestone tag or brief), not `Always`. Include `base-persona` as `Always`.
3. If the agent's write boundary or handoff tag differs from the base persona, add an inline **"Base Persona Override"** block — do not fork `base-persona.md` (convention #2). If the tag set differs, add the persona to `check_handoff.py`'s persona table in the same change (convention #9: the validator is the other end of the contract).
4. Wire it into whichever SOP pipeline spawns it (`skills/bgpdd-*/SKILL.md`) and, if relevant, the squad table in `skills/agent-squad/SKILL.md`; the pipeline validates its handoff with `check_handoff.py --since --ledger`.
5. Confirm every dependency path resolves: `python skills/pipeline-tools/scripts/check_dependency_tables.py skills` and `check_frontmatter.py .` both PASS. Measure the wake-up load (persona words plus every `Always` row's `SKILL.md`); over ~2,500 words is an agent-audit Metric 10 finding.

## Adding a New Methodology Skill

1. Create `skills/<name>/SKILL.md` with `name` + `description` frontmatter. The description ends with the squad-internal sentence its siblings carry; if the skill is directly invocable it also carries the fixed "Also directly invocable …" sentence and a `## Direct invocation` section (≤ 60 words, routes anything larger through `/bg`).
2. Put the lean operational spine (`## Worker Execution Contract`: workflow, rules, verification, escalation) at the top. Keep it minimal — the same-shape reference point is `database-migration-patterns` at roughly 1,000 words. Escalation rows end at the Orchestrator ("escalate to the Orchestrator", "return unbuilt as a planning defect"); a worker never routes lanes (convention #6).
3. Put depth (rationale, anti-patterns, examples) in `skills/<name>/references/*.md` and reference it for on-demand loading. **Do not create a `SKILL-CONTRACT.md`** (convention #1).
4. If the skill offers a `/bgpdd-quick` entry, add a `## Quick card` in the shape convention #10 owns.
5. Every machine contract the skill states (a tag grammar, a citation line, a field a script parses) must be documented at both ends — the writer's file and the parser or consumer — in the same change. A gate, a lint, or a lane that consumes the skill ships with it; a rule with no producer and no enforcement is prose nobody is positioned to follow (audit 2026-09-07, Metric 15(c)).
6. Reference the skill from the agent(s) that use it via their Methodology Dependencies table (conditional rows unless the skill is truly universal), list it in the README catalog, and add a contract eval case under `evals/contract/`.
