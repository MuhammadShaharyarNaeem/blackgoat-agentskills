---
name: pipeline-tools
description: "Deterministic stdlib-Python CLI family for the PDD pipelines: check_coverage.py verifies every Must-Have FR/NFR in requirements.md is covered by plan.md tasks, by passing tests in test-report.md, or by an in-place supersession annotation in detailed-design.md; check_commit_gate.py makes the bgpdd-build milestone commit gate machine-run (verdict, staleness, blockers, optional working-tree verification) and can perform the commit itself on a pass; check_agent_report.py verifies a durable agent report (Cipher's security-report.md, Vera's verification-report.md) backs its Pass verdict with evidenced check lines and zero Critical findings; next_milestone.py derives the next pending milestone from plan.md without a full re-read; run_quiet.py runs builds/tests, logging the full output to disk and surfacing only errors-with-context and a tail; update_state.py is the sanctioned read-modify-write path for orchestrator-state.json; and check_dependency_tables.py statically validates every agent's Methodology Dependencies table. Squad-internal: executed by the Orchestrator directly at the bgpdd pipeline gates, not delegated to agents."
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
- Inside it, `consumes:` and `provides:` keywords (case-insensitive) each introduce a comma-separated identifier list terminated by `;`, a newline, the next keyword, or the first **sentence break** within the line — a `. ` (period followed by whitespace) or a ` — ` (space-emdash-space). This last terminator exists because a machine line is sometimes followed by explanatory prose on the same physical line ("`consumes: none. The ruling is read by Tasks 3, 4, 5.`"); without it, the prose's own commas comma-split into fake identifiers (an observed run produced `4`, `5`, and `not` this way). An identifier's internal dots (`api.mode.ruling`) are never followed by whitespace, so `. ` is safe to use as a terminator without truncating real identifiers. Both keywords may appear in either order, more than once.
- **A single keyword's identifier list terminates at a newline as well as at `;`.** The *field* may span continuation lines, but a *wrapped list* silently contributes only its first line — the gate then reports a missing provider for identifiers the author can plainly see in the file. Authors: keep each keyword's list on one physical line, opening a second `provides:` keyword on the next line rather than wrapping one. Readers of a surprising verdict: before re-doing any work, re-read the raw field and look for a wrap — **a `lint_failures` entry naming an identifier that is visibly present is a format mismatch, not a missing dependency.**
- An identifier is the first `[A-Za-z0-9_./-]` token of each comma-separated part, so backticks and trailing parentheticals are tolerated. Matching is case-insensitive. Leading/trailing `.`, `/`, and `-` characters are stripped from that token before comparison. `none` / `n/a` / `-` / `tbd` are empty values.
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

## check_commit_gate.py

A pure-stdlib CLI (`scripts/check_commit_gate.py`) that makes the `bgpdd-build` milestone commit gate machine-run instead of a manual two-file read: it checks the milestone's latest review verdict, whether that review postdates the diff, and whether the blockers ledger is clean, then — on a pass — performs the commit itself, so a skipped gate is loud (no commit exists) rather than silent.

### Invocation

```bash
python check_commit_gate.py --review-report <path> --state <path> \
    --milestone "<title>" --changed-files <p1> [<p2> ...] \
    [--commit --message "<msg>"] [--repo <dir>] [--ignore-unscoped] \
    [--require-rendered-evidence] [--verify-tree]
python check_commit_gate.py --self-test
```

`--repo` defaults to `.` (the current working directory) when omitted.

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
- **1** — gate failed; the JSON body names the cause (`verdict` not `"Approve"`, `stale`, a non-empty `blocking`, an unignored `unscoped_blockers`, `rendered_evidence_ok: false`, or — with `--verify-tree` — `tree_verified: false`).
- **2** — usage error, an unreadable/missing artifact, invalid state JSON, or a git failure.

### Parsing rules (condensed)

