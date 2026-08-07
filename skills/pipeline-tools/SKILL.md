---
name: pipeline-tools
description: "Deterministic coverage-gate CLI for the PDD pipelines. Provides check_coverage.py, which verifies every Must-Have FR/NFR in requirements.md is covered by plan.md tasks (plan mode) or by passing tests in test-report.md (test mode), and that every requirement a detailed-design.md supersedes carries a matching in-place annotation (design mode). Squad-internal: executed by the Orchestrator at the bgpdd pipeline coverage gates, not delegated to agents."
---

# pipeline-tools

A pure-stdlib Python 3 CLI (`scripts/check_coverage.py`) that makes the requirement-coverage gates in `bgpdd-plan`, `bgpdd-lite`, `bgpdd-build`, and `bgpdd-shipping` machine-checkable instead of a manual read. The Orchestrator runs it directly via a shell action — it is never delegated to an agent.

## Invocation

```bash
python check_coverage.py --requirements <path> --plan <path>          # plan mode
python check_coverage.py --requirements <path> --test-report <path>   # test mode
python check_coverage.py --requirements <path> --design <path>        # design mode
python check_coverage.py --self-test                                  # runs the bundled unittest suite
```

Exactly one of `--plan` / `--test-report` / `--design` must be given — more than one or none is a usage error (exit 2). `--requirements` is required in every mode.

## JSON output shape

The tool always prints exactly one JSON object to stdout (diagnostics go to stderr):

```json
{
  "mode": "plan",
  "requirements_file": "<path as given>",
  "target_file": "<path as given>",
  "must_have": ["FR-1", "FR-2", "NFR-1"],
  "should_have": ["FR-3", "NFR-2"],
  "covered": ["FR-1", "NFR-1", "FR-3"],
  "uncovered": ["FR-2"],
  "uncovered_should": ["NFR-2"],
  "warnings": ["Task 5 has no 'Requirements covered:' field"],
  "lint_failures": [
    {"check": "literal-count", "task": "2", "detail": "hardcoded count \"7 error codes\": ..."}
  ],
  "result": "FAIL",
  "error": null
}
```

- `mode` is `"plan"`, `"test"` or `"design"`.
- `uncovered` and `lint_failures` are the **two gating arrays**: `uncovered` holds Must-Have coverage gaps, `lint_failures` holds lint violations. Either one non-empty ⇒ `"result": "FAIL"`. `uncovered_should` is informational and never affects exit code.
- `lint_failures` entries are always `{"check", "task", "detail"}`. `check` is one of `literal-count`, `consumes-provides`, `path-hygiene` (plan mode) or `supersession-annotation` (design mode); `detail` is the author-facing message. `task` names the offending unit: the task number as a string in plan mode, the **register row's identifier** (`SUP-01`, `DIV-10`, …) in design mode. The array is always present and always empty in test mode (test mode runs no lints).
- **Design mode computes no coverage.** `covered`, `uncovered` and `uncovered_should` are always empty; `must_have` / `should_have` are still populated (design mode still requires a parseable requirements.md and still exits 2 on one with zero Must-Haves). Only `lint_failures` gates.
- On error: `"result": "ERROR"`, `"error"` holds the message, other arrays hold whatever was parsed before the failure.
- ID arrays are naturally sorted (`FR-2` before `FR-10`).

## Exit codes

