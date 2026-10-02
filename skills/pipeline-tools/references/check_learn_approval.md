# check_learn_approval.py — reference

Depth for `check_learn_approval.py`. The contract of record is the script's own `--help` (`python scripts/tool_registry.py show check_learn_approval`); this page holds only the reasoning behind it.

## What failure this converts

`bgpdd-learn` was the only lane with no close gate, and its one restraint — Step 4, "never apply without explicit approval", restated in `agents/forge.md` as "never edit a SKILL.md without explicit human approval" — was prose. It bites at exactly the moment the Orchestrator most wants to proceed: the plan is written, the user is slow to answer, and Forge is one delegation away from applying it. Convention #9 says that rule becomes an artifact that has to be run. `guard_action.py` rule 7 already protected `agents/blackgoat.md`; nothing protected every other rule layer.

## Why the approval is read from the transcript, not typed

The obvious gate — `--approved-by "<quote>"` recorded to the ledger — checks only a string the Orchestrator typed. That is the self-asserted gate the task forbade: the same model that wants to proceed would author the evidence that it may. The session transcript is different in kind: the runtime writes it, and an entry's **role** is not the model's to choose. An assistant text entry is model-authored; a user-role text entry is the human's (or the runtime's); a `tool_result` is the runtime's record of what a tool returned.

So `--record` asks three things of the transcript, each of which the model cannot fake by writing text:

1. an **assistant** entry named every destination — the plan was relayed;
2. the **first human entry after it** exists — the Orchestrator halted for an answer;
3. that entry contains `--quote` — the answer was an approval, in the user's words.

Runtime-injected user-role entries (`isMeta`, `<task-notification>`, `<system-reminder>`) are skipped because they are not a human answer. A `tool_result` that echoes the words (`cat` of a file the model wrote) is not a user text entry and never counts.

**Runtime scope, stated rather than papered over.** The reader understands the Claude Code session JSONL. A runtime that keeps no transcript file cannot pass `--record` (exit 2); on that runtime the prose rule stands, and the lane should say so — a fallback flag that accepted a typed quote would quietly re-introduce the self-asserted gate everywhere.

## Why close reads the working tree, with a baseline

Forge applies edits and never commits (agents never run git), so `git status --porcelain` is the honest view of what changed. The **watched set** is the rule layers Forge's write boundary covers — `agents/*.md`, `skills/**/SKILL.md`, `CLAUDE.md`, `AGENTS.md` — not every file: `bgpdd-learn` Step 5's post-apply guard already halts on any path outside the plugin, and this gate does not restate it.

A plugin checkout often carries the author's own uncommitted work. Charging that to the learn run would make the gate fail on its first real use, so `--record` snapshots every already-dirty watched path with its content hash. At `--close` a path unchanged since that baseline is `preexisting` and passes; the same path edited further during the apply is `unapproved_change`.

`agents/blackgoat.md` is refused by `--close` whatever the plan says — convention #7, and `agents/forge.md`'s carve-out: no approval unlocks it.

## How it pairs with guard rule 9

The script decides after the fact; `guard_action.py` rule 9 (`learn_applies_only_what_was_approved`) refuses before it. While `.docs/learn/*/forge-handoff.md` is fresh and that root's ledger holds no `--close` PASS, a write to a watched path is denied unless the latest `--record` PASS approved it. The guard reads only the ledger record; the transcript verification behind it is this script's. A `--close` PASS disarms the rule.

## Layout this assumes

`.docs/learn/{YYYY-MM-DD}-{learn-slug}/` — `forge-handoff.md` (Forge's Step 3 handoff, saved verbatim; its `Destination:` lines are the grammar `--record` parses) and `gates.jsonl`. `bgpdd-learn` itself keeps no game tape (its own convention #8 divergence); this root holds only the plan and the ledger.
