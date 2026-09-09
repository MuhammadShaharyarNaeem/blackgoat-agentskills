# CLAUDE.md — Working Guidance for Editing This Plugin

This file instructs an AI agent editing the `blackgoat-agentskills` plugin. It reflects the **current** refactored architecture. Follow it exactly; do not reintroduce retired patterns. The tree is what `ls` shows: `agents/*.md` are personas (WHO), `skills/*/SKILL.md` are methodologies and lanes (HOW), `skills/*/references/` hold on-demand depth.

## Non-Negotiable Conventions

1. **One `SKILL.md` per methodology. No shadow contracts.** Each methodology is exactly one `SKILL.md`. Its top is a lean operational spine (`## Worker Execution Contract`: workflow, rules, escalation); verbose rationale lives in that skill's `references/` folder and is loaded on demand. **There are NO `SKILL-CONTRACT.md` shadow files** — that pattern was removed. Never recreate it.

2. **Universal invariants live in `base-persona.md`; role deltas go inline.** `skills/agent-squad/base-persona.md` holds the invariants shared by every agent: runtime neutrality, workspace isolation, the `.docs/{project-name}/` semantic-memory model, `<handoff>` reporting, and `{PLUGIN_ROOT}` path resolution. An agent that needs a different write boundary or handoff tag declares a short **"Base Persona Override"** block inline in its own `agents/<name>.md`. Examples that already exist: Builders (Mason, Max) write to `src/`/`tests/` and report `<changed_files>`; DevOps (Dep) and QA (Quinn) are hybrid (`<changed_files>` + `<artifact>`); the Meta agent (Forge) edits `SKILL.md` files and reports `<changed_skills>`. **There are NO `base-persona-builder/devops/meta/qa` variant files.** Never create one — use an inline override.

3. **Every Methodology-Dependency path must resolve to a real file.** In each `agents/<name>.md`, the "Methodology Dependencies" table uses `{PLUGIN_ROOT}` = the `skills/` directory. Before committing any change to a dependency table (or renaming/moving a skill), glob the referenced paths and confirm each exists. A dangling reference is a Blocker.

4. **Personas = WHO, skills = HOW.** A persona file states identity, judgment, and constraints. Procedural step-by-step detail belongs in a skill's `SKILL.md`, not the persona. Do not let "how to do the work" bloat a persona; do not let identity leak into a methodology.

5. **Runtime neutrality.** This plugin is IDE/LLM-neutral. Name **actions** (read, list, search, write, edit, delegate), never specific tool APIs. New content must map to a runtime's equivalent tool, not hardcode one.

6. **Orchestrator owns routing; subagents are isolated.** Subagents cannot pause to ask the user and cannot spawn further subagents. Never write instructions telling a delegated agent to hand off to another agent, schedule a timer, or spawn its own replacement — that is always the Orchestrator's job. Interactive steps run in the main session.

7. **`agents/blackgoat.md` is the human author's psychological profile — NEVER modify it.** It is not a normal agent persona: it documents the author's core personality and working psychology, maintained by the author to track how they work and whether they are learning; the author extracts skills FROM it over time. It is exempt by design from convention #4, from every agent-audit finding (Role Cohesion, DRY, or any other metric), and from Forge's editing privileges. No agent, audit surgery plan, or improvement proposal may edit, slim, refactor, or "fix" this file for any reason. If an audit flags it, record the finding as N/A-by-design and move on. Single exception: the `## Part VIII: Problem & Solution Ledger` section is append-only via the author's nightly learning review — an entry may be appended there ONLY with the author's explicit in-session approval of the exact text; every other section remains untouchable. Only the human author edits `agents/blackgoat.md`.

8. **A deliberate divergence must name the rule it refines.** This plugin is a layered ruleset (`base-persona.md` → `orchestrator-contract.md` → methodology `SKILL.md` → pipeline). When a rule you write imposes a bound tighter or looser than an inherited or sibling rule's, name the rule you are refining and state that the divergence is deliberate (e.g. "one round here — deliberately tighter than DDD's 3-cycle bound"). An unlabeled divergence is indistinguishable from a contract collision: an auditor reports a false contradiction, and a reader silently picks whichever bound they read first.