- **0** — every Must-Have `FR`/`NFR` is covered and no lint failed (warnings don't affect this). In design mode: every register row routes to an annotation.
- **1** — `uncovered` lists at least one Must-Have gap, **or** `lint_failures` is non-empty. A clean-coverage plan with a lint failure still exits 1.
- **2** — usage error, a missing/unreadable file, or a structural contract failure (no Must-Have requirements found, no task blocks found in the plan). Design mode defines **no** structural failure of its own: a design with no register section is a warning at exit 0.

## Parsing rules (condensed)

**requirements.md**: MoSCoW section headings (`## / ### / ####` + `Must|Should|Could|Won't Have`, trailing text tolerated) open a tier that closes at the next heading of the same-or-higher level. Within a Must/Should/Could tier, any `**FR-n**` bold ID registers at that tier. `**NFR-n**` IDs are found anywhere in the document via `- **NFR-n** (Must|Should|Could ...)`; an NFR ID with no parseable tier tag defaults to **Must** (fail-safe) and emits a warning. Won't-Have IDs are excluded from all sets unless the same ID also appears in a real tier, in which case the first non-Won't tier wins (with a warning). Duplicate IDs across tiers: first occurrence wins (with a warning). Zero Must-Have IDs found across FRs and NFRs combined → exit 2 ("an empty gate must never silently pass").

**Supersession annotations in requirements.md.** A design decision that supersedes an FR/NFR is recorded by *annotating* the requirement in place (strikethrough plus a "superseded by D-x" note), never by renumbering or deleting it. The parser deliberately does **not** treat strikethrough as a tier change: `~~**FR-2** ...~~ — superseded by D-3` keeps FR-2 at whatever tier its section declares, stays in `must_have` if that section is Must Have, and emits one warning per struck ID. This is the same fail-safe precedence the duplicate-ID and Won't-Have rules use — an annotation can never silently remove a gating requirement. A superseded Must-Have is therefore still covered the normal way: the task that implements the superseding design decision cites the original ID in its `**Requirements covered:**` field. Genuinely dropped scope moves to a `Won't Have` section, which is the only construct that de-gates an ID.

**detailed-design.md** (design mode): the machine twin of the annotation doctrine above — it checks the *routing* between the design's register and `requirements.md`, and nothing else.

- The register section opens at a heading (level 2–4) whose text is `Divergence & Supersession Register` (leading section numbering such as `## 17. ` and `and` for `&` are tolerated) and closes at the next heading of the same-or-higher level, so its `###` subsections (`17.1 Divergences`, `17.2 Supersessions`, closing-pass additions) are all included. **A design with no register section is a warning, not a failure** — a greenfield design may legitimately have zero divergences.
- Inside the section, every markdown table row (a line starting with `|`, separator rows excluded) is examined. Ids are read from the row's **subject cells only — the first two**: the `#` cell and the `Requirement` / `Departs from` cell. Later cells are *justification prose*, which cites other requirements as supporting argument without superseding them (an observed register's DIV-04 explains itself by reference to "the FR-1 retry budget"; FR-1 is not superseded). Reading whole rows made 20+ correctly-unannotated requirements look like violations. Ids are deduplicated per row; a row whose subject cells cite no id is skipped.
- **Rule:** for every id named in a register row's subject, `requirements.md` must carry a supersession annotation on that requirement. A requirement's *block* runs from its `**FR-n**` / `**NFR-n**` bold-id line to the next bold-id line (an id declared more than once owns all of its blocks). The block counts as annotated if it contains **any** of: strikethrough (`~~`), a `supersed*` word, or a **citation of the register row's own id** (`SUP-01`, `DIV-07`, …). The row-id citation is the load-bearing one: real annotations read "**REINTERPRETED by SUP-05**", "**SCOPE PINNED by SUP-06**", "**SUPERSEDED IN PART by SUP-02**", so a verb whitelist would reject correctly-annotated requirements. An annotation citing a *different* row does not satisfy a row that names the requirement.
- A violation appends one `lint_failures` entry (`check: "supersession-annotation"`, `task`: the row id) and forces `FAIL`/exit 1. An id named in the register but not defined in `requirements.md` takes the existing unknown-id **warning** path ("unknown requirement ID ... cited in design register") and is not linted — there is no block to annotate.
- **Deliberate scope limit — this lint checks rows-that-exist → annotations, one direction only.** It proves that every divergence the design *filed* was routed back to its requirement. It cannot see a divergence that was **never filed at all**, and it cannot see one filed *outside* the register section (an observed v8 run deleted Cognito custom attributes that FR-29 mandates, resolved it in a §19 revision section rather than the §17 register, and never annotated FR-29 — this lint does not catch that). Detecting an unfiled divergence requires reading the design against the requirements, which stays with the **Phase 2.5 design review gate**. Design mode narrows that gate's surface; it does not replace it. A `PASS` here means "nothing filed was left unrouted", never "this design diverges from nothing".

**plan.md** (plan mode): task blocks split on `## Task [N]:` (brackets optional). Zero task blocks → exit 2. Within each block, the first `**Requirements covered:**` line's `FR-n`/`NFR-n` tokens are unioned into `covered`. "None"/"N/A" is a legitimate empty value (no warning); a field missing entirely from a task warns by task number; an ID cited in the plan but not defined in requirements warns ("unknown requirement ID ... cited in plan") without failing the gate.

**Plan-mode lints (gating).** Three lints run over the same task blocks, in plan mode only. Each violation appends one `lint_failures` entry and forces `FAIL`/exit 1 even when coverage is complete.

**`literal-count`** — enforces "count definitions, not mentions" (below). Flags a transcribed artifact-inventory count anywhere in a task block: a number immediately followed by an inventory noun (`codes`, `error codes`, `status codes`, `routes`, `endpoints`, `entries`, `components`, `screens`, `tables`) — e.g. "maps 7 error codes", "exposes 4 endpoints". A plan states the *rule*, not the tally: assert set-equality against the source table ("every code in the error table has a mapping"), because a transcribed number goes stale the moment the table changes and no test catches it. Unit and threshold values are **not** inventory counts and are never flagged ("2 decimal places", "3 attempts", "60 seconds"), nor are digits that are part of an ID token (`FR-3 endpoints`). Repeated identical phrases report once per task.

