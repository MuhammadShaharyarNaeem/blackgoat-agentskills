---
name: runtime-evidence
description: Squad-internal execution contract for proving a claim against the actually-running application rather than an in-process test host — the tier ladder, the verification-surface registry, the out-of-process probe, and the capture artifact that gates on it. Loaded by agents via their Methodology Dependencies table whenever a requirement asserts behavior a client, device, or human can observe. Owns the `**Runtime evidence:**` citation grammar; user-facing triggers belong to the /bgpdd-build, /bgpdd-verify, and /bgpdd-shipping pipelines.
---

# Runtime Evidence

A test suite proves the code you wrote behaves; it does not prove the running application does. This contract governs the difference: how to observe the real system, what artifact records the observation, and what to write when you cannot observe at all.

## Worker Execution Contract

### Core Principle

**An in-process observation is a strictly one-directional instrument: it can fail a wire claim but never pass one.**

Deliberate refinement (convention #8) of `{PLUGIN_ROOT}/ui-design-patterns/SKILL.md`'s rule — *"Source reading is a strictly one-directional instrument here: it can fail a check but never pass one."* That rule bounds **source reading** against **rendered output**; this one bounds **in-process execution** against **observed output**, and is stricter in one respect: a source read fails obviously, while a green in-process suite is the most convincing false pass available (rationale §1).

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

`[vs:none]` is an explicit, reviewable claim, not an exemption — a written reason a reader can challenge, never silence (rationale §8).

### The Environment Manifest

A probe command is not an environment. A probe that quietly succeeds against shared dev — what the checked-in config still points at — yields a capture that is fresh, well-formed, and about the wrong system (rationale §8).

The facts that make a probe runnable are **caller-supplied**, and they live in a manifest with these blocks:

| Block | What it records |
|-------|-----------------|
| **Bring-up sequence** | The **ordered** steps that take this feature from a clean checkout to a probeable system — and not only "start service X". A step is any action the sequence depends on: build a plugin project, copy its output into a host's plugin directory, install or register an agent, run a one-off function, connect one service to another. Number them; a step that must follow another is why this block is a list and the others are tables. Each step also declares **`Needed for`** — the surfaces or change-scopes that require it (see *Run the minimal subset* below) |
| **Services** | Per service: name, start command, local base URL, the readiness check that proves it answers, and which other services it calls |
| **Repointing map** | Every config key that must move off a shared host onto a local URL — the file or env var, the owning service, the value it ships with, the value it must hold locally |
| **Forbidden hosts** | The shared dev/staging host patterns that must never appear in a capture (these become the gate's `--forbid-host` arguments) |
| **Test identities & fixtures** | The concrete subjects a run acts on: the login username and where its password comes from, the target device/machine names as they appear in the product's own list (e.g. a device `auriga-90`), tenant/account/org ids, seeded records. **Never the password itself** — name its source |
| **Capabilities** | What the verifying agent must actually possess for the surfaces in play: an out-of-process HTTP client, browser automation, a DB/queue/cache client, device or agent access, a Python 3 interpreter |

**Three entry points, one grammar, explicit precedence.** The blocks are written by whoever first has the facts. Exactly one file is authoritative for a run:

| Written by | Path | When |
|------------|------|------|
| `/bgpdd-discovery` Phase 4b (Orchestrator + user) | `.docs/summary/{feature}/QA/runtime-environment.md` | **Brownfield.** Tier 1, durable, per feature — a recipe that was true last month and will be true next month. **Prefer it whenever it exists** |
| `/bgpdd-plan` Phase 3.6 (Orchestrator + user) | `.docs/{project-name}/implementation/environment-manifest.md` | **Greenfield.** Nothing exists to discover, so the Orchestrator **derives** the intended estate from the design and plan it just produced — it knows what services it is about to build and what surfaces it tagged — presents that as a proposal, and asks the user only for what the artifacts cannot say: credentials' source, machine and device names, anything local to this developer |
| `/bgpdd-build` Phase 0 (Orchestrator + user) | same Tier-2 path | Neither ran (e.g. a `/bgpdd-lite` epic), or a run-local delta must be recorded against a Tier-1 recipe |

A Tier-2 file standing alongside a Tier-1 recipe carries **deltas only** — each naming what it overrides. Never a silent second copy.

**Run the minimal subset, and record which subset you ran.** The manifest describes the *whole* estate a feature can need; a given change almost never needs all of it. Select the smallest set of bring-up steps whose `Needed for` covers the milestone's `[vs:<surface>]` tag, run those, and **name the subset in the capture's `Environment` field**. A step you skipped is a scoping decision; a step you skipped silently is an unstated assumption about what the claim covers.

**A missing capability is requested immediately and blocks at the evidence boundary — not at detection.** Docker not installed, browser tooling absent, test device unprovisioned, a credential with no source. Why the split (rationale §8): the human can install Docker while you write the code.

1. **Ask now**, naming exactly what and why — *"Docker Desktop, to run the local Postgres this API's integration tier needs"*. Actionable without a follow-up question.
2. **Record it as a blocker in the same breath** (`update_state.py --add-blocker`). Never one without the other.
3. **Keep working on everything that does not need it.** Write the code; run the tiers you can reach. A missing Tier-3 capability does not make Tier 1 and 2 unavailable.
4. **Stop at the first step that needs it** — your own self-verification, the verifier's capture, the gate that reads it. Not one step past.
5. **The blocker clears only on evidence** that the capability now works — `--resolve-blocker` requires it; cite the exercise-it-once check.

Planning and build check different things, and the divergence is deliberate (**convention #8**): planning checks *capabilities* only — greenfield services do not exist yet, brownfield ones are build's to start — while build checks capabilities **and** starts the services. Neither halts on detection; both route through the ledger above.

**No agent authors this file, and no agent fills a gap in it.** A start command you cannot find, a port nobody wrote down, a base URL you would infer from a compose file, a credential you were not given, a browser you do not have: each is context the caller owes you, not a blank to fill from convention. Escalate via `<handoff>` and stop — the environment-scoped case of *you do not author the probe you are graded on*. **A missing capability is reported the same way, and before the work starts**, never at capture time: by then the only remaining move is a lower tier, which the Tier Ladder forbids.

The manifest is what makes the capture's `Environment` and `Config repointed` fields fillable, and what a reviewer diffs a suspiciously-green capture against.

### The Runtime Probe

1. **START** the application the way a user starts it, using the start command declared in the milestone's `RUNTIME PROBE:` line. Never invent the command — see *Escalate When*.
2. **REPOINT** whatever configuration is needed so the surfaces under test talk to the local instances, and record exactly what you changed.
3. **PROBE** using the declared probe command through the transport below.
4. **CAPTURE** the output to a file under `evidence/runtime/` via `{PLUGIN_ROOT}/pipeline-tools/scripts/run_quiet.py --capture`, which writes the command, timestamp, exit code and output itself. With no Python 3 runtime available, hand-write the capture with the complete field list from *The Capture Artifact* below; `--capture` is preferred because those fields are tool-authored and therefore cannot be faked.
5. **CITE** the capture path in your report.

**You do not author the probe you are graded on.** The probe and its expected observable come from the plan; one invented at verification time is invented by the party motivated to soften it.

### Transports

Read the transport's own contract on demand; this file does not restate it.

| Surface | Transport | Contract |
|---------|-----------|----------|
| `api` | An external HTTP client or a Postman collection run headlessly — anything that opens a real socket | (no separate skill; the capture artifact below is the whole contract) |
| `ui`, `web+api` | Browser automation | `{PLUGIN_ROOT}/playwright-skill/SKILL.md` for driving flows; `{PLUGIN_ROOT}/browser-testing-with-devtools/SKILL.md` for DOM, console and network inspection |
| `rmm` | The platform's own service/package query, run on the target device | (project-declared in the `RUNTIME PROBE:` line) |
| `fn` | The sink's own client — queue peek, cache read, table query | (project-declared) |

An in-process test client is **not a transport**. Naming one in a capture is a gate failure, not a shortcut. The recognizable ones — `WebApplicationFactory`/`TestServer` (.NET), `supertest` (Node), `MockMvc` (Spring), and their equivalents in any stack — are the Tier-2 integration instrument: real routing, real handler logic, real data access, never the wire. The mechanically-enforced tell list lives in `{PLUGIN_ROOT}/pipeline-tools/scripts/check_runtime_evidence.py` (byte-locked to `check_coverage.py`'s plan lint); the prose list here is the recognition aid, not the gate.

### The Capture Artifact

One file per probe, at `.docs/{project-name}/implementation/evidence/runtime/<milestone-slug>-<probe-slug>.md`. Header fields, then the captured output verbatim under a `## Captured output` heading.

Required: `Milestone`, `Requirement IDs`, `Surface`, `Transport`, `Base URL` (or the device/sink identifier), `Probe command`, `Captured`, `Exit code`.
Required when the surface is `web+api` or wider: `Environment` (every service and the local URL it was reached at) and `Config repointed` (what you changed, and from what).
Required when the surface is `api` or `web+api`: `OpenAPI` — the contract-document URL and the status it returned, as `- OpenAPI: <url> — <status>`. Record it for the **failure-path capture too**, not just the success one; the gate scopes per capture, so a sibling missing the field fails the whole milestone. It proves the surface is up and serving its schema — nothing about whether a response body is correct, which is what the captured output and the asserted keys are for. Why this is the cheapest discriminator between a started application and a test host: rationale §9.
Required wherever the running artifact can echo any identity, and **the identity must be commit-bearing**: `Build marker` — the commit the running service reports (`ProductVersion`/informational version, a `git log -1` hash for a from-source run, a build-info endpoint). An assembly or file version is **not** a build marker: two builds of the same version are routinely identical in length and report an identical `FileVersion`, so a version-only marker cannot discriminate the build you meant from the one before it. **And the build must postdate the commit containing the change** — the marker tracks HEAD, so building before committing stamps the *previous* commit onto a binary carrying the new behavior: fresh, well-formed, and lying, which is worse than a missing marker.

Captures are **gating** and belong to whoever verifies. A builder's own self-check capture goes to `evidence/build/` instead and does not satisfy a gate — the same producer split `evidence/review/` already uses for rendered evidence.

### Citation

This file is the single owner of the grammar. Emit it in your report — `test-report.md` during build and verify runs, `verification-report.md` during shipping — inside the block for the unit being reported:

```
**Runtime evidence:** evidence/runtime/<file>.md[, evidence/runtime/<file>.md]
```

Paths are relative to the report's own directory. Cite every capture that backs a claim in that block, including failure-path captures.

The third consumer cites differently: in `acceptance-results.md` the capture path goes **inline in the result line's detail field** (grammar owner: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md`), never as a marker line. That second form is deliberate (convention #8) — that file's per-step line grammar is one line per step, with no room for a marker line beside it.

### When You Cannot Probe

The application will not start, the environment cannot be repointed, the device is unreachable, or the transport is unavailable:

- Record the claim as **`BLOCKED — <what was missing>`**. Never `PASS`. Never omit it.
- Say explicitly what you observed *instead*, if anything: `BLOCKED — app will not start; Tier 2 suite green only`. An unnamed proxy is a fabrication in effect (`{PLUGIN_ROOT}/agent-squad/base-persona.md`, Evidence Integrity).
- Report it in your `<handoff>` as well as your artifact, so it reaches the blockers ledger.

An honest `BLOCKED` costs one round-trip. A Tier-2 pass on a Tier-3 claim costs the project a gate.

### Verification Checklist

- [ ] Every environment literal used (start command, port, base URL, repointed value) came from the environment manifest — none was inferred
- [ ] Every claim about client-, device-, or human-observable behavior has a Tier-3 capture, or a `BLOCKED` line naming what was missing
- [ ] Every capture names a real out-of-process transport — no in-process test client
- [ ] `Environment` records the local URLs actually reached; nothing points at a shared dev or staging host
- [ ] Failure paths are captured too, not only success — a wrapper can shape one and miss the other
- [ ] Every store the requirement names is read back, not inferred from a sibling
- [ ] Every capture is cited with a `**Runtime evidence:**` line
- [ ] On an `api` or `web+api` surface, **every** capture records the `OpenAPI` URL and its status — the failure-path sibling included

### Escalate When

- A start command, port, base URL, credential source, or repointing value you need is absent from the environment manifest (or the manifest itself is absent) → **stop and name the missing field**. Do not infer it from a compose file, a launch profile, a framework default, or a sibling service. Supplying it is the caller's job.
- A capability the surface requires is unavailable in this runtime — no browser automation, no device access, no out-of-process transport → **stop and say which one**, before doing the work. Never quietly drop to a lower tier.
- The milestone declares no `RUNTIME PROBE:` line → **stop**. That absence is a planning defect (`{PLUGIN_ROOT}/planning-and-task-breakdown/SKILL.md`); report it rather than inventing a probe.
- The probe cannot be run out-of-process in this environment at all → report it; do not substitute a lower tier.
- The declared probe's expected observable disagrees with what the requirement asks for → report the conflict; follow the evidence and say that you did.

## Deep Dive

For rationale, the failure histories these rules encode, and per-surface worked examples, read on demand:

- [`references/runtime-evidence-rationale.md`](references/runtime-evidence-rationale.md) — §1 why the in-process tier is the most dangerous false pass; §2 the 2026-08 response-envelope incident traced end to end; §3 the stale-process hazard and its partial mitigations; §4 freshness vs authorship; §5 worked captures per surface, device/agent included; §6 why environment facts are caller-supplied; §7 **a worked multi-service environment manifest**; §8 the shared-dev false-green, named subsets, and the request-now/block-later economics; §9 the `OpenAPI` field and commit-bearing build markers.
