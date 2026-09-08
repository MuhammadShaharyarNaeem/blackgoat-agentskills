# record_run.py — reference

Depth for the `record_run.py` section of `../SKILL.md`: the `--from-json` mapping table, what is deliberately NOT mapped, and the self-test inventory.

## `--from-json` mapping

A runtime's completion payload is read for these fields — top level first, then a nested `usage` object. An explicit flag always overrides the payload.

| Record field | Payload keys tried, in order |
|---|---|
| `tokens_in` | `tokens_in`, `input_tokens`, `prompt_tokens`, `inputTokens` |
| `tokens_out` | `tokens_out`, `output_tokens`, `completion_tokens`, `outputTokens` |
| `tokens_total` | `tokens_total`, `total_tokens`, `subagent_tokens`, `totalTokens` |
| `duration_s` | `duration_s`, `duration_seconds`, `durationSeconds`; else `duration_ms`, `durationMs`, `elapsed_ms`, `total_duration_ms` ÷ 1000 |
| `agent` | `agent`, `agent_name`, `subagent_type`, `subagentType` |
| `model` | `model`, `model_id`, `modelId` |
| `unit` | `unit`, `milestone` |
| `rounds` | `rounds` |
| `status` | `status`, and only if it is in the allowed set |

## Deliberately NOT mapped

- **Cache tokens** (`cache_creation_input_tokens`, `cache_read_input_tokens`): folding them into `tokens_in` is a pricing judgment, and this script records cost inputs, not a price.
- **Booleans**: a `True` coerced to `1` would fabricate a count.
- **`num_turns`**: a runtime turn is not a fix round. `rounds` means builder↔verifier cycles, and conflating the two would make the rounds column mean two different things across runtimes.

`tokens_total` is derived only from two known halves — one known half plus one unknown yields `null`, never the known half alone.

## Encoding and failure behavior

The log file is UTF-8 with `ensure_ascii=False`, so a note carrying an em dash or a non-Latin milestone title round-trips intact. The stdout report is ASCII only, for cp1252 console safety.

A failed write is **exit 2, not a warning** — a deliberate divergence from the best-effort gate ledger (convention #8). The ledger is an audit trail for later gates, so losing one line degrades a signal; here the record IS the artifact, and a silently dropped record is the whole telemetry surface going quiet.

## A verifier never runs below the producer it judges

The agent-audit's model-assignment-fit heuristic ("a verifier never runs below the producer it judges") was a finding a human read after the fact. The run log already held the evidence — one delegation record per agent, each carrying its tier — so this is where the finding becomes a refusal (convention #9).

On `--event delegation` with `--agent` in `quinn|luna|vera|cipher`, the script reads back the most recent **producer** delegation (`mason|nova|max`) in the **same `--unit`** and exits **1** with `verifier_below_producer` when this verifier's tier is lower. Tier order is `haiku < sonnet < opus`.

Three deliberate non-refusals, each of which would otherwise turn the check into noise:

- **An unknown tier is never compared.** The tier is matched by name appearing in the model string, so `claude-opus-4-1` resolves to `opus`; a value naming no tier, or two, resolves to `None` and the check stands down. Refusing on a guess about a model string this tool does not recognize is worse than not refusing — the same Evidence Integrity rule that makes an unmeasured token count `null` rather than `0`.
- **No producer in the unit yet is not an inversion.** A verifier legitimately runs first: the bugfix lane's pre-fix RED capture is Quinn before any builder.
- **Scoping is exact on `--unit`.** M2's cheap verifier is not judged against M1's opus builder; the comparison only means anything between a producer and the verifier of *that* work.

**`--allow-tier-inversion "<reason>"`** overrides it and records `"tier_inversion_reason"` on the record — an extra key, present only on an inverted record. An empty or whitespace-only reason is exit **2**: an inversion nobody justified in writing is precisely the one this check exists to stop, and a flag that accepts `""` is a flag that gets pasted in.

This introduces exit **1** to a script that previously had only 0 and 2. A refused delegation writes nothing.

## Self-test inventory

`python scripts/record_run.py --self-test` runs **31** cases: append plus parent-directory creation, unknowns staying `null`, an explicit `0` preserved, `tokens_total` derivation, field order, `--from-json` mapping including a nested `usage` object and the cache-token exclusion, an unmapped payload key leaving the field `null`, an explicit flag overriding the payload, a malformed and a missing `--from-json` file (exit 2), a missing required flag (exit 2), a bad `--event`/`--status`/count value (exit 2), a UTF-8 round trip, an unwritable path (exit 2), the four mandatory-`--model` cases, and the twelve tier-inversion cases (refused and blocking the write; equal and higher tiers passing; `--allow-tier-inversion` recording its reason; an empty reason as exit 2; a clean record carrying no inversion key; unit scoping; a verifier running first; latest-producer-wins; an unknown tier on either side; a full model id resolving to its tier; non-verifier and non-delegation records ungated; and the `model_tier` helper).

## `model_unknown`, and `dep` as a producer (2.6.1)

**An unresolvable `--model` is exit 2, not a null tier.** The tier-inversion
check reads the tier out of the model string, and `model_tier()` returns
`None` for a value naming no tier or two. The 2026-09-07 audit found that
`Sonnet`, `sonnet[1m]` and `haiku` all correctly reported
`verifier_below_producer` for a Luna record after a `claude-opus-4-1` Mason,
while `gpt-4o` landed `tier: null`, exit 0, no warning. **A typo silently
deleted the check** for that delegation, and nothing in the record said the
check had not run.

A mistyped flag must not be able to disable a gate, so a delegation whose
`--model` resolves to no tier is refused with `problem: "model_unknown"` and
nothing is written. Resolvable means the value contains exactly one of
`haiku`/`sonnet`/`opus`, case-insensitively -- `opus`, `Opus`, `opus-4.1` and
`claude-opus-4-20250514` all pass; `gpt-4o` and `sonnet-or-opus` do not. Only
`--event delegation` is checked: a gate, phase or note record has no model,
and demanding one there would invite a fabrication.

**`PRODUCER_AGENTS` gained `dep`.** Dep produces the deployment artifacts Vera
and Cipher judge at shipping, so a verifier running below Dep is the same
inversion as one running below Mason. Its absence made that single pairing
unmeasurable -- recorded in the audit as a latent Metric-14 nit
(`record_run.py:66 PRODUCER_AGENTS omits dep`), and cheaper to close than to
keep explaining.

The self-test grew to **35**: the five `model_unknown` strings (with nothing
written), the error's shape and content, the end-to-end case proving a typo
can no longer disable the inversion check, a non-delegation event still
needing no resolvable model, and the `dep`-as-producer pairing.
