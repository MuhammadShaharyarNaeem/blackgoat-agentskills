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

---

## 1. Global System Constraints

> ### MANDATORY FIRST READ
>
> **Before Phase 0 you MUST read `## Runtime Neutrality`, `## 3. Role Boundaries`, §1's *Command Timeout Discipline* rule and §2's three halt triggers from `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md`, then `{PLUGIN_ROOT}/agent-squad/pipeline-skeleton.md` in full** (path resolution, error recovery, upgraded chain of thought, game tape). Improvise neither from memory; an unresolved path is a STOP. Refinements below override the skeleton only where labelled (convention #8).
>
> **Four items, not the whole contract — a deliberate convention-#8 refinement of the every-pipeline-reads-the-contract rule.** Dropped: delegation construction, background execution, continuation-vs-fresh, phase-transition confirmation, the state hand-off, and the three rules passed verbatim to subagents — all of which govern a delegated agent, and this lane delegates to nobody. **Kept, because here the Orchestrator *is* the worker**: the 4-minute bound on every command you run, and the halt triggers (tool-call loop, hallucinated path, three failed attempts). **If this lane escalates, the receiving lane reads the contract in full.**

The bullets below carry ONLY this skill's refinements.

- **No delegation: you are the worker — deliberate divergence from Contract §3's role boundaries (convention #8).** §3 guards against context collapse; at three files there is no separation of duties to buy. Not relaxed: Phase 2's capture, never your reading, is the evidence.
- **Methodology on demand, inline.** Follow one `{PLUGIN_ROOT}/<skill>/SKILL.md` yourself — its **`## Quick card`** where it has one, else its Worker Execution Contract. The three usual: `test-driven-development` (new behaviour with a test), `debugging-and-error-recovery` (something broken), `code-simplification` (a refactor). **Any skill carrying a `## Quick card` is admissible — a deliberate widening of this rule's own prior three-skill list (convention #8)**: the card *is* that skill's contract at this lane's size, written by its owner for exactly this use, so refusing a skill that advertises one makes the cards unreachable. Still one skill, never two; no card and no fit → wrong lane.
- **Workspace**: `{quick-root}` = `.docs/quick/{YYYY-MM-DD}-{slug}/` — refining `base-persona.md`'s `.docs/{project-name}/` model (convention #8): no epic to live under. Holds `note.md`, `evidence/check.md` (+ sidecar), `gates.jsonl`.
- **No `orchestrator-state.json`, no `run-log.jsonl` — deliberate divergence from Contract §4 (convention #8).** State is an inter-pipeline handoff and this lane closes in one session; the run log records *delegations*, and this lane never delegates. `gates.jsonl` plus the commit is the record.
- **Phase transitions are emitted, not recalled (convention #9):** before starting any phase run `python {PLUGIN_ROOT}/pipeline-tools/scripts/pipeline_driver.py --root {quick-root} --lane quick --json`; do the `next_action` it prints; exit 1 means the current phase's gate has not passed — run that gate, never the next phase. (Exit 3 = closed and committed.) Contract in `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
- **Autonomous, by Contract §1's own exception.** Phase 0's note is the single user checkpoint; Phases 1–3 need no confirmation; escalations and blocked gates return to the user.
- **Game tape — deliberate divergence from the skeleton's game-tape rule (convention #8)**: **one bullet** under `## Result` in `{quick-root}/note.md`, not a `game-tape.md`: what the gate said, plus what surprised you.
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

   **A test that goes red *while* you make this change stays here** — your own edit misbehaving, which is what the `debugging-and-error-recovery` card is for; a defect that existed **before you started**, with a reproduction, is `/bgpdd-bugfix`. **Escalating mid-change leaves a dirty tree**: name every edit already made and either stash it or hand it over as declared changes — `/bgpdd-bugfix` closes on `--verify-tree`, which blocks undeclared ones (its Phase 0 step 1). Escalation stays one-way and upward (the router's ratchet), and **seeds** the next intake: the note's `What` drafts the bug report's observed behaviour, its `How verified` the reproduction command — drafts only; `check_bugfix_intake.py` still lints them.

3. **Run the stack detector; propose, never adopt, its defaults:**
   ```bash
   python {PLUGIN_ROOT}/pipeline-tools/scripts/detect_stack.py --repo . --json
   ```
   Offer its first `suggested_check_commands` entry as the `How verified` default — the user confirms or replaces it, never you silently. `test_path_globs` goes to Phase 3's `--frozen`. A detected stack with a `skills` entry contributes **only** its `## Quick card` (§1); without a card it contributes nothing here (e.g. `{PLUGIN_ROOT}/vue3-spa-patterns/SKILL.md § Quick card`).
4. **Write `{quick-root}/note.md`** — three labelled lines, no placeholders:
   - `- What:` the one sentence.
   - `- Where:` every file you will touch, comma-separated, **≤ 3**. Phase 3 requires it to equal what changed.
   - `- How verified:` the exact command — a test, a build, a one-line `python -c` assertion. Never "manually".
5. Read the methodology skill you will apply (§1).

### Phase 1: Change (main session)
**Driver:** the driver must report `phase: 1`.
1. Edit only the files the `Where` line names.
2. **Never edit an existing test to make it pass** — a wrong test is a defect with a reproduction (`/bgpdd-bugfix`); Phase 3's `--frozen` globs enforce this.
3. Wider than the note → back to Phase 0.

### Phase 2: Prove (main session)
**Driver:** the driver still reports `phase: 1` — it fuses Change and Prove, because an edit leaves no artifact and this capture is the only observable either phase has.
Run the `How verified` command **through the capture wrapper**, never bare:

```bash
python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture {quick-root}/evidence/check.md -- <the command>
```

Exit 0 required; non-zero → fix and re-run (one round, §1). Phase 3 reads the `check.md.meta.json` sidecar — a hand-written `check.md` has none, and fails closed.

### Phase 3: Close (the gate)
**Driver:** the driver must report `phase: 3`; after the gate it reports `phase: 4` at exit 3.

**When the change adds or edits a test file**, run this before `check_quick_close.py` — that gate has no knowledge of it:
```bash
python {PLUGIN_ROOT}/pipeline-tools/scripts/check_test_authenticity.py --repo . --changed-files <paths> --milestone "{slug}" --ledger {quick-root}/gates.jsonl
```
Principle: `test-driven-development/SKILL.md` § Rules — not restated here. Exit 0 = proceed; cite the ledger entry in the `## Result` bullet (§1). Exit 1 = the one round §1 allows — fix and re-run. Exit 2 = artifact defect. **`pipeline_driver.py` does not emit this step yet** — nothing enforces remembering it.

```bash
python {PLUGIN_ROOT}/pipeline-tools/scripts/check_quick_close.py \
    --note {quick-root}/note.md --capture {quick-root}/evidence/check.md \
    --changed-files <paths> --repo . --max-changed-files 3 \
    --frozen '<glob>' [--frozen '<glob>']... \
    --milestone "{slug}" --ledger {quick-root}/gates.jsonl \
    --commit --message "<msg>"
```

**Pass Phase 0's `test_path_globs`, one `--frozen` per glob** (`tests/**`, `**/*.spec.ts`; a value with no `*`/`?`/`[` is a directory prefix). **The gate holds no default and must not**: a guessed freeze that misses is indistinguishable from a change with no test to protect. Adding a test passes.

- **Exit 0** = every term held; the gate committed exactly the declared files. Append the `## Result` bullet (§1).
- **Exit 1** = **BLOCK**; `problem_codes` names the term. Fix and re-run once. Three terms route differently:
  - `size_bound_exceeded` is unfixable here — **no `--waiver`, deliberately tighter than `bgpdd-bugfix`'s `check_commit_gate.py --waiver` (convention #8)**: the bound *is* the lane, so an overrun means the wrong one — the message names where to escalate.
  - `frozen_path_modified` has an escape the gate's message does not name: **narrow the glob.** A rename touches its call sites and one of them is usually a test — this lane's headline case, not a defect, so do not take the message's routing to `/bgpdd-bugfix`, which has no reproduction to intake. Re-run with the narrower `--frozen` set that still covers the tests you must not edit, record which glob you narrowed and why in `## Result`, and count it as the one round.
  - `capture_command_mismatch` = the capture's recorded `argv` is not the note's `How verified` command. The capture must *be* that command's run: re-run it verbatim through `run_quiet.py --capture`, or correct the note first if the command you needed differed. Never edit the sidecar.
- **Exit 2** = artifact or environment defect (missing flag, no Python, git unusable). Never hand-edit an artifact to pass a gate.

## Limitations
- The gate proves the declared change was checked, not that it was honest about *scale* — three files can still be an architecture change, and Phase 0's table is the only (prose) guard.
