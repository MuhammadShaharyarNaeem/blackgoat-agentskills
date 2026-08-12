---
name: runtime-evidence
description: Squad-internal execution contract for proving a claim against the actually-running application rather than an in-process test host — the tier ladder, the verification-surface registry, the out-of-process probe, and the capture artifact that gates on it. Loaded by agents via their Methodology Dependencies table whenever a requirement asserts behavior a client, device, or human can observe. Owns the `**Runtime evidence:**` citation grammar; user-facing triggers belong to the /bgpdd-build and /bgpdd-shipping pipelines.
---

# Runtime Evidence

A test suite proves the code you wrote does what you think. It does not prove the running application does. This contract governs the difference: how to observe the real system, what artifact records the observation, and what to write when you cannot make the observation at all.

## Worker Execution Contract

### Core Principle

**An in-process observation is a strictly one-directional instrument: it can fail a wire claim but never pass one.**

This is a deliberate refinement (convention #8) of `{PLUGIN_ROOT}/ui-design-patterns/SKILL.md`'s rule — *"Source reading is a strictly one-directional instrument here: it can fail a check but never pass one."* That rule bounds **source reading** against **rendered output**. This one bounds **in-process execution** against **observed output**, and it is stricter in one respect: a source read fails obviously, while an in-process test executes real code and therefore *looks* like evidence. A green in-process suite is the most convincing false pass available — real handlers, real queries, real assertions, everything true except the one thing the claim was about.

Corollary: **an effect asserted in one store is not asserted.** If a requirement says a client is mapped, the UI indicator, the database row, and any downstream agent or device state are three separate sources of truth. Reading one and inferring the others is a proxy substitution, and `base-persona.md`'s Evidence Integrity rules require you to name it.

### The Tier Ladder

| Tier | What it is | What it can prove | What it cannot |
|------|-----------|-------------------|----------------|
| 1 — Unit | Logic at function scope | Branching, calculation, parsing | Nothing about composition |
| 2 — Integration (in-process host) | The app's own pipeline over an in-memory transport, real datastore | Routing wiring, handler logic, query translation, constraints | Serialized wire shape, serializer options, middleware/filter ordering, environment-branch behavior, auth challenge shape, content negotiation, whether a contract surface exists |
| 3 — Observed runtime | The app **started as a user starts it**, probed from outside, output captured to disk | Everything a client actually receives | That the process is the built artifact (see *Build marker* below) |

A Tier-3 claim is never satisfied by a Tier-2 pass. Tier 2 remains mandatory where it applies — this ladder adds a tier, it does not replace one.

### Verification Surfaces

Every milestone carries a `[vs:<surface>]` tag assigned at planning. The tag selects which evidence is required.

| Surface | Required evidence |
|---------|-------------------|
| `api` | Out-of-process response capture; the contract surface (OpenAPI/Swagger) reachable |
| `ui` | Rendered evidence — screenshot or accessibility-tree read from a real browser |
| `web+api` | Both, **plus** the environment manifest recording which local URLs the frontend was repointed at |
| `rmm` | Device/agent state read back on the target machine (installed, paired, running), plus the service set that was up |
| `fn` | The function invoked and the effect read back from its sink — queue, cache, table, blob |
| `none` | No client-observable effect. Requires a **written justification line** in the plan |

`[vs:none]` is an explicit, reviewable claim, not an exemption. It converts "nobody thought about verification" into "someone wrote down why there is nothing to observe" — which a reader can challenge.

### The Runtime Probe

1. **START** the application the way a user starts it, using the start command declared in the milestone's `RUNTIME PROBE:` line. Never invent the command — see *Escalate When*.
2. **REPOINT** whatever configuration is needed so the surfaces under test talk to the local instances, and record exactly what you changed.
3. **PROBE** using the declared probe command through the transport below.
4. **CAPTURE** the output to a file under `evidence/runtime/` via `{PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture`, which writes the command, timestamp, exit code and output itself.
5. **CITE** the capture path in your report.

**You do not author the probe you are graded on.** The probe and its expected observable come from the plan. A probe invented at verification time is invented by the party motivated to soften it.

### Transports

Read the transport's own contract on demand; this file does not restate it.

| Surface | Transport | Contract |
|---------|-----------|----------|
| `api` | An external HTTP client or a Postman collection run headlessly — anything that opens a real socket | (no separate skill; the capture artifact below is the whole contract) |
| `ui`, `web+api` | Browser automation | `{PLUGIN_ROOT}/playwright-skill/SKILL.md` for driving flows; `{PLUGIN_ROOT}/browser-testing-with-devtools/SKILL.md` for DOM, console and network inspection |
| `rmm` | The platform's own service/package query, run on the target device | (project-declared in the `RUNTIME PROBE:` line) |
| `fn` | The sink's own client — queue peek, cache read, table query | (project-declared) |

An in-process test client is **not a transport**. Naming one in a capture is a gate failure, not a shortcut.

### The Capture Artifact

One file per probe, at `.docs/{project-name}/implementation/evidence/runtime/<milestone-slug>-<probe-slug>.md`. Header fields, then the captured output verbatim under a `## Captured output` heading.

Required: `Milestone`, `Requirement IDs`, `Surface`, `Transport`, `Base URL` (or the device/sink identifier), `Probe command`, `Captured`, `Exit code`.
Required when the surface is `web+api` or wider: `Environment` (every service and the local URL it was reached at) and `Config repointed` (what you changed, and from what).
Strongly recommended: `Build marker` — a version or commit the running service echoes back. Without it, a service started before your change and never restarted produces a capture that is fresh, non-empty, and wrong. This is the largest residual hole in the whole tier; treat its absence as a known risk, not a solved problem.

Captures are **gating** and belong to whoever verifies. A builder's own self-check capture goes to `evidence/build/` instead and does not satisfy a gate — the same producer split `evidence/review/` already uses for rendered evidence.

### Citation

This file is the single owner of the grammar. Emit it in your report — `test-report.md` during build, `verification-report.md` during shipping — inside the block for the unit being reported:

```
**Runtime evidence:** evidence/runtime/<file>.md[, evidence/runtime/<file>.md]
```

Paths are relative to the report's own directory. Cite every capture that backs a claim in that block, including failure-path captures.

### When You Cannot Probe

If the application will not start, the environment cannot be repointed, the device is unreachable, or the transport is unavailable:

- Record the claim as **`BLOCKED — <what was missing>`**. Never `PASS`. Never omit it.
- Say explicitly what you observed *instead*, if anything: `BLOCKED — app will not start; Tier 2 suite green only`. An unnamed proxy is a fabrication in effect (`{PLUGIN_ROOT}/agent-squad/base-persona.md`, Evidence Integrity).
- Report it in your `<handoff>` as well as your artifact, so it reaches the blockers ledger.

An honest `BLOCKED` costs one round-trip. A Tier-2 pass on a Tier-3 claim costs the project a gate.

### Verification Checklist

- [ ] Every claim about client-, device-, or human-observable behavior has a Tier-3 capture, or a `BLOCKED` line naming what was missing
- [ ] Every capture names a real out-of-process transport — no in-process test client
- [ ] `Environment` records the local URLs actually reached; nothing points at a shared dev or staging host
- [ ] Failure paths are captured too, not only success — a wrapper can shape one and miss the other
- [ ] Every store the requirement names is read back, not inferred from a sibling
- [ ] Every capture is cited with a `**Runtime evidence:**` line

### Escalate When

- The milestone declares no `RUNTIME PROBE:` line → **stop**. That absence is a planning defect (`{PLUGIN_ROOT}/planning-and-task-breakdown/SKILL.md`); report it rather than inventing a probe.
- The probe cannot be run out-of-process in this environment at all → report it; do not substitute a lower tier.
- The declared probe's expected observable disagrees with what the requirement asks for → report the conflict; follow the evidence and say that you did.

## Deep Dive

For rationale, the failure histories these rules encode, and per-surface worked examples, read on demand:

- [`references/runtime-evidence-rationale.md`](references/runtime-evidence-rationale.md) — why the in-process tier is the most dangerous false pass, the 2026-08 response-envelope incident traced end to end, the stale-process hazard and its partial mitigations, worked captures for each surface including a device/agent example, and the reasoning behind gating captures on freshness rather than authorship.
