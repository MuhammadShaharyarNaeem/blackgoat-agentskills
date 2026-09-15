# check_commit_gate.py — reference

Depth for the `check_commit_gate.py` section of `../SKILL.md`: the runtime-evidence delegation rationale, the parsing rules, and the self-test inventory.

### Runtime-evidence delegation

`--require-runtime-evidence` runs `check_runtime_evidence.py` as a **subprocess** on `sys.executable`, folds its exit code into the pass, and surfaces its whole JSON report under `runtime_evidence` with a `runtime_evidence_ok` boolean. Subprocess rather than import: this family has no shared module by convention, and duplicating existence/provenance/freshness/content logic into a second file is the worse cost. The file already shells out for `git`.

**Every assertion flag forwards**, including the OpenAPI pair. That completeness is the point, not a convenience: `bgpdd-build` runs the runtime gate twice — once at Phase 2 where feedback is cheap, and again here — and if the commit-time run accepted a weaker set of assertions than the earlier one, the gate that actually owns the commit would be the more permissive of the two. Same reasoning as `--verify-tree` running here rather than only earlier: **the restraint has to bind at the moment it is least convenient.** Any forwarded flag passed *without* `--require-runtime-evidence` is a usage error (exit 2) rather than a silent no-op, so a typo'd invocation cannot quietly drop an assertion.

`--require-runtime-evidence` without `--runtime-report` is exit 2. With the flag unset, `runtime_evidence` stays `null` and `runtime_evidence_ok` stays `true` — backward compatible.

### `already_committed`

With `--commit`, the gate first asks whether any declared `--changed-files` path still differs from HEAD. If none does, the change was already committed **outside this gate** — a builder committing its own fix, or a hand commit — so the gate fails (`already_committed: true`, exit 1) rather than reporting a vacuous pass over work it never gated. The remedy is in the warning text: reset the outside commit keeping the tree, then re-run. It sits in `../SKILL.md`'s JSON-key list beside `size_ok`; it was absent from both lists until the 2026-09 audit, which is how a key that can single-handedly fail the gate went undocumented.

### Parsing rules (condensed)

- **Milestone matching**: case-insensitive **word-boundary** match — the full milestone title, OR its leading identifier (the text before the first `:`/`—`), must appear as a whole token (not immediately preceded or followed by an alphanumeric character) against `## Review:` headings in the review report. A bare substring is not enough: `M1` no longer matches a section titled `M10`. The **LAST** matching section wins. Within that section, the **LAST** `**Verdict:**` line wins and must be the exact token `Approve` or `Request Changes`; an unparseable latest line fail-safes to no-verdict rather than falling back to an earlier line.
- **Staleness**: the review report's file mtime must be `>=` every changed file's mtime. This is an mtime **proxy** for "the review postdates the diff" — valid within a single run on one machine, and a documented limitation, not a cryptographic guarantee.
- **Blockers**: every entry in orchestrator-state.json's `blockers` array is normalized to the structured schema (`check_blockers.md` owns that schema and the migration rationale; the helper is **duplicated** here rather than shared, per this family's no-shared-module convention) and then split three ways by **exact equality** on its `milestone` field. Scoped to this milestone → `blocking`, always gates. `milestone: null` → `unscoped_blockers`, gates by default on the fail-safe rationale that an entry stating no scope may well be this milestone's; `--ignore-unscoped` remains the sanctioned override, downgrading them to a warning and naming them in `ignored_unscoped_ids` so the waiver lands in the JSON rather than only in the invocation. Scoped to a *different* milestone → `other_milestone_blockers`, never gates. `Info` severity never blocks, and that floor is **deliberately not caller-tunable here** (convention #8, diverging from `check_blockers.py --severity-floor`): this is the last checkpoint before a commit, and the party running it is the party the gate restrains.
  - **What changed and why.** Scoping used to be the same word-boundary token match the review-report parser uses, applied to freeform blocker text. That made "not obviously this milestone's" indistinguishable from "not this milestone's", so the honest reading was to gate on the whole array — and a blocker raised against `M7` could hold `M2`'s commit hostage. The structured `milestone` field replaces the guess; the fail-safe survives exactly where the writer stated nothing. `bgpdd-build` §1's *Blockers precondition* is worded to match.
