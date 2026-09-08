---
name: dependency-upgrade-patterns
description: "Provides the dependency upgrade execution contract: a changelog-derived Upgrade brief written before any lockfile moves, an audit capture taken before and after the bump and compared, one package (or one coherent group) per commit with its lockfile, a codebase search for every removed or renamed API, `git revert` of that one commit as the rollback, and a framework-major boundary that routes out of the fast lanes. Use if the project bumps a dependency version. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Also directly invocable: when a user asks for this on named files outside a pipeline, the Orchestrator applies the Worker Execution Contract itself in the main session — no delegation."
---

# Dependency Upgrade Patterns

A version bump is the change most often made without reading anything. This contract makes the reading and the audit comparison the deliverable, and the bump a consequence of them. Why each rule reads as it does: [rationale.md](references/rationale.md).

## Direct invocation

A user can ask for this directly on named files outside a pipeline — a deliberate refinement of agent-audit Metric 12, not a trigger collision. The Orchestrator applies the Worker Execution Contract below inline, in the main session: no delegation, no unobserved claims (`base-persona.md`, Evidence Integrity). **Scope: one package, three files or fewer.** Anything larger routes through `/bg`, which picks the lane:

- `/bgpdd-quick` — one patch or minor bump, no breaking change in the brief. The lane admits any skill carrying a `## Quick card`, this one included.
- `/bgpdd-lite` — a breaking change with a migration, or one coherent group.
- `/bgpdd-plan` — a framework major, or a breaking change with no migration.

## Quick card

