---
name: api-contract-evolution
description: "Provides the API contract evolution execution contract: additive-only change within a major version, the seven named breaking-change classes, one declared versioning strategy per API (URL, header or media type — never mixed), deprecation with a sunset date and a named replacement published in the contract document, a listed consumer set, and the mechanical OpenAPI diff gate that verifies all of it. Use if the project publishes an HTTP API whose contract document changes. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Also directly invocable: when a user asks for this on named files outside a pipeline, the Orchestrator applies the Worker Execution Contract itself in the main session — no delegation."
---

# API Contract Evolution

A published API is the one artifact you cannot change by redeploying. Every consumer you cannot see is running against the shape you shipped last. Change it additively inside a major version; when you cannot, that is a plan-level item with a version, a sunset date and a named replacement.

## Direct invocation

A user can ask for this directly on named files outside a pipeline — a deliberate refinement of agent-audit Metric 12, not a trigger collision. The Orchestrator applies the Worker Execution Contract below inline, in the main session: no delegation, and the diff gate is run, not reasoned about (`base-persona.md`, Evidence Integrity). **Scope: three files or fewer, additive only.** Anything larger, and every breaking change, routes through `/bg`.

## Quick card

Derived from the contract below for a ≤ 3-file change; no new rules (convention #8 — deliberately narrower than the full contract, which binds inside any lane).

1. Additive only inside a major; anything else is breaking until the gate says otherwise (§ Additive-Only Within a Major).
2. A breaking change is one of seven named classes (§ The Breaking-Change Classes).
3. One versioning strategy per API, never mixed (§ One Versioning Strategy Per API).
4. A deprecation carries a sunset date and a replacement, in the contract document (§ Deprecation).
5. Run `check_openapi_diff.py`; never read the two documents side by side and conclude (§ Verification).

- Brief → the quick note (What / Where / How verified)
- Artifact → the capture at `{quick-root}/evidence/check.md`
- Handoff → the `## Result` bullet in `note.md`

## Worker Execution Contract

This is the operational spine. Follow it as written.

### The Three Declared Lines

| Line | Written where, by whom | Owned by |
|---|---|---|
| `[api-version: <url\|header\|media-type> — <token>]` | the contract document, once per API | § One Versioning Strategy Per API |
| `[deprecated: <path or field>; sunset: <YYYY-MM-DD>; replacement: <path or field>]` | the contract document, beside the retiring thing | § Deprecation |
| `[breaking: <kind> — <consumer impact>]` | the authorizing plan task, **by the planner** — grammar documented at the writer's end in `{PLUGIN_ROOT}/planning-and-task-breakdown/SKILL.md` (§ Contract-change tags) | § A Breaking Change Is Plan-Level |

### Additive-Only Within a Major

Inside a major version the only sanctioned changes are **additions a consumer written against the previous document keeps working under**: a new endpoint or method; a new **optional** request field or parameter; a new response field; a new response status code; a widened **request** enum. Anything else is breaking until the gate says otherwise.

**Never reason your way to "no one uses that field"** — that is § Consumers' job, answered by reading callers.

### The Breaking-Change Classes

Seven, named so a review has vocabulary and the gate has a `kind`. Fragments, real consumer impact and the additive alternative for each: [breaking-change-classes.md](references/breaking-change-classes.md).

1. **Removed path or method** — `path_removed`, `operation_removed`
2. **Removed or renamed field** — `response_field_removed` (a rename is a removal plus an addition, never one compatible edit)
3. **Type change** — `type_changed`
4. **New required request field** — `required_request_field_added`
5. **Narrowed enum** — `enum_narrowed`
6. **Changed status semantics** — no `kind`; **not mechanically detectable**
7. **Removed status code** — `response_status_removed`

All but 6 are found by the gate. **Changed status semantics is the one class a human reviewer owns and must call out by name** — no diff can see a `200` that now carries an error envelope.

**Enum compatibility inverts between request and response, and the gate does not know which side it is on.** Widening a *request* enum is additive; widening a *response* enum breaks any consumer that switches exhaustively, and the gate reports nothing. Call a widened response enum out by name, the way you would changed status semantics.

### One Versioning Strategy Per API

State it in the contract document, once, as the `[api-version: …]` line — **URL** (`/v1/users`), **header** (`Api-Version: 2024-11-01`) or **media type** (`Accept: application/vnd.acme.v2+json`).

Any of the three is defensible. **Mixing two is not**: two places a request can declare a version means a request that declares both, and a routing rule nobody wrote. You inherit the one the API has; a second escalates.

### Deprecation

A field or endpoint is never deleted straight out of a live contract, and a deprecation that does not say *when it dies* and *what to use instead* is a comment, not a plan. In order:

1. Mark it with the `[deprecated: …; sunset: …; replacement: …]` line **and** the spec's own `deprecated: true`.
2. **Publish it in the contract document** — not only in a changelog, ticket or release note; the document is what a consumer reads.
3. A **JSON** document has no comments: the line becomes an `x-deprecated` extension object beside the marker — `{"sunset", "replacement", "announced"}`. Same facts; YAML uses the comment block. Both forms: [`references/deprecation-template.md`](references/deprecation-template.md).
4. Serve both shapes until the sunset date. Then the removal is a **new major** — a sunset date does not make a removal additive.

### Consumers Are Listed, Not Assumed

Before proposing any change to a published contract, list the consumers of every changed path and field in the **`<consumers>` grammar** defined in `{PLUGIN_ROOT}/../agents/mason.md` (Base Persona Override → `<consumers>`). This skill defines no second grammar for it.

`<consumers>` is a handoff element, so the **brief** asks for it: every milestone that changes a published contract document carries the request, exactly as the `/bgpdd-bugfix` Phase 3 brief does. Outside a handoff — under § Direct invocation, or for an agent that does not report `<changed_files>` — write the same `path::symbol` list into the report you already owe.

An empty consumer list is a finding, not a green light: either the API has no callers here — say so, and name the external consumers separately — or the trace was not done.

### Verification

**Run the diff gate. Do not read the two documents side by side and conclude.**

```bash
python {PLUGIN_ROOT}/pipeline-tools/scripts/check_openapi_diff.py \
    --base <the contract document as published> \
    --head <the contract document as proposed> \
    [--allow-breaking "<reason>"] [--milestone "<title>"] [--ledger <path>]
```

- Exit **0** every difference is additive; **1** the `breaking` array names each class, location and detail; **2** a document is missing, unreadable, or YAML outside the gate's supported subset.
- `--allow-breaking` requires a **non-empty reason** and is for an authorized break only (a new major, an endpoint never shipped). Hand-typed, recorded in the ledger; it verifies nothing.
- Full CLI contract — flags, JSON shape, exit codes, `$ref` and YAML scope limits: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` § `check_openapi_diff.py`. Single authority; do not restate parsing rules here.
- The gate diffs **documents**. That the document is *served by a started application* is `check_runtime_evidence.py --require-openapi-reachable`, owned by `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` — a separate obligation; neither substitutes for the other.

### A Breaking Change Is Plan-Level

A breaking change is **never** absorbed into `/bgpdd-bugfix` or `/bgpdd-quick`: it carries a version decision, a consumer migration and a sunset window, none of which fits a one-contained-change lane.

- Found mid-bugfix or mid-quick → **stop** and report it to the Orchestrator, which routes it.
- In a plan it is its own task carrying the `[breaking: …]` line, the consumer list, the new version, and the deprecation window for the old shape.
- **No `[breaking:]` line in the task → return it unbuilt as a planning defect. NEVER add the line yourself** — the posture `database-migration-patterns` holds on `[destructive-waiver:]`. The planner is told to write it: `{PLUGIN_ROOT}/planning-and-task-breakdown/SKILL.md` § Contract-change tags.

### Verification Checklist

- [ ] `check_openapi_diff.py` run base-versus-head, exit 0 (or exit 0 with a recorded, authorized `--allow-breaking`)
- [ ] The `[api-version: …]` line present, and only one strategy in use across the API
- [ ] Every retired field or endpoint carries `[deprecated: …; sunset: …; replacement: …]` **in the contract document** — as the comment block (YAML) or the `x-deprecated` object (JSON)
- [ ] `<consumers>` listed for every changed path and field, in `{PLUGIN_ROOT}/../agents/mason.md`'s grammar
- [ ] Every breaking change traced to a plan task carrying `[breaking: …]`
- [ ] Changed status *semantics*, and any widened **response** enum, called out by name in the review — the gate cannot see either

### Escalate When

- A breaking change is required and no plan task authorizes it → **BLOCKED**; return it unbuilt as a planning defect and escalate to the Orchestrator. Never build it.
- The change needs a second versioning strategy → escalate to the Orchestrator as a design change; do not mix.
- No base contract document exists to diff against → report it to the Orchestrator. Committing one is the first task; until it exists no compatibility claim is checkable.
- A consumer cannot be migrated before the sunset date → escalate to the Orchestrator before the removal ships, not after.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Breaking-change classes](references/breaking-change-classes.md) — each class with a before/after fragment, why it breaks a real consumer, and the additive alternative.
- [Deprecation template](references/deprecation-template.md) — the contract-document block in YAML and JSON, the sunset-window rule, and a worked field retirement end to end.
