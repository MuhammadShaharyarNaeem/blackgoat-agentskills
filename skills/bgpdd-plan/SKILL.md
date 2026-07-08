---
name: bgpdd-plan
description: Phase 1 of the Prompt-Driven Development SOP (Design & Architecture). Refines ideas, conducts research, and creates an implementation plan using Rex, Aria, and Alex.
---

# End-to-End Multi-Agent PDD: Planning Phase (bgPDD-Plan)

This Standard Operating Procedure (SOP) coordinates the planning squad (Rex, Aria, Alex) to take a rough idea through requirements gathering, technical research, architecture design, and task breakdown.

---

## Path Resolution

Skill and agent paths in this document use `{PLUGIN_ROOT}` as a placeholder for the plugin's `skills/` directory. When this skill is invoked, its base directory is provided to you; `{PLUGIN_ROOT}` is that `skills/` directory (the agents live at `{PLUGIN_ROOT}/../agents/`). Use `Glob` to confirm a path exists before referencing it.

---

## 1. Global System Constraints

- **Strict Delegation**: You are a MANAGER. For non-interactive phases you MUST NOT roleplay the agent's work yourself — this collapses your context window. Instead, use the **`Agent` (Task) tool** with `subagent_type: blackgoat-agentskills:<name>` (e.g. `blackgoat-agentskills:aria`) to delegate. Pass the agent the specific "Working Memory" chunk it needs in the prompt. The agent runs to completion in its own context and returns its `<handoff>` summary as its final message — that returned text is what you read to continue. You cannot message a running agent; each delegation is a single self-contained task.
  - **EXCEPTION — Phase 1 (Honing)**: Requirements honing is interactive (turn-by-turn Q&A with the user). A delegated agent cannot pause to ask the user and resume, so **you (the main session) run Phase 1 yourself** following Rex's persona as the behavioral spec. See Phase 1 below.
- **Phase Transitions**: Never start a new phase until the user explicitly types 'proceed', 'approved', or similar confirmation.
- **Upgraded Chain-of-Thought**: Before transitioning between phases, you MUST explicitly verify that the required artifact exists.
  - *Format*: "Thinking: Phase X requires Y. Checking `.docs/{project-name}/Y`... File exists and is populated. Proceeding."
- **Strict Progressive Disclosure (Working Memory)**: Never pass the entire project history or the full `.docs/` folder to a delegated agent. Extract and pass ONLY the specific "Working Memory" chunk they need for their current task. Overloading context causes downstream hallucination.
- **File Artifacts**: All artifacts must use standard GitHub markdown and be saved under `.docs/{project-name}/`. This folder is the project's persistent **Semantic Memory**.

## 2. Global Error Recovery

If *any* delegated agent (or you, the Orchestrator) exhibits the following behaviors:
1. Gets stuck in a continuous tool-call loop without making progress.
2. Hallucinates a file path that does not exist.
3. Fails to complete its objective after 3 consecutive attempts.

**ACTION**: You MUST immediately halt execution, output a structured state summary of what went wrong, and request explicit human intervention. Do not attempt to guess or bypass the failure silently. (There is no "kill" step — a delegated agent terminates on its own when it returns; simply stop delegating and escalate.)

**AUTONOMOUS REJECTION**: If an agent reports a blocking flaw in a previous agent's artifact, re-delegate to the previous agent (a fresh `Agent` call) with the rejection notes so it fixes the artifact automatically. Do not halt unless human input is explicitly required.

**CONTEXT CHECKPOINTS**: A delegated agent's context is bounded by its own run — you do not need to timebox it. If *you* (the Orchestrator) sense your own context is getting large across many phases, checkpoint your state to `.docs/{project-name}/orchestrator-state.json` (see Phase 4) so a fresh session can resume. Do NOT instruct delegated agents to schedule timers or spawn their own replacements — that is your responsibility, not theirs.

## 3. Few-Shot Handoff Examples

When communicating with the user during a phase transition checkpoint, adhere to these examples:

