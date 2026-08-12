# Case: alex-domain-tags

## Purpose

`planning-and-task-breakdown/SKILL.md`'s Definition of Done requires "every task
carries exactly one domain tag (`[UI]` or `[API]`), and every milestone is
domain-homogeneous" — this is what makes `next_milestone.py`'s `[UI]`/`[API]`
routing (and the `MIXED` planning-defect exit) meaningful at all. Alex's own
persona (`agents/alex.md`) delegates all checklist formatting and tagging to that
methodology file rather than restating the rule itself ("You MUST rely entirely on
the `planning-and-task-breakdown` methodology for how to format the checklist and
tag the tasks. Do not invent your own formatting rules."). This case tests whether
that delegation actually holds under a realistic, ordinary planning brief — one
that never mentions domain tags, homogeneity, or milestone shape at all. If Alex
only produces correctly-tagged, domain-homogeneous milestones when a prompt spells
that out for him, the methodology file isn't actually load-bearing — it's decorative
until someone remembers to repeat its rules in the delegation, which is exactly the
kind of drift `bgpdd-plan`/`bgpdd-lite` cannot catch by inspection at scale.

**The omission in the prompt is the test, not an oversight.** Read the `## Command`
block below: it tells Alex what to read, to follow his Methodology Dependencies, and
where to save the plan — nothing about tags, domain, or milestone shape. That's
deliberate.

## Frozen Input

- Fixture dir: `fixture/requirements.md` — the same "Supplier Contacts" mini-feature
  spec used to smoke-test the `pipeline-tools/mechanical-pipeline` eval's adjacent
  concerns: FR-1..FR-4 Must-Have (2 backend endpoints, a table view, an autocomplete
  search — a natural API/UI split), FR-5 Should-Have, NFR-1/NFR-2 Must-Have.
- Copies to: `.docs/supplier-contacts/`

## Command

```powershell
$promptText = @'
Act as Alex per `agents/alex.md`.

Read `.docs/supplier-contacts/requirements.md`. It's a small mini-feature for an
existing ERP: a supplier record gains a "Contacts" capability, spanning both new
backend endpoints and a new UI panel on the supplier detail view. There is no
separate architecture document for this one — treat the requirements file itself as
your only input.

Before you do anything else, read your Methodology Dependencies exactly as your
persona file lists them, and follow `planning-and-task-breakdown` for how the
checklist itself must be built, formatted, and tagged. Do not invent your own
structure or conventions where that methodology already gives you one.

Produce `.docs/supplier-contacts/plan.md`: an ordered, dependency-aware
implementation checklist that takes this feature from the current state to done.
Break it into whatever tasks and milestones the work actually requires — you decide
the grouping and sequencing based on the dependencies you find, not a shape I'm
handing you.

Save the plan to that path when you're done.
'@
claude -p $promptText --permission-mode acceptEdits
```

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)

1. `.docs/supplier-contacts/requirements.md` is present (fixture sanity check).
2. `.docs/supplier-contacts/plan.md` was produced.
3. Every `## Task [N]:` block in the plan contains **exactly one** of `[UI]` /
   `[API]` — never both, never neither.
4. Every `## Milestone <n>` block is domain-homogeneous — no milestone's task set
   mixes `[UI]` and `[API]` tags.
5. `python skills/pipeline-tools/scripts/next_milestone.py --plan <plan.md>` exits
   `0`. Exit `1` means the tool's own `MIXED`-domain detection fired on the first
   pending milestone — the real gate `bgpdd-build` would hit on this exact plan.
   **Deliberately not the same check as #4**: this only ever inspects the first
   pending milestone (the one actually routed to a builder); #4 covers every
   milestone in the plan, including ones the gate hasn't reached yet.
6. `python skills/pipeline-tools/scripts/check_coverage.py --requirements
   <copied requirements.md> --plan <plan.md>` exits `0` — every Must-Have FR/NFR
   is covered and no lint fires. This is the same coverage gate
   `alex-plan-coverage` checks; it's included here because a plan that fails
   coverage isn't a meaningful pass on domain tagging either, and it costs nothing
   extra to shell out to the tool that already exists.

`grade.ps1` exits `0` only if all six pass; otherwise it exits `1` and prints which
criterion failed.

## Runs / Threshold

`runs=5`, pass threshold **4/5**, per the suite's statistical-evals doctrine
(`evals/README.md`) — this is an ordinary `claude -p` persona invocation and inherits
normal LLM output variance.

## Harness compatibility (fixed 2026-08-09)

This case previously kept its fixture as a flat `fixture-requirements.md` at the
case root and its prompt in a standalone `prompt.md`, with the `## Command` block
left illustrative and a `# NOTE:` explaining it wasn't yet wired for automatic
execution. That broke on two counts against `run-evals.ps1`'s actual harness
contract: `Get-ContractCases` hardcodes every case's `FixtureDir` to `fixture/`
(not the case root), and `Get-ContractCaseCommand`/`Invoke-ContractRun` execute
whatever text sits in the `## Command` fenced block via `Invoke-Expression` — they
never read `prompt.md` and never expose the case directory to that block.

Both are now resolved without touching `run-evals.ps1`:

- The fixture moved to `fixture/requirements.md`, and `Copies to:` now names the
  directory `.docs/supplier-contacts/` (matching every other contract case's
  convention), not a full file path.
- The prompt is no longer a separate `prompt.md`. It's inlined directly in the
  `## Command` fenced block as a PowerShell here-string (`@'...'@`) assigned to
  `$promptText`, then passed to `claude -p $promptText`. A here-string is not a
  single quoted `-p` argument: `Invoke-Expression` runs the whole fenced block as a
  short script, so the full, unabridged, multi-paragraph brief survives intact —
  the original divergence's fear of "collapsing it into a single quoted `-p`
  argument would mangle formatting or tempt a rewrite that reintroduces the exact
  hints (tags, shape) this case exists to keep out" no longer applies, because
  nothing gets collapsed into one line. The prompt text itself is byte-for-byte
  the same brief the case has always used — still silent on tags, domain, and
  milestone shape; that omission remains the test.

This case is now runnable unattended via `run-evals.ps1 -Confirm -Case
alex-domain-tags` at `runs=5`, exactly like every other contract case. It has not
been executed as part of this fix (it spends real tokens); grade logic in
`grade.ps1` is unchanged.

## Future (not implemented)

Whether the *sequencing and dependency structure* Alex chooses (not just tags and
coverage) reflects good task breakdown — e.g., whether the API endpoints
genuinely precede the UI work that consumes them — is a judgment call this case
does not attempt to check. `alex-plan-coverage`'s "Future" section notes the same
scope limit for sequencing quality generally; this case adds nothing new on that
front.
