# Blackgoat Agent Skills

A Claude Code plugin that packages an **agent squad** and a **Prompt-Driven Development (PDD)** workflow into reusable skills and personas. An Orchestrator delegates self-contained tasks to specialized subagents, each of which runs in isolation and returns a structured `<handoff>`. Instead of one agent trying to hold an entire project in context, work is split across a squad of narrow specialists coordinated through slash-command SOPs. It is aimed at engineers who want a disciplined, multi-agent pipeline for taking an idea from discovery through planning, building, and shipping — with requirement traceability enforced end to end.

- **Plugin:** `blackgoat-agentskills` v1.0.0
- **Author:** shaharyar.naeem (shaharyar.naeem@gorelo.io)

---

## How It Works: Squad + PDD

The **Orchestrator** (the `agent-squad` / Blackgoat persona) is the single point of contact with the user. It never builds, reviews, or tests anything itself — it understands what the user wants, delegates to the right specialist agent, reads that agent's returned `<handoff>`, and relays a compressed summary back. This keeps the Orchestrator's context clean and avoids "context collapse."

Two hard constraints define the model:

- **Subagents run in isolation.** A delegated agent cannot pause to ask the user mid-task, and it cannot spawn further subagents. Any interactive step (e.g. live requirements Q&A) is run by the Orchestrator itself.
- **The Orchestrator owns all routing and state.** Agents report back with a `<handoff>`; they never hand work directly to each other. All phase transitions, re-delegations, and error recovery belong to the Orchestrator.

State lives in a per-project semantic-memory folder, `.docs/{project-name}/` (and a global `.docs/summary/` knowledge base from discovery), so a fresh session can rehydrate at any point.

---

## The Agent Squad

| Agent | Role | PDD Phase(s) |
|-------|------|--------------|
| **Blackgoat** | The Liminal Pragmatist — Orchestrator persona bridging architecture and execution | Orchestration (all phases) |
| **Iris** | Observer — lightweight global codebase discovery and reverse-engineering | Discovery |
| **Scout** | Research Worker — disposable deep-dive into one assigned API/repo | Discovery |
| **Rex** | Analyst — turns user intent into a precise, ID'd requirements spec | Plan (Requirements) |
| **Aria** | Architect — designs the data model, API contracts, and file structure | Plan (Architecture) · Build (advisor) |
| **Alex** | Strategist — converts the blueprint into a dependency-ordered task plan | Plan (Planning) |
| **Mason** | Builder — writes clean, tested code against the plan and blueprint | Build (Implementation) |
| **Luna** | Reviewer — multi-axis correctness/security/reliability review (no rewrites) | Build (Code Review) |
| **Max** | Optimizer — refactors for clarity without changing behavior, tests stay green | Build (Refactoring) |
| **Quinn** | QA Tester — legacy QA discovery (Mode A) and build-phase testing (Mode B) | Discovery · Build · Shipping |
| **Cipher** | Security Auditor — hardens boundaries and audits for vulnerabilities | Shipping |
| **Dep** | DevOps — containerization, CI/CD, environment config, rollback plans | Build · Shipping |
| **Forge** | Meta-Engineer / System Coach — analyzes runs and proposes agent improvements | After every phase (human-approved) |

Every agent's frontmatter declares its `role`, `phase`, `model`, and `depends-on`, plus a **Methodology Dependencies** table naming exactly which skills it loads and when.

---

## The Prompt-Driven Development Workflow

PDD runs as a chain of slash-command SOP skills. Each SOP is a *manager script*: it names which agents to spawn and in what order, but it does **not** itself load methodology files — each agent loads its own dependencies. Run each phase in its own chat session; the `.docs/` folders carry state between them.

| Phase | Slash command | Agents spawned | Produces |
|-------|---------------|----------------|----------|
| **Discovery** | `/bgpdd-discovery` | Iris, Scout, Quinn (Mode A), Forge | Tier-1 knowledge base under `.docs/summary/`: tech-stack context, per-API feature maps, reverse-engineered QA baseline |
| **Plan** | `/bgpdd-plan` | Rex, Aria, Alex, Forge | `requirements.md` (FR/NFR IDs), `design/detailed-design.md`, `implementation/plan.md`, `orchestrator-state.json` |
| **Build** | `/bgpdd-build` (`auto` optional) | Mason, Quinn (Mode B), Luna, Max, Dep, Forge | Working code in `src/`/`tests/`, `test-report.md`, `review-report.md`, `ship-decision.md` |
| **Shipping** | `/bgpdd-shipping` | Quinn, Cipher, Dep (parallel Launch Squad) | Green pre-launch checklist, `implementation/ship-decision.md`, updated CHANGELOG/README, launch readiness report |

