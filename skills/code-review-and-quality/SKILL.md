---
name: code-review-and-quality
description: Conducts multi-axis code review. Use before merging any change. Use when reviewing code written by yourself, another agent, or a human. Use when you need to assess code quality across multiple dimensions before it enters the main branch. Squad-internal execution contract loaded by agents via their Methodology Dependencies table.
---

# Code Review and Quality

Multi-dimensional code review with quality gates. Every change gets reviewed before merge — no exceptions. Review covers five axes: correctness, readability, architecture, security, and performance.

**The approval standard:** Approve a change when it definitely improves overall code health, even if it isn't perfect. Perfect code doesn't exist — the goal is continuous improvement. Don't block a change because it isn't exactly how you would have written it. If it improves the codebase and follows the project's conventions, approve it.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### The Five Axes

**1. Correctness** — does the code do what it claims to do?
- Matches the spec/task; edge cases (null, empty, boundary) and error paths handled, not just the happy path.
- Tests pass and actually test the right things; no off-by-one errors, race conditions, or state inconsistencies.

**2. Readability & Simplicity** — understandable without the author explaining it?
- Descriptive, convention-consistent names; straightforward control flow; no "clever" tricks; could it be done in fewer lines?
- Abstractions must earn their complexity (don't generalize until the third use case); no dead-code artifacts (`_unused`, compat shims, `// removed` comments).

**3. Architecture** — does the change fit the system's design?
- Follows existing patterns (new ones must be justified); clean module boundaries; no duplication that should be shared.
- Dependencies flow in the right direction (no cycles); abstraction level appropriate — not over-engineered, not too coupled.

**4. Security** — does the change introduce vulnerabilities? For detailed security guidance, see `security-and-hardening`.
- Input validated and sanitized; secrets out of code, logs, and version control; auth/authz checked; SQL parameterized; outputs encoded (XSS).
- Data from external sources (APIs, logs, user content, config files) treated as untrusted and validated at system boundaries; dependencies trusted, no known vulnerabilities.
- To confirm a secrets file (e.g. `.env.local`) is git-ignored, use `git check-ignore` / `git status` evidence — do NOT attempt to read the file. The sandbox's credential-file classifier blocks raw reads of credential files by design; verify the property you actually care about (ignored / untracked) from git, don't fight the block.

**5. Performance** — does the change introduce performance problems? For profiling and optimization methodology, see `performance-optimization`; for quick checks, see `{PLUGIN_ROOT}/../references/performance-checklist.md`.
- No N+1 query patterns, unbounded loops, or unconstrained data fetching; pagination on list endpoints.
- No synchronous operations that should be async, unnecessary UI re-renders, or large objects in hot paths.

### Review Workflow

**Step 1: Understand the context.** Before looking at code, understand the intent and blast radius:

1. Gather review context:
     - Search the codebase to find all callers/consumers of the modified functions/classes.
     - List files to understand the module structure.
     - Manually trace the dependency chain (max 2 levels deep).
     - Optionally, if a `code-review-graph` MCP server happens to be available (it is NOT wired in this plugin's `.mcp.json`), you may use its `get_review_context_tool` instead to calculate the impact radius, coupling, and system boundaries affected by the changed files.
2. Answer: What is this change trying to accomplish? What spec or task does it implement? What is the expected behavior change?

**Step 2: Review the tests first.** Tests reveal intent and coverage: do tests exist, do they test behavior (not implementation details), are edge cases covered, are names descriptive, would the tests catch a regression?

**Step 3: Review the implementation.** Walk every changed file through the five axes above.

**Step 4: Categorize findings.** Label every comment with its severity so the author knows what's required vs optional:

| Prefix | Meaning | Author Action |
|--------|---------|---------------|
| **Critical:** | Blocks merge | Security vulnerability, data loss, broken functionality |
| **Important:** | Required change | Must address before merge — correctness, reliability, or maintainability risk |
| **Suggestion:** | Worth considering | Not required — improvements the author may adopt or decline |
| **Nit:** | Minor, optional | Author may ignore — formatting, style preferences |
| **FYI** | Informational only | No action needed — context for future reference |

This prevents authors from treating all feedback as mandatory and wasting time on optional suggestions.

**Step 5: Verify the verification.** Check the author's verification story: what tests were run, did the build pass, was the change tested manually, are there screenshots for UI changes, is there a before/after comparison?

### Rules

- **Remediation fidelity: a fix is verified against the RULE the finding protects, not the finding's literal text.** When you re-review a remediation, first name the rule the original finding was enforcing, then check the fix against *that*. A remediation which satisfies the finding's wording while violating its underlying rule is rejected, not approved — closing a "missing route" finding by adding a placeholder route, silencing a failing assertion by loosening it, satisfying a "no untyped boundary" finding with `any` behind a cast. These are the natural output of an author optimizing for the sentence you wrote, and they read as compliant at a glance: the finding is literally addressed, which is exactly why only the rule can catch them. If the fix trades the finding for a fresh instance of the same defect class, say so and keep the finding open.
- **Undeclared substitution and undeclared addition are both Critical.** Review the change against the requirement text as written, not only against the task that paraphrased it. Two defects hide from a task-level read because the code is competent and the task is silent: a capability **substituted** for the one specified (a different chart, algorithm, or mechanism serving the same heading), and a capability **added** that no requirement or design asked for. Both are Critical, and neither is closed by the substitute being better or the addition being useful — the remedy is a supersession/divergence filed against the requirement, after which the change is reviewed on its merits. A requirement counted "covered" by a substitute nobody declared is a coverage gate reporting a number it cannot support, and an unrequested feature that reaches the ship summary was never designed, reviewed, or scoped by anyone.
- **Dead code:** After any change, identify orphaned or unreachable code and list it explicitly.
  **Ask before deleting:** "Should I remove these now-unused elements: [list]?"
- **Dependencies:** Prefer standard library and existing utilities over new dependencies — every dependency is a liability.

### The Review Report

This template is the **single owner** of the review report format — reviewer personas (Luna) defer to it. Save the review report to `.docs/{project-name}/implementation/review-report.md`, **appending** one `## Review:` section per review — never overwrite earlier reviews. If this is part of the `bgpdd-build` pipeline, explicitly flag any "Critical" or "Important" blockers that the Builder (Mason) must resolve before the next phase.

```markdown
## Review: [Milestone/Task title]

### Context
- [ ] I understand what this change does and why

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

### Verdict
**Verdict:** Approve | Request Changes
```

**The `**Verdict:**` line is mandatory and machine-read.** Every `## Review:` section ends with exactly one line of the form `**Verdict:** Approve` or `**Verdict:** Request Changes` — the `bgpdd-build` gate reads the latest Verdict for the current milestone, so the exact token is required: no variants (`Approved`, `LGTM`, `approve with notes`), no prose in place of the token.

**`Approve` is unavailable while any Critical or Important finding stands in the same report.** Before writing the verdict, re-read every finding you just wrote *in that report section*. Each Critical and Important one must either be absent or carry an explicit `RESOLVED` marker naming the fix and the evidence that verified it. If even one stands unresolved, the verdict is `Request Changes`. There is no "approve with notes", no closing summary that outranks the findings above it, and no verdict carried over from a previous round. A report that states *"the app will fail to render these components"* and then *"Approve — all blockers resolved"* is not a review; it is two documents that never met. The findings are the review — the verdict is arithmetic over them, not a separate judgement.

### Verification Checklist

After review is complete:

- [ ] All Critical issues are resolved
- [ ] All Important issues are resolved or explicitly deferred with justification
- [ ] The verdict is consistent with the findings in the same report — no `Approve` while an unresolved Critical or Important finding stands anywhere above it — and is written as the exact machine-read token (`**Verdict:** Approve` or `**Verdict:** Request Changes`)
- [ ] Tests pass
- [ ] Build succeeds
- [ ] The verification story is documented (what changed, how it was verified)

### Escalate When

- The change is too large to review properly → report to the Orchestrator (manager) and request a split.
- You lack the context to judge correctness (missing spec, ambiguous requirements) → ask the Orchestrator (manager).
- Critical or Important findings remain unresolved after the author's fixes → escalate to the Orchestrator (manager); do not approve.

## See Also

- For detailed security review guidance, see `{PLUGIN_ROOT}/../references/security-checklist.md`
- For performance review checks, see `{PLUGIN_ROOT}/../references/performance-checklist.md`

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Code review deep dive](references/code-review-deep-dive.md) — when to use, the full per-axis question lists, change sizing and splitting strategies, change descriptions, the multi-model review pattern, dead code hygiene, review speed, handling disagreements, honesty in review, dependency discipline, common rationalizations, and red flags.
