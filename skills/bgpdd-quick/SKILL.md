---
name: bgpdd-quick
description: "The daily-driver lane for one small contained change — a rename, an added test, a small refactor, a one-file edit, a config tweak. One builder (Mason, Nova or Max) makes the edit; no epic, no plan.md, no Luna. Three lines of intent, one captured check, one close gate that commits. Trigger phrases: 'quick change', 'small change', 'just rename this', 'use bgpdd-quick'."
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
> **Before Phase 0 you MUST read `## Runtime Neutrality`, `## 1. Delegation Discipline`, `## 2. Error Recovery`, `## 3. Role Boundaries` and §4's run-log rule (*Every delegation completion … appends a run-log record*) from `{PLUGIN_ROOT}/agent-squad/orchestrator-contract.md`, then `{PLUGIN_ROOT}/agent-squad/pipeline-skeleton.md` in full** (path resolution, error recovery, upgraded chain of thought, game tape). Improvise neither from memory; an unresolved path is a STOP. Refinements below override the skeleton only where labelled (convention #8).
>
> **Four sections and one rule, not the whole contract — a deliberate convention-#8 refinement of the every-pipeline-reads-the-contract rule.** Dropped: the rest of §4 (state hydration and the inter-pipeline hand-off) and §5–§6 — this lane hydrates no state, hands off to nobody and delegates exactly once, so there is no second handoff to synthesise. **If this lane escalates, the receiving lane reads the contract in full.**

The bullets below carry ONLY this skill's refinements.