**`consumes-provides`** — parses each task block's optional `**Boundary contracts:**` field. Grammar, deliberately forgiving:

```
**Boundary contracts:** provides: auth.session, auth.token; consumes: db.schema
```

- The field is the marker line plus any continuation lines up to the first blank line, next `**Field:**` line, or next heading — so a multi-line indented form works too.
- Inside it, `consumes:` and `provides:` keywords (case-insensitive) each introduce a comma-separated identifier list terminated by `;`, a newline, or the next keyword. Both keywords may appear in either order, more than once.
- **A single keyword's identifier list terminates at a newline as well as at `;`.** The *field* may span continuation lines, but a *wrapped list* silently contributes only its first line — the gate then reports a missing provider for identifiers the author can plainly see in the file. Authors: keep each keyword's list on one physical line, opening a second `provides:` keyword on the next line rather than wrapping one. Readers of a surprising verdict: before re-doing any work, re-read the raw field and look for a wrap — **a `lint_failures` entry naming an identifier that is visibly present is a format mismatch, not a missing dependency.**
- An identifier is the first `[A-Za-z0-9_./-]` token of each comma-separated part, so backticks and trailing parentheticals are tolerated. Matching is case-insensitive. `none` / `n/a` / `-` / `tbd` are empty values.
- **Rule:** every consumed identifier must be provided by a **strictly lower-numbered** task. Provided by a later task, by the same task, or by no task at all is a failure naming the task and the identifier. This is the machine twin of the external-prerequisite ownership rule in `planning-and-task-breakdown`.
- **The field is optional.** A task with no `**Boundary contracts:**` field is never a failure and emits no warning. A consumed identifier with no provider always is.

**`path-hygiene`** — flags file-path-shaped strings that point outside the plan's own repository: Windows absolute paths (`D:\repos\...`), UNC paths (`\\server\share\...`), `file:///` URIs, and repo-escaping relative paths (any `../` segment). Repo-relative paths (`src/import/parser.ts`) are the sanctioned form and pass, as do URL routes (`/auth/login`). Rationale: an observed plan referenced a sibling repository's files by absolute path, which no builder on another machine can resolve and which silently smuggles another codebase into scope. A `file:///D:/...` URI counts once, not twice.

**test-report.md** (test mode): line-based across the whole file — the `#Task [N]:` headers are for humans only. A line is "status-bearing" if it has both an ID token and a status token (`PASS`/`PASSED`/`✅` vs `FAIL`/`FAILED`/`❌`, word-boundary matched; a line with both counts as FAIL). **Latest mention wins** — the last status-bearing line for an ID in file order determines its status. IDs whose only mentions lack a status token get one warning each and are not counted as covered. A missing/unreadable report file → exit 2. A report with zero status-bearing mentions is **not** a structural error — every Must-Have goes to `uncovered` and the gate exits 1 (a report that proves nothing is a coverage failure, not a tool failure).

Quinn's Coverage Ledger format (see `agents/quinn.md` §6) is what the test-report parser expects: within each `#Task [N]:` block, one line per exercised ID —

```
- FR-3: PASS — {test name / evidence}
- NFR-1: FAIL — {failing assertion}
```

Only `PASS`/`FAIL` as the status word, latest mention wins, so a retest appends a fresh line rather than editing history.

**What the evidence field must contain.** The gate is deterministic about the *status* token and completely trusting about the *evidence* prose beside it — so the evidence field carries the entire integrity burden of the gate:

- A `PASS` cites **the executed test that asserts that requirement's own acceptance criterion**, named by test file plus test name. A source file, a component, an infrastructure resource, a design document, or a prior milestone's `PASS` is **not** evidence — those establish that code exists, not that the requirement holds.
- **Never restate a `PASS` you did not just re-execute.** This is the sharp edge of *latest mention wins*: a later, vaguer line silently **overwrites** an earlier, stronger one, and it is the last line in file order that the gate reads. Appending "re-verified" or "final verification" prose over a genuine earlier measurement does not strengthen the ledger — it destroys the only real evidence in it and leaves the gate reading the weakest claim in the file. If you did not run it this round, append nothing.
- A verification you could not perform is recorded as `FAIL` with the reason, or omitted entirely so the gate reports it as uncovered. It is **never** recorded as `PASS` with a hedge (see `agent-squad/base-persona.md`, Evidence Integrity). A gap the gate can see is cheap; a gap it cannot is what the gate exists to prevent.

## Fixtures & self-test

`fixtures/happy/`, `fixtures/uncovered/`, and `fixtures/malformed/` each hold a `requirements.md` (+ `plan.md` and/or `test-report.md`) exercising the pass, gap, and structural-failure paths respectively. Six more cover the lints and annotation handling, each with complete Must-Have coverage (or, in design mode, no coverage computation at all) so the verdict isolates the behaviour under test:

