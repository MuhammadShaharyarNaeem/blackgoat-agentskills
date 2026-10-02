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
| mason, max | `<changed_files>` **and** `<changed_symbols>` | Builder override |
| nova | `<changed_files>`, `<changed_symbols>` **and** `<artifact>` | Hybrid write boundary |
| dep, quinn | `<changed_files>` **and** `<artifact>` | Hybrid write boundary |
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

Without `--since` the gate never asks git anything: it cannot know what window the handoff covers, and a clean tree after a legitimate commit would otherwise read as "the agent changed nothing". With `--since <ref>` it takes `git diff --name-only -z <ref>` (ref..working-tree, so committed-since *and* uncommitted edits both appear) plus `git ls-files -z --others --exclude-standard` (a brand-new source file is the commonest thing a builder names and diff never sees it), and requires `<changed_files>` to be a subset. `-z` is load-bearing: without it git C-quotes a non-ASCII or control-char path (`core.quotePath`), so a truthful `src/été.py` never matched and was refused as `changed_files_not_in_diff`. **With more than one `--repo`, each path is diffed in the specific repo it resolved to, not the first one listed** — a milestone that touches two repos needs `<ref>` to be resolvable in both (e.g. a same-named tag placed in each at milestone start). A ref git cannot resolve in the repo a path resolved to is exit 2, never a pass — an unperformable check is not a satisfied one.

## The honesty rules, and why they are narrow

Two mechanical rules, both chosen to have almost no false-positive surface:

1. **A marker beside an unqualified verdict token, inside one element.** `NOT VERIFIED` or `BLOCKED` co-occurring with a standalone upper-case `PASS`/`PASSED`/`GREEN`. Lower-case reporting — `1 passed, 0 failed` — is explicitly allowed, because base-persona's "Name every substitution" *requires* labelling a weaker observation beside its result, and a partial result reported honestly must stay expressible. The pattern that fails is the one where the same breath both withholds and asserts.
2. **`<status>BLOCKED</status>` with `<blockers>None</blockers>`.** A blocked state that names no blocker is either a copy-paste of the template or a status nobody meant.

`<status>` itself is exempt from rule 1: `BLOCKED` there is the honest declaration, not a marker buried in prose.

## Codes

`handoff_missing`, `element_missing`, `path_missing`, `changed_files_not_in_diff`, `status_invalid`, `consumers_grammar`, `honesty_contradiction`.

`path_missing` covers both a path that does not exist under any searched root and one that escapes all of them (`../x`, another drive). The roots searched are every `--repo` for `<changed_files>`, plus every `--docs-root` — and, for a *relative* path, each `--docs-root`'s own parent directory and the cwd — for `<artifact>`/`<changed_skills>` only. A report path under the shared docs tree is not a code change, so `<changed_files>` never gets the docs-root or its fallbacks. Both failure shapes are the same defect from the consumer's side: the Orchestrator cannot open what the handoff named.

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

## Multi-`--repo` and `--docs-root` (Unreleased)

A milestone that spans more than one repo (a shared `.docs/` tree above
several checkouts, or two repos touched by one delegation) used to have no
honest way to pass this gate: `--repo` took exactly one directory, so a
`<changed_files>` path resolving under the second repo failed `path_missing`
no matter how real the file was. `--repo` is now repeatable, and a path is
accepted the moment it resolves under **any** listed repo; when `--since` is
also given, each path is diffed against the repo it actually resolved to
(`git diff --name-only <ref>` run there), not against the first `--repo`
listed — a two-repo milestone needs `<ref>` resolvable in both.

`--docs-root` is new and repeatable, and is for `<artifact>`/`<changed_skills>`
only — never `<changed_files>`, which is a code change and stays scoped to
`--repo`. It defaults to the nearest ancestor of `--handoff` named `.docs`, so
the common shape (a handoff and its report both under the same `.docs/` tree)
needs no flag at all. A relative `<artifact>`/`<changed_skills>` path also
falls back to each `--docs-root`'s own parent directory and the cwd.

