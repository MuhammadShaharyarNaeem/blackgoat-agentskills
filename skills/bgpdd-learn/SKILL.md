---
name: bgpdd-learn
description: "Captures lessons from the current session and routes them to the right layer — project rules file, agent persona, or methodology skill — via Forge's Learning Triage. Use after any session with corrections, failures, or repeated friction: trigger with /bgpdd-learn, 'capture lessons', 'what did we learn'. Squad-internal: run by the main-session Orchestrator, never by delegated subagents."
trigger: /bgpdd-learn
---

# Learn — Session Learning Triage

Every working session generates lessons — user corrections, agent failures, friction that repeats — and most of them evaporate when the session ends. This skill captures them on demand and routes each one to the layer where it belongs: the project's rules file, an agent persona, or a methodology skill. The Orchestrator gathers evidence in the main session, then delegates analysis and routing to Forge in Learning Triage mode. Nothing is applied without explicit user approval.

## Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Step 1, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.
>
> Then read `{PLUGIN_ROOT}/agent-squad/pipeline-skeleton.md` — the shared pipeline skeleton (path resolution, error recovery, upgraded chain of thought, game tape). Refinements below override the skeleton only where labelled (convention #8).

**No game tape of its own — a deliberate divergence (convention #8) from the skeleton's Game Tape section.** This skill *reads* the accumulated tapes as Step 1 evidence; it does not append to them. Writing a `## bgpdd-learn` entry would put the run that analyses the tape inside the tape, and every lesson it lands is already recorded by the Step 5 apply diff and the user's approval. The skeleton's other sections apply unchanged.

## Orchestrator Execution Contract

This skill runs in the main session, never inside a delegated subagent.

### Step 1: EVIDENCE (main session)

Scan the live conversation for user corrections, agent failures and retries, circuit-breaker trips, and the skills/agents in play. Then read the durable evidence **in this order — mechanical first, narrative second**:

1. **The run-log summary and the gate ledger.** `python {PLUGIN_ROOT}/pipeline-tools/scripts/summarize_run.py --run-log <the lane's run log> --ledger <the lane's gate ledger>` — what the run cost, per agent and per unit, and which gates fired versus only ever passed. These files were written by tools at the moment each thing happened; everything below was written by someone recalling it.
   - **Resolve the roots first — the session may hold more than one, and the epic path is only one of five.** Read every root that exists, in this order, and say which you read:
     | Root | Run log | Gate ledger |
     |---|---|---|
     | `.docs/{project-name}/implementation/` (plan/lite/build/shipping/verify epic) | `run-log.jsonl` | `gates.jsonl` |
     | `.docs/{project-name}/implementation/bugs/<bug-slug>/` (bugfix, feature route) | `run-log.jsonl` | `gates.jsonl` |
     | `.docs/bugfix/<slug>/` (bugfix, standalone route) | `run-log.jsonl` | `gates.jsonl` |
     | `.docs/quick/<date>-<slug>/` | **none** — the lane delegates to nobody (`bgpdd-quick` §1) | `gates.jsonl` |
     | `.docs/summary/` (discovery) | `run-log.jsonl` (`bgpdd-discovery` §1) | `gates.jsonl` |
   - **A root with no run log gets the ledger alone**, and you say so in the brief rather than reporting an empty cost table: quick has no delegations to cost. A root whose files are simply absent is a lane that never ran here — skip it silently.
2. **The game tapes** — `game-tape.md` under each root above that has one (quick's single bullet lives in its `note.md`; discovery and learn keep no tape, per the skeleton).
3. **The durable reports** — `review-report.md`, `test-report.md`, `security-report.md`, handoffs relayed in-conversation, and recent `git log`.
4. **Filtered transcript greps**, last and only for what the first three left open (never a full read — see Step 2).

Compress into an evidence brief of at most 15 bullets: what happened, which skill/agent/rule was involved, what the user had to correct. Carry the run-log summary's fired-versus-rubber-stamped counts into the brief verbatim — Forge needs them to satisfy the Incident Test on any gate proposal.

**Record confirmations, not only failures.** A decision or rule that a later phase confirmed worked cleanly is evidence too — it identifies which rules are earning their keep and must be protected from future pruning or "simplification". Include at least the confirmations you have evidence for: designs that built and tested first time, gates that caught a real defect, rules whose presence visibly prevented a class of error. An evidence brief composed only of failures teaches the next optimization pass to delete the rules that were quietly working, and gives Forge no way to distinguish a load-bearing rule from dead weight.

**Transcript access:** if the runtime persists session transcripts as files (Claude Code: `~/.claude/projects/<project-slug>/<session-id>.jsonl`), resolve the current session's transcript path and pass it to Forge alongside the brief. The brief remains the always-available fallback.

### Step 2: DELEGATE (Forge — Learning Triage mode)

Pass Forge: the evidence brief, the list of skills/agents involved, the transcript path (when available), and **the absolute path of this plugin's `skills/` directory as his `{PLUGIN_ROOT}`**. Forge is a spawned subagent and cannot compute his own on-disk location — without that path injected he must either guess or scan the filesystem to reach his own methodology and the destination files, which his Path Resolution rule forbids. Resolve it from this skill's provided base directory (its parent) and state it explicitly in the brief. Forge applies his `agent-orchestration-improve-agent` methodology (Phase 2 root cause, Phase 3 generalized rule + Pruning Protocol) plus its Destination Triage rubric.

State the hard filtered-read rule in the delegation: Forge NEVER full-reads a transcript file — transcripts embed every tool result. He greps targeted slices only (user messages, correction phrases, `<handoff>` blocks, error/circuit-breaker patterns, skill invocations), then reads just those line ranges.

### Step 3: PROPOSAL

Forge does NOT write any proposal file. He returns the improvement plan inside his `<handoff>` — per lesson: the generalized rule, its destination file, and a one-line rationale for that layer. You read the plan from the handoff. **Validate it with `check_handoff.py --advisory`** (plus `--persona forge --repo . --since <the sha HEAD held when you launched him> --ledger <the lane's gate ledger>`): the brief declares no artifact, and `--advisory` is what lets a deliberately artifact-less handoff pass instead of failing `element_missing`. Without the flag this gate fails by design on every run of this step.

**One lesson, one destination, listed separately.** Reject a plan that groups several lessons under one destination line or leaves a lesson's destination implicit, and send it back for the pairing — this is what makes a later revert one file per lesson instead of an unpickable batch. A lesson that genuinely needs two files is two entries, not one.

### Step 4: HALT & APPROVE

Relay the plan from Forge's handoff to the user and halt. Never apply without explicit approval.

### Step 5: APPLY

On approval, resume the same Forge instance if the runtime supports warm continuation; otherwise delegate a **fresh** Forge with the approved plan only (align with `bgpdd-shipping` Step 7's fresh-on-apply when non-resumable). Paste only the approved lessons (rule + destination per lesson); Forge applies them per his Vector A/B edit scoping. Do NOT re-send the full evidence brief to a fresh Forge — the approved plan is the briefing.

**Before applying**, optionally bracket the change with evals exactly as `bgpdd-shipping` Step 7 step 4 does: run `evals/weekly-check.ps1` (zero-token), relay the `run-evals.ps1` command it prints, and run the "before" leg only if the user asks for it.

**After applying**, run the same post-apply guard `bgpdd-shipping` Step 7 step 6 specifies — `git diff --name-only`, HALT on any changed path that is `agents/blackgoat.md`, lies outside the plugin directory, or touches a frontmatter block, and leave the revert decision to the user. The rationale lives there; it is not restated here. It applies unchanged on this route: the apply is the same Forge doing the same edits, and a mid-epic run has *less* review around it than an end-of-epic one, not more.

### Escalate When

- **No substantive lessons found** — say so plainly; do not invent lessons to justify the run.
- **A lesson contradicts an existing rule** — propose a replacement; never append a conflict.
- **A destination file is outside Forge's write boundary and the user has not approved** — halt.

## Relationship to Other Skills

- **Reuses** the `agent-orchestration-improve-agent` analyze/apply contract, including its Destination Triage rubric.
- **Supersedes** ad-hoc rule appending, such as bgpdd-bugfix's old Phase 5.
- **Complements** the per-phase Game Tape checkpoints and the single end-of-epic Forge run (bgpdd-shipping Step 7); it is the mid-epic escape valve when lessons should not wait for the epic to ship.
