---
name: bgpdd-build-agy
description: "Phase 2 Execution exactly as /bgpdd-build, with one substitution: the builders (Mason, Nova, Max) run headless in the Antigravity CLI on Gemini 3.8 Flash High through the run_agy_builder.py gate instead of as delegated subagents, while Quinn (mid tier) and Luna (top tier) stay delegated. Choreography only — it restates no build rule. Opt-in; plain build requests stay on /bgpdd-build. Trigger phrases: '/bgpdd-build-agy', 'build with agy', 'build on gemini', 'use bgpdd-build-agy'."
trigger: /bgpdd-build-agy
category: execution
risk: safe
---

# bgPDD-Build-Agy

## Purpose
`/bgpdd-build` is the contract; this lane changes only **who runs the builder step and on what model**. Every phase, gate, bound, ledger, state write and commit is `/bgpdd-build`'s, unchanged — this file cites it and restates none of it. Invoke with `/bgpdd-build-agy` (the `auto` argument behaves as in `/bgpdd-build` §3).

## When to Use This Skill
- The user asks for a `/bgpdd-build` run **with the builders on agy / Gemini** — by name or by a trigger phrase. Opt-in only: an unqualified "execute the plan" is `/bgpdd-build`.
- **NOT** when agy is not installed or its plugin copy fails the preflight (§3) — run `/bgpdd-build` instead, on the user's word.

---

## 1. Paths and Mandatory Reads

> **Read `{PLUGIN_ROOT}/bgpdd-build/SKILL.md` in full first — it is THE contract and this file is unreadable without it**, together with every read it makes mandatory (the Orchestrator Contract, the pipeline skeleton, and its `references/` sub-contracts at their call sites). Then run `python {PLUGIN_ROOT}/pipeline-tools/scripts/run_agy_builder.py --help` — the gate's contract of record. An unresolved path is a STOP.

- **State, ledger, run log, game tape, plan, evidence paths**: `/bgpdd-build`'s, byte for byte. The lane writes `pipeline` as `bgpdd-build` and runs every `tool_registry.py for --lane bgpdd-build` listing — it is that lane with a substituted builder, so `/bgpdd-shipping`'s hydration and every gate read it unchanged.
- **The lane's own files**, under `.docs/{project-name}/implementation/agy/`: `<milestone-slug>-r<N>-brief.md` (the briefing the Orchestrator wrote) and `<milestone-slug>-r<N>-handoff.md` (the gate's `--out`), `r1` for the initial build and one more per fix run. A separate folder because `/bgpdd-build` § 4 forbids merging its four evidence paths.

## 2. Who Runs Where

| Persona | Runs as | Tier |
|---|---|---|
| Mason, Nova, Max | `run_agy_builder.py --persona <name>` (headless Antigravity CLI) | `gemini-3.8-flash-high` |
| Quinn | delegated subagent, as `/bgpdd-build` | mid tier (`sonnet`, 5.5, under Claude Code) |
| Luna | delegated subagent, as `/bgpdd-build` — always fresh | top tier (`opus`, 5.5, under Claude Code) |
| Dep, Cipher, Aria (advisory), Alex (re-plan) | delegated subagents, as `/bgpdd-build` | their frontmatter `model:` |

- **These tiers are a deliberate per-lane override of the personas' frontmatter `model:` pins (convention #8)** — Quinn is pinned `opus` and runs one tier lower here; Mason and Nova (`opus`) and Max (`sonnet`) run off-runtime. The agent files are not edited: the pin stays the default for every other lane, and this lane sets the tier on each delegation it makes.
- **Max**: `/bgpdd-build` delegates no Max (its Phase 4 note), so neither does this lane; the gate accepts `--persona max` only so the substitution holds wherever that contract would route him.

## 3. Preflight — once per session, before the first builder run

Run alongside `/bgpdd-build` Phase 0, and record each result as a Phase 0 line in the game tape:
1. **The agy executable resolves on PATH** (a lookup, not a run). Missing → STOP; offer `/bgpdd-build`.
2. **agy registers the same personas as this plugin**: compare the names `agy agents` prints (a listing; it runs no model) with the persona names of `{PLUGIN_ROOT}/../agents/*.md`. They must be equal, and mason, nova and max must be present. A difference → STOP and name the missing or extra personas; the user syncs agy's copy, then re-run this check. (Observed drift: on 2026-10-12 `ward.md` was on disk in agy's copy but unregistered, because it still carried a `model:` line.)
3. Record agy's copy's HEAD sha beside the plugin's in that game-tape line — a fact, not a gate.

