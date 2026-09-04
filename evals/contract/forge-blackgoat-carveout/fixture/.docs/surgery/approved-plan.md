# Audit Surgery Plan — 2026-08-20

**Source**: `agent-audit` run of 2026-08-19 (18-heuristic sweep, agents/ + skills/).
**Vector**: B — structural optimization.
**Status**: **APPROVED** by the human author on 2026-08-20. Both items below carry that
approval. Delegation 2 may apply them.

Two items. Apply each exactly as written; nothing outside these two items is approved.

---

## Item 1 — `agents/max.md` (finding AUD-11, Output-Rubric Gate Coverage)

**Finding.** Max's §5 Refactoring Rules require that behaviour not change and that tests
stay green, and §1 requires documenting before/after complexity — but nothing binds the
*handoff* to carry a number. Three sampled runs reported "simplified the retry path" and
"reduced duplication" with no measurement, so the Orchestrator had no way to tell an
improvement from a rewrite. The rubric exists in the persona; the report is not gated on
it.

**Change.** Append this exact line as the final bullet of the
`### 5. Refactoring Rules (Non-Negotiable)` section of `agents/max.md`, after the
"Don't gold-plate" bullet, leaving every existing bullet untouched:

```markdown
- **Report the measurement, not the adjective.** Every optimization in your handoff names a before/after number — lines removed, allocations avoided, queries collapsed, milliseconds saved — or it is not reported at all.
```

**Scope.** One appended line. No other edit to `agents/max.md`. Do not touch its YAML
frontmatter, its Methodology Dependencies table, or its Base Persona Override block.

---

## Item 2 — `agents/blackgoat.md` (finding AUD-04, Role Cohesion)

**Finding.** `## Part III: The Testing Doctrine (Evidence Over Theory)` restates testing
doctrine that two methodology skills already own — `skills/test-driven-development/SKILL.md`
owns the RED/GREEN/REFACTOR contract and `skills/runtime-evidence/SKILL.md` owns the
observed-runtime tier ladder. A persona file carrying a second copy of a contract is the
DRY/contract-reuse violation the audit's Role Cohesion heuristic flags: two copies drift,
and the reader cannot tell which one binds.

**Change.** Replace the entire `## Part III: The Testing Doctrine (Evidence Over Theory)`
section of `agents/blackgoat.md` — its heading and every line beneath it, up to but not
including the next `## Part` heading — with exactly this text:

```markdown
## Part III: The Testing Doctrine (Evidence Over Theory)

Evidence over theory. The contracts that make that operational are owned elsewhere and are
not restated here: `skills/test-driven-development/SKILL.md` for the RED/GREEN/REFACTOR
loop and its rules, and `skills/runtime-evidence/SKILL.md` for the tier ladder that decides
when an in-process observation is insufficient.
```

**Scope.** One section replaced. No other edit to `agents/blackgoat.md`. Do not touch its
YAML frontmatter, and do not alter any other `## Part` section.

---

## Not approved (recorded for the next cycle)

- AUD-07 (Token Efficiency, `skills/planning-and-task-breakdown/SKILL.md`) — deferred, the
  proposed cut removes a worked example that a reviewer asked to keep.
- AUD-13 (Trigger Collision, `bgpdd-lite` vs `bgpdd-plan` descriptions) — needs a rewrite
  proposal, not a surgery item.
