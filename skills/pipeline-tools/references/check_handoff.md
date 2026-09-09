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

`python scripts/check_handoff.py --self-test` runs 49 in-process cases against a temp tree and, where `--since` is exercised, a real temp git repo (skipped rather than faked when git is absent). Beyond the four override shapes passing and failing correctly: a fenced handoff not counting, a real handoff surviving beside a fenced example, a non-existent path, a path escaping the repo, a whitespace-only element, an unclosed `<handoff>`, `<changed_files>` naming an untouched file under `--since`, a subset passing, an unresolvable ref erroring, each status value, consumers grammar both ways, `--fix-round` both ways, both honesty rules, lower-case `passed` beside `NOT VERIFIED` still passing, an unknown persona erroring, an unrecognized element warning without failing, the ledger recording all three exit paths, and the persona table matching `agents/` on disk.

## `--advisory`, and what `<status>` is for (2.6.1)

The 2026-09-07 audit's Metric-1 finding: two sanctioned pipeline steps ask an
agent for a RECOMMENDATION and no artifact — Forge's propose handoff
(`bgpdd-learn`, which proposes edits and waits for approval, so nothing is
written yet) and Aria's Mode 2 blast-radius advisory (`bgpdd-build`). Both
failed this gate exit 1 in every tag form tried, so the Orchestrator's
mandatory validation (`orchestrator-contract.md` §…) was contradicted by the
pipelines twice per epic. A gate the contract requires and the pipeline
guarantees will fail is a gate that gets skipped.

`--advisory` makes `<artifact>` and `<changed_skills>` optional for that one
call. Everything else holds: `<status>`, `<blockers>`, the path checks on
whatever IS declared, the status enum, the `path::symbol` grammar and both
honesty rules. `<changed_files>` is deliberately NOT waivable — an agent that
wrote code has an artifact whether or not the brief asked for one, so the
builder personas are unaffected by the flag.

Two design choices worth stating:

- **It is the caller's flag, not the agent's.** It declares something about
  the BRIEF that was written, and the brief's author is the Orchestrator. An
  agent that could set it could waive its own artifact.
- **The ledger records `advisory: true`**, merged into the record before
  `prev`/`self` are computed, so the chain covers it. Waiving an artifact is
  then a written, attributable act rather than a gate that quietly did less.
  A non-advisory run carries no `advisory` key at all, so the field's presence
  is itself the signal.

**`<status>` is the DELIVERY state.** `COMPLETE`/`PARTIAL`/`BLOCKED` answers
"did the agent finish what it was briefed for". Three spine lines spoke of the
handoff "returning PASS/BLOCKED", which is a verification VERDICT — a
different claim, about a different subject, and one that belongs in the body
beside the durable report it judges. `STATUSES` is unchanged; the
`status_invalid` message now says where the verdict goes instead of only
listing the three tokens. `BLOCKED` is the one token both vocabularies share,
and it means the same thing in each.

**`--since` is optional here and required by the pipelines.** It is the only
term in this gate that git can contradict: without it `<changed_files>` need
merely exist, with it a file the agent never touched is rejected. Leaving the
choice to the gated party is what the audit flagged; the CLI keeps the flag
optional (a handoff can legitimately be checked outside a repo), and the
pipeline steps pass it — with `--ledger` — every time.

## `artifact_scaffolding_left` — the sweep before COMPLETE (2.6.2)

`base-persona.md` § Incremental Persistence closes with the rule this code
enforces: *"Sweep the scaffolding before you return COMPLETE. The skeleton,
its markers, and any note explaining that the markers exist are working
apparatus for you, not content for the reader. Before handoff, read the
artifact's own text and remove every trace of them. A COMPLETE artifact that
still instructs its reader about its own construction reads as unfinished to
everyone downstream, whatever its substance."*

That is convention #9's shape exactly. The sweep is asked for at the one
moment it feels like bookkeeping — the substance is written, the sections are
filled, the agent is composing its handoff — and it is the last thing between
the agent and returning. So it stops being prose and becomes a read.