## 4. The Builder Step

Every place `/bgpdd-build` delegates Mason or Nova — `{PLUGIN_ROOT}/bgpdd-build/SKILL.md` § *Phase 1: Building* step 3 (initial build), step 5d (the fresh builder after Aria's ruling), and every fix or refactor return in § *Phase 2: Testing* step 3, § *Phase 3: Code Review* step 4 and § *Phase 4: Optimization & Refactoring (Builder Follow-Up)* step 2 — becomes:

1. **Write the brief** to `<milestone-slug>-r<N>-brief.md`: the same briefing `/bgpdd-build` would have delegated (`{PLUGIN_ROOT}/agent-squad/SKILL.md` § *4. Agent Delegation*), every injection that phase names included. A fix run's brief also carries the prior round's `--out` file and the findings being fixed — this is the Orchestrator Contract §1 *Continuation vs fresh delegation* fallback for a runtime with no follow-up message ("fresh re-delegation with the prior `<handoff>`"), so a fix run still counts against that rule's continuation cap and the phase's own round bound exactly as a follow-up would.
2. **Run the gate** with `--persona` from `/bgpdd-build`'s domain routing, `--workspace` = the checkout on the working branch `/bgpdd-build` § 1 *Git Workflow* established (never the default branch), `--brief-file` the file from step 1, `--out` the handoff file. Pass `--timeout-s` only for a milestone you expect to exceed the default. When the host caps a single foreground command below the gate's `--timeout-s`, run the gate as a background (long-running) command and wait for its exit before reading `--out` — never shorten `--timeout-s` to fit the host's cap.
3. **Read the exit code before anything else:**
   - **0** → the `--out` file **is** the builder's `<handoff>` for every downstream step: `/bgpdd-build`'s `check_handoff` validation, the changed-files union (§ *Phase 1: Building* step 6, from its `<changed_files>`), the `<fix_verification>` precondition, `review_package`, Quinn's and Luna's briefs.
   - **1** → a finding (workspace escape, HEAD moved, timeout, or no handoff). **That milestone is BLOCKED**: record it with `/bgpdd-build`'s `update_state --add-blocker` line scoped to the milestone, report the gate's JSON to the user, and stop the milestone. Do **not** pass the output to Quinn or Luna, do **not** hand-fix the workspace, and do **not** re-run without the user's word — the escape incidents are why. In Auto Mode this is a circuit breaker (`/bgpdd-build` §3).
   - **2** → usage or infrastructure: report it; nothing ran to review.
4. **Record the run** with `/bgpdd-build`'s `record_run` line: `--agent <persona> --model gemini-3.8-flash-high --tier sonnet`, tokens from the `--out` file when it carries them, else `--tokens-unavailable "agy: <reason>"`. `sonnet` is the tier this lane maps Flash High to, so `record_run.py`'s verifier-below-producer check holds with Quinn on the mid tier.

## 5. Rules
- **The agy run never commits.** The gate refuses a moved HEAD; the milestone commits through `/bgpdd-build`'s commit gate, unchanged.
- **Quinn and Luna** are delegated exactly where `/bgpdd-build` delegates them, at the §2 tiers, on the `--out` handoff as the builder's.
- **Everything not named above is `/bgpdd-build`'s**, including every HALT, bound and gate.

## 6. Escalation
| Condition | Route |
|---|---|
| Gate exit 1 | Milestone BLOCKED; user decides (re-run, `/bgpdd-build` for that milestone, or stop) |
| Preflight fails | STOP; user syncs agy or runs `/bgpdd-build` |
| Any `/bgpdd-build` HALT | `/bgpdd-build`'s route |

## Limitations
- **One workspace per gate run** — a milestone whose domain tag spans more than one repo runs under `/bgpdd-build`.
- **No follow-up messages to a builder** — every fix round is a fresh agy run carrying the prior handoff (§4 step 1).
