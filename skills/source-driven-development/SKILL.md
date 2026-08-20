---
name: source-driven-development
description: Grounds every implementation decision in official documentation. Use when you want authoritative, source-cited code free from outdated patterns. Use when building with any framework or library where correctness matters. Squad-internal execution contract loaded by agents via their Methodology Dependencies table.
---

# Source-Driven Development

Every framework-specific code decision traces to official documentation, never memory — training data goes stale and APIs deprecate.

## Worker Execution Contract

### Step 1: Detect Stack and Versions

Read the project's dependency file to identify exact versions:

```
package.json    → Node/React/Vue/Angular/Svelte
composer.json   → PHP/Symfony/Laravel
requirements.txt / pyproject.toml → Python/Django/Flask
go.mod          → Go
Cargo.toml      → Rust
Gemfile         → Ruby/Rails
```

State the detected stack and versions explicitly before fetching docs. Don't guess — the version determines which patterns are correct. Missing/ambiguous versions: see Escalate When.

### Step 2: Fetch Official Documentation

Fetch the specific documentation page for the feature you're implementing. Not the homepage, not the full docs — the relevant page.

**Source hierarchy (in order of authority):**

| Priority | Source | Example |
|----------|--------|---------|
| 1 | Official documentation | react.dev, docs.djangoproject.com, symfony.com/doc |
| 2 | Official blog / changelog | react.dev/blog, nextjs.org/blog |
| 3 | Web standards references | MDN, web.dev, html.spec.whatwg.org |
| 4 | Browser/runtime compatibility | caniuse.com, node.green |

**Not authoritative — never cite as primary sources:**

- Stack Overflow answers
- Blog posts or tutorials (even popular ones)
- AI-generated documentation or summaries
- Your own training data (that is the whole point — verify it)

Be precise with what you fetch — the specific reference page, not the homepage (examples: [deep dive](references/source-driven-deep-dive.md)).

After fetching, extract key patterns and note deprecation/migration guidance. Official sources conflicting with each other (e.g. migration guide vs. API reference) → surface the discrepancy and verify which pattern works against the detected version.

### Step 3: Implement Following Documented Patterns

Write code that matches what the documentation shows:

- Use the API signatures from the docs, never from memory.
- Never guess framework-specific component tags or props (e.g. Quasar, Vuetify) — verify exact names and usage in official docs first.
- Docs show a new way → use it. Docs deprecate a pattern → don't use it.
- Docs don't cover something → flag it as unverified.
- Docs conflict with existing project code → surface the conflict with both options to the user. NEVER silently pick one.

### Step 4: Cite Your Sources

Every framework-specific pattern gets a citation. The user must be able to verify every decision.

**Citation rules:**

- Full URLs, not shortened
- Prefer deep links with anchors (e.g. `/useActionState#usage`) — they survive doc restructuring better than top-level pages
- Quote the relevant passage when it supports a non-obvious decision
- Include browser/runtime support data when recommending platform features
- If you cannot find documentation for a pattern, say so explicitly:

```
UNVERIFIED: I could not find official documentation for this
pattern. This is based on training data and may be outdated.
Verify before using in production.
```

### Verification

After implementing with source-driven development:

- [ ] Framework and library versions were identified from the dependency file
- [ ] Official documentation was fetched for framework-specific patterns
- [ ] All sources are official documentation, not blog posts or training data
- [ ] Code follows the patterns shown in the current version's documentation
- [ ] Non-trivial decisions include source citations with full URLs
- [ ] No deprecated APIs are used (checked against migration guides)
- [ ] Conflicts between docs and existing code were surfaced to the user
- [ ] Anything that could not be verified is explicitly flagged as unverified

### Escalate When

- Versions are missing or ambiguous → ask the user (main session) or surface the ambiguity in your `<handoff>` to the Orchestrator (manager) when delegated.
- Docs conflict with the existing codebase and the choice materially affects the deliverable → surface both options; report to the Orchestrator when delegated.
- Official documentation is unreachable or doesn't cover the pattern → flag the code as UNVERIFIED and note it in your report to the Orchestrator.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Source-driven deep dive](references/source-driven-deep-dive.md) — when (not) to use this skill, the STACK DETECTED example, extended fetch good/bad examples, in-code and in-conversation citation examples, the CONFLICT DETECTED walkthrough, the Common Rationalizations table, and red flags.
