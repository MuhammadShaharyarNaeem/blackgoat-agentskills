# Review Report Template

Full skeleton for one `## Review:` section in `.docs/{project-name}/implementation/review-report.md`. Copy it verbatim and fill it in. This file is the shape only — the grammar rules the gates enforce (verdict arithmetic, the machine-read evidence lines, the Files-reviewed line format) live in `code-review-and-quality/SKILL.md` § The Review Report; this file does not restate or vary them.

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
     failure paths: what happens when each fallible call fails (or n/a)
     check_commit_gate.py --require-files-reviewed fails the commit for any declared path with no line here. -->
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