**Good Example (Crisp, action-oriented):**
> Phase 3 (Planning) is complete. Alex has saved the detailed task list to `.docs/my-app/implementation/plan.md`.
> **Blockers**: None.
> **Next Step**: Are you ready to proceed to Phase 4 (Agent Improvement)?

---

## 4. Folder Structure (Semantic Memory)
```text
.docs/{project-name}/
├── rough-idea.md          # Initial concept
├── idea-honing.md         # Interactive Q&A transcript (Phase 1)
├── requirements.md        # Finalized specification (Phase 1)
├── summary/               # Brownfield discovery artifacts (Phases 0–0.6, existing systems only)
│   ├── context.md         #   Global tech-stack context (Iris)
│   ├── {api}.md           #   Per-API feature-fragment maps (Scout)
│   └── QA/
│       ├── code-workflow.md    # Mermaid sequence diagrams & execution paths (Scout)
│       └── manual-testing.md   # Reverse-engineered manual test cases (Quinn)
├── research/              # Technical research & findings (Aria)
├── design/                # System designs & Mermaid diagrams (Aria)
│   └── detailed-design.md
└── implementation/        # Checklists (Alex)
    └── plan.md            # Dependency-mapped task list
```

---

## 5. Detailed Pipeline Phases

> **Brownfield vs Greenfield**: Phases 0, 0.5, and 0.6 apply **only when the user is modifying an existing system (Brownfield)**. For a greenfield (new) project, skip directly to Phase 1.

### Phase 0: Project Context Discovery (Iris)
- **Delegated Agent**: `blackgoat-agentskills:iris` (Observer)
- **Trigger**: Brownfield only — execute FIRST if the user is modifying an existing system.
- **Workflow**:
  1. Delegate to Iris via the `Agent` tool.
  2. Instruct Iris to scan the repository and determine the global tech stack and overall project context (e.g., 2D Godot game vs Next.js Web App).
  3. Instruct Iris to output her findings to `.docs/{project-name}/summary/context.md`. If the file already exists, she must explicitly note this in her handoff so you can ask the user whether to update it.
  4. Read Iris's returned handoff before proceeding.

### Phase 0.5: Feature Auto-Scouting (Orchestrator)
- **Delegated Agent**: `blackgoat-agentskills:scout` (Research Worker)
- **Trigger**: Brownfield only — execute after Phase 0.
- **Workflow**:
  1. YOU (the Orchestrator) MUST ask the user if feature documentation already exists for the feature they are updating.
  2. YOU MUST ask the user which specific microservices or APIs contain fragments of the feature that need to be parsed.
  3. **CRITICAL HALT**: Stop generating your response here and await the user's explicit reply. Do NOT hallucinate a list of APIs; do NOT proceed to step 4 without the user's input.
  4. Once the user provides the list of APIs, delegate a Scout **in parallel for each API** — issue multiple `Agent` calls (`subagent_type: blackgoat-agentskills:scout`) in a single message.
  5. Instruct each Scout to deep-dive its assigned API, map the feature fragments, and write findings to `.docs/{project-name}/summary/{api}.md`. Also instruct Scout to generate `.docs/{project-name}/summary/QA/code-workflow.md` with Mermaid sequence diagrams and execution paths.
  6. Read all Scouts' returned handoffs before proceeding to Phase 0.6.

### Phase 0.6: Legacy QA Extraction (Quinn)
- **Delegated Agent**: `blackgoat-agentskills:quinn` (QA Tester)
- **Trigger**: Brownfield only — execute after Phase 0.5. **Skip if `.docs/{project-name}/summary/QA/code-workflow.md` does not exist.**
- **Workflow**:
  1. Delegate to Quinn via the `Agent` tool.
  2. Instruct Quinn to read `summary/QA/code-workflow.md` and any API research notes to reverse-engineer manual test cases.
  3. Instruct Quinn to write her test cases to `.docs/{project-name}/summary/QA/manual-testing.md` following her Legacy QA Discovery guidelines.
  4. Read Quinn's returned handoff before proceeding to Phase 1.

