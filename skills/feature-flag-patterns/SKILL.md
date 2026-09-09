---
name: feature-flag-patterns
description: "Provides the feature flag execution contract: every flag created with a named owner, an expiry and a removal task already in the plan; default-off; kill-switch semantics that fail to the safe state; config-as-code rather than a hand-edited row; both branches tested; and an expired flag treated as a plan-level blocker rather than a comment. Use if the project gates behaviour behind a runtime flag. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Also directly invocable: when a user asks for this on named files outside a pipeline, the Orchestrator applies the Worker Execution Contract itself in the main session — no delegation."
---

# Feature Flag Patterns

A feature flag is a branch that ships. It buys a decoupling of deploy from release and charges permanent conditional complexity for it, and a flag nobody removes charges that rent forever. This contract is mostly about the removal, because the creation is the part that happens on its own. This skill is the **owner** of the flag lifecycle; `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md` (*Feature Flag Strategy*) carries the rollout staging and cites back here.

## Direct invocation

A user can ask for this directly on named files outside a pipeline — a deliberate refinement of agent-audit Metric 12, not a trigger collision. The Orchestrator applies the Worker Execution Contract inline, in the main session: no delegation, no unobserved claims (`base-persona.md`, Evidence Integrity). **Scope: three files or fewer, and a flag that already exists.** Anything larger, and every new flag, routes through `/bg`:

- `/bgpdd-plan` — creating a flag: creation and removal tasks are planned together.
- `/bgpdd-lite` — flipping a default, widening a rollout, changing who it reads for.
- `/bgpdd-quick` — removing a settled flag whose collapse touches three files or fewer. The lane admits any skill carrying a `## Quick card`, this one included.

## Quick card

