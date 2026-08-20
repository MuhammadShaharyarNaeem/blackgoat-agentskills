# pipeline-tools — rationale and failure histories

Load on demand. `../SKILL.md` is the contract: every flag, exit code, JSON key,
grammar line, and scope limit lives there and is authoritative. This file holds
only the *why* — the observed failures each rule was written against, the design
choices behind them, and the arguments a reader may want when tempted to "fix" a
deliberate posture. Nothing here is normative; do not cite it as a contract.

---

## Family-wide

**No shared module, by convention.** `GateError` is duplicated in seven files;
the in-process tell list, the non-runtime-probe regexes, `cited_under()`, and
`check_coverage.py`'s `parse_requirements()` are duplicated verbatim into their
second consumers. Each duplication is paired with a test asserting byte-equality
or behavioural parity, so the copies cannot drift. The alternative — a shared
package — makes every script's dependency graph a thing an operator has to
understand before running one of them, and these are run one at a time from a
shell action on machines the plugin does not control.

**Why the family is stdlib-only.** Every gate must run on any machine the
pipeline lands on, with no install step and no network. That is also why
`--openapi-doc` accepts JSON only: adding a YAML parser means adding a
dependency, and the caller already has the JSON form the probe fetched.

---

## check_coverage.py

**Why `blocked` exists as its own array.** Only `PASS` ever lands in `covered`,
so a BLOCKED Must-Have already fails the gate through `uncovered`. The separate
array exists purely so a reader can tell *"unperformed and said so"* from
*"never mentioned"* without re-reading the report — and it is reported
unfiltered so an ID the requirements never declared surfaces rather than
vanishing between two set intersections.

**Why supersession is an in-place annotation.** Renumbering or deleting a
superseded requirement destroys the traceability the coverage gate runs on: the
plan task that implements the superseding design decision has nothing left to
cite. Keeping the ID at its declared tier and annotating it means an annotation
can never silently remove a gating requirement — the same fail-safe precedence
the duplicate-ID and Won't-Have rules use. `Won't Have` stays the single
construct that de-gates an ID, so de-gating is always a visible, deliberate act.

**Why the design register reads only the first two cells.** An earlier revision
read whole rows. Later cells are justification prose that cites other
requirements as supporting argument — an observed register's DIV-04 explains
itself by reference to "the FR-1 retry budget", and FR-1 is not thereby
superseded. Reading whole rows made 20+ correctly-unannotated requirements look
like violations, which is the failure mode that makes a lint get switched off.

**Why the annotation check has no verb whitelist.** Real annotations read
`**REINTERPRETED by SUP-05**`, `**SCOPE PINNED by SUP-06**`, `**SUPERSEDED IN
PART by SUP-02**`. A whitelist of supersession verbs would reject every one of
them. The load-bearing marker is the citation of the register row's own id,
because that is the actual routing link between the two documents.

**What the supersession lint cannot see, and why that matters.** It proves every
divergence the design *filed* was routed back to its requirement. An observed v8
run deleted Cognito custom attributes that FR-29 mandates, resolved it in a §19
revision section rather than the §17 register, and never annotated FR-29 — this
lint does not catch that, because the divergence was never filed in the register
at all. Detecting an unfiled divergence requires reading the design against the
requirements, which is why the Phase 2.5 design review gate still exists. Design
mode narrows that gate's surface; it does not replace it.

**Why `literal-count` is a gate rather than advice.** A transcribed number goes
stale the moment the source table changes, and no test catches it — the plan
still reads plausibly, and the discrepancy surfaces only when someone counts by
hand. Asserting set-equality against the source table ("every code in the error
table has a mapping") stays true across table edits.

**Why the `consumes:`/`provides:` list terminates at a sentence break.** A
machine line is sometimes followed by explanatory prose on the same physical
line: `consumes: none. The ruling is read by Tasks 3, 4, 5.` Without a
sentence-break terminator, the prose's own commas comma-split into fake
identifiers — an observed run produced `4`, `5`, and `not` this way. An
identifier's internal dots (`api.mode.ruling`) are never followed by whitespace,
so `. ` is safe as a terminator and truncates no real identifier.

**Why a wrapped list is a documented hazard rather than a parser fix.** The
*field* may span continuation lines, but a *wrapped keyword list* silently
contributes only its first line, and the gate then reports a missing provider
for an identifier the author can plainly see in the file. Making the parser fold
wrapped lists would also fold the prose that follows them, which is the failure
the sentence-break terminator exists to prevent.

**Why `path-hygiene` exists.** An observed plan referenced a sibling
repository's files by absolute path. No builder on another machine can resolve
such a path, and it silently smuggles another codebase into the plan's scope.

**Why "count definitions, not mentions".** Cross-references, prose citations,
and downstream task fields all contain the same `FR-n` tokens as the definition
lines. An observed run counted 131 `FR-` matches against 74 actual definitions.
An inflated count can make an incomplete or malformed artifact appear complete,
which makes a mention-counting check worse than no check at all.

**Why `runtime-criterion` runs at plan time.** A compile, typecheck, bundle, or
source-search command is not a runtime exit criterion — but by the time the
capture exists, the code is written and the cheapest moment to fix the criterion
has passed. Condition 1 (no `RUNTIME PROBE:` line) short-circuits because it is
the single root cause; reporting conditions 2–6 on top of it would be noise.

**Why checkpoint headings are linted at level 2 as well as level 3.**
`next_milestone.py` tolerates the deprecated `## Checkpoint:` form inside a
milestone block. Linting only `###` would leave the deprecated spelling as a
free escape hatch from the probe requirement.

