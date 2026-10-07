---
name: bg
description: "The front door for everyday work: classifies the request and invokes exactly one bgPDD lane, so you never have to know the lane names. Use when the ask is ordinary and the right lane is not obvious — 'help me with this', 'quick change', 'small fix', 'add a test', 'clean this up', 'can you sort this out', 'I'm not sure which lane', or '/bg <anything>'. Routes only; never does the work itself."
trigger: /bg
category: routing
risk: safe
---

# bg — Lane Router

## Purpose
One front door. Classify the request, then invoke exactly **one** lane (or one directly-invocable methodology skill, per the table) — or say plainly that none applies. **This skill never performs the work**: no edits, no delegations, no gates. If you are reading source to answer the ask, you have left the router.

## When to Use This Skill
- The user asks for ordinary work without naming a lane.
- The user types `/bg …`.
- **NOT** when the user already named a lane — honour it (see *Named lane wins*).

## Routing

Check the **state rows** first; if none matches, answer the three questions in order and stop at the first `yes`. **The order is load-bearing, not a convenience**: "execute the existing plan" answers *yes* to question 2 (it does need a new capability — that is what the plan is for) and would re-plan work that is already planned; the `bgpdd-build` state row fires first and reads the plan instead. Row 2a's discovery entry survives as the *plan-first* branch; the discovery state row above is the standalone ask, where nothing is being planned yet.

| The ask | Lane | What it costs |
|---|---|---|
| "execute the plan" / "carry on with the build" — a `.docs/<project>/implementation/plan.md` exists with unchecked milestones | `bgpdd-build` | Mason or Nova per milestone tag, plus Quinn, Luna, Dep; the coverage and commit gates. |
| "map this codebase" / "how does this repo work" — or the ask needs today's behaviour and there is no `.docs/summary/` | `bgpdd-discovery` | Iris, Scout and Echo write the Tier-1 knowledge base. |
| "it's built — ship it" | `bgpdd-shipping` | Launch Squad — Vera, Cipher, Dep — plus the ship-decision gate. |
| "prove a discovered feature still works", no code change | `bgpdd-verify` | Quinn automates the acceptance matrix against the running app; runtime-evidence gate. |
| "security audit this app" / "pentest this app" / "check for vulnerabilities" / "privacy audit this app" | `bgpdd-secure` | Cipher (Ward for privacy/compliance rows, Quinn for browser-side probes) execute the attack matrix against the running app; runtime-evidence gate. |
| "what did we learn" | `bgpdd-learn` | One Forge triage; nothing is written without your approval. |
| "get <squad member> to do this" | *no lane* | Ad-hoc squad use — routing triggers live in `{PLUGIN_ROOT}/agent-squad/SKILL.md`. |
| "production is down" / "hotfix this incident" | `bgpdd-bugfix` | Question 1's cost: an incident is a reproduction of wrong behaviour, and urgency buys no skipped gate. |
| "upgrade / bump this dependency" | `dependency-upgrade-patterns` via its Direct invocation | Its owning persona; changelog brief, before/after audit capture, one package per commit. A framework major routes out per that skill. |
| "review this PR" — someone else's change, not one this session made | `code-review-and-quality` via its Direct invocation | Luna's multi-axis review; no edits. |
| "this is slow" / "profile this" | `performance-optimization` via its Direct invocation | Its owning persona. |
| "add logging / metrics / tracing" / "why can't we see what failed" | `observability-and-diagnosis` via its Direct invocation | Its owning persona. |
| docs-only change, **≤ 3 files** | `bgpdd-quick` | Question 3's cost. Over 3 files of docs is `bgpdd-lite`. |
| refactor over **3 files**, no behaviour change | `bgpdd-lite` | Question 3a's cost; the coverage gate proves nothing moved. |

| # | Question | Lane | What it costs |
|---|---|---|---|
| 1 | Is there a **reproduction of wrong behaviour** — an error, a red test, "it used to work"? | `bgpdd-bugfix` | ~4 delegations (Quinn RED, builder, Quinn GREEN, Luna) and the intake/red-green/route/commit gates. |
| 1a | …and are there **two or more independent bugs** for this session? A single bug stays `bgpdd-bugfix`. | `bgpdd-bugfix-batch` | Question 1's cost per bug, in waves, plus a worktree and a merge each. |
| 2 | Does it need a **new capability, schema, or contract** — or is the spec still unknown? | `bgpdd-plan` | Heaviest lane: Rex Q&A, Aria, Alex, then `/bgpdd-build`. |
| 2a | …and is the codebase **unmapped** (no `.docs/summary/` in the repo)? | `bgpdd-discovery` **first** | Iris, Scout and Echo write the Tier-1 knowledge base; plan follows. |
| 3 | Is it **≤ 3 files** with no behaviour anyone outside them depends on? | `bgpdd-quick` | Cheapest: one builder delegation (Mason, Nova or Max), one captured check, one closing gate. |
| 3a | …else: is the spec **already known** and the pattern established in this repo? | `bgpdd-lite` | Mini-requirements with you, Alex plans, `/bgpdd-build` executes; keeps the coverage gate. |

A "via its Direct invocation" row invokes that methodology skill instead of a lane; its `## Direct invocation` section owns what happens next — the Orchestrator delegates to the skill's owning persona, the agent whose Methodology Dependencies table loads it, and never applies the Worker Execution Contract itself. Nothing fits (a question, a read, a one-line answer): say so, and answer it in the main session — anything that edits code goes to a lane. Over 3 files with a known spec but no established pattern is `bgpdd-lite` too — question 3a's "established" only decides whether Alex needs Aria's design, which is `bgpdd-plan`'s job (question 2).

The cost column lets the user push back *before* a lane spends anything. It is a summary: each lane's own `{PLUGIN_ROOT}/bgpdd-<lane>/SKILL.md` — `{PLUGIN_ROOT}/bgpdd-quick/SKILL.md` included — is authoritative, and this file restates none of it.

## Procedure

1. **Classify** — walk the tables top to bottom.
2. **Announce in one line, then invoke, in the same turn**: "Reads as *<the answer that fired>* → invoking the `<x>` skill." Then invoke it. Never announce a lane you do not then invoke.
3. **The lane owns everything after that** — its phases, its gates, its confirmations. Add none of your own.

### Named lane wins
If the message names a lane, invoke that one. Do not re-classify. State any reservation in the same line, then invoke what was asked.

### Ambiguity: exactly one question
When two lanes fit and nothing in the message separates them, ask **the single question that separates them** — never a menu of lanes. Bugfix vs plan: "Does it behave wrong today, or is this new behaviour?" Quick vs lite: "Does anything outside those files depend on this?" (a *yes* is lite; a *no* stays quick) Quick vs bugfix needs no question: a test that goes red **while** the change is being made stays in `bgpdd-quick` with its debugging card, and only a defect that existed **before** the work started, with a reproduction, is `bgpdd-bugfix`.

> **Refines Orchestrator Contract §1 *Phase Transitions* — deliberately looser (convention #8).** That rule requires explicit confirmation before a phase starts. Routing is not a phase, and the lane's own first step confirms anyway, so confirming here asks the same thing twice. The router invokes without confirmation, and pays for it with the one-question rule above — the only place it may stop.

### The ratchet
A lane escalates **upward** when its own bound trips — quick → bugfix/lite/plan, then one chain, bugfix → lite → plan (bugfix never skips lite) — and **never downward mid-run**. Escalation is that lane's own decision under its own rule; the router does not re-enter to authorize it, and a lane that turns out cheaper than expected still finishes where it started.
