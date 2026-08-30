---
name: pipeline-tools
description: "Deterministic stdlib-Python CLI family for the PDD pipelines: check_coverage.py verifies every Must-Have FR/NFR in requirements.md is covered by plan.md tasks, by passing tests in test-report.md, or by an in-place supersession annotation in detailed-design.md; check_commit_gate.py makes the bgpdd-build milestone commit gate machine-run (verdict, staleness, blockers, optional working-tree verification) and can perform the commit itself on a pass; check_agent_report.py verifies a durable agent report (Cipher's security-report.md, Vera's verification-report.md) backs its Pass verdict with evidenced check lines and zero Critical findings; check_runtime_evidence.py gates observed-runtime captures cited in a test or verification report — out-of-process transport, freshness, and required response keys — so an in-process suite can no longer stand in for an observation; check_acceptance_suite.py gates the feature-scoped walkthrough in acceptance-matrix.md against Quinn's acceptance-results.md, including manual steps that must cite real evidence and inverse operations that must actually have been run; check_ship_decision.py gates Dep's ship-decision.md GO/NO-GO; check_blockers.py gates an empty blockers array in orchestrator-state.json; next_milestone.py derives the next pending milestone from plan.md without a full re-read; run_quiet.py runs builds/tests, logging the full output to disk and surfacing only errors-with-context and a tail; update_state.py is the sanctioned read-modify-write path for orchestrator-state.json; and check_dependency_tables.py statically validates every agent's Methodology Dependencies table. Squad-internal: executed by the Orchestrator directly at the bgpdd pipeline gates, not delegated to agents."
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
  "blocked": [],
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
- `blocked` (test mode) lists every requirement ID whose latest status token is `BLOCKED`. It is **informational and simultaneously gating**: a BLOCKED Must-Have also appears in `uncovered`, so the gate exits 1 — the array exists so a reader can tell *"unperformed and said so"* from *"never mentioned"*. Always present, always `[]` outside test mode. Reported unfiltered (not intersected with the known-ID set) so an ID the requirements never declared still surfaces rather than vanishing.
- `lint_failures` entries are always `{"check", "task", "detail"}`. `check` is one of `literal-count`, `consumes-provides`, `path-hygiene`, `runtime-criterion`, `domain-tag` (plan mode) or `supersession-annotation` / `fr-citation` (design mode — `fr-citation` when the script emits Must-Have IDs missing from the design); `detail` is the author-facing message. `task` names the offending unit: in plan mode the task number as a string, or the owning **milestone's heading text** for `runtime-criterion` and for `domain-tag`'s milestone half; in design mode the **register row's identifier** (`SUP-01`, `DIV-10`, …) or the missing FR/NFR id for `fr-citation`. The array is always present and always empty in test mode (test mode runs no lints).
- **Design mode is supersession-lint + fr-citation, not full FR→design coverage.** `covered`, `uncovered` and `uncovered_should` are always empty for the coverage arrays; `must_have` / `should_have` are still populated (design mode still requires a parseable requirements.md and still exits 2 on one with zero Must-Haves). Only `lint_failures` gates. Every Must-Have ID must appear at least once in the design text (`fr-citation`); register rows must route to matching in-place supersession annotations (`supersession-annotation`). Citation presence is not proof the design satisfies the requirement.
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

**Plan-mode lints (gating).** Five lints run in plan mode only: `literal-count`, `consumes-provides`, `path-hygiene` and `domain-tag` over the same task blocks (`domain-tag` also reads the milestone headings, `runtime-criterion` the checkpoint blocks — described in its own section below). Each violation appends one `lint_failures` entry and forces `FAIL`/exit 1 even when coverage is complete.

**`literal-count`** — enforces "count definitions, not mentions" (below). Flags a transcribed artifact-inventory count anywhere in a task block: a number immediately followed by an inventory noun (`codes`, `error codes`, `status codes`, `routes`, `endpoints`, `entries`, `components`, `screens`, `tables`) — e.g. "maps 7 error codes", "exposes 4 endpoints". A plan states the *rule*, not the tally: assert set-equality against the source table ("every code in the error table has a mapping"), because a transcribed number goes stale the moment the table changes and no test catches it. Unit and threshold values are **not** inventory counts and are never flagged ("2 decimal places", "3 attempts", "60 seconds"), nor are digits that are part of an ID token (`FR-3 endpoints`). Repeated identical phrases report once per task.

**`consumes-provides`** — parses each task block's optional `**Boundary contracts:**` field. Grammar, deliberately forgiving:

```
**Boundary contracts:** provides: auth.session, auth.token; consumes: db.schema
```

- The field is the marker line plus any continuation lines up to the first blank line, next `**Field:**` line, or next heading — so a multi-line indented form works too.
- Inside it, `consumes:` and `provides:` keywords (case-insensitive) each introduce a comma-separated identifier list terminated by `;`, a newline, the next keyword, or the first **sentence break** within the line — a `. ` (period followed by whitespace) or a ` — ` (space-emdash-space). This last terminator exists because a machine line is sometimes followed by explanatory prose on the same physical line ("`consumes: none. The ruling is read by Tasks 3, 4, 5.`"); without it, the prose's own commas comma-split into fake identifiers (an observed run produced `4`, `5`, and `not` this way). An identifier's internal dots (`api.mode.ruling`) are never followed by whitespace, so `. ` is safe to use as a terminator without truncating real identifiers. Both keywords may appear in either order, more than once.
- **A single keyword's identifier list terminates at a newline as well as at `;`.** The *field* may span continuation lines, but a *wrapped list* silently contributes only its first line — the gate then reports a missing provider for identifiers the author can plainly see in the file. Authors: keep each keyword's list on one physical line, opening a second `provides:` keyword on the next line rather than wrapping one. Readers of a surprising verdict: before re-doing any work, re-read the raw field and look for a wrap — **a `lint_failures` entry naming an identifier that is visibly present is a format mismatch, not a missing dependency.**
- An identifier is the first `[A-Za-z0-9_./-]` token of each comma-separated part, so backticks and trailing parentheticals are tolerated. Matching is case-insensitive. Leading/trailing `.`, `/`, and `-` characters are stripped from that token before comparison. `none` / `n/a` / `-` / `tbd` are empty values.
- **Rule:** every consumed identifier must be provided by a **strictly lower-numbered** task. Provided by a later task, by the same task, or by no task at all is a failure naming the task and the identifier. This is the machine twin of the external-prerequisite ownership rule in `planning-and-task-breakdown`.
- **The field is optional.** A task with no `**Boundary contracts:**` field is never a failure and emits no warning. A consumed identifier with no provider always is.

**`path-hygiene`** — flags file-path-shaped strings that point outside the plan's own repository: Windows absolute paths (`D:\repos\...`), UNC paths (`\\server\share\...`), `file:///` URIs, and repo-escaping relative paths (any `../` segment). Repo-relative paths (`src/import/parser.ts`) are the sanctioned form and pass, as do URL routes (`/auth/login`). Rationale: an observed plan referenced a sibling repository's files by absolute path, which no builder on another machine can resolve and which silently smuggles another codebase into scope. A `file:///D:/...` URI counts once, not twice.

**`domain-tag`** — every task declares exactly one domain tag and every milestone is domain-homogeneous, the machine twin of `planning-and-task-breakdown`'s tag legend and **Milestone domain homogeneity** rule (its contract authority). Two halves:

- **Per task**: the block's `**Tags:**` field is read with the same extent rule as `Boundary contracts:` (marker line plus continuation lines to the first blank line, next `**Field:**` line, or next heading). Three failures, `task` = the task number: no `**Tags:**` field at all; a field carrying neither `[UI]` nor `[API]`; a field carrying both (split the task). Overlays (`[SEC]`/`[EXT]`/`[BLOCKED]`) are ignored here.
- **Per milestone**: a milestone heading carrying zero or two domain tags fails outright; otherwise every `## Task <n>:` heading inside that milestone's extent whose task declares the *other* domain is one mixed-domain failure. Both name the milestone's title as `task`.