- **Rendered evidence**: with `--require-rendered-evidence`, the matched review section must cite at least one evidence file — via a `Rendered evidence:` line or a markdown image ref (`![...](path)`) — that (a) exists, resolved relative to the review report's directory or `--repo`, and (b) is cited under an `evidence/review/` directory (repo-relative or review-report-relative, matching whichever resolution found it). This is the mechanical half of `ui-design-patterns`' "source can fail a check but never pass one" rule. Evidence cited under `evidence/build/` (builder-produced) or any other path does not satisfy the gate, even if the file exists on disk. **Scope limit**: this check proves a cited file exists under `evidence/review/` — it does not prove the reviewer produced it, looked at it, or that it depicts the milestone's actual result; evidence files are not mtime-checked.
- **Working-tree verification (`--verify-tree`)**: `git status --porcelain` in `--repo` is read and every listed path (rename/copy lines take the new path; git-quoted paths are unquoted) is normalized to a repo-relative, forward-slash, case-folded-on-Windows form. That set is compared against the declared `--changed-files` **plus** anything under `.docs/` (pipeline artifacts — test reports, review reports, state, evidence — legitimately change during a milestone without being a builder code change). Any dirty path outside that union is an **undeclared edit**: it is appended to `undeclared_changes`, `tree_verified` becomes `false`, and the gate fails regardless of verdict/staleness/blockers. When the flag is unset, `undeclared_changes` stays `[]` and `tree_verified` stays `true` — the check never runs and the gate's behavior is unchanged (backward compatible).
  - **Directory-shaped porcelain entries.** `git status --porcelain`'s default mode collapses an entirely-untracked directory into a single `?? <dir>/` line rather than listing the files inside it. A porcelain path ending in `/` is parsed as a **directory entry**, not a file, and is normalized with its trailing slash restored before comparison: it is allowed iff that normalized directory is `.docs/` or begins with `.docs/`, **or** at least one declared `--changed-files` path lies under that directory prefix (a declared file's own never-before-tracked directory collapses the same way — the file itself never appears as its own porcelain line). Otherwise it is an undeclared edit, appended to `undeclared_changes` **with its trailing slash preserved** so the report is honest about naming a directory rather than a file. Fixed 2026-08-09: naively normalizing a directory-shaped path (`Path(".docs/").resolve()` strips the trailing slash to `.docs`) broke both the `.docs/` carve-out's `startswith` prefix test and a declared file's own directory match.

`bgpdd-build`'s commit gate references this section as its single contract authority and does not restate these parsing rules inline.

`python scripts/check_commit_gate.py --self-test` runs 62 in-process cases (the ledger, the three-way blocker split and the `--ignore-unscoped` id report, `--require-ledger-gates`, section boundaries, ambiguous review titles and the rendered-evidence magic-byte checks among them) (temp git repos, synthetic `os.utime` ordering rather than the real clock) covering verdict precedence, the `M1`/`M10` word-boundary match, staleness, scoped and unscoped blockers, rendered evidence including the `..`-traversal refusal, `--verify-tree` with its directory-shaped-porcelain cases, the runtime delegation's pass and block paths, the OpenAPI forwarding proven by the same capture passing without the flag and failing with it, every forwarded-flag-without-the-gate-flag usage error, and — the load-bearing one — everything green except runtime evidence with `--commit`, asserting the repo holds **zero** commits afterwards. That last case is what distinguishes a gate that blocks from a gate that merely reports.

## Section boundaries, ambiguity, and the ledger gate (P2b)

**Why any level-2-to-6 heading closes a `## Review:` section.** Closing only on `## ` let a `### Addendum` carrying its own `**Verdict:** Approve` override the `Request Changes` above it — the latest-verdict-line-wins rule, applied across a boundary that was not being enforced, turned an appended note into a re-approval. **Migration**: a verdict line must appear BEFORE any subheading inside its review section, or the section reads as no-verdict and fails closed. `code-review-and-quality/SKILL.md`'s report template carries the same rule on the producer side.

**`ambiguous_review_section`** exists because a section titled `## Review: M1 M2 M3` matches three gates by word boundary and answers for all of them with one verdict. Naming more than one distinct milestone id in a review heading is now exit 1 rather than a silently over-broad approval.

