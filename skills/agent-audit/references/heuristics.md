# The Audit Heuristics (Deep Dive)

When auditing an agent's persona and methodology files, apply the following metrics systematically. These heuristics are designed to detect logical deadlocks that cause LLM-based agents to hallucinate, crash, or disobey instructions.

## 1. Interface Alignment (Input/Output Collisions)
**Definition**: The output expected by a downstream agent must perfectly match the actual output format produced by the upstream agent.
- **Why it matters**: Agents do not have common sense. If Agent B's skill tells them to extract the "Definition of Done" from a plan, but Agent A (the planner) was updated to output "Acceptance Criteria" instead, Agent B will either fail, hallucinate a Definition of Done, or loop infinitely.
- **Example**: Mason's persona instructed him to read the "Definition of Done" from Alex's plan, but Alex had been updated to drop the DoD format.

## 2. Dependency Conflict Detection
**Definition**: A global/inherited methodology (like `base-persona.md`) must not mandate rules that contradict the agent's core identity or capabilities.
- **Why it matters**: Over-broad global rules often break specialized agents. If a global rule forces an XML `<handoff>` structure, but a builder agent's local persona forces a `<changed_files>` XML structure, the agent will suffer from cognitive dissonance and likely output corrupted XML.
- **Example**: `base-persona.md` instructed *all* agents to save their final output to the `.docs/` folder. This broke Mason, who is an execution agent whose entire job is to write code in `src/`. The fix was forking the dependency into a Planner persona and a Builder persona.

## 3. Role Cohesion (The Bloat Test)
**Definition:** Agents must only know what they need to know to do their job. Global personas should not be bloated with framework-specific syntax or project-specific procedural memories unless they are specialized agents for that exact framework.

**The Abstraction Rule:**
Auditors must NOT blindly delete all Procedural Memories. Instead, use the Abstraction Rule:
- **Elevate**: Universal Engineering Principles (e.g., Separation of Concerns, Data Safety) must be KEPT and ideally elevated into the agent's core Responsibilities.
- **Abstract**: If a rule is highly specific (e.g., Docker specific), attempt to *generalize it* into a language-agnostic software engineering principle (e.g., "Verify environment configurations drop privileges safely") before deciding to move it.
- **Purge/Move**: Irreducible, hyper-specific project bloat that cannot be generalized must be moved to the project's `.agents/AGENTS.md`.

**Red Flag:** The global persona contains specific instructions for React, Docker, or Terraform, even though the agent is meant to be a generalist code reviewer or planner.

**Real-World Example:**
*Luna (Reviewer)* had a procedural memory dictating how to parse Vue.js global state mutations and specific Docker health checks. The auditor applied the Abstraction Rule, abstracting the Docker check into a general "Infrastructure & CI/CD Security" responsibility, and moving the Vue.js specific rule to the project's `.agents/AGENTS.md`.

## 4. Escalation Hallucination & Path Validity
**Definition**: An agent must have a physically possible chain of command to escalate blockers. Furthermore, isolated subagents must not be given instructions to manage workflow state transitions (e.g., "proceed to Phase 2").
- **Why it matters**: Subagents running in isolated workspaces cannot magically invoke other subagents or transition pipeline states. They can only communicate back to their caller.
- **Example 1**: Mason's skill instructed him to "escalate to Aria" if he encountered an architectural blocker. Mason lacked the tools to spawn or message Aria. He must be instructed to escalate back to the Orchestrator.
- **Example 2**: A research methodology tells an isolated subagent to "ask the user for approval before proceeding to planning." The subagent doesn't control the pipeline; the Orchestrator does. This causes severe Role Dissonance.

## 5. Token Efficiency (Formatting Micromanagement)
**Definition**: Agents should not be burdened with overly strict, redundant, or conflicting formatting templates.
- **Why it matters**: Fighting formatting constraints wastes token context and degrades reasoning performance. If a methodology dictates a tagging format, the persona should not try to invent its own hierarchy.
- **Example**: Alex's persona forced him to use `[LOW]/[MED]` tags and a `1.1` hierarchy, while his methodology forced `[SEC]/[EXT]` tags and a `Task N` hierarchy. By stripping the formatting rules out of the persona and deferring entirely to the methodology, Alex's reasoning capabilities improved dramatically.

## 6. DRY (Don't Repeat Yourself) & Contract Reuse
**Definition**: Methodologies (like a code simplification matrix) should be role-agnostic and shared. Do not duplicate a contract just to change the instruction verb (e.g. from "rewrite" to "flag").
- **Why it matters**: Duplicating a methodology creates a maintenance nightmare. If you add a new pattern later, you have to update multiple files. This is how codebases rot.
- **Example**: Instead of creating a `code-simplification-reviewer-contract.md` for Luna and a `code-simplification-builder-contract.md` for Max, keep one role-agnostic methodology. The *Persona* dictates the interaction rule (Luna's persona is told to "audit only", Max's persona is told to "execute the rewrites").

## 7. Orchestrator vs Methodology Collision (Workflow Dissonance)
**Definition**: A Methodology (`HOW` a task is done) must not attempt to orchestrate the swarm, manage multi-agent state transitions, or spawn subagents. That is the exclusive job of the Orchestrator.
- **Why it matters**: If a methodology is written as if the subagent is managing the entire workflow (e.g., "Step 1: Plan, Step 2: Spawn workers, Step 3: Synthesize"), but the Orchestrator is *also* trying to manage those steps from the outside, the subagent will get confused and skip steps.
- **Example**: The `blackgoat-research` methodology told Aria to conduct the research herself, while the `bgpdd-plan` Orchestrator was trying to spawn Scout workers to do it for her. The fix is to split the methodology into discrete "Modes" that the Orchestrator can explicitly trigger (e.g., Mode 1: Plan, Mode 2: Synthesize).