### Phase 1: Honing & Requirements (run by YOU, the main session)
- **Behavioral spec**: `{PLUGIN_ROOT}/../agents/rex.md` (Rex, the Analyst) + `{PLUGIN_ROOT}/blackgoat-idea-honing/SKILL.md`
- **Why not delegated**: honing is an interactive, turn-by-turn conversation with the user. Delegated agents are fire-and-forget and cannot conduct it. **Run this phase yourself**, adopting Rex's persona and method.
- **Workflow**:
  1. Read Rex's persona (`agents/rex.md`) and the `blackgoat-idea-honing` methodology, and adopt them as your behavior for this phase.
  2. If brownfield, read `.docs/{project-name}/summary/` (context, API maps, QA) first to ground your questions in the real system. Save any rough idea the user gave into `.docs/{project-name}/rough-idea.md`.
  3. Conduct the honing Q&A: ask the user **one targeted question at a time**, probing edge cases deeply, appending each question and answer to `.docs/{project-name}/idea-honing.md`. Use `AskUserQuestion` when a question is a clear multiple-choice decision; otherwise ask in plain conversation.
  4. Even if the user provides a complete requirements document upfront, still review it for missing edge cases and drive it through the honing checkpoint — do not skip straight to acceptance.
  5. When the user confirms honing is complete, write the finalized specification to `.docs/{project-name}/requirements.md` using Rex's requirements template.
  6. Request user confirmation to transition to Phase 2.

### Phase 2: Research & Architecture (Aria)
- **Delegated Agent**: `blackgoat-agentskills:aria` (Architect)
- **Workflow**:
  1. Delegate to Aria via the `Agent` tool.
  2. Instruct Aria to read `.docs/{project-name}/requirements.md` and — **if brownfield** — the discovery artifacts under `.docs/{project-name}/summary/` (so the prior Scout research is consumed, not orphaned). Then conduct any additional necessary technical research.
  3. **CRITICAL PATHING**: Instruct Aria that she MUST write the final blueprint exactly to `.docs/{project-name}/design/detailed-design.md`.
  4. Read Aria's returned handoff.
  5. **Iteration Checkpoint**: Present Aria's design to the user and explicitly offer to bounce back to Phase 1 if research uncovered new questions.

### Phase 3: Planning (Alex)
- **Delegated Agent**: `blackgoat-agentskills:alex` (Strategist)
- **Workflow**:
  1. Delegate to Alex via the `Agent` tool. He reads his own methodology dependencies on-demand with `Read`.
  2. Instruct Alex to read both `.docs/{project-name}/requirements.md` and `.docs/{project-name}/design/detailed-design.md`, and convert the blueprint into micro-tasks ordered to satisfy dependencies.
  3. **CRITICAL PATHING**: Instruct Alex that he MUST save the checklist exactly to `.docs/{project-name}/implementation/plan.md` (NOT the root `.docs/{project-name}/` folder), using his planning methodology's format.
  4. Read Alex's returned handoff.

### Phase 4: Agent Improvement (Forge)
- **Delegated Agent**: `blackgoat-agentskills:forge` (System Coach)
- **Workflow**:
  1. Delegate to Forge via the `Agent` tool. He reads his methodology dependencies (agent-orchestration-improve-agent, agent-audit) on-demand with `Read`.
  2. Instruct Forge to analyze the run: Did Phase 1 miss any edge cases? Did Aria struggle with diagrams? Instruct him to write proposed updates to `.docs/{project-name}/implementation/agent-improvements.md`.
  3. Read Forge's returned handoff.
  4. **HALT EXECUTION**. Explicitly ask the User to review and approve `agent-improvements.md`. Do NOT proceed until you have explicit human approval.
  5. Upon approval, re-delegate to Forge (a fresh `Agent` call) instructing him to apply the approved changes to the relevant `SKILL.md`/agent files with his `Edit`/`Write` tools.
  6. **State Persistence**: Before concluding, write your orchestrator state to `.docs/{project-name}/orchestrator-state.json`. The `bgpdd-build` workflow reads this to hydrate itself.
  7. Prompt the user to open a new chat session and trigger `/bgpdd-build` to execute the code.
