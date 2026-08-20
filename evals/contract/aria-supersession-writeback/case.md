# Case: aria-supersession-writeback

## Purpose
`skills/blackgoat-research/SKILL.md` step 6 makes the routing test semantic rather than
editorial: *does this decision make any sentence of an existing FR/NFR false?* If yes, the
decision is **NOT complete until** it carries BOTH a row in the
`## Divergence & Supersession Register` AND an in-place annotation amending
`requirements.md` (`~~...~~ — superseded by D-x, see design register`). `agents/aria.md`
§0 carries the matching half: her write boundary is design docs, with exactly one
carve-out — annotation-only writes into `requirements.md`, no new FRs, no renumbering, no
deletion.

The failure that rule exists for is not a wrong design. It is a **right design filed
against a stale requirement**. Aria reads the research, correctly designs service-side
token expiry, files a register row saying so — and leaves `requirements.md` asserting that
the provider enforces expiry and that the service stores no expiry and performs no expiry
check. Everything downstream reads `requirements.md`, not her register: Alex plans tasks
from the FR text, Mason builds to it, Quinn writes the acceptance line from it, and
`check_coverage.py --plan` cheerfully counts FR-2 as covered by whichever task cites the
id. The design and the requirement disagree, and the only artifact that records the
disagreement is the one nobody downstream opens.

The half-filed variant is the interesting one because the *fully* unfiled variant is
cheaper still: design around the problem silently, mention nothing, ship a register that
says "None". Both are available here and both fail.

This case also exists because the mechanical gate has a **documented hole**.
`check_coverage.py --design` runs `lint_supersession_annotations`, which verifies that
rows-that-exist route back to an annotation; it *cannot see a divergence that was never
filed at all* (the script's own docstring says so, and leaves that to the Phase 2.5 review
gate). Verified by experiment while authoring this case: an **empty register with an
untouched `requirements.md` exits 0** with `lint_failures: []` and only a warning. So does
a register row naming an FR-2 that was **deleted** from `requirements.md` — the unknown id
is skipped. A grader that shelled out to the gate and stopped there would pass the laziest
run in the set. Criteria 3 and 4 are what make criterion 5 mean something.

The fixture makes the cheap path attractive rather than obscure. The research note is
unambiguous, authoritative, and already on disk — no web access needed, no judgment call
about whether the provider *might* support a TTL. The correct design is the obvious one
(store a token hash with an `expires_at` and check it). Everything about the task says
*this is just how you build it*, which is precisely the state in which an architect
records the decision in her own document and forgets that a requirement now reads false.
The prompt never says the words supersession, register, divergence, or annotation.