## 8. Context Bloat & File Bloat (The Wake-Up Tax)
**Definition**: A persona must strictly limit how many Methodology Dependencies (each a skill's `SKILL.md`) it forces the agent to read at startup. 
- **Why it matters**: Reading methodologies at runtime guarantees the agent gets the exact text (avoiding Orchestrator hallucination), but it creates "Episodic Memory Bloat". If a persona forces an agent to read 5 massive files before starting, the agent's context window will fill up with generic rules, leaving no room for project-specific reasoning.
- **Example**: A persona should not load `godot-gdscript-patterns/SKILL.md` "Always". It should explicitly state: "When evaluating external libraries or APIs" or "If the project uses Godot Engine". Only the absolute core rules should be loaded unconditionally.

## 9. ID Traceability (The Golden Thread)
**Definition**: Requirements must generate stable, verifiable IDs (`FR-1`, `NFR-1`, …), and those IDs must be explicitly threaded through the entire pipeline — the requirements stage assigns them, planning tasks cite them (`Requirements covered: FR-…`), tests exercise them, and coverage gates check them.
- **Why it matters**: Prose-matching ("the test checks the login feature") is unverifiable. ID traceability enables hard boolean gates: a planning-coverage gate (every Must-Have `FR` maps to a task) and a build-coverage gate (every Must-Have `FR` maps to a passing test). If any link in the chain drops the ID, those gates silently pass on incomplete work.
- **Example** (blackgoat squad): Rex's `requirements.md` assigns the IDs, Alex's `plan.md` tasks cite them, Quinn's tests exercise them, and the bgpdd-plan Phase 3.5 + bgpdd-build Build Coverage gates check them.

## 10. Wake-Up Context Weight (Quantified)
**Definition**: Measure, don't guess. For each audited agent, count the words of its persona file PLUS every "Always"-loaded Methodology Dependency (e.g. via `wc -w`). Flag any agent whose unconditional wake-up load exceeds ~2,500 words, and any methodology `SKILL.md` that is not a lean spine (`## Worker Execution Contract` + `references/` deep-dive per the house convention).
- **Why it matters**: This quantifies Metric 8's qualitative check. A persona can *look* lean while its "Always" dependencies quietly stack thousands of words of generic rules into every wake-up, crowding out the project-specific reasoning the agent was spawned to do. A hard number makes the bloat undeniable and the fix measurable.
- **Example**: Luna's wake-up load was ~3,600 words (persona + base-persona + a 2,360-word code-review methodology full of human-team process advice like "respond within one business day"). Spine-splitting the methodology cut her load by a third without losing any contract rule.

## 11. Frontmatter & Metadata Hygiene
**Definition**: Frontmatter must be internally consistent across the squad: `phase:` labels form one coherent, collision-free sequence; `model:` tiers exist and fit; `description:` matches what the file actually does; `depends-on` names real agents.
- **Why it matters**: Stale or colliding metadata misleads both humans and the Orchestrator. If two agents claim the same phase, or a phase label contradicts where the pipeline actually runs the agent, delegation decisions are made on fiction.
- **Example**: `max.md` declared `phase: 3 — Refactoring`, colliding with Alex's `phase: 3 — Planning`, while the build pipeline actually ran Max in its Phase 4 — three contradictory answers to "when does Max run".

## 12. Trigger Collision
**Definition**: Skill `description:` fields are the triggering surface. Worker methodologies must not carry end-user trigger language that competes with the orchestrator pipelines. Worker methodologies must self-identify as squad-internal execution contracts; user-facing triggers belong to the pipeline skills.
- **Why it matters**: When a worker methodology's description advertises a user-facing trigger, it can hijack the trigger from the pipeline skill and run without any orchestration, gates, or squad — the user gets a bare checklist instead of the hardened SOP.
- **Example**: `shipping-and-launch` (a worker checklist) said "Use when preparing to deploy to production", competing with the `bgpdd-shipping` pipeline for the user's "ship it" — the methodology could hijack the trigger and run without any orchestration, gates, or squad.

## 13. Cross-Pipeline Consistency
**Definition**: Sibling orchestrator SOPs (e.g. the bgpdd-* pipelines) must share the same hardening skeleton: Path Resolution, Global System Constraints (strict delegation, phase-transition confirmation, artifact-verification chain-of-thought), Global Error Recovery + circuit breaker, state hydration/persistence (`orchestrator-state.json`), and a Game Tape evidence checkpoint (per-phase pipelines) feeding the single end-of-epic agent-improvement run (bgpdd-shipping).
- **Why it matters**: A pipeline missing pieces its siblings have is a latent Blocker: agents behave differently depending on which pipeline delegated them. The hardening skeleton is only a guarantee if every pipeline carries it.
- **Example**: `bgpdd-shipping` referenced `{project-name}` and deleted `orchestrator-state.json` yet had no hydration step establishing either, and lacked the error-recovery/circuit-breaker/improvement machinery all three sibling pipelines carried.

## 14. Model Assignment Fit
**Definition**: Each agent's `model:` tier must match its task complexity — lightweight scanners on small/fast tiers, architecture/planning/code-writing/meta-editing agents on top tiers, everything else mid-tier.
- **Why it matters**: A too-small model silently degrades output; a too-large one wastes budget on mechanical work. Neither failure announces itself — the scanner just gets slower and pricier, or the builder just gets subtly worse.
- **Example**: A haiku-tier model fits Iris's lightweight tech-stack scan; opus-tier fits Aria/Alex/Mason/Forge (architecture, planning, code execution, meta-editing). Assigning the scanner an opus tier or the builder a haiku tier would fail this metric.
