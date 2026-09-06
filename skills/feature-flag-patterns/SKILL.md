---
name: feature-flag-patterns
description: "Provides the feature flag execution contract: every flag created with a named owner, an expiry and a removal task already in the plan; default-off; kill-switch semantics that fail to the safe state; config-as-code rather than a hand-edited row; both branches tested; and an expired flag treated as a plan-level blocker rather than a comment. Use if the project gates behaviour behind a runtime flag. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Also directly invocable: when a user asks to add, flip, or remove a named flag outside a pipeline, the Orchestrator applies the Worker Execution Contract itself in the main session — no delegation."
---

# Feature Flag Patterns

A feature flag is a branch that ships. It buys a decoupling of deploy from release, and it charges for it in permanent conditional complexity — every flag doubles the states the system can be in, and a flag nobody removes charges that rent forever. This contract is mostly about the removal, because the creation is the part that happens on its own.

## Direct invocation

A user can ask to add, flip, or remove a named flag directly — a deliberate refinement of agent-audit Metric 12, not a trigger collision. The Orchestrator applies the Worker Execution Contract inline: no delegation, no unobserved claims (`base-persona.md`, Evidence Integrity). A new flag with no plan to hold its removal task: route via `/bg`.

## Quick card

Five rules; each names the section that owns it.

1. **No flag without an owner, an expiry, and a removal task already in the plan.** (*The declaration*)
2. **Default off; a flag that cannot be read is off, never on.** (*Defaults and kill switches*)
3. **Flag state is config-as-code — never a row edited by hand in production.** (*Config as code*)
4. **Test both branches; an untested off-branch is a rollback nobody has performed.** (*Both branches*)
5. **A flag past its expiry is a plan-level blocker, not a comment.** (*Expiry is a blocker*)

Inline mapping:

- `/bgpdd-plan` — creating a flag: creation and removal tasks are planned together.
- `/bgpdd-lite` — flipping a default, widening a rollout, changing who it reads for.
- `/bgpdd-quick` — removing a settled flag whose collapse touches three files or fewer.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### The declaration

Every flag is declared, in the config the *Config as code* section defines, with four fields and no exceptions:

```
checkout-v2:
  owner: <the person or team who decides its fate>
  kind: release | kill-switch
  expiry: <YYYY-MM-DD>        # release flags; kill switches carry `review: <YYYY-MM-DD>`
  removal-task: <task id in the plan that deletes it>
  default: off
```

`owner` is a name, never "the team that owns the service" — an unnamed owner is nobody. `expiry` is the date by which the flag is expected to be gone, chosen when it is created and while the intent is still known; a flag created without one is created with an expiry of *never*, whatever the comment beside it says.

**`kind` picks which clock applies.** A **release flag** is temporary scaffolding for an in-progress rollout and carries an `expiry`. A **kill switch** is a permanent operational control and carries a `review` date instead — a deliberate exception to *Expiry is a blocker*, not an escape from it: an unreviewed kill switch is the same finding, raised on the review date.

### The removal task is created at creation time

The task that deletes the flag is written into the plan **in the same planning pass that authorizes the flag**, following `{PLUGIN_ROOT}/planning-and-task-breakdown/SKILL.md`'s task grammar. Not a TODO, not a ticket to be filed later, not an item in a `Future` section — a numbered task with acceptance criteria, sequenced after the rollout it is waiting on.

Express the seam in that skill's machine-parseable `Boundary contracts:` line, so the ordering is enforced by the `consumes-provides` lint rather than by anyone remembering:

- The creation task leads its `Boundary contracts:` with `provides: flag.checkout-v2; consumes: None`.
- Every task whose behaviour is gated by the flag leads with `consumes: flag.checkout-v2`.
- The removal task leads with `consumes: flag.checkout-v2` and provides whatever the collapsed branch now provides unconditionally.

The identifier names the **live flag**, not the config file that declares it — that is rule 2 of *Plans model effects, not artifacts* in the planning skill, applied here; a task that authors the config and a task that makes the flag readable at runtime are separate identifiers when they are separate tasks.

### Defaults and kill switches

- **Default off.** A new flag is off in every environment including the developer's. On is a decision someone makes and records, never the state a flag arrives in.
- **Fail to the safe branch.** If the flag cannot be read — the config is missing, the store is unreachable, the value does not parse — the code takes the *off* path. A read failure that throws, or that defaults to on, converts an outage in the flag system into an outage in the feature.
- **A kill switch is read per request, not per process.** A switch you have to redeploy or restart to flip is not a kill switch; it is a config constant with an optimistic name. Say in the task which one you built.
- **One flag, one decision.** A flag that gates three unrelated behaviours cannot be turned off for one of them, which is the only reason anyone ever wanted it.

### Config as code

Flag declarations and their per-environment defaults live in a **versioned file in the repository**, reviewed like any other change. Never a row edited by hand in a production database or a vendor console: that is a behaviour change with no diff, no review, no author, and no revert — and it is invisible to every gate in this plugin.

A managed flag service is compatible with this rule as long as the declaration and its defaults are applied from committed configuration. What is forbidden is the *hand edit*, not the service.

### Both branches

The suite exercises the flag **on and off** for every behaviour the flag gates. An off-branch with no test is a rollback path nobody has ever executed — which is precisely the path that will be taken, under pressure, on the worst day.

Where the flag's effect is client-observable, the off-branch needs its own capture, not an inference from the on-branch: `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` owns that rule and its citation grammar.

### Expiry is a blocker

A flag past its `expiry` (or a kill switch past its `review`) is a **plan-level blocker**, raised to the Orchestrator as a finding — not a comment added beside the flag, not a date pushed out because the removal is inconvenient this week. Pushing the date is a decision the owner makes explicitly and records; doing it silently is how a two-week flag becomes a four-year one.

The **removal trigger** is the `code-simplification` skill's *settled feature flag* signal — a flag guarding a feature confirmed shipped or killed. That skill owns the signal and the collapse; do not restate either here. When it fires, the removal task written at creation time is the task you execute.

### Verification Checklist

- [ ] Every new flag declares `owner`, `kind`, `expiry` (or `review`), `removal-task` and `default: off`
- [ ] The removal task exists in the plan, numbered and with acceptance criteria, before the flag ships
- [ ] `Boundary contracts:` lines carry the flag identifier, and the `consumes-provides` lint passes
- [ ] The declaration and its defaults are in a committed file; no hand-edited row or console change
- [ ] The suite covers both branches of every gated behaviour, off-branch included
- [ ] A read failure of the flag store demonstrably takes the off path
- [ ] No flag in the config is past its `expiry` or `review` date

### Escalate When

| WHEN | DO |
|---|---|
| A flag is requested with no owner, no expiry, or no plan to put the removal task in | Report to the Orchestrator (manager) before creating it; the flag is the easy half |
| A flag in the config is past its `expiry` or `review` | Raise it as a plan-level blocker (*Expiry is a blocker*); never extend the date yourself |
| The removal would collapse a branch you cannot prove is settled | Report to the Orchestrator (manager) — the `code-simplification` signal has not fired |
| Flag state is only changeable by hand in production, with no committed configuration | Report it; do not make the hand edit, and do not build on it (*Config as code*) |
| One flag gates several unrelated behaviours and the ask is to turn off just one | Report to the Orchestrator (manager); splitting the flag is a planning change, not a build-time fix |

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Flag lifecycle](references/flag-lifecycle.md) — the five stages from declaration to deletion, the release-flag versus kill-switch split in full, worked removal-task shapes, the flag-debt review, and the anti-pattern table.