**2026-09-14 fix round:** a red-team run against the real Gorelo shape found
that `.docs/bugfix/x/review-report.md` — the form every real handoff actually
writes, relative to the workspace root *above* `.docs`, not to `.docs` itself
— still failed `path_missing` even with the `.docs`-ancestor default in place.
The docs-root-parent/cwd fallback above was added to close that gap.
`<changed_files>` is untouched by it.

`--self-test` now runs **57** cases: the fifty above, plus multi-`--repo`/
`--docs-root` cases — a path resolving under the second `--repo`, `--since`
diffed against the repo it resolved to rather than the first one listed, the
`.docs`-ancestor default, and the relative-path parent/cwd fallback for
`<artifact>`/`<changed_skills>` only.

## `blocked_on:` grammar (Unreleased)

Measured on epic slide-s5: Quinn was delegated four times on the same milestone and returned `PARTIAL` every time with the same environment wall — no admin shell, no installed service, no dev token — only the human could clear, and about 1.2M tokens were spent re-discovering that one fact across the four rounds because nothing in the handoff was machine-readable enough to stop the Orchestrator from trying again. `<blockers>` free text said the same thing four different ways.

On a `PARTIAL`/`BLOCKED` `<status>`, `<blockers>` must now carry at least one line matching `blocked_on: <category> — <one-line reason>`, where `<category>` is one of `environment`, `credentials`, `dependency`, `spec`, or `defect`. A line naming a category outside the five, or a `PARTIAL`/`BLOCKED` handoff with no `blocked_on:` line at all, is `blockers_uncategorised`. `COMPLETE` is exempt — the grammar exists to classify a blocker, and a complete handoff has none. An entirely absent `<blockers>` element stays `element_missing`, never additionally `blockers_uncategorised` — one finding per actual gap, not two for the same missing thing.

This is the grammar `check_redelegation.py` reads to decide whether re-delegating the same agent on the same unit would just re-discover the same wall: `environment`/`credentials` halt outright, `dependency` halts unless explicitly waived, and `spec`/`defect` never halt on their own since those are squarely the agent's to keep working on.

Self-test count: 57 → 67 — ten `blocked_on:` grammar cases: every known category, an unknown one, a missing line, the `COMPLETE` exemption, a bulleted/backtick-wrapped line, and the absent-`<blockers>`-is-only-`element_missing` non-duplication case.

## `<changed_symbols>` (Unreleased)

`<changed_files>` says which files a builder touched; it says nothing about what inside them changed, so a builder could name a function it never wrote and nothing mechanical would disagree. `<changed_symbols>` turns that claim into one checked against the diff.

### The contract

- **Who carries it.** Mason, Max and Nova must (`element_missing` otherwise). Every other persona may carry it without a warning.
- **Entry grammar.** One `path::Name` per non-blank line; a list marker and backticks are stripped, and the line splits on its last `::`.
  - `path` names exactly one file, read literally. Every git call on it runs with `--literal-pathspecs`, so `pages/users/[id].vue` is that file, and a glob-looking `src/*.py` or a leading-colon `:/` names only a file literally so called; with none, the claim is refused. A path that is a directory, or whose diff covers any file other than itself (a directory since deleted, even one that held a single file), is `changed_symbols_grammar`.
  - `Name` is the bare identifier as source spells it. A `.` qualifier (`Store.load`) is `changed_symbols_grammar`: source rarely contains the dotted form, so every such honest claim would be refused. A hyphen stays legal, for PowerShell's `Verb-Noun`.
  - `Name` is the innermost symbol edited: the method, not its enclosing class, unless the class declaration line itself changed. With method-scoped drivers an unchanged class line sits outside the hunk, so the class claim is refused.
