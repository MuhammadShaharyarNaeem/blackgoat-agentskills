# CLAUDE.md — Working Guidance for Editing This Plugin

This file instructs an AI agent editing the `blackgoat-agentskills` plugin. It reflects the **current** refactored architecture. Follow it exactly; do not reintroduce retired patterns.

## Repo Map

```
blackgoat-agentskills/
├── .claude-plugin/plugin.json   # Plugin manifest (name, version, author)
├── .mcp.json                    # MCP servers: chrome-devtools, playwright, linear, github
├── agents/                      # One .md persona per squad member (WHO)
│   ├── blackgoat.md             #   Orchestrator persona
│   ├── rex, aria, alex, mason, luna, max, quinn, cipher, dep, forge, iris, scout
├── skills/                      # One folder per skill (HOW)
│   ├── agent-squad/
│   │   ├── SKILL.md             #   The Orchestrator/delegation model
│   │   └── base-persona.md      #   THE ONE shared base persona (universal invariants)
│   ├── bgpdd-discovery|lite|plan|build|shipping/SKILL.md   # PDD SOP pipelines
│   ├── bg-bugfix/SKILL.md       #   Lean bugfix SOP
│   ├── <methodology>/SKILL.md   #   One SKILL.md per methodology
│   └── <skill>/references/*.md  #   Progressive-disclosure deep dives
```

## Non-Negotiable Conventions

1. **One `SKILL.md` per methodology. No shadow contracts.** Each methodology is exactly one `SKILL.md`. Its top is a lean operational spine (`## Worker Execution Contract`: workflow, rules, escalation); verbose rationale lives in that skill's `references/` folder and is loaded on demand. **There are NO `SKILL-CONTRACT.md` shadow files** — that pattern was removed. Never recreate it.

2. **Universal invariants live in `base-persona.md`; role deltas go inline.** `skills/agent-squad/base-persona.md` holds the invariants shared by every agent: runtime neutrality, workspace isolation, the `.docs/{project-name}/` semantic-memory model, `<handoff>` reporting, and `{PLUGIN_ROOT}` path resolution. An agent that needs a different write boundary or handoff tag declares a short **"Base Persona Override"** block inline in its own `agents/<name>.md`. Examples that already exist: Builders (Mason, Max) write to `src/`/`tests/` and report `<changed_files>`; DevOps (Dep) and QA (Quinn) are hybrid (`<changed_files>` + `<artifact>`); the Meta agent (Forge) edits `SKILL.md` files and reports `<changed_skills>`. **There are NO `base-persona-builder/devops/meta/qa` variant files.** Never create one — use an inline override.

3. **Every Methodology-Dependency path must resolve to a real file.** In each `agents/<name>.md`, the "Methodology Dependencies" table uses `{PLUGIN_ROOT}` = the `skills/` directory. Before committing any change to a dependency table (or renaming/moving a skill), glob the referenced paths and confirm each exists. A dangling reference is a Blocker.

4. **Personas = WHO, skills = HOW.** A persona file states identity, judgment, and constraints. Procedural step-by-step detail belongs in a skill's `SKILL.md`, not the persona. Do not let "how to do the work" bloat a persona; do not let identity leak into a methodology.

5. **Runtime neutrality.** This plugin is IDE/LLM-neutral. Name **actions** (read, list, search, write, edit, delegate), never specific tool APIs. New content must map to a runtime's equivalent tool, not hardcode one.

6. **Orchestrator owns routing; subagents are isolated.** Subagents cannot pause to ask the user and cannot spawn further subagents. Never write instructions telling a delegated agent to hand off to another agent, schedule a timer, or spawn its own replacement — that is always the Orchestrator's job. Interactive steps run in the main session.

7. **`agents/blackgoat.md` is the human author's psychological profile — NEVER modify it.** It is not a normal agent persona: it documents the author's core personality and working psychology, maintained by the author to track how they work and whether they are learning; the author extracts skills FROM it over time. It is exempt by design from convention #4, from every agent-audit finding (Role Cohesion, DRY, or any other metric), and from Forge's editing privileges. No agent, audit surgery plan, or improvement proposal may edit, slim, refactor, or "fix" this file for any reason. If an audit flags it, record the finding as N/A-by-design and move on. Single exception: the `## Part VIII: Problem & Solution Ledger` section is append-only via the author's nightly learning review — an entry may be appended there ONLY with the author's explicit in-session approval of the exact text; every other section remains untouchable. Only the human author edits `agents/blackgoat.md`.

## Adding a New Agent

1. Create `agents/<name>.md` with frontmatter: `name`, `description`, `model`, `role`, `phase`, `squad: agent-squad`, `reports-to: agent-squad`, and `depends-on` (if any).
2. Add a **Methodology Dependencies** table listing only the skills it truly needs; mark heavy ones on-demand (`When ...`), not `Always`. Include `base-persona` as `Always`.
3. If the agent's write boundary or handoff tag differs from the base persona, add an inline **"Base Persona Override"** block — do not fork `base-persona.md`.
4. Wire it into whichever SOP pipeline spawns it (`skills/bgpdd-*/SKILL.md`) and, if relevant, the squad table in `skills/agent-squad/SKILL.md`.
5. Confirm every dependency path resolves.

## Adding a New Methodology Skill

1. Create `skills/<name>/SKILL.md` with `name` + `description` frontmatter.
2. Put the lean operational spine (`## Worker Execution Contract`: workflow, rules, verification, escalation) at the top. Keep it minimal.
3. Put depth (rationale, anti-patterns, examples) in `skills/<name>/references/*.md` and reference it for on-demand loading. **Do not create a `SKILL-CONTRACT.md`.**
4. Reference the skill from the agent(s) that use it via their Methodology Dependencies table.

## Validating a Change

- Run the **`agent-audit`** skill against any agent/methodology you touched. It enforces the structural invariants via 15 heuristics: interface alignment, dependency conflict, role cohesion, escalation-path validity, token efficiency, DRY/contract reuse, orchestrator-vs-methodology collision, context/file bloat, ID traceability, wake-up context weight, frontmatter/metadata hygiene, trigger collision, cross-pipeline consistency, model-assignment fit, and skill content validity & cross-skill contract coherence. Fill every row of its coverage table; every `FAIL` must flip to `PASS` before you're done.
- Independently confirm all `{PLUGIN_ROOT}` dependency paths resolve to existing files.
- Grep the tree to confirm no `SKILL-CONTRACT.md` and no `base-persona-*` variant files were introduced.