For lightweight defects that don't need the full squad, use **`/bg-bugfix`** — a lean 5-phase RCA → TDD → fix → blast-radius → memory sequence.

**Requirement traceability** threads through the whole pipeline: Rex assigns stable `FR`/`NFR` IDs → Alex's tasks cite the IDs they satisfy → Quinn's tests exercise them → coverage gates in `bgpdd-plan` and `bgpdd-build` refuse to advance until every Must-Have FR is covered.

---

## Skill Catalog

### SOP Orchestrators (slash-command pipelines)
- **agent-squad** — the Orchestrator/delegation model itself
- **bgpdd-discovery** — global context discovery (Iris, Scout, Quinn)
- **bgpdd-plan** — design & architecture (Rex, Aria, Alex)
- **bgpdd-build** — execution & deployment (Mason, Quinn, Luna, Max, Dep)
- **bgpdd-shipping** — verification & launch squad (Quinn, Cipher, Dep)
- **bg-bugfix** — lean single-agent bugfix loop (no squad overhead)

### Methodology skills (loaded by agents as dependencies)
- **blackgoat-idea-honing** — interactive requirements refinement (Rex)
- **blackgoat-research** — codebase/tech research and system design (Aria)
- **planning-and-task-breakdown** — ordered, dependency-aware task lists (Alex)
- **test-driven-development** — RED/GREEN/REFACTOR worker contract (Mason, Quinn)
- **debugging-and-error-recovery** — root-cause debugging (Mason, Quinn)
- **source-driven-development** — ground decisions in official docs (Aria, Mason)
- **code-review-and-quality** — multi-axis review (Luna)
- **code-simplification** — behavior-preserving cleanup (Luna, Max)
- **security-and-hardening** — vulnerability hardening (Cipher)
- **shipping-and-launch** — pre-launch checklist and rollout (Dep, Launch Squad)
- **playwright-skill** / **browser-testing-with-devtools** — real-browser E2E and DevTools testing (Quinn)
- **godot-gdscript-patterns** — Godot 4 GDScript patterns (conditional, several agents)

### Meta skills (operate on the plugin itself)
- **agent-audit** — audits personas/dependencies against 14 structural heuristics
- **agent-orchestration-improve-agent** — log-parsing → procedural-memory generation (Forge)
- **skill-creator** — scaffolds new CLI skills to Anthropic best practices

### Standalone tools
- **doubt-driven-development** — adversarial fresh-context verification of decisions
- **spec-driven-development** — write a spec before coding
- **github-pr-review** — Linear-driven multi-repo PR review via GitHub MCP
- **prompt-engineering** — prompting patterns and optimization guidance

---

## Using the Plugin

1. **Start a phase** by invoking its slash command in a fresh session (e.g. `/bgpdd-plan`). The Orchestrator drives the phase, delegating to agents and pausing for your approval at each transition.
2. **Answer honing questions** when the Orchestrator runs interactive steps itself (requirements Q&A cannot be delegated).
3. **Review artifacts** under `.docs/{project-name}/` (per-enhancement work) and `.docs/summary/` (global knowledge base) — these are the durable record and the handoff medium between phases.
4. **Approve agent-improvement proposals** from Forge before they are applied.
5. **Move to the next phase** in a new chat once the current one reports complete; state rehydrates from `orchestrator-state.json` and the `.docs/` tree.

### MCP servers

The plugin's `.mcp.json` wires up four MCP servers used by the testing, review, and shipping agents:

- **chrome-devtools-mcp** — DOM/console/network/perf inspection in a real browser
- **playwright** — scripted end-to-end browser flows
- **linear-mcp-server** — Linear issues/PR context (hosted, requires auth)
- **github-mcp-server** — GitHub operations for PR review (requires `GITHUB_PERSONAL_ACCESS_TOKEN`)