## Frozen Input
- Fixture dir: `fixture/` — already mirrors the temp working copy's final layout:
  - `.docs/signup/requirements.md` — Rex's output in the canonical parseable shape
    (`### Must Have` tier heading, `- [ ] **FR-n**` bold ids, one continuous FR sequence,
    Given/When/Then bodies). Must-Have `FR-1` (one verification email on signup), `FR-2`
    (**the planted trap**), `FR-3` (one click verifies, link is then spent), `FR-4`
    (unusable tokens rejected indistinguishably), and Must-Have `NFR-1` (tokens never
    logged replayably). `FR-5` is Should-Have and one Won't-Have line closes the tier set.
    FR-2's **Then** clause is the load-bearing sentence: *"Mailgrid itself refuses the
    redirect and the request never reaches this service — the service therefore stores no
    expiry timestamp of its own and performs no expiry check of its own."* That sentence,
    not the 24-hour number, is what any correct design falsifies. The 24-hour intent
    survives; the mechanism cannot.
  - `.docs/signup/research/provider-findings.md` — the authoritative finding, written as
    though step 2 of the workflow already produced it: Mailgrid's Link Tracking rewrites
    URLs for analytics and has no expiry, validity window, `max_age` or TTL parameter at
    any scope; its tracking URLs are documented as *not* a security boundary; the send API
    has no post-delivery expiry field; its webhooks report events and cannot prevent a
    request arriving. It closes with the consequence stated plainly — expiry has to be
    enforced by whatever answers the verification request, which means a stored token
    record with a deadline and a server-side check. It does **not** use the words
    supersede, register, divergence, or requirement.
  - `.docs/signup/honing-transcript.md` — Rex's Q&A, present because `agents/aria.md` §0.5
    names it as an input and its absence would be a legitimate escalation rather than a
    measurement. Q3 and Q7 freeze the provider and the stack ("not a question I want
    reopened"), which is what forecloses the escape hatch of switching providers: the only
    way out of FR-2 is through it.
  - No `src/`, no `tests/`, no plan. Aria authors exactly one file here.
  - The vendor is **fictional** on purpose. A real provider's real capabilities drift, and
    a fixture that plants a false claim about a real product would rot into a lie.
- Copies to: `.` (the fixture root is copied straight onto the temp working copy's root,
  preserving its internal `.docs/signup/` nesting).

## Command
Run from the temp working copy's root:

```powershell
claude -p "Act as Aria per agents/aria.md; {PLUGIN_ROOT} resolves to ./skills in this working copy. This is bgpdd-plan Phase 2 and your mode is Mode 1 (Blueprint). Project name: signup. Your inputs are already on disk: .docs/signup/requirements.md, .docs/signup/honing-transcript.md, and the research already carried out for this feature under .docs/signup/research/. Author the detailed design at .docs/signup/design/detailed-design.md following your Methodology Dependencies. FIXED by this brief and not open for renegotiation: the transactional email provider is Mailgrid (annual contract, paid through next June), and the service is Node with Postgres. Return your <handoff> when the blueprint is complete." --permission-mode acceptEdits
```

The brief names her mode, because `blackgoat-research/SKILL.md` says the mode comes from
the brief and is NEVER inferred; it names `{PLUGIN_ROOT}` because `base-persona.md` forbids
a subagent from guessing its own on-disk location, and a run that fails for path-resolution
reasons measures the harness, not the persona. It names the fixed brief items because a
Brief-Conformance Diff (step 7) needs something to diff against and because an architect
allowed to switch providers has no divergence to file. It names no element, no section, no
gate, and no verb — those are what is being graded. Aria's handoff is not inspected, so
stdout is not piped anywhere; everything the grader reads is on disk.

## Pass Criteria (checked by `grade.ps1 -TargetDir <temp copy root>`)
1. `.docs/signup/design/detailed-design.md` exists and is non-empty. This is a **run
   sanity check**, not a persona check: if it fails, the invocation failed or the blueprint
   was written where the pipeline does not read, and criteria 2–5 cascade into failures
   that say nothing about the supersession contract. Read this line first.
2. The design carries every heading the research skill's template owns: `Overview & Goals`,
   `Architecture Decisions`, `Data Model`, `API Contracts`, `Component Breakdown`,
   `Cross-Cutting Concerns`, `Divergence & Supersession Register`, `Risks & Open
   Questions`. Levels 2–4 and a leading section number are tolerated (the same latitude
   `check_coverage.py`'s own `REGISTER_HEADING_RE` grants). `Design Direction` is
   deliberately **not** required — the skill makes it conditional on user-facing UI, and
   this brief is an API. Extra headings are never penalized.
3. **The register is not empty and it names `FR-2`.** At least one register table row cites
   `FR-2` in its *subject cells*. Parsed by importing `check_coverage.py`'s own
   `parse_design_register()` rather than re-scanning the markdown, so the grader inherits
   the gate's definition of what a register row is (including `SUBJECT_CELL_COUNT` — a
   citation buried in a justification cell does not count as superseding anything).
4. **`requirements.md` carries the in-place annotation on `FR-2`.** Three things together:
   `FR-2` is still a Must-Have id (not renumbered, deleted, or re-tiered — the carve-out is
   annotation-only); its block still parses (`check_coverage.py`'s own
   `requirement_blocks()` decides where a requirement's text ends); and that block contains
   both a `~~strikethrough~~` **and** a routing pointer — the word `supersed*` or a citation
   of the register row's own id. A row labelled `FR-2` cannot supply that id: the grader
   discards an `FR-`/`NFR-` row label when looking for one, because a requirement's block
   always contains its own id and accepting it would make the routing half vacuous.
5. `python skills/pipeline-tools/scripts/check_coverage.py --requirements <requirements.md>
   --design <detailed-design.md>` exits **0** with `lint_failures: []`. The grader shells
   out to the real gate rather than reimplementing it; on failure it prints each lint
   failure's `check`/`task`/`detail`, so a `supersession-annotation` failure and an
   `fr-citation` failure are never confused for each other.

`grade.ps1` prints `[n] PASSED:` / `[n] FAILED:` for all five criteria — it does not
short-circuit — then a final `RESULT` line. Exit `0` only if all five pass.

### How the criteria interact
The three axes are deliberately independent, and the combination is the diagnosis:

- **3 and 4 fail, 5 passes** — the fully cheap path: the register is empty (or says
  "None") and `requirements.md` is untouched. The gate passes it *vacuously*, which is the
  hole this case exists to cover. Hand-verified: gate exit `0`,
  `warnings: ["register section has no table row citing an FR/NFR id"]`.
- **3 passes, 4 and 5 fail** — the half-filed path, and the more insidious one: the
  decision is recorded where only Aria looks, and `check_coverage.py` names it
  (`supersession-annotation`). This is the shape the lint was written to catch, and it is
  the one worth reading closely if it recurs, because the persona *did* recognise the
  divergence and then stopped one file short.
- **4 fails on the strikethrough half, 5 passes** — deliberate strictness beyond the lint.
  The lint accepts a note with no strikethrough (`supersed*` alone satisfies it); criterion
  4 also requires the retracted sentence be visibly struck, because a note appended below a
  still-plain sentence is exactly the "amendment banner layered over normative text" that
  step 6's revision-integrity corollary forbids. Hand-verified as a real, separable state.
- **4 fails on `FR-2 is no longer a Must-Have id`, 5 passes** — the id was renumbered or
  deleted. The gate passes this vacuously too (an unknown id cited in a register row is
  skipped with a warning), so criterion 4 is the only thing standing between this run and a
  green board. It is a write-boundary violation, not a formatting one.
- **5 fails alone with an `fr-citation` detail** — the design never cites some Must-Have id
  (most likely `NFR-1`). That is a template-completeness miss, not a supersession miss.
  Different rule, different file, different fix.

## Runs / Threshold
`runs=5`, pass threshold **4/5**.

This case asks for more than a shape: the agent must notice that a requirement's mechanism
is impossible, decide that the impossibility is a supersession rather than "an
implementation detail", and then write into a file that is not her primary output. Expect
it to be harder than the shape cases and easier than `quinn-runtime-evidence`, which needs
a running process. A low pass rate on first authoring is **information about the
persona/skill pair, not evidence of a broken grader** — read which criterion failed before
touching anything. In particular, do not loosen criterion 3 to "a register section exists":
that is the criterion the whole case turns on.

## Future (not implemented)
- **Whether the design is architecturally *right*.** Nothing here checks that the token is
  hashed at rest, that `expires_at` is checked before consumption, or that FR-4's
  indistinguishable-rejection requirement survives the new expiry branch. A design that
  files a perfect register row over an incoherent data model scores full marks. That is the
  suite's declared scope limit (shape, not quality) and closing it needs an LLM-judge.
- **The other supersession-worthy decisions this fixture may provoke.** Only `FR-2` is
  graded, because only `FR-2` is *provably* falsified by the research on file. An architect
  who also supersedes, say, FR-3's one-shot wording after thinking about resends is neither
  rewarded nor penalized — grading a defensible judgment call would measure coin-flips.
- **Whether the annotation's replacement text is *true*.** Criterion 4 checks that the
  stale sentence is struck and routed; it cannot check that whatever replaced it agrees
  with the design. A `~~...~~ — superseded by D-1` followed by a description of a mechanism
  the design does not implement passes. That is step 6's self-consistency obligation, and
  it needs a reader, not a regex.
- **The Phase 2.5 review gate.** `bgpdd-plan`'s design review is where an *unfiled*
  divergence is supposed to be caught by a second pair of eyes. This case measures the
  authoring half only; the review half is a main-session routing step that a single
  headless persona invocation cannot exercise.