**Why a milestone-less plan yields `[]` here rather than raising.** The coverage
gate also runs against plans that predate the milestone convention, and
`next_milestone.py` already halts the build on a milestone-less plan — a second
halt from a different tool adds nothing.

---

## check_commit_gate.py

**Why the gate performs the commit.** The prose rules that should already have
prevented a bad commit (Orchestrator Contract §4, *a terminal status is not
evidence*, and the append-only blockers ledger) were in force during an observed
run in which three consecutive milestones were committed over standing `Request
changes` verdicts. Nobody denied the rules; they were simply never converted into
a file you had to open. Making the script perform the commit means a skipped gate
is loud — no commit exists — rather than silent. This is CLAUDE.md convention #9
applied to the commit gate.

**Why runtime-evidence delegation is a subprocess, not an import.** This family
has no shared module by convention, and duplicating existence, provenance,
freshness, and content logic into a second file is the worse cost. The file
already shells out for `git`, and `sys.executable` keeps the child on the same
interpreter.

**Why every assertion flag must forward.** `bgpdd-build` runs the runtime gate
twice: once at Phase 2 where feedback is cheap, and again at the commit. If the
commit-time run accepted a weaker set of assertions than the earlier one, the
gate that actually owns the commit would be the more permissive of the two,
which inverts the whole point. Same reasoning as `--verify-tree` running here
rather than only earlier: **the restraint has to bind at the moment it is least
convenient.** A forwarded flag passed without `--require-runtime-evidence` is a
usage error rather than a silent no-op so a typo cannot quietly drop an
assertion.

**Why unscoped blockers gate by default.** Freeform ledger entries make "not
obviously this milestone's" indistinguishable from "not this milestone's". The
fail-safe reading is that the array must simply be empty before a milestone
commits, which is also what `bgpdd-build` §1 (*Blockers precondition*) says.
`--ignore-unscoped` remains the sanctioned override for exceptional cases.

**Why the `M1`/`M10` word-boundary match was needed.** A bare substring test
matched `M1` against a section titled `M10 — …`, so a gate run for one milestone
could read another milestone's verdict, and an `M10:`-prefixed blocker entry
scoped itself to an `M1` gate run.

**Directory-shaped porcelain entries — the 2026-08-09 fix.** Naively normalizing
a directory-shaped path (`Path(".docs/").resolve()` strips the trailing slash to
`.docs`) broke both the `.docs/` carve-out's `startswith` prefix test and a
declared file's own directory match, so `--verify-tree` misreported legitimate
changes as undeclared the first time a directory was untracked. The current
contract is in `../SKILL.md`; the regression cases are in the script's
`--self-test`.

**Why the self-test's last case is the load-bearing one.** Everything green
except runtime evidence, with `--commit`, asserting the repo holds **zero**
commits afterwards. That case is what distinguishes a gate that blocks from a
gate that merely reports.

---

## check_agent_report.py

**Why the evidence contract is deliberately terse.** Command + exit code +
counts per line is enough to prove an execution happened, and it keeps the
report readable. Requiring full scanner output or log dumps would make the
durable report a place logs get pasted, which is what the log file is for. It is
the same verdict-is-arithmetic-over-findings principle `code-review-and-quality`
enforces on Luna's `**Verdict:** Approve`, applied to the Launch Squad's reports.