9. **A violated prose rule converts to a mechanical gate, not stronger prose.** Rules whose compliance is counting or a launch-time decision may stay prose. A rule that asks the Orchestrator or an agent to restrain itself at the moment it most wants to proceed (committing, approving, marking complete) must be enforced by an artifact that has to be run or opened — a pipeline-tools script, a file read the gate names, a checkable evidence citation. When an audit or game tape shows a prose rule was violated while in force, do not re-word it or bold it: convert it. Existing conversions: `check_coverage.py`, `check_commit_gate.py` (with `--require-rendered-evidence` and `--verify-tree`), `check_agent_report.py` (Cipher/Vera verdicts gated on their durable reports), `next_milestone.py` (stale-cursor detection), `update_state.py` (evidence-gated blocker removal), `check_frontmatter.py` (a frontmatter block that silently fails to register), `mark_milestone.py` (the `[x]` that used to be three typed characters), `summarize_run.py --markdown` (fired-versus-rubber-stamped, previously written from memory), `detect_stack.py` (which stack skills load, previously decided by prose), `check_ship_decision.py --require-rehearsal` / `--require-baseline` (a rollback plan standing in for a rehearsal, and a threshold table of deltas with no recorded baseline).

10. **A `## Quick card` has exactly one shape, and this convention owns it.** A skill that offers a `/bgpdd-quick` entry carries exactly one `## Quick card` section, placed **immediately before `## Worker Execution Contract`** — after the title paragraph and after the `## Direct invocation` section when the skill has one. (Fifteen of the seventeen cards already sit there; a card at the bottom of the file is drift, not a variant.) The card is exactly four parts, in this order:

    1. **The disclaimer-and-scope line**, first, carrying both the ≤ 3-file scope and the derivation guard: `Derived from the contract below for a ≤ 3-file change; no new rules (convention #8 …)`. This line is what keeps a card from becoming the shadow contract convention #1 forbids — the Worker Execution Contract is the contract, and the card is a reading of it.
    2. **Five numbered rules**, each citing **a section in the same file** that actually exists — `(§ Section Name)` or `(*Section Name*)`, one section per rule. A citation to another skill, or to two sections at once, is drift.
    3. **The three-bullet inline mapping, verbatim** and in this order:

       ```
       - Brief → the quick note (What / Where / How verified)
       - Artifact → the capture at `{quick-root}/evidence/check.md`
       - Handoff → the `## Result` bullet in `note.md`
       ```

       `Inline mapping:` means these three bullets and nothing else. It never means lane routing (that belongs in `## Direct invocation`, which addresses the Orchestrator) and never means a tag grammar (that belongs in the spine section that owns the tag).
    4. Nothing else. **≤ 150 words**, or **≤ 100 for a stack skill** (one reachable through `detect_stack.py`'s `skills` map). Measured over the card **body** — everything between the `## Quick card` heading line and the next `##` — by `wc -w`, list markers and em-dashes included. Sixty-odd of those words are the fixed disclaimer and mapping, so the bound is really "five rules, one line each".

    Card drift is an `agent-audit` Metric 18 finding.

## Adding a New Agent or Methodology Skill

Step-by-step authoring procedure: `skills/agent-squad/references/authoring-agents-and-skills.md`. A new skill arrives with a gate script or a lane that consumes it, or it waits.

## Validating a Change

- Run the **`agent-audit`** skill against any agent/methodology you touched — it owns the current heuristic list and its coverage table. It starts with a **mechanical preflight** (`check_frontmatter.py`, `check_dependency_tables.py`, a registration diff against the runtime, every `--self-test`, the ledger grep) before any prose is read. Fill every row of its coverage table; every `FAIL` must flip to `PASS` before you're done.
- Independently confirm all `{PLUGIN_ROOT}` dependency paths resolve to existing files — `python skills/pipeline-tools/scripts/check_dependency_tables.py skills` is the sanctioned way to run this check.
- Grep the tree to confirm no `SKILL-CONTRACT.md` and no `base-persona-{builder,devops,meta,qa}` variant files were introduced (exclude `references/` — `skills/agent-squad/references/base-persona-rationale.md` is a legitimate rationale doc, not a variant).
