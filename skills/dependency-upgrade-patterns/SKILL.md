---
name: dependency-upgrade-patterns
description: "Provides the dependency upgrade execution contract: a changelog-derived Upgrade brief written before any lockfile moves, an audit capture taken before and after the bump and compared, one package (or one coherent group) per commit with its lockfile, a codebase search for every removed or renamed API, `git revert` of that one commit as the rollback, and a framework-major boundary that routes out of the fast lanes. Use if the project bumps a dependency version. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Also directly invocable: when a user asks for a named package bump outside a pipeline, the Orchestrator applies the Worker Execution Contract itself in the main session — no delegation."
---

# Dependency Upgrade Patterns

A version bump is the change most often made without reading anything. The lockfile moves in one command, the suite stays green, and nobody knows which of the versions crossed removed the API that the one untested path calls. This contract makes the reading and the audit comparison the deliverable, and the bump a consequence of them.

## Direct invocation

A user can ask for a named package bump directly — a deliberate refinement of agent-audit Metric 12, not a trigger collision. The Orchestrator applies the Worker Execution Contract below inline, in the main session: no delegation, no unobserved claims (`base-persona.md`, Evidence Integrity). A framework major, or several packages at once: route via `/bg`.

## Quick card

Five rules; each names the section that owns it.

1. **Read every version crossed, then write the `## Upgrade brief` — before the lockfile moves.** (*Step 1*)
2. **Capture suite and audit BEFORE the bump, audit again after, compare the two.** (*Steps 2, 5*)
3. **Search the codebase for every removed or renamed API before running anything.** (*Step 3*)
4. **One package per commit, its lockfile with it, never a wildcard bump.** (*Step 6*)
5. **A framework major is not a quick change; route it.** (*Framework majors*)

Inline mapping:

- `/bgpdd-quick` — one patch or minor bump, no breaking change in the brief.
- `/bgpdd-lite` — a breaking change with a migration, or one coherent group.
- `/bgpdd-plan` — a framework major, or a breaking change with no migration.

## Worker Execution Contract

This is the operational spine. Follow it as written. Steps run in order; none is optional.

### Step 1 — Write the Upgrade brief first