**Why an unparseable latest verdict fail-safes to no verdict.** Falling back to
an earlier, parseable line would let an author downgrade a verdict into
unreadability and have the gate read the stronger old one.

---

## check_runtime_evidence.py

**The failure class this gate exists to stop.** A response envelope green in a
`WebApplicationFactory` suite, green in QA prose, and absent from local Swagger.
Swagger was the falsifier — a reachable OpenAPI document is the exact instrument
that falsified the 2026-08 claim by hand — so the gate makes producing a contract
surface something a caller can demand.

**Why there is no `--allow-stale` override.** Freshness is the specific gap the
observed failure walked through. `check_commit_gate.py`'s `--ignore-unscoped`
precedent exists because unscoped blockers are genuinely ambiguous; a stale
capture is not ambiguous.

**Why assertions are caller-supplied.** A producer-declared assertion grades
itself. Stack-specific keys live in the stack contract
(`dotnet-backend-patterns/SKILL.md` names `isSuccess`, `notifications`,
`statusCode`); forbidden-host patterns are project-declared.

**Why requiring a contract surface is worth a flag.** A probe can be aimed at
anything that answers on a port — a stub, a mock, a previous build, another
service. Demanding that the same probe also recorded a reachable OpenAPI
document forces it at a real host running a real API.

**Why an unresolvable schema is a warning.** A partial resolver that silently
gets JSON-Schema composition wrong is worse than one that says it cannot tell.
An empty declared property set would pass vacuously, so it is refused rather
than counted. The same one-directional discipline as the transport tell list,
applied to schemas.

**How `declared_absent` overriding `--min-captures` was found.** The negative-half
proof: dropping `dataContext`/`notifications` from the happy fixture's success
body still left the 4xx sibling accepted (legitimately schema-skipped), so at
`--min-captures 1` the run exited **0** with `declared_absent` populated — the
original bug, masked by a sibling. A declared-but-absent property is the contract
surface and the runtime contradicting each other, not a "this capture isn't good
enough" judgment, so no number of accepted siblings makes it untrue.

**Why the prose tell list exists alongside the framework tells.** A capture
reading `Transport: direct handler call` named no framework and so passed every
check; with a well-formed envelope body it was accepted outright. Prose is the
weaker signal and does nothing against a *misdescribed* transport — but nothing
here does, and the honest author is now caught.

**Why `node --test` is listed separately.** It is flag-shaped rather than
subcommand-shaped, so it matched none of the `<tool> test` patterns and a capture
declaring it passed the gate with a hand-written envelope body — the same escape
this file exists to stop, through a different hole. Found 2026-08-12 by the eval
fixture; `deno|bun|swift|rails|ctest test` went in with it.

**The fence-regex regression (fixed 2026-08-12).** The body fence regex must
match horizontal whitespace only. A `\s*` there consumes the newline after the
opening fence and then matches the next line, eating the body's first line — which
is exactly the HTTP status line `--expect-status` reads. It silently broke
`--expect-status` and would have dropped the status line from every capture.

**Why the OpenAPI keys were provably additive.** Verified by diffing
old-against-new stdout across all four pre-existing fixtures: every diff line is
an addition, zero changed and zero removed.

**Why staleness has no fixture.** mtimes do not survive a clone, so it is covered
only in `run_self_test()` with synthetic `os.utime` ordering rather than the real
clock — the pattern `check_commit_gate.py` established.

---

## check_acceptance_suite.py

**Why a feature-scoped gate exists above the per-milestone gates.**
Per-milestone evidence proves each brick; nothing else proves the wall stands. A
feature can be green on every milestone gate and still fail its own journey,
because the journey is ordered and stateful — and because **inverse operations
are never exercised by the milestone that added them**: the milestone that adds
mapping has no reason to unmap.

**Why structure mode lives in the same script.** The two modes read the same
grammar, and a second file would drift into a shadow contract.

**Why the exemption marker is worth having even though its truth is uncheckable.**
The gate cannot know whether "a queued distribution job cannot be un-queued" is
true. The marker buys an author nothing except a place to be wrong in writing,
where a human reviewer can see it — still strictly better than an inverse
silently absent.

**Why the result-key separator is a dot.** `AS-2-4` is ambiguous with the
scenario id's own dash, and a forgiving parser would silently bind the wrong
step. Under the dot rule a mis-keyed line lands in `extra_results` as a warning
while the step it meant to cover lands in `missing_results` as a block, so the
mistake fails loud. Because step keys are self-describing, `##` headings in the
results file need no scoping at all — which removes the entire "which section was
this result under" problem that `test-report.md`'s human-only `#Task [N]:`
headers force on other parsers.