- `fixtures/annotated/` — a requirements.md carrying a struck-through, "superseded by D-x" Must-Have FR; exits **0** with a supersession warning.
- `fixtures/lint-literal-count/` — transcribed inventory counts alongside legitimate unit values; exits **1** on `literal-count` only.
- `fixtures/lint-boundary-contracts/` — an identifier provided by a later task, one provided by no task, and a task with no contracts field; exits **1** on `consumes-provides` only.
- `fixtures/lint-paths/` — absolute path, `file:///` URI, and `../sibling-repo/` reference beside sanctioned repo-relative paths; exits **1** on `path-hygiene` only.
- `fixtures/design-annotated/` — a `detailed-design.md` whose register supersedes two requirements, both annotated in place (one by strikethrough + note, one by note alone), plus a divergence row citing no requirement; exits **0**.
- `fixtures/design-unannotated/` — the observed evasion shape: a **divergence** row whose subject is an FR that was never annotated, beside an annotated supersession row and a row citing an undefined id; exits **1** on one `supersession-annotation` entry, with the undefined id as a warning.

Run the bundled suite either directly or through the CLI:

```bash
python scripts/test_check_coverage.py
python scripts/check_coverage.py --self-test
```

## Single contract authority

The four pipeline coverage gates — `bgpdd-plan` Phase 3.5, `bgpdd-lite` Phase 2.5, `bgpdd-build` Phase 5 Step 2, and `bgpdd-shipping` Step 3.5 — reference this file as the single source of truth for the CLI's contract (invocation, JSON shape, exit codes, parsing rules). They do not restate the parsing rules inline; update them here only.

## Pre-gate authoring conformance (smoke-test before you trust the verdict)

The gate is only as trustworthy as its inputs' format. Before relying on a coverage verdict, run check_coverage.py against the ACTUAL requirements.md and test-report.md as a format smoke-test. Treat any of these as "artifacts not in parseable format," NOT as a real coverage result: exit 2 (structural failure / "no Must-Have requirements found"), every ID reported as "unknown requirement ID", or "zero status-bearing mentions". The fix is to correct the artifact to the documented format — **FR-n** bold IDs under MoSCoW headings in requirements.md, and Quinn Coverage Ledger lines (- FR-n: PASS — evidence) in test-report.md — never to fall back to eyeballing coverage by hand. A gate you bypass manually is not a gate.

Design mode has two such tells, both warnings rather than results: "design has no 'Divergence & Supersession Register' section" and "register section has no table row citing an FR/NFR id". On a design that plainly diverges somewhere, either warning means the register is missing or not in table form, so the `PASS` beside it proves nothing — fix the register, then re-run.

**Count definitions, not mentions.** In plan.md this doctrine is now *enforced* by the `literal-count` lint (see Plan-mode lints), which fails the gate on any transcribed artifact-inventory count in a task block; the guidance below still applies wherever you count by hand rather than through this tool. When you verify an artifact's structure with a text search rather than this tool — how many requirements exist, whether every ID carries a tier, whether a document is complete — anchor the pattern on the *definition-line* form (e.g. `- [ ] **FR-n**` under a MoSCoW heading), never on the bare ID token. Cross-references, prose citations, and downstream task fields all contain the same tokens, so a bare-ID count silently inflates: an observed run counted 131 `FR-` matches against 74 actual definitions. An inflated count can make an incomplete or malformed artifact appear to pass. Report unique-ID counts derived from definition lines only, and when a count disagrees with the artifact's own declared total, treat the disagreement itself as the finding — never pick whichever number agrees with the outcome you expect. A check that counts ID *mentions* rather than ID *definitions* can pass a malformed artifact, which makes it worse than no check at all.

## check_dependency_tables.py

A second pure-stdlib CLI (`scripts/check_dependency_tables.py`) that statically validates every agent's "## Methodology Dependencies" section. It checks (a) the section contains the canonical "NOT Skill-tool invocables" wording — the guard against a delegated agent invoking a dependency path through the Skill tool instead of reading it as a file — and (b) every `{PLUGIN_ROOT}` path in the section's table resolves to a real file. `agents/blackgoat.md` is excluded (exempt by design; see repo CLAUDE.md).

### Invocation

```bash
python check_dependency_tables.py <skills_dir>
```

`<skills_dir>` is the plugin's `skills/` directory (i.e. `{PLUGIN_ROOT}`); `agents/` is located as its sibling directory.

### Exit codes

- **0** — every agent's Methodology Dependencies table is valid.
- **1** — at least one violation; a per-violation report is printed to stdout.
- **2** — usage error (wrong argument count, or `<skills_dir>` is not a directory).
