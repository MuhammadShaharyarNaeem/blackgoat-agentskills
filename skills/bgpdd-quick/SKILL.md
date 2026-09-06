---
name: bgpdd-quick
description: "The daily-driver lane for one small contained change — a rename, an added test, a small refactor, a one-file edit, a config tweak. Main session only: no delegation, no epic, no plan.md. Three lines of intent, one captured check, one close gate that commits. Trigger phrases: 'quick change', 'small change', 'just rename this', 'use bgpdd-quick'."
trigger: /bgpdd-quick
category: execution
risk: safe
---

# bgPDD-Quick

## Purpose
Most changes are not epics. The smallest lane that still leaves evidence: what you meant to change, where, and the command proving it — declared *before* the edit, gated *after*. Rationale, escalation, examples: `{PLUGIN_ROOT}/bgpdd-quick/references/quick-rationale.md`.

## When to Use This Skill
- One contained change statable in a sentence, touching **≤ 3 files**, whose check exists or is one line to write: a rename, an added test, a small refactor, a config tweak.
- **NOT** when it alters behaviour others depend on, fixes a reported defect, or adds a capability or contract — Phase 0's table routes those out.
- Trigger phrases: "quick change", "just rename this", "use bgpdd-quick".

---

## 1. Global System Constraints

> ### MANDATORY FIRST READ — the Orchestrator Contract
>
> **Before Phase 0, you MUST read `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md` in full.** Do not improvise those rules from memory. If the file does not resolve, STOP and report the broken path.
>
> Then read `{PLUGIN_ROOT}/agent-squad/pipeline-skeleton.md` — the shared pipeline skeleton (path resolution, error recovery, upgraded chain of thought, game tape). Refinements below override the skeleton only where labelled (convention #8).

The bullets below carry ONLY this skill's refinements.

- **No delegation: you are the worker — deliberate divergence from Contract §3's role boundaries (convention #8).** §3 stops you collapsing your context by roleplaying a squad; at three files there is no separation-of-duties value to buy. Not relaxed: Phase 2's capture, never your reading, is the evidence.
- **Methodology on demand, inline.** Load one from `{PLUGIN_ROOT}/<skill>/SKILL.md`; follow its Worker Execution Contract yourself: `test-driven-development` (new behaviour with a test), `debugging-and-error-recovery` (something broken), `code-simplification` (a refactor). None fits → wrong lane.
- **Workspace**: `{quick-root}` = `.docs/quick/{YYYY-MM-DD}-{slug}/` — refining `base-persona.md`'s `.docs/{project-name}/` model (convention #8): no epic to live under. Holds `note.md`, `evidence/check.md` (+ sidecar), `gates.jsonl`; the gate carries `--ledger {quick-root}/gates.jsonl --milestone "{slug}"`.
- **No `orchestrator-state.json`, no `run-log.jsonl` — deliberate divergence from Contract §4 (convention #8).** State is an inter-pipeline handoff and this lane closes in one session; the run log records *delegations*, and this lane never delegates — §4's obligation has nothing to record. `gates.jsonl` plus the commit is the record.
- **Phase transitions are emitted, not recalled (convention #9):** before starting any phase run `python {PLUGIN_ROOT}/pipeline-tools/scripts/pipeline_driver.py --root {quick-root} --lane quick --json`; do the `next_action` it prints; exit 1 means a gate for the current phase has not passed — run that gate, never the next phase. (Exit 3 = the change is closed and committed.) Contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
- **Autonomous, by Contract §1's own exception.** Phase 0's note is the single user checkpoint; Phases 1–3 need no confirmation; escalations and blocked gates return to the user.
- **Game tape — deliberate divergence from the skeleton's cadence, cap and location (convention #8)**: **one bullet** under `## Result` in `{quick-root}/note.md`, not a `game-tape.md` — what the gate said, plus what surprised you.
- **Round bound: 1 (convention #8, deliberately tighter than `bgpdd-bugfix`'s 2).** One blocked close is a fix-and-re-run; a second means the change was never quick — escalate.

---

## 2. Execution Workflow

Four phases; do not skip or reorder.

### Phase 0: Scope (main session)
**Driver:** `pipeline_driver.py --root {quick-root} --lane quick` must report `phase: 0`.
1. State the intent in **one sentence** with the user; pick `{slug}` and resolve `{quick-root}` (§1).
2. **Escalate before writing anything** — HALT and name the lane, never start it. Route by what the change *is*, not how long it feels.

   | The change | Route |
   |---|---|
   | Alters behaviour something else depends on | `/bgpdd-lite` |
   | Fixes a defect that has a reproduction | `/bgpdd-bugfix` |
   | Adds a capability, or changes a schema or contract | `/bgpdd-plan` |

3. **Write `{quick-root}/note.md`** — three labelled lines, no placeholders:
   - `- What:` the one sentence.
   - `- Where:` every file you will touch, comma-separated, **≤ 3**. Phase 3 requires it to equal what changed.
   - `- How verified:` the exact command — a test, a build, a one-line `python -c` assertion. Never "manually".
4. Read the methodology skill you will apply (§1).

### Phase 1: Change (main session)
**Driver:** the driver must report `phase: 1`.
1. Edit only the files the `Where` line names.
2. **Never edit an existing test to make it pass.** A wrong test is a defect with a reproduction — `/bgpdd-bugfix`. Phase 3's `--frozen` list enforces this.
3. Wider than the note → back to Phase 0.

### Phase 2: Prove (main session)
**Driver:** the driver still reports `phase: 1` here — it fuses Change and Prove, because an edit leaves no artifact of its own and this capture is the only observable either phase has.
Run the `How verified` command **through the capture wrapper**, never bare:

```bash
python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture {quick-root}/evidence/check.md -- <the command>
```

Exit 0 required; non-zero → fix and re-run (one round, §1). Phase 3 reads the `check.md.meta.json` sidecar — a hand-written `check.md` has none, and fails closed.

### Phase 3: Close (the gate)
**Driver:** the driver must report `phase: 3`; after the gate it reports `phase: 4` at exit 3.
```bash
python {PLUGIN_ROOT}/pipeline-tools/scripts/check_quick_close.py \
    --note {quick-root}/note.md --capture {quick-root}/evidence/check.md \
    --changed-files <paths> --repo . --max-changed-files 3 \
    --frozen tests/ [--frozen <path>]... \
    --milestone "{slug}" --ledger {quick-root}/gates.jsonl \
    --commit --message "<msg>"
```

- **Exit 0** = every term held; the gate committed exactly the declared files. Append the `## Result` bullet (§1).
- **Exit 1** = **BLOCK**; `problem_codes` names the term. Fix and re-run once. `size_bound_exceeded` is unfixable here — **no `--waiver`, deliberately tighter than `bgpdd-bugfix`'s `check_commit_gate.py --waiver` (convention #8)**: the bound *is* the lane, so an overrun means the wrong one. The message names where to escalate.
- **Exit 2** = artifact or environment defect (missing flag, no Python, git unusable). Never hand-edit an artifact to pass a gate.
- `--frozen` names tests this change must not **edit** — usually the whole test root. Adding a new test passes; narrowing or dropping it must be recorded in `## Result`.

## Limitations
- The gate proves the declared change was checked, not that it was honest about *scale* — three files can still be an architecture change, and Phase 0's table is the only (prose) guard.
