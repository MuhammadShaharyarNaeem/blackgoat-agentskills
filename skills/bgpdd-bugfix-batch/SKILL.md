---
name: bgpdd-bugfix-batch
description: "Fixes two to five independent localized bugs in one session by running the /bgpdd-bugfix contract once per bug in its own git worktree: parallel RED captures, per-route builders, a GREEN and a fresh Luna per bug, then each bug's own commit gate and one merge at a time. Choreography only — it restates no bugfix rule. Trigger phrases: 'fix these bugs', 'batch of bugs', 'use bgpdd-bugfix-batch'."
trigger: /bgpdd-bugfix-batch
category: execution
risk: safe
---

# bgPDD-Bugfix-Batch

## Purpose
`/bgpdd-bugfix` is the contract; this lane is only the choreography that runs N of it at once, so every rule here cites bugfix or the Orchestrator Contract and restates neither. Why it exists, the hook interaction, the overlap rule, the wave diagram and an example `batch.md`: `{PLUGIN_ROOT}/bgpdd-bugfix-batch/references/batch-rationale.md`.

## When to Use This Skill
- **Two to five** independent localized bugs, each admissible to `{PLUGIN_ROOT}/bgpdd-bugfix/SKILL.md` § *When to Use This Skill* alone.
- **NOT** one bug (`/bgpdd-bugfix`); **NOT** bugfix's feature route (`## Limitations`).

---

## 1. Paths and Mandatory Reads

> **Read `{PLUGIN_ROOT}/bgpdd-bugfix/SKILL.md` in full first — it is THE per-bug contract and this file is unreadable without it.** Then `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` **§1, §2, §4** and `{PLUGIN_ROOT}/agent-squad/pipeline-skeleton.md` § *Branch close*. An unresolved path is a STOP.
>
> **§3 and §5 dropped — a deliberate convention-#8 trim of bugfix's read-in-full rule**: every phase a bug spends is bugfix's, under bugfix's own reads.

- `{batch-root}` = `.docs/bugfix-batch/{YYYY-MM-DD}-{batch-slug}/`, **in the main tree**: `batch.md` (the bug list with per-bug status), `gates.jsonl`, `run-log.jsonl`, `game-tape.md` — no epic to live under, exactly as `bgpdd-bugfix` § 1 refines `base-persona.md` (convention #8).
- **Each bug's `{bugfix-root}` is inside ITS worktree, resolved by `bgpdd-bugfix` § 1 unchanged.**

## 2. Execution Workflow

### Phase 0: Batch list (main session)
Agree the bug list with the user; pick `{batch-slug}` and a `{bug-slug}` each; **N ≤ 5** (§3). No report is written yet — its only home is `{bugfix-root}` *inside* a worktree that does not exist until Phase 1.

### Phase 1: Isolation, then intake
Per bug: `git worktree add <path> -b fix/{bug-slug} <base>`, `<base>` read from the repo (`pipeline-skeleton` § *Branch close*). **Each worktree is then its own single lane to the hook** — `guard_action.py`'s detector is `cwd`-rooted and globs `<cwd>/.docs/bugfix/*/bug-report.md` (rationale § 2). `.docs/bugfix-batch/` matches no detector, so `{batch-root}` arms no lane. Then, inside each worktree, `bgpdd-bugfix` § Phase 0 for that bug, gate included, **one bug at a time with the user** (Contract §1: interactive steps are never delegated).

### Phase 2: Waves
Each wave launches every eligible bug's step in **one message, in the background** (Contract §1); worktrees already partition the write surfaces. **Per bug the step is what `{PLUGIN_ROOT}/pipeline-tools/scripts/pipeline_driver.py --root {bugfix-root} --lane bugfix --milestone "{bug-slug}" --json` emits there.** In order: **RED** (`bgpdd-bugfix` § Phase 1), **RCA and route** (§ Phase 2, main session), **Fix** (§ Phase 3, Mason and/or Nova by that bug's `- Surface:`), **GREEN** (§ Phase 4), **Review** (§ Phase 5 steps 1–4b, a **fresh** Luna per bug).

`PLAN` at the route step **drops that bug**: hand it and its report to `/bgpdd-plan`, mark `DROPPED-PLAN` in `batch.md`, remove its worktree, continue with the rest.

### Phase 3: Close, then merge
1. Per bug, § Phase 5 step 5 — its own `check_commit_gate.py --commit`, in its worktree, unchanged.
2. Then, **one bug at a time, in §3's overlap order**: **(a) precondition, mechanical (convention #9)** — `{PLUGIN_ROOT}/pipeline-tools/scripts/check_ledger.py --ledger <that bug's root>/gates.jsonl` exits 0 **and** that ledger's latest `check_commit_gate.py` record is a `PASS` carrying `--commit`; **(b)** commit that bug's `.docs/bugfix/{bug-slug}/` on its own branch — the gate exempts `.docs/` from `--verify-tree`, so its evidence is untracked and Phase 4's `git worktree remove` would delete it, and `guard_action.py` rule 1's closed-lane carve-out permits this commit once (a) holds; **(c)** merge `fix/{bug-slug}` into the base.
3. An overlap or a conflict routes that bug: **rebase its branch on the merged base, re-run its § Phase 4 GREEN and `check_red_green.py` there**, re-commit its evidence, then merge. Never re-enter step 1 (the fix is committed — the gate answers `already_committed`) and never hand-resolve a conflict: a rebase that cannot replay cleanly is a HALT (§4).

### Phase 4: Batch close
`batch.md`'s final table, a row per bug citing **its commit sha and the ledger record** step 2(a) verified; `git worktree remove` per bug (its evidence is committed, per step 2(b)); **one game-tape bullet per bug** in `{batch-root}/game-tape.md` — unlike bugfix's 2–4 per phase transition, already written per bug (convention #8).

## 3. Rules
- **N ≤ 5 — deliberately looser than `bgpdd-bugfix`'s one bug and `bgpdd-quick`'s ≤ 3 files (convention #8)**: it bounds merges, not fix size — bugfix's `--max-changed-files 5` still binds per bug.
- **Overlapping bugs serialise** — same `## Affected surface`, or intersecting builder `<changed_files>` (`bgpdd-bugfix` § 1's `check_handoff.py --since --ledger`). The second merges after the first and takes Phase 3 step 3's rebase-and-re-GREEN route.
- **Run log: per-bug root only** (`bgpdd-bugfix` § 1) — its commit gate's `--require-run-log` reads that file. `{batch-root}/run-log.jsonl` takes one line per phase: `--event note --pipeline bgpdd-bugfix-batch --unit {batch-slug}`.
- **Ledger**: per-bug gates carry `--ledger {bugfix-root}/gates.jsonl --milestone "{bug-slug}"`; `{batch-root}/gates.jsonl` holds only this lane's `check_ledger.py` runs.

## 4. Escalation
| Condition | Route |
|---|---|
| A bug routes `PLAN` | `/bgpdd-plan`; the batch continues |
| A rebase cannot replay, or one survives a round | HALT that bug (Contract §2) |
| N > 5, or a bug bugfix would refuse alone | sequential `/bgpdd-bugfix` runs |
| A bug belongs to an in-flight epic | bugfix's feature route |

## Limitations
- **No shared-file conflict resolution** — two bugs needing one edit are one bug.
- **No cross-bug RCA** — a shared root cause is one bug with one fix.
- **N ≤ 5**, with no queue, schedule or resume past it.
- **Feature-route bugs of an in-flight epic are not batched** — that epic is one worktree on one branch, and `bgpdd-bugfix` § 1 forbids a private fix branch there.
