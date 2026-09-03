# Pipeline Skeleton (Cross-Cutting)

The boilerplate every `bgpdd-*` pipeline shares, held once. The Orchestrator reads it via each pipeline's MANDATORY FIRST READ block, immediately after `orchestrator-contract.md`.

This file carries **only the common denominator, and nothing the Orchestrator Contract already owns** — where a rule belongs to the contract, this file points there and neither restates nor softens it. A pipeline overrides a section below only where its own text says so and labels the divergence (convention #8).

## Path Resolution

Skill and agent paths use `{PLUGIN_ROOT}` as a placeholder for the plugin's `skills/` directory; the agents live at `{PLUGIN_ROOT}/../agents/`. When a skill is invoked, its base directory is provided to you. List files to confirm a path exists before referencing it.

The resolved `base-persona.md` path and the injection rule that governs it are the Orchestrator Contract §1's (*The resolved `base-persona.md` path*): it lives at `{PLUGIN_ROOT}/agent-squad/base-persona.md`, never under `{PLUGIN_ROOT}/../agents/`. Read the rule there; no pipeline restates it.

## Error Recovery

**The error-recovery skeleton lives in the Orchestrator Contract (§2)** — halt-and-escalate triggers, the circuit breaker you pass to every agent, no-nested-delegation, incremental persistence, context checkpoints, and 2-round bounded autonomous rejection. Read it there; it is not restated here or in any pipeline.

Each pipeline's own error-recovery section therefore carries ONLY its refinements: which artifacts the 2-round bound applies to, and where it checkpoints its own state.

## Upgraded Chain of Thought

Before transitioning between phases (or steps), explicitly verify the required artifact exists.

*Format*: "Thinking: Phase X requires Y. Checking `<the resolved path>`... File exists and is populated. Proceeding."

A pipeline may additionally require a named artifact to satisfy a **content contract** — existence and non-emptiness alone are not sufficient. It states that contract in its own Global System Constraints section and extends the format line to name which check(s) passed. That is an extension of this section, not a divergence from it: this section sets the floor, and a content contract raises it for one artifact, so no convention #8 label is needed. Only a pipeline that *lowers* the floor (skips the existence check for some artifact) diverges, and must label it.

## Game Tape

The obligation is the Orchestrator Contract §4's: evidence checkpoints fire at every state persistence, and the gate ledger — not the tape — is the record of which gates fired, with which flags, against which artifact hashes, so the tape cites `.docs/{project-name}/implementation/gates.jsonl` rather than reproducing it. Neither this file nor a pipeline restates those rules.

The mechanics common to every pipeline that has one:

- **Write it while the session context holding the evidence is still alive.** Append to `.docs/{project-name}/implementation/game-tape.md` — create the file if it does not exist — under a `## <pipeline-name> — [date]` heading.
- **Default cadence and cap: once per run, at most 10 bullets**, covering user corrections made, agent failures/retries, re-delegation rounds and why, circuit-breaker trips, which gates were genuinely exercised versus rubber-stamped, and this session's id/transcript path if the runtime exposes it (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`).
- A pipeline whose cadence, cap, heading grammar or bullet content differs states its own and labels the divergence (convention #8). Two already do: `bgpdd-build` Phase 6 (once per milestone closed, 3–6 bullets) and `bgpdd-bugfix` (once per phase transition, 2–4 bullets).
- `bgpdd-discovery` runs outside any epic, so there is no `.docs/{project-name}/` and no game tape; it offers an on-demand `/bgpdd-learn` run instead.