**Why `Mode` fails closed.** Before the fail-closed rule, `semi` was silently
read as `auto` and a device step citing nothing passed green — verified against
the previous revision, not assumed. A one-character typo was the cheapest way to
buy a device step out of the evidence gate. `--lint-only` blocks such a matrix at
plan time, but a matrix can be hand-edited between plan and build, so execution
mode must fail closed on its own. The blank-cell / absent-column boundary is
deliberate: retroactively making a pre-`Mode` matrix evidence-bearing would break
callers.

**Why an unparsed step table blocks.** One misspelled header cell (`Asserts` for
`ASSERT`) drops the entire table, so its steps never enter the step list and can
never land in `missing_results`, `not_run` or `unevidenced_manual` — an
unevidenced manual device step exited 0/PASS on nothing but a spelling. It is the
same class as `dangling_inverse`: the artifact misrepresenting its own coverage,
not a coverage judgment, and unlike `undeclared_inverse` it rests on no heuristic.

**Why `undeclared_inverse` blocks at plan time and warns at build time.** At plan
time the matrix *is* the artifact under authorship, the fix is a one-line edit,
and there is nothing else green could mean. At build time the code is already
written, so blocking would ask Quinn to author a scenario Alex owed weeks
earlier; the `state_changing` detector rests on a mutating-verb **allowlist** and
is knowably incomplete, and a blocking gate built on an incomplete heuristic
teaches that green means "the heuristic found nothing"; and legitimate one-way
steps exist (nothing un-distributes a queued job, nothing un-reinstalls). The
consequence of a genuinely missing inverse is still caught and still blocks at
build — as `missing_results`, if Alex wrote the step and Quinn didn't run it.

**Why `acceptance-happy` exits 0 in execution mode and 1 under `--lint-only`.**
That is the mode divergence demonstrated on one unchanged input: the same two
uninstall/reinstall steps that are legitimately one-way are tolerated at build
time and demanded in writing at plan time. It is documentation of the posture
change, not a broken fixture.

**Why a scenario id is searched for outside the parentheses.** Requirement ids
already live inside them by contract, so scanning the raw heading let a scenario
with no id of its own silently adopt one: `## Mapping lifecycle — P0 — (FR-1)`
parsed as `id: "FR-1"` and its result keys became `FR-1.1`. Found 2026-08-12.

---

## next_milestone.py

**Why this tool exists.** Real plans reach roughly 290K characters, and the
Orchestrator Contract's mandated re-reads of the whole file at every hydration
and phase-1 entry cost on the order of 73k tokens each. This tool reads the plan
once and returns only what is needed to route the next build phase — for roughly
2K tokens.

**Why three planning defects share one verdict.** `MIXED` is the family name for
"the plan cannot be executed as written". The Orchestrator's action is identical
for mixed `[UI]`/`[API]` tags, `UNTAGGED`, and a missing/unknown `[vs:]` tag —
halt and route back through Alex — so they share an exit code and are told apart
by the `warnings` entry.

**Why a prose heading is not a milestone.** Requiring a digit immediately after
"Milestone" lets a plan discuss "milestone ordering" in prose without the parser
mistaking the discussion for a milestone.

**Why the migration cost was accepted.** Every plan authored before the `[vs:]`
axis existed reads as a defect on its next pending milestone until re-tagged.
That is the intended cost of making the declaration non-omissible: a surface that
can be silently left out is a surface that will be.

---

## check_ship_decision.py

**Why the last verdict-bearing section wins.** `bgpdd-shipping` Step 3 instructs
the re-verifying agent to **append** a fresh section after a fix round, so a
Round-2 `GO` must be able to supersede a Round-1 `NO-GO`. Judging ambiguity
file-wide made an appended document permanently unpassable — the only escape was
rewriting history.

**Why the gate and the eval's `grade.ps1` differ.** That script counts verdicts
file-wide, which is correct for the single-shot document its prompt produces;
this gate scopes to the latest section, which is required for a pipeline artifact
appended to across fix rounds. The two agree on every single-section document.

---

## run_quiet.py

**Why the transcript is narrowed and the log is not.** An agent's context window
is the scarce resource, not disk. The excerpt/tail selection narrows what appears
in the transcript, never what is recoverable — the full log is written on every
run, success or failure, so a failure needing more than the excerpt shows is one
grep away.

