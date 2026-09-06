---
name: code-simplification
description: "Simplifies code for clarity. Use when refactoring code for clarity without changing behavior. Use when code works but is harder to read, maintain, or extend than it should be. Use when reviewing code that has accumulated unnecessary complexity. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Also directly invocable: when a user asks for this on named files outside a pipeline, the Orchestrator applies the Worker Execution Contract itself in the main session — no delegation."
---

# Code Simplification

> Inspired by the [Claude Code Simplifier plugin](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/code-simplifier/agents/code-simplifier.md). Adapted here as a model-agnostic, process-driven skill for any AI coding agent.

Reduce complexity while preserving exact behavior — not fewer lines, but code easier to read, understand, modify, and debug. Test: would a new team member understand this faster than the original?

## Direct invocation

A user can ask for this directly on named files — a deliberate refinement of agent-audit Metric 12, not a trigger collision. The Orchestrator applies the Worker Execution Contract below inline, in the main session: no delegation, no editing tests to pass, no unobserved claims (`base-persona.md`, Evidence Integrity). Over three files, or shared behaviour: route via `/bg` to a lane.

## Quick card

Derived from the contract below for a ≤ 3-file change; no new rules (convention #8 — deliberately narrower than the full contract, which binds inside any lane).

1. Run the suite first — a green baseline before you touch anything (§ Rules).
2. Preserve behaviour exactly; every existing test passes unmodified (§ The Five Principles, 1).
3. Can't say why the code exists? Don't simplify it (§ Chesterton's Fence).
4. One kind of change; no drive-by refactor of code you did not already touch (§ Rules; § The Five Principles, 5).
5. It only passes by modifying a test → revert and escalate (§ Escalate When).

- Brief → the quick note (What / Where / How verified)
- Artifact → the capture at `{quick-root}/evidence/check.md`
- Handoff → the `## Result` bullet in `note.md`

## Worker Execution Contract

This is the operational spine. Follow it as written. For a change of ≤ 3 files outside a pipeline, the Quick card above is the contract; the full contract applies inside a lane.

### The Five Principles

1. **Preserve behavior exactly.** Same output, same error behavior, same side effects and ordering, for every input. All existing tests pass unmodified. Unsure → don't change it.
2. **Follow project conventions.** Match the codebase (CLAUDE.md, neighboring code): imports, declarations, naming, error handling, type-annotation depth. Breaking consistency is churn, not simplification.
3. **Prefer clarity over cleverness.** Explicit beats compact when the compact version needs a mental pause to parse.
4. **Maintain balance.** NEVER: inline too aggressively (removing a helper that named a concept); merge unrelated logic into one function; remove abstractions built for extensibility or testability; optimize for line count over comprehension.
5. **Scope to what changed.** Simplify recently modified code only — no drive-by refactors of unrelated code unless explicitly asked.

### Chesterton's Fence

Check git blame before removing or changing code. Can't answer why it exists → don't simplify it; read more context first.

### Simplification Signals

Scan for these patterns — each one is a concrete signal, not a vague smell:

**Structural complexity:**

| Pattern | Signal | Simplification |
|---------|--------|----------------|
| Deep nesting (3+ levels) | Hard to follow control flow | Extract conditions into guard clauses or helper functions |
| Long functions (50+ lines) | Multiple responsibilities | Split into focused functions with descriptive names |
| Nested ternaries | Requires mental stack to parse | Replace with if/else chains, switch, or lookup objects |
| Boolean parameter flags | `doThing(true, false, true)` | Replace with options objects or separate functions |
| Repeated conditionals | Same `if` check in multiple places | Extract to a well-named predicate function, or a lookup table where the branches are data |
| Long parameter lists (5+ params) | Call sites are positional guesswork | Group the related parameters into a structured object |

**Naming and readability:**

| Pattern | Signal | Simplification |
|---------|--------|----------------|
| Generic names | `data`, `result`, `temp`, `val`, `item` | Rename to describe the content: `userProfile`, `validationErrors` |
| Abbreviated names | `usr`, `cfg`, `btn`, `evt` | Use full words unless the abbreviation is universal (`id`, `url`, `api`) |
| Misleading names | Function named `get` that also mutates state | Rename to reflect actual behavior |
| Comments explaining "what" | `// increment counter` above `count++` | Delete the comment — the code is clear enough |
| Comments explaining "why" | `// Retry because the API is flaky under load` | Keep these — they carry intent the code can't express |
| Imperative loop doing a map/filter/reduce | Intent buried in accumulator bookkeeping | Replace with the declarative equivalent — **only** where clarity genuinely improves; a `reduce` nobody can read is not a simplification |

**Redundancy:**

| Pattern | Signal | Simplification |
|---------|--------|----------------|
| Duplicated logic | Same 5+ lines in multiple places | Extract to a shared function |
| Dead code | Unreachable branches, unused variables, unused imports, whole unreferenced files, commented-out blocks | Remove — after confirming nothing references it |
| Settled feature flags | Flag guarding a feature confirmed shipped or killed | Remove the flag and collapse the branch that can no longer be taken |
| Leftover debug logging | Trace/`console` calls on a production path | Remove |
| Resolved TODOs | `TODO` with no issue-tracker reference | Remove; keep only TODOs that carry a tracker reference |
| Magic constants | Same literal appearing in multiple places | Move to a named constant in the module's config |
| Unnecessary abstractions | Wrapper that adds no value | Inline the wrapper, call the underlying function directly |
| Over-engineered patterns | Factory-for-a-factory, strategy-with-one-strategy | Replace with the simple direct approach |
| Redundant type assertions | Casting to a type that's already inferred | Remove the assertion |

### Rules

- Establish a green baseline **before** you touch anything: run the suite first. A suite that was already red cannot prove your refactor preserved behavior.
- One simplification at a time; run the test suite after each. Pass → continue/commit. Fail → revert and reconsider.
- One *kind* of change per pass and per report — never mix performance work, abstraction extraction, and cleanup in a single pass.
- Refactoring changes ship separately from feature or bug-fix changes — never combine in one PR.
- **The Rule of 500:** a refactor touching more than 500 lines uses automation (codemods, sed scripts, AST transforms), never hand-editing.

### Verification Checklist

After completing a simplification pass:

- [ ] All existing tests pass without modification
- [ ] Build succeeds with no new warnings
- [ ] Linter/formatter passes (no style regressions)
- [ ] Each simplification is a reviewable, incremental change
- [ ] The diff is clean — no unrelated changes mixed in
- [ ] Simplified code follows project conventions (checked against CLAUDE.md or equivalent)
- [ ] No error handling was removed or weakened
- [ ] No dead code was left behind (unused imports, unreachable branches)
- [ ] A teammate or review agent would approve the change as a net improvement

### Escalate When

| WHEN | DO |
|---|---|
| A simplification only passes by modifying tests | Revert it; report to the Orchestrator (manager) — behavior likely changed |
| Can't answer why the code exists (Chesterton's Fence) even after reading context | Ask the Orchestrator (manager) before touching it |
| The needed refactor exceeds the task's scope or the Rule of 500 | Report to the Orchestrator (manager) instead of expanding scope |

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Code simplification deep dive](references/code-simplification-deep-dive.md) — when to use and when not to, worked before/after examples for each principle, the full Chesterton's Fence question list, incremental-change and verification process detail, language-specific guidance (TypeScript, Python, React), common rationalizations, and red flags.
