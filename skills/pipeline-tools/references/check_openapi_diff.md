# check_openapi_diff.py — reference

Depth for the `check_openapi_diff.py` section of `../SKILL.md`.

## Why this is a gate and not a review note

"This change is backwards compatible" is the claim nobody re-derives at the moment they most want to merge. `api-contract-evolution/SKILL.md` states the rule — additive-only within a major version — and convention #9 says a rule the author must restrain themselves to honour at the moment of committing converts to something that has to be *run*. This is that artifact: the base contract document and the head contract document, one exit code.

It does not replace review. It removes the class of breakage a reader misses by eye: a property quietly dropped from a component that six operations `$ref`, a `type` flipped from `string` to `integer`, a `required` added to a request body three levels down.

## The breaking classes, and the rule that detects each

| `kind` | Detection rule |
|---|---|
| `path_removed` | A key of `paths` present in base, absent in head. |
| `operation_removed` | For a path present in **both**, an HTTP method present in base, absent in head. A method lost with its whole path reports only `path_removed` — one root cause, one finding. |
| `response_status_removed` | For a shared operation, a `responses` key present in base, absent in head. |
| `response_field_removed` | For a shared operation/status/media type, a flattened schema path present in base, absent in head. A **rename shows as this plus an additive `response_field_added`** — no attempt is made to guess that `name` "became" `fullName`, because a guess that is wrong reports a compatible change as a rename and hides the removal. |
| `type_changed` | For a schema path or parameter present in both, a differing `type`. Applies to responses, request bodies and parameters alike. Reported when either side names a type; two untyped sides are not a change. |
| `required_request_field_added` | Four shapes: a new request property listed in its object's `required`; an existing request property added to `required`; a new parameter with `required: true`; an existing parameter whose `required` becomes true. Plus `requestBody.required` flipping to true. |
| `enum_narrowed` | An `enum` (on a response property, request property or parameter) that loses a value, **or is introduced where the base accepted any value**. Both are a caller sending something the head refuses. |

Additive kinds, reported for the record and never gating: `path_added`, `operation_added`, `response_status_added`, `response_field_added`, `optional_request_field_added`, `parameter_added`, `enum_widened`.

## `$ref` resolution, and why exactly one level

A `$ref` is resolved by walking the local JSON pointer (`#/components/schemas/User`, and any other `#/...` pointer, so `#/components/parameters/...` resolves too). A **resolved schema's own `$ref`s are left unresolved.** That is what makes a self-referential component (`Node.child -> Node`) terminate without a seen-set, and it costs nothing real: a chain of refs two deep compares as an unresolved `$ref` dict on both sides, which is symmetric and therefore reports no false break. A walk-depth cap of 8 bounds deeply nested inline schemas.

`allOf` members are merged into the parent's flattened path set — the composition shape OpenAPI generators emit most often. `oneOf`/`anyOf` are **not** decomposed: a change inside one branch of a union is invisible to this gate.

## Scope limits, stated rather than papered over

- **Semantics are invisible.** `api-contract-evolution` names "changed status semantics" as a breaking class; this gate sees only whether a status code disappeared. A `200` that now means something else passes. That one stays a reviewer's job, and the skill says so.
- **Removed request properties and removed media types are not reported.** A server that stops reading a field a client still sends is not, by itself, a wire break; a removed request media type usually is, but it has no clean additive counterpart and inventing an unnamed class would put a finding in front of a reader with no rule behind it.
- **Descriptions, examples, servers, security schemes and extensions are ignored entirely.**
- **The gate diffs documents, not implementations.** A head document that no longer matches the code it describes passes here and fails `check_runtime_evidence.py --require-openapi-reachable`, which is the check that the document is actually served by a started application. The two are complementary and neither substitutes for the other.

## YAML: the JSON-compatible block subset, and nothing else

`json.loads` is tried first on every document, whatever its extension — a `.yaml` file that is really JSON loads. A `.json` file that fails JSON is exit 2 immediately; no YAML fallback, because that would turn a typo into a confusing parse error.

Otherwise a **minimal block-YAML loader** runs: nested mappings by indentation, `- ` sequences (including the compact `- name: id` item), plain and quoted scalars, `true`/`false`/`null`/`~`, integers and floats, `[]` and `{}` as empty collections, `#` comments outside quotes, and one leading `---`.

Everything else raises exit 2 with the construct named: anchors (`&`), aliases (`*`), tags (`!`), merge keys (`<<`), block scalars (`|`, `>`), flow collections other than the empty pair, explicit complex keys (`? `), and multi-document streams. **No YAML library is vendored** — this family is stdlib-only, and a hand-rolled loader that *guesses* at an anchor is worse than one that refuses: a mis-parsed base document manufactures either a phantom break or, far worse, a phantom green.

The remedy in every refusal message is the same: convert the document to JSON, or to plain block YAML, and re-run.

## `--allow-breaking`, and what it does and does not buy

A breaking change is sometimes correct — a new major, an unshipped endpoint, a documented cutover. The flag exits 0 and records the reason in the ledger record as `allow_breaking_reason`, alongside `breaking_kinds`.

**Deliberately hand-typed, like `check_commit_gate.py --waiver` (convention #8).** No script can judge whether "v2 cutover approved in plan.md" is true. What the flag buys is the same thing that waiver buys: the decision is durable, attributable and hashed into the chain rather than being a flag on a command line nobody can see afterwards. An **empty or whitespace-only reason is exit 2**, not a silent waiver — an unreasoned waiver is indistinguishable from an omission, the same line `check_runtime_recipe.py` holds on `Skipped —`.

Note the asymmetry a reader should expect: with a waiver the `result` field reads `ALLOWED`, the `breaking` array is still fully populated, and the ledger `verdict` is `PASS` (exit 0 maps to PASS by the family's ledger contract). A downstream `--require-ledger-gates check_openapi_diff.py` therefore accepts a waived run — which is the point of the waiver, and why the reason has to be in the record.

## Self-test

`--self-test` runs **38** cases: the additive baselines (identical, added field, new endpoint, new operation), one per breaking class, the rename-as-remove-plus-add shape, enum widening and enum introduction, all five `required_request_field_added` shapes, `$ref` resolution of both a removal and a type change, the self-referential component, a nested object property, path-level parameter merging, `allOf` walking, the four exit-2 usage paths, both `--allow-breaking` refusals and the accepted one, the three-record chained-ledger assertion, and four YAML cases (block subset parses, anchors refused, block scalar refused, JSON-in-a-`.yaml`-file loads).
