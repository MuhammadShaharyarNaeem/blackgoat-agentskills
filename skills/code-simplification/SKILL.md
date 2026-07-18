---
name: code-simplification
description: Simplifies code for clarity. Use when refactoring code for clarity without changing behavior. Use when code works but is harder to read, maintain, or extend than it should be. Use when reviewing code that has accumulated unnecessary complexity. Squad-internal execution contract loaded by agents via their Methodology Dependencies table.
---

# Code Simplification

> Inspired by the [Claude Code Simplifier plugin](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/code-simplifier/agents/code-simplifier.md). Adapted here as a model-agnostic, process-driven skill for any AI coding agent.

Simplify code by reducing complexity while preserving exact behavior. The goal is not fewer lines — it's code that is easier to read, understand, modify, and debug. Every simplification must pass a simple test: **"Would a new team member understand this faster than the original?"**

## Worker Execution Contract

This is the operational spine. Follow it as written.

### The Five Principles

1. **Preserve behavior exactly.** Change how the code expresses itself, never what it does. Ask before every change: Does this produce the same output for every input? Does this maintain the same error behavior? Does this preserve the same side effects and ordering? Do all existing tests still pass without modification? If unsure, don't make the change.
2. **Follow project conventions.** Match the codebase (CLAUDE.md, neighboring code) for imports, declaration style, naming, error handling, and type annotation depth. Simplification that breaks project consistency is not simplification — it's churn.
3. **Prefer clarity over cleverness.** Explicit code beats compact code when the compact version requires a mental pause to parse.
4. **Maintain balance.** Avoid the over-simplification traps: inlining too aggressively (removing a helper that gave a concept a name); combining unrelated logic into one complex function; removing abstractions that exist for extensibility or testability; optimizing for line count instead of comprehension.
5. **Scope to what changed.** Default to simplifying recently modified code; no drive-by refactors of unrelated code unless explicitly asked.

### Chesterton's Fence

Understand why code exists — check git blame — before removing or changing it. If you can't answer why it was written this way, don't simplify it; read more context first.

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

- Make **one simplification at a time**; run the test suite after each change. Tests pass → commit (or continue); tests fail → revert and reconsider.
- Submit refactoring changes separately from feature or bug fix changes — a PR that refactors and adds a feature is two PRs.
- **The Rule of 500:** if a refactoring would touch more than 500 lines, invest in automation (codemods, sed scripts, AST transforms) rather than making the changes by hand.

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

- A simplification only passes by modifying tests → revert it and report to the Orchestrator (manager); behavior likely changed.
- You can't answer why the code exists (Chesterton's Fence) even after reading context → ask the Orchestrator (manager) before touching it.
- The needed refactor exceeds the current task's scope or the Rule of 500 → report to the Orchestrator (manager) instead of expanding scope.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Code simplification deep dive](references/code-simplification-deep-dive.md) — when to use and when not to, worked before/after examples for each principle, the full Chesterton's Fence question list, incremental-change and verification process detail, language-specific guidance (TypeScript, Python, React), common rationalizations, and red flags.