Derived from the contract below for a ≤ 3-file change; no new rules (convention #8 — deliberately narrower than the full contract, which binds inside any lane).

1. Read every version crossed, then write the `## Upgrade brief` — before the lockfile moves (§ Step 1).
2. Capture the audit before the bump, re-run the same command after, state the delta (§ Step 5).
3. Search the codebase for every removed or renamed API before running anything (§ Step 3).
4. One package per commit, its lockfile with it, never a wildcard bump (§ Step 6).
5. A framework major is not a quick change; report it (§ Framework majors).

- Brief → the quick note (What / Where / How verified)
- Artifact → the capture at `{quick-root}/evidence/check.md`
- Handoff → the `## Result` bullet in `note.md`

## Worker Execution Contract

This is the operational spine. Follow it as written. Steps run in order; none is optional.

### Step 1 — Write the Upgrade brief first

Read the changelog or release notes for **every version crossed**, not only the target. Then write an `## Upgrade brief` into the report you already owe (the task's `test-report.md` block, `{quick-root}/note.md`, or the mini-requirements — whichever the lane gives you), **before any lockfile changes**:

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

A version whose notes you could not find is **not** a version with no breaking changes. Record it as `unknown` and escalate.

### Step 2 — Characterize before you bump

Before the first edit, and in this order:

1. **The existing suite.** It must be green — rule owned by `{PLUGIN_ROOT}/code-simplification/SKILL.md` (Rules).
2. **The audit command**, captured:

```
python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture .docs/{project-name}/implementation/evidence/upgrade/audit-before-<package>.md -- <audit command>
```

`<audit command>` is the stack's: `npm audit`, `dotnet list package --vulnerable`, `pip-audit`, or the wrapper the project declares — the same tool list `{PLUGIN_ROOT}/security-and-hardening/SKILL.md` (*Always Do*) owns for release-time auditing; this contract only adds the before/after pair. A non-zero exit is a legitimate capture: you are recording what the tree looked like, not asserting it was clean.

> **Deliberate divergence from `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` (convention #8).** An audit capture observes the **dependency graph**, not a running application: it lands under `evidence/upgrade/`, claims no tier, and is cited with the different `**Audit capture:**` line of § Step 5. The **citation grammar diverges too** — `check_runtime_evidence.py` rejects any path outside `evidence/runtime/` and any probe that is not a client, so an audit capture cited as runtime evidence fails the build. Never cite one as the other ([rationale.md](references/rationale.md)).

### Step 3 — Search for the removed API before you run anything

For every API the brief marks removed or renamed, search the whole codebase — source, tests, scripts, config, generated clients — and add each hit to the brief's *Call sites* field. **Before** the bump, not after the suite tells you: a transitive break is found by reading, never by a green suite.

### Step 4 — Bump exactly one thing

Change the version of **one package**, or one coherent group that must move together (a framework's sibling packages; a library and its typings). Pin an exact version — never a range widened to "latest", never a blanket `npm update` / `dotnet outdated -u` / `pip install -U -r`. Then update every call site the brief listed, and nothing else.

### Step 5 — Characterize after, and compare

Re-run the suite, then re-run the **same** audit command into `audit-after-<package>.md` through the same `run_quiet.py --capture` invocation. Read the two side by side and state the delta in the report: advisories resolved, introduced, unchanged. Cite both on one line:

```
**Audit capture:** evidence/upgrade/audit-before-<package>.md, evidence/upgrade/audit-after-<package>.md
```

This is deliberately **not** the `**Runtime evidence:**` line, and `check_runtime_evidence.py` neither parses nor accepts it (§ Step 2). The two captures are the evidence; your sentence about them is not (`{PLUGIN_ROOT}/agent-squad/base-persona.md`, Evidence Integrity).

### Step 6 — One commit, and say how to undo it

The commit contains the manifest, **its lockfile**, and the call sites the brief listed — nothing else. State the rollback explicitly in the report: **`git revert <sha>` of that one commit.**

**Two mechanisms carry this rule, not the sentence above (convention #9)** — both at the close, both in the checklist:

1. **Scope** — the closing gate carries `--max-changed-files <N>`, `N` = manifest + lockfile + the call sites the brief listed. `check_quick_close.py` defaults it to `3`; `check_commit_gate.py` takes it opt-in. Contract: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`.
2. **Lockfile presence** — before that gate runs, capture the changed-file list and read it back:

```
python {PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py \
    --capture .docs/{project-name}/implementation/evidence/upgrade/changed-files-<package>.md \
    -- git diff --name-only HEAD
```

The capture must list **the manifest and its lockfile together**, plus only the call sites the brief named. Anything else → do not close; report it.

### Framework majors

A major bump of a framework — Vue major, .NET major, EF Core major, Angular major, Django major, or an equivalent — is **not** a quick change, however small the diff looks. Do not perform one under this contract.

Report it to the Orchestrator with the Upgrade brief attached. Routing is the Orchestrator's call, not yours; the brief is shaped to serve as mini-requirements for `{PLUGIN_ROOT}/bgpdd-lite/SKILL.md` — versions crossed become the scope, each breaking change with its migration becomes a requirement.

### Verification Checklist

Before marking upgrade work complete:

- [ ] `## Upgrade brief` exists, written before the lockfile moved, listing every version crossed
- [ ] Every breaking change in the brief carries a replacement and a migration reference, or is escalated
- [ ] Pre-bump suite green; post-bump suite green with **no test edited to make it so**
- [ ] `audit-before-<package>.md` and `audit-after-<package>.md` both exist with their `run_quiet.py` sidecars
- [ ] The delta is stated in the report and both are cited with `**Audit capture:**` (never `**Runtime evidence:**`)
- [ ] Every call site the brief listed was updated; a fresh search for the removed API returns nothing
- [ ] `changed-files-<package>.md` captured; it lists the manifest **and** its lockfile, and nothing the brief did not name (§ Step 6)
- [ ] The closing gate ran with `--max-changed-files` set to the brief's file count (§ Step 6)
- [ ] The report names `git revert <sha>` as the rollback

### Escalate When

| WHEN | DO |
|---|---|
| A breaking change has **no documented migration** | **HALT**; escalate to the Orchestrator with the brief attached. Never guess the replacement API |
| A crossed version's release notes cannot be found | Record it as `unknown` in the brief and escalate to the Orchestrator — silence is not "no breaking changes" |
| The bump is a **framework major** | Do not perform it; escalate to the Orchestrator with the brief attached (*Framework majors*) |
| The bump only passes by editing an existing test | Revert it and escalate to the Orchestrator — behaviour changed, and the test noticed |
| The after-audit shows an advisory the before-audit did not | Escalate to the Orchestrator with both captures; never ship on your own judgement |
| The changed-file capture shows a manifest without its lockfile, or a path the brief did not name | Do not close; escalate to the Orchestrator (*Step 6*) |
| Two packages must move together and you cannot tell whether they are one coherent group | Escalate to the Orchestrator before combining them |

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Upgrade brief template](references/upgrade-brief-template.md) — the brief field by field, a filled example, and what a well-written *Breaking changes* line looks like.
- [Rationale](references/rationale.md) — why one package per commit, why the audit is captured twice rather than once, why the API search precedes the run, where the framework-major boundary comes from, and the anti-pattern table.