**Why `--capture` refuses tool-owned field names.** The fields a gate reads must
be observed, not authored. Without the refusal, `--capture-field` would be a
fabrication vector rather than a defense against one.

---

## update_state.py

**Why `--resolve-blocker` requires `--evidence`.** Orchestrator Contract §4's
ledger doctrine — an entry is removed only once its fix is verified — was prose,
and prose does not stop a hand-edit. The CLI physically refuses the removal
without a stated evidence string, and appends the removal to
`blockers-resolved.log`, so a removal always leaves an audit trace even though
the state file only ever shows the current `blockers` array. CLAUDE.md
convention #9.

**Why the literal string `null` is special-cased.** `bgpdd-lite` emits
`--set-artifact design=null` when no stack-contract skill governs. Storing the
truthy string `"null"` made `bgpdd-build`'s "inject `artifacts.design` when
non-null" rule treat it as a path.

---

## Self-test case inventories

Maintainer reference: what each bundled `--self-test` suite already covers, so a
new case is added rather than duplicated. The suites themselves are the
authority; run them.

**`check_commit_gate.py --self-test` — 35 cases** (temp git repos, synthetic
`os.utime` ordering rather than the real clock): verdict precedence; the
`M1`/`M10` word-boundary match; staleness; scoped and unscoped blockers;
rendered evidence including the `..`-traversal refusal; `--verify-tree` with its
directory-shaped-porcelain cases (including fresh-`git init`-no-scaffold-commit);
the runtime delegation's pass and block paths; the OpenAPI forwarding, proven by
the same capture passing without the flag and failing with it; every
forwarded-flag-without-the-gate-flag usage error; and — the load-bearing one —
everything green except runtime evidence with `--commit`, asserting the repo
holds **zero** commits afterwards.

**`check_runtime_evidence.py --self-test` — 64 cases**: the happy path; the
missing-envelope-key case; key-nested-deeper (must fail) and key-in-`body` (must
pass); every in-process tell; test-runner and build probes; the
`myorg`-is-not-`rg` word-boundary case; forbidden hosts in both `Base URL:` and
`Environment:`; build-marker mismatch and absence; staleness; `evidence/build/`
non-gating; `..` refusal; milestone scoping including `M1`/`M10`; the status-line
fence regression; empty output; `--min-captures`; the structural exits. OpenAPI
half: the port-is-not-a-status case; separator tolerance; every
unresolvable-schema shape as a warning; inline and Swagger-2.0 schemas;
`body`-scope comparison; non-recursive nesting; leading-slash normalization; the
skip on a non-2xx capture; and the sibling-masking case that made
`declared_absent` override `--min-captures`.

**`check_acceptance_suite.py --self-test` — 78 cases**: matrix/results parsing;
every blocking condition in both modes; the FR→scenario link (a covered
Must-Have, an uncited one naming `fr-scenario-coverage`, an uncited Should-Have
that stays green, an unknown cited ID that only warns, a non-FR citation that is
not an unknown ID, and both exit-2 paths); the manual-evidence paths (missing
file, `evidence/build/` instead of `evidence/runtime/`, `..` traversal,
resolution against `--repo`, a `.docs/`-prefixed citation keeping its leading
dot); dangling vs undeclared inverses; cross-scenario inverse non-resolution;
priority-scope semantics; every structural lint condition; the exemption grammar
including the both-markers contradiction and the no-op-on-a-read-only-step
warning; the two fail-closed regressions (an unrecognized `Mode`, an unparsed
step table) with their ungated/blank-cell boundaries; key parity between the two
modes' output; and every exit-2 trigger.

**`next_milestone.py --self-test`** (temp plan/state files): happy-path
derivation; the prose-heading-not-a-milestone case; all-complete (`DONE`);
zero-milestone-headings (`ERROR`); mixed tags (`MIXED`); untagged-as-MIXED;
missing-surface and unknown-surface as MIXED; every valid surface key accepted;
heading-surface authority over a block mention; surface read from the block when
the heading carries none; the `[vs:api]`/`[API]` non-collision in both
directions; stale/matching/null/unmatchable cursors; missing/invalid file inputs;
a level-3-heading plan with heading-carried domain tags and a trailing `## Risks
and Mitigations` section (asserting the last milestone's block excludes it);
heading-tag authority over a stray same-tag mention in task prose; heading tags
wrapped in backticks; and a deprecated level-2 `## Checkpoint:` heading tolerated
inside its milestone block with a warning (contrasted against the canonical
level-3 form, which emits none).
