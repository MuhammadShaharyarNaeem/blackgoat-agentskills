---
name: code-review-and-quality
description: "Conducts multi-axis code review. Use before merging any change. Use when reviewing code written by yourself, another agent, or a human. Use when you need to assess code quality across multiple dimensions before it enters the main branch. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Also directly invocable: when a user asks for this on named files outside a pipeline, the Orchestrator applies the Worker Execution Contract itself in the main session — no delegation."
---

# Code Review and Quality

Multi-axis review before merge — no change merges unreviewed. Five axes: correctness, readability, architecture, security, performance.

**Approval standard:** approve a change that definitely improves overall code health, even if imperfect. NEVER block a change because it is not how you would have written it — if it improves the codebase and follows project conventions, approve it.

## Direct invocation

A user can ask for this directly on named files — a deliberate refinement of agent-audit Metric 12, not a trigger collision. The Orchestrator applies the Worker Execution Contract below inline, in the main session: no delegation, no editing tests to pass, no unobserved claims (`base-persona.md`, Evidence Integrity). Over three files, or shared behaviour: route via `/bg` to a lane.

## Quick card

Derived from the contract below for a ≤ 3-file change; no new rules (convention #8 — deliberately narrower than the full contract, which binds inside any lane).

1. Read the tests first and write down what they do **not** cover (§ Review Workflow, Step 2).
2. Per changed file, name each authz comparison's trusted source and each fallible call's failure path (§ Review Workflow, Step 3).
3. Label every finding Critical / Important / Suggestion / Nit / FYI (§ Review Workflow, Step 4).
4. The verdict is arithmetic over the findings — no `Approve` while a Critical or Important stands (§ The Review Report).
5. List the dead code your change orphans and ask before deleting (§ Rules).

- Brief → the quick note (What / Where / How verified)
- Artifact → the capture at `{quick-root}/evidence/check.md`
- Handoff → the `## Result` bullet in `note.md`

## Worker Execution Contract

This is the operational spine. Follow it as written. For a change of ≤ 3 files outside a pipeline, the Quick card above is the contract; the full contract applies inside a lane.

### The Five Axes

**1. Correctness** — does the code do what it claims to do?
- Matches the spec/task; edge cases (null, empty, boundary) and error paths handled, not just the happy path.
- Tests pass and actually test the right things; no off-by-one errors, race conditions, or state inconsistencies.
- **Ambiguous-outcome encoding is a Critical correctness defect, never a style nit.** Two shapes, one root:
  - a dispatch construct with no exhaustive-failure arm (a `switch`/map without `default`, an if-chain with no final `else`) that returns its **initialized default** — success-shaped — for input it did not recognize;
  - an error or catch-all path returning the **same value** as a legitimate negative outcome, so "genuinely absent" and "my probe broke" are indistinguishable to every caller.

  Require a distinct, diagnosable value on every unrecognized-input path and every error path. ([why](references/code-review-deep-dive.md#ambiguous-outcome-encoding))

**2. Readability & Simplicity** — understandable without the author explaining it?
- Descriptive, convention-consistent names; straightforward control flow; no "clever" tricks; could it be done in fewer lines?
- Abstractions must earn their complexity (don't generalize until the third use case); no dead-code artifacts (`_unused`, compat shims, `// removed` comments).

**3. Architecture** — does the change fit the system's design?
- Follows existing patterns (new ones must be justified); clean module boundaries; no duplication that should be shared.
- Dependencies flow in the right direction (no cycles); abstraction level appropriate — not over-engineered, not too coupled.

**4. Security** — does the change introduce vulnerabilities? Detailed guidance: `security-and-hardening`; checklist: `{PLUGIN_ROOT}/../references/security-checklist.md`.
- Input validated and sanitized; secrets out of code, logs, and version control; auth/authz checked; SQL parameterized; outputs encoded (XSS).
- Data from external sources (APIs, logs, user content, config files) treated as untrusted and validated at system boundaries; dependencies trusted, no known vulnerabilities.
- Confirm a secrets file (e.g. `.env.local`) is git-ignored from `git check-ignore` / `git status` evidence — NEVER read the file. The sandbox's credential-file classifier blocks raw reads by design; verify the property you care about (ignored / untracked), don't fight the block.

**5. Performance** — does the change introduce performance problems? Methodology: `performance-optimization`; quick checks: `{PLUGIN_ROOT}/../references/performance-checklist.md`.
- No N+1 query patterns, unbounded loops, or unconstrained data fetching; pagination on list endpoints.
- No synchronous operations that should be async, unnecessary UI re-renders, or large objects in hot paths.

### Review Workflow

**Step 1: Understand the context.** Before reading code, establish intent and blast radius:

1. Gather review context:
     - Search the codebase for all callers/consumers of the modified functions/classes.
     - List files to understand the module structure.
     - Manually trace the dependency chain (max 2 levels deep).
     - Optional: if a `code-review-graph` MCP server happens to be available (it is NOT wired in this plugin's `.mcp.json`), its `get_review_context_tool` computes impact radius, coupling, and affected system boundaries instead.
2. Answer: what is this change trying to accomplish? Which spec or task does it implement? What behavior changes?

**Step 2: Review the tests first.** Tests reveal intent and coverage: do tests exist, do they test behavior (not implementation details), are edge cases covered, are names descriptive, would they catch a regression? **A green suite is a claim about what the tests exercise, never about what they omit.** Finish this step by writing down what the suite does *not* cover — those untested paths are your Step 3 reading list, and a verifier's sign-off resting on the suite inherits exactly its blind spots. A test that would still pass with the production code it names deleted is a **Critical** finding — the deletion test (`test-driven-development/SKILL.md` § Rules; `check_test_authenticity.py`).

**Step 3: Review the implementation.** Walk every changed file through the five axes above. Two interrogations are mandatory **per changed file**, answered in the report's Files-reviewed log — they target the defect classes a green suite is structurally blind to, the ones that *look like* working checks:
- **Identity provenance.** For every authorization, tenancy, or ownership comparison: name where each compared value originates. If the trusted side of the comparison originates in the request (body, query, header, path) rather than the authenticated session/token context, that is a **Critical** finding — the check passing its tests *is* the attack working, because any caller can type a different string.
- **Failure-path visibility.** For every awaited or otherwise fallible call whose side effect a requirement depends on: name what happens when it fails. An empty `catch`, a swallowed rejection, or a success status returned regardless of the outcome is **Important** at minimum — a required side effect that can silently not happen, which no green test ever witnesses.

**Step 4: Categorize findings.** Label every comment with its severity, so required and optional are distinguishable:

| Prefix | Meaning | Author Action |
|--------|---------|---------------|
| **Critical:** | Blocks merge | Security vulnerability, data loss, broken functionality |
| **Important:** | Required change | Must address before merge — correctness, reliability, or maintainability risk |
| **Suggestion:** | Worth considering | Not required — improvements the author may adopt or decline |
| **Nit:** | Minor, optional | Author may ignore — formatting, style preferences |
| **FYI** | Informational only | No action needed — context for future reference |

**Step 5: Verify the verification.** Check the author's verification story: which tests were run, did the build pass, was the change tested manually, screenshots for UI changes, before/after comparison.

### Rules

- **Remediation fidelity: verify a fix against the RULE the finding protects, not the finding's literal text.** On re-review, first name the rule the original finding enforced, then check the fix against *that*. A remediation satisfying the finding's wording while violating its rule is rejected: a placeholder route closing a "missing route" finding, a loosened assertion silencing a failing one, `any` behind a cast closing a "no untyped boundary" finding. A fix that trades the finding for a fresh instance of the same defect class keeps the finding open. ([why](references/code-review-deep-dive.md#remediation-fidelity))
- **Undeclared substitution and undeclared addition are both Critical.** Review the change against the requirement text as written, not only against the task that paraphrased it. **Substitution**: a capability serving the specified heading that is not the one specified (a different chart, algorithm, or mechanism). **Addition**: a capability no requirement or design asked for. Neither is closed by the substitute being better or the addition being useful — the remedy is a supersession/divergence filed against the requirement, after which the change is reviewed on its merits. ([why](references/code-review-deep-dive.md#undeclared-substitution-and-addition))
- **Dead code:** after any change, identify orphaned or unreachable code and list it explicitly.
  **Ask before deleting:** "Should I remove these now-unused elements: [list]?"
- **Dependencies:** prefer standard library and existing utilities over new dependencies — every dependency is a liability.

### The Review Report

This template is the **single owner** of the review report format — reviewer personas (Luna) defer to it. Save the review report to `.docs/{project-name}/implementation/review-report.md`, **appending** one `## Review:` section per review — NEVER overwrite earlier reviews. In the `bgpdd-build` pipeline, explicitly flag every "Critical" or "Important" blocker the milestone's builder (Mason or Nova) must resolve before the next phase.

The `## Review:` heading MUST carry the milestone's leading identifier verbatim as written in `plan.md` — the gate matches it as a whole token.

```markdown
## Review: [Milestone/Task title]

<!-- The three machine-read lines come FIRST, before any ### subheading. -->
**Verdict:** Approve | Request Changes
**Rendered evidence:** <path>[, <path>]
**Runtime evidence:** <path>[, <path>]

### Context
- [ ] I understand what this change does and why

### Files reviewed
<!-- One line per changed file - a file missing here has not been reviewed.
     identity: where every authz/tenancy comparison's trusted side originates (or n/a)
     failure paths: what happens when each fallible call fails (or n/a) -->
- `<path>` — identity: <source>; failure paths: <disposition>; findings: <ids or none>

### Correctness
- [ ] Change matches spec/task requirements
- [ ] Edge cases handled
- [ ] Error paths handled
- [ ] Tests cover the change adequately

### Readability
- [ ] Names are clear and consistent
- [ ] Logic is straightforward
- [ ] No unnecessary complexity

### Architecture
- [ ] Follows existing patterns
- [ ] No unnecessary coupling or dependencies
- [ ] Appropriate abstraction level

### Security
- [ ] No secrets in code
- [ ] Input validated at boundaries
- [ ] No injection vulnerabilities
- [ ] Auth checks in place
- [ ] External data sources treated as untrusted

### Performance
- [ ] No N+1 patterns
- [ ] No unbounded operations
- [ ] Pagination on list endpoints

### Verification
- [ ] Tests pass
- [ ] Build succeeds
- [ ] Manual verification done (if applicable)
```

**The `**Verdict:**` line is mandatory, machine-read, and must come BEFORE the section's first `###` subheading.** `check_commit_gate.py` closes a `## Review:` section at ANY heading of level 2–6, so a verdict written under a trailing `### Verdict` heading — or under any addendum subsection — is outside the section the gate reads: the gate finds no verdict and **fails closed**. Write the verdict, and the evidence lines beside it, immediately under the `## Review:` heading. (Migration: reports authored against the older bottom-of-section template must move the line up; nothing else changes.) Every `## Review:` section carries exactly one line of the form `**Verdict:** Approve` or `**Verdict:** Request Changes` — the `bgpdd-build` gate reads the latest Verdict for the current milestone, so the exact token is required: no variants (`Approved`, `LGTM`, `approve with notes`), no prose in place of the token.

**`Approve` is unavailable while any Critical or Important finding stands in the same report.** Before writing the verdict, re-read every finding you just wrote *in that report section*. Each Critical and Important one must be absent or carry an explicit `RESOLVED` marker naming the fix and the evidence that verified it. One standing unresolved → the verdict is `Request Changes`. There is no "approve with notes", no closing summary that outranks the findings above it, and no verdict carried over from a previous round. The findings are the review; the verdict is arithmetic over them, not a separate judgement. ([why](references/code-review-deep-dive.md#the-verdict-is-arithmetic-over-the-findings))

**The `**Rendered evidence:**` line is optional, but machine-read when present, on the same exact-token terms as the Verdict line.** Required whenever the review covers a `[UI]` milestone's design-critique axis: list the path(s) — comma-separated — that you (the reviewer) saved under `.docs/{project-name}/implementation/evidence/review/`, the rendered artifacts the design-critique verdict actually rests on. `check_commit_gate.py --require-rendered-evidence` parses this line for `[UI]` milestones; its grammar authority is `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.

**The `**Runtime evidence:**` line is optional on the same terms — machine-read when present.** Emit it whenever your review passes judgement on behavior a client, person, or device receives: list the observed-runtime capture(s) your judgement rests on. Unlike rendered evidence it need not be reviewer-produced — citing the capture the milestone's verifier wrote is legitimate, provided you read it. **This template owns the slot, not the contract**: citation grammar, required capture fields, and transport rules belong to `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`, their single owner — do not restate or vary them here.

### Verification Checklist

After review is complete:

- [ ] All Critical issues are resolved
- [ ] All Important issues are resolved or explicitly deferred with justification
- [ ] The verdict is the exact machine-read token and consistent with the findings in the same report — no `Approve` while an unresolved Critical or Important finding stands above it
- [ ] Tests pass
- [ ] Build succeeds
- [ ] The verification story is documented (what changed, how it was verified)

### Escalate When

- The change is too large to review properly → report to the Orchestrator (manager) and request a split.
- You lack the context to judge correctness (missing spec, ambiguous requirements) → ask the Orchestrator (manager).
- Critical or Important findings remain unresolved after the author's fixes → escalate to the Orchestrator (manager); do not approve.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Code review deep dive](references/code-review-deep-dive.md) — when to use, the full per-axis question lists, the rationale behind the Critical rules (ambiguous outcomes, remediation fidelity, undeclared substitution, verdict-as-arithmetic, severity labelling), change sizing and splitting, change descriptions, the multi-model review pattern, dead code hygiene, review speed, disagreements, honesty in review, dependency discipline, common rationalizations, and red flags.