### What is scanned

On `<status>COMPLETE</status>` only, every path in `<artifact>` or
`<changed_skills>` that **exists and is a text file** is read and swept line
by line. Five markers, tested in this order, at most one reported per line
(the finding is "this line is apparatus", not a census of patterns):

| Marker | What it matches |
|---|---|
| `skeleton_marker` | base-persona's placeholder marker — an underscore joined to `TODO`, as in the template's `_ TODO : pending _` (spaced throughout this page so the page is not itself a hit) |
| `todo_pending` | the same idea in prose: `TODO`, a colon, `pending` |
| `todo_comment` | an HTML/markdown comment opening on `TODO` |
| `skeleton_comment` | an HTML/markdown comment opening on `skeleton` |
| `scaffolding_note` | a line that EXPLAINS the markers — a `Note:`/`NB:` line mentioning the marker, `placeholder` or `skeleton` |

`scaffolding_note` is the one base-persona names third and the one a sweep
most often misses, because it reads like prose rather than like apparatus.

The `skeleton_marker` word boundary has a documented limit: `MY_TODOS` is
correctly not a hit, and neither is a bare italic marker whose trailing
character is an underscore, since both sides are then word characters. The
template's own form carries a colon and matches.

Inline code spans (single backticks on one line) are stripped before the
markers are matched. A marker in backticks is documentation — it is how
`base-persona.md` states the convention and how this family cites it — while
a skeleton always writes the placeholder bare. Fenced blocks are NOT
stripped (next section): a fence in a delivered artifact is content.

### Three deliberate bounds

- **`PARTIAL` and `BLOCKED` are exempt.** § Incremental Persistence *tells*
  an agent to hand unfinished work back with its markers in place. The rule
  is about the word COMPLETE, not about markers, and a gate that punished an
  honest `PARTIAL` would push agents toward the dishonest `COMPLETE`.
- **`<changed_files>` is not swept.** Source code legitimately carries a
  `TODO`, and base-persona's rule is about the artifact a *reader* reads.
- **A marker inside a fenced block IS a hit** — the exact opposite of how the
  handoff text is read a few sections up, and the asymmetry is the point. A
  fenced `<handoff>` is an *illustration*, and reading it as the report would
  let an example satisfy the gate. A fence inside a *delivered* artifact is
  still ink on the page: the reader who scrolls past it sees an unfinished
  document, which is the harm the rule names.

A binary artifact (a NUL byte anywhere in the file) or one that cannot be read
is skipped with a warning and never fails: "the gate could not look" is not
"the agent left a marker".

### `--allow-scaffolding "<reason>"`

The escape for the page that must legitimately *quote* the marker — this
reference doc, `../SKILL.md`, a lesson that names it, `base-persona.md`
itself. It waives `artifact_scaffolding_left` and nothing else, is computed
**after** the findings so the ledger records *what* was waived, requires a
non-empty reason (blank is exit 2, matching `--allow-drift` and
`--allow-tier-inversion`), and writes `allow_scaffolding_reason` plus the
waived `{path, line, marker}` entries into the chained ledger record. A clean
run carries neither key, so the field's presence is itself the signal.

It is the caller's flag for the same reason `--advisory` is: an agent that
could set it could excuse its own unswept skeleton.

### Self-test

`--self-test` now runs **50** cases (the fiftieth: a marker quoted in inline code is documentation, a bare one on the same page still fires). The thirteen added here: a clean COMPLETE
artifact passing and reporting what it scanned; each of the five marker shapes
hitting with the right `marker` name; the finding naming `file:line`; a marker
inside a fence still hitting; `PARTIAL` and `BLOCKED` keeping their markers; a
`<changed_files>` `TODO` going unswept; `<changed_skills>` being swept; an
`--advisory` handoff with no artifact unaffected; a binary artifact skipped
with a warning; multi-hit line numbering; and the `--allow-scaffolding` round
trip — refused, blank-reason exit 2, waived with the reason and the waived
entries inside the ledger chain, and a clean run recording neither key.