**`--require-ledger-gates`** is the closure on gate-ordering: it is not enough that a sibling gate exists, it must have RUN, PASSED, and passed over the same bytes. For each named gate the LATEST ledger entry whose `gate` matches and whose `milestone` is this one or null must record `PASS` **and** every input it hashed must still hash the same on disk (`ledger_stale` otherwise). Without the re-hash, a gate run before the last three commits would still vouch for them.

**Forwarding by capability probe.** `--ledger` and `--allow-missing-sidecar` forward to `check_runtime_evidence.py` only when that script's source declares them, so an older sibling in the same directory degrades rather than crashing. `--allow-missing-sidecar` without `--require-runtime-evidence` is exit 2, the same anti-typo rule every other forwarded flag follows.

## The ledger chain is a precondition, not a term

`--require-ledger-gates` verifies the ledger's hash chain **before** it looks at a single verdict, and returns one `ledger_chain_broken` problem instead of a per-gate list. The ordering is the point: naming which gate recorded a PASS is meaningless when the file the PASS was read out of has been edited. The route on that code is `check_ledger.py --ledger <path>` — which names the line — and then the user. There is no flag to proceed over it, deliberately: a broken chain is either a real tamper or a tool in this family that appended without chaining, and both are things somebody has to look at.

## `--require-run-log` / `--require-agents` — did the delegation happen?

The gate's original terms all read the *products* of the build: a review report, a state file, a diff, a capture. Every one of them can exist without the delegation that was supposed to produce it, because the Orchestrator writes the report path into the brief and reads the result back. The observed hole: a milestone whose Quinn or Luna round was skipped outright leaves a green `review-report.md` and an **empty run log**, and the gate passed on the report alone.

`record_run.py` already refuses to write a delegation record without `--model`, which makes the run log a usable witness: a delegation record with a null model was hand-written, and a hand-written record is not evidence a delegation occurred. So the gate asks for a record per named agent, scoped to this milestone's `unit`, with a model on it.

**Scoping is exact on `unit`, and that is deliberately tighter than `--require-ledger-gates`'s "this milestone or unscoped"** (convention #8). A gate ledger line legitimately covers a whole epic — `check_coverage.py` runs once. A *delegation* with no unit does not say which milestone it built, and accepting it would let one recorded Luna round vouch for every milestone in the plan.