- **One builder makes the edit; you never do (Contract §3).** Pick it by the kind of change: **Mason** — backend/`[API]`, scripts, config, docs; **Nova** — `[UI]`; **Max** — a refactor with no behaviour change. One builder, one delegation, never two. You keep the note, the brief, the Phase 2 capture and the Phase 3 close gate that commits. No Luna: Phase 2's capture and Phase 3's gate, never your reading, are the evidence.
- **Methodology on demand, named in the brief.** The builder follows one `{PLUGIN_ROOT}/<skill>/SKILL.md` — its **`## Quick card`** where it has one, else its Worker Execution Contract; you name it. The three usual: `test-driven-development` (new behaviour with a test), `debugging-and-error-recovery` (something broken), `code-simplification` (a refactor). **Any skill carrying a `## Quick card` is admissible — a deliberate widening of this rule's own prior three-skill list (convention #8)**: the card *is* that skill's contract at this lane's size, written by its owner for exactly this use, so refusing a skill that advertises one makes the cards unreachable. **Except an Orchestrator-run skill** — one whose spine is an `## Orchestrator Execution Contract` (today `doubt-driven-development`): a builder cannot run it (its fresh reviewer is a nested delegation, Contract §2), so you apply it to the builder's result instead and name a worker skill in the brief. Still one skill, never two; no card and no fit → wrong lane.
- **A card's `Inline mapping` names this lane's artifacts, not the builder's duties.** The builder returns a normal `<handoff>` (validated by `check_handoff.py`); you write the note's `## Result` bullet and run the `{quick-root}/evidence/check.md` capture.
- **Workspace**: `{quick-root}` = `.docs/quick/{YYYY-MM-DD}-{slug}/` — refining `base-persona.md`'s `.docs/{project-name}/` model (convention #8): no epic to live under. Holds `note.md`, `handoff.md`, `evidence/check.md` (+ sidecar), `gates.jsonl`, `run-log.jsonl`.
- **No `orchestrator-state.json` — deliberate divergence from Contract §4 (convention #8).** State is an inter-pipeline handoff and this lane closes in one session. The run log is kept, unrefined: `{quick-root}/run-log.jsonl` holds the one builder delegation (plus any fix round's follow-up), and every gate passes `--ledger {quick-root}/gates.jsonl`.
- **Phase transitions are emitted, not recalled (convention #9):** before starting any phase, run `python {PLUGIN_ROOT}/pipeline-tools/scripts/tool_registry.py for --lane bgpdd-quick --phase '*'` and execute the `pipeline_driver` line it prints; do the `next_action` it prints; exit 1 means the current phase's gate has not passed — run that gate, never the next phase. (Exit 3 = closed and committed.) Contract: `pipeline_driver.py --help`.
- **Autonomous, by Contract §1's own exception.** Phase 0's note is the single user checkpoint; Phases 1–3 need no confirmation; escalations and blocked gates return to the user.
- **Game tape — deliberate divergence from the skeleton's game-tape rule (convention #8)**: **one bullet** under `## Result` in `{quick-root}/note.md`, not a `game-tape.md`: what the gate said, plus what surprised you.
- **Round bound: 1 (convention #8, deliberately tighter than `bgpdd-bugfix`'s 2).** One blocked close or red capture is one fix round — a delta-only follow-up to the same builder (Contract §1, continuation) — and a re-run; a second means the change was never quick — escalate.

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

   **A test that goes red *while* you make this change stays here** — this change's own edit misbehaving, which is what the `debugging-and-error-recovery` card is for; a defect that existed **before you started**, with a reproduction, is `/bgpdd-bugfix`. **Escalating mid-change leaves a dirty tree**: name every edit already made and either stash it or hand it over as declared changes — `/bgpdd-bugfix` closes on `--verify-tree`, which blocks undeclared ones (its Phase 0 step 1). Escalation stays one-way and upward (the router's ratchet), and **seeds** the next intake: the note's `What` drafts the bug report's observed behaviour, its `How verified` the reproduction command — drafts only; `check_bugfix_intake.py` still lints them.

3. **Run the stack detector; propose, never adopt, its defaults:** run `python {PLUGIN_ROOT}/pipeline-tools/scripts/tool_registry.py for --lane bgpdd-quick --phase 0` and execute the `detect_stack` line it prints.

   Offer its first `suggested_check_commands` entry — already quiet at the source — as the `How verified` default, or its `quiet_wrapper` verbatim if the Phase 2 capture wrapper is being written out now instead of composed by hand. The user confirms or replaces it, never you silently. `test_path_globs` goes to Phase 3's `--frozen`. A detected stack with a `skills` entry contributes **only** its `## Quick card` (§1); without a card it contributes nothing here (e.g. `{PLUGIN_ROOT}/vue3-spa-patterns/SKILL.md § Quick card`). Note: Phase 2 already runs the `How verified` command through `run_quiet.py --capture`, which satisfies `guard_action.py` rule 5 on its own — `quiet_wrapper`'s `--log` form only matters if a raw run is needed outside that capture.
4. **Write `{quick-root}/note.md`** — three labelled lines, no placeholders:
   - `- What:` the one sentence.
   - `- Where:` every file you will touch, comma-separated, **≤ 3**. Phase 3 requires it to equal what changed.
   - `- How verified:` the exact command — a test, a build, a one-line `python -c` assertion. Never "manually".
5. Pick the builder and the one methodology skill it will apply (§1).

### Phase 1: Change (one builder)
**Driver:** the driver must report `phase: 1`.
1. **Brief the builder** (Contract §1 delegation construction; background launch). The brief carries: the note's three lines verbatim; the methodology skill's path; Contract §2's three rules verbatim; and these constraints in their own words — *edit only the files the `Where` line names; never edit an existing test to make it pass (a wrong test is a defect with a reproduction, `/bgpdd-bugfix` — Phase 3's `--frozen` globs enforce this); never run git; report every file you touched in `<changed_files>`; the card's `Inline mapping` describes what the Orchestrator does with your work — you report only via `<handoff>`, never by writing `note.md` or the capture.*
2. **On return**, save the handoff to `{quick-root}/handoff.md`, run `python {PLUGIN_ROOT}/pipeline-tools/scripts/tool_registry.py for --lane bgpdd-quick --phase 1` and execute the `check_handoff` line it prints (Contract §1's validation, `--ledger {quick-root}/gates.jsonl`); then execute the `record_run` line from that same listing (Contract §4; `--log {quick-root}/run-log.jsonl --pipeline bgpdd-quick --unit {slug}`).
3. `<changed_files>` wider than the note → back to Phase 0.

### Phase 2: Prove (you, after the builder returns)
**Driver:** the driver still reports `phase: 1` — it fuses Change and Prove, because an edit leaves no artifact and this capture is the only observable either phase has.
Run the `How verified` command **through the capture wrapper**, never bare — you run it, not the builder: run `python {PLUGIN_ROOT}/pipeline-tools/scripts/tool_registry.py for --lane bgpdd-quick --phase 2` and execute the `run_quiet` line it prints.

Exit 0 required; non-zero → send the failing capture to the same builder as the one fix round (§1), then re-run the capture. Phase 3 reads the `check.md.meta.json` sidecar — a hand-written `check.md` has none, and fails closed.

### Phase 3: Close (the gate)
**Driver:** the driver must report `phase: 3`; after the gate it reports `phase: 4` at exit 3.

**When the change adds or edits a test file**, run this before the close gate: run `python {PLUGIN_ROOT}/pipeline-tools/scripts/tool_registry.py for --lane bgpdd-quick --phase 3` and execute the `check_test_authenticity` line it prints.

Principle: `test-driven-development/SKILL.md` § Rules — not restated here. Exit 0 = proceed; cite the ledger entry in the `## Result` bullet (§1). Exit 1 = the one round §1 allows — fix and re-run. Exit 2 = artifact defect. **Mechanical, not a reminder (convention #9):** `check_quick_close.py` refuses to close (`test_authenticity_gate_missing`) whenever a declared file matches `--frozen` or looks like a test file, unless the ledger holds a PASSING `check_test_authenticity.py` record exact-scoped to `{slug}` whose inputs cover it at its current hash — so skipping this step does not silently ship. `pipeline_driver.py` emits this command as the Phase 3 `next_action` whenever the note's `Where` line already names a test file, and folds a conditional reminder into the close command's message otherwise (it reads only the note's text, not the real diff) — either way, the close gate above is the actual enforcer.

Then execute the `check_quick_close` line from that same phase-3 registry listing. It carries `--require-ledger-gates check_handoff.py` — **§1's "you never do" the edit, made mechanical (convention #9)**: no PASSING Phase 1 `check_handoff.py` record over the current `handoff.md` blocks the close with `required_ledger_gate_missing`. After a fix round, save the follow-up handoff and re-run Phase 1 step 2 before this gate.

**Pass Phase 0's `test_path_globs`, one `--frozen` per glob** (`tests/**`, `**/*.spec.ts`; a value with no `*`/`?`/`[` is a directory prefix). **The gate holds no default and must not**: a guessed freeze that misses is indistinguishable from a change with no test to protect. Adding a test passes.

- **Exit 0** = every term held; the gate committed exactly the declared files. Append the `## Result` bullet (§1).
- **Exit 1** = **BLOCK**; `problem_codes` names the term. Fix and re-run once — a code fix goes to the builder as §1's one round, never into your own edit. Four terms route differently:
  - `size_bound_exceeded` is unfixable here — **no `--waiver`, deliberately tighter than `bgpdd-bugfix`'s `check_commit_gate.py --waiver` (convention #8)**: the bound *is* the lane, so an overrun means the wrong one — the message names where to escalate.
  - `frozen_path_modified` has an escape the gate's message does not name: **narrow the glob.** A rename touches its call sites and one of them is usually a test — this lane's headline case, not a defect, so do not take the message's routing to `/bgpdd-bugfix`, which has no reproduction to intake. Re-run with the narrower `--frozen` set that still covers the tests you must not edit, record which glob you narrowed and why in `## Result`, and count it as the one round.
  - `capture_command_mismatch` = the capture's recorded `argv` is not the note's `How verified` command. The capture must *be* that command's run: re-run it verbatim through `run_quiet.py --capture`, or correct the note first if the command you needed differed. Never edit the sidecar.
  - `test_authenticity_gate_missing` = a declared file matches `--frozen` or looks like a test file and the ledger holds no PASSING `check_test_authenticity.py` record exact-scoped to `{slug}` covering it at its current hash. Run the command above, then re-run this gate; it is the same one round.
- **Exit 2** = artifact or environment defect (missing flag, no Python, git unusable). Never hand-edit an artifact to pass a gate.

## Limitations
- The gate proves the declared change was checked, not that it was honest about *scale* — three files can still be an architecture change, and Phase 0's table is the only (prose) guard.
- `test_authenticity_gate_missing`'s "looks like a test file" term is a default-glob heuristic (`check_test_authenticity.py`'s own `DEFAULT_TEST_GLOBS`), not a parse of the diff; an unconventionally named test file that matches neither a `--frozen` glob nor that heuristic is invisible to this term — `--frozen`, sourced from Phase 0's `test_path_globs`, is the one input this lane actually controls, so keep it accurate.
