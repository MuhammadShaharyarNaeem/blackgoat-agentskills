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

## Branch close

Held once here because three lanes closed a branch with three near-identical copies of it. **Interactive, main session, never delegated** (Orchestrator Contract §1 — irreversible steps need the user). A lane that closes a branch cites this section and states only its own deltas: which route it applies on, where the post-merge capture goes, and what survives the close.

- **Read the base branch from the repo**, never guess it: `git symbolic-ref refs/remotes/origin/HEAD`, else the repo's configured default.
- **Offer exactly three, and no fourth**: **merge locally**; **publish the branch and open a pull request through the runtime's tooling**; **keep the branch**. Discarding is not one of the three — it requires the user to type the branch name.
- **After a merge, done is a capture (convention #9)**: `python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture <the lane's post-merge capture path> -- <the project's test command>`. Non-zero exit → report it and stop; the work is not closed.
- **Worktree branch**: offer to remove the worktree after merging.
- **Which lanes have a branch to close.** `bgpdd-bugfix` Phase 5 step 9 (standalone route only) and `bgpdd-lite` Phase 3 step 4 (only when the user stops there) cite this section as written. `bgpdd-shipping` Step 4.5 is the **epic variant** — it pushes the branch and opens the PR rather than offering three, because an epic's branch closes through the release, not through a local choice. `bgpdd-plan`, `bgpdd-verify`, `bgpdd-discovery` and `bgpdd-learn` create no branch and close none; `bgpdd-quick`'s close gate commits on the current branch and offers nothing.

## Game Tape

The obligation is the Orchestrator Contract §4's: evidence checkpoints fire at every state persistence, and the gate ledger — not the tape — is the record of which gates fired, with which flags, against which artifact hashes, so the tape cites `.docs/{project-name}/implementation/gates.jsonl` rather than reproducing it. Neither this file nor a pipeline restates those rules.

The mechanics common to every pipeline that has one:

- **Write it while the session context holding the evidence is still alive.** Append to `.docs/{project-name}/implementation/game-tape.md` — create the file if it does not exist — under a `## <pipeline-name> — [date]` heading.
- **Default cadence: the Contract §4 obligation above — a checkpoint at every state persistence. Cap: at most 10 bullets**, covering user corrections made, agent failures/retries, re-delegation rounds and why, circuit-breaker trips, which gates were genuinely exercised versus rubber-stamped, and this session's id/transcript path if the runtime exposes it (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`).
  - **"Once per run" is that default reduced, not a competing rule.** A lane that persists state exactly once persists it at the end, so its every-state-persistence checkpoint *is* one per run — which is why `bgpdd-plan` Phase 4, `bgpdd-lite` Phase 3 step 1 and `bgpdd-verify` Phase 4 step 3 each write one and correctly declare **no** refinement of this section. A lane that persists state repeatedly checkpoints repeatedly, at the granularity its own refinement names.
- **`bgpdd-build`'s cadence is mechanically enforced, not remembered.** Its milestone-closing writes carry `update_state.py --require-game-tape` and `mark_milestone.py --require-game-tape`, which refuse the write unless that milestone's section exists with 3–6 bullets, a fenced block and a pasted telemetry block (codes `game-tape-missing|no-section|bullet-count|no-pasted-output|no-telemetry`; contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`). Every other pipeline's cadence here is still prose — convention #9 converts a rule when it is observed to be skipped, and build's per-milestone cadence is the one that was.
- A pipeline whose cadence, cap, heading grammar, location or bullet content differs states its own and labels the divergence (convention #8). **Three do**: `bgpdd-build` Phase 6 (once per milestone closed, 3–6 bullets), `bgpdd-bugfix` (once per phase transition, 2–4 bullets, `## bgpdd-bugfix — [phase] — [date]`, under `{bugfix-root}`), and `bgpdd-quick` (one bullet under `## Result` in `{quick-root}/note.md` — no `game-tape.md` at all).
- **Two lanes have no tape, each for its own labelled reason**: `bgpdd-discovery` runs outside any epic, so there is no `.docs/{project-name}/` to append to — it offers an on-demand `/bgpdd-learn` run instead; and `bgpdd-learn` *reads* the accumulated tapes as its evidence and deliberately does not append to them, since the run that analyses the tape must not land inside it.
