---
name: bg
description: "The front door for everyday work: classifies the request and invokes exactly one bgPDD lane, so you never have to know the lane names. Use when the ask is ordinary and the right lane is not obvious — 'help me with this', 'quick change', 'small fix', 'add a test', 'clean this up', 'can you sort this out', 'I'm not sure which lane', or '/bg <anything>'. Routes only; never does the work itself."
trigger: /bg
category: routing
risk: safe
---

# bg — Lane Router

## Purpose
One front door. Classify the request, then invoke exactly **one** lane — or say plainly that none applies. **This skill never performs the work**: no edits, no delegations, no gates. If you are reading source to answer the ask, you have left the router.

## When to Use This Skill
- The user asks for ordinary work without naming a lane.
- The user types `/bg …`.
- **NOT** when the user already named a lane — honour it (see *Named lane wins*).

## Routing

Check the **state rows** first; if none matches, answer the three questions in order and stop at the first `yes`.

| The ask | Lane | What it costs |
|---|---|---|
| "it's built — ship it" | `bgpdd-shipping` | Launch Squad — Vera, Cipher, Dep — plus the ship-decision gate. |
| "prove a discovered feature still works", no code change | `bgpdd-verify` | Quinn automates the acceptance matrix against the running app; runtime-evidence gate. |
| "what did we learn" | `bgpdd-learn` | One Forge triage; nothing is written without your approval. |
| "get <squad member> to do this" | *no lane* | Ad-hoc squad use — routing triggers live in `{PLUGIN_ROOT}/agent-squad/SKILL.md`. |

| # | Question | Lane | What it costs |
|---|---|---|---|
| 1 | Is there a **reproduction of wrong behaviour** — an error, a red test, "it used to work"? | `bgpdd-bugfix` | ~4 delegations (Quinn RED, builder, Quinn GREEN, Luna) and the intake/red-green/route/commit gates. |
| 2 | Does it need a **new capability, schema, or contract** — or is the spec still unknown? | `bgpdd-plan` | Heaviest lane: Rex Q&A, Aria, Alex, then `/bgpdd-build`. |
| 2a | …and is the codebase **unmapped** (no `.docs/summary/` in the repo)? | `bgpdd-discovery` **first** | Iris, Scout and Echo write the Tier-1 knowledge base; plan follows. |
| 3 | Is it **≤ 3 files** with no behaviour anyone outside them depends on? | `bgpdd-quick` | Cheapest: main session only, no delegation, one closing gate. |
| 3a | …else: is the spec **already known** and the pattern established in this repo? | `bgpdd-lite` | Mini-requirements with you, Alex plans, `/bgpdd-build` executes; keeps the coverage gate. |

Nothing fits (a question, a read, a one-line answer): say so, and do it in the main session with whichever methodology skill fits. Over 3 files with a known spec but no established pattern is `bgpdd-lite` too — question 3a's "established" only decides whether Alex needs Aria's design, which is `bgpdd-plan`'s job (question 2).

The cost column lets the user push back *before* a lane spends anything. It is a summary: each lane's own `{PLUGIN_ROOT}/bgpdd-<lane>/SKILL.md` — `{PLUGIN_ROOT}/bgpdd-quick/SKILL.md` included — is authoritative, and this file restates none of it.

## Procedure

1. **Classify** — walk the tables top to bottom.
2. **Announce in one line, then invoke, in the same turn**: "Reads as *<the answer that fired>* → invoking the `bgpdd-<x>` skill." Then invoke it. Never announce a lane you do not then invoke.
3. **The lane owns everything after that** — its phases, its gates, its confirmations. Add none of your own.

### Named lane wins
If the message names a lane, invoke that one. Do not re-classify. State any reservation in the same line, then invoke what was asked.

### Ambiguity: exactly one question
When two lanes fit and nothing in the message separates them, ask **the single question that separates them** — never a menu of lanes. Bugfix vs plan: "Does it behave wrong today, or is this new behaviour?" Quick vs lite: "Does anything outside those files depend on this?" (a *yes* is lite; a *no* stays quick)

> **Refines Orchestrator Contract §1 *Phase Transitions* — deliberately looser (convention #8).** That rule requires explicit confirmation before a phase starts. Routing is not a phase, and the lane's own first step confirms anyway, so confirming here asks the same thing twice. The router invokes without confirmation, and pays for it with the one-question rule above — the only place it may stop.

### The ratchet
A lane escalates **upward** when its own bound trips — quick → bugfix/lite/plan, lite → plan, bugfix → plan — and **never downward mid-run**. Escalation is that lane's own decision under its own rule; the router does not re-enter to authorize it, and a lane that turns out cheaper than expected still finishes where it started.