Derived from the contract below for a ≤ 3-file change; no new rules (convention #8 — deliberately narrower than the full contract, which binds inside any lane).

1. No flag without an owner, an expiry, and a removal task already in the plan (§ The declaration).
2. Default off; a flag that cannot be read is off, never on (§ Defaults and kill switches).
3. Flag state is config-as-code — never a row edited by hand in production (§ Config as code).
4. Test both branches; an untested off-branch is a rollback nobody has performed (§ Both branches).
5. A flag past its expiry is a plan-level blocker, not a comment (§ Expiry is a blocker).

- Brief → the quick note (What / Where / How verified)
- Artifact → the capture at `{quick-root}/evidence/check.md`
- Handoff → the `## Result` bullet in `note.md`

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

`owner` is a name, never "the team that owns the service". `expiry` is the date by which the flag is expected to be gone, chosen at creation while the intent is still known ([flag-lifecycle.md](references/flag-lifecycle.md)).

**`kind` picks which clock applies.** A **release flag** is temporary rollout scaffolding and carries an `expiry`. A **kill switch** is a permanent operational control and carries a `review` date instead — a deliberate exception to *Expiry is a blocker*, not an escape from it: an unreviewed kill switch is the same finding, raised on the review date.

### The removal task is created at creation time

The task that deletes the flag is written into the plan **in the same planning pass that authorizes the flag** — a numbered task with acceptance criteria, sequenced after the rollout it waits on. Not a TODO, not a ticket filed later, not a `Future` section item.

**The producer's end is documented for the planner** in `{PLUGIN_ROOT}/planning-and-task-breakdown/SKILL.md` (§ Contract-change tags), which owns the task grammar. Express the seam in its `Boundary contracts:` line, so ordering is enforced by the `consumes-provides` lint rather than by anyone remembering:

- The creation task leads its `Boundary contracts:` with `provides: flag.checkout-v2; consumes: None`.
- Every task whose behaviour is gated by the flag leads with `consumes: flag.checkout-v2`.
- The removal task leads with `consumes: flag.checkout-v2` and provides whatever the collapsed branch now provides unconditionally.

The identifier names the **live flag**, not the config file that declares it — rule 2 of *Plans model effects, not artifacts* in the planning skill, applied here.

### Defaults and kill switches

- **Default off**, in every environment including the developer's. On is a decision someone makes and records.
- **Fail to the safe branch.** If the flag cannot be read — config missing, store unreachable, value unparseable — the code takes the *off* path. A read that throws, or defaults to on, converts an outage in the flag system into an outage in the feature.
- **A kill switch is read per request, not per process.** One you must redeploy or restart to flip is a config constant with an optimistic name; say in the task which you built.
- **One flag, one decision.** A flag gating three unrelated behaviours cannot be turned off for one of them.
- **Never nest flags.** Two flags on one path produce four states and a combination nobody tested; split the path or sequence the flags.

### Config as code

Flag declarations and their per-environment defaults live in a **versioned file in the repository**, reviewed like any other change. Never a row hand-edited in a production database or vendor console: that is a behaviour change with no diff, no review, no author and no revert. A managed flag service is fine as long as declarations and defaults are applied from committed configuration — the *hand edit* is what is forbidden, not the service.

### Both branches

The suite exercises the flag **on and off** for every behaviour it gates. An off-branch with no test is a rollback path nobody has ever executed.

Where the flag's effect is client-observable, the off-branch needs its own capture, not an inference from the on-branch: `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` owns that rule and its citation grammar.

### Expiry is a blocker

A flag past its `expiry` (or a kill switch past its `review`) is a **plan-level blocker**, raised to the Orchestrator as a finding — not a comment added beside the flag, not a date pushed out because the removal is inconvenient this week. Pushing the date is a decision the owner makes explicitly and records.

**The date is scanned, not remembered (convention #9).** `{PLUGIN_ROOT}/shipping-and-launch/SKILL.md` (*Feature Flag Strategy*) carries the mandated `expiry` scan and the flag-debt review in its pre-launch checklist; a flag-touching lane that does not reach shipping runs the same capture at its own close. Every date the capture shows at or before the run date is a finding.

The **removal trigger** is the `code-simplification` skill's *settled feature flag* signal — a flag guarding a feature confirmed shipped or killed. That skill owns the signal and the collapse; do not restate either here. When it fires, the removal task written at creation time is the task you execute.

### Verification Checklist

- [ ] Every new flag declares `owner`, `kind`, `expiry` (or `review`), `removal-task` and `default: off`
- [ ] The removal task exists in the plan, numbered and with acceptance criteria, **before the flag is declared**
- [ ] `Boundary contracts:` lines carry the flag identifier, and the `consumes-provides` lint passes
- [ ] The declaration and its defaults are in a committed file; no hand-edited row or console change
- [ ] The suite covers both branches of every gated behaviour, off-branch included
- [ ] A read failure of the flag store demonstrably takes the off path
- [ ] No flag nests inside another flag's gated path
- [ ] The `expiry` scan ran, and no flag in the config is past its `expiry` or `review` date (§ Expiry is a blocker)

### Escalate When

| WHEN | DO |
|---|---|
| A flag is requested with no owner, no expiry, or no plan to put the removal task in | Escalate to the Orchestrator before creating it; the flag is the easy half |
| A flag in the config is past its `expiry` or `review` | Report it to the Orchestrator as a plan-level blocker (*Expiry is a blocker*); never extend the date yourself |
| The removal would collapse a branch you cannot prove is settled | Escalate to the Orchestrator — the `code-simplification` signal has not fired |
| Flag state is only changeable by hand in production, with no committed configuration | Report it to the Orchestrator; do not make the hand edit, and do not build on it (*Config as code*) |
| One flag gates several unrelated behaviours and the ask is to turn off just one | Escalate to the Orchestrator; splitting the flag is a planning change, not a build-time fix |
| The ask is to add a flag inside a path another flag already gates | Return it unbuilt as a planning defect (*Defaults and kill switches*) |

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Flag lifecycle](references/flag-lifecycle.md) — the five stages from declaration to deletion, the release-flag versus kill-switch split in full, why an unexpired flag is created with an expiry of *never*, worked removal-task shapes, the flag-debt review, and the anti-pattern table.
