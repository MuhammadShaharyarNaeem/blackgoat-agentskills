# check_handoff.py — reference

Depth for the `check_handoff.py` section of `../SKILL.md`.

## Why the interface nobody parsed is the one worth parsing

`base-persona.md` § Output Format has always defined the `<handoff>` block, and six personas refine its required elements in an inline "Base Persona Override". Every downstream decision the Orchestrator makes — forward the fix to Quinn, close the milestone, run the commit gate — reads that block. Nothing ever parsed it. A handoff missing `<changed_files>`, naming a path the agent never wrote, or claiming `PASS` beside a `NOT VERIFIED` marker rendered exactly like a good one, and the only reader was a party already inclined to accept it.

That is the CLAUDE.md convention #9 shape precisely: the restraint lands at the moment the Orchestrator most wants to proceed. So the check is a command with an exit code.

## Where the required-element table lives, and why not in the persona files

The table is a constant in the script. A gate that re-derived it by parsing `agents/*.md` at runtime would be a gate whose verdict moves whenever a persona is reworded — the failure mode of every "self-configuring" lint. Instead the table is data the change that edits a persona must edit too, and `test_every_persona_file_has_a_table_row` fails the moment `agents/` gains or loses a persona so the drift cannot pass silently.

`agents/blackgoat.md` is deliberately absent, and `--persona blackgoat` is a usage error (exit 2). It is the human author's psychological profile, not a delegatable persona — CLAUDE.md convention #7.

| Persona | Required beyond `<status>` / `<blockers>` | Source |
|---|---|---|
| mason, max | `<changed_files>` | Builder override |
| dep, quinn, nova | `<changed_files>` **and** `<artifact>` | Hybrid write boundary |
| forge | `<changed_skills>` | Meta override |
| alex, aria, cipher, echo, iris, luna, rex, scout, vera | `<artifact>` | base-persona, unchanged |

`<consumers>` is standing-but-optional for mason and nova only ("when the brief asks for it" — the `/bgpdd-bugfix` Phase 3 brief does). `--require consumers` promotes it for any persona, and warns when the persona named carries no standing consumers contract, because that is more often a caller slip than a real bar.

`<fix_verification>` is required under `--fix-round`, per base-persona: "'Already complete' exempts nothing." The gate deliberately accepts `NOT VERIFIED — <what blocked you>` as a value; base-persona says a missing element is the defect, not an honest negative.

## The status enum

`COMPLETE`, `PARTIAL`, `BLOCKED`, and nothing else. `COMPLETE` is base-persona's template value; `PARTIAL` is mandated by § Incremental Persistence ("report unfinished sections and return `PARTIAL`, never `COMPLETE`"); `BLOCKED` by § Evidence Integrity ("An honest BLOCKED costs one round-trip"). A repo-wide grep finds no other value emitted anywhere in the plugin, so nothing else passes. A lower-case spelling is read as its upper-case form and warned, not failed — the enum is about which state was declared, not about shouting.

## Fenced copies, and the adversarial case they cover

A SKILL.md, a persona file and an agent's own prose all routinely *show* a handoff template inside a fence. Reading an illustration as the report is the adversarial case: a genuine `BLOCKED` handoff with a fenced `COMPLETE` example pasted beneath it. So fenced blocks are blanked (line count preserved, so warnings still cite real line numbers) before anything is scanned, and `test_fenced_handoff_is_not_a_handoff` proves a fence-only file reports `handoff_missing` rather than passing.

Where several unfenced blocks survive, the **last** is validated and a warning says so: the final output is what the Orchestrator acts on. This is a deliberate softening of "one block or nothing" — a hard failure there would punish an agent for quoting its own earlier handoff in a fix round, which is the round most likely to do it.

## `--since` and the diff subset

Without `--since` the gate never asks git anything: it cannot know what window the handoff covers, and a clean tree after a legitimate commit would otherwise read as "the agent changed nothing". With `--since <ref>` it takes `git diff --name-only <ref>` (ref..working-tree, so committed-since *and* uncommitted edits both appear) plus `git ls-files --others --exclude-standard` (a brand-new source file is the commonest thing a builder names and diff never sees it), and requires `<changed_files>` to be a subset. A ref git cannot resolve is exit 2, never a pass — an unperformable check is not a satisfied one.

## The honesty rules, and why they are narrow

Two mechanical rules, both chosen to have almost no false-positive surface:

1. **A marker beside an unqualified verdict token, inside one element.** `NOT VERIFIED` or `BLOCKED` co-occurring with a standalone upper-case `PASS`/`PASSED`/`GREEN`. Lower-case reporting — `1 passed, 0 failed` — is explicitly allowed, because base-persona's "Name every substitution" *requires* labelling a weaker observation beside its result, and a partial result reported honestly must stay expressible. The pattern that fails is the one where the same breath both withholds and asserts.
2. **`<status>BLOCKED</status>` with `<blockers>None</blockers>`.** A blocked state that names no blocker is either a copy-paste of the template or a status nobody meant.

`<status>` itself is exempt from rule 1: `BLOCKED` there is the honest declaration, not a marker buried in prose.

## Codes

`handoff_missing`, `element_missing`, `path_missing`, `changed_files_not_in_diff`, `status_invalid`, `consumers_grammar`, `honesty_contradiction`.

`path_missing` covers both a path that does not exist under `--repo` and one that escapes it (`../x`, another drive). Both are the same defect from the consumer's side: the Orchestrator cannot open what the handoff named.

## Self-test

`python scripts/check_handoff.py --self-test` runs 26 in-process cases against a temp tree and, where `--since` is exercised, a real temp git repo (skipped rather than faked when git is absent). Beyond the four override shapes passing and failing correctly: a fenced handoff not counting, a real handoff surviving beside a fenced example, a non-existent path, a path escaping the repo, a whitespace-only element, an unclosed `<handoff>`, `<changed_files>` naming an untouched file under `--since`, a subset passing, an unresolvable ref erroring, each status value, consumers grammar both ways, `--fix-round` both ways, both honesty rules, lower-case `passed` beside `NOT VERIFIED` still passing, an unknown persona erroring, an unrecognized element warning without failing, the ledger recording all three exit paths, and the persona table matching `agents/` on disk.
