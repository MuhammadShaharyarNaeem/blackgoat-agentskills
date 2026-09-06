---
name: api-contract-evolution
description: "Provides the API contract evolution execution contract: additive-only change within a major version, the seven named breaking-change classes, one declared versioning strategy per API (URL, header or media type — never mixed), deprecation with a sunset date and a named replacement published in the contract document, a listed consumer set, and the mechanical OpenAPI diff gate that verifies all of it. Use if the project publishes an HTTP API whose contract document changes. Squad-internal execution contract loaded by agents via their Methodology Dependencies table. Also directly invocable: when a user asks for this on named files outside a pipeline, the Orchestrator applies the Worker Execution Contract itself in the main session — no delegation."
---

# API Contract Evolution

A published API is the one artifact you cannot change by redeploying. Every consumer you cannot see is running against the shape you shipped last. Change it additively inside a major version; when you cannot, that is not an edit — it is a plan-level item with a version, a sunset date and a named replacement.

## Quick card

Five rules, each owned by the section named beside it:

1. **Additive only inside a major** — § Additive-Only Within a Major.
2. **A breaking change is one of seven named classes** — § The Breaking-Change Classes.
3. **One versioning strategy per API, never mixed** — § One Versioning Strategy Per API.
4. **A deprecation carries a sunset date and a replacement, in the contract document** — § Deprecation.
5. **A breaking change is a `/bgpdd-plan` item, never a bugfix or a quick change** — § A Breaking Change Is Plan-Level.

Three inline-mapping lines, written where the section says:

- `[api-version: <url|header|media-type> — <the concrete token>]` — in the contract document, once per API.
- `[deprecated: <path or field>; sunset: <YYYY-MM-DD>; replacement: <path or field>]` — in the contract document, beside the thing being retired.
- `[breaking: <kind> — <consumer impact>]` — in the plan task that authorizes it.

## Direct invocation

A user can ask for this directly on named contract documents — a deliberate refinement of agent-audit Metric 12, not a trigger collision. The Orchestrator applies the Worker Execution Contract below inline, in the main session: no delegation, and the diff gate is run, not reasoned about (`base-persona.md`, Evidence Integrity). A breaking change: route via `/bgpdd-plan`.

## Worker Execution Contract

This is the operational spine. Follow it as written.

### Additive-Only Within a Major

Inside a major version the only sanctioned changes are **additions a consumer written against the previous document keeps working under**: a new endpoint or method; a new **optional** request field or parameter; a new response field; a new response status code; a widened enum. Anything else is breaking until the gate says otherwise.

**Do not reason your way to "no one uses that field"** — that is § Consumers' job, and it is answered by reading callers, not by recalling them.

### The Breaking-Change Classes

Seven, named so a review has vocabulary and the gate has a `kind`:

| Class | What it is |
|---|---|
| **Removed path or method** | An endpoint, or one operation on it, no longer answers. |
| **Removed or renamed field** | A response property is gone. A rename is a removal plus an addition — never treat the pair as one compatible edit. |
| **Type change** | A field's type differs (`string` → `integer`, scalar → object). |
| **New required request field** | A new required body property or parameter; an existing optional one made required; a request body made required. |
| **Narrowed enum** | An accepted value removed — including an enum introduced where any value was legal. |
| **Changed status semantics** | The same status code now means something else (a `200` carrying an error envelope; a `404` that used to be `204`). |
| **Removed status code** | A documented response the consumer branches on is gone. |

The first five and the seventh are mechanically detectable — the gate below finds them. **Changed status semantics is not**: no diff can see it, so it is the one class a human reviewer owns and must call out by name.

### One Versioning Strategy Per API

State it in the contract document, once, as the `[api-version: …]` line — **URL** (`/v1/users`), **header** (`Api-Version: 2024-11-01`) or **media type** (`Accept: application/vnd.acme.v2+json`).

Any of the three is defensible. **Mixing two in one API is not**: two places a request can declare a version means a request that declares both, which means a routing rule nobody wrote. If the API already has one, you inherit it; introducing a second escalates.

### Deprecation

A field or endpoint is never deleted straight out of a live contract, and a deprecation that does not say *when it dies* and *what to use instead* is a comment, not a plan:

