# Breaking-change classes — reference

Depth for `../SKILL.md` § The Breaking-Change Classes. Each class below carries the fragment that breaks, the consumer it breaks, the additive alternative, and the `kind` `check_openapi_diff.py` reports for it.

The organising idea is one sentence: **a change is breaking when a client written against the base document, running unchanged, now gets a different answer or is refused.** Everything here is that sentence applied.

---

## 1. Removed path or method — `path_removed`, `operation_removed`

```diff
 paths:
   /v1/users/{id}:
     get: {...}
-    delete: {...}
```

**Who breaks:** every caller of `DELETE /v1/users/{id}` gets a `404` or `405` where it had a `204`. Retry logic makes it worse, not better — the call will never succeed.

**Additive alternative:** deprecate the operation (§ Deprecation), keep serving it until the sunset date, remove it in the next major. If the behaviour moved, the deprecation's `replacement:` field names where it moved to.

A method lost together with its whole path reports only `path_removed` — one root cause, one finding.

## 2. Removed or renamed field — `response_field_removed` (+ additive `response_field_added`)

```diff
 User:
   properties:
     id: {type: string}
-    name: {type: string}
+    fullName: {type: string}
```

**Who breaks:** anything reading `name`. A strict deserializer throws; a lenient one silently produces a null where a display name used to be, which surfaces days later as an empty column in someone else's UI.

**Why the gate reports it as a removal plus an addition, and does not pair them:** guessing that `name` "became" `fullName` requires knowing intent. A wrong guess reports a removal as a compatible rename and hides it — the exact failure the gate exists to prevent. Two findings that a human pairs in two seconds beats one finding that is confidently wrong.

**Additive alternative:** add `fullName`, populate both, deprecate `name` with a sunset date, remove `name` in the next major.

## 3. Type change — `type_changed`

```diff
 Order:
   properties:
-    total: {type: string}
+    total: {type: number}
```

**Who breaks:** a statically-typed client fails to deserialize outright. A dynamically-typed one is worse: `"19.99" + tax` was string concatenation and is now arithmetic, or vice versa, and nothing throws.

Watch the two quiet variants: **scalar → object** (`owner: string` becoming `owner: {id, name}`) and **`integer` → `string`** for an id that outgrew 64 bits. Both are the same class.

**Additive alternative:** a new field of the new type beside the old one (`totalAmount` beside `total`), then the deprecation cycle.

## 4. New required request field — `required_request_field_added`

Five shapes, all one class:

```diff
 CreateOrder:
   properties:
     items: {...}
+    tenantId: {type: string}
-  required: [items]
+  required: [items, tenantId]
```

One entry: `tenantId`. **Watch the variant where `required` did not exist at all in the base** — writing `+ required: [items, tenantId]` onto a schema with no `required` key makes `items` required too, and the gate correctly emits **two** `required_request_field_added` entries, one of them a field you did not think you were touching. If you meant only the new field, the base must already list the others.

```diff
   parameters:
     - name: tenant
       in: query
-      required: false
+      required: true
```

...plus a brand-new required parameter, an existing body property added to `required`, and `requestBody.required` flipped to `true`.

**Who breaks:** every existing caller, immediately, with a `400`. This is the most commonly *unintended* breaking change, because from the server's side it reads as "adding a field" — and adding a field is the canonical additive move.

**Additive alternative:** add it optional with a documented default. Make it required in the next major, once telemetry says every caller is sending it.

## 5. Narrowed enum — `enum_narrowed`

```diff
     status:
       type: string
-      enum: [pending, active, archived, deleted]
+      enum: [pending, active, archived]
```

**Who breaks:** on a **request** value, a caller sending `deleted` gets a `400`. On a **response** value, a client with an exhaustive switch keeps compiling and its `deleted` branch becomes dead code — usually harmless, occasionally the branch that handled cleanup.

**The introduction case is the same class.** A property that had no `enum` accepted any string; adding `enum: [a, b]` refuses everything else. The gate reports it as `enum_narrowed` with the detail "an enum was introduced where the base accepted any value" — treat it as the removal of every value you did not list.

**Additive alternative:** for a request, keep accepting the value and reject it in validation with a specific error, so the failure is legible. For a response, an enum is a promise about what you emit — narrowing what you emit is safe for callers *only* if their handling of the removed value was itself optional, which is a claim about their code, not yours.

## 6. Changed status semantics — **not mechanically detectable**

```diff
   responses:
     '200':
-      description: the order, created
+      description: the request was accepted; check `result` for success or failure
```

**Who breaks:** every caller that treats `2xx` as success. The document still declares a `200`; the diff is clean; the gate exits 0.

This is the one class the gate cannot see, and it is therefore the one class the review must name explicitly. Two shapes to watch: an error envelope moved *inside* a `200`, and a status that changed which condition it represents (`404` now meaning "soft-deleted" where it meant "never existed").

**Additive alternative:** a new status code, or a new field the caller opts into reading. Never re-point an existing code.

## 7. Removed status code — `response_status_removed`

```diff
   responses:
     '200': {...}
-    '409': {description: duplicate}
     '500': {...}
```

**Who breaks:** a caller branching on `409` to fall back to an update. When the server stops emitting it — usually because the condition now surfaces as a `400` — that branch is unreachable and the fallback silently stops happening.

Note this is a documentation-level finding: the gate sees the removed key, not whether the server still emits the code. Both directions matter, and the fix for "we still emit it, the document was wrong" is to put it back in the document.

**Additive alternative:** keep documenting it while you still emit it; remove it from the document and the code together, in a major.

---

## What the gate does not report, and why that is deliberate

- **A removed *request* property.** A server that ignores a field a client still sends is not a wire break. It usually indicates dead client code, which is a review note.
- **A removed response media type.** Genuinely breaking for a caller that negotiated it, but it has no clean additive counterpart, and reporting it under an unnamed class puts a finding in front of a reader with no rule behind it. Call it out in review.
- **`oneOf` / `anyOf` branches.** Not decomposed. A change inside one branch of a union is invisible. If the contract leans on unions, the diff is a floor, not a ceiling.
- **Descriptions, examples, servers, security schemes, extensions.** Ignored entirely.

Full mechanical detail — `$ref` resolution depth, `allOf` handling, the YAML subset: `{PLUGIN_ROOT}/pipeline-tools/references/check_openapi_diff.md`.