**What it does not prove.** That the agent did good work, or that the model tier was right (`record_run.py`'s own `verifier_below_producer` check owns that), or that the record was written at the time it claims. It proves the Orchestrator ran the phase and recorded it, which is exactly the step that was being skipped.

## What `--require-agents` proves, and what it does not (2.6.1)

Documented here and beside the flag because the 2026-09-07 audit found it
documented nowhere -- while the CAPTURE half of the same forgery is documented
(`references/check_red_green.md` Scope limits, and `../SKILL.md` The
unkeyed-sidecar limit). That asymmetry made the run-log half read as a term
with teeth.

**The run log is AUTHORED, not tool-provenanced.** `record_run.py` writes
nothing a person cannot type: its records carry no hash of anything observed,
no capture, and no chain. Contrast `gates.jsonl`, whose entries this gate
verifies by RE-HASHING every input the recorded run read -- that is what
`ledger_stale` is, and it does bite: editing a reviewed file after the
coverage record was written flips the same invocation to exit 1.

So `--require-run-log` + `--require-agents` proves that a delegation record
EXISTS, is scoped to this milestone, and names a resolvable tier. It does not
prove the delegation happened. Anyone who fabricates the run log satisfies it,
and the audit demonstrated exactly that: a scratch repo whose entire evidence
base was authored passed `--require-rendered-evidence --verify-tree
--max-changed-files 3 --require-runtime-evidence --require-ledger-gates ...
--require-run-log ... --require-agents mason,quinn,luna --commit` and
committed.

**What the flag is still worth**, in the same framing the ledger's own limit
uses: skipping a Quinn or Luna round becomes an OMISSION somebody has to
notice rather than an invisible non-event, and faking one becomes a written
act. Closing it further needs a provenance the runtime does not offer for its
own dispatches, so no flag here pretends to. The terms with teeth beside it
are `--require-ledger-gates` (which re-hashes what the recorded gate read) and
`--require-rendered-evidence`.

Unchanged in 2.6.1: `--require-ledger-gates` still checks the chain first,
then the latest per-gate verdict scoped to the milestone (or unscoped), then
re-hashes every recorded input. That behaviour was verified, not modified.

## `--repo`-relative `--changed-files`, `--docs-root`, and the cwd fallback (Unreleased)

Observed failure: a real invocation from a workspace root ABOVE `--repo`
(one shared `.docs/` over several sibling repos) typed `--changed-files`
entries as cwd-relative paths, and the gate — which had always resolved a
relative entry against the process's cwd, not against `--repo` — either
matched the wrong file under a look-alike sibling repo or reported
`changed_file_missing` on a path that genuinely existed. Two changes close
this:

**`resolve_changed_files` now resolves every entry to a canonical,
repo-relative path, and every downstream use (staleness mtimes, the
runtime-evidence delegation, git pathspecs, the undeclared-tree comparison)
reads that normalized form.** A relative entry resolves against `--repo`
first. Only when that does not exist is it retried against the process's own
cwd — a fix-round addition, since the workspace-root case above still needed
a way in for an honest cwd-relative path — and accepted only if it both
exists there AND resolves under `--repo` (`Path.resolve()` containment, never
a string prefix, so a look-alike path belonging to a sibling repo cannot slip
through as this repo's). An absolute entry must lie under `--repo` outright —
there is no cwd ambiguity for it to fall back on. Either miss is
`changed_file_outside_repo`, exit 2: the fix is to run the gate once per
repo, not to combine paths from several in one invocation.
`changed_file_missing` now names the repo it searched (and that it also
checked the cwd), not just the bare path.

**`--docs-root` is new**, because `.docs/` living above `--repo` (the same
Gorelo shape) has no default that finds it: `resolve_docs_root` tries an
explicit `--docs-root` first, then walks up from `--review-report` (then
`--state`) looking for an ancestor named `.docs`, and only falls back to the
old assumption, `--repo/.docs`, when neither artifact path has such an
ancestor. The resolved value is recorded as `docs_root` in the report, and
`docs_root_repo_prefix` uses it to keep the undeclared-tree comparison from
expecting `git status` (which runs inside `--repo`) to ever report a path
outside it.

Self-test 94 → 105.

## Verdict/severity consistency — `findings_consistent` (convention #9)

**The gap.** `code-review-and-quality/SKILL.md` § The Review Report says "`Approve` is unavailable while any Critical or Important finding stands in the same report" — but the gate read only the `**Verdict:**` token. A reviewer could type `Approve` over a report still listing an unresolved Critical, and nothing mechanical caught it; the rule lived entirely in the reviewer's own re-read.

**Scanning range — fixed after review found the first version scoped to the wrong body.** The first cut scanned the SAME narrow body `find_latest_review`'s verdict comes from — which `parse_review_sections` closes at the FIRST subsequent heading of any level. That silently passed the exact case the rule exists to catch: the review template files real findings under `### Correctness` / `### Security` / etc, all of which sit outside that narrow body. A report with `**Verdict:** Approve` immediately after the heading and a standing `**Critical:**` several subsections down, under `### Security`, read as `(True, [])` — no findings seen, nothing to gate. The fix: `check_finding_consistency` now scans the SAME wider range `find_files_reviewed_paths` always used — `matched_section_range(text, milestone)`, extracted as a shared helper so the two gates cannot drift on where a review section ends — from the matched `## Review:` heading forward to the next level-2 `##` heading. `finding_blocks` gained a fourth block-terminator to match: a heading (`ANY_HEADING_RE`) now also ends a block, since the wider range legitimately contains `### Correctness` / `### Security` / `### Files reviewed` headings the narrower body never had to worry about.

**The grammar, defined here because it did not exist before.** Inside that wider range (fences already stripped), a **finding line** is a line whose first non-list-marker, non-whitespace content is `**Critical:**` or `**Important:**` — `- `, `* `, `1. ` list markers and leading whitespace are allowed in front of it; a `|`-prefixed line (a markdown table row — the severity legend's `| **Critical:** | Blocks merge |`) never counts, checked explicitly rather than left to be inferred from the finding regex simply not matching it. A finding's **block** is its own line plus every following line up to (not including) a blank line, a heading, another list-item line at the same or lesser indentation as the finding's own marker, or another finding line (a stop condition added defensively: two finding lines written back-to-back with no list marker at all are not "list items" and would otherwise merge into one block — the rule's prose does not anticipate that shape, but nothing about it forbids guarding against it). A finding is **resolved** iff its block contains the literal uppercase word `RESOLVED` (`\bRESOLVED\b`, case-sensitive) — `resolved` written as prose ("the fix resolved this") does not count, because the marker is meant to be a deliberate, machine-read annotation, not incidental wording.

**The term.** Verdict `Approve` plus one or more standing (unresolved) Critical/Important findings anywhere in the matched section, subsections included → `findings_consistent: false`, reported in `standing_findings` (`{severity, line, text}`, `line` the 1-based line number in the review report as read, `text` the finding line trimmed to 200 chars), and the gate fails (exit 1) alongside every other consistency term. `Request Changes` is never affected by this term — findings are the normal, expected shape of that verdict; only the LATEST matching `## Review:` section is read (via `matched_section_range`'s own last-match rule), so a finding under a LATER section for a DIFFERENT milestone is never counted, and a finding fixed and re-approved in a later section for the SAME milestone is not held against it by an earlier round's report.

**What this does NOT check.** Whether `RESOLVED` is telling the truth — that a marker naming a real fix and real evidence was written honestly is Luna's fresh-delegation rule (`code-review-and-quality/SKILL.md`'s remediation-fidelity rule), not something a regex can adjudicate. The gate enforces the ARITHMETIC (no standing unresolved finding under an Approve), not the CONTENT of the resolution.

## Files-reviewed coverage — `--require-files-reviewed` (convention #9)

**The gap.** The review template's `### Files reviewed` subsection carries the comment "a file missing here has not been reviewed" — a declared convention with nothing mechanical behind it. A reviewer could Approve a milestone whose report never lists half the changed files, and the gate had no way to notice: `--changed-files` was already checked for existence and staleness, never for having been individually accounted for in the review text.

**Why a second parser, not `find_matching_section`'s body.** `parse_review_sections` closes a section's body at the FIRST subsequent heading of any level 2-6 — that is deliberate (see "Section boundaries" above) and correct for the verdict, but it means `### Files reviewed`, itself a heading, is never IN the body the verdict parser reads. `find_files_reviewed_paths` instead uses `matched_section_range` (the same helper the finding-consistency gate above uses) to walk from the matched `## Review:` heading forward to the NEXT level-2 `##` heading (a narrower subsection heading does not end this wider range), finds a level 3-4 heading matching `Files reviewed` (case-insensitive) inside it, and collects the first backticked path on each of that subsection's list-item lines. Only the LATEST `## Review:` section matching the milestone is read — a `### Files reviewed` subsection that happens to sit under a LATER section for a DIFFERENT milestone is past this section's own level-2 boundary and is never reached.

**The comparison.** Every path in the resolved `--changed-files` list (already repo-relative, forward-slash, via `resolve_changed_files`) must appear on some Files-reviewed line: forward-slash, **case-sensitive** — deliberately diverging from `normalize_repo_path`'s Windows case-fold used by the undeclared-tree check elsewhere in this file (convention #8): that check compares actual filesystem paths, where Windows itself is case-insensitive, but a Files-reviewed line is prose a reviewer typed, and `Src/Foo.cs` is not an honest citation of `src/Foo.cs`. A declared path ending in `/` + a listed path also counts, since a listed path may legitimately be relative to a shorter root than the declared path was resolved to (the same sibling-repo shape `resolve_changed_files`'s own docstring documents). Fenced content is excluded the same way it always is in this file — fences are stripped once, upstream, before any parser runs.

**Missing coverage.** Any declared path with no matching line goes into `files_unreviewed`, `files_reviewed_ok` becomes `false`, and the gate fails (exit 1). No `### Files reviewed` subsection at all means every declared file counts as unreviewed. Unset, the flag changes nothing (`files_reviewed_ok: true`, backward compatible).

**What this does NOT check.** The line's disposition. `review_package.py` is gaining default exclude patterns, and a reviewer records an excluded file as e.g. `` `<path>` — not reviewed: excluded from package``. That line still satisfies this gate — it checks presence of the path, not what the line says happened to it. Judging whether an exclusion was legitimate is a review-quality question, not a mechanical one.

Self-test 105 → 121 → 125 (the fourth case set added when review found `check_finding_consistency` scoped to the wrong body).