- **Files with no symbol.** A changed file with no code symbol (a doc, config or data file) is listed in `<changed_files>` only and omitted from `<changed_symbols>`. `path::none: ...` is not an entry and is `changed_symbols_grammar`.
- **The `none:` form.** The only non-entry form is exactly one `none: <reason>` line with a non-empty reason, for a handoff with no code symbol at all. It is recorded in the ledger as `changed_symbols_none_reason` and never diff-checked.
- **Under `--since`.** Each `Name` must appear as a whole word on an added, removed or context line inside a hunk of `git -c core.attributesFile=<temp> diff --no-color --no-ext-diff -M -W <ref> -- <path>`, never on the `---`/`+++` file headers, and on the `@@` header text only when it names an enclosing scope (below). Whole word, not substring, so `Get` cannot ride on `GetUser`.
- **No cross-check with `<changed_files>`.** `<changed_symbols>` is not compared with `<changed_files>`, so a file left out of `<changed_symbols>` is never flagged.
- **Problem codes.** `changed_symbols_grammar`: a line that is not `path::Name`, a qualified `Name`, a directory path (present or deleted), an empty `none:` reason, or `none:` mixed with entries. `symbol_not_in_diff`: a `Name` the diff does not show; the detail is the entry as written.

### Why the diff rule is shaped this way

