# Deprecation template — reference

Depth for `../SKILL.md` § Deprecation. Copy the block, fill every angle-bracket span, and put it **in the contract document** beside the thing being retired.

## The block

```yaml
# [deprecated: <path or field, exactly as it appears in the document>;
#  sunset: <YYYY-MM-DD>;
#  replacement: <path or field, or "none — see <link>">]
#
# Announced:  <YYYY-MM-DD>
# Consumers:  <the <consumers> list, or "external only — see below">
# Migration:  <one line: what a caller changes>
```

Alongside it, the spec's own marker — so tooling that reads OpenAPI (a generator, a portal, a linter) sees it too, not only a human reading the comment:

```yaml
paths:
  /v1/users/{id}/name:
    get:
      deprecated: true
```

For a **field**, OpenAPI 3.x carries `deprecated: true` on the schema property:

```yaml
User:
  properties:
    name:
      type: string
      deprecated: true
```

The comment block and the spec marker are both required. The marker is machine-readable but says nothing about *when* or *what instead*; the block says both but is invisible to tooling. Neither alone is a deprecation.

## JSON contract documents

JSON has no comments, and `check_openapi_diff.py` reads JSON as the primary format — so in a JSON document the block above is not merely invisible, it is **unwritable**. Carry the same three facts as an `x-deprecated` extension object beside the marker. OpenAPI allows `x-` extensions anywhere a specification object appears, so this survives every generator and linter that reads the document:

```json
"name": {
  "type": "string",
  "deprecated": true,
  "x-deprecated": {
    "sunset": "<YYYY-MM-DD>",
    "replacement": "<path or field, or 'none — see <link>'>",
    "announced": "<YYYY-MM-DD>",
    "consumers": ["<path::symbol>", "external only — see <link>"],
    "migration": "<one line: what a caller changes>"
  }
}
```

`deprecated: true` alone is still not a deprecation in JSON either — the `x-deprecated` object is what carries *when* and *what instead*, and it is the form the Verification Checklist's "in the contract document" row is satisfied by for a JSON document. Use the comment block for YAML, this object for JSON; never both in one document.

## The three fields, and what each is load-bearing for

**`sunset:` — an actual date, not "next quarter".** A deprecation without a date is a permanent second shape: every consumer defers, nothing migrates, and the field is still there three years later carrying the maintenance cost of a supported feature. Pick a date long enough for your slowest consumer, then hold it.

**`replacement:` — a concrete path or field, or an explicit "none".** "Use the new API" is not a replacement. If the capability is genuinely going away with nothing taking its place, write `none — <one line on what callers should do instead>`; that is a legitimate answer and a reader can act on it. What a reader cannot act on is a blank.

**`Consumers:` — the `<consumers>` list from `{PLUGIN_ROOT}/../agents/mason.md`'s grammar.** The migration plan is only as real as the list of who has to execute it. An entry saying "external only" is fine when the callers are outside this repository, provided the external consumers are named somewhere the announcement can reach them.

## The sunset window rule

> **Serve both shapes for the whole window. Then the removal is a new major.**

A sunset date is permission to *stop announcing*, not permission to make a removal additive. On the sunset date:

- If the API's versioning strategy allows a new major, remove the old shape there. The old major keeps serving it until it is itself retired.
- If there is no new major planned, the field stays. A field past its sunset date with no major to remove it in is a finding for the next plan, not a licence to delete it from the current one.

`check_openapi_diff.py` does not read sunset dates and will report the eventual removal as `path_removed` / `response_field_removed` exactly as it should. At the major, that removal is authorized by the plan task carrying `[breaking: …]`, and the gate is run with `--allow-breaking "<the plan task id> — v2 major, <field> sunset <date>"`. **The reason string is where the sunset date proves itself**, because the ledger record keeps it.

## Worked example: retiring `User.name` in favour of `User.fullName`

**Announced 2026-01-15, sunset 2026-07-15, removed in v2.**

1. **Expand (v1, additive).** Add `fullName` beside `name`; both are populated by the server, `fullName` is the canonical one. `check_openapi_diff.py` exits 0 — `response_field_added`.

2. **Mark (v1, additive).** In the contract document:

   ```yaml
   User:
     properties:
       # [deprecated: User.name; sunset: 2026-07-15; replacement: User.fullName]
       #
       # Announced:  2026-01-15
       # Consumers:  src/portal/UserCard.tsx::renderName
       #             src/billing/invoice.ts::buildRecipient
       # Migration:  read `fullName`; it holds exactly what `name` held.
       name:
         type: string
         deprecated: true
       fullName:
         type: string
   ```

   Still exit 0 — a `deprecated: true` marker and a comment are not a schema change.

3. **Migrate (during the window).** Each named consumer moves to `fullName`. The `Consumers:` list shrinks as they land; when it is empty, the removal has no known blocker.

4. **Contract (v2, breaking, authorized).** In the v2 document, `name` is gone. The plan task carries `[breaking: removed-field — User.name, sunset 2026-07-15, all listed consumers migrated]`, and the gate is run against the v1 base:

   ```bash
   python {PLUGIN_ROOT}/pipeline-tools/scripts/check_openapi_diff.py \
       --base openapi.v1.json --head openapi.v2.json \
       --allow-breaking "PLAN-214 — v2 major; User.name sunset 2026-07-15; consumers migrated" \
       --ledger .docs/{project-name}/implementation/gates.jsonl
   ```

   Exit 0, `result: "ALLOWED"`, `breaking` still listing `response_field_removed`, and the reason durable in the ledger.

Note what step 4 is **not**: it is not the v1 document being edited. Diffing v1-as-published against v1-with-the-field-deleted is the mistake this whole cycle exists to prevent, and the gate would exit 1 on it.

## Anti-patterns

| Shape | Why it fails |
|---|---|
| Deprecation announced only in `CHANGELOG.md` or a release note | The contract document is what a consumer reads. A changelog is a place they were not looking. |
| `sunset: TBD` | A placeholder is not a date; nothing will ever migrate against it. |
| `replacement:` left blank | A reader cannot act on a blank. Write `none — <what to do>` if that is the truth. |
| Removing the field on the sunset date, in the same major | The date permits a *major*, not a removal. See § The sunset window rule. |
| `--allow-breaking "deprecated"` | The reason is the durable record. One word records nothing — name the plan task, the field and the sunset date. |