- **Milestone matching**: case-insensitive **word-boundary** match — the full milestone title, OR its leading identifier (the text before the first `:`/`—`), must appear as a whole token (not immediately preceded or followed by an alphanumeric character) against `## Review:` headings in the review report. A bare substring is not enough: `M1` no longer matches a section titled `M10`. The **LAST** matching section wins. Within that section, the **LAST** `**Verdict:**` line wins and must be the exact token `Approve` or `Request Changes`; an unparseable latest line fail-safes to no-verdict rather than falling back to an earlier line.
- **Staleness**: the review report's file mtime must be `>=` every changed file's mtime. This is an mtime **proxy** for "the review postdates the diff" — valid within a single run on one machine, and a documented limitation, not a cryptographic guarantee.
- **Blockers**: orchestrator-state.json's `blockers` array is split into scoped vs. unscoped by the same milestone-token word-boundary match used above (so an `M10:`-prefixed blocker entry no longer scopes to an `M1` gate run). Scoped entries always gate. **Deliberate divergence**: unscoped entries gate by default too — deliberately **tighter** than `bgpdd-build` §1's "no entries scoped to this milestone" wording, on the fail-safe rationale that freeform ledger entries make "not obviously this milestone's" indistinguishable from "not this milestone's". `--ignore-unscoped` is the sanctioned override, downgrading unscoped entries to a warning.
- **Rendered evidence**: with `--require-rendered-evidence`, the matched review section must cite at least one evidence file — via a `Rendered evidence:` line or a markdown image ref (`![...](path)`) — that (a) exists, resolved relative to the review report's directory or `--repo`, and (b) is cited under an `evidence/review/` directory (repo-relative or review-report-relative, matching whichever resolution found it). This is the mechanical half of `ui-design-patterns`' "source can fail a check but never pass one" rule. Evidence cited under `evidence/build/` (builder-produced) or any other path does not satisfy the gate, even if the file exists on disk. **Scope limit**: this check proves a cited file exists under `evidence/review/` — it does not prove the reviewer produced it, looked at it, or that it depicts the milestone's actual result; evidence files are not mtime-checked.
- **Working-tree verification (`--verify-tree`)**: `git status --porcelain` in `--repo` is read and every listed path (rename/copy lines take the new path; git-quoted paths are unquoted) is normalized to a repo-relative, forward-slash, case-folded-on-Windows form. That set is compared against the declared `--changed-files` **plus** anything under `.docs/` (pipeline artifacts — test reports, review reports, state, evidence — legitimately change during a milestone without being a builder code change). Any dirty path outside that union is an **undeclared edit**: it is appended to `undeclared_changes`, `tree_verified` becomes `false`, and the gate fails regardless of verdict/staleness/blockers. When the flag is unset, `undeclared_changes` stays `[]` and `tree_verified` stays `true` — the check never runs and the gate's behavior is unchanged (backward compatible).
  - **Directory-shaped porcelain entries.** `git status --porcelain`'s default mode collapses an entirely-untracked directory into a single `?? <dir>/` line rather than listing the files inside it. A porcelain path ending in `/` is parsed as a **directory entry**, not a file, and is normalized with its trailing slash restored before comparison: it is allowed iff that normalized directory is `.docs/` or begins with `.docs/`, **or** at least one declared `--changed-files` path lies under that directory prefix (a declared file's own never-before-tracked directory collapses the same way — the file itself never appears as its own porcelain line). Otherwise it is an undeclared edit, appended to `undeclared_changes` **with its trailing slash preserved** so the report is honest about naming a directory rather than a file. Fixed 2026-08-09: naively normalizing a directory-shaped path (`Path(".docs/").resolve()` strips the trailing slash to `.docs`) broke both the `.docs/` carve-out's `startswith` prefix test and a declared file's own directory match.

`bgpdd-build`'s commit gate references this section as its single contract authority and does not restate these parsing rules inline.

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
  "next_milestone": {"title": "Milestone 2 — Persistence", "line": 12, "domain": "API"},
  "milestone_text": "## Milestone 2 — Persistence\n\n## Task 2: ...",
  "remaining": ["Milestone 2 — Persistence", "Milestone 3 — Reporting"],
  "completed_count": 1,
  "total_count": 3,
  "cursor": {"stored": "Milestone 3 — Reporting", "matches_next": false, "stale": true},
  "warnings": [],
  "error": null
}
```

- `result` is `"NEXT"` (a pending milestone was found), `"DONE"` (no pending milestone remains — `next_milestone`/`milestone_text` are `null`, `remaining` is `[]`), or `"MIXED"` (the next pending milestone's tasks mix `[UI]` and `[API]` tags — a planning defect).
- `milestone_text` is the next milestone's full block **verbatim**, from its heading line through the line before the next milestone heading (or EOF) — inject it directly into the delegation brief as the milestone text.
- `cursor` is `null` when `--state` was not given. Otherwise `{"stored", "matches_next", "stale"}`: `stored` is the raw `milestone_cursor` value (string or `null`); `matches_next` is true when the cursor names the derived next milestone; `stale` is true when the cursor names a milestone that appears **later** in plan order than the first pending one — resuming forward from it would silently skip the earlier pending work.
- On a structural/usage error the tool prints only `{"result": "ERROR", "error": "<message>"}` — the other fields are not present.

### Exit codes

- **0** — `result` is `"NEXT"` or `"DONE"`.
- **1** — `result` is `"MIXED"`: the next pending milestone mixes `[UI]` and `[API]` task tags. This is a **planning defect**, not a routing decision to improvise past — halt and route back through Alex for re-planning, per `bgpdd-build` Phase 1 step 2.
- **2** — usage error (missing `--plan`), an unreadable file, invalid `--state` JSON, a state file missing `milestone_cursor`, or a structural contract failure: **zero `## Milestone <n>` / `### Milestone <n>` headings found in the plan**.

### Parsing rules (condensed)

**Milestone completion is this tool's official convention, and the one the rest of the pipeline follows: a milestone is recorded complete by appending `[x]` (case-insensitive) to its milestone heading line in `plan.md`; a bare heading is pending.** There is no separate per-task checkbox the tool reads — completion is a property of the milestone heading alone.