A stricter rule, "+/- lines and `@@` headers only", rejected true claims about a change inside a multi-line constant whose name line was unchanged. Counting context lines inside the `-W` hunk widens it deliberately (convention #8): a name the diff's function context never shows is an invented or untouched claim, so the rule catches invention, not precise attribution. Two refinements of that widened rule, also deliberate (convention #8, refining this section's own rule):
- **No `@@` header text.** Under `-W`, a hunk starts at the enclosing declaration, so git's header names the declaration *before* it, an untouched neighbour. The enclosing declaration is already a body line. One exception, a deliberate refinement of this header rule (convention #8): the header counts only while its scope is still open at the hunk's first changed line. Every non-blank line from the header's own line down to that first `+`/`-` line must be indented deeper than the header line, where deeper means the line's indent starts with the header's indent verbatim and is longer. A tab/space mix that differs from the header's is never deeper, the conservative reading, so no tab width is guessed. A change after a nested `def` starts the hunk at the nested def, so the outer function appears only in the header, and it counts. A sibling's scope closes at the next declaration's own line, so the sibling does not count, even when `-W`'s three leading context lines start the hunk in its tail and git's header names it. Git prints the header without its indentation, so the gate finds the line in the preimage blob (`--full-index` supplies its id): the nearest line above the hunk whose text starts with the header. A header line that cannot be found does not count. Preimage and diff lines are numbered as git numbers them, split on `\n` only. Known false refusals, all failing closed: a column-0 comment, or column-0 lines of a multi-line string, inside the enclosing function closes its scope; and with braces on their own line (C# Allman style) the enclosing method or class never gets header credit. Claim the innermost changed symbol instead.
- **Built-in language drivers.** Git's default funcname heuristic matches only unindented lines, so `-W` widened an indented member (a C# method inside a class) to the whole file. A temporary `core.attributesFile` maps common extensions to drivers git ships (`csharp`, `python`, `java`, `golang`, `rust`, `ruby`, `php`, `kotlin`, `cpp`, `bash`, `perl`, `css`, `html`, `markdown`). The repository's own `.gitattributes` still wins. Git ships no JavaScript/TypeScript driver, so those files keep the default heuristic, and their residual is the enclosing unindented block.

`--no-color --no-ext-diff --no-textconv` keep the caller's git config (`color.diff=always`, `diff.external`) and a repository's `diff.<driver>.textconv` from reshaping the output. An untracked file that cannot be read is exit 2, never a finding, and so is a failure to write the temporary attributes file. A failure to delete that file is ignored: a leaked temp file is harmless, but a cleanup error must never mask the verdict.

Why no character ban on `path`: an earlier rule refused `*`, `?`, `[` and a leading `:`, which also refused real files such as Nuxt's `pages/users/[id].vue`. `--literal-pathspecs` already stops a path from widening the diff, so the ban only rejected valid input. A literal pathspec still prefix-matches every file under a directory, which is why an existing directory is refused before diffing and a deleted one when its diff names any file other than the path itself.

**The untracked-file rule.** Builders never commit, so a symbol in a file they created is untracked and `git diff` shows nothing for it. An untracked file at `path` therefore counts as all-added lines, the same "diff plus untracked" rule `<changed_files>` already uses. A deleted file is still diffed (its removed lines count), and a renamed file is cited by its new path.

Self-test count: 67 → 98 (the current total, which includes two later non-ASCII `--since` cases: a changed and an untracked non-ASCII path pass; an unchanged one is still refused).

## `<changed_files>none:` for a capture-only run (2026-09-30)

In `/bgpdd-bugfix`, Quinn's Phase 1 RED and Phase 4 GREEN change no repo file: they write only a capture and a report under the gitignored `.docs/` tree, and the lane passes `--since` on every return. Both honest spellings failed. `<changed_files>None</changed_files>` was read as a path (`path_missing`), and naming the capture was `changed_files_not_in_diff`, since git never lists an ignored file. The Orchestrator had to run the gate without `--since`, so the gate stopped checking anything.

- **Grammar.** The element's entire content is one line, `none: <non-empty reason>`, matched case-insensitively after the list-marker and backtick stripping `<changed_symbols>` uses. It means "this handoff changed no repo file"; the real output is in `<artifact>`, which stays required and is checked exactly as before (existence, scaffolding sweep).
- **Quinn only.** This is deliberately tighter than `<changed_symbols>`' `none:`, which any persona may write (convention #8). Quinn is the one persona whose runs legitimately produce only `.docs/` artifacts; every other persona's run exists to change files, so `none:` in its `<changed_files>` is a finding.
- **Under `--since`.** The form claims the empty set, so the subset check passes trivially. It passes without `--since` too. The gate never checked for unclaimed edits, and this change does not add that check.
- **Findings.** `changed_files_grammar`: `none:` from a persona other than Quinn, an empty reason, or `none:` mixed with paths (on its own line, or after a comma). The legacy bare `None` stays `path_missing`; `none: <reason>` is the only spelling.
- **Ledger and JSON.** The reason is recorded as `changed_files_none_reason`, following `changed_symbols_none_reason`. The JSON report always carries the key (`null` unless the form passed), and the ledger record carries it only when set.

Self-test count: 99 → 104. The new cases: Quinn's `none:` passes with and without `--since`, and its reason reaches the ledger; every other persona is refused; an empty reason fails; `none:` mixed with a path fails; bare `None` stays `path_missing`.

## `--transcript`: the handoff came back from a delegation (Unreleased)

Orchestrator Contract §1's "you MUST NOT roleplay a delegated agent's work yourself" was prose, and every artifact this gate reads could be authored by the Orchestrator: a handoff file, a report, and even `record_run.py`'s delegation record (its `--model` is typed by the same hand). The session transcript is the one artifact whose **roles** the runtime assigns, so `--transcript <session.jsonl>` checks the handoff block (all whitespace ignored — a runtime may re-wrap it) against the runtime's record:

- **accepted** — the `tool_result` of a `Task`/`Agent`/`SendMessage` call (a foreground delegation; `delegation_source.via = delegation_result`, with the call's `subagent_type`), or a user-role text entry: a background agent's `<task-notification>` (mapped back to its `Agent` call through `<tool-use-id>`, `via = delegation_notification`) or a human paste (`via = user_message`);
- **refused** — `handoff_not_delegated` when the block appears only in assistant text (the model wrote it), only in another tool's result (`cat handoff.md` returns what the model wrote), or only in a sidechain.

Optional and backward compatible: without the flag nothing changes. The persona is reported (`subagent_type`), not enforced — a delegation to the wrong agent is still a delegation, and the roleplay this converts is the absence of one. Runtime scope is the Claude Code JSONL shape; a runtime with no transcript file simply does not pass the flag.

Self-test count: 104 → 108 — a foreground delegation result passes (re-wrapped whitespace included), a background notification passes and maps to its call, assistant text / a `cat` of the file / a sidechain each fail `handoff_not_delegated`, and an unreadable transcript is exit 2.
