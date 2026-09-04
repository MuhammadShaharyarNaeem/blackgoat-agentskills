# check_bugfix_intake.py — depth

Contract spine: `../SKILL.md`, `## check_bugfix_intake.py`. This file carries the
rationale, the parsing grammar and the self-test inventory.

## What failure this converts

Before it existed, `/bgpdd-bugfix` Phase 1 read the error text, the logs, the
environment and the version **out of chat**. Three consequences, all observed:

1. **The reproduction was gone by Phase 3.** Quinn was briefed with a paraphrase
   of a command the user had typed twenty messages earlier, so her run and the
   reported bug were not provably the same thing.
2. **The surface was decided by impression.** "This looks like a UI bug" routed
   Nova at a defect whose fix landed in an API handler, and the builder returned
   it as a routing defect one delegation later.
3. **Nothing could refuse to start.** Every other lane in this plugin has an
   entry ticket (`/bgpdd-verify` demands `manual-testing.md`; `/bgpdd-build`
   demands `plan.md`). The bugfix lane's ticket was the Orchestrator's memory.

The gate makes the ticket a file, and the file machine-checkable.

## Why `- Runtime observable:` is a field of its own

`- Surface:` says *where the fix lands* (`api` / `ui` / `both`). It does not say
whether the wrong behaviour is visible at a boundary a client, person or device
reaches. Those are different axes: a null-guard bug in an API handler is
runtime-observable (a 500 on the wire); an off-by-one in a pure date helper on
the same surface is not.

Phase 4's runtime-evidence obligation depends on the second axis, not the first.
Deriving it from `- Surface:` would demand an out-of-process capture for every
logic bug in a backend file — friction with no evidence gained — and inferring
it at the gate would make the decision a judgement call at exactly the moment
convention #9 says to mechanize. So the report answers it once, in writing, and
both the route gate and the Orchestrator read the answer.

## Fenced blocks: masked, not blanked

Every other parser in this family **blanks** fenced regions, because a verdict
token inside a fence is a template. Here the rule inverts for one of the two
things a fence does:

