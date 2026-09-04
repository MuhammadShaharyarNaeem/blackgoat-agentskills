# Blackgoat Agent Skills

[![Listed on ClaudePluginHub](https://www.claudepluginhub.com/badge/muhammadshaharyarnaeem-blackgoat-agentskills)](https://www.claudepluginhub.com/plugins/muhammadshaharyarnaeem-blackgoat-agentskills?ref=badge)

A Claude Code plugin that packages an **agent squad** and a **Prompt-Driven Development (PDD)** workflow into reusable skills and personas. An Orchestrator delegates self-contained tasks to specialized subagents, each of which runs in isolation and returns a structured `<handoff>`. Instead of one agent trying to hold an entire project in context, work is split across a squad of narrow specialists coordinated through slash-command SOPs — with requirement traceability enforced from the first honing question to the final pre-launch gate.

- **Plugin:** `blackgoat-agentskills` v2.1.0 — see [CHANGELOG.md](CHANGELOG.md)
- **Author:** shaharyar.naeem (shaharyar.naeem@gorelo.io)

> Note: this repo's `AGENTS.md` is the Google Antigravity runtime contract, not the generic cross-tool "AGENTS.md" coding-agent convention — see [docs/cursor-setup.md](docs/cursor-setup.md).

![blackgoat-agentskills: claude plugin validate passing, the plugin manifest, and the 15-agent squad inventory](assets/preview.svg)

---

## Start Here: You Don't Need the Whole System on Day One

The plugin is designed with a deliberate adoption gradient. Each step gives you value on its own; none requires the previous one.

**Step 0 — Use it every day, not only for epics.** Type `/bg` in front of an ordinary ask and the plugin picks the lane; for a rename, an added test or a one-file tidy that is `/bgpdd-quick`, which stays in the main session and ends with one gate and one commit. A session-start hook injects a one-screen index of the lanes and the four rules that hold outside any lane (evidence over claims, never edit a test to pass, commits go through a gate, ask before anything irreversible), so an ordinary chat already follows them. The worker methodologies — TDD, debugging, code review, simplification, source-driven development — are directly invocable on named files too.

**Step 1 — Fix one bug with `/bgpdd-bugfix`.** One command, one bug, the smallest squad that can prove it. It walks six gated phases on written evidence: you write a lint-gated bug report with the Orchestrator, Quinn captures the failing run (RED) before anyone touches code, you trace the root cause in the main session and a script routes the fix FAST, FULL or PLAN, Mason (or Nova for UI-side bugs, both for a shared-contract bug) lands the surgical fix without touching the RED, Quinn re-runs the identical command for GREEN plus the full suite, a fresh Luna reviews the diff and its blast radius, and the commit exists only if the commit gate passes with the RED/GREEN pair, a five-file size bound and the review on record. If you currently debug with ad-hoc prompts, this is the smallest possible taste of the disciplined, gated workflow — now with the smallest squad that can carry it.

**Step 2 — Delegate one task to one agent.** Every squad member can be invoked ad hoc, at any project state: "have Luna review this diff", "have Cipher audit the auth routes", "have Quinn write tests for this module". The agent runs in isolation, does exactly its job, and returns a handoff. No pipeline required.

**Step 3 — Run `/bgpdd-lite` for well-specified work.** The mid-weight lane: no honing Q&A, no Aria — you write mini-requirements with the Orchestrator (Rex's template, stable FR/NFR IDs), Alex plans, the coverage gate checks traceability, and the state file hands off to `/bgpdd-build`. A five-question fit check up front routes anything contested or cross-boundary to the full pipeline instead.

**Step 4 — Run the full PDD pipeline** when a feature is big enough to warrant discovery, planning, staged building, and a gated launch. That's the rest of this README.

### What to Run When

| Situation | Command | Runs where |
|---|---|---|
| Not sure which lane, or just an everyday ask | `/bg <what you want>` | Main session — classifies and invokes exactly one lane |
| One small contained change (≤ 3 files: rename, add a test, tidy, config) | `/bgpdd-quick` | Main session only — no agents; one captured check, one closing gate that commits |
| New feature, brownfield codebase | `/bgpdd-discovery` then `/bgpdd-plan` | Spawns agents (Iris/Scout/Echo, then Rex/Aria/Alex) |
| Well-specified small feature (known pattern/contract) | `/bgpdd-lite` | Main session (mini-requirements) + spawns Alex |
| Execute an existing plan | `/bgpdd-build [auto]` | Spawns agents (Mason/Nova, Quinn, Luna, Dep, Cipher) |
| Ship a green epic | `/bgpdd-shipping` | Spawns agents (Vera, Cipher, Dep, Forge) |
| Fix a bug | `/bgpdd-bugfix` | Main session (intake, RCA, route) + spawns agents (Quinn RED, Mason/Nova fix, Quinn GREEN, Luna) |
| Verify an already-discovered feature still works | `/bgpdd-verify {feature}` | Main session (matrix) + spawns Quinn |
| Capture lessons from a session | `/bgpdd-learn` | Main session + spawns Forge |
| Audit the plugin itself | `agent-audit` skill | Main session |
| Ad-hoc delegation to one specialist | `agent-squad` (e.g. "have Luna review this diff") | Spawns the named agent |

---

## Installation

Prerequisite: [Claude Code](https://docs.claude.com/en/docs/claude-code) installed.

**Option 1 — Claude Code marketplace (native).**

```
/plugin marketplace add MuhammadShaharyarNaeem/blackgoat-agentskills
/plugin install blackgoat-agentskills@blackgoat
```

**Option 2 — claudepluginhub.**

```bash
npx claudepluginhub muhammadshaharyarnaeem/blackgoat-agentskills
```

**Option 3 — Manual clone.**

```bash
git clone https://github.com/MuhammadShaharyarNaeem/blackgoat-agentskills ~/.claude/skills/blackgoat-agentskills
```

---

## Core Concepts

Five ideas underpin everything else in the plugin.

**1. Orchestrator-only delegation.** The Orchestrator (the `agent-squad` model, fronted by the Blackgoat persona) is the single point of contact with the user. It never builds, reviews, or tests anything itself — it understands what the user wants, delegates to the right specialist, reads the returned `<handoff>`, and relays a compressed summary back. This prevents "context collapse": one context window trying to hold requirements, design, code, tests, and review simultaneously.

**2. Subagent isolation.** A delegated agent runs to completion in its own bounded context. It **cannot pause to ask the user mid-task**, and it **cannot spawn further subagents**. Its `<handoff>` arrives as its final message, and there is no "kill" step. Consequence: any genuinely interactive step (like turn-by-turn requirements honing) must run in the main session, and all routing, re-delegation, and error recovery belong to the Orchestrator alone.

**3. Background delegation.** Agents are always launched in the **background**, never as a blocking call, and independent delegations go out in a single message so they run concurrently. A blocking delegation makes the Orchestrator unreachable for the agent's whole run — you cannot ask a question, correct a bad brief, or stop work heading the wrong way, and a long phase is indistinguishable from a hang. The Orchestrator is notified on completion, so sequential phase ordering still holds. Paired with this: **incremental persistence** — every agent writes its artifact section by section (and commits code as it goes) rather than saving once at the end, so an interruption costs one unfinished section instead of the entire run.

**4. Working-memory chunking.** The Orchestrator never passes full project history to an agent. Each briefing contains only the specific "Working Memory" chunk that agent needs — e.g., the exact text of one milestone from `plan.md`, or one checklist section pasted verbatim. Overloading a subagent's context causes downstream hallucination, so the SOPs forbid it explicitly.

**5. Artifacts by reference.** Agents save full reports to `.docs/` files; the Orchestrator keeps only a compressed summary (status, 2–3 key outputs, blockers) in active context and passes file *paths*, not file *contents*, to the next agent. The `.docs/` tree is the durable record; context windows are cache.

```mermaid
sequenceDiagram
    participant U as User
    participant O as Orchestrator (main session)
    participant A as Delegated agent (isolated context)
    U->>O: Request / "proceed"
    O->>A: Briefing prompt - compressed working memory + artifact paths
    Note over A: Runs to completion alone.<br/>Cannot ask the user.<br/>Cannot spawn subagents.
    A->>A: Reads .docs/ artifacts, does the work, saves its report file
    A-->>O: Final message: handoff (status, artifact path, blockers)
    O->>U: Compressed relay - summary + artifact linked by reference
```

---

## The Two-Tier Memory Model

State lives on disk in two distinct scopes, and the pipelines are strict about who may write where.

**Tier 1 — `.docs/summary/`** is the *global* project knowledge base, produced **only** by `/bgpdd-discovery` and persisted across enhancement cycles. It is indexed by a durable feature id (`{feature}`, e.g. `slide`), so the next time that feature is touched, its map already exists. Every downstream pipeline treats Tier 1 as **read-only**.

**Tier 2 — `.docs/{project-name}/`** is the *per-enhancement* workspace (e.g. `slide-enhancement`), owned by plan/build/shipping. It holds this cycle's requirements, design, plan, reports, the accumulated `game-tape.md`, and `orchestrator-state.json` — the handoff state that lets a fresh chat session rehydrate mid-pipeline.

```mermaid
flowchart LR
    D["/bgpdd-discovery<br/>(Iris, Scout, Echo)"]
    P["/bgpdd-plan<br/>(Rex, Aria, Alex)"]
    B["/bgpdd-build<br/>(Mason or Nova - routed by the milestone's [API]/[UI] domain tag, Quinn, Luna, Dep)"]
    S["/bgpdd-shipping<br/>(Vera, Cipher, Dep, Forge)"]

    subgraph T1["Tier 1: .docs/summary/ - global, durable, read-only downstream"]
        C1["context.md - tech stack + Target Scope (Iris)"]
        F2["feature-id/api.md - one map per API (Scout)"]
        F1["feature-id/overview.md - cross-API synthesis (Echo)"]
        F3["feature-id/QA/code-workflow.md + manual-testing.md (Echo)"]
    end

    subgraph T2["Tier 2: .docs/project-name/ - per enhancement"]
        R1["rough-idea.md + honing-transcript.md + requirements.md"]
        R2["design/detailed-design.md + research/"]
        R3["implementation/plan.md, test-report.md, review-report.md, ship-decision.md"]
        R4["implementation/game-tape.md"]
        R5["orchestrator-state.json"]
    end

    D -- writes --> T1
    P -- reads --> T1
    B -- reads --> T1
    P -- writes --> T2
    B -- reads + writes --> T2
    S -- reads + writes --> T2
```

The rule is architectural, not stylistic: discovery agents must never write into a feature directory under Tier 2, and build/shipping must never write artifacts into Tier 1. Conflating the tiers would let one enhancement cycle corrupt the durable map every future cycle depends on.

---

## The Agent Squad

Every agent lives in `agents/<name>.md` with frontmatter declaring its `role`, `phase`, `model`, and `depends-on`, plus a **Methodology Dependencies** table naming exactly which skills it loads and when. Universal invariants (workspace isolation, `<handoff>` format, path resolution) live once in `skills/agent-squad/base-persona.md`; agents that need a different write boundary declare an inline override.

| Agent | Role | Model | Phase(s) |
|-------|------|-------|----------|
| **Blackgoat** | The Liminal Pragmatist — the human author's orchestration persona | main session | Orchestration (all phases) |
| **Iris** | System Architect (Discovery) — lightweight codebase discovery | haiku | Discovery |
| **Scout** | Research Scout — disposable deep-dive into one assigned API/repo | sonnet | Discovery (spawned in parallel, one per API group) |
| **Echo** | Legacy QA Analyst — reverse-engineers existing feature behavior | sonnet | Discovery |
| **Rex** | Requirements Analyst | sonnet | Plan 1 — Requirements |
| **Aria** | System Architect | opus | Plan 2 — Architecture; Build advisor on blast-radius escalations |
| **Alex** | Strategist & Planner | opus | Plan 3 — Planning |
| **Mason** | Builder (Backend) — `[API]` milestones | opus | Build 1 — Implementation |
| **Nova** | Builder (UI) — `[UI]` milestones, builds user-facing interfaces from Aria's contracts and the committed design direction; rendered self-verification | opus | Build 1 — Implementation |
| **Quinn** | QA Tester — build-phase testing | sonnet | Build 2 — Testing |
| **Luna** | Code Reviewer | sonnet | Build 3 — Code Review |
| **Max** | Optimizer / Refactorer | opus | Ad hoc, on request — not a bgpdd-build pipeline stage |
| **Vera** | Launch Verifier — pre-launch checklist verification | sonnet | Shipping — Verification (parallel with Cipher) |
| **Cipher** | Security Auditor | sonnet | Shipping — Security (parallel with Vera); Build [SEC]-milestone reviews |
| **Dep** | DevOps Engineer | sonnet | Build 5 — Deployment Prep + epic gate; Shipping rollout |
| **Forge** | Meta-Engineer / System Coach | opus | End of epic (bgpdd-shipping Step 7); `/bgpdd-learn` on demand — always human-approved |

Blurbs, in one line each: Iris scans repos and records the tech stack and Target Scope. Scout maps one feature's fragments inside one API and writes exactly one file. Echo reverse-engineers how an existing feature behaves today, from the Scouts' maps, before any requirements exist. Rex turns a honing transcript into an ID'd, testable spec. Aria designs the data model, contracts, and file structure (design only — a learned squad rule forbids delegating coding to the Architect). Alex converts the blueprint into a dependency-ordered task plan where every task cites the requirements it covers. Mason writes the code for `[API]` milestones, TDD-first, inside a strict blast radius. Nova builds `[UI]` milestones, translating Aria's contracts and the committed design direction into interfaces verified against the rendered result. Quinn proves the build-phase implementation works against the requirements. Luna reviews for correctness, readability, architecture, security, and performance without rewriting anything. Max refactors for clarity with tests staying green, on ad-hoc request outside the build pipeline. Vera runs the pre-launch verification checklist against the finished codebase. Cipher hardens boundaries. Dep owns containers, CI/CD, rollback plans, and the GO/NO-GO verdict. Forge coaches the squad itself.

---

## The PDD Lifecycle

PDD runs as a chain of four slash-command SOPs. Each SOP is a *manager script*: it names which agents to spawn and in what order, but agents load their own methodology dependencies. **Each phase runs in its own fresh chat session** — the `.docs/` tree and `orchestrator-state.json` carry state across the session boundaries, and every phase transition inside a session waits for your explicit "proceed" (except build's opt-in auto mode).

```mermaid
flowchart TD
    subgraph S1["Session 1: /bgpdd-discovery (brownfield only)"]
        A1["Iris: tech stack + Target Scope"] --> A2["Scouts in parallel: one per API group"]
        A2 --> A3["Orchestrator: synthesis gate"] --> A4["Echo: overview + QA baseline"]
        A4 --> A5["Phase 5: optional /bgpdd-learn offer"]
    end
    subgraph S2["Session 2: /bgpdd-plan"]
        B1["Hybrid honing: main session Q&A, then isolated Rex writes requirements.md"]
        B1 --> B2["Aria: detailed-design.md"] --> B3["Alex: implementation/plan.md"]
        B3 --> B4["Phase 3.5 coverage gate"] --> B5["Game Tape checkpoint + write orchestrator-state.json"]
    end
    subgraph S2L["Alt Session 2: /bgpdd-lite (well-specified work)"]
        L1["Fit Check → mini-requirements (Orchestrator + user)"] --> L2["Alex: implementation/plan.md"] --> L3["Coverage gate + Game Tape + state file"]
    end
    subgraph S3["Session 3: /bgpdd-build (auto optional)"]
        C1["Per-milestone loop: Mason or Nova - routed by the milestone's [API]/[UI] domain tag, Quinn, Luna - commit each green milestone"]
        C1 --> C2["Completion + coverage gates"] --> C3["Dep: ship-decision.md + doubt-driven check"]
        C3 --> C4["Game Tape checkpoint + update state"]
    end
    subgraph S4["Session 4: /bgpdd-shipping"]
        D1["Launch Squad: Vera, then Cipher and Dep in parallel"]
        D1 --> D2["Gates, docs, PR, launch readiness report"] --> D3["Forge: single end-of-epic run"]
    end
    subgraph SV["Standalone: /bgpdd-verify (any time after discovery, repeatable)"]
        V1["Fit check: entry ticket is Echo's QA baseline"] --> V2["Derive + lint acceptance-matrix.md"] --> V3["Quinn: automate as permanent Playwright specs, execute against running app"]
        V3 --> V4["Mechanical gates + verdict"] -.-> V5["Product defects → fresh /bgpdd-bugfix session"]
    end
    S1 -- "Tier 1 knowledge base" --> S2
    S1 -. "Tier 1 knowledge base (optional)" .-> S2L
    S1 -. "Tier 1 knowledge base" .-> SV
    S2 -- "state file + plan" --> S3
    S2L -- "state file + plan" --> S3
    S3 -- "state file + green epic" --> S4
```

Phase by phase:

- **`/bgpdd-discovery` (Phase 0)** — brownfield only. The Orchestrator establishes the Target Scope (repos, branch, local paths) up front, Iris writes `context.md`, you name the APIs holding the feature's fragments (the SOP hard-halts rather than hallucinate a list; a single Scout can run a footprint search if you don't know), Scouts fan out in parallel, and Echo synthesizes the cross-API overview plus a reverse-engineered QA baseline. Phase 5 offers an optional `/bgpdd-learn` run — discovery is global-tier and outside any epic, so no game tape exists to catch its lessons later.
- **`/bgpdd-plan` (Phase 1)** — has a brownfield Pre-Flight Check that halts if the Tier 1 knowledge base is missing. Honing is **hybrid**: the live one-question-at-a-time Q&A runs in the main session (a delegated agent can't pause to ask you things), then an isolated Rex synthesizes `requirements.md` from the transcript. Aria designs, Alex plans, the Phase 3.5 gate checks coverage, and Phase 4 writes the game tape and the state file.
- **`/bgpdd-lite` (Plan, lite)** — agents: Alex (+ Orchestrator mini-requirements). Produces `requirements.md`, `implementation/plan.md`, and `orchestrator-state.json` → hands off to `/bgpdd-build`. No honing, no Aria; the governing stack contract stands in for the blueprint, and the same coverage gate still applies.
- **`/bgpdd-build` (Phase 2)** — the milestone loop, detailed below.
- **`/bgpdd-shipping` (Phase 3)** — the Launch Squad, gates, PR, and the epic's single Forge run, detailed below.
- **`/bgpdd-verify` (standalone, not part of the four-phase chain)** — usable any time after `/bgpdd-discovery` has documented a feature. Derives a lint-gated `acceptance-matrix.md` from Echo's QA baseline, has Quinn automate it as permanent Playwright specs and execute them against the running application, and gates the results through the same mechanical checks the build pipeline uses — without running plan or build. It never fixes what it measures: product defects it finds route to a fresh `/bgpdd-bugfix` session, and its re-verify shortcut makes repeat regression runs cheap.

### The state file

`orchestrator-state.json` has a defined schema so downstream pipelines hydrate deterministically:

```json
{
  "schema": "1",
  "project_name": "slide-enhancement",
  "feature": "slide",
  "pipeline": "bgpdd-plan",
  "branch": null,
  "milestone_cursor": null,
  "artifacts": {
    "requirements": ".docs/{project-name}/requirements.md",
    "design": ".docs/{project-name}/design/detailed-design.md",
    "plan": ".docs/{project-name}/implementation/plan.md"
  },
  "blockers": [],
  "updated": "<ISO-8601 timestamp>"
}
```

`feature` is the durable Tier 1 id (`null` for greenfield). `pipeline` records the last writer. `branch` and `milestone_cursor` are owned by build: the working branch established at hydration, and the next pending milestone. Shipping's Step 0 refuses to run if `pipeline` isn't `"bgpdd-build"` (or `"bgpdd-shipping"` from a prior checkpointed shipping session), if milestones remain open, if build Phase 5's prep `ship-decision.md` is missing or isn't a `GO` (Step 0.4 — relaxed to a shape-only check when resuming a prior shipping session, so a legitimate `NO-GO` refresh can't lock the pipeline out of the stage that resolves it), or if the `blockers` ledger has standing entries (Step 0.5), and its Step 6.6 deletes the file once the lifecycle completes — `game-tape.md` alone survives as the epic's durable record.

---

## Inside bgpdd-build: The Milestone Loop

At hydration, build reads the state file and **establishes a working branch** (asks for your naming convention, defaults to `feature/{project-name}`, never builds on main). Then it loops over milestones from `plan.md`:

```mermaid
flowchart TD
    H["Hydrate state + establish branch feature/project-name"] --> M["Mason or Nova builds next milestone<br/>(routed by the [API]/[UI] domain tag; exact milestone text pasted into the briefing)"]
    M --> BR{"Blast radius beyond<br/>the active microservice?"}
    BR -- "yes" --> AR["Aria advisory + user approval,<br/>then the fresh builder resumes"] --> Q
    BR -- "no" --> Q["Quinn tests<br/>appends to test-report.md"]
    Q --> QP{"Tests pass?"}
    QP -- "fail: rounds 1-3" --> MF["Fresh builder (bugfix mode)<br/>with exact failing-test logs"] --> Q
    QP -- "fail after round 3" --> HALT1["HALT - surface milestone,<br/>fixes tried, failing logs"]
    QP -- "pass" --> L["Luna 5-axis review<br/>scoped to changed_files"]
    L --> LC{"Critical or Important findings?"}
    LC -- "yes" --> LF["Fresh builder resolves,<br/>fixes re-verified"] --> L
    LC -- "no" --> MX{"Suggestion-level findings<br/>or user asks?"}
    MX -- "yes" --> MAX["Max refactors ad hoc (outside the loop), tests stay green"] --> COMMIT
    MX -- "no" --> COMMIT["Orchestrator commits the milestone<br/>on the working branch, citing FR/NFR IDs"]
    COMMIT --> NEXT{"Milestones remaining?"}
    NEXT -- "yes" --> M
    NEXT -- "no" --> G1["Completion gate: all plan.md tasks checked"]
    G1 --> G2["Coverage gate: every Must-Have FR/NFR<br/>has a passing test in test-report.md"]
    G2 --> DEP["Dep: risks, rollback plan,<br/>ship-decision.md GO or NO-GO"]
    DEP --> DDD["Orchestrator runs doubt-driven check on Dep's plan"] --> SHIP["User confirms, then /bgpdd-shipping"]
```

Details worth knowing:

- **Blast radius rule.** Before touching any shared DTO, component, or library, the builder (Mason or Nova) must trace every consumer. If the radius crosses the active microservice boundary, it documents it and returns — the Orchestrator brings in Aria as a temporary advisor, gets your approval on her recommendation, and re-delegates a fresh builder with the ruling.
- **The rejection loop is bounded.** Builder-fix → Quinn-retest is capped at **3 rounds per milestone**. After round 3 the pipeline HALTs and surfaces everything rather than burn a fourth round on the same wall.
- **Every agent carries the circuit breaker.** Each delegation prompt includes verbatim: hit the exact same error 3 times in a row → stop, document, return. No fourth attempt.
- **The Orchestrator commits.** Each green milestone is committed on the working branch with a message citing the milestone and its FR/NFR IDs. (Committing is pipeline state management, not application coding — it doesn't violate the no-coding rule.) A worker that can't finish in one run commits its partial work before returning, so a fresh delegation can continue from disk.
- **Auto mode.** `/bgpdd-build auto` runs Build → Test → Review → Refactor per milestone without "proceed" prompts, but drops out and halts on circuit-breaker trips, and always stops for explicit approval before the epic-level Dep phase.

---

## Requirement Traceability: The Plugin's Spine

Every pipeline gate ultimately checks one chain: *requirement → design → task → test → launch*. IDs are assigned once and cited everywhere, so "done" is machine-checkable instead of vibes.

```mermaid
flowchart LR
    R["Rex: requirements.md<br/>stable FR/NFR IDs +<br/>Given/When/Then criteria"]
    A["Aria: detailed-design.md<br/>explicitly references<br/>the FR IDs it addresses"]
    X["Alex: plan.md<br/>every task carries a<br/>Requirements covered: field"]
    G1["Plan Phase 3.5 gate:<br/>every Must-Have ID maps<br/>to at least one task"]
    Q["Quinn: test-report.md<br/>tests exercising each ID"]
    G2["Build Phase 5 gate:<br/>every Must-Have ID has<br/>a passing test"]
    G3["Shipping Step 3.5 gate:<br/>re-verified before docs,<br/>PR, and launch"]
    R --> A --> X --> G1 --> Q --> G2 --> G3
```

The gates are enforced, not decorative: plan's Upgraded Chain-of-Thought checks *content contracts* (an artifact must satisfy its structural requirements, not merely exist), the Phase 3.5 gate re-delegates Alex on any uncovered Must-Have (bounded to 2 auto-fix rounds, then halt), build refuses to invoke Dep while any Must-Have lacks a passing test, and shipping blocks documentation and the PR on the same check. If a requirement silently disappears between planning and launch, three separate gates are positioned to catch it. All three execute a deterministic script (`skills/pipeline-tools/scripts/check_coverage.py`) that returns a machine-readable uncovered-ID list; if Python is unavailable the pipeline HALTs rather than substituting a manual judgment path.

---

## Shipping & the Launch Squad

`/bgpdd-shipping` is the final deployment gate. It runs a numbered checklist, in order, no skipping:

```mermaid
flowchart TD
    S0["Step 0 - Hydration gates:<br/>state pipeline is bgpdd-build, milestones done,<br/>plan.md all checked, test-report.md exists"]
    S1["Step 1 - Read shipping-and-launch skill;<br/>paste exact checklist text into each briefing"]
    ST1["Stage 1 - Vera alone:<br/>Code Quality, Performance, Accessibility"]
    ST2["Stage 2 - Cipher and Dep in parallel:<br/>Security / Infra, Flags, Rollout, Monitoring,<br/>Baseline Capture + Rollback Rehearsal"]
    S3{"All three handoffs green?"}
    FIX["Route failure to Mason or Nova (by domain tag) via /bgpdd-build<br/>max 2 fix-and-reverify rounds per area"]
    HALT["HALT - surface area, both attempts, evidence"]
    S35["Step 3.5 - Requirements coverage gate"]
    S4["Step 4 - Compile CHANGELOG + README updates"]
    S45["Step 4.5 - Push working branch, open the PR<br/>(summary, FR/NFR coverage, link to ship-decision.md)"]
    S5["Step 5 - Launch Readiness Report + manual deploy commands"]
    S55["Step 5.5 - Post-Deploy Verification:<br/>fresh Dep runs the post-launch checklist<br/>against the deployed environment;<br/>gated by check_agent_report + check_runtime_evidence"]
    S55F{"Post-deploy verdict?"}
    S55R["Live defect - rollback decision from the recorded<br/>Time to Rollback and the threshold table; HALT for the user"]
    S64["Step 6.4 - Refresh the legacy QA baseline"]
    S65["Step 6.5 - Final Game Tape checkpoint"]
    S66["Step 6.6 - Cleanup: delete orchestrator-state.json<br/>(game-tape.md and gates.jsonl survive)"]
    S7G{"Game tape carries a build or plan section?"}
    S7["Step 7 - Forge: single end-of-epic improvement run"]
    S7SKIP["Skip Forge - say so out loud"]
    S0 --> S1 --> ST1 --> ST2 --> S3
    S3 -- "failure" --> FIX --> S3
    FIX -- "still failing after 2 rounds" --> HALT
    S3 -- "green" --> S35 --> S4 --> S45 --> S5 --> S55 --> S55F
    S55F -- "pass, or NOT RUN (no deploy this session)" --> S64
    S55F -- "fail" --> S55R
    S64 --> S65 --> S66 --> S7G
    S7G -- "yes" --> S7
    S7G -- "no" --> S7SKIP
```

Why two stages instead of three parallel agents? Vera runs full builds and test suites that take file, build-output, and port locks; running scanners or infra verification concurrently against the same checkout causes lock collisions and flaky failures (especially on Windows). So Vera runs alone first, then Cipher and Dep launch in a single parallel batch. Dep compiles the Emergency Rollback Plan and his GO/NO-GO verdict into `ship-decision.md` — and before that GO is accepted, he has to have *rehearsed* the rollback (a timed revert-plus-health-check captured with its provenance sidecar) and *captured* the rollout baseline the threshold table's deltas are read against. After the deploy lands, **Step 5.5** sends a fresh Dep to run the post-launch checklist against the deployed environment; a `Fail` there is a live production defect, so the pipeline takes the rollback decision from the recorded time and halts for you rather than opening a fix round. Any red area may be routed back through `/bgpdd-build` for a fix — at most **2 fix-and-reverify rounds per area** before the pipeline halts and hands you the evidence. If the `github-pr-review` skill is available, Step 4.5 also offers an automated multi-repo PR review pass.

---

## The Learning Loop

Earlier designs ran Forge at the end of every phase — which was structurally blind to cross-phase patterns, like a build failure whose real root cause was a planning gap. The current design collects evidence continuously and analyzes it once, when the whole epic is visible.

```mermaid
flowchart TD
    P1["bgpdd-plan Phase 4:<br/>Game Tape checkpoint"] --> GT["implementation/game-tape.md<br/>accumulates: corrections, retries,<br/>circuit-breaker trips, rubber-stamped gates,<br/>session transcript paths"]
    P2["bgpdd-build Phase 6:<br/>Game Tape checkpoint"] --> GT
    P3["bgpdd-shipping Step 6.5:<br/>Game Tape checkpoint"] --> GT
    GT --> FG{"Step 7 entry gate:<br/>tape holds a build or plan section?"}
    FG -- "no" --> FSKIP["Forge skipped - stated out loud"]
    FG -- "yes" --> F["Forge - ONE end-of-epic run (Step 7):<br/>game tape first, then reports, then<br/>filtered transcript greps - never full reads.<br/>Hunts cross-phase patterns."]
    F --> PR["agent-improvements.md proposals"]
    PR --> HA["HALT - explicit human approval required"]
    HA --> AP["Fresh Forge applies approved changes<br/>to SKILL.md / persona files"]
    LN["/bgpdd-learn - mid-epic escape valve:<br/>Forge Learning Triage routes each lesson to<br/>project rules, a persona, or a methodology skill"] -.-> HA
```

Each pipeline ends with a cheap, no-halt Orchestrator step: append at most 10 bullets of evidence to `game-tape.md` while the session's context is still alive. Forge reads that file *first* at epic end, then the durable reports, then — under a hard filtered-read rule — greps targeted slices of session transcripts (user messages, correction phrases, `<handoff>` blocks, error patterns) without ever full-reading one. Nothing he proposes is applied without your explicit approval.

When lessons shouldn't wait for the epic to ship — or when there is no epic at all, as in discovery's Phase 5 offer — **`/bgpdd-learn`** is the on-demand escape valve: same Forge, same approval gate, but the plan comes back inside his handoff and each lesson is triaged to the layer where it belongs.

---

## Skill Catalog

### SOP orchestrators (slash-command pipelines)
- **agent-squad** — the Orchestrator/delegation model itself; also home of `base-persona.md`, the one shared base persona
- **bg** — the front door: classifies an everyday ask with three questions and invokes exactly one lane; never does the work itself
- **bgpdd-quick** — the daily-driver lane: one contained change of ≤ 3 files in the main session, no delegation, a captured check, and `check_quick_close.py` as the only gate (commits the declared files, refuses undeclared tree changes, edited frozen tests, stale captures and size overruns)
- **bgpdd-discovery** — global context discovery (Iris, Scout, Echo)
- **bgpdd-plan** — design & architecture (Rex, Aria, Alex)
- **bgpdd-lite** — mid-weight planning for well-specified work (Orchestrator mini-requirements + Alex; hands off to bgpdd-build)
- **bgpdd-build** — execution (Mason or Nova, routed by the milestone's [API]/[UI] domain tag; Quinn, Luna, Dep)
- **bgpdd-shipping** — verification & Launch Squad (Vera, Cipher, Dep, Forge)
- **bgpdd-bugfix** — evidence-gated bugfix lane: lint-gated intake → Quinn's RED capture → RCA and mechanical FAST/FULL/PLAN route (main session) → fix (Mason and/or Nova) → same-command GREEN + red/green gate → fresh Luna → bounded commit gate → Tier-1 prevent write-back
- **bgpdd-verify** — standalone regression-verification lane for an already-discovered feature: derives a lint-gated acceptance matrix from Echo's QA baseline, Quinn automates and executes it as permanent Playwright specs against the running application, gated on runtime evidence; product defects it finds route to `/bgpdd-bugfix`

### Methodology skills (execution contracts loaded by agents via their dependency tables)
- **blackgoat-idea-honing** — interactive requirements refinement (Rex / main session)
- **blackgoat-research** — codebase/tech research and system design (Aria)
- **planning-and-task-breakdown** — ordered, dependency-aware task lists (Alex)
- **test-driven-development** — RED/GREEN/REFACTOR worker contract (Mason, Nova, Quinn)
- **debugging-and-error-recovery** — root-cause debugging (Mason, Nova, Quinn)
- **source-driven-development** — ground decisions in official docs (Aria, Mason, Nova)
- **code-review-and-quality** — multi-axis review (Luna)
- **code-simplification** — behavior-preserving cleanup (Luna, Max)
- **performance-optimization** — profiling and bottleneck fixes (Luna, Max)
- **security-and-hardening** — vulnerability hardening (Cipher)
- **shipping-and-launch** — pre-launch checklist and rollout (Dep, Launch Squad)
- **playwright-skill** / **browser-testing-with-devtools** — real-browser E2E and DevTools testing (Nova, Quinn)
- **cloud-deploy-patterns** — provider-agnostic deploy baseline + AWS/Azure checklists (Dep, Cipher; conditional)
- **dotnet-backend-patterns** — .NET solution segregation, CQRS/REPR, EF Core rules (conditional, several agents)
- **database-migration-patterns** — expand/contract schema evolution, forward-only migrations, two-step deploy, a reviewed idempotent SQL diff, and an explicit waiver for destructive changes (Mason, Aria, Dep, Luna; conditional on a schema change)
- **vue3-spa-patterns** — Vue 3 Composition API, Pinia, Axios interceptor contract (conditional, several agents)
- **ui-design-patterns** — committed visual direction, typography/spacing/color/motion discipline, anti-generic-AI rules, and Luna's design-critique review axis (Aria, Nova, Luna; conditional on user-facing UI)
- **godot-gdscript-patterns** — Godot 4 GDScript patterns (conditional, several agents)

### Meta skills (operate on the plugin itself)
- **agent-audit** — audits personas/dependencies against 21 structural heuristics, starting with a mechanical preflight (frontmatter parse, dependency paths, runtime registration, self-tests, ledger grep). A whole-plugin audit runs as a **fan-out**: one read-only review agent per lens (pipeline flow, personas, methodology skills, tooling/evals/docs, cross-reference sweep, gate red-team, eval diagnosis), then the Orchestrator synthesizes and independently re-verifies every Blocker before reporting it as CONFIRMED rather than PLAUSIBLE
- **agent-orchestration-improve-agent** — log parsing → procedural-memory generation (Forge's core methodology)
- **bgpdd-learn** — `/bgpdd-learn`, the on-demand session-learning triage (Orchestrator + Forge)

### Standalone tools
- **pipeline-tools** — the deterministic gate CLI family (coverage, commit gate, agent report, runtime evidence, acceptance suite, ship decision — including the `--require-rehearsal` and `--require-baseline` flags that make a rollback rehearsal and a rollout baseline evidenced rather than asserted — milestone-scoped blockers, milestone read/write, state writes, quiet runs, and the two static lints) executed by the Orchestrator at every bgpdd gate; there is no manual open-and-read substitute. Alongside the gates: **`detect_stack.py`** gives "if the project uses X" a mechanical floor by reporting evidence-backed stacks and the skills they imply, and **`record_run.py` / `summarize_run.py`** are the run-telemetry pair — one JSON line per delegation, rolled up into the fired-versus-rubber-stamped block the game tape pastes instead of narrating
- **doubt-driven-development** — adversarial fresh-context verification of decisions (run by the main-session Orchestrator, never by subagents)
- **github-pr-review** — Linear-driven multi-repo PR review via GitHub MCP
- **prompt-engineering** — prompting patterns and optimization guidance

---

## Safety & Error Recovery

The plugin's failure doctrine is *halt and surface* — never guess, never silently bypass, never let a loop run unbounded.

- **Circuit breaker (every delegation).** Each agent's prompt includes verbatim: the exact same error 3 times in a row → stop, document what was tried and the exact error in the `<handoff>`, return immediately. No fourth attempt.
- **Bounded loops, everywhere a loop exists.** Build's builder (Mason or Nova) ↔ Quinn rejection loop: **3 rounds per milestone**. Plan's artifact auto-fix (e.g., Alex re-delegated on a coverage gap): **2 rounds per artifact**. Shipping's fix routing: **2 rounds per failing checklist area**. Hitting a bound always halts with the full evidence — the milestone, the attempts, the exact failing logs — instead of trying again.
- **Global error recovery.** A stuck tool-call loop, a hallucinated file path, or 3 consecutive failed attempts at an objective all trigger the same response: halt, output a structured state summary, request human intervention.
- **No watchdogs needed.** A delegated agent's context is bounded by its own run; it terminates when it returns. Workers that can't finish commit partial work to the working branch and describe the remainder in their handoff, and the Orchestrator re-delegates fresh.
- **Doubt-driven development.** Before high-stakes outputs reach you (e.g., Dep's ship decision at the end of build), the Orchestrator runs a fresh-context adversarial review over the artifact rather than trusting a confident first draft.

---

## MCP Servers

The plugin's `.mcp.json` wires up four MCP servers used by the testing, review, and shipping agents:

- **chrome-devtools-mcp** (`npx chrome-devtools-mcp@latest`) — DOM/console/network/perf inspection in a real browser
- **playwright** (`npx @playwright/mcp@latest`) — scripted end-to-end browser flows
- **linear-mcp-server** (`mcp-remote` → `https://mcp.linear.app/mcp`) — Linear issues/PR context (hosted, requires auth)
- **github-mcp-server** (`mcp-remote` → GitHub Copilot MCP endpoint) — GitHub operations for PR review; requires `GITHUB_PERSONAL_ACCESS_TOKEN`

---

## Usage Examples

- `/bg <ask>` — when you do not know or care which lane applies; it announces the classification and invokes one lane
- `/bgpdd-quick` — rename, add a test, small refactor, config tweak: three-line note, one captured check, one gate, one commit; escalates itself to bugfix, lite or plan when the change outgrows it
- `/bgpdd-bugfix` — fix a single bug end-to-end on written evidence: a lint-gated bug report, Quinn's pre-fix RED capture, root-cause analysis and a scripted FAST/FULL/PLAN route in the main session, Mason or Nova's fix, Quinn's same-command GREEN, a fresh Luna review, and a commit gate that requires the RED/GREEN pair and a five-file bound. The smallest squad, not no squad.
- "have Luna review this diff" — delegate one task to one specialist ad hoc; Luna runs in isolation and returns a `<handoff>` with her findings.
- "have Quinn write tests for this module" — same ad-hoc delegation pattern, aimed at test coverage instead of review.
- `/bgpdd-lite` — the mid-weight lane for well-specified work: write mini-requirements with the Orchestrator, Alex plans, the coverage gate checks traceability, then hand off to build.
- `/bgpdd-plan` → `/bgpdd-build` → `/bgpdd-shipping` — the full pipeline for a feature big enough to warrant discovery, honing, architecture, staged building, and a gated launch, each run in its own fresh session.
- `/learn` — after a session with friction or a systemic lesson, route it through Forge's Learning Triage instead of letting it evaporate.

---

## Using the Plugin

1. **Brownfield? Run `/bgpdd-discovery` first** in its own session. Establish the Target Scope (repos, branch, paths), name the APIs when asked (or let a Scout search for the feature's footprint), and let the pipeline build the Tier 1 knowledge base under `.docs/summary/{feature}/`. Take the `/bgpdd-learn` offer at the end if the run had friction. Greenfield projects skip straight to planning.
2. **Run `/bgpdd-plan` in a fresh session.** Answer the honing questions one at a time — this Q&A runs in the main session because delegated agents can't ask you anything. Approve each phase transition; the pipeline ends by writing `game-tape.md` evidence and `orchestrator-state.json`. For well-specified work (a known pattern or contract), run **`/bgpdd-lite`** instead — its Fit Check confirms lite is appropriate, you draft mini-requirements with the Orchestrator, and Alex produces the same gated `plan.md` handoff without honing or architecture phases.
3. **Run `/bgpdd-build` in a fresh session** (add `auto` to skip per-phase confirmations). The pipeline hydrates from the state file, establishes the working branch (default `feature/{project-name}`), loops the milestones, and commits each green one. Expect halts, not heroics, when a bound is hit.
4. **Run `/bgpdd-shipping` in a fresh session.** The Launch Squad verifies, the gates check coverage, Step 4.5 opens the PR, and you get a Launch Readiness Report with the manual deploy commands — production deployment stays in your hands.
5. **Approve Forge's proposals** at Step 7 (or from any `/bgpdd-learn` run) before anything is applied. Review artifacts anytime under `.docs/{project-name}/` (this cycle's work) and `.docs/summary/` (the durable knowledge base).