Read the changelog or release notes for **every version crossed**, not only the target. Then write an `## Upgrade brief` section into the report you already owe (the task's `test-report.md` block, `{quick-root}/note.md`, or the mini-requirements — whichever the lane gives you), **before any lockfile changes**:

```
## Upgrade brief
- Package: <name>, <current> -> <target>
- Versions crossed: <every version between, inclusive of the target>
- Breaking changes: <one line each, or "none stated in the notes">
  - <removed or renamed API> -> <replacement>; migration: <doc section or link>
- Call sites in this repo: <path::symbol, one per line, or "none">
- Audit command: <the exact command this stack uses>
```

Field-by-field guidance and a filled example: [upgrade-brief-template.md](references/upgrade-brief-template.md).

A version whose notes you could not find is **not** a version with no breaking changes — it is a breaking change of unknown shape. Record it as `unknown` and escalate rather than reading silence as safety.

### Step 2 — Characterize before you bump

Before the first edit, and in this order:

1. **The existing suite.** It must be green. A suite that was already red cannot prove the bump preserved behaviour — the rule and its rationale belong to `{PLUGIN_ROOT}/code-simplification/SKILL.md` (Rules); this contract only names when it applies.
2. **The audit command**, captured:

```
python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture .docs/{project-name}/implementation/evidence/upgrade/audit-before-<package>.md -- <audit command>
```

`<audit command>` is the stack's: `npm audit`, `dotnet list package --vulnerable`, `pip-audit`, or the wrapper the project declares. A non-zero exit is a legitimate capture — you are recording what the tree looked like, not asserting it was clean.

> **Deliberate divergence from `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`'s capture location (convention #8).** That skill puts captures under `evidence/runtime/` because they observe the running application. An audit capture observes the dependency graph, so it lands under `evidence/upgrade/` and claims no tier. The **citation grammar is unchanged**, and that skill still owns it.

### Step 3 — Search for the removed API before you run anything

For every API the brief marks removed or renamed, search the whole codebase — source, tests, scripts, config, generated clients — and add each hit to the brief's *Call sites* field. Do this **before** you run the bump, not after the suite tells you.

A transitive break is found by reading, never by a green suite: the suite covers only the paths it covers, and the path calling the removed helper once, in an error branch, is exactly the path it does not.

### Step 4 — Bump exactly one thing

Change the version of **one package**, or one coherent group that genuinely must move together (a framework's own sibling packages; a library and its typings). Pin an exact version — never a range widened to "latest", never a blanket `npm update` / `dotnet outdated -u` / `pip install -U -r`. Then update every call site the brief listed, and nothing else.

### Step 5 — Characterize after, and compare

Re-run the suite, then re-run the **same** audit command into `audit-after-<package>.md` through the same `run_quiet.py --capture` invocation. Read the two captures side by side and state the delta in the report: advisories resolved, advisories introduced, advisories unchanged.

Cite both with the grammar owned by `{PLUGIN_ROOT}/runtime-evidence/SKILL.md`:

```
**Runtime evidence:** evidence/upgrade/audit-before-<package>.md, evidence/upgrade/audit-after-<package>.md
```

**The two captures are the evidence; your sentence about them is not.** "No new vulnerabilities" without both captures cited is an unobserved claim (`{PLUGIN_ROOT}/agent-squad/base-persona.md`, Evidence Integrity).

### Step 6 — One commit, and say how to undo it

The commit contains the manifest, **its lockfile**, and the call sites the brief listed — nothing else. A lockfile committed separately from the manifest that moved it leaves an intermediate commit no clean install reproduces.

State the rollback explicitly in the report: **`git revert <sha>` of that one commit.** That is the whole reason for one package per commit — it is what makes a single bad bump revertible without unpicking four good ones.

### Framework majors

A major bump of a framework — Vue major, .NET major, EF Core major, Angular major, Django major, or an equivalent — is **not** a quick change, however small the diff looks. Do not perform one under this contract.

Route it via `/bg` to `{PLUGIN_ROOT}/bgpdd-lite/SKILL.md`, handing the **Upgrade brief as the mini-requirements**: the versions crossed become the scope, and each breaking change with its migration becomes a requirement Alex can plan and the coverage gate can check.

### Verification Checklist

Before marking upgrade work complete:

- [ ] `## Upgrade brief` exists, written before the lockfile moved, listing every version crossed
- [ ] Every breaking change in the brief carries a replacement and a migration reference, or is escalated
- [ ] The pre-bump suite was green, and the post-bump suite is green with **no test edited to make it so**
- [ ] `audit-before-<package>.md` and `audit-after-<package>.md` both exist with their `run_quiet.py` sidecars
- [ ] The delta between the two captures is stated in the report, and both are cited with `**Runtime evidence:**`
- [ ] Every call site the brief listed was updated; a fresh search for the removed API returns nothing
- [ ] One commit, carrying the manifest, its lockfile and those call sites, and nothing else
- [ ] The report names `git revert <sha>` as the rollback

### Escalate When

| WHEN | DO |
|---|---|
| A breaking change has **no documented migration** | **HALT.** Report to the Orchestrator (manager) with the brief attached. Never guess the replacement API. |
| A changelog or release note for a crossed version cannot be found | Record it as `unknown` in the brief and escalate — silence is not "no breaking changes" |
| The bump is a **framework major** | Do not perform it; route via `/bg` to `/bgpdd-lite` with the brief as mini-requirements (*Framework majors*) |
| The bump only passes by editing an existing test | Revert it; report to the Orchestrator (manager) — behaviour changed, and the test was the thing that noticed |
| The after-audit introduces an advisory the before-audit did not have | Report it with both captures; do not ship the bump on your own judgement |
| Two packages must move together and you cannot tell whether they are one coherent group | Ask the Orchestrator (manager) before combining them into one commit |

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Upgrade brief template](references/upgrade-brief-template.md) — the brief field by field, a filled example, and what a well-written *Breaking changes* line looks like.
- [Rationale](references/rationale.md) — why one package per commit, why the audit is captured twice rather than once, where the framework-major boundary comes from, and the anti-pattern table.
