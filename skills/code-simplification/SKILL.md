---
name: code-simplification
description: Simplifies code for clarity. Use when refactoring code for clarity without changing behavior. Use when code works but is harder to read, maintain, or extend than it should be. Use when reviewing code that has accumulated unnecessary complexity. Squad-internal execution contract loaded by agents via their Methodology Dependencies table.
---

# Code Simplification

> Inspired by the [Claude Code Simplifier plugin](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/code-simplifier/agents/code-simplifier.md). Adapted here as a model-agnostic, process-driven skill for any AI coding agent.

Reduce complexity while preserving exact behavior — not fewer lines, but code easier to read, understand, modify, and debug. Test: would a new team member understand this faster than the original?

## Worker Execution Contract

This is the operational spine. Follow it as written.

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
| Repeated conditionals | Same `if` check in multiple places | Extract to a well-named predicate function |

**Naming and readability:**

| Pattern | Signal | Simplification |
|---------|--------|----------------|
| Generic names | `data`, `result`, `temp`, `val`, `item` | Rename to describe the content: `userProfile`, `validationErrors` |
| Abbreviated names | `usr`, `cfg`, `btn`, `evt` | Use full words unless the abbreviation is universal (`id`, `url`, `api`) |
| Misleading names | Function named `get` that also mutates state | Rename to reflect actual behavior |
| Comments explaining "what" | `// increment counter` above `count++` | Delete the comment — the code is clear enough |
| Comments explaining "why" | `// Retry because the API is flaky under load` | Keep these — they carry intent the code can't express |

**Redundancy:**

| Pattern | Signal | Simplification |
|---------|--------|----------------|
| Duplicated logic | Same 5+ lines in multiple places | Extract to a shared function |
| Dead code | Unreachable branches, unused variables, commented-out blocks | Remove (after confirming it's truly dead) |
| Unnecessary abstractions | Wrapper that adds no value | Inline the wrapper, call the underlying function directly |
| Over-engineered patterns | Factory-for-a-factory, strategy-with-one-strategy | Replace with the simple direct approach |
| Redundant type assertions | Casting to a type that's already inferred | Remove the assertion |

### Rules

- One simplification at a time; run the test suite after each. Pass → continue/commit. Fail → revert and reconsider.
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