Rationale (convention #9's conversion): an untagged task is unroutable — `next_milestone.py` routes `[UI]`→Nova and `[API]`→Mason — and a mixed milestone is rejected as `MIXED` at build time, so both defects must die at plan time rather than a milestone into the build. Scope limit, mirroring `runtime-criterion`: a plan with no milestone headings skips the homogeneity half; the per-task half always applies.

**test-report.md** (test mode): line-based across the whole file — the `#Task [N]:` headers are for humans only. A line is "status-bearing" if it has both an ID token and a status token (`PASS`/`PASSED`/`✅` vs `FAIL`/`FAILED`/`❌`, word-boundary matched; a line with both counts as FAIL). **Latest mention wins** — the last status-bearing line for an ID in file order determines its status. IDs whose only mentions lack a status token get one warning each and are not counted as covered. A missing/unreadable report file → exit 2. A report with zero status-bearing mentions is **not** a structural error — every Must-Have goes to `uncovered` and the gate exits 1 (a report that proves nothing is a coverage failure, not a tool failure).

This section is the grammar authority for the Coverage Ledger format Quinn emits (her persona §6 carries only her role-specific deltas and points back here). The test-report parser expects: within each `#Task [N]:` block, one line per exercised ID —

```
- FR-3: PASS — {test name / evidence}
- NFR-1: FAIL — {failing assertion}
```

Only `PASS`/`FAIL` as the status word for a check you executed; `BLOCKED` per its own rule below. Latest mention wins, so a retest appends a fresh line rather than editing history.

**What the evidence field must contain.** The gate is deterministic about the *status* token and completely trusting about the *evidence* prose beside it — so the evidence field carries the entire integrity burden of the gate:

- A `PASS` cites **the executed test that asserts that requirement's own acceptance criterion**, named by test file plus test name. A source file, a component, an infrastructure resource, a design document, or a prior milestone's `PASS` is **not** evidence — those establish that code exists, not that the requirement holds.
- **Never restate a `PASS` you did not just re-execute.** This is the sharp edge of *latest mention wins*: a later, vaguer line silently **overwrites** an earlier, stronger one, and it is the last line in file order that the gate reads. Appending "re-verified" or "final verification" prose over a genuine earlier measurement does not strengthen the ledger — it destroys the only real evidence in it and leaves the gate reading the weakest claim in the file. If you did not run it this round, append nothing.
- **A verification you could not perform is recorded as `BLOCKED`, with the reason.** `- FR-3: BLOCKED — app will not start; Tier 2 suite green only`. This is the sanctioned record and it is status-bearing: it counts as **not covered**, lands a Must-Have in `uncovered`, and exits 1 — honesty routes the work, it never passes it. Do **not** write `FAIL` (that asserts a test ran and failed, a different fabrication) and do **not** omit the line (that hides the gap). It is never `PASS` with a hedge (see `agent-squad/base-persona.md`, Evidence Integrity). A gap the gate can see is cheap; a gap it cannot is what the gate exists to prevent.
- **Status precedence on one line is `FAIL > BLOCKED > PASS`**, extending the pre-existing both-PASS-and-FAIL-counts-as-FAIL rule. Across lines, latest mention wins, so a `BLOCKED` appended after a stale `PASS` downgrades the ID and a later genuine `PASS` clears it.
- **`NOT RUN` is deliberately NOT a token here** — a divergence (convention #8) from `check_agent_report.py`'s four-token grammar: in the coverage ledger, omission already means "not run", and a status-less mention already warns and stays uncovered. A `NOT RUN` line therefore behaves exactly like any other status-less mention.
- **Authoring hazard**: token matching is case-insensitive prose matching, the same posture as `PASS`/`FAIL`. So `- FR-1: PASS — the BLOCKED-state banner renders` downgrades to BLOCKED. The family's bias is deliberate (a false BLOCKED routes work; a false PASS ships a gap) but avoid the words in evidence prose.
- **Authoring hazard — a status line is a cumulative claim about the requirement, not a per-round log entry.** Because latest mention wins across lines, appending a status token for a requirement you did **not** exercise this round overwrites the evidenced verdict of the round that did; there is no round scoping in the ledger. So: report only requirements this round actually touched; write per-round narration ("not attempted this round", "out of scope for this stage") as prose with **no status token in the token position**; and never repair a downgraded id by writing a `PASS` you did not measure — re-run the check, or leave the honest `BLOCKED` standing and say which round measured what.

**`runtime-criterion` (plan mode).** Mechanizes `planning-and-task-breakdown`'s rule that a compile, typecheck, bundle, or source-search command is not a runtime exit criterion — at **plan time, before any code exists**. It reads each `Checkpoint` block's machine-parseable `RUNTIME PROBE:` line and reports one entry per defect, with `task` = the owning milestone's full heading text and every `detail` naming the checkpoint (one milestone may own several).

Six conditions: (1) no `RUNTIME PROBE:` line at all — this **short-circuits**, since it is the single root cause and reporting 2–6 on top would be noise; (2) `probe:` absent or empty (suppressed when the surface is `none`, where the SKILL replaces the probe fields with `justification:`); (3) `probe:` names an **in-process test client**; (4) `probe:` is a build / typecheck / search / **test-runner** command — `dotnet test` proves a suite is green, never that the running system emits anything; (5) the milestone's surface is `api`, `web+api`, or `fn` but the probe declares no `expect-status:` and/or no `require-keys:` (only the actually-missing field is named), because those become `check_runtime_evidence.py`'s arguments verbatim; (6) the surface is `none` but no `justification:` field is present.

The in-process tell list and the non-runtime-probe regexes are **duplicated verbatim** from `check_runtime_evidence.py` (this family has no shared module by convention), and a test asserts byte-equality of both so the two cannot drift. Milestone block extents mirror `next_milestone.py`'s `parse_milestones()`, with a cross-check test and one deliberate difference: a milestone-less plan yields `[]` here rather than raising, because the coverage gate also runs against plans predating the milestone convention.

**Checkpoint headings are matched at level 2 **and** 3** (`#{2,3}`), not level 3 only. `next_milestone.py` tolerates the deprecated `## Checkpoint:` form inside a milestone block, so linting only `###` would leave the deprecated spelling as a free escape hatch from the probe requirement. `### Checkpoints Overview` does not match (the pattern requires a word boundary after `Checkpoint`).

Scope limits: a plan with **zero** checkpoints yields zero failures — checkpoint *presence* is Step 5's own review item, and failing on absence would retroactively fail every pre-convention plan. A checkpoint outside every milestone block has no surface, so only conditions 1–4 apply. A missing or misspelled `[vs:]` tag is not this lint's business — `next_milestone.py` already halts the build for it. A `;` inside a probe command truncates the value, the documented cost of the `;`-delimited grammar shared with `Boundary contracts:`. The probe is never executed here; the capture it later produces is `check_runtime_evidence.py`'s business. And the tell list is a blocklist, therefore incomplete.

## Fixtures & self-test

`fixtures/happy/`, `fixtures/uncovered/`, and `fixtures/malformed/` each hold a `requirements.md` (+ `plan.md` and/or `test-report.md`) exercising the pass, gap, and structural-failure paths respectively. Six more cover the lints and annotation handling, each with complete Must-Have coverage (or, in design mode, no coverage computation at all) so the verdict isolates the behaviour under test:

- `fixtures/annotated/` — a requirements.md carrying a struck-through, "superseded by D-x" Must-Have FR; exits **0** with a supersession warning.
- `fixtures/lint-literal-count/` — transcribed inventory counts alongside legitimate unit values; exits **1** on `literal-count` only.
- `fixtures/lint-boundary-contracts/` — an identifier provided by a later task, one provided by no task, and a task with no contracts field; exits **1** on `consumes-provides` only.
- `fixtures/lint-paths/` — absolute path, `file:///` URI, and `../sibling-repo/` reference beside sanctioned repo-relative paths; exits **1** on `path-hygiene` only.
- `fixtures/lint-runtime-criterion/` — a checkpoint whose probe is `npm test -- --grep orders` (condition 4) and a second on a `[vs:api]` milestone whose valid `curl` probe declares no `expect-status:`/`require-keys:` (condition 5); exits **1** on exactly two `runtime-criterion` entries and no sibling lint.
- `fixtures/blocked/` — a `- FR-2: BLOCKED — …` ledger line; exits **1** with `FR-2` in **both** `uncovered` and `blocked`, and no warnings (BLOCKED is status-bearing, so it earns no status-less-mention warning).
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

## check_commit_gate.py

A pure-stdlib CLI (`scripts/check_commit_gate.py`) that makes the `bgpdd-build` milestone commit gate machine-run instead of a manual two-file read: it checks the milestone's latest review verdict, whether that review postdates the diff, and whether the blockers ledger is clean, then — on a pass — performs the commit itself, so a skipped gate is loud (no commit exists) rather than silent.

### Invocation

```bash
python check_commit_gate.py --review-report <path> --state <path> \
    --milestone "<title>" --changed-files <p1> [<p2> ...] \
    [--commit --message "<msg>"] [--repo <dir>] [--ignore-unscoped] \
    [--require-rendered-evidence] [--verify-tree] \
    [--require-runtime-evidence --runtime-report <path> \
     [--surface <key>] [--require-key <name>]... [--expect-status <N>] \
     [--forbid-host <pattern>]... [--require-build-marker <value>] \
     [--require-openapi-reachable] \
     [--openapi-doc <path> --openapi-route <path> [--openapi-method <verb>]]]
python check_commit_gate.py --self-test
```

`--repo` defaults to `.` (the current working directory) when omitted.

### Runtime-evidence delegation

`--require-runtime-evidence` runs `check_runtime_evidence.py` as a **subprocess** on `sys.executable`, folds its exit code into the pass, and surfaces its whole JSON report under `runtime_evidence` with a `runtime_evidence_ok` boolean. Subprocess rather than import: this family has no shared module by convention, and duplicating existence/provenance/freshness/content logic into a second file is the worse cost. The file already shells out for `git`.

**Every assertion flag forwards**, including the OpenAPI pair. That completeness is the point, not a convenience: `bgpdd-build` runs the runtime gate twice — once at Phase 2 where feedback is cheap, and again here — and if the commit-time run accepted a weaker set of assertions than the earlier one, the gate that actually owns the commit would be the more permissive of the two. Same reasoning as `--verify-tree` running here rather than only earlier: **the restraint has to bind at the moment it is least convenient.** Any forwarded flag passed *without* `--require-runtime-evidence` is a usage error (exit 2) rather than a silent no-op, so a typo'd invocation cannot quietly drop an assertion.

`--require-runtime-evidence` without `--runtime-report` is exit 2. With the flag unset, `runtime_evidence` stays `null` and `runtime_evidence_ok` stays `true` — backward compatible.

### JSON output shape

```json
{
  "milestone": "M3 — Auth endpoints",
  "review_report": "<path as given>",
  "state_file": "<path as given>",
  "review_found": true,
  "verdict": "Approve",
  "stale": false,
  "blocking": [],
  "unscoped_blockers": [],
  "rendered_evidence": ["evidence/review/m3-table.png"],
  "rendered_evidence_ok": true,
  "undeclared_changes": [],
  "tree_verified": true,
  "warnings": [],
  "committed": true,
  "result": "PASS",
  "error": null
}
```

### Exit codes

- **0** — gate passed (and a commit was created, when `--commit` was given).
- **1** — gate failed; the JSON body names the cause (`verdict` not `"Approve"`, `stale`, a non-empty `blocking`, an unignored `unscoped_blockers`, `rendered_evidence_ok: false`, `runtime_evidence_ok: false`, or — with `--verify-tree` — `tree_verified: false`).
- **2** — usage error (including a forwarded runtime flag without `--require-runtime-evidence`), an unreadable/missing artifact, invalid state JSON, a git failure, or a structural failure reported by the delegated runtime gate.

### Parsing rules (condensed)

- **Milestone matching**: case-insensitive **word-boundary** match — the full milestone title, OR its leading identifier (the text before the first `:`/`—`), must appear as a whole token (not immediately preceded or followed by an alphanumeric character) against `## Review:` headings in the review report. A bare substring is not enough: `M1` no longer matches a section titled `M10`. The **LAST** matching section wins. Within that section, the **LAST** `**Verdict:**` line wins and must be the exact token `Approve` or `Request Changes`; an unparseable latest line fail-safes to no-verdict rather than falling back to an earlier line.
- **Staleness**: the review report's file mtime must be `>=` every changed file's mtime. This is an mtime **proxy** for "the review postdates the diff" — valid within a single run on one machine, and a documented limitation, not a cryptographic guarantee.
- **Blockers**: orchestrator-state.json's `blockers` array is split into scoped vs. unscoped by the same milestone-token word-boundary match used above (so an `M10:`-prefixed blocker entry no longer scopes to an `M1` gate run). Scoped entries always gate. Unscoped entries gate by default too — the commit gate and `bgpdd-build` §1 (*Blockers precondition*) agree that the `blockers` array must be **empty** (no standing blockers at all) before a milestone commits, on the fail-safe rationale that freeform ledger entries make "not obviously this milestone's" indistinguishable from "not this milestone's". `--ignore-unscoped` remains the sanctioned override for exceptional cases, downgrading unscoped entries to a warning.
- **Rendered evidence**: with `--require-rendered-evidence`, the matched review section must cite at least one evidence file — via a `Rendered evidence:` line or a markdown image ref (`![...](path)`) — that (a) exists, resolved relative to the review report's directory or `--repo`, and (b) is cited under an `evidence/review/` directory (repo-relative or review-report-relative, matching whichever resolution found it). This is the mechanical half of `ui-design-patterns`' "source can fail a check but never pass one" rule. Evidence cited under `evidence/build/` (builder-produced) or any other path does not satisfy the gate, even if the file exists on disk. **Scope limit**: this check proves a cited file exists under `evidence/review/` — it does not prove the reviewer produced it, looked at it, or that it depicts the milestone's actual result; evidence files are not mtime-checked.
- **Working-tree verification (`--verify-tree`)**: `git status --porcelain` in `--repo` is read and every listed path (rename/copy lines take the new path; git-quoted paths are unquoted) is normalized to a repo-relative, forward-slash, case-folded-on-Windows form. That set is compared against the declared `--changed-files` **plus** anything under `.docs/` (pipeline artifacts — test reports, review reports, state, evidence — legitimately change during a milestone without being a builder code change). Any dirty path outside that union is an **undeclared edit**: it is appended to `undeclared_changes`, `tree_verified` becomes `false`, and the gate fails regardless of verdict/staleness/blockers. When the flag is unset, `undeclared_changes` stays `[]` and `tree_verified` stays `true` — the check never runs and the gate's behavior is unchanged (backward compatible).
  - **Directory-shaped porcelain entries.** `git status --porcelain`'s default mode collapses an entirely-untracked directory into a single `?? <dir>/` line rather than listing the files inside it. A porcelain path ending in `/` is parsed as a **directory entry**, not a file, and is normalized with its trailing slash restored before comparison: it is allowed iff that normalized directory is `.docs/` or begins with `.docs/`, **or** at least one declared `--changed-files` path lies under that directory prefix (a declared file's own never-before-tracked directory collapses the same way — the file itself never appears as its own porcelain line). Otherwise it is an undeclared edit, appended to `undeclared_changes` **with its trailing slash preserved** so the report is honest about naming a directory rather than a file. Fixed 2026-08-09: naively normalizing a directory-shaped path (`Path(".docs/").resolve()` strips the trailing slash to `.docs`) broke both the `.docs/` carve-out's `startswith` prefix test and a declared file's own directory match.

`bgpdd-build`'s commit gate references this section as its single contract authority and does not restate these parsing rules inline.

`python scripts/check_commit_gate.py --self-test` runs 35 in-process cases (temp git repos, synthetic `os.utime` ordering rather than the real clock) covering verdict precedence, the `M1`/`M10` word-boundary match, staleness, scoped and unscoped blockers, rendered evidence including the `..`-traversal refusal, `--verify-tree` with its directory-shaped-porcelain cases, the runtime delegation's pass and block paths, the OpenAPI forwarding proven by the same capture passing without the flag and failing with it, every forwarded-flag-without-the-gate-flag usage error, and — the load-bearing one — everything green except runtime evidence with `--commit`, asserting the repo holds **zero** commits afterwards. That last case is what distinguishes a gate that blocks from a gate that merely reports.

## check_agent_report.py

A pure-stdlib CLI (`scripts/check_agent_report.py`) that makes an agent's pass/secure verdict machine-verifiable instead of a face-value handoff read: it gates the durable reports Cipher (`security-report.md`) and Vera (`verification-report.md`) write, checking that the latest verdict-bearing section carries the exact `**Verdict:** Pass` token, that every check line cites its execution evidence (an exit code) or an explicit `NOT RUN`/`BLOCKED` reason, and that no Critical finding stands. This is the same verdict-is-arithmetic-over-findings principle `code-review-and-quality` enforces on Luna's `**Verdict:** Approve`, applied to the Launch Squad's reports. Deliberately terse by design: the evidence contract is command + exit code + counts per line — the gate never requires (and the report must never contain) full scanner output or log dumps.

### Invocation

```bash
python check_agent_report.py --report <path>
python check_agent_report.py --self-test
```

### JSON output shape

```json
{
  "report": "<path as given>",
  "section": "Security Audit: Shipping — 2026-08-11",
  "verdict": "Pass",
  "checks": 5,
  "passed": 5,
  "failed": [],
  "blocked": [],
  "not_run": [],
  "unevidenced": [],
  "critical_findings": 0,
  "warnings": [],
  "result": "PASS",
  "error": null
}
```

### Exit codes

- **0** — gate passed: verdict is exactly `Pass`, at least one check line exists, every check line is `PASS` and evidenced, and zero Critical findings stand.
- **1** — gate failed; the JSON body names the cause (`verdict` not `"Pass"` — including a `Fail` verdict and an unparseable latest verdict token, which fail-safes to no-verdict — a non-empty `failed`/`blocked`/`not_run`/`unevidenced`, a non-zero `critical_findings`, or zero check lines).
- **2** — usage error, a missing/empty/unreadable report, or no `## ` section containing a `**Verdict:**` line (structurally not a conforming agent report).

### Parsing rules (condensed)

- **Gated section**: the report splits on level-2 (`## `) headings; the **LAST** section containing a `**Verdict:**` line is gated — each audit/verification round appends a fresh section, so the last one is the current round (the same last-matching-section rule `check_commit_gate.py` uses). Text before the first `## ` heading is preamble and never gated. Within the section, the **LAST** `**Verdict:**` line wins and must be the exact token `Pass` or `Fail`; an unparseable latest line fail-safes to no-verdict rather than falling back to an earlier line.
- **Check lines**: a list item of the form `- <name>: <STATUS> <rest>` where `<name>` contains no colon and `<STATUS>` — exactly `PASS`, `FAIL`, `BLOCKED`, or `NOT RUN`, uppercase — immediately follows the first colon. Anything else is prose and ignored. Duplicate names within the section deduplicate with **latest mention wins**, mirroring the coverage-ledger convention.
- **Evidence**: a `PASS` or `FAIL` line must cite its exit code (`exit <N>`, case-insensitive, `exit code <N>` tolerated) — the terse proof an execution happened; a `NOT RUN` or `BLOCKED` line must carry a non-empty reason. A line missing either lands in `unevidenced` and fails the gate.
- **Findings**: a list item starting `- **Critical**` in the gated section counts as a standing Critical finding; any count above zero fails the gate regardless of the verdict token. Lower severities (Important, Suggestion, Nit, FYI) are the report author's routing signal, not this gate's.
- **Zero check lines** is a gate failure (exit 1), not a structural error — a report that proves nothing is an evidence failure, not a tool failure (the same rule as test mode's zero status-bearing mentions).

The producer-side grammar lives in `agents/cipher.md` §4 and `agents/vera.md` (Verification Report); `bgpdd-shipping` Step 3 references this section as the single contract authority.

### Fixtures & self-test

- `fixtures/agent-report-happy/` — a `security-report.md` and a `verification-report.md`, all lines evidenced and `PASS`, verdict `Pass`; both exit **0**.
- `fixtures/agent-report-sad/` — a `security-report.md` whose `Pass` verdict stands over a failing scanner, an unevidenced `PASS`, a `NOT RUN` item, and a Critical finding (exit **1**); a `verification-report.md` with an honest `Fail` verdict over FAIL/BLOCKED items (still exit **1** — the gate is green-or-blocked, honesty routes, it does not pass); and `no-verdict.md`, a report with no verdict-bearing section (exit **2**).

`python scripts/check_agent_report.py --self-test` runs a bundled in-process `unittest` suite (temp files) covering the happy path, each failure cause, last-section and last-verdict-line precedence, duplicate-name latest-wins, lowercase-status-is-prose, and the three structural errors.

## check_runtime_evidence.py

A pure-stdlib CLI (`scripts/check_runtime_evidence.py`) that converts `runtime-evidence`'s prose rule — *an in-process observation can fail a wire claim but never pass one* — into an artifact that has to exist on disk. It reads a durable agent report (`test-report.md` in build, `verification-report.md` in shipping), collects its `**Runtime evidence:**` citations, and verifies each cited capture. The failure class it exists to stop: a response envelope green in a `WebApplicationFactory` suite, green in QA prose, and absent from local Swagger.

`runtime-evidence/SKILL.md` owns the capture artifact and citation grammar; this section owns only the CLI contract, and the two do not restate each other.

### Invocation

```bash
python check_runtime_evidence.py --report <path> --milestone "<title>" \
    --changed-files <p1> [<p2> ...] [--repo <dir>] \
    [--surface <key>] [--require-key <name>]... [--expect-status <N>] \
    [--forbid-host <pattern>]... [--require-build-marker <value>] \
    [--min-captures <N>] [--require-openapi-reachable] \
    [--openapi-doc <path> --openapi-route <path> [--openapi-method <verb>]]
python check_runtime_evidence.py --self-test
```

`--report` and `--milestone` are required. `--repo` defaults to `.`. `--min-captures` defaults to `1`. `--require-key` and `--forbid-host` are repeatable.

There is deliberately **no `--allow-stale` / `--ignore-freshness` override** — a divergence from `check_commit_gate.py`'s `--ignore-unscoped` precedent (convention #8), because freshness is the specific gap the observed failure walked through.

`--require-key` and `--forbid-host` are supplied by the **caller**, never declared by the producer: a producer-declared assertion grades itself. Stack-specific keys live in the stack contract (`dotnet-backend-patterns/SKILL.md` names `isSuccess`, `notifications`, `statusCode`); forbidden-host patterns are project-declared, never hardcoded here.

### The OpenAPI flags

**Neither flag opens a socket.** This gate reads artifacts; it never becomes a client. `--require-openapi-reachable` gates the `- OpenAPI: <url> — <status>` header the *probe* wrote, and `--openapi-doc` reads a document the *probe* already fetched and saved. Both prove what the probe reported, not that a contract surface is reachable right now.

`--require-openapi-reachable` rejects a capture whose OpenAPI field is absent, empty, names no `http(s)` URL, names a URL but records no status, or records a non-2xx. The point is not the document — it is that **requiring a contract surface forces the probe at a real application rather than at anything that answers on a port**, and a reachable OpenAPI document is the exact instrument that falsified the 2026-08 claim by hand. Apply it when the surface is `[vs:api]`, the same caller-declares pattern as `--forbid-host`. The URL is cut out of the string before the status is searched for, so `http://localhost:200/swagger.json` does not read as a 200; the separator is not load-bearing (em dash, hyphen, comma, bare space all parse).

`--openapi-doc` + `--openapi-route` (+ `--openapi-method`, default `get`) diffs **declared against observed top-level property names**. Any of the three without its partners is exit 2. Resolution: `paths[route][method].responses` → lowest declared `2xx`, then a `2XX` range key → `content[<json media>].schema`, falling back to Swagger-2.0 `response.schema`. `$ref` resolves **one hop, to `#/components/schemas/<name>` only**. `$ref`s *inside* `properties` values are fine and ignored — only the top-level names are compared, matching `--require-key`'s non-recursive rule.

**Unresolvable is a warning — never a pass and never a fail.** `allOf`/`oneOf`/`anyOf`/`not`/`discriminator`, a second-level `$ref`, a foreign or absent `$ref` target, a non-object or multi-typed schema, empty `properties`, an undeclared route or method, no 2xx response, no JSON media type — each records a reason and leaves `result` untouched. An empty declared set would pass vacuously, so it is refused rather than counted. The diff is also skipped when the capture observed a **non-2xx** status, because a declared 2xx schema does not describe a 400 body. A gate that cannot tell must not pretend either way: this is the same one-directional discipline as the transport tell list, applied to schemas.

**`declared_absent` forces `result: FAIL` independently of `--min-captures`** — the one place this script departs from its uniform "enough accepted captures" pass rule, and a deliberate divergence (convention #8). It was found by the negative-half proof: dropping `dataContext`/`notifications` from the happy fixture's success body still left the 4xx sibling accepted (legitimately schema-skipped), so at `--min-captures 1` the run exited **0** with `declared_absent` populated — the original bug, masked by a sibling. A declared-but-absent property is the contract surface and the runtime contradicting each other, which is not a "this capture isn't good enough" judgment. `observed_undeclared` is informational only: a runtime may legitimately send more than it documents.

**Windows caveat:** Git Bash rewrites `--openapi-route /api/orders` into a filesystem path via MSYS conversion, which silently degrades to a route-not-declared *warning*. Prefix `MSYS_NO_PATHCONV=1`, use PowerShell, or pass `api/orders` — leading-slash normalization handles it.

### JSON output shape

One JSON object on stdout, `indent=2`, stable pre-initialized keys. Top level: `report`, `milestone`, `citations`, `captures`, `accepted`, `rejected`, `missing_keys`, `stale`, `in_process_transport`, `min_captures`, `warnings`, `result`, `error`, plus the OpenAPI set `openapi_unreachable`, `require_openapi_reachable`, `openapi_doc`, `openapi_route`, `openapi_method`, `schema_resolved`, `schema_unresolvable_reason`, `declared_properties`, `declared_absent`, `observed_undeclared`. Each entry in `captures` carries `path`, `exists`, `cited_under_evidence_runtime`, `milestone_match`, `fresh`, `surface`, `transport`, `probe_command`, `status`, `body_parsed`, `body_keys`, `missing_keys`, `build_marker`, `openapi_url`, `openapi_status`, `openapi_reachable`, `schema_compared`, `schema_skipped_reason`, `observed_scope`, `declared_absent`, `observed_undeclared`, and `problems` — empty `problems` means accepted.

Three tri-states carry "not asked" distinctly from "asked and false", so a consumer never reads an unrequested check as a negative result: `openapi_reachable` is `null` when the capture has no OpenAPI field; `schema_compared` is `null` when no diff was requested, `false` when requested-but-skipped, `true` when actually compared; `schema_resolved` is `null` without `--openapi-doc`. Adding the OpenAPI keys was verified to be **purely additive** by diffing old-against-new stdout across all four pre-existing fixtures: every diff line is an addition, zero changed and zero removed.

### Exit codes

- **0** — at least `--min-captures` accepted captures for this milestone **and** `declared_absent` empty.
- **1** — evidence failure: no citation at all, a cited file missing, cited outside `evidence/runtime/`, no capture naming this milestone, stale, an in-process transport, a build/test-runner/search probe, a forbidden host, an empty or unparseable body **when a content assertion was requested**, a missing required key, a status mismatch, a build-marker mismatch, an unreachable/unrecorded OpenAPI document under `--require-openapi-reachable`, or any declared-but-absent schema property. The JSON names the cause per capture.
- **2** — structural/usage: missing `--report`/`--milestone`, an unreadable report, a cited capture that exists but has no `## Captured output` section (structurally not a capture), an incomplete `--openapi-doc`/`--openapi-route`/`--openapi-method` combination, or an `--openapi-doc` that is missing, not valid JSON, or not a JSON object (the error tells the caller to save the JSON form — there is no YAML parser and no dependency to add one).

### Parsing rules (condensed)

- **Citations are collected file-wide; scoping happens capture-side.** Every `**Runtime evidence:**` line in the report contributes comma/whitespace-separated path-shaped tokens. Filtering to this milestone then reads each capture's own `- Milestone:` field, using the same word-boundary token match `check_commit_gate.py` uses (so `M1` never matches `M10`). Rationale: `test-report.md`'s `#Task [N]:` headers are documented human-only, so a machine header there would break Quinn's append-only format. A capture naming a *different* milestone is neither accepted nor rejected — it is not this gate's business.
- **Provenance** is a containment scan over the **cited string**: the segments `evidence/runtime` must appear consecutively with at least one segment after, case-insensitively, backslashes normalized. Deliberately a containment scan rather than `check_commit_gate.py:143`'s prefix anchor, because a capture is legitimately cited either report-relative (`evidence/runtime/x.md`) or with its `.docs/{project}/implementation/` prefix. **Any `..` segment is refused** — that predicate's `lstrip("./")` normalization let `../evidence/review/x.png` collapse to a passing path, and this one does not repeat it. Captures under `evidence/build/` (builder-produced) do not gate.
- **Transport honesty.** `Transport:` and `Probe command:` are scanned for in-process tells and for build/test-runner/search shapes by **word-boundary regex**, so a base URL containing `myorg` does not read as `rg`. A test-runner invocation is not a runtime probe: it proves a suite is green, never that the running system emits this. Two categories:
  - **Framework tells** (`WebApplicationFactory`, `CreateClient(`, `TestServer`, `supertest`, `MockMvc`, `ASGITransport`, `rack-test`, …) and **prose tells** (`in-process`, `direct handler`, `invoked directly`, `same process`, …). The prose set exists because a capture reading `Transport: direct handler call` named no framework and so passed every check — with a well-formed envelope body it was accepted outright. Prose is the weaker signal and does nothing against a misdescribed transport, but the honest author is now caught.
  - **Non-runtime probes**: `dotnet|go|cargo|mvn|gradle build|test`, `npm|pnpm test`, `yarn`, `pytest`, `jest`, `vitest`, `mocha`, `rspec`, `phpunit`, `tsc`, `--noEmit`, `grep`/`rg`, and — added after it escaped — **`node --test`**, which is flag-shaped rather than subcommand-shaped and therefore matched none of the `<tool> test` patterns. `deno|bun|swift|rails|ctest test` went in with it.
  Both tuples are duplicated **verbatim** into `check_coverage.py`'s plan-time lint, with a test asserting byte-equality so the two cannot drift — a widening on one side is a widening on both, by construction.
- **Body extraction** takes the **last balanced JSON object** in `## Captured output` — last, not first, because a probe's output routinely carries a status line and headers first and `run_quiet` merges stderr into the stream. The fence regex matches horizontal whitespace only; a `\s*` there consumes the newline after the opening fence and eats the body's first line (fixed 2026-08-12 — it silently broke `--expect-status` and would have dropped the status line from every capture).
- **`--require-key` checks top-level names only**, satisfiable in the document itself or in its `body` object — **not recursive**, so an `isSuccess` buried inside a payload cannot pass an envelope check.
- **The content assertions are JSON-shaped, and a non-JSON body is not an error.** A capture whose output is CSV, HTML, a redirect, or binary parses to no body and **passes** — `body_parsed: false`, no problems — provided its transport, freshness and (if asserted) status hold. That is deliberate: requiring JSON would block every honest non-JSON surface. The consequence is the real limit — **for a claim about a response header, a `content-type`, an exported file's contents, or rendered HTML, this gate proves that a real out-of-process probe ran and what it returned, but asserts nothing about the bytes.** Reading them is a human step, and on a `ui` surface the rendered-evidence gate is the one that bites. If a non-JSON claim needs to be mechanically enforced, that is a missing assertion flag, not something to fake with `--require-key`.
- **Freshness**: the capture's mtime must be `>=` every `--changed-files` mtime. Omitting `--changed-files` skips the check and reports `fresh: null`.

### Scope limits

Proves a cited capture exists under `evidence/runtime/`, names an out-of-process transport, probes a runtime surface, postdates the diff, and carries the required top-level keys. It does **not** prove the process that answered was the built application, that the base URL was not a stub server, or that the body was not hand-typed (`run_quiet.py --capture` narrows the last by owning the load-bearing fields, but this gate cannot tell whether it was used). Freshness is an **mtime proxy**, the same documented limitation as review staleness. The in-process tell list is a **blocklist and therefore incomplete** — a new framework's in-process client passes until its name is added.

**The largest residual risk, and it is not closed:** in a multi-service estate a service started before the edit and never restarted answers with stale behavior, and its capture is fresh, non-empty, well-formed, and may carry every required key. `--require-build-marker` is the only real closure and it requires the service to echo its build version. Where no service does, this hole stays open and must be understood rather than assumed away.

### Fixtures & self-test

- `fixtures/runtime-evidence-happy/` — a report citing a success capture and its 4xx failure sibling; exit **0** at `--min-captures 2` with `--require-key isSuccess --require-key notifications`.
- `fixtures/runtime-evidence-missing-key/` — **the observed 2026-08 failure.** Honest transport, local host, runtime probe, status 200 — and a bare `{"id":…,"total":…}` body. Exit **1**, `missing_keys: ["isSuccess","notifications"]`.
- `fixtures/runtime-evidence-inprocess/` — a capture whose body *does* carry the envelope but whose transport is `WebApplicationFactory<Program>` and whose probe is `dotnet test`. Exit **1**: the in-process tier cannot pass this claim no matter what its body says.
- `fixtures/runtime-evidence-forbidden-host/` — a real out-of-process probe against the shared **dev** gateway, with `Environment:` recording one service still pointing there. Exit **1** *when invoked with* `--forbid-host dev.internal`; exit **0** without it, because the pattern is project-declared by design.
- `fixtures/runtime-evidence-openapi-unreachable/` — clean transport, local host, status 200, full envelope, and `OpenAPI: …/swagger.json — 404`. Exit **0** bare, **1** with `--require-openapi-reachable`: the only defect is that the contract surface was not there.
- `fixtures/runtime-evidence-schema-mismatch/` — a capture sending `statusCode`/`isSuccess`/`data`/`traceId`, plus **two** saved documents for the same operation. Against `openapi.json` (a one-hop `$ref` to a 5-property `OrderEnvelope`): exit **1**, `declared_absent: ["dataContext","notifications"]`, `observed_undeclared: ["traceId"]`. Against `openapi-composed.json` (the same response expressed with `allOf`): exit **0**, `schema_resolved: false`, and a warning — the warn-never-fail path proven on a real document rather than only in a unit test.
- **Staleness has no fixture on purpose** — mtimes do not survive a clone. It is covered only in `run_self_test()`, using synthetic `os.utime` ordering rather than the real clock (the pattern `check_commit_gate.py` established).

`python scripts/check_runtime_evidence.py --self-test` runs a bundled in-process `unittest` suite (64 cases) covering the happy path, the missing-envelope-key case, key-nested-deeper (must fail) and key-in-`body` (must pass), every in-process tell, test-runner and build probes, the `myorg`-is-not-`rg` word-boundary case, forbidden hosts in both `Base URL:` and `Environment:`, build-marker mismatch and absence, staleness, `evidence/build/` non-gating, `..` refusal, milestone scoping including `M1`/`M10`, the status-line fence regression, empty output, `--min-captures`, the structural exits, and — for the OpenAPI half — the port-is-not-a-status case, separator tolerance, every unresolvable-schema shape as a warning, inline and Swagger-2.0 schemas, `body`-scope comparison, non-recursive nesting, leading-slash normalization, the skip on a non-2xx capture, and the sibling-masking case that made `declared_absent` override `--min-captures`.

## check_acceptance_suite.py

A pure-stdlib CLI (`scripts/check_acceptance_suite.py`) gating the **feature-scoped** walkthrough, one scope up from every other gate here. Per-milestone evidence proves each brick; nothing else proves the wall stands — a feature can be green on every milestone gate and still fail its own journey, because the journey is ordered and stateful and because **inverse operations are never exercised by the milestone that added them** (the milestone that adds mapping has no reason to unmap). Run at `bgpdd-build` Phase 5 before Dep writes the prep ship-decision, and again at `bgpdd-shipping` Stage 1 as regression.

Inputs: Alex's `acceptance-matrix.md` (authored at plan time, derived from requirements — never from what got built) and Quinn's `acceptance-results.md`.

### Invocation

```bash
# Execution mode — gates that the matrix was RUN (build Phase 5, shipping Stage 1)
python check_acceptance_suite.py --matrix <path> --results <path> \
    [--repo <dir>] [--require-priority P0[,P1]] [--min-scenarios <N>]
# Structure mode — gates that the matrix is WELL-FORMED (bgpdd-plan Phase 3.5)
python check_acceptance_suite.py --lint-only --matrix <path> \
    [--requirements <path>] [--min-scenarios <N>]
python check_acceptance_suite.py --self-test
```

`--matrix` and `--results` required. `--repo` defaults to `.`; `--min-scenarios` to `1`. `--require-priority` semantics are **"at or above"**: the gated set is every priority numerically ≤ the max value given, so `P1` alone gates {P0, P1} and a careless value can never skip P0. **Omitting it gates every scenario** — otherwise an all-P1 matrix would pass trivially.

### Structure mode (`--lint-only`)

Two gates, one script, because they read the same grammar and a second file would drift into a shadow contract. `--lint-only` runs at **plan time on Alex's output**, before any code exists and therefore before there is anything to execute.

`--results` **with** `--lint-only` is a usage error (exit 2), not a silent ignore: the two modes answer different questions, and a caller who passes both has misunderstood which one they wanted. `--require-priority` is still validated but **does not scope linting** — structural validity is priority-blind, since a broken scenario is broken at every priority — and passing it emits a warning saying so. `--repo` is accepted and ignored (nothing resolves paths in structure mode, and nothing reads an mtime, so there is no freshness dimension here).

Blocking conditions, each with its own JSON array so the failure is addressable rather than a single boolean:

| Array | Defect |
|---|---|
| `missing_priority` | scenario heading declares no `P0`–`P3` — cannot be execution-scoped honestly |
| `missing_step_table` | no table with `GO`/`DO`/`ASSERT` columns — the scenario proves nothing |
| `missing_columns` | no `Stores` or no `Mode` column |
| `unrecognized_mode` | a `Mode` cell that is neither `auto` nor `manual` |
| `missing_stores` | `DO` reads as state-changing but `Stores` is empty — the inverse check cannot run |
| `duplicate_keys` | a scenario id on two headings, or a step number twice in one scenario — `[inverse of N]` and result keys would both be ambiguous |
| `malformed_steps` | `GO`, `DO` and `ASSERT` all empty — a phantom row |
| `dangling_inverse` | `[inverse of N]` naming a step that does not exist |
| `invalid_exemption` | `[no inverse: …]` with no reason text, or on a step that also declares `[inverse of N]` |
| `undeclared_inverse` | a state-changing step with neither an inverse nor an exemption |
| `lint_failures` | check `fr-scenario-coverage` — a Must-Have FR/NFR cited by no scenario heading (only with `--requirements`) |

**`--requirements <path>` gates the FR→scenario link**, and is accepted **only** with `--lint-only` — passing it in execution mode is exit **2**, the same mode-separation rule `--results`-with-`--lint-only` enforces read from the other end: the link is a plan-time question about the matrix, and answering it says nothing about whether the matrix was run. Must-Have tiers are read with `check_coverage.py`'s parser, duplicated verbatim so the two gates recognize one document convention rather than two dialects; every Must-Have ID must appear in at least one scenario heading's parenthesized requirement list, and each one that does not appends a `lint_failures` entry `{check: "fr-scenario-coverage", task: <ID>, detail: …}` and forces exit **1**. **Should-Haves never gate** — an uncited one lands in `uncovered_should` with an advisory warning. An ID cited by a heading but absent from requirements.md **warns**, matching `check_coverage.py`'s unknown-id path; only FR/NFR-shaped tokens are considered, so a heading citing `EC-2` is not accused of naming an unknown requirement. A requirements file that is unreadable or declares **zero** Must-Haves is exit **2** — same posture as `check_coverage.py`, because a gate with nothing to gate must not report green. Omitting the flag leaves the link unchecked, which is why `bgpdd-plan` Phase 3.5 passes it. Presence in a heading is checkable; whether the scenario *exercises* the requirement is not, and stays with the human reading the matrix.

**`missing_columns` blocks here where execution mode only warns** — a labelled divergence (convention #8). Without `Stores` and `Mode`, the Mode check, the Stores check and the inverse check all silently no-op, so a green lint would mean "nothing was checkable": precisely the failure mode this whole tier exists to close.

**The exemption escape hatch.** `[no inverse: <reason>]` anywhere on the row, case-insensitive, satisfies the inverse requirement. The reason must contain at least one letter — `[no inverse: -]` is refused. **Presence is checkable; truth is not.** The gate cannot know whether "a queued distribution job cannot be un-queued" is true. The marker buys an author nothing except a place to be wrong in writing, where a human reviewer can see it. That is still strictly better than the alternative, which is an inverse silently absent.

Exit codes: **0** enough scenarios and every blocking array empty; **1** any structural defect, any undeclared inverse, any uncited Must-Have, or too few scenarios; **2** `--results` passed alongside `--lint-only`, `--matrix` absent, the matrix missing/unreadable, no parseable scenario, a `--requirements` file that is missing/unreadable or declares no Must-Have, or a bad `--require-priority` token.

### JSON output shape

One `indent=2` object, keys pre-initialized. Top level: `matrix`, `results`, `requirements`, `lint_only`, `require_priority`, `min_scenarios`, `scenarios`, `gated_scenarios`, `steps`, `steps_gated`, `passed`, `failed`, `blocked`, `not_run`, `missing_results`, `unevidenced_manual`, `dangling_inverse`, `undeclared_inverse`, `extra_results`, `warnings`, `result`, `error`, plus the structure-mode set `linted_scenarios`, `exempt_steps`, `invalid_exemption`, `missing_priority`, `missing_step_table`, `missing_columns`, `unrecognized_mode`, `missing_stores`, `duplicate_keys`, `malformed_steps`, and — filled only when `--requirements` is given — `must_have`, `should_have`, `uncovered_should`, `lint_failures`. Each `steps` entry carries `key`, `scenario`, `n`, `mode`, `stores`, `inverse_of`, `state_changing`, `gated`, `priority`, `status`, `detail`, `evidence`, `evidence_ok`, `exempt`, `no_inverse_reason`, `linted`, `problems` — empty `problems` means the step is green. On exit 2 the object is the minimal `{"result": "ERROR", "error": …}` envelope.

**Every key is present in both modes**, so the two reports diff key-for-key and a consumer never branches on key existence: structure mode leaves the execution arrays empty and `results` `null`, execution mode leaves `linted_scenarios` empty. Both modes build step entries through one shared function, so the per-step key set is provably identical — there is a self-test asserting it.

### Exit codes

- **0** — gated scenarios ≥ `--min-scenarios`, at least one gated step had a result, and `missing_results` / `failed` / `blocked` / `not_run` / `unevidenced_manual` / `dangling_inverse` / `missing_step_table` are all empty.
- **1** — any gated step missing a result; any gated result `FAIL`/`BLOCKED`/`NOT RUN`; any gated **manual** step (or unrecognized-mode step) reporting `PASS` without an existing `evidence/runtime/` citation; any **dangling** `[inverse of N]` (at *any* priority); any gated scenario whose step table did not parse; too few gated scenarios; zero gated steps.
- **2** — matrix or results missing/unreadable, results empty, no parseable scenario in the matrix, no parseable result line, `--requirements` passed without `--lint-only`, or a `--require-priority` value that is not a `P0`–`P3` token.

### The results grammar Quinn emits

`acceptance-results.md` reuses `check_agent_report.py`'s check-line grammar, keyed by step:

```
- AS-2.1: PASS — exit 0 — 200, mapping row client A -> slide-c-882
- AS-3.5: PASS — evidence/runtime/as3-5-agent-uninstalled.md — agent absent, service deregistered
```

`- <ScenarioId>.<StepNumber>: <PASS|FAIL|BLOCKED|NOT RUN> — <detail>`. The separator is a **dot**, deliberately not a dash (`AS-2-4` is ambiguous with the id's own dash); a mis-keyed line lands in `extra_results` as a warning while the step it meant to cover lands in `missing_results` as a block, so the mistake fails loud rather than silently binding the wrong step. Step keys are self-describing, so `##` headings in the results file are informational and never parsed — that removes the whole "which section was this result under" scoping problem `test-report.md`'s human-only `#Task [N]:` headers force on other parsers. Duplicate keys: **latest wins**, so a retest appends rather than edits.

### Parsing rules (condensed)

- **Scenario** = a `##` heading containing an id matching `\b[A-Za-z]{1,6}-\d+\b`; priority from `\bP([0-3])\b` in the heading; requirement IDs collected only from **inside parentheses** in the heading, so the scenario's own `AS-2` is never mistaken for a requirement. A scenario with **no** priority token is gated anyway, with a warning — an unprioritized scenario cannot be filtered honestly.
- **Step table** = the first table under the scenario whose header cells include `go`, `do`, and `assert`; columns are looked up **by header name**, so column order is free. `Stores` splits on `, / ; +`.
- **`Mode` fails closed.** `manual` demands evidence, so an unrecognized value must not be the cheaper option: a cell that is present but is neither `auto` nor `manual` — `Manual!`, `semi`, `manual (device)` — is gated **as manual**, with a warning saying it was gated that way because the mode was unrecognized rather than because it declared manual. A blank cell or an absent column still defaults to `auto`; that boundary is deliberate, since retroactively making a pre-`Mode` matrix evidence-bearing would break callers, and `--lint-only` blocks the missing column anyway. Before this, `semi` was silently read as `auto` and a device step citing nothing passed green — verified against the previous revision, not assumed.
- **A gated scenario whose step table does not parse blocks.** One misspelled header cell (`Asserts` for `ASSERT`) drops the entire table, so its steps never enter the step list and can never land in `missing_results`, `not_run` or `unevidenced_manual` — an unevidenced manual device step exited 0/PASS on nothing but a spelling. It now lands in `missing_step_table` in **both** modes. Scoped to *gated* scenarios in execution mode so priority filtering keeps its meaning. This is the same class as `dangling_inverse`, which already blocks in both modes: the artifact misrepresenting its own coverage, not a coverage judgment — and unlike `undeclared_inverse` it rests on no heuristic.
- **`[inverse of N]`** is matched over the whole row line, so placement is free, and resolves **scenario-locally**.
- **Manual evidence** is accepted only if the cited token is path-shaped, passes the same `..`-refusing `evidence/runtime/` containment scan `check_runtime_evidence.py` uses, **and** resolves to an existing file against the results file's directory, then `--repo`, then `.`, then as given.

### Scope limits

Verifies the matrix was **executed and evidenced** — never that a scenario is the *right* scenario, that its ASSERT column asserts the right thing, or that preconditions and ordering were honored; authoring is Alex's judgment and stays reviewable prose. It **never opens** a cited capture beyond an existence check — whether the capture is honest (out-of-process transport, freshness, response keys) is `check_runtime_evidence.py`'s job, and running both is the point. **Auto steps are trusted on their `PASS` token** with no exit code required — deliberately narrower than `check_agent_report.py`, because auto steps are already covered by the per-milestone test and commit gates.

**`undeclared_inverse` blocks under `--lint-only` and stays advisory in execution mode.** A deliberate mode divergence (convention #8), refining the "every state-changing step exercises its inverse" doctrine rather than contradicting it: same signal, opposite posture, because both the cost of the fix and the meaning of green differ by phase.

At **plan time** the matrix *is* the artifact under authorship, the fix is a one-line edit, and there is nothing else green could mean — so it blocks. At **build time** the code is already written, so blocking would ask Quinn to author a scenario Alex owed weeks earlier; the `state_changing` detector rests on a mutating-verb **allowlist** and is knowably incomplete, and a blocking gate built on an incomplete heuristic teaches that green means "the heuristic found nothing"; and legitimate one-way steps exist (nothing un-distributes a queued job, nothing un-reinstalls) — so it warns. A **dangling** `[inverse of N]` blocks in both modes at every priority, because that is the artifact misrepresenting its own coverage rather than a coverage judgment. The consequence of a genuinely missing inverse is still caught and still blocks at build — as `missing_results`, if Alex wrote the step and Quinn didn't run it.

### Fixtures & self-test

`fixtures/acceptance-happy/` (exit **0**), `-missing-inverse/`, `-unevidenced-manual/`, `-notrun/` (exit **1** each) — all four modelling the Slide RMM journey: connect → map → green tick → add policy → distribute → verify installed on device → remove → verify uninstalled → reinstall, across 4 scenarios and 14 steps with 3 manual steps citing real captures. The happy fixture deliberately carries a non-empty `undeclared_inverse` while still exiting 0, which is the proof the advisory is genuinely non-blocking.

**`acceptance-happy` exits 0 in execution mode and 1 under `--lint-only`, and that is correct, not a broken fixture.** It is the mode divergence demonstrated on one unchanged input: the same two uninstall/reinstall steps that are legitimately one-way are tolerated at build time and demanded in writing at plan time. Read it as documentation of the posture change rather than as a defect.

`fixtures/acceptance-lint-inverse/` is structure-mode only — a matrix with no results file and no evidence directory, isolating one signal. Two matrices differing by exactly one marker: `acceptance-matrix.md` exits **1** with `undeclared_inverse: ["AL-2.2"]` (a policy distribution nothing undoes) and every other array empty; `acceptance-matrix-exempt.md` adds `[no inverse: a queued distribution job cannot be un-queued; AL-2.4 removes the policy instead]` and exits **0** with `exempt_steps: ["AL-2.2"]`. The pair is the escape hatch's proof that the blocking path is satisfiable rather than a dead end.

`python scripts/check_acceptance_suite.py --self-test` runs 78 in-process cases covering matrix/results parsing, every blocking condition in both modes, the FR→scenario link (a covered Must-Have, an uncited one naming `fr-scenario-coverage`, an uncited Should-Have that stays green, an unknown cited ID that only warns, a non-FR citation that is not an unknown ID, and both exit-2 paths), the manual-evidence paths (missing file, `evidence/build/` instead of `evidence/runtime/`, `..` traversal, resolution against `--repo`, a `.docs/`-prefixed citation keeping its leading dot), dangling vs undeclared inverses, cross-scenario inverse non-resolution, priority-scope semantics, every structural lint condition, the exemption grammar including the both-markers contradiction and the no-op-on-a-read-only-step warning, the two fail-closed regressions (an unrecognized `Mode`, an unparsed step table) with their ungated/blank-cell boundaries, key parity between the two modes' output, and every exit-2 trigger.

## next_milestone.py

A pure-stdlib CLI (`scripts/next_milestone.py`) that makes "what's the next milestone to build" a mechanical derivation from `plan.md` instead of a full re-read. Real plans reach roughly 290K characters; the Orchestrator Contract's mandated re-reads of the whole file at every hydration and phase-1 entry cost on the order of 73k tokens each. This tool reads the plan once and returns only what the Orchestrator needs to route the next build phase — for roughly 2K tokens.

### Invocation

```bash
python next_milestone.py --plan <path> [--state <path>]
python next_milestone.py --self-test
```

`--plan` is required. `--state` (path to `orchestrator-state.json`) is optional and adds the stale-cursor check; without it the `cursor` field is `null`.

### JSON output shape

```json
{
  "plan_file": "<path as given>",
  "result": "NEXT",
  "next_milestone": {"title": "Milestone 2 — Persistence [API] [vs:api]", "line": 12, "domain": "API", "surface": "api"},
  "milestone_text": "## Milestone 2 — Persistence\n\n## Task 2: ...",
  "remaining": ["Milestone 2 — Persistence", "Milestone 3 — Reporting"],
  "completed_count": 1,
  "total_count": 3,
  "cursor": {"stored": "Milestone 3 — Reporting", "matches_next": false, "stale": true},
  "warnings": [],
  "error": null
}
```

- `result` is `"NEXT"` (a pending milestone was found, with a single clear domain AND a valid verification surface), `"DONE"` (no pending milestone remains — `next_milestone`/`milestone_text` are `null`, `remaining` is `[]`), or `"MIXED"`. **`"MIXED"` is the family name for "the plan cannot be executed as written"**, covering three distinct planning defects: the next pending milestone mixes `[UI]` and `[API]` tags; it is `UNTAGGED`; or its `[vs:<surface>]` verification-surface tag is **missing or unknown**. They share a verdict and exit code because the Orchestrator's action is identical in all three — halt, route back through Alex — and are told apart by the `warnings` entry, not the verdict.
- `next_milestone.surface` is the declared surface key (`api`, `ui`, `web+api`, `rmm`, `fn`, `none`), `null` when no tag was found, or the **raw key verbatim** when one was found but is not valid — so a typo (`[vs:apo]`) is distinguishable from an omission.
- `milestone_text` is the next milestone's full block **verbatim**, from its heading line through the line before the next milestone heading (or EOF) — inject it directly into the delegation brief as the milestone text.
- `cursor` is `null` when `--state` was not given. Otherwise `{"stored", "matches_next", "stale"}`: `stored` is the raw `milestone_cursor` value (string or `null`); `matches_next` is true when the cursor names the derived next milestone; `stale` is true when the cursor names a milestone that appears **later** in plan order than the first pending one — resuming forward from it would silently skip the earlier pending work.
- On a structural/usage error the tool prints only `{"result": "ERROR", "error": "<message>"}` — the other fields are not present.

### Exit codes

- **0** — `result` is `"NEXT"` or `"DONE"`.
- **1** — `result` is `"MIXED"`: a **planning defect** — mixed `[UI]`/`[API]` tags, `UNTAGGED`, or a missing/unknown `[vs:<surface>]` tag. Not a routing decision to improvise past: halt and route back through Alex for re-planning, per `bgpdd-build` Phase 1 step 2. None of the three is ever `NEXT`-with-a-warning.
  - **Migration note.** Every plan authored before the `[vs:]` axis existed reads as a defect on its next pending milestone until re-tagged. That is the intended cost of making the declaration non-omissible: a surface that can be silently left out is a surface that will be. Re-tagging is a one-line edit per milestone heading.
- **2** — usage error (missing `--plan`), an unreadable file, invalid `--state` JSON, a state file missing `milestone_cursor`, or a structural contract failure: **zero `## Milestone <n>` / `### Milestone <n>` headings found in the plan**.

### Parsing rules (condensed)

**Milestone completion is this tool's official convention, and the one the rest of the pipeline follows: a milestone is recorded complete by appending `[x]` (case-insensitive) to its milestone heading line in `plan.md`; a bare heading is pending.** There is no separate per-task checkbox the tool reads — completion is a property of the milestone heading alone.

- **Heading match**: a level-2 **or** level-3 heading of the shape `## Milestone <digit...>` / `### Milestone <digit...>` (regex-anchored: `Milestone` immediately followed by whitespace and a digit) opens a new milestone block. A prose heading like `## Milestone ordering — a stated deviation from the usual sequence` does **not** match — no digit immediately follows "Milestone" — and stays inside whichever milestone block precedes it (or is simply prose if it precedes the first real heading). This is deliberate: it lets a plan discuss "milestone ordering" in prose without the parser mistaking the discussion for a milestone. The canonical writer form, per `planning-and-task-breakdown`, is level-3 (`### Milestone <n> — <Title> [<UI|API>]`); level-2 is tolerated for older plans.
- **Block extent**: a milestone's block runs from its heading line to the FIRST of: the next milestone heading (either level), the next level-2 heading whose text does not start with "Task" or "Checkpoint" (case-insensitive) — this is what ends the task list at a trailing section like `## Risks and Mitigations` or `## Open Questions` — or EOF. Every other heading in between — `## Task N:` headings, `### Checkpoint:` blocks, and a level-2 `## Checkpoint:` heading — stays inside the current milestone's block. The level-2 `## Checkpoint:` form is **deprecated** (the canonical form is level-3, `### Checkpoint:`, which needs no such special-casing since `###` never terminates a block); tolerating it here is a defensive read-side fix, and each occurrence emits a `warnings` entry naming the milestone. The write side (which heading level a plan's author emits) is tracked separately.
- **Domain**: the milestone **heading** line's own `[UI]`/`[API]` tag is authoritative when present (backticks around the tag don't matter). Only when the heading carries neither tag does the tool fall back to scanning the whole block text — including task prose — for `[UI]`/`[API]` tags. Both tags present (on the heading, or via fallback scan) → `"MIXED"`; only `[UI]` → `"UI"`; only `[API]` → `"API"`; neither → `"UNTAGGED"`, which the tool reports as `result: "MIXED"` (exit 1 planning defect) — not NEXT with a warning.
- **Verification surface**: a second, **orthogonal** axis, matched as `[vs:<key>]` with the same heading-wins-then-scan-the-block authority rule. The tag is **lowercase-only by design**: the domain regexes match case-sensitive bracket literals `[UI]`/`[API]`, so `[vs:api]` cannot be mistaken for `[API]` and `[API]` cannot be mistaken for a surface. `web+api` is the one key containing `+`. A heading may legitimately carry both axes: `### Milestone 3 — Order envelope [API] [vs:web+api]`.
- **Next pending**: the first milestone (in file order) whose heading line does **not** contain `[x]`/`[X]`.
- **Stale-cursor verdict**: matching between the stored `milestone_cursor` and milestone titles is a case-insensitive substring test in either direction. If the cursor matches no title at all, that's a warning (`stale`/`matches_next` both `false`), not an error — a hand-edited or freeform cursor string shouldn't crash the tool.

### Fixtures & self-test

`scripts/next_milestone.py --self-test` runs a bundled `unittest` suite in-process (temp plan/state files) covering: happy-path derivation, the prose-heading-not-a-milestone case, all-complete (`DONE`), zero-milestone-headings (`ERROR`), mixed tags (`MIXED`), untagged-as-MIXED, missing-surface and unknown-surface as MIXED, every valid surface key accepted, heading-surface authority over a block mention, surface read from the block when the heading carries none, the `[vs:api]`/`[API]` non-collision in both directions, stale/matching/null/unmatchable cursors, missing/invalid file inputs, a level-3-heading plan with heading-carried domain tags and a trailing `## Risks and Mitigations` section (asserting the last milestone's block excludes it), heading-tag authority over a stray same-tag mention in task prose, heading tags wrapped in backticks, and a deprecated level-2 `## Checkpoint:` heading tolerated inside its milestone block with a warning (contrasted against the canonical level-3 form, which emits none).

## check_ship_decision.py

A pure-stdlib CLI (`scripts/check_ship_decision.py`) that makes Dep's `ship-decision.md` GO/NO-GO machine-verifiable: it requires an unambiguous labeled `GO` or `NO-GO` (Ship Decision / Verdict / Recommendation line), a Rollback heading, and a post-deploy checklist section. Used at `bgpdd-build` Phase 5 step 6 (shape-only, no `--require-go` — a prep NO-GO is a legitimate result), `bgpdd-shipping` Step 0.4 (prep entry ticket: `--require-go` on a fresh run, shape-only on a resume so a NO-GO refresh cannot lock the pipeline out of the stage that resolves it), and Step 3 (refreshed exit ticket after Stage 2 Dep, `--require-go`).

### Invocation

```bash
python check_ship_decision.py --report <path> [--require-go]
python check_ship_decision.py --self-test
```

`--require-go` fails (exit 1) when the latest verdict is `NO-GO` rather than `GO`.

### Exit codes

- **0** — structurally valid decision; with `--require-go`, verdict is `GO`.
- **1** — gate failed (NO-GO under `--require-go`, or incomplete/ambiguous decision content).
- **2** — usage error, missing/empty/unreadable report, or structural non-conformance.

### Parsing rules (condensed)

- **Verdict line**: a line starting (after any `#`/`>`/`-`/`*`/whitespace) with `Ship Decision`, `Verdict` or `Recommendation` and containing the token `GO` or `NO-GO` (`NOGO`/`NO GO` normalize to `NO-GO`).
- **Last-section-wins**: the file is split at markdown headings, and only the **LAST** verdict-bearing section is read. This mirrors `check_agent_report.py` and exists because `bgpdd-shipping` Step 3 instructs the re-verifying agent to **append** a fresh section after a fix round — a Round-2 `GO` must be able to supersede a Round-1 `NO-GO`. Judging ambiguity file-wide made an appended document permanently unpassable.
- **Ambiguity** is still caught *within* the winning section: a section stating both `GO` and `NO-GO` fails, verdict `null`.
- **Rollback**: any heading (levels 1–6) whose text contains "rollback".
- **Checklist**: any heading containing "checklist", **OR** at least 3 `- [ ]`/`- [x]` checkbox items. **Scope limit**: a checklist heading with zero items under it satisfies this check — deliberate parity with `evals/contract/dep-ship-decision-shape` criterion 5, not an oversight. The gate proves a decision is machine-readable, never that its checklist is populated or its verdict correct.
- **Divergence from the eval's `grade.ps1`**: that script counts verdicts file-wide (correct for the single-shot document its prompt produces); this gate scopes to the latest section (required for a pipeline artifact that gets appended to across fix rounds). The two agree on every single-section document.

## check_blockers.py

A pure-stdlib CLI (`scripts/check_blockers.py`) that makes the blockers-ledger gate machine-run: it reads `orchestrator-state.json` and exits non-zero when any standing blocker remains. Used at `bgpdd-shipping` Step 0.5. No manual open-and-read substitute.

### Invocation

```bash
python check_blockers.py --state <path>
python check_blockers.py --self-test
```

### Exit codes

- **0** — `blockers` array is empty.
- **1** — one or more standing blockers (JSON stdout lists them).
- **2** — usage/structural failure (missing state, invalid JSON, missing `blockers` field).

## run_quiet.py

A pure-stdlib CLI (`scripts/run_quiet.py`) that runs a build or test command, writes its **full** merged stdout+stderr to a log file on disk, and prints a short plain-text report to stdout: a header, an error excerpt with surrounding context (only when something matched the built-in error profile), and a tail. It exists so an agent's transcript carries only what it needs to diagnose a failure while nothing is actually lost — the full log is always on disk for selective grepping.

### Invocation

```bash
python run_quiet.py --log <path> [--context N] [--tail N] [--timeout SECONDS] -- <command and args...>
python run_quiet.py --capture <path> [--capture-field Name=value]... [--log <path>] -- <command and args...>
python run_quiet.py --self-test
```

**One of `--log` or `--capture`** is required, plus a command after `--`. Defaults: `--context 5`, `--tail 15`, `--timeout 240` (seconds). Everything after `--` is passed to the child process verbatim (no shell).

### `--capture` — writing a runtime-evidence artifact

`--capture <path>` additionally writes a conforming capture artifact (contract: `runtime-evidence/SKILL.md`), creating parent directories. This exists so the fields a gate reads are **observed, not authored**: `run_quiet.py` stamps the probe command, the UTC timestamp, the real child exit code, the duration, and the captured output itself. `--capture-field Name=value` (repeatable) supplies only the descriptive header — `Title`, `Milestone`, `Requirement IDs`, `Surface`, `Transport`, `Base URL`, `Environment`, `Config repointed`, `Build marker`, `OpenAPI`. A `Title` field becomes the artifact's `# Runtime capture: …` heading.

**A field name the tool owns is rejected, not overwritten**: `Probe command`, `Captured`, `Exit code`, `Duration` and `Log` cannot be supplied via `--capture-field` (compared case-insensitively) — the attempt is a usage error, exit **2**, and no capture is written. That refusal is the integrity property of this mode; without it the flag would be a fabrication vector rather than a defense against one.

The captured output is fenced with a backtick run longer than any inside the output, so a body containing fences cannot break the artifact. `--capture-field` without `--capture` is a usage error. Passing both `--capture` and `--log` writes both and records the log path in the artifact. A timed-out probe still writes a capture, annotated that it records an incomplete observation.

### Report shape (plain text on stdout)

```
command: dotnet test
exit code: 1
duration: 12.34s
full log: .docs/demo/implementation/logs/m3-tests.log
total lines: 842

ERROR EXCERPT (context +/-5 lines):
201: Assert.Equal() Failure
202: Expected: 200
203: Actual: 404
...
... 3 further match(es) omitted (cap ~200 excerpt lines) -- see full log: .docs/demo/implementation/logs/m3-tests.log

TAIL (last 15 lines):
828: Failed!  - Failed: 2, Passed: 40, Skipped: 0
...
```

- The header always carries `command`, `exit code`, `duration`, `full log` (the `--log` path — cite this when pointing an agent at the full record), and `total lines`; a timed-out run adds a `TIMEOUT: exceeded <N>s limit; process tree killed` line.
- `ERROR EXCERPT` appears only when at least one line matches the built-in error profile. Matches are merged into `±context`-line windows (overlapping/touching windows combine into one), each rendered with `<line number>: <text>` prefixes; non-adjacent windows are separated by a lone `...` line. The excerpt is capped at roughly 200 lines total; once the cap would be exceeded, further windows are dropped and a summary line reports how many further matches were omitted and repeats the log path.
- On a clean run (`exit code: 0` and no error-profile matches) the body is simply `no errors detected` instead of an excerpt. On a non-zero exit with no error-profile match, neither `no errors detected` nor an excerpt is printed — the body is empty and the report is just the header followed by the tail.
- `TAIL (last N lines)` is always printed: the last `--tail` lines of the run, numbered the same way.

### Exit codes

- Passthrough of the child process's own exit code on a normal completion.
- **124** — the child was killed for exceeding `--timeout` (best-effort process-tree kill: `taskkill /F /T` on Windows, `SIGKILL` to the process group on POSIX).
- **2** — structural/usage failure: missing `--log`, no command given after `--`, the log file's directory couldn't be created, the log file couldn't be written, or the command itself couldn't be launched (not found / not permitted).

**Windows caveat:** `run_quiet.py` launches the child without a shell, so Python cannot exec a `.cmd`/`.bat` shim. `npx`, `npm`, and `node_modules/.bin/playwright` are shims on Windows — invoke `npx.cmd`/`npm.cmd`, or bypass the shim entirely (`node node_modules/@playwright/test/cli.js`).

### Built-in error profile (condensed)

One combined, case-insensitive regex, grouped by the tool family it targets — word-boundaried so summary lines ("`0 Failed`", "`Tests: 3 failed`") match, not just raw error lines:

- **MSBuild/C#**: `error CS/MSB/NU/NETSDK<digits>` diagnostic codes; `": error "` (the generic compiler line shape).
- **Test failures (cross-runner)**: `Failed!` (dotnet test summary), `FAILED` (generic runner summary), `[FAIL]` (tap/pytest-style), `FAIL ` (jest file line), `Error Message:` (xUnit/NUnit failure block), `Assert.` (assertion frame), `Expected:...Actual:` (assertion diff line, `.` matches across the line).
- **Node**: `ERR!` (npm error prefix), `✖` (mocha/jest failure mark).
- **Generic**: `exception`, `Traceback (most recent call last)` (Python), `fatal`.

### No-information-lost guarantee

The **full** log is always written to `--log`, unabridged, on every run — success or failure. The transcript (stdout) only ever loses *noise*, never *diagnostics*: the excerpt/tail selection narrows what appears in the agent's context window, not what's recoverable. When a failure needs more than the excerpt shows, grep the log file directly rather than re-running the command.

## update_state.py

A pure-stdlib CLI (`scripts/update_state.py`) that is **the sanctioned read-modify-write path for `orchestrator-state.json`**, replacing hand-edits that risk malformed JSON or silent blocker deletion. Every invocation validates the existing file (if any), applies the requested action(s), stamps `updated`, and writes atomically before printing the resulting full state as JSON.

### Invocation

```bash
python update_state.py --state <path> \
    [--init --project-name <name>] \
    [--set-cursor <title|null>] [--set-pipeline <name>] \
    [--set-feature <feature|null>] [--set-branch <name>] \
    [--set-artifact <name>=<path>] \
    [--add-blocker "<text>"] \
    [--resolve-blocker "<substring>" --evidence "<text>"]
python update_state.py --self-test
```

At least one action is required per invocation; any combination may be given in one call.

### Actions

- **`--init --project-name <name>`**: if the state file doesn't exist, creates the skeleton (`schema` version string `"1"`, `project_name`, `feature: null`, `pipeline: ""`, `branch: null`, `milestone_cursor: null`, `artifacts: {}`, `blockers: []`). If the file already exists, `--init` is a **no-op** (a warning is emitted, the existing content is untouched) — other actions in the same call still apply. `--init` without `--project-name` is a usage error.
- **`--set-cursor <title|null>`**: sets `milestone_cursor`. The **literal string `null`** (not the shell's `NULL`/empty string) sets the JSON field to `null`; any other value sets it verbatim as a string.
- **`--set-pipeline <name>`** / **`--set-branch <name>`** / **`--set-feature <feature|null>`**: set those fields verbatim (`null` literal clears `feature`).
- **`--set-artifact <name>=<path>`** (repeatable): merges `name: path` into the `artifacts` object. The **literal value `null`** (`design=null`) stores JSON `null`, same rule as `--set-cursor` and `--set-feature` — `bgpdd-lite` emits exactly that when no stack-contract skill governs, and `bgpdd-build`'s "inject `artifacts.design` when non-null" rule would otherwise treat the truthy string `"null"` as a path. A spec with no `=` is a usage error.
- **`--add-blocker "<text>"`** (repeatable): appends each text verbatim to `blockers`, preserving existing entries.
- **`--resolve-blocker "<substring>" --evidence "<text>"`**: removes every `blockers` entry containing `substring` (case-insensitive). **`--evidence` is required and must be non-empty** — omitting it is a usage error, not a silent no-op. A substring matching nothing is not an error: `blockers` is left unchanged and a warning is emitted.

### Output & persistence

- The write is **atomic**: a temp file is written in the same directory (`tempfile.mkstemp`) and swapped into place with `os.replace`. `updated` (UTC ISO-8601, `YYYY-MM-DDTHH:MM:SSZ`) is stamped on every successful write, even one that only resolves a blocker.
- stdout is always the resulting **full state JSON** (indent 2) on success. Warnings (no-op `--init`, a `--resolve-blocker` that matched nothing) go to **stderr** as `Warning: ...` lines, never stdout — stdout stays parseable.

### Exit codes

- **0** — the action(s) applied and the file was written.
- **2** — usage/structural failure: missing `--state`, no action given, `--init` without `--project-name`, `--resolve-blocker` without (non-empty) `--evidence`, an invalid `--set-artifact` spec, the state file is not valid JSON or not a JSON object, or the state file doesn't exist and `--init` wasn't given.

### The ledger rule this mechanizes

Orchestrator Contract §4's blocker-ledger doctrine — **an entry is removed only once its fix is verified** — is enforced here, not just documented: the CLI physically refuses `--resolve-blocker` without a stated `--evidence` string. And every successful removal appends one line per removed entry to a **`blockers-resolved.log`** file beside the state file (`<ISO timestamp>\t<removed entry text>\t<evidence text>`), so a removal always leaves an audit trace even though the state file itself only ever shows the current, post-removal `blockers` array.

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