- **Heading match**: a level-2 **or** level-3 heading of the shape `## Milestone <digit...>` / `### Milestone <digit...>` (regex-anchored: `Milestone` immediately followed by whitespace and a digit) opens a new milestone block. A prose heading like `## Milestone ordering — a stated deviation from the usual sequence` does **not** match — no digit immediately follows "Milestone" — and stays inside whichever milestone block precedes it (or is simply prose if it precedes the first real heading). This is deliberate: it lets a plan discuss "milestone ordering" in prose without the parser mistaking the discussion for a milestone. The canonical writer form, per `planning-and-task-breakdown`, is level-3 (`### Milestone <n> — <Title> [<UI|API>]`); level-2 is tolerated for older plans.
- **Block extent**: a milestone's block runs from its heading line to the FIRST of: the next milestone heading (either level), the next level-2 heading whose text does not start with "Task" or "Checkpoint" (case-insensitive) — this is what ends the task list at a trailing section like `## Risks and Mitigations` or `## Open Questions` — or EOF. Every other heading in between — `## Task N:` headings, `### Checkpoint:` blocks, and a level-2 `## Checkpoint:` heading — stays inside the current milestone's block. The level-2 `## Checkpoint:` form is **deprecated** (the canonical form is level-3, `### Checkpoint:`, which needs no such special-casing since `###` never terminates a block); tolerating it here is a defensive read-side fix, and each occurrence emits a `warnings` entry naming the milestone. The write side (which heading level a plan's author emits) is tracked separately.
- **Domain**: the milestone **heading** line's own `[UI]`/`[API]` tag is authoritative when present (backticks around the tag don't matter). Only when the heading carries neither tag does the tool fall back to scanning the whole block text — including task prose — for `[UI]`/`[API]` tags. Both tags present (on the heading, or via fallback scan) → `"MIXED"`; only `[UI]` → `"UI"`; only `[API]` → `"API"`; neither → `"UNTAGGED"` (still `result: "NEXT"`, but with a warning — the milestone can still be routed, just not automatically).
- **Next pending**: the first milestone (in file order) whose heading line does **not** contain `[x]`/`[X]`.
- **Stale-cursor verdict**: matching between the stored `milestone_cursor` and milestone titles is a case-insensitive substring test in either direction. If the cursor matches no title at all, that's a warning (`stale`/`matches_next` both `false`), not an error — a hand-edited or freeform cursor string shouldn't crash the tool.

### Fixtures & self-test

`scripts/next_milestone.py --self-test` runs a bundled `unittest` suite in-process (temp plan/state files) covering: happy-path derivation, the prose-heading-not-a-milestone case, all-complete (`DONE`), zero-milestone-headings (`ERROR`), mixed tags (`MIXED`), untagged-with-warning, stale/matching/null/unmatchable cursors, missing/invalid file inputs, a level-3-heading plan with heading-carried domain tags and a trailing `## Risks and Mitigations` section (asserting the last milestone's block excludes it), heading-tag authority over a stray same-tag mention in task prose, heading tags wrapped in backticks, and a deprecated level-2 `## Checkpoint:` heading tolerated inside its milestone block with a warning (contrasted against the canonical level-3 form, which emits none).

## run_quiet.py

A pure-stdlib CLI (`scripts/run_quiet.py`) that runs a build or test command, writes its **full** merged stdout+stderr to a log file on disk, and prints a short plain-text report to stdout: a header, an error excerpt with surrounding context (only when something matched the built-in error profile), and a tail. It exists so an agent's transcript carries only what it needs to diagnose a failure while nothing is actually lost — the full log is always on disk for selective grepping.

### Invocation

```bash
python run_quiet.py --log <path> [--context N] [--tail N] [--timeout SECONDS] -- <command and args...>
python run_quiet.py --self-test
```

`--log` and a command after `--` are both required. Defaults: `--context 5`, `--tail 15`, `--timeout 240` (seconds). Everything after `--` is passed to the child process verbatim (no shell).

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
    [--set-branch <name>] [--set-artifact <name>=<path>] \
    [--add-blocker "<text>"] \
    [--resolve-blocker "<substring>" --evidence "<text>"]
python update_state.py --self-test
```

At least one action is required per invocation; any combination may be given in one call.

### Actions

- **`--init --project-name <name>`**: if the state file doesn't exist, creates the skeleton (`schema`, `project_name`, `feature: null`, `pipeline: ""`, `branch: null`, `milestone_cursor: null`, `artifacts: {}`, `blockers: []`). If the file already exists, `--init` is a **no-op** (a warning is emitted, the existing content is untouched) — other actions in the same call still apply. `--init` without `--project-name` is a usage error.
- **`--set-cursor <title|null>`**: sets `milestone_cursor`. The **literal string `null`** (not the shell's `NULL`/empty string) sets the JSON field to `null`; any other value sets it verbatim as a string.
- **`--set-pipeline <name>`** / **`--set-branch <name>`**: set those fields verbatim.
- **`--set-artifact <name>=<path>`** (repeatable): merges `name: path` into the `artifacts` object. A spec with no `=` is a usage error.
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