- A **heading** or a **`- Key: value` line** inside a fence still asserts
  nothing — masked lines never match `HEADING_RE` or `FIELD_RE`. Pasting a whole
  filled-in report inside a ```` ```markdown ```` block satisfies no section.
- But fenced content **counts as section content**, because the "Exact error
  text or log excerpt" section is *supposed* to be a fenced paste. Blanking it
  would make the single most important section of an honest report read as
  empty and fail `section_empty`.

Implementation: `mask_fenced_lines()` replaces each fenced content line with
`FENCED_SENTINEL` (`\x00fenced\x00`) and each fence delimiter with `""`, so line
count is preserved and the two behaviours above fall out of one pass. This is a
labelled divergence from `../SKILL.md`'s "Fenced blocks and encoding" rule
(CLAUDE.md convention #8).

## Placeholder detection, both shapes

`is_placeholder_body()` treats a section as unfilled when **either**:

- every non-blank, non-fenced line is individually a stand-in
  (`<...>`, `TODO`, `TBD`, `FIXME`, `N/A`, `none`, `unknown`, `???`, `...`,
  `xxx`, `_TODO: pending_`), **or**
- the lines **joined** form one `<...>` span.

The second form is not redundant. The shipped template writes multi-line
placeholders (`<What actually happens, in one or two sentences. …>`), and a
line-by-line test alone read the first line as real prose — the most likely way
a skipped section reaches the gate in practice.

Field *values* use the stricter `PLACEHOLDER_VALUE_RE`, in which `n/a` and
`none` also count as non-answers: a required field answered "N/A" is the same
defect as an empty one.

## The `- Command:` value contract

The gate's error text always named the shape ``- Command: `<cmd>` ``, but for a
while it did not enforce it: `- Command: see chat` satisfied the reproduction
check while pointing at exactly the scrollback this gate exists to replace.
`usable_command()` now enforces what the message claims, in three steps:

1. **Backtick-wrapped** (`BACKTICKED_RE`). An unquoted value is prose, and
   prose cannot be re-run. The rule is the shape, not the content -- an
   unquoted *real* command fails too, deliberately, so there is no
   content-sniffing special case to argue with.
2. **Not a placeholder** -- `PLACEHOLDER_VALUE_RE`, the same set the field
   values use.
3. **Command-shaped**: >= 2 whitespace-separated tokens, **or** one token
   carrying `/`, `\`, `.` or `:` (`COMMAND_TOKENISH_RE`). So
   `` `./scripts/repro.sh` `` and `` `python -m pytest` `` pass; a bare
   `` `pytest` `` fails. That last rejection is deliberate: a one-word value is
   indistinguishable from prose, and the cost of the false negative is a few
   characters of typing.

**Documented residual hole.** `` `see chat` `` is backtick-wrapped and two
tokens, so it PASSES here. Backticks plus two words is as far as a text lint
can go without guessing at natural language. It is closed one phase later and
mechanically: `next_bugfix_route.py --red` requires the RED capture's sidecar
`argv` to equal this exact string, and no probe ever ran `see chat`. The
self-test asserts the pass here (`test_backticked_see_chat_passes_intake_by_
documented_design`) and the route gate's self-test asserts the block there
(`test_backticked_see_chat_is_closed_here`), so the pair is the contract.

**An unusable Command line beside usable steps is a WARNING, not a failure.**
The mode falls back to `steps` and the problem is named in `warnings` -- a
half-written command line is the shape an author abandons mid-edit, and the
route gate reads the mode, so it is worth surfacing without blocking a report
that is otherwise re-runnable.

## Numbered steps must be real steps

A step line counts only when the text after `1.` / `1)` is itself
non-placeholder. Counting placeholder steps let the shipped template satisfy
`reproduction_missing` — the template ships two example steps.

## The template must fail its own gate

`test_the_shipped_template_fails_the_gate` loads the real
`bgpdd-bugfix/references/bug-report-template.md` and asserts `FAIL`. A template
that passed would make "copy the template, run the gate" a complete bypass of
Phase 0. As of writing the template fails on six independent codes
(`section_placeholder` ×2, `reproduction_missing`, `surface_invalid`,
`runtime_observable_invalid`, `regression_invalid`), so the assertion is not
resting on a single fragile term. The test skips (rather than fails) if the
template is absent, so the script stays usable outside this plugin's tree.

## Self-test inventory (33 cases)

- **Happy paths (5)** — command-mode report; steps-mode report; `Surface: both`;
  `Runtime observable: no`; `Regression: yes` with a real last-known-good.
- **Section defects (4)** — missing section; angle-bracket placeholder; `TODO`;
  empty section.
- **Enum defects (2)** — the unanswered `api | ui | both`; the unanswered
  `yes | no` for runtime-observable.
- **Reproduction defects (3)** — prose only; one numbered step; placeholder
  `- Command:`.
- **The `- Command:` value contract (7)** — a real backticked command passes and
  is reported in `reproduction_command`; unquoted `see chat` fails; an unquoted
  *real* command fails too (the rule is the shape); backticked `` `see chat` ``
  passes by documented design; a single bare word (`` `pytest` ``) fails; a
  single token with a path character (`` `./scripts/repro.sh` ``) passes; a bad
  Command line beside two usable steps warns and falls back to `steps`.
- **Regression defects (2)** — `yes` with no last-known-good; `yes` with a
  placeholder one.
- **Fence behaviour (3)** — a whole report pasted in a fence satisfies nothing;
  fenced enum lines assert nothing; a fenced-only error section counts as
  content (the divergence above).
- **Encoding / structure (3)** — BOM-prefixed report parses; no headings at all
  is exit 2; missing file is exit 2; missing `--report` is exit 2.
- **Ledger (2)** — a PASS record carries the report's sha256, the milestone and
  the verbatim argv; a FAIL and an ERROR are both recorded.
- **Template (1)** — the shipped template fails.

## Scope limits

- It reads what the report *says*. It cannot tell a real reproduction command
  from a plausible one, or a true `- Runtime observable: no` from a lazy one.
  What it guarantees is that an answer exists, is legible, and is durable — and
  that `next_bugfix_route.py` can refuse to route when the file later changes.
- It does not run the reproduction. Phase 1's `run_quiet.py --capture` does, and
  `check_red_green.py` gates the result.