1. Mark it with the `[deprecated: …; sunset: …; replacement: …]` line and the spec's own `deprecated: true`.
2. **Publish it in the contract document** — not only in a changelog, a ticket or a release note. The document is what a consumer reads; anything else is a place they were not looking.
3. Serve both shapes until the sunset date. Then the removal is a **new major** — a sunset date does not make a removal additive.
4. Template and worked retirement: [`references/deprecation-template.md`](references/deprecation-template.md).

### Consumers Are Listed, Not Assumed

Before proposing any change to a published contract, list the consumers of every changed path and field, using the **`<consumers>` grammar** defined in `agents/mason.md` (Base Persona Override → `<consumers>`). That element is the artifact; this skill defines no second grammar for it.

An empty consumer list is a finding, not a green light: either the API has no callers in this repository — say so, and name the external consumers separately — or the trace was not done.

### Verification

**Run the diff gate. Do not read the two documents side by side and conclude.**

```bash
python {PLUGIN_ROOT}/pipeline-tools/scripts/check_openapi_diff.py \
    --base <the contract document as published> \
    --head <the contract document as proposed> \
    [--allow-breaking "<reason>"] [--milestone "<title>"] [--ledger <path>]
```

- Exit **0** every difference is additive; **1** the `breaking` array names each class, location and detail; **2** a document is missing, unreadable, or YAML outside the gate's supported subset.
- `--allow-breaking` requires a **non-empty reason** and is for an authorized break only (a new major, an endpoint never shipped). It is hand-typed and recorded in the ledger; it verifies nothing. Reaching for it because the gate is inconvenient is the failure this skill exists to prevent.
- Full CLI contract — flags, JSON shape, exit codes, `$ref` and YAML scope limits: `{PLUGIN_ROOT}/pipeline-tools/SKILL.md` § `check_openapi_diff.py`. Single authority; do not restate parsing rules here.
- The gate diffs **documents**. That the document is actually *served by a started application* is `check_runtime_evidence.py --require-openapi-reachable`, owned by `{PLUGIN_ROOT}/runtime-evidence/SKILL.md` — a separate obligation, and neither substitutes for the other.

### A Breaking Change Is Plan-Level

A breaking change is **never** absorbed into `/bgpdd-bugfix` or `/bgpdd-quick`. It carries a version decision, a consumer migration and a sunset window — none of which fits a lane whose premise is one contained change.

- Found while fixing a bug or making a quick change → **stop**, report it, route to `/bgpdd-plan`.
- In a plan it is its own task carrying the `[breaking: …]` line, the consumer list, the new version, and the deprecation window for the old shape.
- **No `[breaking:]` line in the task → return it unbuilt as a planning defect. NEVER add the line yourself** — the posture `database-migration-patterns` holds on `[destructive-waiver:]`.

### Verification Checklist

- [ ] `check_openapi_diff.py` run base-versus-head, exit 0 (or exit 0 with a recorded, authorized `--allow-breaking`)
- [ ] The `[api-version: …]` line present, and only one strategy in use across the API
- [ ] Every retired field or endpoint carries `[deprecated: …; sunset: …; replacement: …]` **in the contract document**
- [ ] `<consumers>` listed for every changed path and field, in `agents/mason.md`'s grammar
- [ ] Every breaking change traced to a plan task carrying `[breaking: …]`
- [ ] Changed status *semantics* called out by name in the review — the gate cannot see it

### Escalate When

- A breaking change is required and no plan task authorizes it → **BLOCKED**; route to `/bgpdd-plan`, never build it.
- The change needs a second versioning strategy → escalate as a design change; do not mix.
- No base contract document exists to diff against → report it. Committing one is the first task; until it exists no compatibility claim is checkable.
- A consumer cannot be migrated before the sunset date → escalate before the removal ships, not after.

## Deep Dive

Read on demand — not needed to execute the contract above:

- [Breaking-change classes](references/breaking-change-classes.md) — each class with a before/after fragment, why it breaks a real consumer, and the additive alternative.
- [Deprecation template](references/deprecation-template.md) — the contract-document block, the sunset-window rule, and a worked field retirement end to end.
